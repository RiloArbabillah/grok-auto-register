"""Create temporary mailboxes, poll messages, and extract verification codes."""
import re
import secrets
import string
import time
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests

DUCKMAIL_API_BASE = "https://api.duckmail.sbs"

YYDS_API_BASE = "https://maliapi.215.im/v1"


config = {}
_cf_domain_index = 0
_cloudmail_domain_index = 0
_OWN_NAMES = {'cloudmail_get_email_and_token', 'get_messages', 'cloudflare_get_messages', 'get_yyds_api_key', 'yyds_generate_username', 'yyds_get_domains', 'yyds_get_email_and_token', 'yyds_get_oai_code', 'get_email_provider', 'cloudflare_get_domains', 'extract_verification_code', 'get_cloudflare_api_base', 'cloudflare_apply_auth_params', 'duckmail_get_oai_code', 'create_account', 'get_yyds_jwt', 'get_message_detail', 'yyds_create_account', 'get_duckmail_api_key', 'get_cloudflare_path', 'cloudflare_create_account', 'cloudflare_get_token', 'cloudflare_get_oai_code', 'get_cloudmail_public_token', 'generate_username', 'yyds_get_message_detail', 'cloudflare_next_default_domain', 'yyds_get_messages', 'yyds_get_token', 'get_domains', 'get_token', 'cloudflare_create_temp_address', 'get_cloudflare_api_key', 'get_cloudmail_path', 'get_cloudmail_api_base', 'cloudmail_get_oai_code', 'cloudflare_build_headers', 'cloudflare_is_admin_create_path', 'cloudmail_next_domain', 'cloudflare_get_message_detail', 'cloudmail_get_messages', 'get_user_agent', 'yyds_pick_domain', '_pick_list_payload', 'get_email_and_token', 'get_oai_code', 'get_cloudflare_auth_mode', 'pick_domain'}


def bind_runtime(namespace):
    global config
    config = namespace.get("config", config)
    for name, value in namespace.items():
        if name.startswith("__") or name in _OWN_NAMES or name in {"config", "_cf_domain_index", "_cloudmail_domain_index"}:
            continue
        globals()[name] = value


def normalize_mail_body(*sources):
    """Return normalized text from provider payloads with string/list HTML support."""
    parts = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("text", "raw", "content", "intro", "body", "snippet"):
            value = source.get(key)
            values = value if isinstance(value, (list, tuple)) else [value]
            for item in values:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
        html_value = source.get("html")
        html_items = html_value if isinstance(html_value, (list, tuple)) else [html_value]
        for item in html_items:
            if isinstance(item, str) and item.strip():
                parts.append(re.sub(r"<[^>]+>", " ", item))
    return "\n".join(parts)


