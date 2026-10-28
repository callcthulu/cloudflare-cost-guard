"""Use the real guard runner/state format across the optional monitor boundary."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cfguard.models import AccountConfig, Config, ResourceKey, Snapshot, Subscription
from cfguard.runner import run_once
from cfguard.monitoring.policy import assess
from cfguard.monitoring.sources import collect


class NativeMonitoringTests(unittest.TestCase):
    def test_guard_run_is_observed_readonly_and_allowed_positive_fee_warns(self):
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        account_id, subscription_id = 'a' * 32, 'synthetic-subscription'
        identity = hashlib.sha256(json.dumps([account_id, subscription_id], separators=(',', ':')).encode()).hexdigest()
        subscription = Subscription(ResourceKey(account_id, 'account', 'subscriptions'),
            identity, 'Synthetic free plan with a positive commitment', Decimal('2.50'),
            'USD', True, provider_id=subscription_id, plan_id='free', plan_scope='account')
        coverage = {'subscriptions.account': 'complete', 'billing_info': 'parsed',
                    'billing_account_coverage': 'unavailable', 'billing_period': 'unverified',
                    'rated_usage': 'unknown', 'workers.requests': 'approximate'}
        snapshot = Snapshot(account_id, (), (), (subscription,), coverage, now)

        class GuardReader:
            def __init__(self, path): pass
            def collect(self, account, timestamp, *, include_rated=True): return snapshot
            def disable_worker_endpoints(self, resource):
                raise AssertionError('observe must never mutate provider resources')

        class InventoryReader:
            def inventory(self, account, product):
                if account != account_id or product not in ('workers', 'zones'):
                    raise AssertionError('inventory must be account-bound and read-only')
                return []

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'guard'
            account = AccountConfig('synthetic', account_id, Path(directory) / 'unused.token',
                                    1, Decimal('0'), 'USD', expected_subscriptions=('free',))
            _, report = run_once(Config(accounts=(account,), state_dir=state), now=now,
                                 client_factory=GuardReader)
            self.assertEqual(report['actions'], [])
            database = state / 'guard.sqlite3'
            before = database.read_bytes()
            config = {'guard_database': str(database), 'accounts': [{
                'id': account_id, 'read_token_file': str(Path(directory) / 'unused.token'),
                'expected_workers': [], 'expected_zones': [],
                'known_limitations': {'billing_account_coverage': 'unavailable'}}]}
            observation = collect(config, now, client_factory=lambda path: InventoryReader())
            self.assertEqual(observation['guard']['status'], 'ok')
            decision = assess(observation, now)
            fees = [issue for issue in decision['issues'] if issue['reason'] == 'positive_subscription']
            self.assertEqual(len(fees), 1)
            self.assertEqual(fees[0]['details'], {'amount': '2.50', 'currency': 'USD'})
            self.assertEqual(database.read_bytes(), before)
            self.assertNotIn(account_id, json.dumps(observation))


if __name__ == '__main__': unittest.main()
