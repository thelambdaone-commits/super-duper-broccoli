#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime
from typing import Optional

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

import numpy as np
try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - exercised only when tqdm is absent
    tqdm = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.training_pipeline import TrainingPipeline
from utils.feature_store import FEATURE_STORE_PATH, FeatureStore
from utils.vault_handler import VaultHandler
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrainAll")

SECTION_SEPARATOR = "=" * 60

TRACKING_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "user_data", "models", "training_runs.jsonl"
)
TOP_PCT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "user_data", "models", "top1pct_runs.json"
)

DEFAULT_TICKERS = ["SOL", "BTC", "ETH", "LINK", "ARB", "OP"]
CONTINUOUS_TICKERS = ["BTCUSDT", "ETHUSDT", "SPY", "QQQ"]
FEATURES = ["oi_5min", "tam_state", "spread_bps", "mid_price"]
TARGET = "mid_price"
N_SAMPLES = 1000
CONTINUOUS_SEQUENCE_SECONDS = 300

HYPERPARAM_GRID = [
    {"n_estimators": 50, "max_depth": 3, "learning_rate": 0.05},
    {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.05},
    {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05},
]


class Progress:
    def __init__(self, total: int, enabled: bool = True) -> None:
        self.total = total
        self.enabled = enabled
        self.current = 0
        self._bar = tqdm(
            total=total,
            desc="Training",
            unit="config",
            dynamic_ncols=True,
        ) if enabled and tqdm else None

    def update(self, ticker: str, params: dict, status: str = "done") -> None:
        self.current += 1
        postfix = {
            "ticker": ticker,
            "n": params.get("n_estimators"),
            "depth": params.get("max_depth"),
            "status": status,
        }
        if self._bar:
            self._bar.set_postfix(postfix)
            self._bar.update(1)
            return

        logger.info(
            "Progress %s/%s [%s] %s n=%s depth=%s",
            self.current,
            self.total,
            status,
            ticker,
            params.get("n_estimators"),
            params.get("max_depth"),
        )

    def close(self) -> None:
        if self._bar:
            self._bar.close()


def _batch_features(store: FeatureStore, rows: list[tuple]) -> None:
    store._conn.executemany("""
        INSERT INTO features_computed (timestamp, ticker, feature_name, feature_value)
        VALUES (?, ?, ?, ?)
    """, rows)
    store._conn.commit()


def generate_synthetic_data(store: FeatureStore) -> None:
    rng = np.random.RandomState(42)
    base_ts = time.time() - N_SAMPLES * CONTINUOUS_SEQUENCE_SECONDS
    for ticker in DEFAULT_TICKERS:
        mid = 0.5 + 0.3 * np.sin(np.linspace(0, 4 * np.pi, N_SAMPLES))
        mid += rng.normal(0, 0.02, N_SAMPLES)
        mid = np.clip(mid, 0.05, 0.95)

        oi = 0.3 * np.sin(np.linspace(0, 6 * np.pi, N_SAMPLES))
        oi += rng.normal(0, 0.1, N_SAMPLES)
        oi = np.clip(oi, -1.0, 1.0)

        tam_raw = rng.randn(N_SAMPLES)
        tam = np.where(tam_raw > 0.5, 1, np.where(tam_raw < -0.5, -1, 0))

        spread = 5.0 + 15.0 * np.abs(np.sin(np.linspace(0, 8 * np.pi, N_SAMPLES)))
        spread += rng.exponential(2.0, N_SAMPLES)
        spread = np.clip(spread, 1.0, 100.0)

        rows = []
        for i in range(N_SAMPLES):
            ts = base_ts + i * CONTINUOUS_SEQUENCE_SECONDS
            rows.append((ts, ticker, "oi_5min", float(oi[i])))
            rows.append((ts, ticker, "tam_state", float(tam[i])))
            rows.append((ts, ticker, "spread_bps", float(spread[i])))
            rows.append((ts, ticker, "mid_price", float(mid[i])))
        _batch_features(store, rows)

        logger.info(
            f"Generated {N_SAMPLES} samples for {ticker}: "
            f"mid=[{mid[0]:.4f}..{mid[-1]:.4f}] "
            f"oi=[{oi[0]:.3f}..{oi[-1]:.3f}]"
        )
    logger.info(f"Total features written: {store.get_stats()['features_computed']}")


