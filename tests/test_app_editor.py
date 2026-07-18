"""Behaviour tests for the block-editor surface (Fase 10, plan 10-10).

Covers the image-upload endpoint (Task 2, SVG-reject + size-cap + Pillow re-encode,
D-17/Pitfall 3) and the save/publish + self-unpublish endpoints (Task 3, D-13/D-16),
all mounted behind ``app.deps.require_editor`` (D-08 IDOR choke point).

``require_editor`` is overridden via ``app.dependency_overrides`` with a fixed
session identity — these tests exercise the ENDPOINT logic (validation, session-
identity enforcement, error handling), not the OAuth/role-check machinery already
covered by ``test_app_auth.py``.
"""

import pytest
from fastapi.testclient import TestClient

import config
from app.deps import require_editor
from app.main import app
from core import github_publish

_IDENT = {"discord_id": "555", "slug": "aria"}


@pytest.fixture
def client(monkeypatch):
    # The app's lifespan fail-fasts on empty OAuth/session config (by design, 10-08) —
    # set dummy-but-non-empty values so the TestClient's startup event doesn't 500.
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    app.dependency_overrides[require_editor] = lambda: _IDENT
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_editor, None)


# ── Task 2: POST /editor/image — SVG-reject + size-cap + Pillow re-encode ─────────
def test_upload_image_valid_commits_reencoded_webp_under_session_slug(monkeypatch, client):
    import app.main as main

    fake_webp = b"FAKE-WEBP-BYTES-NOT-THE-ORIGINAL"
    monkeypatch.setattr(main, "optimize_to_webp", lambda raw: (fake_webp, 100, 100))

    calls = {}

    async def fake_current(discord_id):
        return {"slug": "aria", "discordId": "555", "published": True, "name": "Aria",
                "avatar": "", "tagline": {"es": "", "en": ""}, "links": [], "blocks": []}

    async def fake_sync(entry, images=(), *, message=None):
        calls["entry"] = entry
        calls["images"] = list(images)
        return {"committed": True, "commit_sha": "abc", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", fake_current)
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/image",
        files={"file": ("avatar.png", b"\x89PNG-not-real-but-mocked", "image/png")})

    assert resp.status_code == 200
    data = resp.json()
    assert "/public/editors/aria/" in data["path"] or "/editors/aria/" in data["path"]
    assert data["path"].endswith(".webp")
    # The committed bytes are the RE-ENCODED webp, never the raw upload.
    assert calls["images"][0][1] == fake_webp
    assert calls["entry"]["discordId"] == "555"


def test_upload_image_rejects_svg_by_content_type(monkeypatch, client):
    import app.main as main
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/image",
        files={"file": ("evil.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")})

    assert resp.status_code == 400
    assert sync_calls == []  # nothing committed


def test_upload_image_rejects_svg_by_extension_even_with_faked_content_type(monkeypatch, client):
    import app.main as main
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/image",
        files={"file": ("evil.SVG", b"<svg/>", "image/png")})  # lying content-type

    assert resp.status_code == 400
    assert sync_calls == []


def test_upload_image_rejects_over_size_cap_before_full_read(monkeypatch, client):
    import app.main as main

    monkeypatch.setattr(main, "_MAX_UPLOAD_BYTES", 10)  # tiny cap for the test
    optimize_calls = []
    monkeypatch.setattr(main, "optimize_to_webp",
                         lambda raw: optimize_calls.append(1) or (b"x", 1, 1))

    resp = client.post(
        "/editor/image",
        files={"file": ("big.png", b"0123456789ABCDEF" * 10, "image/png")})

    assert resp.status_code == 400
    assert optimize_calls == []  # rejected before Pillow ever saw it


def test_upload_image_rejects_non_image_bomb_via_pillow_decode_failure(monkeypatch, client):
    import app.main as main
    sync_calls = []

    def fake_optimize(raw):
        raise ValueError("cannot identify image file")

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main, "optimize_to_webp", fake_optimize)
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/image",
        files={"file": ("not-an-image.png", b"garbage-not-an-image-at-all", "image/png")})

    assert resp.status_code == 400
    assert sync_calls == []


