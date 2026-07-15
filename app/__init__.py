"""Editor admin web app (Fase 10) — Discord-OAuth2-gated FastAPI service.

A small internet-facing web app that lets a Nocturna editor log in with Discord
OAuth2, and (in later plans, 10-09/10-10) build a block-based profile page whose
save commits ``editors.json`` + images to the website repo via the same cross-repo
transport the bot already uses (``core/github_publish.py``).

This package is the project's FIRST authenticated web surface. The trust boundary is
established here (10-08) before any editing UI exists:

* ``auth``  — Authlib Discord OAuth2 + a hard bot-token guild-role gate (D-07/D-15) +
  first-login auto-draft creation (D-09).
* ``deps``  — ``require_editor()``, the ownership-scoped dependency that resolves the
  editable identity from the SESSION only, never a request body (D-08 IDOR choke point).
* ``main``  — the FastAPI app: signed short-TTL SessionMiddleware (V3) + route wiring +
  fail-fast config validation.

Runs as its own systemd unit on the ``cinema`` host behind Caddy (automatic HTTPS),
sharing the bot's venv, ``config.py`` and ``core/`` by direct import (D-06). It is NOT
loaded by the discord.py bot process.
"""
