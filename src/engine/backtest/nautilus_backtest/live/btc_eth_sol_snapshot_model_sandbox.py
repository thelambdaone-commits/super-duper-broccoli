from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    import importlib.util

    helper_path = Path(__file__).resolve().parents[1] / "backtests" / "_script_helpers.py"
    spec = importlib.util.spec_from_file_location("_script_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script helper from {helper_path}")
    helpers = importlib.util.module_from_spec(spec)
    sys.modules["_script_helpers"] = helpers
    spec.loader.exec_module(helpers)
    helpers.ensure_repo_root(__file__)

from live import btc_snapshot_model_sandbox

DEFAULT_ETH_SOL_MODEL_PATH = (
    "live/models/btc_snapshot_model_s223_btc_eth_sol_l2_full_feb12_may9.json"
)
DEFAULT_ETH_SOL_EDGE = "0.08"
DEFAULT_ETH_SOL_EXTRA_SPOT_INSTRUMENT_IDS = "ETHUSDT.BINANCE,SOLUSDT.BINANCE"


def _configure_env_defaults() -> None:
    os.environ.setdefault("LIVE_BTC_SNAPSHOT_MODEL_PATH", DEFAULT_ETH_SOL_MODEL_PATH)
    os.environ.setdefault("LIVE_BTC_SNAPSHOT_EDGE", DEFAULT_ETH_SOL_EDGE)
    os.environ.setdefault(
        "LIVE_BTC_EXTRA_SPOT_INSTRUMENT_IDS",
        DEFAULT_ETH_SOL_EXTRA_SPOT_INSTRUMENT_IDS,
    )


async def _main(argv: Sequence[str] | None = None, *, force_run: bool = False) -> None:
    _configure_env_defaults()
    await btc_snapshot_model_sandbox._main(argv, force_run=force_run)


def run() -> None:
    asyncio.run(_main((), force_run=True))


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
