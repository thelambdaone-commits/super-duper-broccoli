from __future__ import annotations

import os
from typing import Any

from bootstrap.helpers import check_rpc_dry_run


async def dry_run_report(
    mode: str,
    circuit_breaker: Any,
    store: Any,
    *,
    logger: Any,
    secrets: dict[str, str],
    vault: Any,
    freqai: Any,
    ledger: Any,
    hmm: Any,
    risk: Any,
    executor: Any,
) -> None:
    if logger is None:
        import logging

        logger = logging.getLogger(__name__)

    logger.info("=== DRY RUN MODE ===")
    component_status: dict[str, bool] = {}

    def _mark(component: str, ok: bool) -> None:
        component_status[component] = ok

    try:
        vault_secrets = secrets or {}
        vault_count = len(vault_secrets)
        required_secrets = ["TELEGRAM_BOT_TOKEN", "CLOB_PRIVATE_KEY"]
        missing_secrets = [s for s in required_secrets if not vault_secrets.get(s)]
        _mark("vault", vault_count > 0 and not missing_secrets)
        session_wallet_count = vault.compter_wallets_session()
        logger.info(f"Vault RAM session wallets state: {session_wallet_count} active session wallets in memory.")
    except Exception as e:
        logger.info(f"Vault Check: ERROR ({e})")

    rpc_url = secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL")
    if rpc_url:
        try:
            res = await check_rpc_dry_run(rpc_url)
            logger.info(f"Alchemy RPC Connectivity: {'OK' if 'result' in res else 'FAILED'}")
        except Exception as e:
            logger.warning(f"Alchemy RPC Connectivity: FAILED ({e})")

    try:
        freqai_status = "OK" if freqai else "MISSING"
        if freqai:
            mid = await freqai.get_midpoint("SOL")
            freqai_status = "OK" if mid and mid > 0 else "DEGRADED"
    except Exception as e:
        logger.info(f"CLOB Engine: ERROR ({e})")
        freqai_status = "FAILED"
    _mark("freqai", freqai_status in {"OK", "DEGRADED"})

    try:
        ledger_status = "OK" if ledger else "MISSING"
        if ledger:
            summary = ledger.get_capital_summary()
            balance = summary.get("available_capital", 0.0)
            positions = ledger.get_open_positions()
            logger.info(f"Ledger: OK (Balance: ${balance:.2f}, Positions: {len(positions)})")
            ledger_status = "OK"
    except Exception as e:
        logger.info(f"Ledger: ERROR ({e})")
        ledger_status = "FAILED"
    _mark("ledger", ledger_status in {"OK", "DEGRADED"})

    try:
        hmm_status = "OK" if hmm else "MISSING"
        if hmm:
            regimes = hmm.get_regime_labels()
            hmm_status = "OK" if regimes else "DEGRADED"
    except Exception as e:
        logger.info(f"HMMRegimeFilter: ERROR ({e})")
        hmm_status = "FAILED"
    _mark("hmm", hmm_status in {"OK", "DEGRADED"})

    try:
        risk_status = "OK" if risk else "MISSING"
        if risk:
            max_size = risk.calculate_max_position_size("SOL", 100.0)
            concentration = risk.get_concentration("SOL")
            logger.info(f"PortfolioRiskEngine: OK (Max size: ${max_size:.2f}, Concentration: {concentration:.1%})")
            risk_status = "OK"
    except Exception as e:
        logger.info(f"PortfolioRiskEngine: ERROR ({e})")
        risk_status = "FAILED"
    _mark("risk", risk_status in {"OK", "DEGRADED"})

    try:
        executor_status = "OK" if executor else "MISSING"
        if executor:
            timeout = getattr(executor, "timeout", 30)
            queue_size = getattr(executor, "queue_size", 0)
            logger.info(f"PassiveExecutor: OK (Timeout: {timeout}s, Queue: {queue_size})")
    except Exception as e:
        logger.info(f"PassiveExecutor: ERROR ({e})")
        executor_status = "FAILED"
    _mark("executor", executor_status == "OK")

    try:
        cb_status = circuit_breaker.status_report
        cb_allowed = circuit_breaker.is_allowed()
        logger.info(f"CircuitBreaker: {cb_status} (Allowed: {cb_allowed})")
    except Exception as e:
        logger.info(f"CircuitBreaker: ERROR ({e})")

    try:
        store_stats = store.get_stats() if store else "N/A"
        logger.info(f"FeatureStore: OK ({store_stats})")
    except Exception as e:
        logger.info(f"FeatureStore: PARTIAL ({e})")

    logger.info(f"Execution Mode: {mode}")
    logger.info("Telegram Bot: SKIPPED (dry-run)")

    if all(component_status.values()):
        logger.info("✅ Pipeline validated successfully. All core components operational.")
    else:
        failed_components = [k for k, v in component_status.items() if not v]
        logger.warning(f"⚠️ Pipeline has {len(failed_components)} failed components: {', '.join(failed_components)}")

    logger.info(f"Active mode: {mode} — {'Virtual' if mode in ('REPLAY', 'PAPER') else 'Real capital at risk.'}")
