"""Period-scoped budget accounting; estimated usage and rated floors stay separate.

No billing completeness is claimed. The CPU term is a configured planning reserve,
never measured CPU or an upper bound. Quality acceptance allows an explicit guard
action at a threshold; it does not turn a partial estimate into an invoice.
"""
import hashlib
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal, localcontext

from .config import billing_window
from .models import Decision, ResourceKey
from .state import encode


def _decimal_text(value):
    """Canonical Decimal identity without context rounding or float conversion."""
    if not value.is_finite():
        return str(value)
    sign, digits, exponent = value.as_tuple()
    coefficient = ''.join(map(str, digits)).rstrip('0')
    if not coefficient:
        return '0'
    return ('-' if sign else '') + coefficient + 'e' + str(exponent + len(digits) - len(coefficient))


def policy_digest(resource, account):
    """Bind approval to target, action, budget and UTC guard-period semantics."""
    if account.account_id != resource.key.account_id:
        raise ValueError('guard approval account identity mismatch')
    budget = {key: _decimal_text(value) if isinstance(value, Decimal) else value
              for key, value in asdict(resource.budget).items()} if resource.budget else None
    return hashlib.sha256(encode({'resource': asdict(resource.key), 'action': resource.permitted_action,
                                 'budget': budget, 'guard_period': {
                                     'model': 'utc-monthly-billing-day-clamped-v1',
                                     'billing_day': account.billing_day,
                                     'currency': account.currency}}).encode()).hexdigest()


def _amount(value):
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _valid_budget(budget):
    if budget is None or not _amount(budget.hard_limit_usd) or budget.hard_limit_usd == 0:
        return False
    if type(budget.accept_partial) is not bool or type(budget.accept_approximate) is not bool:
        return False
    rates = (budget.request_usd_per_million, budget.cpu_usd_per_million_ms, budget.cpu_ms_per_request)
    if budget.source == 'workers_usage_estimate':
        return all(_amount(rate) and rate > 0 for rate in rates) and bool(budget.pricing_source and budget.pricing_as_of)
    return budget.source == 'account_rated_observed' and all(_amount(rate) and rate == 0 for rate in rates)


def _usage(resource, snapshot, store, start, end, now, persist):
    records = store.budget_records('requests', resource.key, start)
    changed = {}
    invalid = False
    for row in snapshot.usage_buckets:
        if row.key != resource.key or row.metric != 'workers.requests':
            continue
        # A complete UTC minute is the only summable unit. Aggregate observations
        # are deliberately not consulted: their rolling windows overlap.
        if row.period_end <= start or row.period_start >= end:
            continue
        valid = (_amount(row.value) and row.value == row.value.to_integral_value()
                 and row.unit == 'requests' and row.complete is True
                 and row.quality in {'good', 'approximate'} and row.source
                 and row.sampled in (False, True, None)
                 and row.period_end - row.period_start == timedelta(minutes=1)
                 and row.period_start.second == row.period_start.microsecond == 0
                 and start <= row.period_start < row.period_end <= min(end, now)
                 and row.period_end <= row.fetched_at <= now
                 and row.data_through is not None and row.period_start <= row.data_through <= row.period_end)
        if not valid:
            invalid = True
            continue
        identity = row.period_start.isoformat()
        previous = records.get(identity)
        # Repeated analytics fetches revise the same minute; retain its maximum.
        # The entire usage-estimate source stays approximate, even for exact rows.
        if previous is None or row.value > Decimal(previous['requests']):
            records[identity] = {'requests': str(row.value), 'source': row.source}
            changed[identity] = records[identity]
    if persist:
        store.save_budget_records('requests', resource.key, start, changed)
    requests = sum((Decimal(row['requests']) for row in records.values()), Decimal('0'))
    budget = resource.budget
    # Enough precision for exact decimal multiplication of bounded provider counts
    # and administrator rates; avoid binary floats and per-bucket rounding.
    with localcontext() as context:
        context.prec = max(50, len(str(requests)) + sum(len(str(rate)) for rate in (
            budget.request_usd_per_million, budget.cpu_usd_per_million_ms, budget.cpu_ms_per_request)) + 20)
        cost = requests / Decimal('1000000') * (budget.request_usd_per_million +
                    budget.cpu_ms_per_request * budget.cpu_usd_per_million_ms)
    return cost if records else None, invalid, tuple(sorted(records))