def _pick_list_payload(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return data.get("results")
        if isinstance(data.get("hydra:member"), list):
            return data.get("hydra:member")
        if isinstance(data.get("data"), list):
            return data.get("data")
        if isinstance(data.get("messages"), list):
            return data.get("messages")
        if isinstance(data.get("data"), dict):
            nested = data.get("data")
            if isinstance(nested.get("messages"), list):
                return nested.get("messages")
    return []

def cloudflare_apply_auth_params(params=None):
    merged = dict(params or {})
    key = get_cloudflare_api_key()
    mode = get_cloudflare_auth_mode()
    if key and mode == "query-key":
        merged["key"] = key
    return merged

def cloudflare_build_headers(content_type=False):
    headers = {"Content-Type": "application/json"} if content_type else {}
    key = get_cloudflare_api_key()
    mode = get_cloudflare_auth_mode()
    if key:
        if mode == "x-api-key":
            headers["X-API-Key"] = key
        elif mode == "x-admin-auth":
            headers["x-admin-auth"] = key
        elif mode != "none":
            headers["Authorization"] = f"Bearer {key}"
    return headers

def cloudflare_create_account(api_base, address, password, api_key=None, expires_in=0):
    headers = cloudflare_build_headers(content_type=True)
    if api_key and "Authorization" in headers:
        headers["Authorization"] = f"Bearer {api_key}"
    if api_key and "X-API-Key" in headers:
        headers["X-API-Key"] = api_key
    payload = {"address": address, "password": password, "expiresIn": expires_in}
    path = get_cloudflare_path("cloudflare_path_accounts", "/accounts")
    params = cloudflare_apply_auth_params()
    resp = http_post(f"{api_base}{path}", json=payload, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def cloudflare_create_temp_address(api_base):
    """Create a cloudflare_temp_email address with optional admin mode."""
    path = get_cloudflare_path("cloudflare_path_accounts", "/api/new_address")
    url = f"{api_base}{path}"
    domain = cloudflare_next_default_domain()
    is_admin_create = cloudflare_is_admin_create_path(path)
    if is_admin_create:
        payload = {"name": generate_username(10), "enablePrefix": True}
        if domain:
            payload["domain"] = domain
        headers = cloudflare_build_headers(content_type=True)
    else:
        payload = {}
        if domain:
            payload["domain"] = domain
        headers = {"Content-Type": "application/json"}
    resp = http_post(url, json=payload, headers=headers)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        raise Exception(f"Cloudflare {path} returned non-JSON: {resp.text[:300]}")
    address = data.get("address")
    jwt = data.get("jwt")
    if not address or not jwt:
        raise Exception(f"Cloudflare {path} response is missing address/jwt: {data}")
    return address, jwt

def cloudflare_get_domains(api_base, api_key=None):
    headers = cloudflare_build_headers(content_type=False)
    if api_key and "Authorization" in headers:
        headers["Authorization"] = f"Bearer {api_key}"
    if api_key and "X-API-Key" in headers:
        headers["X-API-Key"] = api_key
    path = get_cloudflare_path("cloudflare_path_domains", "/domains")
    params = cloudflare_apply_auth_params()
    resp = http_get(f"{api_base}{path}", headers=headers, params=params)
    resp.raise_for_status()
    return _pick_list_payload(resp.json())

def cloudflare_get_message_detail(api_base, token, message_id):
    headers = {"Authorization": f"Bearer {token}"}
    candidates = [
        f"{api_base}/api/mail/{message_id}",
        f"{api_base}{get_cloudflare_path('cloudflare_path_messages', '/messages')}/{message_id}",
    ]
    last_err = None
    for url in candidates:
        try:
            resp = http_get(
                url,
                headers=headers,
                params=cloudflare_apply_auth_params(),
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                return data["data"]
            return data
        except Exception as exc:
            last_err = exc
            continue
    raise Exception(f"Failed to fetch Cloudflare message details: {last_err}")

def cloudflare_get_messages(api_base, token):
    headers = {"Authorization": f"Bearer {token}"}
    path = get_cloudflare_path("cloudflare_path_messages", "/messages")
    params = {"limit": 20, "offset": 0}
    params = cloudflare_apply_auth_params(params)
    resp = http_get(f"{api_base}{path}", headers=headers, params=params)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        raise Exception(f"Cloudflare messages returned non-JSON: {resp.text[:300]}")
    return _pick_list_payload(data)

def cloudflare_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
    resend_callback=None,
):
    api_base = get_cloudflare_api_base()
    if not api_base:
        raise Exception("Cloudflare API base is not configured")
    deadline = time.time() + timeout
    # A message body may become readable later, so retry parsing it.
    seen_attempts = {}
    next_resend_at = time.time() + 35
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        if resend_callback and time.time() >= next_resend_at:
            try:
                resend_callback()
                if log_callback:
                    log_callback("[*] Requested a new verification code")
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] Failed to request a new verification code: {exc}")
            next_resend_at = time.time() + 35
        try:
            messages = cloudflare_get_messages(api_base, dev_token)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] Failed to fetch Cloudflare messages: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        if log_callback:
            log_callback(f"[Debug] Cloudflare messages in this poll: {len(messages)}")

        for msg in messages:
            msg_id = msg.get("id") or msg.get("msgid")
            if not msg_id:
                continue
            attempt = int(seen_attempts.get(msg_id, 0))
            if attempt >= 5:
                continue
            seen_attempts[msg_id] = attempt + 1
            recipients = [t.get("address", "").lower() for t in (msg.get("to") or [])]
            msg_addr = str(msg.get("address", "")).lower()
            # Prefer the target address while tolerating provider schema drift.
            address_matched = True
            if recipients:
                address_matched = email.lower() in recipients
            elif msg_addr:
                address_matched = msg_addr == email.lower()
            if not address_matched:
                if log_callback:
                    log_callback(f"[Debug] Skipping probable non-target message id={msg_id} address={msg_addr} to={recipients}")
                continue
            # Parse list content first to tolerate detail endpoint differences.
            subject = str(msg.get("subject", "") or "")
            combined = normalize_mail_body(msg)
            # Then request message details to fill missing content.
            try:
                detail = cloudflare_get_message_detail(api_base, dev_token, msg_id)
                detail_body = normalize_mail_body(detail)
                if detail_body:
                    combined += "\n" + detail_body
                if not subject:
                    subject = str(detail.get("subject", "") or "")
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] Cloudflare detail endpoint failed; parsing list content instead: {exc}")
            if log_callback:
                log_callback(f"[Debug] Cloudflare message received: {subject}")
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] Extracted verification code from Cloudflare message: {code}")
                return code
            elif log_callback:
                log_callback(f"[Debug] Message parsed without a verification code id={msg_id} attempt={seen_attempts[msg_id]}")
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"Cloudflare verification message not received within {timeout}s")

