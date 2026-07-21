# Phase 2: Owner Settings Panel - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the **owner-only web Settings Panel** on the existing FastAPI admin
app: `GET`/`POST /admin/settings` that reads and writes the 19 safe tunables from the
Phase-1 store (`core/settings.py`). A new `require_owner` gate protects the surface,
server-side validation (`settings.set`) gates every write, and secrets/structural values
never appear.

**In scope:**
- `require_owner` dependency in `app/deps.py` — mirrors the `require_editor` choke-point,
  narrowing to `session.discord_id == config.DISCORD_USER_ID`; **fails closed** when
  `DISCORD_USER_ID` is unset (the `0` default must never authorize) (PANEL-01).
- `GET /admin/settings` — renders the tunables grouped by feature from `settings.all_for_ui()`,
  each field typed; no secret ever appears (PANEL-02).
- `POST /admin/settings` — validates every field server-side via `settings.set`, persists,
  returns success/error feedback; an invalid value is rejected before any write (PANEL-03).
- A saved change is read by the bot on its next relevant use; loop-interval changes apply on
  the next cycle/restart (PANEL-04).
- A minimal, additive extension to `core/settings.py::all_for_ui()` to surface render metadata
  (see D-09).

**Out of scope (this phase — permanently per spec, unless noted):**
- Editing secrets or structural values (stay in `.env`).
- Guild-populated channel/role dropdowns → v2 (POLISH-01); v1 uses validated ID inputs.
- Ops console / monitoring / manual triggers (sync-now, view logs).
- Multi-guild, multi-admin, or a dedicated bot-admin role.
- Live loop-interval hot-swap (`change_interval`).

</domain>

<decisions>
## Implementation Decisions

### Form submission model
- **D-01:** The panel uses **Alpine.js + `fetch()`/JSON**, mirroring the existing editor
  surface (`app/templates/editor.html`, `app/static/alpine.min.js`) — NOT the classic
  server-rendered POST from the design spec. Chosen for consistency with the current app's
  interaction feel. This intentionally supersedes the design spec's "POST re-renders the
  whole page" wording; the outcome (validate → write → feedback) is unchanged.
- **D-02:** `GET /admin/settings` renders the **current values server-side** into the Jinja2
  template (values from `settings.all_for_ui()`); Alpine then hydrates and handles save via
  `fetch()`. Same shape as `editor_page` → `editor.html`.
- **D-03:** `POST /admin/settings` accepts a **JSON payload of all fields** and returns JSON:
  `{ok, message}` on success or `{errors: {KEY: reason}}` on failure. The Alpine client shows
  an inline banner and per-field errors. (Follows the editor's `fetch` + `Accept: application/json`
  convention; the existing `_auth_html_or_json` handler already returns JSON for non-navigation.)

