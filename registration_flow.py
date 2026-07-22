"""Orchestrate the registration flow shared by the GUI and CLI."""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class RegistrationCallbacks:
    log: Callable[[str], None]
    cancelled: Callable[[], bool]


@dataclass
class RegistrationOperations:
    prepare_account_network: Callable[[int], None]
    start_browser: Callable[[], None]
    restart_browser: Callable[[], None]
    browser_missing: Callable[[], bool]
    open_signup_page: Callable[[], None]
    fill_email_and_submit: Callable[[], Tuple[str, str]]
    save_mail_credential: Callable[[str, str], bool]
    fill_code_and_submit: Callable[[str, str], str]
    fill_profile_and_submit: Callable[[], Dict[str, Any]]
    wait_for_sso_cookie: Callable[[], str]
    enable_nsfw: Callable[[str], Tuple[bool, str]]
    persist_account_line: Callable[[str, str, str], None]
    queue_unsaved_result: Callable[[Dict[str, Any], str], bool]
    add_tokens: Callable[[str, str], Dict[str, Dict[str, Any]]]
    export_cpa: Callable[[str, str, str], Dict[str, Any]]
    cleanup: Callable[[str], None]
    sleep: Callable[[float], None]
    cancelled_exception: type
    retry_exception: type


@dataclass
class RegistrationResult:
    ok: bool
    email: str = ""
    password: str = ""
    sso: str = ""
    profile: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retryable: bool = False


@dataclass
class OutputResult:
    registered: bool
    saved: bool
    pending_saved: bool = False
    save_error: str = ""
    pools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cpa: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegistrationSettings:
    count: int
    enable_nsfw: bool = True
    max_mail_retry: int = 3
    max_slot_retry: int = 3
    cleanup_interval: int = 5


@dataclass
class BatchResult:
    success_count: int = 0
    fail_count: int = 0
    processed_count: int = 0
    registered_unsaved_count: int = 0
    postprocess_warning_count: int = 0
    cancelled: bool = False
    results: list = field(default_factory=list)


def register_one_account(callbacks, ops, enable_nsfw=True, max_mail_retry=3):
    email = ""
    dev_token = ""
    code = ""
    mail_ok = False
    for mail_try in range(1, max_mail_retry + 1):
        if callbacks.cancelled():
            raise ops.cancelled_exception()
        callbacks.log(f"[*] 1. Open registration page (attempt {mail_try}/{max_mail_retry})")
        ops.open_signup_page()
        callbacks.log("[*] 2. Create and submit email address")
        email, dev_token = ops.fill_email_and_submit()
        callbacks.log(f"[*] Email: {email}")
        callbacks.log(f"[Debug] Email credential (JWT): {dev_token}")
        if not ops.save_mail_credential(email, dev_token):
            callbacks.log("[!] Failed to save email credentials; registration will continue")
        callbacks.log("[*] 3. Fetch verification code")
        try:
            code = ops.fill_code_and_submit(email, dev_token)
            mail_ok = True
            break
        except Exception as exc:
            message = str(exc)
            if ("\u672a\u6536\u5230\u9a8c\u8bc1\u7801" in message or "\u9a8c\u8bc1\u7801" in message or "verification code" in message.lower()) and mail_try < max_mail_retry:
                callbacks.log(f"[!] No verification code received; retrying with a new email: {message}")
                ops.restart_browser()
                ops.sleep(1)
                continue
            raise
    if not mail_ok:
        raise RuntimeError("Verification failed after the maximum number of retries")
    callbacks.log(f"[*] Verification code: {code}")
    callbacks.log("[*] 4. Complete profile")
    profile = ops.fill_profile_and_submit()
    callbacks.log(f"[*] Profile completed: {profile.get('given_name')} {profile.get('family_name')}")
    callbacks.log("[*] 5. Wait for SSO cookie")
    sso = ops.wait_for_sso_cookie()
    if enable_nsfw:
        callbacks.log("[*] 6. Enable NSFW")
        try:
            nsfw_ok, nsfw_msg = ops.enable_nsfw(sso)
            if nsfw_ok:
                callbacks.log(f"[+] NSFW enabled: {nsfw_msg}")
            else:
                callbacks.log(f"[!] NSFW was not enabled; continuing to save the account: {nsfw_msg}")
        except Exception as exc:
            callbacks.log(f"[!] Failed to enable NSFW; continuing to save the account: {exc}")
    return RegistrationResult(
        ok=True,
        email=email,
        password=str(profile.get("password") or ""),
        sso=sso,
        profile=profile,
    )


