import logging
from typing import Optional

from user_data.strategies.hmm_filter import HMMRegimeFilter
from config.constants import REGIME_SIZING_MULTIPLIER as _REGIME_SIZING_MULTIPLIER
from ledger.ledger_db import Ledger

# Re-export for backward compatibility with tests
REGIME_SIZING_MULTIPLIER = _REGIME_SIZING_MULTIPLIER

logger = logging.getLogger("PortfolioRiskEngine")


BLOCKED_REGIMES = {"ERRATIC_VOLATILITY"}


class PortfolioRiskEngine:
    def __init__(
        self,
        ledger: Optional[Ledger] = None,
        hmm_filter: Optional[HMMRegimeFilter] = None,
        max_exposure_pct: Optional[float] = None,
        max_drawdown_pct: Optional[float] = None,
        max_single_position_pct: float = 0.05,
        max_trailing_drawdown_pct: float = 0.20,
    ) -> None:
        self.ledger = ledger or _NullLedger()
        self.hmm = hmm_filter
        self.kelly_fraction: float = 0.25
        self.max_single_position_pct: float = max(0.0, min(float(max_single_position_pct), 1.0))
        self.max_correlated_drawdown_pct: float = (
            max(0.0, min(float(max_exposure_pct), 1.0))
            if max_exposure_pct is not None else 0.15
        )
        self.max_concentration_pct: float = 0.30
        self.target_portfolio_vol: float = 0.15
        self.max_trailing_drawdown_pct: float = (
            max(0.0, min(float(max_drawdown_pct), 1.0))
            if max_drawdown_pct is not None else max_trailing_drawdown_pct
        )
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
        win_prob = max(0.0, min(float(win_prob), 1.0))
        win_loss_ratio = float(win_loss_ratio)
        capital = max(0.0, float(capital))
        if win_loss_ratio <= 0 or capital <= 0:
            return 0.0
        q = 1.0 - win_prob
        kelly = (win_prob * win_loss_ratio - q) / win_loss_ratio
        kelly = max(0.0, min(kelly, self.kelly_fraction))
        return capital * kelly

    def _vol_target_size(self, capital: float, asset_vol: float) -> float:
        capital = max(0.0, float(capital))
        if asset_vol <= 0:
            return capital * 0.01
        return min(capital * self.target_portfolio_vol / asset_vol, capital * 0.1)

    def _regime_multiplier(self, regime_label: str, confidence: float) -> float:
        confidence = max(0.0, min(float(confidence), 1.0))
        if regime_label in BLOCKED_REGIMES:
            return 0.0
        base = _REGIME_SIZING_MULTIPLIER.get(regime_label, 0.5)
        return base * confidence

    def _zero_size_result(self, reason: str = "") -> dict:
        return {
            "size": 0.0,
            "capital_at_risk": 0.0,
            "kelly_pct": 0.0,
            "vol_target_pct": 0.0,
            "regime_multiplier": 0.0,
            "net_beta_exposure_pct": self.net_beta_exposure_pct,
            "reason": reason,
        }

    def _check_concentration(self, ticker: str, add_size: float, capital: float) -> bool:
        current = self._exposures.get(ticker, 0.0)
        return (current + add_size) / capital <= self.max_concentration_pct

    def _check_correlated_drawdown(self, add_size: float, beta: float, capital: float) -> bool:
        current_net = self.net_beta_exposure_pct / 100.0 * capital
        new_net = current_net + add_size * beta
        max_allowed = self.max_correlated_drawdown_pct * capital
        return new_net <= max_allowed

    def _update_drawdown_tracking(self, current_capital: float) -> Optional[str]:
        if current_capital > self._peak_equity:
            self._peak_equity = current_capital
            
        if hasattr(self.ledger, "get_global_drawdown"):
            global_drawdown = self.ledger.get_global_drawdown()
            if global_drawdown <= -0.10:
                self._is_drawdown_tripped = True
                try:
                    from mcp_agents.mcp_server import emergency_circuit_breaker
                    emergency_circuit_breaker("ENGAGE")
                    logger.critical(f"GLOBAL DRAWDOWN TRIPPED ({global_drawdown*100:.2f}%%). EMERGENCY CIRCUIT BREAKER ENGAGED.")
                except Exception as e:
                    logger.error(f"Failed to engage emergency circuit breaker: {e}")
                return f"GLOBAL_DRAWDOWN_TRIPPED:{global_drawdown*100:.1f}%"
                
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - current_capital) / self._peak_equity
            if drawdown >= self.max_trailing_drawdown_pct:
                self._is_drawdown_tripped = True
                return f"DRAWDOWN_TRIPPED:{drawdown*100:.1f}%"
            if drawdown > 0:
                self._is_drawdown_tripped = False
        return None

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
            return self._zero_size_result("NO_CAPITAL")

        dd_reason = self._update_drawdown_tracking(total)
        if dd_reason is not None:
            return self._zero_size_result(dd_reason)

        if price <= 0:
            return self._zero_size_result("INVALID_PRICE")

        if regime_label in BLOCKED_REGIMES:
            return self._zero_size_result(f"HMM_BLOCKED:{regime_label}")

        base_kelly = self._kelly_size(win_prob, win_loss_ratio, total)
        base_vol = self._vol_target_size(total, asset_volatility)
        single_position_cap = total * self.max_single_position_pct
        base_notional = min(base_kelly, base_vol, single_position_cap)

        regime_multiplier = self._regime_multiplier(regime_label, confidence)
        sized_notional = min(regime_multiplier * base_notional, max(0.0, available))

        ticker_base = ticker.split("-")[0] if "-" in ticker else ticker
        beta = self._beta_to_btc.get(ticker_base, 0.5)

        if not self._check_concentration(ticker, sized_notional, total):
            sized_notional = self.max_concentration_pct * total - self._exposures.get(ticker, 0.0)

        if not self._check_correlated_drawdown(sized_notional, beta, total):
            current_net = self.net_beta_exposure_pct / 100.0 * total
            sized_notional = (
                self.max_correlated_drawdown_pct * total - current_net
                if beta <= 0 else (self.max_correlated_drawdown_pct * total - current_net) / beta
            )

        final_notional = max(0.0, min(sized_notional, max(0.0, available)))
        final_size = final_notional / price

        return {
            "size": final_size,
            "capital_at_risk": final_notional,
            "kelly_pct": base_kelly / total * 100 if total > 0 else 0.0,
            "vol_target_pct": base_vol / total * 100 if total > 0 else 0.0,
            "regime_multiplier": regime_multiplier,
            "net_beta_exposure_pct": self.net_beta_exposure_pct,
            "single_position_cap_pct": self.max_single_position_pct * 100.0,
            "reason": "OK" if final_size > 0 else "RISK_CAP_ZERO",
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


    async def validate_signal_risk(
        self,
        signal: dict,
        current_portfolio_value: float = 0.0,
        active_positions: dict[str, float] | None = None,
    ) -> tuple[bool, str]:
        active_positions = active_positions or {}
        cap = current_portfolio_value or 10_000.0

        dd_reason = self._update_drawdown_tracking(cap)
        if dd_reason is not None:
            return False, dd_reason

        ticker = str(signal.get("ticker", signal.get("token_id", ""))).upper()
        side = str(signal.get("side", "BUY"))
        price = float(signal.get("price", 0.0) or 0.0)
        confidence = float(signal.get("confidence", 0.5))

        regime_label = str(signal.get("regime_label", "LOW_VOLATILITY"))
        if regime_label in BLOCKED_REGIMES:
            return False, f"HMM_BLOCKED:{regime_label}"

        if price <= 0:
            return False, "INVALID_PRICE"

        # Estimate potential size with current compute_position_size
        sizing = self.compute_position_size(
            ticker=ticker, side=side, price=price,
            confidence=confidence,
            regime_label=regime_label,
        )
        if sizing.get("size", 0.0) <= 0:
            return False, sizing.get("reason", "RISK_CAP_ZERO")

        # Concentration check inclusive of existing positions
        existing = active_positions.get(ticker, 0.0)
        if existing > 0 and not self._check_concentration(ticker, sizing["capital_at_risk"], cap):
            return False, "CONCENTRATION_LIMIT"

        return True, "OK"


class _NullLedger:
    def get_capital_summary(self) -> dict:
        return {"total_capital": 10_000.0, "available_capital": 10_000.0}
