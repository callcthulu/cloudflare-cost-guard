"""Deployment safety: modified/foreign paths must never be overwritten or removed."""
import hashlib
import importlib.util
import contextlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'install.py'


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'missing deployment installer')
        spec = importlib.util.spec_from_file_location('installer', SCRIPT)
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / 'owned.txt'
        self.file.write_text('owned', encoding='utf-8')
        self.manifest = {'owned.txt': hashlib.sha256(b'owned').hexdigest()}

    def test_changed_owned_file_refused_before_removal(self):
        self.file.write_text('administrator change', encoding='utf-8')
        with self.assertRaises(self.installer.InstallError):
            self.installer.remove_files(self.root, self.manifest)
        self.assertEqual(self.file.read_text(), 'administrator change')

    def test_remove_preserves_unrelated_backup(self):
        backup = self.root / 'backup.txt'
        backup.write_text('keep')
        self.installer.remove_files(self.root, self.manifest)
        self.assertFalse(self.file.exists())
        self.assertEqual(backup.read_text(), 'keep')

    def test_manifest_traversal_refused(self):
        with self.assertRaises(self.installer.InstallError):
            self.installer.verify_files(self.root, {'../outside': '0' * 64})

    @unittest.skipUnless(os.name == 'posix', 'POSIX permissions required')
    def test_symlink_parent_refused(self):
        target = self.root / 'real'
        target.mkdir()
        (target / 'payload').write_text('owned')
        (self.root / 'link').symlink_to(target, target_is_directory=True)
        with self.assertRaises(self.installer.InstallError):
            self.installer.verify_files(self.root, {'link/payload': self.manifest['owned.txt']})

    def test_missing_owned_file_refused(self):
        self.file.unlink()
        with self.assertRaises(self.installer.InstallError):
            self.installer.verify_files(self.root, self.manifest)

    def test_source_unit_permissions_checked_before_read(self):
        unit = self.root / 'unsafe.service'
        unit.write_text('malicious unit')
        with patch.object(self.installer, 'safe_path', side_effect=self.installer.InstallError('unsafe')):
            with self.assertRaises(self.installer.InstallError):
                self.installer.read_source(unit)

    def test_foreign_dropins_and_enablement_refused(self):
        base = self.root / 'etc/systemd/system'
        dropin = base / 'cloudflare-cost-guard.service.d'
        dropin.mkdir(parents=True)
        with self.assertRaises(self.installer.InstallError):
            self.installer.assert_no_unit_collisions(self.root)
        dropin.rmdir()
        wants = base / 'timers.target.wants'
        wants.mkdir()
        (wants/'cloudflare-cost-guard.timer').write_text('foreign')
        with self.assertRaises(self.installer.InstallError):
            self.installer.assert_no_unit_collisions(self.root)

    @contextlib.contextmanager
    def installation(self, *, mode='enforce', installed=True, unit_state='inactive', unreadable=None):
        """Exercise real config/source preflight; replace only privileged host edges."""
        installer = self.installer
        read, write, approval = (self.root / name for name in ('read.token', 'write.token', 'approval.json'))
        for path in (read, write, approval): path.write_text('synthetic fixture', encoding='utf-8')
        notification_files={name:self.root/name for name in ('slack.url','discord.url','bot.token','chat.id','smtp.json')}
        for path in notification_files.values():path.write_text('synthetic fixture',encoding='utf-8')
        raw = {'mode': mode, 'state_dir': installer.STATE.as_posix(),
               'accounts': [{'key': 'fixture', 'account_id': 'a'*32, 'read_token_file': str(read),
                             'billing_day': 1, 'budget': '0', 'currency': 'USD'}], 'resources': []}
        if mode == 'enforce':
            raw['resources'] = [{'account_id': 'a'*32, 'product': 'workers', 'resource_id': 'fixture', 'name': 'Fixture',
                'permitted_action': 'delete_worker', 'executor_token_file': str(write),
                'approved_manifest_file': str(approval), 'approved_manifest_digest': 'c'*64,
                'budget': {'hard_limit_usd': '1', 'source': 'account_rated_observed', 'accept_partial': True}}]
        config_path = self.root / 'config.json'
        config_path.write_text(json.dumps(raw), encoding='utf-8')
        owned = [installer.CODE / 'cfguard' / '__main__.py', installer.ETC / 'config.json']
        owned += [installer.UNITS / (installer.NAME+'.'+suffix) for suffix in ('service', 'timer')]
        marker = {'application': installer.NAME, 'version': 1, 'uid': 123, 'gid': 456,
                  'files': {path.relative_to('/').as_posix(): 'fixture' for path in owned} if installed else {}}
        mutations, checks, commands = {}, [], []
        real_stat = type(read).stat
        def synthetic_stat(path, *args, **kwargs):
            if path in (read, write, approval, *notification_files.values()):
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_gid=456)
            return real_stat(path, *args, **kwargs)
        def run(args, **kwargs):
            checks.append(args)
            if args[:2] == ['systemctl', 'show']:
                state = unit_state.get(args[2], 'inactive') if isinstance(unit_state, dict) else unit_state
                return SimpleNamespace(returncode=0, stdout='LoadState=loaded\nActiveState='+state+'\n')
            if args[:2] == ['runuser', '-u']:
                private_files={'write':write,'approval':approval,**notification_files}
                return SimpleNamespace(returncode=int(unreadable is not None and args[-1] == str(private_files[unreadable])))
            raise AssertionError('unexpected privileged command')
        def write_owned(path, data, marker, permissions): mutations[str(path)] = data
        with contextlib.ExitStack() as stack:
            for name, value in (('load_marker', lambda: marker), ('verify_identity', lambda marker: None),
                                ('verify_files', lambda root, files: None), ('safe_path', lambda *args: None),
                                ('assert_no_unit_collisions', lambda **kwargs: None), ('write_owned', write_owned),
                                ('save_marker', lambda marker: None), ('command', lambda *args: commands.append(args))):
                stack.enter_context(patch.object(installer, name, value))
            stack.enter_context(patch('cfguard.config.validate_admin_file'))
            stack.enter_context(patch.object(type(read), 'stat', synthetic_stat))
            stack.enter_context(patch.object(installer.subprocess, 'run', run))
            yield SimpleNamespace(config=config_path, raw=raw, marker=marker, mutations=mutations,
                                  checks=checks, commands=commands, write=write, approval=approval,
                                  notification_files=notification_files)

    def test_all_native_notification_files_are_protected_and_service_readable_before_install(self):
        for unreadable in (None,'slack.url','discord.url','bot.token','chat.id','smtp.json'):
            with self.subTest(unreadable=unreadable), self.installation(unreadable=unreadable) as fixture:
                files=fixture.notification_files
                fixture.raw['notification']={'targets':[
                    {'id':'slack','type':'slack','url_file':str(files['slack.url'])},
                    {'id':'discord','type':'discord','url_file':str(files['discord.url'])},
                    {'id':'telegram','type':'telegram','token_file':str(files['bot.token']),'chat_id_file':str(files['chat.id'])},
                    {'id':'email','type':'email','settings_file':str(files['smtp.json'])}]}
                fixture.config.write_text(json.dumps(fixture.raw),encoding='utf-8')
                if unreadable:
                    with self.assertRaises(self.installer.InstallError):
                        self.installer.install(fixture.config,allow_enforce=True)
                    self.assertEqual(fixture.mutations,{})
                else:
                    self.installer.install(fixture.config,allow_enforce=True)
                    readable={args[-1] for args in fixture.checks if args[0]=='runuser'}
                    self.assertTrue({str(path) for path in files.values()} <= readable)

    def test_explicit_enforce_upgrade_installs_valid_guard_checks_both_units_and_all_private_refs(self):
        with self.installation() as fixture:
            self.installer.install(fixture.config, allow_enforce=True)
            self.assertEqual(json.loads(fixture.mutations[str(self.installer.ETC/'config.json')])['mode'], 'enforce')
            states = [args for args in fixture.checks if args[:2] == ['systemctl', 'show']]
            self.assertEqual({args[2] for args in states}, {self.installer.NAME+'.service', self.installer.NAME+'.timer'})
            readable = {args[-1] for args in fixture.checks if args[0] == 'runuser'}
            self.assertIn(str(fixture.write), readable)
            self.assertIn(str(fixture.approval), readable)
            self.assertEqual(fixture.commands, [('systemctl', 'daemon-reload')])

    def test_mixed_enforcement_install_keeps_warning_only_resource_without_writer(self):
        with self.installation() as fixture:
            warning_only = {'account_id': 'a'*32, 'product': 'workers', 'resource_id': 'warning-only',
                            'name': 'Warning-only fixture',
                            'budget': {'source': 'account_rated_observed', 'warnings': [{'usd': '5'}]}}
            fixture.raw['resources'].append(warning_only)
            fixture.config.write_text(json.dumps(fixture.raw), encoding='utf-8')
            self.installer.install(fixture.config, allow_enforce=True)
            installed = json.loads(fixture.mutations[str(self.installer.ETC/'config.json')])
            self.assertEqual(len(installed['resources']), 2)
            self.assertNotIn('executor_token_file', installed['resources'][1])
            reads = [args[-1] for args in fixture.checks if args[0] == 'runuser']
            self.assertEqual(reads.count(str(fixture.write)), 1)
            self.assertEqual(fixture.commands, [('systemctl', 'daemon-reload')])

    def test_enforce_default_uninstalled_active_unreadable_or_unbudgeted_refused_before_writes(self):
        variants = [('default', {}, False), ('uninstalled', {'installed': False}, True),
                    ('active', {'unit_state': 'active'}, True), ('failed', {'unit_state': 'failed'}, True),
                    ('timer_active', {'unit_state': {self.installer.NAME+'.timer': 'active'}}, True),
                    ('unreadable_writer', {'unreadable': 'write'}, True), ('unreadable_approval', {'unreadable': 'approval'}, True),
                    ('no_budget', {}, True), ('no_guards', {}, True)]
        for name, options, allow in variants:
            with self.subTest(case=name), self.installation(**options) as fixture:
                if name == 'no_budget':
                    fixture.raw['resources'][0].pop('budget')
                    fixture.raw['resources'][0]['permitted_action'] = 'disable_worker_endpoints'
                if name == 'no_guards': fixture.raw['resources'] = []
                fixture.config.write_text(json.dumps(fixture.raw), encoding='utf-8')
                with self.assertRaises(self.installer.InstallError):
                    if allow: self.installer.install(fixture.config, allow_enforce=True)
                    else: self.installer.install(fixture.config)
                self.assertEqual(fixture.mutations, {})
                self.assertEqual(fixture.commands, [])

    def test_enforce_preflight_invalid_owned_hash_or_identity_never_deploys(self):
        for boundary in ('verify_identity', 'verify_files'):
            with self.subTest(boundary=boundary), self.installation() as fixture:
                with patch.object(self.installer, boundary, side_effect=self.installer.InstallError('modified')):
                    with self.assertRaises(self.installer.InstallError):
                        self.installer.install(fixture.config, allow_enforce=True)
                self.assertEqual(fixture.mutations, {})
                self.assertEqual(fixture.checks, [])
                self.assertEqual(fixture.commands, [])

    def test_installer_cli_passes_explicit_enforcement_flag(self):
        calls = []
        with patch.object(self.installer.sys, 'platform', 'linux'), \
             patch.object(self.installer.os, 'geteuid', lambda: 0, create=True), \
             patch.object(self.installer.sys, 'argv', ['install.py', 'install', '--allow-enforce', '--config', '/synthetic/config.json']), \
             patch.object(self.installer, 'install', lambda path, **flags: calls.append((path.as_posix(), flags))):
            self.assertEqual(self.installer.main(), 0)
        self.assertEqual(calls, [('/synthetic/config.json', {'allow_enforce': True})])

    def test_enforce_systemd_timeout_refuses_before_writes_with_sanitized_error(self):
        with self.installation() as fixture:
            real_run = self.installer.subprocess.run
            def run(args, **kwargs):
                if args[0] == 'systemctl':
                    raise self.installer.subprocess.TimeoutExpired(args, 10)
                return real_run(args, **kwargs)
            with patch.object(self.installer.subprocess, 'run', run):
                with self.assertRaises(self.installer.InstallError):
                    self.installer.install(fixture.config, allow_enforce=True)
            self.assertEqual(fixture.mutations, {})
            self.assertEqual(fixture.commands, [])

    def test_observe_install_default_path_still_does_not_query_or_start_systemd(self):
        with self.installation(mode='observe', installed=False) as fixture:
            self.installer.install(fixture.config)
            self.assertEqual(json.loads(fixture.mutations[str(self.installer.ETC/'config.json')])['mode'], 'observe')
            self.assertFalse(any(args[0] == 'systemctl' for args in fixture.checks))
            self.assertEqual(fixture.commands, [('systemctl', 'daemon-reload')])
