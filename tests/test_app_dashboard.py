"""Wave 0 (test-first) contract for the Phase 3 staff dashboard shell + tiered access
(03-01, plans 02/05/07 implement the GREEN side).

These six tests pin the Phase Requirements → Test Map from
``.planning/phases/03-dashboard-shell-tiered-access/03-RESEARCH.md`` (SHELL-01, SHELL-02,
ACCESS-01..04): the sidebar renders all seven sections, the Overview page shows the bot
status/last-sync/recent-activity tiles, the owner sees every section including Settings,
a Manager gets the six operational modules but a 403 on Settings, an editor-only identity
is locked out of the whole dashboard but keeps ``/editor``, and a Manager POSTing to
``/admin/settings`` is still 403'd (the self-elevation guard, T-03-01).

They are EXPECTED RED at the end of 03-01: ``app.deps.require_manager`` does not exist yet
(Plan 05), the ``/overview``/``/gallery``/``/reviews``/``/reminders``/``/jinxxy``/``/meetings``
routes do not exist yet (Plan 07), and ``core.db``'s heartbeat/sync-status/activity-log
helpers do not exist yet (Plan 07). ``require_manager``/``require_owner`` are imported
LOCALLY inside each test body — a module-level ``from app.deps import require_manager``
would ImportError and break ``pytest --collect-only`` for this whole file before
``require_manager`` lands, which is not the intended Wave 0 signal (a per-test AttributeError/
ImportError/404/403-mismatch IS the intended signal). Do NOT stub the dependency or routes
here to turn these green — that is Plans 05/07's job.

Mirrors ``tests/test_app_settings.py``'s ``client`` fixture: dummy-but-non-empty OAuth/session
config (the app's lifespan fail-fasts on empty config, 10-08) plus ``config.DB_PATH`` pointed
at a ``tmp_path`` sqlite file, seeded via ``settings.seed_defaults()`` — these routes hit the
real sqlite-backed settings store, not a mock. Each test scopes its own
``app.dependency_overrides`` entries and clears them in a ``finally`` block (never leaking an
override into a later test).
"""

import pytest
from fastapi.testclient import TestClient

import config
from app.main import app
from core import settings

# The six operational modules gated by require_manager (Plan 07). Settings (/admin/settings)
# stays require_owner-gated and is asserted separately in every test below.
_MODULE_ROUTES = ["/overview", "/gallery", "/reviews", "/reminders", "/jinxxy", "/meetings"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    # The app's lifespan fail-fasts on empty OAuth/session config (by design, 10-08) —
    # set dummy-but-non-empty values so the TestClient's startup event doesn't 500.
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    # The dashboard/settings endpoints read/write through the REAL sqlite store — point
    # DB_PATH at a tmp file and seed it so the table exists (mirrors tests/test_app_settings.py).
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "dashboard.db"), raising=False)
    settings.seed_defaults()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── SHELL-01: sidebar renders all seven sections with correct hrefs ────────────────
def test_sidebar_renders_seven_sections(client):
    from app.deps import require_manager

    app.dependency_overrides[require_manager] = lambda: {
        "discord_id": "1", "is_owner": True, "is_manager": True, "is_editor": False,
    }
    try:
        resp = client.get("/overview")
        assert resp.status_code == 200
        body = resp.text
        # The seven section hrefs (six operational modules + Settings) must all be present
        # in the sidebar nav rendered alongside every dashboard page.
        for href in (*_MODULE_ROUTES, "/admin/settings"):
            assert href in body, f"sidebar missing href for {href}"
    finally:
        app.dependency_overrides.clear()


# ── SHELL-02: Overview shows bot status / last sync / recent activity tiles ────────
def test_overview_shows_status_tiles(client):
    from app.deps import require_manager
    from core import db as core_db

    # Seed the three status sources the Overview tiles read (Plan 07's core.db helpers —
    # not yet implemented at Wave 0, so these calls are expected to raise AttributeError).
    core_db.init_heartbeat()
    core_db.set_heartbeat(member_count=42, latency_ms=50)
    core_db.init_jinxxy_sync_status()
    core_db.set_jinxxy_sync_status(ok=True, product_count=10)
    core_db.init_activity_log()
    core_db.log_activity("gallery", "Photo approved")

    app.dependency_overrides[require_manager] = lambda: {
        "discord_id": "1", "is_owner": False, "is_manager": True, "is_editor": False,
    }
    try:
        resp = client.get("/overview")
        assert resp.status_code == 200
        body = resp.text
        # The seeded activity-log message and sync status must render on the Overview tiles.
        assert "Photo approved" in body
        assert "42" in body  # member_count tile
    finally:
        app.dependency_overrides.clear()


# ── ACCESS-01: owner sees/uses every section, including Settings ───────────────────
def test_owner_full_access(client):
    from app.deps import require_manager, require_owner

    app.dependency_overrides[require_owner] = lambda: {"discord_id": "1"}
    app.dependency_overrides[require_manager] = lambda: {
        "discord_id": "1", "is_owner": True, "is_manager": True, "is_editor": False,
    }
    try:
        for route in _MODULE_ROUTES:
            resp = client.get(route)
            assert resp.status_code == 200, f"{route} expected 200 for owner"
        resp = client.get("/admin/settings")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


# ── ACCESS-02: Manager gets the six operational modules, 403 on Settings ───────────
def test_manager_operational_access_settings_403(client):
    from app.deps import require_manager

    app.dependency_overrides[require_manager] = lambda: {
        "discord_id": "2", "is_owner": False, "is_manager": True, "is_editor": False,
    }
    try:
        for route in _MODULE_ROUTES:
            resp = client.get(route)
            assert resp.status_code == 200, f"{route} expected 200 for manager"
        # No require_owner override here — a Manager identity is not the configured owner,
        # so /admin/settings must still 403 via the UNCHANGED require_owner gate (D-04).
        resp = client.get("/admin/settings")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ── ACCESS-03: editor-only identity is locked out of the whole dashboard ───────────
def test_editor_only_locked_out_of_dashboard(client):
    from fastapi import HTTPException

    from app.deps import require_editor, require_manager

    async def _forbid_manager():
        raise HTTPException(status_code=403, detail="needs manager access")

    app.dependency_overrides[require_manager] = _forbid_manager
    app.dependency_overrides[require_editor] = lambda: {"discord_id": "3", "slug": "aria"}
    try:
        for route in _MODULE_ROUTES:
            resp = client.get(route)
            assert resp.status_code == 403, f"{route} expected 403 for editor-only"
        resp = client.get("/admin/settings")
        assert resp.status_code == 403
        # An editor-only identity keeps access to their own presentation section.
        resp = client.get("/editor")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


# ── ACCESS-04 / T-03-01: a Manager cannot edit the tier mapping (self-elevation guard) ──
def test_manager_cannot_edit_mapping(client):
    from app.deps import require_manager

    app.dependency_overrides[require_manager] = lambda: {
        "discord_id": "2", "is_owner": False, "is_manager": True, "is_editor": False,
    }
    try:
        # A Manager identity (never require_owner) POSTing to /admin/settings — including an
        # attempt to edit the manager_roles/editor_roles mapping itself — must still 403.
        resp = client.post("/admin/settings", json={"manager_roles": "999"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
