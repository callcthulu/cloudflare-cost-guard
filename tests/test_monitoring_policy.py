import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

try:
    from cfguard.monitoring.policy import assess
except ImportError:
    assess = None


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
A, R, S = "a" * 16, "b" * 16, "c" * 16
AS = "account:" + A


def at(seconds=0):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def observation():
    return {
        "version": 1, "observed_at": at(),
        "guard": {"status": "ok", "last_attempt": at(-60),
                  "last_finished": at(-60), "last_collection_success": None,
                  "pending_notifications": 0, "oldest_pending_at": None},
        "accounts": [{"account_ref": A, "snapshot_at": at(-60),
                      "subscriptions_status": "complete", "subscriptions": [],
                      "coverage": [{"source": "billing_account_coverage", "status": "covered",
                                    "known_limitation": False}],
                      "inventory": {p: {"status": "complete", "refs": [], "expected": []}
                                    for p in ("workers", "zones")}}],
    }


def row(amount="1", resource=R):
    return {"resource_ref": resource, "amount": amount, "currency": "USD",
            "quality": "good", "allowed": True}


class PolicyTests(unittest.TestCase):
    def check(self, obs=None, **kwargs):
        self.assertTrue(callable(assess), "pure assessment has not been implemented")
        return assess(observation() if obs is None else obs, NOW, **kwargs)

    def reasons(self, result):
        return {issue["reason"] for issue in result["issues"]}

    def test_fresh_complete_evidence_verifies_scopes(self):
        result = self.check()
        self.assertEqual(result["issues"], [])
        self.assertIn("guard:liveness", result["verified_scopes"])
        self.assertIn(AS + ":subscriptions", result["verified_scopes"])
        self.assertIn(AS + ":inventory:workers", result["verified_scopes"])

    def test_invalid_observation_verifies_nothing(self):
        for obs in (False, {}, {"version": 2}, [], "private raw text"):
            with self.subTest(obs=obs):
                result = self.check(obs)
                self.assertIn("observation_unknown", self.reasons(result))
                self.assertEqual(result["verified_scopes"], [])

    def test_stale_and_future_observation_cannot_recover(self):
        for seconds in (-901, 61):
            obs = observation()
            obs["observed_at"] = at(seconds)
            result = self.check(obs)
            self.assertEqual(result["verified_scopes"], [])
            self.assertTrue(result["issues"])

    def test_guard_outage_is_independent_of_sampler_freshness(self):
        obs = observation()
        obs["guard"]["last_finished"] = at(-901)
        result = self.check(obs)
        self.assertIn("guard_stale", self.reasons(result))
        self.assertNotIn("guard:liveness", result["verified_scopes"])
        self.assertIn(AS + ":subscriptions", result["verified_scopes"])

    def test_guard_missing_unknown_and_future_never_verify(self):
        for change in ({"status": "unknown"}, {"last_finished": None},
                       {"last_attempt": at(61)}, {"last_finished": "raw-secret"}):
            obs = observation()
            obs["guard"].update(change)
            result = self.check(obs)
            self.assertIn("guard_unknown", self.reasons(result))
            self.assertNotIn("guard:liveness", result["verified_scopes"])

    def test_notification_backlog_age_and_affirmative_recovery(self):
        obs = observation()
        obs["guard"].update(pending_notifications=3, oldest_pending_at=at(-901))
        result = self.check(obs)
        self.assertIn("notification_backlog", self.reasons(result))
        self.assertIn("guard:notifications", result["verified_scopes"])
        obs["guard"].update(pending_notifications=0, oldest_pending_at=None)
        self.assertNotIn("notification_backlog", self.reasons(self.check(obs)))

    def test_unknown_notification_count_cannot_recover(self):
        for count, stamp in ((None, None), (True, None), (-1, None), (1, None), (1, at(61))):
            obs = observation()
            obs["guard"].update(pending_notifications=count, oldest_pending_at=stamp)
            result = self.check(obs)
            self.assertIn("notification_unknown", self.reasons(result))
            self.assertNotIn("guard:notifications", result["verified_scopes"])

    def test_account_snapshot_age_cannot_be_hidden_by_sampler(self):
        for stamp in (at(-901), at(61), None, "2026-10-28T12:00:00"):
            obs = observation()
            obs["accounts"][0]["snapshot_at"] = stamp
            result = self.check(obs)
            self.assertIn("snapshot_unknown", self.reasons(result))
            self.assertNotIn(AS + ":snapshot", result["verified_scopes"])
            self.assertNotIn(AS + ":subscriptions", result["verified_scopes"])
            self.assertNotIn(AS + ":coverage:billing_account_coverage", result["verified_scopes"])
            self.assertIn(AS + ":inventory:workers", result["verified_scopes"])

    def test_fresh_inventory_drift_survives_stale_or_missing_guard_snapshot(self):
        for stamp in (at(-901), None):
            obs = observation()
            obs["accounts"][0]["snapshot_at"] = stamp
            obs["accounts"][0]["inventory"]["workers"]["refs"] = [R]
            result = self.check(obs)
            self.assertIn("snapshot_unknown", self.reasons(result))
            self.assertIn("inventory_added", self.reasons(result))
            obs["accounts"][0]["inventory"]["workers"]["status"] = "unknown"
            self.assertNotIn(AS + ":inventory:workers", self.check(obs)["verified_scopes"])

    def test_each_positive_commitment_warns_without_summing_or_allowed_plan_exemption(self):
        obs = observation()
        obs["accounts"][0]["subscriptions"] = [row("0.01"), row("99", S)]
        result = self.check(obs)
        positives = [i for i in result["issues"] if i["reason"] == "positive_subscription"]
        self.assertEqual({i["resource_ref"] for i in positives}, {R, S})
        self.assertEqual({i["details"]["amount"] for i in positives}, {"0.01", "99"})

    def test_incomplete_subscriptions_still_report_valid_positive(self):
        obs = observation()
        account = obs["accounts"][0]
        account.update(subscriptions_status="unknown", subscriptions=[row()])
        result = self.check(obs)
        self.assertIn("positive_subscription", self.reasons(result))
        self.assertIn("subscriptions_unknown", self.reasons(result))
        self.assertNotIn(AS + ":subscriptions", result["verified_scopes"])

    def test_invalid_subscription_cannot_recover_prior_positive(self):
        for change in ({"amount": "NaN"}, {"amount": "Infinity"}, {"amount": "-1"},
                       {"amount": "1" * 65}, {"amount": "1" + "0" * 101},
                       {"amount": "0." + "0" * 100 + "1"},
                       {"amount": 0}, {"currency": "EUR"}, {"quality": "unknown"},
                       {"resource_ref": "real private id"}, {"allowed": "yes"}):
            obs = observation()
            candidate = row("0")
            candidate.update(change)
            obs["accounts"][0]["subscriptions"] = [candidate]
            result = self.check(obs)
            self.assertIn("subscriptions_unknown", self.reasons(result))
            self.assertNotIn(AS + ":subscriptions", result["verified_scopes"])

    def test_conflicting_same_identity_is_unknown_without_choosing_zero_or_positive(self):
        obs = observation()
        obs["accounts"][0]["subscriptions"] = [row("0"), row("2")]
        result = self.check(obs)
        self.assertIn("subscriptions_unknown", self.reasons(result))
        self.assertNotIn("positive_subscription", self.reasons(result))
        self.assertNotIn(AS + ":subscriptions", result["verified_scopes"])

    def test_unexpected_plan_and_positive_are_separate_warnings(self):
        obs = observation()
        candidate = row()
        candidate["allowed"] = False
        obs["accounts"][0]["subscriptions"] = [candidate]
        self.assertEqual(self.reasons(self.check(obs)), {"positive_subscription", "unexpected_subscription"})

    def test_complete_inventory_reports_new_and_removed_resources_next_sample(self):
        obs = observation()
        inv = obs["accounts"][0]["inventory"]["workers"]
        inv.update(refs=[R], expected=[R])
        self.assertEqual(self.check(obs)["issues"], [])
        inv.update(refs=[S], expected=[R])
        result = self.check(obs)
        self.assertEqual({(i["reason"], i["resource_ref"]) for i in result["issues"]},
                         {("inventory_added", S), ("inventory_removed", R)})

    def test_incomplete_inventory_cannot_clear_drift(self):
        obs = observation()
        inv = obs["accounts"][0]["inventory"]["workers"]
        for status in ("unknown", "unavailable", "approximate", "unsupported"):
            inv.update(status=status, refs=[], expected=[R])
            result = self.check(obs)
            self.assertIn("inventory_unknown", self.reasons(result))
            self.assertNotIn("inventory_removed", self.reasons(result))
            self.assertNotIn(AS + ":inventory:workers", result["verified_scopes"])

    def test_invalid_inventory_identity_or_duplicates_never_verifies(self):
        for refs in (["private.domain"], [R, R], None, "not-a-list"):
            obs = observation()
            obs["accounts"][0]["inventory"]["workers"]["refs"] = refs
            result = self.check(obs)
            self.assertIn("inventory_unknown", self.reasons(result))
            self.assertNotIn(AS + ":inventory:workers", result["verified_scopes"])

    def test_unknown_product_is_explicit_without_echoing_name(self):
        obs = observation()
        obs["accounts"][0]["inventory"]["secret-product"] = {"status": "complete"}
        result = self.check(obs)
        self.assertIn("inventory_unsupported", self.reasons(result))
        self.assertNotIn("secret-product", json.dumps(result))

    def test_coverage_unknown_states_alert_without_recovery(self):
        for status in ("unknown", "stale", "unavailable", "approximate", "unsupported", "unverified"):
            obs = observation()
            obs["accounts"][0]["coverage"][0]["status"] = status
            result = self.check(obs)
            self.assertIn("coverage_unknown", self.reasons(result))
            self.assertNotIn(AS + ":coverage:billing_account_coverage", result["verified_scopes"])

    def test_exact_known_limitation_is_persistent_not_healthy(self):
        for status in ("unavailable", "unsupported", "approximate", "unverified"):
            obs = observation()
            obs["accounts"][0]["coverage"][0].update(status=status, known_limitation=True)
            result = self.check(obs)
            self.assertEqual(result["issues"], [])
            self.assertEqual(len(result["limitations"]), 1)
            self.assertNotIn(AS + ":coverage:billing_account_coverage", result["verified_scopes"])

    def test_known_limitation_requires_boolean_and_allowed_state(self):
        for status, known in (("unknown", True), ("stale", True), ("unavailable", "true"),
                              ("unavailable", 1)):
            obs = observation()
            obs["accounts"][0]["coverage"][0].update(status=status, known_limitation=known)
            self.assertIn("coverage_unknown", self.reasons(self.check(obs)))

    def test_per_zone_coverage_accepts_only_hashed_source(self):
        obs = observation()
        obs["accounts"][0]["coverage"] = [{"source": "subscriptions.zone:" + R,
                                                 "status": "parsed", "known_limitation": False}]
        self.assertIn(AS + ":coverage:subscriptions.zone:" + R, self.check(obs)["verified_scopes"])

    def test_malformed_payload_has_safe_details_and_no_exceptions(self):
        for value in (None, [], "secret-token", 5):
            for field in ("coverage", "inventory", "subscriptions"):
                if field == "subscriptions" and value == []:
                    continue  # An explicitly complete empty subscription list is affirmative.
                obs = observation()
                obs["accounts"][0][field] = value
                result = self.check(obs)
                self.assertTrue(result["issues"])
                self.assertNotIn("secret-token", json.dumps(result))
        obs = observation()
        obs["accounts"][0]["coverage"] = [{"source": "secret-token", "status": "secret-token"}]
        self.assertNotIn("secret-token", json.dumps(self.check(obs)))

    def test_duplicate_account_cannot_authorize_recovery(self):
        obs = observation()
        obs["accounts"].append(copy.deepcopy(obs["accounts"][0]))
        result = self.check(obs)
        self.assertIn("accounts_unknown", self.reasons(result))
        self.assertFalse(any(s.startswith(AS) for s in result["verified_scopes"]))

    def test_malformed_account_group_recovers_only_with_valid_unique_identities(self):
        obs = observation()
        obs["accounts"].append({"account_ref": "private-account"})
        issue = next(i for i in self.check(obs)["issues"] if i["reason"] == "accounts_unknown")
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])
        obs["accounts"].pop()
        self.assertIn(issue["scope"], self.check(obs)["verified_scopes"])

    def test_malformed_coverage_group_recovers_only_with_affirmative_sources(self):
        obs = observation()
        account = obs["accounts"][0]
        account["coverage"] = [{"source": "private-source", "status": "parsed"}]
        issue = next(i for i in self.check(obs)["issues"] if i["reason"] == "coverage_unknown")
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])
        account["coverage"] = [{"source": "billing_info", "status": "unavailable", "known_limitation": True}]
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])
        account["coverage"][0].update(status="complete", known_limitation=False)
        self.assertIn(issue["scope"], self.check(obs)["verified_scopes"])

    def test_unsupported_inventory_group_recovers_only_with_complete_approved_inventory(self):
        obs = observation()
        inventories = obs["accounts"][0]["inventory"]
        inventories["private-product"] = {}
        issue = next(i for i in self.check(obs)["issues"] if i["reason"] == "inventory_unsupported")
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])
        del inventories["private-product"]
        inventories["workers"]["status"] = "unknown"
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])
        inventories["workers"]["status"] = "complete"
        self.assertIn(issue["scope"], self.check(obs)["verified_scopes"])

    def test_non_scalar_coverage_metadata_is_unknown_without_raw_echo(self):
        for status in ({"private-token": "private-value"}, ["private-token"]):
            obs = observation()
            obs["accounts"][0]["coverage"][0]["status"] = status
            result = self.check(obs)
            self.assertIn("coverage_unknown", self.reasons(result))
            self.assertNotIn("private-token", json.dumps(result))
            self.assertNotIn(AS + ":coverage", result["verified_scopes"])

    def test_positive_then_unknown_then_zero_uses_same_scope_for_genuine_recovery(self):
        obs = observation()
        obs["accounts"][0]["subscriptions"] = [row()]
        issue = next(i for i in self.check(obs)["issues"] if i["reason"] == "positive_subscription")
        obs["accounts"][0]["subscriptions_status"] = "unknown"
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])
        obs["accounts"][0].update(subscriptions_status="complete", subscriptions=[row("0")])
        result = self.check(obs)
        self.assertIn(issue["scope"], result["verified_scopes"])
        self.assertNotIn(issue["key"], {i["key"] for i in result["issues"]})

    def test_healthy_replay_stale_never_clears_previous_drift(self):
        obs = observation()
        obs["accounts"][0]["inventory"]["zones"]["refs"] = [R]
        issue = next(i for i in self.check(obs)["issues"] if i["reason"] == "inventory_added")
        obs["accounts"][0]["inventory"]["zones"]["refs"] = []
        obs["observed_at"] = at(-3600)
        self.assertNotIn(issue["scope"], self.check(obs)["verified_scopes"])

    def test_policy_age_override_changes_real_boundary(self):
        obs = observation()
        obs["observed_at"] = at(-120)
        result = self.check(obs, policy={"max_age_seconds": 100})
        self.assertEqual(result["verified_scopes"], [])


if __name__ == "__main__":
    unittest.main()
