"""Private SQLite state, transactional incidents, and single-instance process lock."""
import contextlib
import hashlib
import json
import os
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
    SCHEMA_VERSION = '4'

    def __init__(self, path):
        path = private_directory(path) / 'guard.sqlite3'
        if path.is_symlink():
            raise ValueError('unsafe database path')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, timeout=2, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        meta_exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        if meta_exists and self.get_meta('schema_version') not in (None, '1', '2', '3', self.SCHEMA_VERSION):
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
                attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS intents (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS budget_ledger (kind TEXT NOT NULL, key TEXT NOT NULL,
                period TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(kind,key,period,identity));
            CREATE TABLE IF NOT EXISTS intent_history (id INTEGER PRIMARY KEY, key TEXT NOT NULL,
                payload TEXT NOT NULL, archived_at TEXT NOT NULL);
        ''')
        version = self.get_meta('schema_version')
        if version not in (None, '1', '2', '3', self.SCHEMA_VERSION):
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

    def enqueue(self, identity, payload, now):
        self.db.execute('INSERT OR IGNORE INTO outbox(id,payload,next_at) VALUES (?,?,?)',
                        (identity, encode(dict(payload, incident_id=identity)), now.isoformat()))

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
        rows = self.db.execute('SELECT * FROM outbox WHERE delivered=0 AND next_at<=? ORDER BY next_at,id LIMIT ?',
                               (now.isoformat(), min(max(limit, 0), 10))).fetchall()
        return [dict(row) | {'payload': json.loads(row['payload'])} for row in rows]

    def pending_count(self):
        return self.db.execute('SELECT COUNT(*) FROM outbox WHERE delivered=0').fetchone()[0]

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
            if version is None or version[0] not in ('1', '2', '3', cls.SCHEMA_VERSION):
                raise ValueError('unsupported backup schema')
            fd = os.open(directory / 'guard.sqlite3', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with contextlib.closing(sqlite3.connect(directory / 'guard.sqlite3')) as target:
                backup.backup(target)
