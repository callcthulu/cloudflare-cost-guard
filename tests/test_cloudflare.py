"""Offline fixtures follow the linked Cloudflare contracts, never live credentials."""
import json
import os
import ssl
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch
from types import SimpleNamespace

from cfguard.cloudflare import Client, CloudflareError, HttpResponse
from cfguard.models import AccountConfig, ResourceConfig, ResourceKey

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def envelope(result, **extra):
    return {"success": True, "errors": [], "result": result, **extra}


def response(value, status=200):
    return HttpResponse(status, json.dumps(value).encode(), {})


class FakeHTTP:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append(request)
        return self.handler(request)


class CollectorTests(unittest.TestCase):
    def test_deep_json_is_sanitized_and_other_account_can_continue(self):
        body = b'{"success":true,"result":[],"unused":' + b'[' * 20000 + b'0' + b']' * 20000 + b'}'
        client = self.client(lambda _: HttpResponse(200,body,{}))
        with self.assertRaisesRegex(CloudflareError,'invalid_json'):
            client.request('GET','/accounts/' + self.account.account_id + '/subscriptions')
        self.assertEqual(len(self.http.calls),1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = Path(self.tmp.name) / "token"
        self.token.write_text("fixture-token")
        self.token.chmod(0o600)
        self.account = AccountConfig("fixture", "a" * 32, self.token, 1, Decimal("0"), "USD", ("free",), ("b" * 32,))

    def client(self, handler, **kwargs):
        self.http = FakeHTTP(handler)
        return Client(self.token, transport=self.http, sleep=lambda _: None, **kwargs)

    def healthy(self, req):
        path = urlsplit(req.full_url).path
        if path.endswith("/subscriptions"):
            return response(envelope([{"id": "sub-free", "price": 0, "currency": "USD", "rate_plan": {"id": "free", "public_name": "Free"}}]))
        if path.endswith("/billable-usage"):
            return response(envelope([]))
        variables = json.loads(req.data)["variables"]
        start = datetime.fromisoformat(variables["start"].replace("Z", "+00:00"))
        return response({"data": {"viewer": {"accounts": [{"workersInvocationsAdaptive": [{"sum": {"requests": 2}, "dimensions": {"datetime": start.isoformat(), "scriptName": "shared-worker", "status": "success"}}]}]}}, "errors": None})

    def test_observe_is_read_only_and_account_total_is_not_duplicated(self):
        snapshot = self.client(self.healthy).collect(self.account, NOW)
        totals = [o for o in snapshot.observations if o.metric == "workers.requests" and o.key.scope == "account"]
        self.assertEqual([o.value for o in totals], [Decimal(10)])
        self.assertEqual(len([o for o in snapshot.observations if o.key.resource_id == "shared-worker"]), 1)
        self.assertTrue(all(r.method == "GET" or urlsplit(r.full_url).path.endswith("/graphql") for r in self.http.calls))
        self.assertIn("unsupported", snapshot.coverage["workers.cpu_ms"])
        self.assertIsNone(totals[0].sampled)
        self.assertEqual(totals[0].quality, "approximate")

    def test_http_failures_are_bounded_sanitized_and_never_zero(self):
        for status in (301, 302, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                client = self.client(lambda _: HttpResponse(status, b"fixture-token secret raw payload", {"Location": "https://evil.invalid"}))
                snapshot = client.collect(self.account, NOW)
                self.assertEqual(snapshot.observations[0].value, None)
                self.assertIn("unknown", snapshot.coverage["rated_usage"])
                self.assertNotIn("fixture-token", repr(snapshot))
                self.assertLessEqual(len(self.http.calls), 16)

    def test_graphql_200_errors_empty_truncated_and_bad_dimensions_are_unknown(self):
        cases = [{"data": None, "errors": [{"message": "secret"}]}, {"data": {"viewer": {"accounts": []}}},
                 {"data": {"viewer": {"accounts": [{"workersInvocationsAdaptive": []}]}}},
                 {"data": {"viewer": {"accounts": [{"workersInvocationsAdaptive": [{"sum": {"requests": 2}, "dimensions": {}}]}]}}}]
        for bad in cases:
            with self.subTest(bad=bad):
                client = self.client(lambda req: response(bad) if req.data else self.healthy(req))
                obs = client.collect(self.account, NOW).observations[0]
                self.assertIsNone(obs.value)
                self.assertFalse(obs.complete)

    def test_missing_recent_bucket_does_not_create_fresh_heartbeat(self):
        def handler(req):
            if req.data:
                value = json.loads(self.healthy(req).body)
                value["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"][0]["dimensions"]["datetime"] = (NOW - timedelta(days=1)).isoformat()
                return response(value)
            return self.healthy(req)
        self.assertIsNone(self.client(handler).collect(self.account, NOW).observations[0].value)

    def test_subscriptions_use_account_and_zone_scopes_and_optional_pagination(self):
        snapshot = self.client(self.healthy).collect(self.account, NOW)
        self.assertEqual({s.key.scope for s in snapshot.subscriptions}, {"account", "zone"})
        self.assertTrue(all(s.allowed for s in snapshot.subscriptions))
        def paged(req):
            if req.full_url.endswith("/subscriptions"):
                return response(envelope([], result_info={"page": 1, "per_page": 20, "count": 0, "total_count": 40}))
            return self.healthy(req)
        snapshot = self.client(paged).collect(self.account, NOW)
        self.assertIn("unknown", snapshot.coverage["subscriptions.account"])

    def test_missing_price_currency_or_identity_is_unknown_not_free(self):
        def handler(req):
            return response(envelope([{"rate_plan": {"id": "free"}}])) if req.full_url.endswith("/subscriptions") else self.healthy(req)
        snapshot = self.client(handler).collect(self.account, NOW)
        self.assertIn("unknown", snapshot.coverage["subscriptions.account"])

    def rated_row(self):
        return {"BillingAccountId": self.account.account_id, "BillingCurrency": "USD", "BillingPeriodStart": "2026-10-01T00:00:00Z", "ChargeCategory": "Usage", "ChargeClass": None,
                "ChargeDescription": "Workers Standard requests", "ChargePeriodStart": "2026-10-25T00:00:00Z", "ChargePeriodEnd": "2026-10-26T00:00:00Z", "ContractedCost": 0.2,
                "CumulatedContractedCost": 7, "ServiceName": "Workers Standard", "SubscriptionId": "sub1", "PricingUnit": "Count", "ConsumedUnit": "Count"}

    def test_v1_rated_contract_deduplicates_incremental_and_never_sums_cumulative(self):
        row = self.rated_row()
        snapshot = self.client(lambda req: response(envelope([row, row])) if req.full_url.endswith("/billable-usage") else self.healthy(req)).collect(self.account, NOW)
        self.assertEqual(len(snapshot.rated_charges), 1)
        self.assertEqual(snapshot.rated_charges[0].amount, Decimal("0.2"))
        self.assertEqual(snapshot.rated_charges[0].kind, "incremental")
        self.assertIn("unverified", snapshot.coverage["billing_period"])

    def test_v1_conflicting_identity_or_guessed_lowercase_schema_is_unknown(self):
        row = self.rated_row()
        for rows in ([row, {**row, "ContractedCost": 0.4}], [{"amount": 1, "currency": "USD"}], [{**row, "BillingAccountId": "wrong"}]):
            snapshot = self.client(lambda req: response(envelope(rows)) if req.full_url.endswith("/billable-usage") else self.healthy(req)).collect(self.account, NOW)
            self.assertIn("unknown", snapshot.coverage["rated_usage"])
            self.assertEqual(snapshot.rated_charges, ())

    def test_transport_timeouts_malformed_and_oversized_bodies(self):
        def timeout(_):
            raise TimeoutError("secret fixture-token")
        for handler in (timeout, lambda _: HttpResponse(200, b"{", {}), lambda _: HttpResponse(200, b"x" * 2001, {})):
            snapshot = self.client(handler, max_body_bytes=2000).collect(self.account, NOW)
            self.assertIn("unknown", snapshot.coverage["rated_usage"])
            self.assertNotIn("fixture-token", repr(snapshot))

    def test_transport_rejects_wrong_origin_mutations_and_cross_account(self):
        client = self.client(self.healthy)
        for path in ("https://evil.invalid/client/v4/accounts/a", "//evil.invalid", "/accounts/a/../b", "/accounts/a?secret=x"):
            with self.assertRaises(CloudflareError):
                client.request("GET", path)
        with self.assertRaises(CloudflareError):
            client.request("DELETE", "/accounts/a")
        client.collect(self.account, NOW)
        other = AccountConfig("other", "c" * 32, self.token, 1, Decimal(0), "USD")
        with self.assertRaises(CloudflareError):
            client.collect(other, NOW)

    def test_request_budget_stops_without_unbounded_retries(self):
        client = self.client(self.healthy, max_requests=2)
        snapshot = client.collect(self.account, NOW)
        self.assertEqual(len(self.http.calls), 2)
        self.assertIn("unknown", snapshot.coverage["workers.requests"])

    def test_hourly_cadence_skips_rated_network_without_claiming_zero(self):
        snapshot = self.client(self.healthy).collect(self.account, NOW, include_rated=False)
        self.assertEqual(snapshot.rated_charges, ())
        self.assertEqual(snapshot.coverage["rated_usage"], "not_fetched")
        self.assertFalse(any("billable-usage" in req.full_url for req in self.http.calls))

    def test_bound_client_cannot_write_other_account_even_through_request(self):
        client = self.client(lambda req: response(envelope({"enabled": False, "previews_enabled": False})) if req.full_url.endswith("/subdomain") else self.healthy(req))
        client.collect(self.account, NOW)
        with self.assertRaises(CloudflareError):
            client.request("POST", "/accounts/" + "c" * 32 + "/workers/scripts/other/subdomain", {"enabled": False, "previews_enabled": False})

    def test_empty_subdomain_response_is_sanitized_error(self):
        resource = ResourceConfig(ResourceKey(self.account.account_id, "resource", "workers", "fixture-worker"), "fixture")
        client = self.client(lambda req: response({"success": True, "errors": []}))
        with self.assertRaises(CloudflareError):
            client.disable_worker_endpoints(resource)

    def test_token_permissions_and_symlink(self):
        if os.name != "nt":
            self.token.chmod(0o644)
            with self.assertRaises(CloudflareError):
                self.client(self.healthy).request("GET", "/accounts/" + "a" * 32 + "/subscriptions")

    def test_token_symlink_is_rejected(self):
        link = Path(self.tmp.name) / "link"
        try:
            link.symlink_to(self.token)
        except OSError:
            self.skipTest("OS does not permit this user to create symlinks")
        client = Client(link, transport=FakeHTTP(self.healthy))
        with self.assertRaises(CloudflareError):
            client.request("GET", "/accounts/" + "a" * 32 + "/subscriptions")

    def test_tls_is_verified_and_redirect_handler_denies_following(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:8888"}):
            client = self.client(self.healthy)
        tls = [h for h in client.opener.handlers if hasattr(h, "_context")][0]._context
        self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(tls.check_hostname)
        redirect = [h for h in client.opener.handlers if hasattr(h, "redirect_request")][0]
        self.assertIsNone(redirect.redirect_request(None, None, 302, "", {}, "https://evil.invalid"))
        proxy = [h for h in client.opener.handlers if hasattr(h, "proxies")]
        self.assertFalse(any(h.proxies for h in proxy))

    def test_root_owned_0640_token_only_allows_current_service_group(self):
        client = self.client(self.healthy)
        actual = self.token.stat()
        trusted = SimpleNamespace(st_mode=0o100640, st_uid=0, st_gid=123, st_dev=actual.st_dev, st_ino=actual.st_ino)
        with patch("cfguard.cloudflare.os.name", "posix"), patch("cfguard.cloudflare.os.geteuid", return_value=456, create=True), patch("cfguard.cloudflare.os.getegid", return_value=123, create=True), patch.object(Path, "lstat", return_value=trusted), patch("cfguard.cloudflare.os.fstat", return_value=trusted):
            self.assertEqual(client._token(), "fixture-token")
            trusted.st_gid = 999
            with self.assertRaises(CloudflareError):
                client._token()

    def test_saturated_graphql_partition_is_unknown(self):
        def handler(req):
            if not req.data:
                return self.healthy(req)
            payload = json.loads(self.healthy(req).body)
            rows = payload["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"]
            rows *= 10000
            return response(payload)
        snapshot = self.client(handler).collect(self.account, NOW)
        self.assertIn("graphql_truncated", snapshot.coverage["workers.requests"])

    def test_two_accounts_same_script_use_separate_tokens_and_identities(self):
        first = self.client(self.healthy).collect(self.account, NOW)
        self.token.write_text("second-fixture-token")
        other = AccountConfig("other", "c" * 32, self.token, 1, Decimal(0), "USD")
        second = self.client(self.healthy).collect(other, NOW)
        self.assertNotEqual(first.observations[1].key, second.observations[1].key)
        self.assertTrue(all(req.get_header("Authorization") == "Bearer second-fixture-token" for req in self.http.calls))

    def test_public_probes_send_no_credentials_and_cannot_guess_blocked(self):
        client = self.client(lambda req: HttpResponse(404, b"not found", {}))
        self.assertEqual(client.probe_endpoint("https://fixture.account.workers.dev/"), "unknown")
        self.assertIsNone(self.http.calls[0].get_header("Authorization"))
        self.assertEqual(client.probe_endpoint("https://fixture.account.workers.dev:bad/"), "unknown")

    def test_write_timeout_is_never_retried(self):
        resource = ResourceConfig(ResourceKey(self.account.account_id, "resource", "workers", "fixture-worker"), "fixture")
        def timeout(req):
            raise TimeoutError()
        client = self.client(timeout)
        with self.assertRaises(CloudflareError):
            client.disable_worker_endpoints(resource)
        self.assertEqual(len(self.http.calls), 1)

    def test_narrow_disable_has_only_documented_flags_and_no_retry(self):
        resource = ResourceConfig(ResourceKey(self.account.account_id, "resource", "workers", "fixture-worker"), "fixture")
        client = self.client(lambda req: response(envelope({"enabled": False, "previews_enabled": False})))
        self.assertEqual(client.disable_worker_endpoints(resource), {"enabled": False, "previews_enabled": False})
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(json.loads(self.http.calls[0].data), {"enabled": False, "previews_enabled": False})
        self.assertTrue(self.http.calls[0].full_url.endswith("/workers/scripts/fixture-worker/subdomain"))
        self.assertEqual(self.http.calls[0].method, "POST")

    def test_endpoint_inventory_unknown_internal_reachability_blocks_completeness(self):
        resource = ResourceConfig(ResourceKey(self.account.account_id, "resource", "workers", "fixture-worker"), "fixture")
        def handler(req):
            path = urlsplit(req.full_url).path
            if path.endswith("/subdomain"):
                return response(envelope({"enabled": True, "previews_enabled": True}))
            if path.endswith("/schedules"):
                return response(envelope({"schedules": []}))
            return response(envelope([]))
        state = self.client(handler).worker_endpoint_state(resource)
        self.assertFalse(state["complete"])
        self.assertEqual(state["internal_triggers"], "unknown")


if __name__ == "__main__":
    unittest.main()
