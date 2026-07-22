<div align="center">

[![Grok Register - GUI and CLI registration automation toolkit](assets/banner.png)](https://github.com/AaronL725/grok-register)

Grok Register is a Python registration automation toolkit for automation workflow research, test-environment validation, and personal learning. It supports GUI and CLI modes, temporary email providers, browser flow control, account output, and writing SSO tokens into a grok2api token pool.

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/Interface-GUI%20%2B%20CLI-success.svg" alt="GUI + CLI">
  <img src="https://img.shields.io/badge/Browser-Chromium%2FChrome-4285F4.svg" alt="Chromium/Chrome">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
  <a href="https://linux.do"><img src="https://img.shields.io/badge/Join-linux.do-orange" alt="linux.do"></a>
</p>

<p align="center">
 <a href="https://www.star-history.com/aaronl725/grok-register">
  <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=AaronL725/grok-register&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=AaronL725/grok-register" />
   <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=AaronL725/grok-register" />
  </picture>
 </a>
</p>

</div>

---

> This project is intended only for automation workflow research, test-environment validation, and personal learning. Follow the target site's terms of service, local laws and regulations, and third-party service limits.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [Output Files](#output-files)
- [Reliability Mechanisms](#reliability-mechanisms)
- [FAQ](#faq)
- [Directory Structure](#directory-structure)
- [License](#license)
- [Acknowledgments](#acknowledgments)
- [Star History](#star-history)

## Features

- GUI mode.
- CLI mode without starting the Tk GUI.
- Registration flow runs through Chromium/Chrome browser pages.
- Multi-worker concurrent registration through `concurrent_count`, with an independent browser and isolated profile per worker.
- DuckMail, YYDS, and Cloudflare temporary email providers.
- Verification email polling and parsing.
- Successful accounts are written to `accounts_*.txt` in real time.
- SSO tokens can be written to local or remote grok2api token pools.
- Optional NSFW enablement after registration.
- Asynchronous CPA xAI credential export, using an independent mint browser by default so the registration page is not blocked.
- Log levels (`quiet` / `info` / `debug`) and per-minute creation-rate stats.
- Stuck-page detection, per-account retry, per-account browser restart, and memory cleanup.

## Requirements

- Python 3.9+
- Google Chrome or Chromium
- Network access to the registration page and temporary email APIs

## Installation

Clone the project:

```bash
git clone https://github.com/maxucheng0/grok-register.git
cd grok-register
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy the example config:

```bash
cp config.example.json config.json
```

Then edit `config.json` as needed.

## Configuration

Common options:

| Option | Description |
| --- | --- |
| `email_provider` | Email provider: `duckmail`, `yyds`, or `cloudflare` |
| `register_count` | Target number of registrations for this run |
| `proxy` | Proxy URL; may be empty |
| `enable_nsfw` | Whether to try enabling NSFW after registration |
| `cloudflare_api_base` | Cloudflare temporary email API base URL |
| `cloudflare_api_key` | Cloudflare temporary email API key; leave empty for the default anonymous mode, or set `ADMIN_PASSWORD` for admin mode |
| `cloudflare_auth_mode` | Cloudflare API auth mode; default is `none`, with `bearer`, `x-api-key`, `x-admin-auth`, and `query-key` also supported |
| `cloudflare_path_domains` | Cloudflare domain-list path; default `/api/domains` |
| `cloudflare_path_accounts` | Cloudflare create-address path; anonymous mode uses `/api/new_address`, admin mode uses `/admin/new_address` |
| `cloudflare_path_token` | Cloudflare token path; default `/api/token` |
| `cloudflare_path_messages` | Cloudflare inbox path; default `/api/mails` |
| `defaultDomains` | Default Cloudflare temporary email domain |
| `grok2api_auto_add_local` | Whether to write to a local grok2api token pool |
| `grok2api_local_token_file` | Local grok2api token file path |
| `grok2api_auto_add_remote` | Whether to write to a remote grok2api service |
| `grok2api_remote_base` | Remote grok2api URL, either the site root or the `/admin/api` management API URL |
| `grok2api_remote_app_key` | Remote grok2api app key |
| `sub2api_auto_import` | Whether to create or update a Sub2API account after a CPA file is written |
| `sub2api_base_url` | Sub2API site root, without `/api/v1/admin` |
| `sub2api_admin_api_key` | Sub2API admin API key sent through `x-api-key` |
| `sub2api_group_ids` | Group IDs assigned when creating a new Sub2API account |
| `sub2api_concurrency` | Concurrency assigned when creating a new Sub2API account |
| `sub2api_priority` | Priority assigned when creating a new Sub2API account |
| `sub2api_timeout_sec` | Timeout for each Sub2API admin request |
| `sub2api_preflight_enabled` | Whether to test the Grok Responses API before importing into Sub2API |
| `sub2api_preflight_timeout_sec` | Timeout for the pre-import Responses API test |
| `sub2api_preflight_attempts` | Maximum Responses API attempts before rejecting an account |
| `sub2api_preflight_retry_delay_sec` | Delay between transient preflight failures |
| `sub2api_rejected_dir` | Directory for CPA files that do not pass strict preflight |
| `sub2api_readiness_timeout_sec` | Maximum wait for the post-import Grok usage probe |
| `sub2api_readiness_poll_sec` | Interval between read-only readiness checks |
| `concurrent_count` | Number of concurrent workers; `1` runs sequentially in one browser, `>1` runs multiple browsers concurrently |
| `browser_restart_every` | Extra periodic restart notice interval in accounts; the browser still fully restarts after every account to avoid session residue |
| `cpa_export_enabled` | Whether to export CPA xAI credentials after successful registration |
| `cpa_mint_async` | Whether CPA minting is asynchronous; default `true` uses an independent browser and background thread |
| `cpa_probe_after_write` | Whether to probe API usability after writing the CPA file |
| `log_level` | Log level: `quiet`, `info` (default), or `debug`; `info` hides high-frequency `[Debug]` lines |
| `speed_log_interval_sec` | Creation-rate stats interval in seconds, default `60`; output is similar to `success 9/min` |
| `browser_use_custom_ua` | Whether to force the custom UA from config; default `false`, closer to the local Chrome UA |
| `token_only_file` | Optional extra output file that stores only SSO tokens |

### Cloudflare Temporary Email Anonymous Mode (Default)

By default, Cloudflare email uses the anonymous API from `dreamhunter2333/cloudflare_temp_email` to create addresses and read messages:

- Create address: `POST /api/new_address`
- Read messages: `GET /api/mails`
- Auth mode: `none`
- `cloudflare_api_key`: empty

This is the default path. If you do not have special requirements, keep this configuration:

```json
{
  "email_provider": "cloudflare",
  "cloudflare_api_base": "https://your-worker-api-domain",
  "cloudflare_api_key": "",
  "cloudflare_auth_mode": "none",
  "cloudflare_path_domains": "/api/domains",
  "cloudflare_path_accounts": "/api/new_address",
  "cloudflare_path_token": "/api/token",
  "cloudflare_path_messages": "/api/mails",
  "defaultDomains": "your-inbox-domain.com"
}
```

### Cloudflare Temporary Email Admin Mode (Optional)

If you use `dreamhunter2333/cloudflare_temp_email` and anonymous `/api/new_address` has Turnstile enabled, you can use the admin create-address API instead:

```json
{
  "email_provider": "cloudflare",
  "cloudflare_api_base": "https://your-worker-api-domain",
  "cloudflare_api_key": "your ADMIN_PASSWORD",
  "cloudflare_auth_mode": "x-admin-auth",
  "cloudflare_path_accounts": "/admin/new_address",
  "cloudflare_path_messages": "/api/mails",
  "defaultDomains": "your-inbox-domain.com"
}
```

Address creation calls `/admin/new_address` with `x-admin-auth`. Later inbox reads still use the address JWT returned by the API to call `/api/mails`. In other words, the admin password is only used to create the address, not to read messages.

You can verify the admin create endpoint with the debug script:

```bash
python cf_mail_debug.py --api-base "https://your-worker-api-domain" --auth-mode x-admin-auth --api-key "your ADMIN_PASSWORD" --create-path /admin/new_address --domain "your-inbox-domain.com"
```

### Remote grok2api Pool Configuration

If `grok2api_auto_add_remote` is enabled, `grok2api_remote_base` can be either the site root or the management API URL:

```json
{
  "grok2api_auto_add_remote": true,
  "grok2api_remote_base": "https://your-grok2api-domain",
  "grok2api_remote_app_key": "your app_key"
}
```

Or:

```json
{
  "grok2api_auto_add_remote": true,
  "grok2api_remote_base": "https://your-grok2api-domain/admin/api",
  "grok2api_remote_app_key": "your app_key"
}
```

The program tries `/tokens/add` first and is compatible with `/admin/api/tokens/add`. Legacy full-save endpoints are also supported through `/tokens` and `/admin/api/tokens`.

`config.json` contains personal settings and secrets. Do not commit it to Git.

### Sub2API CPA Import

Sub2API connection settings and secrets are read only from `config.json`:

```json
{
  "sub2api_auto_import": false,
  "sub2api_base_url": "https://your-sub2api-domain",
  "sub2api_admin_api_key": "your-admin-api-key",
  "sub2api_group_ids": [5],
  "sub2api_concurrency": 1,
  "sub2api_priority": 1,
  "sub2api_timeout_sec": 30,
  "sub2api_preflight_enabled": true,
  "sub2api_preflight_timeout_sec": 30,
  "sub2api_preflight_attempts": 3,
  "sub2api_preflight_retry_delay_sec": 5,
  "sub2api_rejected_dir": "cpa_rejected",
  "sub2api_readiness_timeout_sec": 30,
  "sub2api_readiness_poll_sec": 2
}
```

Keep `sub2api_auto_import` disabled while validating a CPA file. The default command is a redacted dry run and does not contact Sub2API:

```bash
python3 sub2api_admin.py import-cpa cpa_auths/xai-user@example.com.json
```

Apply the import after checking the payload:

```bash
python3 sub2api_admin.py import-cpa cpa_auths/xai-user@example.com.json --apply
```

List detected Grok accounts:

```bash
python3 sub2api_admin.py list-grok
```

Imports are upserts. A matching account receives merged credentials only, preserving its existing groups, concurrency, priority, status, and metadata. Ambiguous duplicate matches stop without changing any account.

Before an apply, the importer sends a minimal Grok Responses API request. Only HTTP 200 accounts are imported. HTTP 402 is rejected immediately; transient 403, 408, 425, 429, network errors, and 5xx responses are retried up to three times with a five-second delay. Any account that never returns 200 is moved to `sub2api_rejected_dir` and excluded from hotload copies and server uploads.

After an apply, the importer waits up to 30 seconds for Sub2API's read-only Grok usage probe. Readiness is reported separately from import success as `ready` (200), `payment_required` (402), `forbidden` (403), `rate_limited` (429), `unexpected`, or `pending`. No refresh or test request is triggered by this check.

## Running

### CLI Mode

CLI mode does not start the Tk GUI, but the registration flow still opens Chromium/Chrome browser pages.

```bash
python grok_register_ttk.py cli
```

After the prompt appears, enter:

```text
start
```

Stop the task:

```text
Ctrl+C
```

CLI mode is suitable for long batch runs. The browser fully restarts after each account. The runtime also performs memory cleanup after every 5 successful registrations.

Concurrency example in `config.json`:

```json
{
  "register_count": 20,
  "concurrent_count": 3,
  "log_level": "info",
  "speed_log_interval_sec": 60
}
```

### GUI Mode

```bash
python grok_register_ttk.py
```

GUI mode opens a Tkinter window for adjusting configuration and watching logs. Logs are still filtered by `log_level`, and global creation speed is printed.

## Output Files

Generated during a run:

- `accounts_*.txt`: successful account, password, and SSO token records.
- `mail_credentials.txt`: temporary email credentials.
- `cpa_auths/`: CPA xAI credential JSON files when `cpa_export_enabled` is enabled.
- `cpa_rejected/`: CPA credentials excluded because strict Responses API preflight never returned HTTP 200.
- `.browser_profiles/`: temporary browser profiles for concurrent workers, generated during runtime and ignored by Git.
- `*.log`: optional log files.

These files contain sensitive information and are ignored by `.gitignore`.

## Reliability Mechanisms

- **Full browser restart after every account** through `restart_browser`, avoiding previous-account SSO reuse and `tos-gate` residue.
- Concurrent workers use independent Chromium instances and isolated user-data directories.
- Default asynchronous CPA minting uses an independent browser (`page=None`) so the registration tab is not occupied.
- Cloudflare block-page detection and registration-page reopen retry.
- Memory cleanup after every 5 successful registrations.
- CLI supports `Ctrl+C`: the first press requests a graceful stop, and a second press exits immediately.
- Automatic current-account retry when the final page does not change for too long.
- Automatic email replacement and retry when no verification code is received.
- Global per-minute creation-rate output.

## FAQ

### Why does CLI mode still open a browser?

CLI mode only skips the Tk GUI. Registration pages, Turnstile, verification-code submission, and SSO cookie extraction still require a real browser environment.

### Why do the first concurrent accounts succeed, then later runs cannot find "Sign up with email"?

A common cause is session residue between accounts, such as landing on `grok.com/tos-gate`. The current version fully restarts the browser after every account. Make sure you are using the latest code and do not switch back to lightweight cookie clearing without restart.

### What should I do if NSFW enablement fails?

If the log shows `Cloudflare protection blocked the request, HTTP 403`, the target site's protection blocked the request. The program still saves the account and writes it to grok2api.

### How do I reduce logs or show Debug logs?

Set this in `config.json`:

- `"log_level": "quiet"`: show only success, failure, key warnings, and speed
- `"log_level": "info"`: default, hides `[Debug]`
- `"log_level": "debug"`: full diagnostics

### Why does the GUI count differ from the config?

The GUI count control may have an upper limit. CLI mode reads `register_count` directly from `config.json`.

## Directory Structure

```text
.
|-- grok_register_ttk.py   # Main program for GUI/CLI registration
|-- cpa_export.py          # CPA xAI export entry point
|-- cpa_xai/               # CPA mint / OAuth / schema
|-- sub2api_admin.py       # Sub2API CPA import and admin CLI
|-- cf_mail_debug.py       # Cloudflare email debug tool
|-- config.example.json    # Example configuration
|-- requirements.txt       # Python dependencies
`-- README.md
```

## License

[MIT](LICENSE).

## Acknowledgments

Thanks to [linux.do](https://linux.do), a vibrant tech community where this project is shared and discussed.

## Star History

<a href="https://www.star-history.com/?repos=AaronL725%2Fgrok-register&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=AaronL725/grok-register&type=date&theme=dark&legend=top-left&sealed_token=uCM--S2xEp0n8rFUZHUg6wUJOgYcfO4XEVCIF9UZAT04YjL9YsMEOVOGAOlQfqwsoS7cQef0Rwc1cYCY4lAmTuMmcg-hKzNnx1A7KNekuCXQotFd4YifLIkvJWOEy5vxiREJX80Mwxbr8F-3GfCv0utIsQz_iq19nS57svUqwv0mSosV8OTxqXTLjmsI" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=AaronL725/grok-register&type=date&legend=top-left&sealed_token=uCM--S2xEp0n8rFUZHUg6wUJOgYcfO4XEVCIF9UZAT04YjL9YsMEOVOGAOlQfqwsoS7cQef0Rwc1cYCY4lAmTuMmcg-hKzNnx1A7KNekuCXQotFd4YifLIkvJWOEy5vxiREJX80Mwxbr8F-3GfCv0utIsQz_iq19nS57svUqwv0mSosV8OTxqXTLjmsI" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=AaronL725/grok-register&type=date&legend=top-left&sealed_token=uCM--S2xEp0n8rFUZHUg6wUJOgYcfO4XEVCIF9UZAT04YjL9YsMEOVOGAOlQfqwsoS7cQef0Rwc1cYCY4lAmTuMmcg-hKzNnx1A7KNekuCXQotFd4YifLIkvJWOEy5vxiREJX80Mwxbr8F-3GfCv0utIsQz_iq19nS57svUqwv0mSosV8OTxqXTLjmsI" />
 </picture>
</a>
