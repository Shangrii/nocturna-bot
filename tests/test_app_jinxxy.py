"""Integration contracts for the Manager-gated Jinxxy sync panel routes."""

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import config
from app.deps import TierForbidden, require_manager
from app.main import app
from core import action_queue, db


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
        str(tmp_path / "jinxxy-routes.db"),
        raising=False,
    )
    db.init_action_queue()
    db.init_jinxxy_sync_status()
    db.init_store_state()
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


def _set_heartbeat(last_beat_utc: str):
    db.set_heartbeat(
        latency_ms=12,
        started_at_utc="2026-07-24T00:00:00+00:00",
        guild_member_count=42,
        loaded_cogs=["jinxxy"],
    )
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE bot_heartbeat SET last_beat_utc = ? WHERE id = 1",
            (last_beat_utc,),
        )


def _fresh_heartbeat():
    _set_heartbeat(datetime.now(timezone.utc).isoformat())


def _stale_heartbeat():
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    _set_heartbeat(stale.isoformat())


def _jinxxy_action_count() -> int:
    with db._get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM action_queue WHERE kind = ?",
            ("jinxxy_sync",),
        ).fetchone()[0]


def _seed_product(
    name: str,
    checkout_url: str,
    *,
    price: str = "10.00",
    category: str = "Avatares",
    nsfw: int = 0,
    date: str = "2026-07-25",
):
    db.upsert_store_snapshot(
        checkout_url,
        f"id-{name.casefold()}",
        name,
        price,
        category,
        nsfw,
        date,
    )


def test_jinxxy_page_renders_for_a_manager(client):
    response = client.get("/jinxxy")

    assert response.status_code == 200


def test_never_synced_empty_state(client):
    response = client.get("/jinxxy")

    assert response.status_code == 200
    assert "Nunca se ha sincronizado" in response.text
    assert (
        "Aún no hay productos sincronizados"
        in response.text
    )
    assert "'—'" not in response.text


def test_product_table_columns(client):
    _seed_product(
        "Cahuama",
        "https://jinxxy.com/nocturna/cahuama",
        nsfw=1,
    )
    _seed_product(
        "Dalia",
        "https://jinxxy.com/nocturna/dalia",
        nsfw=0,
    )

    response = client.get("/jinxxy")

    assert response.status_code == 200
    for heading in (
        "Nombre",
        "Precio",
        "Categoría",
        "NSFW",
        "Fecha",
    ):
        assert heading in response.text
    for forbidden_heading in (
        "<th>Imagen</th>",
        "<th>Descripción</th>",
        "<th>Editor</th>",
    ):
        assert forbidden_heading not in response.text


def test_product_rows_are_seeded_into_the_page(client):
    products = (
        ("Cahuama", "https://jinxxy.com/nocturna/cahuama"),
        ("Dalia", "https://jinxxy.com/nocturna/dalia"),
    )
    for name, checkout_url in products:
        _seed_product(name, checkout_url)

    response = client.get("/jinxxy")

    for name, checkout_url in products:
        assert name in response.text
        assert checkout_url in response.text
    external_links = re.findall(
        r'<a\b[^>]*target="_blank"[^>]*>',
        response.text,
    )
    assert external_links
    assert all('rel="noopener"' in tag for tag in external_links)


def test_products_are_sorted_by_name_case_insensitively(client):
    for name in ("zeta", "Alfa", "beta"):
        _seed_product(name, f"https://jinxxy.com/nocturna/{name.casefold()}")

    response = client.get("/jinxxy")

    assert response.text.index("Alfa") < response.text.index("beta")
    assert response.text.index("beta") < response.text.index("zeta")


def test_page_has_no_confirm_dialog(client):
    response = client.get("/jinxxy")

    assert "confirm-modal" not in response.text
    assert "modal-overlay" not in response.text


