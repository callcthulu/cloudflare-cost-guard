"""Bounded read-only adapters. No upstream imports or provider mutation transport."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


MAX_JSON = 1024 * 1024
MAX_ROWS = 4096
MAX_ACCOUNTS = 64
MAX_PAGES = 32
MAX_REQUESTS = 64
SOURCE_NAMES = frozenset(('subscriptions.account', 'workers.requests', 'billing_info',
    'billing_account_coverage', 'billing_period', 'rated_usage', 'rated_rows', 'rated_freshness'))
STATES = frozenset(('complete', 'approximate', 'unavailable', 'unknown', 'stale',
                    'unsupported', 'unverified', 'covered', 'parsed'))


class SourceError(ValueError):
    """Fixed public error: never retain a provider message, path, ID or credential."""
    def __init__(self, *ignored):
        super().__init__('source_unavailable')


def reference(account_id, product, identity=''):
    return hashlib.sha256(json.dumps([account_id, product, identity],
        ensure_ascii=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:16]


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 48:
        raise SourceError()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise SourceError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise SourceError() from None


def _identifier(value, *, worker=False):
    pattern = r'[A-Za-z0-9_-]{1,128}' if worker else r'[a-fA-F0-9]{32}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise SourceError()
    return value


def _json(value):
    if not isinstance(value, (str, bytes)) or len(value) > MAX_JSON:
        raise SourceError()
    def pairs(rows):
        result = {}
        for key, item in rows:
            if key in result:
                raise SourceError()
            result[key] = item
        return result
    try:
        return json.loads(value, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(SourceError()))
    except (ValueError, RecursionError, UnicodeError):
        raise SourceError() from None


def _token_permissions(info):
    if os.name != 'posix':
        return
    owner = os.geteuid()
    if info.st_uid not in (0, owner) or info.st_mode & 0o027:
        raise SourceError()
    groups = set(os.getgroups()) | {os.getegid()}
    if info.st_uid != owner and owner != 0 and info.st_mode & 0o040 and info.st_gid not in groups:
        raise SourceError()


def _read_token(path):
    """Root-owned 0640/service-group or service-owned 0600 are supported.

    Ancestors must resist non-admin replacement; a root-owned sticky directory is
    safe for an owner's private child. Windows ACL verification remains a live gate.
    """
    try:
        path = Path(path)
        if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise SourceError()
        checked = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(checked.st_mode):
            raise SourceError()
        if os.name == 'posix':
            for parent in path.parents:
                info = parent.stat(follow_symlinks=False)
                if (info.st_uid not in (0, os.geteuid()) or
                        info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
                    raise SourceError()
        with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                              | getattr(os, 'O_NONBLOCK', 0)), 'rb') as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096
                    or (checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino)):
                raise SourceError()
            _token_permissions(info)
            token = handle.read(4097).decode('ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,4096}', token):
            raise SourceError()
        return token
    except (OSError, ValueError, UnicodeError):
        raise SourceError() from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError()


class ReadClient:
    """Only two fixed-origin GET operations, no proxies, redirects, retries or writes."""
    def __init__(self, token_file):
        self._token = _read_token(token_file)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        self._requests = 0
        self._deadline = time.monotonic() + 60

    def _get(self, path, query=None):
        self._requests += 1
        remaining = self._deadline - time.monotonic()
        if self._requests > MAX_REQUESTS or remaining <= 0:
            raise SourceError()
        url = 'https://api.cloudflare.com/client/v4' + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self._token,
            'Accept': 'application/json', 'Accept-Encoding': 'identity'}, method='GET')
        request_deadline = min(self._deadline, time.monotonic() + 10)
        try:
            with self._opener.open(request, timeout=min(10, remaining)) as response:
                if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise SourceError()
                chunks, size = [], 0
                # read1 avoids read(n) waiting for n bytes while a peer dribbles data.
                read = getattr(response, 'read1', response.read)
                while True:
                    if time.monotonic() > request_deadline:
                        raise SourceError()
                    chunk = read(min(4096, MAX_JSON + 1 - size))
                    size += len(chunk)
                    if size > MAX_JSON or time.monotonic() > request_deadline:
                        raise SourceError()
                    if not chunk:
                        break
                    chunks.append(chunk)
                payload = b''.join(chunks)
            if time.monotonic() > self._deadline:
                raise SourceError()
            payload = _json(payload)
            if not isinstance(payload, dict) or payload.get('success') is not True:
                raise SourceError()
            return payload
        except (OSError, ValueError, urllib.error.URLError):
            raise SourceError() from None

    def inventory(self, account_id, product):
        account_id = _identifier(account_id)
        if product not in ('workers', 'zones'):
            raise SourceError()
        identities = []
        total = None
        for page in range(1, MAX_PAGES + 1):
            if product == 'workers':
                # Official scripts list is a SinglePage endpoint; no invented pagination.
                payload = self._get('/accounts/' + account_id + '/workers/scripts')
            else:
                payload = self._get('/zones', {'account.id': account_id, 'page': page,
                    'per_page': 50, 'type': 'full,partial,secondary,internal'})
            rows = payload.get('result')
            if not isinstance(rows, list) or len(rows) > MAX_ROWS:
                raise SourceError()
            for row in rows:
                if not isinstance(row, dict):
                    raise SourceError()
                if product == 'zones' and (not isinstance(row.get('account'), dict)
                                           or row['account'].get('id') != account_id):
                    raise SourceError()
                identity = _identifier(row.get('id'), worker=product == 'workers')
                if identity in identities:
                    raise SourceError()
                identities.append(identity)
            if len(identities) > MAX_ROWS:
                raise SourceError()
            if product == 'workers':
                if 'result_info' in payload:
                    info = payload['result_info']
                    if not isinstance(info, dict) or info.get('total_count') != len(identities):
                        raise SourceError()
                return tuple(identities)
            info = payload.get('result_info')
            if not isinstance(info, dict) or any(type(info.get(k)) is not int for k in
                    ('page', 'per_page', 'count', 'total_count', 'total_pages')):
                raise SourceError()
            if (info['page'] != page or info['per_page'] != 50 or info['count'] != len(rows)
                    or not 0 <= info['total_count'] <= MAX_ROWS
                    or not 0 <= info['total_pages'] <= MAX_PAGES
                    or info['total_pages'] == 0 and info['total_count'] != 0
                    or info['total_pages'] != max(1, (info['total_count'] + 49) // 50)
                       and not (info['total_pages'] == 0 and info['total_count'] == 0)
                    or len(rows) != min(50, max(0, info['total_count'] - (page - 1) * 50))
                    or total is not None and total != (info['total_count'], info['total_pages'])):
                raise SourceError()
            total = (info['total_count'], info['total_pages'])
            if page >= max(1, info['total_pages']):
                if len(identities) != info['total_count']:
                    raise SourceError()
                return tuple(identities)
            if not rows:
                raise SourceError()
        raise SourceError()


def _coverage(account, raw):
    if not isinstance(raw, dict) or len(raw) > MAX_ROWS:
        raise SourceError()
    result = {}
    for source, value in raw.items():
        normalized = source
        if source.startswith('subscriptions.zone:'):
            try:
                zone = _identifier(source.split(':', 1)[1])
            except SourceError:
                continue
            normalized = 'subscriptions.zone:' + reference(account['id'], 'zones', zone)
        elif source not in SOURCE_NAMES:
            continue
        state = value.split(':', 1)[0] if isinstance(value, str) else 'unknown'
        state = {'supported': 'complete', 'verified_config': 'complete'}.get(state, state)
        result[normalized] = state if state in STATES else 'unknown'
    # Missing fixed evidence must remain visible, not disappear and recover old issues.
    for source in ('subscriptions.account', 'billing_info', 'billing_account_coverage',
                   'billing_period', 'rated_usage', 'workers.requests'):
        result.setdefault(source, 'unknown')
    for zone in account['expected_zones']:
        result.setdefault('subscriptions.zone:' + reference(account['id'], 'zones', zone), 'unknown')
    limitations = account.get('known_limitations', {})
    return [{'source': source, 'status': state,
             'known_limitation': limitations.get(source) == state}
            for source, state in sorted(result.items())]


def _subscription(account_id, row):
    if not isinstance(row, dict):
        raise SourceError()
    key = row.get('key')
    if (not isinstance(key, dict) or key.get('account_id') != account_id
            or key.get('product') != 'subscriptions' or key.get('resource_id') is not None):
        raise SourceError()
    scope = key.get('scope')
    if scope == 'zone':
        _identifier(key.get('zone_id'))
    elif scope != 'account' or key.get('zone_id') is not None:
        raise SourceError()
    identity = _identifier(row.get('provider_id'), worker=True)
    _identifier(row.get('plan_id'), worker=True)
    if row.get('plan_scope') not in (None, 'account', 'zone'):
        raise SourceError()
    expected_source = hashlib.sha256(json.dumps([account_id, identity], separators=(',', ':')).encode()).hexdigest()
    amount = row.get('amount')
    if (row.get('source_key') != expected_source or not isinstance(amount, str) or len(amount) > 64
            or not re.fullmatch(r'\d+(?:\.\d+)?(?:[Ee][+-]?\d{1,3})?', amount)
            or row.get('currency') != 'USD' or row.get('quality') not in ('good', 'approximate')
            or type(row.get('allowed')) is not bool):
        raise SourceError()
    try:
        parsed = Decimal(amount)
        if not parsed.is_finite() or parsed < 0 or abs(parsed.adjusted()) > 100:
            raise SourceError()
    except InvalidOperation:
        raise SourceError() from None
    return {'resource_ref': reference(account_id, 'subscriptions', identity),
            'amount': format(parsed, 'f'), 'currency': 'USD', 'quality': row['quality'], 'allowed': row['allowed']}


def _snapshot(account, payload):
    result = {'account_ref': reference(account['id'], 'account'), 'snapshot_at': None,
              'subscriptions_status': 'unknown', 'subscriptions': [], 'coverage': []}
    snapshot = _json(payload)
    if not isinstance(snapshot, dict) or snapshot.get('account_id') != account['id']:
        raise SourceError()
    result['snapshot_at'] = _timestamp(snapshot.get('collected_at'))
    try:
        result['coverage'] = _coverage(account, snapshot.get('coverage'))
    except SourceError:
        result['coverage'] = _coverage(account, {})
    rows = snapshot.get('subscriptions')
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return result
    complete = all(row['status'] == 'complete' for row in result['coverage']
                   if row['source'].startswith('subscriptions.'))
    seen, provenance = {}, {}
    for row in rows:
        try:
            safe = _subscription(account['id'], row)
        except SourceError:
            complete = False
            continue
        ref = safe['resource_ref']
        plans, zones, scopes = provenance.setdefault(ref, (set(), set(), set()))
        plans.add(row['plan_id'])
        if row['key']['scope'] == 'zone':
            zones.add(row['key']['zone_id'])
        if row.get('plan_scope') is not None:
            scopes.add(row['plan_scope'])
        candidates = seen.setdefault(ref, [])
        if safe not in candidates:
            candidates.append(safe)
        if len(candidates) > 1:
            # Preserve the disagreement for policy; neither amount is authoritative.
            complete = False
        if safe['quality'] != 'good':
            complete = False
    expected_zones = set(account['expected_zones'])
    for ref, (plans, zones, scopes) in provenance.items():
        # Account-list appearances do not assert account ownership. Reconcile the
        # original endpoint/plan metadata before trusting the sanitized duplicate.
        if (len(plans) > 1 or len(zones) > 1 or len(scopes) > 1
                or zones and 'account' in scopes or zones - expected_zones):
            complete = False
            for item in seen[ref]:
                item['quality'] = 'unknown'
    result['subscriptions'] = sorted((item for candidates in seen.values() for item in candidates),
                                     key=lambda row: row['resource_ref'])
    result['subscriptions_status'] = 'complete' if complete else 'unknown'
    return result


def _unknown_guard():
    return {'status': 'unknown', 'last_attempt': None, 'last_finished': None,
            'last_collection_success': None, 'pending_notifications': None, 'oldest_pending_at': None}


def _read_guard(config, now):
    path = Path(config['guard_database'])
    if not path.is_absolute() or path.is_symlink():
        raise SourceError()
    deadline = time.monotonic() + 2
    steps = 0
    def progress():
        nonlocal steps
        steps += 1
        return steps > 2000 or time.monotonic() > deadline
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                                           timeout=1, isolation_level=None)) as db:
        db.set_progress_handler(progress, 1000)
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        schema = db.execute("SELECT substr(value,1,2) FROM meta WHERE key='schema_version'").fetchone()
        if schema != ('6',):
            raise SourceError()
        guard = _unknown_guard() | {'status': 'ok'}
        for key in ('last_attempt', 'last_finished', 'last_collection_success'):
            row = db.execute('SELECT substr(value,1,49) FROM meta WHERE key=?', (key,)).fetchone()
            guard[key] = _timestamp(row[0]) if row and row[0] else None
        pending = db.execute('''SELECT substr(next_at,1,49),NULL FROM outbox WHERE routing='legacy' AND delivered=0
            UNION ALL SELECT substr(d.next_at,1,49),substr(d.last_attempt,1,49) FROM notification_deliveries AS d
            JOIN outbox AS o ON o.id=d.event_id WHERE d.status='pending' AND o.routing='multi'
            LIMIT ?''', (MAX_ROWS + 1,)).fetchall()
        if len(pending) > MAX_ROWS:
            raise SourceError()
        guard['pending_notifications'] = len(pending)
        times = [_timestamp(value) for row in pending for value in row if value is not None]
        # Schema 6 has no enqueue time. This is a lower-bound waiting-age signal:
        # retries move next_at forward; last_attempt helps only for multi delivery.
        # The independent watcher additionally tracks first-seen pending time.
        guard['oldest_pending_at'] = min([now] + times) if pending else None
        accounts = []
        for account in config['accounts']:
            row = db.execute('SELECT CASE WHEN length(current)<=? THEN current END FROM snapshots WHERE account=?',
                             (MAX_JSON, account['id'])).fetchone()
            try:
                accounts.append(_snapshot(account, row[0] if row else None))
            except SourceError:
                accounts.append(_placeholder(account))
        db.execute('ROLLBACK')
        return guard, accounts


def _placeholder(account):
    return {'account_ref': reference(account['id'], 'account'), 'snapshot_at': None,
            'subscriptions_status': 'unknown', 'subscriptions': [], 'coverage': []}


def collect(config, now, client_factory=None):
    """Sample enrolled accounts only; return safe placeholders at every failed source."""
    now = _timestamp(now.isoformat())
    accounts = config['accounts']
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= MAX_ACCOUNTS:
        raise SourceError()
    for account in accounts:
        _identifier(account['id'])
        for product in ('workers', 'zones'):
            expected = account['expected_' + product]
            if not isinstance(expected, list) or len(expected) > MAX_ROWS:
                raise SourceError()
            for identity in expected:
                _identifier(identity, worker=product == 'workers')
    try:
        guard, rows = _read_guard(config, now)
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        guard, rows = _unknown_guard(), [_placeholder(account) for account in accounts]
    factory = client_factory or ReadClient
    for account, output in zip(accounts, rows):
        output['inventory'] = {}
        try:
            client = factory(account['read_token_file'])
        except Exception:
            client = None
        for product in ('workers', 'zones'):
            inventory = {'status': 'unknown', 'refs': [], 'expected': sorted(
                reference(account['id'], product, item) for item in account['expected_' + product])}
            try:
                if client is None:
                    raise SourceError()
                identities = client.inventory(account['id'], product)
                if not isinstance(identities, (tuple, list)) or len(identities) > MAX_ROWS:
                    raise SourceError()
                identities = [_identifier(identity, worker=product == 'workers') for identity in identities]
                if len(identities) != len(set(identities)):
                    raise SourceError()
                inventory.update(status='complete', refs=sorted(reference(account['id'], product, item)
                                                                 for item in identities))
            except Exception:
                pass
            output['inventory'][product] = inventory
    return {'version': 1, 'observed_at': now, 'guard': guard, 'accounts': rows}
