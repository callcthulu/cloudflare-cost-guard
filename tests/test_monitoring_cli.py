"""Exercise public commands as a user would, with no provider or notification access."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_path = self.root / 'watch.json'
        self.config = {'version': 1, 'observation_file': str(self.root / 'observation.json'),
                       'state_dir': str(self.root / 'state'),
                       'smtp_file': str(self.root / 'not-created-smtp.json'),
                       'expected_account_refs': ['a' * 16]}

    def run_cli(self, *args):
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
        self.config_path.chmod(0o600)
        result = subprocess.run([sys.executable, '-B', '-m', 'cfguard.monitoring', *args,
                                 '--config', str(self.config_path)], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.stderr, '')
        return result.returncode, json.loads(result.stdout)

    def test_validate_does_not_read_credentials_or_initialize_state(self):
        code, report = self.run_cli('validate')
        self.assertEqual((code, report), (0, {'valid': True}))
        self.assertFalse((self.root / 'state').exists())

    def test_default_watch_reports_unavailable_observation_without_sending(self):
        code, report = self.run_cli('watch')
        self.assertEqual(code, 4)
        self.assertTrue(report['preview'])
        self.assertEqual(report['delivered'], 0)
        self.assertEqual(report['issues'][0]['reason'], 'observation_unknown')
        self.assertFalse((self.root / 'state').exists())

    def test_send_without_apply_is_a_sanitized_configuration_error(self):
        code, report = self.run_cli('watch', '--send')
        self.assertEqual(code, 2)
        self.assertEqual(report, {'error': 'invalid_configuration_or_evidence'})

    def test_invalid_account_baseline_fails_without_echoing_configuration(self):
        self.config['expected_account_refs'] = ['PRIVATE-MALFORMED-IDENTITY']
        code, report = self.run_cli('watch')
        self.assertEqual(code, 2)
        self.assertNotIn('PRIVATE', json.dumps(report))


if __name__ == '__main__': unittest.main()
