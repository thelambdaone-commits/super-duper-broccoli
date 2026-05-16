import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException
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
from utils.vault_handler import VaultHandler

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
    
    container = ServiceContainer.get_instance()
    _ledger = container.ledger
    _freqai = container.freqai
    _hmm = container.hmm
    _risk = container.risk
    _store = container.store
    _executor = container.executor
    
    _arb = ArbitrageScanner()
    _sentiment = SentimentAnalyzer()
    _market_intel = CryptoMarketIntelligence()
    _poly_client = PolymarketClient()
    
    mcp_initialize(
        ledger=_ledger, hmm_filter=_hmm, risk_engine=_risk,
        feature_store=_store, passive_executor=_executor, arb_scanner=_arb,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
