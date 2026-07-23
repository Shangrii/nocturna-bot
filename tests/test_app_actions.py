"""Route contracts for the manager-gated panel -> bot action queue."""

import base64
import json

import itsdangerous
import pytest
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import config
from app.deps import require_manager
from app.main import app
from core import action_queue, db, settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "actions.db"), raising=False)
    settings.seed_defaults()
    db.init_action_queue()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _manager_override():
    return {
        "discord_id": "2",
        "is_owner": False,
        "is_manager": True,
        "is_editor": False,
    }


def _set_session(client: TestClient, discord_id: str) -> None:
    """Set a signed session using the live SessionMiddleware secret."""
    middleware = next(m for m in app.user_middleware if m.cls is SessionMiddleware)
    signer = itsdangerous.TimestampSigner(str(middleware.kwargs["secret_key"]))
    payload = base64.b64encode(json.dumps({"discord_id": discord_id}).encode("utf-8"))
    client.cookies.set("session", signer.sign(payload).decode("utf-8"))


def test_enqueue_requires_manager(client, monkeypatch):
    async def no_roles(_discord_id):
        return set()

    monkeypatch.setattr("app.deps.auth._fetch_member_roles", no_roles)
    _set_session(client, "999999999999999999")

    response = client.post("/api/actions", json={"kind": "noop", "payload": {}})

    assert response.status_code == 403


def test_enqueue_noop_returns_pending_integer_id(client):
    app.dependency_overrides[require_manager] = _manager_override
    try:
        response = client.post(
            "/api/actions",
            json={"kind": "noop", "payload": {"echo": "panel"}},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    action_id = response.json()["id"]
    assert isinstance(action_id, int)
    assert action_queue.get_status(action_id)["status"] == "pending"


def test_enqueue_rejects_unknown_kind_before_enqueue(client):
    app.dependency_overrides[require_manager] = _manager_override
    try:
        response = client.post(
            "/api/actions",
            json={"kind": "not_allowed", "payload": {}},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    with db._get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0] == 0


def test_action_status_shape_and_unknown_id(client):
    action_id = action_queue.enqueue("noop", {"echo": "panel"}, "2")
    action_queue.complete(action_id, {"echo": "panel"})
    app.dependency_overrides[require_manager] = _manager_override
    try:
        response = client.get(f"/api/actions/{action_id}")
        missing = client.get("/api/actions/999999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert {"status", "error", "result", "bot_online"} <= body.keys()
    assert body["status"] == "done"
    assert body["error"] is None
    assert body["result"] == {"echo": "panel"}
    assert missing.status_code == 404


def test_status_reports_bot_offline(client):
    action_id = action_queue.enqueue("noop", {}, "2")
    app.dependency_overrides[require_manager] = _manager_override
    try:
        response = client.get(f"/api/actions/{action_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["bot_online"] is False


def test_retry_non_failed_action_returns_409(client):
    action_id = action_queue.enqueue("noop", {}, "2")
    app.dependency_overrides[require_manager] = _manager_override
    try:
        response = client.post(f"/api/actions/{action_id}/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409


def test_retry_failed_action_returns_new_id(client):
    action_id = action_queue.enqueue("noop", {"echo": "again"}, "2")
    for _ in range(action_queue._MAX_DISPATCH_ATTEMPTS):
        action_queue.fail(action_id, "forced failure")
    assert action_queue.get_status(action_id)["status"] == "failed"

    app.dependency_overrides[require_manager] = _manager_override
    try:
        response = client.post(f"/api/actions/{action_id}/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    new_id = response.json()["id"]
    assert isinstance(new_id, int)
    assert new_id != action_id
    assert action_queue.get_status(new_id)["status"] == "pending"
