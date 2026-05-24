from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from random import Random
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


ARTIFACT_ROOT = Path("output/telonex_churn")
_WINDOW_SIZE = timedelta(minutes=5)
_DEFAULT_START = datetime(2026, 4, 26, 18, 0, tzinfo=UTC)
_WORKER_ENV = "TELONEX_CHURN_PASSIVE_PAIR_WORKER"
_WORKER_PARAMS_ENV = "TELONEX_CHURN_PASSIVE_PAIR_WORKER_PARAMS"
_WORKER_REPLAYS_ENV = "TELONEX_CHURN_PASSIVE_PAIR_WORKER_REPLAYS"
_WORKER_RESULT_ENV = "TELONEX_CHURN_PASSIVE_PAIR_WORKER_RESULT"
_WORKER_PHASE_ENV = "TELONEX_CHURN_PASSIVE_PAIR_WORKER_PHASE"
_WORKER_TRIAL_ID_ENV = "TELONEX_CHURN_PASSIVE_PAIR_WORKER_TRIAL_ID"
_RUN_LABEL_ENV = "TELONEX_CHURN_BTC_PASSIVE_PAIR_RUN_LABEL"

PASSIVE_PAIR_CHAMPION_PARAMS: dict[str, Any] = {
    "trade_size": Decimal("5"),
    "min_settlement_edge": 0.02,
    "max_total_cost": 0.92,
    "min_leg_price": 0.01,
    "max_leg_price": 0.90,
    "min_spread": 0.01,
    "max_spread": 0.08,
    "min_visible_size": 25.0,
    "depth_levels": 4,
    "min_bid_depth": 80.0,
    "min_pair_updates_before_entry": 12,
    "max_leg_update_gap": 0,
    "quote_improvement_ticks": 1,
    "ask_buffer_ticks": 1,
    "entry_refresh_updates": 12,
    "pair_completion_timeout_updates": 260,
    "exit_unmatched_surplus": True,
    "cancel_pair_on_leg_failure": False,
    "max_entries_per_pair": 1,
    "reentry_cooldown_updates": 180,
    "include_maker_fees_in_signal": True,
}


@dataclass(frozen=True)
class _Evaluation:
    trial_id: int
    phase: str
    params: dict[str, Any]
    score: float
    pnl: float
    max_drawdown_currency: float
    fills: int
    coverage: float
    loaded_ratio: float
    result_count: int
    replay_count: int
    rolling_cash_required: float
    capital_penalty: float
    status: str


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _initial_cash() -> float:
    return _env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 1_000.0)


def _run_label() -> str:
    label = os.getenv(_RUN_LABEL_ENV, "s104_depth_warmup")
    safe_label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in label.strip()
    ).strip("_")
    return safe_label or "s104_depth_warmup"


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _start_time() -> datetime:
    raw = os.getenv("TELONEX_CHURN_BTC_START")
    if raw is None or raw.strip() == "":
        return _DEFAULT_START
    return datetime.fromtimestamp(int(raw), tz=UTC)


def _btc_5m_windows(*, start: datetime, count: int) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            f"btc-updown-5m-{int(window_start.timestamp())}",
            _utc_iso(window_start),
            _utc_iso(window_start + _WINDOW_SIZE),
        )
        for index in range(count)
        for window_start in (start + (index * _WINDOW_SIZE),)
    )


def _btc_5m_replays(windows: tuple[tuple[str, str, str], ...]) -> tuple[object, ...]:
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


def _candidate(**overrides: Any) -> dict[str, Any]:
    params = dict(PASSIVE_PAIR_CHAMPION_PARAMS)
    params.update(overrides)
    return params


