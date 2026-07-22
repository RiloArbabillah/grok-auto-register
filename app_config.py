"""Manage application defaults, persistence, normalization, and validation."""
import json
import os
import re
import tempfile
import urllib.parse

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "duckmail_api_key": "",
    "cloudflare_api_base": "",
    "cloudflare_api_key": "",
    "cloudflare_auth_mode": "none",
    "cloudflare_path_domains": "/api/domains",
    "cloudflare_path_accounts": "/api/new_address",
    "cloudflare_path_token": "/api/token",
    "cloudflare_path_messages": "/api/mails",
    "cloudmail_api_base": "",
    "cloudmail_public_token": "",
    "cloudmail_domains": "",
    "cloudmail_path_messages": "/api/public/emailList",
    "imap_host": "",
    "imap_port": 993,
    "imap_ssl": True,
    "imap_user": "",
    "imap_password": "",
    "imap_folder": "INBOX",
    "imap_address_domain": "",
    "imap_address_suffix": "-grok",
    "proxy_mode": "manual",
    "proxy": "",
    "proxyscrape_country_codes": [],
    "enable_nsfw": True,
    "register_count": 1,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "grok2api_auto_add_local": False,
    "grok2api_local_token_file": "",
    "grok2api_pool_name": "ssoBasic",
    "grok2api_auto_add_remote": False,
    "grok2api_remote_base": "",
    "grok2api_remote_app_key": "",
    "sub2api_auto_import": False,
    "sub2api_base_url": "",
    "sub2api_admin_api_key": "",
    "sub2api_group_ids": [5],
    "sub2api_concurrency": 1,
    "sub2api_priority": 1,
    "sub2api_timeout_sec": 30,
    "sub2api_preflight_enabled": True,
    "sub2api_preflight_timeout_sec": 30,
    "sub2api_preflight_attempts": 3,
    "sub2api_preflight_retry_delay_sec": 5,
    "sub2api_rejected_dir": "cpa_rejected",
    "sub2api_readiness_timeout_sec": 30,
    "sub2api_readiness_poll_sec": 2,
    "api_reverse_tools": "",
    "cpa_export_enabled": True,
    "cpa_auth_dir": "./cpa_auths",
    "cpa_copy_to_hotload": False,
    "cpa_hotload_dir": "",
    "cpa_base_url": "https://cli-chat-proxy.grok.com/v1",
    "cpa_proxy": "",
    "cpa_headless": False,
    "cpa_force_standalone": True,
    "cpa_mint_timeout_sec": 300,
    "cpa_mint_cookie_inject": True,
    "cpa_oidc_request_timeout_sec": 15,
    "cpa_oidc_poll_timeout_sec": 15,
    "cpa_device_code_attempts": 4,
    "cpa_device_code_retry_delay_sec": 60,
    "cpa_device_code_max_retry_delay_sec": 300,
    "grok2api_allow_legacy_full_save": False,
    "email_provider": "duckmail",
    "yyds_api_key": "",
    "yyds_jwt": "",
    "defaultDomains": "",
}


config = DEFAULT_CONFIG.copy()

class ConfigError(RuntimeError):
    pass


def _require_bool(cfg, key):
    value = cfg.get(key)
    if type(value) is not bool:
        raise ConfigError(f"Config option {key} must be a boolean true/false")
    return value