def cloudflare_get_token(api_base, address, password, api_key=None):
    headers = cloudflare_build_headers(content_type=True)
    if api_key and "Authorization" in headers:
        headers["Authorization"] = f"Bearer {api_key}"
    if api_key and "X-API-Key" in headers:
        headers["X-API-Key"] = api_key
    path = get_cloudflare_path("cloudflare_path_token", "/token")
    resp = http_post(
        f"{api_base}{path}",
        json={"address": address, "password": password},
        headers=headers,
        params=cloudflare_apply_auth_params(),
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        if data.get("token"):
            return data.get("token")
        if isinstance(data.get("data"), dict) and data["data"].get("token"):
            return data["data"].get("token")
    return None

def cloudflare_is_admin_create_path(path):
    """Return whether the configured path is the admin mailbox endpoint."""
    return str(path or "").rstrip("/").lower() == "/admin/new_address"

def cloudflare_next_default_domain():
    """Select the next configured Cloudflare mailbox domain."""
    global _cf_domain_index
    domains = [x.strip() for x in str(config.get("defaultDomains", "") or "").split(",") if x.strip()]
    if not domains:
        return ""
    domain = domains[_cf_domain_index % len(domains)]
    _cf_domain_index += 1
    return domain

def cloudmail_get_email_and_token():
    """Generate a Cloud Mail address without pre-creating an account."""
    if not get_cloudmail_api_base():
        raise Exception("Cloud Mail API base is not configured")
    if not get_cloudmail_public_token():
        raise Exception("Cloud Mail public token is not configured")
    domain = cloudmail_next_domain()
    if not domain:
        raise Exception("Cloud Mail inbox domains are not configured")
    address = f"{generate_username(12)}@{domain}"
    # Return a non-sensitive placeholder; the public token stays in config.json.
    return address, f"cloudmail:{address}"

def cloudmail_get_messages(address):
    api_base = get_cloudmail_api_base()
    public_token = get_cloudmail_public_token()
    if not api_base:
        raise Exception("Cloud Mail API base is not configured")
    if not public_token:
        raise Exception("Cloud Mail public token is not configured")
    payload = {
        "toEmail": address,
        "type": 0,
        "isDel": 0,
        "timeSort": "desc",
        "num": 1,
        "size": 20,
    }
    resp = http_post(
        f"{api_base}{get_cloudmail_path()}",
        headers={
            "Authorization": public_token,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        raise Exception(f"Cloud Mail message endpoint returned non-JSON: {resp.text[:300]}")
    if not isinstance(data, dict):
        raise Exception(f"Cloud Mail message endpoint returned an invalid format: {data}")
    result_code = data.get("code")
    if result_code not in (None, 200, "200"):
        raise Exception(
            f"Cloud Mail message endpoint failed: code={result_code}, message={data.get('message', '')}"
        )
    messages = data.get("data")
    if isinstance(messages, list):
        return messages
    return _pick_list_payload(data)

def cloudmail_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
    resend_callback=None,
):
    # dev_token preserves the provider contract; Cloud Mail uses its configured public token.
    _ = dev_token
    deadline = time.time() + timeout
    seen_attempts = {}
    next_resend_at = time.time() + 35
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        if resend_callback and time.time() >= next_resend_at:
            try:
                resend_callback()
                if log_callback:
                    log_callback("[*] Requested a new verification code")
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] Failed to request a new verification code: {exc}")
            next_resend_at = time.time() + 35
        try:
            messages = cloudmail_get_messages(email)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] Failed to fetch Cloud Mail messages: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        if log_callback:
            log_callback(f"[Debug] Cloud Mail messages in this poll: {len(messages)}")
        for msg in messages:
            msg_id = msg.get("emailId") or msg.get("email_id") or msg.get("id")
            if not msg_id:
                continue
            attempt = int(seen_attempts.get(msg_id, 0))
            if attempt >= 5:
                continue
            seen_attempts[msg_id] = attempt + 1
            target_address = str(
                msg.get("toEmail") or msg.get("to_email") or ""
            ).strip().lower()
            if target_address and target_address != email.lower():
                continue
            code_value = str(msg.get("code", "") or "").strip()
            combined = normalize_mail_body(msg)
            if code_value:
                combined = f"verification code: {code_value}\n{combined}"
            subject = str(msg.get("subject", "") or "")
            if log_callback:
                log_callback(f"[Debug] Cloud Mail message received: {subject}")
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] Extracted verification code from Cloud Mail message: {code}")
                return code
            if log_callback:
                log_callback(
                    f"[Debug] Cloud Mail message parsed without a verification code "
                    f"id={msg_id} attempt={seen_attempts[msg_id]}"
                )
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"Cloud Mail verification message not received within {timeout}s")

