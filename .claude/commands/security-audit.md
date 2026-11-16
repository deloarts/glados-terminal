---
description: Run a read-only security audit of the codebase
argument-hint: [scope, e.g. bridge | docker | dependencies | a path]
---

Run a READ-ONLY security audit of this repo. Do not modify any source files. Do not commit
anything. Use local tools only — never send source code, diffs, or file contents to any external
service.

This audits the whole codebase. To review only the pending changes on the current branch, use the
built-in `/security-review` skill instead — it's the lighter tool for that job.

## Scope

Arguments given: `$ARGUMENTS`

- If `$ARGUMENTS` is empty, run a full audit of this repo.
- If `$ARGUMENTS` is `docker`, audit only `docker-compose.yml`, `docker/bridge.Dockerfile`,
  `docker/kiosk.Dockerfile`, and `docker/kiosk-entrypoint.sh`.
- If `$ARGUMENTS` is `dependencies`, audit dependency advisories only (skip the other dimensions).
- Otherwise treat `$ARGUMENTS` as a path (e.g. `src/devices`, `src/api`): audit all applicable
  dimensions but restrict findings to that path.

## Dimensions

- **Network exposure** — this process must never be reachable from anywhere but localhost. Check
  `src/infrastructure/config.py`'s `BridgeSettings` default, `docker-compose.yml`'s port mapping
  (must stay `"127.0.0.1:8600:8600"`, never a bare `"8600:8600"`), and that no endpoint/router adds
  a second bind or a reverse-proxy-style passthrough.
- **Auth boundary** — this bridge is explicitly meant to carry no authentication (see CLAUDE.md).
  Flag any code that starts to add one; the finding here is "this shouldn't exist", not "this is
  implemented insecurely".
- **Business logic creep** — flag any endpoint or device handler making a decision that belongs in
  glados-backend (permission checks, workflow state, anything beyond "a device observed X").
- **Injection / input handling** — `POST /debug/simulate`'s payload, and anything a device driver
  parses from raw hardware input (evdev key sequences, serial line payloads) before it becomes an
  event's `data` field.
- **Docker/deployment**: `privileged: true` and the `/dev` bind mount on the bridge service (see
  `docker-compose.yml`'s own comments for the accepted tradeoff and its justification; the audit
  should confirm the tradeoff is still the documented one, not relitigate it), and the bridge
  container running as root (same). The kiosk service must stay unprivileged: only `/dev/dri` and
  `/dev/input`, `no-new-privileges`, Chromium as the `kiosk` user with its sandbox (never
  `--no-sandbox`), and `docker/kiosk-seccomp.json` differing from Docker's default profile only by
  the documented `clone` and `unshare` rules.
- **Secrets** — `.env`/`.env.dev` must never be committed (check `.gitignore`); no credentials of
  any kind belong in this repo at all. The bridge's only secrets are generated or provisioned on the
  device: the device key in the `identity` volume and the terminal key in `.env`.
- **Dependencies** — `poetry run pip-audit` or equivalent if available; report plainly if no such
  tool is installed rather than guessing at results.

## Before starting

Read existing audit output files in `.audit/security-audit-<date>` first. They track residual items
and conventions already accepted from the prior audit.

## Method

1. Fan out parallel read-only Explore (or general-purpose) subagents, one per dimension in scope.
   Each subagent searches and reads only — no edits.
2. Before reporting any finding, verify it: it must cite a concrete `file:line`, and you must
   re-check that file:line yourself (or have the subagent re-check) before it goes in the report.
   Do not report a finding you have not personally verified.

## Output

Write a report to `.audit/security-audit-<today's date>/` (create the folder; use `YYYY-MM-DD` for
today). Structure:
- Findings ranked by severity (critical/high/medium/low).
- Each finding: **Finding** (what, and a concrete attack scenario — who can do what they
  shouldn't), **Files** (file:line references), **Approach** (how it would be fixed), **Risk**,
  **Effort**.
- Describe attack scenarios in prose. Do not write working exploit payloads into the report.

Then send the user a short summary: count of findings by severity and the report path. Do not
include the full report inline unless the user asks.

Hard constraints: this is read-only. Do not edit, create, or delete any source file. Do not run
`git add`/`git commit`. Use only local tools — never transmit code to an external service. The only
files you write are the audit report files.

## Models

Use model `haiku` to investigate the codebase. Minimize token usage. Don't assume anything.
