"""Real collector/runner/action integration with synthetic HTTP and credentials."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from cfguard.budget import policy_digest
from cfguard.cloudflare import Client, CloudflareError, HttpResponse
from cfguard.models import AccountConfig, Config, GuardBudget, ResourceConfig, ResourceKey
from cfguard.runner import run_once
from cfguard.state import Store

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


class CutoffRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.read = self.root / 'read.token'
        self.write = self.root / 'write.token'
        for path in (self.read, self.write):
            path.write_text('SYNTHETIC_' + path.stem)
            path.chmod(0o600)
        self.account = AccountConfig('fixture', 'a' * 32, self.read, 1, D('0'), 'USD')
        budget = GuardBudget(D('.0001'), 'workers_usage_estimate', D('1'), D('1'), D('50'),
                             'synthetic pricing', '2026-10-27', True, True)
        self.resource = ResourceConfig(ResourceKey(self.account.account_id, 'resource', 'workers', 'demo-worker'),
                                       'Demo', permitted_action='delete_worker', executor_token_file=self.write,
                                       approved_manifest_file=self.root / 'approval.json', budget=budget)
        self.deleted = False
        self.enabled = True
        self.calls, self.factories = [], []
        self.timeout = False
        self.write_credential_touched = False

    def config(self, mode='enforce', action='delete_worker', budget=None):
        resource = replace(self.resource, permitted_action=action,
                           budget=budget or self.resource.budget)
        manifest = {'version': 2, 'approval_reference': 'synthetic-owner-approval',
                    'expires_at': (NOW + timedelta(days=1)).isoformat(),
                    'resource': {'account_id': self.account.account_id, 'product': 'workers', 'resource_id': 'demo-worker'},
                    'action': action, 'budget_digest': policy_digest(resource, self.account),
                    'accept_approximate': resource.budget.accept_approximate,
                    'accept_partial': resource.budget.accept_partial,
                    'acknowledge_deletion': True, 'restore_source_confirmed': True, 'stateless_worker_confirmed': True}
        raw = json.dumps(manifest).encode()
        resource.approved_manifest_file.write_bytes(raw)
        resource.approved_manifest_file.chmod(0o600)
        resource = replace(resource, approved_manifest_digest=hashlib.sha256(raw).hexdigest())
        return Config(mode=mode, accounts=(self.account,), resources=(resource,), state_dir=self.root / 'state')

    def transport(self, request, timeout):
        self.calls.append((request.method, request.full_url, request.get_header('Authorization')))
        path = urlsplit(request.full_url).path
        if request.method == 'DELETE':
            self.assertEqual(urlsplit(request.full_url).query, 'force=false')
            self.assertTrue(path.endswith('/workers/scripts/demo-worker'))
            self.deleted = True
            if self.timeout:
                raise TimeoutError('synthetic uncertain delivery')
            return HttpResponse(200, b'', {})
        if request.method == 'POST' and path.endswith('/subdomain'):
            self.assertEqual(json.loads(request.data), {'enabled': False, 'previews_enabled': False})
            self.enabled = False
            result = {'enabled': False, 'previews_enabled': False}
        elif path.endswith('/graphql'):
            variables = json.loads(request.data)['variables']
            return HttpResponse(200, json.dumps({'data': {'viewer': {'accounts': [{
                'workersInvocationsAdaptive': [{'sum': {'requests': 2}, 'dimensions': {
                    'datetime': variables['start'], 'scriptName': 'demo-worker', 'status': 'success'}}]}]}},
                'errors': None}).encode(), {})
        elif path.endswith('/workers/scripts'):
            result = [] if self.deleted else [{'id': 'demo-worker', 'etag': 'synthetic-etag',
                'handlers': ['fetch'], 'named_handlers': [], 'has_assets': False, 'has_modules': True}]
        elif path.endswith('/settings'):
            result = {'bindings': [], 'limits': {'cpu_ms': 50}, 'usage_model': 'standard', 'exports': {}}
        elif path.endswith('/deployments'):
            result = {'deployments': [{'id': 'deploy-1', 'versions': [{'version_id': 'version-1', 'percentage': 100}]}]}
        elif '/versions/' in path:
            result = {'resources': {'script': {'etag': 'synthetic-etag', 'handlers': ['fetch'], 'named_handlers': []},
                                    'bindings': {}, 'script_runtime': {'exports': {
                                        'default': {'type': 'worker', 'state': 'created', 'cache': {'enabled': False}}}}}}
        elif path.endswith('/durable_objects/namespaces'):
            return HttpResponse(200, json.dumps({'success': True, 'result': [],
                'result_info': {'page': 1, 'total_pages': 1, 'total_count': 0}}).encode(), {})
        elif path.endswith('/subdomain'):
            result = {'enabled': self.enabled, 'previews_enabled': self.enabled}
        elif path.endswith('/billable-usage/info'):
            result = {'covered': False, 'subscriptions': []}
        elif path.endswith('/billable-usage') or path.endswith('/subscriptions'):
            result = []
        else:
            self.fail('unexpected synthetic API path: ' + path)
        return HttpResponse(200, json.dumps({'success': True, 'result': result}).encode(), {})

    def factory(self, path):
        self.factories.append(path)
        return Client(path, transport=self.transport, sleep=lambda _: None)

    def run_guard(self, config, **kwargs):
        # POSIX root ownership has separate negative tests. Keep real manifest
        # parsing/hash/expiry/identity checks and the real collector/HTTP transport.
        with patch('cfguard.cutoff.validate_admin_file'):
            return run_once(config, now=NOW, client_factory=self.factory, **kwargs)

    def test_budget_crossing_automatically_deletes_worker_with_real_client_once(self):
        config = self.config()
        _, report = self.run_guard(config)
        self.assertTrue(self.deleted)
        self.assertEqual([entry['status'] for entry in report['actions']], ['worker_deleted'])
        self.assertTrue(any(d['metric'] == 'guard_cost_usd' for d in report['accounts'][0]['decisions']))
        with Store(config.state_dir) as store:
            self.assertEqual(store.intent(self.resource.key)['status'], 'worker_deleted')
        _, repeated = self.run_guard(config)
        self.assertEqual(sum(method == 'DELETE' for method, *_ in self.calls), 1)
        writer_calls = [(method, url) for method, url, auth in self.calls if auth == 'Bearer SYNTHETIC_write']
        self.assertEqual(len(writer_calls), 1)  # Writer needs no Analytics or Billing permission.
        self.assertNotIn('demo-worker', json.dumps(report))
        self.assertNotIn('SYNTHETIC_', json.dumps(repeated))

    def test_observe_probe_and_preview_never_open_executor_or_mutate_provider(self):
        for mode, options in (('observe', {}), ('enforce', {'probe': True}), ('enforce', {'preview': True})):
            with self.subTest(mode=mode, options=options):
                config = self.config(mode=mode)
                self.factories.clear()
                self.calls.clear()
                _, report = self.run_guard(config, **options)
                self.assertNotIn(self.write, self.factories)
                self.assertFalse(self.deleted)
                self.assertFalse(any(method == 'DELETE' for method, *_ in self.calls))
                with Store(config.state_dir) as store:
                    self.assertIsNone(store.intent(self.resource.key))

    def test_endpoint_cutoff_is_automatic_but_reports_only_endpoint_scope(self):
        _, report = self.run_guard(self.config(action='disable_worker_endpoints'))
        self.assertFalse(self.deleted)
        self.assertFalse(self.enabled)
        self.assertEqual(report['actions'][0]['status'], 'endpoints_disabled')
        self.assertEqual(sum(method == 'POST' and urlsplit(url).path.endswith('/subdomain')
                             for method, url, _ in self.calls), 1)

    def test_delete_timeout_after_application_reconciles_without_resending(self):
        self.timeout = True
        config = self.config()
        _, report = self.run_guard(config)
        self.assertEqual(report['actions'][0]['status'], 'worker_deleted')
        self.run_guard(config)
        self.assertEqual(sum(method == 'DELETE' for method, *_ in self.calls), 1)

    def test_observed_account_charge_budget_has_explicit_target_not_inferred_guilt(self):
        budget = GuardBudget(D('2'), 'account_rated_observed', accept_partial=True)
        config = self.config(budget=budget)
        original = self.transport
        def transport(request, timeout):
            if urlsplit(request.full_url).path.endswith('/billable-usage'):
                return HttpResponse(200, json.dumps({'success': True, 'result': [{
                    'BillingAccountId': self.account.account_id, 'BillingCurrency': 'USD',
                    'BillingPeriodStart': '2026-10-01T00:00:00Z', 'ChargeCategory': 'Usage',
                    'ChargeDescription': 'Synthetic account charge', 'ChargePeriodStart': '2026-10-25T00:00:00Z',
                    'ChargePeriodEnd': '2026-10-26T00:00:00Z', 'ContractedCost': '2',
                    'ServiceName': 'Synthetic product', 'PricingUnit': 'Count', 'ConsumedUnit': 'Count'}]}).encode(), {})
            return original(request, timeout)
        self.transport = transport
        _, report = self.run_guard(config)
        self.assertTrue(self.deleted)
        self.assertEqual(report['actions'][0]['status'], 'worker_deleted')

    def test_one_broken_account_does_not_reuse_another_reader_or_block_other_guard(self):
        config = self.config()
        broken_path = self.root / 'broken.token'
        broken = replace(self.account, key='broken', account_id='b' * 32, read_token_file=broken_path)
        config = replace(config, accounts=(broken, self.account))
        original = self.factory
        def factory(path):
            if path == broken_path:
                raise OSError('SYNTHETIC_PRIVATE_ERROR')
            return original(path)
        with patch('cfguard.cutoff.validate_admin_file'):
            _, report = run_once(config, now=NOW, client_factory=factory)
        self.assertEqual(len(report['accounts']), 2)
        self.assertTrue(self.deleted)
        self.assertNotIn('SYNTHETIC_PRIVATE_ERROR', json.dumps(report))

    def test_unknown_namespace_owner_blocks_stateless_readiness(self):
        original = self.transport
        for owner in ('', ' ', '../demo-worker'):
            with self.subTest(owner=owner):
                def transport(request, timeout):
                    if urlsplit(request.full_url).path.endswith('/durable_objects/namespaces'):
                        return HttpResponse(200, json.dumps({'success': True,
                            'result': [{'id': 'namespace-1', 'script': owner}],
                            'result_info': {'page': 1, 'total_pages': 1, 'total_count': 1}}).encode(), {})
                    return original(request, timeout)
                self.transport = transport
                with self.assertRaises(CloudflareError):
                    self.factory(self.read).worker_cutoff_state(self.resource)

    def test_owned_namespace_on_later_page_prevents_deletion(self):
        original = self.transport
        def transport(request, timeout):
            parsed = urlsplit(request.full_url)
            if parsed.path.endswith('/durable_objects/namespaces'):
                page = 2 if 'page=2&' in parsed.query else 1
                return HttpResponse(200, json.dumps({'success': True,
                    'result': [{'id': 'namespace-' + str(page),
                                'script': 'another-worker' if page == 1 else 'demo-worker'}],
                    'result_info': {'page': page, 'total_pages': 2, 'total_count': 2}}).encode(), {})
            return original(request, timeout)
        self.transport = transport
        _, report = self.run_guard(self.config())
        self.assertFalse(self.deleted)
        self.assertEqual(report['actions'][0]['status'], 'not_applied')
        self.assertNotIn(self.write, self.factories)

    def test_definite_auth_rejection_needs_manual_rearm_but_can_recover(self):
        original = self.transport
        for status in (401, 403):
            # A fresh state/approval identity for each definitive provider refusal.
            config = replace(self.config(), state_dir=self.root / ('state-' + str(status)))
            self.deleted = False
            self.calls.clear()
            def transport(request, timeout):
                if request.method == 'DELETE':
                    self.calls.append((request.method, request.full_url, request.get_header('Authorization')))
                    return HttpResponse(status, b'synthetic forbidden payload', {})
                return original(request, timeout)
            self.transport = transport
            _, report = self.run_guard(config)
            self.assertEqual(report['actions'][0]['status'], 'not_applied')
            self.run_guard(config)
            self.assertEqual(sum(method == 'DELETE' for method, *_ in self.calls), 1)
            with Store(config.state_dir) as store:
                store.rearm(self.resource.key)
            self.transport = original
            _, report = self.run_guard(config)
            self.assertEqual(report['actions'][0]['status'], 'worker_deleted')
            self.assertEqual(sum(method == 'DELETE' for method, *_ in self.calls), 2)

    def test_auth_rejection_with_unavailable_readback_stays_uncertain_until_read_recovers(self):
        config = self.config()
        original = self.transport
        reader_down = [False]
        def transport(request, timeout):
            if request.method == 'DELETE':
                self.calls.append((request.method, request.full_url, request.get_header('Authorization')))
                reader_down[0] = True
                return HttpResponse(403, b'synthetic rejection', {})
            if reader_down[0] and urlsplit(request.full_url).path.endswith('/workers/scripts'):
                raise TimeoutError('synthetic unavailable readback')
            return original(request, timeout)
        self.transport = transport
        _, report = self.run_guard(config)
        self.assertEqual(report['actions'][0]['status'], 'uncertain')
        with Store(config.state_dir) as store:
            self.assertEqual(store.intent(self.resource.key)['writer_rejection'], 403)
            with self.assertRaises(ValueError):
                store.rearm(self.resource.key)
        reader_down[0] = False
        _, report = self.run_guard(config)
        self.assertEqual(report['actions'][0]['status'], 'not_applied')
        self.assertEqual(sum(method == 'DELETE' for method, *_ in self.calls), 1)

    def test_server_error_remains_ambiguous_and_never_retries_mutation(self):
        config = self.config()
        original = self.transport
        def transport(request, timeout):
            if request.method == 'DELETE':
                self.calls.append((request.method, request.full_url, request.get_header('Authorization')))
                return HttpResponse(503, b'synthetic ambiguous error', {})
            return original(request, timeout)
        self.transport = transport
        for _ in range(2):
            _, report = self.run_guard(config)
            self.assertEqual(report['actions'][0]['status'], 'uncertain')
        self.assertEqual(sum(method == 'DELETE' for method, *_ in self.calls), 1)
        with Store(config.state_dir) as store:
            self.assertNotIn('writer_rejection', store.intent(self.resource.key))
