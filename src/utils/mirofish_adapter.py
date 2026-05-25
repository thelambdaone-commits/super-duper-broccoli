import json
import os
from functools import lru_cache
from typing import Any

from utils.llm_council import _redact_secret_like_text


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")
MIROFISH_CONFIG_PATH = os.path.join(CONFIG_DIR, "mirofish.json")


@lru_cache(maxsize=1)
def load_mirofish_config(path: str = MIROFISH_CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _bounded_int(value: int | None, default: int, maximum: int) -> int:
    if value is None or value <= 0:
        return default
    return min(value, maximum)


def build_mirofish_simulation_plan(
    prediction_question: str,
    seed_materials: list[str] | None = None,
    rounds: int | None = None,
    agents: int | None = None,
    domain: str = "market_prediction",
) -> dict[str, Any]:
    config = load_mirofish_config()
    safe_question = _redact_secret_like_text(prediction_question.strip())
    safe_seeds = [
        _redact_secret_like_text(seed.strip())
        for seed in (seed_materials or [])
        if seed and seed.strip()
    ]
    round_count = _bounded_int(rounds, config.get("default_rounds", 12), config.get("max_rounds", 40))
    agent_count = _bounded_int(agents, config.get("default_agents", 24), config.get("max_agents", 120))

    return {
        "source": config.get("source"),
        "license_note": config.get("license_note"),
        "domain": domain,
        "prediction_question": safe_question,
        "seed_material_count": len(safe_seeds),
        "seed_material_previews": [seed[:500] for seed in safe_seeds[:8]],
        "rounds": round_count,
        "agents": agent_count,
        "agent_cohorts": config.get("agent_cohorts", []),
        "workflow": config.get("workflow", []),
        "simulation_contract": {
            "inputs": [
                "prediction_question",
                "seed_materials",
                "domain",
                "rounds",
                "agents",
            ],
            "outputs": [
                "scenario_branches",
                "emergent_consensus",
                "dissenting_paths",
                "confidence_drivers",
                "monitoring_indicators",
                "trade_guardrail_recommendations",
            ],
            "status": "planning_only",
        },
        "guardrails": config.get("guardrails", []),
    }


def build_mirofish_trading_research_brief(
    ticker: str,
    market_context: str,
    prediction_question: str = "",
    rounds: int | None = None,
    agents: int | None = None,
) -> dict[str, Any]:
    question = prediction_question or f"What plausible paths could affect {ticker} market probability?"
    seeds = [
        f"Ticker: {ticker}",
        market_context,
        "Execution context: Polymarket CLOB bot; simulation output is advisory and cannot place orders.",
    ]
    plan = build_mirofish_simulation_plan(
        prediction_question=question,
        seed_materials=seeds,
        rounds=rounds,
        agents=agents,
        domain="trading_research",
    )
    plan["ticker"] = ticker.upper().strip()
    plan["required_project_checks"] = [
        "Compare scenario output with HMM regime and Dissimilarity Index.",
        "Require portfolio_risk_engine sizing before any order.",
        "Require ledger validate_and_reserve before booking exposure.",
        "Keep PAPER/SHADOW mode unless production approval is explicit.",
    ]
    return plan
