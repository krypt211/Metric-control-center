"""HTTP regressions for session auth; no MetricFlow requests or real advertising mutations."""
from datetime import timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from sqlalchemy import select
from backend.app import app
from backend.auth import validate_environment
from services.auth.sessions import authenticate,cookie_name,new_user,utcnow
from services.storage.models import UserSession,User
from test_sync import StorageFixture

class MemoryLimits:
    def __init__(self):self.values={}
    def eval(self,script,keys,key,seconds):
        self.values[key]=self.values.get(key,0)+1;return self.values[key]
    def get(self,key):return None

class AuthTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.secret=Path(self.directory.name)/"session";self.secret.write_text("x"*48)
        self.environment=patch.dict(os.environ,{"AUTH_ENABLED":"true","APP_ENV":"development",
            "SESSION_SECRET_FILE":str(self.secret),"APP_ORIGIN":"http://test",
            "WORKSPACE_ID":"default","LOCAL_READ_ONLY":"true","ACTIONS_ENABLED":"false","AUTH_TRUST_PROXY":"false"})
        self.environment.start()
        self.limit=MemoryLimits();self.patches=[
            patch("backend.app.database_sessions",return_value=self.sessions),
            patch("backend.auth.limiter",return_value=self.limit)]
        for p in self.patches:p.start()
        with self.sessions.begin() as session:
            for role in ("admin","operator","viewer"):
                new_user(session,"default",role,"Strong-password-12345",role)
            new_user(session,"other","foreign","Strong-password-12345","admin")
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test")
    async def asyncTearDown(self):
        await self.client.aclose()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.environment.stop();super().tearDown()
    async def csrf(self):
        r=await self.client.get("/api/auth/csrf");self.assertEqual(r.status_code,200)
        return {"Origin":os.environ["APP_ORIGIN"],"X-CSRF-Token":r.json()["csrf_token"]}
    async def login(self,login="viewer",password="Strong-password-12345"):
        return await self.client.post("/api/auth/login",headers=await self.csrf(),json={"login":login,"password":password})
    async def test_all_private_routes_require_auth_independent_of_proxy(self):
        for path in ["/api/dashboard/today","/api/stats/summary?start=2026-10-01&end=2026-10-07",
            "/api/stats/table?start=2026-10-01&end=2026-10-07","/api/stats/filters",
            "/api/stats/optional?start=2026-10-01&end=2026-10-07&kind=creative",
            "/api/recommendations","/api/system/status","/api/admin/users"]:
            r=await self.client.get(path,headers={"Authorization":"Bearer shared-operator","X-User-ID":"admin"})
            self.assertEqual(r.status_code,401,path)
    async def test_login_and_failure_are_safe_and_password_hash_is_argon2id(self):
        r=await self.login(password="invalid");self.assertEqual(r.status_code,401)
        self.assertEqual((await self.login("unknown")).json(),r.json())
        r=await self.login();self.assertEqual(r.status_code,200)
        self.assertNotIn("session_token",r.text);self.assertNotIn("password",r.text)
        with self.sessions() as s:
            u=s.scalar(select(User).where(User.email=="viewer"))
            self.assertTrue(u.password_hash.startswith("$argon2id$"))
            row=s.scalar(select(UserSession));self.assertNotIn(self.client.cookies["mcc_session"],row.token_hash)
        self.assertEqual((await self.client.get("/api/auth/me")).json()["user"]["role"],"viewer")
    async def test_logout_revokes_and_old_cookie_does_not_work(self):
        await self.login();old=self.client.cookies["mcc_session"]
        r=await self.client.post("/api/auth/logout",headers=await self.csrf());self.assertEqual(r.status_code,200)
        self.client.cookies.set("mcc_session",old)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code,401)
    async def test_session_expiry_and_recreated_engine_preserve_storage(self):
        await self.login();token=self.client.cookies["mcc_session"]
        self.assertIsNotNone(authenticate(self.sessions,token))
        from services.storage.database import make_engine,sessions
        second=make_engine(self.db.url)
        try:self.assertIsNotNone(authenticate(sessions(second),token))
        finally:second.dispose()
        with self.sessions.begin() as session:session.scalar(select(UserSession)).expires_at=utcnow()-timedelta(seconds=1)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code,401)
    async def test_roles_and_cross_workspace_cannot_escape(self):
        self.assertEqual((await self.login("foreign")).status_code,401)
        for role in ("viewer","operator"):
            await self.login(role);self.assertEqual((await self.client.get("/api/admin/users")).status_code,403)
        await self.login("admin");self.assertEqual((await self.client.get("/api/admin/users")).status_code,200)
    async def test_csrf_login_logout_and_admin_mutations(self):
        self.assertEqual((await self.client.post("/api/auth/login",json={"login":"admin","password":"Strong-password-12345"})).status_code,403)
        await self.login("admin")
        self.assertEqual((await self.client.post("/api/auth/logout")).status_code,403)
        headers=await self.csrf();headers["Origin"]="https://evil.invalid"
        self.assertEqual((await self.client.post("/api/auth/logout",headers=headers)).status_code,403)
        self.assertEqual((await self.client.post("/api/admin/users",headers=await self.csrf(),
            json={"login":"fresh","password":"Strong-password-12345","role":"viewer"})).status_code,201)
    async def test_revocation_and_last_admin_protection(self):
        await self.login("admin")
        users=(await self.client.get("/api/admin/users")).json()["users"]
        administrator=next(u for u in users if u["role"]=="admin")
        r=await self.client.patch("/api/admin/users/"+administrator["id"],headers=await self.csrf(),json={"active":False})
        self.assertEqual(r.status_code,409)
        viewer=next(u for u in users if u["role"]=="viewer")
        self.assertEqual((await self.client.patch("/api/admin/users/"+viewer["id"],headers=await self.csrf(),json={"active":False})).status_code,200)
        self.assertEqual((await self.login("viewer")).status_code,401)
    async def test_bruteforce_limit_and_public_api_limit(self):
        with patch.dict(os.environ,{"LOGIN_RATE_LIMIT":"2"}):
            self.assertEqual((await self.login(password="bad")).status_code,401)
            self.assertEqual((await self.login(password="bad")).status_code,401)
            r=await self.login(password="bad");self.assertEqual(r.status_code,429);self.assertIn("retry-after",r.headers)
        self.limit.values.clear()
        with patch.dict(os.environ,{"API_RATE_PER_MINUTE":"1"}):
            await self.client.get("/api/auth/csrf")
            self.assertEqual((await self.client.get("/api/auth/csrf")).status_code,429)
    async def test_production_cookies_secure_httponly_strict_and_host_only(self):
        with patch.dict(os.environ,{"APP_ENV":"production","APP_ORIGIN":"https://test"}):
            self.client.base_url="https://test"
            r=await self.login()
            # Cookie transmission is exercised over an HTTPS test origin.
            self.assertEqual(r.status_code,200)
            value=r.headers.get_list("set-cookie")[0].lower()
            for flag in ("__host-mcc_session=","secure","httponly","samesite=strict","path=/"):self.assertIn(flag,value)
            self.assertNotIn("domain=",value)
    async def test_validation_and_errors_never_echo_passwords_or_credentials(self):
        r=await self.client.post("/api/auth/login",headers=await self.csrf(),json={"login":"admin","password":"secret","extra":"mf_live_private_fixture"})
        self.assertEqual(r.status_code,422);self.assertEqual(r.json(),{"detail":"INVALID_REQUEST"})
        self.assertNotIn("mf_live_",r.text);self.assertNotIn("secret",r.text)
        with patch("backend.auth.limiter",side_effect=RuntimeError("password=secret")):
            r=await self.client.get("/api/auth/csrf")
            self.assertEqual(r.status_code,503);self.assertNotIn("secret",r.text)
    async def test_shared_token_cannot_replace_real_session_and_write_is_disabled(self):
        await self.login("admin")
        r=await self.client.post("/api/actions",headers=await self.csrf(),json={})
        self.assertEqual(r.status_code,403)
        r=await self.client.get("/api/auth/me",headers={"X-User-ID":"another","Authorization":"Bearer operator"})
        self.assertEqual(r.json()["user"]["role"],"admin")
    def test_production_environment_rejects_unprotected_or_write_setup(self):
        with patch.dict(os.environ,{"APP_ENV":"production","AUTH_ENABLED":"false"}):
            with self.assertRaises(RuntimeError):validate_environment()
        with patch.dict(os.environ,{"APP_ENV":"production","APP_ORIGIN":"https://stats.example.com",
            "AI_ENABLED":"false","AI_AUTOPILOT_ALLOWED":"false","TELEGRAM_ENABLED":"false","METRICFLOW_WRITE_KEY_FILE":"/write"}):
            with self.assertRaises(RuntimeError):validate_environment()

