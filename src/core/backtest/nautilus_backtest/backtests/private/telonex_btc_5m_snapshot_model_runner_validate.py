from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if __package__ in {None, ""}:
    import importlib.util

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
    _as_float,
    _as_int,
    _btc_5m_windows,
    _env_float,
    _env_int,
    _evaluate_results,
    _evaluation_row,
)

_DEFAULT_FORWARD_START = 1_777_320_000  # 2026-04-27T20:00:00Z
_DEFAULT_FORWARD_WINDOWS = 48
_DEFAULT_CHUNK_WINDOWS = 12
_WORKER_ENV = "TELONEX_CHURN_BTC_MODEL_RUNNER_WORKER"
_WORKER_REPLAYS_ENV = "TELONEX_CHURN_BTC_MODEL_RUNNER_WORKER_REPLAYS"
_WORKER_RESULT_ENV = "TELONEX_CHURN_BTC_MODEL_RUNNER_WORKER_RESULT"
_WORKER_CHUNK_INDEX_ENV = "TELONEX_CHURN_BTC_MODEL_RUNNER_WORKER_CHUNK_INDEX"
_WORKER_DIAGNOSTICS_ENV = "TELONEX_CHURN_BTC_MODEL_RUNNER_DIAGNOSTICS_PATH"


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_BTC_MODEL_RUNNER_LABEL", "s157_snapshot_model_runner")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "s157_snapshot_model_runner"


def _model_path() -> str:
    configured = os.getenv("TELONEX_CHURN_BTC_MODEL_RUNNER_MODEL_PATH")
    if configured:
        return configured
    return "live/models/btc_snapshot_model_s150_ev_guarded_cached_432_summary.json"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _replays(windows: tuple[tuple[str, str, str], ...]) -> tuple[object, ...]:
    from prediction_market_extensions.backtesting._replay_specs import BookReplay

    return tuple(
        BookReplay(
            market_slug=slug,
            token_index=token_index,
            start_time=start_time,
            end_time=end_time,
            metadata={"sim_label": f"{slug}-{'up' if token_index == 0 else 'down'}"},
        )
        for slug, start_time, end_time in windows
        for token_index in (0, 1)
    )


def _replays_from_payload(payload: list[dict[str, Any]]) -> tuple[object, ...]:
    from prediction_market_extensions.backtesting._replay_specs import BookReplay

    return tuple(
        BookReplay(
            market_slug=str(item["market_slug"]),
            token_index=int(item["token_index"]),
            start_time=str(item["start_time"]),
            end_time=str(item["end_time"]),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in payload
    )


def _replays_to_payload(replays: tuple[object, ...]) -> list[dict[str, Any]]:
    return [
        {
            "market_slug": getattr(replay, "market_slug"),
            "token_index": getattr(replay, "token_index"),
            "start_time": getattr(replay, "start_time"),
            "end_time": getattr(replay, "end_time"),
            "metadata": dict(getattr(replay, "metadata", None) or {}),
        }
        for replay in replays
    ]


def _snapshot_seconds() -> tuple[int, ...]:
    raw = os.getenv("TELONEX_CHURN_BTC_MODEL_RUNNER_SNAPSHOT_SECONDS", "180,120,60,30,10")
    values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not values:
        raise ValueError("TELONEX_CHURN_BTC_MODEL_RUNNER_SNAPSHOT_SECONDS cannot be empty.")
    return values


def _strategy_config() -> dict[str, Any]:
    return {
        "strategy_path": ("strategies.private.btc_snapshot_model:BookBtcSnapshotModelStrategy"),
        "config_path": ("strategies.private.btc_snapshot_model:BookBtcSnapshotModelConfig"),
        "config": {
            "instrument_ids": "__ALL_SIM_INSTRUMENT_IDS__",
            "model_path": _model_path(),
            "trade_size": Decimal(str(_env_float("TELONEX_CHURN_BTC_MODEL_QUANTITY", 2.0))),
            "edge": _env_float("TELONEX_CHURN_BTC_MODEL_RUNNER_EDGE", 0.06),
            "snapshot_seconds": _snapshot_seconds(),
            "min_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MIN_ASK_PRICE", 0.0),
            "max_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MAX_ASK_PRICE", 0.70),
            "max_spread": _env_float("TELONEX_CHURN_BTC_MODEL_RUNNER_MAX_SPREAD", 0.20),
            "max_book_age_seconds": _env_float(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MAX_BOOK_AGE_SECONDS",
                8.0,
            ),
            "depth_levels": _env_int("TELONEX_CHURN_BTC_MODEL_DEPTH_LEVELS", 5),
            "max_expected_slippage": _env_float(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MAX_EXPECTED_SLIPPAGE",
                0.02,
            ),
            "min_visible_size": _env_float(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MIN_VISIBLE_SIZE",
                1.0,
            ),
            "min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "expensive_ask_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_ASK_FLOOR",
                1.0,
            ),
            "expensive_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "expensive_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "adverse_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "adverse_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "exhausted_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "exhausted_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "volatile_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "volatile_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "max_yes_no_ask_cost": _env_float(
                "TELONEX_CHURN_BTC_MODEL_MAX_YES_NO_ASK_COST",
                0.0,
            ),
            "diagnostics_path": os.getenv(_WORKER_DIAGNOSTICS_ENV),
            "momentum_alignment": os.getenv(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MOMENTUM_ALIGNMENT",
                "none",
            ),
        },
    }


