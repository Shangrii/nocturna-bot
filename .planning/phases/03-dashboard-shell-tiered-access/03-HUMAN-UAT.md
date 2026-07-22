---
status: partial
phase: 03-dashboard-shell-tiered-access
source: [03-VERIFICATION.md]
started: 2026-07-22
updated: 2026-07-22
---

## Current Test

[awaiting live-environment human testing — accepted-in-lieu-of via automated matrix on 2026-07-22]

## Tests

### 1. Live Discord OAuth 3-tier walkthrough
expected: With a real `.env` (OAuth client + session secret + bot token) and the bot running, `python -m app.main` on 127.0.0.1:8770 — an owner logs in and lands on /overview with all 7 sections unlocked (200); a Manager (role 1453560115423875205) gets 200 on the 6 operational modules and an in-shell 403 (forbidden.html) on Settings; an editor-only user gets in-shell 403 on all dashboard sections but 200 on /editor. Per-tier post-login redirect routes correctly.
result: [accepted-in-lieu-of — owner approved automated TestClient access-matrix coverage on 2026-07-22; residual is only the live OAuth round-trip, unchanged from prior phases]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
