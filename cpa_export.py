"""Optionally generate CPA xAI OIDC credentials after registration."""
from dataclasses import dataclass
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent
_DEFAULT_AUTH_DIR = _ROOT / "cpa_auths"


def _configured_cpa_proxy(config):
    cfg = config or {}
    explicit = str(cfg.get("cpa_proxy") or "").strip()
    if explicit:
        return explicit
    if str(cfg.get("proxy_mode", "manual") or "manual").lower() == "manual":
        return str(cfg.get("proxy") or "").strip()
    return ""


@dataclass(frozen=True)
class CpaExportSettings:
    enabled: bool
    auth_dir: Path
    hotload_dir: Optional[Path]
    copy_to_hotload: bool
    proxy: str
    headless: bool
    mint_timeout: float
    request_timeout: float
    poll_timeout: float
    device_code_attempts: int
    device_code_retry_delay: float
    device_code_max_retry_delay: float
    base_url: str
    force_standalone: bool
    cookie_inject: bool
    tools_dir: str

    @classmethod
    def from_config(cls, config):
        cfg = dict(config or {})
        auth_dir = Path(cfg.get("cpa_auth_dir") or _DEFAULT_AUTH_DIR).expanduser()
        if not auth_dir.is_absolute():
            auth_dir = (_ROOT / auth_dir).resolve()
        hotload_value = str(cfg.get("cpa_hotload_dir") or "").strip()
        hotload_dir = Path(hotload_value).expanduser() if hotload_value else None
        if hotload_dir is not None and not hotload_dir.is_absolute():
            hotload_dir = (_ROOT / hotload_dir).resolve()
        return cls(
            enabled=bool(cfg.get("cpa_export_enabled", True)),
            auth_dir=auth_dir,
            hotload_dir=hotload_dir,
            copy_to_hotload=bool(cfg.get("cpa_copy_to_hotload", False)),
            proxy=_configured_cpa_proxy(cfg),
            headless=bool(cfg.get("cpa_headless", False)),
            mint_timeout=float(cfg.get("cpa_mint_timeout_sec") or 300),
            request_timeout=float(cfg.get("cpa_oidc_request_timeout_sec") or 15),
            poll_timeout=float(cfg.get("cpa_oidc_poll_timeout_sec") or 15),
            device_code_attempts=int(cfg.get("cpa_device_code_attempts") or 4),
            device_code_retry_delay=float(cfg.get("cpa_device_code_retry_delay_sec") or 60),
            device_code_max_retry_delay=float(cfg.get("cpa_device_code_max_retry_delay_sec") or 300),
            base_url=str(cfg.get("cpa_base_url") or "https://cli-chat-proxy.grok.com/v1").strip(),
            force_standalone=bool(cfg.get("cpa_force_standalone", True)),
            cookie_inject=bool(cfg.get("cpa_mint_cookie_inject", True)),
            tools_dir=str(cfg.get("api_reverse_tools") or "").strip(),
        )


