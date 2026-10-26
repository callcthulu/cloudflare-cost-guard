import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from cfguard.config import billing_window
from cfguard.models import (AccountConfig, Config, Observation, Price, RatedCharge,
                            ResourceConfig, ResourceKey, ResourceState, Snapshot,
                            Subscription, Threshold)
from cfguard.policy import evaluate, rated_total

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
START, END = billing_window(NOW, 1)
ACCOUNT = ResourceKey("a", "account", "workers")
WORKER = ResourceKey("a", "resource", "workers", "shared")
PRICE = Price("requests", "requests", "USD", D("0.30"), D("1000000"), D("10000000"), "fixture", "2026-10-01")


def account(**kwargs):
    return AccountConfig("sandbox", "a", "/etc/cfguard/read.token", 1, D("0"), "USD",
                         prices=(PRICE,), billing_period_verified=True, **kwargs)


def observation(key=ACCOUNT, **kwargs):
    values = dict(key=key, metric="requests", value=D("12000000"), unit="requests",
                  period_start=START, period_end=END, fetched_at=NOW, data_through=NOW,
                  quality="good", source="fixture", complete=True, sampled=False)
    values.update(kwargs)
    return Observation(**values)


def snapshot(observations=(), rated_charges=(), subscriptions=(), coverage=None):
    return Snapshot("a", observations, rated_charges, subscriptions,
                    coverage or {"requests": "supported", "rated": "complete", "subscriptions": "complete"}, NOW)


