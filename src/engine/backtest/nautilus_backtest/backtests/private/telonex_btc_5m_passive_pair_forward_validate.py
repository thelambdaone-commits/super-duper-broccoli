from __future__ import annotations

import csv
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

if __package__ in {None, ""}:
    _HELPER_PATH = Path(__file__).resolve().parents[1] / "_script_helpers.py"
    _SPEC = importlib.util.spec_from_file_location("_script_helpers", _HELPER_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError(f"Unable to load script helper from {_HELPER_PATH}")
    _HELPER = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(_HELPER)
    ensure_repo_root = _HELPER.ensure_repo_root
else:
    from backtests._script_helpers import ensure_repo_root

ensure_repo_root(__file__)

from backtests.private.telonex_btc_5m_passive_pair_accumulation_search import (  # noqa: E402
    ARTIFACT_ROOT,
    PASSIVE_PAIR_CHAMPION_PARAMS,
    _btc_5m_replays,
    _btc_5m_windows,
    _deserialize_params,
    _env_int,
    _evaluate_trial,
    _evaluation_row,
)


_DEFAULT_FORWARD_START = 1_777_248_000  # 2026-04-27T00:00:00Z
_DEFAULT_FORWARD_WINDOWS = 72


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_BTC_PASSIVE_PAIR_RUN_LABEL", "s104_depth_warmup")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "s104_depth_warmup"


def _forward_params() -> dict[str, object]:
    params = dict(PASSIVE_PAIR_CHAMPION_PARAMS)
    raw_overrides = os.getenv("TELONEX_CHURN_BTC_PASSIVE_PAIR_PARAM_OVERRIDES")
    if raw_overrides is None or raw_overrides.strip() == "":
        return params
    payload = {name: str(value) for name, value in json.loads(raw_overrides).items()}
    params.update(_deserialize_params(payload))
    return params


def run() -> None:
    from prediction_market_extensions.backtesting._timing_harness import timing_harness

    load_dotenv()
    os.environ.setdefault("TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK", "1")
    os.environ.setdefault("TELONEX_CHURN_BTC_PASSIVE_PAIR_RUN_LABEL", "s104_depth_warmup_forward")

    @timing_harness
    def _run() -> None:
        start = datetime.fromtimestamp(
            _env_int("TELONEX_CHURN_BTC_START", _DEFAULT_FORWARD_START),
            tz=UTC,
        )
        window_count = _env_int(
            "TELONEX_CHURN_BTC_PASSIVE_PAIR_FORWARD_WINDOWS",
            _DEFAULT_FORWARD_WINDOWS,
        )
        windows = _btc_5m_windows(start=start, count=window_count)
        replays = _btc_5m_replays(windows)

        print(
            "Strategy hypothesis: fixed passive paired-bid settlement carry "
            "should remain positive on later BTC 5m windows if the edge is caused "
            "by persistent complementary-token underpricing rather than the "
            "original train/holdout block."
        )
        params = _forward_params()
        evaluation = _evaluate_trial(
            trial_id=1,
            phase="forward",
            replays=replays,
            params=params,
        )
        row = _evaluation_row(evaluation)

        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        label = _run_label()
        csv_path = ARTIFACT_ROOT / f"telonex_btc_5m_passive_pair_{label}_forward_validation.csv"
        json_path = ARTIFACT_ROOT / f"telonex_btc_5m_passive_pair_{label}_forward_validation.json"
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted(row))
            writer.writeheader()
            writer.writerow(row)
        json_path.write_text(
            json.dumps(
                {
                    "name": f"telonex_btc_5m_passive_pair_{label}_forward_validation",
                    "hypothesis": (
                        "Fixed passive paired-bid settlement carry should remain "
                        "positive on later BTC 5m windows if the edge is caused by "
                        "persistent complementary-token underpricing rather than the "
                        "original train/holdout block."
                    ),
                    "params": {name: str(value) for name, value in params.items()},
                    "forward": row,
                },
                indent=2,
                sort_keys=True,
            )
        )
        print(
            f"forward: score={evaluation.score:.4f} pnl={evaluation.pnl:.4f} "
            f"fills={evaluation.fills} loaded={evaluation.loaded_ratio:.2%} "
            f"status={evaluation.status}"
        )
        print(f"Strategy passive-pair validation CSV: {csv_path}")
        print(f"Strategy passive-pair validation JSON: {json_path}")

    _run()


if __name__ == "__main__":
    run()