def train_configs(
    pipeline: TrainingPipeline,
    ticker: str,
    hyperparams_list: list[dict],
    n_splits_wf: int = 5,
    validation_split: float = 0.2,
    progress: Optional[Progress] = None,
) -> list[dict]:
    results: list[dict] = []
    for params in hyperparams_list:
        run_id = f"{ticker}_{int(time.time())}_{params['n_estimators']}_{params['max_depth']}"
        start = time.time()

        try:
            result = pipeline.train(ticker, hyperparams=params)
            duration = time.time() - start

            if result is None:
                logger.warning(f"[{run_id}] training returned None")
                if progress:
                    progress.update(ticker, params, "skipped")
                continue

            wf_result = pipeline.backtest_walk_forward(
                ticker, n_splits=n_splits_wf, hyperparams=params
            )

            run = {
                "run_id": run_id,
                "ticker": ticker,
                "timestamp": datetime.utcnow().isoformat(),
                "duration_sec": round(duration, 2),
                "hyperparams": params,
                "train_accuracy": result.get("train_accuracy", 0),
                "val_accuracy": result.get("val_accuracy", 0),
                "train_samples": result.get("train_samples", 0),
                "val_samples": result.get("val_samples", 0),
                "meta_weights": result.get("meta_weights", {}),
                "top_features": result.get("top_features", {}),
                "model_path": result.get("model_path", ""),
            }
            if wf_result:
                run["wf_mean_accuracy"] = wf_result.get("mean_val_accuracy", 0)
                run["wf_std_accuracy"] = wf_result.get("std_val_accuracy", 0)
                run["wf_n_folds"] = wf_result.get("n_splits", 0)
                run["wf_fold_metrics"] = wf_result.get("fold_metrics", [])

            results.append(run)
            if progress:
                progress.update(ticker, params, "ok")
            logger.info(
                f"[{run_id}] train_acc={run['train_accuracy']:.4f} "
                f"val_acc={run['val_accuracy']:.4f} "
                f"wf_acc={run.get('wf_mean_accuracy', 0):.4f} "
                f"({duration:.1f}s)"
            )

        except Exception as e:
            logger.error(f"[{run_id}] FAILED: {e}")
            if progress:
                progress.update(ticker, params, "failed")

    return results


def train_continuous_configs(
    pipeline: TrainingPipeline,
    ticker: str,
    hyperparams_list: list[dict],
    horizon: int = 3,
    n_splits_wf: int = 5,
    progress: Optional[Progress] = None,
) -> list[dict]:
    results: list[dict] = []
    for params in hyperparams_list:
        run_id = f"{ticker}_{int(time.time())}_{params['n_estimators']}_{params['max_depth']}_continuous"
        start = time.time()

        try:
            result = pipeline.train_continuous(ticker, hyperparams=params, horizon=horizon)
            duration = time.time() - start

            if result is None:
                logger.warning(f"[{run_id}] continuous training returned None")
                if progress:
                    progress.update(ticker, params, "skipped")
                continue

            wf_result = pipeline.backtest_walk_forward_continuous(
                ticker, n_splits=n_splits_wf, hyperparams=params, horizon=horizon
            )

            run = {
                "run_id": run_id,
                "ticker": ticker,
                "market_type": "continuous",
                "timestamp": datetime.utcnow().isoformat(),
                "duration_sec": round(duration, 2),
                "hyperparams": params,
                "horizon": horizon,
                "train_accuracy": result.get("train_accuracy", 0),
                "val_accuracy": result.get("val_accuracy", 0),
                "train_samples": result.get("train_samples", 0),
                "val_samples": result.get("val_samples", 0),
                "meta_weights": result.get("meta_weights", {}),
                "top_features": result.get("top_features", {}),
                "model_path": result.get("model_path", ""),
                "calibrator_path": result.get("calibrator_path", ""),
                "calibrated_model_path": result.get("calibrated_model_path", ""),
            }
            if wf_result:
                run["wf_mean_accuracy"] = wf_result.get("mean_val_accuracy", 0)
                run["wf_std_accuracy"] = wf_result.get("std_val_accuracy", 0)
                run["wf_n_folds"] = wf_result.get("n_splits", 0)
                run["wf_fold_metrics"] = wf_result.get("fold_metrics", [])

            results.append(run)
            if progress:
                progress.update(ticker, params, "ok")
            logger.info(
                f"[{run_id}] train_acc={run['train_accuracy']:.4f} "
                f"val_acc={run['val_accuracy']:.4f} "
                f"wf_acc={run.get('wf_mean_accuracy', 0):.4f} "
                f"({duration:.1f}s)"
            )
        except Exception as e:
            logger.error(f"[{run_id}] FAILED: {e}")
            if progress:
                progress.update(ticker, params, "failed")

    return results


