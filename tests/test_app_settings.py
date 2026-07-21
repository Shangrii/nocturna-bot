"""Integration tests for the owner-only settings panel routes (Phase 2, 02-04).

Covers the whole PANEL-01..04 surface: the `require_owner` gate on GET/POST
`/admin/settings`, the grouped/typed render with no secret in the body, the atomic
two-pass validate-then-write POST (D-04/D-05 — a mixed valid/invalid POST writes
NOTHING), and the read-at-use round-trip (PANEL-04 — a saved value is visible to
`settings.get`, the same accessor the bot's cogs call).

Mirrors `tests/test_app_editor.py`'s `client` fixture (dummy OAuth/session config +
`app.dependency_overrides` + `TestClient`), additionally pointing `config.DB_PATH` at a
`tmp_path` sqlite file (per `tests/test_settings.py::_use_tmp_db`) and seeding it via
`settings.seed_defaults()` — these routes hit the real sqlite-backed store, not a mock.
"""

import pytest
from fastapi.testclient import TestClient

import config
from app.deps import require_owner
from app.main import app
from core import settings

_IDENT = {"discord_id": "555"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    # The app's lifespan fail-fasts on empty OAuth/session config (by design, 10-08) —
    # set dummy-but-non-empty values so the TestClient's startup event doesn't 500.
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    # The settings endpoints read/write through the REAL sqlite store — point DB_PATH at
    # a tmp file and seed it so the table exists (mirrors tests/test_settings.py).
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "settings.db"), raising=False)
    settings.seed_defaults()

    app.dependency_overrides[require_owner] = lambda: _IDENT
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_owner, None)


# ── PANEL-01: the gate ─────────────────────────────────────────────────────────────
def test_get_settings_non_owner_gets_403_no_data(monkeypatch, tmp_path):
    """Without the require_owner override (deny path), GET is 403 and carries no settings."""
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "settings.db"), raising=False)
    settings.seed_defaults()

    with TestClient(app) as c:
        resp = c.get("/admin/settings", headers={"Accept": "application/json"})

    assert resp.status_code == 403
    assert "PHOTO_CHANNEL_ID" not in resp.text
    assert "JINXXY_POLL_HOURS" not in resp.text


def test_post_settings_non_owner_gets_403_no_data(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "settings.db"), raising=False)
    settings.seed_defaults()

    with TestClient(app) as c:
        resp = c.post("/admin/settings", json={"JINXXY_POLL_HOURS": 12})

    assert resp.status_code == 403


# ── PANEL-02: GET renders grouped tunables, no secret ──────────────────────────────
def test_get_settings_owner_renders_grouped_no_secret(client):
    resp = client.get("/admin/settings")

    assert resp.status_code == 200
    body = resp.text
    # Group markup present (each group is a <fieldset> in settings.html, per PATTERNS.md).
    assert "fieldset" in body or "group" in body
    # No secret/structural value ever reaches the body.
    for secret in ("BOT_TOKEN", "GITHUB_PAT", "JINXXY_API_KEY", "SESSION_SECRET", "DB_PATH"):
        assert secret not in body


# ── PANEL-03/D-04: atomic POST — valid persists, mixed valid/invalid writes nothing ─
def test_post_settings_valid_change_persists_and_returns_ok(client):
    resp = client.post("/admin/settings", json={"JINXXY_POLL_HOURS": 12})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "message" in data
    # PANEL-04: the bot's read-at-use path (settings.get) sees the new value.
    assert settings.get("JINXXY_POLL_HOURS") == 12


def test_post_settings_mixed_valid_invalid_returns_422_and_writes_nothing(client):
    default_poll_hours = settings.get("JINXXY_POLL_HOURS")

    resp = client.post(
        "/admin/settings",
        json={"JINXXY_POLL_HOURS": 12, "PHOTO_CHANNEL_ID": "nope"},
    )

    assert resp.status_code == 422
    data = resp.json()
    assert "errors" in data
    assert "PHOTO_CHANNEL_ID" in data["errors"]
    # D-04: NOTHING was written — even the otherwise-valid field stayed at its default.
    assert settings.get("JINXXY_POLL_HOURS") == default_poll_hours


# ── PANEL-04: read-at-use round-trip ────────────────────────────────────────────────
def test_post_settings_round_trip_visible_to_settings_get(client):
    client.post("/admin/settings", json={"REMINDERS_CATCHUP_GRACE_HOURS": 42})

    assert settings.get("REMINDERS_CATCHUP_GRACE_HOURS") == 42


def _flatten(groups: list[dict]) -> dict:
    """Mirror settingsApp's flatten (settings.html lines 104-114): key -> current value,
    for every setting in every group. Reproduces the EXACT payload the browser posts on an
    unmodified "Save" click — all keys, current (already string-serialized) values."""
    return {
        setting["key"]: setting["value"]
        for group in groups
        for setting in group["settings"]
    }


# ── CR-01/CR-02 (02-05 gap closure): GET-payload → POST-unchanged round trip ───────
def test_post_settings_unchanged_save_preserves_snowflake_precision(client):
    """Test F: flattening all_for_ui() and POSTing it back unedited must not corrupt a
    17-20 digit Discord snowflake (CR-01 — a bare int would round in the browser's JS,
    but here we drive the same payload shape server-side through the real route)."""
    payload = _flatten(settings.all_for_ui())

    resp = client.post("/admin/settings", json=payload)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert settings.get("PHOTO_CHANNEL_ID") == 1416329356426481717


def test_post_settings_unchanged_save_preserves_staff_role_cascade(client):
    """Test G: an unmodified full-form save must not bake the CONF-03 gallery fallback into
    REVIEWS/REMINDERS/JINXXY_STAFF_ROLE_IDS (CR-02) — the cascade must still respond to a
    later gallery-only edit."""
    settings.set("GALLERY_STAFF_ROLE_IDS", [111])

    payload = _flatten(settings.all_for_ui())
    # the raw (unresolved) dependent lists are empty strings in the payload (Task 1 fix)
    assert payload["REVIEWS_STAFF_ROLE_IDS"] == ""
    assert payload["REMINDERS_STAFF_ROLE_IDS"] == ""
    assert payload["JINXXY_STAFF_ROLE_IDS"] == ""

    resp = client.post("/admin/settings", json=payload)
    assert resp.status_code == 200

    # unchanged save: nothing baked in, still cascading from the gallery list
    assert settings.get("REVIEWS_STAFF_ROLE_IDS") == [111]
    assert settings.get("REMINDERS_STAFF_ROLE_IDS") == [111]
    assert settings.get("JINXXY_STAFF_ROLE_IDS") == [111]

    resp2 = client.post("/admin/settings", json={"GALLERY_STAFF_ROLE_IDS": "222"})
    assert resp2.status_code == 200

    # editing only the gallery list still cascades to every dependent key
    assert settings.get("REVIEWS_STAFF_ROLE_IDS") == [222]
    assert settings.get("REMINDERS_STAFF_ROLE_IDS") == [222]
    assert settings.get("JINXXY_STAFF_ROLE_IDS") == [222]


# ── bad JSON body → 400 ─────────────────────────────────────────────────────────────
def test_post_settings_non_dict_body_returns_400(client):
    resp = client.post("/admin/settings", json=["not", "a", "dict"])

    assert resp.status_code == 400


def test_post_settings_bad_json_returns_400(client):
    resp = client.post(
        "/admin/settings",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
    )

    assert resp.status_code == 400
