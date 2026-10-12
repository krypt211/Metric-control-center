"""Provision independent service/encryption secrets; never create provider WRITE keys."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
folder = root / ".secrets"
folder.mkdir(mode=0o700, exist_ok=True)
for name, value in (
    ("metricflow_write_encryption_key", Fernet.generate_key()),
    ("credential_management_db_password", secrets.token_urlsafe(48).encode()),
):
    path = folder / name
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(value)
    # Private host parent; individual Docker secret mounts readable by non-root app.
    if os.name != "nt":
        path.chmod(0o444)
print("Independent credential service secrets configured; no provider key created")
