# Superpowers Workflow Adaptation

This repository adapts the `obra/superpowers` agentic methodology and software engineering framework as a local operating pattern, rather than a vendored runtime dependency.

## What Was Adapted

- **Brainstorming / Design-First (`brainstorm`)**: Strictly clarify requirements, consider design alternatives, identify edge cases, and establish a clear specification before writing code.
- **Planning (`planning`)**: Decompose tasks into short, atomic 2-5 minute steps, each backed by a clear verification checkpoint.
- **Test-Driven Development (`tdd`)**: Enforce a strict Red-Green-Refactor TDD cycle where a failing unit test is written and run (Red) before the implementation code is added to satisfy it (Green), followed by clean refactoring.
- **Execution & Isolation (`execution`)**: Apply focused edits in isolation to prevent scope creep.
- **Code Review (`review`)**: Self-review changes against the specification, style guides, and codebase standards.
- **Branch Completion (`completion`)**: Execute the full test suite to guarantee regression control prior to workspace integration.

## Local Entry Points

- `config/superpowers.json`: Specification of phases, required outputs, and custom project guardrails.
- `core/services/superpowers_workflow.py`: Task packet builder and programmatic report verification engine.
- `docs/superpowers_workflow.md`: Detailed documentation and usage instructions.
- `tests/services/test_superpowers_workflow.py`: Unit tests validating task building and phase verification.

## Guardrails

- Protect secrets, private keys, raw Telegram data, and raw production logs from prompts.
- Do not execute trades directly from LLM-generated recommendations.
- All code changes must pass localized unit tests prior to main workspace integration.
- Maintain high modularity and separate concerns across all adapters.

## Minimal Usage

```python
from core.services.superpowers_workflow import SuperpowersWorkflow

workflow = SuperpowersWorkflow()
packet = workflow.build_task_packet(
    goal="Implement new SOL Polymarket feed adapter",
    specialist_id="superpowers_spec_pilot",
)
print(packet.as_dict())
```

## Report Verification

```python
from core.services.superpowers_workflow import SuperpowersWorkflow

workflow = SuperpowersWorkflow()
result = workflow.verify_report({
    "phase_outputs": {
        "brainstorm": {
            "requirements_agreed": "Yes, verified setup",
            "alternatives_considered": "Compared standard RPC vs fallback",
            "specification": "Implemented adapter interface"
        },
        "planning": {
            "step_breakdown": ["Step 1: Write test", "Step 2: Implement feed"],
            "verification_checkpoints": ["Test fails", "Test passes"]
        },
        "tdd": {
            "failing_test_written": "test_feed_failure.py",
            "failing_test_run_red": "Verified pytest fail on missing feed implementation",
            "test_passes_green": "Verified pytest success on implementation",
            "refactoring_done": "Refactored feed parser cleanly"
        },
        "execution": {
            "isolated_changes": ["utils/sol_feed.py", "tests/test_sol_feed.py"],
            "scope_creep_prevented": "No extra modules edited"
        },
        "review": {
            "spec_compliance_checked": "Verified against interface specification",
            "style_lint_verified": "Checked with pylint/py compile"
        },
        "completion": {
            "full_test_suite_passed": "Yes, all tests pass",
            "clean_git_status": "Clean git status on branch completion"
        }
    },
    "honored_guardrails": workflow.config["guardrails"]
})
assert result.ok
```

## Source

Reference project: `https://github.com/obra/superpowers`.
