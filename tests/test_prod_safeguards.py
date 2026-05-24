from main_agentic_clob import require_production_confirmation, resolve_execution_mode


def test_prod_confirmation_skips_non_prod_modes(monkeypatch):
    require_production_confirmation("PAPER")


def test_prod_confirmation_requires_secret_for_prod() -> None:
    import pytest
    from utils.exceptions import QuantFatal
    with pytest.raises(QuantFatal, match="LOBSTAR_PROD_CONFIRM_SECRET"):
        require_production_confirmation("PROD")


def test_prod_confirmation_accepts_force_prod_non_interactive(monkeypatch) -> None:
    monkeypatch.setenv("LOBSTAR_PROD_CONFIRM_SECRET", "test-secret")
    monkeypatch.setenv("FORCE_PROD", "true")
    require_production_confirmation("PROD")


def test_prod_confirmation_force_prod_bypasses_secret(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_PROD", "true")
    require_production_confirmation("PROD")


def test_resolve_execution_mode_prefers_cli(monkeypatch):
    monkeypatch.setenv("REAL", "true")
    monkeypatch.setenv("PAPER", "true")

    assert resolve_execution_mode("SHADOW") == "SHADOW"


def test_resolve_execution_mode_prefers_real_when_both_set(monkeypatch, caplog):
    monkeypatch.setenv("REAL", "true")
    monkeypatch.setenv("PAPER", "true")

    with caplog.at_level("INFO"):
        mode = resolve_execution_mode(None)

    assert mode == "PROD"
    assert "Both REAL=true and PAPER=true are set" in caplog.text
    assert "Execution mode resolved from env: PROD" in caplog.text


def test_resolve_execution_mode_defaults_to_paper(monkeypatch, caplog):
    monkeypatch.delenv("REAL", raising=False)
    monkeypatch.delenv("PAPER", raising=False)

    with caplog.at_level("INFO"):
        mode = resolve_execution_mode(None)

    assert mode == "PAPER"
    assert "Execution mode fallback: PAPER" in caplog.text
