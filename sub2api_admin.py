"""Sub2API admin integration for Grok CPA credential files."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import requests


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.json"
DEFAULT_GROUP_IDS = [5]
DEFAULT_CONCURRENCY = 1
DEFAULT_PRIORITY = 1
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_READINESS_TIMEOUT_SEC = 30
DEFAULT_READINESS_POLL_SEC = 2
DEFAULT_PREFLIGHT_TIMEOUT_SEC = 30
DEFAULT_PREFLIGHT_ATTEMPTS = 3
DEFAULT_PREFLIGHT_RETRY_DELAY_SEC = 5
DEFAULT_REJECTED_DIR = "cpa_rejected"
DEFAULT_SCOPE = "openid profile email offline_access grok-cli:access api:access"
DEFAULT_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
DEFAULT_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
SECRET_KEY_RE = re.compile(r"(token|secret|password|cookie|key)", re.I)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ValueError(f"Config file not found: {config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read config file {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"Config file must contain a JSON object: {config_path}")
    return config


def redact(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {item_key: redact(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if key and SECRET_KEY_RE.search(key):
        return "***redacted***"
    if isinstance(value, str) and len(value) > 140:
        return value[:137] + "..."
    return value


def _response_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


class Sub2APIClient:
    def __init__(self, base_url: str, admin_api_key: str, timeout: float = DEFAULT_TIMEOUT_SEC):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.admin_api_key = str(admin_api_key or "").strip()
        self.timeout = float(timeout or DEFAULT_TIMEOUT_SEC)
        if not self.base_url:
            raise ValueError("sub2api_base_url is required in config.json")
        if not self.admin_api_key:
            raise ValueError("sub2api_admin_api_key is required in config.json")
        if self.timeout <= 0:
            raise ValueError("sub2api_timeout_sec must be greater than zero")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Sub2APIClient":
        return cls(
            base_url=config.get("sub2api_base_url", ""),
            admin_api_key=config.get("sub2api_admin_api_key", ""),
            timeout=config.get("sub2api_timeout_sec", DEFAULT_TIMEOUT_SEC),
        )

    @property
    def headers(self) -> dict[str, str]:
        return {"x-api-key": self.admin_api_key, "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self.headers,
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Sub2API returned invalid JSON for {method} {path}") from exc

    def list_accounts(self, page_size: int = 200) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request(
                "GET",
                "/api/v1/admin/accounts",
                params={"page": page, "page_size": page_size},
            )
            data = _response_data(payload)
            if isinstance(data, list):
                items = data
                total = len(data)
            elif isinstance(data, dict):
                items = data.get("items") or []
                total = data.get("total") or data.get("total_count")
            else:
                raise ValueError("Sub2API account list has an unexpected response shape")
            if not isinstance(items, list):
                raise ValueError("Sub2API account list items must be an array")
            accounts.extend(item for item in items if isinstance(item, dict))
            if not items or (total is not None and len(accounts) >= int(total)) or len(items) < page_size:
                break
            page += 1
        return accounts

    def get_account(self, account_id: Any) -> dict[str, Any]:
        data = _response_data(self._request("GET", f"/api/v1/admin/accounts/{account_id}"))
        if not isinstance(data, dict):
            raise ValueError("Sub2API account detail has an unexpected response shape")
        return data

    def create_account(self, body: dict[str, Any]) -> Any:
        return self._request("POST", "/api/v1/admin/accounts", json=body)

    def update_credentials(self, account_id: Any, credentials: dict[str, Any]) -> Any:
        return self._request(
            "PUT",
            f"/api/v1/admin/accounts/{account_id}",
            json={"credentials": credentials},
        )


def _configured_group_ids(config: dict[str, Any]) -> list[int]:
    raw = config.get("sub2api_group_ids", DEFAULT_GROUP_IDS)
    if not isinstance(raw, list) or not raw:
        raise ValueError("sub2api_group_ids must be a non-empty JSON array")
    try:
        return [int(group_id) for group_id in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError("sub2api_group_ids must contain integer IDs") from exc


def _read_cpa_payload(cpa_path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(cpa_path).expanduser()
    try:
        cpa = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read CPA file {path}: {exc}") from exc
    if not isinstance(cpa, dict):
        raise ValueError(f"CPA file must contain a JSON object: {path}")
    return path, cpa


def build_grok_account_from_cpa(
    cpa_path: str | Path,
    config: dict[str, Any],
    *,
    name: str | None = None,
) -> dict[str, Any]:
    path, cpa = _read_cpa_payload(cpa_path)

    email = str(cpa.get("email") or "").strip()
    account_name = str(name or email or path.stem.removeprefix("xai-")).strip()
    refresh_token = str(cpa.get("refresh_token") or "").strip()
    if not account_name:
        raise ValueError(f"Cannot determine account name from {path}")
    if not refresh_token:
        raise ValueError(f"{path} does not contain refresh_token")

    credentials: dict[str, Any] = {
        "refresh_token": refresh_token,
        "base_url": cpa.get("base_url") or DEFAULT_BASE_URL,
        "client_id": cpa.get("client_id") or DEFAULT_CLIENT_ID,
        "scope": cpa.get("scope") or DEFAULT_SCOPE,
        "token_type": cpa.get("token_type") or "Bearer",
    }
    if email:
        credentials["email"] = email
    for source_key, destination_key in (
        ("access_token", "access_token"),
        ("id_token", "id_token"),
        ("sub", "sub"),
        ("team_id", "team_id"),
        ("expired", "expires_at"),
        ("token_endpoint", "token_endpoint"),
        ("redirect_uri", "redirect_uri"),
    ):
        value = cpa.get(source_key)
        if value not in (None, ""):
            credentials[destination_key] = value

    return {
        "name": account_name,
        "platform": "grok",
        "type": "oauth",
        "status": "active",
        "group_ids": _configured_group_ids(config),
        "concurrency": int(config.get("sub2api_concurrency", DEFAULT_CONCURRENCY)),
        "priority": int(config.get("sub2api_priority", DEFAULT_PRIORITY)),
        "credentials": credentials,
        "extra": {"source": "grok-auto-register", "cpa_file": path.name},
    }


def _account_id(account: dict[str, Any]) -> Any:
    return account.get("id") or account.get("account_id")


def _account_identities(account: dict[str, Any]) -> set[str]:
    credentials = account.get("credentials") or {}
    values = [account.get("name"), account.get("email")]
    if isinstance(credentials, dict):
        values.append(credentials.get("email"))
    return {str(value).strip().casefold() for value in values if str(value or "").strip()}


def _result_account_id(payload: Any) -> Any:
    data = _response_data(payload)
    return _account_id(data) if isinstance(data, dict) else None


def _usage_snapshot(account: dict[str, Any]) -> dict[str, Any]:
    extra = account.get("extra") or {}
    if not isinstance(extra, dict):
        return {}
    snapshot = extra.get("grok_usage_snapshot") or {}
    return snapshot if isinstance(snapshot, dict) else {}


def _snapshot_updated_at(account: dict[str, Any]) -> str:
    return str(_usage_snapshot(account).get("updated_at") or "").strip()


def _classify_readiness(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    raw_status = snapshot.get("status_code")
    if raw_status in (None, ""):
        return None
    try:
        status_code = int(raw_status)
    except (TypeError, ValueError):
        return {"state": "unexpected", "status_code": raw_status}
    states = {
        200: "ready",
        402: "payment_required",
        403: "forbidden",
        429: "rate_limited",
    }
    return {"state": states.get(status_code, "unexpected"), "status_code": status_code}


def _safe_probe_error(raw_error: Any) -> tuple[str, str]:
    text = str(raw_error or "").strip()[:800]
    if not text:
        return "", ""
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return "", text[:500]
    if not isinstance(payload, dict):
        return "", text[:500]
    code = str(payload.get("code") or "").strip()[:200]
    message = str(payload.get("error") or payload.get("message") or "").strip()[:500]
    return code, message


def preflight_cpa_account(cpa_path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    if not config.get("sub2api_preflight_enabled", True):
        return {"state": "disabled", "status_code": None}
    _, cpa = _read_cpa_payload(cpa_path)
    access_token = str(cpa.get("access_token") or "").strip()
    if not access_token:
        return {
            "state": "failed",
            "status_code": None,
            "last_status_code": None,
            "attempt_count": 0,
            "attempts": [],
            "reason": "missing_access_token",
        }
    try:
        timeout = float(
            config.get("sub2api_preflight_timeout_sec", DEFAULT_PREFLIGHT_TIMEOUT_SEC)
        )
        max_attempts = int(
            config.get("sub2api_preflight_attempts", DEFAULT_PREFLIGHT_ATTEMPTS)
        )
        retry_delay = float(
            config.get(
                "sub2api_preflight_retry_delay_sec", DEFAULT_PREFLIGHT_RETRY_DELAY_SEC
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Sub2API preflight timeout, attempts, and delay must be numbers") from exc
    if timeout <= 0:
        raise ValueError("sub2api_preflight_timeout_sec must be greater than zero")
    if max_attempts <= 0:
        raise ValueError("sub2api_preflight_attempts must be greater than zero")
    if retry_delay < 0:
        raise ValueError("sub2api_preflight_retry_delay_sec cannot be negative")

    from cpa_xai.probe import probe_mini_response

    transient_statuses = {0, 403, 408, 425, 429, 500, 502, 503, 504}
    attempts: list[dict[str, Any]] = []
    for attempt_number in range(1, max_attempts + 1):
        try:
            probe = probe_mini_response(
                access_token,
                base_url=str(cpa.get("base_url") or DEFAULT_BASE_URL),
                timeout=timeout,
                proxy=str(config.get("cpa_proxy") or config.get("proxy") or "").strip()
                or None,
            )
        except Exception:  # noqa: BLE001
            probe = {"ok": False, "status": 0, "error": "probe exception"}
        raw_status = probe.get("status")
        try:
            status_code = int(raw_status) if raw_status not in (None, "") else 0
        except (TypeError, ValueError):
            status_code = 0
        code, _ = _safe_probe_error(probe.get("error"))
        attempt_state = "passed" if status_code == 200 and probe.get("ok") else "failed"
        attempt_result: dict[str, Any] = {
            "attempt": attempt_number,
            "status_code": status_code,
            "state": attempt_state,
        }
        if code:
            attempt_result["code"] = code
        attempts.append(attempt_result)

        if attempt_state == "passed":
            return {
                "state": "passed",
                "status_code": 200,
                "attempt_count": attempt_number,
                "attempts": attempts,
            }
        if status_code == 402:
            result: dict[str, Any] = {
                "state": "usage_limit",
                "status_code": 402,
                "last_status_code": 402,
                "attempt_count": attempt_number,
                "attempts": attempts,
            }
            if code:
                result["code"] = code
            return result
        if status_code not in transient_statuses or attempt_number >= max_attempts:
            return {
                "state": "failed",
                "status_code": status_code,
                "last_status_code": status_code,
                "attempt_count": attempt_number,
                "attempts": attempts,
            }
        time.sleep(retry_delay)

    raise RuntimeError("Sub2API preflight loop ended unexpectedly")


def move_rejected_cpa(cpa_path: str | Path, config: dict[str, Any]) -> Path:
    source = Path(cpa_path).expanduser().resolve()
    rejected_raw = str(config.get("sub2api_rejected_dir") or DEFAULT_REJECTED_DIR).strip()
    rejected_dir = Path(rejected_raw).expanduser()
    if not rejected_dir.is_absolute():
        rejected_dir = (PROJECT_DIR / rejected_dir).resolve()
    rejected_dir.mkdir(parents=True, exist_ok=True)
    destination = rejected_dir / source.name
    suffix = 1
    while destination.exists():
        destination = rejected_dir / f"{source.stem}-{suffix}{source.suffix}"
        suffix += 1
    shutil.move(str(source), str(destination))
    destination.chmod(0o600)
    return destination


def wait_for_account_readiness(
    client: Sub2APIClient,
    account_id: Any,
    config: dict[str, Any],
    *,
    previous_snapshot_updated_at: str = "",
) -> dict[str, Any]:
    try:
        timeout = float(
            config.get("sub2api_readiness_timeout_sec", DEFAULT_READINESS_TIMEOUT_SEC)
        )
        poll_interval = float(
            config.get("sub2api_readiness_poll_sec", DEFAULT_READINESS_POLL_SEC)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Sub2API readiness timeout and poll interval must be numbers") from exc
    if timeout < 0:
        raise ValueError("sub2api_readiness_timeout_sec cannot be negative")
    if poll_interval <= 0:
        raise ValueError("sub2api_readiness_poll_sec must be greater than zero")
    if account_id is None:
        return {"state": "pending", "status_code": None, "reason": "missing_account_id"}
    if timeout == 0:
        return {"state": "pending", "status_code": None, "reason": "polling_disabled"}

    deadline = time.monotonic() + timeout
    while True:
        try:
            account = client.get_account(account_id)
        except Exception as exc:  # noqa: BLE001
            return {
                "state": "pending",
                "status_code": None,
                "reason": "readiness_check_failed",
                "error": str(exc),
            }
        snapshot = _usage_snapshot(account)
        snapshot_updated_at = str(snapshot.get("updated_at") or "").strip()
        is_fresh = not previous_snapshot_updated_at or (
            snapshot_updated_at and snapshot_updated_at != previous_snapshot_updated_at
        )
        readiness = _classify_readiness(snapshot) if is_fresh else None
        if readiness is not None:
            return readiness

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"state": "pending", "status_code": None, "reason": "timeout"}
        time.sleep(min(poll_interval, remaining))


def sync_cpa_account(
    cpa_path: str | Path,
    config: dict[str, Any],
    *,
    name: str | None = None,
    client: Sub2APIClient | None = None,
) -> dict[str, Any]:
    body = build_grok_account_from_cpa(cpa_path, config, name=name)
    preflight = preflight_cpa_account(cpa_path, config)
    if preflight.get("state") in {"usage_limit", "failed"}:
        rejected_path = move_rejected_cpa(cpa_path, config)
        return {
            "ok": True,
            "action": "skipped",
            "reason": "preflight_rejected",
            "account_id": None,
            "preflight": preflight,
            "rejected_path": str(rejected_path),
        }

    api = client or Sub2APIClient.from_config(config)
    identity = body["name"].casefold()
    email = str(body["credentials"].get("email") or "").casefold()
    targets = {value for value in (identity, email) if value}
    matches = [account for account in api.list_accounts() if targets & _account_identities(account)]

    if len(matches) > 1:
        ids = [_account_id(account) for account in matches]
        raise ValueError(f"Multiple Sub2API accounts match {body['name']!r}; conflicting IDs: {ids}")
    if not matches:
        response = api.create_account(body)
        account_id = _result_account_id(response)
        return {
            "ok": True,
            "action": "created",
            "account_id": account_id,
            "preflight": preflight,
            "readiness": wait_for_account_readiness(api, account_id, config),
        }

    account_id = _account_id(matches[0])
    if account_id is None:
        raise ValueError(f"Matching Sub2API account {body['name']!r} has no ID")
    existing = api.get_account(account_id)
    previous_snapshot_updated_at = _snapshot_updated_at(existing)
    existing_credentials = existing.get("credentials") or {}
    if not isinstance(existing_credentials, dict):
        existing_credentials = {}
    merged_credentials = {**existing_credentials, **body["credentials"]}
    response = api.update_credentials(account_id, merged_credentials)
    result_account_id = _result_account_id(response) or account_id
    return {
        "ok": True,
        "action": "updated",
        "account_id": result_account_id,
        "preflight": preflight,
        "readiness": wait_for_account_readiness(
            api,
            result_account_id,
            config,
            previous_snapshot_updated_at=previous_snapshot_updated_at,
        ),
    }


def is_grok_account(account: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(account.get(key, "")) for key in ("name", "platform", "type", "status", "notes")
    )
    return bool(re.search(r"(grok|xai|x\.ai)", haystack, re.I))


def summarize_account(account: dict[str, Any]) -> dict[str, Any]:
    credentials = account.get("credentials") or {}
    return {
        "id": _account_id(account),
        "name": account.get("name"),
        "platform": account.get("platform"),
        "type": account.get("type"),
        "status": account.get("status"),
        "group_ids": account.get("group_ids") or account.get("groupIds") or account.get("groups"),
        "concurrency": account.get("concurrency"),
        "priority": account.get("priority"),
        "credential_keys": sorted(credentials.keys()) if isinstance(credentials, dict) else [],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sub2API admin helper for Grok CPA accounts")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.json")
    subcommands = parser.add_subparsers(dest="command", required=True)

    list_command = subcommands.add_parser("list-grok", help="List Grok-like Sub2API accounts")
    list_command.add_argument("--limit", type=int, default=20)

    import_command = subcommands.add_parser("import-cpa", help="Create or update from CPA JSON")
    import_command.add_argument("cpa_json")
    import_command.add_argument("--name", default="")
    import_command.add_argument("--apply", action="store_true", help="Apply the upsert to Sub2API")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "list-grok":
        accounts = Sub2APIClient.from_config(config).list_accounts()
        grok_accounts = [account for account in accounts if is_grok_account(account)]
        print(f"total_accounts={len(accounts)}")
        print(f"grok_accounts={len(grok_accounts)}")
        for account in grok_accounts[: args.limit]:
            print(json.dumps(summarize_account(account), ensure_ascii=False))
        return 0

    if not args.apply:
        body = build_grok_account_from_cpa(args.cpa_json, config, name=args.name or None)
        print(json.dumps(redact(body), ensure_ascii=False, indent=2))
        return 0
    result = sync_cpa_account(args.cpa_json, config, name=args.name or None)
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
