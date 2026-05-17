import json
import logging
from typing import Any, Optional

import numpy as np
from mcp.server.fastmcp import FastMCP

from core.portfolio_risk_engine import PortfolioRiskEngine
from execution.passive_executor import PassiveExecutor
from ledger.ledger_db import Ledger
from user_data.strategies.arbitrage_scanner import ArbitrageScanner
from user_data.strategies.hmm_filter import HMMRegimeFilter

from mcp_agents.tools.ledger_tools import get_ledger_tools
from mcp_agents.tools.market_tools import get_market_tools
from mcp_agents.tools.execution_tools import get_execution_tools
from mcp_agents.tools.storage_tools import get_storage_tools

# Specialist utilities
from utils.ai_specialists import (
    build_specialist_prompt_context,
    get_ai_routing_policy,
    get_ai_specialist,
    list_ai_specialists,
    list_free_ai_provider_sources,
)
from utils.project_context import (
    get_project_context,
    list_local_skill_contexts,
    list_project_contexts,
)
from utils.prompt_memory import (
    build_project_prompt_context,
    format_project_prompt_context,
    list_project_memory,
    record_project_memory,
)

logger = logging.getLogger("MCPServer")

_ledger: Optional[Ledger] = None
_hmm_filter: Optional[HMMRegimeFilter] = None
_risk_engine: Optional[PortfolioRiskEngine] = None
_feature_store: Optional[Any] = None
_passive_executor: Optional[PassiveExecutor] = None
_arb_scanner: Optional[ArbitrageScanner] = None
_circuit_breaker_engaged = False

mcp = FastMCP(
    "quant-agentic-mcp",
    instructions="MCP server for quant-agentic-trading-core. "
    "Exposes ledger state, HMM market regime, and emergency circuit breaker.",
)

def initialize(
    ledger: Ledger,
    hmm_filter: HMMRegimeFilter,
    risk_engine: Optional[PortfolioRiskEngine] = None,
    feature_store: Optional[any] = None,
    passive_executor: Optional[PassiveExecutor] = None,
    arb_scanner: Optional[ArbitrageScanner] = None,
) -> None:
    global _ledger, _hmm_filter, _risk_engine, _feature_store, _passive_executor, _arb_scanner
    _ledger = ledger
    _hmm_filter = hmm_filter
    _risk_engine = risk_engine
    _feature_store = feature_store
    _passive_executor = passive_executor
    _arb_scanner = arb_scanner

    # Register tools with initialized components
    get_ledger_tools(mcp, ledger)
    get_market_tools(mcp, hmm_filter, arb_scanner)
    get_execution_tools(mcp, ledger, risk_engine, hmm=hmm_filter)
    get_storage_tools(mcp, feature_store)
    
    # Register specialized AI tools
    _register_specialist_tools(mcp)
    
    logger.info("MCP Server tools initialized.")

def _register_specialist_tools(mcp):
    @mcp.tool(name="list_ai_specialists")
    def list_ai_specialists_tool(task: str = ""): return {"specialists": list_ai_specialists(task)}

    @mcp.tool(name="get_ai_specialist")
    def get_ai_specialist_tool(specialist_id: str): return get_ai_specialist(specialist_id)

    @mcp.tool(name="get_project_prompt_context")
    def get_project_prompt_context_tool(task: str = "", specialist_id: str = "", component: str = "", token_budget: int = 2500):
        context = build_project_prompt_context(task=task, specialist_id=specialist_id, component=component, token_budget=token_budget)
        return {"context": context, "text": format_project_prompt_context(context)}

    @mcp.tool(name="record_project_memory")
    def record_project_memory_tool(component: str, summary: str, kind: str = "note", tags_json: str = "[]", details: str = ""):
        tags = json.loads(tags_json or "[]")
        return {"entry": record_project_memory(component=component, summary=summary, kind=kind, tags=tags, details=details)}

    # ── Dynamic Agent Skills Integration ──
    @mcp.tool(name="scan_polymarket")
    def scan_polymarket_tool(limit: int = 5) -> dict:
        """Scans Polymarket predictive markets for sentiment analysis and activity levels."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("market_scanner_skill", "scan_polymarket", {"limit": limit})

    @mcp.tool(name="calculate_kelly_size")
    def calculate_kelly_size_tool(ticker: str, side: str, price: float, confidence: float = 0.55, regime: str = "LOW_VOLATILITY") -> dict:
        """Computes recommended position sizing based on trade confidence, asset price, and current volatility regime."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("portfolio_risk_skill", "calculate_kelly_size", {
            "ticker": ticker, "side": side, "price": price, "confidence": confidence, "regime": regime
        })

    @mcp.tool(name="run_swarm_backtest")
    def run_swarm_backtest_tool(asset: str) -> dict:
        """Orchestrates multi-agent backtesting scenarios on historical quantitative assets."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("backtest_swarm_skill", "run_swarm_backtest", {"asset": asset})

    @mcp.tool(name="find_arbitrage_opportunities")
    def find_arbitrage_opportunities_tool(min_spread_pct: float = 1.5) -> dict:
        """Finds crypto and prediction market arbitrage opportunities with high implied spreads."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("crypto_arbitrage_skill", "find_arbitrage_opportunities", {"min_spread_pct": min_spread_pct})

    @mcp.tool(name="calculate_market_making_spreads")
    def calculate_market_making_spreads_tool(mid_price: float, volatility: float, inventory: float, target_inventory: float = 0.0) -> dict:
        """Calculates skew-adjusted bid and ask quotes for prediction market order-books."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("polymarket_market_making_skill", "calculate_market_making_spreads", {
            "mid_price": mid_price, "volatility": volatility, "inventory": inventory, "target_inventory": target_inventory
        })

    @mcp.tool(name="search_brave_web")
    def search_brave_web_tool(query: str, count: int = 5) -> dict:
        """Executes external web search via Brave API to gather recent market consensus and context."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("brave_search_skill", "search_brave_web", {"query": query, "count": count})

    # ── Continuous Improvement Integration ──
    @mcp.tool(name="get_continuous_improvement_report")
    def get_continuous_improvement_report_tool() -> dict:
        """Generates a consolidated code quality audit, test gap analysis, and self-improvement suggestions report."""
        from continuous_improvement.agent import CIRegistry
        ci = CIRegistry()
        return {
            "status": "SUCCESS",
            "consolidated_report": ci.generate_consolidated_report(),
            "untested_gaps": ci.find_test_gaps()
        }


