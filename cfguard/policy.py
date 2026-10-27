"""Pure policy evaluation; estimates, rated charges and commitments stay separate."""

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
import re

from .config import billing_window
from .models import Decision, ResourceKey


def _amount(value):
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def evidence_id(observation):
    """Stable identifier over non-secret evidence, independent of fetch time."""
    fields = (observation.key, observation.metric, observation.period_start.isoformat(),
              observation.period_end.isoformat(), observation.data_through, observation.value,
              observation.unit, observation.quality, observation.complete, observation.sampled, observation.source)
    return sha256(repr(fields).encode()).hexdigest()


def _quality(observation, now, max_age, unit):
    if observation.unit != unit or not observation.unit: return "unit_unknown"
    if not _amount(observation.value): return "value_unknown"
    if not observation.complete: return "incomplete"
    if observation.quality not in {"good", "approximate"}: return "quality_unknown"
    if observation.data_through is None: return "data_time_unknown"
    if observation.fetched_at > now or observation.data_through > now: return "future_data"
    if not observation.period_start <= observation.data_through <= observation.period_end: return "invalid_window"
    if (now - observation.data_through).total_seconds() > max_age: return "stale"
    if observation.sampled is not False or observation.quality == "approximate": return "approximate"
    return "good"


def rated_total(rows, account_id, currency, start, end):
    """Reconcile an account-period ledger; None means ambiguous or unavailable.

    Source keys must identify disjoint incremental provider charge lines. Resource
    breakdowns cannot reconstruct an account bill. Multiple cumulative readings
    reconcile one ledger and are never added to incremental rows.
    """
    relevant = [r for r in rows if r.key.account_id == account_id
                and r.period_start < end and r.period_end > start]
    if not relevant: return None
    if any(r.period_start < start or r.period_end > end for r in relevant): return None
    accounts = [r for r in relevant if r.key.scope == "account"]
    if not accounts: return None
    if len({r.key.product for r in accounts}) != 1: return None
    unique = {}
    for row in accounts:
        if (not row.source_key or not row.source or row.currency != currency or row.quality != "good"
                or not _amount(row.amount) or row.kind not in {"incremental", "cumulative"}): return None
        if row.source_key in unique and unique[row.source_key] != row: return None
        unique[row.source_key] = row
    increments = [r for r in unique.values() if r.kind == "incremental"]
    cumulative = [r for r in unique.values() if r.kind == "cumulative"]
    # A cumulative amount is usable only for the complete current period; partial
    # readings cannot silently stand in for the configured period total.
    if any((r.period_start, r.period_end) != (start, end) for r in cumulative): return None
    cumulative_amounts = {r.amount for r in cumulative}
    if len(cumulative_amounts) > 1: return None
    total = sum((r.amount for r in increments), Decimal("0"))
    if increments:
        if cumulative_amounts and total != next(iter(cumulative_amounts)): return None
        return total
    return next(iter(cumulative_amounts), None)


def _coverage(snapshot, *keys):
    return next((snapshot.coverage[k] for k in keys if k in snapshot.coverage), "unknown")


