from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    _as_float,
    _as_int,
    _env_float,
    _env_int,
    _evaluate_results,
    _evaluation_row,
)
from prediction_market_extensions.adapters.polymarket.research import (  # noqa: E402
    discover_resolved_sports_markets,
    market_trade_window_bounds,
)

_WORKER_ENV = "TELONEX_CHURN_SPORTS_WORKER"
_WORKER_REPLAYS_ENV = "TELONEX_CHURN_SPORTS_WORKER_REPLAYS"
_WORKER_RESULT_ENV = "TELONEX_CHURN_SPORTS_WORKER_RESULT"
_WORKER_STRATEGY_ENV = "TELONEX_CHURN_SPORTS_WORKER_STRATEGY"
_WORKER_TRIAL_ID_ENV = "TELONEX_CHURN_SPORTS_WORKER_TRIAL_ID"


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_SPORTS_RUN_LABEL", "s159_resolved_sports")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "s159_resolved_sports"


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _candidate_strategies() -> list[dict[str, Any]]:
    trade_size = Decimal(str(_env_float("TELONEX_CHURN_SPORTS_TRADE_SIZE", 5.0)))
    return [
        {
            "name": "late_favorite_90_88_95",
            "strategy_path": "strategies:BookLateFavoriteTakerHoldStrategy",
            "config_path": "strategies:BookLateFavoriteTakerHoldConfig",
            "config": {
                "trade_size": trade_size,
                "activation_start_time_ns": "__SIM_METADATA__:activation_start_time_ns",
                "market_close_time_ns": "__SIM_METADATA__:market_close_time_ns",
                "min_midpoint": 0.90,
                "min_bid_price": 0.88,
                "max_entry_price": 0.95,
                "max_spread": 0.04,
                "min_visible_size": 5.0,
                "enable_cheap_no_entry": False,
            },
        },
        {
            "name": "late_favorite_92_90_96",
            "strategy_path": "strategies:BookLateFavoriteTakerHoldStrategy",
            "config_path": "strategies:BookLateFavoriteTakerHoldConfig",
            "config": {
                "trade_size": trade_size,
                "activation_start_time_ns": "__SIM_METADATA__:activation_start_time_ns",
                "market_close_time_ns": "__SIM_METADATA__:market_close_time_ns",
                "min_midpoint": 0.92,
                "min_bid_price": 0.90,
                "max_entry_price": 0.96,
                "max_spread": 0.035,
                "min_visible_size": 5.0,
                "enable_cheap_no_entry": False,
            },
        },
        {
            "name": "final_momentum_80_92_55",
            "strategy_path": "strategies:BookFinalPeriodMomentumStrategy",
            "config_path": "strategies:BookFinalPeriodMomentumConfig",
            "config": {
                "trade_size": trade_size,
                "market_close_time_ns": "__SIM_METADATA__:market_close_time_ns",
                "final_period_minutes": 30,
                "entry_price": 0.80,
                "take_profit_price": 0.92,
                "stop_loss_price": 0.55,
            },
        },
    ]


async def _discover_markets() -> list[dict[str, Any]]:
    markets = await discover_resolved_sports_markets(
        candidate_limit=_env_int("TELONEX_CHURN_SPORTS_MARKETS", 8),
        max_results=_env_int("TELONEX_CHURN_SPORTS_MAX_RESULTS", 500),
        min_volume_24h=_env_float("TELONEX_CHURN_SPORTS_MIN_VOLUME_24H", 0.0),
        max_days_since_close=_env_float("TELONEX_CHURN_SPORTS_MAX_DAYS_SINCE_CLOSE", 14.0),
        games_only=_bool_env("TELONEX_CHURN_SPORTS_GAMES_ONLY", True),
    )
    return markets


