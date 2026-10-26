"""Deployment safety: modified/foreign paths must never be overwritten or removed."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
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