def _rated(resource, snapshot, store, start, end, now, persist):
    account_key = ResourceKey(resource.key.account_id, 'account', 'billing')
    records = store.budget_records('rated', account_key, start)
    changed = {}
    invalid = False
    for row in snapshot.rated_charges:
        if row.key.account_id != account_key.account_id:
            continue
        if row.period_end <= start or row.period_start >= end:
            continue
        # Resource/product breakdowns are not account increments. A positive row
        # binds the selected target through configuration, not alleged guilt.
        if row.key != account_key:
            continue
        if (not isinstance(row.source_key, str) or not row.source_key or not row.source
                or row.currency != 'USD' or row.kind != 'incremental' or row.quality != 'good'
                or not _amount(row.amount) or not start <= row.period_start < row.period_end <= min(end, now)):
            invalid = True
            continue
        payload = {'amount': _decimal_text(row.amount), 'source': row.source,
                   'start': row.period_start.isoformat(), 'end': row.period_end.isoformat()}
        previous = records.get(row.source_key)
        if previous is not None and previous != payload:
            # Conflicts persist, including when the provider later replays the
            # original row. Manual rearm does not erase accounting ambiguity.
            records[row.source_key] = {'conflict': True}
        else:
            records[row.source_key] = payload
        if records[row.source_key] != previous:
            changed[row.source_key] = records[row.source_key]
    invalid |= any(row.get('conflict') for row in records.values())
    invalid |= len({row.get('source') for row in records.values() if not row.get('conflict')}) > 1
    if persist:
        store.save_budget_records('rated', account_key, start, changed)
    # Distinct opaque identities do not prove disjoint consumption. In particular,
    # expanded charge windows may revise earlier rows under a different key. The
    # largest individually validated gross charge is the only floor established by
    # this adapter; it is not a net invoice balance or a sum of independent charges.
    floor = None if invalid or not records else max(Decimal(row['amount']) for row in records.values())
    return floor, invalid, tuple(sorted(records))


def evaluate_budget(config, resource, snapshot, store, now, *, persist=True):
    """Evaluate current guard period; preview merges evidence without writing state.

    Requests sum disjoint minutes; rated evidence uses the largest validated line.
    Missing history remains partial. Thus a value below the threshold is unknown,
    while a crossing may propose the explicitly configured quality-accepted action.
    Latch persistence belongs to Store.record_decisions, never this evaluator.
    """
    account = next((a for a in config.accounts if a.account_id == resource.key.account_id), None)
    if account is None:
        raise ValueError('guard resource account is not enrolled')
    start, end = billing_window(now, account.billing_day)
    value, invalid, evidence = None, False, ()
    budget = resource.budget
    valid = (resource.key.scope == 'resource' and resource.key.product == 'workers'
             and any(r.key == resource.key for r in config.resources)
             and account.currency == 'USD' and snapshot.account_id == account.account_id
             and snapshot.collected_at <= now and _valid_budget(budget))
    reason = 'guard_budget_invalid'
    if valid:
        if budget.source == 'workers_usage_estimate':
            value, invalid, evidence = _usage(resource, snapshot, store, start, end, now, persist)
            reason = 'estimated_requests_cpu_reserve_partial'
            accepted = budget.accept_partial and budget.accept_approximate
        else:
            value, invalid, evidence = _rated(resource, snapshot, store, start, end, now, persist)
            reason = 'largest_rated_line_floor_partial'
            accepted = budget.accept_partial
        if invalid:
            reason += '_conflicting_or_invalid'
        elif value is None:
            reason += '_missing'
        elif not accepted:
            reason += '_quality_unaccepted'
        elif value >= budget.hard_limit_usd:
            return Decision(resource.key, 'tripped', reason + '_budget_reached', resource.permitted_action,
                            evidence, 'guard_cost_usd', value, 'currency', 'USD', start, end)
        else:
            reason += '_below_budget_unknown'
    return Decision(resource.key, 'unknown', reason, evidence_ids=evidence, metric='guard_cost_usd',
                    value=value, unit='currency', currency='USD', period_start=start, period_end=end)
