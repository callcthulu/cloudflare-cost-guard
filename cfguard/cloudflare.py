"""Small bounded Cloudflare adapter. Collection never changes provider state."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

from .models import Observation, RatedCharge, ResourceKey, Snapshot, Subscription
from .config import billing_window

API = "https://api.cloudflare.com/client/v4"
GRAPHQL_LIMIT = 10000


class CloudflareError(Exception):
    """Sanitized error code; provider payloads and credentials never escape."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise CloudflareError("schema_number")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise CloudflareError("schema_number") from None
    if not result.is_finite() or result < 0:
        raise CloudflareError("schema_number")
    return result


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise CloudflareError("schema_timestamp") from None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise CloudflareError("invalid_identifier")
    return value


def _rows(payload):
    result = payload.get("result")
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise CloudflareError("schema_list")
    info = payload.get("result_info")
    if info is not None:
        # These list endpoints do not document pagination query parameters.
        # Never assume a generic page=2 works when the endpoint does not say so.
        if not isinstance(info, dict) or info.get("total_count") != len(result):
            raise CloudflareError("incomplete_inventory")
    return result


class Client:
    def __init__(self, token_file, *, account_id=None, transport=None, timeout=10,
                 max_attempts=2, max_requests=80, max_body_bytes=2_000_000,
                 sleep=time.sleep):
        if not (0 < timeout <= 30 and 1 <= max_attempts <= 3 and 1 <= max_requests <= 200
                and 1 <= max_body_bytes <= 8_000_000):
            raise ValueError("invalid HTTP bounds")
        self.token_file = Path(token_file)
        self.account_id = account_id
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.max_body_bytes = max_body_bytes
        self.requests = 0
        self.sleep = sleep
        self.transport = transport or self._transport
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())

    def _token(self):
        try:
            before = self.token_file.lstat()
            if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
                raise CloudflareError("unsafe_token_file")
            if os.name != "nt":
                trusted_group = before.st_uid == 0 and before.st_gid == os.getegid()
                if before.st_mode & 0o027 or before.st_mode & 0o040 and not trusted_group or before.st_uid not in {0, os.geteuid()}:
                    raise CloudflareError("unsafe_token_permissions")
            fd = os.open(self.token_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="ascii") as handle:
                actual = os.fstat(handle.fileno())
                if (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino):
                    raise CloudflareError("token_file_changed")
                if (before.st_mode, before.st_uid, before.st_gid) != (actual.st_mode, actual.st_uid, actual.st_gid):
                    raise CloudflareError("token_permissions_changed")
                token = handle.read(4097).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,4096}", token):
                raise CloudflareError("invalid_token_file")
            return token
        except (OSError, UnicodeError):
            raise CloudflareError("token_file_unreadable") from None

    def _transport(self, request, timeout):
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return HttpResponse(response.status, response.read(self.max_body_bytes + 1), dict(response.headers))

    def _bind(self, account_id):
        _identifier(account_id)
        if self.account_id is not None and self.account_id != account_id:
            raise CloudflareError("cross_account_client")
        self.account_id = account_id

    def request(self, method, path, body=None):
        if not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_/-]+", path) or "//" in path:
            raise CloudflareError("invalid_api_path")
        if method not in {"GET", "POST"}:
            raise CloudflareError("mutation_denied")
        graphql = method == "POST" and path == "/graphql"
        disable = method == "POST" and re.fullmatch(r"/accounts/[A-Za-z0-9_-]+/workers/scripts/[A-Za-z0-9_-]+/subdomain", path)
        if method == "POST" and not (graphql or disable and body == {"enabled": False, "previews_enabled": False}):
            raise CloudflareError("mutation_denied")
        if method == "GET" and body is not None:
            raise CloudflareError("unexpected_request_body")
        account_path = re.match(r"/accounts/([^/]+)(?:/|$)", path)
        if account_path:
            self._bind(account_path.group(1))
        if graphql:
            try:
                self._bind(body["variables"]["accountTag"])
            except (KeyError, TypeError):
                raise CloudflareError("graphql_account_identity") from None
        attempts = self.max_attempts if not disable else 1
        for attempt in range(attempts):
            if self.requests >= self.max_requests:
                raise CloudflareError("request_budget_exhausted")
            self.requests += 1
            request = urllib.request.Request(API + path, method=method,
                data=None if body is None else json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + self._token(), "Accept": "application/json", "Content-Type": "application/json"})
            try:
                response = self.transport(request, self.timeout)
                if not isinstance(response.body, bytes) or len(response.body) > self.max_body_bytes:
                    raise CloudflareError("response_too_large")
                if response.status == 429 or 500 <= response.status < 600:
                    raise TimeoutError()
                if not 200 <= response.status < 300:
                    raise CloudflareError("http_" + str(response.status))
                payload = json.loads(response.body, parse_float=Decimal, parse_constant=lambda _: None)
                if not isinstance(payload, dict) or payload.get("errors"):
                    raise CloudflareError("api_errors")
                if not graphql and payload.get("success") is not True:
                    raise CloudflareError("api_unsuccessful")
                return payload
            except (TimeoutError, OSError, urllib.error.URLError):
                if attempt + 1 == attempts:
                    raise CloudflareError("transport_unavailable") from None
                self.sleep(min(2 ** attempt, 2))
            except (ValueError, UnicodeError, RecursionError):
                raise CloudflareError("invalid_json") from None

    def _subscriptions(self, account, scope, scope_id):
        if scope == "account":
            rows = _rows(self.request("GET", f"/accounts/{_identifier(scope_id)}/subscriptions"))
        else:
            row = self.request("GET", f"/zones/{_identifier(scope_id)}/subscription").get("result")
            if not isinstance(row, dict):
                raise CloudflareError("subscription_schema")
            rows = [row]
        result = {}
        key = ResourceKey(account.account_id, scope, "subscriptions", zone_id=scope_id if scope == "zone" else None)
        for row in rows:
            source_id = _identifier(row.get("id"))
            plan = row.get("rate_plan")
            currency = row.get("currency")
            if not isinstance(plan, dict) or currency != "USD":
                raise CloudflareError("subscription_schema")
            plan_id = _identifier(plan.get("id"))
            plan_scope = plan.get("scope")
            if "scope" in plan and (not isinstance(plan_scope, str) or plan_scope not in {"account", "zone"}):
                raise CloudflareError("subscription_schema")
            price = _number(row.get("price"))
            # The documented top-level price is in USD, even though display currency is optional.
            source = hashlib.sha256(json.dumps([account.account_id, source_id], separators=(",", ":")).encode()).hexdigest()
            item = Subscription(key, source, plan.get("public_name", plan_id), price, currency,
                                plan_id in account.expected_subscriptions, provider_id=source_id,
                                plan_id=plan_id, plan_scope=plan_scope)
            if source in result and result[source] != item:
                raise CloudflareError("conflicting_subscription")
            result[source] = item
        return tuple(result.values())

    def _billing_info(self, account, now):
        result = self.request("GET", f"/accounts/{account.account_id}/billable-usage/info").get("result")
        if not isinstance(result, dict) or type(result.get("covered")) is not bool:
            raise CloudflareError("billing_info_schema")
        subscriptions = result.get("subscriptions")
        if not isinstance(subscriptions, list):
            raise CloudflareError("billing_info_schema")
        active_anchors = set()
        valid_until = billing_window(now, account.billing_day)[1]
        for row in subscriptions:
            if not isinstance(row, dict):
                raise CloudflareError("billing_info_schema")
            _identifier(row.get("id"))
            anchor = _timestamp(row.get("billing_cycle_anchor_timestamp"))
            start = _timestamp(row.get("start_timestamp"))
            end = _timestamp(row["end_timestamp"]) if "end_timestamp" in row else None
            if end is not None and end <= start:
                raise CloudflareError("billing_info_window")
            if start <= now and (end is None or now < end):
                active_anchors.add(anchor)
                if end is not None:
                    valid_until = min(valid_until, end)
            elif start > now:
                valid_until = min(valid_until, start)
        verified = False
        if result["covered"] and account.billing_period_verified and len(active_anchors) == 1:
            anchor = next(iter(active_anchors))
            verified = anchor <= now and anchor.day == account.billing_day and not any((anchor.hour, anchor.minute, anchor.second, anchor.microsecond))
        return result["covered"], verified, valid_until if verified else None

    def _rated(self, account, now):
        rows = _rows(self.request("GET", f"/accounts/{account.account_id}/billable-usage"))
        if not rows:
            raise CloudflareError("empty_rated_response")
        charges = {}
        for row in rows:
            required = ("BillingAccountId", "BillingCurrency", "BillingPeriodStart", "ChargeCategory", "ChargeDescription", "ChargePeriodStart", "ChargePeriodEnd", "ServiceName", "PricingUnit", "ConsumedUnit")
            if any(field not in row for field in required) or row["BillingAccountId"] != account.account_id or row["ChargeCategory"] != "Usage":
                raise CloudflareError("rated_schema")
            if any(not isinstance(row[field], str) or not row[field] for field in required if field != "ConsumedUnit"):
                raise CloudflareError("rated_schema")
            if not re.fullmatch(r"[A-Z]{3}", row["BillingCurrency"]) or row.get("ChargeClass") not in {None, ""}:
                raise CloudflareError("rated_schema")
            start, end, billing_start = (_timestamp(row[field]) for field in ("ChargePeriodStart", "ChargePeriodEnd", "BillingPeriodStart"))
            if not billing_start <= start < end <= now:
                raise CloudflareError("rated_window")
            dimensions = [row.get(field) for field in required] + [row.get("SubscriptionId"), row.get("ZoneId"), "incremental"]
            source_key = hashlib.sha256(json.dumps(dimensions, separators=(",", ":")).encode()).hexdigest()
            charge = RatedCharge(ResourceKey(account.account_id, "account", "billing"), source_key,
                                 _number(row.get("ContractedCost")), "incremental", row["BillingCurrency"], start, end, "billable-usage-v1", "good")
            if source_key in charges and charges[source_key] != charge:
                raise CloudflareError("conflicting_rated_identity")
            charges[source_key] = charge
        return tuple(charges.values())

    def _workers(self, account_id, now, script=None):
        end = now.replace(second=0, microsecond=0)
        start = end - timedelta(minutes=5)
        rows_seen = set()
        totals = {}
        through = None
        query = '''query Guard($accountTag: string, $start: string, $end: string) {
          viewer { accounts(filter: {accountTag: $accountTag}) {
            workersInvocationsAdaptive(limit: 10000, filter: {datetime_geq: $start, datetime_lt: $end SCRIPT}) {
              sum { requests } dimensions { datetime scriptName status }
            }
          } }
        }'''.replace("SCRIPT", "" if script is None else ", scriptName: " + json.dumps(script))
        for minute in range(5):
            lower = start + timedelta(minutes=minute)
            upper = lower + timedelta(minutes=1)
            payload = self.request("POST", "/graphql", {"query": query, "variables": {"accountTag": account_id, "start": _iso(lower), "end": _iso(upper)}})
            try:
                accounts = payload["data"]["viewer"]["accounts"]
                if len(accounts) != 1:
                    raise CloudflareError("graphql_account_coverage")
                rows = accounts[0]["workersInvocationsAdaptive"]
                if not isinstance(rows, list) or not rows:
                    raise CloudflareError("graphql_no_heartbeat")
                if len(rows) >= GRAPHQL_LIMIT:
                    raise CloudflareError("graphql_truncated")
                for row in rows:
                    dims = row["dimensions"]
                    timestamp = _timestamp(dims["datetime"])
                    name, status = dims["scriptName"], dims["status"]
                    if not isinstance(name, str) or not name or not isinstance(status, str) or not lower <= timestamp < upper or script is not None and script != name:
                        raise CloudflareError("graphql_dimensions")
                    identity = (timestamp, name, status)
                    if identity in rows_seen:
                        raise CloudflareError("graphql_duplicate_bucket")
                    rows_seen.add(identity)
                    value = _number(row["sum"]["requests"])
                    if value != value.to_integral_value():
                        raise CloudflareError("graphql_request_unit")
                    totals[name] = totals.get(name, Decimal(0)) + value
                    through = max(through or timestamp, timestamp)
            except (KeyError, TypeError, AttributeError):
                raise CloudflareError("graphql_schema") from None
        observations = []
        if script is None:
            observations.append(Observation(ResourceKey(account_id, "account", "workers"), "workers.requests", sum(totals.values(), Decimal(0)), "requests", start, end, now, through, "approximate", "graphql-workers-adaptive", True, None))
        for name, total in sorted(totals.items()):
            observations.append(Observation(ResourceKey(account_id, "resource", "workers", name), "workers.requests", total, "requests", start, end, now, through, "approximate", "graphql-workers-adaptive", True, None))
        return tuple(observations)

    def collect(self, account, now, *, include_rated=True):
        self._bind(account.account_id)
        if Path(account.read_token_file) != self.token_file:
            raise CloudflareError("wrong_account_token_file")
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("now must be UTC")
        subscriptions = []
        coverage = {"workers.cpu_ms": "unsupported: no documented aggregate CPU sum", "workers.billing_period_requests": "unsupported: rolling five-minute window only", "billing_period": "unverified", "other_products": "unsupported: no fast metrics or cutoff", "inventory": "partial: only configured zones; no automatic enrollment"}
        for scope, scope_id in [("account", account.account_id)] + [("zone", zone) for zone in account.zones]:
            label = "subscriptions.account" if scope == "account" else "subscriptions.zone:" + scope_id
            try:
                subscriptions.extend(self._subscriptions(account, scope, scope_id))
                coverage[label] = "complete"
            except CloudflareError as error:
                coverage[label] = "unknown:" + str(error)
        rated = ()
        coverage["rated_usage"] = "not_fetched"
        coverage["billing_info"] = "not_fetched"
        coverage["billing_account_coverage"] = "unknown:not_fetched"
        if include_rated:
            try:
                covered, verified, valid_until = self._billing_info(account, now)
                coverage["billing_info"] = "parsed"
                coverage["billing_account_coverage"] = "covered" if covered else "unavailable"
                coverage["billing_period"] = "verified_config" if verified else "unverified"
                if verified:
                    coverage["billing_period_valid_until"] = _iso(valid_until)
            except CloudflareError as error:
                coverage["billing_info"] = "unknown:" + str(error)
                coverage["billing_account_coverage"] = "unknown:" + str(error)
            try:
                rated = self._rated(account, now)
                coverage["rated_usage"] = "unknown: source update heartbeat unavailable"
                coverage["rated_rows"] = "parsed"
                coverage["rated_data_through"] = _iso(max(row.period_end for row in rated))
                coverage["rated_freshness"] = "unknown: no provider update heartbeat; daily source"
            except CloudflareError as error:
                coverage["rated_usage"] = "unknown:" + str(error)
        try:
            observations = self._workers(account.account_id, now)
            coverage["workers.requests"] = "approximate: rolling five-minute window; adaptive sampling status unknown"
        except CloudflareError as error:
            end = now.replace(second=0, microsecond=0)
            observations = (Observation(ResourceKey(account.account_id, "account", "workers"), "workers.requests", None, "requests", end - timedelta(minutes=5), end, now, None, "unknown", "graphql-workers-adaptive", False, None),)
            coverage["workers.requests"] = "unknown:" + str(error)
        return Snapshot(account.account_id, observations, rated, tuple(subscriptions), coverage, now)

    def _resource(self, resource):
        key = resource.key
        if key.scope != "resource" or key.product != "workers":
            raise CloudflareError("unsupported_resource")
        self._bind(key.account_id)
        return key.account_id, _identifier(key.resource_id)

    def worker_endpoint_state(self, resource, *, zones=()):
        account, script = self._resource(resource)
        state = {"identity": {"account_id": account, "script_name": script}, "enabled": None, "previews_enabled": None,
                 "routes": (), "custom_domains": (), "internal_triggers": "unknown", "complete": False, "endpoints": (), "reason": "unknown_internal_reachability"}
        try:
            flags = self.request("GET", f"/accounts/{account}/workers/scripts/{script}/subdomain")["result"]
            if not all(type(flags.get(flag)) is bool for flag in ("enabled", "previews_enabled")):
                raise CloudflareError("endpoint_flags_schema")
            state.update({flag: flags[flag] for flag in ("enabled", "previews_enabled")})
            domains = _rows(self.request("GET", f"/accounts/{account}/workers/domains"))
            state["custom_domains"] = tuple(row for row in domains if row.get("service") == script)
            routes = []
            for zone in sorted(set(zones) | set(resource.zones)):
                routes.extend(row for row in _rows(self.request("GET", f"/zones/{_identifier(zone)}/workers/routes")) if row.get("script") == script)
            state["routes"] = tuple(routes)
            schedules = self.request("GET", f"/accounts/{account}/workers/scripts/{script}/schedules")["result"]["schedules"]
            if not isinstance(schedules, list):
                raise CloudflareError("schedules_schema")
            state["schedules"] = tuple(schedules)
            # Inbound service bindings, queue consumers and account-wide routes cannot
            # be proven absent using only this enrolled-resource inventory.
        except (CloudflareError, KeyError, TypeError) as error:
            state["reason"] = str(error) if isinstance(error, CloudflareError) else "endpoint_schema"
        return state

    def disable_worker_endpoints(self, resource):
        account, script = self._resource(resource)
        result = self.request("POST", f"/accounts/{account}/workers/scripts/{script}/subdomain", {"enabled": False, "previews_enabled": False}).get("result")
        if not isinstance(result, dict) or not all(type(result.get(flag)) is bool for flag in ("enabled", "previews_enabled")):
            raise CloudflareError("endpoint_flags_schema")
        return {flag: result[flag] for flag in ("enabled", "previews_enabled")}

    def fresh_trigger(self, resource, *, now=None):
        account, script = self._resource(resource)
        return self._workers(account, now or datetime.now(timezone.utc), script)[0]

    def probe_endpoint(self, url):
        try:
            parsed = urllib.parse.urlsplit(url)
            valid = parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in {None, 443} and parsed.hostname and parsed.hostname.endswith(".workers.dev") and not parsed.query and not parsed.fragment
        except (ValueError, TypeError):
            valid = False
        if not valid:
            return "unknown"
        if self.requests >= self.max_requests:
            return "unknown"
        self.requests += 1
        try:
            # No Authorization header, cookies, redirects or API credentials on public probes.
            response = self.transport(urllib.request.Request(url, method="GET", headers={"Cache-Control": "no-cache"}), self.timeout)
            if len(response.body) > self.max_body_bytes:
                return "unknown"
            # Arbitrary 403/404 can come from a still-running Worker. No status alone
            # is a documented provider cutoff signature, so never certify it blocked.
            return "reachable" if 200 <= response.status < 300 else "unknown"
        except (OSError, TimeoutError, urllib.error.URLError):
            return "unknown"


def collect(account, now, *, include_rated=True):
    return Client(account.read_token_file, account_id=account.account_id).collect(account, now, include_rated=include_rated)


def worker_endpoint_state(resource, client, **kwargs):
    return client.worker_endpoint_state(resource, **kwargs)
