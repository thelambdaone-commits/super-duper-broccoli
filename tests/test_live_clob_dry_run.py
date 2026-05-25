from __future__ import annotations

from scripts import live_clob_dry_run


def test_resolve_signature_type_uses_deposit_wallet_default(monkeypatch) -> None:
    monkeypatch.delenv("POLYMARKET_SIGNATURE_TYPE", raising=False)
    assert live_clob_dry_run._resolve_signature_type("0xproxy") == 3


def test_resolve_signature_type_respects_explicit_env_override(monkeypatch) -> None:
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "7")
    assert live_clob_dry_run._resolve_signature_type("0xproxy") == 7
    assert live_clob_dry_run._resolve_signature_type(None) == 7