def test_upload_image_path_uses_session_slug_never_body(monkeypatch, client):
    import app.main as main

    monkeypatch.setattr(main, "optimize_to_webp", lambda raw: (b"webp", 10, 10))

    async def fake_current(discord_id):
        return {"slug": "aria", "discordId": "555", "published": True, "name": "Aria",
                "avatar": "", "tagline": {"es": "", "en": ""}, "links": [], "blocks": []}

    async def fake_sync(entry, images=(), *, message=None):
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", fake_current)
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    # A hostile client-supplied slug field (if any) must never affect the path.
    resp = client.post(
        "/editor/image",
        data={"slug": "someone-elses-slug"},
        files={"file": ("x.png", b"bytes", "image/png")})

    assert resp.status_code == 200
    assert "someone-elses-slug" not in resp.json()["path"]
    assert "aria" in resp.json()["path"]


# ── 10.1-11 Task 1: POST /editor/media — per-kind caps + optimize + slug commit ───
def _fake_current():
    async def fake_current(discord_id):
        return {"slug": "aria", "discordId": "555", "published": True, "name": "Aria",
                "avatar": "", "tagline": {"es": "", "en": ""}, "links": [], "blocks": []}
    return fake_current


def test_upload_media_image_optimizes_and_commits_under_session_slug(monkeypatch, client):
    import app.main as main

    fake_webp = b"FAKE-WEBP-OPTIMIZED"
    monkeypatch.setattr(main, "optimize_to_webp", lambda raw: (fake_webp, 100, 100))

    calls = {}

    async def fake_sync(entry, images=(), *, message=None):
        calls["images"] = list(images)
        return {"committed": True, "commit_sha": "abc", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", _fake_current())
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/media",
        files={"file": ("bg.png", b"\x89PNG-mocked", "image/png")})

    assert resp.status_code == 200
    data = resp.json()
    assert "/editors/aria/" in data["path"]
    assert data["path"].endswith(".webp")
    assert calls["images"][0][1] == fake_webp  # only the re-encoded bytes are committed


def test_upload_media_video_transcodes_via_ffmpeg_and_commits_mp4(monkeypatch, client):
    import app.main as main

    fake_mp4 = b"FAKE-MP4-TRANSCODED"
    monkeypatch.setattr(main, "_ffmpeg_transcode_video", lambda raw: fake_mp4)

    calls = {}

    async def fake_sync(entry, images=(), *, message=None):
        calls["images"] = list(images)
        return {"committed": True, "commit_sha": "abc", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", _fake_current())
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/media",
        files={"file": ("loop.mp4", b"rawvideobytes", "video/mp4")})

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"].endswith(".mp4")
    assert "/editors/aria/" in data["path"]
    assert calls["images"][0][1] == fake_mp4  # only the transcoded bytes are committed


def test_upload_media_fails_closed_when_ffmpeg_unavailable(monkeypatch, client):
    import app.main as main
    sync_calls = []

    def boom(raw):
        raise main.MediaProcessingError("ffmpeg binary not available")

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main, "_ffmpeg_transcode_video", boom)
    monkeypatch.setattr(main, "_fetch_current_entry", _fake_current())
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/media",
        files={"file": ("loop.mp4", b"rawvideobytes", "video/mp4")})

    assert resp.status_code == 400
    assert sync_calls == []  # nothing committed when ffmpeg can't optimize


def test_upload_media_rejects_svg(monkeypatch, client):
    import app.main as main
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/media",
        files={"file": ("evil.svg", b"<svg><script>x</script></svg>", "image/svg+xml")})

    assert resp.status_code == 400
    assert sync_calls == []


