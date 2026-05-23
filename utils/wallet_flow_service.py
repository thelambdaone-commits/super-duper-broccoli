from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from utils.polymarket_crawler.traders import LeaderboardTrader, TraderScraper

logger = logging.getLogger("WalletFlowService")
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "wallet_flow_scores.json"


@dataclass
class WalletMarketFlow:
    market_slug: str
    score: float
    trade_count: int
    wallet_count: int
    last_updated: float


class WalletFlowService:
    """
    Build lightweight market-level signals from historically profitable wallets.

    The intent is not to copy one wallet blindly, but to compress public historical
    wallet activity into a reusable feature for strategy generation.
    """

    def __init__(
        self,
        scraper: TraderScraper | None = None,
        *,
        cache_path: str | os.PathLike[str] = DEFAULT_CACHE_PATH,
        refresh_ttl_seconds: float = 1800.0,
        leaderboard_limit: int = 15,
        trade_limit: int = 80,
        category: str = "OVERALL",
    ) -> None:
        self.scraper = scraper or TraderScraper()
        self.cache_path = Path(cache_path)
        self.refresh_ttl_seconds = float(refresh_ttl_seconds)
        self.leaderboard_limit = int(leaderboard_limit)
        self.trade_limit = int(trade_limit)
        self.category = category
        self._scores: dict[str, WalletMarketFlow] = {}
        self._last_refresh = 0.0
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if not self.cache_path.exists():
                return
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._last_refresh = float(payload.get("last_refresh", 0.0) or 0.0)
            entries = payload.get("scores", {})
            loaded: dict[str, WalletMarketFlow] = {}
            for market_slug, item in entries.items():
                loaded[market_slug] = WalletMarketFlow(
                    market_slug=market_slug,
                    score=float(item.get("score", 0.0) or 0.0),
                    trade_count=int(item.get("trade_count", 0) or 0),
                    wallet_count=int(item.get("wallet_count", 0) or 0),
                    last_updated=float(item.get("last_updated", self._last_refresh) or self._last_refresh),
                )
            self._scores = loaded
        except Exception as exc:
            logger.warning("Failed to load wallet flow cache: %s", exc)

    def _persist_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "last_refresh": self._last_refresh,
                "scores": {slug: asdict(flow) for slug, flow in self._scores.items()},
            }
            self.cache_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to persist wallet flow cache: %s", exc)

    def needs_refresh(self) -> bool:
        return (time.time() - self._last_refresh) >= self.refresh_ttl_seconds

    def get_market_score(self, market_slug: str) -> float:
        flow = self._scores.get((market_slug or "").lower())
        return flow.score if flow else 0.0

    def get_all_scores(self) -> dict[str, WalletMarketFlow]:
        return dict(self._scores)

    def refresh_scores(self, force: bool = False) -> dict[str, WalletMarketFlow]:
        if not force and not self.needs_refresh():
            return self.get_all_scores()

        traders = self.scraper.fetch_leaderboard(
            category=self.category,
            time_period="ALL",
            order_by="PNL",
            limit=self.leaderboard_limit,
        )
        if not traders:
            logger.warning("Wallet flow refresh found no leaderboard traders")
            return self.get_all_scores()

        aggregated: dict[str, dict[str, float]] = {}
        wallet_presence: dict[str, set[str]] = {}
        for trader in traders:
            wallet_weight = self._wallet_weight(trader)
            if wallet_weight <= 0:
                continue
            try:
                trades = self.scraper.fetch_trades(trader.proxy_wallet, limit=self.trade_limit)
                positions = self.scraper.fetch_closed_positions(trader.proxy_wallet, limit=self.trade_limit)
            except Exception as exc:
                logger.warning("Wallet flow fetch failed for %s: %s", trader.proxy_wallet, exc)
                continue

            realized_map = {
                (position.market_slug or "").lower(): float(position.realized_pnl or 0.0)
                for position in positions
                if position.market_slug
            }
            for trade in trades:
                market_slug = (trade.market_slug or "").lower()
                if not market_slug:
                    continue
                side_sign = 1.0 if str(trade.side).upper() == "BUY" else -1.0
                trade_size = max(1.0, float(trade.size or 0.0))
                realized_pnl = realized_map.get(market_slug, 0.0)
                pnl_boost = 1.0 + max(-0.5, min(1.5, realized_pnl / 1000.0))
                contribution = side_sign * wallet_weight * math.log1p(trade_size) * pnl_boost

                bucket = aggregated.setdefault(market_slug, {"score_sum": 0.0, "trade_count": 0.0})
                bucket["score_sum"] += contribution
                bucket["trade_count"] += 1.0
                wallet_presence.setdefault(market_slug, set()).add(trader.proxy_wallet.lower())

        now = time.time()
        normalized: dict[str, WalletMarketFlow] = {}
        for market_slug, bucket in aggregated.items():
            trade_count = int(bucket["trade_count"])
            wallet_count = len(wallet_presence.get(market_slug, set()))
            if trade_count <= 0 or wallet_count <= 0:
                continue
            raw_score = bucket["score_sum"] / max(1.0, math.sqrt(trade_count))
            clipped = max(-1.0, min(1.0, raw_score / 8.0))
            normalized[market_slug] = WalletMarketFlow(
                market_slug=market_slug,
                score=clipped,
                trade_count=trade_count,
                wallet_count=wallet_count,
                last_updated=now,
            )

        self._scores = normalized
        self._last_refresh = now
        self._persist_cache()
        logger.info("Wallet flow refresh completed: %s scored markets", len(normalized))
        return self.get_all_scores()

    @staticmethod
    def _wallet_weight(trader: LeaderboardTrader) -> float:
        pnl = max(0.0, float(trader.pnl or 0.0))
        volume = max(0.0, float(trader.volume or 0.0))
        if pnl <= 0 and volume <= 0:
            return 0.0
        rank_factor = 1.0 / max(1.0, float(trader.rank or 1))
        pnl_factor = math.log1p(pnl / 100.0)
        volume_factor = 0.25 * math.log1p(volume / 1000.0)
        return rank_factor * (1.0 + pnl_factor + volume_factor)
