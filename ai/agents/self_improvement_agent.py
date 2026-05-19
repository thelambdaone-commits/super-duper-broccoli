import logging
import os
import json
import time
from typing import Any, List, Optional
from datetime import datetime

logger = logging.getLogger("SelfImprovementAgent")

class SelfImprovementAgent:
    """
    Autonomous Quant Infrastructure Supervisor.
    Analyzes system state, detects inefficiencies, and suggests improvements.
    """
    def __init__(self, memory_dir: str = "memory"):
        self.memory_dir = memory_dir
        self.knowledge_base_path = os.path.join(memory_dir, "semantic", "knowledge_base.jsonl")
        os.makedirs(os.path.dirname(self.knowledge_base_path), exist_ok=True)

    def log_incident(self, category: str, description: str, root_cause: str, impact: str):
        """Records an incident for future learning."""
        incident = {
            "timestamp": datetime.utcnow().isoformat(),
            "category": category,
            "description": description,
            "root_cause": root_cause,
            "impact": impact,
            "status": "ANALYZED"
        }
        with open(self.knowledge_base_path, "a") as f:
            f.write(json.dumps(incident) + "\n")
        logger.info(f"Incident recorded: {category} - {root_cause}")

    def analyze_logs(self, log_file: str = "logs/pm2-out.log") -> list:
        """
        Delegates log analysis to LobstarAutonomicHealer to avoid dual-scanning
        and concurrent remediation actions on the same incident.
        The AutonomicHealer uses seek/tell (incremental scanning) which is more
        efficient than reading the last N lines each time.
        """
        try:
            from core.autonomic_healer import LobstarAutonomicHealer
            healer = LobstarAutonomicHealer(log_file_path=log_file)
            incident_ids = healer.analyser_nouveaux_logs()
            # Convert incident IDs to the same format used by generate_improvement_report()
            findings = []
            for incident_id in incident_ids:
                findings.append({
                    "type": incident_id,
                    "issue": f"Incident detected: {incident_id}",
                    "suggestion": "Consult LobstarAutonomicHealer remediation actions for details.",
                })
            return findings
        except Exception as e:
            logger.warning(f"Log analysis via AutonomicHealer failed, falling back: {e}")
            # Fallback: lightweight local pattern scan (no remediation actions)
            findings = []
            if not os.path.exists(log_file):
                return []
            with open(log_file, "r") as f:
                lines = f.readlines()[-500:]
            if sum(1 for l in lines if "latency" in l.lower() and "ms" in l.lower()) > 10:
                findings.append({
                    "type": "PERFORMANCE",
                    "issue": "Recurring latency spikes detected in execution loop.",
                    "suggestion": "Move orderbook parsing to a dedicated worker thread.",
                })
            if any("drift" in l.lower() and "detected" in l.lower() for l in lines):
                findings.append({
                    "type": "MODEL_GOVERNANCE",
                    "issue": "Model drift detected for multiple tickers.",
                    "suggestion": "Trigger automatic retraining pipeline with updated hyperparam grid.",
                })
            return findings

    async def _call_local_coding_tool(self, tool: str, prompt: str) -> Optional[str]:
        """Calls local coding assistants like opencode, copilot, or codex."""
        try:
            import shutil
            import subprocess
            
            # 0. Check if tool exists in PATH
            if not shutil.which(tool):
                return None

            # 1. Prepare command
            cmd = [tool, "fix", "--prompt", prompt]
            if tool == "codex":
                cmd = ["codex", "suggest", prompt]
            elif tool == "copilot":
                cmd = ["copilot", "explain", "--fix", prompt]
                
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if process.returncode == 0:
                return process.stdout.strip()
            return None
        except Exception as e:
            logger.debug(f"Local tool {tool} failed: {e}")
            return None

    async def generate_fix_patch(self, issue: dict) -> Optional[str]:
        """Uses LLM (Groq) or local tools (Copilot/Codex) to generate a code improvement patch."""
        prompt = (
            f"You are a Senior Quant Engineer. Analyze this issue: {issue['issue']}\n"
            f"Proposed Solution: {issue['suggestion']}\n"
            "Generate a concise Python code snippet or diff to implement this optimization."
        )

        # 1. Try local tools first
        for tool in ["opencode", "copilot", "codex"]:
            patch = await self._call_local_coding_tool(tool, prompt)
            if patch:
                logger.info(f"Generated fix using local tool: {tool}")
                return patch

        # 2. Fallback to Cognitive Infrastructure
        try:
            # Reusing the LOBSTAR infrastructure if available
            return (
                f"# [AUTO-GENERATED PATCH PROPOSAL]\n"
                f"# Category: {issue.get('type', 'GENERAL')}\n"
                f"# Issue: {issue['issue']}\n"
                f"# Implementation: {issue['suggestion']}\n"
                f"# Note: Autonomous implementation pending manual verification."
            )
        except Exception as e:
            logger.error(f"Self-coding failed: {e}")
            return None

    def generate_improvement_report(self) -> str:
        """Generates a structured report for the Telegram supervisor."""
        findings = self.analyze_logs()
        if not findings:
            return "✅ System Health: PERFECT. No optimizations suggested at this time."

        report = "🧠 *SELF-IMPROVEMENT REPORT*\n\n"
        for f in findings:
            report += f"📍 *{f['type']}*\n"
            report += f"Issue: {f['issue']}\n"
            report += f"Optimization: {f['suggestion']}\n\n"
        
        report += "Status: Awaiting validation before autonomous implementation."
        return report

    async def execute_refactor(self, plan: dict):
        """Placeholder for autonomous PR generation."""
        logger.info(f"Executing autonomous refactor: {plan['type']}")
        # In a real setup, this would use a git agent to create a branch and PR.
        pass
