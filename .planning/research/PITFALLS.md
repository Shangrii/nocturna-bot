# Pitfalls Research

**Domain:** Multi-tier admin dashboard bolted onto an existing Discord bot + FastAPI app,
sharing a single sqlite file as the only cross-process channel (v2.0 Staff Dashboard)
**Researched:** 2026-07-21
**Confidence:** HIGH (grounded directly in this repo's `core/db.py`, `core/settings.py`,
`app/deps.py`, `cogs/gallery.py`, `cogs/reminders.py`, `app/main.py`; MEDIUM/LOW flagged
separately where general web/Discord-API knowledge fills a gap)

## Critical Pitfalls

### Pitfall 1: The editable role→tier mapping locks out the owner or lets Manager grant Manager

**What goes wrong:**
Settings becomes owner-only (already true today per `require_owner`), but the NEW
role→tier mapping table it edits is exactly the kind of data structure that invites three
concrete failure modes once it's a normal CRUD form instead of a fixed config: (1) the owner
edits the Manager role mapping and, through a bug or a bad edit, no role (including any role
the owner personally holds) maps to `owner`/`Manager` any more — the owner is now the ONLY
identity with dashboard access (by `DISCORD_USER_ID`), which is safe, but a Manager
accidentally editing themselves out is a lockout with no panel-based recovery; (2) if tier
assignment is ever exposed to Manager (even read-only-looking UI that has a working POST
behind it), a Manager can grant the Manager tier to another role or to themselves at a
higher level, i.e. horizontal-to-vertical privilege escalation; (3) the tier check and the
owner check silently diverge — `require_owner` already hard-codes identity-equality against
`config.DISCORD_USER_ID` (int vs str, Pitfall 4 noted in that module's own docstring), and a
NEW `require_tier("manager")` dependency that re-derives "am I Manager" from a DIFFERENT
source (role IDs fetched live from Discord vs. a cached session value) can disagree with
`require_owner` about who the owner even is, producing an owner who fails the Manager check
or a Manager who accidentally satisfies the owner check.

**Why it happens:**
The codebase's whole owner-gate discipline (`require_owner` fails closed on unset/`0`
`DISCORD_USER_ID`, `str()`-normalizes both operands) was purpose-built for a SINGLE boolean
gate. Generalizing it to N tiers with an editable mapping multiplies the trust boundary:
every new tier check needs the SAME fail-closed discipline, and the mapping itself becomes
writable data that must be validated with the same rigor as `core/settings.py`'s allowlisted
schema — but it's tempting to treat "which role is Manager" as just another settings row and
skip the write-time invariant that role→tier assignment can never be self-serve for the tier
doing the editing.

**How to avoid:**
- Keep tier-assignment writes owner-gated ONLY (`require_owner`), never delegate to Manager
  — this is already the locked decision in PROJECT.md ("permission edits are a trust-boundary
  change so they stay owner-gated"); do not let a later phase quietly relax it for UX reasons.
- Derive tier from a single function that all dependencies call (`resolve_tier(discord_id,
  member_roles) -> "owner"|"manager"|"editor"|None`), with `owner` checked FIRST via the exact
  same `DISCORD_USER_ID` fail-closed comparison `require_owner` already uses — never let a
  second code path re-implement the owner check.
- Validate the mapping at write time: reject a POST that would leave zero roles mapped to
  `manager` only if that's actually unsafe for the product (it may be fine — owner-only is a
  valid state); but ALWAYS reject a POST that attempts to write `owner` as an assignable tier
  for a role (owner must stay the single hard-coded Discord user id, never a role).
- Add a server-side guard: the tier-assignment endpoint itself requires `require_owner`, and
  additionally the request body's target tier can never include `"owner"` as a value — enforce
  via the same allowlist validator pattern `core/settings.py::validate_only` already uses.
- Provide a break-glass recovery path independent of the panel (e.g. the owner can still fix
  a bad mapping via a `.env`/DB one-liner on the host) since the owner is defined by
  `DISCORD_USER_ID`, not by the editable mapping — this means owner lockout is IMPOSSIBLE by
  construction as long as tier-assignment never touches the owner check. Document this loudly
  so nobody "simplifies" the owner check to route through the same mapping table later.

**Warning signs:**
- A PR that makes `require_owner` read from the SAME table the Manager-tier mapping writes to.
- Any endpoint where the tier-assignment POST doesn't call `require_owner` explicitly (e.g. it
  reuses a generic "require_manager_or_higher" that was meant for operational actions, not
  trust-boundary changes).
- Tests that only cover "Manager cannot see Settings" but never test "Manager POST to the
  tier-assignment endpoint directly is 403" (UI hiding is not authorization).

**Phase to address:**
Tiered Access / Editable Permissions phase (the phase implementing role→tier mapping in
Settings) — must ship with explicit tests for self-elevation, Manager-granting-Manager, and
owner-lockout-impossibility before any other tier-gated feature is built on top of it.

---

### Pitfall 2: Check-then-act publish/unpublish race between the panel and the live Discord reaction flow

