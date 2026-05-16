#!/usr/bin/env python
"""Build a local MiroFish-style swarm simulation plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.mirofish_adapter import build_mirofish_simulation_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="MiroFish-style simulation planning adapter.")
    parser.add_argument("question", help="Prediction question to simulate.")
    parser.add_argument("--seed", action="append", default=[], help="Seed material text. Repeatable.")
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--agents", type=int, default=None)
    parser.add_argument("--domain", default="market_prediction")
    args = parser.parse_args()

    plan = build_mirofish_simulation_plan(
        prediction_question=args.question,
        seed_materials=args.seed,
        rounds=args.rounds,
        agents=args.agents,
        domain=args.domain,
    )
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
