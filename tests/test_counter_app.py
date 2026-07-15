"""Behaviour tests for the self-hosted view counter (Fase 10.1, plan 10.1-12, D-25).

Covers the endpoint contract ``ViewCounter.astro`` calls — increment, read-only, unknown-slug
→ 0, malformed-slug reject — plus the two mitigations from the threat register: the per-slug+
ip_hash dedup window (a reload doesn't inflate the count, T-10.1-12-01) and IP-as-hash storage
(never the raw address, T-10.1-12-02).

Each test runs against a throwaway sqlite file (``config.DB_PATH`` monkeypatched to ``tmp_path``)
so the tables are created fresh by the app's lifespan startup and never touch the real bot.db.
"""

import pytest
from fastapi.testclient import TestClient

import config
from app.counter_app import app
from core import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point every _get_conn() at a throwaway db; the app lifespan creates the tables on startup.
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "views.db")
    with TestClient(app) as c:
        yield c


# ── Endpoint contract: increment + read-only ─────────────────────────────────────
def test_hit_increments_and_returns_fresh_count(client):
    r1 = client.get("/api/views/aria?hit=1", headers={"X-Forwarded-For": "1.1.1.1"})
    assert r1.status_code == 200
    assert r1.json() == {"count": 1}

    # A different IP is a distinct viewer → the count advances.
    r2 = client.get("/api/views/aria?hit=1", headers={"X-Forwarded-For": "2.2.2.2"})
    assert r2.json() == {"count": 2}


def test_read_only_without_hit_does_not_increment(client):
    client.get("/api/views/luna?hit=1", headers={"X-Forwarded-For": "3.3.3.3"})
    r = client.get("/api/views/luna")  # no hit → read-only
    assert r.status_code == 200
    assert r.json() == {"count": 1}


# ── T-10.1-12-01: dedup window (a reload can't inflate the count) ─────────────────
def test_reload_same_ip_is_deduped_noop(client):
    client.get("/api/views/nyx?hit=1", headers={"X-Forwarded-For": "9.9.9.9"})
    reload = client.get("/api/views/nyx?hit=1", headers={"X-Forwarded-For": "9.9.9.9"})
    assert reload.status_code == 200
    assert reload.json() == {"count": 1}  # same IP within the window → no-op


# ── Never 500 on a missing slug; reject a malformed one ──────────────────────────
def test_unknown_slug_returns_zero(client):
    r = client.get("/api/views/nonexistent")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


def test_malformed_slug_is_rejected(client):
    # Underscore + uppercase are outside [a-z0-9-] → rejected before any DB access.
    r = client.get("/api/views/Bad_Slug")
    assert r.status_code == 404


# ── T-10.1-12-02: only a HASH of the IP is stored, never the raw address ──────────
def test_ip_is_stored_as_hash_only(client, monkeypatch):
    client.get("/api/views/aria?hit=1", headers={"X-Forwarded-For": "5.5.5.5"})
    with db._get_conn() as conn:
        rows = conn.execute("SELECT ip_hash FROM view_dedup").fetchall()
    assert rows, "dedup row should be recorded on a hit"
    stored = rows[0]["ip_hash"]
    assert stored != "5.5.5.5"            # never the raw IP
    assert len(stored) == 64              # sha256 hex digest length


# ── CORS allows the public site origin (a different origin from the editors subdomain) ──
def test_cors_allows_public_site_origin(client):
    origin = config.WEBSITE_BASE_URL.rstrip("/")
    r = client.get(
        "/api/views/aria",
        headers={"Origin": origin},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
