import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cfguard.models import Decision, ResourceKey
from cfguard.state import Store, RunLock, Locked


class StateTests(unittest.TestCase):
    def test_latch_outbox_restart_and_rearm(self):
        key = ResourceKey('a', 'resource', 'workers', 'worker')
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory)) as store:
                store.record_decisions((Decision(key, 'tripped', 'limit', metric='requests'),), now)
                store.record_decisions((Decision(key, 'tripped', 'limit', metric='requests'),), now)
                self.assertEqual(len(store.pending_notifications(now)), 1)
                event = store.pending_notifications(now)[0]
                store.notification_result(event['id'], False, now)
                self.assertEqual(store.pending_count(), 1)
                self.assertEqual(len(store.pending_notifications(now)), 0)
                store.save_intent(key, {'action': 'disable_worker_endpoints'})
                self.assertEqual(store.prior()[key].execution_status, 'pending')
            with Store(Path(directory)) as store:
                self.assertEqual(store.prior()[key].status, 'tripped')
                self.assertEqual(store.intent(key)['status'], 'pending')
                store.record_decisions((Decision(key, 'unknown', 'stale', metric='requests'),), now)
                self.assertEqual(store.prior()[key].status, 'tripped')
                with self.assertRaises(ValueError):
                    store.rearm(key)
                store.db.execute('DELETE FROM intents')
                store.db.execute('DELETE FROM resources')
                store.rearm(key)
                self.assertEqual(store.prior()[key].status, 'healthy')

    def test_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            with self.assertRaises(RuntimeError):
                with store.transaction():
                    store.db.execute("INSERT INTO meta VALUES ('rollback','bad')")
                    raise RuntimeError('crash')
            self.assertIsNone(store.get_meta('rollback'))

    def test_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            with RunLock(Path(directory)):
                with self.assertRaises(Locked):
                    with RunLock(Path(directory)):
                        pass
            with RunLock(Path(directory)):
                pass

    def test_failed_delivery_never_delivered_and_bounded_due(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            for i in range(10):
                store.enqueue('event' + str(i), {'reason_code': 'unknown'}, now)
            self.assertEqual(len(store.pending_notifications(now, limit=3)), 3)
            event = store.pending_notifications(now)[0]
            self.assertEqual(event['payload']['incident_id'],event['id'])
            store.notification_result(event['id'], False, now)
            self.assertEqual(store.pending_count(), 10)
            store.notification_result(event['id'], True, now)
            self.assertEqual(store.pending_count(), 9)


if __name__ == '__main__':
    unittest.main()
