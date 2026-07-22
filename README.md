# Grok Register

[![Grok Register - GUI and CLI registration automation toolkit](assets/banner.png)](https://github.com/AaronL725/grok-register)

Grok Register is a Python automation toolkit for workflow research, test-environment validation, and personal learning. It provides GUI and CLI modes, temporary email integrations, Chromium automation, safe account persistence, pending recovery, grok2api token pool integration, CPA xAI OIDC export, and optional Sub2API import.

> This project is intended only for automation workflow research, test-environment validation, and personal learning. Follow the target site's terms of service, local laws, and third-party service limits. Do not use it for abuse, restriction bypassing, or unauthorized commercial activity.

## Features

- Real Chromium or Chrome registration flow with verification code, profile, Turnstile, and SSO cookie handling.
- Temporary email support for DuckMail, YYDS, Cloudflare temporary mail, Cloud Mail, and read-only IMAP catch-all inboxes.
- Immediate account output with atomic pending recovery when the main result cannot be written.
- Optional local and remote grok2api token pool updates.
- Optional CPA xAI OIDC credential export and CLIProxyAPI hotload copying.
- Optional Sub2API import with strict Grok Responses API preflight.
- Browser restart, stuck-flow retry, mailbox replacement, memory cleanup, and safe cancellation.

## Requirements

- Python 3.9+
- Google Chrome or Chromium
- Tkinter for GUI mode; CLI mode works without Tkinter
- Network access to the registration page and selected email provider

## Installation

```bash
git clone https://github.com/RiloArbabillah/grok-auto-register.git
cd grok-auto-register
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
```

Edit `config.json` before starting. This file may contain API keys, JWTs, proxies, and administrator credentials and is ignored by Git.

## Configuration

### Registration and email

| Option | Description |
| --- | --- |
| `email_provider` | `duckmail`, `yyds`, `cloudflare`, `cloudmail`, or `imap` |
| `register_count` | Number of accounts to process |
| `proxy` | Optional main registration proxy |
| `enable_nsfw` | Attempt to enable NSFW after registration |
| `user_agent` | Browser and HTTP User-Agent |

Cloudflare temporary mail uses `cloudflare_api_base`, `cloudflare_auth_mode`, the configured endpoint paths, and `defaultDomains`. YYDS requires `yyds_api_key` or `yyds_jwt`. Cloud Mail requires `cloudmail_api_base`, `cloudmail_public_token`, and `cloudmail_domains`.

### IMAP catch-all inbox

The IMAP provider generates human-name aliases such as `putra-pratama-grok@example.com`. It records the mailbox UID baseline before registration and only scans newer messages for the exact alias, preventing old messages from being reused when a human name repeats.

```json
{
  "email_provider": "imap",
  "imap_host": "imap.example.com",
  "imap_port": 993,
  "imap_ssl": true,
  "imap_user": "inbox@example.com",
  "imap_password": "your-password",
  "imap_folder": "INBOX",
  "imap_address_domain": "example.com",
  "imap_address_suffix": "-grok"
}
```

The mailbox is selected read-only and messages are fetched with `BODY.PEEK[]`; the provider does not delete messages or change flags. The password remains in ignored `config.json` and is never included in `mail_credentials.txt` or logs.

### grok2api pools

| Option | Description |
| --- | --- |
| `grok2api_auto_add_local` | Add SSO tokens to a local pool |
| `grok2api_local_token_file` | Local `token.json`; empty uses the project default |
| `grok2api_pool_name` | `ssoBasic` or `ssoSuper` |
| `grok2api_auto_add_remote` | Add SSO tokens to a remote pool |
| `grok2api_remote_base` | Remote root, `/admin`, or `/admin/api` URL |
| `grok2api_remote_app_key` | Remote administrator app key |
| `grok2api_allow_legacy_full_save` | Allow ETag-protected legacy full-save fallback |

Remote writes prefer the incremental `/tokens/add` endpoint. Legacy full-save is disabled by default to prevent concurrent overwrites and requires an ETag when explicitly enabled.

### CPA xAI OIDC export

| Option | Description |
| --- | --- |
| `cpa_export_enabled` | Export CPA credentials after registration |
| `cpa_auth_dir` | Credential output directory |
| `cpa_copy_to_hotload` | Copy accepted credentials to a CLIProxyAPI auth directory |
| `cpa_hotload_dir` | Hotload destination; required only when copying is enabled |
| `cpa_base_url` | API base URL written into CPA credentials |
| `cpa_proxy` | CPA-specific proxy; empty falls back to `proxy` |
| `cpa_headless` | Run the CPA browser headless |
| `cpa_force_standalone` | Use an independent CPA browser session |
| `cpa_mint_timeout_sec` | Browser authorization timeout |
| `cpa_mint_cookie_inject` | Inject acquired cookies into the CPA session |

### Sub2API import

Enable `sub2api_auto_import` to test and import each generated CPA credential:

```json
{
  "sub2api_auto_import": true,
  "sub2api_base_url": "https://your-sub2api-host",
  "sub2api_admin_api_key": "your-admin-api-key",
  "sub2api_group_ids": [5],
  "sub2api_concurrency": 1,
  "sub2api_priority": 1,
  "sub2api_preflight_enabled": true,
  "sub2api_preflight_timeout_sec": 30,
  "sub2api_preflight_attempts": 3,
  "sub2api_preflight_retry_delay_sec": 5,
  "sub2api_rejected_dir": "cpa_rejected",
  "sub2api_readiness_timeout_sec": 30,
  "sub2api_readiness_poll_sec": 2
}
```

The importer sends a minimal Grok Responses API request before touching Sub2API. Only HTTP `200` passes. HTTP `402` is rejected immediately; transient network errors, `403`, `408`, `425`, `429`, and selected `5xx` responses are retried. A final non-200 result moves the CPA file to `cpa_rejected/` and prevents hotload copying.

After import, readiness is reported as `ready`, `payment_required`, `forbidden`, `rate_limited`, `unexpected`, or `pending`. Readiness does not undo a completed import.

## Usage

Start the GUI:

```bash
python grok_register_ttk.py
```

Start CLI mode:

```bash
python grok_register_ttk.py cli
```

Enter `start` at the prompt. Press `Ctrl+C` to request cancellation and cleanup.

Recover pending account records:

```bash
python grok_register_ttk.py retry-pending <pending-file> [output-file]
```

Import a CPA credential manually with Sub2API:

```bash
python sub2api_admin.py import-cpa cpa_auths/xai-user@example.com.json --apply
```

Omit `--apply` for a redacted dry run.

## Output Files

| Path | Contents |
| --- | --- |
| `accounts_*.txt` | Successfully persisted account records |
| `mail_credentials.txt` | Temporary mailbox credentials |
| `*.pending.jsonl` | Registered accounts awaiting recovery |
| `cpa_auths/xai-*.json` | Generated CPA xAI credentials |
| `cpa_rejected/xai-*.json` | Credentials rejected by strict Sub2API preflight |
| `cpa_auths/cpa_auth_failed.txt` | CPA export failure records |
| `screenshots/` | CPA browser diagnostic screenshots |

## Reliability

- Account output, local token pools, and pending updates use locks and atomic replacement.
- Pending recovery is idempotent and rejects identical input/output paths.
- Remote grok2api fallback requires explicit opt-in and ETag protection.
- Token pool and CPA export failures do not discard a successfully registered account.
- Cleanup and observer failures do not overwrite the original task outcome.

## Architecture

```text
grok_register_ttk.py       GUI, CLI, and compatibility entry point
registration_flow.py       Shared batch orchestration
registration_browser.py    Registration page automation
browser_runtime.py         HTTP, proxy, and Chromium setup
mail_service.py            Temporary email and read-only IMAP providers
account_outputs.py         Account, pending, and token pool persistence
app_config.py              Defaults, loading, saving, and validation
cpa_export.py              CPA export and Sub2API distribution hook
cpa_xai/                   CPA OAuth, browser, schema, proxy, and probe modules
sub2api_admin.py            Sub2API preflight, import, and readiness checks
tests/                      Unit and regression tests
```

## Testing

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

## License

See [LICENSE](LICENSE).
