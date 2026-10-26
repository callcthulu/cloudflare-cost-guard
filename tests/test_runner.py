import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from cfguard.models import AccountConfig, Config, Snapshot, ResourceKey, ResourceConfig, ActionResult
from cfguard.state import Store
from unittest.mock import patch
from cfguard.runner import run_once


class FakeClient:
    mutations = 0
    calls = []
    def __init__(self, token_file):
        self.token_file = token_file
    def collect(self, account, now, *, include_rated=True):
        self.calls.append((account.account_id, include_rated))
        if account.account_id == 'broken':
            raise OSError('token SECRET_DO_NOT_LOG')
        return Snapshot(account.account_id, (), (), (), {'rated_usage': 'unknown', 'subscriptions': 'unknown'}, now)
    def disable_worker_endpoints(self, resource):
        FakeClient.mutations += 1
        raise AssertionError('observe attempted mutation')


class RunnerTests(unittest.TestCase):
    def test_hourly_rated_cadence_and_missed_run_alert(self):
        FakeClient.calls = []
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            account = AccountConfig('a','ok',Path('/unused'),1,Decimal('0'),'USD')
            config = Config(accounts=(account,),state_dir=Path(directory))
            run_once(config,now=now,client_factory=FakeClient)
            run_once(config,now=now+timedelta(minutes=5),client_factory=FakeClient)
            _, report = run_once(config,now=now+timedelta(minutes=61),client_factory=FakeClient)
            self.assertEqual([call[1] for call in FakeClient.calls],[True,False,True])
            self.assertEqual(report['scheduler'],'missed_runs')

    def test_pending_intent_reconciles_without_spike_or_executor_token(self):
        with tempfile.TemporaryDirectory() as directory:
            account = AccountConfig('a','ok',Path('/unused'),1,Decimal('0'),'USD')
            key = ResourceKey('ok','resource','workers','demo')
            resource = ResourceConfig(key,'Sample',permitted_action='disable_worker_endpoints')
            config = Config(mode='enforce',accounts=(account,),resources=(resource,),state_dir=Path(directory))
            with Store(Path(directory)) as store:
                store.save_intent(key,{'action':'disable_worker_endpoints'})
            def readonly(resource,config,client,store):
                self.assertEqual(client.token_file,account.read_token_file)
                result = ActionResult(key,'verified_public_cutoff',{}, {},store.intent(key)['attempt_id'])
                store.finish_intent(key,result)
                return result
            with patch('cfguard.actions.reconcile',side_effect=readonly) as reconcile:
                _, report = run_once(config,client_factory=FakeClient)
                self.assertEqual(reconcile.call_count,1)
                self.assertEqual(report['actions'][0]['status'],'verified_public_cutoff')

    def test_account_failure_isolated_observe_no_writes_dedup_restart(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            accounts = tuple(AccountConfig(a, a, Path('/unused'), 1, Decimal('0'), 'USD') for a in ('broken','ok'))
            config = Config(accounts=accounts, state_dir=Path(directory))
            code, report = run_once(config, now=now, client_factory=FakeClient)
            self.assertIn(code, (3, 5))
            self.assertEqual(len(report['accounts']), 2)
            self.assertEqual(FakeClient.mutations, 0)
            self.assertNotIn('SECRET', str(report))
            self.assertNotIn('broken', str(report))
            pending = report['notification']['pending']
            code, report2 = run_once(config, now=now, client_factory=FakeClient)
            self.assertEqual(report2['notification']['pending'], pending)
            self.assertEqual(FakeClient.mutations, 0)

    def test_probe_never_mutates_or_delivers(self):
        with tempfile.TemporaryDirectory() as directory:
            account = AccountConfig('a','ok',Path('/unused'),1,Decimal('0'),'USD')
            code, report = run_once(Config(mode='enforce', accounts=(account,), state_dir=Path(directory)),
                                    client_factory=FakeClient, probe=True)
            self.assertEqual(report['mode'], 'probe')
            self.assertEqual(FakeClient.mutations, 0)


if __name__ == '__main__':
    unittest.main()
