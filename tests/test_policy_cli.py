"""Human-readable policy inspection is offline and sanitized."""
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from cfguard.models import AccountConfig, Config, GuardBudget, ResourceConfig, ResourceKey
from cfguard.runner import main


class PolicyInspectionTests(unittest.TestCase):
    def test_show_policy_reports_settings_without_state_or_provider_access(self):
        from cfguard import models
        self.assertTrue(hasattr(models, 'BudgetWarning'), 'budget warning configuration missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account = AccountConfig('fixture', 'a'*32, root/'never-read.token', 1, D('0'), 'USD')
            budget = GuardBudget(D('10'), 'account_rated_observed',
                                 warnings=(models.BudgetWarning(usd=D('5')), models.BudgetWarning(percent=D('80'))))
            resource = ResourceConfig(ResourceKey(account.account_id, 'resource', 'workers', 'private-script-name'),
                                      'Private display name', permitted_action='delete_worker', budget=budget)
            config = Config(accounts=(account,), resources=(resource,), state_dir=root/'never-created')
            output = io.StringIO()
            with patch('cfguard.runner.load_config', return_value=config), \
                    patch('cfguard.cloudflare.Client') as client, patch('cfguard.runner.Store') as store, \
                    contextlib.redirect_stdout(output):
                try:
                    code = main(['show-policy', '--config', str(root/'config.json')])
                except SystemExit as error:
                    self.fail('show-policy command unavailable: ' + str(error))
            self.assertEqual(code, 0)
            client.assert_not_called()
            store.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertIn('\n', output.getvalue().rstrip(), 'inspection output should be formatted for humans')
            self.assertEqual(report['mode'], 'observe')
            policy = report['policies'][0]
            self.assertEqual(D(policy['hard_limit_usd']), D('10'))
            self.assertFalse(policy['cutoff_enabled'])
            self.assertEqual([D(w['threshold_usd']) for w in policy['warnings']], [D('5'), D('8')])
            self.assertNotIn(account.account_id, output.getvalue())
            self.assertNotIn('private-script-name', output.getvalue())
            self.assertNotIn('Private display name', output.getvalue())
            self.assertFalse(config.state_dir.exists())

    def test_prepare_cutoff_cannot_create_approval_for_warning_only_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account = AccountConfig('fixture', 'a'*32, root/'never-read', 1, D('0'), 'USD')
            resource = ResourceConfig(ResourceKey(account.account_id, 'resource', 'workers', 'sample'),
                                      'Sample', permitted_action='delete_worker',
                                      budget=GuardBudget(None, 'account_rated_observed'))
            config = Config(accounts=(account,), resources=(resource,), state_dir=root/'never-created')
            output = root/'approval.json'
            with patch('cfguard.runner.load_config', return_value=config), contextlib.redirect_stdout(io.StringIO()):
                code = main(['prepare-cutoff','--config',str(root/'config.json'),'--account-id','a'*32,
                             '--resource-id','sample','--output',str(output)])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())
