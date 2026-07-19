"""Tests for the /pago payments cog: staff gate, configured-only embed, response plan.

Pure logic only (no Discord runtime): ``_is_staff`` / ``build_payment_embed`` /
``plan_response`` are import-safe, so a SimpleNamespace member + monkeypatched config
values exercise every branch without a live interaction.
"""
from types import SimpleNamespace

import pytest

import config
from cogs import payments


def _member(*role_ids):
    return SimpleNamespace(roles=[SimpleNamespace(id=r) for r in role_ids])


# ── staff gate ───────────────────────────────────────────────────────────────────
def test_is_staff_true_for_configured_role(monkeypatch):
    monkeypatch.setattr(config, "PAGO_STAFF_ROLE_IDS", [111, 222])
    assert payments._is_staff(_member(999, 222)) is True


def test_is_staff_false_without_role(monkeypatch):
    monkeypatch.setattr(config, "PAGO_STAFF_ROLE_IDS", [111])
    assert payments._is_staff(_member(999)) is False


def test_is_staff_false_for_roleless(monkeypatch):
    monkeypatch.setattr(config, "PAGO_STAFF_ROLE_IDS", [111])
    assert payments._is_staff(SimpleNamespace()) is False  # no roles attr → falsy


# ── embed: only configured methods appear, in order ────────────────────────────────
def _set_methods(monkeypatch, mx="", intl="", paypal=""):
    monkeypatch.setattr(config, "PAGO_DEPOSITO_MX_INFO", mx)
    monkeypatch.setattr(config, "PAGO_INTERNACIONAL_INFO", intl)
    monkeypatch.setattr(config, "PAGO_PAYPAL_INFO", paypal)


def test_embed_none_when_nothing_configured(monkeypatch):
    _set_methods(monkeypatch)
    assert payments.build_payment_embed() is None


def test_embed_includes_only_configured_methods(monkeypatch):
    _set_methods(monkeypatch, mx="CLABE 0001", paypal="paypal.me/nocturna")
    embed = payments.build_payment_embed()
    names = [f.name for f in embed.fields]
    values = [f.value for f in embed.fields]
    assert len(embed.fields) == 2  # intl omitted (blank)
    assert any("México" in n for n in names)
    assert any("PayPal" in n for n in names)
    assert not any("Revolut" in n for n in names)
    assert "CLABE 0001" in values and "paypal.me/nocturna" in values


def test_embed_strips_whitespace_only_values(monkeypatch):
    _set_methods(monkeypatch, mx="   ", paypal="x@y.com")
    embed = payments.build_payment_embed()
    assert len(embed.fields) == 1
    assert embed.fields[0].value == "x@y.com"


# ── response plan (what /pago sends) ──────────────────────────────────────────────
def test_plan_non_staff_is_ephemeral_denial():
    assert payments.plan_response(False, object()) == ("Sin permisos.", None, True)


def test_plan_staff_no_methods_is_ephemeral_warning():
    content, embed, ephemeral = payments.plan_response(True, None)
    assert embed is None and ephemeral is True and "configurados" in content


def test_plan_staff_with_embed_is_public():
    sentinel = object()
    assert payments.plan_response(True, sentinel) == (None, sentinel, False)
