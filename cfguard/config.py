"""Strict JSON configuration and UTC billing-cycle boundaries."""

import calendar
import json
import os
import re
import stat
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath, PureWindowsPath

from .models import AccountConfig, Config, GuardBudget, Price, ResourceConfig, ResourceKey, Threshold


class ConfigError(ValueError):
    """Invalid configuration; messages intentionally omit input values."""


def billing_window(now: datetime, billing_day: int) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset().total_seconds() != 0 or not 1 <= billing_day <= 31:
        raise ValueError("UTC time and billing day 1..31 required")
    def boundary(year, month):
        return datetime(year, month, min(billing_day, calendar.monthrange(year, month)[1]), tzinfo=timezone.utc)
    start = boundary(now.year, now.month)
    if now < start:
        start = boundary(now.year - (now.month == 1), 12 if now.month == 1 else now.month - 1)
    end = boundary(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1)
    return start, end


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ConfigError("unknown or missing configuration fields")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ConfigError("nonempty text required")
    return value


def _strings(value):
    if not isinstance(value, list): raise ConfigError("list required")
    result = tuple(_text(item) for item in value)
    if len(result) != len(set(result)): raise ConfigError("duplicate list entries")
    return result


def _decimal(value, positive=False):
    if not isinstance(value, str): raise ConfigError("decimal strings required")
    try: result = Decimal(value)
    except InvalidOperation: raise ConfigError("invalid decimal") from None
    if not result.is_finite() or result < 0 or positive and result == 0:
        raise ConfigError("invalid nonnegative decimal")
    return result


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ConfigError("integer outside permitted range")
    return value


def _boolean(value):
    if type(value) is not bool: raise ConfigError("boolean required")
    return value


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value): raise ConfigError("currency code required")
    return value


def _provider_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise ConfigError("provider account and zone IDs must have 32 hexadecimal characters")
    return value


def _resource_id(value):
    value = _text(value)
    if value in {".", ".."} or any(c in value for c in "/\\?#%"):
        raise ConfigError("invalid provider resource identity")
    return value


def _path(value):
    value = _text(value)
    if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()) or ".." in value.replace("\\", "/").split("/"):
        raise ConfigError("absolute external file path required")
    return Path(value)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ConfigError("duplicate JSON object key")
        result[key] = value
    return result


def _guard_budget(raw, account, mode):
    fields = {'hard_limit_usd', 'source', 'request_usd_per_million', 'cpu_usd_per_million_ms',
              'cpu_ms_per_request', 'pricing_source', 'pricing_as_of', 'accept_approximate', 'accept_partial'}
    _object(raw, fields, {'hard_limit_usd', 'source'})
    if account.currency != 'USD': raise ConfigError('guard budgets require USD')
    source = _text(raw['source'])
    if source not in {'workers_usage_estimate', 'account_rated_observed'}:
        raise ConfigError('unsupported guard budget source')
    approximate = _boolean(raw.get('accept_approximate', False))
    partial = _boolean(raw.get('accept_partial', False))
    price_fields = {'request_usd_per_million', 'cpu_usd_per_million_ms', 'cpu_ms_per_request', 'pricing_source', 'pricing_as_of'}
    if source == 'workers_usage_estimate':
        if price_fields - raw.keys(): raise ConfigError('guard pricing and provenance required')
        rates = [_decimal(raw[field], True) for field in ('request_usd_per_million', 'cpu_usd_per_million_ms', 'cpu_ms_per_request')]
        provenance = _text(raw['pricing_source'])
        as_of = _text(raw['pricing_as_of'])
        try: date.fromisoformat(as_of)
        except ValueError: raise ConfigError('guard price date required') from None
        if mode == 'enforce' and not approximate: raise ConfigError('approximate budget acceptance required')
    else:
        if price_fields & raw.keys(): raise ConfigError('rated budgets cannot include usage pricing')
        rates, provenance, as_of = [Decimal('0')] * 3, '', ''
    if mode == 'enforce' and not partial: raise ConfigError('partial budget acceptance required')
    return GuardBudget(_decimal(raw['hard_limit_usd'], True), source, *rates, provenance, as_of, approximate, partial)


def validate_admin_file(path: Path):
    """Linux policy: root-owned regular file, protected from non-admin replacement."""
    if os.name != "posix": return
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ConfigError("configuration must be root-owned and not group/world writable")
        for parent in path.absolute().parents:
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise ConfigError("configuration parent directories permit replacement")
    except OSError:
        raise ConfigError("cannot inspect configuration ownership") from None


