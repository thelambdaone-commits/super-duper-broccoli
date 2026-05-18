#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "${ROOT_DIR}/.venv/bin/bandit" ]]; then
  BANDIT_BIN="${ROOT_DIR}/.venv/bin/bandit"
else
  BANDIT_BIN="bandit"
fi

exec "${BANDIT_BIN}" \
  "${ROOT_DIR}/agents" \
  "${ROOT_DIR}/api" \
  "${ROOT_DIR}/config" \
  "${ROOT_DIR}/core" \
  "${ROOT_DIR}/continuous_improvement" \
  "${ROOT_DIR}/continuous_improvement/agents" \
  "${ROOT_DIR}/continuous_improvement/skills" \
  "${ROOT_DIR}/execution" \
  "${ROOT_DIR}/ledger" \
  "${ROOT_DIR}/mcp_agents" \
  "${ROOT_DIR}/mcp_agents/tools" \
  "${ROOT_DIR}/models" \
  "${ROOT_DIR}/monitors" \
  "${ROOT_DIR}/scrapers" \
  "${ROOT_DIR}/telegram_scraper" \
  "${ROOT_DIR}/utils" \
  "${ROOT_DIR}/utils/polymarket_crawler" \
  "${ROOT_DIR}/main_agentic_clob.py" \
  "${ROOT_DIR}/scripts" \
  -c "${ROOT_DIR}/.bandit" \
  -f txt
