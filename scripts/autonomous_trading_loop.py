from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.autonomous_trading_loop import AutonomousTradingConfig, AutonomousTradingLoop
from core.autonomous_mode_controller import AutonomousModeController
from core.strategy_lifecycle_manager import StrategyLifecycleManager, StrategyPhase
from database.ledger_db import Ledger
from utils.config_loader import get_trading_config


def load_features_jsonl(path: str) -> list[dict[str, Any]]:
    feature_path = Path(path)
    if not feature_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in feature_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


async def run_once(
    features_path: str | None = None,
    paper_enable_backtest: bool = False,
    bootstrap_paper_trades: int = 0,
) -> None:
    ledger = Ledger()
    lifecycle = StrategyLifecycleManager()
    if paper_enable_backtest:
        # Manual dry-run override. Real eligibility still requires lifecycle gates.
        for state in lifecycle.states.values():
            if state.phase == StrategyPhase.BACKTEST:
                state.phase = StrategyPhase.PAPER
        lifecycle.persist_state()

    decision = AutonomousModeController(ledger, lifecycle).apply()
    print(json.dumps({"mode": decision.mode, "reason": decision.reason, "profit_directive": decision.profit_directive}, sort_keys=True))

    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(mode=ledger.get_execution_mode()),
    )
    features = load_features_jsonl(features_path) if features_path else []
    if bootstrap_paper_trades > 0:
        bootstrap_actions = await loop.bootstrap_paper_history(features, target_trades=bootstrap_paper_trades)
        for action in bootstrap_actions:
            print(json.dumps(action.__dict__, sort_keys=True))
        decision = loop.mode_controller.apply()
        print(json.dumps({
            "mode": decision.mode,
            "reason": decision.reason,
            "profit_directive": decision.profit_directive,
            "shadow_ready": decision.shadow_ready,
            "real_ready": decision.real_ready,
        }, sort_keys=True))
    actions = await loop.run_once(features)
    for action in actions:
        print(json.dumps(action.__dict__, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run autonomous Polymarket strategy loop")
    parser.add_argument("--once", action="store_true", help="Run one pass and exit")
    parser.add_argument(
        "--features-jsonl",
        default=str(get_trading_config("autonomous_features_jsonl", "", allow_env=False)),
    )
    parser.add_argument(
        "--paper-enable-backtest",
        action="store_true",
        help="Dry-run override: allow BACKTEST strategies to open PAPER positions.",
    )
    parser.add_argument(
        "--bootstrap-paper-trades",
        type=int,
        default=int(get_trading_config("autonomous_bootstrap_paper_trades", 0, allow_env=False)),
        help="Create and close this many bootstrap paper trades before the main loop.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if not args.once:
        raise SystemExit("Use --once for now; daemon mode should be supervised explicitly via PM2 after paper validation.")
    asyncio.run(
        run_once(
            args.features_jsonl or None,
            paper_enable_backtest=args.paper_enable_backtest,
            bootstrap_paper_trades=args.bootstrap_paper_trades,
        )
    )


if __name__ == "__main__":
    main()
