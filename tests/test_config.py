import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from cfguard.config import ConfigError, billing_window, load_config
from cfguard.models import ResourceKey


def example():
    return {"accounts": [{"key": "sandbox", "account_id": "a" * 32,
        "read_token_file": "/etc/cfguard/read.token", "billing_day": 31,
        "billing_period_verified": True, "budget": "0", "currency": "USD",
        "expected_subscriptions": [], "zones": ["b" * 32],
        "prices": [{"metric": "requests", "unit": "requests", "currency": "USD",
                    "amount": "0.30", "per_quantity": "1000000", "allowance": "10000000",
                    "source": "synthetic fixture", "as_of": "2026-10-01"}]}],
        "resources": [{"account_id": "a" * 32, "product": "workers", "resource_id": "sample",
                       "name": "Sample", "zones": ["b" * 32], "hostnames": ["one.example", "two.example"],
                       "thresholds": [{"metric": "requests", "limit": "100", "unit": "requests"}]}]}


class ConfigTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            # Parser fixtures are unprivileged; ownership has its own negative tests
            # and is exercised for real in the disposable Linux installation.
            with patch('cfguard.config.validate_admin_file'):
                return load_config(path)

    def test_default_observe_and_decimal(self):
        config = self.load(example())
        self.assertEqual(config.mode, "observe")
        self.assertEqual(config.accounts[0].prices[0].amount, Decimal("0.30"))
        self.assertEqual(len(config.resources), 1)

    def test_reject_invalid_identity_threshold_and_secrets(self):
        base = example()
        variants = []
        for field, value in (("mode", "unsafe"), ("token", "secret-value")):
            data = copy.deepcopy(base); data[field] = value; variants.append(data)
        data = copy.deepcopy(base); data["resources"] *= 2; variants.append(data)
        data = copy.deepcopy(base); data["resources"][0]["account_id"] = "c" * 32; variants.append(data)
        data = copy.deepcopy(base); data["resources"][0]["zones"] = ["c" * 32]; variants.append(data)
        data = copy.deepcopy(base); data["resources"][0]["resource_id"] = "../other"; variants.append(data)
        data = copy.deepcopy(base); data["accounts"][0]["account_id"] = "../other"; variants.append(data)
        for limit in (-1, "NaN", "-1", 0.3):
            data = copy.deepcopy(base); data["resources"][0]["thresholds"][0]["limit"] = limit; variants.append(data)
        data = copy.deepcopy(base); data["accounts"][0]["currency"] = ""; variants.append(data)
        data = copy.deepcopy(base); data["accounts"][0]["read_token_file"] = "relative.token"; variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ConfigError): self.load(data)

    def test_scope_identity_rules(self):
        with self.assertRaises(ValueError): ResourceKey("a", "account", "workers", resource_id="x")
        with self.assertRaises(ValueError): ResourceKey("a", "resource", "workers")
        with self.assertRaises(ValueError): ResourceKey("a", "zone", "workers", resource_id="x", zone_id="z")

    def test_utc_billing_anchor_rollover(self):
        utc = timezone.utc
        self.assertEqual(billing_window(datetime(2026, 3, 1, tzinfo=utc), 31),
                         (datetime(2026, 2, 28, tzinfo=utc), datetime(2026, 3, 31, tzinfo=utc)))
        self.assertEqual(billing_window(datetime(2028, 2, 29, tzinfo=utc), 31),
                         (datetime(2028, 2, 29, tzinfo=utc), datetime(2028, 3, 31, tzinfo=utc)))
        with self.assertRaises(ValueError): billing_window(datetime(2026, 1, 1), 1)

    def test_invalid_mode_type_and_duplicate_json_key(self):
        data = example(); data["mode"] = []
        with self.assertRaises(ConfigError): self.load(data)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"accounts": [], "accounts": []}', encoding="utf-8")
            with self.assertRaises(ConfigError): load_config(path)

    def test_linux_admin_ownership_validation(self):
        import stat
        from cfguard.config import validate_admin_file
        from types import SimpleNamespace
        good = SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=0)
        for bad in (SimpleNamespace(st_mode=stat.S_IFREG | 0o660, st_uid=0),
                    SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=1000),
                    SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0)):
            with patch("cfguard.config.os.name", "posix"), patch.object(type(Path()), "lstat", return_value=bad):
                with self.assertRaises(ConfigError): validate_admin_file(Path("config.json"))
        path = Path("config.json")
        with patch("cfguard.config.os.name", "posix"), patch.object(type(path), "lstat", side_effect=[good, SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=1000)]):
            with self.assertRaises(ConfigError): validate_admin_file(path)


if __name__ == "__main__": unittest.main()
