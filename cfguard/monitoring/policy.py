"""Pure, conservative assessment of sanitized version-1 observations."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


_REF = re.compile(r"[0-9a-f]{16}\Z")
_SOURCES = {"subscriptions.account", "workers.requests", "billing_info",
            "billing_account_coverage", "billing_period", "rated_usage",
            "rated_rows", "rated_freshness"}
_AFFIRMATIVE = {"complete", "covered", "parsed"}
_LIMITATIONS = {"unavailable", "unsupported", "approximate", "unverified"}
_STATES = _AFFIRMATIVE | _LIMITATIONS | {"unknown", "stale"}
_MAX_ITEMS = 10000


def _reference(value):
    return isinstance(value, str) and _REF.fullmatch(value) is not None


def _items(value):
    return isinstance(value, list) and len(value) <= _MAX_ITEMS


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _source(value):
    return (isinstance(value, str) and
            (value in _SOURCES or (value.startswith("subscriptions.zone:") and
                                   _reference(value.removeprefix("subscriptions.zone:")))))


def _subscription(value):
    """Return validated money evidence; never coerce raw objects into output."""
    if not isinstance(value, dict) or not _reference(value.get("resource_ref")):
        return None
    amount = value.get("amount")
    if (not isinstance(amount, str) or len(amount) > 256 or
            re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount) is None or
            value.get("currency") != "USD" or value.get("quality") != "good" or
            type(value.get("allowed")) is not bool):
        return None
    try:
        number = Decimal(amount)
        # Fixed-point expansion of a bounded source coefficient may exceed 64 characters.
        digits = ''.join(str(d) for d in number.as_tuple().digits).rstrip('0')
        if not number.is_finite() or abs(number.adjusted()) > 100 or len(digits) > 64:
            return None
    except InvalidOperation:
        return None
    return value["resource_ref"], number, amount, value["allowed"]


def assess(observation, now, policy=None):
    """Return issues and only scopes backed by fresh affirmative evidence.

    Subscription recovery is account-wide: an incomplete/invalid list cannot
    clear an older positive row. Inventory recovery is independent per product;
    coverage is independent per normalized source. This function does no I/O.
    """
    settings = {"max_age_seconds": 900, "future_tolerance_seconds": 60,
                "backlog_age_seconds": 900}
    if policy is not None:
        if not isinstance(policy, dict) or set(policy) - set(settings):
            raise ValueError("invalid policy settings")
        for key, value in policy.items():
            if type(value) is not int or value < 0 or value > 31536000:
                raise ValueError("invalid policy threshold")
            settings[key] = value
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    issues, limitations, verified = {}, [], set()

    def issue(reason, scope, ref="monitor", details=None):
        key = reason + ":" + scope + ":" + ref
        issues[key] = {"key": key, "scope": scope, "reason": reason,
                       "resource_ref": ref, "level": "warning", "details": details or {}}

    def age(stamp):
        parsed = _timestamp(stamp)
        return (now - parsed).total_seconds() if parsed is not None else None

    def fresh(stamp):
        seconds = age(stamp)
        return (seconds is not None and -settings["future_tolerance_seconds"] <= seconds
                <= settings["max_age_seconds"])

    def result():
        return {"issues": [issues[key] for key in sorted(issues)],
                "limitations": limitations, "verified_scopes": sorted(verified)}

    if (not isinstance(observation, dict) or type(observation.get("version")) is not int or
            observation["version"] != 1 or not fresh(observation.get("observed_at")) or
            not isinstance(observation.get("guard"), dict) or not _items(observation.get("accounts"))):
        issue("observation_unknown", "observation")
        return result()
    verified.add("observation")

    guard = observation["guard"]
    last_attempt, last_finished = age(guard.get("last_attempt")), age(guard.get("last_finished"))
    if (guard.get("status") != "ok" or last_attempt is None or last_finished is None or
            min(last_attempt, last_finished) < -settings["future_tolerance_seconds"]):
        issue("guard_unknown", "guard:liveness")
    elif max(last_attempt, last_finished) > settings["max_age_seconds"]:
        issue("guard_stale", "guard:liveness")
    else:
        verified.add("guard:liveness")

    pending, oldest = guard.get("pending_notifications"), age(guard.get("oldest_pending_at"))
    if (type(pending) is not int or not 0 <= pending <= 10**9 or
            (pending > 0 and (oldest is None or oldest < -settings["future_tolerance_seconds"])) or
            (pending == 0 and guard.get("oldest_pending_at") is not None)):
        issue("notification_unknown", "guard:notifications")
    else:
        verified.add("guard:notifications")
        if pending and oldest >= settings["backlog_age_seconds"]:
            issue("notification_backlog", "guard:notifications", details={"pending": pending})

    accounts = observation["accounts"]
    refs = [a.get("account_ref") for a in accounts if isinstance(a, dict)]
    duplicate_refs = {r for r in refs if _reference(r) and refs.count(r) > 1}
    if len(refs) == len(accounts) and all(_reference(r) for r in refs) and not duplicate_refs:
        verified.add("accounts")
    for account in accounts:
        if (not isinstance(account, dict) or not _reference(account.get("account_ref")) or
                account["account_ref"] in duplicate_refs):
            issue("accounts_unknown", "accounts")
            continue
        ref = account["account_ref"]
        scope = "account:" + ref
        if not fresh(account.get("snapshot_at")):
            issue("snapshot_unknown", scope + ":snapshot", ref)
        else:
            verified.add(scope + ":snapshot")

            sub_scope = scope + ":subscriptions"
            rows = account.get("subscriptions")
            complete = account.get("subscriptions_status") == "complete" and _items(rows)
            parsed_rows = [_subscription(row) for row in rows] if _items(rows) else []
            if any(row is None for row in parsed_rows):
                complete = False
            by_ref = {}
            for row in parsed_rows:
                if row is not None:
                    by_ref.setdefault(row[0], []).append(row)
            for resource, matches in by_ref.items():
                if len(set((r[1], r[3]) for r in matches)) > 1:
                    complete = False
                    continue
                _, number, amount, allowed = matches[0]
                if number > 0:
                    issue("positive_subscription", sub_scope, resource,
                          {"amount": amount, "currency": "USD"})
                if not allowed:
                    issue("unexpected_subscription", sub_scope, resource)
            if complete:
                verified.add(sub_scope)
            else:
                issue("subscriptions_unknown", sub_scope, ref)

            coverage = account.get("coverage")
            if not _items(coverage) or not coverage:
                issue("coverage_unknown", scope + ":coverage", ref)
            else:
                sources = [c.get("source") for c in coverage if isinstance(c, dict)]
                for row in coverage:
                    if not isinstance(row, dict) or not _source(row.get("source")):
                        issue("coverage_unknown", scope + ":coverage", ref)
                        continue
                    source = row["source"]
                    coverage_scope = scope + ":coverage:" + source
                    status, known = row.get("status"), row.get("known_limitation")
                    valid = isinstance(status, str) and status in _STATES and type(known) is bool
                    if sources.count(source) > 1 or not valid:
                        issue("coverage_unknown", coverage_scope, ref)
                    elif known and status in _LIMITATIONS:
                        limitations.append({"scope": coverage_scope, "resource_ref": ref,
                                            "source": source, "status": status})
                    elif status in _AFFIRMATIVE:
                        verified.add(coverage_scope)
                    else:
                        issue("coverage_unknown", coverage_scope, ref, {"status": status})
                if all(isinstance(row, dict) and _source(row.get("source")) and
                       scope + ":coverage:" + row["source"] in verified for row in coverage):
                    verified.add(scope + ":coverage")

        inventories = account.get("inventory")
        if not isinstance(inventories, dict):
            inventories = {}
        if set(inventories) - {"workers", "zones"}:
            issue("inventory_unsupported", scope + ":inventory:unsupported", ref)
        for product in ("workers", "zones"):
            inventory_scope = scope + ":inventory:" + product
            inventory = inventories.get(product)
            valid = isinstance(inventory, dict) and inventory.get("status") == "complete"
            for field in ("refs", "expected"):
                values = inventory.get(field) if isinstance(inventory, dict) else None
                if not _items(values) or not all(_reference(r) for r in values):
                    valid = False
                elif len(set(values)) != len(values):
                    valid = False
            if not valid:
                issue("inventory_unknown", inventory_scope, ref)
                continue
            verified.add(inventory_scope)
            actual, expected = set(inventory["refs"]), set(inventory["expected"])
            for resource in sorted(actual - expected):
                issue("inventory_added", inventory_scope, resource, {"product": product})
            for resource in sorted(expected - actual):
                issue("inventory_removed", inventory_scope, resource, {"product": product})
        if (not set(inventories) - {"workers", "zones"} and
                all(scope + ":inventory:" + p in verified for p in ("workers", "zones"))):
            verified.add(scope + ":inventory:unsupported")
    return result()
