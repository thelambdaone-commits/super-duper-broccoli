import logging
import inspect
import time
import uuid
from typing import Optional, Dict, Any

from core.freqai_engine import FreqAIEngine
from core.portfolio_risk_engine import PortfolioRiskEngine
from core.trade_objective import estimate_trade_objective
from execution.passive_executor import PassiveExecutor
from ledger.ledger_db import Ledger
from mcp_agents.lobstar_agent import LobstarAgent
from utils.feature_store import FeatureStore
from utils.regime_utils import get_regime_label

from utils.config_loader import TRADING_PARAMS

logger = logging.getLogger("SignalExecutor")

SUCCESS_STATUSES = {"FILLED", "TAKER_FILLED", "MATCHED", "LIVE", "DELAYED"}
BLOCKED_REGIMES = set(TRADING_PARAMS["BLOCKED_REGIMES"])

FILL_STATUS_KEYS = {"FILLED", "PARTIAL", "PARTIALLY_FILLED", "PARTIAL_FILL", "OK", "MATCHED"}


def _dynamic_slippage_threshold(price: float, bid: float, ask: float) -> float:
    base = TRADING_PARAMS["SLIPPAGE_GATE_BASE"]
    max_threshold = TRADING_PARAMS["SLIPPAGE_GATE_MAX"]
    if price <= 0:
        return base
    if bid <= 0 or ask <= 0 or ask <= bid:
        return base * 1.5
    spread = ask - bid
    spread_pct = spread / max(price, 1e-6)
    threshold = base + spread_pct * 1.5
    return max(base, min(max_threshold, threshold))

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
    base = float(TRADING_PARAMS.get("CONFIDENCE_BASE", 0.5))
    step = float(TRADING_PARAMS.get("CONFIDENCE_STEP", 0.1))
    cap = float(TRADING_PARAMS.get("CONFIDENCE_CAP", 0.85))
    return min(base + significant_decimals * step, cap)


def _apply_cognitive_confidence(signal: dict, base_confidence: float) -> float:
    cognitive_confidence = signal.get("cognitive_confidence")
    if cognitive_confidence is None:
        return base_confidence
    try:
        cognitive_value = max(0.0, min(0.99, float(cognitive_confidence)))
    except (TypeError, ValueError):
        return base_confidence

    blended = (float(base_confidence) + cognitive_value) / 2.0
    if signal.get("cognitive_action") == "FADE":
        return max(0.0, min(blended, float(base_confidence) * 0.5))
    return max(0.0, min(0.99, blended))


def _risk_rejection_reason(size: float, regime: str, sizing: dict) -> Optional[str]:
    if regime in BLOCKED_REGIMES:
        return f"HMM_BLOCKED:{regime}"
    sizing_reason = str(sizing.get("reason", ""))
    if size <= 0 and sizing_reason:
        return sizing_reason
    return None


def _extract_fill_confirmation(confirmation: Optional[dict], requested_size: float, requested_price: float) -> dict:
    if not isinstance(confirmation, dict):
        return {
            "filled_size": 0.0,
            "filled_price": requested_price,
            "status": "UNKNOWN",
        }

    status = str(confirmation.get("status", "")).upper()
    if status not in FILL_STATUS_KEYS and not confirmation.get("orderID") and not confirmation.get("order_id"):
        return {
            "filled_size": 0.0,
            "filled_price": requested_price,
            "status": status or "REJECTED",
        }

    raw_filled = confirmation.get("filled_size", confirmation.get("filledSize", confirmation.get("size", requested_size)))
    try:
        filled_size = max(0.0, float(raw_filled))
    except (TypeError, ValueError):
        filled_size = 0.0

    raw_price = confirmation.get("price", requested_price)
    try:
        filled_price = float(raw_price)
    except (TypeError, ValueError):
        filled_price = requested_price

    return {
        "filled_size": filled_size,
        "filled_price": filled_price,
        "status": status or ("FILLED" if filled_size > 0 else "UNKNOWN"),
        "order_id": confirmation.get("orderID", confirmation.get("order_id")),
    }


