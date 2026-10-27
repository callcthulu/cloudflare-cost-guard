"""Synthetic regressions for cross-endpoint identity and billing-info caching."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cfguard.models import AccountConfig, Config, ResourceKey, Snapshot, Subscription, RatedCharge
from cfguard.policy import evaluate
from cfguard.runner import _rated_snapshot
from cfguard.state import Store


NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def subscription(provider_id='shared', scope='account', zone=None, amount='7', **extra):
    source = hashlib.sha256(json.dumps(['account-fixture', provider_id], separators=(',', ':')).encode()).hexdigest()
    return Subscription(ResourceKey('account-fixture', scope, 'subscriptions', zone_id=zone),
                        source, 'Fixture', Decimal(amount), 'USD', True,
                        provider_id=provider_id, plan_id='free', **extra)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.account = AccountConfig('fixture', 'account-fixture', Path('/unused'), 1, Decimal('0'),
                                     'USD', zones=('zone-fixture',), billing_period_verified=True)

    def snapshot(self, subscriptions=(), **coverage):
        return Snapshot(self.account.account_id, (), (), subscriptions,
                        {'subscriptions.account': 'complete', 'subscriptions.zone:zone-fixture': 'complete',
                         **coverage}, NOW)

    def commitment(self, *rows, **coverage):
        decisions = evaluate(Config(accounts=(self.account,)), self.snapshot(rows, **coverage), {})
        return next(d for d in decisions if d.metric == 'subscription_commitment')

    def test_same_provider_identity_across_scopes_is_counted_once(self):
        for price in ('0', '7'):
            with self.subTest(price=price):
                a = subscription(amount=price)
                z = subscription(scope='zone', zone='zone-fixture', amount=price)
                decision = self.commitment(a, z, a, z)
                self.assertEqual(decision.value, Decimal(price))
                self.assertEqual(decision.status, 'healthy')
                self.assertEqual(len(decision.evidence_ids), 1)

    def test_distinct_provider_subscriptions_are_counted_separately(self):
        self.assertEqual(self.commitment(subscription(), subscription('second')).value, Decimal('14'))

    def test_conflicting_duplicate_identity_never_produces_a_total(self):
        a = subscription()
        z = subscription(scope='zone', zone='zone-fixture')
        conflicts = (replace(z, amount=Decimal('8')), replace(z, currency='EUR'),
                     replace(z, plan_id='different'), replace(z, provider_id='different'),
                     replace(z, source_key='different'), replace(z, plan_scope='account'),
                     replace(z, key=ResourceKey(self.account.account_id, 'zone', 'subscriptions', zone_id='another-zone')))
        for other in conflicts:
            with self.subTest(other=other):
                decision = self.commitment(a, z, other)
                self.assertIsNone(decision.value)
                self.assertEqual(decision.status, 'unknown')

    def test_names_are_not_identity_and_zone_attribution_survives(self):
        a = subscription()
        z = replace(subscription(scope='zone', zone='zone-fixture', plan_scope='zone'), name='Localized')
        self.assertEqual(self.commitment(a, z).value, Decimal('7'))
        self.assertEqual(z.key.zone_id, 'zone-fixture')
        self.assertEqual(a.key.scope, 'account')

    def test_missing_verified_identity_or_plan_is_unknown(self):
        for change in ({'provider_id': None}, {'plan_id': None}, {'provider_id': []},
                       {'plan_scope': 'unsupported'}, {'allowed': 1}):
            with self.subTest(change=change):
                self.assertIsNone(self.commitment(replace(subscription(), **change)).value)

    def test_incomplete_endpoint_does_not_clear_a_commitment_to_zero(self):
        result = self.commitment(**{'subscriptions.account': 'unknown:incomplete_inventory'})
        self.assertIsNone(result.value)
        self.assertEqual(result.status, 'unknown')

    def test_unverified_billing_info_blocks_even_a_claimed_complete_rated_total(self):
        start = NOW.replace(day=1, hour=0)
        row = RatedCharge(ResourceKey(self.account.account_id, 'account', 'billing'), 'line', Decimal('0'),
                          'incremental', 'USD', start, NOW, 'fixture', 'good')
        for metadata in ({}, {'billing_period': 'unverified'}, {'billing_period': 'unknown:missing'},
                         {'billing_account_coverage': 'covered'}, {'billing_period': 'verified_config'},
                         {'billing_period': 'verified_config', 'billing_account_coverage': 'covered'},
                         {'billing_period': 'verified_config', 'billing_account_coverage': 'covered', 'billing_info': 'unknown:schema'},
                         {'billing_period': 'verified_config', 'billing_account_coverage': 'unavailable'},
                         {'billing_period': 'verified_config', 'billing_account_coverage': 'unknown:schema'}):
            snap = replace(self.snapshot(**{'rated_usage': 'complete', **metadata}), rated_charges=(row,))
            result = next(d for d in evaluate(Config(accounts=(self.account,)), snap, {}) if d.metric == 'rated_cost')
            self.assertIsNone(result.value)
            self.assertEqual(result.status, 'unknown')

    def test_missing_info_proof_also_blocks_full_period_estimates(self):
        from test_policy import observation, PRICE
        account = replace(self.account, prices=(PRICE,))
        obs = replace(observation(), key=ResourceKey(account.account_id, 'account', 'workers'),
                      fetched_at=NOW, data_through=NOW)
        proof = {'billing_period': 'verified_config', 'billing_account_coverage': 'covered', 'billing_info': 'parsed'}
        for missing in (None, *proof):
            with self.subTest(missing=missing):
                coverage = {key: value for key, value in proof.items() if key != missing}
                snap = replace(self.snapshot(**coverage), observations=(obs,))
                result = next(d for d in evaluate(Config(accounts=(account,)), snap, {}) if d.metric == 'estimated_cost')
                self.assertEqual(result.value, Decimal('0.60') if missing is None else None)
                if missing is not None:
                    self.assertEqual(result.reason_code, 'billing_period_unverified')

    def test_billing_metadata_is_cached_without_promoting_unknown_coverage(self):
        for status in ('unavailable', 'covered', 'unknown:billing_info_schema'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
                first = self.snapshot(**{'billing_info': 'parsed', 'billing_account_coverage': status,
                                         'billing_period': 'unverified', 'rated_usage': 'unknown:empty_rated_response'})
                _rated_snapshot(store, self.account, first, NOW, True)
                next_snap = self.snapshot(**{'billing_info': 'not_fetched', 'billing_account_coverage': 'not_fetched',
                                             'billing_period': 'unverified', 'rated_usage': 'not_fetched'})
                restored = _rated_snapshot(store, self.account, next_snap, NOW + timedelta(minutes=5), False)
                self.assertEqual(restored.coverage['billing_account_coverage'], status)
                self.assertEqual(restored.coverage['billing_info'], 'parsed')
                self.assertEqual(restored.coverage['billing_period'], 'unverified')
                self.assertEqual(restored.coverage['rated_usage'], 'unknown:empty_rated_response')

    def test_stale_future_or_previous_period_cache_cannot_verify_period(self):
        for offset in (timedelta(hours=2), timedelta(minutes=-5), timedelta(days=5)):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
                first = self.snapshot(**{'billing_info': 'parsed', 'billing_account_coverage': 'covered',
                                         'billing_period': 'verified_config', 'rated_usage': 'unknown'})
                _rated_snapshot(store, self.account, first, NOW, True)
                restored = _rated_snapshot(store, self.account, first, NOW + offset, False)
                self.assertEqual(restored.coverage['billing_period'], 'unverified')
                self.assertNotEqual(restored.coverage['billing_account_coverage'], 'covered')

    def test_cached_period_cannot_override_config_or_cross_boundary(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            first = self.snapshot(**{'billing_info': 'parsed', 'billing_account_coverage': 'covered',
                                     'billing_period': 'verified_config', 'rated_usage': 'unknown',
                                     'billing_period_valid_until': '2026-11-01T00:00:00Z'})
            before = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)
            _rated_snapshot(store, self.account, first, before, True)
            restored = _rated_snapshot(store, self.account, first, before + timedelta(minutes=5), False)
            self.assertEqual(restored.coverage['billing_period'], 'unverified')
            restored = _rated_snapshot(store, replace(self.account, billing_period_verified=False), first, before, False)
            self.assertEqual(restored.coverage['billing_period'], 'unverified')
            restored = _rated_snapshot(store, replace(self.account, billing_day=2), first, before, False)
            self.assertEqual(restored.coverage['billing_period'], 'unverified')

    def test_old_cache_without_billing_metadata_is_unknown_after_upgrade(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            store.set_meta('rated_cache:' + self.account.account_id,
                           json.dumps({'rows': [], 'coverage': 'unknown', 'fetched_at': NOW.isoformat()}))
            result = _rated_snapshot(store, self.account, self.snapshot(), NOW, False)
            self.assertEqual(result.coverage['billing_period'], 'unverified')
            self.assertEqual(result.coverage['billing_account_coverage'], 'unknown:cache_metadata_missing')

    def test_cached_period_proof_expires_at_known_metadata_transition(self):
        for expires in (None, 'invalid', '2026-10-27T12:01:00Z', '2026-10-27T12:05:00Z',
                        '2026-12-01T00:00:00Z', '2026-10-27T12:06:00Z'):
            with self.subTest(expires=expires), tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
                first = self.snapshot(**{'billing_info': 'parsed', 'billing_account_coverage': 'covered',
                                         'billing_period': 'verified_config', 'rated_usage': 'unknown'})
                if expires is not None:
                    first = replace(first, coverage={**first.coverage, 'billing_period_valid_until': expires})
                _rated_snapshot(store, self.account, first, NOW, True)
                result = _rated_snapshot(store, self.account, first, NOW + timedelta(minutes=5), False)
                self.assertEqual(result.coverage['billing_period'],
                                 'verified_config' if expires == '2026-10-27T12:06:00Z' else 'unverified')

    def test_collector_to_policy_reconciles_real_adapter_metadata(self):
        from cfguard.cloudflare import Client, HttpResponse
        for zone_price in (7, 8):
            with self.subTest(zone_price=zone_price), tempfile.TemporaryDirectory() as directory:
                token = Path(directory) / 'synthetic.token'
                token.write_text('synthetic-token')
                token.chmod(0o600)
                account = replace(self.account, read_token_file=token, expected_subscriptions=('free',))
                calls = []
                row = {'id': 'shared', 'price': 7, 'currency': 'USD', 'rate_plan': {'id': 'free', 'scope': 'zone'}}
                def transport(request, timeout):
                    calls.append(request)
                    if request.full_url.endswith('/subscriptions'):
                        value = {'success': True, 'result': [row]}
                    elif request.full_url.endswith('/subscription'):
                        value = {'success': True, 'result': {**row, 'price': zone_price}}
                    elif request.full_url.endswith('/billable-usage/info'):
                        value = {'success': True, 'result': {'covered': False, 'subscriptions': []}}
                    elif request.full_url.endswith('/billable-usage'):
                        value = {'success': True, 'result': []}
                    else:
                        self.assertEqual(request.method, 'POST')
                        self.assertTrue(request.full_url.endswith('/graphql'))
                        value = {'errors': [{'message': 'synthetic unavailable analytics'}]}
                    return HttpResponse(200, json.dumps(value).encode(), {})
                snap = Client(token, transport=transport).collect(account, NOW)
                result = next(d for d in evaluate(Config(accounts=(account,)), snap, {})
                              if d.metric == 'subscription_commitment')
                self.assertEqual(result.value, Decimal('7') if zone_price == 7 else None)
                self.assertEqual({s.key.scope for s in snap.subscriptions}, {'account', 'zone'})
                self.assertEqual(snap.coverage['billing_account_coverage'], 'unavailable')
                self.assertEqual(snap.coverage['billing_period'], 'unverified')
                self.assertTrue(all(r.method == 'GET' or r.full_url.endswith('/graphql') for r in calls))
