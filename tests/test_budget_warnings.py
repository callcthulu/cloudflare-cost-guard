"""Notification-only budget thresholds use validated accounting, never invoice claims."""
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

from cfguard import budget, models
from cfguard.state import resource_label
import test_budget
from test_budget import KEY, NOW


class BudgetWarningTests(unittest.TestCase):
    setUp = test_budget.BudgetTests.setUp
    bucket = test_budget.BudgetTests.bucket
    snapshot = test_budget.BudgetTests.snapshot
    charge = test_budget.BudgetTests.charge
    rated_resource = test_budget.BudgetTests.rated_resource

    def warning(self, **values):
        self.assertTrue(hasattr(models, 'BudgetWarning'), 'budget warning model is missing')
        return models.BudgetWarning(**values)

    def events(self, resource, decision):
        self.assertTrue(hasattr(budget, 'budget_warning_events'), 'warning event evaluator is missing')
        return budget.budget_warning_events(resource, decision)

    def test_no_hard_limit_tracks_unknown_cost_without_cutoff_even_with_action(self):
        resource = replace(self.resource, budget=replace(self.budget, hard_limit_usd=None))
        decision = self.evaluate(self.config, resource, self.snapshot(self.bucket()), self.store, NOW)
        self.assertEqual((decision.value, decision.status, decision.proposed_action), (D('1'), 'unknown', None))

    def test_zero_one_many_warnings_cross_at_equality_and_ignore_quality_acceptance(self):
        warnings = (self.warning(usd=D('.25')), self.warning(percent=D('50')), self.warning(usd=D('.75')))
        resource = replace(self.resource, budget=replace(self.budget, warnings=warnings,
                                                        accept_approximate=False, accept_partial=False))
        decision = self.evaluate(self.config, resource, self.snapshot(self.bucket('500000')), self.store, NOW)
        self.assertIsNone(decision.proposed_action)
        events = self.events(resource, decision)
        self.assertEqual(len(events), 2)
        payload = events[1][1]
        self.assertEqual(payload, {'reason_code': 'budget_warning', 'status': 'warning',
            'resource_ref': resource_label(KEY), 'metric': 'guard_cost_usd', 'value': '0.500',
            'threshold_usd': '0.5', 'hard_limit_usd': '1', 'percent_of_hard_limit': '50.000',
            'warning_percent': '50', 'currency': 'USD', 'source': 'workers_usage_estimate',
            'quality': 'approximate_partial', 'period_start': '2026-10-01T00:00:00+00:00',
            'period_end': '2026-11-01T00:00:00+00:00'})
        self.assertNotIn(KEY.account_id, str(payload))
        self.assertNotIn(KEY.resource_id, str(payload))
        self.assertEqual(self.events(replace(resource, budget=replace(resource.budget, warnings=())), decision), ())

    def test_warning_only_rated_payload_is_partial_and_has_no_percent(self):
        resource = replace(self.rated_resource(), permitted_action=None,
            budget=replace(self.rated_resource().budget, hard_limit_usd=None, accept_partial=False,
                           warnings=(self.warning(usd=D('.5')),)))
        decision = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge(),)), self.store, NOW)
        self.assertEqual(decision.value, D('.5'))
        payload = self.events(resource, decision)[0][1]
        self.assertEqual((payload['quality'], payload['hard_limit_usd'], payload['percent_of_hard_limit'],
                          payload['warning_percent']), ('partial', None, None, None))

    def test_identity_ignores_order_value_decimal_spelling_and_threshold_representation(self):
        resource = replace(self.resource, budget=replace(self.budget, warnings=(self.warning(usd=D('.5')),)))
        decision = self.evaluate(self.config, resource, self.snapshot(self.bucket()), self.store, NOW)
        identity = self.events(resource, decision)[0][0]
        self.assertTrue(identity.startswith('budget-warning:'))
        equivalent = replace(resource, name='Renamed', budget=replace(resource.budget,
            hard_limit_usd=D('2'), warnings=(self.warning(usd=D('.25')), self.warning(percent=D('25.00')))))
        self.assertEqual(identity, self.events(equivalent, replace(decision, value=D('2')))[1][0])
        different_period = replace(decision, period_start=decision.period_end,
                                   period_end=decision.period_end + timedelta(days=30))
        self.assertNotEqual(identity, self.events(resource, different_period)[0][0])
        different_source = replace(resource, budget=replace(resource.budget, source='account_rated_observed',
            request_usd_per_million=D('0'), cpu_usd_per_million_ms=D('0'), cpu_ms_per_request=D('0')))
        rated_decision = replace(decision, reason_code='largest_rated_line_floor_partial_below_budget_unknown')
        self.assertNotEqual(identity, self.events(different_source, rated_decision)[0][0])
        other = replace(resource, key=replace(KEY, resource_id='different'))
        self.assertNotEqual(identity, self.events(other, replace(decision, key=other.key))[0][0])

    def test_warning_configuration_does_not_change_preexisting_cutoff_digest(self):
        previous = 'e156c66445dd26c92349fa9845055b7f1b851ad2301937cda3bd4463de2f515e'
        self.assertEqual(self.digest(self.resource, self.config.accounts[0]), previous)
        resource = replace(self.resource, budget=replace(self.budget,
            warnings=(self.warning(usd=D('.25')), self.warning(percent=D('50')))))
        self.assertEqual(self.digest(resource, self.config.accounts[0]), previous)
        for changes in ({'hard_limit_usd': D('2')}, {'cpu_ms_per_request': D('36')},
                        {'pricing_source': 'new provenance'}, {'pricing_as_of': '2026-10-28'},
                        {'source': 'account_rated_observed'}):
            self.assertNotEqual(self.digest(replace(resource, budget=replace(resource.budget, **changes)),
                                            self.config.accounts[0]), previous)

    def test_missing_invalid_and_persisted_conflicting_evidence_never_warn(self):
        warning = self.warning(usd=D('.25'))
        resource = replace(self.resource, budget=replace(self.budget, warnings=(warning,)))
        for snapshot in (self.snapshot(), self.snapshot(self.bucket(complete=False)),
                         self.snapshot(self.bucket(), self.bucket(value=D('NaN'), minute=2)),
                         self.snapshot(self.bucket(), account_id='c' * 32)):
            decision = self.evaluate(self.config, resource, snapshot, self.store, NOW, persist=False)
            self.assertEqual(self.events(resource, decision), ())
            context = budget.budget_context(resource, decision)
            self.assertEqual((context['value'], context['quality']), (None, 'unknown'))
        resource = replace(self.rated_resource(), budget=replace(self.rated_resource().budget, warnings=(warning,)))
        self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('1'),)), self.store, NOW)
        decision = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('2'),)), self.store, NOW)
        self.assertEqual(self.events(resource, decision), ())
        context = budget.budget_context(resource, decision)
        self.assertEqual((context['value'], context['quality']), (None, 'unknown'))
        decision = self.evaluate(self.config, resource, self.snapshot(charges=(self.charge('1'),)), self.store, NOW)
        self.assertEqual(self.events(resource, decision), ())

    def test_warning_requires_matching_valid_guard_decision(self):
        resource = replace(self.resource, budget=replace(self.budget, warnings=(self.warning(usd=D('.25')),)))
        decision = self.evaluate(self.config, resource, self.snapshot(self.bucket()), self.store, NOW)
        for changes in ({'key': replace(KEY, resource_id='other')}, {'metric': 'requests'}, {'currency': 'EUR'},
                        {'unit': 'requests'}, {'period_start': None}, {'period_end': None},
                        {'period_start': decision.period_end}, {'value': None}, {'value': D('-1')},
                        {'value': D('Infinity')}, {'value': D('NaN')},
                        {'reason_code': 'estimated_requests_cpu_reserve_partial_conflicting_or_invalid'},
                        {'reason_code': 'guard_budget_invalid'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.events(resource, replace(decision, **changes)), ())

    def test_extreme_hard_limits_do_not_abort_context_or_warning_events(self):
        for hard_limit, threshold, percent in (
                ('1e-1000000', '5e-1000001', '1.00e1000002'),
                ('1e1000000', '.5', '1.00e-999998'),
                ('1e-999999999999999999', '5e-1000000000000000000', None)):
            resource = replace(self.resource, budget=replace(self.budget, hard_limit_usd=D(hard_limit),
                               warnings=(self.warning(usd=D(threshold)),)))
            decision = self.evaluate(self.config, resource, self.snapshot(self.bucket()), self.store, NOW,
                                     persist=False)
            context = budget.budget_context(resource, decision)
            self.assertEqual(D(context['value']), D('1'))
            self.assertEqual(context['hard_limit_usd'], str(D(hard_limit)))
            if percent is None:
                self.assertIsNone(context['percent_of_hard_limit'])
            else:
                self.assertEqual(D(context['percent_of_hard_limit']), D(percent))
            event = self.events(resource, decision)[0][1]
            self.assertEqual(event['percent_of_hard_limit'], context['percent_of_hard_limit'])
            self.assertEqual(event['hard_limit_usd'], str(D(hard_limit)))
            self.assertEqual(D(event['value']), D('1'))


if __name__ == '__main__': unittest.main()
