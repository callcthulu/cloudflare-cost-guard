"""Offline approval preparation never arms an action or reads credentials."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from cfguard.models import AccountConfig, Config, GuardBudget, ResourceConfig, ResourceKey
from cfguard.runner import main


class CutoffPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        account = AccountConfig('fixture', 'a' * 32, self.root / 'never-read.token', 1, D('0'), 'USD')
        budget = GuardBudget(D('10'), 'account_rated_observed', accept_partial=True)
        resource = ResourceConfig(ResourceKey(account.account_id, 'resource', 'workers', 'demo'),
                                  'Fixture', permitted_action='delete_worker', budget=budget)
        self.config = Config(accounts=(account,), resources=(resource,), state_dir=self.root / 'never-created-state')

    def invoke(self, output, *extra):
        stream = io.StringIO()
        argv = ['prepare-cutoff', '--config', str(self.root / 'not-opened.json'),
                '--account-id', 'a' * 32, '--resource-id', 'demo', '--output', str(output), *extra]
        with patch('cfguard.runner.load_config', return_value=self.config), \
                patch('cfguard.cloudflare.Client') as client, contextlib.redirect_stdout(stream):
            code = main(argv)
            client.assert_not_called()
        return code, json.loads(stream.getvalue())

    def test_preparation_writes_private_unarmed_template_not_approval_or_state(self):
        output = self.root / 'new.pending.json'
        code, report = self.invoke(output)
        self.assertEqual(code, 0)
        self.assertIs(report['armed'], False)
        self.assertEqual(report['provider_writes'], 0)
        self.assertNotIn('a' * 32, json.dumps(report))
        self.assertFalse(self.config.state_dir.exists())
        content = json.loads(output.read_text())
        self.assertEqual(content['approval_reference'], 'PENDING_OWNER_APPROVAL')
        self.assertFalse(content['acknowledge_deletion'])
        self.assertFalse(content['stateless_worker_confirmed'])
        self.assertFalse(content['restore_source_confirmed'])
        with self.assertRaises(ValueError):
            datetime.fromisoformat(content['expires_at'])
        if __import__('os').name != 'nt':
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_existing_output_is_preserved(self):
        output = self.root / 'existing.json'
        output.write_text('KEEP')
        code, _ = self.invoke(output)
        self.assertNotEqual(code, 0)
        self.assertEqual(output.read_text(), 'KEEP')

    def test_output_inside_source_checkout_is_rejected(self):
        output = Path(__file__).resolve().parents[1] / '.local/should-not-be-created.pending.json'
        code, report = self.invoke(output)
        self.assertEqual(code, 2)
        self.assertEqual(report, {'error': 'invalid_configuration'})
        self.assertFalse(output.exists())

    def test_dangling_output_symlink_is_not_followed(self):
        target = self.root / 'should-not-exist.json'
        output = self.root / 'link.json'
        try:
            output.symlink_to(target)
        except OSError:
            self.skipTest('OS does not permit this user to create symlinks')
        code, _ = self.invoke(output)
        self.assertNotEqual(code, 0)
        self.assertFalse(target.exists())

    def test_unknown_resource_does_not_create_template(self):
        output = self.root / 'unknown.json'
        code, _ = self.invoke(output, '--resource-id', 'not-enrolled')
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())