**What goes wrong:**
`cogs/gallery.py::_publish` and `_unpublish` are check-then-act: `_publish` reads
`message.reactions` for the bot's own 🟢 marker, and if absent, proceeds to build entries and
call `github_publish.publish_message`. That "is it already published" check and the actual
commit are NOT atomic. Today this window is nearly unreachable because the only actor is a
single Discord reaction event per message. Once the panel's Gallery approval queue offers its
OWN "Approve" button that also calls into the publish path (either by simulating the ✅
reaction or by calling a shared publish function directly), the SAME message can be approved
from Discord (staff reacts ✅) and from the panel (someone clicks Approve) close enough in
time that BOTH read "not yet published" before either finishes — resulting in two
`github_publish.publish_message` calls, i.e. a double commit / duplicate gallery.json entries
for one message. The mirror case (🌙 unpublish from Discord racing a "Remove" click in the
panel) can double-call `remove_message`, which is more tolerant (removal is closer to
idempotent) but can still produce confusing duplicate replies/log noise or, if the remove
logic isn't perfectly idempotent for partial states, an inconsistent gallery.json.

**Why it happens:**
The existing idempotency guard (`if any 🟢 marker: return`) was designed for a SINGLE control
surface (Discord reactions) where the realistic race window is one human clicking a reaction
twice, not two DIFFERENT processes racing to publish the same message. Adding the panel as a
second writer against the same "is this message published" question, without a shared lock or
a single-writer chokepoint, reintroduces the exact TOCTOU (time-of-check-to-time-of-use) gap
the marker-reaction check was never hardened against.

**How to avoid:**
- Route BOTH the Discord reaction handler and the panel's Approve/Remove actions through the
  SAME single function (`_publish(message)` / `_unpublish(message)` in the gallery cog, called
  in-process) rather than having the panel re-implement "check 🟢, then call
  `github_publish.publish_message`" independently — this at least collapses two divergent
  implementations into one, but does not remove the race by itself if the panel action reaches
  the bot process asynchronously (see Pitfall 3 on the sqlite-only channel).
  since the panel is a SEPARATE PROCESS from the bot, the panel cannot call `_publish` directly
  in-process. The realistic implementation is: panel writes an "approve requested" row/flag to
  sqlite; the bot's gallery cog (which already owns the Discord connection) is the ONLY writer
  that ever calls `github_publish.publish_message`/`remove_message`. The panel then either
  simulates the same reaction event (adds the ✅/🌙 reaction via the bot's own token — requires
  the panel to know the bot token or delegate through the bot, see Pitfall 4) or the bot polls a
  small "pending panel action" table and performs the publish itself. Either way, publish
  MUST be single-writer: only the bot process ever calls `github_publish.publish_message`.
- Make the 🟢-marker check-and-commit sequence effectively atomic per message by serializing it:
  a per-message in-process lock (e.g. an `asyncio.Lock` keyed by `message.id`) around the
  check+publish+mark-published sequence closes the race for actions that both arrive inside the
  bot process (Discord reaction handler + a bot-side consumer of panel-approve requests), even
  though sqlite itself can't provide this guarantee across processes.
  race is closed by construction rather than by chance.
- For the panel side, treat "approve" as a REQUEST, not a fire-and-forget direct action, and
  surface the panel UI's pending/settled state from the SAME source of truth the reaction flow
  already uses (🟢 marker / gallery.json entries) — never from a separate "panel thinks it's
  approved" flag that can drift from Discord's actual state.

**Warning signs:**
- Two different code paths (one in `cogs/gallery.py`, one in a new `app/` route or panel
  action handler) that both call `github_publish.publish_message` or `remove_message` directly.
- Duplicate gallery.json entries for the same message id observed in production, or GitHub
  commit history showing two publish commits for one Discord message within seconds of
  each other.
- The panel's "Approve" button ever sends its own commit through a helper that doesn't first
  ask the single source of truth (the bot process) whether the message is already published.

**Phase to address:**
Gallery approval queue phase — the parity requirement ("approve/remove photos with parity to
the ✅/🌙 reaction flow") should be read as "the panel is a second INPUT to the same single
publish path," not "the panel independently re-implements publish." Design the cross-process
hand-off (see Pitfall 3) before writing the panel's approve/remove endpoints.

---

### Pitfall 3: sqlite cross-process channel silently degrades as the panel adds write volume

**What goes wrong:**
`core/db.py::_get_conn()` opens a fresh connection per call and sets `PRAGMA
journal_mode=WAL` on every connection, which correctly solves the v1.0 reader/writer
contention (bot reads settings while the panel writes them, at low frequency: an owner edits
occasionally). WAL solves READER/writer blocking, but SQLite still allows only ONE writer at
a time — WAL does NOT solve writer/writer contention. v2.0 turns the panel into a much more
frequent writer: gallery approve/remove, reviews approve/remove, reminders CRUD + pause/resume,
Jinxxy manual sync-trigger writes, and meeting summary edits can all fire in bursts (e.g. a
Manager triage-clearing a backlog of 15 pending gallery photos in one sitting, each click a
separate write), overlapping with the bot's OWN writes (gallery backfill cursor advances,
reminders scheduler's `set_next_fire`/`delete_reminder` on every 1-minute tick, presence
updates). No connection here sets `PRAGMA busy_timeout` explicitly (Python's `sqlite3.connect`
default busy timeout is 5 seconds, which is adequate at today's volume but not a documented,
intentional choice) and there is no retry/backoff wrapper around a `sqlite3.OperationalError:
database is locked`. As dashboard write volume grows, occasional "database is locked" errors
surfacing as raw 500s (or worse, silently swallowed inside a broad `except Exception` and
logged as a different failure) become likely, and they will look like flaky, hard-to-reproduce
bugs because they depend on timing, not logic.

