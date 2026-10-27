"""Explicit USD guard actions, bounded approvals and one persisted write attempt.

Provider deletion is destructive. Approval enrolls an exact account/script name,
including future versions. A prewrite fingerprint narrows deployment races but
cannot eliminate them: the provider has no conditional DELETE contract.
"""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import time

from .actions import ActionBlocked, _fields, _require, _resource_record
from .budget import evaluate_budget, policy_digest
from .cloudflare import CloudflareError
from .config import _pairs, validate_admin_file
from .models import ActionResult


def _manifest(resource, account, now, *, current=True):
    _require(resource.approved_manifest_file is not None and resource.approved_manifest_digest is not None,
             'approval_missing')
    path = Path(resource.approved_manifest_file)
    try:
        validate_admin_file(path)
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode), 'unsafe_manifest')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as handle:
            actual = os.fstat(handle.fileno())
            _require((before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_gid,
                      before.st_mtime_ns, before.st_size) ==
                     (actual.st_dev, actual.st_ino, actual.st_mode, actual.st_uid, actual.st_gid,
                      actual.st_mtime_ns, actual.st_size), 'manifest_changed')
            content = handle.read(65537)
            after = os.fstat(handle.fileno())
            _require((actual.st_mtime_ns, actual.st_size) == (after.st_mtime_ns, after.st_size), 'manifest_changed')
        _require(len(content) <= 65536, 'manifest_too_large')
        digest = sha256(content).hexdigest()
        _require(digest == resource.approved_manifest_digest, 'approval_digest_mismatch')
        value = json.loads(content, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _fields(value, {'version', 'approval_reference', 'expires_at', 'resource', 'action', 'budget_digest',
                        'accept_approximate', 'accept_partial', 'acknowledge_deletion',
                        'restore_source_confirmed', 'stateless_worker_confirmed'})
        _require(type(value['version']) is int and value['version'] == 2, 'approval_version')
        reference = value['approval_reference']
        _require(isinstance(reference, str) and reference.strip()
                 and not any(ord(c) < 32 for c in reference), 'approval_reference_invalid')
        expiry = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
        _require(expiry.tzinfo is not None and expiry.utcoffset() == timedelta(0)
                 and (not current or expiry > now), 'approval_expired_or_invalid')
        _require(_resource_record(value['resource']) == {'account_id': resource.key.account_id,
                 'product': resource.key.product, 'resource_id': resource.key.resource_id}, 'approval_identity_mismatch')
        _require(value['action'] == resource.permitted_action, 'approval_action_mismatch')
        _require(value['budget_digest'] == policy_digest(resource, account), 'approval_budget_mismatch')
        flags = ('accept_approximate', 'accept_partial', 'acknowledge_deletion',
                 'restore_source_confirmed', 'stateless_worker_confirmed')
        _require(all(type(value[f]) is bool for f in flags), 'approval_flags_invalid')
        _require(value['accept_approximate'] == resource.budget.accept_approximate
                 and value['accept_partial'] == resource.budget.accept_partial, 'approval_quality_mismatch')
        if resource.permitted_action == 'delete_worker':
            _require(all(value[f] for f in flags[2:]), 'deletion_acknowledgements_missing')
        return value, digest
    except ActionBlocked:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
        raise ActionBlocked('approval_unreadable_or_invalid') from None


def _state(resource, reader):
    state = reader.worker_cutoff_state(resource)
    _require(isinstance(state, dict) and state.get('identity') == {
        'account_id': resource.key.account_id, 'script_name': resource.key.resource_id}, 'provider_identity_mismatch')
    _require(type(state.get('exists')) is bool, 'provider_existence_unknown')
    return state


def _preflight_state(resource, reader):
    state = _state(resource, reader)
    _require(state['exists'], 'worker_absent')
    _require(state.get('stateless') is True, 'stateless_worker_not_verified')
    _require(isinstance(state.get('fingerprint'), str)
             and re.fullmatch('[a-f0-9]{64}', state['fingerprint']), 'worker_fingerprint_unknown')
    _require(all(type(state.get(f)) is bool for f in ('enabled', 'previews_enabled')), 'endpoint_flags_unknown')
    return state


def _result(resource, status, reason, *, state=None, intent=None):
    scope = 'worker_script' if resource.permitted_action == 'delete_worker' else 'workers.dev_and_preview_only'
    flags = {f: state[f] for f in ('enabled', 'previews_enabled') if state is not None and type(state.get(f)) is bool}
    verification = {'scope': scope, 'reason': reason}
    if scope == 'workers.dev_and_preview_only':
        verification['internal_invocations_stopped'] = False
    return ActionResult(resource.key, status, flags, verification, intent['attempt_id'] if intent else '')


def _reconcile(resource, account, reader, store, now, *, preview=False):
    intent = store.intent(resource.key)
    try:
        _, digest = _manifest(resource, account, now, current=False)
        _require(intent.get('manifest_digest') == digest and intent.get('budget_digest') == policy_digest(resource, account)
                 and intent.get('action') == resource.permitted_action and intent.get('approval_version') == 2,
                 'intent_approval_mismatch')
        if intent.get('status') == 'not_applied':
            # This attempt stopped before mutation or received a definite auth
            # rejection with read-back. Preserve that result for manual rearm.
            saved = intent['result']
            return ActionResult(resource.key, 'not_applied', saved['observed_endpoint_flags'],
                                saved['verification'], intent['attempt_id'])
        state = _state(resource, reader)
        if resource.permitted_action == 'delete_worker' and state['exists'] is False:
            result = _result(resource, 'worker_deleted', 'authenticated_inventory_absence', intent=intent)
        elif (resource.permitted_action == 'disable_worker_endpoints' and state['exists']
              and all(state.get(f) is False for f in ('enabled', 'previews_enabled'))):
            result = _result(resource, 'endpoints_disabled', 'provider_flags_disabled', state=state, intent=intent)
        elif type(intent.get('writer_rejection')) is int and intent['writer_rejection'] in (401, 403):
            result = _result(resource, 'not_applied', 'provider_authentication_rejected_write', state=state, intent=intent)
        else:
            # A timed-out write can apply later. Presence never authorizes retry
            # or establishes that a previous provider operation did not apply.
            result = _result(resource, 'uncertain', 'provider_action_not_confirmed', state=state, intent=intent)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, CloudflareError):
        result = _result(resource, 'uncertain', 'reconciliation_unavailable', intent=intent)
    if not preview:
        store.finish_intent(resource.key, result)
    return result