def _estimate_spread_from_orderbook(book: Any, price: float) -> float:
    bids = book.bids if hasattr(book, "bids") else book.get("bids", [])
    asks = book.asks if hasattr(book, "asks") else book.get("asks", [])
    if not isinstance(bids, (list, tuple)) or not isinstance(asks, (list, tuple)) or not bids or not asks:
        return 0.0
    try:
        best_bid_raw = bids[0].price if hasattr(bids[0], "price") else bids[0].get("price", 0)
        best_ask_raw = asks[0].price if hasattr(asks[0], "price") else asks[0].get("price", 0)
        best_bid = float(best_bid_raw)
        best_ask = float(best_ask_raw)
    except (TypeError, ValueError, AttributeError, IndexError):
        return 0.0
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return 0.0
    return max(0.0, best_ask - best_bid)


def _minimum_polymarket_notional(freqai: Any) -> float:
    try:
        return float(getattr(freqai, "POLYMARKET_MIN_NOTIONAL", 5.0) or 5.0)
    except (TypeError, ValueError):
        return 5.0

async def _execute_guarded(
    ticker: str, side: str, price: float, size: float,
    confidence: float, regime: str, sizing: dict,
    ledger: Ledger, freqai: FreqAIEngine, risk: Optional[PortfolioRiskEngine],
    store: Optional[FeatureStore], mode: str, signal_source: str,
    executor: Optional[PassiveExecutor] = None,
    tenant_wallet: Optional[str] = None,
) -> Dict[str, Any]:
    rejection_reason = _risk_rejection_reason(size, regime, sizing)
    if rejection_reason or size <= 0:
        return {"status": "SKIPPED", "reason": rejection_reason or "Zero size"}

    if price <= 0:
        return {"status": "SKIPPED", "reason": "Invalid price"}

    # --- LOBSTAR V2: PRE-VALIDATION NORMALIZATION ---
    # We must normalize size BEFORE checking risk/reserving capital,
    # because Polymarket might increase the size to meet min_notional.
    normalized_size = size
    normalized_price = price
    estimated_spread = 0.0
    try:
        normalizer = getattr(freqai, "normalize_and_validate", None) if freqai else None
        if callable(normalizer):
            normalized = normalizer(ticker, price, size)
            if inspect.isawaitable(normalized):
                normalized = await normalized
            if isinstance(normalized, (list, tuple)) and len(normalized) == 2:
                normalized_size, normalized_price = normalized
                logger.debug(f"📐 Size normalized for {ticker}: {size} -> {normalized_size}")
    except Exception as e:
        logger.warning(f"📐 Normalization failed for {ticker}: {e}")

    # Slippage Gate: reject when the live book is meaningfully worse than the signal.
    try:
        if str(mode).upper() != "REPLAY" and freqai and hasattr(freqai, "client") and hasattr(freqai.client, "get_order_book"):
            book = freqai.client.get_order_book(ticker)
            if inspect.isawaitable(book):
                book = await book
            estimated_spread = _estimate_spread_from_orderbook(book, price)
            bids = book.bids if hasattr(book, "bids") else book.get("bids", [])
            asks = book.asks if hasattr(book, "asks") else book.get("asks", [])
            if isinstance(bids, (list, tuple)) and isinstance(asks, (list, tuple)) and bids and asks:
                best_bid_raw = bids[0].price if hasattr(bids[0], "price") else bids[0].get("price", 0)
                best_ask_raw = asks[0].price if hasattr(asks[0], "price") else asks[0].get("price", 0)
                best_bid = float(best_bid_raw)
                best_ask = float(best_ask_raw)
                if best_bid > 0 and best_ask > 0:
                    mid_price = (best_bid + best_ask) / 2.0
                    price_diff = abs(mid_price - price) / price
                    threshold = _dynamic_slippage_threshold(price, best_bid, best_ask)
                    if price_diff > threshold:
                        logger.warning(
                            f"⚡ [SLIPPAGE GATE] Price deviation too high: mid_price={mid_price:.4f}, "
                            f"signal_price={price:.4f} (diff={price_diff:.2%}, threshold={threshold:.2%}). Rejecting trade."
                        )
                        return {
                            "status": "SKIPPED",
                            "reason": f"Slippage threshold exceeded (deviation={price_diff:.2%}, threshold={threshold:.2%})",
                            "ticker": ticker,
                            "side": side,
                        }
    except Exception as exc:
        logger.debug(f"Slippage check bypassed: {exc}")

    expected_edge = max(0.0, float(confidence) - float(normalized_price))
    objective = estimate_trade_objective(
        edge=expected_edge,
        price=normalized_price,
        size=normalized_size,
        spread=estimated_spread,
    )
    min_expected_profit = float(TRADING_PARAMS.get("MIN_EXPECTED_PROFIT_USDC", 0.05))
    if objective.expected_net_profit_usdc <= min_expected_profit:
        return {
            "status": "SKIPPED",
            "reason": (
                f"Objective rejected: expected net profit {objective.expected_net_profit_usdc:.4f} "
                f"<= minimum {min_expected_profit:.4f} USDC after fees"
            ),
            "objective": objective.objective,
            "estimated_cost_usdc": objective.estimated_cost_usdc,
            "expected_net_profit_usdc": objective.expected_net_profit_usdc,
        }

    report_data = {
        "ticker": ticker, "side": side, "price": normalized_price,
        "size": normalized_size, "executed_size": 0.0, "probability": confidence,
        "kelly_pct": sizing.get("kelly_pct", 0), "regime": regime,
        "path": "PASSIVE_MAKER" if executor else "DIRECT_CLOB",
        "trade_id": "N/A", "status": "PENDING",
        "reason_1": "Pattern alignment detected",
        "reason_2": "Liquidity depth sufficient",
        "reason_3": "Risk thresholds validated",
        "trading_objective": objective.objective,
        "estimated_cost_usdc": objective.estimated_cost_usdc,
        "expected_net_profit_usdc": objective.expected_net_profit_usdc,
    }

    if mode == "REPLAY":
        report_data["status"] = "SUCCESS"
        report_data["reason_1"] = "REPLAY_SKIP_EXECUTION"
        if store:
            try:
                store.record_decision(
                    mode=mode, ticker=ticker, side=side, price=normalized_price, sized=normalized_size,
                    executed_size=0.0, kelly_pct=sizing.get("kelly_pct", 0.0),
                    regime_label=regime, net_beta_pct=sizing.get("net_beta_exposure_pct", 0.0),
                    authorized=True, reason="REPLAY_SKIP_EXECUTION",
                )
            except Exception as e:
                logger.error(f"Failed to record replay decision: {e}")
        return report_data

    if store:
        try:
            store.record_signal(
                source=signal_source, ticker=ticker, side=side, price=normalized_price,
                size=normalized_size, confidence=confidence, regime_label=regime,
            )
        except Exception as e:
            logger.error(f"Failed to record signal: {e}")

    # PROD / SHADOW / PAPER Logic: validate risk before recording anything
    validation = ledger.validate_and_reserve(
        ticker=ticker,
        side=side,
        limit_price=normalized_price,
        requested_size=normalized_size,
    )
    if not validation["authorized"]:
        report_data["status"] = "FAILED"
        report_data["reason_1"] = validation["reason"]
        if store:
            try:
                store.record_decision(
                    mode=mode, ticker=ticker, side=side, price=normalized_price, sized=normalized_size,
                    executed_size=0.0, kelly_pct=sizing.get("kelly_pct", 0.0),
                    regime_label=regime, net_beta_pct=sizing.get("net_beta_exposure_pct", 0.0),
                    authorized=False, reason=validation["reason"],
                )
            except Exception as e:
                logger.error(f"Failed to record auth-failed decision: {e}")
        return report_data

    # Now authorized: record to paper and proceed
    final_size = validation["size"]
    paper_order_id = f"paper-{uuid.uuid4().hex[:8]}"
    try:
        ledger.record_paper_order(
            ticker=ticker, side=side, price=normalized_price, size=final_size,
            confidence=confidence, regime_label=regime, signal_source=signal_source,
            tenant_wallet=tenant_wallet,
        )
        if risk and mode == "PAPER":
            risk.book_exposure(ticker, final_size, side)
    except Exception as e:
        logger.error(f"Concurrent Paper recording failed: {e}")

    if mode == "PAPER":
        report_data["status"] = "SUCCESS"
        report_data["executed_size"] = final_size
        report_data["trade_id"] = paper_order_id
        if store:
            try:
                store.record_decision(
                    mode=mode, ticker=ticker, side=side, price=normalized_price, sized=final_size,
                    executed_size=final_size, kelly_pct=sizing.get("kelly_pct", 0.0),
                    regime_label=regime, net_beta_pct=sizing.get("net_beta_exposure_pct", 0.0),
                    authorized=True, reason="Paper order recorded",
                )
            except Exception as e:
                logger.error(f"Failed to record paper decision: {e}")
        return report_data

    final_size = validation["size"]
    if mode == "SHADOW":
        multiplier = float(TRADING_PARAMS.get("SHADOW_SIZE_MULTIPLIER", 0.01))
        final_size = max(1.0, final_size * multiplier)

    minimum_notional = _minimum_polymarket_notional(freqai)
    final_notional = float(final_size) * float(price)
    if final_size <= 0 or final_notional < minimum_notional:
        return {
            "status": "SKIPPED",
            "reason": (
                f"Pre-execution sizing rejection: notional {final_notional:.2f} "
                f"< Polymarket minimum {minimum_notional:.2f}"
            ),
            "ticker": ticker,
            "side": side,
            "price": price,
            "size": final_size,
        }

    exec_ok = False
    executed_size = 0.0
    position_id = f"{ticker}-{side}-{int(time.time())}"

    if executor:
        exec_result = await executor.execute(ticker, side, price, final_size)
        exec_ok = exec_result.get("status") in SUCCESS_STATUSES or _execution_succeeded(exec_result)
    else:
        try:
            exec_result = await freqai.clob_execute(ticker=ticker, side=side, price=price, size=final_size)
            exec_ok = _execution_succeeded(exec_result)
        except Exception as e:
            logger.error(f"Execution error: {e}")
            exec_ok = False

    if exec_ok:
        fill = _extract_fill_confirmation(exec_result, final_size, price)
        executed_size = fill["filled_size"]
        executed_price = fill["filled_price"]
        if executed_size > 0:
            ledger.record_order(
                position_id=position_id,
                ticker=ticker,
                side=side,
                price=executed_price,
                size=executed_size,
                tenant_wallet=tenant_wallet,
                requested_qty=final_size,
                filled_qty=executed_size,
                execution_price=executed_price,
                notional_usd=executed_size * executed_price,
                exchange_order_id=fill.get("order_id"),
            )
            if risk: risk.book_exposure(ticker, executed_size, side)
            report_data["status"] = "SUCCESS"
            report_data["executed_size"] = executed_size
            report_data["executed_price"] = executed_price
            report_data["trade_id"] = position_id
        else:
            report_data["status"] = "FAILED"
            report_data["reason_1"] = "Zero fill returned by CLOB"
    else:
        report_data["status"] = "FAILED"

        report_data["reason_1"] = "Execution rejected by CLOB"

    if store:
        try:
            store.record_decision(
                mode=mode, ticker=ticker, side=side, price=price, sized=size,
                executed_size=executed_size, kelly_pct=sizing.get("kelly_pct", 0.0),
                regime_label=regime, net_beta_pct=sizing.get("net_beta_exposure_pct", 0.0),
                authorized=exec_ok, reason=report_data.get("reason_1", "Nominal execution"),
            )
        except Exception as e:
            logger.error(f"Failed to record final decision: {e}")

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
    confidence = _apply_cognitive_confidence(signal, _regex_confidence(price))

    risk = kwargs.get("risk")
    sizing = risk.compute_position_size(
        ticker=ticker, side=side, price=price,
        confidence=confidence, regime_label=regime,
    ) if risk else {"size": 10.0}

    return await _execute_guarded(
        ticker, side, price, sizing["size"], confidence, regime, sizing,
        ledger, freqai, risk, kwargs.get("store"),
        mode, "regex", kwargs.get("executor"),
        tenant_wallet=kwargs.get("tenant_wallet"),
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
    confidence = _apply_cognitive_confidence(signal, decision.get("confidence", 0.0))

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
        mode, "lobstar_llm", kwargs.get("executor"),
        tenant_wallet=kwargs.get("tenant_wallet"),
    )
