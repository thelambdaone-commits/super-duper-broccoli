from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_lifecycle_manager import StrategyLifecycleManager, StrategyPhase
from utils.config_loader import get_trading_config

logger = logging.getLogger("ReinforcementOptimizationLoop")


def optimize_once(manager: StrategyLifecycleManager) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for strategy_id, state in manager.states.items():
        strategy = manager.strategies[strategy_id]

        if state.phase == StrategyPhase.REAL and state.paper.consecutive_losses >= manager.config.max_consecutive_losses:
            manager.demote(strategy_id, "Circuit breaker: 3 consecutive losses in real/paper telemetry")
            continue

        if state.paper.max_slippage > manager.config.max_paper_slippage:
            new_edge = min(0.25, strategy.parameters.min_edge * 1.10 + 0.002)
            mutations.append(
                manager.apply_mutation(
                    strategy_id,
                    {"min_edge": round(new_edge, 6)},
                    "Slippage exceeded gate; increasing activation edge",
                )
            )

        if state.paper.trade_count >= 3 and state.paper.total_profit < 0:
            new_conf = min(0.95, strategy.parameters.min_confidence + 0.03)
            new_batch = max(1, int(strategy.parameters.batch_size * 0.75))
            mutations.append(
                manager.apply_mutation(
                    strategy_id,
                    {"min_confidence": round(new_conf, 6), "batch_size": new_batch},
                    "Live/Paper underperformance; tightening confidence and reducing batch size",
                )
            )
    return mutations


def load_synthetic_paper_events(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    event_path = Path(path)
    if not event_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in event_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid paper event line: %s", line[:120])
    return events


def run_loop(interval_seconds: float = 3600.0, once: bool = False, paper_events_path: str | None = None) -> None:
    manager = StrategyLifecycleManager()
    for event in load_synthetic_paper_events(paper_events_path):
        strategy_id = str(event.get("strategy_id", ""))
        if strategy_id in manager.states:
            manager.record_paper_result(
                strategy_id=strategy_id,
                pnl=float(event.get("pnl", 0.0) or 0.0),
                slippage=float(event.get("slippage", 0.0) or 0.0),
                rejected=bool(event.get("rejected", False)),
            )

    while True:
        mutations = optimize_once(manager)
        manager.persist_state()
        manager.write_dashboard()
        logger.info("Optimization pass complete. mutations=%s", len(mutations))
        if once:
            return
        time.sleep(max(60.0, interval_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-improving strategy optimization loop")
    parser.add_argument("--once", action="store_true", help="Run one optimization pass and exit")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(get_trading_config("strategy_opt_interval_seconds", 3600.0, allow_env=False)),
    )
    parser.add_argument(
        "--paper-events",
        default=str(get_trading_config("strategy_paper_events_jsonl", "", allow_env=False)),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_loop(interval_seconds=args.interval_seconds, once=args.once, paper_events_path=args.paper_events or None)


if __name__ == "__main__":
    main()
