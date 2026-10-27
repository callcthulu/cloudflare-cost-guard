import copy
import unittest

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


if __name__ == '__main__': unittest.main()
