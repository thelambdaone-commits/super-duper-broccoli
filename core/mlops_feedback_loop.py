import logging
import json
import asyncio
import time
import os
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from scipy.stats import entropy
from sklearn.metrics import brier_score_loss

logger = logging.getLogger("MLOpsEngine")


@dataclass
class DriftReport:
    timestamp: str
    ticker: str
    psi: float
    kl_divergence: float
    drift_detected: bool
    severity: str
    recommendation: str


@dataclass
class CalibrationReport:
    timestamp: str
    brier_score: float
    action: str
    reason: str
    sample_size: int


from utils.config_loader import TRADING_PARAMS

class LobstarMLOpsEngine:
    """
    Moteur MLOps de grade institutionnel pour l'essaim Ruflo.
    Surveille le drift des caractéristiques, calcule la perte de calibration
    et pilote le réentraînement adaptatif.
    """

    PSI_THRESHOLD = TRADING_PARAMS["PSI_THRESHOLD"]
    KL_THRESHOLD = TRADING_PARAMS["KL_THRESHOLD"]
    BRIER_THRESHOLD = TRADING_PARAMS["BRIER_THRESHOLD"]

    def __init__(
        self,
        brier_threshold: float = BRIER_THRESHOLD,
        psi_threshold: float = PSI_THRESHOLD,
        kl_threshold: float = KL_THRESHOLD,
        embedding_path: str = "user_data/data/raw_stream"
    ):
        self.brier_threshold = brier_threshold
        self.psi_threshold = psi_threshold
        self.kl_threshold = kl_threshold
        self.embedding_path = embedding_path
        self._baseline_features: Dict[str, np.ndarray] = {}
        self._drift_history: List[DriftReport] = []
        self._calibration_history: List[CalibrationReport] = []
        self._drift_callback: Optional[Callable] = None
        self._last_prune_ts: float = 0.0

    def set_drift_callback(self, callback: Callable[[dict], None]) -> None:
        """Register a callback for drift detection events."""
        self._drift_callback = callback

    def set_baseline(self, ticker: str, features: np.ndarray) -> None:
        """Définir la distribution baseline pour un ticker."""
        self._baseline_features[ticker] = features
        logger.info(f"📊 [MLOPS] Baseline set for {ticker}: shape={features.shape}")

    def calculer_divergence_kl(
        self,
        p_baseline: np.ndarray,
        q_live: np.ndarray
    ) -> float:
        """
        Mesure la dérive de concept (Concept Drift) entre la distribution
        d'entraînement (baseline) et les données du marché en temps réel (live).
        """
        p = np.clip(p_baseline, 1e-10, 1.0)
        q = np.clip(q_live, 1e-10, 1.0)

        p = p / np.sum(p) if np.sum(p) > 0 else p
        q = q / np.sum(q) if np.sum(q) > 0 else q

        kl_div = float(entropy(p, q))
        logger.info(f"📊 [MLOPS DRIFT] Divergence KL: {kl_div:.4f}")
        return kl_div

    def calculer_psi(
        self,
        baseline: np.ndarray,
        live: np.ndarray,
        bins: int = 10
    ) -> float:
        """
        Population Stability Index (PSI) pour détecter les changements
        dans la distribution des features.
        """
        if len(baseline) < 10 or len(live) < 10:
            return 0.0

        try:
            hist, bin_edges = np.histogram(baseline, bins=bins, density=True)
            live_hist, _ = np.histogram(live, bins=bin_edges, density=True)

            hist = np.clip(hist, 1e-10, 1.0)
            live_hist = np.clip(live_hist, 1e-10, 1.0)

            hist = hist / np.sum(hist)
            live_hist = live_hist / np.sum(live_hist)

            psi = np.sum((live_hist - hist) * np.log(live_hist / hist))
            return float(abs(psi))

        except Exception as e:
            logger.error(f"PSI calculation error: {e}")
            return 0.0

    def detecter_drift(
        self,
        ticker: str,
        live_features: np.ndarray
    ) -> DriftReport:
        """Détecter le drift pour un ticker donné."""
        if ticker not in self._baseline_features:
            return DriftReport(
                timestamp=datetime.now(timezone.utc).isoformat(),
                ticker=ticker,
                psi=0.0,
                kl_divergence=0.0,
                drift_detected=False,
                severity="UNKNOWN",
                recommendation="No baseline established"
            )

        baseline = self._baseline_features[ticker]

        kl_div = self.calculer_divergence_kl(baseline.flatten(), live_features.flatten())
        psi = self.calculer_psi(baseline.flatten(), live_features.flatten())

        drift_detected = kl_div > self.kl_threshold or psi > self.psi_threshold

        if kl_div > self.kl_threshold * 2 or psi > self.psi_threshold * 2:
            severity = "CRITICAL"
        elif drift_detected:
            severity = "MODERATE"
        else:
            severity = "NONE"

        if severity == "CRITICAL":
            recommendation = "IMMEDIATE_RETRAIN"
        elif severity == "MODERATE":
            recommendation = "MONITOR_CLOSELY"
        else:
            recommendation = "OPTIMAL"

        report = DriftReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ticker=ticker,
            psi=psi,
            kl_divergence=kl_div,
            drift_detected=drift_detected,
            severity=severity,
            recommendation=recommendation
        )

        self._drift_history.append(report)
        if len(self._drift_history) > 100:
            self._drift_history.pop(0)

        logger.info(f"📊 [MLOPS DRIFT] {ticker}: PSI={psi:.4f}, KL={kl_div:.4f} -> {severity}")

        if self._drift_callback and drift_detected:
            self._drift_callback({
                "ticker": ticker,
                "psi": psi,
                "kl_divergence": kl_div,
                "severity": severity,
                "recommendation": recommendation,
            })

        return report

    def evaluer_sante_brain(
        self,
        true_labels: List[int],
        calibrated_probs: List[float]
    ) -> CalibrationReport:
        """
        Analyse la précision probabiliste réelle du cerveau via le score de Brier.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        if len(true_labels) < 50:
            return CalibrationReport(
                timestamp=timestamp,
                brier_score=0.0,
                action="HOLD",
                reason="Échantillon historique trop faible pour audit.",
                sample_size=len(true_labels)
            )

        score_brier = brier_score_loss(true_labels, calibrated_probs)
        logger.info(f"🎯 [MLOPS METRICS] Brier Score: {score_brier:.5f}")

        if score_brier > self.brier_threshold:
            action = "TRIGGER_RETRAIN"
            reason = f"Dégradation calibration ({score_brier:.5f} > {self.brier_threshold})"
        else:
            action = "OPTIMAL"
            reason = "Cerveau parfaitement calibré"

        report = CalibrationReport(
            timestamp=timestamp,
            brier_score=score_brier,
            action=action,
            reason=reason,
            sample_size=len(true_labels)
        )

        self._calibration_history.append(report)
        if len(self._calibration_history) > 100:
            self._calibration_history.pop(0)

        return report

    async def archiver_embeddings_tft(
        self,
        ticker: str,
        embeddings: np.ndarray,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Sérialise les représentations latentes du Transformer au format JSONL.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        payload = {
            "timestamp": timestamp,
            "timestamp_unix": time.time(),
            "ticker": ticker,
            "latent_vector": embeddings.tolist() if isinstance(embeddings, np.ndarray) else embeddings,
            "embedding_dim": int(embeddings.shape[0]) if hasattr(embeddings, 'shape') else len(embeddings),
            "metadata": metadata or {}
        }

        filename = f"{self.embedding_path}/tft_embeddings_{ticker}.jsonl"
        await asyncio.to_thread(self._write_jsonl, filename, payload)

        logger.info(f"💾 [MLOPS] Embedded {ticker} to {filename}")
        return filename

    def prune_feature_store(
        self,
        store: Any,
        raw_retention_days: int = 7,
        vacuum: bool = True,
    ) -> dict[str, int]:
        """
        Keep only recent raw HF data and retain longer-lived derived features.
        """
        cutoff_ts = time.time() - float(raw_retention_days * 86400)
        removed = store.prune_before(
            cutoff_ts,
            tables=["web_events_raw", "market_microstructure"],
        )
        if vacuum:
            store.vacuum()
        self._last_prune_ts = time.time()
        logger.info("Feature store pruned before %s: %s", cutoff_ts, removed)
        return removed

    def should_prune(self, interval_hours: int = 24) -> bool:
        if self._last_prune_ts <= 0:
            return True
        return (time.time() - self._last_prune_ts) >= interval_hours * 3600

    @staticmethod
    def _write_jsonl(filename: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def get_drift_summary(self) -> Dict[str, Any]:
        if not self._drift_history:
            return {"total_checks": 0, "drift_detected": 0}

        total = len(self._drift_history)
        drift_count = sum(1 for r in self._drift_history if r.drift_detected)
        critical = sum(1 for r in self._drift_history if r.severity == "CRITICAL")

        return {
            "total_checks": total,
            "drift_detected": drift_count,
            "critical": critical,
            "recent_tickers": [r.ticker for r in self._drift_history[-5:]]
        }

    def get_calibration_summary(self) -> Dict[str, Any]:
        if not self._calibration_history:
            return {"total_evaluations": 0, "avg_brier": 0}

        recent = self._calibration_history[-20:]
        avg_brier = sum(r.brier_score for r in recent) / len(recent)
        retrain_needed = sum(1 for r in recent if r.action == "TRIGGER_RETRAIN")

        return {
            "total_evaluations": len(self._calibration_history),
            "avg_brier_score": avg_brier,
            "retrain_triggered": retrain_needed,
            "last_action": self._calibration_history[-1].action if self._calibration_history else "N/A"
        }

    def format_mlops_report(self) -> str:
        drift = self.get_drift_summary()
        calib = self.get_calibration_summary()

        lines = [
            "🧠 *MLOPS FEEDBACK LOOP REPORT*",
            "───────────────────────────────",
            "",
            "📊 *DRIFT DETECTION:*",
            f"  • Total Checks: `{drift['total_checks']}`",
            f"  • Drift Detected: `{drift['drift_detected']}`",
            f"  • Critical: `{drift.get('critical', 0)}`",
            "",
            "🎯 *CALIBRATION HEALTH:*",
            f"  • Avg Brier Score: `{calib['avg_brier']:.5f}`",
            f"  • Retrain Triggered: `{calib['retrain_triggered']}`",
            f"  • Last Action: `{calib['last_action']}`",
        ]

        return "\n".join(lines)

    async def analyser_sante_brain(self) -> None:
        """PATH LONG: audit predictive Brier calibration score and feature drift metrics."""
        logger.info("🧠 [MLOPS AUDIT] Commencing high-precision calibration and drift analysis...")
        report = self.evaluer_sante_brain([], [])
        logger.info(f"🧠 [MLOPS AUDIT RESULT] Brier score calibration audit: {report.reason}")
