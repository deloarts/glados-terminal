---
description: Run a read-only codebase audit across the dimensions below
argument-hint: [dimension or scope, e.g. security, devices, src/devices]
---

Run a READ-ONLY audit of this repo. Do not modify any source files. Do not commit anything.

## Scope

Arguments given: `$ARGUMENTS`

- If `$ARGUMENTS` names a dimension (see list below), audit only that dimension across the whole
  repo.
- If `$ARGUMENTS` names a path (e.g. `src/devices`), audit all applicable dimensions but restrict
  findings to that path.
- If `$ARGUMENTS` is empty, run a broad audit across all dimensions.

Dimensions:
- architecture / layering (`api → events → devices`, never the reverse)
- localhost-only / no-business-logic boundary (see CLAUDE.md's hard rules)
- device failure isolation (a device crash must never take the daemon down)
- typing hygiene (mypy strict)
- event bus correctness (slow-consumer isolation, no unbounded growth)
- Docker/deployment (`docker-compose.yml`, both Dockerfiles, the `network_mode: "service:bridge"`
  linkage between `bridge` and `kiosk`)
- security
- logging discipline
- tests
- dead code + dependencies
- industry standard

## Before starting

Read existing audit output files in `.audit/audit-<date>` first. They track residual items and
conventions already accepted from the prior audit.

## Method

1. Fan out parallel read-only Explore (or general-purpose) subagents, one per dimension in scope.
   Each subagent searches and reads only — no edits.
2. Before reporting any finding, verify it: it must cite a concrete `file:line`, and you must
   re-check that file:line yourself (or have the subagent re-check) before it goes in the report.
   Do not report a finding you have not personally verified.

## Output

Write a report to `.audit/audit-<today's date>/` (create the folder; use `YYYY-MM-DD` for today).
Structure:
- Findings ranked by severity (high/medium/low).
- Each finding in the established work-package style: **Findings** (what and why), **Files**
  (file:line references), **Approach** (how it would be fixed), **Risk**, **Effort**.

Then send the user a short summary: dimension(s) covered, count of findings by severity, and the
report path. Do not include the full report inline unless the user asks.

Hard constraints: this is read-only. Do not edit, create, or delete any source file. Do not run
`git add`/`git commit`. The only file you write is the audit report itself.

## Models

Use model `haiku` to investigate the codebase. Minimize token usage. Don't assume anything.
