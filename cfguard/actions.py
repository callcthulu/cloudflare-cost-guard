"""Only an approved standalone Worker's public endpoints may be disabled.

No provider write is retried automatically. Pending intents are reconciled by
read-back/probes, including when a prior process died after an applied write.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from .cloudflare import CloudflareError
from .config import _pairs, validate_admin_file
from .models import ActionPlan, ActionResult, Config, Decision, ResourceConfig
from .policy import _quality, evidence_id


class ActionBlocked(ValueError):
    """Sanitized denial code; never includes raw provider/configuration data."""


def inventory_digest(inventory):
    return sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class _PreparedPlan(ActionPlan):
    proposal: Decision
    config: Config
    resource: ResourceConfig
    manifest_digest: str
    inventory_json: str
    endpoints: tuple[str, ...]


def _require(condition, code):
    if not condition: raise ActionBlocked(code)


def _fields(value, names):
    _require(isinstance(value, dict) and set(value) == set(names), "manifest_schema")


def _resource_record(value):
    _fields(value, {"account_id", "product", "resource_id"})
    _require(all(isinstance(v, str) and v for v in value.values()), "manifest_identity")
    return value


def _endpoint(url):
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        return (parsed.scheme == "https" and parsed.username is None and parsed.password is None
                and parsed.port in {None, 443} and hostname.endswith(".workers.dev")
                and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname) is not None
                and all(label and not label.startswith("-") and not label.endswith("-") for label in hostname.split("."))
                and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
    except (ValueError, TypeError, AttributeError):
        return False


def _manifest(resource, *, require_current=True):
    path = resource.approved_manifest_file
    _require(path is not None and resource.approved_manifest_digest is not None, "approval_missing")
    path = Path(path)
    try:
        validate_admin_file(path)
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode), "unsafe_manifest")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            actual = os.fstat(handle.fileno())
            _require((actual.st_dev, actual.st_ino) == (before.st_dev, before.st_ino), "manifest_changed")
            content = handle.read(65537)
            after = os.fstat(handle.fileno())
            _require((actual.st_mtime_ns, actual.st_size) == (after.st_mtime_ns, after.st_size), "manifest_changed")
        _require(len(content) <= 65536, "manifest_too_large")
        digest = sha256(content).hexdigest()
        _require(digest == resource.approved_manifest_digest, "approval_digest_mismatch")
        manifest = json.loads(content, object_pairs_hook=_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ActionBlocked:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ActionBlocked("manifest_unreadable_or_unsafe") from None
    _fields(manifest, {"version", "approval_reference", "expires_at", "resource", "action", "trigger", "baseline_digest", "protected_resources", "endpoints"})
    _require(type(manifest["version"]) is int and manifest["version"] == 1, "manifest_version")
    _require(isinstance(manifest["approval_reference"], str) and manifest["approval_reference"].strip()
             and not any(ord(c) < 32 for c in manifest["approval_reference"]), "approval_reference_missing")
    try:
        expires = datetime.fromisoformat(manifest["expires_at"].replace("Z", "+00:00"))
        _require(expires.tzinfo is not None and expires.utcoffset().total_seconds() == 0, "approval_expiry_invalid")
        _require(not require_current or expires > _now(), "approval_expired")
    except (ValueError, TypeError, AttributeError):
        raise ActionBlocked("approval_expired_or_invalid") from None
    return manifest, digest


def _inventory(resource, account, client, manifest):
    inventory = client.worker_endpoint_state(resource, zones=account.zones)
    _require(isinstance(inventory, dict), "inventory_schema")
    _require(inventory.get("identity") == {"account_id": resource.key.account_id, "script_name": resource.key.resource_id}, "inventory_identity")
    _require(inventory.get("complete") is True, "inventory_incomplete")
    for field in ("routes", "custom_domains", "internal_triggers"):
        _require(isinstance(inventory.get(field), (tuple, list)) and not inventory[field], "unsupported_endpoint_layout")
    _require(not inventory.get("schedules"), "internal_trigger_present")
    _require(all(type(inventory.get(flag)) is bool for flag in ("enabled", "previews_enabled")), "endpoint_flags_unknown")
    endpoints = inventory.get("endpoints")
    _require(isinstance(endpoints, (list, tuple)) and endpoints and len(set(endpoints)) == len(endpoints)
             and all(_endpoint(url) for url in endpoints), "endpoints_unknown")
    _require(set(endpoints) == set(manifest["endpoints"]), "endpoint_inventory_drift")
    # Only the two disable flags may differ during crash/timeout reconciliation.
    # execute requires the exact enabled baseline before a new intent can write.
    baseline = dict(inventory, enabled=True, previews_enabled=True)
    _require(inventory_digest(baseline) == manifest["baseline_digest"], "baseline_drift")
    return inventory


def preflight(proposal, config, client):
    """Validate an approval and fresh exact raw trigger; performs no write."""
    try:
        _require(config.mode == "enforce", "mode_not_enforce")
        _require(proposal.key.scope == "resource" and proposal.key.product == "workers", "unsupported_scope")
        _require(proposal.status == "tripped" and proposal.reason_code in {"threshold_crossed", "latched_threshold_crossed"}
                 and proposal.proposed_action == "disable_worker_endpoints", "invalid_proposal")
        resources = [r for r in config.resources if r.key == proposal.key]
        accounts = [a for a in config.accounts if a.account_id == proposal.key.account_id]
        _require(len(resources) == 1 and len(accounts) == 1, "resource_not_uniquely_enrolled")
        resource, account = resources[0], accounts[0]
        _require(resource.permitted_action == proposal.proposed_action, "action_not_enrolled")
        _require(resource.executor_token_file is not None and Path(resource.executor_token_file) != Path(account.read_token_file), "separate_executor_required")
        manifest, digest = _manifest(resource)
        identity = _resource_record(manifest["resource"])
        _require(identity == {"account_id": resource.key.account_id, "product": resource.key.product, "resource_id": resource.key.resource_id}, "approval_identity_mismatch")
        _require(manifest["action"] == proposal.proposed_action, "approval_action_mismatch")
        protected = manifest["protected_resources"]
        _require(isinstance(protected, list), "protected_resources_missing")
        _require(all(_resource_record(item) != identity for item in protected), "protected_resource")
        endpoints = manifest["endpoints"]
        _require(isinstance(endpoints, list) and endpoints and len(set(endpoints)) == len(endpoints)
                 and all(_endpoint(url) for url in endpoints), "approval_endpoints_invalid")
        _require(isinstance(manifest["baseline_digest"], str) and re.fullmatch(r"[a-f0-9]{64}", manifest["baseline_digest"]), "baseline_digest_invalid")
        trigger = manifest["trigger"]
        _fields(trigger, {"metric", "limit", "unit", "window_seconds"})
        _require(trigger["metric"] in {"workers.requests", "workers.cpu_ms"}, "unsupported_trigger")
        unit = "requests" if trigger["metric"] == "workers.requests" else "milliseconds"
        _require(trigger["unit"] == unit and proposal.metric == trigger["metric"] and proposal.unit == unit
                 and proposal.currency is None, "trigger_dimension_mismatch")
        _require(type(trigger["window_seconds"]) is int and 1 <= trigger["window_seconds"] <= 3600, "trigger_window_invalid")
        _require(isinstance(trigger["limit"], str), "trigger_limit_invalid")
        limit = Decimal(trigger["limit"])
        _require(limit.is_finite() and limit >= 0, "trigger_limit_invalid")
        thresholds = [t for t in resource.thresholds if t.metric == trigger["metric"]]
        _require(len(thresholds) == 1 and thresholds[0].limit == limit and thresholds[0].unit == unit, "approval_threshold_mismatch")
        observation = client.fresh_trigger(resource, now=_now())
        _require(observation.key == resource.key and observation.metric == trigger["metric"]
                 and observation.complete is True and observation.sampled is False
                 and observation.source and _quality(observation, _now(), account.max_data_age_seconds, unit) == "good", "trigger_not_exact_fresh_complete")
        _require((observation.period_end - observation.period_start).total_seconds() == trigger["window_seconds"], "trigger_window_mismatch")
        _require(observation.value > 0 and observation.value >= limit, "trigger_not_crossed")
        _require(proposal.evidence_ids == (evidence_id(observation),) and proposal.value == observation.value
                 and (proposal.period_start, proposal.period_end) == (observation.period_start, observation.period_end), "trigger_evidence_changed")
        inventory = _inventory(resource, account, client, manifest)
        return _PreparedPlan(proposal.key, proposal.proposed_action, manifest["baseline_digest"], manifest["approval_reference"],
                             proposal.evidence_ids, proposal, config, resource, digest,
                             json.dumps(inventory, sort_keys=True, separators=(",", ":")), tuple(endpoints))
    except ActionBlocked:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, CloudflareError):
        raise ActionBlocked("preflight_unavailable_or_invalid") from None


def execute(plan, client, store):
    """Persist intent before one write; reconcile actual state after ambiguity."""
    _require(isinstance(plan, _PreparedPlan), "prepared_plan_required")
    if store.intent(plan.key):
        # Old trigger evidence is never authorization for another write. Existing
        # intents need only read-only reconciliation, even after the spike ends.
        return reconcile(plan.resource, plan.config, client, store)
    if hasattr(client, "token_file"):
        _require(Path(client.token_file) == Path(plan.resource.executor_token_file), "wrong_executor_credential")
    current = preflight(plan.proposal, plan.config, client)
    _require((current.key, current.action, current.baseline_digest, current.approval_reference, current.manifest_digest)
             == (plan.key, plan.action, plan.baseline_digest, plan.approval_reference, plan.manifest_digest), "plan_changed")
    payload = {"action": plan.action, "baseline_digest": plan.baseline_digest,
               "approval_reference": plan.approval_reference, "manifest_digest": plan.manifest_digest,
               "evidence_ids": plan.evidence_ids}
    _require(inventory_digest(json.loads(current.inventory_json)) == plan.baseline_digest, "baseline_flags_changed_without_intent")
    intent = store.save_intent(plan.key, payload)
    try:
        # Record intent first, then check all current facts again immediately
        # before the sole allowed mutation. Operator drift blocks the call.
        latest = preflight(plan.proposal, plan.config, client)
        _require(latest.manifest_digest == plan.manifest_digest
                 and inventory_digest(json.loads(latest.inventory_json)) == plan.baseline_digest, "prewrite_drift")
    except ActionBlocked:
        result = ActionResult(plan.key, "failed", {}, {"scope": "workers.dev_and_preview_only", "reason": "prewrite_validation_failed"}, intent["attempt_id"])
        store.finish_intent(plan.key, result)
        return result
    try:
        client.disable_worker_endpoints(plan.resource)
    except (OSError, TimeoutError, ValueError, CloudflareError):
        # The provider may have applied the write before the error. Never
        # resend it based solely on transport outcome.
        pass
    return reconcile(plan.resource, plan.config, client, store)


def reconcile(resource, config, client, store):
    """Read-only provider reconciliation of a persisted intent; never retries.

    The original spike may have ended after an applied cutoff, so fresh usage
    evidence is unnecessary for these reads. A missing intent is always denied.
    """
    _require(config.mode == "enforce" and resource in config.resources, "reconciliation_not_enrolled")
    intent = store.intent(resource.key)
    _require(intent is not None, "reconciliation_intent_missing")
    if intent["status"] == "verified_public_cutoff":
        saved = intent["result"]
        return ActionResult(resource.key, saved["status"], saved["observed_endpoint_flags"], saved["verification"], intent["attempt_id"])
    flags, verification = {}, {"scope": "workers.dev_and_preview_only", "internal_invocations": "not_proven_stopped"}
    status = "partial"
    try:
        accounts = [a for a in config.accounts if a.account_id == resource.key.account_id]
        _require(len(accounts) == 1, "reconciliation_account_not_unique")
        account = accounts[0]
        manifest, digest = _manifest(resource, require_current=False)
        _require(digest == intent.get("manifest_digest")
                 and intent.get("baseline_digest") == manifest["baseline_digest"]
                 and intent.get("approval_reference") == manifest["approval_reference"]
                 and intent.get("action") == manifest["action"] == resource.permitted_action == "disable_worker_endpoints", "intent_approval_mismatch")
        _require(_resource_record(manifest["resource"]) == {"account_id": resource.key.account_id, "product": resource.key.product, "resource_id": resource.key.resource_id}
                 and resource.key.scope == "resource" and resource.key.product == "workers", "reconciliation_identity_mismatch")
        actual = _inventory(resource, account, client, manifest)
        flags = {flag: actual[flag] for flag in ("enabled", "previews_enabled")}
        verification["identity"] = "matched"
        verification["inventory"] = "complete"
        probes = {url: client.probe_endpoint(url) for url in manifest["endpoints"]}
        verification["public_endpoints"] = probes
        if all(value is False for value in flags.values()) and all(value == "blocked" for value in probes.values()):
            status = "verified_public_cutoff"
            verification["verified_at"] = _now().isoformat()
        elif all(value is True for value in flags.values()):
            status = "failed"
    except (OSError, ValueError, TypeError, KeyError, AttributeError, CloudflareError):
        verification["reason"] = "verification_incomplete"
    result = ActionResult(resource.key, status, flags, verification, intent["attempt_id"])
    store.finish_intent(resource.key, result)
    return result