def load_config(path: Path) -> Config:
    path = Path(path)
    validate_admin_file(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ConfigError("invalid JSON constant")))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ConfigError("cannot read valid JSON configuration") from None
    raw = _object(raw, {"mode", "accounts", "resources", "state_dir", "notification", "run_timeout_seconds", "heartbeat_max_age_seconds"}, {"accounts"})
    mode = raw.get("mode", "observe")
    if not isinstance(mode, str) or mode not in {"observe", "enforce"}: raise ConfigError("invalid mode")
    if not isinstance(raw["accounts"], list) or not raw["accounts"]: raise ConfigError("at least one account required")
    accounts = []
    for a in raw["accounts"]:
        _object(a, {"key", "account_id", "read_token_file", "billing_day", "budget", "currency", "expected_subscriptions", "zones", "prices", "max_data_age_seconds", "billing_period_verified"},
                {"key", "account_id", "read_token_file", "billing_day", "budget", "currency"})
        prices = []
        if not isinstance(a.get("prices", []), list): raise ConfigError("prices must be a list")
        for p in a.get("prices", []):
            _object(p, {"metric", "unit", "currency", "amount", "per_quantity", "allowance", "source", "as_of"}, {"metric", "unit", "currency", "amount", "per_quantity", "allowance", "source", "as_of"})
            try: date.fromisoformat(_text(p["as_of"]))
            except ValueError: raise ConfigError("price date required") from None
            prices.append(Price(_text(p["metric"]), _text(p["unit"]), _currency(p["currency"]), _decimal(p["amount"]),
                                _decimal(p["per_quantity"], True), _decimal(p["allowance"]), _text(p["source"]), p["as_of"]))
        if len({p.metric for p in prices}) != len(prices): raise ConfigError("duplicate price metric")
        zones = _strings(a.get("zones", []))
        for zone in zones: _provider_id(zone)
        accounts.append(AccountConfig(_text(a["key"]), _provider_id(a["account_id"]), _path(a["read_token_file"]),
            _integer(a["billing_day"], 1, 31), _decimal(a["budget"]), _currency(a["currency"]),
            _strings(a.get("expected_subscriptions", [])), zones, tuple(prices),
            _integer(a.get("max_data_age_seconds", 900), 1, 86400), _boolean(a.get("billing_period_verified", False))))
    if len({a.key for a in accounts}) != len(accounts) or len({a.account_id for a in accounts}) != len(accounts):
        raise ConfigError("duplicate account identity")
    if len({z for a in accounts for z in a.zones}) != sum(len(a.zones) for a in accounts):
        raise ConfigError("zone enrolled in multiple accounts")
    account_map = {a.account_id: a for a in accounts}
    resources = []
    if not isinstance(raw.get("resources", []), list): raise ConfigError("resources must be a list")
    for r in raw.get("resources", []):
        _object(r, {"account_id", "product", "resource_id", "name", "zones", "hostnames", "thresholds", "permitted_action", "executor_token_file", "approved_manifest_file", "approved_manifest_digest", "budget"}, {"account_id", "product", "resource_id", "name"})
        key = ResourceKey(_provider_id(r["account_id"]), "resource", _resource_id(r["product"]), _resource_id(r["resource_id"]))
        if key.account_id not in account_map: raise ConfigError("resource account is not enrolled")
        zones = _strings(r.get("zones", []))
        if set(zones) - set(account_map[key.account_id].zones): raise ConfigError("resource zone is not enrolled in account")
        thresholds = []
        if not isinstance(r.get("thresholds", []), list): raise ConfigError("thresholds must be a list")
        for t in r.get("thresholds", []):
            _object(t, {"metric", "limit", "unit", "warning"}, {"metric", "limit", "unit"})
            limit = _decimal(t["limit"])
            warning = _decimal(t["warning"]) if "warning" in t else None
            if warning is not None and warning > limit: raise ConfigError("warning exceeds limit")
            thresholds.append(Threshold(_text(t["metric"]), limit, _text(t["unit"]), warning))
        if len({t.metric for t in thresholds}) != len(thresholds): raise ConfigError("duplicate threshold metric")
        action = r.get("permitted_action")
        if action is not None and (action not in {"disable_worker_endpoints", "delete_worker"} or key.product != "workers"):
            raise ConfigError("unsupported permitted action")
        budget = _guard_budget(r['budget'], account_map[key.account_id], mode) if 'budget' in r else None
        if budget is not None and key.product != 'workers': raise ConfigError('unsupported guard budget product')
        if action == 'delete_worker' and budget is None: raise ConfigError('deletion requires an explicit guard budget')
        digest = r.get("approved_manifest_digest")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ConfigError("invalid approval digest")
        executor = _path(r['executor_token_file']) if r.get('executor_token_file') is not None else None
        manifest = _path(r['approved_manifest_file']) if r.get('approved_manifest_file') is not None else None
        if mode == 'enforce' and (action is None or executor is None or manifest is None or digest is None
                                  or executor == account_map[key.account_id].read_token_file):
            raise ConfigError('enforcement requires action, separate writer and pinned approval')
        resources.append(ResourceConfig(key, _text(r["name"]), zones, _strings(r.get("hostnames", [])), tuple(thresholds), action,
            executor, manifest, digest, budget))
    if len({r.key for r in resources}) != len(resources): raise ConfigError("duplicate resource identity")
    notification = raw.get("notification")
    if notification is not None:
        _object(notification, {"url_file", "max_attempts"}, {"url_file"})
        notification = {"url_file": _path(notification["url_file"]), "max_attempts": _integer(notification.get("max_attempts", 3), 1, 10)}
    return Config(mode, tuple(accounts), tuple(resources), _path(raw.get("state_dir", "/var/lib/cloudflare-cost-guard")), notification,
                  _integer(raw.get("run_timeout_seconds", 240), 1, 299), _integer(raw.get("heartbeat_max_age_seconds", 660), 301, 86400))
