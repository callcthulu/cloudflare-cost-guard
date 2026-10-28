"""Actual bounded Cloudflare HTTP contracts, with synthetic credentials only."""
import json
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from cfguard.cloudflare import Client, CloudflareError, HttpResponse
from cfguard.models import AccountConfig, Config, GuardBudget, Observation, ResourceConfig, ResourceKey, Snapshot
from cfguard.budget import policy_digest
from cfguard.state import Store


def reply(result, **extra):
    return HttpResponse(200, json.dumps(dict(success=True, errors=[], result=result, **extra)).encode(), {})


class ProviderCutoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = Path(self.tmp.name) / 'token'
        self.token.write_text('synthetic-token')
        self.token.chmod(0o600)
        self.resource = ResourceConfig(ResourceKey('account', 'resource', 'workers', 'demo'), 'demo')
        self.calls = []
        self.deleted = False
        self.enabled = True
        self.namespaces = []
        self.script = {'id': 'demo', 'etag': 'content-hash', 'handlers': ['fetch'],
                       'named_handlers': [], 'has_assets': False}
        self.settings = {'bindings': [], 'limits': {'cpu_ms': 50}, 'usage_model': 'standard', 'exports': {}}
        self.client = Client(self.token, account_id='account', transport=self.transport, sleep=lambda _: None)

    def transport(self, request, timeout):
        self.calls.append(request)
        path = urlsplit(request.full_url).path
        if request.method == 'DELETE':
            self.deleted = True
            return HttpResponse(200, b'', {})
        if path.endswith('/workers/scripts'):
            return reply([] if self.deleted else [self.script])
        if path.endswith('/settings'):
            return reply(self.settings)
        if path.endswith('/deployments'):
            return reply({'deployments': [{'id': 'deployment', 'versions': [{'version_id': 'version', 'percentage': 100}]}]})
        if '/versions/' in path:
            return reply({'resources': {'bindings': [], 'script': self.script,
                                       'script_runtime': {'exports': {}}}})
        if path.endswith('/namespaces'):
            return reply(self.namespaces, result_info={'page': 1, 'total_pages': 1, 'total_count': len(self.namespaces)})
        if path.endswith('/subdomain'):
            if request.method == 'POST':
                self.enabled = False
            return reply({'enabled': self.enabled, 'previews_enabled': self.enabled})
        raise AssertionError('unexpected synthetic API path')

    def test_real_delete_is_exact_single_attempt_and_empty_success_reconciles(self):
        self.client.delete_worker(self.resource)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0].method, 'DELETE')
        self.assertTrue(self.calls[0].full_url.endswith('/accounts/account/workers/scripts/demo?force=false'))
        self.assertIsNone(self.calls[0].data)
        state = self.client.worker_cutoff_state(self.resource)
        self.assertFalse(state['exists'])

    def test_delete_rejects_other_paths_force_or_body_before_transport(self):
        for path, body in [('/accounts/account/workers/scripts/demo', None),
                           ('/accounts/account/workers/scripts/demo?force=true', None),
                           ('/accounts/other/workers/scripts/demo?force=false', None),
                           ('/accounts/account/workers/scripts/demo?force=false', {}),
                           ('/accounts/account/workers/scripts/demo?force=false&x=1', None),
                           ('/accounts/account/workers/scripts/demo/other?force=false', None)]:
            with self.subTest(path=path, body=body), self.assertRaises(CloudflareError):
                self.client.request('DELETE', path, body)
        self.assertEqual(self.calls, [])

    def test_positive_stateless_state_fingerprint_and_owned_namespace_exclusion(self):
        state = self.client.worker_cutoff_state(self.resource)
        self.assertTrue(state['exists'])
        self.assertTrue(state['stateless'])
        self.assertEqual(len(state['fingerprint']), 64)
        self.namespaces = [{'id': 'namespace', 'script': 'demo', 'class': 'Counter'}]
        state = self.client.worker_cutoff_state(self.resource)
        self.assertFalse(state['stateless'])
        self.assertEqual(state['reason'], 'owned_durable_objects')

    def test_delete_timeout_is_not_retried(self):
        def timeout(request, timeout):
            self.calls.append(request)
            raise TimeoutError('synthetic-secret-never-exposed')
        self.client.transport = timeout
        with self.assertRaises(CloudflareError) as caught:
            self.client.delete_worker(self.resource)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(str(caught.exception), 'transport_unavailable')

    def action_fixture(self, action='delete_worker'):
        self.now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        self.writer_token = Path(self.tmp.name) / 'writer'
        self.writer_token.write_text('synthetic-writer-token')
        self.writer_token.chmod(0o600)
        manifest_file = Path(self.tmp.name) / 'approval.json'
        budget = GuardBudget(Decimal('1'), 'workers_usage_estimate', Decimal('0.3'), Decimal('0.02'),
                             Decimal('50'), 'synthetic-price-provenance', '2026-10-27', True, True)
        resource = replace(self.resource, permitted_action=action, budget=budget,
                           executor_token_file=self.writer_token, approved_manifest_file=manifest_file)
        self.account = AccountConfig('fixture', 'account', self.token, 1, Decimal(0), 'USD')
        approval = {'version': 2, 'approval_reference': 'synthetic-approval',
                    'expires_at': (self.now + timedelta(days=1)).isoformat(),
                    'resource': {'account_id': 'account', 'product': 'workers', 'resource_id': 'demo'},
                    'action': action, 'budget_digest': policy_digest(resource, self.account),
                    'accept_approximate': True, 'accept_partial': True,
                    'acknowledge_deletion': True, 'restore_source_confirmed': True,
                    'stateless_worker_confirmed': True}
        content = json.dumps(approval).encode()
        manifest_file.write_bytes(content)
        self.resource = replace(resource, approved_manifest_digest=hashlib.sha256(content).hexdigest())
        self.config = Config('enforce', (self.account,), (self.resource,))
        row = Observation(self.resource.key, 'workers.requests', Decimal('1000000'), 'requests',
                          self.now - timedelta(minutes=1), self.now, self.now, self.now,
                          'approximate', 'graphql-workers-adaptive', True, None)
        self.snapshot = Snapshot('account', (), (), (), {}, self.now, (row,))
        self.store = Store(Path(self.tmp.name) / 'state')
        self.addCleanup(self.store.db.close)
        self.writer_calls = 0

    def writer(self, token):
        self.assertIsNotNone(self.store.intent(self.resource.key), 'intent must be durable before writer access')
        self.assertEqual(token, self.writer_token)
        self.writer_calls += 1
        return Client(token, account_id='account', transport=self.transport)

    def test_budget_action_deletes_and_reconciles_without_second_writer(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
            again = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                      self.writer, self.store, self.now)
        self.assertEqual(result.status, 'worker_deleted')
        self.assertEqual(again.status, 'worker_deleted')
        self.assertEqual(self.writer_calls, 1)
        self.assertEqual(len([r for r in self.calls if r.method == 'DELETE']), 1)

    def test_budget_preview_never_opens_writer_or_persists_intent_or_ledger(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        before = self.store.db.total_changes
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now, preview=True)
        self.assertEqual(result.status, 'not_applied')
        self.assertEqual(self.store.db.total_changes, before)
        self.assertEqual(self.writer_calls, 0)

    def test_budget_endpoint_success_is_narrow_api_confirmation(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture('disable_worker_endpoints')
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
        self.assertEqual(result.status, 'endpoints_disabled')
        self.assertEqual(result.verification['scope'], 'workers.dev_and_preview_only')
        self.assertNotIn('DELETE', [r.method for r in self.calls])

    def test_ambiguous_delete_stays_uncertain_and_never_reopens_writer(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        normal = self.transport
        def ambiguous(request, timeout):
            if request.method == 'DELETE':
                self.calls.append(request)
                raise TimeoutError('synthetic-private-detail')
            return normal(request, timeout)
        self.transport = ambiguous
        self.client.transport = ambiguous
        with patch('cfguard.cutoff.validate_admin_file'):
            first = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                      self.writer, self.store, self.now)
            second = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
        self.assertEqual((first.status, second.status), ('uncertain', 'uncertain'))
        self.assertEqual(self.writer_calls, 1)
        self.assertNotIn('synthetic-private-detail', repr(first))

    def test_crash_after_intent_reconciles_without_any_write(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        self.store.save_intent(self.resource.key, {'approval_version': 2, 'action': 'delete_worker',
            'manifest_digest': self.resource.approved_manifest_digest, 'budget_digest': policy_digest(self.resource, self.account)})
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
        self.assertEqual(result.status, 'uncertain')
        self.assertEqual(self.writer_calls, 0)
        self.assertFalse(any(r.method == 'DELETE' for r in self.calls))

    def test_prewrite_drift_blocks_factory_after_durable_intent(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        normal = self.transport
        lists = 0
        def drifting(request, timeout):
            nonlocal lists
            if request.full_url.endswith('/workers/scripts'):
                lists += 1
                if lists == 2:
                    self.script['etag'] = 'different-content'
            return normal(request, timeout)
        self.client.transport = drifting
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
        self.assertEqual(result.status, 'not_applied')
        self.assertEqual(result.verification['reason'], 'prewrite_drift')
        self.assertEqual(self.writer_calls, 0)
        self.assertEqual(self.store.intent(self.resource.key)['status'], 'not_applied')
        with patch('cfguard.cutoff.validate_admin_file'):
            repeated = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                         self.writer, self.store, self.now)
        self.assertEqual(repeated.status, 'not_applied')
        self.assertEqual(self.writer_calls, 0)

    def test_malformed_runtime_metadata_is_sanitized(self):
        normal = self.transport
        def malformed(request, timeout):
            if '/versions/' in request.full_url:
                return reply({'resources': {'bindings': [], 'script': self.script, 'script_runtime': None}})
            return normal(request, timeout)
        self.client.transport = malformed
        with self.assertRaisesRegex(CloudflareError, 'worker_version_schema'):
            self.client.worker_cutoff_state(self.resource)

    def test_pinned_approval_identity_expiry_and_deletion_acks_are_required(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        original = json.loads(self.resource.approved_manifest_file.read_text())
        changes = [{'acknowledge_deletion': False}, {'restore_source_confirmed': False},
                   {'stateless_worker_confirmed': False}, {'accept_partial': False},
                   {'expires_at': self.now.isoformat()}, {'budget_digest': '0' * 64},
                   {'resource': {'account_id': 'other', 'product': 'workers', 'resource_id': 'demo'}},
                   {'version': True}, {'unknown_field': 'denied'}]
        for change in changes:
            with self.subTest(change=change):
                content = json.dumps({**original, **change}).encode()
                self.resource.approved_manifest_file.write_bytes(content)
                resource = replace(self.resource, approved_manifest_digest=hashlib.sha256(content).hexdigest())
                config = replace(self.config, resources=(resource,))
                with patch('cfguard.cutoff.validate_admin_file'):
                    result = run_budget_cutoff(config, resource, self.snapshot, self.client,
                                               self.writer, self.store, self.now)
                self.assertEqual(result.status, 'not_applied')
                self.assertEqual(self.writer_calls, 0)
                self.assertIsNone(self.store.intent(resource.key))
        self.assertEqual(self.calls, [])

    def test_manifest_replacement_without_repin_is_denied(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        self.resource.approved_manifest_file.write_text('{}')
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
        self.assertEqual(result.verification['reason'], 'approval_digest_mismatch')
        self.assertEqual(self.writer_calls, 0)

    def test_observe_never_reads_or_opens_executor(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        result = run_budget_cutoff(replace(self.config, mode='observe'), self.resource,
                                  self.snapshot, self.client, self.writer, self.store, self.now)
        self.assertEqual(result.status, 'not_applied')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.writer_calls, 0)

    def test_owned_do_export_is_rejected_even_without_self_binding(self):
        self.settings['exports'] = {'Counter': {'type': 'durable-object', 'storage': 'sqlite'}}
        state = self.client.worker_cutoff_state(self.resource)
        self.assertFalse(state['stateless'])

    def test_missing_namespace_pagination_cannot_prove_stateless(self):
        normal = self.transport
        self.client.transport = lambda request, timeout: reply([]) if '/namespaces?' in request.full_url else normal(request, timeout)
        with self.assertRaisesRegex(CloudflareError, 'namespace_inventory_incomplete'):
            self.client.worker_cutoff_state(self.resource)

    def test_cpu_limit_absence_does_not_invalidate_explicit_planning_reserve(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        self.settings.pop('limits')
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now)
        self.assertEqual(result.status, 'worker_deleted')

    def test_official_empty_bindings_map_and_default_fetch_export_are_supported(self):
        normal = self.transport
        def official_shape(request, timeout):
            if '/versions/' in request.full_url:
                return reply({'resources': {'bindings': {}, 'script': self.script, 'script_runtime': {
                    'exports': {'default': {'type': 'worker', 'state': 'created', 'cache': {'enabled': False}}}}}})
            return normal(request, timeout)
        self.client.transport = official_shape
        self.assertTrue(self.client.worker_cutoff_state(self.resource)['stateless'])

    def test_approval_expiring_during_preflight_never_opens_writer(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        tick = [self.now]
        normal = self.transport
        settings_reads = 0
        def slow(request, timeout):
            nonlocal settings_reads
            if request.full_url.endswith('/settings'):
                settings_reads += 1
                if settings_reads == 2:
                    tick[0] = self.now + timedelta(days=2)
            return normal(request, timeout)
        self.client.transport = slow
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now, clock=lambda: tick[0])
        self.assertEqual(result.status, 'not_applied')
        self.assertEqual(result.verification['reason'], 'approval_expired_or_invalid')
        self.assertEqual(self.writer_calls, 0)

    def test_guard_period_rollover_during_preflight_never_opens_writer(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        approval = json.loads(self.resource.approved_manifest_file.read_bytes())
        approval['expires_at'] = '2026-12-01T00:00:00Z'
        content = json.dumps(approval).encode()
        self.resource.approved_manifest_file.write_bytes(content)
        self.resource = replace(self.resource, approved_manifest_digest=hashlib.sha256(content).hexdigest())
        self.config = replace(self.config, resources=(self.resource,))
        tick = [self.now]
        normal = self.transport
        settings_reads = 0
        def slow(request, timeout):
            nonlocal settings_reads
            if request.full_url.endswith('/settings'):
                settings_reads += 1
                if settings_reads == 2:
                    tick[0] = datetime(2026, 11, 1, tzinfo=timezone.utc)
            return normal(request, timeout)
        self.client.transport = slow
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       self.writer, self.store, self.now, clock=lambda: tick[0])
        self.assertEqual(result.status, 'not_applied')
        self.assertEqual(result.verification['reason'], 'prewrite_budget_changed')
        self.assertEqual(self.writer_calls, 0)

    def test_approval_expiring_while_executor_is_constructed_still_blocks_mutation(self):
        from cfguard.cutoff import run_budget_cutoff
        self.action_fixture()
        tick = [self.now]
        def delayed_writer(path):
            client = self.writer(path)
            tick[0] = self.now + timedelta(days=2)
            return client
        with patch('cfguard.cutoff.validate_admin_file'):
            result = run_budget_cutoff(self.config, self.resource, self.snapshot, self.client,
                                       delayed_writer, self.store, self.now, clock=lambda: tick[0])
        self.assertEqual(result.status, 'not_applied')
        self.assertFalse(any(r.method == 'DELETE' for r in self.calls))


if __name__ == '__main__':
    unittest.main()
