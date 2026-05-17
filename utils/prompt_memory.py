import json
import os
import re
import time
from datetime import datetime
from typing import Any, Optional


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
KB_DIR = os.path.join(PROJECT_ROOT, "continuous_improvement", "knowledge_base")
PROJECT_MEMORY_PATH = os.path.join(KB_DIR, "project_memory.json")
AGENTS_PATH = os.path.join(PROJECT_ROOT, "AGENTS.md")
GRAPHIFY_REPORT_PATH = os.path.join(PROJECT_ROOT, "graphify-out", "GRAPH_REPORT.md")
GRAPHIFY_MANIFEST_PATH = os.path.join(PROJECT_ROOT, "graphify-out", "manifest.json")
PROJECT_CONTEXTS_PATH = os.path.join(CONFIG_DIR, "project_contexts.json")
AI_SPECIALISTS_PATH = os.path.join(CONFIG_DIR, "ai_specialists.json")

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|private[_-]?key|passphrase)\s*[:=]\s*\S+"),
    re.compile(r"0x[a-fA-F0-9]{64}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9_-]{16,}"),
]


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True, default=str)
        f.write("\n")


def _read_text(path: str, max_chars: int) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except OSError:
        return ""


def _redact_secrets(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    
    # Entropy-based security guardrail (moltbook-agent-guard pattern)
    # Scan for high-entropy alphanumeric strings that could be private keys or API credentials
    import math
    from collections import Counter
    
    # Find candidate alphanumeric strings of length 30 to 128
    candidates = re.findall(r"\b[A-Za-z0-9\-_]{30,128}\b", redacted)
    for cand in set(candidates):
        # Skip strings that are entirely digits to prevent over-redacting numbers
        if cand.isdigit():
            continue
        # Skip standard long words if lowercase and moderately short
        if cand.islower() and len(cand) < 40:
            continue
        # Shannon entropy
        counts = Counter(cand)
        cand_len = len(cand)
        entropy = 0.0
        for count in counts.values():
            p = count / cand_len
            entropy -= p * math.log2(p)
        
        # High entropy threshold (typically keys have entropy > 3.6)
        if entropy > 3.6:
            redacted = redacted.replace(cand, "<redacted_high_entropy_key>")
            
    return redacted


def _truncate(value: str, max_chars: int) -> str:
    value = _redact_secrets(str(value or "").strip())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _default_memory() -> dict[str, Any]:
    return {
        "version": 1,
        "purpose": "Persistent compact memory for project prompts. Store decisions, gotchas, preferences, and verification notes; never store secrets or raw private data.",
        "updated_at": _utc_now(),
        "entries": [],
    }


def load_project_memory(path: str = PROJECT_MEMORY_PATH) -> dict[str, Any]:
    memory = _load_json(path, _default_memory())
    if not isinstance(memory, dict):
        return _default_memory()
    memory.setdefault("version", 1)
    memory.setdefault("purpose", _default_memory()["purpose"])
    memory.setdefault("updated_at", _utc_now())
    memory.setdefault("entries", [])
    if not isinstance(memory["entries"], list):
        memory["entries"] = []
    return memory


def record_project_memory(
    component: str,
    summary: str,
    kind: str = "note",
    tags: Optional[list[str]] = None,
    details: str = "",
    source: str = "manual",
    path: str = PROJECT_MEMORY_PATH,
    max_entries: int = 200,
) -> dict[str, Any]:
    memory = load_project_memory(path)
    entry = {
        "timestamp": time.time(),
        "date": _utc_now(),
        "kind": _truncate(kind, 40) or "note",
        "component": _truncate(component, 120) or "project",
        "summary": _truncate(summary, 600),
        "details": _truncate(details, 1400),
        "tags": [_truncate(tag, 60) for tag in (tags or []) if str(tag).strip()][:12],
        "source": _truncate(source, 120) or "manual",
    }
    memory["entries"].append(entry)
    memory["entries"] = memory["entries"][-max_entries:]
    memory["updated_at"] = _utc_now()
    _write_json(path, memory)
    return entry


def list_project_memory(
    component: str = "",
    tag: str = "",
    limit: int = 10,
    path: str = PROJECT_MEMORY_PATH,
) -> list[dict[str, Any]]:
    entries = load_project_memory(path).get("entries", [])
    component_norm = component.strip().lower()
    tag_norm = tag.strip().lower()
    if component_norm:
        entries = [e for e in entries if component_norm in str(e.get("component", "")).lower()]
    if tag_norm:
        entries = [
            e for e in entries
            if tag_norm in {str(t).lower() for t in e.get("tags", [])}
        ]
    return entries[-max(1, min(limit, 50)):]


def _load_recent_decisions(limit: int = 6) -> list[dict[str, Any]]:
    decisions = _load_json(os.path.join(KB_DIR, "decisions.json"), [])
    if not isinstance(decisions, list):
        return []
    return decisions[-limit:]


def _load_project_context_summary(limit: int = 12) -> list[dict[str, Any]]:
    data = _load_json(PROJECT_CONTEXTS_PATH, {})
    projects = data.get("projects", []) if isinstance(data, dict) else []
    summary = []
    for project in projects[:limit]:
        summary.append({
            "id": project.get("id"),
            "category": project.get("category"),
            "status": project.get("status"),
            "token_strategy": project.get("token_strategy"),
        })
    return summary


def _load_specialist(specialist_id: str) -> dict[str, Any]:
    if not specialist_id:
        return {}
    data = _load_json(AI_SPECIALISTS_PATH, {})
    normalized = specialist_id.strip().lower().replace("-", "_")
    for specialist in data.get("specialists", []):
        if normalized == str(specialist.get("id", "")).lower():
            return specialist
    return {}


def _load_graphify_summary(max_chars: int = 2500) -> dict[str, Any]:
    manifest = _load_json(GRAPHIFY_MANIFEST_PATH, {})
    report = _read_text(GRAPHIFY_REPORT_PATH, max_chars)
    manifest_summary: dict[str, Any] = {}
    if isinstance(manifest, dict):
        manifest_summary = {
            "file_count": len(manifest),
            "sample_files": [
                os.path.relpath(path, PROJECT_ROOT)
                for path in list(manifest.keys())[:12]
            ],
        }
    return {
        "available": bool(report or manifest),
        "manifest": manifest_summary,
        "report_excerpt": _truncate(report, max_chars),
    }


def _approx_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=True, default=str)
    return max(1, len(text) // 4)


def build_project_prompt_context(
    task: str = "",
    specialist_id: str = "",
    component: str = "",
    token_budget: int = 2500,
) -> dict[str, Any]:
    budget = max(800, min(int(token_budget or 2500), 8000))
    context: dict[str, Any] = {
        "version": 1,
        "generated_at": _utc_now(),
        "task": _truncate(task, 500),
        "context_budget_tokens": budget,
        "rules": {
            "lowest_token_path": [
                "Use AGENTS.md, project memory, project context cards, and Graphify before broad file reads.",
                "Read source files only after the compact context identifies likely targets.",
                "Never store or send secrets, raw logs, private Telegram messages, ledger data, or local databases.",
            ],
            "verification": "Graph and memory are hints; verify behavior in source files and tests before changing trading code.",
        },
        "agent_guide_excerpt": _truncate(_read_text(AGENTS_PATH, 2200), 2200),
        "specialist": _load_specialist(specialist_id),
        "project_memory": list_project_memory(component=component, limit=10),
        "recent_decisions": _load_recent_decisions(limit=6),
        "project_context_cards": _load_project_context_summary(limit=14),
        "graphify": _load_graphify_summary(max_chars=2200),
    }

    if _approx_tokens(context) > budget:
        context["graphify"]["report_excerpt"] = _truncate(context["graphify"].get("report_excerpt", ""), 900)
    if _approx_tokens(context) > budget:
        context["agent_guide_excerpt"] = _truncate(context.get("agent_guide_excerpt", ""), 900)
    if _approx_tokens(context) > budget:
        context["project_context_cards"] = context["project_context_cards"][:6]
    while _approx_tokens(context) > budget and len(context["recent_decisions"]) > 2:
        context["recent_decisions"] = context["recent_decisions"][1:]
    while _approx_tokens(context) > budget and len(context["project_memory"]) > 1:
        context["project_memory"] = context["project_memory"][1:]
    context["estimated_tokens"] = _approx_tokens(context)
    if context["estimated_tokens"] > budget:
        context["estimated_tokens"] = _approx_tokens({k: v for k, v in context.items() if k != "estimated_tokens"})
    return context


def format_project_prompt_context(context: dict[str, Any]) -> str:
    lines = [
        "PROJECT PROMPT CONTEXT",
        f"Task: {context.get('task') or '(not specified)'}",
        f"Budget: {context.get('context_budget_tokens')} tokens; estimated: {context.get('estimated_tokens')}",
        "",
        "Rules:",
    ]
    for rule in context.get("rules", {}).get("lowest_token_path", []):
        lines.append(f"- {rule}")
    lines.append(f"- {context.get('rules', {}).get('verification')}")

    specialist = context.get("specialist") or {}
    if specialist:
        lines.extend([
            "",
            f"Specialist: {specialist.get('id')} ({specialist.get('name')})",
            f"Priority files: {', '.join(specialist.get('priority_files', [])[:8])}",
            f"Output contract: {specialist.get('output_contract', '')}",
        ])

    memory = context.get("project_memory", [])
    if memory:
        lines.extend(["", "Project memory:"])
        for entry in memory[-8:]:
            tags = ", ".join(entry.get("tags", []))
            tag_text = f" [{tags}]" if tags else ""
            lines.append(f"- {entry.get('component')} ({entry.get('kind')}){tag_text}: {entry.get('summary')}")

    decisions = context.get("recent_decisions", [])
    if decisions:
        lines.extend(["", "Recent decisions:"])
        for decision in decisions[-5:]:
            lines.append(f"- {decision.get('component')}: {decision.get('description')}")

    graphify = context.get("graphify", {})
    if graphify.get("available"):
        lines.extend([
            "",
            "Graphify:",
            "- graphify-out/graph.json is available; use graphify query/path/explain before broad file reads.",
        ])

    return "\n".join(lines)