def _require_int(cfg, key, minimum, maximum):
    value = cfg.get(key)
    if type(value) is not int:
        raise ConfigError(f"Config option {key} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(f"Config option {key} must be between {minimum} and {maximum}")
    return value


def _require_string(cfg, key, path=False):
    value = cfg.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Config option {key} must be a string")
    value = value.strip() if key not in ("user_agent",) else value
    if "\x00" in value:
        raise ConfigError(f"Config option {key} contains an invalid null character")
    if path and value:
        os.path.expanduser(value)
    return value


def validate_config_structure(raw):
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    cfg = {**DEFAULT_CONFIG, **raw}
    bool_keys = (
        "enable_nsfw", "grok2api_auto_add_local", "grok2api_auto_add_remote",
        "grok2api_allow_legacy_full_save", "cpa_export_enabled",
        "cpa_copy_to_hotload", "cpa_headless", "cpa_force_standalone",
        "cpa_mint_cookie_inject", "sub2api_auto_import",
        "sub2api_preflight_enabled", "imap_ssl",
    )
    for key in bool_keys:
        cfg[key] = _require_bool(cfg, key)
    cfg["register_count"] = _require_int(cfg, "register_count", 1, 2500)
    cfg["cpa_mint_timeout_sec"] = _require_int(cfg, "cpa_mint_timeout_sec", 30, 1800)
    cfg["cpa_oidc_request_timeout_sec"] = _require_int(cfg, "cpa_oidc_request_timeout_sec", 3, 120)
    cfg["cpa_oidc_poll_timeout_sec"] = _require_int(cfg, "cpa_oidc_poll_timeout_sec", 3, 120)
    cfg["cpa_device_code_attempts"] = _require_int(cfg, "cpa_device_code_attempts", 1, 10)
    cfg["cpa_device_code_retry_delay_sec"] = _require_int(cfg, "cpa_device_code_retry_delay_sec", 1, 600)
    cfg["cpa_device_code_max_retry_delay_sec"] = _require_int(cfg, "cpa_device_code_max_retry_delay_sec", 1, 900)
    cfg["sub2api_concurrency"] = _require_int(cfg, "sub2api_concurrency", 1, 1000)
    cfg["sub2api_priority"] = _require_int(cfg, "sub2api_priority", 1, 1000)
    cfg["sub2api_timeout_sec"] = _require_int(cfg, "sub2api_timeout_sec", 1, 1800)
    cfg["sub2api_preflight_timeout_sec"] = _require_int(cfg, "sub2api_preflight_timeout_sec", 1, 1800)
    cfg["sub2api_preflight_attempts"] = _require_int(cfg, "sub2api_preflight_attempts", 1, 20)
    cfg["sub2api_preflight_retry_delay_sec"] = _require_int(cfg, "sub2api_preflight_retry_delay_sec", 0, 300)
    cfg["sub2api_readiness_timeout_sec"] = _require_int(cfg, "sub2api_readiness_timeout_sec", 0, 1800)
    cfg["sub2api_readiness_poll_sec"] = _require_int(cfg, "sub2api_readiness_poll_sec", 1, 300)
    cfg["imap_port"] = _require_int(cfg, "imap_port", 1, 65535)
    group_ids = cfg.get("sub2api_group_ids")
    if not isinstance(group_ids, list) or not group_ids or any(type(value) is not int for value in group_ids):
        raise ConfigError("Config option sub2api_group_ids must be a non-empty integer array")
    country_codes = cfg.get("proxyscrape_country_codes")
    if not isinstance(country_codes, list) or any(not isinstance(value, str) for value in country_codes):
        raise ConfigError("Config option proxyscrape_country_codes must be an array of ISO country codes")
    normalized_country_codes = []
    for value in country_codes:
        code = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise ConfigError("Config option proxyscrape_country_codes contains an invalid ISO country code")
        if code not in normalized_country_codes:
            normalized_country_codes.append(code)
    cfg["proxyscrape_country_codes"] = normalized_country_codes
    string_keys = tuple(key for key, value in DEFAULT_CONFIG.items() if isinstance(value, str))
    path_keys = {"grok2api_local_token_file", "api_reverse_tools", "cpa_auth_dir", "cpa_hotload_dir"}
    for key in string_keys:
        cfg[key] = _require_string(cfg, key, path=key in path_keys)
    enums = {
        "proxy_mode": {"off", "manual", "proxyscrape"},
        "email_provider": {"duckmail", "yyds", "cloudflare", "cloudmail", "imap"},
        "cloudflare_auth_mode": {"query-key", "bearer", "x-api-key", "x-admin-auth", "none"},
        "grok2api_pool_name": {"ssoBasic", "ssoSuper"},
    }
    for key, allowed in enums.items():
        value = cfg.get(key, DEFAULT_CONFIG.get(key, ""))
        if value not in allowed:
            raise ConfigError(f"Config option {key} has invalid value {value!r}; allowed values: {sorted(allowed)}")
        cfg[key] = value

    api_path_keys = {
        "cloudflare_path_domains", "cloudflare_path_accounts",
        "cloudflare_path_token", "cloudflare_path_messages",
        "cloudmail_path_messages",
    }
    for key in api_path_keys:
        value = cfg[key]
        if value and not value.startswith("/"):
            value = "/" + value
        cfg[key] = value

    url_keys = {
        "cloudflare_api_base", "cloudmail_api_base",
        "grok2api_remote_base", "cpa_base_url", "sub2api_base_url",
    }
    for key in url_keys:
        value = cfg[key]
        if not value:
            continue
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"Config option {key} must be a valid HTTP/HTTPS URL")

    for key in path_keys:
        value = cfg[key]
        if value.startswith("~"):
            cfg[key] = os.path.expanduser(value)
    return cfg


