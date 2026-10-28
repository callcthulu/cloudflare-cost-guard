import copy
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

try:
    from cfguard.monitoring import runtime
except ImportError:
    runtime = None

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def observation(pending=0):
    return {"version": 1, "observed_at": NOW.isoformat(),
            "guard": {"status": "ok", "last_attempt": NOW.isoformat(),
                      "last_finished": NOW.isoformat(), "last_collection_success": None,
                      "pending_notifications": pending,
                      "oldest_pending_at": NOW.isoformat() if pending else None},
            "accounts": []}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime, 'runtime must implement the approved watcher')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.smtp = self.root / 'smtp.json'
        self.settings = {"host": "smtp.example.invalid", "port": 465, "tls": "ssl",
                         "username": "fixture", "password": "SYNTHETIC-ONLY",
                         "from": "guard@example.invalid", "to": "owner@example.invalid"}
        self.write(self.smtp, self.settings)
        self.config = {"version": 1, "state_dir": str(self.root / 'state'),
                       "observation_file": str(self.root / 'observation.json'),
                       "smtp_file": str(self.smtp), "reminder_seconds": 86400, "policy": {}}

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
        path.chmod(0o600)

    def run_watch(self, obs, **kwargs):
        return runtime.watch(self.config, now=kwargs.pop('now', NOW),
                             loader=lambda _: obs, **kwargs)

    def test_configuration_rejects_unknown_keys_and_mutating_or_ambiguous_sources(self):
        for change in ({'command': 'arbitrary'}, {'ssh_profile': '-oProxyCommand=bad'},
                       {'version': True}, {'reminder_seconds': 0},
                       {'policy': {'max_age_seconds': -1}}):
            raw = self.config | change
            p = self.root / 'config.json'; self.write(p, raw)
            with self.subTest(change=change), self.assertRaises(ValueError):
                runtime.load_config(p)

    def test_preview_reads_no_smtp_and_creates_no_state(self):
        self.smtp.unlink()
        report = self.run_watch(None)
        self.assertTrue(report['preview'])
        self.assertTrue(report['issues'])
        self.assertFalse((self.root / 'state').exists())

    def test_send_requires_apply(self):
        with self.assertRaises(ValueError): self.run_watch(None, send=True)
        self.assertFalse((self.root / 'state').exists())

    def test_persist_deduplicates_and_reminds_after_interval(self):
        first = self.run_watch(None, apply=True, send=True, sender=lambda settings, event: None)
        second = self.run_watch(None, apply=True, now=NOW + timedelta(hours=1))
        third = self.run_watch(None, apply=True, now=NOW + timedelta(days=1))
        self.assertEqual(first['queued'], 1)
        self.assertEqual(second['queued'], 0)
        self.assertEqual(third['queued'], 1)
        self.assertEqual(third['pending'], 1)

    def test_failed_delivery_does_not_accumulate_duplicate_reminders(self):
        self.run_watch(None, apply=True)
        later = self.run_watch(None, apply=True, now=NOW + timedelta(days=2))
        self.assertEqual(later['queued'], 0)
        self.assertEqual(later['pending'], 1)

    def test_recovery_cancels_unsent_obsolete_alert(self):
        self.run_watch(None, apply=True)
        sent = []
        result = self.run_watch(observation(), apply=True, send=True,
                                sender=lambda settings, event: sent.append(event))
        self.assertEqual(result['cancelled'], 1)
        self.assertEqual([e['kind'] for e in sent], ['recovered'])

    def test_missing_expected_account_is_visible_and_can_recover(self):
        self.config['expected_account_refs'] = ['a' * 16]
        report = self.run_watch(observation())
        self.assertTrue(any(i['reason'] == 'account_set_changed' for i in report['issues']))

    def test_deeply_nested_observation_is_unknown_without_traceback(self):
        p = Path(self.config['observation_file'])
        p.write_text('[' * 2000 + '0' + ']' * 2000, encoding='utf-8'); p.chmod(0o600)
        self.assertIsNone(runtime.read_observation(self.config))

    def test_unused_nested_payload_does_not_crash_persistent_watcher(self):
        value = observation()
        nested = []
        for _ in range(2000): nested = [nested]
        value['unused'] = nested
        result = self.run_watch(value, apply=True)
        self.assertEqual(result['active_incidents'], 0)

    def test_uncertain_observation_does_not_recover_prior_guard_incident(self):
        old = observation(); old['guard']['last_finished'] = (NOW - timedelta(hours=1)).isoformat()
        self.run_watch(old, apply=True)
        sent = []
        self.run_watch(None, apply=True, send=True, sender=lambda settings, event: sent.append(event))
        self.assertFalse(any(e['kind'] == 'recovered' for e in sent))

    def test_affirmative_recovery_is_sent_once(self):
        self.run_watch(None, apply=True)
        events = []
        report = self.run_watch(observation(), apply=True, send=True,
                                sender=lambda settings, event: events.append(event))
        self.assertEqual(sum(e['kind'] == 'recovered' for e in events), 1)
        self.assertEqual(report['pending'], 0)
        report = self.run_watch(observation(), apply=True)
        self.assertEqual(report['queued'], 0)

    def test_recurrence_cancels_queued_or_backed_off_recovery_before_delivery(self):
        for failed_recovery in (False, True):
            with self.subTest(failed_recovery=failed_recovery):
                self.config['state_dir'] = str(self.root / str(failed_recovery))
                sent = []
                sender = lambda settings, event: sent.append(event)
                self.run_watch(None, apply=True, send=True, sender=sender)
                def fail(settings, event): raise OSError('synthetic failure')
                self.run_watch(observation(), apply=True, send=failed_recovery, sender=fail)
                recurrence = self.run_watch(None, apply=True, send=True, sender=sender,
                                            now=NOW + timedelta(seconds=30))
                self.assertEqual(recurrence['cancelled'], 1)
                self.assertEqual([e['kind'] for e in sent], ['opened', 'opened'])
                self.run_watch(None, apply=True, send=True, sender=sender,
                               now=NOW + timedelta(seconds=61))
                self.assertFalse(any(e['kind'] == 'recovered' for e in sent))
                self.assertEqual(recurrence['pending'], 0)

    def test_available_coverage_loss_alerts_across_restart_and_unknown_cannot_recover(self):
        from test_monitoring_policy import observation as account_observation
        obs = account_observation()
        coverage = obs['accounts'][0]['coverage'][0]
        coverage.update(status='unavailable', known_limitation=True)
        initial = self.run_watch(obs, apply=True)
        self.assertEqual(initial['queued'], 0)
        self.assertEqual(len(initial['limitations']), 1)
        coverage.update(status='covered', known_limitation=False)
        self.run_watch(obs, apply=True)
        coverage.update(status='unavailable', known_limitation=True)
        sent = []
        sender = lambda settings, event: sent.append(event)
        lost = self.run_watch(obs, apply=True, send=True, sender=sender)
        self.assertEqual([i['reason'] for i in lost['issues']], ['coverage_lost'])
        self.assertEqual([e['kind'] for e in sent], ['opened'])
        self.run_watch(None, apply=True)
        coverage.update(status='unknown', known_limitation=False)
        self.run_watch(obs, apply=True)
        with contextlib.closing(sqlite3.connect(self.root / 'state' / 'watch.sqlite3')) as db:
            active = db.execute("SELECT active FROM incidents WHERE key LIKE 'coverage_lost:%'").fetchone()
        self.assertEqual(active, (1,))
        self.assertFalse(any(e['kind'] == 'recovered' for e in sent))
        coverage.update(status='covered', known_limitation=False)
        self.run_watch(obs, apply=True, send=True, sender=sender)
        self.assertEqual([e['kind'] for e in sent if e['issue']['reason'] == 'coverage_lost'],
                         ['opened', 'recovered'])

    def test_stale_snapshot_does_not_establish_available_coverage_history(self):
        from test_monitoring_policy import observation as account_observation
        obs = account_observation()
        obs['accounts'][0]['snapshot_at'] = (NOW - timedelta(hours=1)).isoformat()
        self.run_watch(obs, apply=True)
        obs['accounts'][0]['snapshot_at'] = NOW.isoformat()
        obs['accounts'][0]['coverage'][0].update(status='unavailable', known_limitation=True)
        report = self.run_watch(obs, apply=True)
        self.assertFalse(any(i['reason'] == 'coverage_lost' for i in report['issues']))

    def test_stale_account_cannot_establish_history_for_a_disappearing_source(self):
        from test_monitoring_policy import observation as account_observation
        obs = account_observation()
        obs['accounts'][0]['coverage'].append({'source': 'rated_rows', 'status': 'parsed',
                                              'known_limitation': False})
        obs['accounts'][0]['snapshot_at'] = (NOW - timedelta(hours=1)).isoformat()
        self.run_watch(obs, apply=True)
        obs['accounts'][0]['snapshot_at'] = NOW.isoformat()
        obs['accounts'][0]['coverage'].pop()
        report = self.run_watch(obs, apply=True)
        self.assertFalse(any(i['reason'] == 'coverage_lost' for i in report['issues']))
        with contextlib.closing(sqlite3.connect(self.root / 'state' / 'watch.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coverage_history WHERE scope LIKE '%:rated_rows'").fetchone(), (0,))

    def test_missing_historical_source_cannot_verify_the_coverage_group(self):
        from test_monitoring_policy import observation as account_observation
        obs = account_observation()
        coverage = obs['accounts'][0]['coverage']
        coverage.append({'source': 'rated_rows', 'status': 'parsed', 'known_limitation': False})
        self.assertEqual(self.run_watch(obs, apply=True)['queued'], 0)
        coverage.pop()
        report = self.run_watch(obs, apply=True)
        self.assertEqual([i['reason'] for i in report['issues']], ['coverage_lost'])
        self.assertNotIn('account:' + 'a' * 16 + ':coverage', report['verified_scopes'])
        self.assertEqual(report['queued'], 1)
        self.assertEqual(self.run_watch(obs, apply=True)['queued'], 0)

    def test_equivalent_decimal_spellings_do_not_trigger_updated_amount(self):
        from test_monitoring_policy import observation as account_observation, row
        obs = account_observation()
        obs['accounts'][0]['subscriptions'] = [row('10.0')]
        sent = []
        sender = lambda settings, event: sent.append(event)
        self.run_watch(obs, apply=True, send=True, sender=sender)
        obs['accounts'][0]['subscriptions'][0]['amount'] = '10.00'
        report = self.run_watch(obs, apply=True, send=True, sender=sender)
        self.assertEqual(report['queued'], 0)
        self.assertEqual([e['kind'] for e in sent], ['opened'])

    def test_delivery_failure_retries_with_backoff_without_duplicate_incident(self):
        calls = []
        def fail(settings, event):
            calls.append(event); raise OSError('PRIVATE-MUST-NOT-LEAK')
        first = self.run_watch(None, apply=True, send=True, sender=fail)
        self.assertEqual((first['failed'], first['pending']), (1, 1))
        self.assertNotIn('PRIVATE', json.dumps(first))
        self.run_watch(None, apply=True, send=True, now=NOW+timedelta(seconds=30), sender=fail)
        self.assertEqual(len(calls), 1)
        last = self.run_watch(None, apply=True, send=True, now=NOW+timedelta(seconds=61),
                              sender=lambda settings, event: calls.append(event))
        self.assertEqual(last['queued'], 0)
        self.assertEqual(last['pending'], 0)

    def test_destination_change_cancels_historical_backlog(self):
        self.run_watch(None, apply=True)
        self.settings['to'] = 'new-owner@example.invalid'; self.write(self.smtp, self.settings)
        sent = []
        result = self.run_watch(None, apply=True, send=True,
                                sender=lambda settings, event: sent.append(event))
        self.assertEqual(result['cancelled'], 1)
        self.assertEqual(sent, [])

    def test_password_rotation_preserves_bound_destination(self):
        self.run_watch(None, apply=True)
        self.settings['password'] = 'SYNTHETIC-ROTATED'; self.write(self.smtp, self.settings)
        sent = []
        result = self.run_watch(None, apply=True, send=True,
                                sender=lambda settings, event: sent.append(event))
        self.assertEqual(result['cancelled'], 0)
        self.assertEqual(len(sent), 1)

    def test_pending_age_survives_moving_retry_timestamp(self):
        self.run_watch(observation(1), apply=True)
        later = NOW + timedelta(minutes=20)
        fresh = observation(1)
        fresh['observed_at'] = later.isoformat()
        fresh['guard'].update(last_finished=later.isoformat(), last_attempt=later.isoformat(),
                              oldest_pending_at=later.isoformat())
        result = self.run_watch(fresh, apply=True, now=later)
        self.assertTrue(any('backlog' in i['reason'] for i in result['issues']))

    def test_overlapping_watchers_are_rejected(self):
        with runtime.Lock(self.root / 'state'):
            with self.assertRaises(runtime.Busy): self.run_watch(None, apply=True)

    def test_export_is_atomic_and_private_and_failure_preserves_previous_snapshot(self):
        dest = self.root / 'export' / 'observation.json'
        runtime.sample({}, dest, now=NOW, collector=lambda c, n: observation())
        original = dest.read_bytes()
        with self.assertRaises(RuntimeError):
            runtime.sample({}, dest, now=NOW, collector=lambda c, n: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(dest.read_bytes(), original)
        if os.name == 'posix': self.assertEqual(dest.stat().st_mode & 0o777, 0o600)

    def test_local_observation_size_and_malformed_data_are_unknown(self):
        p = Path(self.config['observation_file'])
        p.write_bytes(b'x' * (runtime.LIMIT + 1)); p.chmod(0o600)
        self.assertIsNone(runtime.read_observation(self.config))
        p.write_text('{bad json', encoding='utf-8')
        self.assertIsNone(runtime.read_observation(self.config))

    def test_ssh_uses_only_fixed_read_command_and_strict_profile(self):
        config = {'ssh_profile': 'fixture-guard'}
        with patch.object(runtime, 'read_process', return_value=json.dumps(observation()).encode()) as proc:
            self.assertEqual(runtime.read_observation(config)['version'], 1)
        args = proc.call_args.args[0]
        self.assertIn('BatchMode=yes', args)
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertEqual(args[-1], '/usr/bin/head -c 2097153 /var/lib/cloudflare-cost-guard-monitor/observation.json')

    def test_smtp_tls_is_mandatory_and_header_injection_rejected(self):
        for change in ({'tls': 'none'}, {'to': 'a@example.invalid\r\nBcc: leak@example.invalid'},
                       {'host': 'https://example.invalid'}, {'extra': 'not-supported'}):
            self.write(self.smtp, self.settings | change)
            with self.subTest(change=change), self.assertRaises(ValueError): runtime.load_smtp(self.smtp)

    def test_starttls_verifies_tls_before_authentication(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        settings = self.settings | {'tls': 'starttls', 'port': 587}
        with patch.object(runtime.smtplib, 'SMTP', return_value=client), \
                patch.object(runtime.ssl, 'create_default_context', wraps=runtime.ssl.create_default_context) as tls:
            runtime.send_email(settings, {'kind': 'opened', 'issue': {'reason': 'test'}})
        self.assertTrue(tls.called)
        calls = [c[0] for c in client.method_calls]
        self.assertLess(calls.index('starttls'), calls.index('login'))
        self.assertLess(calls.index('login'), calls.index('send_message'))

    def test_sensitive_values_never_appear_in_report_or_state_payloads(self):
        result = self.run_watch(None, apply=True)
        self.assertNotIn(self.settings['to'], json.dumps(result))
        self.assertNotIn(self.settings['password'], json.dumps(result))
        with contextlib.closing(sqlite3.connect(self.root / 'state' / 'watch.sqlite3')) as db:
            text = '\n'.join(str(row) for row in db.iterdump())
        self.assertNotIn(self.settings['to'], text)
        self.assertNotIn(self.settings['password'], text)


if __name__ == '__main__': unittest.main()
