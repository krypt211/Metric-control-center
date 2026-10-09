"""Provider ADMIN security / persistence with real FastAPI and temporary SQLite."""
import json,os
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select,func
from test_sync import StorageFixture
from test_auth import MemoryLimits
from test_providers import CREDS,TOKEN,SECRET,graph
from backend.app import app
from services.auth.sessions import new_user
from services.providers.credentials import decrypt
from services.providers.models import ProviderConnection,ProviderCredential,ProviderJob,ProviderRoutingSetting
from services.providers.manager import ProviderManager
from services.storage.models import ActionRequest,AdAccount
from services.sync.engine import utc_now
class ProviderApiTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        secret=Path(self.directory.name)/"session";secret.write_text("s"*48)
        key=Path(self.directory.name)/"encryption";key.write_bytes(Fernet.generate_key())
        self.env=patch.dict(os.environ,{"AUTH_ENABLED":"true","APP_ENV":"development","SESSION_SECRET_FILE":str(secret),
            "PROVIDER_ENCRYPTION_KEY_FILE":str(key),"APP_ORIGIN":"http://test","WORKSPACE_ID":"default",
            "LOCAL_READ_ONLY":"true","ACTIONS_ENABLED":"false","SYNC_ENABLED":"true"})
        self.env.start()
        self.patches=[patch("backend.app.database_sessions",return_value=self.sessions),patch("backend.auth.limiter",return_value=MemoryLimits())]
        for p in self.patches:p.start()
        with self.sessions.begin() as s:
            for role in ("admin","viewer","operator"):new_user(s,"default",role,"Strong-password-12345",role)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test")
    async def asyncTearDown(self):await self.client.aclose()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.env.stop();super().tearDown()
    async def csrf(self):
        r=await self.client.get("/api/auth/csrf")
        return {"Origin":"http://test","X-CSRF-Token":r.json()["csrf_token"]}
    async def login(self,role="admin"):
        r=await self.client.post("/api/auth/login",headers=await self.csrf(),json={"login":role,"password":"Strong-password-12345"})
        self.assertEqual(r.status_code,200)
    async def connect(self):
        r=await self.client.post("/api/admin/providers/meta/credentials",headers=await self.csrf(),json=CREDS)
        self.assertEqual(r.status_code,200,r.text)
        return r
    async def test_auth_admin_role_and_csrf_on_every_provider_mutation(self):
        paths=[("/api/admin/providers/meta/credentials","POST",CREDS),
            ("/api/admin/providers/meta/disconnect","POST",{"acknowledge_last_source":True}),
            ("/api/admin/providers/meta/check","POST",{}),
            ("/api/admin/providers/meta/sync","POST",{"start":"2026-10-01","end":"2026-10-07"}),
            ("/api/admin/providers/routing","PUT",{"primary_provider":"meta"}),
            ("/api/admin/providers/routing/00000000-0000-0000-0000-000000000001","DELETE",None),
            ("/api/admin/providers/mapping","POST",{"account_id":"one","target_account_id":"two","confirm":True})]
        self.assertEqual((await self.client.get("/api/admin/providers")).status_code,401)
        for role in ("viewer","operator"):
            await self.login(role)
            self.assertEqual((await self.client.get("/api/admin/providers")).status_code,403)
            for path,method,body in paths:
                r=await self.client.request(method,path,headers=await self.csrf(),json=body)
                self.assertEqual(r.status_code,403,path)
        await self.login()
        for path,method,body in paths:
            self.assertEqual((await self.client.request(method,path,json=body)).status_code,403,path)
        for path in ("/api/actions","/api/automation/control","/api/ai/analyses"):
            self.assertEqual((await self.client.post(path,headers=await self.csrf(),json={})).status_code,403)
    async def test_credentials_encrypted_metadata_safe_and_restart_persistent(self):
        await self.login();response=await self.connect();self.assertNotIn(TOKEN,response.text)
        settings=(await self.client.get("/api/admin/providers")).text
        self.assertNotIn(TOKEN,settings);self.assertNotIn(SECRET,settings);self.assertNotIn("encrypted",json.loads(settings).get("credentials",{}))
        with self.sessions() as s:
            stored=s.get(ProviderCredential,("default","meta"));self.assertNotIn(TOKEN,stored.encrypted)
            self.assertEqual(decrypt("default","meta",stored.encrypted),CREDS)
        from services.storage.database import make_engine,sessions
        engine=make_engine(self.db.url)
        try:
            with sessions(engine)() as s:self.assertEqual(decrypt("default","meta",s.get(ProviderCredential,("default","meta")).encrypted),CREDS)
        finally:engine.dispose()
        self.assertEqual((await self.client.get("/api/admin/providers")).status_code,200)
    async def test_secret_validation_never_echoes_rejected_input_and_key_unavailable_fails_closed(self):
        await self.login()
        for data in ({**CREDS,"token":TOKEN+" unsafe"},{**CREDS,"app_id":"https://evil.test"},{**CREDS,"leak":TOKEN}):
            r=await self.client.post("/api/admin/providers/meta/credentials",headers=await self.csrf(),json=data)
            self.assertEqual(r.status_code,422);self.assertNotIn(TOKEN,r.text)
        with patch.dict(os.environ,{"PROVIDER_ENCRYPTION_KEY_FILE":""}):
            self.assertFalse((await self.client.get("/api/admin/providers")).json()["credentials_ui_enabled"])
            r=await self.client.post("/api/admin/providers/meta/credentials",headers=await self.csrf(),json=CREDS)
            self.assertEqual(r.status_code,422)
        with self.sessions() as s:self.assertEqual(s.scalar(select(func.count()).select_from(ProviderCredential)),0)
    async def test_last_source_warning_local_forget_no_remote_write_and_snapshot_preserved(self):
        await self.login();await self.connect()
        with self.sessions.begin() as s:
            s.add(AdAccount(id="test-account",workspace_id="default",provider="meta",external_id="act_100",name="Account",currency="USD",timezone="UTC",observed_at=utc_now()))
            for c in s.scalars(select(ProviderConnection)):c.enabled=c.provider=="meta";c.status="healthy" if c.provider=="meta" else "disconnected"
        r=await self.client.post("/api/admin/providers/meta/disconnect",headers=await self.csrf(),json={})
        self.assertEqual(r.status_code,409);self.assertEqual(r.json()["detail"],"LAST_WORKING_SOURCE_WARNING")
        r=await self.client.post("/api/admin/providers/meta/disconnect",headers=await self.csrf(),json={"acknowledge_last_source":True,"forget_credentials":True})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()["remote_revocation"],"not_performed")
        with self.sessions() as s:
            self.assertIsNone(s.get(ProviderCredential,("default","meta")));self.assertFalse(s.get(ProviderConnection,("default","meta")).enabled)
            self.assertEqual(s.scalar(select(func.count()).select_from(AdAccount)),1)
            self.assertEqual(s.scalar(select(func.count()).select_from(ActionRequest)),0)
    async def test_manual_routing_health_required_action_disabled_and_scope_isolated(self):
        await self.login();await self.connect()
        body={"primary_provider":"meta","fallback_provider":"metricflow","action_provider":"disabled"}
        r=await self.client.put("/api/admin/providers/routing",headers=await self.csrf(),json=body)
        self.assertEqual(r.status_code,409)
        result=await ProviderManager(self.sessions,transports={"meta":httpx.MockTransport(graph)}).health_check("meta")
        self.assertEqual(result["status"],"healthy",result)
        denied=await self.client.put("/api/admin/providers/routing",headers=await self.csrf(),json=body)
        self.assertEqual(denied.status_code,409);self.assertEqual(denied.json()["detail"],"PRIMARY_SYNC_REQUIRED")
        from services.providers.sync import MetaSync
        today=utc_now().date();synced=await MetaSync(ProviderManager(self.sessions,transports={"meta":httpx.MockTransport(graph)})).run("today",today,today)
        self.assertEqual(synced["status"],"succeeded",synced)
        r=await self.client.put("/api/admin/providers/routing",headers=await self.csrf(),json=body);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual((await self.client.get("/api/admin/providers")).json()["routing"][0]["primary_provider"],"meta")
        for extra,status in (({"action_provider":"meta"},422),({"fallback_provider":"meta"},422),({"scope":"foreign-account"},404)):
            r=await self.client.put("/api/admin/providers/routing",headers=await self.csrf(),json={**body,**extra});self.assertEqual(r.status_code,status,r.text)
        await self.connect()
        result=await ProviderManager(self.sessions,transports={"meta":httpx.MockTransport(graph)}).health_check("meta")
        self.assertEqual(result["status"],"healthy")
        denied=await self.client.put("/api/admin/providers/routing",headers=await self.csrf(),json=body)
        self.assertEqual(denied.status_code,409);self.assertEqual(denied.json()["detail"],"PRIMARY_SYNC_REQUIRED")
    async def test_date_job_limits_duplicate_jobs_and_replacement_cancel_old_generation(self):
        await self.login();await self.connect()
        r=await self.client.post("/api/admin/providers/meta/sync",headers=await self.csrf(),json={"start":"2026-10-01","end":"2026-10-07"})
        self.assertEqual(r.status_code,409)
        await self.connect()
        with self.sessions.begin() as s:
            cancelled=s.scalars(select(ProviderJob).where(ProviderJob.status=="cancelled")).all();self.assertEqual(len(cancelled),1)
            for j in s.scalars(select(ProviderJob).where(ProviderJob.status=="queued")):j.status="succeeded"
        r=await self.client.post("/api/admin/providers/meta/sync",headers=await self.csrf(),json={"start":"2026-10-01","end":"2026-10-07"})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(r.json()["job_ids"]),3)
        r=await self.client.post("/api/admin/providers/meta/sync",headers=await self.csrf(),json={"start":"2025-01-01","end":"2026-10-07"})
        self.assertEqual(r.status_code,422)
    async def test_diagnostics_and_read_indicator_are_read_only_and_safe(self):
        await self.login();await self.connect()
        manager=ProviderManager(self.sessions,transports={"meta":httpx.MockTransport(graph)})
        await manager.health_check("meta")
        from services.providers.sync import MetaSync
        today=utc_now().date();await MetaSync(manager).run("today",today,today)
        params={"start":str(today),"end":str(today)}
        r=await self.client.get("/api/admin/providers/diagnostics",params=params)
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn(TOKEN,r.text);self.assertNotIn(SECRET,r.text)
        self.assertEqual(len(r.json()["meta_entity_state"]),3)
        await self.login("viewer")
        r=await self.client.get("/api/stats/sources",params=params);self.assertEqual(r.status_code,200)
        self.assertEqual((await self.client.get("/api/admin/providers/diagnostics",params=params)).status_code,403)