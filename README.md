# AOSP Tracker

Tracks updates from AOSP refs and Android Security Bulletins, then optionally posts to Telegram and pushes updated data files.

## What It Updates

- `branches`
- `tags`
- `security_patch`
- helper/generated files: `*_old`, `*_changes`

## Requirements

- `uv`
- Telegram bot token (for posting): `bottoken`
- GitHub token `XFU` only for local/manual `--push` outside GitHub Actions

## Run Locally

Safe parse check:

```bash
uv run aosp_tracker.py --parse-only
```

No side effects:

```bash
uv run aosp_tracker.py --dry-run
```

Post to Telegram + push:

```bash
bottoken=... XFU=... uv run aosp_tracker.py --send-telegram --push
```

## Flags

- `--parse-only`: fetch + parse only, no file updates or side effects
- `--dry-run`: disables Telegram and push
- `--send-telegram`: enables Telegram notifications
- `--push`: enables git commit/push
- `--max-telegram-messages`: safety cap for refs notifications (default: `20`)

## GitHub Actions

Workflow: `.github/workflows/ci.yml`

- Triggers:
  - every 2 hours (`0 */2 * * *`)
  - manual (`workflow_dispatch`)
- Runs:
  - `uv run aosp_tracker.py --send-telegram --push`
- Required secret:
  - `BOTTOKEN`

Push in Actions uses `GITHUB_TOKEN` (`origin`) with `contents: write`, so no `XFU` secret is needed in CI.

## Failure Behavior

- Retries upstream HTTP requests with backoff
- If upstream is down, the run is skipped in GitHub Actions (non-fatal)
- If there are no staged data changes, commit/push is skipped cleanly
