from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

import numpy as np

from bootstrap.helpers import run_blocking, should_broadcast_message
from bootstrap.runtime_context import RuntimeContext
from utils.clob_feed_utils import extract_live_clob_token_ids
from utils.message_formatter import format_scan_report_html, format_market_report, format_winning_bets_alert


DEFAULT_TICKERS = ["SOL", "BTC", "ETH"]


@dataclass(slots=True)
class MarketScanLoop:
    ctx: RuntimeContext
    listener: Any
    clob_listener: Any
    broadcaster: Any
    orchestrator: Any
    crypto_intelligence: Any

    async def run(self) -> None:
        from utils.market_scanner import SCAN_INTERVAL_SECONDS

        market_scanner = self.ctx.market_scanner
        store = self.ctx.store
        snapshot_mgr = self.ctx.snapshot_mgr
        ledger = self.ctx.ledger
        passive_executor = self.ctx.passive_executor

        for _ in range(30):
            if self.listener.application:
                break
            await asyncio.sleep(1)

        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Market scanner started (interval={SCAN_INTERVAL_SECONDS}s)")

        last_crypto_intelligence_at = 0.0
        crypto_intelligence_interval = int(os.getenv("CRYPTO_INTELLIGENCE_INTERVAL_SECONDS", "1800"))
        last_sentiment = None
        iteration_count = 0

        try:
            top_markets = await run_blocking(
                "prime live clob token ids",
                market_scanner.client.list_markets,
                limit=25,
                sort_by="volume",
                timeout=30.0,
            )
            live_token_ids = extract_live_clob_token_ids(top_markets)
            if ledger:
                try:
                    open_pos = ledger.get_open_positions()
                    for pos in open_pos:
                        tid = pos.get("ticker")
                        if tid and tid not in live_token_ids:
                            live_token_ids.append(tid)
                except Exception:
                    pass
            if live_token_ids:
                async def _persist_live_snapshot(snapshot: dict[str, Any]) -> None:
                    snapshot_mgr.capture(
                        category="SYSTEM",
                        component="CLOB_ORDERBOOK",
                        data=snapshot,
                        tags=["live", "clob", snapshot.get("token_id", "unknown")],
                    )
                    if ledger:
                        ticker = snapshot.get("token_id")
                        mid_price = snapshot.get("mid_price")
                        if ticker and mid_price:
                            open_pos = [p for p in ledger.get_open_positions() if p.get("ticker") == ticker]
                            if open_pos:
                                due = ledger.get_positions_due_for_exit({ticker: mid_price})
                                for pos in due:
                                    asyncio.create_task(_execute_exit(pos))

                async def _execute_exit(pos: dict):
                    reason = pos.get("exit_reason", "unknown")
                    ticker = pos.get("ticker", "")
                    pos_id = pos.get("position_id", "")
                    entry = float(pos.get("entry_price", 0.0))
                    exit_p = float(pos.get("exit_price", 0.0))
                    entry_side = pos.get("side", "BUY").upper()
                    exit_side = "SELL" if entry_side == "BUY" else "BUY"
                    size = float(pos.get("size", 0.0))
                    try:
                        exec_res = await passive_executor.execute(
                            ticker=ticker,
                            side=exit_side,
                            price=exit_p,
                            size=size,
                            override_strict_maker=True,
                        )
                        if exec_res.get("status") in ("FILLED", "TAKER_FILLED"):
                            ledger.close_position(pos_id, exit_price=exit_p)
                            pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0.0
                            await self.listener.send_message(
                                f"⏹ <b>[FAST-PATH] Position Closed</b>\n"
                                f"Ticker: <code>{ticker}</code>\nExit: <code>{exit_p:.4f}</code>\nPnL: <b>{pnl_pct:+.2f}%</b>",
                                parse_mode="HTML",
                            )
                    except Exception as e:
                        logger.error(f"Error in fast-path SL/TP execution: {e}")

                # The lifecycle owns the CLOB listener task. MarketScanLoop only
                # updates subscriptions to avoid creating unawaited coroutines.
        except Exception:
            pass

        while True:
            try:
                iteration_count += 1
                is_first_scan = iteration_count == 1
                result = await run_blocking(
                    "market scan",
                    market_scanner.scan_markets,
                    timeout=float(os.getenv("MARKET_SCAN_TIMEOUT_SECONDS", "60")),
                )
                if result.total_markets_scanned > 0:
                    if is_first_scan:
                        signals = (
                            result.winning_bets
                            + result.trending_markets
                            + result.competitive_markets
                            + result.arbitrage_opportunities
                        )
                        report = format_scan_report_html(result) if signals else format_market_report(
                            await run_blocking("market report fallback", market_scanner.client.list_markets, limit=10, timeout=30.0)
                        )
                        if should_broadcast_message("baseline_report", report):
                            await self.listener.send_message(report, parse_mode="HTML")
                        snapshot_mgr.capture(category="SYSTEM", component="MARKET_REPORT", data={"report": report}, tags=["periodic", "market_scan", "first_run"])
                        snapshot_mgr.capture(category="TRADING", component="MARKET_SCAN_RESULTS", data={"timestamp": result.timestamp, "total_markets": result.total_markets_scanned}, tags=["market_scan", "first_run", "gems"])
                    sentiment = result.aggregate_sentiment.get("sentiment", "NEUTRAL")
                    if sentiment != last_sentiment:
                        mood = result.aggregate_sentiment.get("bullish_pct", 50)
                        msg = f"🌍 <b>Market Feeling</b>: <code>{sentiment}</code> ({mood:.1f}% bull)"
                        if should_broadcast_message("market_feeling", msg):
                            await self.listener.send_message(msg, parse_mode="HTML")
                        last_sentiment = sentiment
                    await run_blocking("record scanner features", market_scanner.record_features, store, timeout=30.0)
                    await self.broadcaster.scan_and_broadcast()
                    now = datetime.now(timezone.utc).timestamp()
                    should_run_intelligence = is_first_scan or (now - last_crypto_intelligence_at) >= crypto_intelligence_interval
                    if should_run_intelligence:
                        markets = await run_blocking("crypto intelligence market fetch", market_scanner.client.list_markets, limit=100, sort_by="volume", timeout=30.0)
                        intelligence_report = await run_blocking("crypto intelligence analysis", self.crypto_intelligence.analyze, markets, timeout=30.0)
                        if intelligence_report.crypto_market_count > 0:
                            intelligence_text = self.crypto_intelligence.format_intelligence_report(intelligence_report) if hasattr(self.crypto_intelligence, "format_intelligence_report") else format_scan_report_html(result)
                            if should_broadcast_message("crypto_intelligence", intelligence_text):
                                sent = await self.listener.send_message(intelligence_text, parse_mode="HTML")
                                if sent:
                                    last_crypto_intelligence_at = now
                    all_signals = (
                        result.winning_bets
                        + result.trending_markets
                        + result.competitive_markets
                        + result.arbitrage_opportunities
                    )

                    if all_signals:
                        # Alert for winning bets (highest priority)
                        if result.winning_bets:
                            alert = format_winning_bets_alert(result.winning_bets[:3])
                            if alert and should_broadcast_message("winning_bets_alert", alert):
                                await self.listener.send_message(alert, parse_mode="HTML")
                        
                        # Process all signals
                        for bet in all_signals:
                            try:
                                if self.clob_listener:
                                    self.clob_listener.subscribe([bet.ticker])
                                signal = {
                                    "ticker": bet.ticker,
                                    "side": bet.side,
                                    "price": bet.price,
                                    "confidence": bet.confidence,
                                    "reason": bet.reason,
                                    "market_question": bet.market_question,
                                    "market_slug": bet.market_slug,
                                    "source": "market_scanner",
                                    "token_id": bet.ticker,
                                    "size": 0.0,
                                    "market_features": getattr(bet, "market_features", {}),
                                }
                                await self.orchestrator.on_signal(signal)
                            except Exception as e:
                                logger.warning(f"Failed to auto-trade signal {bet.ticker}: {e}")
                else:
                    logger.warning("Scan returned 0 markets — check API connectivity")
            except Exception as e:
                logger.error(f"❌ [MARKET SCAN] Failed: {e}")
            finally:
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@dataclass(slots=True)
class HMMTrainingLoop:
    ctx: RuntimeContext
    market_scanner: Any
    hmm: Any

    async def run(self) -> None:
        try:
            markets = await run_blocking("hmm training data fetch", self.market_scanner.client.list_markets, limit=50, sort_by="volume", timeout=30.0)
            prob_series: list[float] = []
            for m in markets[:10]:
                try:
                    ob = await run_blocking(f"orderbook {m.id}", self.market_scanner.client.get_order_book, m.id, timeout=15.0)
                    prob_series.append(float(ob.get("midpoint", 0.5) or 0.5))
                except Exception:
                    pass
            if len(prob_series) >= 20:
                returns = np.diff(np.log(np.clip(prob_series, 0.01, 0.99)))
                returns = returns[np.isfinite(returns)]
                if len(returns) >= 10:
                    self.hmm.fit(returns)
        except Exception:
            pass