def test_upload_media_rejects_non_media_type(monkeypatch, client):
    import app.main as main
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/media",
        files={"file": ("payload.exe", b"MZ-not-media", "application/octet-stream")})

    assert resp.status_code == 400
    assert sync_calls == []


def test_upload_media_rejects_over_cap_before_optimize(monkeypatch, client):
    import app.main as main

    monkeypatch.setattr(main, "_MEDIA_IMAGE_MAX_BYTES", 10)  # tiny cap for the test
    optimize_calls = []
    monkeypatch.setattr(main, "optimize_to_webp",
                        lambda raw: optimize_calls.append(1) or (b"x", 1, 1))

    resp = client.post(
        "/editor/media",
        files={"file": ("big.png", b"0123456789ABCDEF" * 4, "image/png")})

    assert resp.status_code == 400
    assert optimize_calls == []  # rejected before the optimizer ever saw it


def test_upload_media_path_uses_session_slug_never_body(monkeypatch, client):
    import app.main as main

    monkeypatch.setattr(main, "optimize_to_webp", lambda raw: (b"webp", 10, 10))

    async def fake_sync(entry, images=(), *, message=None):
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", _fake_current())
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/media",
        data={"slug": "someone-elses-slug"},
        files={"file": ("bg.png", b"bytes", "image/png")})

    assert resp.status_code == 200
    assert "someone-elses-slug" not in resp.json()["path"]
    assert "aria" in resp.json()["path"]


# ── 10.1-11 Task 2: POST /editor/audio — 5 MB cap + audio allowlist + slug commit ──
def test_upload_audio_commits_under_session_slug(monkeypatch, client):
    import app.main as main

    raw_audio = b"ID3-fake-mp3-bytes"
    calls = {}

    async def fake_sync(entry, images=(), *, message=None):
        calls["images"] = list(images)
        return {"committed": True, "commit_sha": "abc", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", _fake_current())
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/audio",
        files={"file": ("track.mp3", raw_audio, "audio/mpeg")})

    assert resp.status_code == 200
    data = resp.json()
    assert "/editors/aria/" in data["path"]
    assert data["path"].endswith(".mp3")
    assert calls["images"][0][1] == raw_audio


def test_upload_audio_rejects_non_audio_type(monkeypatch, client):
    import app.main as main
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/audio",
        files={"file": ("payload.exe", b"MZ-not-audio", "application/octet-stream")})

    assert resp.status_code == 400
    assert sync_calls == []


def test_upload_audio_rejects_over_cap_before_commit(monkeypatch, client):
    import app.main as main

    monkeypatch.setattr(main, "_AUDIO_MAX_BYTES", 10)  # tiny cap for the test
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/audio",
        files={"file": ("big.mp3", b"0123456789ABCDEF" * 4, "audio/mpeg")})

    assert resp.status_code == 400
    assert sync_calls == []  # rejected before any commit


def test_upload_audio_path_uses_session_slug_never_body(monkeypatch, client):
    import app.main as main

    async def fake_sync(entry, images=(), *, message=None):
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", _fake_current())
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post(
        "/editor/audio",
        data={"slug": "someone-elses-slug"},
        files={"file": ("track.ogg", b"OggS-bytes", "audio/ogg")})

    assert resp.status_code == 200
    assert "someone-elses-slug" not in resp.json()["path"]
    assert "aria" in resp.json()["path"]
    assert resp.json()["path"].endswith(".ogg")


# ── Task 3: POST /editor/save + POST /editor/unpublish (D-13/D-16) ────────────────
_VALID_BODY = {
    "name": "Aria",
    "avatar": "",
    "lang": "es",
    "tagline": "Editora",
    "slug": "aria",
    "links": [{"label": "Discord", "url": "https://discord.gg/example"}],
    "blocks": [{"type": "bio", "text": "Hola"}],
}


