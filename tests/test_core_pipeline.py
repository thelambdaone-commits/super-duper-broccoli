import pytest
import numpy as np
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ledger.ledger_db import Ledger, SCHEMA_PATH
from user_data.strategies.feature_pipeline import (
    compute_order_imbalance,
    compute_order_imbalance_from_frame,
    ternary_agreement_model,
    polymarket_time_to_resolution,
)


@pytest.fixture
def ledger() -> Ledger:
    return Ledger(db_path=":memory:", schema_path=SCHEMA_PATH)


def test_circuit_breaker_hard_cap(ledger: Ledger) -> None:
    ticker = "0x12345"
    side = "YES"
    limit_price = 0.50
    oversized_size = 2000.0

    result = ledger.validate_and_reserve(ticker, side, limit_price, oversized_size)

    assert result["authorized"] is True
    assert result["size"] == 1000.0
    assert result["capital"] == 500.0
    assert "circuit breaker" in result["reason"].lower()


def test_insufficient_capital(ledger: Ledger) -> None:
    ticker = "0x12345"
    side = "YES"
    limit_price = 100.0
    size = 200.0

    result = ledger.validate_and_reserve(ticker, side, limit_price, size)

    assert result["authorized"] is False
    assert "Insufficient capital" in result["reason"]


def test_nominal_validation(ledger: Ledger) -> None:
    ticker = "0x12345"
    side = "YES"
    limit_price = 0.50
    size = 100.0

    result = ledger.validate_and_reserve(ticker, side, limit_price, size)

    assert result["authorized"] is True
    assert result["size"] == 100.0
    assert result["capital"] == 50.0
    assert "nominal" in result["reason"].lower()


def test_order_imbalance_nominal() -> None:
    bids = np.array([100.0, 200.0], dtype=np.float32)
    asks = np.array([50.0, 150.0], dtype=np.float32)
    oi = compute_order_imbalance(bids, asks)
    expected = (bids - asks) / (bids + asks)
    np.testing.assert_array_almost_equal(oi, expected.astype(np.float32))


def test_order_imbalance_zero_volume() -> None:
    bids = np.array([0.0, 0.0], dtype=np.float32)
    asks = np.array([0.0, 0.0], dtype=np.float32)
    oi = compute_order_imbalance(bids, asks)
    assert oi[0] == 0.0
    assert oi[1] == 0.0


def test_order_imbalance_single_side() -> None:
    bids = np.array([100.0], dtype=np.float32)
    asks = np.array([0.0], dtype=np.float32)
    oi = compute_order_imbalance(bids, asks)
    assert oi[0] == pytest.approx(1.0)


def test_order_imbalance_from_frame() -> None:
    df = pd.DataFrame({
        "bid_volume": [100.0, 200.0, 0.0],
        "ask_volume": [50.0, 150.0, 0.0],
    })
    oi = compute_order_imbalance_from_frame(df)
    expected = np.float32([50.0 / 150.0, 50.0 / 350.0, 0.0])
    np.testing.assert_array_almost_equal(oi.values, expected)


def test_ternary_agreement_model_agreement() -> None:
    btc = pd.Series([0.01, 0.01, 0.01, 0.01], name="btc")
    alt = pd.Series([0.015, 0.015, 0.015, 0.015], name="alt")
    tam = ternary_agreement_model(btc, alt, lag=1, threshold=0.001)
    valid = tam.dropna()
    assert (valid["tam_state"] == 1).all()
    assert (valid["tam_agreement"] == 1).all()
    assert (valid["tam_disagreement"] == 0).all()


def test_polymarket_time_to_resolution() -> None:
    now = pd.Timestamp("2025-01-15")
    timestamps = pd.Series([pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-01")])
    expiration = pd.Timestamp("2025-01-20")
    ttr = polymarket_time_to_resolution(timestamps, expiration)
    assert ttr.iloc[0] == pytest.approx(10.0, rel=0.1)
    assert ttr.iloc[1] == pytest.approx(19.0, rel=0.1)
