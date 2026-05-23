.PHONY: bandit setup-submodules update-submodules setup-integration-envs

bandit:
	@./scripts/run_bandit.sh

# ── Submodule management ──
setup-submodules:
	git submodule update --init --recursive

update-submodules:
	git submodule update --remote --recursive

# ── Integration environments ──
setup-integration-envs: setup-submodules
	@echo "=== Setting up pydantic-ai ==="
	@echo "pydantic-ai is a pip dependency — run: pip install -r requirements.txt"
	@echo ""
	@echo "=== Setting up polymarket_lp_tool ==="
	@echo "Python deps already covered by requirements.txt"
	@echo ""
	@echo "=== Setting up Polymarket_data (separate env for Python >=3.12) ==="
	@echo "  python3.12 -m venv .venv_polymarket_data"
	@echo "  source .venv_polymarket_data/bin/activate"
	@echo "  cd utils/polymarket_data && pip install -e . && cd ../.."
	@echo ""
	@echo "=== Setting up prediction-market-backtesting (separate env for Python >=3.12 + Rust) ==="
	@echo "  python3.12 -m venv .venv_nautilus_backtest"
	@echo "  source .venv_nautilus_backtest/bin/activate"
	@echo "  cd engine/backtest/nautilus_backtest && pip install -r requirements.txt && maturin develop --release && cd ../../.."
	@echo ""
	@echo "=== Starting Docker sidecars ==="
	@echo "  docker compose -f docker-compose.integrations.yml up -d clodds polybot-executor"
