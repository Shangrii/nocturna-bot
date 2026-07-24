"""Integration contracts for the Manager-gated gallery queue routes."""

import json

import pytest
from fastapi.testclient import TestClient

import config
from app.deps import TierForbidden, require_manager
from app.main import app
from core import action_queue, db


PENDING_ID = 801
PUBLISHED_ID = 802


def _configure_app(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(
        config,
        "DISCORD_OAUTH_REDIRECT_URI",
        "https://x/auth/callback",
    )
    monkeypatch.setattr(
        config,
        "DB_PATH",
        str(tmp_path / "gallery-routes.db"),
        raising=False,
    )
    db.init_gallery_queue()
    db.init_action_queue()
    db.upsert_gallery_queue_row(
        PENDING_ID,
        "pending",
        "Pending Poster",
        "Pending caption",
        "https://cdn.example/pending.webp",
        "2026-07-23T12:00:00+00:00",
        f"https://discord.com/channels/1/2/{PENDING_ID}",
    )
    db.upsert_gallery_queue_row(
        PUBLISHED_ID,
        "published",
        "Published Poster",
        "Published caption",
        "https://cdn.example/published.webp",
        "2026-07-23T13:00:00+00:00",
        f"https://discord.com/channels/1/2/{PUBLISHED_ID}",
    )


def _manager_override():
    return {
        "discord_id": "manager-2",
        "is_owner": False,
        "is_manager": True,
        "is_editor": False,
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    app.dependency_overrides[require_manager] = _manager_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _assert_enqueued(response, expected_kind, expected_message_id):
    assert response.status_code == 200
    action_id = response.json()["id"]
    assert isinstance(action_id, int)
    row = action_queue.get_status(action_id)
    assert row["status"] == "pending"
    assert row["kind"] == expected_kind
    assert json.loads(row["payload_json"]) == {
        "message_id": expected_message_id
    }


def test_gallery_page_renders_pending_queue(client):
    response = client.get("/gallery")

    assert response.status_code == 200
    assert "Pendientes" in response.text
    assert 'class="gq"' in response.text
    assert "Pending caption" in response.text
    assert "Pending Poster" in response.text


def test_gallery_approve_enqueues_publish_action(client):
    response = client.post(f"/gallery/{PENDING_ID}/approve")

    _assert_enqueued(response, "gallery_publish", PENDING_ID)


def test_gallery_remove_enqueues_remove_action(client):
    response = client.post(f"/gallery/{PUBLISHED_ID}/remove")

    _assert_enqueued(response, "gallery_remove", PUBLISHED_ID)


@pytest.mark.parametrize("operation", ["approve", "remove"])
def test_gallery_unknown_message_returns_404_before_enqueue(client, operation):
    response = client.post(f"/gallery/999999/{operation}")

    assert response.status_code == 404
    with db._get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0]
    assert count == 0


def test_gallery_queue_json_returns_pending_and_published_rows(client):
    response = client.get("/gallery/queue")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"pending", "published"}
    assert [row["message_id"] for row in body["pending"]] == [PENDING_ID]
    assert [row["message_id"] for row in body["published"]] == [PUBLISHED_ID]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/gallery"),
        ("get", "/gallery/queue"),
        ("post", f"/gallery/{PENDING_ID}/approve"),
        ("post", f"/gallery/{PUBLISHED_ID}/remove"),
    ],
)
def test_gallery_routes_reject_non_manager(
    monkeypatch, tmp_path, method, path
):
    _configure_app(monkeypatch, tmp_path)

    async def deny_manager():
        raise TierForbidden(required_tier="manager")

    app.dependency_overrides[require_manager] = deny_manager
    try:
        with TestClient(app) as test_client:
            response = getattr(test_client, method)(
                path,
                headers={"Accept": "application/json"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Pending Poster" not in response.text


def test_gallery_non_integer_message_id_returns_422(client):
    response = client.post("/gallery/not-an-int/approve")

    assert response.status_code == 422
