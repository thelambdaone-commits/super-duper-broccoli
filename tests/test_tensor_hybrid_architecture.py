import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.portfolio_risk_engine import PortfolioRiskEngine
from user_data.freqaimodels.HybridQuantModel import (
    HAS_TORCH,
    HybridQuantModelAdapter,
    UnifiedScoringOutput,
)


class ConstantTensorModel:
    def eval(self):
        return self

    def __call__(self, tensor):
        import torch

        batch = tensor.shape[0]
        return torch.tensor([[0.70, 0.20]] * batch, dtype=torch.float32)


@pytest.fixture
def ledger() -> MagicMock:
    ledger = MagicMock()
    ledger.get_capital_summary.return_value = {
        "total_capital": 20_000.0,
        "available_capital": 15_000.0,
    }
    return ledger


def test_unified_scoring_output_exports_scalar_signal_fields() -> None:
    output = UnifiedScoringOutput(
        market_id="btc-test",
        ml_calibrated_score=0.70,
        estimated_edge=0.12,
        is_fallback=False,
        dissimilarity_index=0.2,
    )

    fields = output.to_signal_fields()

    assert output.is_tradable(0.07) is True
    assert fields["predictive_probability"] == pytest.approx(0.70)
    assert fields["predictive_edge"] == pytest.approx(0.12)
    assert fields["is_fallback"] is False


@pytest.mark.parametrize(
    "features",
    [
        {"market_id": "empty", "microstructure_vector": [], "historical_closes": [0.62]},
        {"market_id": "nan", "microstructure_vector": [np.nan, 0.2], "historical_closes": [0.62]},
        {"market_id": "inf", "microstructure_vector": [np.inf, 0.2], "historical_closes": [0.62]},
        {"market_id": "shape", "microstructure_vector": [0.1, 0.2, 0.3], "historical_closes": [0.62]},
    ],
)
def test_tensor_adapter_falls_back_on_poisoned_features(features: dict) -> None:
    adapter = HybridQuantModelAdapter(
        model=ConstantTensorModel(),
        expected_features=2,
    )

    output = adapter.score_market(features, current_odds=0.50)

    assert output.is_fallback is True
    assert output.market_id == features["market_id"]
    assert output.ml_calibrated_score == pytest.approx(0.62)
    assert output.estimated_edge == pytest.approx(0.12)


@pytest.mark.skipif(not HAS_TORCH, reason="torch is optional")
def test_tensor_adapter_uses_cpu_tensor_path_when_valid() -> None:
    adapter = HybridQuantModelAdapter(
        model=ConstantTensorModel(),
        expected_features=2,
    )

    output = adapter.score_market(
        {"market_id": "valid", "microstructure_vector": [0.1, 0.2]},
        current_odds=0.50,
    )

    assert output.is_fallback is False
    assert output.ood_alert is False
    assert output.ml_calibrated_score == pytest.approx(0.70)
    assert output.estimated_edge == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_risk_engine_rejects_ood_and_requires_extra_edge_for_fallback(ledger: MagicMock) -> None:
    engine = PortfolioRiskEngine(ledger=ledger)

    ok_ood, reason_ood = await engine.validate_signal_risk({
        "ticker": "BTC",
        "side": "BUY",
        "price": 0.50,
        "confidence": 0.8,
        "ood_alert": True,
    })
    ok_low, reason_low = await engine.validate_signal_risk({
        "ticker": "BTC",
        "side": "BUY",
        "price": 0.50,
        "confidence": 0.8,
        "is_fallback": True,
        "predictive_edge": 0.09,
    })

    assert ok_ood is False
    assert reason_ood == "ML_OOD_ALERT"
    assert ok_low is False
    assert reason_low.startswith("ML_FALLBACK_EDGE_TOO_LOW")


def test_sizing_parity_between_tensor_and_fallback_outputs(ledger: MagicMock) -> None:
    engine = PortfolioRiskEngine(ledger=ledger)
    tensor_output = UnifiedScoringOutput(
        market_id="parity",
        ml_calibrated_score=0.70,
        estimated_edge=0.20,
        is_fallback=False,
    )
    fallback_output = UnifiedScoringOutput(
        market_id="parity",
        ml_calibrated_score=0.70,
        estimated_edge=0.20,
        is_fallback=True,
    )

    common = {
        "ticker": "BTC",
        "side": "BUY",
        "price": 0.50,
        "confidence": 0.8,
        "regime_label": "LOW_VOLATILITY",
    }
    tensor_size = engine.compute_position_size(
        **common,
        win_prob=tensor_output.ml_calibrated_score,
    )
    fallback_size = engine.compute_position_size(
        **common,
        win_prob=fallback_output.ml_calibrated_score,
    )

    assert round(tensor_size["capital_at_risk"], 2) == round(fallback_size["capital_at_risk"], 2)


def test_tensor_adapter_single_trade_latency_is_bounded() -> None:
    adapter = HybridQuantModelAdapter(
        model=ConstantTensorModel(),
        expected_features=2,
    )
    features = {"market_id": "latency", "microstructure_vector": [0.1, 0.2]}

    start = time.perf_counter()
    adapter.score_market(features, current_odds=0.50)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 25.0
