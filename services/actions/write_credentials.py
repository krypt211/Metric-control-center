"""Independent encrypted WRITE vault; storage is never execution authorization."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from services.metricflow.errors import ConfigurationError
from services.metricflow.secrets import validate_key


class WriteCredentialError(ValueError):
    """Sanitized WRITE storage failure."""


@dataclass(frozen=True)
class WriteCredential:
    workspace: str
    revision: int
    token: str = field(repr=False)
    provider: str = "metricflow"
    purpose: str = "ADVERTISING_WRITE"
    verification: str = "UNVERIFIED"


class WriteCredentialVault:
    """Keep a purpose-bound envelope outside the existing READ credential slot."""

    def __init__(self, path: Path, encryption_key: bytes):
        self.path = path
        self._cipher = Fernet(encryption_key)

    @classmethod
    def from_environment(cls) -> WriteCredentialVault:
        record = os.environ.get("METRICFLOW_WRITE_VAULT_FILE")
        key = os.environ.get("METRICFLOW_WRITE_ENCRYPTION_KEY_FILE")
        if not record or not key:
            raise WriteCredentialError("WRITE_VAULT_NOT_CONFIGURED")
        paths = [Path(record).resolve(), Path(key).resolve()]
        protected = [
            os.environ.get(name)
            for name in (
                "METRICFLOW_READ_KEY_FILE",
                "PROVIDER_ENCRYPTION_KEY_FILE",
                "METRICFLOW_WRITE_KEY_FILE",
            )
        ]
        if (
            paths[0] == paths[1]
            or (paths[0].exists() and paths[1].exists() and paths[0].samefile(paths[1]))
        ) or any(
            p == Path(other).resolve()
            or (p.exists() and Path(other).exists() and p.samefile(other))
            for p in paths
            for other in protected
            if other
        ):
            raise WriteCredentialError("WRITE_VAULT_MUST_BE_SEPARATE")
        try:
            return cls(paths[0], paths[1].read_bytes().strip())
        except (OSError, ValueError):
            raise WriteCredentialError("WRITE_VAULT_KEY_UNAVAILABLE") from None

    @staticmethod
    def _validate_token(token: str) -> str:
        try:
            return validate_key(token)
        except (ConfigurationError, TypeError, AttributeError):
            raise WriteCredentialError("WRITE_VAULT_INVALID_TOKEN") from None

    def save_new(self, workspace: str, token: str, revision: int) -> None:
        """Create a private envelope exclusively; never overwrite another secret."""
        if (
            not isinstance(workspace, str)
            or not workspace.strip()
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
        ):
            raise WriteCredentialError("WRITE_VAULT_INVALID_BINDING")
        payload = {
            "version": 1,
            "workspace": workspace,
            "provider": "metricflow",
            "purpose": "ADVERTISING_WRITE",
            "revision": revision,
            "verification": "UNVERIFIED",
            "token": self._validate_token(token),
        }
        encrypted = self._cipher.encrypt(json.dumps(payload).encode())
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
        except OSError:
            raise WriteCredentialError("WRITE_VAULT_CREATE_FAILED") from None

    def load(self, workspace: str, revision: int) -> WriteCredential:
        """Reject tampering, wrong purpose/workspace/revision; never fall back READ."""
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise WriteCredentialError("WRITE_VAULT_INVALID_BINDING")
        try:
            value = json.loads(self._cipher.decrypt(self.path.read_bytes()))
            if (
                value["version"] != 1
                or value["workspace"] != workspace
                or value["provider"] != "metricflow"
                or value["purpose"] != "ADVERTISING_WRITE"
                or value["revision"] != revision
                or value["verification"] != "UNVERIFIED"
            ):
                raise ValueError()
            return WriteCredential(
                workspace, revision, self._validate_token(value["token"])
            )
        except (OSError, InvalidToken, ValueError, KeyError, TypeError):
            raise WriteCredentialError("WRITE_VAULT_UNAVAILABLE") from None