async def _build_replays() -> tuple[tuple[object, ...], list[dict[str, Any]]]:
    from prediction_market_extensions.backtesting._replay_specs import BookReplay

    active_window_hours = _env_float("TELONEX_CHURN_SPORTS_ACTIVE_WINDOW_HOURS", 2.0)
    activation_seconds = _env_int("TELONEX_CHURN_SPORTS_ACTIVATION_SECONDS", 90)
    markets = await _discover_markets()
    replays: list[object] = []
    manifest: list[dict[str, Any]] = []
    for market in markets:
        slug = str(market.get("slug") or market.get("market_slug") or "")
        if not slug:
            continue
        window_start, window_end = market_trade_window_bounds(
            market,
            active_window_hours=active_window_hours,
        )
        if window_start is None or window_end is None:
            continue
        if window_start >= window_end:
            continue
        activation_start = max(window_start, window_end - timedelta(seconds=activation_seconds))
        metadata = {
            "sim_label": slug,
            "market_close_time_ns": int(window_end.timestamp() * 1_000_000_000),
            "activation_start_time_ns": int(activation_start.timestamp() * 1_000_000_000),
        }
        for token_index in (0, 1):
            replays.append(
                BookReplay(
                    market_slug=slug,
                    token_index=token_index,
                    start_time=_utc_iso(window_start),
                    end_time=_utc_iso(window_end),
                    metadata={**metadata, "sim_label": f"{slug}-{token_index}"},
                )
            )
        manifest.append(
            {
                "slug": slug,
                "question": market.get("question"),
                "closedTime": market.get("closedTime"),
                "start": _utc_iso(window_start),
                "end": _utc_iso(window_end),
                "activation_start": _utc_iso(activation_start),
                "volume": market.get("volume"),
                "event_total_volume": market.get("event_total_volume"),
            }
        )
    return tuple(replays), manifest


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


def _run_experiment(
    *,
    name: str,
    replays: tuple[object, ...],
    strategy_spec: dict[str, Any],
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
                "Resolved sports market late-price research using Telonex API L2 book replay"
            ),
            data=MarketDataConfig(
                platform=Polymarket,
                data_type=Book,
                vendor=Telonex,
                sources=("api:${TELONEX_API_KEY}",),
            ),
            replays=replays,
            strategy_configs=[
                {
                    "strategy_path": strategy_spec["strategy_path"],
                    "config_path": strategy_spec["config_path"],
                    "config": strategy_spec["config"],
                }
            ],
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
            partial_message="Completed {completed} of {total} resolved sports legs.",
            return_summary_series=True,
        )
    )
    assert isinstance(result, list)
    return result


def _strategy_by_name(name: str) -> dict[str, Any]:
    for strategy_spec in _candidate_strategies():
        if strategy_spec["name"] == name:
            return strategy_spec
    raise KeyError(name)


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


def _evaluate_strategy_worker(
    *,
    trial_id: int,
    strategy_spec: dict[str, Any],
    replays: tuple[object, ...],
) -> dict[str, Any]:
    result_path = ARTIFACT_ROOT / f".{_run_label()}-sports-{uuid.uuid4().hex}.json"
    env = os.environ.copy()
    env.update(
        {
            _WORKER_ENV: "1",
            _WORKER_TRIAL_ID_ENV: str(trial_id),
            _WORKER_STRATEGY_ENV: str(strategy_spec["name"]),
            _WORKER_REPLAYS_ENV: json.dumps(_replays_to_payload(replays), default=str),
            _WORKER_RESULT_ENV: str(result_path),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())], env=env, check=False
    )
    try:
        if completed.returncode != 0:
            raise RuntimeError(
                f"Sports worker {strategy_spec['name']} failed with exit code "
                f"{completed.returncode}."
            )
        return json.loads(result_path.read_text())
    finally:
        result_path.unlink(missing_ok=True)


