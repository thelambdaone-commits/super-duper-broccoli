from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
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
    _Evaluation,
    _btc_5m_replays,
    _btc_5m_windows,
    _env_float,
    _env_int,
    _evaluation_from_worker_payload,
    _evaluate_results,
    _evaluation_row,
    _replays_from_payload,
    _replays_to_payload,
)

_DEFAULT_FORWARD_START = 1_777_258_800  # 2026-04-27T03:00:00Z
_DEFAULT_FORWARD_WINDOWS = 144
_DEFAULT_CHUNK_WINDOWS = 24
_WORKER_ENV = "TELONEX_CHURN_MICROPRICE_WORKER"
_WORKER_PARAMS_ENV = "TELONEX_CHURN_MICROPRICE_WORKER_PARAMS"
_WORKER_REPLAYS_ENV = "TELONEX_CHURN_MICROPRICE_WORKER_REPLAYS"
_WORKER_RESULT_ENV = "TELONEX_CHURN_MICROPRICE_WORKER_RESULT"
_WORKER_PHASE_ENV = "TELONEX_CHURN_MICROPRICE_WORKER_PHASE"
_WORKER_TRIAL_ID_ENV = "TELONEX_CHURN_MICROPRICE_WORKER_TRIAL_ID"

MICROPRICE_CHAMPION_PARAMS: dict[str, Any] = {
    "trade_size": Decimal("2"),
    "depth_levels": 3,
    "entry_imbalance": 0.62,
    "exit_imbalance": 0.48,
    "min_microprice_edge": 0.0015,
    "max_spread": 0.05,
    "max_entry_price": 0.90,
    "max_expected_slippage": 0.015,
    "min_holding_updates": 10,
    "reentry_cooldown_updates": 40,
    "min_holding_seconds": 10.0,
    "reentry_cooldown_seconds": 30.0,
    "take_profit": 0.015,
    "stop_loss": 0.020,
}


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_BTC_MICROPRICE_RUN_LABEL", "chunked_forward")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "chunked_forward"


def _initial_cash() -> float:
    return _env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 20.0)


def _deserialize_params(payload: dict[str, str]) -> dict[str, Any]:
    int_keys = {
        "depth_levels",
        "min_holding_updates",
        "reentry_cooldown_updates",
    }
    decimal_keys = {"trade_size"}
    params: dict[str, Any] = {}
    for name, value in payload.items():
        if name in decimal_keys:
            params[name] = Decimal(value)
        elif name in int_keys:
            params[name] = int(value)
        else:
            params[name] = float(value)
    return params


def _serialize_params(params: dict[str, Any]) -> dict[str, str]:
    return {name: str(value) for name, value in params.items()}


def _forward_params() -> dict[str, Any]:
    params = dict(MICROPRICE_CHAMPION_PARAMS)
    raw_overrides = os.getenv("TELONEX_CHURN_BTC_MICROPRICE_PARAM_OVERRIDES")
    if raw_overrides is None or raw_overrides.strip() == "":
        return params
    payload = {name: str(value) for name, value in json.loads(raw_overrides).items()}
    params.update(_deserialize_params(payload))
    return params


def _strategy_config(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_path": "strategies:BookMicropriceImbalanceStrategy",
        "config_path": "strategies:BookMicropriceImbalanceConfig",
        "config": params,
    }


