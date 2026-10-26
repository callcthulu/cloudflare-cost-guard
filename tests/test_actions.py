import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from cfguard.actions import ActionBlocked, execute, inventory_digest, preflight, reconcile
from cfguard.models import AccountConfig, Config, Decision, Observation, ResourceConfig, ResourceKey, ResourceState, Threshold
from cfguard.policy import evaluate, evidence_id
from cfguard.state import Store

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
KEY = ResourceKey("a" * 32, "resource", "workers", "disposable")
URLS = ["https://disposable.sandbox.workers.dev", "https://preview-disposable.sandbox.workers.dev"]


class FakeClient:
    def __init__(self, observation, inventory):
        self.observation = observation
        self.inventory = copy.deepcopy(inventory)
        self.calls = []
        self.mutations = 0
        self.behavior = "normal"
        self.probe = "blocked"
        self.inventory_reads = 0
        self.on_inventory = None
        self.protected = {"access": {"login": True}, "dns": ["original"], "other_worker": {"enabled": True}}

    def fresh_trigger(self, resource, *, now=None):
        self.calls.append(("fresh", resource.key))
        return self.observation

    def worker_endpoint_state(self, resource, *, zones=()):
        self.calls.append(("inventory", resource.key))
        self.inventory_reads += 1
        if self.on_inventory: self.on_inventory(self)
        return copy.deepcopy(self.inventory)

    def disable_worker_endpoints(self, resource):
        self.calls.append(("write", resource.key, {"enabled": False, "previews_enabled": False}))
        self.mutations += 1
        if self.behavior != "not_applied":
            self.inventory.update(enabled=False, previews_enabled=False)
        if self.behavior == "timeout": raise TimeoutError("SECRET_PROVIDER_PAYLOAD")
        if self.behavior == "crash": raise KeyboardInterrupt("simulated process death")
        return {"enabled": False, "previews_enabled": False}

    def probe_endpoint(self, url):
        self.calls.append(("probe", url))
        return self.probe


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.manifest_path = self.folder / "approval.json"
        self.observation = Observation(KEY, "workers.requests", Decimal("200"), "requests", NOW - timedelta(minutes=5), NOW,
            NOW, NOW, "good", "exact-fixture", True, False)
        self.inventory = {"identity": {"account_id": KEY.account_id, "script_name": KEY.resource_id},
            "enabled": True, "previews_enabled": True, "routes": [], "custom_domains": [],
            "internal_triggers": [], "complete": True, "endpoints": URLS}
        self.manifest = {"version": 1, "approval_reference": "synthetic-owner-review-1",
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "resource": {"account_id": KEY.account_id, "product": KEY.product, "resource_id": KEY.resource_id},
            "action": "disable_worker_endpoints", "trigger": {"metric": "workers.requests", "limit": "100",
                "unit": "requests", "window_seconds": 300}, "baseline_digest": inventory_digest(self.inventory),
            "protected_resources": [], "endpoints": URLS}
        self.account = AccountConfig("sandbox", KEY.account_id, self.folder / "read.token", 1, Decimal("0"), "USD")
        self.resource = ResourceConfig(KEY, "Disposable", thresholds=(Threshold("workers.requests", Decimal("100"), "requests"),),
            permitted_action="disable_worker_endpoints", executor_token_file=self.folder / "execute.token",
            approved_manifest_file=self.manifest_path)
        self.config = Config("enforce", (self.account,), (self.resource,), self.folder / "state")
        self.proposal = Decision(KEY, "tripped", "threshold_crossed", "disable_worker_endpoints", (evidence_id(self.observation),),
            "workers.requests", self.observation.value, "requests", period_start=self.observation.period_start, period_end=NOW)
        self.client = FakeClient(self.observation, self.inventory)
        self.write_manifest()
        self.clock = patch("cfguard.actions._now", return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)
        # These are synthetic approval fixtures, not administrator-owned deployed
        # files. Permission behavior has separate real/synthetic negative tests.
        self.admin_fixture = patch("cfguard.actions.validate_admin_file")
        self.admin_fixture.start(); self.addCleanup(self.admin_fixture.stop)

    def write_manifest(self):
        payload = json.dumps(self.manifest, sort_keys=True).encode()
        self.manifest_path.write_bytes(payload)
        self.resource = replace(self.resource, approved_manifest_digest=hashlib.sha256(payload).hexdigest())
        self.config = replace(self.config, resources=(self.resource,))

    def test_observe_missing_approval_wrong_identity_and_action_never_write(self):
        configs = [replace(self.config, mode="observe"), replace(self.config, resources=()),
            replace(self.config, resources=(replace(self.resource, approved_manifest_file=None),)),
            replace(self.config, resources=(replace(self.resource, executor_token_file=None),)),
            replace(self.config, resources=(replace(self.resource, executor_token_file=self.account.read_token_file),)),
            replace(self.config, resources=(replace(self.resource, approved_manifest_digest="0" * 64),))]
        for config in configs:
            with self.subTest(config=config), self.assertRaises(ActionBlocked): preflight(self.proposal, config, self.client)
        for proposal in (replace(self.proposal, proposed_action="delete_worker"),
                         replace(self.proposal, key=ResourceKey(KEY.account_id, "account", "workers")),
                         replace(self.proposal, key=ResourceKey("b" * 32, "resource", "workers", "disposable")),
                         replace(self.proposal, status="warning"), replace(self.proposal, evidence_ids=())):
            with self.subTest(proposal=proposal), self.assertRaises(ActionBlocked): preflight(proposal, self.config, self.client)
        self.assertEqual(self.client.mutations, 0)

    def test_manifest_protection_expiry_threshold_and_endpoint_mismatches_block(self):
        changes = [lambda m: m.update(approval_reference=""),
            lambda m: m.update(expires_at=NOW.isoformat()),
            lambda m: m["resource"].update(resource_id="other"),
            lambda m: m.update(action="delete_worker"),
            lambda m: m["trigger"].update(limit="99"),
            lambda m: m["trigger"].update(window_seconds=60),
            lambda m: m.update(protected_resources=[m["resource"]]),
            lambda m: m.update(endpoints=["https://origin.example"]),
            lambda m: m.update(endpoints=["http://disposable.sandbox.workers.dev"]),
            lambda m: m.update(endpoints=["https://user:pass@disposable.sandbox.workers.dev"]),
            lambda m: m.update(unexpected="field")]
        original = copy.deepcopy(self.manifest)
        for change in changes:
            self.manifest = copy.deepcopy(original); change(self.manifest); self.write_manifest()
            with self.subTest(manifest=self.manifest), self.assertRaises(ActionBlocked): preflight(self.proposal, self.config, self.client)
        self.assertEqual(self.client.mutations, 0)

    def test_sampled_stale_partial_unpriced_unknown_units_and_scope_cannot_write(self):
        variants = [replace(self.observation, sampled=True), replace(self.observation, sampled=None),
            replace(self.observation, complete=False), replace(self.observation, quality="approximate"),
            replace(self.observation, data_through=NOW - timedelta(hours=1)),
            replace(self.observation, value=None), replace(self.observation, unit="unknown"),
            replace(self.observation, metric="estimated_cost"),
            replace(self.observation, key=ResourceKey(KEY.account_id, "account", "workers")),
            replace(self.observation, value=Decimal("50"))]
        for observation in variants:
            self.client.observation = observation
            proposal = replace(self.proposal, evidence_ids=(evidence_id(observation),))
            with self.subTest(observation=observation), self.assertRaises(ActionBlocked): preflight(proposal, self.config, self.client)
        self.assertEqual(self.client.mutations, 0)

    def test_routes_domains_internal_unknown_inventory_and_identity_drift_block(self):
        for field, value in (("routes", [{"pattern": "protected.example/*"}]), ("custom_domains", ["protected.example"]),
                             ("internal_triggers", "unknown"), ("internal_triggers", ["cron"]), ("complete", False),
                             ("identity", {"account_id": KEY.account_id, "script_name": "other"})):
            self.client.inventory = copy.deepcopy(self.inventory); self.client.inventory[field] = value
            with self.subTest(field=field), self.assertRaises(ActionBlocked): preflight(self.proposal, self.config, self.client)
        self.assertEqual(self.client.mutations, 0)

    def test_only_approved_flags_changed_and_public_scope_verified(self):
        protected = copy.deepcopy(self.client.protected)
        plan = preflight(self.proposal, self.config, self.client)
        with Store(self.config.state_dir) as store:
            result = execute(plan, self.client, store)
            self.assertEqual(result.status, "verified_public_cutoff")
            self.assertEqual(store.intent(KEY)["status"], "verified_public_cutoff")
        self.assertEqual(self.client.mutations, 1)
        self.assertEqual([c for c in self.client.calls if c[0] == "write"],
                         [("write", KEY, {"enabled": False, "previews_enabled": False})])
        self.assertEqual(protected, self.client.protected)
        self.assertEqual(result.verification["scope"], "workers.dev_and_preview_only")

    def test_timeout_after_applied_write_reconciles_with_one_mutation(self):
        self.client.behavior = "timeout"
        plan = preflight(self.proposal, self.config, self.client)
        with Store(self.config.state_dir) as store:
            result = execute(plan, self.client, store)
        self.assertEqual(result.status, "verified_public_cutoff")
        self.assertEqual(self.client.mutations, 1)
        self.assertNotIn("SECRET", str(result))

    def test_crash_restart_reconciles_pending_and_completed_never_rewrites(self):
        self.client.behavior = "crash"
        plan = preflight(self.proposal, self.config, self.client)
        with Store(self.config.state_dir) as store:
            with self.assertRaises(KeyboardInterrupt): execute(plan, self.client, store)
            self.assertEqual(store.intent(KEY)["status"], "pending")
        self.client.behavior = "normal"
        with Store(self.config.state_dir) as store:
            recovered = execute(preflight(self.proposal, self.config, self.client), self.client, store)
            repeated = execute(preflight(self.proposal, self.config, self.client), self.client, store)
        self.assertEqual(recovered.status, "verified_public_cutoff")
        self.assertEqual(repeated.attempt_id, recovered.attempt_id)
        self.assertEqual(self.client.mutations, 1)

    def test_partial_verification_stays_latched_and_no_automatic_retry(self):
        self.client.probe = "unknown"
        with Store(self.config.state_dir) as store:
            result = execute(preflight(self.proposal, self.config, self.client), self.client, store)
            self.assertEqual(result.status, "partial")
            self.assertEqual(store.prior()[KEY].execution_status, "partial")
            repeated = execute(preflight(self.proposal, self.config, self.client), self.client, store)
        self.assertEqual(repeated.status, "partial")
        self.assertEqual(self.client.mutations, 1)

    def test_concurrent_manifest_or_inventory_edits_prevent_mutation(self):
        plan = preflight(self.proposal, self.config, self.client)
        self.manifest_path.write_bytes(b"changed")
        with Store(self.config.state_dir) as store, self.assertRaises(ActionBlocked): execute(plan, self.client, store)
        self.write_manifest()
        self.client.inventory_reads = 0
        def drift(client):
            if client.inventory_reads == 3: client.inventory["custom_domains"] = ["operator.example"]
        self.client.on_inventory = drift
        with Store(self.config.state_dir) as store:
            result = execute(preflight(self.proposal, self.config, self.client), self.client, store)
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.client.mutations, 0)

    def test_fresh_exact_latched_trip_keeps_proposal_but_unknown_does_not(self):
        from cfguard.models import Snapshot
        prior = {KEY: ResourceState(status="tripped", dimensions={"workers.requests": "tripped"})}
        def proposal_for(observation):
            snap = Snapshot(KEY.account_id, (observation,), (), (), {}, NOW)
            return next(d for d in evaluate(self.config, snap, prior) if d.key == KEY)
        self.assertEqual(proposal_for(self.observation).proposed_action, "disable_worker_endpoints")
        self.assertIsNone(proposal_for(replace(self.observation, value=None)).proposed_action)

    def test_reconcile_after_crash_needs_no_new_spike_and_never_writes(self):
        self.client.behavior = "crash"
        plan = preflight(self.proposal, self.config, self.client)
        with Store(self.config.state_dir) as store:
            with self.assertRaises(KeyboardInterrupt): execute(plan, self.client, store)
        self.client.observation = replace(self.observation, value=Decimal("0"), sampled=None)
        fresh_calls = len([c for c in self.client.calls if c[0] == "fresh"])
        with Store(self.config.state_dir) as store:
            # Expiry forbids a new mutation, but does not forbid reading back
            # the actual result of an already-authorized pending attempt.
            with patch("cfguard.actions._now", return_value=NOW + timedelta(hours=2)):
                result = reconcile(self.resource, self.config, self.client, store)
        self.assertEqual(result.status, "verified_public_cutoff")
        self.assertEqual(self.client.mutations, 1)
        self.assertEqual(len([c for c in self.client.calls if c[0] == "fresh"]), fresh_calls)

    def test_manifest_permissions_are_checked_even_with_matching_digest(self):
        from cfguard.config import ConfigError
        with patch("cfguard.actions.validate_admin_file", side_effect=ConfigError("unsafe")) as check:
            with self.assertRaises(ActionBlocked): preflight(self.proposal, self.config, self.client)
            check.assert_called_once_with(self.manifest_path)
        self.assertEqual(self.client.mutations, 0)


if __name__ == "__main__": unittest.main()
