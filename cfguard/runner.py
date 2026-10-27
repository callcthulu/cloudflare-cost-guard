"""One-shot orchestration with bounded execution and sanitized output."""
import argparse
import hashlib
import json
import signal
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .config import ConfigError, load_config
from .config import billing_window
from .models import Decision, RatedCharge, ResourceKey, Snapshot
from .notify import deliver
from .policy import evaluate
from .state import Locked, RunLock, Store, encode, resource_label


class RunDeadline(Exception):
    pass


@contextmanager
def time_budget(seconds):
    if hasattr(signal, 'setitimer'):
        previous = signal.getsignal(signal.SIGALRM)
        def expired(*_):
            raise RunDeadline('run deadline exceeded')
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    else:
        yield  # Offline Windows testing; production requires systemd/Linux deadline.


def account_label(account_id):
    return hashlib.sha256(account_id.encode()).hexdigest()[:16]


def report_coverage(coverage):
    return {(key.split(':', 1)[0] + ':' + account_label(key.split(':', 1)[1])
             if key.startswith('subscriptions.zone:') else key): value
            for key, value in coverage.items()}


def _rated_snapshot(store, account, snapshot, now, fetch):
    cache_key = 'rated_cache:' + account.account_id
    if fetch:
        store.set_meta('rated_fetch:' + account.account_id, now.isoformat())
        metadata = {key: value for key, value in snapshot.coverage.items()
                    if key.startswith('rated_') or key.startswith('billing_')}
        store.set_meta(cache_key, encode({'rows': snapshot.rated_charges,
            'coverage': snapshot.coverage.get('rated_usage', 'unknown'),
            'metadata': metadata, 'billing_day': account.billing_day, 'fetched_at': now.isoformat()}))
        return snapshot
    cached = store.get_meta(cache_key)
    if not cached:
        return snapshot
    raw = json.loads(cached)
    rows = []
    for row in raw['rows']:
        row = dict(row)
        row['key'] = ResourceKey(**row['key'])
        row['amount'] = Decimal(row['amount']) if row['amount'] is not None else None
        for name in ('period_start', 'period_end'):
            row[name] = datetime.fromisoformat(row[name])
        rows.append(RatedCharge(**row))
    fetched_at = datetime.fromisoformat(raw['fetched_at'])
    age = (now - fetched_at).total_seconds()
    coverage = dict(snapshot.coverage)
    fresh = 0 <= age <= 3900
    metadata = raw.get('metadata', {})  # Old cache entries carry no coverage proof.
    if fresh and metadata:
        coverage.update(metadata)
    else:
        problem = 'stale_cache' if not fresh else 'cache_metadata_missing'
        coverage['billing_info'] = 'unknown:' + problem
        coverage['billing_account_coverage'] = 'unknown:' + problem
    coverage['rated_usage'] = raw['coverage'] if fresh else 'stale'
    try:
        valid_until = datetime.fromisoformat(metadata.get('billing_period_valid_until', '').replace('Z', '+00:00'))
        period_valid = (valid_until.tzinfo is not None and valid_until.utcoffset().total_seconds() == 0
                        and fetched_at <= now < valid_until <= billing_window(now, account.billing_day)[1])
    except (ValueError, TypeError, AttributeError):
        period_valid = False
    if (not fresh or not period_valid or not account.billing_period_verified
            or metadata.get('billing_info') != 'parsed' or metadata.get('billing_account_coverage') != 'covered'
            or raw.get('billing_day') != account.billing_day
            or billing_window(fetched_at, account.billing_day) != billing_window(now, account.billing_day)):
        coverage['billing_period'] = 'unverified'
        coverage.pop('billing_period_valid_until', None)
    return replace(snapshot, rated_charges=tuple(rows), coverage=coverage)


