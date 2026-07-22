import json
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import cpa_export
import sub2api_admin


class FakeClient:
    def __init__(self, accounts=None, details=None):
        self.accounts = accounts or []
        self.details = details or {}
        self.created = []
        self.updated = []
        self.list_calls = 0

    def list_accounts(self):
        self.list_calls += 1
        return self.accounts

    def get_account(self, account_id):
        detail = self.details[account_id]
        if isinstance(detail, list):
            if len(detail) > 1:
                return detail.pop(0)
            return detail[0]
        return detail

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
            "sub2api_preflight_enabled": False,
            "sub2api_readiness_timeout_sec": 0,
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

        self.assertEqual(result, {
            "ok": True,
            "action": "created",
            "account_id": 77,
            "preflight": {"state": "disabled", "status_code": None},
            "readiness": {
                "state": "pending",
                "status_code": None,
                "reason": "polling_disabled",
            },
        })
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

        self.assertEqual(result, {
            "ok": True,
            "action": "updated",
            "account_id": 40,
            "preflight": {"state": "disabled", "status_code": None},
            "readiness": {
                "state": "pending",
                "status_code": None,
                "reason": "polling_disabled",
            },
        })
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

    def test_classifies_known_and_unexpected_readiness_statuses(self):
        expected = {
            200: "ready",
            402: "payment_required",
            403: "forbidden",
            429: "rate_limited",
            503: "unexpected",
        }
        config = {"sub2api_readiness_timeout_sec": 1, "sub2api_readiness_poll_sec": 0.01}
        for status_code, state in expected.items():
            with self.subTest(status_code=status_code):
                client = FakeClient(details={1: {
                    "extra": {"grok_usage_snapshot": {
                        "status_code": status_code,
                        "updated_at": "2026-07-22T08:00:00Z",
                    }}
                }})
                readiness = sub2api_admin.wait_for_account_readiness(client, 1, config)
                self.assertEqual(readiness, {"state": state, "status_code": status_code})

    def test_upsert_waits_for_snapshot_newer_than_existing_credentials(self):
        old_snapshot = {
            "extra": {"grok_usage_snapshot": {
                "status_code": 403,
                "updated_at": "2026-07-22T08:00:00Z",
            }},
            "credentials": {"model_mapping": {"grok": "grok-4"}},
        }
        fresh_snapshot = {
            "extra": {"grok_usage_snapshot": {
                "status_code": 200,
                "updated_at": "2026-07-22T08:00:02Z",
            }},
            "credentials": {},
        }
        client = FakeClient(
            accounts=[{"id": 40, "name": "user@example.com"}],
            details={40: [old_snapshot, old_snapshot, fresh_snapshot]},
        )
        config = {
            **self.config,
            "sub2api_readiness_timeout_sec": 1,
            "sub2api_readiness_poll_sec": 0.01,
        }

        with patch("sub2api_admin.time.sleep", return_value=None):
            result = sub2api_admin.sync_cpa_account(self.cpa_path, config, client=client)

        self.assertEqual(result["readiness"], {"state": "ready", "status_code": 200})

    def test_readiness_timeout_returns_pending(self):
        client = FakeClient(details={1: {"extra": {}}})
        config = {"sub2api_readiness_timeout_sec": 1, "sub2api_readiness_poll_sec": 0.1}

        with patch("sub2api_admin.time.monotonic", side_effect=[10, 12]):
            readiness = sub2api_admin.wait_for_account_readiness(client, 1, config)

        self.assertEqual(readiness, {
            "state": "pending",
            "status_code": None,
            "reason": "timeout",
        })

    def test_readiness_get_failure_does_not_fail_import(self):
        client = FakeClient()
        config = {"sub2api_readiness_timeout_sec": 1, "sub2api_readiness_poll_sec": 0.1}

        readiness = sub2api_admin.wait_for_account_readiness(client, 404, config)

        self.assertEqual(readiness["state"], "pending")
        self.assertEqual(readiness["reason"], "readiness_check_failed")

    def test_preflight_402_skips_sub2api_and_moves_file_to_rejected(self):
        client = FakeClient()
        config = {
            **self.config,
            "sub2api_preflight_enabled": True,
            "sub2api_rejected_dir": str(Path(self.temp_dir.name) / "rejected"),
        }
        probe_result = {
            "ok": False,
            "status": 402,
            "error": json.dumps({
                "code": "personal-team-blocked:spending-limit",
                "error": "You have run out of credits",
            }),
        }

        with patch("cpa_xai.probe.probe_mini_response", return_value=probe_result):
            result = sub2api_admin.sync_cpa_account(self.cpa_path, config, client=client)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "preflight_rejected")
        self.assertEqual(result["preflight"]["status_code"], 402)
        self.assertEqual(result["preflight"]["attempt_count"], 1)
        self.assertEqual(
            result["preflight"]["code"], "personal-team-blocked:spending-limit"
        )
        self.assertFalse(self.cpa_path.exists())
        self.assertTrue(Path(result["rejected_path"]).is_file())
        self.assertEqual(client.list_calls, 0)
        self.assertEqual(client.created, [])
        self.assertEqual(client.updated, [])

    def test_rejected_move_does_not_overwrite_existing_file(self):
        rejected_dir = Path(self.temp_dir.name) / "rejected"
        rejected_dir.mkdir()
        existing = rejected_dir / self.cpa_path.name
        existing.write_text("existing", encoding="utf-8")

        destination = sub2api_admin.move_rejected_cpa(
            self.cpa_path,
            {"sub2api_rejected_dir": str(rejected_dir)},
        )

        self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
        self.assertEqual(destination.name, "xai-user@example.com-1.json")
        self.assertTrue(destination.is_file())

    def test_preflight_200_imports_on_first_attempt(self):
        client = FakeClient()
        config = {
            **self.config,
            "sub2api_preflight_enabled": True,
            "sub2api_readiness_timeout_sec": 0,
        }
        with patch(
            "cpa_xai.probe.probe_mini_response",
            return_value={"ok": True, "status": 200},
        ) as probe:
            result = sub2api_admin.sync_cpa_account(self.cpa_path, config, client=client)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["preflight"]["state"], "passed")
        self.assertEqual(result["preflight"]["attempt_count"], 1)
        self.assertEqual(len(client.created), 1)
        probe.assert_called_once()

    def test_preflight_retries_transient_statuses_until_200(self):
        client = FakeClient()
        config = {
            **self.config,
            "sub2api_preflight_enabled": True,
            "sub2api_preflight_attempts": 3,
            "sub2api_preflight_retry_delay_sec": 5,
            "sub2api_readiness_timeout_sec": 0,
        }
        responses = [
            {"ok": False, "status": 403, "error": "forbidden"},
            {"ok": False, "status": 429, "error": "rate limited"},
            {"ok": True, "status": 200},
        ]
        with patch(
            "cpa_xai.probe.probe_mini_response", side_effect=responses
        ) as probe, patch("sub2api_admin.time.sleep") as sleep:
            result = sub2api_admin.sync_cpa_account(self.cpa_path, config, client=client)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["preflight"]["state"], "passed")
        self.assertEqual(result["preflight"]["attempt_count"], 3)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(5.0)

    def test_preflight_rejects_after_transient_attempts_exhausted(self):
        client = FakeClient()
        config = {
            **self.config,
            "sub2api_preflight_enabled": True,
            "sub2api_preflight_attempts": 3,
            "sub2api_preflight_retry_delay_sec": 0,
            "sub2api_rejected_dir": str(Path(self.temp_dir.name) / "rejected"),
        }
        responses = [
            {"ok": False, "status": 403, "error": "forbidden"},
            {"ok": False, "status": 0, "error": "timeout"},
            {"ok": False, "status": 503, "error": "unavailable"},
        ]
        with patch("cpa_xai.probe.probe_mini_response", side_effect=responses):
            result = sub2api_admin.sync_cpa_account(self.cpa_path, config, client=client)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "preflight_rejected")
        self.assertEqual(result["preflight"]["state"], "failed")
        self.assertEqual(result["preflight"]["attempt_count"], 3)
        self.assertEqual(result["preflight"]["last_status_code"], 503)
        self.assertEqual(client.list_calls, 0)
        self.assertTrue(Path(result["rejected_path"]).is_file())

    def test_preflight_rejects_non_transient_status_without_retry(self):
        client = FakeClient()
        config = {
            **self.config,
            "sub2api_preflight_enabled": True,
            "sub2api_preflight_attempts": 3,
            "sub2api_rejected_dir": str(Path(self.temp_dir.name) / "rejected"),
        }
        with patch(
            "cpa_xai.probe.probe_mini_response",
            return_value={"ok": False, "status": 401, "error": "unauthorized"},
        ) as probe:
            result = sub2api_admin.sync_cpa_account(self.cpa_path, config, client=client)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["preflight"]["last_status_code"], 401)
        self.assertEqual(result["preflight"]["attempt_count"], 1)
        probe.assert_called_once()
        self.assertEqual(client.list_calls, 0)


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

    def test_usage_limit_skip_prevents_hotload_and_server_upload(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_path = Path(temp_dir.name) / "xai-user@example.com.json"
        rejected_path = Path(temp_dir.name) / "rejected" / output_path.name
        rejected_path.parent.mkdir()

        def fake_mint(**kwargs):
            output_path.write_text("{}", encoding="utf-8")
            return {"ok": True, "path": str(output_path)}

        def fake_sync(path, config):
            rejected_path.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
            output_path.unlink()
            return {
                "ok": True,
                "action": "skipped",
                "reason": "preflight_rejected",
                "account_id": None,
                "preflight": {"state": "usage_limit", "status_code": 402},
                "rejected_path": str(rejected_path),
            }

        upload = Mock()
        fake_grok_module = types.SimpleNamespace(upload_to_cpa_server=upload)
        with patch("cpa_xai.mint_and_export", side_effect=fake_mint), patch(
            "sub2api_admin.sync_cpa_account", side_effect=fake_sync
        ), patch("cpa_export.shutil.copy2") as copy, patch.dict(
            sys.modules, {"grok_register_ttk": fake_grok_module}
        ):
            result = cpa_export.export_cpa_xai_for_account(
                "user@example.com",
                "password",
                config={
                    "cpa_export_enabled": True,
                    "cpa_auth_dir": temp_dir.name,
                    "cpa_copy_to_hotload": True,
                    "cpa_hotload_dir": str(Path(temp_dir.name) / "hotload"),
                    "cpa_server_host": "server.example",
                    "sub2api_auto_import": True,
                },
                log_callback=lambda _message: None,
            )

        self.assertEqual(result["path"], str(rejected_path))
        self.assertEqual(result["sub2api_import"]["reason"], "preflight_rejected")
        copy.assert_not_called()
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
