import logging
import os
from contextlib import asynccontextmanager
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

from core.container import ServiceContainer
from core.freqai_engine import FreqAIEngine
from core.portfolio_risk_engine import PortfolioRiskEngine
from execution.passive_executor import PassiveExecutor
from ledger.ledger_db import Ledger
from mcp_agents.mcp_server import (
    initialize as mcp_initialize,
    get_ledger_state,
    get_market_regime,
    emergency_circuit_breaker,
    set_execution_mode,
    get_execution_mode,
    get_executor_metrics,
    get_arbitrage_opportunities,
    get_feature_store_stats,
    get_feature_history,
)
from user_data.strategies.arbitrage_scanner import ArbitrageScanner
from user_data.strategies.hmm_filter import HMMRegimeFilter
from user_data.strategies.sentiment_nlp import SentimentAnalyzer
from utils.crypto_market_intelligence import (
    CryptoMarketIntelligence,
    format_intelligence_report,
)
from utils.feature_store import FeatureStore
from utils.polymarket_client import PolymarketClient
from utils.regime_utils import get_regime_label

# New module imports (optional - gracefully degrade if missing)
try:
    from models.volatility_surface import VolSurfaceAdapter
except ImportError:
    VolSurfaceAdapter = None  # type: ignore[assignment]
try:
    from utils.earnings_sentiment_pipeline import EarningsSentimentPipeline
except ImportError:
    EarningsSentimentPipeline = None  # type: ignore[assignment]
try:
    from utils.chart_pattern_detector import ChartPatternDetector
except ImportError:
    ChartPatternDetector = None  # type: ignore[assignment]
try:
    from utils.sentiment_ensemble import SentimentEnsemble
except ImportError:
    SentimentEnsemble = None  # type: ignore[assignment]
try:
    from models.portfolio import PortfolioOptimizer
except ImportError:
    PortfolioOptimizer = None  # type: ignore[assignment]
try:
    from utils.macro_intelligence import MacroIntelligence
except ImportError:
    MacroIntelligence = None  # type: ignore[assignment]
try:
    from engine.backtest import Backtester, CostModel
except ImportError:
    Backtester = None  # type: ignore[assignment]
    CostModel = None  # type: ignore[assignment]
try:
    from utils.feature_factory import FeatureFactory
except ImportError:
    FeatureFactory = None  # type: ignore[assignment]

logger = logging.getLogger("APIServer")

_ledger: Optional[Ledger] = None
_freqai: Optional[FreqAIEngine] = None
_hmm: Optional[HMMRegimeFilter] = None
_risk: Optional[PortfolioRiskEngine] = None
_store: Optional[FeatureStore] = None
_executor: Optional[PassiveExecutor] = None
_arb: Optional[ArbitrageScanner] = None
_sentiment: Optional[SentimentAnalyzer] = None
_market_intel: Optional[CryptoMarketIntelligence] = None
_poly_client: Optional[PolymarketClient] = None

# New module globals
_vol_surface: Optional[VolSurfaceAdapter] = None
_earnings: Optional[EarningsSentimentPipeline] = None
_chart_detector: Optional[ChartPatternDetector] = None
_sentiment_ensemble: Optional[SentimentEnsemble] = None
_portfolio_opt: Optional[PortfolioOptimizer] = None
_macro: Optional[MacroIntelligence] = None
_backtester: Optional[Backtester] = None


def _make_timeout_calibrator(hmm: HMMRegimeFilter, base_timeout: float = 5.0) -> Callable[[str], float]:
    def calibrate(ticker: str) -> float:
        label = get_regime_label(hmm, ticker)
        if label == "ERRATIC_VOLATILITY":
            return max(1.0, base_timeout * 0.3)
        elif label == "HIGH_TREND_VOLATILITY":
            return max(1.0, base_timeout * 0.6)
        return base_timeout
    return calibrate


class ModeRequest(BaseModel):
    mode: str


class ActionRequest(BaseModel):
    action: str


class SignalRequest(BaseModel):
    ticker: str
    side: str
    price: float
    size: float = 0.0
    confidence: float = 0.5


class SentimentRequest(BaseModel):
    text: str


class SentimentBatchRequest(BaseModel):
    texts: list[str]


