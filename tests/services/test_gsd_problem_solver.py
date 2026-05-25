from __future__ import annotations

import pytest

from services.gsd_problem_solver import GSDProblemSolverAgent


def test_gsd_solver_agent_initialization() -> None:
    """Verifies that the GSD solver agent can be instantiated successfully."""
    agent = GSDProblemSolverAgent()
    assert agent.workspace_path.exists()
    assert agent.workflow is not None


@pytest.mark.asyncio
async def test_gsd_solver_intake_phase() -> None:
    """Verifies that the intake phase successfully parses goals and scopes from issue description."""
    agent = GSDProblemSolverAgent()
    intake = await agent._run_intake_phase("Fix timing delay in binance websocket client")

    assert "goal" in intake
    assert "scope" in intake
    assert "non_goals" in intake
    assert len(intake["scope"]) > 0


@pytest.mark.asyncio
async def test_gsd_solver_context_phase() -> None:
    """Verifies that the context phase identifies files and handles license notes correctly."""
    agent = GSDProblemSolverAgent()
    packet = agent.workflow.build_task_packet(goal="Fix timing delay in binance websocket client")
    context = await agent._run_context_phase(packet, "Fix timing delay in binance websocket client")

    assert "priority_files" in context
    assert "external_sources" in context
    assert "license_notes" in context


def test_gsd_solver_guardrails_sensitive_files() -> None:
    """Verifies that sensitive patterns like vault, .env, or keys are excluded from AI modifications."""
    agent = GSDProblemSolverAgent()
    candidates = [
        "utils/vault_handler.py",
        "src/services/gsd_workflow.py",
        "config/.env",
        "core/portfolio_risk_engine.py",
    ]
    safe_files = agent._filter_sensitive_files(candidates)

    assert "src/services/gsd_workflow.py" in safe_files
    assert "utils/vault_handler.py" not in safe_files
    assert "config/.env" not in safe_files
    assert "core/portfolio_risk_engine.py" not in safe_files


def test_gsd_solver_backup_and_restore() -> None:
    """Verifies that the agent can successfully back up and restore modified files in memory."""
    agent = GSDProblemSolverAgent()
    target_file = "src/services/gsd_workflow.py"
    full_path = agent.workspace_path / target_file

    with open(full_path, "r", encoding="utf-8") as handle:
        original_content = handle.read()

    # Step 1: Backup
    backups = agent._backup_files([target_file])
    assert target_file in backups
    assert backups[target_file] == original_content

    # Step 2: Modify
    with open(full_path, "w", encoding="utf-8") as handle:
        handle.write("Modified content for test")

    # Step 3: Restore
    agent._restore_backups(backups)
    with open(full_path, "r", encoding="utf-8") as handle:
        restored_content = handle.read()

    assert restored_content == original_content


@pytest.mark.asyncio
async def test_gsd_solver_dry_run() -> None:
    """Verifies that a dry run completes successfully without writing changes or running tests."""
    agent = GSDProblemSolverAgent()
    report = await agent.solve_issue(
        issue_text="Fix timing delay in binance websocket client",
        dry_run=True,
    )

    assert report.ok
    assert "intake" in report.phases
    assert "context" in report.phases
    assert "implementation" in report.phases
    assert "verification" in report.phases
    assert report.changed_files == []
    assert report.tests_run == []
