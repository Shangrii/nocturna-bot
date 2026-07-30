"""Integration contracts for the Manager-gated meetings browser routes."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import config
from app.deps import TierForbidden, require_manager
from app.main import app
from core import action_queue, db


def _configure_app(monkeypatch, tmp_path, *, init_meetings=True):
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
        str(tmp_path / "meeting-routes.db"),
        raising=False,
    )
    if init_meetings:
        db.init_meetings()
    db.init_action_queue()
    db.init_heartbeat()


def _manager_override():
    return {
        "discord_id": "manager-2",
        "is_owner": False,
        "is_manager": True,
        "is_editor": False,
        "username": "Nombre",
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


def _meeting(meeting_id, *, topic, started_at, summary, transcript):
    return {
        "id": meeting_id,
        "tema": topic,
        "started_at": started_at,
        "ended_at": None,
        "attendees": ["Ana", "Nox"],
        "attendees_json": '["Ana", "Nox"]',
        "notes_json": "[]",
        "transcript": transcript,
        "summary": summary,
        "thread_id": 900 + meeting_id,
        "starter_message_id": 900 + meeting_id,
    }


def test_meetings_list_renders_rows_in_database_order(monkeypatch, client):
    rows = [
        _meeting(
            2,
            topic="Más reciente",
            started_at="2026-07-29T10:00:00",
            summary="Resumen nuevo",
            transcript="Transcripción nueva",
        ),
        _meeting(
            1,
            topic="Más antigua",
            started_at="2026-07-20T10:00:00",
            summary="Resumen anterior",
            transcript="Transcripción anterior",
        ),
    ]
    monkeypatch.setattr(db, "list_meetings", Mock(return_value=rows))

    response = client.get("/meetings")

    assert response.status_code == 200
    assert "Reuniones" in response.text
    assert response.text.index("Más reciente") < response.text.index("Más antigua")
    assert "Resumen nuevo" in response.text
    assert "2 asistente(s)" in response.text


def test_fresh_app_startup_initializes_meetings_table(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path, init_meetings=False)
    app.dependency_overrides[require_manager] = _manager_override
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/meetings")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Aún no hay reuniones" in response.text


def test_meeting_detail_renders_summary_and_transcript(monkeypatch, client):
    row = _meeting(
        7,
        topic="Planeación",
        started_at="2026-07-29T10:00:00",
        summary="Resumen editable",
        transcript="Transcripción completa",
    )
    monkeypatch.setattr(db, "get_meeting", Mock(return_value=row))

    response = client.get("/meetings/7")

    assert response.status_code == 200
    assert "Resumen editable" in response.text
    assert "Transcripción completa" in response.text
    assert "Guardar y republicar" in response.text


def test_meeting_detail_returns_404_for_unknown_id(monkeypatch, client):
    monkeypatch.setattr(db, "get_meeting", Mock(return_value=None))

    response = client.get(
        "/meetings/404",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 404


def test_republish_strips_saves_then_enqueues_with_manager_attribution(
    monkeypatch, client
):
    operations = []

    def update_summary(meeting_id, summary):
        operations.append(("update", meeting_id, summary))

    def enqueue(kind, payload, requested_by, *, dedupe_key=None):
        operations.append(
            ("enqueue", kind, payload, requested_by, dedupe_key)
        )
        return 321

    monkeypatch.setattr(db, "update_meeting_summary", update_summary)
    monkeypatch.setattr(action_queue, "enqueue_deduped", enqueue)

    response = client.post(
        "/meetings/7/republish",
        json={"summary": "  Resumen corregido  "},
    )

    assert response.status_code == 200
    assert response.json() == {"id": 321}
    assert operations == [
        ("update", 7, "Resumen corregido"),
        (
            "enqueue",
            "meeting_republish",
            {"meeting_id": 7, "actor_name": "Nombre"},
            "manager-2",
            "meeting_republish:7",
        ),
    ]


def test_republish_uses_stable_per_meeting_dedupe_keys(monkeypatch, client):
    dedupe_keys = []
    monkeypatch.setattr(db, "update_meeting_summary", Mock())

    def enqueue(kind, payload, requested_by, *, dedupe_key=None):
        dedupe_keys.append(dedupe_key)
        return len(dedupe_keys)

    monkeypatch.setattr(action_queue, "enqueue_deduped", enqueue)

    first = client.post("/meetings/7/republish", json={"summary": "Uno"})
    duplicate = client.post("/meetings/7/republish", json={"summary": "Dos"})
    different = client.post("/meetings/8/republish", json={"summary": "Tres"})

    assert first.status_code == duplicate.status_code == different.status_code == 200
    assert dedupe_keys == [
        "meeting_republish:7",
        "meeting_republish:7",
        "meeting_republish:8",
    ]


def test_republish_caps_summary_before_database_write(monkeypatch, client):
    update_summary = Mock()
    monkeypatch.setattr(db, "update_meeting_summary", update_summary)
    monkeypatch.setattr(
        action_queue,
        "enqueue_deduped",
        Mock(return_value=654),
    )

    response = client.post(
        "/meetings/7/republish",
        json={"summary": f"  {'x' * 5000}  "},
    )

    assert response.status_code == 200
    stored_summary = update_summary.call_args.args[1]
    assert len(stored_summary) == 4096
    assert stored_summary == "x" * 4096


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/meetings", {}),
        ("get", "/meetings/7", {}),
        ("post", "/meetings/7/republish", {"json": {"summary": "Cambio"}}),
    ],
)
def test_meeting_routes_reject_non_manager(
    monkeypatch, tmp_path, method, path, kwargs
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
                **kwargs,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
