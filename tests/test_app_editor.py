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
    "links": [{"label": "Discord", "url": "https://discord.gg/example"}],
    "blocks": [{"type": "bio", "text": {"es": "Hola", "en": "Hi"}}],
}


def test_save_valid_body_validates_forces_session_identity_and_publishes(monkeypatch, client):
    import app.main as main
    calls = {}

    async def fake_sync(entry, images=(), *, message=None):
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
    sync_calls = []

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    bad_body = dict(_VALID_BODY)
    bad_body["blocks"] = [{"type": "not-a-real-block-type", "text": {"es": "x", "en": "y"}}]

    resp = client.post("/editor/save", json=bad_body)

    assert 400 <= resp.status_code < 500
    assert sync_calls == []


def test_save_invalid_link_url_returns_4xx_and_does_not_commit(monkeypatch, client):
    import app.main as main
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


def test_save_ignores_body_supplied_discord_id_and_slug(monkeypatch, client):
    import app.main as main
    calls = {}

    async def fake_sync(entry, images=(), *, message=None):
        calls["entry"] = entry
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(main.github_publish, "sync_editors", fake_sync)

    hostile_body = dict(_VALID_BODY)
    hostile_body["discordId"] = "999-someone-else"
    hostile_body["slug"] = "someone-elses-slug"

    resp = client.post("/editor/save", json=hostile_body)

    assert resp.status_code == 200
    # Session identity wins — the hostile body values are discarded entirely.
    assert calls["entry"]["discordId"] == "555"
    assert calls["entry"]["slug"] == "aria"


def test_save_transient_commit_failure_returns_generic_copy_no_internals(monkeypatch, client):
    import app.main as main

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
