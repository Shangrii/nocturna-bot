"""INFRA-02 go/no-go gate (D-12): simulated bot write-loop + panel write burst against
the SAME sqlite file must never raise an unhandled 'database is locked'.

Run with the project's conda interpreter (per project test-run convention):
  C:\\Users\\Shangri\\miniconda3\\python.exe -m pytest tests/test_action_queue_concurrency.py -v
"""
import concurrent.futures
import sqlite3
import threading

import pytest

import config
from core import action_queue, db


def _use_tmp_db(monkeypatch, tmp_path):
    # tmp_path is always a LOCAL filesystem path under pytest — required for WAL (core/db.py
    # docstring notes WAL does not work over a network share).
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "concurrency.db"), raising=False)


# DEVELOPMENT-TIME sanity check (never commit the flaky form): temporarily remove the
# busy_timeout pragma and _retry_on_locked decorator, then run this once locally. It should
# intermittently raise "database is locked", proving the harness reproduces the fixed failure.
def test_concurrent_bot_and_panel_writes_never_raise_database_locked(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_action_queue()

    stop = threading.Event()
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def _record(exc):
        with errors_lock:
            errors.append(exc)

    def bot_loop():
        # Tight loop (no sleep) — simulates the ActionQueueCog's ~1.5s tick but maximizes
        # contention density for the test's duration instead of waiting real wall-clock time.
        while True:
            try:
                action_queue.recover_stale_claims()
                row = action_queue.claim_next()
                if row is not None:
                    action_queue.complete(row["id"], {"ok": True})
                elif stop.is_set():
                    break
            except sqlite3.OperationalError as exc:
                _record(exc)

    def panel_burst(n: int):
        for i in range(n):
            try:
                action_queue.enqueue("noop", {"i": i}, requested_by="test-manager")
            except sqlite3.OperationalError as exc:
                _record(exc)

    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    # 16 concurrent "panel clicks", 25 writes each = 400 rapid inserts racing the bot
    # thread's claim/complete writes on the same file.
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(panel_burst, 25) for _ in range(16)]
        concurrent.futures.wait(futures, timeout=30)

    stop.set()
    bot_thread.join()

    assert errors == [], f"'database is locked' escaped unhandled: {errors!r}"

    # Sanity: every enqueued row was eventually claimed+completed (nothing silently lost).
    with db._get_conn() as conn:
        remaining_pending = conn.execute(
            "SELECT COUNT(*) AS n FROM action_queue WHERE status='pending'"
        ).fetchone()["n"]
    assert remaining_pending == 0
