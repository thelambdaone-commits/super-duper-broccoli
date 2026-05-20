#!/usr/bin/env python3
import argparse
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "project_dump.txt"

INCLUDE_DIRS = [
    "api",
    "continuous_improvement",
    "core",
    "execution",
    "ledger",
    "mcp_agents",
    "models",
    "monitors",
    "scrapers",
    "telegram_scraper",
    "scrappers",
    "user_data/freqaimodels",
    "user_data/strategies",
    "utils",
    "config",
    "tests",
]

INCLUDE_FILES = [
    "README.md",
    "requirements.txt",
    "main_agentic_clob.py",
    "api/api_server.py",
    "api/dashboard.py",
    "ecosystem.config.js",
    "pytest.ini",
]

EXCLUDE_NAMES = {
    "__pycache__",
    ".pytest_cache",
}

EXCLUDE_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".pkl",
    ".pyc",
}

SECTION_SEPARATOR = "=" * 88


def iter_project_files() -> list[Path]:
    paths: list[Path] = []

    for file_name in INCLUDE_FILES:
        path = PROJECT_ROOT / file_name
        if path.is_file():
            paths.append(path)

    for directory in INCLUDE_DIRS:
        root = PROJECT_ROOT / directory
        if not root.is_dir():
            continue
        for current_root, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_NAMES)
            for file_name in sorted(files):
                path = Path(current_root) / file_name
                if path.suffix in EXCLUDE_SUFFIXES:
                    continue
                paths.append(path)

    return sorted(set(paths), key=lambda p: p.relative_to(PROJECT_ROOT).as_posix())


def dump_project(output: Path = DEFAULT_OUTPUT) -> None:
    files = iter_project_files()
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as out:
        out.write(f"Project dump: {PROJECT_ROOT}\n")
        out.write(f"Files: {len(files)}\n")
        out.write(f"{SECTION_SEPARATOR}\n\n")

        for file_path in files:
            rel_path = file_path.relative_to(PROJECT_ROOT)
            out.write(f"{SECTION_SEPARATOR}\n")
            out.write(f"FILE: {rel_path}\n")
            out.write(f"{SECTION_SEPARATOR}\n")
            try:
                out.write(file_path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                out.write("[binary or non-utf8 file skipped]\n")
            out.write("\n\n")

    print(f"Dumped {len(files)} files to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump core project files into one text file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output file path. Default: {DEFAULT_OUTPUT}",
    )
    args = parser.parse_args()
    dump_project(args.output)


if __name__ == "__main__":
    main()
