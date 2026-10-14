"""Prepare mock-only UI acceptance against a separately restored database."""

import json
import secrets
import sys
from pathlib import Path

import yaml
from cryptography.fernet import Fernet

import scripts.local_activation_evidence as m

assert len(sys.argv) == 2, "Provide a separately restored mcc_integrations_* database"
assert (
    sys.argv[1].startswith("mcc_integrations_")
    and sys.argv[1].replace("_", "").isalnum()
)
assert m.sql("SELECT version_num FROM alembic_version;", sys.argv[1]) in (
    "0013_integrations",
    "0014_meta_jobs",
    "0015_meta_pilot",
    "0016_smart_control",
)
state = {"restore_database": sys.argv[1]}
db = state["restore_database"]
workspace = "integration-ui-" + secrets.token_hex(8)
root = Path.cwd()
folder = root / ".tools/integration-secrets"
folder.mkdir(exist_ok=True)
for name, value in [
    ("session", secrets.token_urlsafe(48).encode()),
    ("read_cipher", Fernet.generate_key()),
    ("write_cipher", Fernet.generate_key()),
]:
    (folder / name).write_bytes(value)
# Grant the existing restricted role access only in this restored test database.
# Existing role credentials are not overwritten if already present.
m.run(
    m.P
    + [
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "-e",
        "POSTGRES_DB=" + db,
        "-v",
        str(root / "scripts/provision_credential_role.py") + ":/provision.py:ro",
        "-v",
        str(root / ".secrets/credential_management_db_password")
        + ":/run/secrets/credential_db_password:ro",
        "migrate",
        "python",
        "/provision.py",
    ]
)
baseenv = {
    "POSTGRES_HOST": "postgres",
    "POSTGRES_DB": db,
    "POSTGRES_USER": "metric_control",
    "POSTGRES_PASSWORD_FILE": "/run/secrets/postgres_password",
    "WORKSPACE_ID": workspace,
    "LOCAL_READ_ONLY": "true",
    "ACTIONS_ENABLED": "false",
    "AI_ENABLED": "false",
    "AI_AUTOPILOT_ALLOWED": "false",
    "SYNC_ENABLED": "false",
    "APP_ENV": "development",
    "META_CONTROLLED_READ_PILOT": "true",
    "APP_ORIGIN": "http://127.0.0.1:3001",
    "SESSION_SECRET_FILE": "/run/secrets/session_secret",
    "AUTH_ENABLED": "true",
    "AUTH_TRUST_PROXY": "true",
    "CELERY_BROKER_URL": "redis://redis:6379/0",
    "CREDENTIAL_MANAGEMENT_ENABLED": "true",
    "PROVIDER_ENCRYPTION_KEY_FILE": "/run/secrets/fixture_read_cipher",
    "SYNC_DAILY_BUDGET": "800",
}
services = {
    "backend": {
        "image": "metric-control-center-backend",
        "command": [
            "uvicorn",
            "backend.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-access-log",
        ],
        "environment": baseenv,
        "secrets": ["postgres_password", "session_secret", "fixture_read_cipher"],
        "networks": ["app", "data"],
    },
    "acceptance-credentials": {
        "image": "metric-control-center-credential-manager",
        "command": [
            "uvicorn",
            "services.actions.credential_service:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8002",
            "--no-access-log",
        ],
        "environment": {
            **baseenv,
            "POSTGRES_USER": "mcc_credential_manager",
            "POSTGRES_PASSWORD_FILE": "/run/secrets/credential_db_password",
            "METRICFLOW_WRITE_VAULT_FILE": "/test-namespace/write",
            "METRICFLOW_WRITE_ENCRYPTION_KEY_FILE": "/run/secrets/fixture_write_cipher",
            "CREDENTIAL_TEST_MODE": "true",
        },
        "secrets": ["credential_db_password", "session_secret", "fixture_write_cipher"],
        "networks": {"app": {"aliases": ["credential-manager"]}, "data": {}},
    },
    "frontend": {
        "image": "metric-control-center-frontend",
        "environment": {"BACKEND_INTERNAL_URL": "http://backend:8000"},
        "ports": ["127.0.0.1:3001:3000"],
        "networks": ["app"],
    },
}
for service in services.values():
    service.update(
        {
            "read_only": True,
            "tmpfs": ["/tmp"],
            "security_opt": ["no-new-privileges:true"],
        }
    )
compose = {
    "name": "mcc-integration-acceptance",
    "services": services,
    "secrets": {
        "postgres_password": {"file": str(root / ".secrets/postgres_password")},
        "credential_db_password": {
            "file": str(root / ".secrets/credential_management_db_password")
        },
        "session_secret": {"file": str(folder / "session")},
        "fixture_read_cipher": {"file": str(folder / "read_cipher")},
        "fixture_write_cipher": {"file": str(folder / "write_cipher")},
    },
    "networks": {
        "app": {},
        "data": {"external": True, "name": "metric-control-center_default"},
    },
}
file = root / ".tools/integrations-acceptance.yml"
file.write_text(yaml.safe_dump(compose), encoding="utf-8")
Path(".tools/integrations-acceptance-state.json").write_text(
    json.dumps({"database": db, "workspace": workspace, "compose": str(file)}, indent=2)
)
m.run([m.D, "compose", "-f", str(file), "up", "-d"])
fixture = Path("frontend/e2e/integration_accounts.py").read_bytes()
result = m.run(
    [m.D, "compose", "-f", str(file), "exec", "-T", "backend", "python", "-"], fixture
)
Path(".tools/integrations-fixture-state.json").write_bytes(result)
print(
    "ISOLATED_STACK_CREATED: mock-only fixture ready; run with INTEGRATION_ACCEPTANCE=true / UI_BASE_URL=http://127.0.0.1:3001"
)