def validate_run_requirements(cfg):
    cfg = validate_config_structure(cfg)
    provider = cfg["email_provider"]
    if provider == "cloudflare" and not cfg["cloudflare_api_base"]:
        raise ConfigError("Cloudflare mode requires cloudflare_api_base")
    if provider == "cloudmail":
        missing = [
            key for key in ("cloudmail_api_base", "cloudmail_public_token", "cloudmail_domains")
            if not cfg[key]
        ]
        if missing:
            raise ConfigError("Cloud Mail mode is missing required options: " + ", ".join(missing))
    if provider == "yyds" and not (cfg["yyds_api_key"] or cfg["yyds_jwt"]):
        raise ConfigError("YYDS mode requires yyds_api_key or yyds_jwt")
    if provider == "imap":
        missing = [
            key for key in (
                "imap_host", "imap_user", "imap_password", "imap_folder",
                "imap_address_domain", "imap_address_suffix",
            )
            if not cfg[key]
        ]
        if missing:
            raise ConfigError("IMAP mode is missing required options: " + ", ".join(missing))
        domain = cfg["imap_address_domain"].lstrip("@").lower()
        if "." not in domain or any(char.isspace() for char in domain):
            raise ConfigError("Config option imap_address_domain must be a valid mail domain")
        cfg["imap_address_domain"] = domain
        suffix = cfg["imap_address_suffix"].lower()
        if not re.fullmatch(r"-[a-z0-9]+", suffix):
            raise ConfigError("Config option imap_address_suffix must match -name")
        cfg["imap_address_suffix"] = suffix
    if cfg["grok2api_auto_add_remote"]:
        missing = [
            key for key in ("grok2api_remote_base", "grok2api_remote_app_key")
            if not cfg[key]
        ]
        if missing:
            raise ConfigError("Remote token pool is missing required options: " + ", ".join(missing))
    if cfg["cpa_export_enabled"] and cfg["cpa_copy_to_hotload"] and not cfg["cpa_hotload_dir"]:
        raise ConfigError("cpa_hotload_dir is required when CPA hotload copying is enabled")
    if cfg["sub2api_auto_import"]:
        missing = [
            key for key in ("sub2api_base_url", "sub2api_admin_api_key")
            if not cfg[key]
        ]
        if missing:
            raise ConfigError("Sub2API auto-import is missing required options: " + ", ".join(missing))
    return cfg


def validate_config(raw):
    """Backward-compatible full validation used before a run or save."""
    return validate_run_requirements(raw)



def _replace_config(value):
    config.clear()
    config.update(value)
    return config


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            return _replace_config(validate_config_structure(loaded))
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(f"Failed to parse config file {CONFIG_FILE}: {exc}") from exc
    return _replace_config(validate_config_structure(DEFAULT_CONFIG.copy()))


def save_config():
    normalized = validate_config_structure(config)
    _replace_config(normalized)
    config_dir = os.path.dirname(os.path.abspath(CONFIG_FILE))
    os.makedirs(config_dir, exist_ok=True)
    fd = None
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".config-", suffix=".json.tmp", dir=config_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(config, handle, indent=4, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except Exception:
            pass
        os.replace(temp_path, CONFIG_FILE)
        temp_path = None
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass
    except Exception as exc:
        raise ConfigError(f"Failed to save config: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    return config