def test_page_renders_the_sync_button_labels(client):
    response = client.get("/jinxxy")

    assert "Sincronizar catálogo" in response.text
    assert "Sincronizando…" in response.text


def test_rendered_page_does_not_leak_the_raw_error_column(client):
    secret_error = "https://api.jinxxy.com/v1/products 503"
    db.set_jinxxy_sync_status(
        ok=False,
        product_count=None,
        error=secret_error,
    )

    response = client.get("/jinxxy")

    assert response.status_code == 200
    assert secret_error not in response.text


def test_sync_post_enqueues_jinxxy_sync(client):
    response = client.post("/jinxxy/sync")

    assert response.status_code == 200
    action_id = response.json()["id"]
    assert isinstance(action_id, int)
    row = action_queue.get_status(action_id)
    assert row["kind"] == "jinxxy_sync"
    assert row["status"] == "pending"
    assert row["requested_by"] == "manager-2"
    assert json.loads(row["payload_json"]) == {"actor_name": "Nombre"}


def test_dedupe_at_enqueue(client):
    first = client.post("/jinxxy/sync")
    second = client.post("/jinxxy/sync")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert _jinxxy_action_count() == 1


def test_dedupe_holds_while_claimed(client):
    first = client.post("/jinxxy/sync")
    duplicate = client.post("/jinxxy/sync")
    claimed = action_queue.claim_next()
    third = client.post("/jinxxy/sync")

    assert first.status_code == duplicate.status_code == third.status_code == 200
    assert claimed["id"] == first.json()["id"]
    assert duplicate.json()["id"] == first.json()["id"]
    assert third.json()["id"] == first.json()["id"]
    assert _jinxxy_action_count() == 1


def test_status_reports_never_synced_on_a_cold_database(client):
    response = client.get("/jinxxy/status")

    assert response.status_code == 200
    body = response.json()
    assert body["never_synced"] is True
    assert body["running"] is False
    assert body["last_run_utc"] is None


def test_status_reports_never_synced_when_only_the_mirror_row_exists(client):
    db.clear_jinxxy_sync_running()

    response = client.get("/jinxxy/status")

    assert response.status_code == 200
    assert response.json()["never_synced"] is True


def test_status_reports_last_run_counts(client):
    db.set_jinxxy_sync_status(
        ok=True,
        product_count=9,
        error=None,
        added_count=3,
        updated_count=2,
        removed_count=1,
    )

    response = client.get("/jinxxy/status")

    assert response.status_code == 200
    body = response.json()
    assert body["never_synced"] is False
    assert body["ok"] is True
    assert body["product_count"] == 9
    assert body["added"] == 3
    assert body["updated"] == 2
    assert body["removed"] == 1


def test_status_reports_running_with_source_and_actor(client):
    _fresh_heartbeat()
    db.mark_jinxxy_sync_running("panel", "Nombre")

    response = client.get("/jinxxy/status")

    assert response.status_code == 200
    body = response.json()
    assert body["running"] is True
    assert body["source"] == "panel"
    assert body["actor_name"] == "Nombre"
    assert body["started_at"] is not None


def test_status_voids_the_running_mirror_on_a_stale_heartbeat(client):
    _stale_heartbeat()
    db.mark_jinxxy_sync_running("panel", "Nombre")

    response = client.get("/jinxxy/status")

    assert response.status_code == 200
    assert response.json()["running"] is False
    assert response.json()["bot_online"] is False


def test_status_does_not_leak_the_raw_error_column(client):
    secret_error = "https://api.jinxxy.com/v1/products 503"
    db.set_jinxxy_sync_status(
        ok=False,
        product_count=None,
        error=secret_error,
    )

    response = client.get("/jinxxy/status")

    assert response.status_code == 200
    assert secret_error not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/jinxxy"),
        ("get", "/jinxxy/status"),
        ("post", "/jinxxy/sync"),
    ],
)
def test_jinxxy_routes_reject_non_manager(
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
