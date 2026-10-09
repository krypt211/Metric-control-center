import copy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from sqlalchemy import func, select
from services.metricflow.onboarding import discover
from services.metricflow.probe import scope_check, usage_summary
from services.metricflow.errors import PermissionDenied
from services.storage.database import make_engine, sessions
from services.storage.models import Base, DailyMetric
from services.sync.engine import SyncEngine
from services.sync.schema import InsightSchema, SchemaError, page_items

ROOT=Path(__file__).resolve().parents[1]
def sample(name):
    return json.loads((ROOT/'docs/metricflow-live-contract'/f'{name}.json').read_text())['body']

class LiveContractTests(unittest.TestCase):
    def test_actual_catalog_and_insights_discovery(self):
        config=discover(sample('ad-accounts'),sample('insights'))
        self.assertEqual(config['pagination']['next_cursor_path'],'pagination.cursor')
        self.assertEqual(config['fields']['sales'],'purchases')
        schema=InsightSchema(config)
        rows,cursor=schema.page(sample('insights'))
        self.assertEqual(len(rows),59); self.assertIsNone(cursor)
        self.assertNotIn('revenue',config['fields'])
        self.assertNotIn('tracker_present',config['fields'])

    def test_catalog_truncation_and_changed_limit_fail_closed(self):
        payload=sample('ad-accounts')
        config=discover(payload,sample('insights'))['account_catalog']
        for alteration in ('truncated','limited','missing'):
            bad=copy.deepcopy(payload)
            if alteration=='truncated':bad['data'].pop()
            if alteration=='limited':bad['meta']['limit']=2
            if alteration=='missing':del bad['meta']['total']
            with self.subTest(alteration=alteration),self.assertRaises(SchemaError):
                page_items(bad,config['items_path'],config['pagination'])

    def test_cursor_and_has_more_disagreement_fails_closed(self):
        config=discover(sample('ad-accounts'),sample('insights'))
        for cursor,more in ((None,True),('next',False),('',True),(None,'false')):
            bad=sample('insights');bad['pagination']={'cursor':cursor,'has_more':more}
            with self.subTest(cursor=cursor,more=more),self.assertRaises(SchemaError):InsightSchema(config).page(bad)
        bad=sample('insights');bad['meta']['total']-=1
        with self.assertRaises(SchemaError):InsightSchema(config).page(bad)

    def test_nested_read_scopes_and_usage_are_recognized(self):
        self.assertTrue(scope_check(sample('me')))
        self.assertIn('daily_used',usage_summary(sample('usage')))
        with self.assertRaises(PermissionDenied):scope_check({'api_key':{'scopes':['campaigns:write']}})

class LiveAtomicityTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_change_between_pages_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            db=make_engine(f'sqlite:///{Path(directory)/"db.sqlite"}')
            Base.metadata.create_all(db); factory=sessions(db)
            catalog=sample('ad-accounts'); insights=sample('insights')
            config=discover(catalog,insights)
            def handler(request):
                if request.url.path.endswith('/ad-accounts'):return httpx.Response(200,json=catalog)
                body=copy.deepcopy(insights);body['data']=body['data'][1:2] if 'cursor' in request.url.params else body['data'][:1]
                body['meta']['total']=1
                more='cursor' not in request.url.params
                body['pagination']={'cursor':'next' if more else None,'has_more':more}
                if not more:body['meta']['data_updated_at']='2026-10-07T16:21:51+00:00'
                return httpx.Response(200,json=body)
            result=await SyncEngine(factory,InsightSchema(config),'mfk_fixture',transport=httpx.MockTransport(handler)).run('test',date(2026,10,6),date(2026,10,7))
            self.assertEqual(result['error_code'],'SchemaError')
            with factory() as session:self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)),0)
            db.dispose()

class ParentStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.db=make_engine(f'sqlite:///{Path(self.directory.name)/"state.db"}')
        Base.metadata.create_all(self.db);self.factory=sessions(self.db)
        self.config=json.loads((ROOT/'config/metricflow-schema.json').read_text())
        self.catalog=sample('ad-accounts');self.insights=sample('insights')
        self.calls=[];self.corrupt=False
        from datetime import datetime,timezone
        self.now=datetime(2026,10,7,16,34,tzinfo=timezone.utc)

    def tearDown(self):
        self.db.dispose();self.directory.cleanup()

    def handler(self,request):
        self.assertEqual(request.method,'GET')
        self.calls.append(request.url.path)
        if request.url.path.endswith('/ad-accounts'):return httpx.Response(200,json=self.catalog)
        if request.url.path.endswith('/insights'):return httpx.Response(200,json=self.insights)
        path=request.url.path.split('/')
        aid,endpoint=path[-2:]
        kind='campaign' if endpoint=='campaigns' else 'adset'
        rows={}
        for item in self.insights['data']:
            if item['ad_account_id']!=aid:continue
            eid=item[kind+'_id']
            rows[eid]={'id':eid,'name':'parent fixture','effective_status':'ACTIVE'}
            if kind=='adset':rows[eid]['campaign_id']='999' if self.corrupt else item['campaign_id']
        return httpx.Response(200,json={'data':list(rows.values()),'meta':{'total':len(rows),'limit':None,'offset':None}})

    async def run_sync(self):
        return await SyncEngine(self.factory,InsightSchema(self.config),'mfk_fixture',
            transport=httpx.MockTransport(self.handler),clock=lambda:self.now).run('test',date(2026,10,6),date(2026,10,7))

    async def test_parent_statuses_are_loaded_then_cached_without_extra_reads(self):
        from datetime import timedelta
        from services.storage.models import EntityCurrentState
        first=await self.run_sync()
        self.assertEqual(first['status'],'succeeded')
        self.assertEqual(len(self.calls),8)
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(EntityCurrentState)),92)
        from services.analytics.table import Filters, table_data
        with self.factory() as session:
            selected = table_data(session, "default", Filters(date(2026,10,6), date(2026,10,7), status="ACTIVE"), level="account")
            self.assertEqual(selected["total"], 3)
            self.assertTrue(all(r["status"] == "ACTIVE" for r in selected["rows"]))
        self.calls.clear()
        self.assertEqual((await self.run_sync())['status'],'succeeded')
        self.assertEqual(len(self.calls),2)
        self.now+=timedelta(hours=1)
        self.calls.clear()
        self.assertEqual((await self.run_sync())['status'],'succeeded')
        self.assertEqual(len(self.calls),8)

    async def test_parent_hierarchy_mismatch_does_not_publish_any_facts(self):
        self.corrupt=True
        self.assertEqual((await self.run_sync())['error_code'],'SchemaError')
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)),0)
