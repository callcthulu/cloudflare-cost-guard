import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from cfguard.models import Config
from cfguard.notify import ping_healthchecks
from cfguard.runner import RunDeadline, main


URL = 'https://hc-ping.com/00000000-0000-4000-8000-000000000000'
URL_FILE = Path('/private/healthchecks.url')


class HealthchecksTests(unittest.TestCase):
    def test_ping_retries_transient_failure_without_sending_run_data(self):
        for first_error in (OSError(URL), HTTPError(URL, 503, URL, None, None)):
            with self.subTest(error=type(first_error)), \
                    patch('cfguard.notify._protected_text', return_value=URL), \
                    patch('cfguard.notify.time.sleep'), \
                    patch('cfguard.notify._post', side_effect=[first_error, 200]) as post:
                self.assertEqual(ping_healthchecks(URL_FILE), 'accepted')
                self.assertEqual([call.args for call in post.call_args_list], [(URL, b'')] * 2)

    def test_ping_rejects_unsafe_and_non_success_destinations(self):
        with patch('cfguard.notify._post') as post:
            for invalid in (URL + '/start', URL + '?create=1', URL.replace('hc-ping.com', 'example.com')):
                with self.subTest(invalid=invalid), patch('cfguard.notify._protected_text', return_value=invalid):
                    self.assertEqual(ping_healthchecks(URL_FILE), 'invalid_destination')
            with patch('cfguard.notify._protected_text', side_effect=OSError(URL)):
                self.assertEqual(ping_healthchecks(URL_FILE), 'invalid_destination')
            post.assert_not_called()
        with patch('cfguard.notify._protected_text', return_value=URL), \
                patch('cfguard.notify._post', side_effect=HTTPError(URL, 404, URL, None, None)) as post:
            self.assertEqual(ping_healthchecks(URL_FILE), 'http_404')
            post.assert_called_once()

    def invoke(self, command, reason='collection_complete', code=5, *, deadline=False, configured=True):
        report = {'collection': 'unknown', 'accounts': [{'decisions': [{'reason_code': reason}]}]}
        config = Config(healthchecks_ping_url_file=URL_FILE if configured else None)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('cfguard.runner.load_config', return_value=config), \
                patch('cfguard.runner.run_once', return_value=(code, report),
                      side_effect=RunDeadline if deadline else None) as run, \
                patch('cfguard.runner.ping_healthchecks', return_value='transport_error') as ping, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            def after_report(url_file):
                self.assertEqual(url_file, URL_FILE)
                self.assertEqual(json.loads(stdout.getvalue()), report)
                return 'transport_error'

            ping.side_effect = after_report
            result = main([*command, '--config', '/unused'])
        return result, ping.call_count, run.call_count, stderr.getvalue()

    def test_completed_run_reports_even_with_incident_and_keeps_exit_status(self):
        for code in (0, 3, 4, 5):
            with self.subTest(code=code):
                self.assertEqual(self.invoke(['run', '--scheduled'], code=code),
                                 (code, 1, 1, 'healthchecks heartbeat: transport_error\n'))

    def test_incomplete_runs_and_other_entry_points_do_not_ping(self):
        self.assertEqual(self.invoke(['run', '--scheduled'], reason='collection_failed'),
                         (5, 0, 1, 'healthchecks heartbeat: skipped_collection_failed\n'))
        self.assertEqual(self.invoke(['run', '--scheduled'], deadline=True), (3, 0, 1, ''))
        self.assertEqual(self.invoke(['run', '--scheduled'], configured=False), (5, 0, 1, ''))
        for command in ('run', 'probe', 'enforce-preview'):
            with self.subTest(command=command):
                self.assertEqual(self.invoke([command]), (5, 0, 1, ''))
        self.assertEqual(self.invoke(['probe', '--scheduled']), (2, 0, 0, ''))
