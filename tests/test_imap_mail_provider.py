"""Test the read-only IMAP catch-all email provider."""

import unittest
from unittest.mock import patch

import app_config
import mail_service


MESSAGE_OTHER = b"""From: no-reply@x.ai
To: other@example.com
Subject: OLD-111 xAI
Content-Type: text/plain; charset=utf-8

OLD-111
"""

MESSAGE_TARGET = b"""From: no-reply@x.ai
To: Inbox <putra-pratama-grok@amazingnusantararun.com>
Subject: ABC-123 xAI
Content-Type: multipart/alternative; boundary=part

--part
Content-Type: text/plain; charset=utf-8

Your verification code is ABC-123
--part
Content-Type: text/html; charset=utf-8

<p>Your verification code is <b>ABC-123</b></p>
--part--
"""

MESSAGE_TARGET_NEW_SUBJECT = b"""From: no-reply@x.ai
To: Inbox <putra-pratama-grok@amazingnusantararun.com>
Subject: SpaceXAI confirmation code: MJI-2BK
Content-Type: text/html; charset=utf-8

<style>.per-100 { width: 100%; }</style>
<p>Confirm your email address to continue.</p>
"""


class FakeIMAP:
    def __init__(self, messages=None, uidvalidity=77):
        self.messages = messages or {}
        self.uidvalidity = uidvalidity
        self.calls = []

    def login(self, user, password):
        self.calls.append(("login", user, password))
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def response(self, name):
        self.calls.append(("response", name))
        return name, [str(self.uidvalidity).encode()]

    def uid(self, command, *args):
        self.calls.append(("uid", command, args))
        if command == "search":
            return "OK", [b" ".join(str(uid).encode() for uid in self.messages)]
        if command == "fetch":
            uid = int(args[0])
            return "OK", [(b"BODY[]", self.messages[uid])]
        raise AssertionError(command)

    def close(self):
        self.calls.append(("close",))
        return "OK", []

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", []


class ImapConfigTests(unittest.TestCase):
    def test_defaults_and_active_provider_validation(self):
        config = app_config.validate_config_structure({})
        self.assertEqual(config["imap_port"], 993)
        self.assertTrue(config["imap_ssl"])
        self.assertEqual(config["imap_folder"], "INBOX")

        with self.assertRaises(app_config.ConfigError):
            app_config.validate_run_requirements({"email_provider": "imap"})

        config = app_config.validate_run_requirements({
            "email_provider": "imap",
            "imap_host": "imap.example.com",
            "imap_user": "inbox@example.com",
            "imap_password": "secret",
            "imap_folder": "INBOX",
            "imap_address_domain": "Example.COM",
            "imap_address_suffix": "-GROK",
        })
        self.assertEqual(config["imap_address_domain"], "example.com")
        self.assertEqual(config["imap_address_suffix"], "-grok")


class ImapProviderTests(unittest.TestCase):
    def setUp(self):
        self.original_config = mail_service.config
        self.original_aliases = set(mail_service._imap_aliases_in_run)
        mail_service.config = {
            "email_provider": "imap",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "imap_ssl": True,
            "imap_user": "inbox@example.com",
            "imap_password": "secret-value",
            "imap_folder": "INBOX",
            "imap_address_domain": "amazingnusantararun.com",
            "imap_address_suffix": "-grok",
        }
        mail_service._imap_aliases_in_run.clear()

    def tearDown(self):
        mail_service.config = self.original_config
        mail_service._imap_aliases_in_run.clear()
        mail_service._imap_aliases_in_run.update(self.original_aliases)

    def test_human_alias_ends_with_required_suffix(self):
        with patch.object(mail_service.secrets, "choice", side_effect=["putra", "pratama"]):
            address = mail_service.generate_imap_alias()
        self.assertEqual(address, "putra-pratama-grok@amazingnusantararun.com")

    def test_connect_uses_tls_login_and_readonly_folder(self):
        client = FakeIMAP()
        with patch.object(mail_service.imaplib, "IMAP4_SSL", return_value=client) as constructor:
            result = mail_service._imap_connect(readonly=True, timeout=12)
        self.assertIs(result, client)
        constructor.assert_called_once_with("imap.example.com", 993, timeout=12)
        self.assertIn(("select", "INBOX", True), client.calls)

    def test_snapshot_token_contains_uids_but_no_credentials(self):
        client = FakeIMAP({4: MESSAGE_OTHER, 9: MESSAGE_OTHER})
        with patch.object(mail_service, "_imap_connect", return_value=client), patch.object(
            mail_service, "generate_imap_alias", return_value="putra-pratama-grok@amazingnusantararun.com"
        ):
            address, token = mail_service.imap_get_email_and_token()
        self.assertEqual(address, "putra-pratama-grok@amazingnusantararun.com")
        self.assertEqual(token, "imap:v1:77:9")
        self.assertNotIn("secret-value", token)
        self.assertNotIn("inbox@example.com", token)

    def test_polling_uses_new_uids_peek_and_recipient_filter(self):
        client = FakeIMAP({11: MESSAGE_OTHER, 12: MESSAGE_TARGET})
        logs = []
        with patch.object(mail_service, "_imap_connect", return_value=client):
            code = mail_service.imap_get_oai_code(
                "imap:v1:77:10",
                "putra-pratama-grok@amazingnusantararun.com",
                timeout=5,
                poll_interval=0,
                log_callback=logs.append,
            )
        self.assertEqual(code, "ABC-123")
        search_calls = [call for call in client.calls if call[:2] == ("uid", "search")]
        self.assertIn(("uid", "search", (None, "UID", "11:*")), search_calls)
        fetch_calls = [call for call in client.calls if call[:2] == ("uid", "fetch")]
        self.assertTrue(all(call[2][1] == "(BODY.PEEK[])" for call in fetch_calls))
        self.assertFalse(any(call[0] == "store" for call in client.calls))

    def test_new_subject_code_wins_over_lowercase_css_token(self):
        client = FakeIMAP({12: MESSAGE_TARGET_NEW_SUBJECT})
        with patch.object(mail_service, "_imap_connect", return_value=client):
            code = mail_service.imap_get_oai_code(
                "imap:v1:77:10",
                "putra-pratama-grok@amazingnusantararun.com",
                timeout=5,
                poll_interval=0,
            )
        self.assertEqual(code, "MJI-2BK")

    def test_lowercase_css_token_is_not_a_generic_code(self):
        self.assertIsNone(mail_service.extract_verification_code("width: per-100"))

    def test_uidvalidity_change_fails_without_reading_messages(self):
        client = FakeIMAP({11: MESSAGE_TARGET}, uidvalidity=88)
        with patch.object(mail_service, "_imap_connect", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "UIDVALIDITY changed"):
                mail_service.imap_get_oai_code(
                    "imap:v1:77:10",
                    "putra-pratama-grok@amazingnusantararun.com",
                    timeout=5,
                    poll_interval=0,
                )
        self.assertFalse(any(call[:2] == ("uid", "fetch") for call in client.calls))

    def test_provider_dispatches_without_exposing_password(self):
        expected = ("putra-pratama-grok@amazingnusantararun.com", "imap:v1:77:10")
        with patch.object(mail_service, "imap_get_email_and_token", return_value=expected) as provider:
            self.assertEqual(mail_service.get_email_and_token(), expected)
        provider.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
