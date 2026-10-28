"""Synthetic persistence boundaries for independently routed notifications."""
import hashlib
from contextlib import closing
import sqlite3
import tempfile
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cfguard.state import Store


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def route(identity='alpha', config='a', destination='b'):
    return {'id': identity, 'config_digest': config * 64,
            'destination_digest': destination * 64 if destination else None}


class DeliveryStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'state')
        self.addCleanup(lambda: self.store.db.close())

    def children(self):
        return [dict(row) for row in self.store.db.execute(
            'SELECT * FROM notification_deliveries ORDER BY event_id,target_id')]

    def test_each_target_keeps_independent_success_failure_and_backoff_after_restart(self):
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        self.store.enqueue('incident', {'reason_code': 'synthetic'}, NOW, priority=100)
        self.assertEqual(self.store.pending_notifications(NOW), [])
        self.assertEqual(self.store.pending_count(), 2)
        rows = self.store.pending_deliveries(NOW)
        self.assertEqual([(row['id'], row['target_id']) for row in rows],
                         [('incident', 'alpha'), ('incident', 'beta')])
        self.assertEqual(rows[0]['payload'], {'incident_id': 'incident', 'reason_code': 'synthetic'})
        self.assertEqual(rows[0]['priority'], 100)
        self.store.notification_delivery_result('incident', 'alpha', True, NOW)
        self.store.notification_delivery_result('incident', 'beta', False, NOW)
        self.assertEqual(self.store.pending_count(), 1)
        self.assertEqual(self.store.pending_deliveries(NOW + timedelta(seconds=119)), [])
        self.assertEqual(self.store.db.execute('SELECT delivered FROM outbox').fetchone()[0], 0)
        self.store.db.close()
        self.store = Store(self.root / 'state')
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        rows = self.store.pending_deliveries(NOW + timedelta(seconds=120))
        self.assertEqual([(row['target_id'], row['attempts']) for row in rows], [('beta', 1)])
        self.store.notification_delivery_result('incident', 'beta', True, NOW + timedelta(seconds=120))
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(self.store.db.execute('SELECT delivered FROM outbox').fetchone()[0], 1)

    def test_duplicate_does_not_fan_out_reset_or_resend_success(self):
        self.store.configure_notification_targets([route()], NOW)
        self.store.enqueue('incident', {}, NOW)
        self.store.notification_delivery_result('incident', 'alpha', True, NOW)
        original = self.children()
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        self.store.enqueue('incident', {'replacement': True}, NOW, priority=100)
        self.store.notification_delivery_result('incident', 'alpha', False, NOW)
        self.assertEqual(self.children(), original)
        self.assertEqual(self.store.pending_deliveries(NOW + timedelta(days=1)), [])
        self.store.enqueue('new', {}, NOW)
        self.assertEqual([row['target_id'] for row in self.store.pending_deliveries(NOW)], ['alpha', 'beta'])

    def test_removal_and_configuration_change_cancel_without_reopening_or_replaying(self):
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        self.store.enqueue('incident', {}, NOW)
        self.store.notification_delivery_result('incident', 'alpha', False, NOW)
        self.assertEqual(self.store.configure_notification_targets([route(config='c')], NOW), 2)
        children = self.children()
        self.assertEqual([row['status'] for row in children], ['cancelled', 'cancelled'])
        self.assertEqual(children[0]['attempts'], 1)
        self.assertEqual(children[0]['next_at'], (NOW + timedelta(seconds=120)).isoformat())
        self.assertEqual(children[0]['cancelled_at'], NOW.isoformat())
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(self.store.db.execute('SELECT delivered FROM outbox').fetchone()[0], 0)
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        self.store.enqueue('incident', {}, NOW)
        self.assertEqual(self.children(), children)
        self.store.enqueue('new', {}, NOW)
        self.assertEqual(len(self.store.pending_deliveries(NOW)), 2)

    def test_destination_first_resolution_binds_missing_secret_preserves_binding_and_change_cancels(self):
        self.store.configure_notification_targets([route(destination=None)], NOW)
        self.store.enqueue('incident', {}, NOW)
        self.store.notification_delivery_result('incident', 'alpha', False, NOW)
        self.store.configure_notification_targets([route(destination='c')], NOW)
        row = self.children()[0]
        self.assertEqual(row['destination_digest'], 'c' * 64)
        self.assertEqual((row['status'], row['attempts']), ('pending', 1))
        self.store.configure_notification_targets([route(destination=None)], NOW)
        self.assertEqual(self.children()[0], row)
        self.assertEqual(self.store.configure_notification_targets([route(destination='d')], NOW), 1)
        self.assertEqual(self.children()[0]['status'], 'cancelled')
        self.store.enqueue('new', {}, NOW)
        self.assertEqual(self.store.pending_deliveries(NOW)[0]['destination_digest'], 'd' * 64)

    def test_opt_in_cancels_only_undelivered_legacy_and_disable_keeps_history(self):
        self.store.enqueue('legacy', {'reason_code': 'original'}, NOW, priority=10)
        self.store.enqueue('sent', {}, NOW)
        self.store.notification_result('legacy', False, NOW)
        self.store.notification_result('sent', True, NOW)
        original = dict(self.store.db.execute("SELECT * FROM outbox WHERE id='legacy'").fetchone())
        self.assertEqual(self.store.configure_notification_targets([route()], NOW), 1)
        actual = dict(self.store.db.execute("SELECT * FROM outbox WHERE id='legacy'").fetchone())
        self.assertEqual(actual, original | {'routing': 'legacy_cancelled'})
        self.assertEqual(self.store.configure_notification_targets([route()], NOW), 0)
        self.store.enqueue('new', {}, NOW)
        self.assertEqual(self.store.disable_notification_targets(NOW), 1)
        self.assertEqual(self.store.pending_count(), 0)
        self.store.enqueue('legacy-again', {}, NOW)
        self.assertEqual([row['id'] for row in self.store.pending_notifications(NOW)], ['legacy-again'])
        self.store.configure_notification_targets([route()], NOW)
        self.assertEqual(self.store.pending_deliveries(NOW), [])
        summary = self.store.delivery_summary()
        self.assertEqual(summary, {'targets': [{'target_ref': hashlib.sha256(b'alpha').hexdigest()[:16],
                                               'pending': 0, 'delivered': 0, 'cancelled': 1}],
                                   'legacy_cancelled': 2})

    def test_pending_children_are_bounded_prioritized_and_transactional(self):
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        for index in range(12):
            self.store.enqueue(f'routine-{index:02}', {}, NOW - timedelta(hours=1))
        self.store.enqueue('critical', {}, NOW, priority=100)
        self.assertEqual([(row['id'], row['target_id']) for row in self.store.pending_deliveries(NOW, 2)],
                         [('critical', 'alpha'), ('critical', 'beta')])
        self.store.notification_delivery_result('critical', 'alpha', False, NOW)
        self.assertEqual(self.store.pending_deliveries(NOW)[0]['target_id'], 'beta')
        self.assertEqual(len(self.store.pending_deliveries(NOW, 100)), 10)
        self.assertEqual(self.store.pending_deliveries(NOW, -1), [])
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.enqueue('rolled-back', {}, NOW)
                raise RuntimeError('synthetic crash')
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM outbox WHERE id='rolled-back'").fetchone())
        self.assertEqual(self.store.pending_count(), 26)

    def test_validation_rejects_invalid_routes_without_changing_current_routing(self):
        self.store.configure_notification_targets([route()], NOW)
        invalid = ([route('Bad')], [route('a' * 65)], [route('bad.id')], [route(), route()],
                   [route(str(index)) for index in range(17)], [route(config='g')],
                   [route() | {'destination_digest': 'secret-url'}], [route() | {'id': None}])
        for routes in invalid:
            with self.subTest(routes=routes), self.assertRaises(ValueError):
                self.store.configure_notification_targets(routes, NOW)
        self.store.enqueue('incident', {}, NOW)
        self.assertEqual([row['target_id'] for row in self.store.pending_deliveries(NOW)], ['alpha'])

    def test_reconfigure_large_backlog_bounds_python_memory_and_preserves_retry_audit(self):
        targets = ('removed', 'alpha', 'beta', 'gamma', 'delta')
        next_at = (NOW + timedelta(seconds=240)).isoformat()
        previous = (NOW - timedelta(minutes=1)).isoformat()
        with self.store.transaction():
            self.store.db.executemany('''INSERT INTO outbox(id,payload,next_at,routing)
                VALUES (?,'{}',?,'multi')''', ((f'bulk-{index:05}', next_at) for index in range(10000)))
            self.store.db.executemany('''INSERT INTO notification_deliveries
                (event_id,target_id,config_digest,destination_digest,attempts,next_at,last_attempt)
                VALUES (?,?,?,?,2,?,?)''',
                ((f'bulk-{index:05}', targets[index // 2000],
                  ('c' if index // 2000 == 1 else 'a') * 64,
                  None if index // 2000 == 3 else 'c' * 64, next_at, previous)
                 for index in range(10000)))
        routes = [route(), route('beta'), route('gamma'), route('delta', destination=None)]
        tracemalloc.start()
        try:
            cancelled = self.store.configure_notification_targets(routes, NOW)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024, f'reconfiguration allocated {peak} bytes for the backlog')
        self.assertEqual(cancelled, 6000)
        self.assertEqual(self.store.pending_count(), 4000)
        counts = {tuple(row[:3]): row[3] for row in self.store.db.execute('''
            SELECT target_id,status,reason,COUNT(*) FROM notification_deliveries
            GROUP BY target_id,status,reason''')}
        self.assertEqual(counts, {
            ('removed', 'cancelled', 'target_removed'): 2000,
            ('alpha', 'cancelled', 'configuration_changed'): 2000,
            ('beta', 'cancelled', 'destination_changed'): 2000,
            ('gamma', 'pending', None): 2000,
            ('delta', 'pending', None): 2000})
        self.assertEqual(self.store.db.execute('''SELECT COUNT(*) FROM notification_deliveries
            WHERE attempts=2 AND next_at=? AND last_attempt=?''', (next_at, previous)).fetchone()[0], 10000)
        self.assertEqual(self.store.db.execute('''SELECT COUNT(*) FROM notification_deliveries
            WHERE status='cancelled' AND cancelled_at=?''', (NOW.isoformat(),)).fetchone()[0], 6000)
        bindings = dict(self.store.db.execute('''SELECT target_id,MIN(destination_digest)
            FROM notification_deliveries WHERE status='pending' GROUP BY target_id'''))
        self.assertEqual(bindings, {'gamma': 'b' * 64, 'delta': 'c' * 64})
        self.assertEqual(self.store.configure_notification_targets(routes, NOW), 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM notification_deliveries').fetchone()[0], 10000)

    def test_populated_schema_five_migration_preserves_payload_delivery_priority_and_retry(self):
        directory = self.root / 'old'
        directory.mkdir(mode=0o700)
        with closing(sqlite3.connect(directory / 'guard.sqlite3')) as db, db:
            db.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO meta VALUES ('schema_version','5');
                CREATE TABLE outbox (id TEXT PRIMARY KEY,payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,next_at TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0,priority INTEGER NOT NULL DEFAULT 0);
            ''')
            db.executemany('INSERT INTO outbox VALUES (?,?,?,?,?,?)', [
                ('cutoff:explicit-routine', '{"original":true}', 3, NOW.isoformat(), 0, 0),
                ('warning', '{}', 1, NOW.isoformat(), 0, 10),
                ('sent', '{}', 2, NOW.isoformat(), 1, 100)])
            before = list(db.execute('SELECT * FROM outbox ORDER BY id'))
        with Store(directory) as store:
            self.assertEqual(store.get_meta('schema_version'), '6')
            after = list(store.db.execute('SELECT id,payload,attempts,next_at,delivered,priority FROM outbox ORDER BY id'))
            self.assertEqual([tuple(row) for row in after], before)
            self.assertEqual([row['id'] for row in store.pending_notifications(NOW)],
                             ['warning', 'cutoff:explicit-routine'])
            self.assertEqual(store.configure_notification_targets([route()], NOW), 2)
            self.assertEqual(store.pending_count(), 0)
            self.assertEqual(store.pending_deliveries(NOW), [])

    def test_current_backup_preserves_children_and_future_seven_is_refused(self):
        self.store.configure_notification_targets([route(), route('beta')], NOW)
        self.store.enqueue('incident', {}, NOW)
        self.store.notification_delivery_result('incident', 'alpha', True, NOW)
        self.store.notification_delivery_result('incident', 'beta', False, NOW)
        source = self.root / 'backup.sqlite3'
        self.store.backup(source)
        Store.restore(source, self.root / 'restore')
        with Store(self.root / 'restore') as store:
            self.assertEqual(store.pending_count(), 1)
            self.assertEqual(store.pending_deliveries(NOW), [])
            self.assertEqual(store.pending_deliveries(NOW + timedelta(seconds=120))[0]['target_id'], 'beta')
        with closing(sqlite3.connect(source)) as db, db:
            db.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
        with self.assertRaises(ValueError):
            Store.restore(source, self.root / 'future-restore')
        future = self.root / 'future-open'
        future.mkdir(mode=0o700)
        source.replace(future / 'guard.sqlite3')
        with self.assertRaises(ValueError):
            Store(future)


if __name__ == '__main__':
    unittest.main()