def _parameter_samples(*, max_trials: int, random_seed: int) -> list[dict[str, Any]]:
    rng = Random(random_seed)
    seeded_candidates = [
        _candidate(),
        _candidate(max_leg_update_gap=4),
        _candidate(max_leg_update_gap=8),
        _candidate(max_leg_update_gap=12),
        _candidate(max_leg_update_gap=16),
        _candidate(trade_size=Decimal("3"), max_entries_per_pair=1),
        _candidate(trade_size=Decimal("2"), max_entries_per_pair=1),
        _candidate(
            trade_size=Decimal("3"),
            max_entries_per_pair=1,
            quote_improvement_ticks=0,
            ask_buffer_ticks=2,
        ),
        _candidate(min_bid_depth=25.0),
        _candidate(min_bid_depth=55.0, min_pair_updates_before_entry=16),
        _candidate(depth_levels=5, min_bid_depth=55.0, min_pair_updates_before_entry=16),
        _candidate(depth_levels=5, min_bid_depth=100.0, max_leg_update_gap=8),
        _candidate(max_leg_update_gap=8, exit_unmatched_surplus=False),
        _candidate(
            max_leg_update_gap=4, exit_unmatched_surplus=False, cancel_pair_on_leg_failure=True
        ),
        _candidate(
            max_leg_update_gap=8, exit_unmatched_surplus=False, cancel_pair_on_leg_failure=True
        ),
        _candidate(min_pair_updates_before_entry=16),
        _candidate(
            max_total_cost=0.90,
            depth_levels=4,
            min_bid_depth=80.0,
            entry_refresh_updates=20,
            max_leg_update_gap=8,
        ),
    ]
    spaces: dict[str, tuple[Any, ...]] = {
        "trade_size": (Decimal("2"), Decimal("3"), Decimal("5"), Decimal("7.5"), Decimal("10")),
        "min_settlement_edge": (0.020, 0.035, 0.050),
        "max_total_cost": (0.900, 0.920, 0.940),
        "min_leg_price": (0.010, 0.030),
        "max_leg_price": (0.900, 0.950),
        "min_spread": (0.010, 0.020),
        "max_spread": (0.080, 0.100, 0.140),
        "min_visible_size": (10.0, 15.0, 25.0),
        "depth_levels": (3, 4, 5),
        "min_bid_depth": (40.0, 55.0, 80.0, 100.0),
        "min_pair_updates_before_entry": (8, 12, 16, 32),
        "max_leg_update_gap": (0, 4, 8, 12, 16),
        "quote_improvement_ticks": (0, 1),
        "ask_buffer_ticks": (1, 2, 3),
        "entry_refresh_updates": (8, 12, 20),
        "pair_completion_timeout_updates": (180, 260, 360),
        "exit_unmatched_surplus": (True, False),
        "cancel_pair_on_leg_failure": (True, False),
        "max_entries_per_pair": (1, 2),
        "reentry_cooldown_updates": (120, 180, 260),
        "include_maker_fees_in_signal": (True,),
    }

    samples: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(params: dict[str, Any]) -> None:
        if len(samples) >= max_trials:
            return
        if params["min_settlement_edge"] > 1.0 - params["max_total_cost"] + 0.02:
            return
        if params["min_spread"] >= params["max_spread"]:
            return
        if params["min_leg_price"] >= params["max_leg_price"]:
            return
        canonical = json.dumps({k: str(v) for k, v in sorted(params.items())}, sort_keys=True)
        if canonical in seen:
            return
        seen.add(canonical)
        samples.append(params)

    for params in seeded_candidates:
        add(params)

    attempts = 0
    while len(samples) < max_trials and attempts < max_trials * 250:
        attempts += 1
        add({name: rng.choice(values) for name, values in spaces.items()})
    return samples


def _serialize_params(params: dict[str, Any]) -> dict[str, str]:
    return {name: str(value) for name, value in params.items()}


def _deserialize_params(payload: dict[str, str]) -> dict[str, Any]:
    int_keys = {
        "ask_buffer_ticks",
        "depth_levels",
        "entry_refresh_updates",
        "pair_completion_timeout_updates",
        "max_entries_per_pair",
        "max_leg_update_gap",
        "quote_improvement_ticks",
        "reentry_cooldown_updates",
        "min_pair_updates_before_entry",
    }
    bool_keys = {
        "cancel_pair_on_leg_failure",
        "exit_unmatched_surplus",
        "include_maker_fees_in_signal",
    }
    decimal_keys = {"trade_size"}
    params: dict[str, Any] = {}
    for name, value in payload.items():
        if name in decimal_keys:
            params[name] = Decimal(value)
        elif name in int_keys:
            params[name] = int(value)
        elif name in bool_keys:
            params[name] = value == "True"
        else:
            params[name] = float(value)
    return params


