"""Offline sharing demo: python -B -m examples.monitoring_demo.

Real watcher policy, SQLite incidents and delivery bookkeeping; synthetic
observations and an in-memory sender. No provider, SSH or SMTP connections.
"""
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path

from cfguard.monitoring import runtime


def observation(now, amount):
    stamp = now.isoformat()
    return {
        'version': 1, 'observed_at': stamp,
        'guard': {'status': 'ok', 'last_attempt': stamp, 'last_finished': stamp,
                  'last_collection_success': None, 'pending_notifications': 0,
                  'oldest_pending_at': None},
        'accounts': [{
            'account_ref': 'a' * 16, 'snapshot_at': stamp,
            'subscriptions_status': 'complete',
            'subscriptions': [{'resource_ref': 'b' * 16, 'amount': amount,
                               'currency': 'USD', 'quality': 'good', 'allowed': True}],
            'coverage': [{'source': 'billing_account_coverage', 'status': 'unavailable',
                          'known_limitation': True}],
            'inventory': {product: {'status': 'complete', 'refs': [], 'expected': []}
                          for product in ('workers', 'zones')},
        }],
    }


def main():
    print('SYNTHETIC offline monitoring demo - not a financial cap.')
    print('Injected observations and FAKE events only; no real email or provider calls.')
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    stages = [
        ('Fresh zero-fee subscription', '0.00', 0, []),
        ('Allowed subscription now USD 5.50', '5.50', 1, [('opened', 'positive_subscription')]),
        ('Repeat fee: duplicate suppressed', '5.50', 1, []),
        ('Missing evidence: prior fee stays active', None, 2, [('opened', 'observation_unknown')]),
        ('Fresh data restored, fee still USD 5.50', '5.50', 1, [('recovered', 'observation_unknown')]),
        ('Fresh confirmed zero: fee recovers', '0.00', 0, [('recovered', 'positive_subscription')]),
        ('Repeat zero: duplicate recovery suppressed', '0.00', 0, []),
    ]
    events = []

    def fake_sender(settings, event):
        events.append(event)

    with tempfile.TemporaryDirectory(prefix='cfguard-synthetic-demo-') as temporary:
        root = Path(temporary)
        smtp = root / 'synthetic-smtp.json'
        runtime.atomic_write(smtp, runtime.canonical({
            'host': 'smtp.example.invalid', 'port': 465, 'tls': 'ssl',
            'username': 'synthetic', 'password': 'SYNTHETIC-NOT-A-CREDENTIAL',
            'from': 'demo@example.invalid', 'to': 'observer@example.invalid',
        }).encode())
        config = {'version': 1, 'state_dir': str(root / 'state'),
                  'smtp_file': str(smtp), 'expected_account_refs': ['a' * 16]}
        for index, (label, amount, active, expected_events) in enumerate(stages):
            at = now + timedelta(minutes=index)
            value = observation(at, amount) if amount is not None else None
            before = len(events)
            report = runtime.watch(config, now=at, apply=True, send=True,
                                   loader=lambda _: value, sender=fake_sender)
            emitted = events[before:]
            actual_events = [(event['kind'], event['issue']['reason']) for event in emitted]
            expected_issues = (['observation_unknown'] if amount is None else
                               ['positive_subscription'] if amount == '5.50' else [])
            if (report['active_incidents'] != active or actual_events != expected_events or
                    report['queued'] != len(expected_events) or
                    report['delivered'] != len(expected_events) or
                    report['pending'] != 0 or report['failed'] != 0 or
                    [issue['reason'] for issue in report['issues']] != expected_issues):
                raise RuntimeError('Synthetic demo transition failed at stage ' + str(index + 1))
            if value is not None and (len(report['limitations']) != 1 or
                    report['limitations'][0]['status'] != 'unavailable'):
                raise RuntimeError('Synthetic billing limitation was lost')
            print(f'{index + 1}. {label}: active={report["active_incidents"]}, '
                  f'new fake events={len(emitted)}')
            for event in emitted:
                print(f'   FAKE event (no email): {event["kind"]} {event["issue"]["reason"]}')
            if index == 0:
                limitation = report['limitations'][0]
                print(f'   Known billing limitation: {limitation["source"]} '
                      f'{limitation["status"]}; complete bill remains unknown.')
    print('PASS: expected transitions verified; temporary SQLite and synthetic SMTP file removed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
