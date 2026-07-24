"""Integration contracts for the Manager-gated reviews queue routes."""

import json

import pytest
from fastapi.testclient import TestClient

import config
from app.deps import TierForbidden, require_manager
from app.main import app
from core import action_queue, db


PENDING_ID = 901
PUBLISHED_ID = 902


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
        str(tmp_path / "review-routes.db"),
        raising=False,
    )
    db.init_reviews_queue()
    db.init_action_queue()
    db.upsert_reviews_queue_row(
        PENDING_ID,
        "pending",
        None,
        1,
        "Anonymous pending review",
        "2026-07-23T12:00:00+00:00",
        f"https://discord.com/channels/1/3/{PENDING_ID}",
    )
    db.upsert_reviews_queue_row(
        PUBLISHED_ID,
        "published",
        "Named Reviewer",
        0,
        "Published review",
        "2026-07-23T13:00:00+00:00",
        f"https://discord.com/channels/1/3/{PUBLISHED_ID}",
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


def test_review_approve_enqueues_publish_action(client):
    response = client.post(f"/reviews/{PENDING_ID}/approve")

    _assert_enqueued(response, "review_publish", PENDING_ID)


def test_review_remove_enqueues_remove_action(client):
    response = client.post(f"/reviews/{PUBLISHED_ID}/remove")

    _assert_enqueued(response, "review_remove", PUBLISHED_ID)


@pytest.mark.parametrize("operation", ["approve", "remove"])
def test_review_unknown_message_returns_404_before_enqueue(client, operation):
    response = client.post(f"/reviews/999999/{operation}")

    assert response.status_code == 404
    with db._get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0]
    assert count == 0


def test_reviews_queue_json_preserves_anonymous_contract(client):
    response = client.get("/reviews/queue")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"pending", "published"}
    anonymous = body["pending"][0]
    assert anonymous["message_id"] == PENDING_ID
    assert anonymous["is_anonymous"] == 1
    assert anonymous["author"] is None
    assert "Secret Submitter" not in response.text
    assert [row["message_id"] for row in body["published"]] == [PUBLISHED_ID]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/reviews"),
        ("get", "/reviews/queue"),
        ("post", f"/reviews/{PENDING_ID}/approve"),
        ("post", f"/reviews/{PUBLISHED_ID}/remove"),
    ],
)
def test_review_routes_reject_non_manager(
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
    assert "Anonymous pending review" not in response.text


def test_review_non_integer_message_id_returns_422(client):
    response = client.post("/reviews/not-an-int/approve")

    assert response.status_code == 422