def save_tracking(runs: list[dict]) -> None:
    os.makedirs(os.path.dirname(TRACKING_FILE), exist_ok=True)
    with open(TRACKING_FILE, "a") as f:
        for run in runs:
            f.write(json.dumps(run) + "\n")
    logger.info(f"Appended {len(runs)} runs to {TRACKING_FILE}")


def compute_top1pct(runs: list[dict]) -> list[dict]:
    scored = [r for r in runs if r.get("wf_mean_accuracy", 0) > 0]
    if not scored:
        return []
    scored.sort(key=lambda r: -r["wf_mean_accuracy"])
    n_top = max(1, len(scored) // 100)
    top = scored[:n_top]
    logger.info(
        f"Top 1%: {len(top)}/{len(scored)} configs "
        f"(threshold wf_acc >= {top[-1]['wf_mean_accuracy']:.4f})"
    )
    return top


def main(
    dry_run: bool = False,
    db_path: Optional[str] = None,
    allow_synthetic_live: bool = False,
    tickers: Optional[list[str]] = None,
    continuous: bool = False,
) -> None:
    tickers = tickers or DEFAULT_TICKERS
    store = FeatureStore(db_path=db_path) if db_path else FeatureStore()

    if dry_run:
        logger.info("[DRY RUN] FeatureStore OK. Would generate data and train.")
        pipeline = TrainingPipeline(
            store=store,
            retrain_interval_hours=9999,
            min_train_samples=50,
            validation_split=0.2,
        )
        for ticker in DEFAULT_TICKERS:
            pipeline.register_features(ticker, FEATURES, target_feature=TARGET)
            logger.info(f"[DRY RUN] Would train {len(HYPERPARAM_GRID)} configs for {ticker}")
        logger.info("Dry run complete. Run without --dry-run to actually train.")
        return

    using_live_store = db_path is None or (
        os.path.abspath(db_path) == os.path.abspath(FEATURE_STORE_PATH)
    )
    if store.get_stats()["features_computed"] == 0:
        if using_live_store and not allow_synthetic_live:
            raise RuntimeError(
                "Refusing to generate synthetic training data in the live FeatureStore. "
                "Pass --db-path /tmp/train.duckdb or --allow-synthetic-live explicitly."
            )
        logger.info("No data found. Generating synthetic training data...")
        generate_synthetic_data(store)
    else:
        logger.info(f"Using existing data: {store.get_stats()}")

    pipeline = TrainingPipeline(
        store=store,
        retrain_interval_hours=9999,
        min_train_samples=50,
        validation_split=0.2,
    )

    all_runs: list[dict] = []
    progress = Progress(total=len(tickers) * len(HYPERPARAM_GRID))
    try:
        for ticker in tickers:
            logger.info(f"\n{SECTION_SEPARATOR}\nTraining {ticker}\n{SECTION_SEPARATOR}")
            pipeline.register_features(ticker, FEATURES, target_feature=TARGET)
            runs = train_configs(pipeline, ticker, HYPERPARAM_GRID, progress=progress)
            all_runs.extend(runs)
            save_tracking(runs)
    finally:
        progress.close()

    if all_runs:
        top_runs = compute_top1pct(all_runs)
        with open(TOP_PCT_PATH, "w") as f:
            json.dump({
                "generated_at": datetime.utcnow().isoformat(),
                "total_runs": len(all_runs),
                "top1pct_count": len(top_runs),
                "top1pct_runs": top_runs,
            }, f, indent=2, default=str)
        logger.info(f"Top 1% runs saved to {TOP_PCT_PATH}")

        best = top_runs[0] if top_runs else all_runs[0]
        logger.info(
            f"\nBEST CONFIG: {best.get('ticker')} "
            f"params={best.get('hyperparams')} "
            f"wf_acc={best.get('wf_mean_accuracy', 0):.4f} "
            f"model={best.get('model_path')}"
        )

    summary = {
        "total_runs": len(all_runs),
        "tickers_trained": tickers,
        "models_dir": pipeline.model_dir,
        "tracking_file": TRACKING_FILE,
        "top1pct_file": TOP_PCT_PATH,
        "timestamp": datetime.utcnow().isoformat(),
    }
    summary_path = os.path.join(os.path.dirname(TRACKING_FILE), "training_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary saved to {summary_path}")

    # ── Continuous market training (additive) ──
    if continuous:
        from config.constants import CONTINUOUS_FEATURE_NAMES, CONTINUOUS_TARGET_FEATURE
        cont_tickers = [t for t in tickers if t in CONTINUOUS_TICKERS] if tickers else CONTINUOUS_TICKERS
        logger.info(f"\n{SECTION_SEPARATOR}\nContinuous market training: {cont_tickers}\n{SECTION_SEPARATOR}")

        for cticker in cont_tickers:
            pipeline.register_continuous_features(
                cticker,
                feature_names=CONTINUOUS_FEATURE_NAMES,
                target_feature=CONTINUOUS_TARGET_FEATURE,
                horizon=3,
            )
            runs = train_continuous_configs(
                pipeline,
                cticker,
                HYPERPARAM_GRID,
                horizon=3,
                n_splits_wf=5,
                progress=Progress(total=len(HYPERPARAM_GRID)),
            )
            all_runs.extend(runs)
            save_tracking(runs)

    # Telegram Notification
    try:
        vault = VaultHandler()
        secrets = vault.fetch_quantum_secrets()
        bot_token = secrets.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("CHAT_ID")

        if bot_token and chat_id:
            msg = (
                f"🎯 *Training Complete*\n\n"
                f"Tickers: `{', '.join(tickers)}`\n"
                f"Total Runs: `{len(all_runs)}`\n"
                f"Best Model: `{best.get('ticker')} (wf_acc: {best.get('wf_mean_accuracy', 0):.4f})`\n"
                f"Models Dir: `{pipeline.model_dir}`"
            )
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown"
            }
            httpx.post(url, json=payload, timeout=10.0)
            logger.info("Telegram notification sent")
    except Exception as te:
        logger.warning(f"Could not send Telegram notification: {te}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train all models with hyperparameter search")
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without training")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional FeatureStore DuckDB path. Useful for isolated dry-runs/tests.",
    )
    parser.add_argument(
        "--allow-synthetic-live",
        action="store_true",
        help="Allow synthetic data generation in the default live FeatureStore.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Tickers to train (default: all 6). Example: --tickers ETH LINK ARB",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Also train on continuous market tickers (BTCUSDT, ETHUSDT, SPY, QQQ)",
    )
    args = parser.parse_args()
    main(
        dry_run=args.dry_run,
        db_path=args.db_path,
        allow_synthetic_live=args.allow_synthetic_live,
        tickers=args.tickers,
        continuous=args.continuous,
    )
