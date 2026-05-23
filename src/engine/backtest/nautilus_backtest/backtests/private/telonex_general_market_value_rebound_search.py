from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
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

from backtests.polymarket_telonex_book_100_replay_runner import (  # noqa: E402
    POPULAR_MARKET_SLUGS,
    WINDOW_END,
    WINDOW_END_NS,
    WINDOW_START,
    WINDOW_START_NS,
)
from backtests.private.telonex_btc_5m_passive_pair_accumulation_search import (  # noqa: E402
    ARTIFACT_ROOT,
    _Evaluation,
    _env_float,
    _env_int,
    _evaluation_from_worker_payload,
    _evaluate_results,
    _evaluation_row,
    _replays_from_payload,
    _replays_to_payload,
)

_WORKER_ENV = "TELONEX_CHURN_GENERAL_VALUE_WORKER"
_WORKER_CANDIDATE_ENV = "TELONEX_CHURN_GENERAL_VALUE_WORKER_CANDIDATE"
_WORKER_REPLAYS_ENV = "TELONEX_CHURN_GENERAL_VALUE_WORKER_REPLAYS"
_WORKER_RESULT_ENV = "TELONEX_CHURN_GENERAL_VALUE_WORKER_RESULT"
_WORKER_PHASE_ENV = "TELONEX_CHURN_GENERAL_VALUE_WORKER_PHASE"
_WORKER_TRIAL_ID_ENV = "TELONEX_CHURN_GENERAL_VALUE_WORKER_TRIAL_ID"


@dataclass(frozen=True)
class Candidate:
    name: str
    strategy_path: str
    config_path: str
    config: dict[str, Any]


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_GENERAL_VALUE_RUN_LABEL", "general_value_rebound")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "general_value_rebound"


def _initial_cash() -> float:
    return _env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 20.0)


def _candidate_payload(candidate: Candidate) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "strategy_path": candidate.strategy_path,
        "config_path": candidate.config_path,
        "config": {name: str(value) for name, value in candidate.config.items()},
    }


def _candidate_from_payload(payload: dict[str, Any]) -> Candidate:
    decimal_keys = {"trade_size"}
    bool_keys = {"single_entry"}
    int_keys = {"drop_window", "max_holding_periods", "vwap_window"}
    config: dict[str, Any] = {}
    for name, value in dict(payload["config"]).items():
        text = str(value)
        if name in decimal_keys:
            config[name] = Decimal(text)
        elif name in bool_keys:
            config[name] = text.lower() in {"1", "true", "yes", "on"}
        elif name in int_keys:
            config[name] = int(text)
        else:
            config[name] = float(text)
    return Candidate(
        name=str(payload["name"]),
        strategy_path=str(payload["strategy_path"]),
        config_path=str(payload["config_path"]),
        config=config,
    )


def _candidates() -> list[Candidate]:
    candidates = [
        Candidate(
            name="deep_value_08_size5",
            strategy_path="strategies:BookDeepValueHoldStrategy",
            config_path="strategies:BookDeepValueHoldConfig",
            config={
                "trade_size": Decimal("5"),
                "entry_price_max": 0.08,
                "single_entry": True,
            },
        ),
        Candidate(
            name="deep_value_12_size5",
            strategy_path="strategies:BookDeepValueHoldStrategy",
            config_path="strategies:BookDeepValueHoldConfig",
            config={
                "trade_size": Decimal("5"),
                "entry_price_max": 0.12,
                "single_entry": True,
            },
        ),
        Candidate(
            name="deep_value_18_size5",
            strategy_path="strategies:BookDeepValueHoldStrategy",
            config_path="strategies:BookDeepValueHoldConfig",
            config={
                "trade_size": Decimal("5"),
                "entry_price_max": 0.18,
                "single_entry": True,
            },
        ),
        Candidate(
            name="panic_fade_22_drop4_size5",
            strategy_path="strategies:BookPanicFadeStrategy",
            config_path="strategies:BookPanicFadeConfig",
            config={
                "trade_size": Decimal("5"),
                "drop_window": 120,
                "min_drop": 0.04,
                "panic_price": 0.22,
                "rebound_exit": 0.32,
                "max_holding_periods": 2000,
                "take_profit": 0.06,
                "stop_loss": 0.03,
            },
        ),
        Candidate(
            name="panic_fade_25_drop8_size5",
            strategy_path="strategies:BookPanicFadeStrategy",
            config_path="strategies:BookPanicFadeConfig",
            config={
                "trade_size": Decimal("5"),
                "drop_window": 200,
                "min_drop": 0.08,
                "panic_price": 0.25,
                "rebound_exit": 0.35,
                "max_holding_periods": 3000,
                "take_profit": 0.08,
                "stop_loss": 0.04,
            },
        ),
        Candidate(
            name="vwap_reversion_160_size5",
            strategy_path="strategies:BookVWAPReversionStrategy",
            config_path="strategies:BookVWAPReversionConfig",
            config={
                "trade_size": Decimal("5"),
                "vwap_window": 160,
                "entry_threshold": 0.015,
                "exit_threshold": 0.004,
                "min_tick_size": 5.0,
                "take_profit": 0.03,
                "stop_loss": 0.02,
            },
        ),
    ]
    limit = _env_int("TELONEX_CHURN_GENERAL_VALUE_MAX_CANDIDATES", len(candidates))
    return candidates[: max(1, limit)]


