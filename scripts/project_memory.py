import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.prompt_memory import (  # noqa: E402
    build_project_prompt_context,
    format_project_prompt_context,
    list_project_memory,
    record_project_memory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Project prompt memory helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    context_parser = subparsers.add_parser("context", help="Build compact prompt context.")
    context_parser.add_argument("--task", default="")
    context_parser.add_argument("--specialist-id", default="")
    context_parser.add_argument("--component", default="")
    context_parser.add_argument("--token-budget", type=int, default=2500)
    context_parser.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list", help="List project memory entries.")
    list_parser.add_argument("--component", default="")
    list_parser.add_argument("--tag", default="")
    list_parser.add_argument("--limit", type=int, default=10)

    record_parser = subparsers.add_parser("record", help="Record a compact memory entry.")
    record_parser.add_argument("component")
    record_parser.add_argument("summary")
    record_parser.add_argument("--kind", default="note")
    record_parser.add_argument("--tag", action="append", default=[])
    record_parser.add_argument("--details", default="")
    record_parser.add_argument("--source", default="cli")

    args = parser.parse_args()

    if args.command == "context":
        context = build_project_prompt_context(
            task=args.task,
            specialist_id=args.specialist_id,
            component=args.component,
            token_budget=args.token_budget,
        )
        if args.json:
            print(json.dumps(context, indent=2, ensure_ascii=True))
        else:
            print(format_project_prompt_context(context))
        return 0

    if args.command == "list":
        print(json.dumps(
            list_project_memory(component=args.component, tag=args.tag, limit=args.limit),
            indent=2,
            ensure_ascii=True,
        ))
        return 0

    if args.command == "record":
        entry = record_project_memory(
            component=args.component,
            summary=args.summary,
            kind=args.kind,
            tags=args.tag,
            details=args.details,
            source=args.source,
        )
        print(json.dumps(entry, indent=2, ensure_ascii=True))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