def _strategy_config(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_path": (
            "strategies.private.passive_pair_accumulation:BookPassivePairAccumulationStrategy"
        ),
        "config_path": (
            "strategies.private.passive_pair_accumulation:BookPassivePairAccumulationConfig"
        ),
        "config": {
            "instrument_ids": "__ALL_SIM_INSTRUMENT_IDS__",
            "pairing_mode": "sequential",
            **params,
        },
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
                "BTC 5m complementary-token passive maker pair accumulation "
                "with Telonex API-only book replay"
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
            partial_message="Completed {completed} of {total} BTC 5m passive pair legs.",
            return_summary_series=True,
        )
    )
    assert isinstance(result, list)
    return result


def _as_float(value: object, *, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _as_int(value: object, *, default: int = 0) -> int:
    return int(value) if isinstance(value, int | float) else default


def _parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _event_side(result: dict[str, Any], event: dict[str, Any]) -> str:
    side = str(event.get("side") or "").strip().casefold()
    if side in {"yes", "no"}:
        return side
    return "yes" if int(result.get("token_index") or 0) == 0 else "no"


def _rolling_cash_required(results: list[dict[str, Any]]) -> float:
    merge_matched_pairs = os.getenv("TELONEX_CHURN_BTC_MERGE_MATCHED_PAIRS", "1") != "0"
    merge_delay_seconds = _env_float("TELONEX_CHURN_BTC_MERGE_DELAY_SECONDS", 30.0)
    cash_events: list[tuple[datetime, float]] = []
    positions: dict[str, dict[str, float]] = {}
    merged_by_slug: dict[str, float] = {}

    fill_rows: list[tuple[datetime, str, str, str, float, float, float]] = []
    for result in results:
        slug = str(result.get("slug") or result.get("market") or result.get("instrument_id"))
        for event in result.get("fill_events") or []:
            if not isinstance(event, dict):
                continue
            timestamp = _parse_time(event.get("timestamp"))
            if timestamp is None:
                continue
            quantity = _as_float(event.get("quantity"))
            price = _as_float(event.get("price"))
            if quantity <= 0.0 or price <= 0.0:
                continue
            commission = _as_float(event.get("commission"))
            action = str(event.get("action") or "buy").strip().casefold()
            fill_rows.append(
                (timestamp, slug, _event_side(result, event), action, price, quantity, commission)
            )

    for timestamp, slug, side, action, price, quantity, commission in sorted(fill_rows):
        notional = price * quantity
        if action == "sell":
            cash_events.append((timestamp, notional - commission))
            state = positions.setdefault(slug, {"yes": 0.0, "no": 0.0})
            state[side] = max(0.0, state.get(side, 0.0) - quantity)
            continue

        cash_events.append((timestamp, -notional - commission))
        state = positions.setdefault(slug, {"yes": 0.0, "no": 0.0})
        state[side] = state.get(side, 0.0) + quantity
        if not merge_matched_pairs:
            continue
        matched = min(state.get("yes", 0.0), state.get("no", 0.0))
        already_merged = merged_by_slug.get(slug, 0.0)
        newly_mergeable = max(0.0, matched - already_merged)
        if newly_mergeable <= 0.0:
            continue
        merged_by_slug[slug] = already_merged + newly_mergeable
        cash_events.append((timestamp + timedelta(seconds=merge_delay_seconds), newly_mergeable))

    cash_balance = 0.0
    min_cash_balance = 0.0
    for _, amount in sorted(cash_events):
        cash_balance += amount
        min_cash_balance = min(min_cash_balance, cash_balance)
    return -min_cash_balance


def _evaluate_results(
    *,
    trial_id: int,
    phase: str,
    params: dict[str, Any],
    results: list[dict[str, Any]],
    replay_count: int,
) -> _Evaluation:
    from prediction_market_extensions.backtesting._optimizer import (
        _joint_portfolio_drawdown,
        _score_result,
    )

    result_count = len(results)
    loaded_ratio = result_count / replay_count if replay_count else 0.0
    pnl = sum(_as_float(result.get("pnl")) for result in results)
    fills = sum(_as_int(result.get("fills")) for result in results)
    coverages = [_as_float(result.get("requested_coverage_ratio")) for result in results]
    coverage = sum(coverages) / len(coverages) if coverages else 0.0
    drawdown = _joint_portfolio_drawdown([result.get("equity_series") for result in results])
    terminated = any(bool(result.get("terminated_early")) for result in results)
    min_fills = _env_int("TELONEX_CHURN_BTC_MIN_FILLS", 2)
    initial_cash = _initial_cash()
    score = _score_result(
        pnl=pnl,
        max_drawdown_currency=drawdown,
        fills=fills,
        requested_coverage_ratio=coverage,
        terminated_early=terminated,
        initial_cash=initial_cash,
        min_fills_per_window=min_fills,
    )
    rolling_cash_required = _rolling_cash_required(results)
    capital_penalty = max(0.0, rolling_cash_required - initial_cash) * _env_float(
        "TELONEX_CHURN_BTC_CAPITAL_PENALTY_MULTIPLIER",
        10.0,
    )
    score -= capital_penalty
    min_loaded_ratio = _env_float("TELONEX_CHURN_BTC_MIN_LOADED_RATIO", 0.70)
    status = "ok"
    if loaded_ratio < min_loaded_ratio:
        score -= 1_000.0 * (min_loaded_ratio - loaded_ratio) * 10.0
        status = "low_loaded_ratio"
    elif result_count < replay_count:
        score -= 1_000.0 * (1.0 - loaded_ratio)
        status = "partial"
    return _Evaluation(
        trial_id=trial_id,
        phase=phase,
        params=params,
        score=score,
        pnl=pnl,
        max_drawdown_currency=drawdown,
        fills=fills,
        coverage=coverage,
        loaded_ratio=loaded_ratio,
        result_count=result_count,
        replay_count=replay_count,
        rolling_cash_required=rolling_cash_required,
        capital_penalty=capital_penalty,
        status=status,
    )


def _worker_payload(evaluation: _Evaluation) -> dict[str, Any]:
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
    }


