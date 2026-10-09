import copy
from datetime import date,timedelta
from decimal import Decimal
import json
from pathlib import Path
import unittest
import httpx
from sqlalchemy import func,select
from services.analytics.scopes import finance,creative_window,tracker_days,breakdown_identity
from services.analytics.optional import optional_statistics
from services.sync.backfill import Backfill,windows
from services.sync.optional import OptionalSync
from services.sync.schema import SchemaError
from services.storage.models import AdAccount,ReadStatistic,DailyMetric
from tests.test_sync import StorageFixture,row

ROOT=Path(__file__).resolve().parents[1]
START=date(2026,10,1);END=date(2026,10,7)
def captures():
    data=json.loads((ROOT/'docs/metricflow-full-read/capture.json').read_text())
    return {r['label']:r['body'] for r in data['captures'] if 'body' in r}

class ScopeTests(unittest.TestCase):
    def test_additive_events_and_nonadditive_reach_frequency(self):
        from services.analytics.dashboard import aggregate
        from services.storage.models import DailyMetric
        a=DailyMetric(spend=Decimal(1),impressions=10,clicks=2,leads=0,sales=0,conversions=0,
            reach=7,frequency=Decimal("1.42"),raw={"registrations":3,"inline_link_clicks":1})
        result=aggregate([(a,None)],"USD","UTC")
        self.assertEqual(result["reach"],7);self.assertEqual(result["registrations"],3)
        result=aggregate([(a,None),(a,None)],"USD","UTC")
        self.assertEqual(result["registrations"],6);self.assertIsNone(result["reach"]);self.assertIsNone(result["frequency"])
        a.raw={"registrations":True}
        self.assertIsNone(aggregate([(a,None)],"USD","UTC")["registrations"])
    def test_extra_counters_on_aggregate_without_raw_metadata_are_unknown(self):
        from types import SimpleNamespace
        from services.analytics.dashboard import extra_metrics
        values=extra_metrics([(SimpleNamespace(),None)])
        self.assertTrue(all(value is None for value in values.values()))
    def test_ad_tracker_window_keeps_raw_and_configured_conversion_counters(self):
        from services.analytics.scopes import tracker_ad_windows
        source=captures()
        for i in range(3):
            rows=tracker_ad_windows(source[f"{i}-ads-week"],START,END)
            self.assertTrue(rows)
            raw=sum(r["counts"]["conversions_raw"] or 0 for r in rows)
            configured=sum(r["counts"]["conversions"] or 0 for r in rows)
            account=sum(r["conversions"] for r in source[f"{i}-tracker-week"]["data"])
            self.assertEqual(raw,account)
            self.assertNotEqual(raw,configured)
    def test_tracker_real_days_counts_and_unknown_currency(self):
        source=captures()
        for i in range(3):
            rows=tracker_days(source[f'{i}-tracker-week'],START,END)
            self.assertEqual(len(rows),7)
            self.assertTrue(all(r['currency'] is None for r in rows))
            self.assertIn('sales',rows[0]['counts'])
    def test_tracker_duplicate_or_outside_window_fails(self):
        body=captures()['0-tracker-week']
        bad=copy.deepcopy(body);bad['data'].append(bad['data'][0]);bad['meta']['total']+=1
        with self.assertRaises(SchemaError):tracker_days(bad,START,END)
        bad=copy.deepcopy(body);bad['data'][0]['date']='2026-09-01'
        with self.assertRaises(SchemaError):tracker_days(bad,START,END)
    def test_real_creative_keys_join_ads_and_reconcile(self):
        source=captures()
        for i in range(3):
            rows=creative_window(source[f'{i}-ads-week'],source[f'{i}-creatives-week'],START,END,'USD')
            self.assertTrue(rows);self.assertTrue(all(r['ad_ids'] for r in rows))
    def test_creative_key_stable_in_repeat_and_single_day(self):
        source=captures()
        week={r['creative_key'] for r in source['0-creatives-week']['data']}
        self.assertEqual(week,{r['creative_key'] for r in source['0-creatives-week-repeat']['data']})
        self.assertTrue({r['creative_key'] for r in source['0-creatives-day']['data']}<=week)
    def test_creative_unlinked_identity_or_wrong_totals_fail(self):
        source=captures()
        for kind in ('identity','metric','version','currency','tracker_count'):
            ads=copy.deepcopy(source['0-ads-week']);cs=copy.deepcopy(source['0-creatives-week'])
            if kind=='identity':cs['data'][0]['creative_key']='not_linked'
            if kind=='metric':cs['data'][0]['spend']+=1
            if kind=='version':cs['meta']['data_updated_at']='another_version'
            if kind=='currency':ads['data'][0]['currency']='EUR'
            if kind=='tracker_count':cs['data'][0]['tracker']['clicks']=True
            with self.subTest(kind=kind),self.assertRaises(SchemaError):creative_window(ads,cs,START,END,'USD')
    def test_breakdown_does_not_infer_dimension_from_age_like_values(self):
        b=captures()['breakdown-country']
        with self.assertRaises(SchemaError):breakdown_identity(b,START,END,'country')
        with self.assertRaises(SchemaError):breakdown_identity(b,START,END,'age')
    def test_finance_unknown_and_mismatched_currency_or_scope(self):
        base=dict(revenue_currency='USD',spend_currency='USD',revenue_scope=('acct','2026-10-07'),spend_scope=('acct','2026-10-07'))
        for name,value in [('revenue_currency',None),('revenue_currency','EUR'),('revenue_scope',('different','2026-10-07')),('revenue_scope',None)]:
            with self.subTest(name=name,value=value):
                p={**base,name:value};self.assertEqual(finance(100,50,**p),{'revenue':None,'profit':None,'roi':None})
        self.assertIsNone(finance(None,50,**base)['roi'])
    def test_roi_calculation_including_loss_and_zero_spend(self):
        p=dict(revenue_currency='USD',spend_currency='USD',revenue_scope='exact',spend_scope='exact')
        self.assertEqual(Decimal(finance(150,100,**p)['roi']),50)
        self.assertEqual(Decimal(finance(50,100,**p)['roi']),-50)
        self.assertIsNone(finance(50,0,**p)['roi'])

class BackfillTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
    def handler(self,request):
        self.assertEqual(request.method,'GET')
        a=date.fromisoformat(request.url.params['from']);b=date.fromisoformat(request.url.params['to'])
        if getattr(self,'broken',None)==a:return httpx.Response(200,json={'items':[{'bad':True}],'next_cursor':None})
        return httpx.Response(200,json={'items':[row(day=str(a+timedelta(days=i))) for i in range((b-a).days+1)],'next_cursor':None})
    async def test_thirty_days_replay_and_resume_without_extra_http(self):
        a=date(2026,9,8);b=date(2026,10,7)
        engine=self.sync(self.handler,max_pages=4);service=Backfill(engine)
        result=await service.run(a,b)
        self.assertEqual(result['days_completed'],30);self.assertEqual(result['requests'],10)
        self.assertEqual((await service.run(a,b))['requests'],0)
        self.assertEqual((await service.run(a,b,replay=True))['requests'],10)
        with self.sessions() as session:self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)),30)
    async def test_failed_window_atomic_and_resume_skips_success(self):
        a=date(2026,9,8);b=a+timedelta(days=8);self.broken=a+timedelta(days=3)
        service=Backfill(self.sync(self.handler,max_pages=4))
        first=await service.run(a,b);self.assertEqual(first['status'],'paused');self.assertEqual(first['days_completed'],3)
        with self.sessions() as session:self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)),3)
        self.broken=None
        second=await service.run(a,b)
        self.assertEqual(second['windows'][0]['status'],'already_complete');self.assertEqual(second['requests'],2)
        with self.sessions() as session:self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)),9)
    async def test_low_quota_preflight_sends_no_request(self):
        service=Backfill(self.sync(self.handler,budget=2,max_pages=4))
        result=await service.run(START,END)
        self.assertEqual(result['status'],'paused_quota');self.assertEqual(result['requests'],0)
    def test_window_edges(self):
        self.assertEqual(list(windows(START,START)),[(START,START)])
        self.assertEqual(len(list(windows(START,END))),3)
        with self.assertRaises(ValueError):list(windows(END,START))
    async def test_changed_schema_does_not_reuse_old_checkpoint(self):
        service=Backfill(self.sync(self.handler,max_pages=4))
        await service.run(START,END)
        other=self.sync(self.handler,max_pages=4);other.schema.config['query']={'limit':50}
        self.assertNotEqual(service.job,Backfill(other).job)
        self.assertEqual(Backfill(other).plan(START,END)['completed_windows'],0)

class OptionalTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
    def prepare(self):
        self.source=captures()
        with self.sessions.begin() as session:
            session.add(AdAccount(id='account',workspace_id='default',provider='metricflow',
                external_id='act_100',name='Account',currency='USD',timezone='Europe/Moscow',observed_at=self.sync(lambda r:None).clock()))
    def handler(self,request):
        self.assertEqual(request.method,'GET')
        endpoint=request.url.path.split('/')[-1]
        name={'tracker':'tracker','ads':'ads','creatives':'creatives'}[endpoint]
        body=copy.deepcopy(self.source['0-'+name+'-week'])
        if getattr(self,'bad_creative',False) and endpoint=='creatives':body['data'][0]['spend']+=1
        return httpx.Response(200,json=body)
    async def test_optional_import_idempotent_keeps_core_facts_untouched(self):
        self.prepare()
        core=self.sync(self.handler);original_lease=core.lease_key
        service=OptionalSync(core)
        self.assertEqual(core.lease_key,original_lease)
        self.assertNotEqual(service.sync.lease_key,original_lease)
        first=await service.run(START,END);self.assertEqual(first['status'],'succeeded');self.assertEqual(first['requests'],3)
        second=await service.run(START,END);self.assertEqual(second['status'],'succeeded')
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)),0)
            self.assertEqual(session.scalar(select(func.count()).select_from(ReadStatistic).where(ReadStatistic.kind=="creative")),12)
            self.assertGreater(optional_statistics(session,"default",START,END,"tracker",scope="ad")["total"],0)
            tracker=optional_statistics(session,'default',START,END,'tracker')
            self.assertEqual(tracker['total'],7);self.assertTrue(all(r['revenue'] is None and r['timezone'] is None for r in tracker['rows']))
            self.assertEqual(optional_statistics(session,'default',START+timedelta(days=1),END,'creative')['total'],0)
    async def test_optional_failure_preserves_previous_creative_window(self):
        self.prepare();service=OptionalSync(self.sync(self.handler));await service.run(START,END)
        self.bad_creative=True
        result=await service.run(START,END);self.assertEqual(result['status'],'partial')
        with self.sessions() as session:self.assertEqual(optional_statistics(session,'default',START,END,'creative')['total'],12)

    async def test_optional_numeric_sort_is_global_before_pagination_and_keeps_unknowns(self):
        self.prepare();await OptionalSync(self.sync(self.handler)).run(START,END)
        with self.sessions() as session:
            for kind in ("creative","tracker"):
                all_rows=optional_statistics(session,"default",START,END,kind,sort_key="clicks",sort_direction="desc")
                self.assertGreater(all_rows["total"],1)
                first=optional_statistics(session,"default",START,END,kind,sort_key="clicks",sort_direction="desc",limit=1)
                second=optional_statistics(session,"default",START,END,kind,sort_key="clicks",sort_direction="desc",offset=1,limit=1)
                self.assertEqual(first["rows"],all_rows["rows"][:1])
                self.assertEqual(second["rows"],all_rows["rows"][1:2])
                self.assertEqual(first["next_offset"],1)
                self.assertEqual(first["total"],all_rows["total"])
                self.assertTrue(all(r["revenue"] is None and r["profit"] is None and r["roi"] is None for r in all_rows["rows"]))