def _mock_fetch_json(monkeypatch):
    """Task 4: save_editor now fetches editors.json once (uniqueness + current entry).

    Pre-existing save tests predate that fetch and only mocked ``sync_editors`` — without
    this, they'd hit the real network. The mocked array owns "aria" for discordId "555",
    matching ``_IDENT``/the default ``_VALID_BODY["slug"]``.
    """
    import app.main as main
    monkeypatch.setattr(
        main.github_publish, "_fetch_json",
        lambda *a, **k: [{"discordId": "555", "slug": "aria", "mediaId": "tok"}])


def test_save_valid_body_validates_forces_session_identity_and_publishes(monkeypatch, client):
    import app.main as main
    _mock_fetch_json(monkeypatch)
    calls = {}

    async def fake_sync(entry, images=(), *, message=None, prune=False):
        calls["entry"] = entry
        return {"committed": True, "commit_sha": "abc", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/save", json=_VALID_BODY)

    assert resp.status_code == 200
    assert calls["entry"]["discordId"] == "555"
    assert calls["entry"]["slug"] == "aria"
    assert calls["entry"]["published"] is True
    assert calls["entry"]["name"] == "Aria"


def test_save_invalid_block_returns_4xx_and_does_not_commit(monkeypatch, client):
    import app.main as main
    _mock_fetch_json(monkeypatch)
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    bad_body = dict(_VALID_BODY)
    bad_body["blocks"] = [{"type": "not-a-real-block-type", "text": "x"}]

    resp = client.post("/editor/save", json=bad_body)

    assert 400 <= resp.status_code < 500
    assert sync_calls == []


def test_save_invalid_link_url_returns_4xx_and_does_not_commit(monkeypatch, client):
    import app.main as main
    _mock_fetch_json(monkeypatch)
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    bad_body = dict(_VALID_BODY)
    bad_body["links"] = [{"label": "Evil", "url": "javascript:alert(1)"}]

    resp = client.post("/editor/save", json=bad_body)

    assert 400 <= resp.status_code < 500
    assert sync_calls == []


def test_save_ignores_body_supplied_discord_id(monkeypatch, client):
    """discordId is always forced from the session (D-08 IDOR guard).

    NOTE (Task 4): this test used to also assert the body's ``slug`` was discarded.
    That guarantee no longer holds by design — the slug is now the editor's own
    validated choice (``resolve_slug``), so a self-owned slug in the body is legitimately
    honored, not an IDOR hijack. Slug-specific behavior (typed slug honored / taken slug
    rejected / reserved slug rejected) is covered by
    ``test_save_honors_typed_slug_and_forces_identity``,
    ``test_save_rejects_slug_taken_by_another_editor`` and
    ``test_save_rejects_reserved_slug`` below. This test now isolates the still-true
    discordId-forcing guarantee only.
    """
    import app.main as main
    _mock_fetch_json(monkeypatch)
    calls = {}

    async def fake_sync(entry, images=(), *, message=None, prune=False):
        calls["entry"] = entry
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    hostile_body = dict(_VALID_BODY)
    hostile_body["discordId"] = "999-someone-else"
    hostile_body["slug"] = "aria"  # the caller's own already-owned slug — not a hijack

    resp = client.post("/editor/save", json=hostile_body)

    assert resp.status_code == 200
    # Session identity wins — the hostile body discordId is discarded entirely.
    assert calls["entry"]["discordId"] == "555"
    assert calls["entry"]["slug"] == "aria"


def test_save_transient_commit_failure_returns_generic_copy_no_internals(monkeypatch, client):
    import app.main as main
    _mock_fetch_json(monkeypatch)

    async def fake_sync(*a, **k):
        raise main.github_publish.GitHubPublishError("PAT abc123 rejected by GitHub")

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/save", json=_VALID_BODY)

    assert resp.status_code >= 500
    body_text = resp.text
    assert "PAT" not in body_text
    assert "abc123" not in body_text


def test_save_requires_a_session(monkeypatch):
    """Without the require_editor override, an unauthenticated POST is rejected."""
    import config
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    from app.main import app as real_app

    async def deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    real_app.dependency_overrides[require_editor] = deny
    try:
        with TestClient(real_app) as c:
            resp = c.post("/editor/save", json=_VALID_BODY)
            assert resp.status_code == 401
    finally:
        real_app.dependency_overrides.pop(require_editor, None)


def test_unpublish_flips_session_editor_to_unpublished(monkeypatch, client):
    import app.main as main
    calls = {}

    async def fake_unpublish(discord_id, *, message=None):
        calls["discord_id"] = discord_id
        return {"committed": True, "commit_sha": "abc", "slug": "aria"}

    monkeypatch.setattr(main.github_publish, "unpublish_editor", fake_unpublish)

    resp = client.post("/editor/unpublish")

    assert resp.status_code == 200
    assert calls["discord_id"] == "555"


def test_unpublish_transient_failure_returns_generic_copy(monkeypatch, client):
    import app.main as main

    async def fake_unpublish(discord_id, *, message=None):
        raise main.github_publish.GitHubPublishError("PAT abc123 rejected")

    monkeypatch.setattr(main.github_publish, "unpublish_editor", fake_unpublish)

    resp = client.post("/editor/unpublish")

    assert resp.status_code >= 500
    assert "PAT" not in resp.text
    assert "abc123" not in resp.text


# ── Task 4: editor-chosen slug wired through save + upload endpoints ──────────────
def _valid_page_body(slug="mi-link", **overrides):
    body = {"name": "Aria", "lang": "es", "slug": slug}
    body.update(overrides)
    return body


def test_save_honors_typed_slug_and_forces_identity(monkeypatch, client):
    import app.main as main
    editors = [{"discordId": "555", "slug": "aria", "mediaId": "tok999"}]
    monkeypatch.setattr(main.github_publish, "_fetch_json", lambda *a, **k: editors)

    captured = {}

    async def fake_sync(entry, images=(), *, message=None, prune=False):
        captured["entry"] = entry
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/save", json=_valid_page_body(slug="Mi Nuevo Link!"))

    assert resp.status_code == 200
    assert captured["entry"]["slug"] == "mi-nuevo-link"   # typed slug, normalized
    assert captured["entry"]["discordId"] == "555"        # identity forced from session
    assert captured["entry"]["mediaId"] == "tok999"       # mediaId preserved from entry


def test_save_rejects_slug_taken_by_another_editor(monkeypatch, client):
    import app.main as main
    editors = [
        {"discordId": "555", "slug": "aria", "mediaId": "tokme"},
        {"discordId": "999", "slug": "taken-name", "mediaId": "tokother"},
    ]
    monkeypatch.setattr(main.github_publish, "_fetch_json", lambda *a, **k: editors)

    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/save", json=_valid_page_body(slug="taken-name"))

    assert resp.status_code == 409
    assert sync_calls == []  # nothing committed


def test_save_rejects_reserved_slug(monkeypatch, client):
    import app.main as main
    editors = [{"discordId": "555", "slug": "aria", "mediaId": "tokme"}]
    monkeypatch.setattr(main.github_publish, "_fetch_json", lambda *a, **k: editors)

    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/save", json=_valid_page_body(slug="api"))

    assert resp.status_code == 422
    assert sync_calls == []


def test_upload_image_returns_path_under_media_id(monkeypatch, client):
    import app.main as main
    monkeypatch.setattr(main, "optimize_to_webp", lambda raw: (b"WEBP", 10, 10))

    async def fake_current(discord_id):
        return {"slug": "aria", "discordId": "555", "mediaId": "tok777",
                "published": True, "name": "Aria", "avatar": "", "links": [], "blocks": []}

    async def fake_sync(entry, images=(), *, message=None, prune=False):
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main, "_fetch_current_entry", fake_current)
    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/image", files={"file": ("a.png", b"x", "image/png")})

    assert resp.status_code == 200
    assert "/editors/tok777/" in resp.json()["path"]


