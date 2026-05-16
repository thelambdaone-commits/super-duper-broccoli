#!/usr/bin/env bash
# dump_project — recursively print all source files with clear section separators
# Usage: ./scripts/dump_project.sh [path] [pattern] [extra external_dir]
#   ./scripts/dump_project.sh                              # all .py files
#   ./scripts/dump_project.sh src/                         # all .py in src/
#   ./scripts/dump_project.sh . "*.json"                   # all .json files
#   ./scripts/dump_project.sh . "*.{py,js,ts}"             # .py + .js + .ts
#   ./scripts/dump_project.sh . "*.py" /path/to/external   # dump external too

set -euo pipefail

ROOT="${1:-.}"
PATTERN="${2:-*.py}"
EXTRA_DIR="${3:-}"

# Default: exclude __pycache__, .venv, node_modules, .git
EXCLUDES=(-not -path '*/__pycache__/*' -not -path '*/.venv/*' -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/venv/*' -not -path '*/.mypy_cache/*' -not -path '*/__pycache__/*')

dump_dir() {
    local dir="$1"
    local label="$2"
    echo "============================================================"
    echo " DUMP PROJECT: $(realpath "$dir" 2>/dev/null || echo "$dir")"
    echo " LABEL: $label"
    echo " PATTERN: $PATTERN"
    echo "============================================================"
    echo ""

    if [ ! -d "$dir" ]; then
        echo "[WARNING] Directory not found: $dir"
        echo ""
        return
    fi

    find "$dir" -type f -name "$PATTERN" "${EXCLUDES[@]}" 2>/dev/null | sort | while read -r f; do
        lines=$(wc -l < "$f" 2>/dev/null || echo "?")
        echo "============================================================"
        echo " FILE: $f  ($lines lines)"
        echo "============================================================"
        cat "$f"
        echo -e "\n"
    done
}

dump_dir "$ROOT" "main"

if [ -n "$EXTRA_DIR" ]; then
    dump_dir "$EXTRA_DIR" "external"
fi

echo "============================================================"
echo " END DUMP"
echo "============================================================"