def _run_experiment(
    *,
    name: str,
    replays: tuple[object, ...],
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    from prediction_market_extensions.backtesting._execution_config import (
        ExecutionModelConfig,
        StaticLatencyConfig,
    )
    from prediction_market_extensions.backtesting._experiments import (
        build_replay_experiment,
        run_experiment,
    )
    from prediction_market_extensions.backtesting._prediction_market_runner import MarketDataConfig
    from prediction_market_extensions.backtesting.data_sources import Book, Polymarket, Telonex

    result = run_experiment(
        build_replay_experiment(
            name=name,
            description=(
                "BTC 5m Telonex L2 microprice/depth-imbalance strategy with "
                "realistic passive-book execution"
            ),
            data=MarketDataConfig(
                platform=Polymarket,
                data_type=Book,
                vendor=Telonex,
                sources=("api:${TELONEX_API_KEY}",),
            ),
            replays=replays,
            strategy_configs=[_strategy_config(params)],
            initial_cash=_initial_cash(),
            probability_window=30,
            min_book_events=1,
            min_price_range=0.0,
            execution=ExecutionModelConfig(
                queue_position=True,
                latency_model=StaticLatencyConfig(
                    base_latency_ms=75.0,
                    insert_latency_ms=10.0,
                    update_latency_ms=5.0,
                    cancel_latency_ms=5.0,
                ),
            ),
            nautilus_log_level=os.getenv("TELONEX_CHURN_NAUTILUS_LOG_LEVEL", "INFO"),
            partial_message="Completed {completed} of {total} BTC 5m microprice legs.",
            return_summary_series=True,
        )
    )
    assert isinstance(result, list)
    return result


def _evaluate_trial_direct(
    *,
    trial_id: int,
    phase: str,
    replays: tuple[object, ...],
    params: dict[str, Any],
):
    results = _run_experiment(
        name=f"telonex_btc_5m_microprice_{_run_label()}_{phase}_trial_{trial_id:03d}",
        replays=replays,
        params=params,
    )
    return _evaluate_results(
        trial_id=trial_id,
        phase=phase,
        params=params,
        results=results,
        replay_count=len(replays),
    )


def _worker_payload(evaluation: object) -> dict[str, Any]:
    return {
        "score": float(getattr(evaluation, "score")),
        "pnl": float(getattr(evaluation, "pnl")),
        "max_drawdown_currency": float(getattr(evaluation, "max_drawdown_currency")),
        "fills": int(getattr(evaluation, "fills")),
        "coverage": float(getattr(evaluation, "coverage")),
        "loaded_ratio": float(getattr(evaluation, "loaded_ratio")),
        "result_count": int(getattr(evaluation, "result_count")),
        "replay_count": int(getattr(evaluation, "replay_count")),
        "rolling_cash_required": float(getattr(evaluation, "rolling_cash_required")),
        "capital_penalty": float(getattr(evaluation, "capital_penalty")),
        "status": str(getattr(evaluation, "status")),
    }


def _evaluate_trial(
    *,
    trial_id: int,
    phase: str,
    replays: tuple[object, ...],
    params: dict[str, Any],
):
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    result_path = ARTIFACT_ROOT / f".{_run_label()}-microprice-{phase}-{uuid.uuid4().hex}.json"
    env = os.environ.copy()
    env.update(
        {
            _WORKER_ENV: "1",
            _WORKER_PARAMS_ENV: json.dumps(_serialize_params(params), sort_keys=True),
            _WORKER_REPLAYS_ENV: json.dumps(_replays_to_payload(replays), sort_keys=True),
            _WORKER_RESULT_ENV: str(result_path),
            _WORKER_PHASE_ENV: phase,
            _WORKER_TRIAL_ID_ENV: str(trial_id),
            "TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK": "1",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())], env=env, check=False
    )
    if completed.returncode != 0:
        return _Evaluation(
            trial_id=trial_id,
            phase=phase,
            params=params,
            score=-1_000_000_000.0,
            pnl=0.0,
            max_drawdown_currency=0.0,
            fills=0,
            coverage=0.0,
            loaded_ratio=0.0,
            result_count=0,
            replay_count=len(replays),
            rolling_cash_required=0.0,
            capital_penalty=0.0,
            status=f"worker_error_{completed.returncode}",
        )
    try:
        payload = json.loads(result_path.read_text())
    finally:
        result_path.unlink(missing_ok=True)
    return _evaluation_from_worker_payload(
        trial_id=trial_id,
        phase=phase,
        params=params,
        payload=payload,
    )