# ── Task 5: editable "Tu link · Your link" slug field in the admin editor form ────
def test_editor_page_renders_slug_field(monkeypatch, client):
    import app.main as main

    async def fake_current(discord_id):
        return {"slug": "aria", "discordId": "555", "mediaId": "tok",
                "published": True, "name": "Aria", "avatar": "", "tagline": "",
                "links": [], "blocks": []}

    monkeypatch.setattr(main, "_fetch_current_entry", fake_current)

    resp = client.get("/editor")
    assert resp.status_code == 200
    assert 'id="f-slug"' in resp.text


# ── Final-review fixes: server-forced mediaId + session-slug refresh on rename ────
def test_save_forces_server_mediaid_over_hostile_body_mediaid(monkeypatch, client):
    """A save body carrying a hostile ``mediaId`` must never reach the commit path.

    ``_apply_session_identity`` (app/main.py ~line 610-624) always overwrites
    ``merged["mediaId"]`` with the server-derived value, mirroring the existing
    ``discordId``/``slug`` identity-forcing guarantees (D-08 Pitfall 1). A client
    trying to smuggle its own path segment via ``mediaId`` (path-hijack surface for
    the image/media/audio commit dirs) must be silently overridden, not merely
    rejected.
    """
    import app.main as main
    editors = [{"discordId": "555", "slug": "aria", "mediaId": "realtok"}]
    monkeypatch.setattr(main.github_publish, "_fetch_json", lambda *a, **k: editors)

    captured = {}

    async def fake_sync(entry, images=(), *, message=None, prune=False):
        captured["entry"] = entry
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    hostile_body = _valid_page_body(slug="aria")
    hostile_body["mediaId"] = "evilpath"  # valid charset, but not this editor's real key

    resp = client.post("/editor/save", json=hostile_body)

    assert resp.status_code == 200
    # Server-derived mediaId wins — the hostile body value never reaches the commit.
    assert captured["entry"]["mediaId"] == "realtok"


