"""Synthetic accounting regressions: no provider access or real identities."""
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

from cfguard import models
from cfguard.models import AccountConfig, ActionResult, Config, Observation, RatedCharge, ResourceConfig, ResourceKey, Snapshot
from cfguard.state import Store


NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
KEY = ResourceKey('a' * 32, 'resource', 'workers', 'sample')


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(models, 'GuardBudget'), 'explicit guard budget model is missing')
        from cfguard.budget import evaluate_budget, policy_digest
        self.evaluate = evaluate_budget
        self.digest = policy_digest
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.db.close())
        self.budget = models.GuardBudget(D('1'), 'workers_usage_estimate', D('0.3'), D('0.02'), D('35'),
                                         'synthetic price fixture', '2026-10-27', True, True)
        self.resource = ResourceConfig(KEY, 'Sample', permitted_action='delete_worker', budget=self.budget)
        self.config = Config(accounts=(AccountConfig('fixture', KEY.account_id, Path('/read'), 1, D('0'), 'USD'),),
                             resources=(self.resource,))

    def bucket(self, value='1000000', minute=1, **changes):
        start = NOW - timedelta(minutes=minute + 1)
        return replace(Observation(KEY, 'workers.requests', D(value), 'requests', start, start + timedelta(minutes=1),
                                   NOW, start + timedelta(minutes=1), 'approximate', 'workers-graphql', True, None), **changes)

    def snapshot(self, *buckets, charges=(), **changes):
        return replace(Snapshot(KEY.account_id, (), charges, (), {}, NOW, tuple(buckets)), **changes)

    def test_gross_estimate_request_plus_cpu_reserve_and_no_five_minute_addition(self):
        bucket = self.bucket()
        aggregate = replace(bucket, period_start=NOW-timedelta(minutes=5), period_end=NOW, value=D('999999999'))
        result = self.evaluate(self.config, self.resource, self.snapshot(bucket, observations=(aggregate,)), self.store, NOW)
        self.assertEqual((result.value, result.status, result.proposed_action), (D('1'), 'tripped', 'delete_worker'))
        self.assertIn('estimated', result.reason_code)
        self.assertEqual((result.metric, result.unit, result.currency), ('guard_cost_usd', 'currency', 'USD'))

    def test_real_provider_minute_start_timestamp_is_usable_as_approximate_bucket(self):
        bucket = self.bucket()
        bucket = replace(bucket, data_through=bucket.period_start)
        result = self.evaluate(self.config, self.resource, self.snapshot(bucket), self.store, NOW)
        self.assertEqual((result.value, result.proposed_action), (D('1'), 'delete_worker'))

    def test_schema_three_upgrade_preserves_latch_snapshot_and_legacy_intent(self):
        from cfguard.models import Decision
        self.store.record_decisions((Decision(KEY, 'tripped', 'fixture', metric='requests'),), NOW)
        self.store.save_snapshot(self.snapshot())
        self.store.save_intent(KEY, {'action': 'disable_worker_endpoints'})
        self.store.db.execute('DROP TABLE budget_ledger')
        self.store.db.execute('DROP TABLE intent_history')
        self.store.set_meta('schema_version', '3')
        with Store(self.path) as upgraded:
            self.assertEqual(upgraded.prior()[KEY].status, 'tripped')
            self.assertEqual(upgraded.intent(KEY)['status'], 'pending')
            self.assertEqual(upgraded.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 1)
            self.assertEqual(self.evaluate(self.config, self.resource, self.snapshot(self.bucket()), upgraded, NOW).value, D('1'))

    def test_buckets_deduplicate_max_revision_persist_restart_and_preview_does_not_write(self):
        self.evaluate(self.config, self.resource, self.snapshot(self.bucket('100000')), self.store, NOW)
        self.evaluate(self.config, self.resource, self.snapshot(self.bucket('150000')), self.store, NOW)
        result = self.evaluate(self.config, self.resource, self.snapshot(self.bucket('120000'), self.bucket('50000', 2)), self.store, NOW)
        self.assertEqual(result.value, D('0.2'))
        before = self.store.db.total_changes
        preview = self.evaluate(self.config, self.resource, self.snapshot(self.bucket('1000000')), self.store, NOW, persist=False)
        self.assertEqual(preview.value, D('1.05'))
        self.assertEqual(self.store.db.total_changes, before)
        with Store(self.path) as reopened:
            result = self.evaluate(self.config, self.resource, self.snapshot(), reopened, NOW)
            self.assertEqual(result.value, D('0.2'))
            self.assertEqual(result.status, 'unknown')

    def test_missing_history_below_threshold_unknown_quality_must_be_explicitly_accepted(self):
        result = self.evaluate(self.config, self.resource, self.snapshot(self.bucket('10')), self.store, NOW)
        self.assertEqual(result.status, 'unknown')
        for flags in ({'accept_partial': False}, {'accept_approximate': False}):
            resource = replace(self.resource, budget=replace(self.budget, **flags))
            result = self.evaluate(self.config, resource, self.snapshot(self.bucket()), self.store, NOW)
            self.assertIsNone(result.proposed_action)
            self.assertEqual(result.status, 'unknown')

    def test_invalid_identity_window_and_failed_collection_never_create_zero_or_cutoff(self):
        bad = [replace(self.bucket(), key=replace(KEY, resource_id='unrelated')),
               self.bucket(complete=False), self.bucket(value=D('-1')), self.bucket(value=D('NaN')),
               self.bucket(period_end=NOW), self.bucket(fetched_at=NOW+timedelta(seconds=1))]
        for bucket in bad:
            with self.subTest(bucket=bucket):
                result = self.evaluate(self.config, self.resource, self.snapshot(bucket), self.store, NOW, persist=False)
                self.assertEqual(result.status, 'unknown')
                self.assertIsNone(result.proposed_action)
        result = self.evaluate(self.config, self.resource, self.snapshot(), self.store, NOW)
        self.assertIsNone(result.value)

    def test_guard_period_isolated_and_old_latch_does_not_propose_new_action(self):
        first = self.evaluate(self.config, self.resource, self.snapshot(self.bucket()), self.store, NOW)
        self.store.record_decisions((first,), NOW)
        later = datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc)
        result = self.evaluate(self.config, self.resource, self.snapshot(), self.store, later)
        self.assertIsNone(result.proposed_action)
        self.assertIsNone(result.value)
        self.assertEqual(result.period_start, datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertEqual(self.store.prior()[KEY].status, 'tripped')

    def charge(self, amount='0.5', source_key='row-one', **changes):
        return replace(RatedCharge(ResourceKey(KEY.account_id, 'account', 'billing'), source_key, D(amount),
                                   'incremental', 'USD', NOW-timedelta(days=1), NOW, 'billable-usage-v1', 'good'), **changes)

    def rated_resource(self):
        return replace(self.resource, budget=models.GuardBudget(D('1'), 'account_rated_observed', accept_partial=True))

    def test_rated_rows_persist_deduplicate_and_bind_explicit_target_without_breakdown(self):
        resource = self.rated_resource()
        self.evaluate(self.config, resource, self.snapshot(charges=(self.charge(), self.charge())), self.store, NOW)
        result = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge(source_key='row-two'),)), self.store, NOW)
        self.assertEqual((result.value, result.status, result.proposed_action), (D('0.5'), 'unknown', None))
        self.assertIn('largest_rated_line_floor_partial', result.reason_code)
        result = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('1', 'row-three'),)), self.store, NOW)
        self.assertEqual((result.value, result.proposed_action), (D('1'), 'delete_worker'))

    def test_expanded_charge_window_with_new_identity_cannot_false_trigger_by_addition(self):
        resource = self.rated_resource()
        first = self.charge('0.60', 'earlier', period_start=NOW-timedelta(hours=2), period_end=NOW-timedelta(hours=1))
        expanded = self.charge('0.80', 'expanded', period_start=NOW-timedelta(hours=2))
        self.evaluate(self.config, resource, self.snapshot(charges=(first,)), self.store, NOW)
        with Store(self.path) as reopened:
            result = self.evaluate(self.config, resource, self.snapshot(charges=(expanded,)), reopened, NOW)
            self.assertEqual((result.value, result.status, result.proposed_action), (D('0.80'), 'unknown', None))

    def test_decimal_spelling_does_not_conflict_or_change_approval_semantics(self):
        resource = self.rated_resource()
        self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('1.0'),)), self.store, NOW)
        result = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('1.00'),)), self.store, NOW)
        self.assertEqual((result.value, result.proposed_action), (D('1'), 'delete_worker'))
        self.assertEqual(self.digest(self.resource, self.config.accounts[0]), self.digest(replace(self.resource,
            budget=replace(self.budget, hard_limit_usd=D('1.00'), request_usd_per_million=D('0.300'))), self.config.accounts[0]))

    def test_pre_upgrade_backup_restores_then_migrates_without_losing_latch(self):
        from cfguard.models import Decision
        self.store.record_decisions((Decision(KEY, 'tripped', 'fixture', metric='requests'),), NOW)
        self.store.db.execute('DROP TABLE budget_ledger')
        self.store.db.execute('DROP TABLE intent_history')
        self.store.set_meta('schema_version', '3')
        backup = self.path / 'legacy-backup.sqlite3'
        self.store.backup(backup)
        target = self.path / 'restored'
        Store.restore(backup, target)
        with Store(target) as restored:
            self.assertEqual(restored.prior()[KEY].status, 'tripped')
            self.assertEqual(self.evaluate(self.config, self.resource, self.snapshot(self.bucket()), restored, NOW).value, D('1'))

    def test_rated_identity_conflict_survives_restart_and_ambiguous_rows_block_action(self):
        resource = self.rated_resource()
        self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('2'),)), self.store, NOW)
        result = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('3'),)), self.store, NOW)
        self.assertEqual(result.status, 'unknown')
        self.assertIsNone(result.proposed_action)
        with Store(self.path) as reopened:
            result = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('2'),)), reopened, NOW)
            self.assertEqual(result.status, 'unknown')
        for row in (self.charge('5', kind='cumulative'), self.charge('5', currency='EUR'),
                    self.charge('5', period_start=datetime(2026, 9, 30, tzinfo=timezone.utc))):
            with self.subTest(row=row):
                result = self.evaluate(self.config, resource, self.snapshot(charges=(row,)), self.store, NOW, persist=False)
                self.assertIsNone(result.proposed_action)

    def test_rearm_archives_terminal_budget_intent_preserves_usage_blocks_uncertain(self):
        self.evaluate(self.config, self.resource, self.snapshot(self.bucket()), self.store, NOW)
        for status in ('pending', 'uncertain'):
            self.store.save_intent(KEY, {'action': 'delete_worker', 'budget_digest': self.digest(self.resource, self.config.accounts[0])})
            if status == 'uncertain':
                self.store.finish_intent(KEY, ActionResult(KEY, status, {}, {}, 'fixture'))
            with self.assertRaises(ValueError): self.store.rearm(KEY)
        for status in ('worker_deleted', 'endpoints_disabled', 'not_applied'):
            self.store.finish_intent(KEY, ActionResult(KEY, status, {}, {}, 'fixture'))
            self.store.rearm(KEY)
            self.assertIsNone(self.store.intent(KEY))
            self.assertEqual(self.evaluate(self.config, self.resource, self.snapshot(), self.store, NOW).value, D('1'))
            self.store.save_intent(KEY, {'action': 'delete_worker', 'budget_digest': self.digest(self.resource, self.config.accounts[0])})
        self.assertEqual(len(self.store.intent_history(KEY)), 3)

    def test_policy_digest_binds_identity_action_budget_but_not_display_name(self):
        digest = self.digest(self.resource, self.config.accounts[0])
        self.assertEqual(digest, self.digest(replace(self.resource, name='Rename'), self.config.accounts[0]))
        for resource in (replace(self.resource, key=replace(KEY, resource_id='other')),
                         replace(self.resource, permitted_action='disable_worker_endpoints'),
                         replace(self.resource, budget=replace(self.budget, hard_limit_usd=D('2')))):
            self.assertNotEqual(digest, self.digest(resource, self.config.accounts[0]))

    def test_approval_digest_binds_billing_anchor_and_currency(self):
        account = self.config.accounts[0]
        digest = self.digest(self.resource, account)
        self.assertNotEqual(digest, self.digest(self.resource, replace(account, billing_day=15)))
        self.assertNotEqual(digest, self.digest(self.resource, replace(account, currency='EUR')))
        self.assertEqual(digest, self.digest(self.resource, replace(account, key='display-alias')))


if __name__ == '__main__': unittest.main()
