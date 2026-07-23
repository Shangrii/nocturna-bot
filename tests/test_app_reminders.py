"""Integration contracts for the Manager-gated reminders panel backend (06-04)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import config
from app.deps import TierForbidden, require_manager
from app.main import app
from app.routers import reminders as reminders_router
from core import db


CHANNEL_ID = 123456789012345678
ROLE_ID = 223456789012345678
ATTACKER_NEXT_FIRE = "2099-12-31T23:59:00+00:00"


def _configure_app(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "reminders.db"), raising=False)
    db.init_reminders()
    db.init_discord_names()


def _manager_override():
    return {
        "discord_id": "2",
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


def _weekly_payload(**overrides):
    payload = {
        "name": "Junta semanal",
        "frequency": "weekly",
        "time": "09:30",
        "weekday": 2,
        "channel_id": str(CHANNEL_ID),
        "message": "Recuerden la junta",
        "mentions": f"<@&{ROLE_ID}>",
        "reactions": "✅ 🎉",
        "next_fire_utc": ATTACKER_NEXT_FIRE,
    }
    payload.update(overrides)
    return payload


def _add_reminder(
    *,
    frequency="weekly",
    weekday=2,
    day_of_month=None,
    run_date=None,
    next_fire_utc=None,
):
    return db.add_reminder(
        name="Existente",
        frequency=frequency,
        weekday=weekday,
        day_of_month=day_of_month,
        run_date=run_date,
        hour=9,
        minute=30,
        channel_id=CHANNEL_ID,
        message="Mensaje existente",
        created_by=1,
        next_fire_utc=next_fire_utc
        or (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )


def test_every_reminders_route_requires_manager():
    expected = {
        ("GET", "/reminders"),
        ("POST", "/reminders"),
        ("POST", "/reminders/preview"),
        ("POST", "/reminders/{reminder_id}"),
        ("POST", "/reminders/{reminder_id}/delete"),
        ("POST", "/reminders/{reminder_id}/pause"),
        ("POST", "/reminders/{reminder_id}/resume"),
    }
    routes = {
        (method, route.path): route
        for route in reminders_router.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if (method, route.path) in expected
    }

    assert set(routes) == expected
    for route in routes.values():
        assert any(dep.call is require_manager for dep in route.dependant.dependencies)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/reminders"),
        ("post", "/reminders"),
        ("post", "/reminders/preview"),
        ("post", "/reminders/1"),
        ("post", "/reminders/1/delete"),
        ("post", "/reminders/1/pause"),
        ("post", "/reminders/1/resume"),
    ],
)
def test_reminders_routes_non_manager_gets_403_without_data(
    monkeypatch, tmp_path, method, path
):
    _configure_app(monkeypatch, tmp_path)
    _add_reminder()

    async def deny_manager():
        raise TierForbidden(required_tier="manager")

    app.dependency_overrides[require_manager] = deny_manager
    try:
        with TestClient(app) as test_client:
            if method == "post":
                response = test_client.post(
                    path, json={}, headers={"Accept": "application/json"}
                )
            else:
                response = test_client.get(
                    path, headers={"Accept": "application/json"}
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Existente" not in response.text


def test_create_persists_server_computed_next_fire(client):
    before = datetime.now(timezone.utc)

    response = client.post("/reminders", json=_weekly_payload())

    assert response.status_code == 200
    assert response.json()["ok"] is True
    rows = db.list_reminders()
    assert len(rows) == 1
    row = rows[0]
    assert row["frequency"] == "weekly"
    assert row["weekday"] == 2
    assert row["created_by"] == 2
    assert row["next_fire_utc"] != ATTACKER_NEXT_FIRE
    assert datetime.fromisoformat(row["next_fire_utc"]) > before


def test_create_biweekly_accepts_past_anchor_and_rolls_forward(client):
    response = client.post(
        "/reminders",
        json=_weekly_payload(
            frequency="biweekly",
            weekday=None,
            run_date="2020-01-01",
        ),
    )

    assert response.status_code == 200
    row = db.list_reminders()[0]
    assert row["frequency"] == "biweekly"
    assert row["run_date"] == "2020-01-01"
    assert datetime.fromisoformat(row["next_fire_utc"]) > datetime.now(timezone.utc)


def test_create_invalid_schedule_returns_422_and_writes_nothing(client):
    response = client.post("/reminders", json=_weekly_payload(weekday=9))

    assert response.status_code == 422
    assert "weekday" in response.json()["errors"]
    assert db.list_reminders() == []


def test_edit_stale_version_returns_409_reload_message(client):
    reminder_id = _add_reminder()
    stale_version = db.get_reminder(reminder_id)["version"]
    assert db.update_reminder(reminder_id, name="Cambio concurrente") is True

    response = client.post(
        f"/reminders/{reminder_id}",
        json=_weekly_payload(name="Edición obsoleta", version=stale_version),
    )

    assert response.status_code == 409
    assert response.status_code != 422
    error = response.json()["error"].lower()
    assert "recarga" in error and "reload" in error
    assert db.get_reminder(reminder_id)["name"] == "Cambio concurrente"


def test_edit_recomputes_next_fire_and_keeps_paused_state(client):
    reminder_id = _add_reminder()
    assert db.update_reminder(reminder_id, paused=1) is True
    version = db.get_reminder(reminder_id)["version"]

    response = client.post(
        f"/reminders/{reminder_id}",
        json=_weekly_payload(
            name="Editado",
            time="10:45",
            weekday=4,
            version=version,
        ),
    )

    assert response.status_code == 200
    row = db.get_reminder(reminder_id)
    assert row["name"] == "Editado"
    assert row["paused"] == 1
    assert (row["hour"], row["minute"], row["weekday"]) == (10, 45, 4)
    assert row["next_fire_utc"] != ATTACKER_NEXT_FIRE


def test_delete_is_version_guarded(client):
    reminder_id = _add_reminder()
    version = db.get_reminder(reminder_id)["version"]

    response = client.post(
        f"/reminders/{reminder_id}/delete", json={"version": version}
    )

    assert response.status_code == 200
    assert db.get_reminder(reminder_id) is None

    stale_id = _add_reminder()
    stale_version = db.get_reminder(stale_id)["version"]
    assert db.update_reminder(stale_id, name="Más nuevo") is True
    stale_response = client.post(
        f"/reminders/{stale_id}/delete", json={"version": stale_version}
    )
    assert stale_response.status_code == 409
    assert db.get_reminder(stale_id) is not None


def test_pause_sets_flag_and_excludes_row_from_due_query(client):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    reminder_id = _add_reminder(next_fire_utc=past)
    version = db.get_reminder(reminder_id)["version"]

    response = client.post(
        f"/reminders/{reminder_id}/pause", json={"version": version}
    )

    assert response.status_code == 200
    assert db.get_reminder(reminder_id)["paused"] == 1
    assert db.due_reminders(datetime.now(timezone.utc).isoformat()) == []


def test_resume_recomputes_recurring_next_fire_forward(client):
    past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    reminder_id = _add_reminder(next_fire_utc=past)
    assert db.update_reminder(reminder_id, paused=1) is True
    version = db.get_reminder(reminder_id)["version"]
    before = datetime.now(timezone.utc)

    response = client.post(
        f"/reminders/{reminder_id}/resume", json={"version": version}
    )

    assert response.status_code == 200
    row = db.get_reminder(reminder_id)
    assert row["paused"] == 0
    assert datetime.fromisoformat(row["next_fire_utc"]) > before


def test_resume_overdue_oneoff_sets_nowish_fire(client):
    reminder_id = _add_reminder(
        frequency="oneoff",
        weekday=None,
        run_date="2020-01-01",
        next_fire_utc="2020-01-01T15:30:00+00:00",
    )
    assert db.update_reminder(reminder_id, paused=1) is True
    version = db.get_reminder(reminder_id)["version"]
    before = datetime.now(timezone.utc)

    response = client.post(
        f"/reminders/{reminder_id}/resume", json={"version": version}
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    row = db.get_reminder(reminder_id)
    next_fire = datetime.fromisoformat(row["next_fire_utc"])
    assert row["paused"] == 0
    assert before <= next_fire <= after
    assert [due["id"] for due in db.due_reminders(after.isoformat())] == [reminder_id]


def test_preview_returns_server_computed_next_fire(client):
    response = client.post(
        "/reminders/preview",
        json={
            "frequency": "monthly",
            "time": "09:30",
            "day_of_month": 31,
            "next_fire_utc": ATTACKER_NEXT_FIRE,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["next_fire_utc"] != ATTACKER_NEXT_FIRE
    assert datetime.fromisoformat(data["next_fire_utc"]) > datetime.now(timezone.utc)
    assert "Mensual" in data["summary"]


def test_preview_biweekly_past_anchor_rolls_forward(client):
    response = client.post(
        "/reminders/preview",
        json={
            "frequency": "biweekly",
            "time": "09:30",
            "run_date": "2020-01-01",
        },
    )

    assert response.status_code == 200
    assert datetime.fromisoformat(
        response.json()["next_fire_utc"]
    ) > datetime.now(timezone.utc)
