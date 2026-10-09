"""Fixed-origin GET-only Graph client. Pagination never follows credential-bearing URLs."""
import asyncio,hashlib,hmac,json,re,logging
from datetime import datetime,timezone
from urllib.parse import urlsplit
import httpx
from services.providers.contracts import ProviderError

class RedactedHTTPLog(logging.Filter):
    def filter(self,record):
        record.msg="provider_http_event"
        record.args=()
        record.exc_info=None
        record.exc_text=None
        return True
def protect_http_logs():
    for name in ("httpx","httpcore.connection","httpcore.http11","httpcore.http2","httpcore.proxy","httpcore.socks"):
        logger=logging.getLogger(name)
        if not any(isinstance(f,RedactedHTTPLog) for f in logger.filters):logger.addFilter(RedactedHTTPLog())

class MetaClient:
    def __init__(self,credentials,*,transport=None,before_request=None,retries=2,retry_delay=0.5,max_pages=100,max_rows=200000):
        protect_http_logs()
        self.successful_calls=0
        self.credentials=credentials
        self.version=credentials["graph_version"]
        if not re.fullmatch(r"v[0-9]{1,3}\.0",self.version):raise ProviderError("INVALID_GRAPH_VERSION")
        self.client=httpx.AsyncClient(base_url=f"https://graph.facebook.com/{self.version}/",
            timeout=httpx.Timeout(30,connect=10),follow_redirects=False,trust_env=False,transport=transport)
        self.before_request=before_request;self.retries=retries;self.retry_delay=retry_delay
        self.max_pages=max_pages;self.max_rows=max_rows;self.quota={};self.blocked_until=None
    async def close(self):await self.client.aclose()
    def _usage(self,response):
        # Only usage numbers are retained, not arbitrary upstream header strings.
        for header in ("x-app-usage","x-ad-account-usage","x-business-use-case-usage"):
            try:value=json.loads(response.headers.get(header,"{}"))
            except (ValueError,TypeError):continue
            def safe(v,depth=0):
                if depth>5:return None
                if isinstance(v,dict):return {k:safe(x,depth+1) for k,x in v.items() if re.fullmatch(r"[A-Za-z0-9_]{1,64}",k)}
                if isinstance(v,list):return [safe(x,depth+1) for x in v[:20]]
                return v if type(v) in (int,float) and 0<=v<=1000000 else None
            self.quota[header]=safe(value)
    async def get(self,path,params=None,*,app_auth=False):
        if not re.fullmatch(r"(?:me(?:/(?:adaccounts|permissions))?|debug_token|(?:act_)?[0-9]+(?:/(?:campaigns|adsets|ads|adcreatives|insights))?)",path):
            raise ProviderError("INVALID_META_PATH")
        params=dict(params or {})
        if any(k in params for k in ("access_token","method","batch","async")):raise ProviderError("INVALID_META_PARAMETERS")
        token=f'{self.credentials["app_id"]}|{self.credentials["app_secret"]}' if app_auth else self.credentials["token"]
        if not app_auth:
            params["appsecret_proof"]=hmac.new(self.credentials["app_secret"].encode(),token.encode(),hashlib.sha256).hexdigest()
        for attempt in range(self.retries+1):
            if self.before_request:await self.before_request()
            try:response=await self.client.get(path,params=params,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
            except httpx.TransportError:
                if attempt<self.retries:
                    await asyncio.sleep(self.retry_delay*2**attempt);continue
                raise ProviderError("META_TIMEOUT") from None
            self._usage(response)
            try:body=response.json()
            except (ValueError,UnicodeError):body={}
            error=body.get("error",{}) if isinstance(body,dict) else {}
            code=error.get("code") if isinstance(error,dict) else None
            if response.status_code==401 or code==190:raise ProviderError("META_TOKEN_INVALID")
            if response.status_code==403 or code in (10,200,294):raise ProviderError("META_PERMISSION_DENIED")
            if response.status_code==429 or code in (4,17,32,613,80004):
                retry=response.headers.get("retry-after","")
                raise ProviderError("META_RATE_LIMIT",min(int(retry),86400) if retry.isdigit() else 900)
            if response.status_code>=500 or response.status_code==408 or (isinstance(error,dict) and error.get("is_transient") is True):
                if attempt<self.retries:
                    await asyncio.sleep(self.retry_delay*2**attempt);continue
                raise ProviderError("META_UNAVAILABLE")
            if not 200<=response.status_code<300 or error:raise ProviderError("META_REQUEST_REJECTED")
            if not isinstance(body,dict):raise ProviderError("META_INVALID_RESPONSE")
            self.successful_calls+=1
            return body
    async def edge(self,path,params):
        params={**params,"limit":100};seen=set();result=[]
        for _ in range(self.max_pages):
            body=await self.get(path,params)
            rows=body.get("data")
            if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):raise ProviderError("META_INVALID_SCHEMA")
            result.extend(rows)
            if len(result)>self.max_rows:raise ProviderError("META_ROW_CAP")
            paging=body.get("paging",{})
            if not isinstance(paging,dict):raise ProviderError("META_INVALID_PAGINATION")
            next_url=paging.get("next")
            if not next_url:return result
            if not isinstance(next_url,str):raise ProviderError("META_INVALID_PAGINATION")
            try:
                parsed=urlsplit(next_url)
                valid=(parsed.scheme=="https" and parsed.hostname=="graph.facebook.com" and parsed.port in (None,443) and not parsed.username and not parsed.password and parsed.path.rstrip("/")==f"/{self.version}/{path}")
            except ValueError:
                valid=False
            if not valid:raise ProviderError("META_INVALID_PAGINATION")
            cursors=paging.get("cursors") or {}
            if not isinstance(cursors,dict):raise ProviderError("META_INVALID_PAGINATION")
            cursor=cursors.get("after")
            if not isinstance(cursor,str) or not cursor or len(cursor)>4096 or cursor in seen or not rows:
                raise ProviderError("META_INVALID_PAGINATION")
            seen.add(cursor);params["after"]=cursor
        raise ProviderError("META_PAGE_CAP")
    async def verify_token(self):
        result=await self.get("debug_token",{"input_token":self.credentials["token"]},app_auth=True)
        data=result.get("data")
        if not isinstance(data,dict) or data.get("is_valid") is not True or str(data.get("app_id"))!=self.credentials["app_id"]:
            raise ProviderError("META_TOKEN_INVALID")
        now=int(datetime.now(timezone.utc).timestamp())
        for key in ("expires_at","data_access_expires_at"):
            value=data.get(key)
            if value not in (None,0) and (type(value)!=int or value<=now):raise ProviderError("META_TOKEN_EXPIRED")
        scopes=data.get("scopes")
        if not isinstance(scopes,list) or "ads_read" not in scopes:raise ProviderError("META_ADS_READ_REQUIRED")
        permissions=await self.edge("me/permissions",{"fields":"permission,status"})
        granted={r.get("permission") for r in permissions if r.get("status")=="granted"}
        if "ads_read" not in granted:raise ProviderError("META_ADS_READ_REQUIRED")
        return {"read":True,"write_permission":"ads_management" in scopes and "ads_management" in granted,
            "write_enabled":False,"scopes":sorted(granted & {"ads_read","ads_management","business_management"}),
            "expires_at":data.get("expires_at"),"data_access_expires_at":data.get("data_access_expires_at"),
            "app_id":self.credentials["app_id"],"oauth":"not_configured","token_verified":True}
