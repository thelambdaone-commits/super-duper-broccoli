import logging
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

logger = logging.getLogger("PydanticAgentFactory")


class TradeSignal(BaseModel):
    action: str = Field(description="BUY, SELL, or HOLD")
    token_id: str = Field(description="Polymarket CLOB token ID")
    price: float = Field(ge=0.01, le=0.99, description="Limit price in USDC")
    size: int = Field(ge=1, description="Order size in contracts")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    reasoning: str = Field(description="Rationale for the signal")


class RiskAssessment(BaseModel):
    approved: bool
    max_size: int
    reason: str


class MarketAnalysis(BaseModel):
    fair_price: float = Field(ge=0.0, le=1.0)
    edge: float = Field(description="Edge vs market price")
    regime: str = Field(description="HMM regime label")
    recommendation: str


@dataclass
class AgentDeps:
    secrets: dict
    store: Any
    ledger: Any
    risk: Any
    executor: Any
    hmm: Any
    freqai: Any
    market_scanner: Any
    notifier: Any
    signal_router: Any


class PydanticAgentFactory:

    _agents: dict = {}

    def __init__(self, deps: AgentDeps, default_model: str = "groq:llama-3.3-70b-versatile"):
        self.deps = deps
        self.default_model = default_model

    def create_signal_agent(self, model: Optional[str] = None) -> Agent[AgentDeps, TradeSignal]:
        return self._make_agent(
            "signal_agent",
            model or self.default_model,
            TradeSignal,
            "You are a Polymarket trading signal analyst. Analyze market data and return validated trade signals.",
            tools=[self._get_market_data, self._get_portfolio_state, self._get_technical_indicators],
        )

    def create_risk_agent(self, model: Optional[str] = None) -> Agent[AgentDeps, RiskAssessment]:
        return self._make_agent(
            "risk_agent",
            model or self.default_model,
            RiskAssessment,
            "You are a risk management specialist. Assess trade proposals for the Polymarket portfolio.",
            tools=[self._get_portfolio_state, self._get_risk_metrics],
        )

    def create_analysis_agent(self, model: Optional[str] = None) -> Agent[AgentDeps, MarketAnalysis]:
        return self._make_agent(
            "analysis_agent",
            model or self.default_model,
            MarketAnalysis,
            "You are a market analysis agent. Compute fair prices and edges for Polymarket markets.",
            tools=[self._get_market_data, self._get_orderbook],
        )

    async def run_signal_flow(self, prompt: str, usage_limits: Optional[UsageLimits] = None) -> TradeSignal:
        agent = self.create_signal_agent()
        result = await agent.run(
            prompt,
            deps=self.deps,
            usage_limits=usage_limits or UsageLimits(request_limit=5, total_tokens_limit=4000),
        )
        return result.output

    async def run_risk_check(self, signal: TradeSignal) -> RiskAssessment:
        agent = self.create_risk_agent()
        result = await agent.run(
            f"Assess risk for: {signal.model_dump_json()}",
            deps=self.deps,
            usage_limits=UsageLimits(request_limit=3, total_tokens_limit=2000),
        )
        return result.output

    # ── tools ──

    async def _get_market_data(self, ctx: RunContext[AgentDeps], token_id: str) -> dict:
        return {"token_id": token_id, "status": "mock_data", "mid_price": 0.50}

    async def _get_portfolio_state(self, ctx: RunContext[AgentDeps]) -> dict:
        ledger = ctx.deps.ledger
        return {"balance": getattr(ledger, "get_balance", lambda: 0)(), "status": "ok"}

    async def _get_technical_indicators(self, ctx: RunContext[AgentDeps], token_id: str) -> dict:
        return {"token_id": token_id, "rsi": 50, "status": "mock_indicators"}

    async def _get_risk_metrics(self, ctx: RunContext[AgentDeps]) -> dict:
        risk = ctx.deps.risk
        return {"var": 0.05, "max_position": 1000, "status": "ok"}

    async def _get_orderbook(self, ctx: RunContext[AgentDeps], token_id: str) -> dict:
        return {"token_id": token_id, "bids": [], "asks": [], "mid": 0.50}

    # ── internal ──

    def _make_agent(
        self,
        name: str,
        model: str,
        result_type: type,
        instructions: str,
        tools: list,
    ) -> Agent:
        if name in self._agents:
            return self._agents[name]
        agent = Agent(
            model,
            deps_type=AgentDeps,
            result_type=result_type,
            system_prompt=instructions,
        )
        for tool_fn in tools:
            agent.tool()(tool_fn)
        self._agents[name] = agent
        return agent