def cloudmail_next_domain():
    """Select the next configured Cloud Mail catch-all domain."""
    global _cloudmail_domain_index
    domains = [
        item.strip().lstrip("@")
        for item in str(config.get("cloudmail_domains", "") or "").split(",")
        if item.strip().lstrip("@")
    ]
    if not domains:
        return ""
    domain = domains[_cloudmail_domain_index % len(domains)]
    _cloudmail_domain_index += 1
    return domain

def create_account(address, password, api_key=None, expires_in=0):
    headers = {"Content-Type": "application/json"}
    key = api_key or get_duckmail_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = {"address": address, "password": password, "expiresIn": expires_in}
    resp = http_post(f"{DUCKMAIL_API_BASE}/accounts", json=data, headers=headers)
    resp.raise_for_status()
    return resp.json()

def duckmail_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
):
    deadline = time.time() + timeout
    seen_attempts = {}
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            messages = get_messages(dev_token)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] Failed to fetch message list: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        for msg in messages:
            msg_id = msg.get("id") or msg.get("msgid")
            if not msg_id:
                continue
            recipients = [t.get("address", "").lower() for t in (msg.get("to") or [])]
            if email.lower() not in recipients:
                continue
            attempt = int(seen_attempts.get(msg_id, 0))
            if attempt >= 5:
                continue
            seen_attempts[msg_id] = attempt + 1
            try:
                detail = get_message_detail(dev_token, msg_id)
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] Failed to fetch message details: {exc}")
                continue
            combined = normalize_mail_body(detail)
            subject = detail.get("subject", "")
            if log_callback:
                log_callback(f"[Debug] Message received: {subject}")
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] Extracted verification code: {code}")
                return code
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"Verification message not received within {timeout}s")