def _run_experiment(*, name: str, replays: tuple[object, ...]) -> list[dict[str, Any]]:
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
                "BTC 5m Telonex snapshot logistic model strategy with real Nautilus L2 replay"
            ),
            data=MarketDataConfig(
                platform=Polymarket,
                data_type=Book,
                vendor=Telonex,
                sources=("api:${TELONEX_API_KEY}",),
            ),
            replays=replays,
            strategy_configs=[_strategy_config()],
            initial_cash=_env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 20.0),
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
            partial_message="Completed {completed} of {total} BTC 5m model legs.",
            return_summary_series=True,
        )
    )
    assert isinstance(result, list)
    return result


def _evaluate_chunk(
    *,
    chunk_index: int,
    windows: tuple[tuple[str, str, str], ...],
) -> _Evaluation:
    replays = _replays(windows)
    results = _run_experiment(
        name=f"telonex_btc_5m_snapshot_model_{_run_label()}_chunk_{chunk_index:03d}",
        replays=replays,
    )
    return _evaluate_results(
        trial_id=1,
        phase=f"chunk_{chunk_index:03d}",
        params={
            "model_path": _model_path(),
            "trade_size": Decimal(str(_env_float("TELONEX_CHURN_BTC_MODEL_QUANTITY", 2.0))),
            "edge": _env_float("TELONEX_CHURN_BTC_MODEL_RUNNER_EDGE", 0.06),
            "min_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MIN_ASK_PRICE", 0.0),
            "max_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MAX_ASK_PRICE", 0.70),
            "momentum_alignment": os.getenv(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MOMENTUM_ALIGNMENT",
                "none",
            ),
            "expensive_ask_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_ASK_FLOOR",
                1.0,
            ),
            "expensive_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "expensive_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "adverse_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "adverse_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "exhausted_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "exhausted_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "volatile_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "volatile_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "max_yes_no_ask_cost": _env_float(
                "TELONEX_CHURN_BTC_MODEL_MAX_YES_NO_ASK_COST",
                0.0,
            ),
        },
        results=results,
        replay_count=len(replays),
    )


def _worker_payload(
    evaluation: _Evaluation,
    *,
    fill_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "score": evaluation.score,
        "pnl": evaluation.pnl,
        "max_drawdown_currency": evaluation.max_drawdown_currency,
        "fills": evaluation.fills,
        "coverage": evaluation.coverage,
        "loaded_ratio": evaluation.loaded_ratio,
        "result_count": evaluation.result_count,
        "replay_count": evaluation.replay_count,
        "rolling_cash_required": evaluation.rolling_cash_required,
        "capital_penalty": evaluation.capital_penalty,
        "status": evaluation.status,
        "fill_diagnostics": fill_diagnostics or [],
    }


