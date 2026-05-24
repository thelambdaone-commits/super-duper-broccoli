from __future__ import annotations

from textual.widgets import Static, Label
from textual.containers import Grid

class StatsGrid(Static):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loaded = False

    def compose(self):
        with Grid():
            yield Label("Win Rate:", id="win-rate-label")
            yield Label("0%", id="win-rate-val")
            yield Label("Sharpe:", id="sharpe-label")
            yield Label("0.0", id="sharpe-val")
            yield Label("Trades:", id="trades-label")
            yield Label("0", id="trades-val")
            yield Label("PnL:", id="pnl-label")
            yield Label("0.0", id="pnl-val")
            yield Label("Drawdown:", id="dd-label")
            yield Label("0.0%", id="dd-val")
            yield Label("Mode:", id="mode-label")
            yield Label("PAPER", id="mode-val")

    def update_stats(self, stats: dict):
        self.query_one("#win-rate-val").update(f"{stats.get('win_rate', 0):.1%}")
        self.query_one("#sharpe-val").update(f"{stats.get('sharpe', 0):.2f}")
        self.query_one("#trades-val").update(str(stats.get('total_trades', 0)))
        self.query_one("#pnl-val").update(f"{stats.get('total_net_pnl', stats.get('net_pnl', 0.0)):+.2f}")
        drawdown = stats.get("max_drawdown", stats.get("drawdown", 0.0))
        self.query_one("#dd-val").update(f"{float(drawdown or 0.0):.1%}")
        self.query_one("#mode-val").update(str(stats.get("mode", stats.get("execution_mode", "PAPER"))))
