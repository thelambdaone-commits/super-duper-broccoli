from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LeaderboardEntry:
    rank: int
    proxy_wallet: str
    name: str
    pseudonym: str
    amount: float
    pnl: float
    volume: float
    realized: float
    unrealized: float


@dataclass
class BiggestWin:
    win_rank: int
    proxy_wallet: str
    user_name: str
    event_slug: str
    event_title: str
    initial_value: float
    final_value: float
    pnl: float
    theme: str = "general"


@dataclass
class Trade:
    market: str
    side: str
    size: float
    price: float
    pnl: float
    timestamp: str
    hold_time_minutes: Optional[float] = None
    theme: str = "general"
    strategy: Optional[str] = None
    outcome_label: str = ""


@dataclass
class WalletProfile:
    wallet: str
    name: str
    rank: int
    pnl: float
    volume: float
    themes: dict = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    biggest_wins: list[BiggestWin] = field(default_factory=list)


@dataclass
class StrategyPattern:
    name: str
    theme: str
    conviction: float
    win_rate: float
    avg_roi: float
    total_trades: int
    avg_size: float
    avg_hold_minutes: Optional[float]
    conditions: dict
    rule: str
    low_confidence: bool = False


@dataclass
class ScoredWallet:
    wallet: str
    name: str
    overall_score: float
    patterns: list[StrategyPattern]
    total_pnl: float
    total_volume: float
    total_trades: int
    top_theme: str


@dataclass
class Decision:
    wallet: str
    name: str
    theme: str
    strategy: str
    conviction: float
    allocation_usdc: float
    rule: str
    conditions: dict
