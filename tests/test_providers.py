"""READ provider regressions; all remote requests use httpx.MockTransport."""
import copy,json,os
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select,func
from test_sync import StorageFixture,DAY,NOW,row,config
from services.providers.contracts import ProviderError,WriteDisabled,ActionProviderRouter
from services.providers.credentials import validate,encrypt,decrypt,CredentialError
from services.providers.models import ProviderConnection,ProviderCredential,ProviderRoutingSetting,ProviderWindow,ProviderAccountMapping,ProviderSwitchEvent
from services.providers.manager import ProviderManager
from services.providers.sync import MetaSync,metricflow_sync
from services.providers.matching import confirm_accounts,hierarchy_hash
from services.providers.router import DataSourceRouter
from services.storage.models import AdAccount,DailyMetric,Entity,ActionRequest,SyncRun,ApiQuota
from services.storage.repository import identity,save_row
from services.sync.schema import InsightSchema
from services.sync.engine import utc_now
from services.meta.provider import MetaMarketingProvider
from services.meta.mapper import map_rows,numeric,action
from services.analytics.table import table_data,Filters,filter_options
from services.analytics.dashboard import dashboard_today,summary

TOKEN="EA_test_token_never_log_12345"
SECRET="app_secret_never_log_12345"
CREDS={"token":TOKEN,"app_id":"123","app_secret":SECRET,"graph_version":"v26.0"}
ATTR={"action_attribution_windows":["7d_click","1d_view"],"action_report_time":"impression","use_unified_attribution_setting":False,"conversion_basis":"advertising","lead_action_type":"lead","purchase_action_type":"purchase"}
def account(number="100",currency="USD",zone="Europe/Moscow"):
    return {"id":"act_"+number,"account_id":number,"name":"Same name","account_status":1,"currency":currency,"timezone_name":zone}
def catalog():
    return {
        "campaign":[{"id":"10","name":"Campaign","account_id":"100","effective_status":"ACTIVE","daily_budget":"10000","bid_strategy":"LOWEST_COST_WITHOUT_CAP"}],
        "adset":[{"id":"20","name":"Adset","account_id":"100","campaign_id":"10","effective_status":"ACTIVE","bid_amount":"500"}],
        "ad":[{"id":"1","name":"Ad","account_id":"100","campaign_id":"10","adset_id":"20","effective_status":"ACTIVE","creative":{"id":"30"}}],
        "creative":[{"id":"30","name":"Creative","account_id":"100","thumbnail_url":"https://example.test/image.png"}]}
def insight(day=None):
    return {"account_id":"100","account_name":"Same name","account_currency":"USD","campaign_id":"10","adset_id":"20","ad_id":"1",
        "date_start":str(day or date.today()),"date_stop":str(day or date.today()),"spend":"100","impressions":"1000","clicks":"20","reach":"800","frequency":"1.25",
        "actions":[{"action_type":"lead","value":"5"},{"action_type":"purchase","value":"2"},{"action_type":"omni_purchase","value":"2"}],
        "action_values":[{"action_type":"purchase","value":"180"}]}
def graph(request):
    assert request.method=="GET"
    path=request.url.path.rsplit("/",1)[-1]
    if path=="debug_token":return httpx.Response(200,json={"data":{"is_valid":True,"app_id":"123","scopes":["ads_read"],"expires_at":0,"data_access_expires_at":0}})
    if path=="permissions":return httpx.Response(200,json={"data":[{"permission":"ads_read","status":"granted"}]})
    if path=="adaccounts":return httpx.Response(200,json={"data":[account()]})
    if path in ("campaigns","adsets","ads","adcreatives"):
        kind={"campaigns":"campaign","adsets":"adset","ads":"ad","adcreatives":"creative"}[path]
        return httpx.Response(200,json={"data":catalog()[kind]})
    if path=="insights":
        period=json.loads(request.url.params["time_range"]);first=date.fromisoformat(period["since"]);end=date.fromisoformat(period["until"])
        return httpx.Response(200,json={"data":[insight(first+timedelta(days=i)) for i in range((end-first).days+1)]})
    return httpx.Response(200,json=catalog()["ad"][0])

class MetaConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_get_only_accounts_catalogs_levels_and_current_state(self):
        calls=[]
        def handler(r):calls.append(r);return graph(r)
        p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(handler),retry_delay=0)
        try:
            result=await p.health_check();self.assertTrue(result["permissions"]["read"])
            self.assertFalse(result["permissions"]["write_enabled"])
            for method in (p.get_campaigns,p.get_adsets,p.get_ads,p.get_creatives):self.assertTrue(await method("act_100",DAY,DAY))
            for level in ("account","campaign","adset","ad"):
                self.assertTrue((await p.get_insights("act_100",DAY,DAY,level))["complete"])
            self.assertEqual((await p.get_entity_state("act_100","ad","1"))["id"],"1")
            for method in (p.pause_entity,p.enable_entity,p.set_budget,p.set_bid):
                count=len(calls)
                with self.assertRaises(WriteDisabled):await method("1")
                self.assertEqual(len(calls),count)
            self.assertTrue(all(c.method=="GET" and c.url.host=="graph.facebook.com" and "/v26.0/" in c.url.path for c in calls))
            self.assertTrue(all("access_token" not in c.url.params for c in calls))
            self.assertIn("input_token",calls[0].url.params)
        finally:await p.close()
    async def test_cursor_pagination_and_never_follow_next_query(self):
        calls=[]
        def handler(r):
            calls.append(r)
            if "after" in r.url.params:return httpx.Response(200,json={"data":[account("200")]})
            return httpx.Response(200,json={"data":[account()],"paging":{"next":"https://graph.facebook.com/v26.0/me/adaccounts?access_token=LEAK&after=second","cursors":{"after":"second"}}})
        p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(handler),retry_delay=0)
        try:
            self.assertEqual(len(await p.get_accounts()),2)
            self.assertEqual(calls[1].url.params["after"],"second");self.assertNotIn("access_token",calls[1].url.params)
        finally:await p.close()
    async def test_malformed_port_or_cursors_are_symbolic_pagination_errors(self):
        for paging in ({"next":"https://graph.facebook.com:invalid/v26.0/me/adaccounts","cursors":{"after":"one"}},
                       {"next":"https://graph.facebook.com/v26.0/me/adaccounts","cursors":["one"]}):
            p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"data":[account()],"paging":paging})))
            try:
                with self.assertRaises(ProviderError) as error:await p.get_accounts()
                self.assertEqual(error.exception.code,"META_INVALID_PAGINATION")
            finally:await p.close()
    async def test_foreign_pagination_url_cursor_loop_and_page_cap_fail_closed(self):
        for mode in ("foreign","loop","cap","missing"):
            calls=[]
            def handler(r):
                calls.append(r);paging={"next":"https://graph.facebook.com/v26.0/me/adaccounts","cursors":{"after":"same"}}
                if mode=="foreign":paging["next"]="https://evil.test/steal"
                if mode=="missing":paging.pop("cursors")
                return httpx.Response(200,json={"data":[account()],"paging":paging})
            p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(handler),retry_delay=0,max_pages=1 if mode=="cap" else 3)
            try:
                with self.assertRaises(ProviderError):await p.get_accounts()
                self.assertTrue(all(r.url.host=="graph.facebook.com" for r in calls))
            finally:await p.close()
    async def test_429_graph_limits_and_usage_headers_are_redacted(self):
        for code,status in ((4,400),(17,400),(613,400),(80004,400),(None,429)):
            p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(lambda r:httpx.Response(status,json={"error":{"code":code,"message":TOKEN}},headers={"Retry-After":"20","X-App-Usage":'{"call_count":99,"secret":"LEAK"}'})),retry_delay=0)
            try:
                with self.assertRaises(ProviderError) as error:await p.get_accounts()
                self.assertEqual(error.exception.code,"META_RATE_LIMIT");self.assertEqual(error.exception.retry_after,20)
                self.assertNotIn(TOKEN,str(error.exception));self.assertNotIn("LEAK",json.dumps(p.client.quota))
            finally:await p.close()
    async def test_transient_retries_and_transport_timeouts_get_only(self):
        calls=[]
        def handler(r):
            calls.append(r)
            if len(calls)<3:return httpx.Response(503,json={"error":{"message":TOKEN}})
            return httpx.Response(200,json={"data":[account()]})
        p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(handler),retry_delay=0)
        try:self.assertEqual(len(await p.get_accounts()),1);self.assertEqual(len(calls),3)
        finally:await p.close()
        def timeout(r):raise httpx.ReadTimeout(TOKEN,request=r)
        p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(timeout),retry_delay=0)
        try:
            with self.assertRaises(ProviderError) as error:await p.get_accounts()
            self.assertEqual(error.exception.code,"META_TIMEOUT");self.assertNotIn(TOKEN,str(error.exception))
        finally:await p.close()
    async def test_invalid_expired_wrong_app_and_missing_ads_read_fail(self):
        for mode in ("invalid","expired","access_expired","wrong_app","scope","denied"):
            def handler(r):
                if r.url.path.endswith("debug_token"):
                    data={"is_valid":True,"app_id":"123","scopes":["ads_read"],"expires_at":0}
                    if mode=="invalid":data["is_valid"]=False
                    if mode=="expired":data["expires_at"]=1
                    if mode=="access_expired":data["data_access_expires_at"]=1
                    if mode=="wrong_app":data["app_id"]="999"
                    if mode=="scope":data["scopes"]=[]
                    return httpx.Response(200,json={"data":data})
                return httpx.Response(200,json={"data":[{"permission":"ads_read","status":"declined"}]})
            p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(handler),retry_delay=0)
            try:
                with self.assertRaises(ProviderError):await p.health_check()
            finally:await p.close()
    async def test_token_and_permission_errors_are_not_retried(self):
        for status,code,expected in ((400,190,"META_TOKEN_INVALID"),(403,200,"META_PERMISSION_DENIED")):
            calls=[]
            def handler(r):calls.append(r);return httpx.Response(status,json={"error":{"code":code,"message":TOKEN}})
            p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(handler),retry_delay=0)
            try:
                with self.assertRaises(ProviderError) as error:await p.get_accounts()
                self.assertEqual(error.exception.code,expected);self.assertEqual(len(calls),1)
            finally:await p.close()
    async def test_id_path_injection_and_cross_account_state_rejected(self):
        calls=[]
        p=MetaMarketingProvider(CREDS,transport=httpx.MockTransport(lambda r:(calls.append(r) or graph(r))),retry_delay=0)
        try:
            for value in ("https://evil.test","100/../me","1?access_token=bad","act_notnumeric"):
                with self.assertRaises(ProviderError):await p.get_ads(value,DAY,DAY)
            self.assertEqual(len(calls),0)
            with self.assertRaises(ProviderError):await p.get_entity_state("act_200","ad","1")
        finally:await p.close()
    def test_mapper_exact_action_types_do_not_double_count_and_fractionals_unknown(self):
        data=map_rows([insight(DAY)],account(),catalog(),DAY,DAY,ATTR)[0]
        self.assertEqual(data.metrics["sales"],2);self.assertEqual(data.metrics["revenue"],180)
        self.assertIsNone(data.metrics["conversions"]);self.assertIsNone(numeric("1.5",True))
        self.assertIsNone(action([], "purchase"));self.assertIsNone(action(None,"purchase"))
        with self.assertRaises(ProviderError):action([{"action_type":"lead","value":1},{"action_type":"lead","value":2}],"lead")
    def test_mapper_foreign_ids_hierarchy_currency_dates_and_duplicates_fail(self):
        for mode in ("account","entity","parent","currency","date","duplicate"):
            data=insight(DAY)
            if mode=="account":data["account_id"]="999"
            if mode=="entity":data["ad_id"]="999"
            if mode=="parent":data["adset_id"]="999"
            if mode=="currency":data["account_currency"]="EUR"
            if mode=="date":data["date_stop"]=str(DAY+timedelta(days=1))
            with self.assertRaises(ProviderError):map_rows([data,data] if mode=="duplicate" else [data],account(),catalog(),DAY,DAY,ATTR)

class ProviderIntegrationTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.key=Path(self.directory.name)/"encryption";self.key.write_bytes(Fernet.generate_key())
        self.schema=Path(self.directory.name)/"schema.json";self.schema.write_text(json.dumps(config()))
        self.env=patch.dict(os.environ,{"PROVIDER_ENCRYPTION_KEY_FILE":str(self.key),"METRICFLOW_SCHEMA_FILE":str(self.schema),"META_DAILY_BUDGET":"5000"})
        self.env.start()
        with self.sessions.begin() as s:
            for provider in ("meta","metricflow"):
                s.add(ProviderConnection(workspace_id="default",provider=provider,enabled=provider=="meta",credential_source="encrypted",revision=1,config={},status="healthy",permissions={},capabilities={},quota={},updated_at=datetime.now(timezone.utc)))
                credentials=CREDS if provider=="meta" else {"token":"mfk_test"}
                s.add(ProviderCredential(workspace_id="default",provider=provider,encrypted=encrypt("default",provider,credentials),updated_at=datetime.now(timezone.utc)))
        self.manager=ProviderManager(self.sessions,transports={"meta":httpx.MockTransport(graph)})
    def tearDown(self):self.env.stop();super().tearDown()
    def primary(self,p="meta",fallback=None):
        with self.sessions.begin() as s:
            old=s.get(ProviderRoutingSetting,("default","workspace"))
            if old:old.primary_provider=p;old.fallback_provider=fallback
            else:s.add(ProviderRoutingSetting(workspace_id="default",scope="workspace",primary_provider=p,fallback_provider=fallback,action_provider="disabled",updated_at=datetime.now(timezone.utc)))
    async def test_meta_only_full_dashboard_filters_catalog_persistence_without_metricflow(self):
        today=date.today();self.primary()
        result=await MetaSync(self.manager).run("initial",today-timedelta(days=2),today)
        self.assertEqual(result["status"],"succeeded",result)
        with self.sessions() as s:
            for level in ("account","campaign","adset","ad","creative"):
                report=table_data(s,"default",Filters(today,today),level=level)
                self.assertEqual(report["total"],1,level);self.assertEqual(report["rows"][0]["spend"],"100.00000000")
                self.assertEqual(report["rows"][0]["source_provider"],"meta")
            from services.analytics.optional import optional_statistics
            self.assertEqual(optional_statistics(s,"default",today,today,"creative")["total"],1)
            self.assertEqual(optional_statistics(s,"default",today,today,"tracker")["total"],0)
            choices=filter_options(s,"default")["options"];self.assertEqual(len(choices["account"]),1)
            self.assertEqual(table_data(s,"default",Filters(today,today,account=choices["account"][0]["id"]))["total"],1)
            self.assertEqual(dashboard_today(s,"default")["status"],"ready")
            self.assertEqual(s.scalar(select(func.count()).select_from(ActionRequest)),0)
            self.assertEqual(s.scalar(select(ApiQuota.requests).where(ApiQuota.provider=="metricflow")),None)
        from services.storage.database import make_engine,sessions
        other=make_engine(self.db.url)
        try:
            with sessions(other)() as s:self.assertEqual(table_data(s,"default",Filters(today,today))["total"],1)
        finally:other.dispose()
    async def test_meta_reconciliation_replaces_disappeared_facts_and_idempotent_catalog(self):
        today=date.today();await MetaSync(self.manager).run("today",today,today)
        await MetaSync(self.manager).run("today",today,today)
        with self.sessions() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(DailyMetric)),1)
            self.assertEqual(s.scalar(select(func.count()).select_from(AdAccount)),1)
        def no_rows(r):
            if r.url.path.endswith("insights"):return httpx.Response(200,json={"data":[]})
            return graph(r)
        self.manager.transports["meta"]=httpx.MockTransport(no_rows)
        self.assertEqual((await MetaSync(self.manager).run("today",today,today))["status"],"succeeded")
        with self.sessions() as s:self.assertEqual(s.scalar(select(func.count()).select_from(DailyMetric)),0)
    async def test_meta_second_page_failure_preserves_previous_snapshot(self):
        today=date.today();await MetaSync(self.manager).run("today",today,today)
        def broken(r):
            if r.url.path.endswith("insights"):
                if "after" in r.url.params:return httpx.Response(400,json={"error":{"code":100,"message":TOKEN}})
                return httpx.Response(200,json={"data":[insight(today)],"paging":{"next":"https://graph.facebook.com/v26.0/act_100/insights","cursors":{"after":"p2"}}})
            return graph(r)
        self.manager.transports["meta"]=httpx.MockTransport(broken)
        result=await MetaSync(self.manager).run("today",today,today)
        self.assertEqual(result["status"],"partial")
        with self.sessions() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(DailyMetric)),1)
            self.assertEqual(s.scalar(select(DailyMetric.spend)),100)
    async def test_revision_change_fences_publishing_and_disconnect_is_not_reenabled(self):
        today=date.today()
        def changed(r):
            if r.url.path.endswith("insights"):
                with self.sessions.begin() as s:
                    c=s.get(ProviderConnection,("default","meta"));c.enabled=False;c.revision+=1;c.status="disconnected"
            return graph(r)
        self.manager.transports["meta"]=httpx.MockTransport(changed)
        result=await MetaSync(self.manager).run("today",today,today)
        self.assertIn(result["status"],("failed","partial"))
        with self.sessions() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(DailyMetric)),0)
            self.assertEqual(s.get(ProviderConnection,("default","meta")).status,"disconnected")
    async def test_meta_quota_limits_each_http_attempt_without_stopping_metricflow(self):
        with patch.dict(os.environ,{"META_DAILY_BUDGET":"2"}):
            result=await MetaSync(self.manager).run("today",date.today(),date.today())
            self.assertEqual(result["status"],"failed")
        with self.sessions() as s:
            self.assertEqual(s.scalar(select(ApiQuota.requests).where(ApiQuota.provider=="meta")),2)
            self.assertEqual(s.scalar(select(func.count()).select_from(DailyMetric)),0)
    async def seed_both(self):
        today=date.today();await MetaSync(self.manager).run("today",today,today)
        item=row(day=str(today));item.update(campaign_id="10",campaign_name="Campaign",adset_id="20",adset_name="Adset",creative_id="30")
        cfg=config();cfg["fields"].update(campaign_id="campaign_id",campaign_name="campaign_name",adset_id="adset_id",adset_name="adset_name",creative_id="creative_id")
        normalized=InsightSchema(cfg).row(item)
        with self.sessions.begin() as s:
            c=s.get(ProviderConnection,("default","metricflow"));c.enabled=True;c.status="healthy"
            save_row(s,"default","metricflow",normalized,datetime.now(timezone.utc));confirm_accounts(s,"default")
            aid=identity("default","metricflow","act_100")
            run=SyncRun(id="mf-run",workspace_id="default",provider="metricflow",job="today",status="succeeded",start_day=today,end_day=today,started_at=datetime.now(timezone.utc),finished_at=datetime.now(timezone.utc),pages=1,rows=1,requests=1)
            s.add(run);s.flush()
            s.add(ProviderWindow(account_id=aid,start_day=today,end_day=today,imported_at=datetime.now(timezone.utc),source_timestamp=None,attribution=ATTR,hierarchy_hash=hierarchy_hash(s,aid,today,today),complete=True,run_id=run.id,credential_revision=1))
        return today
    async def test_matching_single_canonical_account_no_double_spend_and_manual_switch(self):
        today=await self.seed_both()
        self.primary("metricflow")
        with self.sessions() as s:
            mf=table_data(s,"default",Filters(today,today))["rows"];self.assertEqual(len(mf),1);self.assertEqual(mf[0]["spend"],"100.00000000")
        self.primary("meta")
        with self.sessions() as s:
            meta=table_data(s,"default",Filters(today,today))["rows"]
            self.assertEqual(meta[0]["id"],mf[0]["id"])
            self.assertEqual(meta[0]["spend"],mf[0]["spend"])
            self.assertEqual(len(filter_options(s,"default")["options"]["account"]),1)
    async def test_safe_fallback_same_account_window_attribution_hierarchy_and_audit(self):
        today=await self.seed_both();self.primary("metricflow","meta")
        with self.sessions.begin() as s:s.get(ProviderConnection,("default","metricflow")).status="error"
        with self.sessions.begin() as s:
            result=DataSourceRouter(s,"default").resolve(today,today)
            route=next(iter(result.values()));self.assertEqual(route["mode"],"fallback");self.assertEqual(route["provider"],"meta")
        with self.sessions() as s:self.assertEqual(s.scalar(select(func.count()).select_from(ProviderSwitchEvent)),1)
    async def test_fallback_currency_timezone_attribution_stale_and_hierarchy_mismatch_denied(self):
        today=await self.seed_both();self.primary("metricflow","meta")
        for mode in ("currency","timezone","attribution","stale","hierarchy","incomplete","unavailable","unconfirmed"):
            with self.sessions.begin() as s:
                c=s.get(ProviderConnection,("default","metricflow"));c.status="error"
                aid=identity("default","meta","act_100");a=s.get(AdAccount,aid);w=s.get(ProviderWindow,(aid,today,today))
                old=(a.currency,a.timezone,w.attribution,w.imported_at,w.complete,s.get(ProviderConnection,("default","meta")).status)
                if mode=="currency":a.currency="EUR"
                if mode=="timezone":a.timezone="UTC"
                if mode=="attribution":w.attribution={**ATTR,"action_report_time":"conversion"}
                if mode=="stale":w.imported_at=datetime.now(timezone.utc)-timedelta(hours=1)
                if mode=="incomplete":w.complete=False
                if mode=="unavailable":s.get(ProviderConnection,("default","meta")).status="error"
                if mode=="unconfirmed":w.attribution=None
                if mode=="hierarchy":
                    e=s.get(Entity,identity(aid,"campaign","10"));e.external_id="999"
                s.flush()
                route=next(iter(DataSourceRouter(s,"default").resolve(today,today).values()))
                self.assertEqual(route["mode"],"stale",mode);self.assertTrue(route["stale"],mode)
                self.assertEqual(route["provider"],"metricflow",mode)
                a.currency,a.timezone,w.attribution,w.imported_at,w.complete,s.get(ProviderConnection,("default","meta")).status=old
                if mode=="hierarchy":e.external_id="10"
    async def test_same_names_different_ids_stay_separate(self):
        await MetaSync(self.manager).run("today",date.today(),date.today())
        with self.sessions.begin() as s:
            s.add(AdAccount(id="other",workspace_id="default",provider="metricflow",external_id="act_999",name="Same name",currency="USD",timezone="Europe/Moscow",observed_at=datetime.now(timezone.utc)))
            s.flush();confirm_accounts(s,"default")
            identities=s.scalars(select(ProviderAccountMapping.canonical_id)).all()
            self.assertEqual(len(set(identities)),2)
    async def test_per_account_override_independent_and_write_router_disabled(self):
        today=await self.seed_both();self.primary("metricflow")
        with self.sessions.begin() as s:
            mapping=s.scalar(select(ProviderAccountMapping).limit(1))
            s.add(ProviderRoutingSetting(workspace_id="default",scope=mapping.canonical_id,primary_provider="meta",fallback_provider=None,action_provider="disabled",updated_at=datetime.now(timezone.utc)))
        with self.sessions() as s:self.assertEqual(table_data(s,"default",Filters(today,today))["rows"][0]["source_provider"],"meta")
        with self.assertRaises(WriteDisabled):await ActionProviderRouter().execute("meta","pause_entity","1")
    def test_authenticated_encryption_binding_replacement_and_missing_key(self):
        enc=encrypt("default","meta",CREDS)
        self.assertNotIn(TOKEN,enc);self.assertEqual(decrypt("default","meta",enc),CREDS)
        with self.assertRaises(CredentialError):decrypt("other","meta",enc)
        with self.assertRaises(CredentialError):decrypt("default","metricflow",enc)
        with patch.dict(os.environ,{"PROVIDER_ENCRYPTION_KEY_FILE":""}):
            with self.assertRaises(CredentialError):encrypt("default","meta",CREDS)
class MetricFlowProviderTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
    def schema(self):
        from services.metricflow.onboarding import discover
        x=row();x.update(campaign_id="10",campaign_name="Campaign",adset_id="20",adset_name="Adset")
        catalog_payload={"items":[{"id":"act_100","name":"Account","currency":"USD","timezone":"Europe/Moscow"}],"next_cursor":None}
        payload={"items":[x],"next_cursor":None}
        return InsightSchema(discover(catalog_payload,payload)),catalog_payload,payload
    async def test_adapter_preserves_verified_get_contract_and_disabled_write(self):
        from services.providers.metricflow import MetricFlowProvider
        schema,accounts,insights=self.schema();calls=[]
        def handler(r):
            calls.append(r);self.assertEqual(r.method,"GET")
            endpoint=r.url.path.rsplit("/",1)[-1]
            body={"scopes":["analytics:read","ad_accounts:read","campaigns:read"]} if endpoint=="me" else {"used":0,"limit":1000} if endpoint=="usage" else accounts if endpoint=="ad-accounts" else insights if endpoint=="insights" else {"items":[{"id":"1","effective_status":"ACTIVE"}],"next_cursor":None}
            return httpx.Response(200,json=body)
        p=MetricFlowProvider({"token":"mfk_fixture_only"},schema=schema,transport=httpx.MockTransport(handler),retry_delay=0)
        try:
            self.assertEqual((await p.health_check())["status"],"healthy")
            for method in (p.get_campaigns,p.get_adsets,p.get_ads,p.get_creatives):self.assertEqual(len(await method("act_100",DAY,DAY)),1)
            self.assertEqual(len((await p.get_insights("act_100",DAY,DAY))["data"]),1)
            request=next(r for r in calls if r.url.path.endswith("/insights"))
            self.assertEqual(request.url.params["from"],str(DAY));self.assertEqual(request.url.params["to"],str(DAY))
            self.assertEqual((await p.get_insights("act_999",DAY,DAY))["data"],[])
            for method in (p.pause_entity,p.enable_entity,p.set_budget,p.set_bid):
                with self.assertRaises(WriteDisabled):await method("1")
        finally:await p.close()
    async def test_metricflow_only_sync_dashboard_with_meta_disabled_no_meta_http(self):
        schema,accounts,insights=self.schema()
        key=Path(self.directory.name)/"key";key.write_bytes(Fernet.generate_key())
        with patch.dict(os.environ,{"PROVIDER_ENCRYPTION_KEY_FILE":str(key)}):
            with self.sessions.begin() as s:
                for provider in ("metricflow","meta"):
                    s.add(ProviderConnection(workspace_id="default",provider=provider,enabled=provider=="metricflow",credential_source="encrypted",revision=1,config={},status="healthy" if provider=="metricflow" else "disconnected",permissions={},capabilities={},quota={},updated_at=utc_now()))
                s.add(ProviderCredential(workspace_id="default",provider="metricflow",encrypted=encrypt("default","metricflow",{"token":"mfk_fixture_only"}),updated_at=utc_now()))
            calls=[]
            def handler(r):
                calls.append(r);self.assertEqual(r.method,"GET")
                return httpx.Response(200,json=accounts if r.url.path.endswith("ad-accounts") else insights)
            manager=ProviderManager(self.sessions,transports={"metricflow":httpx.MockTransport(handler)})
            result=await metricflow_sync(manager,"today",DAY,DAY,schema)
            self.assertEqual(result["status"],"succeeded",result)
            with self.sessions() as s:
                for level in ("account","campaign","adset","ad"):
                    self.assertEqual(table_data(s,"default",Filters(DAY,DAY),level=level)["total"],1)
                self.assertEqual(s.scalar(select(func.count()).select_from(ApiQuota).where(ApiQuota.provider=="meta")),0)
                self.assertEqual(s.scalar(select(func.count()).select_from(ActionRequest)),0)
                self.assertEqual(s.scalar(select(func.count()).select_from(ProviderWindow)),1)
            self.assertTrue(all(r.url.host=="metricflowit.click" for r in calls))
