"""Test recovery of CPA credentials from saved account records."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cpa_export
import grok_register_ttk


class CpaRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.accounts = self.root / "accounts.txt"
        self.email = "user@example.com"
        self.password = "password-secret"
        self.sso = "sso-secret"
        self.accounts.write_text(
            "%s----%s----%s\n" % (self.email, self.password, self.sso),
            encoding="utf-8",
        )
        self.config = {
            "cpa_export_enabled": True,
            "cpa_auth_dir": str(self.root / "cpa"),
            "sub2api_auto_import": False,
        }

    def test_recovery_mints_from_exact_account_without_logging_secrets(self):
        logs = []
        expected = {"ok": True, "path": str(self.root / "cpa" / "xai-user@example.com.json")}
        with patch.object(cpa_export, "export_cpa_xai_for_account", return_value=expected) as export:
            result = cpa_export.retry_cpa_from_accounts_file(
                self.accounts, self.email, config=self.config, log_callback=logs.append
            )
        self.assertTrue(result["ok"])
        kwargs = export.call_args.kwargs
        self.assertEqual(kwargs["password"], self.password)
        self.assertEqual(kwargs["sso"], self.sso)
        self.assertNotIn(self.password, "\n".join(logs))
        self.assertNotIn(self.sso, "\n".join(logs))

    def test_existing_valid_cpa_skips_mint_and_repeats_distribution(self):
        auth_dir = Path(self.config["cpa_auth_dir"])
        auth_dir.mkdir(parents=True)
        existing = auth_dir / "xai-user@example.com.json"
        existing.write_text(
            json.dumps({
                "email": self.email,
                "access_token": "access",
                "refresh_token": "refresh",
            }),
            encoding="utf-8",
        )
        with patch.object(cpa_export, "export_cpa_xai_for_account") as mint, \
             patch.object(cpa_export, "_sync_sub2api_before_distribution", return_value=True) as sync:
            result = cpa_export.retry_cpa_from_accounts_file(
                self.accounts, self.email, config=self.config
            )
        self.assertTrue(result["reused"])
        self.assertEqual(result["path"], str(existing))
        mint.assert_not_called()
        sync.assert_called_once()

    def test_recovery_rejects_missing_malformed_and_ambiguous_records(self):
        with self.assertRaisesRegex(ValueError, "email not found"):
            cpa_export.retry_cpa_from_accounts_file(
                self.accounts, "missing@example.com", config=self.config
            )
        self.accounts.write_text("malformed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "malformed"):
            cpa_export.retry_cpa_from_accounts_file(
                self.accounts, self.email, config=self.config
            )
        self.accounts.write_text(
            "%s----one----sso-one\n%s----two----sso-two\n" % (self.email, self.email),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            cpa_export.retry_cpa_from_accounts_file(
                self.accounts, self.email, config=self.config
            )


class RetryCpaCliTests(unittest.TestCase):
    def test_retry_cpa_exit_codes(self):
        argv = ["grok_register_ttk.py", "retry-cpa", "accounts.txt", "--email", "user@example.com"]
        with patch.object(grok_register_ttk.sys, "argv", argv), \
             patch.object(grok_register_ttk, "run_retry_cpa_cli", return_value=True):
            self.assertEqual(grok_register_ttk.main(), 0)
        with patch.object(grok_register_ttk.sys, "argv", argv), \
             patch.object(grok_register_ttk, "run_retry_cpa_cli", return_value=False):
            self.assertEqual(grok_register_ttk.main(), 1)
        with patch.object(grok_register_ttk.sys, "argv", argv), \
             patch.object(grok_register_ttk, "run_retry_cpa_cli", side_effect=KeyboardInterrupt), \
             patch.object(grok_register_ttk, "cli_log"):
            self.assertEqual(grok_register_ttk.main(), 130)

    def test_retry_cpa_rejects_invalid_arguments(self):
        argv = ["grok_register_ttk.py", "retry-cpa", "accounts.txt"]
        with patch.object(grok_register_ttk.sys, "argv", argv):
            self.assertEqual(grok_register_ttk.main(), 2)


if __name__ == "__main__":
    unittest.main()
