"""Test ProxyScrape filtering, pagination, probing, and browser assignment."""

import unittest
from unittest.mock import patch

import browser_runtime
from proxyscrape_pool import ProxyScrapeError, ProxyScrapePool


def candidate(proxy, ip, country="DE", timeout=100, average=200, uptime=99):
    return {
        "alive": True,
        "protocol": "http",
        "ssl": True,
        "anonymity": "elite",
        "timeout": timeout,
        "average_timeout": average,
        "uptime": uptime,
        "proxy": proxy,
        "ip": ip,
        "ip_data": {"countryCode": country},
    }


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class ProxyScrapePoolTests(unittest.TestCase):
    def test_fetch_all_follows_pagination(self):
        pages = [
            Response({"proxies": [{"ip": "one"}], "nextpage": True}),
            Response({"proxies": [{"ip": "two"}], "nextpage": False}),
        ]
        pool = ProxyScrapePool()
        with patch("proxyscrape_pool.requests.get", side_effect=pages) as mocked:
            result = pool._fetch_all()
        self.assertEqual([item["ip"] for item in result], ["one", "two"])
        self.assertEqual(mocked.call_args_list[1].kwargs["params"]["skip"], 1)

    def test_filter_requires_quality_and_configured_country(self):
        pool = ProxyScrapePool(country_codes=["de"])
        self.assertTrue(pool._eligible(candidate("http://1.1.1.1:80", "1.1.1.1")))
        self.assertFalse(pool._eligible(candidate("http://2.2.2.2:80", "2.2.2.2", country="NL")))
        self.assertFalse(pool._eligible(candidate("http://3.3.3.3:80", "3.3.3.3", timeout=1001)))
        self.assertFalse(pool._eligible(candidate("http://4.4.4.4:80", "4.4.4.4", uptime=89)))

    def test_select_uses_fastest_probe_and_never_reuses_ip(self):
        first = candidate("http://1.1.1.1:80", "1.1.1.1")
        second = candidate("http://2.2.2.2:80", "2.2.2.2")
        pool = ProxyScrapePool()
        pool._candidates = [first, second]
        pool._fetched_at = __import__("time").monotonic()
        outcomes = {
            first["proxy"]: (True, 300, first["proxy"], first["ip"], 200),
            second["proxy"]: (True, 100, second["proxy"], second["ip"], 302),
        }
        with patch.object(pool, "_probe", side_effect=lambda item: outcomes[item["proxy"]]):
            self.assertEqual(pool.select(), second["proxy"])
            self.assertEqual(pool.select(), first["proxy"])

    def test_select_fails_closed_when_all_probes_fail(self):
        item = candidate("http://1.1.1.1:80", "1.1.1.1")
        pool = ProxyScrapePool()
        pool._candidates = [item]
        pool._fetched_at = __import__("time").monotonic()
        with patch.object(pool, "_probe", return_value=(False, 10, item["proxy"], item["ip"], 403)):
            with self.assertRaisesRegex(ProxyScrapeError, "No ProxyScrape candidate"):
                pool.select()


class BrowserRuntimeProxyScrapeTests(unittest.TestCase):
    def tearDown(self):
        browser_runtime.configure_runtime({"proxy_mode": "manual", "proxy": ""})
        browser_runtime.reset_proxy_selection()

    def test_assignment_is_sticky_per_account_and_browser_only(self):
        config = {
            "proxy_mode": "proxyscrape",
            "proxy": "http://manual.invalid:80",
            "proxyscrape_country_codes": [],
        }
        fake_pool = unittest.mock.Mock()
        fake_pool.select.side_effect = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        browser_runtime.configure_runtime(config)
        with patch("browser_runtime.ProxyScrapePool", return_value=fake_pool):
            browser_runtime.reset_proxy_selection()
            self.assertEqual(browser_runtime.prepare_account_proxy(0), "http://1.1.1.1:80")
            self.assertEqual(browser_runtime.prepare_account_proxy(0), "http://1.1.1.1:80")
            self.assertEqual(browser_runtime.get_proxies(), {})
            self.assertEqual(browser_runtime.prepare_account_proxy(1), "http://2.2.2.2:80")
        self.assertEqual(fake_pool.select.call_count, 2)

    def test_rejected_proxy_is_replaced_for_same_account(self):
        browser_runtime.configure_runtime(
            {"proxy_mode": "proxyscrape", "proxy": "", "proxyscrape_country_codes": []}
        )
        fake_pool = unittest.mock.Mock()
        fake_pool.select.side_effect = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        with patch("browser_runtime.ProxyScrapePool", return_value=fake_pool):
            browser_runtime.reset_proxy_selection()
            browser_runtime.prepare_account_proxy(0)
            browser_runtime.reject_current_browser_proxy()
            self.assertEqual(browser_runtime.prepare_account_proxy(0), "http://2.2.2.2:80")
        fake_pool.reject.assert_called_once_with("http://1.1.1.1:80")


if __name__ == "__main__":
    unittest.main()
