"""WRITE storage and migration boundary tests; synthetic keys, no network."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import text

from services.actions.write_credentials import (
    WriteCredentialError,
    WriteCredentialVault,
)
from services.storage.database import make_engine
from services.storage.migrate import migrate

ROOT = Path(__file__).resolve().parents[1]


def test_vault_separate_encrypted_bound_and_never_overwrites(tmp_path):
    key = Fernet.generate_key()
    vault = WriteCredentialVault(tmp_path / "write.enc", key)
    token = "mfk_test_fixture_write_only"
    vault.save_new("workspace", token, 1)
    assert token.encode() not in vault.path.read_bytes()
    stored = vault.load("workspace", 1)
    assert stored.token == token and stored.verification == "UNVERIFIED"
    assert token not in repr(stored)
    for workspace, revision in (("other", 1), ("workspace", 2)):
        with pytest.raises(WriteCredentialError):
            vault.load(workspace, revision)
    with pytest.raises(WriteCredentialError):
        vault.save_new("workspace", "mfk_test_fixture_other", 2)
    assert vault.load("workspace", 1).token == token
    vault.path.write_bytes(b"tampered")
    with pytest.raises(WriteCredentialError):
        vault.load("workspace", 1)


@pytest.mark.parametrize(
    "field,value",
    [("purpose", "READ"), ("provider", "meta"), ("verification", "VERIFIED")],
)
def test_authenticated_envelope_still_rejects_wrong_purpose(tmp_path, field, value):
    key = Fernet.generate_key()
    vault = WriteCredentialVault(tmp_path / "write.enc", key)
    vault.save_new("workspace", "mfk_test_fixture_write", 1)
    data = json.loads(Fernet(key).decrypt(vault.path.read_bytes()))
    data[field] = value
    vault.path.write_bytes(Fernet(key).encrypt(json.dumps(data).encode()))
    with pytest.raises(WriteCredentialError):
        vault.load("workspace", 1)


def test_environment_requires_independent_write_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("METRICFLOW_WRITE_VAULT_FILE", raising=False)
    monkeypatch.delenv("METRICFLOW_WRITE_ENCRYPTION_KEY_FILE", raising=False)
    with pytest.raises(WriteCredentialError):
        WriteCredentialVault.from_environment()
    read = tmp_path / "read-secret"
    monkeypatch.setenv("METRICFLOW_READ_KEY_FILE", str(read))
    monkeypatch.setenv("METRICFLOW_WRITE_VAULT_FILE", str(read))
    monkeypatch.setenv(
        "METRICFLOW_WRITE_ENCRYPTION_KEY_FILE", str(tmp_path / "write-key")
    )
    with pytest.raises(WriteCredentialError, match="MUST_BE_SEPARATE"):
        WriteCredentialVault.from_environment()
    assert not read.exists()


def test_migration_current_head_never_calls_upgrade(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "migration.db")
    monkeypatch.setenv("DATABASE_URL", url)
    engine = make_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    try:
        assert migrate(engine, config) == "UPGRADED"
        with patch("services.storage.migrate.command.upgrade") as upgrade:
            assert migrate(engine, config) == "ALREADY_CURRENT"
            upgrade.assert_not_called()
        with engine.begin() as c:
            c.execute(text("UPDATE alembic_version SET version_num='future_revision'"))
        with patch("services.storage.migrate.command.upgrade") as upgrade:
            with pytest.raises(RuntimeError, match="NOT_IN_IMAGE"):
                migrate(engine, config)
            upgrade.assert_not_called()
    finally:
        engine.dispose()


def test_migration_stamped_incomplete_schema_does_not_repair(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "incomplete.db")
    monkeypatch.setenv("DATABASE_URL", url)
    engine = make_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    try:
        command.stamp(config, "head")
        with patch("services.storage.migrate.command.upgrade") as upgrade:
            with pytest.raises(RuntimeError, match="SCHEMA_INCOMPLETE"):
                migrate(engine, config)
            upgrade.assert_not_called()
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [True, 0, -1, 1.5, "1"])
def test_vault_invalid_revision_never_creates_file(tmp_path, revision):
    vault = WriteCredentialVault(tmp_path / "write.enc", Fernet.generate_key())
    with pytest.raises(WriteCredentialError):
        vault.save_new("workspace", "mfk_test_fixture_write", revision)
    with pytest.raises(WriteCredentialError):
        vault.load("workspace", revision)
    assert not vault.path.exists()