**Why it happens:**
The `_get_conn()` fresh-connection-per-call idiom was designed for LOW-frequency, SHORT
writes (an owner tweaking a handful of settings, a bot cog updating a single cursor row once
in a while). It was never load-tested against a dashboard UI encouraging rapid consecutive
clicks (approve, approve, approve...) from a human, each opening/closing its own connection
and transaction, racing the bot's periodic writes on unrelated tables in the SAME file.

**How to avoid:**
- Explicitly set `conn.execute("PRAGMA busy_timeout = 5000")` (or higher, e.g. 10000ms) on
  every connection alongside the existing `journal_mode=WAL` pragma, and treat the timeout
  value as a deliberate, documented decision rather than an implicit Python default.
- Wrap write paths that are newly panel-triggered (reminders CRUD, gallery/reviews
  approve/remove, meeting edit+republish) in a small retry-with-backoff helper that catches
  `sqlite3.OperationalError` matching "database is locked" and retries 2-3 times before
  surfacing a real error to the panel user — this converts a rare timing collision into an
  invisible retry instead of a user-facing 500.
- Keep every transaction SHORT: never hold a connection open across an `await` that talks to
  Discord's API or GitHub (the existing idiom of "connect, one statement, close inside `with`"
  already does this correctly — preserve it; do not introduce a "hold the connection across
  the whole approve flow" pattern for convenience).
- Load-test the busiest realistic scenario (a Manager triage session clearing an approval
  queue) against the bot running its own 1-minute reminders tick concurrently before shipping,
  not after a production report of intermittent 500s.

**Warning signs:**
- Any log line containing `database is locked` in either process's logs.
- Panel actions that "sometimes" fail and succeed on retry with no code change.
- A code review introducing a write path that does more than one `_get_conn()` round trip
  per user action, or that performs a slow operation (image encode, GitHub API call, Discord
  API call) INSIDE an open `with _get_conn() as conn:` block.

**Phase to address:**
Should be addressed once, early, as a small cross-cutting hardening task before or alongside
the Gallery approval queue phase (the first phase that meaningfully increases write
frequency) — not deferred to "whichever phase happens to hit it first" since every later
phase (Reminders CRUD, Reviews, Meetings edit) inherits whatever `_get_conn()` looks like at
that point.

---

### Pitfall 4: Reintroducing Discord bot credentials into the admin app breaks the v1 credential-isolation invariant

