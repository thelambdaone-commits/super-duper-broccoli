import numpy as np
import pytest

from strategies.probability_calibrator import (
    ProbabilityCalibrator, FUSION_MODES,
)


@pytest.fixture
def synthetic_oof() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.RandomState(42)
    n = 200
    raw_proba = rng.beta(2, 5, size=n)
    y_true = (rng.uniform(size=n) < raw_proba).astype(np.int32)
    probas = np.zeros((n, 2))
    probas[:, 1] = raw_proba
    probas[:, 0] = 1.0 - raw_proba
    return probas, y_true


class TestFusionModes:
    def test_valid_modes(self) -> None:
        assert FUSION_MODES == {"platt_only", "isotonic_only", "ensemble"}

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="fusion_mode"):
            ProbabilityCalibrator(fusion_mode="invalid")


class TestCalibrate:
    def test_nominal_platt(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator(fusion_mode="platt_only")
        cal.calibrate(probas, y_true)
        assert cal.is_fitted
        assert "raw_brier" in cal.calibration_log
        assert "calibrated_brier" in cal.calibration_log

    def test_nominal_isotonic(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator(fusion_mode="isotonic_only")
        cal.calibrate(probas, y_true)
        assert cal.is_fitted

    def test_nominal_ensemble(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator(fusion_mode="ensemble")
        cal.calibrate(probas, y_true)
        assert cal.is_fitted
        assert cal.calibration_log["fusion_mode"] == "ensemble"

    def test_insufficient_samples_raises(self) -> None:
        cal = ProbabilityCalibrator()
        probas = np.ones((3, 2)) * 0.5
        y_true = np.array([0, 1, 0])
        with pytest.raises(ValueError, match="at least 10"):
            cal.calibrate(probas, y_true)

    def test_single_class_y_raises(self) -> None:
        cal = ProbabilityCalibrator()
        probas = np.ones((20, 2)) * 0.5
        y_true = np.zeros(20, dtype=np.int32)
        with pytest.raises(ValueError, match="both classes"):
            cal.calibrate(probas, y_true)

    def test_1d_input_proba(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator()
        cal.calibrate(probas[:, 1], y_true)
        assert cal.is_fitted


class TestPredictProba:
    def test_predict_before_fit_raises(self) -> None:
        cal = ProbabilityCalibrator()
        with pytest.raises(RuntimeError, match="not fitted"):
            cal.predict_proba(np.array([[0.5, 0.5]]))

    def test_predict_output_shape(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator()
        cal.calibrate(probas, y_true)

        test_probas = np.array([[0.3, 0.7], [0.8, 0.2], [0.1, 0.9]])
        result = cal.predict_proba(test_probas)
        assert result.shape == (3, 2)

    def test_predict_1d_input(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator()
        cal.calibrate(probas, y_true)

        test_input = np.array([0.7, 0.3, 0.9])
        result = cal.predict_proba(test_input)
        assert result.shape == (3, 2)

    def test_predict_output_sum_to_one(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator()
        cal.calibrate(probas, y_true)

        test_probas = np.array([[0.3, 0.7], [0.8, 0.2]])
        result = cal.predict_proba(test_probas)
        assert np.allclose(result.sum(axis=1), 1.0)

    def test_predict_bounds(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator()
        cal.calibrate(probas, y_true)

        extreme = np.array([[0.001, 0.999], [0.999, 0.001]])
        result = cal.predict_proba(extreme)
        assert np.all((result >= 0.0) & (result <= 1.0))


class TestCalibrationImprovement:
    def test_brier_improvement_tracked(
        self, synthetic_oof: tuple[np.ndarray, np.ndarray],
    ) -> None:
        probas, y_true = synthetic_oof
        cal = ProbabilityCalibrator()
        cal.calibrate(probas, y_true)
        log = cal.calibration_log
        assert log["n_samples"] == 200
        assert "calibrated_brier" in log
        assert "brier_improvement" in log
