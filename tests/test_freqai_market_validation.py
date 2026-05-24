import pytest

from core.freqai_engine import FreqAIEngine


class _BooklessClient:
    def get_order_book(self, token_id):
        raise RuntimeError(f"market not found for {token_id}")


class _InactiveBookClient:
    def get_order_book(self, token_id):
        return {"active": False, "closed": True, "archived": False}


def test_normalize_and_validate_rejects_missing_market() -> None:
    engine = object.__new__(FreqAIEngine)
    engine.client = _BooklessClient()

    with pytest.raises(ValueError, match="token_id invalide|marché indisponible"):
        engine.normalize_and_validate("token-1", 0.5, 10)


def test_normalize_and_validate_rejects_inactive_market() -> None:
    engine = object.__new__(FreqAIEngine)
    engine.client = _InactiveBookClient()

    with pytest.raises(ValueError, match="marché inactif/résolu"):
        engine.normalize_and_validate("token-1", 0.5, 10)