def _evaluation_from_payload(
    *,
    chunk_index: int,
    payload: dict[str, Any],
) -> _Evaluation:
    return _Evaluation(
        trial_id=1,
        phase=f"chunk_{chunk_index:03d}",
        params={
            "model_path": _model_path(),
            "trade_size": Decimal(str(_env_float("TELONEX_CHURN_BTC_MODEL_QUANTITY", 2.0))),
            "edge": _env_float("TELONEX_CHURN_BTC_MODEL_RUNNER_EDGE", 0.06),
            "min_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MIN_ASK_PRICE", 0.0),
            "max_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MAX_ASK_PRICE", 0.70),
            "momentum_alignment": os.getenv(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MOMENTUM_ALIGNMENT",
                "none",
            ),
            "expensive_ask_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_ASK_FLOOR",
                1.0,
            ),
            "expensive_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "expensive_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "adverse_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "adverse_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "exhausted_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "exhausted_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "volatile_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "volatile_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "max_yes_no_ask_cost": _env_float(
                "TELONEX_CHURN_BTC_MODEL_MAX_YES_NO_ASK_COST",
                0.0,
            ),
        },
        score=float(payload["score"]),
        pnl=float(payload["pnl"]),
        max_drawdown_currency=float(payload["max_drawdown_currency"]),
        fills=int(payload["fills"]),
        coverage=float(payload["coverage"]),
        loaded_ratio=float(payload["loaded_ratio"]),
        result_count=int(payload["result_count"]),
        replay_count=int(payload["replay_count"]),
        rolling_cash_required=float(payload["rolling_cash_required"]),
        capital_penalty=float(payload["capital_penalty"]),
        status=str(payload["status"]),
    )


def _evaluate_chunk_worker(
    *,
    chunk_index: int,
    replays: tuple[object, ...],
) -> tuple[_Evaluation, list[dict[str, Any]]]:
    result_path = ARTIFACT_ROOT / f".{_run_label()}-model-runner-{uuid.uuid4().hex}.json"
    diagnostics_path = (
        ARTIFACT_ROOT / f".{_run_label()}-model-runner-{uuid.uuid4().hex}.diagnostics.json"
    )
    env = os.environ.copy()
    env.update(
        {
            _WORKER_ENV: "1",
            _WORKER_CHUNK_INDEX_ENV: str(chunk_index),
            _WORKER_REPLAYS_ENV: json.dumps(_replays_to_payload(replays), default=str),
            _WORKER_RESULT_ENV: str(result_path),
            _WORKER_DIAGNOSTICS_ENV: str(diagnostics_path),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())], env=env, check=False
    )
    try:
        if completed.returncode != 0:
            raise RuntimeError(
                f"Chunk worker {chunk_index} failed with exit code {completed.returncode}."
            )
        payload = json.loads(result_path.read_text())
        diagnostics = payload.get("fill_diagnostics") or []
        if not isinstance(diagnostics, list):
            diagnostics = []
        return _evaluation_from_payload(chunk_index=chunk_index, payload=payload), diagnostics
    finally:
        result_path.unlink(missing_ok=True)
        diagnostics_path.unlink(missing_ok=True)


def _resolved_up_from_result(result: dict[str, Any]) -> float | None:
    realized = result.get("realized_outcome")
    if not isinstance(realized, int | float):
        return None
    outcome = str(result.get("outcome") or "").strip().casefold()
    if outcome in {"up", "yes"}:
        return float(realized)
    if outcome in {"down", "no"}:
        return 1.0 - float(realized)
    return None


