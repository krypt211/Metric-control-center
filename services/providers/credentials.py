"""Authenticated encryption with a separate Docker/.secrets key, never database key material."""
import json,os,re
from pathlib import Path
from cryptography.fernet import Fernet,InvalidToken
from services.metricflow.secrets import validate_key
from services.providers.models import ProviderCredential

class CredentialError(ValueError): pass
def cipher():
    try:
        path=os.environ.get("PROVIDER_ENCRYPTION_KEY_FILE")
        if not path: raise ValueError()
        return Fernet(Path(path).read_bytes().strip())
    except (OSError,ValueError,TypeError):
        raise CredentialError("CREDENTIAL_ENCRYPTION_NOT_CONFIGURED") from None

def validate(provider,data):
    if provider=="metricflow":
        return {"token":validate_key(data.get("token",""))}
    if provider!="meta": raise CredentialError("INVALID_PROVIDER")
    token=data.get("token","")
    if not isinstance(token,str) or not re.fullmatch(r"[A-Za-z0-9._~-]{16,4096}",token):
        raise CredentialError("INVALID_META_TOKEN")
    app_id=data.get("app_id","")
    secret=data.get("app_secret","")
    if not re.fullmatch(r"[0-9]{1,64}",app_id) or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}",secret):
        raise CredentialError("META_APP_CONFIGURATION_REQUIRED")
    version=data.get("graph_version","v26.0")
    if not re.fullmatch(r"v[0-9]{1,3}\.0",version):raise CredentialError("INVALID_GRAPH_VERSION")
    return {"token":token,"app_id":app_id,"app_secret":secret,"graph_version":version}

def encrypt(workspace,provider,data):
    value={"workspace":workspace,"provider":provider,"credentials":validate(provider,data)}
    return cipher().encrypt(json.dumps(value).encode()).decode("ascii")

def decrypt(workspace,provider,encrypted):
    try:
        value=json.loads(cipher().decrypt(encrypted.encode("ascii")))
        if value["workspace"]!=workspace or value["provider"]!=provider: raise ValueError()
        return validate(provider,value["credentials"])
    except (InvalidToken,ValueError,KeyError,UnicodeError):
        raise CredentialError("CREDENTIAL_UNAVAILABLE") from None

def load(session,workspace,provider):
    credential=session.get(ProviderCredential,(workspace,provider))
    if credential:return decrypt(workspace,provider,credential.encrypted)
    if provider=="metricflow":
        from services.metricflow.secrets import read_key_file
        return {"token":read_key_file(os.environ.get("METRICFLOW_READ_KEY_FILE"))}
    raise CredentialError("META_NOT_CONNECTED")
