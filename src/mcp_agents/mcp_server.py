import json
import logging
from typing import Any, Optional

import numpy as np
from mcp.server.fastmcp import FastMCP

from services.portfolio_risk_engine import PortfolioRiskEngine
from polymarket.execution.passive_executor import PassiveExecutor
from database.ledger_db import Ledger
from strategies.arbitrage_scanner import ArbitrageScanner
from strategies.hmm_filter import HMMRegimeFilter

from mcp_agents.tools.ledger_tools import get_ledger_tools
from mcp_agents.tools.market_tools import get_market_tools
from mcp_agents.tools.execution_tools import get_execution_tools
from mcp_agents.tools.storage_tools import get_storage_tools

# Specialist utilities
from utils.ai_specialists import (
    get_ai_specialist,
    list_ai_specialists,
)
from utils.prompt_memory import (
    build_project_prompt_context,
    format_project_prompt_context,
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

# New module globals (shared state)
_vol_surface: Optional[Any] = None
_earnings: Optional[Any] = None
_chart_detector: Optional[Any] = None
_sentiment_ensemble: Optional[Any] = None
_portfolio_opt: Optional[Any] = None
_macro: Optional[Any] = None
_backtester: Optional[Any] = None
_feature_factory_cls: Optional[Any] = None

mcp = FastMCP(
    "quant-agentic-mcp",
    instructions="MCP server for quant-agentic-trading-core. "
    "Exposes ledger state, HMM market regime, and emergency circuit breaker.",
)

def initialize(
    ledger: Ledger,
    hmm_filter: HMMRegimeFilter,
    risk_engine: Optional[PortfolioRiskEngine] = None,
    feature_store: Optional[Any] = None,
    passive_executor: Optional[PassiveExecutor] = None,
    arb_scanner: Optional[ArbitrageScanner] = None,
    vol_surface: Optional[Any] = None,
    earnings: Optional[Any] = None,
    chart_detector: Optional[Any] = None,
    sentiment_ensemble: Optional[Any] = None,
    portfolio_opt: Optional[Any] = None,
    macro: Optional[Any] = None,
    backtester: Optional[Any] = None,
    feature_factory_cls: Optional[Any] = None,
) -> None:
    global _ledger, _hmm_filter, _risk_engine, _feature_store, _passive_executor, _arb_scanner
    global _vol_surface, _earnings, _chart_detector, _sentiment_ensemble
    global _portfolio_opt, _macro, _backtester, _feature_factory_cls
    _ledger = ledger
    _hmm_filter = hmm_filter
    _risk_engine = risk_engine
    _feature_store = feature_store
    _passive_executor = passive_executor
    _arb_scanner = arb_scanner
    _vol_surface = vol_surface
    _earnings = earnings
    _chart_detector = chart_detector
    _sentiment_ensemble = sentiment_ensemble
    _portfolio_opt = portfolio_opt
    _macro = macro
    _backtester = backtester
    _feature_factory_cls = feature_factory_cls

    # Register tools with initialized components
    get_ledger_tools(mcp, ledger)
    get_market_tools(mcp, hmm_filter, arb_scanner)
    get_execution_tools(mcp, ledger, risk_engine, hmm=hmm_filter)
    get_storage_tools(mcp, feature_store)

    # Register specialized AI tools
    _register_specialist_tools(mcp)

    # Register new module tools
    _register_new_module_tools(mcp)

    logger.info("MCP Server tools initialized.")

def _get_adapter(module_name: str):
    """Lazy singleton helper: returns shared instance or creates one."""
    global _vol_surface, _earnings, _chart_detector, _sentiment_ensemble
    global _portfolio_opt, _macro, _backtester
    if module_name == "vol_surface":
        if _vol_surface is None:
            from schemas.volatility import VolSurfaceAdapter
            _vol_surface = VolSurfaceAdapter()
        return _vol_surface
    elif module_name == "earnings":
        if _earnings is None:
            from utils.earnings_sentiment_pipeline import EarningsSentimentPipeline
            _earnings = EarningsSentimentPipeline(use_huggingface=True)
        return _earnings
    elif module_name == "chart_detector":
        if _chart_detector is None:
            from utils.chart_pattern_detector import ChartPatternDetector
            _chart_detector = ChartPatternDetector()
        return _chart_detector
    elif module_name == "sentiment_ensemble":
        if _sentiment_ensemble is None:
            from utils.sentiment_ensemble import SentimentEnsemble
            _sentiment_ensemble = SentimentEnsemble(use_vader=True, use_finbert=True)
        return _sentiment_ensemble
    elif module_name == "portfolio_opt":
        if _portfolio_opt is None:
            from schemas.optimization import PortfolioOptimizer
            _portfolio_opt = PortfolioOptimizer(method="mean_variance")
        return _portfolio_opt
    elif module_name == "macro":
        if _macro is None:
            from utils.macro_intelligence import MacroIntelligence
            _macro = MacroIntelligence()
        return _macro
    elif module_name == "backtester":
        if _backtester is None:
            from core.backtest import Backtester
            _backtester = Backtester(initial_capital=10000.0)
        return _backtester
    raise ValueError(f"Unknown module: {module_name}")

def _register_new_module_tools(mcp):
    @mcp.tool(name="vol_surface_status")
    def vol_surface_status_tool() -> dict:
        """Returns the status of the volatility surface module (SSVI models)."""
        return _get_adapter("vol_surface").get_status()

    @mcp.tool(name="vol_surface_synthetic")
    def vol_surface_synthetic_tool(n_surfaces: int = 10, seed: int = 42) -> dict:
        """Generates synthetic SSVI volatility surfaces for training or analysis."""
        surfaces = _get_adapter("vol_surface").generate_synthetic_surfaces(n_surfaces=n_surfaces, seed=seed)
        return {"n_surfaces": len(surfaces), "samples": surfaces[:3]}

    @mcp.tool(name="sentiment_ensemble")
    def sentiment_ensemble_tool(text: str) -> dict:
        """Analyzes financial text sentiment using an ensemble of VADER + FinBERT."""
        return _get_adapter("sentiment_ensemble").analyze(text)

    @mcp.tool(name="macro_taylor_rule")
    def macro_taylor_rule_tool(inflation: float = 3.0, unemployment: float = 4.0, current_rate: float = 4.5, variant: str = "1993") -> dict:
        """Estimates implied central bank policy rate using Taylor Rule."""
        taylor = _get_adapter("macro").taylor_rule(inflation=inflation, unemployment=unemployment, current_rate=current_rate, variant=variant)
        return {"implied_rate": taylor.implied_rate, "stance": taylor.stance, "z_score": taylor.z_score}

    @mcp.tool(name="macro_risk_assessment")
    def macro_risk_assessment_tool(inflation: float = 3.0, unemployment: float = 4.0, vix: float = 15.0) -> dict:
        """Assesses macro risk-on/risk-off regime using Taylor Rule + GDP + VIX."""
        macro = _get_adapter("macro")
        taylor = macro.taylor_rule(inflation=inflation, unemployment=unemployment)
        return macro.risk_off_score(taylor_result=taylor, vix=vix)

    @mcp.tool(name="chart_detect_patterns")
    def chart_detect_patterns_tool(ohlcv_json: str, conf_threshold: float = 0.5) -> dict:
        """Detects candlestick chart patterns (Head&Shoulders, Triangle, etc.) using YOLOv8."""
        import json
        ohlcv = json.loads(ohlcv_json)
        detections = _get_adapter("chart_detector").detect_from_array(ohlcv, conf_threshold=conf_threshold)
        return {"detections": detections, "count": len(detections)}

    @mcp.tool(name="portfolio_optimize")
    def portfolio_optimize_tool(prices_json: str, tickers_json: str, method: str = "equal_weight") -> dict:
        """Optimizes portfolio weights using mean-variance, risk-parity, or equal-weight methods."""
        import json
        import pandas as pd
        prices = json.loads(prices_json)
        tickers = json.loads(tickers_json)
        df = pd.DataFrame(dict(zip(tickers, [prices] * len(tickers))))
        return _get_adapter("portfolio_opt").optimize_weights(df, method=method)

    @mcp.tool(name="hedge_simulate_rl")
    def hedge_simulate_rl_tool(n_episodes: int = 20, s0: float = 100.0, sigma: float = 0.2) -> dict:
        """Simulates option hedging using a DDPG reinforcement learning agent."""
        from schemas.risk import HedgingEnv, DDPGHedgingAgent
        env = HedgingEnv(S0=s0, sigma=sigma)
        agent = DDPGHedgingAgent()
        results = []
        for ep in range(min(n_episodes, 30)):
            state = env.reset(seed=ep)
            total_reward = 0.0
            done = False
            while not done:
                action = agent.select_action(state, noise=0.1)
                next_state, reward, done, _ = env.step(action)
                agent.replay.push(state, action, reward, next_state, done)
                agent.train_step()
                total_reward += reward
                state = next_state
            results.append({"episode": ep, "reward": round(total_reward, 4)})
        return {"n_episodes": len(results), "episodes": results}

    @mcp.tool(name="earnings_sentiment_status")
    def earnings_sentiment_status_tool() -> dict:
        """Returns the status of the earnings sentiment pipeline."""
        return _get_adapter("earnings").get_status()

    @mcp.tool(name="earnings_sentiment_analyze")
    def earnings_sentiment_analyze_tool(ticker: str, quarter: str = "") -> dict:
        """Analyzes earnings call transcript sentiment for a given ticker."""
        result = _get_adapter("earnings").analyze_earnings_call(ticker=ticker, quarter=quarter or None)
        return {
            "ticker": result.ticker,
            "quarter": result.quarter,
            "year": result.year,
            "sentiment_score": result.sentiment_score,
            "confidence": result.confidence,
            "key_themes": result.key_themes,
            "qualitative_assessment": result.qualitative_assessment,
            "error": result.error,
        }

    @mcp.tool(name="backtest_run")
    def backtest_run_tool(prices_json: str, signals_json: str, initial_capital: float = 10000.0, spread_bps: float = 1.0) -> dict:
        """Runs a vectorized backtest on price/signal dataframes with cost model."""
        import json
        import pandas as pd
        from core.backtest import CostModel
        prices = pd.DataFrame(json.loads(prices_json))
        signals = pd.DataFrame(json.loads(signals_json))
        bt = _get_adapter("backtester")
        bt.initial_capital = initial_capital
        bt.cost_model = CostModel(spread_bps=spread_bps)
        return bt.run(prices, signals)

    @mcp.tool(name="feature_factory_compute")
    def feature_factory_compute_tool(ohlcv_json: str) -> dict:
        """Computes 40+ technical features from OHLCV data using FeatureFactory."""
        import json
        import pandas as pd
        from utils.feature_factory import FeatureFactory
        ohlcv = json.loads(ohlcv_json)
        df = pd.DataFrame(ohlcv)
        ff = FeatureFactory(df)
        names = ff.get_feature_names()
        matrix = ff.get_feature_matrix()
        return {
            "feature_names": names,
            "feature_count": len(names),
            "feature_matrix_shape": list(matrix.shape),
            "last_row": {name: float(matrix[-1, i]) for i, name in enumerate(names)} if len(matrix) > 0 else {},
        }


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

    @mcp.tool(name="search_news_feeds")
    def search_news_feeds_tool(query: str, count: int = 5) -> dict:
        """Queries free RSS news feeds to gather recent market consensus and context."""
        from agent_skills.registry import SkillsRegistry
        return SkillsRegistry().dispatch_tool("news_aggregator_skill", "search_news_feeds", {"query": query, "count": count})

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


@mcp.tool(name="emergency_circuit_breaker", description="Instantly freezes or unfreezes all outbound trading operations. Action must be 'ENGAGE' or 'DISENGAGE'.")
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

# ── External Integration Bridges ──

_clodds_mcp_client: Optional[Any] = None


async def _ensure_clodds_client():
    """Lazily connect to CloddsBot MCP server if available."""
    global _clodds_mcp_client
    if _clodds_mcp_client is not None:
        return True
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:18789/health", timeout=2.0)
            if resp.status_code == 200:
                _clodds_mcp_client = resp
                logger.info("CloddsBot MCP peer detected at localhost:18789")
                return True
    except Exception:
        logger.debug("CloddsBot MCP peer not available")
    return False


@mcp.tool()
async def clodds_lp_repricing(
    token_id: str,
    side: str,
    current_price: float,
    mid_price: float,
    delta: float = 0.03,
) -> dict:
    """Use the polymarket_lp_tool SimplePricePolicy to decide whether to keep, cancel, or reprice
    a limit order. token_id is the CLOB token ID, side is BUY or SELL."""
    from agent_skills.polymarket_market_making_skill.adapter_lp_tool import LpToolAdapter
    adapter = LpToolAdapter()
    return adapter.decide_price(
        token_id=token_id,
        side=side,
        current_price=current_price,
        mid_price=mid_price,
        delta=delta,
    )


@mcp.tool()
async def clodds_lp_set_custom_rule(token_id: str, side: str, target_price: float) -> str:
    """Set a custom pricing rule for a given token+side. The rule will persist and override
    the default SimplePricePolicy logic for future repricing decisions."""
    from agent_skills.polymarket_market_making_skill.adapter_lp_tool import LpToolAdapter
    adapter = LpToolAdapter()
    adapter.set_custom_rule(token_id, side, {"target_price": target_price})
    return f"Custom rule set for {token_id}:{side} -> target_price={target_price}"


@mcp.tool()
async def pydantic_agent_analyze(market_query: str) -> dict:
    """Run the Pydantic AI analysis agent on a market query. Returns a structured MarketAnalysis
    with fair price, edge, regime, and recommendation."""
    try:
        from core.pydantic_agent_factory import PydanticAgentFactory, AgentDeps
        from core.container import _container
        if _container is None:
            return {"error": "ServiceContainer not initialized"}
        deps = AgentDeps(
            secrets=getattr(_container, "secrets", {}),
            store=getattr(_container, "store", None),
            ledger=getattr(_container, "ledger", None),
            risk=getattr(_container, "risk", None),
            executor=getattr(_container, "executor", None),
            hmm=getattr(_container, "hmm", None),
            freqai=getattr(_container, "freqai", None),
            market_scanner=getattr(_container, "market_scanner", None),
            notifier=getattr(_container, "notifier", None),
            signal_router=getattr(_container, "signal_router", None),
        )
        factory = PydanticAgentFactory(deps)
        result = await factory.run_signal_flow(market_query)
        return result.model_dump()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def clodds_mcp_health() -> dict:
    """Check if the CloddsBot MCP sidecar is reachable."""
    available = await _ensure_clodds_client()
    return {"clodds_bot_available": available, "status": "ok" if available else "unavailable"}


@mcp.tool()
async def polymarket_data_fetch_onchain(blocks: int = 100) -> dict:
    """Fetch recent on-chain Polymarket OrderFilled events using the Polymarket_data
    submodule. Fetches the latest N blocks from Polygon RPC."""
    try:
        from utils.polymarket_data.polymarket import LogFetcher, EventDecoder
        fetcher = LogFetcher(use_alchemy=False)
        latest = fetcher.get_latest_block()
        logs = fetcher.fetch_range_in_batches(latest - blocks, latest)
        decoder = EventDecoder()
        decoded = decoder.decode_batch(logs)
        events = decoder.format_batch(decoded)
        return {"status": "ok", "blocks_scanned": blocks, "events_found": len(events), "events": events[:50]}
    except ImportError:
        return {"error": "Polymarket_data not installed. Run: cd utils/polymarket_data && pip install -e ."}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