def extract_verification_code(text, subject=""):
    if subject:
        match = re.search(r"^([A-Z0-9]{3}-[A-Z0-9]{3})\s+xAI", subject, re.IGNORECASE)
        if match:
            return match.group(1)
    match = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", text, re.IGNORECASE)
    if match:
        return match.group(1)
    patterns = [
        r"verification\s+code[:\s]+(\d{4,8})",
        r"your\s+code[:\s]+(\d{4,8})",
        r"confirm(?:ation)?\s+code[:\s]+(\d{4,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def generate_username(length=10):
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

def get_cloudflare_api_base():
    return str(config.get("cloudflare_api_base", "") or "").rstrip("/")

def get_cloudflare_api_key():
    return config.get("cloudflare_api_key", "")

def get_cloudflare_auth_mode():
    return str(config.get("cloudflare_auth_mode", "none") or "none").lower()

def get_cloudflare_path(key, default_path):
    raw = str(config.get(key, default_path) or default_path).strip()
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw

def get_cloudmail_api_base():
    return str(config.get("cloudmail_api_base", "") or "").strip().rstrip("/")

def get_cloudmail_path():
    raw = str(
        config.get("cloudmail_path_messages", "/api/public/emailList")
        or "/api/public/emailList"
    ).strip()
    return raw if raw.startswith("/") else "/" + raw

def get_cloudmail_public_token():
    return str(config.get("cloudmail_public_token", "") or "").strip()

def get_domains(api_key=None):
    headers = {}
    key = api_key or get_duckmail_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = http_get(f"{DUCKMAIL_API_BASE}/domains", headers=headers)
    resp.raise_for_status()
    return resp.json().get("hydra:member", [])

def get_duckmail_api_key():
    return config.get("duckmail_api_key", "")

def get_email_and_token(api_key=None):
    provider = get_email_provider()
    if provider == "yyds":
        return yyds_get_email_and_token(api_key=api_key, jwt=get_yyds_jwt())
    if provider == "cloudmail":
        return cloudmail_get_email_and_token()
    if provider == "cloudflare":
        api_base = get_cloudflare_api_base()
        if not api_base:
            raise Exception("Cloudflare API base is not configured")
        try:
            # cloudflare_temp_email-specific mode.
            return cloudflare_create_temp_address(api_base)
        except Exception as primary_exc:
            # Fall back to the Mail.tm-compatible flow.
            key = api_key or get_cloudflare_api_key()
            domains = cloudflare_get_domains(api_base, api_key=key)
            if not domains:
                raise Exception(f"Failed to create Cloudflare mailbox: {primary_exc}")
            verified = [d for d in domains if d.get("isVerified")]
            target = verified[0] if verified else domains[0]
            domain = target.get("domain")
            if not domain:
                raise Exception("Invalid Cloudflare domain data: missing domain field")
            username = generate_username(10)
            address = f"{username}@{domain}"
            password = secrets.token_urlsafe(12)
            cloudflare_create_account(
                api_base, address, password, api_key=key, expires_in=0
            )
            token = cloudflare_get_token(api_base, address, password, api_key=key)
            if not token:
                raise Exception("Failed to obtain Cloudflare mailbox token")
            return address, token
    key = api_key or get_duckmail_api_key()
    domain = pick_domain(api_key=key)
    username = generate_username(10)
    address = f"{username}@{domain}"
    password = secrets.token_urlsafe(12)
    create_account(address, password, api_key=key, expires_in=0)
    token = get_token(address, password)
    if not token:
        raise Exception("Failed to obtain DuckMail token")
    return address, token

def get_email_provider():
    return config.get("email_provider", "duckmail")

def get_message_detail(token, message_id):
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_get(f"{DUCKMAIL_API_BASE}/messages/{message_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()

def get_messages(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_get(f"{DUCKMAIL_API_BASE}/messages", headers=headers)
    resp.raise_for_status()
    return resp.json().get("hydra:member", [])

def get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
    resend_callback=None,
):
    provider = get_email_provider()
    if provider == "yyds":
        return yyds_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            jwt=get_yyds_jwt(),
            cancel_callback=cancel_callback,
        )
    if provider == "cloudmail":
        return cloudmail_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
            resend_callback=resend_callback,
        )
    if provider == "cloudflare":
        return cloudflare_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
            resend_callback=resend_callback,
        )
    return duckmail_get_oai_code(
        dev_token,
        email,
        timeout=timeout,
        poll_interval=poll_interval,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )

def get_token(address, password):
    data = {"address": address, "password": password}
    resp = http_post(f"{DUCKMAIL_API_BASE}/token", json=data)
    resp.raise_for_status()
    return resp.json().get("token")

def get_user_agent():
    return config.get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    )