def _enrich_fill_diagnostics(
    *,
    diagnostics_path: Path,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not diagnostics_path.exists():
        return []
    payload = json.loads(diagnostics_path.read_text())
    raw_fills = payload.get("fills") if isinstance(payload, dict) else None
    if not isinstance(raw_fills, list):
        return []

    result_by_instrument = {
        str(result.get("instrument_id")): result
        for result in results
        if result.get("instrument_id") is not None
    }
    rows: list[dict[str, Any]] = []
    for raw_fill in raw_fills:
        if not isinstance(raw_fill, dict):
            continue
        row = dict(raw_fill)
        instrument_id = str(row.get("instrument_id") or row.get("fill_instrument_id") or "")
        result = result_by_instrument.get(instrument_id)
        if result is not None:
            contract_realized = result.get("realized_outcome")
            row["result_outcome"] = result.get("outcome")
            row["result_realized_outcome"] = contract_realized
            row["resolved_up"] = _resolved_up_from_result(result)
            row["result_pnl"] = result.get("pnl")
            row["result_fills"] = result.get("fills")
            row["settlement_pnl_applied"] = result.get("settlement_pnl_applied")
            if isinstance(contract_realized, int | float):
                row["contract_won"] = float(contract_realized) == 1.0
                fill_price = _as_float(row.get("fill_price"))
                fill_quantity = _as_float(row.get("fill_quantity"))
                fill_commission = _as_float(row.get("fill_commission"))
                row["fill_settlement_pnl_estimate"] = (
                    (float(contract_realized) * fill_quantity)
                    - (fill_price * fill_quantity)
                    - fill_commission
                )
        rows.append(row)
    return rows


def _run_worker() -> None:
    load_dotenv()
    result_path = Path(os.environ[_WORKER_RESULT_ENV])
    chunk_index = int(os.environ[_WORKER_CHUNK_INDEX_ENV])
    payload = json.loads(os.environ[_WORKER_REPLAYS_ENV])
    replays = _replays_from_payload(payload)
    results = _run_experiment(
        name=f"telonex_btc_5m_snapshot_model_{_run_label()}_chunk_{chunk_index:03d}",
        replays=replays,
    )
    evaluation = _evaluate_results(
        trial_id=1,
        phase=f"chunk_{chunk_index:03d}",
        params={
            "model_path": _model_path(),
            "trade_size": Decimal(str(_env_float("TELONEX_CHURN_BTC_MODEL_QUANTITY", 2.0))),
            "edge": _env_float("TELONEX_CHURN_BTC_MODEL_RUNNER_EDGE", 0.06),
            "min_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MIN_ASK_PRICE", 0.0),
            "max_ask_price": _env_float("TELONEX_CHURN_BTC_MODEL_MAX_ASK_PRICE", 0.70),
            "momentum_alignment": os.getenv(
                "TELONEX_CHURN_BTC_MODEL_RUNNER_MOMENTUM_ALIGNMENT",
                "none",
            ),
            "expensive_ask_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_ASK_FLOOR",
                1.0,
            ),
            "expensive_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "expensive_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "adverse_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "adverse_min_signed_momentum_30s": _env_float(
                "TELONEX_CHURN_BTC_MODEL_ADVERSE_MIN_SIGNED_MOMENTUM_30S",
                0.0,
            ),
            "exhausted_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "exhausted_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "volatile_price_diff_floor": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_PRICE_DIFF_FLOOR",
                0.0,
            ),
            "volatile_min_selected_probability": _env_float(
                "TELONEX_CHURN_BTC_MODEL_VOLATILE_MIN_SELECTED_PROBABILITY",
                0.0,
            ),
            "max_yes_no_ask_cost": _env_float(
                "TELONEX_CHURN_BTC_MODEL_MAX_YES_NO_ASK_COST",
                0.0,
            ),
        },
        results=results,
        replay_count=len(replays),
    )
    fill_diagnostics = _enrich_fill_diagnostics(
        diagnostics_path=Path(os.environ[_WORKER_DIAGNOSTICS_ENV]),
        results=results,
    )
    result_path.write_text(
        json.dumps(
            _worker_payload(evaluation, fill_diagnostics=fill_diagnostics),
            sort_keys=True,
            default=str,
        )
    )


def _aggregate(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "score": sum(_as_float(row.get("score")) for row in chunks),
        "pnl": sum(_as_float(row.get("pnl")) for row in chunks),
        "max_drawdown_currency": max(
            (_as_float(row.get("max_drawdown_currency")) for row in chunks),
            default=0.0,
        ),
        "fills": sum(_as_int(row.get("fills")) for row in chunks),
        "loaded_ratio": (
            sum(_as_float(row.get("loaded_ratio")) for row in chunks) / len(chunks)
            if chunks
            else 0.0
        ),
        "rolling_cash_required": max(
            (_as_float(row.get("rolling_cash_required")) for row in chunks),
            default=0.0,
        ),
    }


