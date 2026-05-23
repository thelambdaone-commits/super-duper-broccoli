import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("CI_KnowledgeBase")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
KB_DIR = os.path.join(BASE_DIR, "continuous_improvement", "knowledge_base")


DECISIONS_PATH = os.path.join(KB_DIR, "decisions.json")
ERRORS_PATH = os.path.join(KB_DIR, "errors.json")
IMPROVEMENTS_PATH = os.path.join(KB_DIR, "improvements.json")
TEST_RESULTS_PATH = os.path.join(KB_DIR, "test_results.json")


def _load(path: str) -> list[dict[str, Any]]:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save(path: str, data: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


class KnowledgeBase:
    def __init__(self, kb_dir: str = KB_DIR) -> None:
        self.kb_dir = kb_dir
        os.makedirs(kb_dir, exist_ok=True)
        self._cache: dict[str, list[dict]] = {}

    def _path(self, name: str) -> str:
        return os.path.join(self.kb_dir, f"{name}.json")

    def _get(self, name: str) -> list[dict]:
        if name not in self._cache:
            self._cache[name] = _load(self._path(name))
        return self._cache[name]

    def _flush(self, name: str) -> None:
        data = self._cache.get(name, [])
        _save(self._path(name), data)

    # ── Decisions ──

    def record_decision(self, category: str, component: str, description: str, rationale: str, outcome: str = "") -> None:
        entries = self._get("decisions")
        entries.append({
            "timestamp": time.time(),
            "date": datetime.utcnow().isoformat(),
            "category": category,
            "component": component,
            "description": description,
            "rationale": rationale,
            "outcome": outcome,
        })
        self._flush("decisions")
        logger.info(f"Decision recorded: [{category}] {component} — {description[:60]}")

    def get_decisions(self, category: Optional[str] = None, component: Optional[str] = None, limit: int = 20) -> list[dict]:
        entries = self._get("decisions")
        if category:
            entries = [e for e in entries if e.get("category") == category]
        if component:
            entries = [e for e in entries if e.get("component") == component]
        return entries[-limit:]

    # ── Errors ──

    def record_error(self, component: str, error_type: str, message: str, context: str = "") -> None:
        entries = self._get("errors")
        entries.append({
            "timestamp": time.time(),
            "date": datetime.utcnow().isoformat(),
            "component": component,
            "error_type": error_type,
            "message": message,
            "context": context,
            "resolved": False,
        })
        self._flush("errors")
        logger.warning(f"Error recorded: [{component}] {error_type} — {message[:80]}")

    def resolve_error(self, index: int, resolution: str) -> None:
        entries = self._get("errors")
        if 0 <= index < len(entries):
            entries[index]["resolved"] = True
            entries[index]["resolved_at"] = datetime.utcnow().isoformat()
            entries[index]["resolution"] = resolution
            self._flush("errors")

    def get_unresolved_errors(self, component: Optional[str] = None) -> list[dict]:
        entries = self._get("errors")
        unresolved = [e for e in entries if not e.get("resolved")]
        if component:
            unresolved = [e for e in unresolved if e.get("component") == component]
        return unresolved

    def get_frequent_errors(self, top_n: int = 5) -> list[tuple[str, int]]:
        entries = self._get("errors")
        counts: dict[str, int] = {}
        for e in entries:
            key = f"{e.get('component')}:{e.get('error_type')}"
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda x: -x[1])[:top_n]

    # ── Improvements ──

    def record_improvement(self, component: str, suggestion: str, priority: str = "medium", impact: str = "") -> None:
        entries = self._get("improvements")
        entries.append({
            "timestamp": time.time(),
            "date": datetime.utcnow().isoformat(),
            "component": component,
            "suggestion": suggestion,
            "priority": priority,
            "impact": impact,
            "applied": False,
        })
        self._flush("improvements")

    def mark_applied(self, index: int, result: str = "") -> None:
        entries = self._get("improvements")
        if 0 <= index < len(entries):
            entries[index]["applied"] = True
            entries[index]["applied_at"] = datetime.utcnow().isoformat()
            entries[index]["result"] = result
            self._flush("improvements")

    def get_pending_improvements(self, priority: Optional[str] = None) -> list[dict]:
        entries = self._get("improvements")
        pending = [e for e in entries if not e.get("applied")]
        if priority:
            pending = [e for e in pending if e.get("priority") == priority]
        return pending

    # ── Test Results ──

    def record_test_run(self, total: int, passed: int, failed: int, duration_s: float, details: str = "") -> None:
        entries = self._get("test_results")
        entries.append({
            "timestamp": time.time(),
            "date": datetime.utcnow().isoformat(),
            "total": total,
            "passed": passed,
            "failed": failed,
            "duration_s": round(duration_s, 2),
            "details": details,
        })
        self._flush("test_results")

    def get_test_trend(self, limit: int = 10) -> list[dict]:
        entries = self._get("test_results")
        return entries[-limit:]

    def get_regressions(self) -> list[dict]:
        entries = self._get("test_results")
        regressions = []
        for i in range(1, len(entries)):
            prev = entries[i - 1]
            curr = entries[i]
            if curr["passed"] < prev["passed"]:
                regressions.append({
                    "from": prev,
                    "to": curr,
                    "regression": prev["passed"] - curr["passed"],
                })
        return regressions

    # ── Summary ──

    def summary(self) -> dict:
        return {
            "decisions": len(self._get("decisions")),
            "errors": {
                "total": len(self._get("errors")),
                "unresolved": len(self.get_unresolved_errors()),
            },
            "improvements": {
                "total": len(self._get("improvements")),
                "pending": len(self.get_pending_improvements()),
            },
            "test_runs": len(self._get("test_results")),
            "frequent_errors": self.get_frequent_errors(3),
        }