def _run_worker() -> None:
    load_dotenv()
    strategy_name = os.environ[_WORKER_STRATEGY_ENV]
    trial_id = int(os.environ[_WORKER_TRIAL_ID_ENV])
    result_path = Path(os.environ[_WORKER_RESULT_ENV])
    replays = _replays_from_payload(json.loads(os.environ[_WORKER_REPLAYS_ENV]))
    strategy_spec = _strategy_by_name(strategy_name)
    results = _run_experiment(
        name=f"telonex_resolved_sports_{_run_label()}_{strategy_spec['name']}",
        replays=replays,
        strategy_spec=strategy_spec,
    )
    evaluation = _evaluate_results(
        trial_id=trial_id,
        phase=str(strategy_spec["name"]),
        params={"strategy": strategy_spec["name"], **strategy_spec["config"]},
        results=results,
        replay_count=len(replays),
    )
    result_path.write_text(json.dumps(_worker_payload(evaluation), sort_keys=True))


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "score": sum(_as_float(row.get("score")) for row in rows),
        "pnl": sum(_as_float(row.get("pnl")) for row in rows),
        "max_drawdown_currency": max(
            (_as_float(row.get("max_drawdown_currency")) for row in rows),
            default=0.0,
        ),
        "fills": sum(_as_int(row.get("fills")) for row in rows),
        "loaded_ratio": (
            sum(_as_float(row.get("loaded_ratio")) for row in rows) / len(rows) if rows else 0.0
        ),
    }


async def _run_async() -> None:
    load_dotenv()
    os.environ.setdefault("TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK", "1")
    print(
        "Strategy hypothesis: recently resolved sports books may exhibit late "
        "favorite persistence near close. We test only markets whose outcomes "
        "should be observable by replay end, using Telonex API L2 data and $20 cash."
    )
    replays, manifest = await _build_replays()
    if not replays:
        raise RuntimeError("No resolved sports replays discovered.")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    label = _run_label()
    manifest_path = ARTIFACT_ROOT / f"telonex_resolved_sports_{label}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str))
    print(f"resolved sports markets: {len(manifest)} ({len(replays)} token replays)")

    rows: list[dict[str, Any]] = []
    for trial_id, strategy_spec in enumerate(_candidate_strategies(), start=1):
        payload = _evaluate_strategy_worker(
            trial_id=trial_id,
            strategy_spec=strategy_spec,
            replays=replays,
        )
        from backtests.private.telonex_btc_5m_passive_pair_accumulation_search import (
            _evaluation_from_worker_payload,
        )

        evaluation = _evaluation_from_worker_payload(
            trial_id=trial_id,
            phase=str(strategy_spec["name"]),
            params={"strategy": strategy_spec["name"], **strategy_spec["config"]},
            payload=payload,
        )
        row = _evaluation_row(evaluation)
        rows.append(row)
        print(
            f"{strategy_spec['name']}: score={evaluation.score:.4f} "
            f"pnl={evaluation.pnl:.4f} fills={evaluation.fills} "
            f"loaded={evaluation.loaded_ratio:.2%} status={evaluation.status}"
        )

    from backtests.private.telonex_btc_5m_snapshot_model_research import _write_csv

    rows.sort(key=lambda row: float(row["score"]), reverse=True)
    leaderboard_path = ARTIFACT_ROOT / f"telonex_resolved_sports_{label}_leaderboard.csv"
    summary_path = ARTIFACT_ROOT / f"telonex_resolved_sports_{label}_summary.json"
    _write_csv(leaderboard_path, rows)
    summary = {
        "name": f"telonex_resolved_sports_{label}",
        "hypothesis": (
            "Late favorite persistence or final-period momentum in recently resolved "
            "sports markets can be tested with observable settlement PnL."
        ),
        "manifest_json": str(manifest_path),
        "leaderboard_csv": str(leaderboard_path),
        "markets": manifest,
        "leaderboard": rows,
        "aggregate": _aggregate(rows),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
    best = rows[0]
    print(
        "best resolved sports candidate: "
        f"{best.get('phase')} score={float(best['score']):.4f} "
        f"pnl={float(best['pnl']):.4f} fills={int(best['fills'])}"
    )
    print(f"Resolved sports summary JSON: {summary_path}")


def main() -> None:
    load_dotenv()
    os.environ.setdefault("TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK", "1")
    if os.getenv(_WORKER_ENV) == "1":
        _run_worker()
        return
    asyncio.run(_run_async())


def run() -> None:
    main()


if __name__ == "__main__":
    main()