@dataclass(slots=True)
class SLTPMonitoringLoop:
    ctx: RuntimeContext
    ledger: Any
    passive_executor: Any
    listener: Any

    async def run(self) -> None:
        try:
            open_positions = self.ledger.get_open_positions()
            if not open_positions:
                return
            current_prices: dict[str, float] = {}
            for pos in open_positions:
                ticker = pos.get("ticker", "")
                if ticker in current_prices:
                    continue
                try:
                    ob = await run_blocking(f"sltp orderbook {ticker}", self.ctx.market_scanner.client.get_order_book, ticker, timeout=10.0)
                    mid = float(ob.get("midpoint", 0.0) or ob.get("price", 0.0))
                    if mid > 0:
                        current_prices[ticker] = mid
                except Exception:
                    pass
            due = self.ledger.get_positions_due_for_exit(current_prices)
            for pos in due:
                reason = pos.get("exit_reason", "unknown")
                ticker = pos.get("ticker", "")
                pos_id = pos.get("position_id", "")
                entry = float(pos.get("entry_price", 0.0))
                exit_p = float(pos.get("exit_price", 0.0))
                pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0.0
                entry_side = pos.get("side", "BUY").upper()
                exit_side = "SELL" if entry_side == "BUY" else "BUY"
                size = float(pos.get("size", 0.0))
                if size > 0:
                    exec_res = await self.passive_executor.execute(ticker=ticker, side=exit_side, price=exit_p, size=size, override_strict_maker=True)
                    if exec_res.get("status") not in ("FILLED", "TAKER_FILLED"):
                        continue
                self.ledger.close_position(pos_id, exit_price=exit_p)
                try:
                    await self.listener.send_message(
                        f"⏹ <b>Position Closed</b>\nTicker: <code>{ticker}</code>\n"
                        f"Entry: <code>{entry:.4f}</code> → Exit: <code>{exit_p:.4f}</code>\n"
                        f"PnL: <b>{pnl_pct:+.2f}%</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        except Exception:
            pass


@dataclass(slots=True)
class ModelDriftAndHealthLoop:
    ctx: RuntimeContext
    model_validator: Any
    training_pipeline: Any
    self_improver: Any
    listener: Any

    async def run(self) -> None:
        for ticker in DEFAULT_TICKERS:
            try:
                report = await run_blocking(f"model health check {ticker}", self.model_validator.run_health_check, ticker, "default_v1", timeout=30.0)
                if report.get("health") == "CRITICAL":
                    await self.listener.send_message(
                        f"🚨 <b>DRIFT DETECTED: {ticker}</b>\n\nModel failed. Retraining triggered...",
                        parse_mode="HTML",
                    )
                    try:
                        await run_blocking(f"training cycle {ticker}", self.training_pipeline.run_cycle, ticker, timeout=float(os.getenv("TRAINING_CYCLE_TIMEOUT_SECONDS", "300")))
                        await self.listener.send_message(
                            f"✅ <b>RECALIBRATION COMPLETE: {ticker}</b>\n\nWeights redeployed.",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        await self.listener.send_message(
                            f"❌ <b>RECALIBRATION FAILED: {ticker}</b>\n\nError: <code>{e}</code>",
                            parse_mode="HTML",
                        )
                    self.self_improver.log_incident("MODEL_DRIFT", f"Drift detected for {ticker}", "Distribution shift", "Prediction accuracy degradation")
            except Exception:
                pass
        try:
            imp_report = await run_blocking("self-improvement report", self.self_improver.generate_improvement_report, timeout=30.0)
            await self.listener.send_message(imp_report, parse_mode="HTML")
        except Exception:
            pass
