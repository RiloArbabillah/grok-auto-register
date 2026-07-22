"""Test OAuth device discovery, retries, polling, and errors."""

import json
import unittest
from unittest.mock import patch

from cpa_xai import oauth_device as oauth


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body.encode("utf-8")
        self.status = status
        self.headers = headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.body


class Opener:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
    def open(self, request, timeout=None):
        self.calls += 1
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class OAuthDeviceTests(unittest.TestCase):
    def test_discovery_success(self):
        payload = {"device_authorization_endpoint": "https://auth.x.ai/device", "token_endpoint": "https://auth.x.ai/token"}
        opener = Opener([Response(json.dumps(payload))])
        with patch.object(oauth, "_build_opener", return_value=opener):
            self.assertEqual(oauth.discover(retries=0)["token_endpoint"], payload["token_endpoint"])

    def test_discovery_cancelled_before_request(self):
        with self.assertRaisesRegex(oauth.OAuthDeviceError, "cancelled"):
            oauth.discover(cancel=lambda: True)

    def test_discovery_retries_transient_error(self):
        payload = {"device_authorization_endpoint": "https://auth.x.ai/device", "token_endpoint": "https://auth.x.ai/token"}
        opener = Opener([TimeoutError("slow"), Response(json.dumps(payload))])
        with patch.object(oauth, "_build_opener", return_value=opener), patch.object(oauth, "_sleep_with_cancel"):
            oauth.discover(retries=1)
        self.assertEqual(opener.calls, 2)

    def test_post_form_returns_non_json_body(self):
        opener = Opener([Response("not-json", status=502)])
        with patch.object(oauth, "_build_opener", return_value=opener):
            status, payload = oauth._post_form("https://auth.x.ai/token", {}, retries=0)
        self.assertEqual((status, payload), (502, "not-json"))

    def test_slow_down_increases_wait(self):
        responses = [
            (400, {"error": "slow_down"}),
            (200, {"access_token": "a", "refresh_token": "r"}),
        ]
        waits = []
        with patch.object(oauth, "_post_form", side_effect=responses), patch.object(oauth, "_sleep_with_cancel", side_effect=lambda seconds, cancel=None: waits.append(seconds)):
            result = oauth.poll_device_token("d", "https://auth.x.ai/token", interval=1, expires_in=60)
        self.assertEqual(result.refresh_token, "r")
        self.assertEqual(waits, [6])

    def test_device_code_429_respects_retry_after(self):
        success = {
            "device_code": "device",
            "user_code": "USER-CODE",
            "verification_uri": "https://accounts.x.ai/oauth2/device",
        }
        responses = [
            (429, {"error": "slow_down"}, {"retry-after": "7"}),
            (200, success, {}),
        ]
        waits = []
        logs = []
        discovery = {
            "device_authorization_endpoint": "https://auth.x.ai/device",
            "token_endpoint": "https://auth.x.ai/token",
        }
        with patch.object(oauth, "discover", return_value=discovery), \
             patch.object(oauth, "_post_form_details", side_effect=responses), \
             patch.object(oauth, "_sleep_with_cancel", side_effect=lambda seconds, cancel=None: waits.append(seconds)):
            session = oauth.request_device_code(rate_limit_attempts=4, log=logs.append)
        self.assertEqual(session.user_code, "USER-CODE")
        self.assertEqual(waits, [7])
        self.assertIn("retry 2/4 in 7s", logs[0])

    def test_device_code_429_uses_bounded_exponential_fallback(self):
        success = {"device_code": "device", "user_code": "CODE"}
        responses = [
            (429, {"error": "slow_down"}, {}),
            (429, {"error": "slow_down"}, {}),
            (200, success, {}),
        ]
        waits = []
        discovery = {
            "device_authorization_endpoint": "https://auth.x.ai/device",
            "token_endpoint": "https://auth.x.ai/token",
        }
        with patch.object(oauth, "discover", return_value=discovery), \
             patch.object(oauth, "_post_form_details", side_effect=responses), \
             patch.object(oauth, "_sleep_with_cancel", side_effect=lambda seconds, cancel=None: waits.append(seconds)):
            oauth.request_device_code(
                rate_limit_attempts=3,
                rate_limit_delay=60,
                rate_limit_max_delay=90,
            )
        self.assertEqual(waits, [60, 90])

    def test_device_code_stops_after_rate_limit_attempt_limit(self):
        discovery = {
            "device_authorization_endpoint": "https://auth.x.ai/device",
            "token_endpoint": "https://auth.x.ai/token",
        }
        limited = (429, {"error": "slow_down"}, {})
        with patch.object(oauth, "discover", return_value=discovery), \
             patch.object(oauth, "_post_form_details", side_effect=[limited, limited]), \
             patch.object(oauth, "_sleep_with_cancel") as sleep:
            with self.assertRaisesRegex(oauth.OAuthDeviceError, "HTTP 429"):
                oauth.request_device_code(rate_limit_attempts=2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