class PolicyTests(unittest.TestCase):
    def config(self, **kwargs):
        return Config(accounts=(account(),), resources=(ResourceConfig(WORKER, "Shared", hostnames=("one.example", "two.example"),
            thresholds=(Threshold("requests", D("13000000"), "requests"),)),), **kwargs)

    def test_shared_allowance_account_estimate_once_separate_from_usage(self):
        decisions = evaluate(self.config(), snapshot((observation(), observation(WORKER))), {})
        estimates = [d for d in decisions if d.metric == "estimated_cost"]
        self.assertEqual(len(estimates), 1)
        self.assertEqual(estimates[0].value, D("0.60"))
        self.assertEqual(estimates[0].key.scope, "account")
        self.assertEqual(estimates[0].status, "tripped")
        self.assertIsNone(estimates[0].proposed_action)
        usage = [d for d in decisions if d.key == WORKER and d.metric == "requests"]
        self.assertEqual(usage[0].value, D("12000000"))
        self.assertFalse(any(d.metric == "rated_cost" and d.value == D("0.60") for d in decisions))

    def test_incremental_duplicate_cumulative_and_previous_period(self):
        def row(key, amount, kind="incremental", start=START, end=END):
            return RatedCharge(ACCOUNT, key, D(amount), kind, "USD", start, end, "fixture", "good")
        rows = (row("one", ".20"), row("two", ".40"), row("one", ".20"), row("total", ".60", "cumulative"),
                row("old", "99", start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=START))
        self.assertEqual(rated_total(rows, "a", "USD", START, END), D(".60"))
        decisions = evaluate(self.config(), snapshot(rated_charges=rows,
            subscriptions=(Subscription(ACCOUNT, "plan", "Paid", D("7.00"), "USD", False),)), {})
        self.assertEqual(next(d.value for d in decisions if d.metric == "rated_cost"), D(".60"))
        self.assertEqual(next(d.value for d in decisions if d.metric == "subscription_commitment"), D("7.00"))
        self.assertIsNone(rated_total(rows + (row("one", ".30"),), "a", "USD", START, END))

    def test_missing_stale_partial_and_unknown_do_not_clear_latch(self):
        config = self.config()
        prior = {WORKER: ResourceState(status="tripped", dimensions={"requests": "tripped"})}
        for obs in ((), (observation(WORKER, data_through=NOW - timedelta(days=1)),),
                    (observation(WORKER, complete=False),), (observation(WORKER, value=None),)):
            with self.subTest(obs=obs):
                decision = next(d for d in evaluate(config, snapshot(obs), prior) if d.key == WORKER and d.metric == "requests")
                self.assertEqual(decision.status, "tripped")
                self.assertIn("latched", decision.reason_code)

    def test_sampled_and_unknown_sampling_cannot_trip(self):
        config = replace(self.config(), resources=(replace(self.config().resources[0],
                thresholds=(Threshold("requests", D("1"), "requests"),), permitted_action="disable_worker_endpoints"),))
        for sampled in (True, None):
            decision = next(d for d in evaluate(config, snapshot((observation(WORKER, sampled=sampled),)), {}) if d.key == WORKER)
            self.assertIn(decision.status, ("warning", "unknown"))
            self.assertIsNone(decision.proposed_action)

    def test_missing_cpu_unpriced_and_unverified_period(self):
        config = replace(self.config(), accounts=(replace(account(), prices=()),), resources=(replace(self.config().resources[0],
            thresholds=(Threshold("cpu_ms", D("1"), "milliseconds"),)),))
        decisions = evaluate(config, snapshot((observation(),), coverage={"cpu_ms": "unsupported"}), {})
        self.assertEqual(next(d.reason_code for d in decisions if d.metric == "cpu_ms"), "unsupported")
        self.assertEqual(next(d.value for d in decisions if d.metric == "estimated_cost"), None)
        config = replace(config, accounts=(replace(account(), billing_period_verified=False),))
        self.assertEqual(next(d.reason_code for d in evaluate(config, snapshot((observation(),)), {}) if d.metric == "estimated_cost"), "billing_period_unverified")

    def test_short_window_and_resource_subset_cannot_get_monthly_allowance(self):
        for rows in ((observation(period_start=NOW - timedelta(minutes=5), period_end=NOW),),
                     (observation(WORKER),)):
            decision = next(d for d in evaluate(self.config(), snapshot(rows), {}) if d.metric == "estimated_cost")
            self.assertEqual(decision.status, "unknown")
            self.assertIsNone(decision.value)

    def test_rated_stale_currency_conflict_and_overlapping_period_are_unknown(self):
        row = RatedCharge(ACCOUNT, "one", D(".20"), "incremental", "USD", START, END, "fixture", "good")
        for rows, coverage in (((row,), {"rated_usage": "stale"}),
                               ((replace(row, currency="EUR"),), {"rated_usage": "complete"}),
                               ((replace(row, period_start=START - timedelta(days=1)),), {"rated_usage": "complete"}),
                               ((), {"rated_usage": "complete"})):
            decision = next(d for d in evaluate(self.config(), snapshot(rated_charges=rows, coverage=coverage), {}) if d.metric == "rated_cost")
            self.assertEqual(decision.status, "unknown")
            self.assertIsNone(decision.value)

    def test_healthy_cannot_clear_latch_and_exact_usage_only_proposes(self):
        resource = replace(self.config().resources[0], thresholds=(Threshold("requests", D("1"), "requests"),), permitted_action="disable_worker_endpoints")
        config = replace(self.config(), resources=(resource,))
        trip = next(d for d in evaluate(config, snapshot((observation(WORKER),)), {}) if d.key == WORKER)
        self.assertEqual(trip.status, "tripped")
        self.assertEqual(trip.proposed_action, "disable_worker_endpoints")
        healthy = next(d for d in evaluate(config, snapshot((observation(WORKER, value=D("0")),)),
                            {WORKER: ResourceState(dimensions={"requests": "tripped"})}) if d.key == WORKER)
        self.assertEqual(healthy.status, "tripped")
        self.assertIsNone(healthy.proposed_action)

    def test_different_accounts_and_breakdowns_never_add_to_account_total(self):
        unrelated = observation(ResourceKey("other", "account", "workers"), value=D("999999999"))
        breakdown = observation(ResourceKey("a", "zone", "workers", zone_id="z"), value=D("999999999"))
        rows = (observation(), observation(), observation(WORKER), unrelated, breakdown)
        estimates = [d for d in evaluate(self.config(), snapshot(rows), {}) if d.metric == "estimated_cost"]
        self.assertEqual([d.value for d in estimates], [D(".60")])


if __name__ == "__main__": unittest.main()
