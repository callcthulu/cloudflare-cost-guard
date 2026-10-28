from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cfguard.notify import deliver
from cfguard.state import Store


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


class OutboxPriorityTests(unittest.TestCase):
    def test_cutoff_and_warning_bypass_routine_backlog_with_bounded_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'destination'
            destination.write_text('https://alerts.example.invalid/synthetic')
            destination.chmod(0o600)
            with Store(root / 'state') as store:
                for index in range(20):
                    store.enqueue(f'routine-{index:02}', {}, NOW - timedelta(hours=1))
                store.enqueue('warning', {}, NOW, priority=10)
                store.enqueue('cutoff', {}, NOW, priority=100)
                received = []

                def receive(url, body):
                    received.append(json.loads(body)['incident_id'])
                    return 204

                result = deliver(store, {'url_file': destination, 'max_attempts': 2},
                                 NOW, transport=receive)
                self.assertEqual(received, ['cutoff', 'warning'])
                self.assertEqual(result, {'delivered': 2, 'failed': 0, 'pending': 20})
                self.assertEqual(len(store.pending_notifications(NOW, limit=1000)), 10)

    def test_critical_retry_respects_backoff_and_priority_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Store(root) as store:
                store.enqueue('routine', {}, NOW)
                store.enqueue('cutoff', {}, NOW, priority=100)
                store.notification_result('cutoff', False, NOW)
            with Store(root) as store:
                self.assertEqual([row['id'] for row in store.pending_notifications(NOW)], ['routine'])
                self.assertEqual([row['id'] for row in store.pending_notifications(
                    NOW + timedelta(seconds=119))], ['routine'])
                due = store.pending_notifications(NOW + timedelta(seconds=120))
                self.assertEqual([row['id'] for row in due], ['cutoff', 'routine'])
                self.assertEqual(due[0]['priority'], 100)
                self.assertEqual(due[0]['attempts'], 1)

    def test_duplicates_preserve_payload_priority_attempts_and_delivery(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            for event, delivered in (('retry', False), ('delivered', True)):
                store.enqueue(event, {'reason_code': 'original'}, NOW, priority=10)
                store.notification_result(event, delivered, NOW)
                original = dict(store.db.execute('SELECT * FROM outbox WHERE id=?', (event,)).fetchone())
                store.enqueue(event, {'reason_code': 'replacement'}, NOW, priority=100)
                self.assertEqual(dict(store.db.execute('SELECT * FROM outbox WHERE id=?',
                                                       (event,)).fetchone()), original)
            self.assertEqual(store.pending_count(), 1)
            self.assertEqual([row['id'] for row in store.pending_notifications(
                NOW + timedelta(days=1))], ['retry'])

    def test_priority_is_strict_bounded_integer(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            for priority in (True, False, '10', '0); DROP TABLE outbox;--', None, 10.0, -1, 101):
                with self.subTest(priority=priority), self.assertRaises(ValueError):
                    store.enqueue('invalid', {}, NOW, priority=priority)
            self.assertEqual(store.pending_count(), 0)
            store.enqueue('default', {}, NOW)
            self.assertEqual(store.pending_notifications(NOW)[0]['priority'], 0)

    def test_populated_schema_four_migration_preserves_all_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'guard.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO meta VALUES ('schema_version','4'),('operator','preserved');
                    CREATE TABLE outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL,
                        delivered INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE intents (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                    INSERT INTO intents VALUES ('synthetic-key','{"status":"uncertain"}');
                    CREATE TABLE budget_ledger (kind TEXT NOT NULL, key TEXT NOT NULL,
                        period TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL,
                        PRIMARY KEY(kind,key,period,identity));
                    INSERT INTO budget_ledger VALUES ('requests','synthetic-key','2026-10-01',
                        'synthetic-bucket','{"requests":"7"}');
                ''')
                db.executemany('INSERT INTO outbox VALUES (?,?,?,?,?)', (
                    ('b', '{"incident_id":"b"}', 3, NOW.isoformat(), 0),
                    ('a', '{"incident_id":"a"}', 0, NOW.isoformat(), 0),
                    ('delivered', '{}', 2, NOW.isoformat(), 1),
                    ('delayed', '{}', 4, (NOW + timedelta(hours=1)).isoformat(), 0),
                    ('cutoff:pending', '{"reason_code":"original"}', 2, NOW.isoformat(), 0),
                    ('blocked:pending', '{}', 1, NOW.isoformat(), 0),
                    ('cutoff:delivered', '{}', 3, NOW.isoformat(), 1),
                    ('cutoff:delayed', '{}', 4, (NOW + timedelta(hours=1)).isoformat(), 0),
                    ('cutoffish:routine', '{}', 0, NOW.isoformat(), 0),
                ))
                before = list(db.execute('SELECT * FROM outbox ORDER BY id'))
            with Store(root) as store:
                self.assertEqual(store.get_meta('schema_version'), '5')
                self.assertEqual(store.get_meta('operator'), 'preserved')
                after = list(store.db.execute('SELECT id,payload,attempts,next_at,delivered FROM outbox ORDER BY id'))
                self.assertEqual([tuple(row) for row in after], before)
                self.assertEqual([row['id'] for row in store.pending_notifications(NOW)],
                                 ['blocked:pending', 'cutoff:pending', 'a', 'b', 'cutoffish:routine'])
                self.assertEqual(store.pending_count(), 7)
                priorities = dict(store.db.execute('SELECT id,priority FROM outbox'))
                self.assertEqual(priorities, {
                    'a': 0, 'b': 0, 'delivered': 0, 'delayed': 0, 'cutoffish:routine': 0,
                    'blocked:pending': 100, 'cutoff:pending': 100,
                    'cutoff:delivered': 100, 'cutoff:delayed': 100,
                })
                for identity in ('cutoff:pending', 'blocked:pending', 'cutoff:delivered', 'cutoff:delayed'):
                    original = dict(store.db.execute('SELECT * FROM outbox WHERE id=?', (identity,)).fetchone())
                    store.enqueue(identity, {'reason_code': 'replacement'}, NOW)
                    self.assertEqual(dict(store.db.execute('SELECT * FROM outbox WHERE id=?',
                                                           (identity,)).fetchone()), original)
                store.notification_result('cutoff:pending', False, NOW)
                self.assertEqual([row['id'] for row in store.pending_notifications(NOW)],
                                 ['blocked:pending', 'a', 'b', 'cutoffish:routine'])
                self.assertEqual([row['id'] for row in store.pending_notifications(
                    NOW + timedelta(hours=1), limit=3)],
                    ['blocked:pending', 'cutoff:pending', 'cutoff:delayed'])
                self.assertEqual(store.db.execute('SELECT payload FROM intents').fetchone()[0],
                                 '{"status":"uncertain"}')
                self.assertEqual(store.db.execute('SELECT payload FROM budget_ledger').fetchone()[0],
                                 '{"requests":"7"}')
                store.enqueue('cutoff:explicit-routine', {}, NOW)
            with Store(root) as store:
                self.assertEqual(store.db.execute(
                    "SELECT priority FROM outbox WHERE id='cutoff:explicit-routine'").fetchone()[0], 0)

    def test_legacy_backups_restore_and_upgrade_and_future_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in ('1', '2', '3', '4', '6'):
                with self.subTest(version=version):
                    source = root / f'backup-{version}.sqlite3'
                    with closing(sqlite3.connect(source)) as db, db:
                        db.executescript('''
                            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                            CREATE TABLE outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                                attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL,
                                delivered INTEGER NOT NULL DEFAULT 0);
                        ''')
                        db.execute('INSERT INTO meta VALUES (?,?)', ('schema_version', version))
                        db.execute('INSERT INTO outbox VALUES (?,?,?,?,?)',
                                   ('legacy', '{}', 2, NOW.isoformat(), 0))
                    restored = root / f'restored-{version}'
                    if version == '6':
                        with self.assertRaises(ValueError):
                            Store.restore(source, restored)
                        direct = root / 'future'
                        direct.mkdir(mode=0o700)
                        source.replace(direct / 'guard.sqlite3')
                        with self.assertRaises(ValueError):
                            Store(direct)
                    else:
                        Store.restore(source, restored)
                        with Store(restored) as store:
                            event = store.pending_notifications(NOW)[0]
                            self.assertEqual(event['priority'], 0)
                            self.assertEqual(event['attempts'], 2)
                            store.enqueue('critical', {}, NOW, priority=100)
                            self.assertEqual(store.pending_notifications(NOW)[0]['id'], 'critical')


if __name__ == '__main__':
    unittest.main()