def _svg_line_chart(
    *,
    title: str,
    values: list[float],
    labels: list[str],
    width: int = 980,
    height: int = 320,
) -> str:
    if not values:
        return "<p>No chunk data was available for charting.</p>"

    padding_left = 64
    padding_right = 24
    padding_top = 34
    padding_bottom = 44
    plot_width = width - padding_left - padding_right
    plot_height = height - padding_top - padding_bottom
    min_y = min(0.0, min(values))
    max_y = max(0.0, max(values))
    if abs(max_y - min_y) < 1e-9:
        max_y += 1.0
        min_y -= 1.0

    def x_at(index: int) -> float:
        if len(values) == 1:
            return padding_left + (plot_width / 2.0)
        return padding_left + (plot_width * index / (len(values) - 1))

    def y_at(value: float) -> float:
        return padding_top + ((max_y - value) / (max_y - min_y) * plot_height)

    points = " ".join(f"{x_at(index):.2f},{y_at(value):.2f}" for index, value in enumerate(values))
    zero_y = y_at(0.0)
    last_x = x_at(len(values) - 1)
    last_y = y_at(values[-1])
    first_label = escape(labels[0]) if labels else ""
    last_label = escape(labels[-1]) if labels else ""
    return f"""
<section>
  <h2>{escape(title)}</h2>
  <svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
    <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>
    <line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{height - padding_bottom}" stroke="#8a949e"/>
    <line x1="{padding_left}" y1="{height - padding_bottom}" x2="{width - padding_right}" y2="{height - padding_bottom}" stroke="#8a949e"/>
    <line x1="{padding_left}" y1="{zero_y:.2f}" x2="{width - padding_right}" y2="{zero_y:.2f}" stroke="#c9ced6" stroke-dasharray="5 5"/>
    <polyline points="{points}" fill="none" stroke="#1769aa" stroke-width="3"/>
    <circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="4" fill="#1769aa"/>
    <text x="{padding_left}" y="22" class="chart-label">{max_y:.2f}</text>
    <text x="{padding_left}" y="{height - 16}" class="chart-label">{min_y:.2f}</text>
    <text x="{padding_left}" y="{height - 6}" class="chart-label">{first_label}</text>
    <text x="{width - padding_right}" y="{height - 6}" text-anchor="end" class="chart-label">{last_label}</text>
    <text x="{last_x:.2f}" y="{max(18, last_y - 10):.2f}" text-anchor="end" class="chart-label">final {values[-1]:.2f}</text>
  </svg>
</section>
"""


def _html_table(rows: list[tuple[str, object]]) -> str:
    body = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>" for key, value in rows
    )
    return f"<table>{body}</table>"