def get_ledger_state() -> dict:
    if _ledger is None:
        return {"error": "Ledger not initialized"}
    return {
        "capital_summary": _ledger.get_capital_summary(),
        "open_positions": _ledger.get_open_positions(),
    }


def get_market_regime(ticker: str = "SOL", returns_json: str = "") -> dict:
    if _hmm_filter is None:
        return {"error": "HMM filter not initialized", "regime": "UNKNOWN"}

    if returns_json:
        returns = np.array(json.loads(returns_json), dtype=np.float32)
    else:
        returns = np.zeros(100, dtype=np.float32)

    state, label = _hmm_filter.predict_with_label(returns)
    di = _hmm_filter.compute_dissimilarity_index(returns)
    allowed, reason = _hmm_filter.is_trading_allowed(returns)
    if _circuit_breaker_engaged:
        allowed = False
        reason = "Emergency circuit breaker engaged"

    return {
        "ticker": ticker,
        "hmm_state": int(state),
        "regime_label": label,
        "dissimilarity_index": round(float(di), 6),
        "trading_allowed": allowed,
        "reason": reason,
    }


def emergency_circuit_breaker(action: str) -> dict:
    global _circuit_breaker_engaged

    action_upper = action.strip().upper()
    if action_upper in ("ENGAGE", "FREEZE", "ON", "KILL"):
        _circuit_breaker_engaged = True
        return {
            "status": "ENGAGED",
            "trading_allowed": False,
            "message": "Emergency circuit breaker engaged. Outbound trading is frozen.",
        }
    if action_upper in ("DISENGAGE", "RESUME", "OFF", "UNFREEZE"):
        _circuit_breaker_engaged = False
        return {
            "status": "DISENGAGED",
            "trading_allowed": True,
            "message": "Emergency circuit breaker disengaged. Outbound trading is allowed.",
        }
    return {
        "error": f"Invalid action: {action}. Choose ENGAGE or DISENGAGE.",
        "trading_allowed": not _circuit_breaker_engaged,
    }


def set_execution_mode(mode: str) -> dict:
    if _ledger is None:
        return {"error": "Ledger not initialized"}
    mode_upper = mode.upper().strip()
    if mode_upper not in ("REPLAY", "PAPER", "SHADOW", "PROD"):
        return {"error": f"Invalid mode: {mode}. Choose from REPLAY, PAPER, SHADOW, PROD."}
    _ledger.set_execution_mode(mode_upper)
    return {
        "status": "OK",
        "execution_mode": mode_upper,
        "message": f"Execution mode set to {mode_upper}.",
    }


def get_execution_mode() -> dict:
    if _ledger is None:
        return {"error": "Ledger not initialized"}
    return {"execution_mode": _ledger.get_execution_mode()}


def get_executor_metrics() -> dict:
    if _passive_executor is None:
        return {"error": "PassiveExecutor not initialized"}
    return {
        "metrics": _passive_executor.get_metrics(),
        "queue": _passive_executor.get_queue_snapshot(),
    }


def get_arbitrage_opportunities() -> dict:
    if _arb_scanner is None:
        return {"error": "ArbitrageScanner not initialized"}
    return {
        "opportunity_count": _arb_scanner.opportunity_count,
        "opportunities": _arb_scanner.get_active_opportunities(),
    }


def get_feature_store_stats() -> dict:
    if _feature_store is None:
        return {"error": "FeatureStore not initialized"}
    return {"stats": _feature_store.get_stats()}


def get_feature_history(
    ticker: str,
    feature_name: str,
    since_timestamp: float = 0.0,
    limit: int = 100,
) -> dict:
    if _feature_store is None:
        return {"error": "FeatureStore not initialized"}
    features = _feature_store.get_feature_history(ticker, feature_name, since_timestamp, limit)
    return {
        "ticker": ticker,
        "feature": feature_name,
        "count": len(features),
        "samples": features[:limit],
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
