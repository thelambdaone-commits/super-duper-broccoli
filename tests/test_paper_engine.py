import pytest

from execution.paper_engine import PolymarketPaperEngine


@pytest.mark.asyncio
async def test_market_order_sweeps_book_and_marks_partial_all_in_cost() -> None:
    engine = PolymarketPaperEngine(latency_min_ms=0, latency_max_ms=0, friction_per_contract=0.005)
    orderbook = {
        "bids": [[0.49, 100]],
        "asks": [[0.50, 50], [0.60, 50]],
    }

    result = await engine.execute_order(
        ticker="SOL",
        side="BUY",
        order_type="MARKET",
        target_price=0.50,
        allocated_capital=100.0,
        orderbook=orderbook,
    )

    assert result.status == "SUCCESS"
    assert result.partial_fill is True
    assert result.size_contracts == pytest.approx(100.0)
    assert result.filled_volume_usdc == pytest.approx(55.0)
    assert result.fill_price == pytest.approx(0.55)
    assert result.friction_cost == pytest.approx(0.50)
    assert result.spread_slippage_cost == pytest.approx(5.5)
    assert result.total_execution_cost == pytest.approx(6.0)


def test_limit_fill_probability_uses_order_imbalance() -> None:
    engine = PolymarketPaperEngine()
    balanced_bids = [(0.49, 100)]
    balanced_asks = [(0.51, 100)]
    ask_heavy_bids = [(0.49, 50)]
    ask_heavy_asks = [(0.51, 250)]

    balanced = engine._calculate_limit_fill_probability("BUY", 0.48, balanced_bids, balanced_asks)
    ask_heavy = engine._calculate_limit_fill_probability("BUY", 0.48, ask_heavy_bids, ask_heavy_asks)

    assert ask_heavy > balanced


@pytest.mark.asyncio
async def test_lookahead_orderbook_is_rejected() -> None:
    engine = PolymarketPaperEngine(latency_min_ms=0, latency_max_ms=0)

    result = await engine.execute_order(
        ticker="SOL",
        side="BUY",
        order_type="MARKET",
        target_price=0.50,
        allocated_capital=10.0,
        orderbook={
            "signal_timestamp": 100.0,
            "timestamp": 101.0,
            "bids": [[0.49, 100]],
            "asks": [[0.50, 100]],
        },
    )

    assert result.status == "REJECTED"
    assert "Look-ahead" in result.reason
