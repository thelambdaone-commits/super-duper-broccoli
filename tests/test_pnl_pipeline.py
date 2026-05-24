import pytest
from database.ledger_db import Ledger
from core.performance_attribution import PerformanceAttribution


@pytest.fixture
def temp_ledger(tmp_path):
    db_path = tmp_path / "test_pnl.db"
    ledger = Ledger(db_path=str(db_path))
    return ledger


@pytest.fixture
def perf_attr(temp_ledger):
    return PerformanceAttribution(ledger=temp_ledger)


def test_close_paper_position_populates_performance_metrics(temp_ledger):
    """Verify that closing a paper position updates performance_metrics."""
    result = temp_ledger.record_paper_order(
        ticker="SOL",
        side="BUY",
        price=0.50,
        size=100,
        confidence=0.8,
        regime_label="LOW_VOLATILITY",
        signal_source="test",
    )
    assert "position_id" in result
    pid = result["position_id"]

    temp_ledger.close_paper_position(
        position_id=pid,
        exit_price=0.75,
        pnl=25.0,
        is_win=True,
    )

    summary = temp_ledger.get_performance_summary(mode="PAPER")
    assert summary["total_trades"] == 1
    assert summary["winning_trades"] == 1
    assert summary["total_net_pnl"] == 25.0
    assert summary["win_rate"] == 1.0


def test_close_paper_position_losing_trade(temp_ledger):
    """Verify losing trade correctly updates metrics."""
    result = temp_ledger.record_paper_order(
        ticker="ETH",
        side="BUY",
        price=0.60,
        size=50,
        confidence=0.7,
        regime_label="HIGH_VOLATILITY",
        signal_source="test",
    )
    pid = result["position_id"]

    temp_ledger.close_paper_position(
        position_id=pid,
        exit_price=0.40,
        pnl=-10.0,
        is_win=False,
    )

    summary = temp_ledger.get_performance_summary(mode="PAPER")
    assert summary["total_trades"] == 1
    assert summary["winning_trades"] == 0
    assert summary["losing_trades"] == 1
    assert summary["total_net_pnl"] == -10.0


def test_close_paper_position_multiple_trades_aggregates_correctly(temp_ledger):
    """Verify multiple closed trades produce correct aggregates."""
    for i in range(3):
        r = temp_ledger.record_paper_order(
            ticker="SOL",
            side="BUY",
            price=0.50,
            size=100,
            confidence=0.8,
            regime_label="LOW_VOLATILITY",
            signal_source="test",
        )
        temp_ledger.close_paper_position(
            position_id=r["position_id"],
            exit_price=0.75,
            pnl=25.0,
            is_win=True,
        )

    for i in range(2):
        r = temp_ledger.record_paper_order(
            ticker="BTC",
            side="SELL",
            price=0.30,
            size=100,
            confidence=0.6,
            regime_label="LOW_VOLATILITY",
            signal_source="test",
        )
        temp_ledger.close_paper_position(
            position_id=r["position_id"],
            exit_price=0.40,
            pnl=-10.0,
            is_win=False,
        )

    summary = temp_ledger.get_performance_summary(mode="PAPER")
    assert summary["total_trades"] == 5
    assert summary["winning_trades"] == 3
    assert summary["losing_trades"] == 2
    assert summary["total_net_pnl"] == pytest.approx(55.0)  # 3*25 + 2*(-10)
    assert summary["win_rate"] == pytest.approx(0.6)
    assert summary["avg_win"] == pytest.approx(25.0)
    assert summary["avg_loss"] == pytest.approx(-10.0)


def test_get_historical_performance_returns_closed_trades(temp_ledger, perf_attr):
    """Verify historical_performance is queryable after trade resolution."""
    trade_id = perf_attr.enregistrer_trade(
        ticker="SOL",
        condition_id="cond_test",
        side="YES",
        entry_price=0.50,
        size=100,
        mid_price_at_signal=0.52,
        fill_price=0.50,
        confidence=0.8,
        signal_source="test",
        regime_label="LOW_VOLATILITY",
        resolution_timestamp=0,
    )
    assert trade_id != ""

    cursor = temp_ledger.conn.cursor()
    cursor.execute("SELECT * FROM active_trades WHERE trade_id = ?", (trade_id,))
    trade = dict(cursor.fetchone())

    from datetime import datetime, timezone
    cursor.execute("""
        INSERT INTO historical_performance (
            trade_id, ticker, side, entry_price, exit_price, size,
            capital_engaged, gross_pnl, friction_cost, net_pnl, is_win,
            mid_price_at_signal, fill_price, slippage, execution_loss_pct,
            alpha_source, confidence, regime_label, resolution_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_id, trade["ticker"], trade["side"], trade["entry_price"],
        0.75, trade["size"], trade["capital_engaged"],
        25.0, trade["friction_cost"], 24.0, 1,
        trade["mid_price_at_signal"], trade["fill_price"], 0.0,
        0.0, trade["signal_source"], trade["confidence"],
        trade["regime_label"], datetime.now(timezone.utc).isoformat()
    ))
    cursor.execute("DELETE FROM active_trades WHERE trade_id = ?", (trade_id,))
    temp_ledger.conn.commit()

    history = temp_ledger.get_historical_performance(limit=10)
    assert len(history) >= 1
    match = [h for h in history if h["trade_id"] == trade_id]
    assert len(match) == 1
    assert match[0]["net_pnl"] == 24.0


def test_get_historical_performance_empty_when_no_trades(temp_ledger):
    """Verify get_historical_performance returns empty list with no data."""
    history = temp_ledger.get_historical_performance(limit=10)
    assert history == []


def test_performance_summary_empty_when_no_data(temp_ledger):
    """Verify get_performance_summary returns empty dict for unknown mode."""
    summary = temp_ledger.get_performance_summary(mode="UNKNOWN_MODE")
    assert summary == {}


def test_performance_summary_all_modes_get_seeded(temp_ledger):
    """Verify all execution modes have seeded performance_metrics rows."""
    cursor = temp_ledger.conn.cursor()
    cursor.execute("SELECT DISTINCT execution_mode FROM performance_metrics")
    modes = {row["execution_mode"] for row in cursor.fetchall()}
    assert "PAPER" in modes