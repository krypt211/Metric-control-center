"""Provision .secrets only; no default admin password and no WRITE key."""
from getpass import getpass
import os
from pathlib import Path
import re,secrets
root=Path(__file__).resolve().parents[1]
directory=root/".secrets";directory.mkdir(mode=0o700,exist_ok=True)
if os.name!="nt":directory.chmod(0o700)
for name in ("postgres_password","session_secret"):
    path=directory/name
    if not path.exists():path.write_text(secrets.token_urlsafe(48),encoding="utf-8")
path=directory/"metricflow_read_key"
if not path.exists() or path.stat().st_size==0:
    key=getpass("MetricFlow READ key: ").strip()
    if not re.fullmatch(r"(?:mfk_|mf_live_)[\x21-\x7e]+",key) or "*" in key:
        raise SystemExit("Invalid READ key format; nothing saved")
    path.write_text(key,encoding="utf-8")
# The host parent is 0700. Only specific files are mounted into their containers.
if os.name!="nt":
    for name in ("postgres_password","session_secret","metricflow_read_key"):(directory/name).chmod(0o444)
print("Secret files configured. Values not printed.")
