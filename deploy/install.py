#!/usr/bin/env python3
"""Root-only, explicit local preparation/install/removal; no provider I/O."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

NAME = 'cloudflare-cost-guard'
CODE = Path('/opt') / NAME
ETC = Path('/etc') / NAME
STATE = Path('/var/lib') / NAME
MARKER = ETC / '.installation.json'
UNITS = Path('/etc/systemd/system')
DIRECTORIES = (CODE, ETC, ETC / 'secrets', STATE)


class InstallError(ValueError):
    pass


def safe_path(path, owner=0, boundary=None):
    """Reject links and replaceable components, including existing ancestors."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if not part.exists() and not part.is_symlink():
            continue
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise InstallError('symlink in managed path')
        expected_owner = owner if part == path or boundary is not None else 0
        if os.name == 'posix' and (info.st_uid != expected_owner or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise InstallError('untrusted ownership or writable managed path')
        if boundary is not None and part == Path(boundary).absolute():
            break


def verify_files(root, files):
    for relative, digest in files.items():
        item = PurePosixPath(relative)
        if item.is_absolute() or '..' in item.parts or not item.parts:
            raise InstallError('invalid manifest path')
        target = Path(root).joinpath(*item.parts)
        safe_path(target, os.getuid() if os.name == 'posix' else 0, root)
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise InstallError('owned file missing or modified; refusing changes')


def remove_files(root, files):
    verify_files(root, files)  # Validate every file before deleting any.
    for relative in files:
        Path(root).joinpath(*PurePosixPath(relative).parts).unlink()


def command(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def read_source(path):
    safe_path(path)
    return path.read_bytes()


def assert_no_unit_collisions(root=Path('/'), allow_installed=False):
    for relative in ('etc/systemd/system', 'run/systemd/system',
                     'usr/local/lib/systemd/system', 'usr/lib/systemd/system'):
        directory = root / relative
        for suffix in ('service', 'timer'):
            name = f'{NAME}.{suffix}'
            dropin = directory / (name + '.d')
            if dropin.exists() or dropin.is_symlink():
                raise InstallError('foreign service or timer drop-ins exist')
            unit = directory / name
            installed = allow_installed and relative == 'etc/systemd/system'
            if not installed and (unit.exists() or unit.is_symlink()):
                raise InstallError('foreign unit exists')
            for activation in ('*.wants/', '*.requires/'):
                for enabled in directory.glob(activation + name):
                    if not (allow_installed and enabled.is_symlink() and enabled.resolve() == UNITS / name):
                        raise InstallError('foreign enabled unit exists')


def load_marker():
    safe_path(MARKER)
    try:
        result = json.loads(MARKER.read_text())
        if result.get('application') != NAME or result.get('version') != 1 or not isinstance(result.get('files'), dict):
            raise ValueError
        return result
    except (OSError, ValueError, TypeError):
        raise InstallError('missing or invalid installation ownership marker') from None


def save_marker(marker):
    temp = MARKER.with_suffix('.tmp')
    if temp.exists() or temp.is_symlink():
        raise InstallError('foreign temporary marker exists')
    with temp.open('x', encoding='utf-8') as handle:
        os.chmod(temp, 0o600)
        json.dump(marker, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(MARKER)


def prepare():
    import grp
    import pwd
    if MARKER.exists():
        marker = load_marker()
        verify_files('/', marker['files'])
        verify_identity(marker)
        assert_no_unit_collisions(allow_installed=True)
        return marker
    assert_no_unit_collisions()
    for directory in DIRECTORIES:
        safe_path(directory)
        if directory.exists():
            raise InstallError('existing unowned application directory')
    for unit in ('service', 'timer'):
        path = UNITS / f'{NAME}.{unit}'
        safe_path(path)
        if path.exists():
            raise InstallError('existing unowned service or timer')
    try:
        pwd.getpwnam(NAME)
    except KeyError:
        pass
    else:
        raise InstallError('existing unowned service user')
    try:
        grp.getgrnam(NAME)
    except KeyError:
        pass
    else:
        raise InstallError('existing unowned service group')
    command('groupadd', '--system', NAME)
    command('useradd', '--system', '--gid', NAME, '--no-create-home', '--home-dir', str(STATE), '--shell', '/usr/sbin/nologin', NAME)
    account = pwd.getpwnam(NAME)
    for directory in DIRECTORIES:
        directory.mkdir(mode=0o750)
        os.chown(directory, 0, account.pw_gid)
    os.chown(STATE, account.pw_uid, account.pw_gid)
    os.chmod(STATE, 0o700)
    marker = {'application': NAME, 'version': 1, 'uid': account.pw_uid, 'gid': account.pw_gid, 'files': {}}
    save_marker(marker)
    return marker


def verify_identity(marker):
    import pwd
    try:
        account = pwd.getpwnam(NAME)
    except KeyError:
        raise InstallError('service identity missing') from None
    if account.pw_uid != marker['uid'] or account.pw_gid != marker['gid'] or account.pw_shell != '/usr/sbin/nologin':
        raise InstallError('service identity changed')
    for directory in DIRECTORIES:
        safe_path(directory, marker['uid'] if directory == STATE else 0)
        if not directory.is_dir():
            raise InstallError('managed directory missing')


def write_owned(path, data, marker, mode=0o644):
    safe_path(path)
    relative = path.relative_to('/').as_posix()
    if (path.exists() or path.is_symlink()) and relative not in marker['files']:
        raise InstallError('refusing to overwrite unowned file')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.cfguard-new')
    if temp.exists() or temp.is_symlink():
        raise InstallError('foreign temporary file exists')
    with temp.open('xb') as handle:
        os.chmod(temp, mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chown(temp, 0, marker['gid'])
    temp.replace(path)
    marker['files'][relative] = hashlib.sha256(data).hexdigest()


def assert_units_inactive():
    """Read-only arming gate; never stop a running unit on the operator's behalf."""
    for suffix in ('service', 'timer'):
        try:
            result = subprocess.run(['systemctl', 'show', f'{NAME}.{suffix}',
                                     '--property=LoadState', '--property=ActiveState'],
                                    capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            raise InstallError('cannot establish managed unit state') from None
        states = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode or states.get('LoadState') != 'loaded' or states.get('ActiveState') != 'inactive':
            raise InstallError('enforcement installation requires both managed units loaded and inactive')


def install(config_path, *, allow_enforce=False):
    marker = load_marker()
    verify_identity(marker)
    verify_files('/', marker['files'])
    assert_no_unit_collisions(allow_installed=True)
    source = Path(__file__).resolve().parents[1]
    # Validate source trust BEFORE importing any package code with root privileges.
    package = source / 'cfguard'
    safe_path(package)
    for original in package.rglob('*'):
        safe_path(original)
    sources = sorted(package.glob('*.py'))
    if not sources or not (package / '__main__.py').is_file():
        raise InstallError('incomplete source package')
    for suffix in ('service', 'timer'):
        safe_path(source / 'deploy' / f'{NAME}.{suffix}')
    sys.path.insert(0, str(source))
    from cfguard.config import load_config
    config = load_config(config_path)
    if allow_enforce:
        required = {path.relative_to('/').as_posix() for path in (
            CODE / 'cfguard' / '__main__.py', ETC / 'config.json',
            UNITS / f'{NAME}.service', UNITS / f'{NAME}.timer')}
        if not required <= marker['files'].keys():
            raise InstallError('enforcement requires an existing complete managed installation')
        if (config.mode != 'enforce' or not config.resources
                or any(resource.budget is None or resource.permitted_action not in
                       {'delete_worker', 'disable_worker_endpoints'} for resource in config.resources)):
            raise InstallError('enforcement installation requires explicit supported budget guards')
    elif config.mode != 'observe' or any(r.executor_token_file is not None for r in config.resources):
        raise InstallError('initial installer requires observe mode without executor credentials')
    if config.state_dir != STATE:
        raise InstallError('state_dir must match protected service state directory')
    secrets = [account.read_token_file for account in config.accounts]
    if config.notification:
        secrets.append(config.notification['url_file'])
    if allow_enforce:
        for resource in config.resources:
            secrets.extend((resource.executor_token_file, resource.approved_manifest_file))
    for secret in secrets:
        safe_path(secret)
        info = secret.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_gid != marker['gid'] or stat.S_IMODE(info.st_mode) != 0o640:
            raise InstallError('secret must be root:service-group regular file mode 0640')
        result = subprocess.run(['runuser', '-u', NAME, '--', 'test', '-r', str(secret)], capture_output=True)
        if result.returncode:
            raise InstallError('service cannot read a configured secret')
    payloads = [(CODE / 'cfguard' / p.name, read_source(p), 0o644) for p in sources]
    payloads += [(UNITS / f'{NAME}.{suffix}', read_source(source / 'deploy' / f'{NAME}.{suffix}'), 0o644) for suffix in ('service', 'timer')]
    payloads.append((ETC / 'config.json', config_path.read_bytes(), 0o640))
    for destination, _, _ in payloads:
        safe_path(destination)
        if destination.exists() and destination.relative_to('/').as_posix() not in marker['files']:
            raise InstallError('foreign deployment target exists')
    for original in sources:
        safe_path(original)
    if allow_enforce:
        assert_units_inactive()
    for destination, data, mode in payloads:
        write_owned(destination, data, marker, mode)
    save_marker(marker)
    command('systemctl', 'daemon-reload')
    print(f'Installed in {config.mode} mode. Timer remains under administrator control.')


def uninstall():
    marker = load_marker()
    verify_identity(marker)
    verify_files('/', marker['files'])
    if not marker['files']:
        print('Already uninstalled; retained state and credentials untouched.')
        return
    command('systemctl', 'disable', '--now', f'{NAME}.timer')
    command('systemctl', 'stop', f'{NAME}.service')
    remove_files('/', marker['files'])
    marker['files'] = {}
    save_marker(marker)
    command('systemctl', 'daemon-reload')
    print('Uninstalled executable/unit files; state, secrets, identity and ownership marker retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'install', 'uninstall'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--allow-enforce', action='store_true',
                        help='explicitly install budget enforcement on an existing stopped managed installation')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Linux root is required')
    if args.operation == 'install' and args.config is None:
        parser.error('install requires --config')
    if args.allow_enforce and args.operation != 'install':
        parser.error('--allow-enforce applies only to install')
    try:
        if args.operation == 'prepare':
            prepare()
            print('Prepared protected directories and dedicated identity; provision secret files before install.')
        elif args.operation == 'install':
            install(args.config, allow_enforce=args.allow_enforce)
        else:
            uninstall()
    except (InstallError, OSError, subprocess.CalledProcessError, ValueError):
        print('Deployment refused: unsafe, modified or invalid local installation/configuration.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
