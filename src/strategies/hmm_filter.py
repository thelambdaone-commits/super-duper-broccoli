import numpy as np
from hmmlearn import hmm
from typing import Optional, Tuple
from scipy.stats import wasserstein_distance


REGIME_LABELS = {
    0: "LOW_VOLATILITY",
    1: "HIGH_TREND_VOLATILITY",
    2: "ERRATIC_VOLATILITY",
}

REGIME_BLOCKED = {"ERRATIC_VOLATILITY"}


class HMMRegimeFilter:
    def __init__(
        self,
        n_regimes: int = 3,
        n_iter: int = 200,
        random_state: int = 42,
        covariance_type: str = "full",
    ) -> None:
        self.model = hmm.GaussianHMM(
            n_components=n_regimes,
            covariance_type=covariance_type,
            n_iter=n_iter,
            random_state=random_state,
            tol=1e-4,
        )
        self._fitted = False
        self._training_means: Optional[np.ndarray] = None
        self._training_covars: Optional[np.ndarray] = None
        self._label_map: dict[int, str] = {}

    def fit(self, returns: np.ndarray) -> None:
        X = self._prepare_returns(returns)
        if len(X) < self.model.n_components:
            raise ValueError("Not enough return observations to fit HMM")
        self.model.fit(X)
        self._fitted = True

        self._training_means = self.model.means_.copy()
        self._training_covars = self.model.covars_.copy()

        means_flat = self.model.means_.flatten()
        sorted_idx = np.argsort(np.abs(means_flat))
        labels = ["LOW_VOLATILITY", "HIGH_TREND_VOLATILITY", "ERRATIC_VOLATILITY"]
        self._label_map = {
            int(state): labels[min(rank, len(labels) - 1)]
            for rank, state in enumerate(sorted_idx)
        }
        stds = np.sqrt(self.model.covars_.flatten())
        max_std_idx = int(np.argmax(stds))
        if len(sorted_idx) >= 3 and max_std_idx != sorted_idx[2]:
            self._label_map[max_std_idx] = "ERRATIC_VOLATILITY"
            remaining = [s for s in range(3) if s != max_std_idx]
            self._label_map[remaining[0]] = "LOW_VOLATILITY"
            self._label_map[remaining[1]] = "HIGH_TREND_VOLATILITY"

    @staticmethod
    def _prepare_returns(returns: np.ndarray) -> np.ndarray:
        arr = np.asarray(returns, dtype=np.float64).reshape(-1, 1)
        if arr.size == 0:
            return arr
        return arr[np.isfinite(arr[:, 0])]

    def predict_regime(self, returns: np.ndarray) -> int:
        if not self._fitted:
            return 2
        X = self._prepare_returns(returns)
        if len(X) == 0:
            return 2
        hidden = self.model.predict(X)
        return int(hidden[-1])

    def get_regime_label(self, state: int) -> str:
        return self._label_map.get(state, REGIME_LABELS.get(state, "UNKNOWN"))

    def get_regime_labels(self) -> list[str]:
        if not self._fitted:
            return list(REGIME_LABELS.values())
        return list(self._label_map.values())

    def predict_with_label(self, returns: np.ndarray) -> Tuple[int, str]:
        state = self.predict_regime(returns)
        return state, self.get_regime_label(state)

    def is_execution_blocked(self, returns: np.ndarray) -> bool:
        _, label = self.predict_with_label(returns)
        return label in REGIME_BLOCKED

    def compute_dissimilarity_index(
        self, returns: np.ndarray, window: int = 50
    ) -> float:
        clean = self._prepare_returns(returns).flatten()
        if len(clean) < window * 2:
            return 0.0
        ref = clean[-window * 2 : -window]
        current = clean[-window:]
        di = float(wasserstein_distance(ref.flatten(), current.flatten()))
        return di

    def is_ood_detected(
        self,
        returns: np.ndarray,
        di_threshold: float = 2.0,
        window: int = 50,
    ) -> bool:
        di = self.compute_dissimilarity_index(returns, window)
        return di > di_threshold

    def is_trading_allowed(
        self,
        returns: np.ndarray,
        di_threshold: float = 2.0,
        di_window: int = 50,
    ) -> Tuple[bool, str]:
        clean = self._prepare_returns(returns)
        if len(clean) == 0:
            return False, "HMM_BLOCKED: invalid_or_empty_returns"
        _, label = self.predict_with_label(returns)
        if label in REGIME_BLOCKED:
            return False, f"HMM_BLOCKED: regime={label}"

        ood = self.is_ood_detected(returns, di_threshold, di_window)
        if ood:
            di = self.compute_dissimilarity_index(returns, di_window)
            return (
                False,
                f"OOD_BLOCKED: dissimilarity_index={di:.4f} > threshold={di_threshold}",
            )

        return True, f"TRADING_ALLOWED: regime={label}"
