"""Private sampler/watcher integration. Never writes upstream or Cloudflare state."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import smtplib
import sqlite3
import ssl
import stat
import subprocess
import tempfile
import threading

LIMIT = 2 * 1024 * 1024
REMOTE_READ = '/usr/bin/head -c 2097153 /var/lib/cloudflare-cost-guard-monitor/observation.json'


def timestamp(value):
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value):
    if not isinstance(value, str): raise ValueError('invalid_timestamp')
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None: raise ValueError('invalid_timestamp')
    return dt.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def absolute(value):
    return isinstance(value, str) and len(value) <= 4096 and '\x00' not in value and (
        PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute())


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('unsafe_path')
    return path


def private_read(path, limit=LIMIT):
    path = safe_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('invalid_file')
    if os.name == 'posix' and (info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o027):
        raise ValueError('unprotected_file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino): raise ValueError('replaced_file')
        data = stream.read(limit + 1)
    if len(data) > limit: raise ValueError('oversized_file')
    return data


def load_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('duplicate_field')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))
    except (RecursionError, UnicodeError):
        raise ValueError('invalid_json') from None


def load_config(path):
    raw = load_json(private_read(path, 65536))
    allowed = {'version', 'guard_database', 'accounts', 'observation_file', 'ssh_profile',
               'state_dir', 'smtp_file', 'policy', 'reminder_seconds', 'expected_account_refs'}
    if not isinstance(raw, dict) or set(raw) - allowed or type(raw.get('version')) is not int or raw['version'] != 1:
        raise ValueError('invalid_configuration')
    for name in ('guard_database', 'observation_file', 'state_dir', 'smtp_file'):
        if name in raw and not absolute(raw[name]): raise ValueError('invalid_path')
    if 'ssh_profile' in raw and (not isinstance(raw['ssh_profile'], str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', raw['ssh_profile'])):
        raise ValueError('invalid_profile')
    if 'ssh_profile' in raw and 'observation_file' in raw: raise ValueError('ambiguous_source')
    refs = raw.get('expected_account_refs', [])
    if not isinstance(refs, list) or len(refs) > 20 or any(
            not isinstance(r, str) or not re.fullmatch('[a-f0-9]{16}', r) for r in refs) or len(set(refs)) != len(refs):
        raise ValueError('invalid_account_baseline')
    reminder = raw.get('reminder_seconds', 86400)
    if type(reminder) is not int or not 3600 <= reminder <= 604800: raise ValueError('invalid_reminder')
    policy = raw.get('policy', {})
    limits = {'max_age_seconds': (60, 86400), 'future_tolerance_seconds': (0, 60),
              'backlog_age_seconds': (60, 86400)}
    if not isinstance(policy, dict) or set(policy) - set(limits): raise ValueError('invalid_policy')
    for name, value in policy.items():
        if type(value) is not int or not limits[name][0] <= value <= limits[name][1]: raise ValueError('invalid_policy')
    accounts = raw.get('accounts', [])
    if not isinstance(accounts, list) or len(accounts) > 20: raise ValueError('invalid_accounts')
    seen = set()
    for account in accounts:
        fields = {'id', 'read_token_file', 'expected_workers', 'expected_zones', 'known_limitations'}
        if not isinstance(account, dict) or set(account) - fields or not fields - {'known_limitations'} <= set(account):
            raise ValueError('invalid_account')
        identity = account['id']
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity) or identity in seen:
            raise ValueError('invalid_identity')
        seen.add(identity)
        if not absolute(account['read_token_file']): raise ValueError('invalid_token_path')
        for name, pattern in (('expected_workers', r'[A-Za-z0-9_-]{1,128}'), ('expected_zones', r'[a-f0-9]{32}')):
            values = account[name]
            if not isinstance(values, list) or len(values) > 10000 or any(
                    not isinstance(v, str) or not re.fullmatch(pattern, v) for v in values) or len(set(values)) != len(values):
                raise ValueError('invalid_baseline')
        known = account.get('known_limitations', {})
        # Exact source/status acknowledgements; never accept a wildcard suppression.
        if not isinstance(known, dict) or len(known) > 100 or any(
                not re.fullmatch(r'(billing_account_coverage|billing_info|billing_period|rated_usage|rated_rows|rated_freshness|workers.requests|subscriptions.account|subscriptions.zone:[a-f0-9]{16})', k)
                or not isinstance(v, str) or v not in {'unavailable', 'unsupported', 'approximate', 'unverified'}
                for k, v in known.items()): raise ValueError('invalid_limitation')
    return raw


def private_directory(path):
    path = safe_path(path)
    # Refuse operational artifacts inside a Git checkout, even if ignored.
    if any((p / '.git').exists() for p in (path, *path.parents)): raise ValueError('state_inside_git')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'posix':
        info = path.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077: raise ValueError('unprotected_directory')
    return path


def atomic_write(path, data):
    path = safe_path(path)
    parent = private_directory(path.parent)
    if path.exists() and not path.is_file(): raise ValueError('invalid_output')
    fd, temporary = tempfile.mkstemp(prefix='.observation-', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def sample(config, output, *, now=None, collector=None):
    if collector is None:
        from .sources import collect
        collector = collect
    observation = collector(config, now or datetime.now(timezone.utc))
    data = canonical(observation).encode()
    if len(data) > LIMIT: raise ValueError('oversized_observation')
    atomic_write(output, data)
    return {'exported': True, 'version': 1}


def read_process(argv, timeout=20):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, shell=False)
    received = []
    def read():
        try: received.append(process.stdout.read(LIMIT + 1))
        except OSError: received.append(b'')
    reader = threading.Thread(target=read, daemon=True); reader.start()
    try:
        reader.join(timeout)
        if reader.is_alive(): raise ValueError('observation_timeout')
        code = process.wait(timeout=2)
        if code != 0 or not received or len(received[0]) > LIMIT: raise ValueError('observation_failed')
        return received[0]
    finally:
        if process.poll() is None: process.kill()
        process.wait(timeout=2)
        reader.join(2)
        process.stdout.close()


def read_observation(config):
    try:
        if 'ssh_profile' in config:
            profile = config['ssh_profile']
            if not isinstance(profile, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', profile):
                return None
            data = read_process(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                 '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5',
                                 '-o', 'ServerAliveCountMax=2', profile, REMOTE_READ])
        else:
            data = private_read(config['observation_file'])
        observation = load_json(data)
        return observation if isinstance(observation, dict) else None
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return None


def load_smtp(path):
    settings = load_json(private_read(path, 65536))
    required = {'host', 'port', 'tls', 'username', 'password', 'from', 'to'}
    if not isinstance(settings, dict) or set(settings) != required: raise ValueError('invalid_smtp')
    if (not isinstance(settings['host'], str) or len(settings['host']) > 253 or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', settings['host']) or
            type(settings['port']) is not int or not 1 <= settings['port'] <= 65535 or
            settings['tls'] not in {'ssl', 'starttls'}): raise ValueError('invalid_smtp')
    for field in ('username', 'password', 'from', 'to'):
        value = settings[field]
        if not isinstance(value, str) or not value or len(value) > 4096 or '\x00' in value:
            raise ValueError('invalid_smtp')
    for field in ('from', 'to'):
        value = settings[field]
        if '\r' in value or '\n' in value or len(value) > 254 or parseaddr(value)[1] != value or value.count('@') != 1:
            raise ValueError('invalid_smtp_address')
    return settings


def recipient_digest(settings):
    return hashlib.sha256(canonical({k: v for k, v in settings.items() if k != 'password'}).encode()).hexdigest()


def send_email(settings, event):
    message = EmailMessage()
    message['Subject'] = 'Cloudflare monitor: ' + event['kind']
    message['From'], message['To'] = settings['from'], settings['to']
    message.set_content('Monitoring evidence, not a spending cap.\n\n' + json.dumps(event, sort_keys=True, indent=2))
    context = ssl.create_default_context()
    client = None
    try:
        if settings['tls'] == 'ssl':
            client = smtplib.SMTP_SSL(settings['host'], settings['port'], timeout=10, context=context)
        elif settings['tls'] == 'starttls':
            client = smtplib.SMTP(settings['host'], settings['port'], timeout=10)
            client.ehlo(); client.starttls(context=context); client.ehlo()
        else: raise ValueError('tls_required')
        client.login(settings['username'], settings['password'])
        client.send_message(message)
    finally:
        if client is not None: client.close()


class Busy(RuntimeError):
    pass


class Lock:
    def __init__(self, directory): self.directory = directory
    def __enter__(self):
        directory = private_directory(self.directory)
        path = safe_path(directory / 'watch.lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.file = os.fdopen(fd, 'r+b')
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                if path.stat().st_size == 0: self.file.write(b'0'); self.file.flush()
                self.file.seek(0); msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close(); raise Busy('overlapping_watch') from None
        return self
    def __exit__(self, *args): self.file.close()


class Store:
    def __init__(self, directory):
        path = safe_path(Path(directory) / 'watch.sqlite3')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600); os.close(fd)
        self.db = sqlite3.connect(path, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS incidents (key TEXT PRIMARY KEY, scope TEXT NOT NULL,
                payload TEXT NOT NULL, active INTEGER NOT NULL, emitted_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, issue_key TEXT NOT NULL, payload TEXT NOT NULL,
                target TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL, priority INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS coverage_history (scope TEXT PRIMARY KEY);
        ''')
    def close(self): self.db.close()
    def pending_since(self, observation, now, max_age=900):
        """Track backlog age independently of upstream delivery retry timestamps."""
        if not isinstance(observation, dict) or not isinstance(observation.get('guard'), dict): return observation
        observation = dict(observation)
        guard = observation['guard'] = dict(observation['guard'])
        try:
            observed = parse_time(observation['observed_at'])
            if not 0 <= (now-observed).total_seconds() <= max_age or guard.get('status') != 'ok': return observation
            count = guard.get('pending_notifications')
            if type(count) is not int or count < 0: return observation
            if count == 0:
                self.db.execute("DELETE FROM meta WHERE key='pending_since'")
            else:
                row = self.db.execute("SELECT value FROM meta WHERE key='pending_since'").fetchone()
                since = parse_time(row['value']) if row else now
                if since > now: since = now
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('pending_since',?)", (timestamp(since),))
                try: prior = parse_time(guard.get('oldest_pending_at'))
                except (ValueError, TypeError): prior = now
                guard['oldest_pending_at'] = timestamp(min(prior, since))
            self.db.commit()
        except (ValueError, KeyError, TypeError): pass
        return observation

    def reconcile(self, assessment, now, target, reminder):
        queued = 0
        def enqueue(kind, issue):
            nonlocal queued
            reason = issue['reason']
            priority = 100 if reason in {'positive_subscription', 'unexpected_subscription', 'inventory_added',
                                         'account_set_changed'} else 80 if reason in {
                'observation_unknown', 'guard_stale', 'guard_unknown', 'notification_backlog'} else 10
            self.db.execute('INSERT INTO outbox(issue_key,payload,target,next_at,priority) VALUES (?,?,?,?,?)',
                            (issue['key'], canonical({'kind': kind, 'issue': issue}), target, timestamp(now), priority))
            queued += 1
        with self.db:
            cancelled = self.db.execute("UPDATE outbox SET status='cancelled' WHERE status='pending' AND target!=?", (target,)).rowcount
            # Only policy-verified scopes establish history: stale snapshots cannot do so.
            self.db.executemany('INSERT OR IGNORE INTO coverage_history VALUES (?)',
                ((scope,) for scope in assessment['verified_scopes'] if ':coverage:' in scope))
            for limitation in assessment['limitations']:
                scope, ref = limitation['scope'], limitation['resource_ref']
                if self.db.execute('SELECT 1 FROM coverage_history WHERE scope=?', (scope,)).fetchone():
                    assessment['issues'].append({'key': 'coverage_lost:' + scope + ':' + ref,
                        'scope': scope, 'reason': 'coverage_lost', 'resource_ref': ref,
                        'level': 'warning', 'details': {'status': limitation['status']}})
            prior = {row['key']: row for row in self.db.execute('SELECT * FROM incidents WHERE active=1')}
            keys = set()
            for issue in assessment['issues']:
                key = issue['key']; keys.add(key)
                old = prior.get(key)
                if not old:
                    # A recurring incident invalidates its unsent recovery, including retries.
                    cancelled += self.db.execute("UPDATE outbox SET status='cancelled' WHERE issue_key=? AND status='pending'", (key,)).rowcount
                changed = bool(old and 'amount' in issue['details'] and
                    Decimal(issue['details']['amount']) != Decimal(load_json(old['payload'])['details']['amount']))
                due = bool(old and (now-parse_time(old['emitted_at'])).total_seconds() >= reminder)
                waiting = self.db.execute("SELECT 1 FROM outbox WHERE issue_key=? AND status='pending' LIMIT 1", (key,)).fetchone()
                if waiting and not changed: due = False
                if not old or due or changed:
                    if changed:
                        # Preserve retry backoff when a pending amount alert is updated.
                        if waiting:
                            self.db.execute("UPDATE outbox SET payload=? WHERE issue_key=? AND status='pending'",
                                (canonical({'kind': 'updated', 'issue': issue}), key))
                            self.db.execute('UPDATE incidents SET payload=? WHERE key=?', (canonical(issue), key))
                            continue
                    enqueue('opened' if not old else 'updated' if changed else 'reminder', issue)
                    self.db.execute('INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?)',
                                    (key, issue['scope'], canonical(issue), 1, timestamp(now)))
            for key, old in prior.items():
                if key not in keys and old['scope'] in assessment['verified_scopes']:
                    cancelled += self.db.execute("UPDATE outbox SET status='cancelled' WHERE issue_key=? AND status='pending'", (key,)).rowcount
                    enqueue('recovered', load_json(old['payload']))
                    self.db.execute('UPDATE incidents SET active=0 WHERE key=?', (key,))
        return queued, cancelled

    def deliver(self, now, target, settings, sender):
        delivered = failed = 0
        rows = self.db.execute("SELECT * FROM outbox WHERE status='pending' AND target=? AND next_at<=? ORDER BY priority DESC,id LIMIT 3",
                               (target, timestamp(now))).fetchall()
        for row in rows:
            try:
                sender(settings, load_json(row['payload']))
                success = True
            except (OSError, ValueError, smtplib.SMTPException): success = False
            attempts = row['attempts'] + 1
            next_at = now + timedelta(seconds=min(3600, 60 * 2 ** min(attempts-1, 6)))
            with self.db:
                self.db.execute('UPDATE outbox SET status=?,attempts=?,next_at=? WHERE id=?',
                    ('delivered' if success else 'pending', attempts, timestamp(next_at), row['id']))
            delivered += success; failed += not success
        return delivered, failed


def watch(config, *, now=None, apply=False, send=False, loader=None, sender=None):
    from .policy import assess
    if send and not apply: raise ValueError('send_requires_apply')
    now = now or datetime.now(timezone.utc)
    observation = (loader or read_observation)(config)
    def assessment_for(value):
        assessment = assess(value, now, config.get('policy'))
        expected = set(config.get('expected_account_refs', []))
        # Only a fresh structurally accepted observation can verify the account set.
        if expected and 'observation' in assessment['verified_scopes']:
            actual = {a.get('account_ref') for a in value['accounts'] if isinstance(a, dict)
                      and isinstance(a.get('account_ref'), str)}
            if actual != expected:
                assessment['issues'].append({'key': 'account_set_changed', 'scope': 'account_set',
                    'reason': 'account_set_changed', 'resource_ref': 'monitor', 'level': 'warning',
                    'details': {'missing': len(expected-actual), 'unexpected': len(actual-expected)}})
            else: assessment['verified_scopes'].append('account_set')
        return assessment
    if not apply:
        return {'preview': True, **assessment_for(observation), 'queued': 0, 'delivered': 0}
    settings = load_smtp(config['smtp_file'])
    target = recipient_digest(settings)
    with Lock(Path(config['state_dir'])):
        store = Store(config['state_dir'])
        try:
            observation = store.pending_since(observation, now, config.get('policy', {}).get('max_age_seconds', 900))
            assessment = assessment_for(observation)
            queued, cancelled = store.reconcile(assessment, now, target, config.get('reminder_seconds', 86400))
            delivered, failed = store.deliver(now, target, settings, sender or send_email) if send else (0, 0)
            pending = store.db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0]
            active = store.db.execute('SELECT COUNT(*) FROM incidents WHERE active=1').fetchone()[0]
            return {'preview': False, **assessment, 'queued': queued, 'cancelled': cancelled,
                    'delivered': delivered, 'failed': failed, 'pending': pending, 'active_incidents': active}
        finally: store.close()
