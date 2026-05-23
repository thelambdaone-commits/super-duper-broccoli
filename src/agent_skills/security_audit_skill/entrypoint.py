from __future__ import annotations

import re
from pathlib import Path


SECRET_PATTERNS = {
    "Hex private key": re.compile(r"\b0x[a-fA-F0-9]{64}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
}


def _iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".git") for part in path.parts):
            continue
        if path.suffix in {".pyc", ".db", ".duckdb", ".png", ".jpg", ".jpeg", ".gif", ".zip"}:
            continue
        files.append(path)
    return files


def _line_findings(path: Path, root: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings

    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append(
                    {
                        "location": f"{path.relative_to(root)}:{lineno}",
                        "severity": "HIGH",
                        "vulnerability": name,
                        "impact": "Potential credential exposure in source or logs.",
                        "mitigation": "Remove the secret from source control and rotate it immediately.",
                    }
                )
    return findings


def _boundary_findings(path: Path, root: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings

    if path.suffix == ".py" and ("websocket" in text.lower() or "update.effective_message" in text.lower()):
        if "pydantic" not in text.lower() and "from_mapping" not in text and "schema" not in text.lower():
            findings.append(
                {
                    "location": str(path.relative_to(root)),
                    "severity": "MEDIUM",
                    "vulnerability": "Unvalidated external input path",
                    "impact": "Malformed inbound messages can bypass normalization and trigger undefined behavior.",
                    "mitigation": "Introduce schema validation or typed normalization at the ingress boundary.",
                }
            )
    return findings


def _db_findings(path: Path, root: Path) -> list[dict]:
    findings: list[dict] = []
    if path.suffix != ".py":
        return findings
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings

    dangerous = re.findall(r'execute\((f["\']|["\'].*%s|["\'].*\{)', text)
    if dangerous:
        findings.append(
            {
                "location": str(path.relative_to(root)),
                "severity": "MEDIUM",
                "vulnerability": "Potential dynamic SQL construction",
                "impact": "Unsafe SQL composition increases injection and schema-corruption risk.",
                "mitigation": "Prefer parameterized queries and avoid interpolating user-controlled strings into SQL.",
            }
        )
    return findings


def run_security_audit(root_dir: str = ".") -> dict:
    root = Path(root_dir).resolve()
    findings: list[dict] = []
    for path in _iter_text_files(root):
        findings.extend(_line_findings(path, root))
        findings.extend(_boundary_findings(path, root))
        findings.extend(_db_findings(path, root))

    return {
        "status": "SUCCESS",
        "root_dir": str(root),
        "finding_count": len(findings),
        "findings": findings,
    }
