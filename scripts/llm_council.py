#!/usr/bin/env python
"""Run or inspect the local LLM Council integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm_council import LLMCouncil


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Council via OpenRouter.")
    parser.add_argument("question", help="Question to send to the council.")
    parser.add_argument("--max-models", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the council plan without calling external LLMs.",
    )
    args = parser.parse_args()

    council = LLMCouncil()
    if args.dry_run:
        print(json.dumps(council.build_plan(args.question, args.max_models), indent=2))
        return 0

    result = __import__("asyncio").run(council.ask(args.question, args.max_models))
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
