"""Acceptance tests across policy/state/runtime boundaries."""
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cfguard.models import AccountConfig, Config, Decision, RatedCharge, ResourceKey, Snapshot
from cfguard.policy import evaluate
from cfguard.state import Store, resource_label


class IntegrationTests(unittest.TestCase):
    def test_confirmed_positive_rated_row_alerts_even_incomplete_ledger(self):
        now = datetime(2026,10,26,tzinfo=timezone.utc)
        key = ResourceKey('a','account','billing')
        account = AccountConfig('sandbox','a',Path('/unused'),1,Decimal('10'),'USD',billing_period_verified=True)
        row = RatedCharge(key,'line1',Decimal('0.20'),'incremental','USD',now-timedelta(days=2),now-timedelta(days=1),'v1','good')
        snapshot = Snapshot('a',(),(row,),(),{'rated_usage':'unknown','subscriptions':'complete'},now)
        decisions = evaluate(Config(accounts=(account,)),snapshot,{})
        observed = next(d for d in decisions if d.metric == 'observed_rated_spend')
        self.assertEqual(observed.status, 'warning')
        self.assertIsNone(observed.proposed_action)
        self.assertIsNone(next(d for d in decisions if d.metric == 'rated_cost').value)

    def test_latched_threshold_does_not_send_duplicate_identical_alert(self):
        key = ResourceKey('a','resource','workers','demo')
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            d = Decision(key,'tripped','threshold_crossed',metric='requests')
            store.record_decisions((d,),now)
            store.record_decisions((replace(d,reason_code='latched_threshold_crossed'),),now)
            self.assertEqual(store.pending_count(), 1)

    def test_state_backup_restores_latch(self):
        key = ResourceKey('a','resource','workers','demo')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Store(root/'original') as store:
                store.record_decisions((Decision(key,'tripped','limit',metric='requests'),),datetime.now(timezone.utc))
                store.backup(root/'backup.sqlite3')
            Store.restore(root/'backup.sqlite3', root/'restored')
            with Store(root/'restored') as store:
                self.assertEqual(store.prior()[key].status,'tripped')

    def test_rearm_starts_new_notification_generation_for_all_dimensions(self):
        key = ResourceKey('a','resource','workers','demo')
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            decisions = (Decision(key,'tripped','limit',metric='requests'),
                         Decision(key,'unknown','stale',metric='cpu'))
            store.record_decisions(decisions,now)
            old_ids = {event['id'] for event in store.pending_notifications(now)}
            for event in store.pending_notifications(now):
                store.notification_result(event['id'],True,now)
            store.rearm(key)
            store.record_decisions(decisions,now)
            new_ids = {event['id'] for event in store.pending_notifications(now)}
            self.assertEqual(len(new_ids),2)
            self.assertTrue(new_ids.isdisjoint(old_ids))
            store.record_decisions(decisions,now)
            self.assertEqual(store.pending_count(),2)

    def test_private_resource_attribution_without_exposing_inventory(self):
        key = ResourceKey('private-account','resource','workers','private-worker')
        other = ResourceKey('private-account','resource','workers','other-worker')
        self.assertNotEqual(resource_label(key), resource_label(other))
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            now = datetime.now(timezone.utc)
            store.record_decisions((Decision(key,'tripped','limit',metric='requests'),),now)
            payload = store.pending_notifications(now)[0]['payload']
            self.assertEqual(payload['resource_ref'],resource_label(key))
            self.assertNotIn('private-',str(payload))

    def test_outage_recovery_then_new_outage_notifies_again(self):
        key = ResourceKey('a','account','monitor')
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            outage = Decision(key,'unknown','collection_failed',metric='collection')
            store.record_decisions((outage,),now)
            for event in store.pending_notifications(now):
                store.notification_result(event['id'],True,now)
            store.record_decisions((Decision(key,'healthy','collection_complete',metric='collection'),),now)
            store.record_decisions((outage,),now)
            self.assertEqual(store.pending_count(),1)


if __name__ == '__main__':
    unittest.main()
