from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from utils.wallet_flow_service import WalletFlowService


@dataclass
class _Trader:
    rank: int
    proxy_wallet: str
    user_name: str = "wallet"
    x_username: str = ""
    verified_badge: bool = False
    volume: float = 50_000.0
    pnl: float = 5_000.0
    profile_image: str = ""
    category: str = "OVERALL"


@dataclass
class _Trade:
    market_slug: str
    side: str
    price: float
    size: float
    timestamp: str = "2026-01-01T00:00:00Z"
    maker: str = "0xwallet"
    outcome: str = "YES"


@dataclass
class _ClosedPosition:
    market_slug: str
    title: str = "market"
    side: str = "BUY"
    size: float = 100.0
    avg_price: float = 0.5
    realized_pnl: float = 250.0
    outcome: str = "YES"


class _StubScraper:
    def fetch_leaderboard(self, **_kwargs):
        return [_Trader(rank=1, proxy_wallet="0xabc")]

    def fetch_trades(self, proxy_wallet: str, limit: int = 80):
        assert proxy_wallet == "0xabc"
        return [
            _Trade(market_slug="btc-above-100k", side="BUY", price=0.45, size=400.0),
            _Trade(market_slug="btc-above-100k", side="BUY", price=0.48, size=200.0),
            _Trade(market_slug="eth-below-2k", side="SELL", price=0.40, size=100.0),
        ][:limit]

    def fetch_closed_positions(self, proxy_wallet: str, limit: int = 80):
        assert proxy_wallet == "0xabc"
        return [
            _ClosedPosition(market_slug="btc-above-100k", realized_pnl=500.0),
            _ClosedPosition(market_slug="eth-below-2k", realized_pnl=100.0),
        ][:limit]


def test_wallet_flow_service_scores_markets_and_persists(tmp_path: Path) -> None:
    service = WalletFlowService(
        scraper=_StubScraper(),
        cache_path=tmp_path / "wallet_flow_scores.json",
        refresh_ttl_seconds=0.0,
        leaderboard_limit=5,
        trade_limit=10,
    )

    scores = service.refresh_scores(force=True)

    assert "btc-above-100k" in scores
    assert scores["btc-above-100k"].score > 0
    assert scores["eth-below-2k"].score < 0
    assert (tmp_path / "wallet_flow_scores.json").exists()
