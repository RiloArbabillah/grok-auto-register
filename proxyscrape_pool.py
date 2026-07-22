"""Select verified public HTTP proxies from the ProxyScrape v4 API."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import urllib.parse

from curl_cffi import requests


API_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get"
PROBE_URL = "https://accounts.x.ai/sign-up?redirect=grok-com"


class ProxyScrapeError(RuntimeError):
    pass


class ProxyScrapePool:
    def __init__(
        self,
        country_codes=None,
        log=None,
        cancel=None,
        cache_ttl=60.0,
        probe_timeout=8.0,
        max_probe_candidates=20,
        probe_workers=8,
    ):
        self.country_codes = {
            str(code).strip().upper() for code in (country_codes or []) if str(code).strip()
        }
        self.log = log or (lambda message: None)
        self.cancel = cancel or (lambda: False)
        self.cache_ttl = float(cache_ttl)
        self.probe_timeout = float(probe_timeout)
        self.max_probe_candidates = int(max_probe_candidates)
        self.probe_workers = int(probe_workers)
        self._candidates = []
        self._fetched_at = 0.0
        self._used_ips = set()
        self._rejected = set()
        self._lock = threading.Lock()

    def _raise_if_cancelled(self):
        if self.cancel():
            raise ProxyScrapeError("Proxy selection was cancelled")

    def _fetch_page(self, skip):
        params = {
            "request": "display_proxies",
            "proxy_format": "protocolipport",
            "format": "json",
            "limit": 2000,
            "skip": int(skip),
        }
        last_error = None
        for attempt in range(1, 4):
            self._raise_if_cancelled()
            try:
                response = requests.get(API_URL, params=params, timeout=20)
                if response.status_code != 200:
                    raise ProxyScrapeError("ProxyScrape API returned HTTP %s" % response.status_code)
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("proxies"), list):
                    raise ProxyScrapeError("ProxyScrape API returned an invalid JSON payload")
                return payload
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
        raise ProxyScrapeError("Unable to fetch ProxyScrape API: %s" % last_error)

    def _fetch_all(self):
        records = []
        skip = 0
        while True:
            payload = self._fetch_page(skip)
            page = payload["proxies"]
            records.extend(page)
            if not payload.get("nextpage") or not page:
                break
            next_skip = skip + len(page)
            if next_skip <= skip:
                raise ProxyScrapeError("ProxyScrape pagination did not advance")
            skip = next_skip
        return records

    def _eligible(self, item):
        if not isinstance(item, dict):
            return False
        ip_data = item.get("ip_data") if isinstance(item.get("ip_data"), dict) else {}
        country = str(ip_data.get("countryCode") or "").upper()
        try:
            return (
                item.get("alive") is True
                and str(item.get("protocol") or "").lower() == "http"
                and item.get("ssl") is True
                and str(item.get("anonymity") or "").lower() == "elite"
                and float(item.get("timeout")) <= 1000.0
                and float(item.get("average_timeout")) <= 1500.0
                and float(item.get("uptime")) >= 90.0
                and (not self.country_codes or country in self.country_codes)
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _identity(item):
        raw = str(item.get("proxy") or "").strip()
        parsed = urllib.parse.urlsplit(raw)
        return raw, str(item.get("ip") or parsed.hostname or "").strip()

    def _refresh(self, force=False):
        now = time.monotonic()
        if not force and self._candidates and now - self._fetched_at < self.cache_ttl:
            return
        records = self._fetch_all()
        candidates = [item for item in records if self._eligible(item)]
        candidates.sort(
            key=lambda item: (
                float(item.get("timeout") or 1e9),
                float(item.get("average_timeout") or 1e9),
                -float(item.get("uptime") or 0),
            )
        )
        self._candidates = candidates
        self._fetched_at = now
        self.log("[*] ProxyScrape candidates after quality filters: %s" % len(candidates))

    def _probe(self, item):
        proxy, ip = self._identity(item)
        started = time.monotonic()
        try:
            response = requests.get(
                PROBE_URL,
                proxies={"http": proxy, "https": proxy},
                timeout=self.probe_timeout,
                allow_redirects=True,
                impersonate="chrome120",
            )
            elapsed_ms = (time.monotonic() - started) * 1000.0
            ok = 200 <= int(response.status_code) < 400
            return ok, elapsed_ms, proxy, ip, int(response.status_code)
        except Exception:
            return False, (time.monotonic() - started) * 1000.0, proxy, ip, 0

    def _available(self):
        result = []
        for item in self._candidates:
            proxy, ip = self._identity(item)
            if proxy and ip and proxy not in self._rejected and ip not in self._used_ips:
                result.append(item)
        return result

    def select(self):
        with self._lock:
            self._raise_if_cancelled()
            self._refresh()
            available = self._available()
            if not available:
                self._refresh(force=True)
                available = self._available()
            batch = available[: self.max_probe_candidates]
            if not batch:
                raise ProxyScrapeError("No unused ProxyScrape candidates match the configured filters")

            results = []
            with ThreadPoolExecutor(max_workers=min(self.probe_workers, len(batch))) as executor:
                futures = [executor.submit(self._probe, item) for item in batch]
                for future in as_completed(futures):
                    self._raise_if_cancelled()
                    result = future.result()
                    if result[0]:
                        results.append(result)
                    else:
                        self._rejected.add(result[2])
            if not results:
                raise ProxyScrapeError("No ProxyScrape candidate could open the xAI signup page")

            _, elapsed_ms, proxy, ip, status = min(results, key=lambda result: result[1])
            self._used_ips.add(ip)
            self.log(
                "[*] Selected ProxyScrape proxy %s (probe %.0f ms, HTTP %s)"
                % (proxy, elapsed_ms, status)
            )
            return proxy

    def reject(self, proxy):
        value = str(proxy or "").strip()
        if value:
            with self._lock:
                self._rejected.add(value)
