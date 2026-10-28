"""Offline contracts for the read-only, privacy-preserving sampler."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
ACCOUNT = 'a' * 32
ZONE = 'b' * 32


def subscription(identity='subscription-one', amount='5.50'):
    return {'key': {'account_id': ACCOUNT, 'product': 'subscriptions',
                    'scope': 'account', 'resource_id': None, 'zone_id': None},
            'source_key': hashlib.sha256(json.dumps([ACCOUNT, identity], separators=(',', ':')).encode()).hexdigest(),
            'provider_id': identity, 'plan_id': 'plan-one', 'plan_scope': 'account',
            'name': 'PRIVATE PLAN NAME', 'amount': amount, 'currency': 'USD',
            'quality': 'good', 'allowed': True}


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('cfguard.monitoring.sources'), 'source adapter is not implemented')
        self.sources = importlib.import_module('cfguard.monitoring.sources')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / 'guard.sqlite3'
        self.config = {'guard_database': str(self.database), 'accounts': [
            {'id': ACCOUNT, 'read_token_file': '/external/token',
             'expected_workers': ['expected-worker'], 'expected_zones': [ZONE],
             'known_limitations': {'billing_account_coverage': 'unavailable'}}]}
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE snapshots (account TEXT PRIMARY KEY, current TEXT, last_good TEXT);
                CREATE TABLE outbox (id TEXT PRIMARY KEY, payload TEXT, attempts INTEGER DEFAULT 0,
                    next_at TEXT, delivered INTEGER DEFAULT 0, priority INTEGER DEFAULT 0, routing TEXT DEFAULT 'legacy');
                CREATE TABLE notification_deliveries (event_id TEXT, target_id TEXT, config_digest TEXT,
                    status TEXT, next_at TEXT, last_attempt TEXT);
            ''')
            db.executemany('INSERT INTO meta VALUES (?,?)', [('schema_version', '6'),
                ('last_attempt', STAMP), ('last_finished', STAMP), ('last_collection_success', STAMP)])
        self.snapshot = {'account_id': ACCOUNT, 'collected_at': STAMP,
            'subscriptions': [subscription()], 'coverage': {'subscriptions.account': 'complete',
                'billing_account_coverage': 'unavailable', 'workers.requests': 'approximate: private detail',
                'subscriptions.zone:' + ZONE: 'complete', 'PRIVATE DOMAIN': 'PRIVATE ERROR'}}
        self.save_snapshot()

    def save_snapshot(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?,NULL)', (ACCOUNT, json.dumps(self.snapshot)))

    def collect(self, inventory=None):
        class Client:
            def inventory(inner, account, product):
                if inventory is not None:
                    return inventory(account, product)
                return ['expected-worker'] if product == 'workers' else [ZONE]
        return self.sources.collect(self.config, NOW, lambda token: Client())

    def test_hashes_are_stable_account_and_product_bound(self):
        ref = self.sources.reference(ACCOUNT, 'workers', 'expected-worker')
        self.assertRegex(ref, r'^[0-9a-f]{16}$')
        self.assertEqual(ref, self.sources.reference(ACCOUNT, 'workers', 'expected-worker'))
        self.assertNotEqual(ref, self.sources.reference('c' * 32, 'workers', 'expected-worker'))
        self.assertNotEqual(ref, self.sources.reference(ACCOUNT, 'zones', 'expected-worker'))

    def test_collect_sanitizes_rows_coverage_and_inventory(self):
        result = self.collect()
        self.assertEqual(result['guard']['status'], 'ok')
        account = result['accounts'][0]
        self.assertEqual(account['subscriptions_status'], 'complete')
        self.assertEqual(account['subscriptions'][0]['amount'], '5.50')
        self.assertEqual(account['inventory']['workers']['status'], 'complete')
        limitation = next(row for row in account['coverage'] if row['source'] == 'billing_account_coverage')
        self.assertEqual(limitation, {'source': 'billing_account_coverage', 'status': 'unavailable', 'known_limitation': True})
        encoded = json.dumps(result)
        for private in (ACCOUNT, ZONE, 'expected-worker', 'PRIVATE', 'subscription-one', 'plan-one'):
            self.assertNotIn(private, encoded)

    def test_database_remains_byte_identical(self):
        before = self.database.read_bytes()
        self.collect()
        self.assertEqual(self.database.read_bytes(), before)

    def test_unknown_schema_has_missing_account_placeholders(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
        result = self.collect()
        self.assertEqual(result['guard']['status'], 'unknown')
        self.assertIsNone(result['guard']['last_finished'])
        self.assertEqual(result['accounts'][0]['subscriptions_status'], 'unknown')
        self.assertIsNone(result['accounts'][0]['snapshot_at'])

    def test_missing_database_does_not_create_it(self):
        self.database.unlink()
        self.assertEqual(self.collect()['guard']['status'], 'unknown')
        self.assertFalse(self.database.exists())

    def test_malformed_snapshot_binding_and_naive_timestamp_are_unknown(self):
        for field, value in [('account_id', 'c' * 32), ('collected_at', '2026-10-28T12:00:00')]:
            with self.subTest(field=field):
                old = self.snapshot[field]
                self.snapshot[field] = value
                self.save_snapshot()
                row = self.collect()['accounts'][0]
                self.assertIsNone(row['snapshot_at'])
                self.assertEqual(row['subscriptions_status'], 'unknown')
                self.snapshot[field] = old

    def test_partial_subscriptions_preserve_valid_positive(self):
        self.snapshot['subscriptions'] += [subscription('bad', 'NaN')]
        self.snapshot['coverage']['subscriptions.account'] = 'unknown: secret'
        self.save_snapshot()
        account = self.collect()['accounts'][0]
        self.assertEqual(account['subscriptions_status'], 'unknown')
        self.assertEqual([row['amount'] for row in account['subscriptions']], ['5.50'])

    def test_exponent_amounts_normalize_exactly_and_assess_as_positive(self):
        from cfguard.monitoring.policy import assess
        for raw, fixed in [('1E+1', '10'), ('1E-100', '0.' + '0' * 99 + '1'),
                           ('1E+100', '1' + '0' * 100),
                           ('123456789012345678901234567890123456789E-100',
                            '0.' + '0' * 61 + '123456789012345678901234567890123456789')]:
            with self.subTest(amount=raw):
                self.snapshot['subscriptions'] = [subscription(amount=raw)]
                self.save_snapshot()
                observed = self.collect()
                self.assertEqual(observed['accounts'][0]['subscriptions'][0]['amount'], fixed)
                positive = [i for i in assess(observed, NOW)['issues']
                            if i['reason'] == 'positive_subscription']
                self.assertEqual(len(positive), 1)
                self.assertEqual(positive[0]['details']['amount'], fixed)

    def test_malformed_coverage_preserves_valid_positive_with_unknown_status(self):
        self.snapshot['coverage'] = None
        self.save_snapshot()
        account = self.collect()['accounts'][0]
        self.assertEqual(account['subscriptions_status'], 'unknown')
        self.assertEqual([row['amount'] for row in account['subscriptions']], ['5.50'])

    def test_invalid_amount_currency_quality_and_identity_never_look_complete(self):
        variants = [('amount', 4), ('amount', '-1'), ('amount', 'Infinity'),
                    ('currency', 'EUR'), ('quality', 'unknown'), ('provider_id', None),
                    ('source_key', 'fake'), ('allowed', 'yes')]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                self.snapshot['subscriptions'] = [subscription() | {field: value}]
                self.save_snapshot()
                self.assertEqual(self.collect()['accounts'][0]['subscriptions_status'], 'unknown')

    def test_conflicting_duplicate_subscription_preserves_conflict_without_choosing_amount(self):
        self.snapshot['subscriptions'] += [subscription(amount='0')]
        self.save_snapshot()
        row = self.collect()['accounts'][0]
        self.assertEqual(row['subscriptions_status'], 'unknown')
        self.assertCountEqual([item['amount'] for item in row['subscriptions']], ['5.50', '0'])

    def test_original_subscription_provenance_conflicts_remain_unknown(self):
        from copy import deepcopy
        from cfguard.monitoring.policy import assess
        account = subscription(amount='0')
        zone = deepcopy(account)
        zone['key'].update(scope='zone', zone_id=ZONE)
        zone['plan_scope'] = 'zone'
        other_zone = deepcopy(zone)
        other_zone['key']['zone_id'] = 'c' * 32
        self.config['accounts'][0]['expected_zones'].append('c' * 32)
        self.snapshot['coverage']['subscriptions.zone:' + 'c' * 32] = 'complete'
        variants = [
            [account, account | {'plan_id': 'plan-two'}],
            [account, account | {'plan_scope': 'zone'}],
            [zone | {'plan_scope': 'account'}],
            [zone, other_zone],
            [subscription(), subscription() | {'plan_id': 'plan-two'}],
        ]
        for rows in variants:
            with self.subTest(rows=rows):
                self.snapshot['subscriptions'] = rows + [subscription('unrelated', '7')]
                self.save_snapshot()
                observed = self.collect()
                output = observed['accounts'][0]
                self.assertEqual(output['subscriptions_status'], 'unknown')
                assessed = assess(observed, NOW)
                self.assertFalse(any(s.endswith(':subscriptions') for s in assessed['verified_scopes']))
                positives = [i for i in assessed['issues'] if i['reason'] == 'positive_subscription']
                self.assertEqual([i['details']['amount'] for i in positives], ['7'])
                for private in (ACCOUNT, ZONE, 'plan-one', 'plan-two', 'PRIVATE'):
                    self.assertNotIn(private, json.dumps(observed))

    def test_compatible_account_and_zone_appearances_deduplicate(self):
        from copy import deepcopy
        account = subscription()
        account['plan_scope'] = None
        zone = deepcopy(account)
        zone['key'].update(scope='zone', zone_id=ZONE)
        zone['plan_scope'] = 'zone'
        self.snapshot['subscriptions'] = [account, zone, deepcopy(zone)]
        self.save_snapshot()
        output = self.collect()['accounts'][0]
        self.assertEqual(output['subscriptions_status'], 'complete')
        self.assertEqual([r['amount'] for r in output['subscriptions']], ['5.50'])

    def test_missing_subscription_coverage_is_unknown_even_for_empty_rows(self):
        self.snapshot['subscriptions'] = []
        self.snapshot['coverage'] = {}
        self.save_snapshot()
        self.assertEqual(self.collect()['accounts'][0]['subscriptions_status'], 'unknown')

    def test_mixed_outbox_joins_only_actual_pending_deliveries(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executemany('INSERT INTO outbox(id,payload,next_at,routing) VALUES (?,\'{}\',?,?)',
                [('legacy', '2026-10-28T11:00:00+00:00', 'legacy'),
                 ('multi', STAMP, 'multi'), ('cancelled', STAMP, 'legacy_cancelled')])
            db.executemany('INSERT INTO notification_deliveries VALUES (?,?,\'digest\',?,?,?)',
                [('multi', 'target', 'pending', STAMP, '2026-10-28T10:00:00+00:00'),
                 ('multi', 'done', 'delivered', STAMP, None),
                 ('missing-outbox', 'orphan', 'pending', STAMP, None)])
        guard = self.collect()['guard']
        self.assertEqual(guard['pending_notifications'], 2)
        self.assertEqual(guard['oldest_pending_at'], '2026-10-28T10:00:00+00:00')

    def test_inventory_failure_never_becomes_authoritative_empty(self):
        def fail(account, product):
            raise self.sources.SourceError('PRIVATE PROVIDER ERROR')
        result = self.collect(fail)
        for row in result['accounts'][0]['inventory'].values():
            self.assertEqual(row['status'], 'unknown')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_duplicate_inventory_ids_are_incomplete(self):
        row = self.collect(lambda a, p: ['same', 'same'])['accounts'][0]['inventory']['workers']
        self.assertEqual(row['status'], 'unknown')

    def test_oversized_snapshot_is_unknown(self):
        self.snapshot['extra'] = 'x' * (2 * 1024 * 1024)
        self.save_snapshot()
        self.assertEqual(self.collect()['accounts'][0]['subscriptions_status'], 'unknown')


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('cfguard.monitoring.sources'), 'source adapter is not implemented')
        self.sources = importlib.import_module('cfguard.monitoring.sources')

    def client(self, pages):
        # Patch only the external HTTP boundary. Real request construction and pagination run.
        calls = []
        class Response:
            status = 200
            headers = {}
            def __init__(inner, body):
                inner.body = io.BytesIO(json.dumps(body).encode())
            def read(inner, size):
                return inner.body.read(size)
            def __enter__(inner):
                return inner
            def __exit__(inner, *args):
                pass
        class Opener:
            def open(inner, request, timeout):
                calls.append(request)
                if len(calls) > len(pages):
                    raise AssertionError('request limit exceeded')
                return Response(pages[len(calls) - 1])
        with patch.object(self.sources, '_read_token', return_value='synthetic-token'), \
                patch('urllib.request.build_opener', return_value=Opener()):
            client = self.sources.ReadClient('/external/synthetic-token')
        return client, calls

    def test_workers_single_page_is_get_account_bound(self):
        client, calls = self.client([{'success': True, 'result': [{'id': 'one'}]}])
        self.assertEqual(client.inventory(ACCOUNT, 'workers'), ('one',))
        self.assertEqual(calls[0].get_method(), 'GET')
        self.assertEqual(calls[0].full_url, 'https://api.cloudflare.com/client/v4/accounts/' + ACCOUNT + '/workers/scripts')

    def test_zones_paginates_and_checks_account_on_every_page(self):
        def page(number, identity):
            identities = [f'{index:032x}' for index in range(50)] if number == 1 else [identity]
            return {'success': True, 'result': [{'id': item, 'account': {'id': ACCOUNT}} for item in identities],
                    'result_info': {'page': number, 'per_page': 50, 'count': len(identities),
                                    'total_count': 51, 'total_pages': 2}}
        client, calls = self.client([page(1, ZONE), page(2, 'c' * 32)])
        self.assertEqual(len(client.inventory(ACCOUNT, 'zones')), 51)
        self.assertIn('account.id=' + ACCOUNT, calls[0].full_url)
        self.assertIn('page=2', calls[1].full_url)
        self.assertIn('internal', calls[0].full_url)

    def test_zones_missing_pagination_or_account_is_not_empty_success(self):
        cases = [{'success': True, 'result': []},
            {'success': True, 'result': [{'id': ZONE, 'account': {'id': 'c' * 32}}],
             'result_info': {'page': 1, 'per_page': 50, 'count': 1, 'total_count': 1, 'total_pages': 1}},
            {'success': True, 'result': [], 'result_info': {'page': 1, 'per_page': 50,
              'count': 0, 'total_count': 2, 'total_pages': 1}}]
        for payload in cases:
            client, _ = self.client([payload])
            with self.subTest(payload=payload), self.assertRaises(self.sources.SourceError):
                client.inventory(ACCOUNT, 'zones')

    def test_unsupported_product_and_path_injection_make_no_requests(self):
        client, calls = self.client([])
        for account, product in [(ACCOUNT, 'r2'), ('../../evil', 'workers')]:
            with self.assertRaises(self.sources.SourceError):
                client.inventory(account, product)
        self.assertEqual(calls, [])

    def test_workers_body_limit_and_request_limit_fail_closed(self):
        client, calls = self.client([{'success': True, 'result': [], 'extra': 'x' * (1024 * 1024)}])
        with self.assertRaises(self.sources.SourceError):
            client.inventory(ACCOUNT, 'workers')
        client, calls = self.client([{'success': True, 'result': []}] * 64)
        for _ in range(64):
            self.assertEqual(client.inventory(ACCOUNT, 'workers'), ())
        with self.assertRaises(self.sources.SourceError):
            client.inventory(ACCOUNT, 'workers')
        self.assertEqual(len(calls), 64)

    def test_dribbling_body_is_stopped_by_total_deadline(self):
        clock = [0]
        class SlowResponse:
            status = 200
            headers = {}
            def __init__(inner):
                inner.stream = io.BytesIO(json.dumps({'success': True, 'result': [], 'extra': 'x' * 20000}).encode())
            def read(inner, size):
                clock[0] += 2
                return inner.stream.read(size)
            read1 = read
            def __enter__(inner):
                return inner
            def __exit__(inner, *args):
                pass
        class Opener:
            def open(inner, request, timeout):
                return SlowResponse()
        client, _ = self.client([])
        client._opener = Opener()
        client._deadline = 3
        with patch.object(self.sources.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(self.sources.SourceError):
                client.inventory(ACCOUNT, 'workers')

    def test_inconsistent_pagination_metadata_is_rejected(self):
        client, _ = self.client([{'success': True,
            'result': [{'id': ZONE, 'account': {'id': ACCOUNT}}],
            'result_info': {'page': 1, 'per_page': 50, 'count': 1, 'total_count': 1, 'total_pages': 2}},
            {'success': True, 'result': [],
            'result_info': {'page': 2, 'per_page': 50, 'count': 0, 'total_count': 1, 'total_pages': 2}}])
        with self.assertRaises(self.sources.SourceError):
            client.inventory(ACCOUNT, 'zones')

    def test_redirects_are_rejected_and_proxy_handler_is_empty(self):
        with patch.object(self.sources, '_read_token', return_value='synthetic-token'), \
                patch('urllib.request.build_opener') as build:
            self.sources.ReadClient('/external/synthetic-token')
        handlers = build.call_args.args
        proxy = next(item for item in handlers if isinstance(item, self.sources.urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        redirect = next(item for item in handlers if isinstance(item, self.sources._NoRedirect))
        with self.assertRaises(self.sources.SourceError):
            redirect.redirect_request(None, None, 302, 'private', {}, 'https://elsewhere.example')

    def test_posix_root_group_read_token_and_private_owned_token_are_supported(self):
        with patch.object(self.sources.os, 'name', 'posix'), \
                patch.object(self.sources.os, 'geteuid', return_value=1000, create=True), \
                patch.object(self.sources.os, 'getegid', return_value=42, create=True), \
                patch.object(self.sources.os, 'getgroups', return_value=[42], create=True):
            self.assertIsNone(self.sources._token_permissions(SimpleNamespace(
                st_uid=0, st_gid=42, st_mode=stat.S_IFREG | 0o640)))
            self.assertIsNone(self.sources._token_permissions(SimpleNamespace(
                st_uid=1000, st_gid=9, st_mode=stat.S_IFREG | 0o600)))
            for uid, gid, mode in [(2, 42, 0o640), (0, 9, 0o640), (0, 42, 0o644), (0, 42, 0o660)]:
                with self.subTest(uid=uid, gid=gid, mode=mode), self.assertRaises(self.sources.SourceError):
                    self.sources._token_permissions(SimpleNamespace(
                        st_uid=uid, st_gid=gid, st_mode=stat.S_IFREG | mode))

    def test_opened_token_must_match_previously_checked_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            path.write_text('synthetic-token', encoding='utf-8')
            info = path.stat()
            replacement = SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid,
                st_gid=info.st_gid, st_size=info.st_size, st_dev=info.st_dev, st_ino=info.st_ino + 1)
            with patch.object(self.sources.os, 'fstat', return_value=replacement):
                with self.assertRaises(self.sources.SourceError):
                    self.sources._read_token(path)

    def test_token_bad_content_and_overbroad_posix_mode_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            path.write_text('synthetic-token', encoding='utf-8')
            if os.name == 'posix':
                path.chmod(0o644)
                with self.assertRaises(self.sources.SourceError):
                    self.sources.ReadClient(path)
            path.write_text('bad\nheader', encoding='utf-8')
            with self.assertRaises(self.sources.SourceError):
                self.sources.ReadClient(path)


if __name__ == '__main__':
    unittest.main()