def run_once(config, *, now=None, client_factory=None, probe=False, preview=False):
    from .cloudflare import Client, CloudflareError
    now = now or datetime.now(timezone.utc)
    factory = client_factory or Client
    started = time.monotonic()
    report = {'mode': 'probe' if probe else 'enforce-preview' if preview else config.mode,
              'accounts': [], 'scheduler': 'on_time', 'collection': 'unknown',
              'notification': {'delivered': 0, 'failed': 0, 'pending': 0}, 'actions': []}
    conditions = set()
    with RunLock(config.state_dir), Store(config.state_dir) as store:
        with time_budget(config.run_timeout_seconds):
            last_attempt = store.get_meta('last_attempt')
            if last_attempt:
                gap = (now - datetime.fromisoformat(last_attempt)).total_seconds()
                if gap < 0 or gap > config.heartbeat_max_age_seconds:
                    report['scheduler'] = 'missed_runs'
                    conditions.add(3)
                    if not probe and not preview:
                        store.enqueue('scheduler:' + last_attempt, {'reason_code': 'missed_runs'}, now)
            if not probe and not preview:
                store.set_meta('last_attempt', now.isoformat())
            for account in config.accounts:
                label = account_label(account.account_id)
                last_fetch = store.get_meta('rated_fetch:' + account.account_id)
                age = (now - datetime.fromisoformat(last_fetch)).total_seconds() if last_fetch else None
                fetch_rated = probe or age is None or age < 0 or age >= 3600
                try:
                    client = factory(account.read_token_file)
                    snapshot = client.collect(account, now, include_rated=fetch_rated)
                    if not probe and not preview:
                        snapshot = _rated_snapshot(store, account, snapshot, now, fetch_rated)
                        store.save_snapshot(snapshot)
                    decisions = evaluate(config, snapshot, store.prior())
                    decisions += (Decision(ResourceKey(account.account_id, 'account', 'monitor'),
                                           'healthy', 'collection_complete', metric='collection'),)
                except RunDeadline:
                    raise
                except (CloudflareError, OSError, ValueError, TypeError, KeyError):
                    snapshot = Snapshot(account.account_id, (), (), (), {'collection': 'unknown'}, now)
                    decisions = (Decision(ResourceKey(account.account_id, 'account', 'monitor'),
                                          'unknown', 'collection_failed', metric='collection'),)
                if not probe and not preview:
                    store.record_decisions(decisions, now)
                statuses = [d.status for d in decisions]
                if 'unknown' in statuses:
                    conditions.add(3)
                if 'tripped' in statuses or 'warning' in statuses:
                    conditions.add(4)
                report['accounts'].append({'account_ref': label, 'coverage': report_coverage(snapshot.coverage),
                    'decisions': [{'scope': d.key.scope, 'resource_ref': resource_label(d.key), 'status': d.status,
                                   'reason_code': d.reason_code, 'metric': d.metric,
                                   'value': str(d.value) if d.value is not None else None,
                                   'unit': d.unit, 'currency': d.currency} for d in decisions]})
                if not probe and (config.mode == 'enforce' or preview):
                    from .actions import preflight, execute, reconcile
                    reconciled = set()
                    if not preview:
                        for resource in config.resources:
                            if resource.key.account_id != account.account_id:
                                continue
                            intent = store.intent(resource.key)
                            if intent and intent['status'] in ('pending', 'partial', 'failed'):
                                result = reconcile(resource, config, client, store)
                                reconciled.add(resource.key)
                                report['actions'].append({'status': result.status, 'attempt_id': result.attempt_id,
                                                          'resource_ref': resource_label(resource.key)})
                                store.enqueue('cutoff:' + result.attempt_id + ':' + result.status,
                                              {'reason_code': 'cutoff_result', 'status': result.status,
                                               'resource_ref': resource_label(resource.key)}, now)
                                if result.status != 'verified_public_cutoff':
                                    conditions.add(5)
                    for decision in decisions:
                        if not decision.proposed_action or decision.key in reconciled:
                            continue
                        intent = store.intent(decision.key)
                        if intent and intent['status'] == 'verified_public_cutoff':
                            continue
                        resource = next(r for r in config.resources if r.key == decision.key)
                        try:
                            # Observe and preview never load the executor credential.
                            action_client = client if preview else factory(resource.executor_token_file)
                            plan = preflight(decision, config, action_client)
                            if preview:
                                report['actions'].append({'status': 'proposed', 'baseline_digest': plan.baseline_digest})
                            else:
                                result = execute(plan, action_client, store)
                                report['actions'].append({'status': result.status, 'attempt_id': result.attempt_id})
                                store.enqueue('cutoff:' + result.attempt_id + ':' + result.status,
                                              {'reason_code': 'cutoff_result', 'status': result.status}, now)
                                if result.status != 'verified_public_cutoff':
                                    conditions.add(5)
                        except RunDeadline:
                            raise
                        except (CloudflareError, OSError, ValueError, TypeError, KeyError):
                            report['actions'].append({'status': 'failed', 'reason_code': 'preflight_or_execution_blocked'})
                            conditions.add(5)
                            if not preview:
                                store.enqueue('blocked:' + hashlib.sha256(encode(decision.key).encode()).hexdigest(),
                                              {'reason_code': 'cutoff_blocked'}, now)
            if not probe and not preview:
                report['notification'] = deliver(store, config.notification, now)
                if report['notification']['failed'] or report['notification']['pending']:
                    conditions.add(5)
                store.set_meta('last_finished', now.isoformat())
                store.set_meta('last_collection_healthy', str(3 not in conditions).lower())
                if 3 not in conditions:
                    store.set_meta('last_collection_success', now.isoformat())
            report['collection'] = 'unknown' if 3 in conditions else 'complete'
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    # Failure > threshold incident > collection unknown > healthy; config errors precede I/O.
    return max(conditions, default=0), report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Best-effort Cloudflare cost monitor; not a spending cap.')
    parser.add_argument('command', choices=('validate', 'probe', 'run', 'status', 'rearm', 'enforce-preview'))
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--account-id')
    parser.add_argument('--product', default='workers')
    parser.add_argument('--resource-id')
    parser.add_argument('--scope', choices=('account', 'resource'), default='resource')
    parser.add_argument('--show-identities', action='store_true',
                        help='status only: include private local resource mapping; do not share output')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.show_identities and args.command != 'status':
            raise ConfigError('private mapping is a status-only option')
        if args.command == 'validate':
            report, code = {'valid': True, 'mode': config.mode, 'accounts': len(config.accounts),
                            'resources': len(config.resources)}, 0
        elif args.command in ('run', 'probe', 'enforce-preview'):
            code, report = run_once(config, probe=args.command == 'probe', preview=args.command == 'enforce-preview')
        else:
            with RunLock(config.state_dir), Store(config.state_dir) as store:
                if args.command == 'rearm':
                    if not args.account_id or args.scope == 'resource' and not args.resource_id:
                        raise ConfigError('rearm requires exact enrolled resource')
                    key = ResourceKey(args.account_id, args.scope, args.product,
                                      args.resource_id if args.scope == 'resource' else None)
                    enrolled = ({r.key for r in config.resources} if args.scope == 'resource' else
                                {k for k in store.prior() if k.scope == 'account' and
                                 k.account_id in {a.account_id for a in config.accounts}})
                    if key not in enrolled:
                        raise ConfigError('resource not enrolled')
                    store.rearm(key)
                    report = {'rearmed': True, 'remote_changes': 0}
                else:
                    states = tuple(store.prior().values())
                    report = {'last_attempt': store.get_meta('last_attempt'),
                              'last_finished': store.get_meta('last_finished'),
                              'last_collection_success': store.get_meta('last_collection_success'),
                              'last_collection_healthy': store.get_meta('last_collection_healthy'),
                              'pending_notifications': store.pending_count(),
                              'tripped': sum(s.status == 'tripped' for s in states)}
                    if args.show_identities:
                        keys = set(store.prior()) | {r.key for r in config.resources}
                        report['private_identity_mapping'] = [
                            {'resource_ref': resource_label(key), 'identity': json.loads(encode(key))}
                            for key in sorted(keys, key=lambda key: resource_label(key))]
                code = 0
    except ConfigError:
        report, code = {'error': 'invalid_configuration'}, 2
    except Locked:
        report, code = {'error': 'overlapping_run'}, 3
    except RunDeadline:
        report, code = {'error': 'run_deadline_exceeded', 'collection': 'unknown'}, 3
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        report, code = {'error': 'runtime_failure'}, 3
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
