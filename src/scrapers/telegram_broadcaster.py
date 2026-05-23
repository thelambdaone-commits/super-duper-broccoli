from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional, Sequence

from utils.notifier import TelegramNotifier
from utils.polymarket_client import Market, PolymarketClient
from utils.security_utils import decrypt_data
from utils.telegram.formatter import TelegramMessageFormatter

logger = logging.getLogger("TelegramBroadcaster")


@dataclass(frozen=True)
class BroadcastSignal:
    ticker: str
    market_slug: str
    market_question: str
    calibrated_probability: float
    market_probability: float
    edge: float
    action: str
    model_version: str = "HybridQuantModel"
    calibrator_version: str = "ProbabilityCalibrator"
    timestamp: str = ""


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: int = 3,
        refill_period_seconds: float = 60.0,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_period_seconds <= 0:
            raise ValueError("refill_period_seconds must be > 0")
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_rate = float(capacity) / float(refill_period_seconds)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated_at
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self._updated_at = now

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait_seconds = max(0.0, (1.0 - self.tokens) / self.refill_rate)
            await asyncio.sleep(wait_seconds)


class BroadcastMemory:
    def __init__(
        self,
        ttl_seconds: int = 3600,
        max_entries: int = 256,
        probability_bucket: float = 0.01,
        feature_store: Any = None,
    ) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self.probability_bucket = max(0.0001, float(probability_bucket))
        self._sent_at: dict[str, float] = {}
        self._last_by_ticker: dict[str, BroadcastSignal] = {}

        if feature_store is not None:
            self.rehydrate_from_db(feature_store)

    def rehydrate_from_db(self, feature_store: Any) -> None:
        try:
            cutoff = time.time() - self.ttl_seconds
            signals = feature_store.replay_signals(since_timestamp=cutoff, limit=self.max_entries)

            rehydrated_count = 0
            for sig in signals:
                ticker = sig.get("ticker")
                side = sig.get("side")
                price = sig.get("price") or 0.0
                confidence = sig.get("confidence") or 0.0
                timestamp_val = sig.get("timestamp") or time.time()

                if not ticker or not side:
                    continue

                market_slug = ""
                raw_dec = sig.get("decision_json")
                if raw_dec:
                    try:
                        decrypted = decrypt_data(raw_dec)
                        decision = json.loads(decrypted)
                        market_slug = decision.get("market_slug", "")
                    except Exception:
                        pass

                broadcast_sig = BroadcastSignal(
                    ticker=ticker,
                    market_slug=market_slug,
                    market_question="",
                    calibrated_probability=confidence,
                    market_probability=price,
                    edge=confidence - price,
                    action=side,
                    timestamp=datetime.fromtimestamp(timestamp_val, timezone.utc).isoformat()
                )
                self._sent_at[self.signature(broadcast_sig)] = timestamp_val
                self._last_by_ticker[ticker.upper()] = broadcast_sig
                rehydrated_count += 1

            if rehydrated_count > 0:
                logger.info(
                    "💾 [TEMPORAL RECOVERY] Rehydrated %d historical signals from FeatureStore to prevent duplication.",
                    rehydrated_count,
                )
        except Exception as e:
            logger.warning("⚠️ [TEMPORAL RECOVERY] Rehydration from FeatureStore failed: %s", e)

    def _bucket(self, value: float) -> int:
        return round(float(value) / self.probability_bucket)

    def signature(self, signal: BroadcastSignal) -> str:
        return "|".join(
            [
                signal.ticker.upper(),
                signal.market_slug,
                signal.action.upper(),
                str(self._bucket(signal.calibrated_probability)),
                str(self._bucket(signal.market_probability)),
                str(self._bucket(signal.edge)),
            ]
        )

    def prune(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        expired = [key for key, sent_at in self._sent_at.items() if now - sent_at >= self.ttl_seconds]
        for key in expired:
            self._sent_at.pop(key, None)

        while len(self._sent_at) > self.max_entries:
            oldest = min(self._sent_at, key=self._sent_at.get)
            self._sent_at.pop(oldest, None)

    def was_sent(self, signal: BroadcastSignal, now: Optional[float] = None) -> bool:
        self.prune(now)
        return self.signature(signal) in self._sent_at

    def remember(self, signal: BroadcastSignal, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._sent_at[self.signature(signal)] = now
        self._last_by_ticker[signal.ticker.upper()] = signal
        self.prune(now)

    def last_for_ticker(self, ticker: str) -> BroadcastSignal | None:
        return self._last_by_ticker.get(ticker.upper())


class TelegramBroadcaster:
    def __init__(
        self,
        notifier: TelegramNotifier,
        training_pipeline,
        market_client: Optional[PolymarketClient] = None,
        tickers: Optional[Sequence[str]] = None,
        edge_threshold: float = 0.07,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        memory: Optional[BroadcastMemory] = None,
        enabled: bool = True,
        feature_store: Any = None,
    ) -> None:
        self.notifier = notifier
        self.training_pipeline = training_pipeline
        self.market_client = market_client or PolymarketClient()
        self.tickers = [ticker.strip().upper() for ticker in (tickers or []) if ticker.strip()]
        self.edge_threshold = float(edge_threshold)
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.feature_store = feature_store
        self.memory = memory or BroadcastMemory(
            ttl_seconds=int(os.getenv("TELEGRAM_BROADCAST_MEMORY_TTL_SECONDS", "3600")),
            max_entries=int(os.getenv("TELEGRAM_BROADCAST_MEMORY_MAX_ENTRIES", "256")),
            probability_bucket=float(os.getenv("TELEGRAM_BROADCAST_MEMORY_PROB_BUCKET", "0.01")),
            feature_store=feature_store,
        )
        self.enabled = enabled
        self._last_broadcast_at: dict[str, float] = {}
        self._cooldown_seconds = int(os.getenv("TELEGRAM_BROADCAST_COOLDOWN_SECONDS", "600"))
        self._formatter = TelegramMessageFormatter()

    @staticmethod
    def escape_markdown_v2(text: Any) -> str:
        return TelegramMessageFormatter.escape_markdown_v2(text)

    def _resolve_market(self, ticker: str) -> Market | None:
        direct = self.market_client.get_market(ticker)
        if direct and direct.active and not direct.closed:
            return direct

        candidates = self.market_client.search_markets(ticker, limit=10)
        candidates = [m for m in candidates if m.active and not m.closed]
        if not candidates:
            return None
        return sorted(candidates, key=lambda m: (-m.volume, -m.liquidity))[0]

    def _build_signal(self, ticker: str, market: Market, calibrated_prob: float) -> BroadcastSignal | None:
        market_prob = float(market.yes_price)
        edge = float(calibrated_prob) - market_prob
        if abs(edge) < self.edge_threshold:
            return None

        action = "BUY" if edge > 0 else "SELL"
        return BroadcastSignal(
            ticker=ticker,
            market_slug=market.slug,
            market_question=market.question,
            calibrated_probability=float(calibrated_prob),
            market_probability=market_prob,
            edge=edge,
            action=action,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _is_on_cooldown(self, ticker: str) -> bool:
        last = self._last_broadcast_at.get(ticker)
        if last is None:
            return False
        return (time.time() - last) < self._cooldown_seconds

    def _mark_broadcast(self, ticker: str) -> None:
        self._last_broadcast_at[ticker] = time.time()

    def _format_signal(self, signal: BroadcastSignal) -> str:
        edge_pct = signal.edge * 100.0
        return (
            "<b>🚨 CALIBRATED EDGE ALERT</b>\n"
            "───────────────────\n"
            f"Asset: <code>{escape(signal.ticker)}</code>\n"
            f"Action: <b>{escape(signal.action)}</b>\n"
            f"Regime: <code>QUANT_FUSION</code>\n"
            "───────────────────\n"
            "<b>Edge Metrics:</b>\n"
            f"• AI Prob: <code>{signal.calibrated_probability:.1%}</code>\n"
            f"• Market: <code>{signal.market_probability:.1%}</code>\n"
            f"• Alpha: <b>{signal.edge:+.1%}</b>\n"
            "───────────────────\n"
            "<pre>"
            f"slug: {escape(signal.market_slug)}\n"
            f"question: {escape(signal.market_question[:80])}...\n"
            f"model: {escape(signal.model_version)}\n"
            f"source: telegram_broadcaster\n"
            "</pre>\n"
            f"Edge condition met: <code>{edge_pct:+.2f}%</code> vs market price."
        )

    async def diffuser_alerte_risque_au_canal(self, alert_data: dict[str, Any], escape_body: bool = True) -> bool:
        if not self.enabled:
            return False
        if not escape_body:
            title = self._formatter._html(alert_data.get("title", "Alert"))
            body = alert_data.get("message", "")
            severity = str(alert_data.get("severity", "info")).upper()
            emoji = "⚠️" if severity == "WARNING" else "🔴" if severity == "CRITICAL" else "ℹ️"
            text = (
                f"<b>{emoji} RISK ALERT: {title}</b>\n"
                "───────────────────\n"
                f"{body}\n"
                "───────────────────"
            )
        else:
            text = self._formatter.format_risk_alert_html(alert_data)
        return await self._send(text, parse_mode="HTML")

    async def _send(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.notifier.enabled:
            logger.info("Telegram broadcaster disabled")
            return False
        await self.rate_limiter.acquire()
        return await self.notifier.send_async(text, parse_mode=parse_mode)

    async def broadcast_opportunity(self, signal: BroadcastSignal) -> bool:
        if not self.enabled:
            return False
        if self.memory.was_sent(signal):
            logger.info(
                "Skipping duplicate Telegram signal for %s: edge=%+.2f%% market=%s",
                signal.ticker,
                signal.edge * 100.0,
                signal.market_slug,
            )
            return False
        text = self._format_signal(signal)
        ok = await self._send(text)
        if ok:
            self._mark_broadcast(signal.ticker)
            self.memory.remember(signal)
            if self.feature_store is not None:
                try:
                    self.feature_store.record_signal(
                        source="telegram_broadcaster",
                        ticker=signal.ticker,
                        side=signal.action,
                        price=signal.market_probability,
                        size=0.0,
                        confidence=signal.calibrated_probability,
                        raw_text=signal.market_question,
                        regime_label="",
                        decision_json={"market_slug": signal.market_slug},
                    )
                    logger.info(f"💾 Persisted broadcasted signal to FeatureStore for {signal.ticker}")
                except Exception as e:
                    logger.error(f"Failed to persist broadcasted signal to FeatureStore: {e}")
        return ok

    async def evaluate_ticker(self, ticker: str) -> Optional[BroadcastSignal]:
        ticker = ticker.strip().upper()
        if not ticker or self._is_on_cooldown(ticker):
            return None

        feature_vector = self.training_pipeline.latest_features_as_vector(ticker)
        if feature_vector is None:
            return None

        prediction = self.training_pipeline.predict(ticker, feature_vector)
        if not prediction:
            return None

        market = self._resolve_market(ticker)
        if market is None:
            logger.debug("No active market resolved for %s", ticker)
            return None

        signal = self._build_signal(ticker, market, prediction["prob_up"])
        if signal is None:
            return None

        await self.broadcast_opportunity(signal)
        return signal

    async def scan_and_broadcast(self, tickers: Optional[Sequence[str]] = None) -> list[BroadcastSignal]:
        if not self.enabled:
            return []

        selected = [ticker.strip().upper() for ticker in (tickers or self.tickers) if ticker.strip()]
        results: list[BroadcastSignal] = []
        for ticker in selected:
            try:
                signal = await self.evaluate_ticker(ticker)
                if signal is not None:
                    results.append(signal)
            except Exception as e:
                logger.warning("Broadcast evaluation failed for %s: %s", ticker, e)
        return results


# Backward-compatible alias during migration from the old channel broadcaster naming.
TelegramChannelBroadcaster = TelegramBroadcaster
