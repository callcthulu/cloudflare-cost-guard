"""An explicit notification test never runs Cloudflare collection or real incidents."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cfguard.models import Config
from cfguard.runner import main


class NotificationCliTests(unittest.TestCase):
    def invoke(self,configuration,*flags):
        config=Config(notification=configuration)
        output=io.StringIO()
        with patch('cfguard.runner.load_config',return_value=config), \
                patch('cfguard.runner.Store') as store, patch('cfguard.cloudflare.Client') as provider, \
                patch('cfguard.notify._http_post',side_effect=AssertionError('unexpected real HTTP request')), \
                patch('cfguard.notify._smtp_factory',side_effect=AssertionError('unexpected real SMTP connection')), \
                contextlib.redirect_stdout(output):
            try:
                code=main(['test-notification','--config','/synthetic/config.json',*flags])
            except SystemExit as error:
                self.fail('explicit notification test command unavailable: '+str(error))
            store.assert_not_called()
            provider.assert_not_called()
        return code,json.loads(output.getvalue())

    def test_default_preview_does_not_open_secrets_or_make_network_requests(self):
        config={'targets':[{'id':'ops','type':'slack','url_file':Path('/missing/never-open.url')}]}
        with patch('cfguard.notify._protected_text',side_effect=AssertionError('preview read a secret')), \
                patch('cfguard.notify._http_post',side_effect=AssertionError('preview sent a request')):
            code,report=self.invoke(config,'--target','ops')
        self.assertEqual(code,0)
        self.assertIs(report['preview'],True)
        self.assertNotIn('never-open',json.dumps(report))

    def test_send_uses_only_selected_target_and_reports_acceptance_not_human_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'url'
            path.write_text('https://hooks.slack.com/services/SYNTHETIC/ONLY/FIXTURE')
            path.chmod(0o600)
            config={'targets':[{'id':'ops','type':'slack','url_file':path},
                               {'id':'other','type':'email','settings_file':Path('/missing/not-read.json')}]}
            with patch('cfguard.notify.send_target',return_value=True) as send:
                code,report=self.invoke(config,'--target','ops','--send')
            self.assertEqual(code,0)
            self.assertIs(report['accepted'],True)
            self.assertIs(report['human_receipt_verified'],False)
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0]['id'],'ops')
            self.assertNotIn(str(path),json.dumps(report))

    def test_failed_send_is_exit_five_and_missing_or_unknown_target_is_config_error(self):
        config={'targets':[{'id':'ops','type':'slack','url_file':Path('/missing/not-read.url')}]}
        with patch('cfguard.notify.send_target',return_value=False):
            code,report=self.invoke(config,'--target','ops','--send')
        self.assertEqual(code,5)
        self.assertIs(report['accepted'],False)
        for flags in ((),('--target','unknown')):
            with self.subTest(flags=flags):
                code,report=self.invoke(config,*flags)
                self.assertEqual(code,2)
