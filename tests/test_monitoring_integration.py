"""Actual SQLite -> sampler -> watcher -> durable delivery, with synthetic I/O."""
import contextlib
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import unittest

from cfguard.monitoring.runtime import sample, watch
from cfguard.monitoring.sources import collect, reference
import test_monitoring_sources as fixture


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.source = fixture.SourcesTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.directory = self.source.database.parent
        self.config = {'version': 1, 'observation_file': str(self.directory / 'observation.json'),
                       'state_dir': str(self.directory / 'watch'),
                       'smtp_file': str(self.directory / 'smtp.json'),
                       'expected_account_refs': [reference(fixture.ACCOUNT, 'account')]}
        settings = {'host': 'smtp.example.invalid', 'port': 465, 'tls': 'ssl',
                    'username': 'fixture', 'password': 'SYNTHETIC-ONLY',
                    'from': 'watch@example.invalid', 'to': 'owner@example.invalid'}
        Path(self.config['smtp_file']).write_text(json.dumps(settings), encoding='utf-8')
        Path(self.config['smtp_file']).chmod(0o600)
        self.workers = ['expected-worker']
        self.inventory_failure = False
        self.sent = []

    def export(self):
        owner = self
        class Client:
            def inventory(self, account, product):
                if owner.inventory_failure: raise OSError('PRIVATE-FAILURE')
                return owner.workers if product == 'workers' else [fixture.ZONE]
        def collector(config, now): return collect(config, now, lambda _: Client())
        sample(self.source.config, self.config['observation_file'], now=fixture.NOW, collector=collector)

    def run_watch(self, **kwargs):
        return watch(self.config, now=kwargs.pop('now', fixture.NOW), apply=True, send=True,
                     sender=lambda settings, event: self.sent.append(event), **kwargs)

    def test_positive_allowed_fee_alerts_and_recovers_without_guard_database_write(self):
        before = self.source.database.read_bytes()
        self.export(); first = self.run_watch()
        positives = [e for e in self.sent if e['issue']['reason'] == 'positive_subscription']
        self.assertEqual(len(positives), 1)
        self.assertEqual(positives[0]['issue']['details'], {'amount': '5.50', 'currency': 'USD'})
        self.assertEqual(before, self.source.database.read_bytes())
        self.run_watch(); self.assertEqual(len([e for e in self.sent if e['issue']['reason'] == 'positive_subscription']), 1)
        self.source.snapshot['subscriptions'][0]['amount'] = '0'
        self.source.save_snapshot(); self.export(); self.run_watch()
        self.assertEqual([e['kind'] for e in self.sent if e['issue']['reason'] == 'positive_subscription'], ['opened', 'recovered'])
        self.assertNotIn(fixture.ACCOUNT, json.dumps(first))

    def test_new_worker_then_outage_does_not_false_recover_then_complete_absence_recovers(self):
        self.export(); self.run_watch()
        self.workers.append('new-unapproved-worker'); self.export(); self.run_watch()
        added = [e for e in self.sent if e['issue']['reason'] == 'inventory_added']
        self.assertEqual(len(added), 1)
        self.inventory_failure = True; self.export(); self.run_watch()
        self.assertFalse(any(e['kind'] == 'recovered' and e['issue']['reason'] == 'inventory_added' for e in self.sent))
        self.inventory_failure = False; self.workers.remove('new-unapproved-worker'); self.export(); self.run_watch()
        self.assertEqual([e['kind'] for e in self.sent if e['issue']['reason'] == 'inventory_added'], ['opened', 'recovered'])

    def test_zero_subscription_with_conflicting_plan_identity_cannot_recover_positive(self):
        self.export(); self.run_watch()
        zero = fixture.subscription(amount='0')
        self.source.snapshot['subscriptions'] = [zero, zero | {'plan_id': 'plan-two'}]
        self.source.save_snapshot(); self.export(); result = self.run_watch()
        self.assertTrue(any(i['reason'] == 'subscriptions_unknown' for i in result['issues']))
        with contextlib.closing(sqlite3.connect(self.directory / 'watch' / 'watch.sqlite3')) as db:
            active = db.execute("SELECT active FROM incidents WHERE key LIKE 'positive_subscription:%'").fetchone()
        self.assertEqual(active, (1,))
        self.assertEqual([e['kind'] for e in self.sent if e['issue']['reason'] == 'positive_subscription'], ['opened'])
        self.source.snapshot['subscriptions'] = [zero]
        self.source.save_snapshot(); self.export(); self.run_watch()
        self.assertEqual([e['kind'] for e in self.sent if e['issue']['reason'] == 'positive_subscription'],
                         ['opened', 'recovered'])

    def test_disappearing_rated_source_alerts_across_restart_until_fresh_restoration(self):
        self.source.snapshot['coverage']['rated_rows'] = 'parsed'
        self.source.save_snapshot(); self.export(); self.run_watch()
        del self.source.snapshot['coverage']['rated_rows']
        self.source.save_snapshot(); self.export(); lost = self.run_watch()
        losses = [i for i in lost['issues'] if i['reason'] == 'coverage_lost']
        self.assertEqual(len(losses), 1)
        self.assertTrue(losses[0]['scope'].endswith(':coverage:rated_rows'))
        self.assertEqual(losses[0]['details'], {'status': 'unknown'})
        self.assertEqual(self.run_watch()['queued'], 0)
        self.source.snapshot['coverage']['rated_rows'] = 'parsed'
        self.source.snapshot['collected_at'] = (fixture.NOW - timedelta(hours=1)).isoformat()
        self.source.save_snapshot(); self.export(); self.run_watch()
        self.assertFalse(any(e['kind'] == 'recovered' and e['issue']['reason'] == 'coverage_lost'
                             for e in self.sent))
        self.source.snapshot['collected_at'] = fixture.STAMP
        self.source.save_snapshot(); self.export(); self.run_watch()
        self.assertEqual([e['kind'] for e in self.sent if e['issue']['reason'] == 'coverage_lost'],
                         ['opened', 'recovered'])

    def test_sampler_freshness_never_conceals_guard_outage(self):
        old = (fixture.NOW - timedelta(hours=1)).isoformat()
        with contextlib.closing(sqlite3.connect(self.source.database)) as db, db:
            db.execute("UPDATE meta SET value=? WHERE key IN ('last_finished','last_attempt')", (old,))
        self.export(); result = self.run_watch()
        self.assertTrue(any(i['reason'] == 'guard_stale' for i in result['issues']))
        self.assertEqual(json.loads(Path(self.config['observation_file']).read_text())['observed_at'], fixture.STAMP)

    def test_guard_database_failure_keeps_fresh_inventory_drift_and_failed_inventory_cannot_recover(self):
        self.source.database.unlink()
        self.workers.append('new-worker')
        self.export(); result = self.run_watch()
        reasons = {i['reason'] for i in result['issues']}
        self.assertIn('snapshot_unknown', reasons)
        self.assertIn('inventory_added', reasons)
        self.inventory_failure = True; self.export(); self.run_watch()
        self.assertFalse(any(e['kind'] == 'recovered' and e['issue']['reason'] == 'inventory_added'
                             for e in self.sent))
        self.inventory_failure = False; self.workers.remove('new-worker'); self.export(); self.run_watch()
        self.assertEqual([e['kind'] for e in self.sent if e['issue']['reason'] == 'inventory_added'],
                         ['opened', 'recovered'])


if __name__ == '__main__': unittest.main()
