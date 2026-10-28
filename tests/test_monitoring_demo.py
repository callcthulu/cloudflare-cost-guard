"""The sharing demo must exercise real persistence without external I/O."""
import contextlib
import importlib
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from cfguard.monitoring import runtime


class MonitoringDemoTests(unittest.TestCase):
    def test_demo_retains_fee_when_evidence_is_missing_and_cleans_up(self):
        try:
            demo = importlib.import_module('examples.monitoring_demo')
        except ModuleNotFoundError:
            self.fail('examples.monitoring_demo must implement the offline sharing demo')

        outputs = []
        for _ in range(2):
            reports, active_reasons, events, directories = [], [], [], []
            real_watch = runtime.watch

            def watch(config, **kwargs):
                self.assertTrue(callable(kwargs.get('loader')))
                sender = kwargs.get('sender')
                self.assertTrue(callable(sender))

                def capture(settings, event):
                    events.append(event)
                    return sender(settings, event)

                kwargs['sender'] = capture
                report = real_watch(config, **kwargs)
                reports.append(report)
                directory = Path(config['state_dir'])
                directories.append(directory.parent)
                with contextlib.closing(sqlite3.connect(directory / 'watch.sqlite3')) as db:
                    rows = db.execute('SELECT payload FROM incidents WHERE active=1').fetchall()
                active_reasons.append(sorted(json.loads(row[0])['reason'] for row in rows))
                return report

            output = io.StringIO()
            with contextlib.ExitStack() as stack:
                for target in ('socket.socket', 'socket.create_connection', 'subprocess.Popen',
                               'smtplib.SMTP', 'smtplib.SMTP_SSL'):
                    stack.enter_context(patch(target, side_effect=AssertionError('external I/O forbidden')))
                stack.enter_context(patch.object(runtime, 'watch', side_effect=watch))
                stack.enter_context(contextlib.redirect_stdout(output))
                self.assertEqual(demo.main(), 0)

            self.assertEqual([r['queued'] for r in reports], [0, 1, 0, 1, 1, 1, 0])
            self.assertEqual([r['active_incidents'] for r in reports], [0, 1, 1, 2, 1, 0, 0])
            self.assertEqual(active_reasons[3], ['observation_unknown', 'positive_subscription'])
            self.assertEqual([(e['kind'], e['issue']['reason']) for e in events], [
                ('opened', 'positive_subscription'), ('opened', 'observation_unknown'),
                ('recovered', 'observation_unknown'), ('recovered', 'positive_subscription')])
            self.assertEqual(events[0]['issue']['details'], {'amount': '5.50', 'currency': 'USD'})
            for index in (0, 1, 2, 4, 5, 6):
                self.assertEqual(reports[index]['limitations'][0]['status'], 'unavailable')
                self.assertNotIn('account:' + 'a' * 16 + ':coverage:billing_account_coverage',
                                 reports[index]['verified_scopes'])
            self.assertTrue(all(r['pending'] == r['failed'] == 0 for r in reports))
            self.assertTrue(directories)
            self.assertTrue(all(not directory.exists() for directory in directories))
            outputs.append(output.getvalue())

        self.assertEqual(outputs[0], outputs[1])
        self.assertIn('SYNTHETIC', outputs[0])
        self.assertIn('FAKE', outputs[0])
        self.assertIn('not a financial cap', outputs[0])


if __name__ == '__main__':
    unittest.main()
