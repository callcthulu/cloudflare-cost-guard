import copy
import unittest
from decimal import Decimal as D

from cfguard.config import ConfigError
import test_config


def fixture():
    raw = test_config.example()
    raw['mode'] = 'enforce'
    raw['resources'][0].update(permitted_action='delete_worker', executor_token_file='/etc/cfguard/write.token',
                               approved_manifest_file='/etc/cfguard/approval.json', approved_manifest_digest='c'*64,
                               budget={'hard_limit_usd': '1', 'source': 'workers_usage_estimate',
                                       'request_usd_per_million': '0.3', 'cpu_usd_per_million_ms': '0.02',
                                       'cpu_ms_per_request': '35', 'pricing_source': 'synthetic fixture',
                                       'pricing_as_of': '2026-10-27', 'accept_approximate': True, 'accept_partial': True})
    return raw


class BudgetConfigTests(unittest.TestCase):
    load = test_config.ConfigTests.load

    def test_enrolled_estimate_and_rated_budget_parse(self):
        config = self.load(fixture())
        self.assertEqual(str(config.resources[0].budget.hard_limit_usd), '1')
        raw = fixture()
        raw['resources'][0]['budget'] = {'hard_limit_usd': '2', 'source': 'account_rated_observed', 'accept_partial': True}
        self.assertEqual(self.load(raw).resources[0].budget.source, 'account_rated_observed')

    def test_reject_unsafe_source_rate_identity_quality_and_unarmed_action(self):
        base = fixture()
        variants = []
        for field, value in (('hard_limit_usd', '0'), ('hard_limit_usd', 'NaN'), ('hard_limit_usd', 1),
                             ('source', 'invoice_total'), ('cpu_ms_per_request', '0'), ('pricing_source', ''),
                             ('pricing_as_of', 'yesterday'), ('accept_approximate', False), ('accept_partial', False),
                             ('accept_partial', 'yes'), ('currency', 'EUR')):
            raw = copy.deepcopy(base); raw['resources'][0]['budget'][field] = value; variants.append(raw)
        for field in ('executor_token_file', 'approved_manifest_file', 'approved_manifest_digest', 'budget', 'permitted_action'):
            raw = copy.deepcopy(base); del raw['resources'][0][field]; variants.append(raw)
        raw = copy.deepcopy(base); raw['resources'][0]['executor_token_file'] = raw['accounts'][0]['read_token_file']; variants.append(raw)
        raw = copy.deepcopy(base); raw['resources'][0]['product'] = 'r2'; variants.append(raw)
        raw = copy.deepcopy(base); raw['accounts'][0]['currency'] = 'EUR'; variants.append(raw)
        raw = copy.deepcopy(base); raw['resources'][0]['budget']['source'] = 'account_rated_observed'; variants.append(raw)
        for raw in variants:
            with self.subTest(raw=raw), self.assertRaises(ConfigError): self.load(raw)

    def test_observe_can_report_budget_without_quality_acceptance_or_action(self):
        raw = fixture(); raw['mode'] = 'observe'
        resource = raw['resources'][0]
        for field in ('permitted_action', 'executor_token_file', 'approved_manifest_file', 'approved_manifest_digest'):
            del resource[field]
        resource['budget']['accept_partial'] = False
        resource['budget']['accept_approximate'] = False
        self.assertIsNone(self.load(raw).resources[0].permitted_action)

    def warning_only(self, hard_limit=None):
        raw = fixture()
        resource = raw['resources'][0]
        for field in ('permitted_action', 'executor_token_file', 'approved_manifest_file', 'approved_manifest_digest'):
            del resource[field]
        resource['budget'] = {'source': 'account_rated_observed', 'hard_limit_usd': hard_limit}
        return raw

    def test_warning_only_tracking_and_mixed_enforcement_require_no_writer_or_quality_acceptance(self):
        for omitted in (False, True):
            raw = self.warning_only()
            if omitted:
                del raw['resources'][0]['budget']['hard_limit_usd']
            resource = self.load(raw).resources[0]
            self.assertIsNone(resource.budget.hard_limit_usd)
            self.assertEqual(resource.budget.warnings, ())
            raw['resources'][0]['budget']['warnings'] = [{'usd': '1'}, {'usd': '2'}]
            raw['resources'].append(fixture()['resources'][0])
            raw['resources'][1]['resource_id'] = 'armed'
            config = self.load(raw)
            self.assertEqual(tuple(w.usd for w in config.resources[0].budget.warnings), (D('1'), D('2')))
            self.assertEqual(config.resources[1].permitted_action, 'delete_worker')
        raw = self.warning_only()
        raw['resources'][0]['budget'] = fixture()['resources'][0]['budget']
        del raw['resources'][0]['budget']['hard_limit_usd']
        raw['resources'][0]['budget'].update(accept_partial=False, accept_approximate=False)
        self.assertIsNone(self.load(raw).resources[0].budget.hard_limit_usd)

    def test_budget_warning_usd_percent_and_many_thresholds_parse(self):
        raw = fixture()
        raw['resources'][0]['budget']['warnings'] = [{'usd': '0.1'}, {'percent': '50'}]
        warnings = self.load(raw).resources[0].budget.warnings
        self.assertEqual([(w.usd, w.percent) for w in warnings], [(D('0.1'), None), (None, D('50'))])
        raw = self.warning_only()
        raw['resources'][0]['budget']['warnings'] = [{'usd': str(i)} for i in range(1, 151)]
        self.assertEqual(len(self.load(raw).resources[0].budget.warnings), 150)

    def test_reject_invalid_duplicate_or_nonadvance_budget_warnings(self):
        variants = [None, {}, '1', [None], [{}], [{'usd': '0.1', 'percent': '10'}],
                    [{'usd': '0.1', 'extra': 'no'}], [{'usd': '0.1'}, {'usd': '0.10'}],
                    [{'usd': '0.5'}, {'percent': '50'}], [{'percent': '100'}], [{'percent': '101'}],
                    [{'usd': '1'}], [{'usd': '2'}]]
        for field in ('usd', 'percent'):
            variants += [[{field: value}] for value in (0, 1, True, False, None, '0', '-1', 'NaN', 'Infinity', '-Infinity')]
        for warnings in variants:
            raw = fixture(); raw['resources'][0]['budget']['warnings'] = warnings
            with self.subTest(warnings=warnings), self.assertRaises(ConfigError):
                self.load(raw)
        raw = self.warning_only(); raw['resources'][0]['budget']['warnings'] = [{'percent': '50'}]
        with self.assertRaises(ConfigError): self.load(raw)

    def test_warn_only_rejects_action_writer_and_approval_fields_even_when_null(self):
        for field, value in (('permitted_action', 'delete_worker'), ('permitted_action', 'disable_worker_endpoints'),
                             ('executor_token_file', '/etc/write.token'), ('approved_manifest_file', '/etc/approval.json'),
                             ('approved_manifest_digest', 'c' * 64)):
            for entry in (value, None):
                raw = self.warning_only(); raw['resources'][0][field] = entry
                with self.subTest(field=field, entry=entry), self.assertRaises(ConfigError):
                    self.load(raw)

    def test_hard_limit_removal_never_downgrades_armed_resource(self):
        for omitted in (False, True):
            raw = fixture()
            if omitted: del raw['resources'][0]['budget']['hard_limit_usd']
            else: raw['resources'][0]['budget']['hard_limit_usd'] = None
            with self.assertRaises(ConfigError): self.load(raw)

    def test_percent_threshold_is_exact_for_long_decimals_and_large_exponents(self):
        for hard_limit, usd in (
                ('1.123456789012345678901234567890123456789', '.5617283945061728394506172839450617283945'),
                ('1e1000000', '5e999999'), ('1e-1000000', '5e-1000001')):
            raw = fixture()
            raw['resources'][0]['budget'].update(hard_limit_usd=hard_limit, warnings=[{'percent': '50'}])
            parsed = self.load(raw).resources[0].budget
            self.assertEqual(parsed.warnings[0].threshold_usd(parsed.hard_limit_usd), D(usd))
            raw['resources'][0]['budget']['warnings'].append({'usd': usd})
            with self.assertRaises(ConfigError): self.load(raw)

    def test_unrepresentable_positive_percentage_never_becomes_zero_warning(self):
        for percent in ('1e-1000', '1e-999999999999999999'):
            raw = fixture(); raw['mode'] = 'observe'
            raw['resources'][0]['budget'] = {'source': 'account_rated_observed',
                'hard_limit_usd': '1e-999999999999999999', 'warnings': [{'percent': percent}]}
            with self.subTest(percent=percent):
                with self.assertRaises(ConfigError) as error:
                    self.load(raw)
                self.assertNotIn(percent, str(error.exception))
                self.assertNotIn('1e-999999999999999999', str(error.exception))


if __name__ == '__main__': unittest.main()
