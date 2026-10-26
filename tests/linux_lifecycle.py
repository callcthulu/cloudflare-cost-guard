#!/usr/bin/env python3
"""Destructive ONLY inside a disposable Linux fixture; never run on a real server.

CFGUARD_DISPOSABLE=1 python3 tests/linux_lifecycle.py
Uses synthetic credentials, a staged fake collector and a private network namespace.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

NAME = 'cloudflare-cost-guard'
STATE = Path('/var/lib') / NAME
ETC = Path('/etc') / NAME
STAGE = Path('/root/cfguard-lifecycle-source')
SECRET = 'FAKE_LOCAL_FIXTURE_TOKEN_NEVER_VALID'
REPORT = {}


def run(*args, good=(0,)):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode not in good:
        raise AssertionError(f'local command failed: {args[0]} exit={result.returncode}: {result.stderr[:250]}')
    return result


def ctl(*args, good=(0,)):
    return run('systemctl', *args, good=good)


def wait_for(predicate, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.15)
    raise AssertionError('fixture deadline exceeded')


def main():
    if sys.platform != 'linux' or os.geteuid() != 0 or os.environ.get('CFGUARD_DISPOSABLE') != '1':
        raise SystemExit('Requires Linux root and explicit CFGUARD_DISPOSABLE=1 inside an expendable fixture.')
    if Path('/proc/1/comm').read_text().strip() != 'systemd':
        raise SystemExit('Booted systemd is required.')
    source = Path(__file__).resolve().parents[1]
    if STAGE.exists():
        raise SystemExit('Existing lifecycle stage; use a fresh disposable fixture.')
    STAGE.mkdir(mode=0o700)
    for directory in ('cfguard', 'deploy'):
        (STAGE / directory).mkdir()
        for path in (source / directory).iterdir():
            if path.is_file() and path.suffix in ('.py', '.service', '.timer'):
                shutil.copyfile(path, STAGE / directory / path.name)
    # The collector is replaced only in the disposable staging copy. Production
    # package, state, policy, runner and scheduler still execute their real code.
    with (STAGE / 'cfguard/cloudflare.py').open('a') as handle:
        handle.write('''
# Disposable Linux lifecycle adapter; never part of production source.
def collect(account, now):
    import time
    from pathlib import Path
    from decimal import Decimal
    from .models import ResourceKey, Observation, Snapshot
    from .config import billing_window
    root = Path('/var/lib/cloudflare-cost-guard')
    counter = root / 'fixture-count'
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    (root / 'fixture-active').write_text('active')
    time.sleep(3)
    (root / 'fixture-active').unlink()
    start, end = billing_window(now, account.billing_day)
    observation = Observation(ResourceKey(account.account_id, 'resource', 'workers', 'fixture-worker'),
        'requests', Decimal('20') if count == 1 else Decimal('0'), 'requests',
        start, end, now, now, 'good', 'offline_fixture', True, False)
    return Snapshot(account.account_id, (observation,), (), (),
        {'requests': 'complete', 'subscriptions': 'complete'}, now)
class Client:
    def __init__(self, token_file):
        from pathlib import Path
        if not Path(token_file).read_text():
            raise ValueError('fixture credential unavailable')
    def collect(self, account, now, *, include_rated=True):
        return collect(account, now)
''')
    installer = [sys.executable, str(STAGE / 'deploy/install.py')]
    run(*installer, 'prepare')
    run(*installer, 'prepare')
    import grp
    gid = grp.getgrnam(NAME).gr_gid
    token = ETC / 'secrets/read.token'
    token.write_text(SECRET)
    os.chown(token, 0, gid)
    os.chmod(token, 0o640)
    config = {'mode': 'observe', 'accounts': [{'key': 'fixture', 'account_id': 'a' * 32,
        'read_token_file': str(token), 'billing_day': 1, 'budget': '1', 'currency': 'USD'}],
        'resources': [{'account_id': 'a' * 32, 'product': 'workers', 'resource_id': 'fixture-worker',
        'name': 'Offline fixture', 'thresholds': [{'metric': 'requests', 'limit': '10', 'unit': 'requests'}]}]}
    config_path = STAGE / 'config.json'
    config_path.write_text(json.dumps(config))
    os.chmod(config_path, 0o600)
    # Unsafe token permissions must fail before unit/code installation.
    os.chmod(token, 0o644)
    run(*installer, 'install', '--config', str(config_path), good=(2,))
    assert not Path('/etc/systemd/system/' + NAME + '.service').exists()
    os.chmod(token, 0o640)
    run(*installer, 'install', '--config', str(config_path))
    run(*installer, 'install', '--config', str(config_path))
    REPORT['install_twice'] = 'passed'
    assert ctl('is-enabled', NAME + '.timer', good=(1,)).stdout.strip() == 'disabled'
    verify = run('systemd-analyze', 'verify', '/etc/systemd/system/' + NAME + '.service',
                 '/etc/systemd/system/' + NAME + '.timer')
    assert not verify.stderr, verify.stderr
    REPORT['unit_verify'] = 'passed without diagnostics'
    # Explicit fixture-only drop-ins accelerate cadence and remove all external network.
    for suffix, text in [('service', '[Service]\nPrivateNetwork=true\n'), ('timer',
        '[Timer]\nOnBootSec=\nOnUnitActiveSec=\nOnActiveSec=1s\nOnUnitInactiveSec=2s\nAccuracySec=100ms\n')]:
        folder = Path('/etc/systemd/system') / (NAME + '.' + suffix + '.d')
        folder.mkdir()
        (folder / 'fixture.conf').write_text(text)
    ctl('daemon-reload')
    started = time.time()
    ctl('start', NAME + '.timer')
    counter = STATE / 'fixture-count'
    wait_for(lambda: (STATE / 'fixture-active').exists())
    # A direct concurrent invocation must be refused by the real process lock.
    overlap = subprocess.run(
        ['runuser', '-u', NAME, '--', '/usr/bin/python3', '-B', '-m', 'cfguard', 'run',
         '--config', str(ETC / 'config.json')], cwd='/opt/' + NAME, text=True, capture_output=True)
    assert overlap.returncode == 3 and json.loads(overlap.stdout) == {'error': 'overlapping_run'}, 'overlap did not hit process lock'
    assert int(counter.read_text()) == 1, 'overlap reached collector'
    REPORT['overlap'] = {'exit': overlap.returncode, 'collector_calls': 1}
    main_pid = ctl('show', NAME + '.service', '-p', 'MainPID', '--value').stdout.strip()
    if main_pid != '0':
        status = Path('/proc') / main_pid / 'status'
        REPORT['running_memory'] = [line for line in status.read_text().splitlines() if line.startswith(('VmRSS:', 'VmHWM:'))]
    wait_for(lambda: counter.exists() and int(counter.read_text()) >= 2)
    ctl('stop', NAME + '.timer')
    wait_for(lambda: not (STATE / 'fixture-active').exists())
    wait_for(lambda: ctl('show', NAME + '.service', '-p', 'ActiveState', '--value').stdout.strip() != 'activating')
    REPORT['scheduled_runs'] = int(counter.read_text())
    assert ctl('show', NAME + '.service', '-p', 'PrivateNetwork', '--value').stdout.strip() == 'yes'
    REPORT['resource_accounting'] = ctl('show', NAME + '.service', '-p', 'CPUUsageNSec', '-p', 'MemoryPeak', '-p', 'Result').stdout.strip().splitlines()
    db = sqlite3.connect(STATE / 'guard.sqlite3')
    rows = db.execute('SELECT state FROM resources').fetchall()
    assert any(json.loads(row[0])['status'] == 'tripped' for row in rows), 'trip did not survive healthy second process'
    db.close()
    REPORT['restart_latch'] = 'persisted across scheduled processes'
    denied = run('runuser', '-u', 'nobody', '--', 'cat', str(token), good=(1,))
    assert SECRET not in denied.stdout
    logs = run('journalctl', '-u', NAME + '.service', '--since', '@' + str(int(started)), '--no-pager').stdout
    assert SECRET not in logs
    assert 'Traceback' not in logs
    REPORT['secret_restriction_and_logs'] = 'nobody denied; fake token absent from journal'
    # A foreign backup is deliberately outside the ownership manifest.
    backup = Path('/opt') / NAME / 'operator-backup.txt'
    backup.write_text('preserve fixture backup')
    before = hashlib.sha256((STATE / 'guard.sqlite3').read_bytes()).hexdigest()
    run(*installer, 'uninstall')
    assert not Path('/etc/systemd/system/' + NAME + '.timer').exists()
    assert not Path('/etc/systemd/system/' + NAME + '.service').exists()
    assert hashlib.sha256((STATE / 'guard.sqlite3').read_bytes()).hexdigest() == before
    assert backup.read_text() == 'preserve fixture backup'
    assert token.read_text() == SECRET
    REPORT['uninstall'] = 'units/code removed; exact DB, secrets, unrelated backup preserved'
    print(json.dumps(REPORT, indent=2))


if __name__ == '__main__':
    main()