def test_save_rename_refreshes_session_slug(monkeypatch, client):
    """After a slug rename, ``save_editor`` writes the new slug into the session
    (app/main.py ~line 680, ``request.session["slug"] = slug``) so the session's
    cached slug never goes stale post-rename. Decoded directly with the same
    itsdangerous ``TimestampSigner`` Starlette's ``SessionMiddleware`` uses — this
    reads the real Set-Cookie the middleware emits, not a hand-rolled stand-in.

    NOTE: the signer key must be the ``secret_key`` the middleware was actually
    constructed with (captured once, at ``app.add_middleware`` time during module
    import) — NOT ``config.SESSION_SECRET`` read now, which the ``client`` fixture
    monkeypatches to a dummy value only so the lifespan config check doesn't 500.
    Those two diverge, so the real key is pulled straight off the live middleware
    stack (``app.user_middleware``) instead of assumed.
    """
    import base64
    import json as _json

    import itsdangerous
    from starlette.middleware.sessions import SessionMiddleware

    import app.main as main
    editors = [{"discordId": "555", "slug": "aria", "mediaId": "tok"}]
    monkeypatch.setattr(main.github_publish, "_fetch_json", lambda *a, **k: editors)

    async def fake_sync(entry, images=(), *, message=None, prune=False):
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    resp = client.post("/editor/save", json=_valid_page_body(slug="nuevo-nombre"))
    assert resp.status_code == 200

    cookie_value = client.cookies.get("session")
    assert cookie_value is not None, "SessionMiddleware did not set a session cookie"

    session_mw = next(
        m for m in main.app.user_middleware if m.cls is SessionMiddleware)
    real_secret = session_mw.kwargs["secret_key"]

    signer = itsdangerous.TimestampSigner(str(real_secret))
    unsigned = signer.unsign(cookie_value.encode("utf-8"), max_age=None)
    session_data = _json.loads(base64.b64decode(unsigned))
    assert session_data["slug"] == "nuevo-nombre"