def _strategy_config(candidate: Candidate) -> dict[str, Any]:
    return {
        "strategy_path": candidate.strategy_path,
        "config_path": candidate.config_path,
        "config": dict(candidate.config),
    }


def _market_slugs() -> tuple[str, ...]:
    limit = _env_int("TELONEX_CHURN_GENERAL_VALUE_MARKET_LIMIT", 80)
    return tuple(POPULAR_MARKET_SLUGS[: max(1, limit)])


def _replays(slugs: tuple[str, ...]) -> tuple[object, ...]:
    from prediction_market_extensions.backtesting._replay_specs import BookReplay

    return tuple(
        BookReplay(
            market_slug=slug,
            token_index=token_index,
            start_time=WINDOW_START,
            end_time=WINDOW_END,
            metadata={
                "sim_label": f"{slug}-{'yes' if token_index == 0 else 'no'}",
                "replay_window_start_ns": WINDOW_START_NS,
                "replay_window_end_ns": WINDOW_END_NS,
            },
        )
        for slug in slugs
        for token_index in (0, 1)
    )


def _run_experiment(
    *,
    name: str,
    replays: tuple[object, ...],
    candidate: Candidate,
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
                "General-market Telonex value/rebound search over popular Polymarket "
                "markets with $20 cash discipline"
            ),
            data=MarketDataConfig(
                platform=Polymarket,
                data_type=Book,
                vendor=Telonex,
                sources=("api:${TELONEX_API_KEY}",),
            ),
            replays=replays,
            strategy_configs=[_strategy_config(candidate)],
            initial_cash=_initial_cash(),
            probability_window=30,
            min_book_events=_env_int("TELONEX_CHURN_GENERAL_VALUE_MIN_BOOK_EVENTS", 25),
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
            partial_message="Completed {completed} of {total} general-market Telonex legs.",
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
    candidate: Candidate,
):
    results = _run_experiment(
        name=f"telonex_general_value_{_run_label()}_{phase}_{candidate.name}",
        replays=replays,
        candidate=candidate,
    )
    params = {
        "candidate": candidate.name,
        "strategy_path": candidate.strategy_path,
        **candidate.config,
    }
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
    candidate: Candidate,
):
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    result_path = ARTIFACT_ROOT / f".{_run_label()}-general-{phase}-{uuid.uuid4().hex}.json"
    env = os.environ.copy()
    env.update(
        {
            _WORKER_ENV: "1",
            _WORKER_CANDIDATE_ENV: json.dumps(_candidate_payload(candidate), sort_keys=True),
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
            params={"candidate": candidate.name, "strategy_path": candidate.strategy_path},
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
        params={
            "candidate": candidate.name,
            "strategy_path": candidate.strategy_path,
            **candidate.config,
        },
        payload=payload,
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run() -> None:
    from prediction_market_extensions.backtesting._timing_harness import timing_harness

    load_dotenv()
    os.environ.setdefault("TELONEX_DISABLE_POLYMARKET_TRADE_FALLBACK", "1")
    if os.getenv(_WORKER_ENV) == "1":
        candidate = _candidate_from_payload(json.loads(os.environ[_WORKER_CANDIDATE_ENV]))
        replays = _replays_from_payload(json.loads(os.environ[_WORKER_REPLAYS_ENV]))
        evaluation = _evaluate_trial_direct(
            trial_id=int(os.environ[_WORKER_TRIAL_ID_ENV]),
            phase=os.environ[_WORKER_PHASE_ENV],
            replays=replays,
            candidate=candidate,
        )
        Path(os.environ[_WORKER_RESULT_ENV]).write_text(
            json.dumps(_worker_payload(evaluation), sort_keys=True)
        )
        return

    @timing_harness
    def _run() -> None:
        slugs = _market_slugs()
        train_count = _env_int("TELONEX_CHURN_GENERAL_VALUE_TRAIN_MARKETS", 40)
        holdout_count = _env_int("TELONEX_CHURN_GENERAL_VALUE_HOLDOUT_MARKETS", 40)
        if train_count < 1 or holdout_count < 1:
            raise ValueError("train and holdout market counts must be >= 1")
        if train_count + holdout_count > len(slugs):
            raise ValueError(
                "train + holdout markets exceeds selected market limit "
                f"({train_count=} {holdout_count=} selected={len(slugs)})"
            )
        train_replays = _replays(slugs[:train_count])
        holdout_replays = _replays(slugs[train_count : train_count + holdout_count])
        candidates = _candidates()
        print(
            "Strategy hypothesis: broad event markets should offer more robust "
            "low-price convexity/rebound opportunities than BTC 5m churn. We "
            "test cheap-entry and post-panic rebound families on train markets, "
            "then rerun only top candidates unchanged on separate holdout markets."
        )

        train_rows: list[dict[str, Any]] = []
        for trial_id, candidate in enumerate(candidates, start=1):
            evaluation = _evaluate_trial(
                trial_id=trial_id,
                phase="train",
                replays=train_replays,
                candidate=candidate,
            )
            row = _evaluation_row(evaluation)
            train_rows.append(row)
            print(
                f"train {candidate.name}: score={evaluation.score:.4f} "
                f"pnl={evaluation.pnl:.4f} fills={evaluation.fills} "
                f"cash_req={evaluation.rolling_cash_required:.2f} "
                f"loaded={evaluation.loaded_ratio:.2%} status={evaluation.status}"
            )

        train_rows.sort(key=lambda row: float(row["score"]), reverse=True)
        top_k = _env_int("TELONEX_CHURN_GENERAL_VALUE_HOLDOUT_TOP_K", 2)
        candidate_by_name = {candidate.name: candidate for candidate in candidates}
        holdout_rows: list[dict[str, Any]] = []
        for rank, train_row in enumerate(train_rows[: max(1, top_k)], start=1):
            candidate = candidate_by_name[str(train_row["param_candidate"])]
            evaluation = _evaluate_trial(
                trial_id=rank,
                phase="holdout",
                replays=holdout_replays,
                candidate=candidate,
            )
            row = _evaluation_row(evaluation)
            holdout_rows.append(row)
            print(
                f"holdout {candidate.name}: score={evaluation.score:.4f} "
                f"pnl={evaluation.pnl:.4f} fills={evaluation.fills} "
                f"cash_req={evaluation.rolling_cash_required:.2f} "
                f"loaded={evaluation.loaded_ratio:.2%} status={evaluation.status}"
            )

        holdout_rows.sort(key=lambda row: float(row["score"]), reverse=True)
        label = _run_label()
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        train_csv = ARTIFACT_ROOT / f"telonex_general_value_{label}_train.csv"
        holdout_csv = ARTIFACT_ROOT / f"telonex_general_value_{label}_holdout.csv"
        summary_path = ARTIFACT_ROOT / f"telonex_general_value_{label}_summary.json"
        _write_csv(train_csv, train_rows)
        _write_csv(holdout_csv, holdout_rows)
        summary = {
            "name": f"telonex_general_value_{label}",
            "hypothesis": (
                "Broad event markets may offer robust low-price convexity and "
                "panic-rebound opportunities. Candidate selection is made on "
                "train markets and rerun unchanged on holdout markets with $20 cash."
            ),
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "train_market_count": train_count,
            "holdout_market_count": holdout_count,
            "candidate_count": len(candidates),
            "train": train_rows,
            "holdout": holdout_rows,
            "best_train": train_rows[0] if train_rows else None,
            "best_holdout": holdout_rows[0] if holdout_rows else None,
            "train_csv": str(train_csv),
            "holdout_csv": str(holdout_csv),
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
        if holdout_rows:
            best = holdout_rows[0]
            print(
                f"general value best holdout: candidate={best['param_candidate']} "
                f"score={float(best['score']):.4f} pnl={float(best['pnl']):.4f} "
                f"fills={int(best['fills'])} loaded={float(best['loaded_ratio']):.2%}"
            )
        print(f"General value summary JSON: {summary_path}")

    _run()


if __name__ == "__main__":
    run()
