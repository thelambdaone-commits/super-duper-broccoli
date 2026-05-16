from utils.mirofish_adapter import (
    build_mirofish_simulation_plan,
    build_mirofish_trading_research_brief,
    load_mirofish_config,
)


def test_mirofish_config_loads_guardrails():
    config = load_mirofish_config()

    assert config["source"] == "https://github.com/666ghj/MiroFish"
    assert config["max_rounds"] >= config["default_rounds"]
    assert config["guardrails"]


def test_mirofish_plan_bounds_counts_and_redacts_seed_materials():
    plan = build_mirofish_simulation_plan(
        prediction_question="Will this market move after sk-or-secret?",
        seed_materials=["raw key gsk_secretvalue", "policy draft"],
        rounds=999,
        agents=999,
    )

    assert plan["rounds"] == load_mirofish_config()["max_rounds"]
    assert plan["agents"] == load_mirofish_config()["max_agents"]
    assert "sk-or-[REDACTED]" in plan["prediction_question"]
    assert "secretvalue" not in " ".join(plan["seed_material_previews"])
    assert plan["simulation_contract"]["status"] == "planning_only"


def test_mirofish_trading_brief_adds_project_checks():
    brief = build_mirofish_trading_research_brief(
        ticker="sol",
        market_context="Liquidity thin; social attention rising.",
        rounds=4,
        agents=8,
    )

    assert brief["ticker"] == "SOL"
    assert brief["domain"] == "trading_research"
    assert brief["rounds"] == 4
    assert brief["agents"] == 8
    assert any("portfolio_risk_engine" in check for check in brief["required_project_checks"])
