# GSD Workflow Adaptation

This repository adapts `gsd-build/get-shit-done` as a local operating pattern, not as a vendored runtime dependency.

## What Was Adapted

- Spec-driven task intake.
- Compact context packets to reduce context rot.
- Phase gates: intake, context, implementation, verification, handoff.
- Verification-first final handoff.
- External-project fusion through adapters and context cards.

## Local Entry Points

- `config/gsd_operating_system.json`: phase gates, guardrails, context budget, and durable artifact paths.
- `.agents/gsd_execution_skill.md`: agent-facing execution rules.
- `core/services/gsd_workflow.py`: deterministic task packet builder and report verifier.
- `config/project_contexts.json`: durable external-project context card.

## Guardrails

- No secrets, private keys, raw Telegram data, encrypted wallet data, or runtime logs in external prompts.
- No direct trading execution from agent text.
- Risk engine, ledger reserve, HMM regime, and `MODE` remain the source of truth.
- Prefer local adapters and context cards over vendoring external framework code.
- Every workflow adapter must have focused tests or an explicit residual-risk note.

## Minimal Usage

```python
from core.services.gsd_workflow import GSDWorkflow

workflow = GSDWorkflow()
packet = workflow.build_task_packet(
    goal="Add fast Polymarket wallet reconciliation",
    specialist_id="project_fusion_architect",
)
print(packet.as_dict())
```

## Report Verification

```python
from core.services.gsd_workflow import GSDWorkflow

workflow = GSDWorkflow()
result = workflow.verify_report({
    "phase_outputs": {
        "intake": {"goal": "...", "scope": "...", "non_goals": "..."},
        "context": {"priority_files": ["..."], "external_sources": ["..."], "license_notes": "..."},
        "implementation": {"changed_files": ["..."], "behavior_change": "..."},
        "verification": {"tests_run": ["pytest ..."], "residual_risks": "none"},
        "handoff": {"summary": "...", "next_commands": ["..."]}
    },
    "honored_guardrails": workflow.config["guardrails"]
})
assert result.ok
```

## Autonomous Problem Solving Agent

The repository features a fully integrated **GSD Autonomous Problem Solver Agent** inspired by frameworks like `AI-Problem-Solver`, OpenClaw's `github-issue-resolver`, and Haystack's `github_issue_resolver_agent`. It takes any bug description or feature ticket, parses the GSD spec, semantically selects relevant files, plans modifications, applies them, executes `pytest` tests, and automatically rolls back changes if validation checks fail.

### CLI Usage

Execute the solver directly in your terminal to fix any issue autonomously:

```bash
# Run intake and planning without changing any files (Dry-Run)
python scripts/gsd_problem_solver.py --issue "Fix timing delay in binance websocket client" --dry-run

# Run full autonomous loop with up to 3 iterative attempts and test verification
python scripts/gsd_problem_solver.py --issue "Fix formatting anomalies in Telegram logger" --max-iterations 3
```

### Python API

```python
import asyncio
from core.services.gsd_problem_solver import GSDProblemSolverAgent

async def run_solver():
    solver = GSDProblemSolverAgent()
    report = await solver.solve_issue(
        issue_text="Fix formatting anomalies in Telegram logger",
        dry_run=False
    )
    if report.ok:
        print("Issue resolved and validated!")
        print("Changed files:", report.changed_files)
    else:
        print("Failed to resolve safely. State rolled back.")

asyncio.run(run_solver())
```

## Source

Reference project: `https://github.com/gsd-build/get-shit-done`.