def _aggregate_rows(rows: list[dict[str, Any]], params: dict[str, object]) -> dict[str, Any]:
    pnl = sum(float(row["pnl"]) for row in rows)
    fills = sum(int(row["fills"]) for row in rows)
    replay_count = sum(int(row["replay_count"]) for row in rows)
    result_count = sum(int(row["result_count"]) for row in rows)
    loaded_ratio = result_count / replay_count if replay_count else 0.0
    max_drawdown_currency = sum(float(row["max_drawdown_currency"]) for row in rows)
    rolling_cash_required = max((float(row["rolling_cash_required"]) for row in rows), default=0.0)
    capital_penalty = max(0.0, rolling_cash_required - _initial_cash()) * _env_float(
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
    if os.getenv(_WORKER_ENV) == "1":
        params = _deserialize_params(json.loads(os.environ[_WORKER_PARAMS_ENV]))
        replays = _replays_from_payload(json.loads(os.environ[_WORKER_REPLAYS_ENV]))
        evaluation = _evaluate_trial_direct(
            trial_id=int(os.environ[_WORKER_TRIAL_ID_ENV]),
            phase=os.environ[_WORKER_PHASE_ENV],
            replays=replays,
            params=params,
        )
        Path(os.environ[_WORKER_RESULT_ENV]).write_text(
            json.dumps(_worker_payload(evaluation), sort_keys=True)
        )
        return

    @timing_harness
    def _run() -> None:
        start = datetime.fromtimestamp(
            _env_int("TELONEX_CHURN_BTC_START", _DEFAULT_FORWARD_START),
            tz=UTC,
        )
        total_windows = _env_int(
            "TELONEX_CHURN_BTC_MICROPRICE_FORWARD_WINDOWS",
            _DEFAULT_FORWARD_WINDOWS,
        )
        chunk_windows = _env_int(
            "TELONEX_CHURN_BTC_MICROPRICE_CHUNK_WINDOWS",
            _DEFAULT_CHUNK_WINDOWS,
        )
        if total_windows < 1:
            raise ValueError("TELONEX_CHURN_BTC_MICROPRICE_FORWARD_WINDOWS must be >= 1")
        if chunk_windows < 1:
            raise ValueError("TELONEX_CHURN_BTC_MICROPRICE_CHUNK_WINDOWS must be >= 1")

        windows = _btc_5m_windows(start=start, count=total_windows)
        params = _forward_params()
        print(
            "Strategy hypothesis: short-horizon L2 depth imbalance and "
            "microprice pressure can identify prediction-market legs whose "
            "near-term repricing odds exceed visible execution cost. This is "
            "tested as a distinct directional family, not paired settlement carry."
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
                f"chunk {trial_id:03d}: score={float(evaluation.score):.4f} "
                f"pnl={float(evaluation.pnl):.4f} fills={int(evaluation.fills)} "
                f"loaded={float(evaluation.loaded_ratio):.2%} status={evaluation.status}"
            )

        aggregate = _aggregate_rows(rows, params)
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        label = _run_label()
        csv_path = ARTIFACT_ROOT / f"telonex_btc_5m_microprice_{label}_chunked_forward.csv"
        json_path = ARTIFACT_ROOT / f"telonex_btc_5m_microprice_{label}_chunked_forward.json"
        fieldnames = sorted({key for row in [aggregate, *rows] for key in row})
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(aggregate)
            writer.writerows(rows)
        json_path.write_text(
            json.dumps(
                {
                    "name": f"telonex_btc_5m_microprice_{label}_chunked_forward",
                    "hypothesis": (
                        "Short-horizon L2 depth imbalance and microprice pressure "
                        "can identify prediction-market legs whose near-term "
                        "repricing odds exceed visible execution cost."
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
            f"microprice chunked forward: score={aggregate['score']:.4f} "
            f"pnl={aggregate['pnl']:.4f} fills={aggregate['fills']} "
            f"loaded={aggregate['loaded_ratio']:.2%} status={aggregate['status']}"
        )
        print(f"Strategy chunked forward CSV: {csv_path}")
        print(f"Strategy chunked forward JSON: {json_path}")

    _run()


if __name__ == "__main__":
    run()