def _write_html_report(
    *,
    path: Path,
    summary: dict[str, Any],
    chunks: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    cumulative_pnl: list[float] = []
    running = 0.0
    chunk_labels: list[str] = []
    for row in chunks:
        running += _as_float(row.get("pnl"))
        cumulative_pnl.append(running)
        chunk_labels.append(str(row.get("chunk_start") or row.get("phase") or ""))

    aggregate = dict(summary.get("aggregate") or {})
    wins = sum(1 for row in fills if str(row.get("contract_won")).casefold() == "true")
    losses = sum(1 for row in fills if str(row.get("contract_won")).casefold() == "false")
    fill_count = wins + losses
    win_rate = (wins / fill_count) if fill_count else 0.0
    daily_stop_days = ", ".join(str(day) for day in summary.get("daily_stop_stopped_days") or [])
    summary_table = _html_table(
        [
            ("PnL", f"{_as_float(aggregate.get('pnl')):.4f}"),
            ("Fills", int(_as_int(aggregate.get("fills")))),
            ("Wins / losses", f"{wins} / {losses}"),
            ("Win rate", f"{win_rate:.2%}"),
            ("Max drawdown", f"{_as_float(aggregate.get('max_drawdown_currency')):.4f}"),
            ("Rolling cash required", f"{_as_float(aggregate.get('rolling_cash_required')):.4f}"),
            ("Loaded ratio", f"{_as_float(aggregate.get('loaded_ratio')):.2%}"),
            ("Skipped chunks", len(skipped)),
            ("Daily stop days", daily_stop_days or "none"),
            ("Model", summary.get("model_path", "")),
        ]
    )
    fill_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(row.get('slug', '')))}</td>"
        f"<td>{escape(str(row.get('selected_outcome', '')))}</td>"
        f"<td>{_as_float(row.get('selected_probability')):.3f}</td>"
        f"<td>{_as_float(row.get('selected_ask')):.3f}</td>"
        f"<td>{_as_float(row.get('model_edge')):.3f}</td>"
        f"<td>{escape(str(row.get('contract_won', '')))}</td>"
        f"<td>{_as_float(row.get('fill_settlement_pnl_estimate')):.3f}</td>"
        "</tr>"
        for row in fills[:200]
    )
    if not fill_rows:
        fill_rows = '<tr><td colspan="7">No fills.</td></tr>'

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(str(summary.get("name", "BTC snapshot model report")))}</title>
  <style>
    body {{
      color: #17212b;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 32px;
      line-height: 1.45;
    }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    section {{ margin-top: 28px; }}
    table {{
      border-collapse: collapse;
      font-size: 14px;
      width: 100%;
    }}
    th, td {{
      border-bottom: 1px solid #d9dee7;
      padding: 7px 9px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #f3f6f9; font-weight: 600; }}
    .chart-label {{ fill: #34465a; font-size: 12px; }}
    .note {{ color: #56677a; max-width: 980px; }}
  </style>
</head>
<body>
  <h1>{escape(str(summary.get("name", "BTC snapshot model report")))}</h1>
  <p class="note">{escape(str(summary.get("hypothesis", "")))}</p>
  <section>
    <h2>Summary</h2>
    {summary_table}
  </section>
  {_svg_line_chart(title="Cumulative PnL By Chunk", values=cumulative_pnl, labels=chunk_labels)}
  <section>
    <h2>First Fills</h2>
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Side</th>
          <th>Model probability</th>
          <th>Ask</th>
          <th>Edge</th>
          <th>Won</th>
          <th>Estimated PnL</th>
        </tr>
      </thead>
      <tbody>
        {fill_rows}
      </tbody>
    </table>
  </section>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> None:
    load_dotenv()
    os.environ.setdefault("TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK", "1")
    if os.getenv(_WORKER_ENV) == "1":
        _run_worker()
        return
    if not Path(_model_path()).exists():
        raise FileNotFoundError(_model_path())
    start_ts = _env_int("TELONEX_CHURN_BTC_MODEL_RUNNER_START", _DEFAULT_FORWARD_START)
    window_count = _env_int(
        "TELONEX_CHURN_BTC_MODEL_RUNNER_FORWARD_WINDOWS",
        _DEFAULT_FORWARD_WINDOWS,
    )
    chunk_windows = _env_int(
        "TELONEX_CHURN_BTC_MODEL_RUNNER_CHUNK_WINDOWS",
        _DEFAULT_CHUNK_WINDOWS,
    )
    start = datetime.fromtimestamp(start_ts, UTC)
    all_windows = _btc_5m_windows(start=start, count=window_count)
    daily_stop_loss = _env_float("TELONEX_CHURN_BTC_MODEL_DAILY_STOP_LOSS", 0.0)
    print(
        "Strategy hypothesis: the Telonex BTC snapshot classifier should remain "
        "profitable through real Nautilus/Telonex L2 replay when model edge is "
        "gated by configured ask bounds, liquidity caps, latency, and "
        f"momentum_alignment={os.getenv('TELONEX_CHURN_BTC_MODEL_RUNNER_MOMENTUM_ALIGNMENT', 'none')!r}; "
        "expensive entries may additionally require higher model probability "
        "and/or signed BTC momentum, while context-quality gates may reject "
        "adverse, exhausted, or volatile marginal entries. If configured, "
        "the runner-level daily stop evaluates resolved market PnL after each "
        "completed chunk and skips later chunks in that UTC day."
    )
    chunk_rows: list[dict[str, Any]] = []
    fill_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    daily_pnl: dict[str, float] = {}
    stopped_days: set[str] = set()
    for chunk_index, offset in enumerate(range(0, len(all_windows), chunk_windows), start=1):
        windows = all_windows[offset : offset + chunk_windows]
        if not windows:
            continue
        day_key = _parse_utc(windows[0][1]).date().isoformat()
        if daily_stop_loss > 0.0 and day_key in stopped_days:
            skipped_rows.append(
                {
                    "chunk_index": chunk_index,
                    "chunk_window_start_index": offset,
                    "chunk_window_count": len(windows),
                    "chunk_start": windows[0][1],
                    "chunk_end": str(_parse_utc(windows[-1][2]).isoformat()),
                    "day": day_key,
                    "reason": "daily_stop_loss",
                    "day_pnl": daily_pnl.get(day_key, 0.0),
                }
            )
            print(
                f"chunk {chunk_index}: skipped day={day_key} "
                f"daily_pnl={daily_pnl.get(day_key, 0.0):.4f} "
                f"stop_loss={daily_stop_loss:.4f}"
            )
            continue
        evaluation, chunk_fill_rows = _evaluate_chunk_worker(
            chunk_index=chunk_index,
            replays=_replays(windows),
        )
        row = _evaluation_row(evaluation)
        row["chunk_window_start_index"] = offset
        row["chunk_window_count"] = len(windows)
        row["chunk_start"] = windows[0][1]
        row["chunk_end"] = str((_parse_utc(windows[-1][2]) + timedelta(seconds=0)).isoformat())
        chunk_rows.append(row)
        for fill_row in chunk_fill_rows:
            fill_row["chunk_index"] = chunk_index
            fill_row["chunk_start"] = windows[0][1]
            fill_row["chunk_end"] = row["chunk_end"]
            fill_rows.append(fill_row)
        print(
            f"chunk {chunk_index}: score={evaluation.score:.4f} "
            f"pnl={evaluation.pnl:.4f} fills={evaluation.fills} "
            f"loaded={evaluation.loaded_ratio:.2%} status={evaluation.status}"
        )
        if daily_stop_loss > 0.0:
            daily_pnl[day_key] = daily_pnl.get(day_key, 0.0) + float(evaluation.pnl)
            if daily_pnl[day_key] <= -daily_stop_loss:
                stopped_days.add(day_key)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    label = _run_label()
    chunks_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_runner_{label}_chunks.csv"
    fills_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_runner_{label}_fills.csv"
    skipped_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_runner_{label}_skipped.csv"
    summary_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_runner_{label}_summary.json"
    report_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_runner_{label}_report.html"
    from backtests.private.telonex_btc_5m_snapshot_model_research import _write_csv

    _write_csv(chunks_path, chunk_rows)
    _write_csv(fills_path, fill_rows)
    _write_csv(skipped_path, skipped_rows)
    summary = {
        "name": f"telonex_btc_5m_snapshot_model_runner_{label}",
        "hypothesis": (
            "Offline BTC snapshot model edge should survive real Nautilus/Telonex "
            "L2 replay under $20 capital and realistic latency."
        ),
        "model_path": _model_path(),
        "start": start.isoformat(),
        "window_count": window_count,
        "chunk_windows": chunk_windows,
        "strategy_config": _strategy_config()["config"],
        "aggregate": _aggregate(chunk_rows),
        "chunks": chunk_rows,
        "daily_stop_loss": daily_stop_loss,
        "daily_stop_pnl_by_day": daily_pnl,
        "daily_stop_stopped_days": sorted(stopped_days),
        "skipped_chunks": skipped_rows,
        "chunks_csv": str(chunks_path),
        "fills_csv": str(fills_path),
        "skipped_csv": str(skipped_path),
        "summary_report_path": str(report_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
    _write_html_report(
        path=report_path,
        summary=summary,
        chunks=chunk_rows,
        fills=fill_rows,
        skipped=skipped_rows,
    )
    aggregate = summary["aggregate"]
    print(
        "runner aggregate: "
        f"score={aggregate['score']:.4f} pnl={aggregate['pnl']:.4f} "
        f"fills={aggregate['fills']} loaded={aggregate['loaded_ratio']:.2%}"
    )
    print(f"Snapshot model runner summary JSON: {summary_path}")
    print(f"Snapshot model runner HTML report: {report_path}")


def run() -> None:
    main()


if __name__ == "__main__":
    run()