class MispricingRequest(BaseModel):
    market_prices: dict[str, float]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ledger, _freqai, _hmm, _risk, _store, _executor, _arb, _sentiment, _market_intel, _poly_client
    global _vol_surface, _earnings, _chart_detector, _sentiment_ensemble, _portfolio_opt, _macro, _backtester

    container = ServiceContainer.get_instance()
    _ledger = container.ledger
    _freqai = container.freqai
    _hmm = container.hmm
    _risk = container.risk
    _store = container.store
    _executor = container.executor

    _arb = ArbitrageScanner()
    _sentiment = SentimentAnalyzer(use_finbert=True)
    _market_intel = CryptoMarketIntelligence()
    _poly_client = PolymarketClient()

    _vol_surface = container.vol_surface or VolSurfaceAdapter()
    _earnings = container.earnings or EarningsSentimentPipeline(use_huggingface=True)
    _chart_detector = container.chart_detector or ChartPatternDetector()
    _sentiment_ensemble = container.sentiment_ensemble or SentimentEnsemble(use_vader=True, use_finbert=True)
    _portfolio_opt = container.portfolio_opt or PortfolioOptimizer(method="mean_variance")
    _macro = container.macro or MacroIntelligence()
    _backtester = container.backtester or Backtester(initial_capital=10000.0)

    mcp_initialize(
        ledger=_ledger, hmm_filter=_hmm, risk_engine=_risk,
        feature_store=_store, passive_executor=_executor, arb_scanner=_arb,
        vol_surface=_vol_surface, earnings=_earnings, chart_detector=_chart_detector,
        sentiment_ensemble=_sentiment_ensemble, portfolio_opt=_portfolio_opt,
        macro=_macro, backtester=_backtester,
        feature_factory_cls=FeatureFactory,
    )
    logger.info("API server initialized via ServiceContainer")
    try:
        yield
    finally:
        if _poly_client is not None:
            _poly_client.close()


