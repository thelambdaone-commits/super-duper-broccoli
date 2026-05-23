from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

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

from backtests.private.telonex_btc_5m_snapshot_model_research import (  # noqa: E402
    ARTIFACT_ROOT,
    _FEATURE_COLUMNS,
    _classification_metrics,
    _env_float,
    _env_int,
    _evaluate_policy,
    _feature_columns,
    _fit_logistic,
    _json_default,
    _policy_grid,
    _predict,
    _write_csv,
)


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_BTC_WALKFORWARD_RUN_LABEL", "s154_snapshot_walkforward")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "s154_snapshot_walkforward"


def _latest_dataset_path() -> Path:
    configured = os.getenv("TELONEX_CHURN_BTC_WALKFORWARD_DATASET")
    if configured:
        path = Path(configured)
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    paths = sorted(
        ARTIFACT_ROOT.glob("telonex_btc_5m_snapshot_model_*_dataset.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        raise FileNotFoundError(
            "No snapshot model dataset found. Run "
            "backtests/private/telonex_btc_5m_snapshot_model_research.py first."
        )
    return paths[0]


def _parse_value(key: str, value: str) -> Any:
    if key == "slug":
        return value
    if value == "":
        return math.nan
    if key in {"market_index", "market_start_ts", "seconds_left", "snapshot_ts"}:
        return int(float(value))
    try:
        return float(value)
    except ValueError:
        return value


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        rows = [
            {key: _parse_value(key, value) for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]
    if not rows:
        raise RuntimeError(f"Dataset has no rows: {path}")
    return rows


def _summary_path_for_dataset(path: Path) -> Path | None:
    name = path.name
    prefix = "telonex_btc_5m_snapshot_model_"
    suffix = "_dataset.csv"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    label = name[len(prefix) : -len(suffix)]
    return path.with_name(f"{prefix}{label}_summary.json")


def _feature_columns_for_dataset(path: Path, rows: list[dict[str, Any]]) -> tuple[str, ...]:
    summary_path = _summary_path_for_dataset(path)
    if summary_path is not None and summary_path.exists():
        payload = json.loads(summary_path.read_text())
        features = payload.get("features")
        if isinstance(features, list | tuple) and all(isinstance(item, str) for item in features):
            return tuple(features)
    columns = _feature_columns()
    missing = sorted(set(columns).difference(rows[0]))
    if not missing:
        return columns
    base_missing = sorted(set(_FEATURE_COLUMNS).difference(rows[0]))
    if base_missing:
        raise RuntimeError(f"Dataset is missing required columns: {base_missing}")
    return _FEATURE_COLUMNS


def _date(value: int) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _fold_rows(
    rows: list[dict[str, Any]],
    *,
    indexes: list[int],
    start: int,
    train_windows: int,
    validation_windows: int,
    holdout_windows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    train_indexes = set(indexes[start : start + train_windows])
    validation_start = start + train_windows
    validation_indexes = set(indexes[validation_start : validation_start + validation_windows])
    holdout_start = validation_start + validation_windows
    holdout_indexes = set(indexes[holdout_start : holdout_start + holdout_windows])
    train_rows = [row for row in rows if int(row["market_index"]) in train_indexes]
    validation_rows = [row for row in rows if int(row["market_index"]) in validation_indexes]
    holdout_rows = [row for row in rows if int(row["market_index"]) in holdout_indexes]
    return train_rows, validation_rows, holdout_rows


def _chunked_validation_rows(
    rows: list[dict[str, Any]],
    *,
    indexes: list[int],
    start: int,
    windows: int,
    chunk_windows: int,
    min_rows: int,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    end = start + windows
    for offset in range(start, end, chunk_windows):
        chunk_indexes = set(indexes[offset : min(offset + chunk_windows, end)])
        chunk_rows = [row for row in rows if int(row["market_index"]) in chunk_indexes]
        if len(chunk_rows) >= min_rows:
            chunks.append(chunk_rows)
    return chunks


def _stable_policy_rows(
    validation_chunks: list[list[dict[str, Any]]],
    validation_chunk_probs: list[Any],
    grid: list[Any],
    policy_kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for policy in grid:
        evaluations = [
            _evaluate_policy(chunk_rows, chunk_probs, policy, **policy_kwargs)
            for chunk_rows, chunk_probs in zip(
                validation_chunks,
                validation_chunk_probs,
                strict=True,
            )
        ]
        score_values = [float(row["score"]) for row in evaluations]
        pnl_values = [float(row["pnl"]) for row in evaluations]
        trades = sum(int(row["trades"]) for row in evaluations)
        wins = sum(int(row["wins"]) for row in evaluations)
        rows.append(
            {
                "policy": policy.name,
                "edge": policy.edge,
                "seconds_left": ",".join(str(value) for value in policy.seconds_left),
                "validation_chunk_count": len(evaluations),
                "median_validation_chunk_score": median(score_values)
                if score_values
                else -math.inf,
                "worst_validation_chunk_score": min(score_values, default=-math.inf),
                "total_validation_chunk_score": sum(score_values),
                "median_validation_chunk_pnl": median(pnl_values) if pnl_values else 0.0,
                "worst_validation_chunk_pnl": min(pnl_values, default=0.0),
                "total_validation_chunk_pnl": sum(pnl_values),
                "profitable_validation_chunks": sum(1 for value in pnl_values if value > 0.0),
                "trades": trades,
                "wins": wins,
                "win_rate": wins / trades if trades else 0.0,
            }
        )
    rows.sort(
        key=lambda row: (
            float(row["median_validation_chunk_score"]),
            float(row["worst_validation_chunk_score"]),
            float(row["total_validation_chunk_score"]),
            int(row["profitable_validation_chunks"]),
            int(row["trades"]),
        ),
        reverse=True,
    )
    return rows


def _aggregate_selected(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnl_values = [float(row["pnl"]) for row in rows]
    score_values = [float(row["score"]) for row in rows]
    dd_values = [float(row["max_drawdown_currency"]) for row in rows]
    trades = sum(int(row["trades"]) for row in rows)
    wins = sum(int(row["wins"]) for row in rows)
    policy_counts = Counter(str(row["policy"]) for row in rows)
    return {
        "folds": len(rows),
        "profitable_folds": sum(1 for value in pnl_values if value > 0.0),
        "losing_folds": sum(1 for value in pnl_values if value < 0.0),
        "total_pnl": sum(pnl_values),
        "median_fold_pnl": median(pnl_values) if pnl_values else 0.0,
        "worst_fold_pnl": min(pnl_values, default=0.0),
        "best_fold_pnl": max(pnl_values, default=0.0),
        "total_score": sum(score_values),
        "median_fold_score": median(score_values) if score_values else 0.0,
        "max_fold_drawdown_currency": max(dd_values, default=0.0),
        "trades": trades,
        "wins": wins,
        "win_rate": wins / trades if trades else 0.0,
        "policy_frequency": dict(policy_counts.most_common()),
    }


def main() -> None:
    dataset_path = _latest_dataset_path()
    rows = _read_rows(dataset_path)
    feature_columns = _feature_columns_for_dataset(dataset_path, rows)
    required = {*feature_columns, "yes_ask", "no_ask", "resolved_up", "market_index"}
    missing = sorted(required.difference(rows[0]))
    if missing:
        raise RuntimeError(f"Dataset is missing required columns: {missing}")
    indexes = sorted({int(row["market_index"]) for row in rows})
    snapshot_seconds = tuple(sorted({int(row["seconds_left"]) for row in rows}, reverse=True))
    train_windows = _env_int("TELONEX_CHURN_BTC_WALKFORWARD_TRAIN_WINDOWS", 192)
    validation_windows = _env_int("TELONEX_CHURN_BTC_WALKFORWARD_VALIDATION_WINDOWS", 72)
    holdout_windows = _env_int("TELONEX_CHURN_BTC_WALKFORWARD_HOLDOUT_WINDOWS", 24)
    step_windows = _env_int("TELONEX_CHURN_BTC_WALKFORWARD_STEP_WINDOWS", holdout_windows)
    if min(train_windows, validation_windows, holdout_windows, step_windows) <= 0:
        raise ValueError("Walk-forward window sizes must be positive.")
    min_rows = _env_int("TELONEX_CHURN_BTC_WALKFORWARD_MIN_ROWS", 40)
    selector = os.getenv("TELONEX_CHURN_BTC_WALKFORWARD_SELECTOR", "aggregate_validation")
    validation_chunk_windows = _env_int(
        "TELONEX_CHURN_BTC_WALKFORWARD_VALIDATION_CHUNK_WINDOWS",
        min(validation_windows, holdout_windows),
    )
    min_chunk_rows = _env_int("TELONEX_CHURN_BTC_WALKFORWARD_MIN_CHUNK_ROWS", 8)
    policy_kwargs = {
        "quantity": _env_float("TELONEX_CHURN_BTC_MODEL_QUANTITY", 2.0),
        "initial_cash": _env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 20.0),
        "taker_fee_rate": _env_float("TELONEX_CHURN_BTC_MODEL_TAKER_FEE_RATE", 0.0),
        "settlement_delay_seconds": _env_int(
            "TELONEX_CHURN_BTC_MODEL_SETTLEMENT_DELAY_SECONDS",
            60,
        ),
    }
    grid = _policy_grid(snapshot_seconds)
    fold_rows: list[dict[str, Any]] = []
    fold_policy_rows: list[dict[str, Any]] = []
    stop = len(indexes) - train_windows - validation_windows - holdout_windows
    print(
        "Strategy hypothesis: a Telonex BTC 5m snapshot logistic edge can be "
        "trusted only if policy selection on a validation block carries into "
        "successive unseen forward blocks, not just one lucky holdout."
    )
    for fold_index, start in enumerate(range(0, stop + 1, step_windows), start=1):
        train_rows, validation_rows, holdout_rows = _fold_rows(
            rows,
            indexes=indexes,
            start=start,
            train_windows=train_windows,
            validation_windows=validation_windows,
            holdout_windows=holdout_windows,
        )
        if min(len(train_rows), len(validation_rows), len(holdout_rows)) < min_rows:
            continue
        model = _fit_logistic(
            train_rows,
            columns=feature_columns,
            learning_rate=_env_float("TELONEX_CHURN_BTC_MODEL_LEARNING_RATE", 0.05),
            steps=_env_int("TELONEX_CHURN_BTC_MODEL_STEPS", 1200),
            l2=_env_float("TELONEX_CHURN_BTC_MODEL_L2", 0.002),
        )
        validation_probs = _predict(model, validation_rows)
        holdout_probs = _predict(model, holdout_rows)
        validation_policy_rows = [
            _evaluate_policy(validation_rows, validation_probs, policy, **policy_kwargs)
            for policy in grid
        ]
        validation_policy_rows.sort(key=lambda row: float(row["score"]), reverse=True)
        if selector == "median_validation_chunk_score":
            validation_start = start + train_windows
            validation_chunks = _chunked_validation_rows(
                rows,
                indexes=indexes,
                start=validation_start,
                windows=validation_windows,
                chunk_windows=validation_chunk_windows,
                min_rows=min_chunk_rows,
            )
            if len(validation_chunks) < 2:
                raise RuntimeError(
                    "Stable selector needs at least two validation chunks. "
                    f"Got {len(validation_chunks)} chunks for fold {fold_index}."
                )
            validation_chunk_probs = [
                _predict(model, chunk_rows) for chunk_rows in validation_chunks
            ]
            stable_policy_rows = _stable_policy_rows(
                validation_chunks,
                validation_chunk_probs,
                grid,
                policy_kwargs,
            )
            selected_policy_name = str(stable_policy_rows[0]["policy"])
            for row in stable_policy_rows:
                fold_policy_rows.append(
                    {"fold": fold_index, "split": "validation_stability", **row}
                )
        else:
            selected_policy_name = str(validation_policy_rows[0]["policy"])
        selected_policy = next(policy for policy in grid if policy.name == selected_policy_name)
        selected_holdout = _evaluate_policy(
            holdout_rows,
            holdout_probs,
            selected_policy,
            **policy_kwargs,
        )
        holdout_policy_rows = [
            _evaluate_policy(holdout_rows, holdout_probs, policy, **policy_kwargs)
            for policy in grid
        ]
        holdout_policy_rows.sort(key=lambda row: float(row["score"]), reverse=True)
        train_start_ts = min(int(row["market_start_ts"]) for row in train_rows)
        train_end_ts = max(int(row["market_start_ts"]) for row in train_rows)
        holdout_start_ts = min(int(row["market_start_ts"]) for row in holdout_rows)
        holdout_end_ts = max(int(row["market_start_ts"]) for row in holdout_rows)
        holdout_metrics = _classification_metrics(
            holdout_rows,
            holdout_probs,
            columns=feature_columns,
        )
        fold_summary = {
            "fold": fold_index,
            "start_position": start,
            "train_start": _date(train_start_ts),
            "train_end": _date(train_end_ts),
            "holdout_start": _date(holdout_start_ts),
            "holdout_end": _date(holdout_end_ts),
            "train_rows": len(train_rows),
            "validation_rows": len(validation_rows),
            "holdout_rows": len(holdout_rows),
            "holdout_auc": holdout_metrics["auc"],
            "holdout_brier": holdout_metrics["brier"],
            "selected_validation_policy": selected_policy_name,
            "selected_holdout_score": selected_holdout["score"],
            "selected_holdout_pnl": selected_holdout["pnl"],
            "selected_holdout_trades": selected_holdout["trades"],
            "selected_holdout_win_rate": selected_holdout["win_rate"],
            "selected_holdout_max_drawdown_currency": selected_holdout["max_drawdown_currency"],
            "selected_holdout_realized_ev_per_trade": selected_holdout["realized_ev_per_trade"],
            "selected_holdout_worst_trade_pnl": selected_holdout["worst_trade_pnl"],
            "best_holdout_policy": holdout_policy_rows[0]["policy"],
            "best_holdout_score": holdout_policy_rows[0]["score"],
            "best_holdout_pnl": holdout_policy_rows[0]["pnl"],
            "best_holdout_trades": holdout_policy_rows[0]["trades"],
        }
        fold_rows.append(fold_summary)
        for row in validation_policy_rows:
            fold_policy_rows.append({"fold": fold_index, "split": "validation", **row})
        for row in holdout_policy_rows:
            fold_policy_rows.append({"fold": fold_index, "split": "holdout", **row})
        print(
            f"fold {fold_index}: selected={selected_policy_name} "
            f"holdout_pnl={selected_holdout['pnl']:.2f} "
            f"trades={selected_holdout['trades']} "
            f"win_rate={selected_holdout['win_rate']:.1%} "
            f"auc={holdout_metrics['auc']}"
        )
    if not fold_rows:
        raise RuntimeError("No walk-forward folds had enough rows.")

    selected_rows = [
        {
            "policy": row["selected_validation_policy"],
            "score": row["selected_holdout_score"],
            "pnl": row["selected_holdout_pnl"],
            "max_drawdown_currency": row["selected_holdout_max_drawdown_currency"],
            "trades": row["selected_holdout_trades"],
            "wins": round(
                float(row["selected_holdout_win_rate"]) * int(row["selected_holdout_trades"])
            ),
        }
        for row in fold_rows
    ]
    label = _run_label()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    folds_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_walkforward_{label}_folds.csv"
    policies_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_walkforward_{label}_policies.csv"
    summary_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_walkforward_{label}_summary.json"
    _write_csv(folds_path, fold_rows)
    _write_csv(policies_path, fold_policy_rows)
    summary = {
        "name": f"telonex_btc_5m_snapshot_walkforward_{label}",
        "dataset_csv": str(dataset_path),
        "folds_csv": str(folds_path),
        "policies_csv": str(policies_path),
        "train_windows": train_windows,
        "validation_windows": validation_windows,
        "holdout_windows": holdout_windows,
        "step_windows": step_windows,
        "selector": selector,
        "validation_chunk_windows": validation_chunk_windows,
        "min_chunk_rows": min_chunk_rows,
        "snapshot_seconds": snapshot_seconds,
        "features": feature_columns,
        "policy_assumptions": policy_kwargs,
        "selected_policy_aggregate": _aggregate_selected(selected_rows),
        "folds": fold_rows,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=_json_default))
    aggregate = summary["selected_policy_aggregate"]
    print(
        "walk-forward selected-policy aggregate: "
        f"folds={aggregate['folds']} profitable={aggregate['profitable_folds']} "
        f"total_pnl={aggregate['total_pnl']:.2f} "
        f"median_pnl={aggregate['median_fold_pnl']:.2f} "
        f"worst_fold={aggregate['worst_fold_pnl']:.2f} "
        f"trades={aggregate['trades']} win_rate={aggregate['win_rate']:.1%}"
    )
    print(f"Walk-forward summary JSON: {summary_path}")


def run() -> None:
    main()


if __name__ == "__main__":
    main()
