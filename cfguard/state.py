"""Private SQLite state, transactional incidents, and single-instance process lock."""
import contextlib
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .models import ResourceKey, ResourceState


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (datetime, Decimal, Path)):
        return str(value)
    raise TypeError('unsupported state type')


def encode(value):
    return json.dumps(value, default=json_default, sort_keys=True, separators=(',', ':'), allow_nan=False)


def key_id(key):
    return encode(asdict(key))


def resource_label(key):
    return hashlib.sha256(key_id(key).encode()).hexdigest()[:16]


class Locked(RuntimeError):
    pass


def private_directory(path):
    path = Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('unsafe state path')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'posix':
        info = path.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('state directory must be private and service-owned')
    return path


class RunLock:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        path = private_directory(self.path) / 'run.lock'
        if path.is_symlink():
            raise ValueError('unsafe lock path')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.file = os.fdopen(fd, 'r+b')
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                if path.stat().st_size == 0:
                    self.file.write(b'0')
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            self.file = None
            raise Locked('another run holds the lock') from None
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()


class Store:
    SCHEMA_VERSION = '6'

    def __init__(self, path):
        self._notification_targets = None
        path = private_directory(path) / 'guard.sqlite3'
        if path.is_symlink():
            raise ValueError('unsafe database path')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, timeout=2, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        meta_exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        if meta_exists and self.get_meta('schema_version') not in (None, '1', '2', '3', '4', '5', self.SCHEMA_VERSION):
            self.db.close()
            raise ValueError('unsupported database schema')
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resources (key TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots (account TEXT PRIMARY KEY, current TEXT, last_good TEXT);
            CREATE TABLE IF NOT EXISTS observations (key TEXT PRIMARY KEY, current TEXT NOT NULL, last_good TEXT);
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, active INTEGER NOT NULL,
                resource_key TEXT, generation INTEGER NOT NULL DEFAULT 1, dimension TEXT);
            CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0, routing TEXT NOT NULL DEFAULT 'legacy');
            CREATE TABLE IF NOT EXISTS notification_deliveries (
                event_id TEXT NOT NULL, target_id TEXT NOT NULL, config_digest TEXT NOT NULL,
                destination_digest TEXT, status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','delivered','cancelled')),
                attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL,
                last_attempt TEXT, cancelled_at TEXT, reason TEXT,
                PRIMARY KEY(event_id,target_id));
            CREATE TABLE IF NOT EXISTS intents (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS budget_ledger (kind TEXT NOT NULL, key TEXT NOT NULL,
                period TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(kind,key,period,identity));
            CREATE TABLE IF NOT EXISTS intent_history (id INTEGER PRIMARY KEY, key TEXT NOT NULL,
                payload TEXT NOT NULL, archived_at TEXT NOT NULL);
        ''')
        version = self.get_meta('schema_version')
        if version not in (None, '1', '2', '3', '4', '5', self.SCHEMA_VERSION):
            self.db.close()
            raise ValueError('unsupported database schema')
        with self.transaction():
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(incidents)')}
            if 'resource_key' not in columns:
                self.db.execute('ALTER TABLE incidents ADD COLUMN resource_key TEXT')
            if 'generation' not in columns:
                self.db.execute('ALTER TABLE incidents ADD COLUMN generation INTEGER NOT NULL DEFAULT 1')
            if 'dimension' not in columns:
                self.db.execute('ALTER TABLE incidents ADD COLUMN dimension TEXT')
            outbox_columns = {row['name'] for row in self.db.execute('PRAGMA table_info(outbox)')}
            if 'priority' not in outbox_columns:
                self.db.execute('ALTER TABLE outbox ADD COLUMN priority INTEGER NOT NULL DEFAULT 0')
            if 'routing' not in outbox_columns:
                self.db.execute("ALTER TABLE outbox ADD COLUMN routing TEXT NOT NULL DEFAULT 'legacy'")
            if version not in ('5', self.SCHEMA_VERSION):
                self.db.execute("UPDATE outbox SET priority=100 WHERE id GLOB 'cutoff:*' OR id GLOB 'blocked:*'")
            self.set_meta('schema_version', self.SCHEMA_VERSION)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def get_meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def prior(self):
        return {ResourceKey(**json.loads(row['key'])): ResourceState(**json.loads(row['state']))
                for row in self.db.execute('SELECT * FROM resources')}

    def enqueue(self, identity, payload, now, *, priority=0):
        if type(priority) is not int or not 0 <= priority <= 100:
            raise ValueError('notification priority must be an integer from 0 to 100')
        # record_decisions already owns a transaction; standalone enqueues need one too.
        with contextlib.nullcontext() if self.db.in_transaction else self.transaction():
            inserted = self.db.execute('''INSERT OR IGNORE INTO outbox(id,payload,next_at,priority,routing)
                VALUES (?,?,?,?,?)''', (identity, encode(dict(payload, incident_id=identity)),
                                       now.isoformat(), priority,
                                       'multi' if self._notification_targets is not None else 'legacy')).rowcount
            if inserted and self._notification_targets is not None:
                self.db.executemany('''INSERT INTO notification_deliveries
                    (event_id,target_id,config_digest,destination_digest,next_at) VALUES (?,?,?,?,?)''',
                    [(identity, target['id'], target['config_digest'], target['destination_digest'], now.isoformat())
                     for target in self._notification_targets])

    def configure_notification_targets(self, routes, now):
        """Snapshot hashes only; cancel changed routes without replaying historical alerts."""
        if not isinstance(routes, (list, tuple)) or len(routes) > 16:
            raise ValueError('invalid notification target routes')
        targets = {}
        for route in routes:
            if not isinstance(route, dict):
                raise ValueError('invalid notification target route')
            identity, digest, destination = route.get('id'), route.get('config_digest'), route.get('destination_digest')
            if (not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', identity) or
                    identity in targets or not isinstance(digest, str) or
                    not re.fullmatch(r'[0-9a-f]{64}', digest) or
                    destination is not None and (not isinstance(destination, str) or
                                                  not re.fullmatch(r'[0-9a-f]{64}', destination))):
                raise ValueError('invalid notification target route')
            targets[identity] = {'id': identity, 'config_digest': digest, 'destination_digest': destination}
        with self.transaction():
            cancelled = self.db.execute("UPDATE outbox SET routing='legacy_cancelled' WHERE routing='legacy' AND delivered=0").rowcount
            # Work per bounded route set, never materialize the pending backlog in Python.
            removed = 'target_id NOT IN (' + ','.join('?' for _ in targets) + ')' if targets else '1'
            cancelled += self.db.execute(f'''UPDATE notification_deliveries
                SET status='cancelled',cancelled_at=?,reason='target_removed'
                WHERE status='pending' AND {removed}''', (now.isoformat(), *targets)).rowcount
            for target in targets.values():
                cancelled += self.db.execute('''UPDATE notification_deliveries
                    SET status='cancelled',cancelled_at=?,reason='configuration_changed'
                    WHERE status='pending' AND target_id=? AND config_digest!=?''',
                    (now.isoformat(), target['id'], target['config_digest'])).rowcount
                if target['destination_digest'] is not None:
                    cancelled += self.db.execute('''UPDATE notification_deliveries
                        SET status='cancelled',cancelled_at=?,reason='destination_changed'
                        WHERE status='pending' AND target_id=? AND destination_digest IS NOT NULL
                        AND destination_digest!=?''',
                        (now.isoformat(), target['id'], target['destination_digest'])).rowcount
                    self.db.execute('''UPDATE notification_deliveries SET destination_digest=?
                        WHERE status='pending' AND target_id=? AND destination_digest IS NULL''',
                        (target['destination_digest'], target['id']))
        self._notification_targets = tuple(targets.values())
        return cancelled

    def disable_notification_targets(self, now):
        with self.transaction():
            cancelled = self.db.execute('''UPDATE notification_deliveries
                SET status='cancelled',cancelled_at=?,reason='targets_disabled' WHERE status='pending' ''',
                                       (now.isoformat(),)).rowcount
        self._notification_targets = None
        return cancelled

    def pending_deliveries(self, now, limit=5):
        rows = self.db.execute('''SELECT delivery.*,outbox.id,outbox.payload,outbox.priority
            FROM notification_deliveries AS delivery JOIN outbox ON outbox.id=delivery.event_id
            WHERE delivery.status='pending' AND delivery.next_at<=? AND outbox.routing='multi'
            ORDER BY outbox.priority DESC,delivery.next_at,delivery.event_id,delivery.target_id LIMIT ?''',
                               (now.isoformat(), min(max(limit, 0), 10))).fetchall()
        return [dict(row) | {'payload': json.loads(row['payload'])} for row in rows]

    def notification_delivery_result(self, event_id, target_id, success, now):
        with self.transaction():
            row = self.db.execute('''SELECT status,attempts FROM notification_deliveries
                WHERE event_id=? AND target_id=?''', (event_id, target_id)).fetchone()
            if row is None:
                raise ValueError('unknown notification delivery')
            if row['status'] != 'pending':
                return
            attempts = row['attempts'] + 1
            next_at = now + timedelta(seconds=min(3600, 60 * 2 ** min(attempts, 6)))
            self.db.execute('''UPDATE notification_deliveries SET status=?,attempts=?,next_at=?,last_attempt=?
                WHERE event_id=? AND target_id=? AND status='pending' ''',
                            ('delivered' if success else 'pending', attempts, next_at.isoformat(),
                             now.isoformat(), event_id, target_id))
            self.db.execute('''UPDATE outbox SET delivered=1 WHERE id=? AND routing='multi'
                AND NOT EXISTS (SELECT 1 FROM notification_deliveries WHERE event_id=? AND status!='delivered')''',
                            (event_id, event_id))

    def delivery_summary(self):
        counts = {target['id']: {'pending': 0, 'delivered': 0, 'cancelled': 0}
                  for target in self._notification_targets or ()}
        for row in self.db.execute('''SELECT target_id,status,COUNT(*) AS count FROM notification_deliveries
            GROUP BY target_id,status'''):
            counts.setdefault(row['target_id'], {'pending': 0, 'delivered': 0, 'cancelled': 0})[row['status']] = row['count']
        return {'targets': [{'target_ref': hashlib.sha256(identity.encode()).hexdigest()[:16], **counts[identity]}
                            for identity in sorted(counts)],
                'legacy_cancelled': self.db.execute("SELECT COUNT(*) FROM outbox WHERE routing='legacy_cancelled'").fetchone()[0]}

    def record_decisions(self, decisions, now):
        with self.transaction():
            prior = self.prior()
            for decision in decisions:
                old = prior.get(decision.key, ResourceState())
                dimensions = dict(old.dimensions)
                dimension = decision.metric or decision.reason_code
                if decision.status == 'healthy' and dimensions.get(dimension) != 'tripped':
                    self.db.execute('UPDATE incidents SET active=0 WHERE resource_key=? AND dimension=?',
                                    (key_id(decision.key), dimension))
                if dimensions.get(dimension) != 'tripped':
                    dimensions[dimension] = decision.status
                status = 'tripped' if old.status == 'tripped' or 'tripped' in dimensions.values() else (
                    'unknown' if 'unknown' in dimensions.values() else (
                        'warning' if 'warning' in dimensions.values() else 'healthy'))
                incident_id = old.incident_id
                notification = old.notification_status
                if decision.status != 'healthy':
                    reason = decision.reason_code.removeprefix('latched_')
                    incident_id = hashlib.sha256((key_id(decision.key) + dimension + reason).encode()).hexdigest()
                    incident = self.db.execute('SELECT active,generation FROM incidents WHERE id=?', (incident_id,)).fetchone()
                    if not incident or not incident[0]:
                        generation = incident['generation'] + 1 if incident else 1
                        self.db.execute('INSERT OR REPLACE INTO incidents(id,active,resource_key,generation,dimension) VALUES (?,1,?,?,?)',
                                        (incident_id, key_id(decision.key), generation, dimension))
                        event_id = incident_id + ':' + str(generation)
                        self.enqueue(event_id, {'incident_id': event_id, 'status': decision.status,
                                     'reason_code': decision.reason_code, 'scope': decision.key.scope,
                                     'resource_ref': resource_label(decision.key),
                                     'metric': decision.metric}, now)
                        notification = 'pending'
                new = ResourceState(status, old.execution_status, notification, dimensions, incident_id)
                self.db.execute('INSERT OR REPLACE INTO resources VALUES (?,?)', (key_id(decision.key), encode(new)))
                prior[decision.key] = new

    def save_snapshot(self, snapshot):
        with self.transaction():
            self._save_snapshot(snapshot)

    def _save_snapshot(self, snapshot):
        payload = encode(snapshot)
        good = bool(snapshot.coverage) and all(value in ('complete', 'supported', 'unsupported')
                                               for value in snapshot.coverage.values())
        self.db.execute('''INSERT INTO snapshots VALUES (?,?,?) ON CONFLICT(account) DO UPDATE SET
            current=excluded.current,last_good=COALESCE(excluded.last_good,snapshots.last_good)''',
                        (snapshot.account_id, payload, payload if good else None))
        for observation in snapshot.observations:
            identity = key_id(observation.key) + ':' + observation.metric
            valid = (observation.value is not None and observation.complete and
                     observation.quality in ('good', 'approximate') and observation.data_through is not None)
            value = encode(observation)
            self.db.execute('''INSERT INTO observations VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET
                current=excluded.current,last_good=COALESCE(excluded.last_good,observations.last_good)''',
                            (identity, value, value if valid else None))

    def pending_notifications(self, now, limit=5):
        rows = self.db.execute("SELECT * FROM outbox WHERE routing='legacy' AND delivered=0 AND next_at<=? ORDER BY priority DESC,next_at,id LIMIT ?",
                               (now.isoformat(), min(max(limit, 0), 10))).fetchall()
        return [dict(row) | {'payload': json.loads(row['payload'])} for row in rows]

    def pending_count(self):
        return self.db.execute("""SELECT (SELECT COUNT(*) FROM outbox WHERE routing='legacy' AND delivered=0)
            + (SELECT COUNT(*) FROM notification_deliveries WHERE status='pending')""").fetchone()[0]

    def notification_result(self, identity, success, now):
        with self.transaction():
            row = self.db.execute('SELECT attempts FROM outbox WHERE id=?', (identity,)).fetchone()
            if not row:
                raise ValueError('unknown outbox event')
            attempts = row[0] + 1
            next_at = now + timedelta(seconds=min(3600, 60 * 2 ** min(attempts, 6)))
            self.db.execute('UPDATE outbox SET attempts=?,next_at=?,delivered=? WHERE id=?',
                            (attempts, next_at.isoformat(), int(success), identity))

    def save_intent(self, key, payload):
        attempt_id = hashlib.sha256((key_id(key) + datetime.now(timezone.utc).isoformat()).encode()).hexdigest()
        record = dict(payload, status='pending', attempt_id=attempt_id)
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO intents VALUES (?,?)', (key_id(key), encode(record)))
            row = self.db.execute('SELECT state FROM resources WHERE key=?', (key_id(key),)).fetchone()
            state = json.loads(row[0]) if row else asdict(ResourceState(status='tripped'))
            state['execution_status'] = 'pending'
            self.db.execute('INSERT OR REPLACE INTO resources VALUES (?,?)', (key_id(key), encode(state)))
        return record

    def intent(self, key):
        row = self.db.execute('SELECT payload FROM intents WHERE key=?', (key_id(key),)).fetchone()
        return json.loads(row[0]) if row else None

    def note_write_rejection(self, key, status):
        """Persist only definite authentication rejection, never a retry instruction."""
        if type(status) is not int or status not in (401, 403):
            raise ValueError('not a definite authentication rejection')
        record = self.intent(key)
        if record is None:
            raise ValueError('missing action intent')
        record['writer_rejection'] = status
        with self.transaction():
            self.db.execute('UPDATE intents SET payload=? WHERE key=?', (encode(record), key_id(key)))

    def finish_intent(self, key, result):
        record = self.intent(key)
        if record is None:
            raise ValueError('missing action intent')
        record.update(status=result.status, result=asdict(result))
        with self.transaction():
            self.db.execute('UPDATE intents SET payload=? WHERE key=?', (encode(record), key_id(key)))
            row = self.db.execute('SELECT state FROM resources WHERE key=?', (key_id(key),)).fetchone()
            state = json.loads(row[0]) if row else asdict(ResourceState(status='tripped'))
            state['execution_status'] = result.status
            self.db.execute('INSERT OR REPLACE INTO resources VALUES (?,?)', (key_id(key), encode(state)))

    def rearm(self, key):
        with self.transaction():
            state = self.prior().get(key, ResourceState())
            intent = self.intent(key)
            if (state.execution_status in ('pending', 'uncertain', 'partial', 'verified_public_cutoff') or
                    intent and intent['status'] in ('pending', 'uncertain', 'partial', 'verified_public_cutoff')):
                raise ValueError('rearm cannot reopen or erase unresolved/completed cutoff; preserve evidence')
            if intent and intent['status'] in ('worker_deleted', 'endpoints_disabled', 'not_applied'):
                self.db.execute('INSERT INTO intent_history(key,payload,archived_at) VALUES (?,?,?)',
                                (key_id(key), encode(intent), datetime.now(timezone.utc).isoformat()))
                self.db.execute('DELETE FROM intents WHERE key=?', (key_id(key),))
            self.db.execute('INSERT OR REPLACE INTO resources VALUES (?,?)', (key_id(key), encode(ResourceState())))
            self.db.execute('UPDATE incidents SET active=0 WHERE resource_key=? OR id=?',
                            (key_id(key), state.incident_id))

    def intent_history(self, key):
        return tuple(json.loads(row['payload']) for row in self.db.execute(
            'SELECT payload FROM intent_history WHERE key=? ORDER BY id', (key_id(key),)))

    def budget_records(self, kind, key, period):
        return {row['identity']: json.loads(row['payload']) for row in self.db.execute(
            'SELECT identity,payload FROM budget_ledger WHERE kind=? AND key=? AND period=?',
            (kind, key_id(key), period.isoformat()))}

    def save_budget_records(self, kind, key, period, records):
        with self.transaction():
            for identity, payload in records.items():
                self.db.execute('INSERT OR REPLACE INTO budget_ledger VALUES (?,?,?,?,?)',
                                (kind, key_id(key), period.isoformat(), identity, encode(payload)))

    def backup(self, destination):
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise ValueError('backup target must be new')
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with contextlib.closing(sqlite3.connect(destination)) as target:
            self.db.backup(target)
        os.chmod(destination, 0o600)

    @classmethod
    def restore(cls, source, directory):
        """Restore into an empty state directory; never overwrite existing state."""
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError('invalid restore source')
        directory = private_directory(directory)
        if any(directory.iterdir()):
            raise ValueError('restore requires an empty state directory')
        with contextlib.closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as backup:
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('corrupt backup')
            version = backup.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if version is None or version[0] not in ('1', '2', '3', '4', '5', cls.SCHEMA_VERSION):
                raise ValueError('unsupported backup schema')
            fd = os.open(directory / 'guard.sqlite3', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with contextlib.closing(sqlite3.connect(directory / 'guard.sqlite3')) as target:
                backup.backup(target)
