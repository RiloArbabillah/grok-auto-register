import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cpa_export
import sub2api_admin


class FakeClient:
    def __init__(self, accounts=None, details=None):
        self.accounts = accounts or []
        self.details = details or {}
        self.created = []
        self.updated = []

    def list_accounts(self):
        return self.accounts

    def get_account(self, account_id):
        return self.details[account_id]

    def create_account(self, body):
        self.created.append(body)
        return {"data": {"id": 77}}

    def update_credentials(self, account_id, credentials):
        self.updated.append((account_id, credentials))
        return {"data": {"id": account_id}}


class Sub2APIAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cpa_path = Path(self.temp_dir.name) / "xai-user@example.com.json"
        self.cpa_path.write_text(
            json.dumps({
                "email": "user@example.com",
                "refresh_token": "refresh-secret",
                "access_token": "access-secret",
                "sub": "subject-1",
            }),
            encoding="utf-8",
        )
        self.config = {
            "sub2api_group_ids": [5, 8],
            "sub2api_concurrency": 3,
            "sub2api_priority": 2,
        }

    def test_builds_account_from_cpa_and_config(self):
        body = sub2api_admin.build_grok_account_from_cpa(self.cpa_path, self.config)

        self.assertEqual(body["name"], "user@example.com")
        self.assertEqual(body["group_ids"], [5, 8])
        self.assertEqual(body["concurrency"], 3)
        self.assertEqual(body["priority"], 2)
        self.assertEqual(body["credentials"]["email"], "user@example.com")
        self.assertEqual(body["credentials"]["refresh_token"], "refresh-secret")

    def test_redacts_sensitive_values_recursively(self):
        redacted = sub2api_admin.redact({
            "credentials": {"refresh_token": "secret", "client_id": "visible"},
            "admin_api_key": "key-secret",
        })

        self.assertEqual(redacted["credentials"]["refresh_token"], "***redacted***")
        self.assertEqual(redacted["admin_api_key"], "***redacted***")
        self.assertEqual(redacted["credentials"]["client_id"], "visible")

    def test_creates_when_account_does_not_exist(self):
        client = FakeClient()

        result = sub2api_admin.sync_cpa_account(self.cpa_path, self.config, client=client)

        self.assertEqual(result, {"ok": True, "action": "created", "account_id": 77})
        self.assertEqual(len(client.created), 1)
        self.assertEqual(client.updated, [])

    def test_updates_credentials_without_overwriting_account_settings(self):
        client = FakeClient(
            accounts=[{"id": 40, "name": "USER@example.com", "concurrency": 99}],
            details={40: {
                "id": 40,
                "name": "USER@example.com",
                "group_ids": [123],
                "concurrency": 99,
                "priority": 9,
                "credentials": {"model_mapping": {"grok": "grok-4"}, "refresh_token": "old"},
            }},
        )

        result = sub2api_admin.sync_cpa_account(self.cpa_path, self.config, client=client)

        self.assertEqual(result, {"ok": True, "action": "updated", "account_id": 40})
        self.assertEqual(client.created, [])
        account_id, credentials = client.updated[0]
        self.assertEqual(account_id, 40)
        self.assertEqual(credentials["refresh_token"], "refresh-secret")
        self.assertEqual(credentials["model_mapping"], {"grok": "grok-4"})

    def test_rejects_ambiguous_duplicate_accounts(self):
        client = FakeClient(accounts=[
            {"id": 40, "name": "user@example.com"},
            {"id": 41, "credentials": {"email": "USER@example.com"}},
        ])

        with self.assertRaisesRegex(ValueError, "Multiple Sub2API accounts"):
            sub2api_admin.sync_cpa_account(self.cpa_path, self.config, client=client)

        self.assertEqual(client.created, [])
        self.assertEqual(client.updated, [])

    def test_client_requires_config_credentials(self):
        with self.assertRaisesRegex(ValueError, "sub2api_base_url"):
            sub2api_admin.Sub2APIClient.from_config({})
        with self.assertRaisesRegex(ValueError, "sub2api_admin_api_key"):
            sub2api_admin.Sub2APIClient.from_config({"sub2api_base_url": "https://sub.example"})

    def test_cli_dry_run_does_not_require_credentials_or_make_requests(self):
        config_path = Path(self.temp_dir.name) / "config.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")
        output = io.StringIO()

        with patch("sub2api_admin.requests.request") as request, redirect_stdout(output):
            exit_code = sub2api_admin.main([
                "--config",
                str(config_path),
                "import-cpa",
                str(self.cpa_path),
            ])

        self.assertEqual(exit_code, 0)
        request.assert_not_called()
        self.assertNotIn("refresh-secret", output.getvalue())
        self.assertIn("***redacted***", output.getvalue())

    def test_client_paginates_account_list(self):
        class DummyResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        responses = [
            DummyResponse({"data": {"items": [{"id": 1}, {"id": 2}], "total": 3}}),
            DummyResponse({"data": {"items": [{"id": 3}], "total": 3}}),
        ]
        client = sub2api_admin.Sub2APIClient("https://sub.example", "admin-secret")

        with patch("sub2api_admin.requests.request", side_effect=responses) as request:
            accounts = client.list_accounts(page_size=2)

        self.assertEqual([account["id"] for account in accounts], [1, 2, 3])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].kwargs["params"]["page"], 1)
        self.assertEqual(request.call_args_list[1].kwargs["params"]["page"], 2)


class Sub2APICPAExportHookTests(unittest.TestCase):
    def _export(self, auto_import):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_path = Path(temp_dir.name) / "xai-user@example.com.json"

        def fake_mint(**kwargs):
            output_path.write_text(
                json.dumps({"email": "user@example.com", "refresh_token": "secret"}),
                encoding="utf-8",
            )
            return {"ok": True, "path": str(output_path)}

        config = {
            "cpa_export_enabled": True,
            "cpa_auth_dir": temp_dir.name,
            "sub2api_auto_import": auto_import,
        }
        with patch("cpa_xai.mint_and_export", side_effect=fake_mint), patch(
            "sub2api_admin.sync_cpa_account",
            return_value={"ok": True, "action": "created", "account_id": 55},
        ) as sync:
            result = cpa_export.export_cpa_xai_for_account(
                "user@example.com",
                "password",
                config=config,
                log_callback=lambda _message: None,
            )
        return result, sync

    def test_disabled_auto_import_is_reported_as_skipped(self):
        result, sync = self._export(False)

        self.assertEqual(result["sub2api_import"]["action"], "skipped")
        sync.assert_not_called()

    def test_enabled_auto_import_runs_after_successful_export(self):
        result, sync = self._export(True)

        self.assertEqual(result["sub2api_import"]["action"], "created")
        sync.assert_called_once()

    def test_auto_import_failure_does_not_fail_cpa_export(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_path = Path(temp_dir.name) / "xai-user@example.com.json"

        def fake_mint(**kwargs):
            output_path.write_text("{}", encoding="utf-8")
            return {"ok": True, "path": str(output_path)}

        with patch("cpa_xai.mint_and_export", side_effect=fake_mint), patch(
            "sub2api_admin.sync_cpa_account", side_effect=RuntimeError("service unavailable")
        ):
            result = cpa_export.export_cpa_xai_for_account(
                "user@example.com",
                "password",
                config={
                    "cpa_export_enabled": True,
                    "cpa_auth_dir": temp_dir.name,
                    "sub2api_auto_import": True,
                },
                log_callback=lambda _message: None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["sub2api_import"]["action"], "error")


if __name__ == "__main__":
    unittest.main()
