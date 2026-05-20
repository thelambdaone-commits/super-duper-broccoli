import ast
import logging
import os
from typing import Any, Optional

from continuous_improvement.skills import ALL_SKILLS

logger = logging.getLogger("CI_Analyzer")

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
IGNORE_DIRS = {".venv", "__pycache__", ".git", ".pytest_cache", "logs", "node_modules"}


class CodeAnalyzer:
    def __init__(self, root: str = PROJECT_ROOT) -> None:
        self.root = root

    def _walk_python_files(self) -> list[str]:
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for f in filenames:
                if f.endswith(".py"):
                    files.append(os.path.join(dirpath, f))
        return files

    def find_duplicated_functions(self) -> list[dict[str, Any]]:
        funcs_by_name: dict[str, list[tuple[str, int]]] = {}
        for filepath in self._walk_python_files():
            try:
                with open(filepath) as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        rel = os.path.relpath(filepath, self.root)
                        funcs_by_name.setdefault(node.name, []).append((rel, node.lineno))
            except (SyntaxError, IOError):
                pass

        duplicates = []
        for name, locations in funcs_by_name.items():
            if len(locations) > 1 and not name.startswith("test_"):
                duplicates.append({
                    "function": name,
                    "locations": locations,
                    "occurrences": len(locations),
                })
        return sorted(duplicates, key=lambda x: -x["occurrences"])

    def find_missing_type_hints(self) -> list[dict[str, Any]]:
        issues = []
        for filepath in self._walk_python_files():
            rel = os.path.relpath(filepath, self.root)
            try:
                with open(filepath) as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for arg in node.args.args:
                            if arg.arg == "self":
                                continue
                            if arg.annotation is None:
                                issues.append({
                                    "file": rel,
                                    "line": node.lineno,
                                    "function": node.name,
                                    "missing": f"parameter '{arg.arg}'",
                                })
                        if node.returns is None:
                            issues.append({
                                "file": rel,
                                "line": node.lineno,
                                "function": node.name,
                                "missing": "return type",
                            })
            except (SyntaxError, IOError):
                pass

        return issues[:50]

    def find_import_anti_patterns(self) -> list[dict[str, Any]]:
        issues = []
        for filepath in self._walk_python_files():
            rel = os.path.relpath(filepath, self.root)
            try:
                with open(filepath) as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                        continue
                    if isinstance(node, ast.Call):
                        func = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                        if func == "__import__":
                            issues.append({
                                "file": rel,
                                "line": node.lineno,
                                "severity": "high",
                                "message": "Uses __import__() built-in instead of standard import statement",
                            })
            except (SyntaxError, IOError):
                pass
        return issues

    def find_too_long_functions(self, max_lines: int = 80) -> list[dict[str, Any]]:
        issues = []
        for filepath in self._walk_python_files():
            rel = os.path.relpath(filepath, self.root)
            try:
                with open(filepath) as f:
                    lines = f.readlines()
                tree = ast.parse("".join(lines))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        start = node.lineno
                        end = getattr(node, "end_lineno", None) or len(lines)
                        length = end - start + 1
                        if length > max_lines:
                            issues.append({
                                "file": rel,
                                "line": start,
                                "function": node.name,
                                "lines": length,
                            })
            except (SyntaxError, IOError):
                pass
        return sorted(issues, key=lambda x: -x["lines"])[:30]

    def check_test_balance(self) -> dict[str, Any]:
        test_dir = os.path.join(self.root, "tests")
        if not os.path.exists(test_dir):
            return {"exists": False}

        test_files = [f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")]
        total_lines = 0
        test_functions = 0
        for tf in test_files:
            path = os.path.join(test_dir, tf)
            try:
                with open(path) as f:
                    tree = ast.parse(f.read())
                total_lines += len(open(path).read().splitlines())
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                        test_functions += 1
            except (SyntaxError, IOError):
                pass

        source_files = len(self._walk_python_files())
        return {
            "exists": True,
            "test_files": len(test_files),
            "test_functions": test_functions,
            "test_lines": total_lines,
            "source_files": source_files,
            "tests_per_source_file": round(len(test_files) / max(source_files, 1), 2),
        }

    def analyze_all(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        results["duplicated_functions"] = self.find_duplicated_functions()
        results["import_anti_patterns"] = self.find_import_anti_patterns()
        results["long_functions"] = self.find_too_long_functions()
        results["missing_type_hints"] = self.find_missing_type_hints()
        results["test_balance"] = self.check_test_balance()

        all_skill_issues = []
        for skill_name, skill in ALL_SKILLS.items():
            issues = skill.detect_issues()
            for issue in issues:
                issue["skill"] = skill_name
            all_skill_issues.extend(issues)
        results["skill_detected_issues"] = all_skill_issues

        return results

    def generate_report(self, analysis: Optional[dict[str, Any]] = None) -> str:
        if analysis is None:
            analysis = self.analyze_all()

        lines = []
        lines.append("=" * 60)
        lines.append("  CONTINUOUS IMPROVEMENT — CODE ANALYSIS REPORT")
        lines.append("=" * 60)

        dups = analysis.get("duplicated_functions", [])
        lines.append(f"\n## Duplicated Functions: {len(dups)}")
        for d in dups[:10]:
            locs = "; ".join(f"{f}:{l}" for f, l in d["locations"])
            lines.append(f"  - {d['function']} ({d['occurrences']}x): {locs}")

        imports = analysis.get("import_anti_patterns", [])
        lines.append(f"\n## Import Anti-Patterns: {len(imports)}")
        for i in imports[:10]:
            lines.append(f"  - {i['file']}:{i['line']} — {i['message']}")

        long_funcs = analysis.get("long_functions", [])
        lines.append(f"\n## Long Functions (>80 lines): {len(long_funcs)}")
        for f in long_funcs[:10]:
            lines.append(f"  - {f['file']}:{f['line']} {f['function']} ({f['lines']} lines)")

        hints = analysis.get("missing_type_hints", [])
        lines.append(f"\n## Missing Type Hints: {len(hints)}")
        for h in hints[:10]:
            lines.append(f"  - {h['file']}:{h['line']} {h['function']} — missing {h['missing']}")

        tb = analysis.get("test_balance", {})
        lines.append(f"\n## Test Balance")
        if tb.get("exists"):
            lines.append(f"  Test files: {tb['test_files']}")
            lines.append(f"  Test functions: {tb['test_functions']}")
            lines.append(f"  Test lines: {tb['test_lines']}")
            lines.append(f"  Source files: {tb['source_files']}")
            lines.append(f"  Tests per source file: {tb['tests_per_source_file']}")
        else:
            lines.append("  No test directory found")

        skill_issues = analysis.get("skill_detected_issues", [])
        lines.append(f"\n## Skill-Detected Issues: {len(skill_issues)}")
        for iss in skill_issues[:15]:
            lines.append(f"  [{iss.get('skill','?')}] {iss.get('message','')}")

        lines.append("\n" + "=" * 60)
        lines.append("  End of Report")
        lines.append("=" * 60)
        return "\n".join(lines)