class DeploymentTests(unittest.TestCase):
    def test_production_only_proxy_ports_and_no_control_services(self):
        import yaml
        root=Path(__file__).resolve().parents[1];data=yaml.safe_load((root/"docker-compose.production.yml").read_text())
        for name,service in data["services"].items():
            if name!="caddy":self.assertNotIn("ports",service)
            self.assertNotIn("metricflow_write_key",service.get("secrets",[]))
        self.assertFalse({"ai-worker","action-worker","telegram-bot"}&set(data["services"]))
        self.assertEqual(data["services"]["backend"]["environment"]["AUTH_ENABLED"],"true")
    def test_proxy_has_no_shared_secret_or_identity_headers(self):
        root=Path(__file__).resolve().parents[1]
        s=(root/"frontend/lib/proxy.ts").read_text()
        self.assertNotIn("readFile",s);self.assertNotIn("Bearer",s);self.assertNotIn("localStorage",s)
        self.assertIn('["cookie","origin","x-csrf-token","x-real-ip","idempotency-key"]',s)
    def test_backup_path_cannot_escape_and_restore_requires_confirmation(self):
        import importlib.util,tempfile
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location("backup",root/"scripts/database_backup.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"BACKUP_DIR":d}):
            for path in ("../x.dump","/outside.dump","junk"):
                with self.assertRaises(ValueError):m.validate_path(path)
            self.assertEqual(m.validate_path("mcc-20261008T000000Z-abcdef12.dump").parent,Path(d).resolve())

@unittest.skipUnless(os.environ.get("TEST_POSTGRES_URL"), "PostgreSQL integration URL not configured")
class PostgreSQLAuthMigrationTests(unittest.TestCase):
    def test_postgresql_migration_consistency_and_sessions(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect
        from services.storage.database import make_engine
        from services.storage.models import Base
        root=Path(__file__).resolve().parents[1]
        with patch.dict(os.environ,{"DATABASE_URL":os.environ["TEST_POSTGRES_URL"]}):
            command.upgrade(Config(str(root/"alembic.ini")),"head")
            db=make_engine()
            try:
                inspector=inspect(db)
                for name,table in Base.metadata.tables.items():
                    self.assertEqual({c["name"] for c in inspector.get_columns(name)},set(table.columns.keys()))
            finally:db.dispose()

class BootstrapInputTests(unittest.TestCase):
    def test_password_with_unicode_symbols_and_spaces_is_not_normalized(self):
        from services.auth.bootstrap import read_password
        from services.auth.sessions import password_hash,verify_password
        value = "  Pass-\u0416\u0430\u0440 $&%'\\\"^()\\\\ + 123  "
        with patch("services.auth.bootstrap.getpass", side_effect=[value,value]):
            result=read_password()
        self.assertEqual(result,value)
        stored=password_hash(result)
        self.assertTrue(verify_password(stored,value))
        self.assertFalse(verify_password(stored,value.strip()))

    def test_invalid_or_mismatched_password_retries_without_logging_input(self):
        from services.auth.bootstrap import read_password
        import io
        from contextlib import redirect_stdout
        value="Private-fixture-password-123"
        output=io.StringIO()
        with redirect_stdout(output), patch("services.auth.bootstrap.getpass",
                side_effect=["short",value,"different",value,value]):
            self.assertEqual(read_password(),value)
        self.assertIn("Please retry",output.getvalue())
        self.assertNotIn(value,output.getvalue())
        self.assertNotIn("short",output.getvalue())

    def test_bootstrap_rejects_sqlite_before_password_prompt(self):
        from services.auth.bootstrap import main
        from unittest.mock import MagicMock
        db=MagicMock();db.dialect.name="sqlite"
        with patch("sys.argv",["bootstrap"]),patch("services.auth.bootstrap.make_engine",return_value=db),patch("services.auth.bootstrap.getpass") as prompt:
            with self.assertRaisesRegex(SystemExit,"PostgreSQL"):main()
        prompt.assert_not_called()
        db.dispose.assert_called_once()

    def test_bootstrap_rejects_wrong_workspace_before_connecting(self):
        from services.auth.bootstrap import main
        with patch.dict(os.environ,{"WORKSPACE_ID":"default"}),patch("sys.argv",["bootstrap","--workspace","other"]),patch("services.auth.bootstrap.make_engine") as engine:
            with self.assertRaisesRegex(SystemExit,"WORKSPACE_ID"):main()
        engine.assert_not_called()

    def test_existing_admin_password_is_never_prompted_or_overwritten(self):
        from services.auth.bootstrap import main
        from unittest.mock import MagicMock
        db=MagicMock();db.dialect.name="postgresql"
        factory=MagicMock()
        factory.return_value.__enter__.return_value.scalar.return_value="existing-admin-fixture"
        with patch("sys.argv",["bootstrap"]),patch("services.auth.bootstrap.make_engine",return_value=db),patch("services.auth.bootstrap.sessions",return_value=factory),patch("services.auth.bootstrap.getpass") as prompt:
            with self.assertRaisesRegex(SystemExit,"password unchanged"):main()
        prompt.assert_not_called()
        factory.begin.assert_not_called()
