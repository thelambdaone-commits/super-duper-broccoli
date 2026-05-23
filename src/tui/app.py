from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Log, Label, TabbedContent, TabPane
from textual.binding import Binding
from textual.reactive import reactive

from tui.widgets.market_chart import MarketChart
from tui.widgets.stats_grid import StatsGrid
from tui.widgets.signal_feed import SignalFeed
from tui.widgets.position_table import PositionTable

logger = logging.getLogger("LobstarTUI")

class LobstarTerminal(App):
    """
    Lobstar Terminal - Professional TUI for Quant Trading.
    Inspired by Bloomberg Terminal and OpenBB.
    """

    CSS = """
    Screen {
        background: #000b1e;
    }

    Header {
        background: #001f3f;
        color: #0074D9;
        text-style: bold;
    }

    Footer {
        background: #001f3f;
        color: #7FDBFF;
    }

    #main-container {
        padding: 1;
    }

    .panel {
        border: solid #0074D9;
        background: #001529;
        margin: 1;
        height: 100%;
    }

    .status-bar {
        height: 3;
        background: #001f3f;
        color: white;
        padding-left: 1;
        padding-right: 1;
    }

    Log {
        background: #000;
        color: #00FF00;
        border: solid #333;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("s", "switch_mode", "Switch Mode (Hot-Swap)"),
        Binding("r", "refresh_data", "Refresh Data"),
        Binding("f1", "switch_tab('trading')", "Trading"),
        Binding("f2", "switch_tab('ai')", "AI & Signals"),
        Binding("f3", "switch_tab('monitoring')", "Monitoring"),
        Binding("f4", "switch_tab('risk')", "Risk"),
    ]

    execution_mode = reactive("PAPER")
    wallet_balance = reactive(0.0)
    current_ticker = reactive("")

    def __init__(self, bot_lifecycle=None, execution_mode: str = "PAPER", **kwargs):
        super().__init__(**kwargs)
        self.bot_lifecycle = bot_lifecycle
        self.execution_mode = execution_mode
        self._shutdown_cleaned_up = False
        self._signals_seen: set[tuple[str, str, str]] = set()
        self.sub_tasks = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status-bar", classes="status-bar")
        with Container(id="main-container"):
            with TabbedContent(initial="trading"):
                with TabPane("Trading (F1)", id="trading"):
                    with Horizontal():
                        with Vertical(classes="panel"):
                            yield Label("📈 MARKET DATA")
                            yield MarketChart(id="market-chart")
                        with Vertical(classes="panel"):
                            yield Label("💰 POSITIONS")
                            yield PositionTable(id="position-table")

                with TabPane("AI & Signals (F2)", id="ai"):
                    with Horizontal():
                        with Vertical(classes="panel"):
                            yield Label("🧠 AI INTELLIGENCE FEED")
                            yield SignalFeed(id="signal-feed")
                        with Vertical(classes="panel"):
                            yield Label("📊 MODEL STATS")
                            yield StatsGrid(id="stats-grid")

                with TabPane("Monitoring & Logs (F3)", id="monitoring"):
                    with Horizontal():
                        with Vertical(classes="panel"):
                            yield Label("SYSTEM LOG")
                            yield Log(id="system-log")
                        with Vertical(classes="panel"):
                            yield Label("RAW WEB EVENTS")
                            yield Log(id="web-events-log")

                with TabPane("Risk Management (F4)", id="risk"):
                    with Vertical(classes="panel"):
                        yield Label("⚖️ EXPOSURE & RISK")
                        yield Static("Risk Engine Data Loading...", id="risk-data")

        yield Footer()

    async def on_mount(self) -> None:
        self.title = "🦞 LOBSTAR QUANT TERMINAL v2.0"
        self.sub_title = f"MODE: {self.execution_mode}"
        self.query_one("#system-log").write_line("🚀 Terminal Mounted. Connecting to trading core...")

        # Access shared core components if available in context
        from core.container import ServiceContainer
        self.container = ServiceContainer.get_instance()

        # Start data update loops
        self.set_interval(1.0, self.update_market_data)
        self.set_interval(3.0, self.update_portfolio_data)
        self.set_interval(2.0, self.update_signal_feed)
        self.set_interval(1.0, self.update_status_bar)
        self.set_interval(4.0, self.update_web_events)

    async def on_unmount(self) -> None:
        await self.request_shutdown()

    async def update_market_data(self) -> None:
        try:
            ticker = self._resolve_active_ticker()
            if not ticker:
                return

            feature_store = getattr(self.container, "store", None)
            if feature_store is None:
                return

            mid_history = feature_store.get_feature_history(ticker, "mid_price", limit=120)
            if mid_history:
                latest = float(mid_history[-1]["value"] or 0.0)
                chart = self.query_one(MarketChart)
                chart.update_chart(latest, label=f"{ticker} Mid Price")
                self.current_ticker = ticker
                self.query_one("#system-log").write_line(f"Market updated for {ticker}: {latest:.4f}")
        except Exception as e:
            self.query_one("#system-log").write_line(f"Market update error: {e}")

    async def update_portfolio_data(self) -> None:
        try:
            if hasattr(self.container, "ledger"):
                positions = self.container.ledger.get_open_positions()
                self.query_one(PositionTable).update_positions(positions)
                perf = self.container.ledger.get_performance_summary(self.execution_mode)
                if perf:
                    perf = dict(perf)
                    perf["mode"] = self.execution_mode
                    self.query_one(StatsGrid).update_stats(perf)
                balance = self._extract_wallet_balance(positions)
                if balance is not None:
                    self.wallet_balance = balance
                    self.query_one("#risk-data").update(
                        f"Wallet balance estimate: {balance:.2f} USDC\nOpen positions: {len(positions)}"
                    )
                if positions:
                    self.current_ticker = str(positions[0].get("ticker", self.current_ticker or ""))
        except Exception as e:
            self.query_one("#system-log").write_line(f"Portfolio update error: {e}")

    async def update_signal_feed(self) -> None:
        try:
            history = getattr(self.container, "history", None)
            if history is None:
                return
            events = history.get_web_events(event_type="signal", window=None)
            feed = self.query_one(SignalFeed)
            for event in events[-10:]:
                raw = event.get("raw", {})
                key = (
                    str(event.get("timestamp", "")),
                    str(raw.get("ticker", raw.get("asset", ""))),
                    str(raw.get("side", raw.get("direction", ""))),
                )
                if key in self._signals_seen:
                    continue
                self._signals_seen.add(key)
                feed.add_signal(
                    {
                        "source": event.get("source", "history"),
                        "ticker": raw.get("ticker", raw.get("asset", "???")),
                        "side": raw.get("side", raw.get("direction", "???")),
                        "confidence": raw.get("confidence", raw.get("p_real", 0.0)),
                        "timestamp": event.get("timestamp", ""),
                    }
                )
        except Exception as e:
            self.query_one("#system-log").write_line(f"Signal feed error: {e}")

    async def update_web_events(self) -> None:
        try:
            history = getattr(self.container, "history", None)
            if history is None:
                return
            events = history.get_web_events(window=None)
            log = self.query_one("#web-events-log", Log)
            for event in events[-15:]:
                raw = event.get("raw", {})
                event_type = event.get("event_type", "unknown")
                source = event.get("source", "history")
                ts = event.get("timestamp", "")
                line = f"[{source}] {event_type} @ {ts} :: {raw}"
                if len(line) > 500:
                    line = line[:500] + "..."
                log.write_line(line)
        except Exception as e:
            self.query_one("#system-log").write_line(f"Web event log error: {e}")

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_refresh_data(self) -> None:
        self.query_one("#system-log").write_line("Manual refresh triggered.")
        self.refresh()

    def action_quit(self) -> None:
        self.exit()

    def action_switch_mode(self) -> None:
        target = self._next_mode()
        script = Path(__file__).resolve().parents[1] / "scripts" / "redis_control.py"
        if not script.exists():
            self.query_one("#system-log").write_line("Redis hot-swap script not found.")
            return
        try:
            result = subprocess.run(
                [os.fspath(script), target],
                capture_output=True,
                text=True,
                check=False,
            )
            output = (result.stdout or result.stderr or "").strip()
            self.query_one("#system-log").write_line(
                f"Hot-swap requested: {self.execution_mode} -> {target}"
            )
            if output:
                self.query_one("#system-log").write_line(output)
        except Exception as exc:
            self.query_one("#system-log").write_line(f"Hot-swap failed: {exc}")

    async def request_shutdown(self) -> None:
        if self._shutdown_cleaned_up:
            return
        self._shutdown_cleaned_up = True
        if self.bot_lifecycle is not None:
            try:
                await self.bot_lifecycle.stop()
            except Exception as exc:
                logger.warning("TUI shutdown cleanup failed: %s", exc)

    async def update_status_bar(self) -> None:
        try:
            status = self.query_one("#status-bar", Static)
            latency = self._estimate_latency_ms()
            ticker = self.current_ticker or "-"
            status.update(
                f"MODE={self.execution_mode} | TICKER={ticker} | "
                f"BALANCE={self.wallet_balance:.2f} USDC | LATENCY={latency:.0f} ms"
            )
        except Exception as exc:
            logger.debug("Status bar update failed: %s", exc)

    def _resolve_active_ticker(self) -> str:
        if self.current_ticker:
            return self.current_ticker
        positions = []
        try:
            positions = self.container.ledger.get_open_positions()
        except Exception:
            pass
        if positions:
            return str(positions[0].get("ticker", ""))
        return ""

    def _extract_wallet_balance(self, positions: list[dict]) -> float | None:
        if not positions:
            return None
        total = 0.0
        for position in positions:
            entry = float(position.get("entry_price", 0.0) or 0.0)
            size = float(position.get("size", 0.0) or 0.0)
            current = float(position.get("current_price", entry) or entry)
            total += max(0.0, size * current)
        return total

    def _next_mode(self) -> str:
        modes = ["PAPER", "SHADOW", "PROD"]
        current = (self.execution_mode or "PAPER").upper()
        try:
            idx = modes.index(current)
        except ValueError:
            idx = 0
        return modes[(idx + 1) % len(modes)]

    def _estimate_latency_ms(self) -> float:
        try:
            metrics = getattr(self.container, "metrics_exporter", None)
            hist = getattr(metrics, "get_latency_summary", None)
            if callable(hist):
                summary = hist()
                return float(summary.get("p95_ms", 0.0) or 0.0)
        except Exception:
            pass
        return 0.0

if __name__ == "__main__":
    app = LobstarTerminal()
    app.run()
