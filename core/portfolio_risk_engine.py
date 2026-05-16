import logging
from typing import Optional

from user_data.strategies.hmm_filter import HMMRegimeFilter
from config.constants import REGIME_SIZING_MULTIPLIER as _REGIME_SIZING_MULTIPLIER
from ledger.ledger_db import Ledger

# Re-export for backward compatibility with tests
REGIME_SIZING_MULTIPLIER = _REGIME_SIZING_MULTIPLIER

logger = logging.getLogger("PortfolioRiskEngine")


class PortfolioRiskEngine:
    def __init__(
        self,
        ledger: Ledger,
        hmm_filter: Optional[HMMRegimeFilter] = None,
        max_trailing_drawdown_pct: float = 0.20,
    ) -> None:
        self.ledger = ledger
        self.hmm = hmm_filter
        self.kelly_fraction: float = 0.25
        self.max_correlated_drawdown_pct: float = 0.15
        self.max_concentration_pct: float = 0.30
        self.target_portfolio_vol: float = 0.15
        self.max_trailing_drawdown_pct: float = max_trailing_drawdown_pct
        self._exposures: dict[str, float] = {}
        self._peak_equity: float = 0.0
        self._beta_to_btc: dict[str, float] = {
            "BTC": 1.0, "SOL": 0.8, "ETH": 0.85,
            "POLY": 0.6, "LINK": 0.7, "ARB": 0.75,
            "OP": 0.7, "USDC": 0.0,
        }
        self._is_drawdown_tripped: bool = False

    @property
    def net_beta_exposure_pct(self) -> float:
        total = sum(
            size * self._beta_to_btc.get(t.split("-")[0] if "-" in t else t, 0.5)
            for t, size in self._exposures.items()
        )
        cap = self.ledger.get_capital_summary().get("total_capital", 10_000.0)
        return (total / cap * 100) if cap > 0 else 0.0

    def _kelly_size(self, win_prob: float, win_loss_ratio: float, capital: float) -> float:
        if win_loss_ratio <= 0:
            return 0.0
        q = 1.0 - win_prob
        kelly = (win_prob * win_loss_ratio - q) / win_loss_ratio
        kelly = max(0.0, min(kelly, self.kelly_fraction))
        return capital * kelly

    def _vol_target_size(self, capital: float, asset_vol: float) -> float:
        if asset_vol <= 0:
            return capital * 0.01
        return min(capital * self.target_portfolio_vol / asset_vol, capital * 0.1)

    def _regime_multiplier(self, regime_label: str, confidence: float) -> float:
        base = _REGIME_SIZING_MULTIPLIER.get(regime_label, 0.5)
        return base * confidence

    def _check_concentration(self, ticker: str, add_size: float, capital: float) -> bool:
        current = self._exposures.get(ticker, 0.0)
        return (current + add_size) / capital <= self.max_concentration_pct

    def _check_correlated_drawdown(self, add_size: float, beta: float, capital: float) -> bool:
        current_net = self.net_beta_exposure_pct / 100.0 * capital
        new_net = current_net + add_size * beta
        max_allowed = self.max_correlated_drawdown_pct * capital
        return new_net <= max_allowed

    def compute_position_size(
        self,
        ticker: str,
        side: str,
        price: float,
        confidence: float = 0.5,
        win_prob: float = 0.55,
        win_loss_ratio: float = 1.5,
        asset_volatility: float = 0.5,
        regime_label: str = "LOW_VOLATILITY",
    ) -> dict:
        cap = self.ledger.get_capital_summary()
        total = cap.get("total_capital", 10_000.0)
        available = cap.get("available_capital", total)

        if total <= 0:
            return {
                "size": 0.0, "capital_at_risk": 0.0,
                "kelly_pct": 0.0, "vol_target_pct": 0.0,
                "regime_multiplier": 0.0, "net_beta_exposure_pct": self.net_beta_exposure_pct,
            }

        base_kelly = self._kelly_size(win_prob, win_loss_ratio, total)
        base_vol = self._vol_target_size(total, asset_volatility)
        base = min(base_kelly, base_vol)

        regime_sized = self._regime_multiplier(regime_label, confidence) * base
        max_by_avail = available / price if price > 0 else available
        raw = min(regime_sized, max_by_avail)

        ticker_base = ticker.split("-")[0] if "-" in ticker else ticker
        beta = self._beta_to_btc.get(ticker_base, 0.5)

        if not self._check_concentration(ticker, raw, total):
            raw = self.max_concentration_pct * total - self._exposures.get(ticker, 0.0)

        if not self._check_correlated_drawdown(raw, beta, total):
            current_net = self.net_beta_exposure_pct / 100.0 * total
            raw = (self.max_correlated_drawdown_pct * total - current_net) / beta

        final_size = max(0.0, raw)

        return {
            "size": final_size,
            "capital_at_risk": final_size * price,
            "kelly_pct": base_kelly / total * 100 if total > 0 else 0.0,
            "vol_target_pct": base_vol / total * 100 if total > 0 else 0.0,
            "regime_multiplier": (regime_sized / (base + 1e-12)) if base > 0 else 0.0,
            "net_beta_exposure_pct": self.net_beta_exposure_pct,
        }

    def rehydrate_from_ledger(self, ledger: Ledger) -> None:
        positions = ledger.get_open_positions()
        for pos in positions:
            ticker = pos.get("ticker", "")
            size = pos.get("size", 0.0)
            side = pos.get("side", "BUY")
            signed = size if side in ("BUY", "YES", "LONG") else -size
            self._exposures[ticker] = self._exposures.get(ticker, 0.0) + signed
        logger.info(
            f"Rehydrated {len(positions)} positions into exposures: "
            f"{dict(self._exposures)}"
        )

    def book_exposure(self, ticker: str, size: float, side: str) -> None:
        signed = size if side in ("BUY", "YES", "LONG") else -size
        self._exposures[ticker] = self._exposures.get(ticker, 0.0) + signed
        logger.info(
            f"Exposure updated: {ticker} -> {self._exposures[ticker]:.2f} "
            f"(net beta exposure: {self.net_beta_exposure_pct:.1f}%)"
        )
