import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_FreqAI")


class FreqAISkill(Skill):
    @property
    def name(self) -> str:
        return "freqai"

    @property
    def description(self) -> str:
        return "Analyzes ML training pipeline, model architecture, feature engineering, and calibration"

    @property
    def priority_files(self) -> list[str]:
        return [
            "core/training_pipeline.py",
            "user_data/freqaimodels/HybridQuantModel.py",
            "strategies/probability_calibrator.py",
            "strategies/feature_pipeline.py",
            "utils/feature_store.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        target_paths = paths or self.priority_files
        for filepath in target_paths:
            try:
                with open(filepath) as f:
                    content = f.read()
                if "train_test_split" in content:
                    issues.append({
                        "file": filepath,
                        "severity": "high",
                        "message": "Uses random train_test_split on time series — lookahead bias risk",
                        "snippet": "Time-series data should use walk-forward or time-based split",
                    })
                if "np.random" in content and "randn" in content:
                    issues.append({
                        "file": filepath,
                        "severity": "medium",
                        "message": "Uses np.random.randn for synthetic data in production code",
                        "snippet": "Non-deterministic behavior in production path",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "training_pipeline",
                "suggestion": "Replace sequential validation split with time-series-aware TimeSeriesSplit",
                "priority": "high",
                "impact": "Eliminates lookahead bias in validation metrics",
            },
            {
                "component": "training_pipeline",
                "suggestion": "Add feature importance tracking over time to detect concept drift",
                "priority": "medium",
                "impact": "Enables early detection of degrading model performance",
            },
            {
                "component": "feature_pipeline",
                "suggestion": "Wire feature_pipeline's build_feature_matrix into the live execution loop to persist computed features",
                "priority": "high",
                "impact": "Feature store will actually contain features consumed by models",
            },
            {
                "component": "HybridQuantModel",
                "suggestion": "Add early stopping callback to prevent overfitting during training",
                "priority": "medium",
                "impact": "Improves generalization on unseen data",
            },
            {
                "component": "probability_calibrator",
                "suggestion": "Add streaming Brier score computation on live predictions for drift detection",
                "priority": "medium",
                "impact": "Continuous calibration quality monitoring",
            },
        ]