**What goes wrong:**
v1 explicitly kept `BOT_TOKEN` out of the admin app's process — it used a separate,
narrower OAuth flow (`has_editor_role` does its own bot-token REST read today per
`app/deps.py`, so a LIMITED bot-token capability may already partially exist, but the panel's
own identity/session flow does not carry the token as a general-purpose credential). v2.0's
"Discord API calls from the web app" requirement (resolve #channel/@role names in Settings)
and any panel-initiated action that must reach Discord (e.g., simulating an approve reaction,
or fetching current guild roles for the tier-assignment UI) needs SOME Discord credential in
the admin app process. The pitfall is treating this as "just add `BOT_TOKEN` to the admin
app's `.env` and call the REST API directly" without re-deriving the blast radius: a credential
that can read/write full guild state (roles, channels, messages) now lives in a second
process, doubling the attack surface for a token leak (logs, error pages, dependency
supply-chain compromise of the FastAPI app's dependencies) that v1's design deliberately
avoided. It also reopens the exact secret-exposure risk `core/settings.py`'s allowlist schema
was built to prevent for CONFIG values — but for a credential, not a config value.

**Why it happens:**
It's the path of least resistance: the bot process already has full bot-token REST access, so
"just give the admin app the same token" looks like the fastest way to unblock name
resolution and panel-initiated actions, especially under deadline pressure once the dashboard
shell is otherwise done.

**How to avoid:**
- Scope whatever Discord credential the admin app gets to the MINIMUM capability actually
  needed. Read-only guild/channel/role name resolution needs only `GUILDS`/read scopes — if a
  bot token is used, treat it as read-mostly and NEVER let the admin app hold write-capable
  Discord REST calls (message send, reaction add, role edit) directly; those stay
  bot-process-only, reached via the sqlite hand-off (see Pitfall 3) or a narrow internal RPC,
  not by handing the token to a second process.
  local network-only) IPC to ask the bot process to perform the write, rather than the panel
  process holding write-capable Discord credentials at all — this preserves the spirit of the
  v1 "no bot credentials in the admin app" stance for anything beyond read-only name resolution.
- If a token IS added to the admin app for name resolution, treat it with the SAME discipline
  `core/settings.py` already applies to secrets: never log it, never render it, never let it
  round-trip through a form, and add it to the existing "never rendered" secrets list alongside
  `BOT_TOKEN`/`GITHUB_PAT`/`JINXXY_API_KEY`/`SESSION_SECRET` in developer-facing docs so a
  future contributor doesn't accidentally add a debug endpoint that echoes it.
- Cache resolved names aggressively (see Pitfall 5) so the credential is exercised rarely
  (batch-resolve on Settings page load, not per-row on every render), shrinking both the rate
  limit exposure and the number of code paths that touch the credential.
- Document this as an explicit, reviewed scope decision (the PROJECT.md Key Decisions table
  already flags it as "Pending (v2.0)") — get sign-off on exactly which Discord API
  capabilities the admin app gains before writing the code, not after.

**Warning signs:**
- A `.env` value named anything like `BOT_TOKEN`/`DISCORD_TOKEN` appearing in `app/`'s config
  reads where it wasn't read before.
- Any panel endpoint that calls `discord.py`/raw Discord REST directly to WRITE state (send a
  message, add a reaction, edit a role) instead of going through the bot process.
- The credential appearing in a stack trace, error page, or log line during manual testing.

**Phase to address:**
Settings phase (Discord-API-resolved readable names) is the first phase that NEEDS any
Discord credential in the admin app — decide and document the exact scope there, before the
Gallery/Reviews approval-queue phases build panel-initiated actions that might be tempted to
reuse whatever credential Settings introduced for a purpose it wasn't scoped for.

---

### Pitfall 5: Discord API rate limits and stale cached names surface as silently-wrong UI, not errors

**What goes wrong:**
Discord's REST API enforces a global 50 requests/second per-token limit plus per-route
bucket limits; resolving every channel/role ID shown in the dashboard (Settings' 19 tunables
alone reference ~7+ distinct snowflakes, and a growing role→tier mapping list adds more) on
every page render, or per-row instead of batched, risks 429s under normal admin traffic
patterns (multiple staff opening the dashboard around the same time) even though the ABSOLUTE
request volume is small — a burst is enough. Separately, if resolved names are cached (which
they should be, per Pitfall 4's mitigation), a stale cache means the dashboard shows an old
channel/role name after a rename in Discord, which is a silent correctness bug (the ID is
still correct and functional; only the human-readable label lies) rather than a crash — the
kind of bug that goes unnoticed until an owner acts on a wrong assumption ("that's the #old-name
channel, not the one I renamed to #announcements").

**Why it happens:**
Per-row name resolution (fetch-on-render for every ID shown) is the natural first
implementation once "call Discord API to resolve names" is the requirement, because it's the
simplest code to write; batching and caching are both extra work that's easy to defer, and a
cache without a TTL/invalidation strategy is easy to ship as "cache forever" for expedience.

**How to avoid:**
- Batch-resolve: fetch the guild's full role list and channel list ONCE per Settings page
  load (`guild.fetch_roles()` / the channels list endpoint, each a single call) and resolve
  every ID shown on that page from the in-memory batch, rather than one REST call per
  ID/per-row.
- Cache the resolved name↔ID map with a short TTL (minutes, not hours) and a visible
  "resolved as of ..." or a manual refresh affordance, so staff can tell the difference
  between "the ID is stale/wrong" and "the cached NAME is stale" — never let an unresolvable
  ID silently show blank; fall back to showing the raw snowflake (which is exactly today's v1
  behavior) when resolution fails or rate-limits.
- Respect `Retry-After` on a 429 with real backoff, and never retry a 429 synchronously inside
  a page request (that turns one slow admin page load into a cascading multi-second stall) —
  degrade to raw IDs immediately on a 429 rather than blocking the page.
- Since discord.py (bot process) already has these roles/channels in its gateway cache for
  free, prefer having the BOT process resolve names (which touches the cache, not the REST
  API, for anything it has already seen via the gateway) and hand the resolved map to the
  panel via sqlite/a small read endpoint, instead of the admin app independently hitting
  Discord's REST API cold for every request — this also reduces how much Discord credential
  capability the admin app needs (reinforces Pitfall 4's minimal-scope goal).

**Warning signs:**
- 429 responses in logs correlated with multiple staff opening Settings/the dashboard at once.
- A "channel name" cache with no expiry field or invalidation code path at all.
- Name resolution implemented as N sequential REST calls in a template-rendering loop.

**Phase to address:**
Settings phase (Discord-API-resolved readable names) — same phase as Pitfall 4, since the
caching/batching strategy and the credential-scope decision are two halves of the same
design choice.

---

### Pitfall 6: SameSite=Lax + session-only identity is NOT free CSRF coverage for every new dashboard action shape

**What goes wrong:**
The existing accepted mitigation (`SessionMiddleware` with `same_site="lax"` + every
protected endpoint resolving identity from `request.session` only, never the request body) is
explicitly documented as sufficient for `/editor/save` and `/admin/settings` because BOTH are
POST-only, state-changing endpoints. `SameSite=Lax` blocks cross-site POST/PUT/DELETE
requests from being sent with the session cookie attached, but it does NOT block a cross-site
TOP-LEVEL GET navigation (that's the whole point of "Lax" vs "Strict" — it exists to let the
OAuth redirect back in). A new dashboard action implemented as a GET (e.g. a convenience
"quick approve" link `<a href="/gallery/approve/123">`, or a bookmarkable pause/resume toggle
using GET for simplicity) silently steps outside the mitigation the rest of the app relies on
— an attacker-controlled page (or an image tag, or a link in a Discord embed staff might
click) could trigger a state-changing GET while the staff member's session cookie is valid,
with SameSite=Lax doing nothing to stop it.

**Why it happens:**
GET-triggered actions are a common shortcut for "make it a simple link instead of a form with
a button" in dashboard UIs (pagination-style "approve" links, `?action=pause&id=5` query-param
toggles) precisely because they're easier to wire up than a POST form or a `fetch()` call with
a body — and the existing CSRF reasoning in this codebase is documented per-endpoint, not
enforced by a project-wide lint rule, so a new contributor unaware of the SameSite=Lax
rationale can introduce a GET-based mutation without realizing they've broken the invariant.

**How to avoid:**
- Enforce, as a hard project convention (and ideally a test), that EVERY state-changing
  dashboard action (approve/remove/pause/resume/delete/edit/re-publish/sync-now/tier-assign)
  is a POST (or PUT/PATCH/DELETE) — never a GET, never a query-param-triggered mutation.
- Keep the identity-from-session-only discipline (`require_editor`/`require_owner`/whatever
  new `require_tier` dependency) on EVERY new endpoint — no new endpoint should ever accept a
  target discord_id/slug/role from the request body or query string as the AUTHORIZING
  identity, only as the subject of the action (mirrors the existing D-08 IDOR discipline).
- If the dashboard adds any cross-origin API consumption in the future (a separate SPA origin,
  a mobile client), revisit CSRF strategy then — the SameSite=Lax mitigation implicitly
  assumes same-origin form/fetch submission, which holds for a server-rendered Jinja dashboard
  but would NOT hold if v2.0 quietly grows a JSON API consumed cross-origin.
- Add one project-level test that enumerates all registered routes and asserts every
  state-mutating one is not `GET`-only, so this becomes a CI-caught regression, not a
  code-review-catches-it-or-doesn't gamble across a much larger v2.0 route surface than v1.0's
  handful of endpoints.

**Warning signs:**
- Any `@app.get(...)` handler whose body calls a `db.update_*`/`db.delete_*`/
  `github_publish.*` write function.
- A UI element that is an `<a href>` link rather than a `<form method="post">` or a
  `fetch(..., {method: "POST"})` for anything that changes state.
- A "resend the same link to re-trigger the action" bug report — a strong signal the action
  was GET-based (POSTs aren't naturally re-triggerable by revisiting a URL).

**Phase to address:**
Dashboard shell phase (establish the POST-only convention and the route-enumeration test
FIRST, before any module-specific action endpoints exist) — then every subsequent phase
(Gallery, Reviews, Reminders, Jinxxy, Meetings) inherits and is checked against it.

---

### Pitfall 7: The reminders scheduler can silently undo or outrun a concurrent panel edit/delete

**What goes wrong:**
`RemindersCog._process_due` reads the full due-reminder row ONCE (`db.due_reminders(now)`),
does async work (Discord send via `_deliver`), and only THEN writes back — either
`db.delete_reminder(r["id"])` (one-off) or `db.set_next_fire(r["id"],
compute_next(r, now).isoformat())` (recurring), where `compute_next` recomputes strictly from
the FIELDS ALREADY IN `r` (the pre-fetch snapshot: `frequency`, `weekday`, `day_of_month`,
`hour`, `minute`). If the panel's reminder-edit endpoint runs concurrently — between the
scheduler's fetch and its write-back — two distinct bugs are possible: (1) **stale
next-fire overwrite**: a staff member edits a weekly reminder's weekday via the panel (say,
Monday → Friday) at the same moment the scheduler is mid-tick for that same row; the
scheduler's `set_next_fire` write only touches the `next_fire_utc` column, but it computes
that value from the OLD (pre-edit) `weekday` it already had in memory — so it overwrites the
panel's just-saved edit's implied next occurrence with one computed from the STALE schedule,
and the reminder fires on the old schedule despite the panel showing (and having persisted)
the new one; (2) **delete-then-fire-anyway**: a staff member deletes a reminder via the panel
right as the scheduler has already fetched it as due; the scheduler still sends the Discord
message (using the content it already has in memory) and then calls `set_next_fire`/
`delete_reminder` against a row that's ALREADY gone — which silently no-ops (zero rows
affected, no error raised) — so a deleted reminder still fires exactly once after the staff
member believed they'd stopped it.

**Why it happens:**
There is no version/optimistic-concurrency column and no transaction spanning "read the due
row" through "act on it" through "write the outcome" — by design, per the module's own
documented crash-semantics ("advance-after-send... a crash between the two causes a rare
missed advance... healed by the next tick"), which was reasoned about ONLY against the
scheduler's own crash risk, not against a second writer (the panel) mutating the same row
mid-flight. Introducing panel-initiated CRUD on the exact table the scheduler polls every
minute is new: v1 had no second writer to this table at all.

**How to avoid:**
- Add a lightweight optimistic-concurrency guard: an `updated_at`/`version` column bumped by
  every panel write; `set_next_fire`/`delete_reminder` become conditional
  (`WHERE id = ? AND version = ?`) using the version the scheduler captured at fetch time —
  if the row changed underneath it (0 rows affected), the scheduler logs "reminder changed
  mid-fire, skipping stale write-back" and lets the FRESH row's state stand, rather than
  clobbering it.
- For the delete race specifically, this doesn't prevent the "fires once more after delete"
  behavior (the message was already sent before the delete could be observed) — treat that as
  an accepted, documented risk (same spirit as the existing `T-05-11`-style accepted-risk
  entries elsewhere in this codebase) rather than something to eliminate, and surface it in
  the panel's delete-confirmation copy if a reminder is currently within, say, one scheduler
  tick of firing ("this reminder may already be mid-send; deleting stops future occurrences").
- Alternative/simpler mitigation: make the scheduler's `_process_due` re-fetch each row
  immediately before acting on it (`db.get_reminder(r["id"])` right before `_deliver`) instead
  of trusting the batch snapshot from `due_reminders()` — this shrinks the race window from
  "up to a full tick" to "the width of the Discord send" without needing a version column, at
  the cost of one extra read per due reminder (cheap at this scale).
- Whichever mitigation is chosen, add a test that explicitly simulates "panel edits row X
  between due_reminders() fetch and the write-back" and asserts the final persisted state
  reflects the EDIT, not the stale in-flight computation.

**Warning signs:**
- A support report of "I changed the reminder time but it still fired at the old time once."
- A reminder that reappears in `listar`/the panel list briefly after being deleted (would
  indicate a related but distinct bug — a delete racing an `INSERT OR REPLACE`-style upsert —
  worth testing for even though today's `delete_reminder` is a plain `DELETE`).
- Any new panel endpoint that calls `db.update_reminder`/`db.delete_reminder` without first
  reading a fresh row inside the SAME request (using a value passed from a stale list-page
  render is the same TOCTOU shape from the other direction — the panel's OWN edit could act on
  data the scheduler already changed, e.g. `next_fire_utc` after a catch-up fire).

**Phase to address:**
Reminders CRUD phase — the mitigation (version column, or re-fetch-before-act in the
scheduler) should ship IN this phase, not retrofitted after a production report, because the
scheduler's crash-semantics docstring already shows the team reasons carefully about exactly
this class of race and would want the panel-introduced case reasoned about the same way.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Panel calls `github_publish.publish_message`/`remove_message` directly instead of routing through the bot process | Faster to build (no cross-process hand-off plumbing) | Reintroduces the exact double-publish race (Pitfall 2) the reaction flow already has, now with two writers | Never — always route through the bot as single writer |
| GET-based "quick action" links for approve/pause/etc. | Simpler markup, no CSRF-token plumbing needed | Silently breaks the SameSite=Lax CSRF model (Pitfall 6) | Never |
| Caching resolved Discord names "forever" (no TTL) | One less moving part to build | Stale names mislead staff after a rename, invisibly | Only for near-immutable data (e.g. a channel that's structurally never renamed); never for role names, which change often as tiers evolve |
| Skipping a `busy_timeout`/retry wrapper on new panel write paths | Ships faster | Intermittent "database is locked" 500s as write volume grows (Pitfall 3) | Acceptable only if the phase's write volume is provably low (e.g. Jinxxy manual sync-trigger, which is rare); never for high-frequency paths like Gallery/Reviews approve queues |
| Reusing `require_editor`'s "live re-check on every call" pattern for the NEW tier dependency without also mirroring `require_owner`'s fail-closed unset-config guard | Less code to write initially | A misconfigured/unset Manager role ID could default to an unsafe state (open instead of closed) | Never — copy both halves of the existing pattern, not just the convenient one |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| Discord REST (name resolution) | Resolving IDs one-by-one per row on every render | Batch-fetch the guild's roles/channels once per page load or reuse the bot's gateway cache via the sqlite hand-off (Pitfall 4/5) |
| Discord REST (rate limits) | Retrying a 429 synchronously inside a page request | Respect `Retry-After`, degrade to showing the raw ID immediately, retry out-of-band |
| sqlite (shared file, two processes) | Assuming WAL solves ALL contention | WAL only fixes reader/writer blocking; writer/writer contention still needs `busy_timeout` + retry + short transactions (Pitfall 3) |
| GitHub cross-repo publish (`github_publish`) | Panel and bot both calling the publish/remove transport for the same message | Single-writer discipline: only the bot process calls `github_publish.*`; the panel requests, the bot executes (Pitfall 2) |
| Discord OAuth session (Starlette `SessionMiddleware`) | Treating SameSite=Lax as blanket CSRF coverage regardless of HTTP method | Enforce POST/PUT/DELETE-only for every state-changing action; SameSite=Lax doesn't cover GET (Pitfall 6) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Fresh sqlite connection + no `busy_timeout` per panel write | Occasional `database is locked` under concurrent bot+panel writes | Explicit `busy_timeout` pragma + retry/backoff wrapper (Pitfall 3) | Once panel write frequency exceeds a few writes/minute overlapping the bot's own periodic writes (reminders tick, gallery backfill, presence updates) |
| Per-row Discord REST name resolution | Dashboard page load slows or 429s when multiple staff view Settings/tier-assignment concurrently | Batch-resolve once per page load, cache with short TTL (Pitfall 5) | As soon as more than ~1-2 staff use the dashboard around the same time, or the tier-assignment/settings page references more than a handful of IDs |
| Scheduler snapshot-then-write-back with no re-fetch | Reminders silently revert to a stale schedule after a concurrent panel edit | Re-fetch immediately before acting, or add optimistic-concurrency versioning (Pitfall 7) | As soon as panel-based reminder editing exists at all — this is a correctness trap from day one, not a scale threshold |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Letting Manager-tier reach the tier-assignment write endpoint, even if the UI hides the control | Manager grants itself/another role the Manager or (worse) owner-equivalent tier — vertical privilege escalation | `require_owner` (not a generic `require_manager_or_higher`) on every tier-assignment write, tested directly against the endpoint, not just the UI (Pitfall 1) |
| Admin app holding a write-capable Discord bot token for panel-initiated actions | Doubles the blast radius of a token leak across two processes, reversing the v1 credential-isolation decision | Scope any Discord credential in the admin app to read-only name resolution; route all WRITE actions (publish, react, message) through the bot process only (Pitfall 4) |
| Owner check (`require_owner`) and a new Manager-tier check derived from different, divergent logic (e.g. one from `config.DISCORD_USER_ID`, the other from a live role fetch that could itself be miscategorized) | Owner and Manager checks disagree about who holds which tier, opening either a gap (owner locked out) or a hole (non-owner treated as owner-equivalent) | One `resolve_tier()` function backing every tier dependency; owner check always first and always the existing fail-closed `DISCORD_USER_ID` comparison (Pitfall 1) |
| GET-triggered state-changing dashboard actions | CSRF via a cross-site top-level navigation the SameSite=Lax cookie policy doesn't block | POST/PUT/DELETE-only convention, enforced by a route-enumeration test (Pitfall 6) |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| A Manager sees a "quick approve" work in the Gallery queue but occasionally finds a photo double-published (or the reply/marker missing) because the panel and Discord raced | Confusing, erodes trust in the "parity with reactions" promise | Route panel approve/remove through the same single-writer path as reactions (Pitfall 2); surface pending/in-flight state honestly rather than optimistically |
| A staff member edits a reminder's time/channel and it appears saved in the panel, but the OLD schedule still fires once | Feels like the dashboard "lied" about the save succeeding | Re-fetch-before-act or versioned write-back in the scheduler (Pitfall 7); if truly unavoidable for an in-flight tick, say so in the UI |
| Settings/tier-assignment page shows a channel/role name that's actually stale (renamed in Discord since the cache was populated) | Owner acts on a wrong assumption about which channel/role is configured | Short TTL + visible "resolved as of" indicator, with the raw ID always visible underneath (already true today per POLISH-01) |
| A rate-limited Settings page load hangs while retrying Discord API calls synchronously | Feels like the dashboard is broken/slow | Degrade instantly to raw IDs on a 429/failure rather than blocking the render (Pitfall 5) |

## "Looks Done But Isn't" Checklist

- [ ] **Editable role→tier mapping:** Often missing a same-process test that a Manager POSTing
  directly to the tier-assignment endpoint (bypassing the UI) is rejected — verify with a
  direct HTTP client test, not just "the button isn't shown to Managers."
- [ ] **Gallery/Reviews panel approve-remove parity:** Often missing the cross-process hand-off
  design entirely (panel silently calls the GitHub transport directly) — verify the panel
  action's code path traces through the bot process, not a duplicate implementation.
- [ ] **sqlite write paths added for the dashboard:** Often missing an explicit `busy_timeout`
  and any retry logic — verify by grepping every new write for a retry wrapper, not assuming
  WAL alone is sufficient.
- [ ] **Discord-API name resolution in Settings:** Often missing rate-limit handling and cache
  invalidation — verify by simulating a 429 and a stale cache entry, not just the happy path
  of "the name shows up."
- [ ] **Reminders CRUD from the panel:** Often missing any interaction test with the live
  scheduler tick running concurrently — verify with a test that edits/deletes a row between
  `due_reminders()` fetch and write-back, not just isolated CRUD unit tests.
- [ ] **CSRF coverage on new dashboard routes:** Often missing verification that EVERY new
  action route is POST/PUT/DELETE, not GET — verify with an automated route-enumeration
  check, not a manual read-through.
- [ ] **Meeting summary edit + re-publish to forum:** Often missing idempotency/duplicate-post
  guarding if "re-publish" is invoked twice in a row (double-click, or a panel retry after a
  timeout that actually succeeded) — verify the re-publish path is safe to call twice.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|----------------|-----------------|
| Owner accidentally locked out via a bad tier mapping | LOW | Owner identity is `DISCORD_USER_ID`, never affected by the mapping — owner can still access Settings and fix the mapping; if `DISCORD_USER_ID` itself is wrong, fix via `.env`/host access (no panel round-trip needed) |
| Double-published gallery photo from a panel/reaction race | LOW | `github_publish` already tolerates a re-✅ as a clean republish (WR-02 commit-level dedupe per the cog's own docstring); a 🌙 removal clears both, self-heals |
| Reminder fired once on a stale (pre-edit) schedule | LOW | No data loss — the stored row already reflects the correct edit after the race window passes; at most one extra/wrong-time send, document as accepted risk |
| `database is locked` 500 surfaced to a panel user | LOW-MEDIUM | Add the retry wrapper (Pitfall 3) as a fast-follow patch; in the interim, the panel action can simply be retried manually by the user |
| Admin app credential leak (if a Discord token was added) | HIGH | Rotate the token immediately via the Discord developer portal, audit logs for the exposure window, re-scope the credential per Pitfall 4's minimal-capability guidance before reissuing |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| Editable permission mapping lockout/self-elevation | Tiered Access / Editable Permissions phase | Direct-endpoint test: Manager POST to tier-assignment is 403; owner-lockout-impossibility test; owner-vs-tier-check divergence test |
| Panel/reaction publish race (double publish/remove) | Gallery approval queue phase | Concurrency test: simulate panel approve + Discord ✅ near-simultaneously, assert exactly one commit |
| sqlite write contention as volume grows | Cross-cutting hardening (before/alongside Gallery phase) | Load test: burst of panel writes concurrent with the bot's periodic writes, zero unhandled `database is locked` |
| Discord bot credentials reintroduced into admin app | Settings (Discord-API name resolution) phase | Code review checklist: no write-capable Discord call from `app/`; credential-scope decision documented and signed off |
| Discord rate limits / stale name cache | Settings (Discord-API name resolution) phase | Test: batch resolution (not N calls), TTL-bounded cache, graceful 429 degradation to raw ID |
| GET-based CSRF gap on new actions | Dashboard shell phase (establish convention first) | Automated route-enumeration test: every state-mutating route rejects GET |
| Scheduler vs. panel reminder-edit race | Reminders CRUD phase | Test: edit/delete a reminder between `due_reminders()` fetch and scheduler write-back, assert the fresh state wins |

## Sources

- This repository: `core/db.py`, `core/settings.py`, `app/deps.py`, `app/main.py`,
  `cogs/gallery.py`, `cogs/reminders.py`, `.planning/PROJECT.md` (direct code reading —
  HIGH confidence for every pitfall grounded in a specific line/function cited above).
- [SQLite User Forum: WAL mode single-writer lock/busy_timeout limitations](https://sqlite.org/forum/info/ae41cf11fa83ce8045c31dc90d28d12465a87f3e821a2632f154d791871fd7da) — MEDIUM confidence, corroborates "WAL doesn't fix writer/writer contention."
- [Bert Hubert: What to do about SQLITE_BUSY errors despite setting a timeout](https://berthub.eu/articles/posts/a-brief-post-on-sqlite3-database-locked-despite-timeout/) — MEDIUM confidence, corroborates busy_timeout + short-transaction guidance.
- [Discord Developer Docs: Rate Limits](https://docs.discord.com/developers/topics/rate-limits) — HIGH confidence (official docs), global 50 req/s + per-route bucket limits.
- [Discord support: My Bot is Being Rate Limited](https://support-dev.discord.com/hc/en-us/articles/6223003921559-My-Bot-is-Being-Rate-Limited) — MEDIUM confidence, corroborates 429/backoff behavior.
- General CSRF/SameSite reasoning (SameSite=Lax blocks cross-site POST but not cross-site
  top-level GET navigation) — MEDIUM confidence, standard web-security knowledge consistent
  with this codebase's own documented rationale in `app/main.py`/`02-SECURITY.md`; not
  independently re-verified against a dated external source in this pass — flag for
  validation if a CSRF-hardening spike is ever done.

---
*Pitfalls research for: multi-tier admin dashboard added to an existing Discord bot + FastAPI
app, v2.0 Staff Dashboard milestone*
*Researched: 2026-07-21*
