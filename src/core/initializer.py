from __future__ import annotations

from core.container import ServiceContainer
from core.runtime_context import RuntimeContext
from core.service_factory import build_runtime_services
from core.factories import build_access_control, build_copy_trading_agent, build_cognitive_brain


def prepare_runtime_context(execution_mode: str) -> RuntimeContext:
    container = ServiceContainer.get_instance()
    services = build_runtime_services(container, execution_mode)
    access_control, chat_id = build_access_control(services["secrets"], execution_mode)
    copy_trading_agent = build_copy_trading_agent(risk_engine=services["risk"])
    training_pipeline = services["training_pipeline"]
    market_scanner = services["market_scanner"]
    snapshot_mgr = services["snapshot_mgr"]
    model_validator = services["model_validator"]
    self_improver = services["self_improver"]
    cognitive_brain = build_cognitive_brain(
        store=services["store"],
        market_scanner=market_scanner,
        training_pipeline=training_pipeline,
    )
    lobstar = None
    if services["secrets"].get("GROQ_API_KEY"):
        from mcp_agents.lobstar_agent import LobstarAgent
        lobstar = LobstarAgent(api_key=services["secrets"]["GROQ_API_KEY"])
    return RuntimeContext(
        notifier=services["notifier"],
        secrets=services["secrets"],
        access_control=access_control,
        chat_id=chat_id,
        ledger=services["ledger"],
        freqai=services["freqai"],
        hmm=services["hmm"],
        risk=services["risk"],
        store=services["store"],
        passive_executor=services["passive_executor"],
        lobstar=lobstar,
        circuit_breaker=services["circuit_breaker"],
        market_scanner=market_scanner,
        cognitive_brain=cognitive_brain,
        copy_trading_agent=copy_trading_agent,
        training_pipeline=training_pipeline,
        snapshot_mgr=snapshot_mgr,
        model_validator=model_validator,
        self_improver=self_improver,
    )