def _reauthorize(config, resource, account, snapshot, store, decision, current_time, minimum_time):
    _require(current_time.tzinfo is not None and current_time.utcoffset() == timedelta(0)
             and current_time >= minimum_time, 'cutoff_clock_invalid')
    _, digest = _manifest(resource, account, current_time)
    latest = evaluate_budget(config, resource, snapshot, store, current_time, persist=False)
    _require(latest.status == 'tripped' and latest.proposed_action == resource.permitted_action
             and (latest.period_start, latest.period_end) == (decision.period_start, decision.period_end),
             'prewrite_budget_changed')
    return digest


def run_budget_cutoff(config, resource, snapshot, reader, writer_factory, store, now, *, preview=False, clock=None):
    """Recompute approved evidence; reader observes, writer performs one action.

    Preview changes no ledger/intent/outbox and never constructs the executor.
    Existing attempts are reconciled without collecting another write credential.
    """
    started = time.monotonic()
    clock = clock or (lambda: now + timedelta(seconds=time.monotonic() - started))
    intent = None
    try:
        _require(now.tzinfo is not None and now.utcoffset() == timedelta(0), 'cutoff_time_invalid')
        _require(resource in config.resources and resource.key.scope == 'resource'
                 and resource.key.product == 'workers' and resource.budget is not None, 'cutoff_not_enrolled')
        _require(resource.permitted_action in {'delete_worker', 'disable_worker_endpoints'}, 'cutoff_action_unsupported')
        _require(config.mode == 'enforce' or preview and config.mode == 'enforce-preview', 'mode_not_enforce')
        accounts = [a for a in config.accounts if a.account_id == resource.key.account_id]
        _require(len(accounts) == 1 and snapshot.account_id == resource.key.account_id, 'cutoff_account_mismatch')
        account = accounts[0]
        _require(resource.executor_token_file is not None and Path(resource.executor_token_file) != Path(accounts[0].read_token_file),
                 'separate_executor_required')
        if hasattr(reader, 'token_file'):
            _require(Path(reader.token_file) == Path(accounts[0].read_token_file), 'wrong_reader_credential')
        intent = store.intent(resource.key)
        if intent:
            return _reconcile(resource, account, reader, store, clock(), preview=preview)
        current_time = clock()
        _require(current_time.tzinfo is not None and current_time.utcoffset() == timedelta(0)
                 and current_time >= now, 'cutoff_clock_invalid')
        manifest, digest = _manifest(resource, account, current_time)
        decision = evaluate_budget(config, resource, snapshot, store, current_time, persist=False)
        _require(decision.status == 'tripped' and decision.proposed_action == resource.permitted_action
                 and decision.metric == 'guard_cost_usd' and decision.currency == 'USD', 'guard_budget_not_reached')
        current = _preflight_state(resource, reader)
        if preview:
            return _result(resource, 'not_applied', 'preview_eligible', state=current)
        intent = store.save_intent(resource.key, {'approval_version': 2, 'action': resource.permitted_action,
            'budget_digest': policy_digest(resource, account), 'manifest_digest': digest,
            'approval_reference': manifest['approval_reference'], 'fingerprint': current['fingerprint'],
            'evidence_ids': decision.evidence_ids})
        # All read checks remain on the read token, including the immediate
        # fingerprint comparison. The write token needs no analytics permissions.
        latest = _preflight_state(resource, reader)
        latest_time = clock()
        latest_digest = _reauthorize(config, resource, account, snapshot, store, decision, latest_time, current_time)
        _require(latest_digest == digest and latest['fingerprint'] == current['fingerprint'], 'prewrite_drift')
        writer = writer_factory(Path(resource.executor_token_file))
        _require(Path(writer.token_file) == Path(resource.executor_token_file), 'wrong_executor_credential')
        # Construction can also take time; no network write or token read has
        # occurred yet on the real Client. Check again at the mutation boundary.
        _reauthorize(config, resource, account, snapshot, store, decision, clock(), latest_time)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, CloudflareError) as error:
        reason = str(error) if isinstance(error, ActionBlocked) else 'cutoff_preflight_unavailable'
        result = _result(resource, 'not_applied', reason, intent=intent)
        if intent and not preview:
            store.finish_intent(resource.key, result)
        return result
    try:
        if resource.permitted_action == 'delete_worker':
            writer.delete_worker(resource)
        else:
            writer.disable_worker_endpoints(resource)
    except CloudflareError as error:
        if str(error) in ('http_401', 'http_403'):
            store.note_write_rejection(resource.key, int(str(error)[5:]))
    except (OSError, TimeoutError, ValueError):
        pass
    return _reconcile(resource, account, reader, store, clock())
