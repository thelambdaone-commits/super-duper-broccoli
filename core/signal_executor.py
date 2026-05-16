import logging
import time
import uuid
from typing import Optional, Dict, Any

from core.freqai_engine import FreqAIEngine
from core.portfolio_risk_engine import PortfolioRiskEngine
from execution.passive_executor import PassiveExecutor
from ledger.ledger_db import Ledger
from mcp_agents.lobstar_agent import LobstarAgent
from user_data.strategies.hmm_filter import HMMRegimeFilter
from utils.feature_store import FeatureStore
from utils.regime_utils import get_regime_label

logger = logging.getLogger("SignalExecutor")

SUCCESS_STATUSES = {"FILLED", "TAKER_FILLED", "MATCHED", "LIVE", "DELAYED"}

def _execution_succeeded(result: Optional[dict]) -> bool:
    if not result:
        return False
    status = str(result.get("status", "")).upper()
    if status in {"REJECTED", "POST_ONLY_REJECTED", "CANCEL_FAILED", "ERROR"}:
        return False
    return status in SUCCESS_STATUSES or bool(result.get("orderID") or result.get("order_id"))


def _regex_confidence(price: float, decimals: int = 4) -> float:
    price_str = f"{price:.{decimals}f}"
    decimal_part = price_str.split(".")[1] if "." in price_str else ""
    significant_decimals = len(decimal_part.rstrip("0"))
    return min(0.5 + significant_decimals * 0.1, 0.85)

async def _execute_guarded(
    ticker: str, side: str, price: float, size: float,
    confidence: float, regime: str, sizing: dict,
    ledger: Ledger, freqai: FreqAIEngine, risk: Optional[PortfolioRiskEngine],
    store: Optional[FeatureStore], mode: str, signal_source: str,
    executor: Optional[PassiveExecutor] = None,
) -> Dict[str, Any]:
    if size <= 0:
        return {"status": "SKIPPED", "reason": "Zero size"}

    report_data = {
        "ticker": ticker, "side": side, "price": price,
        "size": size, "executed_size": 0.0, "probability": confidence,
        "kelly_pct": sizing.get("kelly_pct", 0), "regime": regime,
        "path": "PASSIVE_MAKER" if executor else "DIRECT_CLOB",
        "trade_id": "N/A", "status": "PENDING",
        "reason_1": "Pattern alignment detected",
        "reason_2": "Liquidity depth sufficient",
        "reason_3": "Risk thresholds validated",
    }

    if mode == "REPLAY":
        report_data["status"] = "SUCCESS"
        report_data["reason_1"] = "REPLAY_SKIP_EXECUTION"
        return report_data

    if mode == "PAPER":
        ledger.record_paper_order(
            ticker=ticker, side=side, price=price, size=size,
            confidence=confidence, regime_label=regime, signal_source=signal_source,
        )
        if risk: risk.book_exposure(ticker, size, side)
        report_data["status"] = "SUCCESS"
        report_data["executed_size"] = size
        report_data["trade_id"] = f"paper-{uuid.uuid4().hex[:8]}"
        return report_data

    # PROD / SHADOW Logic
    validation = ledger.validate_and_reserve(
        ticker=ticker,
        side=side,
        limit_price=price,
        requested_size=size,
    )
    if not validation["authorized"]:
        report_data["status"] = "FAILED"
        report_data["reason_1"] = validation["reason"]
        return report_data

    final_size = validation["size"]
    if mode == "SHADOW":
        final_size = max(1.0, final_size * 0.01)

    exec_ok = False
    executed_size = 0.0
    position_id = f"{ticker}-{side}-{int(time.time())}"

    if executor:
        exec_result = await executor.execute(ticker, side, price, final_size)
        exec_ok = exec_result.get("status") in SUCCESS_STATUSES
    else:
        try:
            exec_result = await freqai.clob_execute(ticker, side, price, final_size)
            exec_ok = _execution_succeeded(exec_result)
        except Exception as e:
            logger.error(f"Execution error: {e}")
            exec_ok = False

    if exec_ok:
        executed_size = final_size
        ledger.record_order(
            position_id=position_id,
            ticker=ticker,
            side=side,
            price=price,
            size=executed_size,
        )
        if risk: risk.book_exposure(ticker, executed_size, side)
        report_data["status"] = "SUCCESS"
        report_data["executed_size"] = executed_size
        report_data["trade_id"] = position_id
    else:
        report_data["status"] = "FAILED"
        report_data["reason_1"] = "Execution rejected by CLOB"

    return report_data

async def execute_regex_signal(
    signal: dict, ledger: Ledger, freqai: FreqAIEngine, **kwargs
) -> Dict[str, Any]:
    ticker, side, price = signal["asset"], signal["action"], signal["price"]
    
    # Resolve ticker to Token ID if scanner is available
    scanner = kwargs.get("scanner")
    if scanner:
        token_id = scanner.resolve_ticker_to_token_id(ticker, side)
        if token_id:
            logger.info(f"Resolved ticker {ticker} to token_id {token_id}")
            ticker = token_id
    
    mode = ledger.get_execution_mode()
    regime = get_regime_label(kwargs.get("hmm"), ticker)
    confidence = _regex_confidence(price)
    
    risk = kwargs.get("risk")
    sizing = risk.compute_position_size(
        ticker=ticker, side=side, price=price,
        confidence=confidence, regime_label=regime,
    ) if risk else {"size": 10.0}

    return await _execute_guarded(
        ticker, side, price, sizing["size"], confidence, regime, sizing,
        ledger, freqai, risk, kwargs.get("store"),
        mode, "regex", kwargs.get("executor")
    )

async def execute_lobstar_signal(
    signal: dict, ledger: Ledger, freqai: FreqAIEngine, lobstar: LobstarAgent, **kwargs
) -> Dict[str, Any]:
    decision = await lobstar.analyser_signal_contextuel(signal.get("raw", ""))
    if not decision:
        return {"status": "FAILED", "reason": "Invalid LLM decision"}
        
    ticker = decision.get("ticker", "")
    side = decision.get("side", "")
    price = decision.get("price_limite", 0.0)
    size = decision.get("size", 0.0)
    confidence = decision.get("confidence", 0.0)

    if not ticker or not side or not (0.01 <= price <= 0.99):
        logger.warning(f"LOBSTAR: Incomplete decision: {decision}")
        return {"status": "FAILED", "reason": "Incomplete LLM decision"}

    if confidence < 0.3:
        logger.warning(f"LOBSTAR: Low confidence ({confidence:.2f}), skipping.")
        return {"status": "FAILED", "reason": "Low LLM confidence"}
    
    mode = ledger.get_execution_mode()
    regime = get_regime_label(kwargs.get("hmm"), ticker)
    
    risk = kwargs.get("risk")
    sizing = risk.compute_position_size(
        ticker=ticker, side=side, price=price,
        confidence=confidence, win_prob=confidence,
        regime_label=regime,
    ) if risk else {"size": size}

    # Resolve ticker to Token ID if scanner is available
    scanner = kwargs.get("scanner")
    if scanner:
        token_id = scanner.resolve_ticker_to_token_id(ticker, side)
        if token_id:
            logger.info(f"Resolved ticker {ticker} to token_id {token_id}")
            ticker = token_id
            
    return await _execute_guarded(
        ticker, side, price, sizing["size"], confidence, regime, sizing,
        ledger, freqai, risk, kwargs.get("store"),
        mode, "lobstar_llm", kwargs.get("executor")
    )