def get_yyds_api_key():
    return config.get("yyds_api_key", "")

def get_yyds_jwt():
    return config.get("yyds_jwt", "")

def pick_domain(api_key=None):
    domains = get_domains(api_key=api_key)
    if not domains:
        raise Exception("DuckMail returned no available domains")
    private = [d for d in domains if d.get("ownerId")]
    verified_private = [d for d in private if d.get("isVerified")]
    if verified_private:
        return verified_private[0]["domain"]
    public = [d for d in domains if d.get("isVerified")]
    if public:
        return public[0]["domain"]
    raise Exception("DuckMail has no verified domains available")

def yyds_create_account(address=None, domain=None, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["X-API-Key"] = key
    payload = {}
    if address:
        payload["address"] = address
    if domain:
        payload["domain"] = domain
    elif key or token:
        payload["autoDomainStrategy"] = "prefer_owned"
    resp = http_post(f"{YYDS_API_BASE}/accounts", json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {})
    raise Exception(f"Failed to create YYDS mailbox: {data}")

def yyds_generate_username(length=10):
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

def yyds_get_domains(api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_get(f"{YYDS_API_BASE}/domains", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", []) if data.get("success") else []

def yyds_get_email_and_token(api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    if not token and not key:
        raise Exception("YYDS API key or JWT is not configured")
    domain = yyds_pick_domain(api_key=key, jwt=token)
    username = yyds_generate_username(10)
    result = yyds_create_account(
        address=username, domain=domain, api_key=key, jwt=token
    )
    address = result.get("address") or f"{username}@{domain}"
    temp_token = result.get("token")
    if not temp_token:
        temp_token = yyds_get_token(address, api_key=key, jwt=token)
    if not temp_token:
        raise Exception("Failed to obtain YYDS token")
    print(f"[*] Created YYDS mailbox: {address}")
    return address, temp_token

def yyds_get_message_detail(message_id, token=None, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    temp_token = token or jwt or get_yyds_jwt()
    headers = {}
    if temp_token:
        headers["Authorization"] = f"Bearer {temp_token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_get(f"{YYDS_API_BASE}/messages/{message_id}", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {})
    raise Exception(f"Failed to fetch YYDS message details: {data}")

def yyds_get_messages(address, token=None, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    temp_token = token or jwt or get_yyds_jwt()
    headers = {}
    if temp_token:
        headers["Authorization"] = f"Bearer {temp_token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_get(
        f"{YYDS_API_BASE}/messages",
        params={"address": address},
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {}).get("messages", [])
    return []

def yyds_get_oai_code(
    token,
    address,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    jwt=None,
    cancel_callback=None,
):
    deadline = time.time() + timeout
    seen_attempts = {}
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            messages = yyds_get_messages(address, token=token, jwt=jwt)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] Failed to fetch YYDS messages: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id:
                continue
            to_addrs = [t.get("address", "").lower() for t in (msg.get("to") or [])]
            if address.lower() not in to_addrs:
                continue
            attempt = int(seen_attempts.get(msg_id, 0))
            if attempt >= 5:
                continue
            seen_attempts[msg_id] = attempt + 1
            try:
                detail = yyds_get_message_detail(msg_id, token=token, jwt=jwt)
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] Failed to fetch YYDS message details: {exc}")
                continue
            combined = normalize_mail_body(detail)
            subject = detail.get("subject", "")
            if log_callback:
                log_callback(f"[Debug] YYDS message received: {subject}")
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] Extracted verification code from YYDS message: {code}")
                return code
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"YYDS verification message not received within {timeout}s")

def yyds_get_token(address, api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["X-API-Key"] = key
    resp = http_post(
        f"{YYDS_API_BASE}/token", json={"address": address}, headers=headers
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data.get("data", {}).get("token")
    raise Exception(f"Failed to obtain YYDS token: {data}")

def yyds_pick_domain(api_key=None, jwt=None):
    domains = yyds_get_domains(api_key=api_key, jwt=jwt)
    if not domains:
        raise Exception("YYDS returned no available domains")
    private = [d for d in domains if d.get("isVerified") and not d.get("isPublic")]
    if private:
        return private[0]["domain"]
    public = [d for d in domains if d.get("isVerified") and d.get("isPublic")]
    if public:
        return public[0]["domain"]
    verified = [d for d in domains if d.get("isVerified")]
    if verified:
        return verified[0]["domain"]
    raise Exception("YYDS has no verified domains available")



class CloudflareMailClient:
    """Standalone Cloudflare mail client used by the debug CLI."""
    def __init__(self, api_base, auth_mode="none", api_key="", create_path="/api/new_address", timeout=20):
        self.api_base = str(api_base or "").rstrip("/")
        self.auth_mode = str(auth_mode or "none").lower()
        self.api_key = str(api_key or "")
        self.create_path = self.normalize_path(create_path, "/api/new_address")
        self.timeout = int(timeout)

    @staticmethod
    def normalize_path(path, default_path):
        raw = (path or default_path).strip() or default_path
        return raw if raw.startswith("/") else "/" + raw

    def build_auth_headers(self, content_type=False):
        headers = {"Content-Type": "application/json"} if content_type else {}
        if not self.api_key:
            return headers
        if self.auth_mode == "x-admin-auth":
            headers["x-admin-auth"] = self.api_key
        elif self.auth_mode == "x-api-key":
            headers["X-API-Key"] = self.api_key
        elif self.auth_mode == "bearer":
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    @staticmethod
    def json_or_text(response):
        try:
            return response.json(), ""
        except Exception:
            return None, str(getattr(response, "text", "") or "")[:400]

    def create_address(self, domain="", name=""):
        is_admin = self.create_path.rstrip("/").lower() == "/admin/new_address"
        payload = {}
        headers = {"Content-Type": "application/json"}
        if is_admin:
            payload = {"name": name.strip() if str(name).strip() else generate_username(), "enablePrefix": True}
            if str(domain).strip():
                payload["domain"] = str(domain).strip()
            headers = self.build_auth_headers(content_type=True)
        elif str(domain).strip():
            payload["domain"] = str(domain).strip()
        response = requests.post(self.api_base + self.create_path, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data, raw = self.json_or_text(response)
        if not data:
            raise RuntimeError("%s returned non-JSON: %s" % (self.create_path, raw))
        address = str(data.get("address", "")).strip()
        jwt = str(data.get("jwt", "")).strip()
        if not address or not jwt:
            raise RuntimeError("%s response is missing address/jwt: %r" % (self.create_path, data))
        return address, jwt

    def fetch_box(self, jwt, path, params):
        response = requests.get(
            self.api_base + path,
            params=params,
            headers={"Authorization": "Bearer " + str(jwt)},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            return []
        data, _ = self.json_or_text(response)
        return _pick_list_payload(data)

    def probe_all_boxes(self, jwt):
        probes = [
            ("/api/mails", {"limit": 20, "offset": 0}),
            ("/api/sendbox", {"limit": 20, "offset": 0}),
            ("/api/mails", {"limit": 20, "offset": 0, "box": "trash"}),
            ("/api/mails", {"limit": 20, "offset": 0, "folder": "trash"}),
            ("/api/mails", {"limit": 20, "offset": 0, "deleted": "1"}),
            ("/api/mails", {"limit": 20, "offset": 0, "status": "deleted"}),
        ]
        return [("%s?%s" % (path, params), self.fetch_box(jwt, path, params)) for path, params in probes]

    def get_detail(self, jwt, mail_id):
        for path in ("/api/mail/%s" % mail_id, "/api/mails/%s" % mail_id):
            try:
                response = requests.get(
                    self.api_base + path,
                    headers={"Authorization": "Bearer " + str(jwt)},
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    continue
                data, _ = self.json_or_text(response)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return {}

    @staticmethod
    def flatten_mail_text(item, detail):
        subject = str(item.get("subject") or detail.get("subject") or "")
        parts = []
        for source in (item, detail):
            for key in ("text", "raw", "content", "intro", "body", "snippet"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
            html_value = source.get("html")
            if isinstance(html_value, str):
                html_value = [html_value]
            if isinstance(html_value, list):
                parts.extend(re.sub(r"<[^>]+>", " ", item) for item in html_value if isinstance(item, str))
        return subject, "\n".join(parts)