def _evaluation_from_worker_payload(
    *,
    trial_id: int,
    phase: str,
    params: dict[str, Any],
    payload: dict[str, Any],
) -> _Evaluation:
    return _Evaluation(
        trial_id=trial_id,
        phase=phase,
        params=params,
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


def _evaluate_trial_direct(
    *,
    trial_id: int,
    phase: str,
    replays: tuple[object, ...],
    params: dict[str, Any],
) -> _Evaluation:
    results = _run_experiment(
        name=(
            f"telonex_btc_5m_passive_pair_accumulation_{_run_label()}_{phase}_trial_{trial_id:03d}"
        ),
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


def _evaluate_trial(
    *,
    trial_id: int,
    phase: str,
    replays: tuple[object, ...],
    params: dict[str, Any],
) -> _Evaluation:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    result_path = (
        ARTIFACT_ROOT / f".{_run_label()}-worker-{phase}-{trial_id:03d}-{uuid.uuid4().hex}.json"
    )
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


def _evaluation_row(evaluation: _Evaluation) -> dict[str, Any]:
    return {
        "trial_id": evaluation.trial_id,
        "phase": evaluation.phase,
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
        **{f"param_{name}": str(value) for name, value in evaluation.params.items()},
    }


def _write_artifacts(evaluations: list[_Evaluation]) -> tuple[Path, Path]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    label = _run_label()
    csv_path = ARTIFACT_ROOT / f"telonex_btc_5m_passive_pair_accumulation_{label}_leaderboard.csv"
    json_path = ARTIFACT_ROOT / f"telonex_btc_5m_passive_pair_accumulation_{label}_summary.json"
    rows = [_evaluation_row(evaluation) for evaluation in evaluations]
    fieldnames = sorted({key for row in rows for key in row})
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    train_rows = [evaluation for evaluation in evaluations if evaluation.phase == "train"]
    holdout_rows = [evaluation for evaluation in evaluations if evaluation.phase == "holdout"]
    best_holdout = max(holdout_rows, key=lambda item: item.score, default=None)
    best_train = max(train_rows, key=lambda item: item.score, default=None)
    payload = {
        "name": f"telonex_btc_5m_passive_pair_accumulation_{label}",
        "hypothesis": (
            "BTC UP/DOWN 5-minute contracts can offer settlement-carry when "
            "both complementary legs can be passively accumulated below one "
            "unit after fees. The current champion adds L2 bid-depth and "
            "book-warmup gates to avoid single-level stale liquidity and reduce "
            "unmatched-leg risk without changing the paired-bid carry logic."
        ),
        "evaluations": rows,
        "best_train": _evaluation_row(best_train) if best_train is not None else None,
        "best_holdout": _evaluation_row(best_holdout) if best_holdout is not None else None,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return csv_path, json_path


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
        max_trials = _env_int("TELONEX_CHURN_BTC_PASSIVE_PAIR_MAX_TRIALS", 6)
        holdout_top_k = _env_int("TELONEX_CHURN_BTC_PASSIVE_PAIR_HOLDOUT_TOP_K", 2)
        train_count = _env_int("TELONEX_CHURN_BTC_PASSIVE_PAIR_TRAIN_WINDOWS", 48)
        holdout_count = _env_int("TELONEX_CHURN_BTC_PASSIVE_PAIR_HOLDOUT_WINDOWS", 24)
        windows = _btc_5m_windows(start=_start_time(), count=train_count + holdout_count)
        train_replays = _btc_5m_replays(windows[:train_count])
        holdout_replays = _btc_5m_replays(windows[train_count:])
        params_list = _parameter_samples(
            max_trials=max_trials,
            random_seed=_env_int("TELONEX_CHURN_RANDOM_SEED", 20260580),
        )

        print(
            "Strategy hypothesis: durable edge is settlement carry from "
            "passively buying both BTC 5m complementary legs below one unit. "
            "Depth and warmup variants should improve it only if they cut "
            "unmatched single-leg fills without destroying paired fill rate."
        )
        evaluations: list[_Evaluation] = []
        for trial_id, params in enumerate(params_list, start=1):
            evaluation = _evaluate_trial(
                trial_id=trial_id,
                phase="train",
                replays=train_replays,
                params=params,
            )
            evaluations.append(evaluation)
            print(
                f"train trial {trial_id:03d}: score={evaluation.score:.4f} "
                f"pnl={evaluation.pnl:.4f} fills={evaluation.fills} "
                f"loaded={evaluation.loaded_ratio:.2%} status={evaluation.status}"
            )

        eligible_holdouts = [
            evaluation
            for evaluation in sorted(evaluations, key=lambda item: item.score, reverse=True)
            if evaluation.score > 0.0 and evaluation.pnl > 0.0 and evaluation.fills >= 4
        ][:holdout_top_k]
        for evaluation in eligible_holdouts:
            holdout = _evaluate_trial(
                trial_id=evaluation.trial_id,
                phase="holdout",
                replays=holdout_replays,
                params=evaluation.params,
            )
            evaluations.append(holdout)
            print(
                f"holdout trial {holdout.trial_id:03d}: score={holdout.score:.4f} "
                f"pnl={holdout.pnl:.4f} fills={holdout.fills} "
                f"loaded={holdout.loaded_ratio:.2%} status={holdout.status}"
            )
        if not eligible_holdouts:
            print("No train candidate cleared positive-score and positive-PnL holdout gate.")

        csv_path, json_path = _write_artifacts(evaluations)
        print(f"Strategy {_run_label()} leaderboard CSV: {csv_path}")
        print(f"Strategy {_run_label()} summary JSON: {json_path}")

    _run()


if __name__ == "__main__":
    run()