app = FastAPI(
    title="Quant Agentic Trading Core API",
    description="REST API for Polymarket CLOB trading bot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("API_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/ledger")
def v1_ledger() -> dict:
    if _ledger is None:
        raise HTTPException(503, "Not initialized")
    return get_ledger_state()


@app.get("/v1/regime")
def v1_regime(ticker: str = "SOL") -> dict:
    if _hmm is None:
        raise HTTPException(503, "Not initialized")
    return get_market_regime(ticker=ticker)


@app.post("/v1/circuit-breaker")
def v1_circuit_breaker(body: ActionRequest) -> dict:
    return emergency_circuit_breaker(body.action)


@app.post("/v1/execution-mode")
def v1_set_mode(body: ModeRequest) -> dict:
    return set_execution_mode(body.mode)


@app.get("/v1/execution-mode")
def v1_get_mode() -> dict:
    return get_execution_mode()


@app.get("/v1/executor/metrics")
def v1_executor_metrics() -> dict:
    return get_executor_metrics()


@app.get("/v1/arbitrage")
def v1_arbitrage() -> dict:
    return get_arbitrage_opportunities()


@app.post("/v1/arbitrage/scan-mispricing")
def v1_scan_mispricing(body: MispricingRequest) -> dict:
    if _arb is None:
        raise HTTPException(503, "ArbitrageScanner not initialized")
    opps = _arb.scan_mispricing(body.market_prices)
    return {"opportunities": opps, "count": len(opps)}


@app.post("/v1/sentiment")
def v1_sentiment(body: SentimentRequest) -> dict:
    if _sentiment is None:
        raise HTTPException(503, "SentimentAnalyzer not initialized")
    result = _sentiment.analyze(body.text)
    return {"text": body.text, "sentiment": result}


@app.post("/v1/sentiment/batch")
def v1_sentiment_batch(body: SentimentBatchRequest) -> dict:
    if _sentiment is None:
        raise HTTPException(503, "SentimentAnalyzer not initialized")
    results = _sentiment.analyze_batch(body.texts)
    return {"results": results, "count": len(results)}


@app.get("/v1/feature-store")
def v1_feature_store() -> dict:
    return get_feature_store_stats()


@app.get("/v1/features/{ticker}/{feature_name}")
def v1_feature_history(ticker: str, feature_name: str, since: float = 0.0, limit: int = 100) -> dict:
    return get_feature_history(ticker=ticker, feature_name=feature_name, since_timestamp=since, limit=limit)


@app.get("/v1/pnl/summary")
def v1_pnl_summary(mode: str = "PAPER") -> dict:
    if _ledger is None:
        raise HTTPException(503, "Not initialized")
    summary = _ledger.get_performance_summary(mode=mode)
    if not summary:
        return {"execution_mode": mode, "total_trades": 0}
    return summary


@app.get("/v1/pnl/history")
def v1_pnl_history(limit: int = 50) -> dict:
    if _ledger is None:
        raise HTTPException(503, "Not initialized")
    history = _ledger.get_historical_performance(limit=limit)
    return {"trades": history, "count": len(history)}


@app.get("/v1/pnl/positions")
def v1_pnl_positions(status: str = "CLOSED", limit: int = 50) -> dict:
    if _ledger is None:
        raise HTTPException(503, "Not initialized")
    positions = _ledger.get_paper_positions(status=status)[:limit]
    return {"positions": positions, "count": len(positions)}


@app.get("/v1/market-intelligence/crypto")
def v1_crypto_market_intelligence(limit: int = 30, query: str = "", as_text: bool = False) -> dict:
    if _market_intel is None or _poly_client is None:
        raise HTTPException(503, "Market intelligence not initialized")
    markets = (
        _poly_client.search_markets(query, limit=limit)
        if query else _poly_client.list_markets(limit=limit, sort_by="volume")
    )
    report = _market_intel.analyze(markets)
    payload = report.to_dict()
    if as_text:
        payload["text"] = format_intelligence_report(report)
    return payload


# ── New Module Endpoints ─────────────────────────────────────────────

class MacroIndicatorsRequest(BaseModel):
    inflation: float = 3.0
    unemployment: float = 4.0
    current_rate: float = 4.5
    variant: str = "1993"
    high_freq: dict[str, float] = {}
    vix: Optional[float] = None

class VolSurfaceRequest(BaseModel):
    n_surfaces: int = 10
    seed: Optional[int] = None

class OHLCVPoint(BaseModel):
    Open: float
    High: float
    Low: float
    Close: float
    Volume: float = 0.0

class ChartDetectionRequest(BaseModel):
    ohlcv: list[OHLCVPoint]
    conf_threshold: float = 0.5

class HedgeSimulateRequest(BaseModel):
    n_episodes: int = 100
    s0: float = 100.0
    sigma: float = 0.2
    spread: float = 0.01

class PortfolioRequest(BaseModel):
    prices: list[float]
    tickers: list[str]
    method: str = "equal_weight"

class BacktestRequest(BaseModel):
    prices: dict[str, list[float]]
    signals: dict[str, list[float]]
    initial_capital: float = 10000.0
    spread_bps: float = 1.0

@app.get("/v1/vol-surface/status")
def v1_vol_surface_status() -> dict:
    if _vol_surface is None:
        raise HTTPException(503, "VolSurface not initialized")
    return _vol_surface.get_status()

@app.post("/v1/vol-surface/synthetic")
def v1_vol_surface_synthetic(body: VolSurfaceRequest) -> dict:
    if _vol_surface is None:
        raise HTTPException(503, "VolSurface not initialized")
    surfaces = _vol_surface.generate_synthetic_surfaces(n_surfaces=body.n_surfaces, seed=body.seed)
    return {"n_surfaces": len(surfaces), "surfaces": surfaces[:5], "note": "Showing first 5 samples"}

@app.get("/v1/earnings/status")
def v1_earnings_status() -> dict:
    if _earnings is None:
        raise HTTPException(503, "Earnings pipeline not initialized")
    return _earnings.get_status()

@app.post("/v1/sentiment/advanced")
def v1_sentiment_advanced(body: SentimentRequest) -> dict:
    if _sentiment_ensemble is None:
        raise HTTPException(503, "SentimentEnsemble not initialized")
    return _sentiment_ensemble.analyze(body.text)

@app.post("/v1/sentiment/advanced/batch")
def v1_sentiment_advanced_batch(body: SentimentBatchRequest) -> dict:
    if _sentiment_ensemble is None:
        raise HTTPException(503, "SentimentEnsemble not initialized")
    results = _sentiment_ensemble.analyze_batch(body.texts)
    return {"results": results, "count": len(results)}

@app.post("/v1/chart/detect")
def v1_chart_detect(body: ChartDetectionRequest) -> dict:
    if _chart_detector is None:
        raise HTTPException(503, "ChartDetector not initialized")
    ohlcv_list = [{"Open": p.Open, "High": p.High, "Low": p.Low, "Close": p.Close, "Volume": p.Volume} for p in body.ohlcv]
    detections = _chart_detector.detect_from_array(ohlcv_list, conf_threshold=body.conf_threshold)
    return {"detections": detections, "count": len(detections)}

@app.get("/v1/chart/patterns")
def v1_chart_patterns() -> dict:
    if _chart_detector is None:
        raise HTTPException(503, "ChartDetector not initialized")
    return {"supported_patterns": _chart_detector.get_supported_patterns()}

@app.post("/v1/macro/taylor-rule")
def v1_macro_taylor(body: MacroIndicatorsRequest) -> dict:
    if _macro is None:
        raise HTTPException(503, "MacroIntelligence not initialized")
    taylor = _macro.taylor_rule(
        inflation=body.inflation, unemployment=body.unemployment,
        current_rate=body.current_rate, variant=body.variant,
    )
    risk = _macro.risk_off_score(taylor_result=taylor, vix=body.vix)
    return {"taylor_rule": {
        "implied_rate": taylor.implied_rate,
        "current_rate": taylor.current_rate,
        "stance": taylor.stance,
        "z_score": taylor.z_score,
        "variant": taylor.variant,
        "components": taylor.components,
    }, "risk_assessment": risk}

@app.post("/v1/macro/gdp-nowcast")
def v1_macro_gdp(body: MacroIndicatorsRequest) -> dict:
    if _macro is None:
        raise HTTPException(503, "MacroIntelligence not initialized")
    gdp = _macro.gdp_nowcast(body.high_freq)
    return {
        "gdp_growth_pct": gdp.gdp_growth,
        "confidence_interval": list(gdp.confidence_interval),
        "r_squared": gdp.r_squared,
        "rmse": gdp.rmse,
    }

@app.post("/v1/portfolio/optimize")
def v1_portfolio_optimize(body: PortfolioRequest) -> dict:
    if _portfolio_opt is None:
        raise HTTPException(503, "PortfolioOptimizer not initialized")
    if not body.tickers:
        raise HTTPException(400, "tickers must not be empty")
    if not body.prices:
        raise HTTPException(400, "prices must not be empty")
    try:
        import pandas as pd
        df = pd.DataFrame({ticker: body.prices for ticker in body.tickers})
        result = _portfolio_opt.optimize_weights(df, method=body.method)
        return result
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/v1/hedging/simulate")
def v1_hedging_simulate(body: HedgeSimulateRequest) -> dict:
    from models.hedging import HedgingEnv, DDPGHedgingAgent
    env = HedgingEnv(S0=body.s0, sigma=body.sigma, spread=body.spread)
    agent = DDPGHedgingAgent()
    episodes_log = []
    for ep in range(min(body.n_episodes, 50)):
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
        episodes_log.append({"episode": ep, "reward": round(total_reward, 4)})
    return {"n_episodes": len(episodes_log), "episodes": episodes_log[:10], "note": "Showing first 10 episodes"}

@app.post("/v1/backtest/run")
def v1_backtest_run(body: BacktestRequest) -> dict:
    import pandas as pd
    global _backtester
    prices_df = pd.DataFrame(body.prices)
    signals_df = pd.DataFrame(body.signals)
    if _backtester is None:
        _backtester = Backtester()
    previous_capital = _backtester.initial_capital
    previous_cost_model = _backtester.cost_model
    try:
        _backtester.initial_capital = body.initial_capital
        _backtester.cost_model = CostModel(spread_bps=body.spread_bps)
        return _backtester.run(prices_df, signals_df)
    finally:
        _backtester.initial_capital = previous_capital
        _backtester.cost_model = previous_cost_model


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
