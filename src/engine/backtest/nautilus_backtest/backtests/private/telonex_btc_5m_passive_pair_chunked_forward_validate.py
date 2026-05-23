from __future__ import annotations

import csv
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    _env_float,
    _env_int,
    _evaluate_trial,
    _evaluation_row,
)

_DEFAULT_FORWARD_START = 1_777_258_800  # 2026-04-27T03:00:00Z
_DEFAULT_FORWARD_WINDOWS = 144
_DEFAULT_CHUNK_WINDOWS = 36


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_BTC_PASSIVE_PAIR_RUN_LABEL", "chunked_forward")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "chunked_forward"


def _forward_params() -> dict[str, object]:
    params = dict(PASSIVE_PAIR_CHAMPION_PARAMS)
    raw_overrides = os.getenv("TELONEX_CHURN_BTC_PASSIVE_PAIR_PARAM_OVERRIDES")
    if raw_overrides is None or raw_overrides.strip() == "":
        return params
    payload = {name: str(value) for name, value in json.loads(raw_overrides).items()}
    params.update(_deserialize_params(payload))
    return params


def _aggregate_rows(rows: list[dict[str, Any]], params: dict[str, object]) -> dict[str, Any]:
    pnl = sum(float(row["pnl"]) for row in rows)
    fills = sum(int(row["fills"]) for row in rows)
    replay_count = sum(int(row["replay_count"]) for row in rows)
    result_count = sum(int(row["result_count"]) for row in rows)
    loaded_ratio = result_count / replay_count if replay_count else 0.0
    max_drawdown_currency = sum(float(row["max_drawdown_currency"]) for row in rows)
    rolling_cash_required = max((float(row["rolling_cash_required"]) for row in rows), default=0.0)
    initial_cash = _env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 1_000.0)
    capital_penalty = max(0.0, rolling_cash_required - initial_cash) * _env_float(
        "TELONEX_CHURN_BTC_CAPITAL_PENALTY_MULTIPLIER",
        10.0,
    )
    score = pnl - (0.5 * max_drawdown_currency) - capital_penalty
    status = "ok"
    if any(str(row["status"]) != "ok" for row in rows):
        status = "chunk_error"
        score -= 1_000.0
    min_loaded_ratio = _env_float("TELONEX_CHURN_BTC_MIN_LOADED_RATIO", 0.70)
    if loaded_ratio < min_loaded_ratio:
        status = "low_loaded_ratio"
        score -= 1_000.0 * (min_loaded_ratio - loaded_ratio) * 10.0

    return {
        "trial_id": 0,
        "phase": "chunked_forward",
        "score": score,
        "pnl": pnl,
        "max_drawdown_currency": max_drawdown_currency,
        "fills": fills,
        "coverage": (
            sum(float(row["coverage"]) * int(row["replay_count"]) for row in rows) / replay_count
            if replay_count
            else 0.0
        ),
        "loaded_ratio": loaded_ratio,
        "result_count": result_count,
        "replay_count": replay_count,
        "rolling_cash_required": rolling_cash_required,
        "capital_penalty": capital_penalty,
        "status": status,
        "chunks": len(rows),
        **{f"param_{name}": str(value) for name, value in params.items()},
    }


def run() -> None:
    from prediction_market_extensions.backtesting._timing_harness import timing_harness

    load_dotenv()
    os.environ.setdefault("TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK", "1")

    @timing_harness
    def _run() -> None:
        start = datetime.fromtimestamp(
            _env_int("TELONEX_CHURN_BTC_START", _DEFAULT_FORWARD_START),
            tz=UTC,
        )
        total_windows = _env_int(
            "TELONEX_CHURN_BTC_PASSIVE_PAIR_FORWARD_WINDOWS",
            _DEFAULT_FORWARD_WINDOWS,
        )
        chunk_windows = _env_int(
            "TELONEX_CHURN_BTC_PASSIVE_PAIR_CHUNK_WINDOWS",
            _DEFAULT_CHUNK_WINDOWS,
        )
        if total_windows < 1:
            raise ValueError("TELONEX_CHURN_BTC_PASSIVE_PAIR_FORWARD_WINDOWS must be >= 1")
        if chunk_windows < 1:
            raise ValueError("TELONEX_CHURN_BTC_PASSIVE_PAIR_CHUNK_WINDOWS must be >= 1")

        windows = _btc_5m_windows(start=start, count=total_windows)
        params = _forward_params()
        print(
            "Strategy hypothesis: split validation should preserve the same "
            "passive-pair edge estimate while avoiding monolithic worker memory "
            "failure. Conservative aggregation sums chunk drawdowns and caps "
            "capital by the worst chunk."
        )

        rows: list[dict[str, Any]] = []
        for offset in range(0, total_windows, chunk_windows):
            chunk = windows[offset : offset + chunk_windows]
            replays = _btc_5m_replays(chunk)
            trial_id = (offset // chunk_windows) + 1
            evaluation = _evaluate_trial(
                trial_id=trial_id,
                phase=f"chunk_{trial_id:03d}",
                replays=replays,
                params=params,
            )
            row = _evaluation_row(evaluation)
            row["chunk_window_start_index"] = offset
            row["chunk_window_count"] = len(chunk)
            rows.append(row)
            print(
                f"chunk {trial_id:03d}: score={evaluation.score:.4f} "
                f"pnl={evaluation.pnl:.4f} fills={evaluation.fills} "
                f"loaded={evaluation.loaded_ratio:.2%} status={evaluation.status}"
            )

        aggregate = _aggregate_rows(rows, params)
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        label = _run_label()
        csv_path = ARTIFACT_ROOT / f"telonex_btc_5m_passive_pair_{label}_chunked_forward.csv"
        json_path = ARTIFACT_ROOT / f"telonex_btc_5m_passive_pair_{label}_chunked_forward.json"
        fieldnames = sorted({key for row in [aggregate, *rows] for key in row})
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(aggregate)
            writer.writerows(rows)
        json_path.write_text(
            json.dumps(
                {
                    "name": f"telonex_btc_5m_passive_pair_{label}_chunked_forward",
                    "hypothesis": (
                        "Split validation should preserve the same passive-pair "
                        "edge estimate while avoiding monolithic worker memory "
                        "failure. Conservative aggregation sums chunk drawdowns "
                        "and caps capital by the worst chunk."
                    ),
                    "params": {name: str(value) for name, value in params.items()},
                    "aggregate": aggregate,
                    "chunks": rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
        print(
            f"chunked forward: score={aggregate['score']:.4f} "
            f"pnl={aggregate['pnl']:.4f} fills={aggregate['fills']} "
            f"loaded={aggregate['loaded_ratio']:.2%} status={aggregate['status']}"
        )
        print(f"Strategy chunked forward CSV: {csv_path}")
        print(f"Strategy chunked forward JSON: {json_path}")

    _run()


if __name__ == "__main__":
    run()