def _subscription_commitment(rows, account, complete):
    """Reconcile endpoint appearances without discarding their original provenance.

    Only an account + verified provider subscription ID identifies a commitment.
    A zone endpoint establishes zone attribution; an account-list appearance
    does not assert that a subscription belongs to the account rather than a zone.
    """
    unique, zones, scopes = {}, {}, {}
    invalid = not complete
    for row in rows:
        identifiers = (row.provider_id, row.plan_id)
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)
               for value in identifiers):
            invalid = True
            continue
        source = sha256(json.dumps([account.account_id, row.provider_id], separators=(',', ':')).encode()).hexdigest()
        if (row.source_key != source or row.quality != 'good' or not _amount(row.amount)
                or row.currency != account.currency or type(row.allowed) is not bool
                or row.key.product != 'subscriptions' or row.key.scope not in {'account', 'zone'}
                or row.plan_scope not in (None, 'account', 'zone')):
            invalid = True
        previous = unique.get(source)
        if previous and (previous.amount, previous.currency, previous.plan_id, previous.allowed) != (
                row.amount, row.currency, row.plan_id, row.allowed):
            invalid = True
        unique[source] = row
        attributed = zones.setdefault(source, set())
        if row.key.scope == 'zone':
            attributed.add(row.key.zone_id)
            if row.key.zone_id not in account.zones:
                invalid = True
        declared = scopes.setdefault(source, set())
        if row.plan_scope is not None:
            # Invalid values were rejected above; do not hash an untrusted object.
            if isinstance(row.plan_scope, str):
                declared.add(row.plan_scope)
        if len(attributed) > 1 or len(declared) > 1 or attributed and 'account' in declared:
            invalid = True
    total = None if invalid else sum((row.amount for row in unique.values()), Decimal('0'))
    return total, tuple(sorted(unique))


def _single(observations):
    unique = []
    for row in observations:
        if row not in unique: unique.append(row)
    return unique[0] if len(unique) == 1 else None