def persist_account_result(result, callbacks, ops):
    try:
        ops.persist_account_line(result.email, result.password, result.sso)
        saved = True
        save_error = ""
        pending_saved = False
    except Exception as exc:
        saved = False
        save_error = str(exc)
        try:
            pending_saved = bool(
                ops.queue_unsaved_result(
                    {
                        "email": result.email,
                        "password": result.password,
                        "sso": result.sso,
                        "profile": result.profile,
                    },
                    save_error,
                )
            )
        except Exception as pending_exc:
            pending_saved = False
            callbacks.log(f"[!] Failed to write to the pending queue: {pending_exc}")
        callbacks.log(f"[!] Account registered, but the main result file could not be saved: {save_error}")
        if pending_saved:
            callbacks.log("[!] Unsaved account added to the pending queue for recovery")
        else:
            callbacks.log("[!] Failed to write the pending queue; copy the account details immediately")

    try:
        pools = ops.add_tokens(result.sso, result.email)
        if not isinstance(pools, dict):
            raise TypeError("token pool result must be a dict")
    except Exception as exc:
        callbacks.log(f"[!] Token pool post-processing failed; account result was preserved: {exc}")
        pools = {
            "internal": {
                "enabled": True,
                "ok": False,
                "error": str(exc),
            }
        }
    for name, state in pools.items():
        if isinstance(state, dict) and state.get("enabled") and not state.get("ok"):
            callbacks.log(f"[!] Failed to add token to grok2api {name} pool: {state.get('error')}")

    try:
        cpa = ops.export_cpa(result.email, result.password, result.sso)
        if not isinstance(cpa, dict):
            raise TypeError("CPA result must be a dict")
    except Exception as exc:
        callbacks.log(f"[!] CPA export post-processing failed; account result was preserved: {exc}")
        cpa = {"ok": False, "skipped": False, "error": str(exc)}

    return OutputResult(
        registered=True,
        saved=saved,
        pending_saved=pending_saved,
        save_error=save_error,
        pools=pools,
        cpa=cpa,
    )


def _notify_observer(observer, result, account, output, callbacks):
    try:
        observer(result, account, output)
    except Exception as exc:
        callbacks.log(f"[Debug] Observer failed: {exc}")


def _run_cleanup_safely(ops, callbacks, reason):
    try:
        ops.cleanup(reason)
        return True
    except Exception as exc:
        callbacks.log(f"[!] Cleanup failed and was ignored without affecting account statistics: {reason}: {exc}")
        return False


def _prepare_next_account(result, settings, callbacks, ops):
    if result.processed_count >= settings.count:
        return False
    if callbacks.cancelled():
        result.cancelled = True
        return False
    try:
        ops.prepare_account_network(result.processed_count)
        if ops.browser_missing():
            ops.start_browser()
        else:
            ops.restart_browser()
        ops.sleep(1)
        return True
    except ops.cancelled_exception:
        result.cancelled = True
        callbacks.log("[!] Stopped while preparing the next account")
        return False


def run_batch(count, callbacks, observer, ops, enable_nsfw=True, cleanup_interval=5,
              max_slot_retry=3, max_mail_retry=3, settings=None):
    if settings is None:
        settings = RegistrationSettings(
            count=int(count),
            enable_nsfw=bool(enable_nsfw),
            cleanup_interval=int(cleanup_interval),
            max_slot_retry=int(max_slot_retry),
            max_mail_retry=int(max_mail_retry),
        )
    result = BatchResult()
    retry_count_for_slot = 0
    last_cleanup_success_count = 0
    try:
        ops.prepare_account_network(0)
        ops.start_browser()
        callbacks.log("[*] Browser started")
        while result.processed_count < settings.count:
            if callbacks.cancelled():
                result.cancelled = True
                break
            callbacks.log(f"--- Starting account {result.processed_count + 1}/{settings.count} ---")
            account = None
            output = None
            continue_batch = True
            try:
                account = register_one_account(
                    callbacks,
                    ops,
                    enable_nsfw=settings.enable_nsfw,
                    max_mail_retry=settings.max_mail_retry,
                )
                output = persist_account_result(account, callbacks, ops)
                result.results.append({"registration": account, "output": output})
                retry_count_for_slot = 0
                result.processed_count += 1
                if output.saved:
                    result.success_count += 1
                    callbacks.log(f"[+] Account registered and saved: {account.email}")
                    if (
                        settings.cleanup_interval > 0
                        and result.success_count % settings.cleanup_interval == 0
                        and result.success_count != last_cleanup_success_count
                        and result.processed_count < settings.count
                    ):
                        _run_cleanup_safely(
                            ops,
                            callbacks,
                            f"{result.success_count} accounts completed; running scheduled cleanup",
                        )
                        last_cleanup_success_count = result.success_count
                else:
                    result.fail_count += 1
                    result.registered_unsaved_count += 1
                    callbacks.log(f"[-] Account registered but not persisted: {account.email}")
                pool_warning = any(
                    isinstance(state, dict) and state.get("enabled") and not state.get("ok")
                    for state in output.pools.values()
                )
                cpa_warning = bool(
                    output.cpa
                    and not output.cpa.get("skipped")
                    and (
                        not output.cpa.get("ok")
                        or output.cpa.get("warning")
                        or output.cpa.get("cpa_copy_error")
                    )
                )
                if pool_warning or cpa_warning:
                    result.postprocess_warning_count += 1
            except ops.cancelled_exception:
                result.cancelled = True
                callbacks.log("[!] Registration stopped")
                continue_batch = False
            except ops.retry_exception as exc:
                retry_count_for_slot += 1
                if retry_count_for_slot <= settings.max_slot_retry:
                    callbacks.log(
                        f"[!] Current account flow is stuck; retry {retry_count_for_slot}/{settings.max_slot_retry}: {exc}"
                    )
                else:
                    result.fail_count += 1
                    result.processed_count += 1
                    retry_count_for_slot = 0
                    callbacks.log(f"[-] Current account reached the retry limit and was skipped: {exc}")
            except Exception as exc:
                result.fail_count += 1
                result.processed_count += 1
                retry_count_for_slot = 0
                callbacks.log(f"[-] Registration failed: {exc}")
            finally:
                _notify_observer(observer, result, account, output, callbacks)

            if not continue_batch or result.cancelled:
                break
            if not _prepare_next_account(result, settings, callbacks, ops):
                break
    finally:
        _run_cleanup_safely(ops, callbacks, "Task complete")
    return result
