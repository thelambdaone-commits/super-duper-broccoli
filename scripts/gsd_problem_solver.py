#!/usr/bin/env python3
"""
CLI Utility for running GSD Autonomous Problem Solver Agent.
Allows auto-solving bugs and coding tasks in the workspace with GSD phase gates.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.services.gsd_problem_solver import GSDProblemSolverAgent


# Terminal coloring helpers
def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


async def main():
    parser = argparse.ArgumentParser(
        description="GSD Autonomous Problem Solver CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--issue",
        required=True,
        help="Description of the bug or problem to solve automatically.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run intake and planning stages without making actual file changes.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum loop iterations for making fixes and running tests.",
    )

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print(bold(cyan("🚀 GSD AUTONOMOUS PROBLEM SOLVER ENGINE")))
    print("=" * 80)
    print(f"🎯 {bold('Target Issue')}: '{args.issue}'")
    print(f"⚙️  {bold('Dry-Run')}: {args.dry_run}")
    print(f"🔄 {bold('Max Iterations')}: {args.max_iterations}")
    print("=" * 80 + "\n")

    solver = GSDProblemSolverAgent()

    try:
        report = await solver.solve_issue(
            issue_text=args.issue,
            dry_run=args.dry_run,
            max_iterations=args.max_iterations,
        )

        print("\n" + "=" * 80)
        print(bold(cyan("📊 RESOLUTION PROCESS COMPLETE")))
        print("=" * 80)

        # 1. Intake phase output
        intake = report.phases.get("intake", {})
        print(f"\n📋 {bold('PHASE A: Intake Spec Summary')}")
        print(f"  • {bold('Goal')}: {intake.get('goal')}")
        print(f"  • {bold('Scope')}: {', '.join(intake.get('scope', []))}")
        print(f"  • {bold('Non-Goals')}: {', '.join(intake.get('non_goals', []))}")

        # 2. Context phase output
        context = report.phases.get("context", {})
        print(f"\n🔍 {bold('PHASE B: Codebase Context Discovery')}")
        print(f"  • {bold('Selected Target Files')}: {yellow(', '.join(context.get('priority_files', [])))}")
        print(f"  • {bold('External Framework References')}: {', '.join(context.get('external_sources', []))}")

        # 3. Implementation and verification outcome
        print(f"\n🛠️  {bold('PHASE C & D: Code Modification & Verification')}")
        if report.changed_files:
            print(f"  • {bold('Modified Files')}: {green(', '.join(report.changed_files))}")
        else:
            print(f"  • {bold('Modified Files')}: None")

        if report.tests_run:
            print(f"  • {bold('Executed Test Suite')}: {', '.join(report.tests_run)}")
            print(f"  • {bold('Pytest Outcome')}: " + (green("SUCCESS (All tests passed) ✅") if report.ok else red("FAILURE (Verification failed) ❌")))
        else:
            print(f"  • {bold('Pytest Outcome')}: Skipped / Dry-run")

        print(f"  • {bold('Residual Risks')}: {report.residual_risks}")

        # 4. Handoff summary
        handoff = report.phases.get("handoff", {})
        print(f"\n📤 {bold('PHASE E: GSD Operational Handoff')}")
        print(f"  • {bold('Summary')}: {handoff.get('summary')}")
        print(f"  • {bold('Next Recommended Commands')}:")
        for cmd in handoff.get("next_commands", []):
            print(f"    - `{cmd}`")

        print("\n" + "=" * 80)
        status_str = green("🟢 SUCCESS — RESOLVED AND VERIFIED") if report.ok else red("🔴 FAILED — UNABLE TO VERIFY SAFE FIX")
        print(bold(f"STATUS: {status_str}"))
        print(bold(cyan("Report saved to: user_data/reports/gsd_issue_resolver_report.md")))
        print("=" * 80 + "\n")

        sys.exit(0 if report.ok else 1)

    except KeyboardInterrupt:
        print(bold(yellow("\n\n⚠️ Execution cancelled by operator.")))
        sys.exit(130)
    except Exception as e:
        print(bold(red(f"\n\n❌ Unexpected solver exception: {e}")))
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
