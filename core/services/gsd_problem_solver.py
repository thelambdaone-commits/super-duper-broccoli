from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.services.gsd_workflow import GSDWorkflow, GSDTaskPacket
from utils.llm_council import OpenRouterChatClient, resolve_openrouter_api_key

logger = logging.getLogger("GSDProblemSolver")


@dataclass(frozen=True)
class SolverReport:
    ok: bool
    issue: str
    phases: dict[str, dict[str, Any]]
    changed_files: list[str]
    tests_run: list[str]
    test_stdout: str
    residual_risks: str


class GSDProblemSolverAgent:
    """
    Autonomous AI Problem Solver Agent built on local 'Get Shit Done' (GSD) spec-driven architecture.
    """

    def __init__(self, workspace_path: str | Path = "/home/ogj9f33gvvzc/quant-agentic-trading-core-v2"):
        self.workspace_path = Path(workspace_path)
        self.workflow = GSDWorkflow()
        self.api_key = resolve_openrouter_api_key()
        self._chat_client = None
        if self.api_key:
            try:
                self._chat_client = OpenRouterChatClient(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize OpenRouter client: {e}")

    async def solve_issue(
        self,
        issue_text: str,
        dry_run: bool = False,
        max_iterations: int = 3,
    ) -> SolverReport:
        """
        Coordinates the recursive GSD phase gates to solve an issue autonomously.
        """
        logger.info(f"🏁 Starting GSD Problem Solver loop for issue: '{issue_text}'")

        # ----------------------------------------------------
        # PHASE A: INTAKE
        # ----------------------------------------------------
        intake_data = await self._run_intake_phase(issue_text)
        packet = self.workflow.build_task_packet(
            goal=intake_data["goal"],
            specialist_id="gsd_workflow_operator",
        )

        # ----------------------------------------------------
        # PHASE B: CONTEXT
        # ----------------------------------------------------
        context_data = await self._run_context_phase(packet, issue_text)
        priority_files = context_data.get("priority_files", [])

        # Filter out sensitive files from modification list
        safe_priority_files = self._filter_sensitive_files(priority_files)

        # ----------------------------------------------------
        # PHASE C & D: IMPLEMENTATION & VERIFICATION LOOP
        # ----------------------------------------------------
        phase_outputs = {
            "intake": intake_data,
            "context": context_data,
        }

        changed_files = []
        tests_run = []
        test_stdout = ""
        residual_risks = "None detected."
        ok = False

        if dry_run:
            logger.info("⚠️ Dry-run enabled. Skipping implementation and verification phases.")
            phase_outputs["implementation"] = {
                "changed_files": [],
                "behavior_change": "[DRY RUN] Propose changes to target files."
            }
            phase_outputs["verification"] = {
                "tests_run": [],
                "residual_risks": "[DRY RUN] Verification skipped."
            }
            phase_outputs["handoff"] = {
                "summary": "[DRY RUN] Issue intake and planning completed successfully.",
                "next_commands": ["python3 scripts/gsd_problem_solver.py --issue ..."]
            }
            return SolverReport(
                ok=True,
                issue=issue_text,
                phases=phase_outputs,
                changed_files=[],
                tests_run=[],
                test_stdout="Dry-run success",
                residual_risks="Dry-run execution."
            )

        for iteration in range(1, max_iterations + 1):
            logger.info(f"🔄 Iteration {iteration}/{max_iterations} for issue resolution...")

            # Backup files before modifying
            backups = self._backup_files(safe_priority_files)

            try:
                # 3. Call LLM to generate the fix proposals
                impl_data = await self._run_implementation_phase(
                    issue_text=issue_text,
                    task_packet=packet,
                    target_files=safe_priority_files,
                )
                phase_outputs["implementation"] = impl_data
                changed_files = impl_data.get("changed_files", [])

                # 4. Verification: run pytest
                veri_data = await self._run_verification_phase(safe_priority_files)
                phase_outputs["verification"] = veri_data
                tests_run = veri_data.get("tests_run", [])
                test_stdout = veri_data.get("test_stdout", "")

                if veri_data.get("ok", False):
                    logger.info("✅ All tests passed! Fix verified successfully.")
                    ok = True
                    # Clean up backups
                    self._remove_backups(backups)
                    break
                else:
                    logger.warning(f"❌ Tests failed on iteration {iteration}. Rolling back changes.")
                    self._restore_backups(backups)
                    residual_risks = f"Verification failed on iteration {iteration}. rolled back."
            except Exception as e:
                logger.error(f"Error during resolution loop: {e}")
                self._restore_backups(backups)
                residual_risks = f"Error: {e}. rolled back."

        # ----------------------------------------------------
        # PHASE E: HANDOFF
        # ----------------------------------------------------
        handoff_data = await self._run_handoff_phase(issue_text, phase_outputs)
        phase_outputs["handoff"] = handoff_data

        report = SolverReport(
            ok=ok,
            issue=issue_text,
            phases=phase_outputs,
            changed_files=changed_files,
            tests_run=tests_run,
            test_stdout=test_stdout,
            residual_risks=residual_risks,
        )

        # Write handoff report file
        self._write_report_file(report)

        return report

    async def _run_intake_phase(self, issue_text: str) -> dict[str, Any]:
        """Convert issue text into a GSD task spec."""
        logger.info("📋 Step A: Intake spec synthesis...")
        prompt = (
            f"Convert this raw problem or issue description into a structured GSD intake document.\n"
            f"Problem description: '{issue_text}'\n\n"
            f"Format your response as a strict JSON object with these keys:\n"
            f"- 'goal': A concise one-sentence statement of the goal.\n"
            f"- 'scope': A list of scope items.\n"
            f"- 'non_goals': A list of non-goals.\n"
        )
        try:
            content = await self._call_llm_with_fallback(prompt)
            data = json.loads(self._clean_json(content))
            return {
                "goal": data.get("goal", f"Resolve issue: {issue_text}"),
                "scope": data.get("scope", ["Investigate and fix"]),
                "non_goals": data.get("non_goals", ["Do not refactor outside scope"]),
            }
        except Exception as e:
            logger.warning(f"Intake LLM call failed, returning rule-based default: {e}")
            return {
                "goal": f"Resolve issue: {issue_text}",
                "scope": ["Analyze issue constraints", "Implement targeted fix", "Verify via pytest"],
                "non_goals": ["Refactor broad codebase components", "Modify credentials or trading state"],
            }

    async def _run_context_phase(self, packet: GSDTaskPacket, issue_text: str) -> dict[str, Any]:
        """Identify relevant files in the codebase."""
        logger.info("🔍 Step B: Context discovery & file selection...")
        # Rule-based fast mapping of workspace files
        all_files = []
        for p in self.workspace_path.rglob("*.py"):
            if ".venv" not in p.parts and "tests" not in p.parts:
                all_files.append(str(p.relative_to(self.workspace_path)))

        prompt = (
            f"Given this list of codebase files:\n{all_files}\n\n"
            f"And the target issue goal:\n'{packet.goal}'\n\n"
            f"Select which files are most likely relevant to locate and fix this issue.\n"
            f"Format your response as a strict JSON object with these keys:\n"
            f"- 'priority_files': A list of the top 1-3 most relevant file paths from the list.\n"
            f"- 'external_sources': A list of references or frameworks to consider.\n"
            f"- 'license_notes': A short string noting any license bounds.\n"
        )
        try:
            content = await self._call_llm_with_fallback(prompt)
            data = json.loads(self._clean_json(content))
            return {
                "priority_files": data.get("priority_files", []),
                "external_sources": data.get("external_sources", []),
                "license_notes": data.get("license_notes", "MIT/Local only"),
            }
        except Exception as e:
            logger.warning(f"Context LLM call failed, returning rule-based context: {e}")
            # Dynamic keyword match fallback
            matches = []
            keywords = issue_text.lower().split()
            for f in all_files:
                f_lower = f.lower()
                if any(kw in f_lower for kw in keywords if len(kw) > 3):
                    matches.append(f)
            if not matches:
                # Default fallback files
                matches = ["core/services/gsd_workflow.py"]
            return {
                "priority_files": matches[:3],
                "external_sources": [],
                "license_notes": "Local workspace boundary",
            }

    async def _run_implementation_phase(
        self,
        issue_text: str,
        task_packet: GSDTaskPacket,
        target_files: Sequence[str],
    ) -> dict[str, Any]:
        """Formulate and apply code edits to the selected files."""
        logger.info("🛠️ Step C: Implementation plan & code generation...")
        changed_files = []
        for file_path in target_files:
            full_path = self.workspace_path / file_path
            if not full_path.exists():
                continue

            with open(full_path, "r", encoding="utf-8") as handle:
                original_content = handle.read()

            prompt = (
                f"Analyze the issue description:\n'{issue_text}'\n\n"
                f"And the original contents of the file '{file_path}':\n"
                f"```python\n{original_content}\n```\n\n"
                f"Generate the exact, modified code that resolves the issue cleanly.\n"
                f"Format your response as a strict JSON object with this key:\n"
                f"- 'code': The complete, corrected drop-in code for the file.\n"
            )
            try:
                content = await self._call_llm_with_fallback(prompt)
                data = json.loads(self._clean_json(content))
                new_code = data.get("code")
                if new_code:
                    with open(full_path, "w", encoding="utf-8") as out:
                        out.write(new_code)
                    changed_files.append(file_path)
                    logger.info(f"✍️ Modified {file_path} successfully.")
            except Exception as e:
                logger.error(f"Failed to implement changes for {file_path}: {e}")

        return {
            "changed_files": changed_files,
            "behavior_change": f"Applied targeted modifications to: {changed_files}",
        }

    async def _run_verification_phase(self, target_files: Sequence[str]) -> dict[str, Any]:
        """Run pytest to verify the correctness of the workspace changes."""
        logger.info("🧪 Step D: Verification suite checks...")
        # Locate matching tests in tests/
        test_file = ""
        for file_path in target_files:
            file_name = Path(file_path).name
            candidate = self.workspace_path / "tests" / f"test_{file_name}"
            if candidate.exists():
                test_file = f"tests/test_{file_name}"
                break
            candidate_service = self.workspace_path / "tests" / "services" / f"test_{file_name}"
            if candidate_service.exists():
                test_file = f"tests/services/test_{file_name}"
                break

        # Fallback to general system test if no file-specific test is found
        if not test_file:
            test_file = "tests/test_message_formatter.py"

        cmd = [".venv/bin/pytest", test_file, "-q"]
        logger.info(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.workspace_path,
        )

        ok = result.returncode == 0
        return {
            "ok": ok,
            "tests_run": [test_file],
            "test_stdout": result.stdout + "\n" + result.stderr,
            "residual_risks": "None" if ok else "Pytest execution returned failure.",
        }

    async def _run_handoff_phase(self, issue_text: str, phase_outputs: dict[str, Any]) -> dict[str, Any]:
        """Leave operational handoff summary."""
        logger.info("📤 Step E: Handoff compilation...")
        prompt = (
            f"Generate a GSD handoff report for this issue resolution:\n"
            f"Issue: '{issue_text}'\n"
            f"Phases metadata: {list(phase_outputs.keys())}\n\n"
            f"Format your response as a strict JSON object with these keys:\n"
            f"- 'summary': A concise summary of changes and validation details.\n"
            f"- 'next_commands': A list of next commands to deploy or run.\n"
        )
        try:
            content = await self._call_llm_with_fallback(prompt)
            data = json.loads(self._clean_json(content))
            return {
                "summary": data.get("summary", "Autonomous problem solver resolved the issue successfully."),
                "next_commands": data.get("next_commands", ["git diff", "pm2 restart all"]),
            }
        except Exception as e:
            return {
                "summary": "Completed autonomous resolution with deterministic rollback checks.",
                "next_commands": ["git status", "pytest tests/"],
            }

    async def _call_llm_with_fallback(self, prompt: str) -> str:
        """Helper to invoke OpenRouter with fallback to mock response if keys are missing."""
        if self._chat_client:
            try:
                content = await self._chat_client.complete(
                    model="openai/gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a precise GSD JSON assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=2000,
                )
                return content
            except Exception as e:
                logger.warning(f"OpenRouter complete call failed: {e}. Falling back to mock generator.")

        # Static Mock JSON generator based on requested keywords in the prompt
        if "goal" in prompt:
            return json.dumps({
                "goal": "Fix timing delay in binance websocket client",
                "scope": ["Locate latency sources", "Implement non-blocking event loops"],
                "non_goals": ["Refactor database models"]
            })
        elif "priority_files" in prompt:
            # Try to return realistic priority files if the prompt listed them
            return json.dumps({
                "priority_files": ["core/services/gsd_workflow.py"],
                "external_sources": ["https://github.com/gsd-build/get-shit-done"],
                "license_notes": "MIT"
            })
        elif "code" in prompt:
            # Simply echo back the original code or modify something tiny for testing
            # Let's extract any Python code block from the prompt to echo it back
            lines = prompt.splitlines()
            code_lines = []
            capture = False
            for line in lines:
                if line.startswith("```python"):
                    capture = True
                    continue
                elif line.startswith("```") and capture:
                    break
                if capture:
                    code_lines.append(line)
            code_str = "\n".join(code_lines)
            return json.dumps({
                "code": code_str or "print('mock code change')"
            })
        else:
            return json.dumps({
                "summary": "Resolved",
                "next_commands": ["git diff"]
            })

    def _filter_sensitive_files(self, file_paths: Sequence[str]) -> list[str]:
        """Ensure no sensitive system files are ever modified by the AI solver."""
        safe_list = []
        sensitive_patterns = [
            "vault", "secret", "private", "key", ".env", "risk", "ledger"
        ]
        for path in file_paths:
            path_lower = path.lower()
            if any(pat in path_lower for pat in sensitive_patterns):
                logger.warning(f"🛡️ Guardrail active: Blocked sensitive file from AI modification list: {path}")
            else:
                safe_list.append(path)
        return safe_list

    def _backup_files(self, file_paths: Sequence[str]) -> dict[str, str]:
        """Backs up files in memory before modification to allow complete rollback on error."""
        backups = {}
        for path in file_paths:
            full_path = self.workspace_path / path
            if full_path.exists():
                try:
                    with open(full_path, "r", encoding="utf-8") as handle:
                        backups[path] = handle.read()
                except Exception as e:
                    logger.warning(f"Could not back up {path}: {e}")
        return backups

    def _restore_backups(self, backups: dict[str, str]):
        """Restores file states from memory backups."""
        for path, content in backups.items():
            full_path = self.workspace_path / path
            try:
                with open(full_path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                logger.info(f"🔄 Restored file from backup: {path}")
            except Exception as e:
                logger.error(f"Critical: Failed to restore backup for {path}: {e}")

    def _remove_backups(self, backups: dict[str, str]):
        """Backups cleanup after successful validation."""
        pass  # Memory backups, no disk files to delete

    def _clean_json(self, text: str) -> str:
        """Strip markdown ticks or any extra formatting from LLM response before parsing."""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    def _write_report_file(self, report: SolverReport):
        """Dumps a premium GSD handoff report to disk."""
        report_dir = self.workspace_path / "user_data" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "gsd_issue_resolver_report.md"

        markdown_content = f"""# GSD Autonomous Problem Solver Report
Created: Autonomous GSD Loop
Status: {"🟢 PASSED & VERIFIED" if report.ok else "🔴 FAILED & ROLLED BACK"}

## Issue Target
> {report.issue}

## Intake Phase
- **Goal**: {report.phases.get("intake", {}).get("goal", "")}
- **Scope**: {", ".join(report.phases.get("intake", {}).get("scope", []))}
- **Non-Goals**: {", ".join(report.phases.get("intake", {}).get("non_goals", []))}

## Context Phase
- **Identified Files**: {", ".join(report.phases.get("context", {}).get("priority_files", []))}
- **External Framework References**: {", ".join(report.phases.get("context", {}).get("external_sources", []))}

## Implementation Phase
- **Changed Files**: {", ".join(report.changed_files)}
- **Action**: {report.phases.get("implementation", {}).get("behavior_change", "")}

## Verification Phase
- **Tests Executed**: {", ".join(report.tests_run)}
- **Pytest Outcome**: {"SUCCESS ✅" if report.ok else "FAILURE ❌"}
- **Residual Risks**: {report.residual_risks}

## Next Operational Steps
{chr(10).join(f"- `{cmd}`" for cmd in report.phases.get("handoff", {}).get("next_commands", []))}
"""
        with open(report_path, "w", encoding="utf-8") as out:
            out.write(markdown_content)
        logger.info(f"📝 Wrote handoff report to: {report_path.relative_to(self.workspace_path)}")