def _load_mint_and_export(tools_dir=""):
    tools_value = str(tools_dir or "").strip()
    if not tools_value:
        from cpa_xai import mint_and_export
        return mint_and_export
    tools = Path(tools_value).expanduser().resolve()
    package = tools if tools.name == "cpa_xai" else tools / "cpa_xai"
    init_path = package / "__init__.py"
    if package.resolve() == (_ROOT / "cpa_xai").resolve():
        from cpa_xai import mint_and_export
        return mint_and_export
    if not init_path.is_file():
        raise ImportError("cpa_xai package not found under %s" % tools)
    module_name = "_external_cpa_xai_%s" % abs(hash(str(package)))
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(init_path),
        submodule_search_locations=[str(package)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("unable to load cpa_xai from %s" % package)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module.mint_and_export


def export_cookies_from_page(page):
    if page is None:
        return []
    cookies = None
    for getter in (
        lambda: page.cookies(all_domains=True, all_info=True),
        lambda: page.cookies(all_domains=True),
        lambda: page.cookies(),
    ):
        try:
            cookies = getter()
            if cookies:
                break
        except TypeError:
            continue
        except Exception:
            continue
    if not cookies:
        try:
            browser = getattr(page, "browser", None)
            if browser is not None:
                cookies = browser.cookies()
        except Exception:
            cookies = None
    return [item for item in cookies if isinstance(item, dict)] if isinstance(cookies, list) else []


def _normalize_result(result, email=""):
    value = dict(result or {})
    value.setdefault("ok", False)
    value.setdefault("skipped", False)
    value.setdefault("email", str(email or ""))
    value.setdefault("error", None)
    return value


def _sync_sub2api_before_distribution(result, config, log):
    if not config.get("sub2api_auto_import", False):
        result["sub2api_import"] = {
            "ok": False, "action": "skipped", "reason": "disabled",
        }
        return True
    try:
        from sub2api_admin import sync_cpa_account
        sub2api_result = sync_cpa_account(result["path"], config)
    except Exception as exc:
        result["sub2api_import"] = {
            "ok": False, "action": "error", "error": str(exc),
        }
        log("[cpa] Sub2API import failed: %s" % exc)
        return True

    result["sub2api_import"] = sub2api_result
    preflight = sub2api_result.get("preflight") or {}
    if (
        sub2api_result.get("action") == "skipped"
        and sub2api_result.get("reason") == "preflight_rejected"
    ):
        rejected_path = sub2api_result.get("rejected_path")
        result["rejected_path"] = rejected_path
        result["path"] = rejected_path
        log(
            "[cpa] Sub2API skipped: preflight rejected state=%s status=%s code=%s rejected=%s"
            % (
                preflight.get("state"), preflight.get("status_code"),
                preflight.get("code", ""), rejected_path,
            )
        )
        return False

    readiness = sub2api_result.get("readiness") or {}
    log(
        "[cpa] Sub2API %s: account_id=%s preflight=%s readiness=%s status=%s"
        % (
            sub2api_result.get("action"), sub2api_result.get("account_id"),
            preflight.get("state", "unknown"), readiness.get("state", "unknown"),
            readiness.get("status_code"),
        )
    )
    return True


def _distribute_result(result, settings, config, log):
    allow_distribution = True
    if result.get("ok") and result.get("path"):
        allow_distribution = _sync_sub2api_before_distribution(result, config or {}, log)
    if (allow_distribution and result.get("ok") and result.get("path")
            and settings.copy_to_hotload and settings.hotload_dir):
        try:
            settings.hotload_dir.mkdir(parents=True, exist_ok=True)
            source = Path(result["path"])
            target = settings.hotload_dir / source.name
            shutil.copy2(str(source), str(target))
            try:
                os.chmod(str(target), 0o600)
            except Exception:
                pass
            result["hotload_path"] = str(target)
            log("[cpa] hotload copy -> %s" % target)
        except Exception as exc:
            result["cpa_copy_error"] = str(exc)
            result["warning"] = True
            result["partial"] = True
            log("[cpa] hotload copy failed: %s" % exc)
    return result


def export_cpa_xai_for_account(email, password, page=None, cookies=None, sso=None,
                               config=None, log_callback=None, cancel_callback=None):
    settings = CpaExportSettings.from_config(config)
    log = log_callback or (lambda message: None)
    if not settings.enabled:
        return _normalize_result({"ok": False, "skipped": True, "reason": "disabled"}, email)
    try:
        mint_and_export = _load_mint_and_export(settings.tools_dir)
    except Exception as exc:
        log("[cpa] import cpa_xai failed: %s" % exc)
        return _normalize_result({"ok": False, "error": "import: %s" % exc}, email)

    use_cookies = cookies
    if use_cookies is None and settings.cookie_inject and page is not None:
        use_cookies = export_cookies_from_page(page)
    if not settings.cookie_inject:
        use_cookies = None
    elif sso:
        base = list(use_cookies) if isinstance(use_cookies, list) else []
        sso_value = str(sso).strip()
        for cookie_name in ("sso", "sso-rw"):
            for domain in (".x.ai", "accounts.x.ai", ".accounts.x.ai", "auth.x.ai", ".auth.x.ai", "grok.com", ".grok.com"):
                base.append({"name": cookie_name, "value": sso_value, "domain": domain,
                             "path": "/", "secure": True, "httpOnly": True})
        use_cookies = base

    settings.auth_dir.mkdir(parents=True, exist_ok=True)
    log("[cpa] mint OIDC for %s -> %s" % (email, settings.auth_dir))
    result = mint_and_export(
        email=email, password=password, auth_dir=settings.auth_dir,
        page=None if settings.force_standalone else page,
        proxy=settings.proxy or None, headless=settings.headless,
        base_url=settings.base_url, browser_timeout_sec=settings.mint_timeout,
        force_standalone=settings.force_standalone, cookies=use_cookies,
        reuse_browser=True, recycle_every=15,
        log=lambda message: log("[cpa] %s" % message), cancel=cancel_callback,
        request_timeout_sec=settings.request_timeout,
        poll_timeout_sec=settings.poll_timeout,
        device_code_attempts=settings.device_code_attempts,
        device_code_retry_delay_sec=settings.device_code_retry_delay,
        device_code_max_retry_delay_sec=settings.device_code_max_retry_delay,
    )
    result = _normalize_result(result, email)
    _distribute_result(result, settings, config or {}, log)
    if not result.get("ok"):
        fail_path = settings.auth_dir / "cpa_auth_failed.txt"
        try:
            with open(str(fail_path), "a", encoding="utf-8") as handle:
                handle.write("%s----%s----%s\n" % (email, result.get("error") or "unknown", int(time.time())))
        except Exception as exc:
            log("[cpa] failed to persist failure record: %s" % exc)
    return result


def _account_record_for_email(accounts_path, email):
    path = Path(accounts_path).expanduser().resolve()
    target_email = str(email or "").strip().lower()
    if not path.is_file():
        raise ValueError("accounts file not found: %s" % path)
    if not target_email:
        raise ValueError("email is required")
    matches = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split("----", 2)
            if len(parts) != 3:
                raise ValueError("malformed account record at line %s" % line_number)
            record_email, password, sso = parts
            if record_email.strip().lower() == target_email:
                matches.append((record_email.strip(), password, sso.strip()))
    unique = list(dict.fromkeys(matches))
    if not unique:
        raise ValueError("email not found in accounts file: %s" % email)
    if len(unique) != 1:
        raise ValueError("ambiguous duplicate account records for email: %s" % email)
    record_email, password, sso = unique[0]
    if not password or not sso:
        raise ValueError("account record is missing password or SSO token")
    return {"email": record_email, "password": password, "sso": sso, "path": str(path)}


def retry_cpa_from_accounts_file(accounts_path, email, config=None, log_callback=None,
                                 cancel_callback=None):
    cfg = dict(config or {})
    log = log_callback or (lambda message: None)
    settings = CpaExportSettings.from_config(cfg)
    record = _account_record_for_email(accounts_path, email)
    from cpa_xai.schema import credential_file_name

    existing_path = settings.auth_dir / credential_file_name(record["email"])
    if existing_path.is_file():
        try:
            payload = json.loads(existing_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("existing CPA file is invalid: %s" % exc) from exc
        if str(payload.get("email") or "").strip().lower() != record["email"].lower():
            raise ValueError("existing CPA file belongs to a different email")
        if not payload.get("access_token") or not payload.get("refresh_token"):
            raise ValueError("existing CPA file is missing required tokens")
        log("[cpa] existing credential found; skipping mint for %s" % record["email"])
        result = _normalize_result(
            {"ok": True, "path": str(existing_path), "reused": True}, record["email"]
        )
        return _distribute_result(result, settings, cfg, log)

    return export_cpa_xai_for_account(
        email=record["email"],
        password=record["password"],
        page=None,
        sso=record["sso"],
        config=cfg,
        log_callback=log,
        cancel_callback=cancel_callback,
    )