### Save & validation atomicity
- **D-04:** **Atomic all-or-nothing save.** The `POST` handler validates **every** submitted
  field first, collecting all failures; if ANY field is invalid it **writes nothing** and
  returns all errors at once (keyed by setting). Only when every field passes does it persist.
  This is the strict reading of PANEL-03 ("rejected before any write, so the bot never reads a
  bad value") and lets the owner see every problem in a single pass.
- **D-05:** Because `settings.set` raises `SettingRejected` on the **first** bad value, the
  handler must **not** rely on it for multi-error collection — validate each field independently
  (catch `SettingRejected` per field to build the error map), then call `settings.set` for all
  fields only after the whole payload is clean. (Exact mechanism — reuse the schema validators
  vs. per-field try/`set` in a dry-run — is planner discretion; the contract is: no partial writes.)

### Field rendering (v1 = validated inputs, no guild dropdowns)
- **D-06:** **Timezone** (`REMINDERS_TZ`) renders as a `<select>` populated from
  `zoneinfo.available_timezones()` (sorted), current value pre-selected. Round-trips through the
  same `_validate_timezone` gate.
- **D-07:** **Role-ID lists** (`*_STAFF_ROLE_IDS`) render as a single **comma-separated text
  input** (e.g. `123, 456`). Matches how `config.py` parses these today and what
  `_validate_role_id_list` already accepts. Repeatable rows were considered and rejected as
  over-built for v1.
- **D-08:** Field types to render come from the 7 `type_tag`s actually present in the schema:
  `snowflake`, `role_list`, `int_range`, `timezone`, `free_string`, `url`, `lang`. **Note:**
  the current 19 tunables include **no boolean/enum toggles** despite the spec mentioning
  checkboxes — no checkbox rendering is needed for v1. `WHISPER_MODEL`/`OLLAMA_MODEL` are free
  strings with a host-availability hint (already in the schema `hint`).

### Store metadata extension (touches the completed Phase-1 module)
- **D-09:** **Extend `core/settings.py::all_for_ui()`** to surface structured render metadata
  so the panel is not forced to duplicate validation bounds. Needed extras: `int_range` `min`/`max`
  (currently baked inside the `_make_int_range` closures — must be exposed as data on the
  `_Setting` descriptor), the timezone option source, and a human `label` per setting. This is an
  **additive** change; `get`/`set`/`seed_defaults` contracts are unchanged. **Phase-1 tests for
  `all_for_ui()` (`tests/test_settings.py`) must be updated** to assert the new keys. Keeping the
  schema as the single source of truth avoids drift between the validator ranges and what the form shows.

### Owner access / auth
- **D-10:** **`require_owner` mirrors `require_editor`** (`app/deps.py`) but checks
  `session.discord_id == config.DISCORD_USER_ID`, returning 403 otherwise. It **fails closed**
  when `DISCORD_USER_ID` is unset/`0` (PANEL-01). Identity comes from the **session only**,
  never the request body (same D-08 IDOR discipline as `require_editor`).
- **D-11:** **The owner authenticates through the existing Discord OAuth flow.** Confirmed
  assumption: the owner also holds the **editor role**, so `login` (which 403s non-editors in
  `app/auth.py`) admits them and establishes a session; `require_owner` then narrows to the owner.
  The login gate is **not** modified. (If this ever ceases to be true, making owner login
  independent of the editor role is the fallback — see Deferred.)

### Discoverability & copy
- **D-12:** Add an **owner-only `⚙ Ajustes / Settings` link** on the editor dashboard
  (`app/templates/editor.html`), rendered only when the session is the owner
  (pass an `is_owner` flag into the `editor_page` template context). The `/admin/settings`
  route stays gated by `require_owner` regardless of the link's visibility.
- **D-13:** Panel labels, hints, banners, and error messages are **bilingual ES–EN**, matching
  the house style used throughout the app (e.g. `_PUBLISH_SUCCESS_COPY`, `_FORBIDDEN_COPY`).

### Claude's Discretion
- Exact route/template file names and Jinja2 structure for the settings page (mirror
  `editor.html` conventions incl. the `?v=<mtime>` CSS cache-buster).
- The precise multi-error collection mechanism in `POST` (D-05) as long as no partial write occurs.
- The internal shape of the `all_for_ui()` metadata extension (D-09) — dataclass fields vs.
  computed dict — provided the schema remains the single source of truth.
- Whether `POST` writes only changed fields or all fields (upsert is idempotent; either is fine
  given the atomic validation in D-04).
- Bilingual copy wording.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design contract
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — the approved design spec;
  **Phase B ("The panel")** is this phase. Note D-01/D-03 intentionally choose Alpine/JSON over
  the spec's classic-POST wording.
- `.planning/REQUIREMENTS.md` — PANEL-01..PANEL-04 (this phase) and POLISH-01 (deferred v2).
- `.planning/phases/01-config-store-consolidation/01-CONTEXT.md` — Phase-1 decisions this phase
  builds on (store API, read-at-use, WAL, secret/structural split).

### The store this panel drives (Phase 1 output)
- `core/settings.py` — `all_for_ui()` (render source, to be extended per D-09), `set()` (the
  validation gate), `get()` (never raises), `SettingRejected`, and the 19-key `_SCHEMA` with
  per-type validators and `hint`s.
- `tests/test_settings.py` — the existing store tests; `all_for_ui()` assertions must be updated
  for the D-09 metadata extension.

### Existing admin-app patterns to mirror
- `app/deps.py` — `require_editor`, the single documented auth choke-point; `require_owner`
  extends this pattern (session-only identity, 403 semantics).
- `app/auth.py` — the OAuth login flow, `has_editor_role`, `POST_LOGIN_REDIRECT`, `_FORBIDDEN_COPY`,
  and where `session["discord_id"]` is set (relevant to D-11).
- `app/main.py` — FastAPI assembly: `Jinja2Templates`, `SessionMiddleware`, the
  `_auth_html_or_json` 401/403 handler, `editor_page` (server-render + Alpine hydrate pattern for
  D-02), the `fetch`/JSON save endpoints (`/editor/save` pattern for D-03), route registration,
  loopback bind.
- `app/templates/editor.html`, `app/templates/login.html` — template + Alpine conventions to
  mirror (login.html is what the 401/403 handler renders).
- `app/static/alpine.min.js`, `app/static/editor.css` — vendored Alpine (not CDN) and the CSS the
  new page should visually align with.
- `config.py` — `DISCORD_USER_ID` (owner gate), and the safe/structural/secret split.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `settings.all_for_ui()` / `set()` / `get()` — the panel's entire data layer already exists;
  Phase 2 renders/writes through them (plus the D-09 metadata extension).
- `require_editor` (`app/deps.py`) — near-exact template for `require_owner`.
- `editor_page` + `editor.html` (`app/main.py`) — the server-render-then-Alpine-hydrate pattern
  and the `?v=<mtime>` CSS cache-buster to copy for `GET /admin/settings`.
- `/editor/save` (`app/main.py`) — the `fetch`/JSON POST + JSON-error-body pattern to copy for
  `POST /admin/settings`.
- `_auth_html_or_json` exception handler — already renders `login.html` for a browser hitting a
  401/403, so a non-owner navigation gets the login/forbidden page (no bare JSON).
- Bilingual copy constants (`_FORBIDDEN_COPY`, `_PUBLISH_SUCCESS_COPY`, …) — the ES–EN style to
  follow (D-13).

### Established Patterns
- Session-only identity, never from the request body (D-08 IDOR discipline) — `require_owner`
  must follow it.
- Parameterized SQL + schema allowlist in `settings.set` (a key not in `_SCHEMA` can never be
  written) — the panel inherits this protection; do not bypass it.
- Fail-fast/fail-closed config posture (`validate_config`, the owner-gate `0`-default rule).
- `SessionMiddleware`: `https_only=True`, `same_site="lax"`, short TTL — CSRF mitigation for
  state-changing POSTs is SameSite=Lax + session-only identity (no hand-rolled CSRF token), same
  as the editor saves.

### Integration Points
- New `/admin/settings` GET+POST routes registered in `app/main.py`.
- New `require_owner` in `app/deps.py`.
- `editor_page` template context gains an `is_owner` flag; `editor.html` gains the owner-only link
  (D-12).
- `core/settings.py::all_for_ui()` (+ `_Setting` descriptor) extended for render metadata (D-09).
- The bot process picks up saved values via `settings.get` at read-at-use sites already migrated
  in Phase 1 (no bot-side change needed; loop intervals apply next cycle).

</code_context>

<specifics>
## Specific Ideas

- Mirror `editor.html`/`editor_page` as closely as possible so the settings page reads as part of
  the same app (same CSS, same Alpine idioms, same `?v=<mtime>` cache-buster, same JSON-error UX).
- The atomic-save error response should be a map `{KEY: reason}` so the Alpine client can place
  each `SettingRejected.reason` inline next to its field.
- Group order and grouping in the form come straight from `all_for_ui()` (gallery, reviews,
  reminders, jinxxy, meetings, forum) — don't invent a new grouping.

</specifics>

<deferred>
## Deferred Ideas

- **Guild-populated channel/role dropdowns** (fetch names via the bot token) → v2 (POLISH-01);
  v1 stays on validated ID inputs.
- **Making owner login independent of the editor role** — only if the owner ever stops holding
  the editor role (D-11 fallback). Not built now.
- Editing secrets/structural values, ops console/monitoring, multi-admin, live interval hot-swap
  → out of scope permanently per spec/REQUIREMENTS.md.

None of the above expanded this phase's scope — discussion stayed within the panel domain.

</deferred>

---

*Phase: 02-owner-settings-panel*
*Context gathered: 2026-07-21*
