from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from database.ledger_db import Ledger
from utils.feature_store import FeatureStore


@dataclass(frozen=True)
class HistoryWindow:
    since_ts: float = 0.0
    until_ts: Optional[float] = None
    limit: int = 1000


class HistoryAccessService:
    """
    Single read boundary for bot history.

    The service intentionally aggregates the existing persistence layers rather
    than introducing a new database. It makes the data access contract explicit:
    feature history, trade history, and live event history all pass through one
    place.
    """

    def __init__(self, feature_store: FeatureStore, ledger: Optional[Ledger] = None) -> None:
        self.feature_store = feature_store
        self.ledger = ledger

    def get_feature_history(
        self,
        ticker: str,
        feature_name: str,
        window: HistoryWindow | None = None,
    ) -> list[dict[str, Any]]:
        w = window or HistoryWindow()
        return self.feature_store.get_feature_history(
            ticker,
            feature_name,
            since_ts=w.since_ts,
            limit=w.limit,
            until_ts=w.until_ts,
        )

    def get_multi_market_feature_frame(
        self,
        target_ticker: str,
        base_feature_names: list[str],
        binance_symbol: Optional[str] = None,
        window: HistoryWindow | None = None,
        window_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        w = window or HistoryWindow()
        return self.feature_store.get_multi_market_feature_frame(
            target_ticker=target_ticker,
            base_feature_names=base_feature_names,
            binance_symbol=binance_symbol,
            since_ts=w.since_ts,
            limit=w.limit,
            window_seconds=window_seconds,
        )

    def get_web_events(
        self,
        event_type: Optional[str] = None,
        window: HistoryWindow | None = None,
    ) -> list[dict[str, Any]]:
        w = window or HistoryWindow()
        return self.feature_store.get_web_events(
            since_ts=w.since_ts,
            limit=w.limit,
            event_type=event_type,
        )

    def get_open_positions(self) -> list[dict[str, Any]]:
        if not self.ledger:
            return []
        return self.ledger.get_open_positions()

    def get_paper_positions(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        if not self.ledger:
            return []
        return self.ledger.get_paper_positions(status=status)

    def get_historical_performance(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self.ledger:
            return []
        return self.ledger.get_historical_performance(limit=limit)

    def get_performance_summary(self, mode: Optional[str] = None) -> dict[str, Any]:
        if not self.ledger:
            return {}
        if mode is None:
            return self.ledger.get_performance_summary()
        return self.ledger.get_performance_summary(mode=mode)