def evaluate(config, snapshot, prior):
    """Return decisions without I/O. Unknown/healthy evidence never clears a trip."""
    account = next((a for a in config.accounts if a.account_id == snapshot.account_id), None)
    if account is None: raise ValueError("snapshot account is not enrolled")
    now = snapshot.collected_at
    start, end = billing_window(now, account.billing_day)
    ledger_key = ResourceKey(account.account_id, "account", "billing")
    decisions = []

    def emit(decision):
        state = prior.get(decision.key)
        if state and (state.dimensions.get(decision.metric) == "tripped"
                      or not state.dimensions and state.status == "tripped"):
            decision = replace(decision, status="tripped", reason_code="latched_" + decision.reason_code,
                               proposed_action=decision.proposed_action if decision.reason_code == "threshold_crossed" else None)
        decisions.append(decision)

    for resource in config.resources:
        if resource.key.account_id != snapshot.account_id: continue
        for threshold in resource.thresholds:
            rows = [o for o in snapshot.observations if o.key == resource.key and o.metric == threshold.metric]
            observation = _single(rows)
            reason = ("unsupported" if _coverage(snapshot, threshold.metric) == "unsupported" else
                      "ambiguous" if rows and observation is None else "missing" if observation is None else
                      _quality(observation, now, account.max_data_age_seconds, threshold.unit))
            status, action = "unknown", None
            if reason in {"good", "approximate"}:
                crossed = observation.value > 0 and observation.value >= threshold.limit
                if reason == "approximate": status = "warning"
                elif crossed:
                    status, reason = "tripped", "threshold_crossed"
                    action = resource.permitted_action
                elif threshold.warning is not None and observation.value >= threshold.warning:
                    status, reason = "warning", "warning_threshold"
                else: status, reason = "healthy", "below_threshold"
            emit(Decision(resource.key, status, reason, action,
                          (evidence_id(observation),) if observation else (), threshold.metric,
                          observation.value if observation else None, threshold.unit,
                          period_start=observation.period_start if observation else None,
                          period_end=observation.period_end if observation else None))

    # Account estimates use one full billing-period account series per price.
    # No per-resource allowance, reconstruction from a subset, or partial-month
    # extrapolation is permitted.
    estimate, estimate_ids, estimate_reason, approximate = Decimal("0"), [], "good", False
    period_verified = account.billing_period_verified and snapshot.coverage.get('billing_period') == 'verified_config'
    billing_covered = (snapshot.coverage.get('billing_account_coverage') == 'covered'
                       and snapshot.coverage.get('billing_info') == 'parsed')
    if not period_verified or not billing_covered:
        estimate_reason = "billing_period_unverified"
    elif not account.prices: estimate_reason = "price_unknown"
    else:
        account_rows = [o for o in snapshot.observations if o.key.account_id == account.account_id and o.key.scope == "account"]
        if any(o.metric not in {p.metric for p in account.prices} for o in account_rows):
            estimate_reason = "price_unknown"
        for price in account.prices:
            if estimate_reason != "good": break
            observation = _single([o for o in account_rows if o.metric == price.metric])
            if price.currency != account.currency: estimate_reason = "currency_unknown"
            elif observation is None: estimate_reason = "account_coverage_unknown"
            elif (observation.period_start, observation.period_end) != (start, end): estimate_reason = "period_coverage_unknown"
            else:
                quality = _quality(observation, now, account.max_data_age_seconds, price.unit)
                if quality not in {"good", "approximate"}: estimate_reason = quality
                else:
                    approximate |= quality == "approximate"
                    estimate += max(Decimal("0"), observation.value - price.allowance) * price.amount / price.per_quantity
                    estimate_ids.append(evidence_id(observation))
    if estimate_reason != "good":
        emit(Decision(ledger_key, "unknown", estimate_reason, metric="estimated_cost", currency=account.currency,
                      period_start=start, period_end=end))
    else:
        crossed = estimate > account.budget
        status = "warning" if approximate else "tripped" if crossed else "healthy"
        emit(Decision(ledger_key, status, "approximate_estimate" if approximate else "estimated_budget_exceeded" if crossed else "estimated_within_budget",
                      evidence_ids=tuple(estimate_ids), metric="estimated_cost", value=estimate, unit="currency",
                      currency=account.currency, period_start=start, period_end=end))

    rated_coverage = _coverage(snapshot, "rated_usage", "rated")
    rated = rated_total(snapshot.rated_charges, account.account_id, account.currency, start, end) if rated_coverage == "complete" and period_verified and billing_covered else None
    rated_status = "unknown" if rated is None else "tripped" if rated > account.budget else "warning" if rated > 0 else "healthy"
    rated_reason = "rated_unknown" if rated is None else "rated_budget_exceeded" if rated > account.budget else "rated_spend" if rated > 0 else "rated_zero"
    emit(Decision(ledger_key, rated_status, rated_reason, evidence_ids=tuple(sorted({r.source_key for r in snapshot.rated_charges if r.key.account_id == account.account_id})),
                  metric="rated_cost", value=rated, unit="currency", currency=account.currency, period_start=start, period_end=end))

    # A confirmed positive line is actionable alert evidence even when the full
    # period total or source heartbeat is unknown. Do not label a subset a total.
    positive_rows = [r for r in snapshot.rated_charges if r.key.account_id == account.account_id
                     and r.quality == 'good' and r.currency == account.currency
                     and _amount(r.amount) and r.amount > 0 and r.source_key
                     and start <= r.period_start < r.period_end <= end]
    if rated is None and positive_rows:
        emit(Decision(ledger_key, 'warning', 'positive_rated_line_total_unknown',
                      evidence_ids=tuple(sorted({r.source_key for r in positive_rows})),
                      metric='observed_rated_spend', unit='currency', currency=account.currency))

    subscriptions = [s for s in snapshot.subscriptions if s.key.account_id == account.account_id]
    subscription_coverage = _coverage(snapshot, "subscriptions.account", "subscriptions")
    zone_coverage = all(_coverage(snapshot, "subscriptions.zone:" + z, "subscriptions") == "complete" for z in account.zones)
    commitment, subscription_ids = _subscription_commitment(
        subscriptions, account, subscription_coverage == 'complete' and zone_coverage)
    forbidden = any(s.allowed is False and s.quality == "good" for s in subscriptions)
    status = "tripped" if forbidden else "unknown" if commitment is None else "healthy"
    reason = "forbidden_subscription" if forbidden else "subscription_unknown" if commitment is None else "subscriptions_expected"
    emit(Decision(ledger_key, status, reason, evidence_ids=subscription_ids, metric="subscription_commitment",
                  value=commitment, unit="currency", currency=account.currency))
    return tuple(decisions)
