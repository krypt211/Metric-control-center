"""Durable provider job isolation, recovery and READ guards; no broker/network."""
import os,unittest
from datetime import timedelta
from unittest.mock import AsyncMock,patch
from sqlalchemy import select
from test_sync import StorageFixture,DAY,NOW
from services.providers.manager import ProviderManager
from services.providers.models import ProviderJob
from workers.providers import dispatch,run_job,meta_sync

class ProviderJobTests(StorageFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.env=patch.dict(os.environ,{'SYNC_ENABLED':'true','ACTIONS_ENABLED':'false','LOCAL_READ_ONLY':'true'})
        self.env.start()
        self.manager=ProviderManager(self.sessions)
        self.mock=patch('workers.providers.manager',return_value=self.manager);self.mock.start()
    def tearDown(self):
        self.mock.stop();self.env.stop();super().tearDown()
    def job(self,id,provider,status='queued',started=None):
        with self.sessions.begin() as s:
            s.add(ProviderJob(id=id,workspace_id='default',provider=provider,kind='health',start_day=DAY,end_day=DAY,status=status,created_at=NOW,started_at=started))
    def test_disabled_or_unsafe_runtime_never_accesses_manager(self):
        for env in ({'SYNC_ENABLED':'false'},{'ACTIONS_ENABLED':'true'},{'LOCAL_READ_ONLY':'false'}):
            with patch.dict(os.environ,env),patch('workers.providers.manager') as manager:
                for task,args in ((dispatch,()),(run_job,('unknown',)),(meta_sync,())):
                    self.assertEqual(task.run(*args)['status'],'disabled')
                manager.assert_not_called()
    def test_provider_failure_does_not_prevent_other_durable_job_and_no_duplicate_claim(self):
        self.job('m','meta');self.job('f','metricflow')
        async def health(provider):
            return {'status':'failed','error_code':'META_TOKEN_INVALID'} if provider=='meta' else {'status':'healthy'}
        with patch.object(self.manager,'health_check',side_effect=health) as call:
            self.assertEqual(run_job.run('m')['status'],'failed')
            self.assertEqual(run_job.run('f')['status'],'succeeded')
            self.assertEqual(run_job.run('f')['status'],'already_claimed')
            self.assertEqual(call.call_count,2)
        with self.sessions() as s:
            self.assertEqual(s.get(ProviderJob,'m').error_code,'META_TOKEN_INVALID')
            self.assertIsNotNone(s.get(ProviderJob,'f').finished_at)
    def test_dispatch_skips_running_provider_but_recovers_expired_claim_after_restart(self):
        self.job('active','meta','running',NOW);self.job('waiting','meta');self.job('other','metricflow')
        with patch('workers.providers.utc_now',return_value=NOW),patch('workers.providers.run_job.apply_async') as send:
            self.assertEqual(dispatch.run()['dispatched'],1)
            self.assertEqual(send.call_args.kwargs['args'],['other'])
        with patch('workers.providers.utc_now',return_value=NOW+timedelta(minutes=31)),patch('workers.providers.run_job.apply_async') as send:
            self.assertEqual(dispatch.run()['dispatched'],2)
            self.assertEqual({c.kwargs['args'][0] for c in send.call_args_list},{'active','other'})
        with self.sessions() as s:self.assertEqual(s.get(ProviderJob,'active').status,'queued')
