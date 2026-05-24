import numpy as np
import pandas as pd
from typing import List, Tuple, Generator, Optional, Callable
from itertools import combinations
from sklearn.metrics import log_loss


EXECUTION_FRICTION = 0.005
EMBARGO_HOURS = 24


def combinatorial_purged_cv(
    n_samples: int,
    n_folds: int,
    n_test_folds: int,
) -> Generator[Tuple[List[int], List[int]], None, None]:
    indices = np.arange(n_samples)
    fold_indices = [list(f) for f in np.array_split(indices, n_folds)]
    for combo in combinations(range(n_folds), n_test_folds):
        test_idx = sorted(
            idx for f in combo for idx in fold_indices[f]
        )
        train_idx = sorted(
            idx for f in range(n_folds) if f not in combo for idx in fold_indices[f]
        )
        yield train_idx, test_idx


def purge_overlapping_labels(
    train_idx: List[int],
    test_idx: List[int],
    timestamps: pd.Series,
    label_end_timestamps: pd.Series,
) -> Tuple[List[int], List[int]]:
    if len(test_idx) == 0 or len(train_idx) == 0:
        return train_idx, test_idx
    test_min_t = timestamps.iloc[test_idx].min()
    test_max_t = timestamps.iloc[test_idx].max()
    purged = [
        i
        for i in train_idx
        if label_end_timestamps.iloc[i] < test_min_t
        or timestamps.iloc[i] > test_max_t
    ]
    return purged, test_idx


def apply_embargo(
    train_idx: List[int],
    test_idx: List[int],
    timestamps: pd.Series,
    embargo_hours: int = EMBARGO_HOURS,
) -> Tuple[List[int], List[int]]:
    if len(test_idx) == 0:
        return train_idx, test_idx
    test_end = timestamps.iloc[test_idx[-1]]
    embargo_end = test_end + pd.Timedelta(hours=embargo_hours)
    purged = [
        i
        for i in train_idx
        if timestamps.iloc[i] <= test_end
        or timestamps.iloc[i] >= embargo_end
    ]
    return purged, test_idx


def friction_adjusted_returns(returns: pd.Series) -> pd.Series:
    return returns - np.sign(returns) * EXECUTION_FRICTION


def friction_sharpe_ratio(
    returns: pd.Series, annual_factor: float = np.sqrt(252)
) -> float:
    adj = friction_adjusted_returns(returns)
    if adj.std() == 0.0:
        return 0.0
    return float(annual_factor * adj.mean() / adj.std())


def friction_adjusted_loss(
    y_true: np.ndarray, y_pred: np.ndarray, n_contracts: int = 1
) -> float:
    base_loss = log_loss(y_true, y_pred)
    friction_penalty = EXECUTION_FRICTION
    return base_loss + friction_penalty


def friction_scorer(
    estimator,
    X: np.ndarray,
    y: np.ndarray,
    n_contracts: int = 1,
) -> float:
    y_pred = estimator.predict_proba(X)
    cost = EXECUTION_FRICTION * n_contracts * len(X)
    base = log_loss(y, y_pred)
    return -(base + cost / (len(X) + 1e-8))


def purged_cv_score(
    X: pd.DataFrame,
    y: pd.Series,
    timestamps: pd.Series,
    model,
    label_end_timestamps: Optional[pd.Series] = None,
    n_folds: int = 5,
    n_test_folds: int = 1,
    embargo_hours: int = EMBARGO_HOURS,
    use_friction: bool = True,
) -> Tuple[float, List[float], List[float], float]:
    scores_raw: List[float] = []
    scores_friction: List[float] = []
    fold_count = 0

    for train_idx, test_idx in combinatorial_purged_cv(
        len(X), n_folds, n_test_folds
    ):
        if label_end_timestamps is not None:
            train_idx, test_idx = purge_overlapping_labels(
                train_idx, test_idx, timestamps, label_end_timestamps
            )
        train_idx, test_idx = apply_embargo(
            train_idx, test_idx, timestamps, embargo_hours
        )
        if len(train_idx) < 2 or len(test_idx) < 2:
            continue

        X_train = X.iloc[train_idx]
        y_train = y.iloc[train_idx]
        X_test = X.iloc[test_idx]
        y_test = y.iloc[test_idx]

        model.fit(X_train, y_train)
        if hasattr(model, "predict_proba"):
            y_pred = model.predict_proba(X_test)[:, 1]
        else:
            y_pred = model.predict(X_test)

        n_contracts = len(test_idx)
        raw_cost = EXECUTION_FRICTION * n_contracts
        if hasattr(model, "predict_proba"):
            base_loss = log_loss(y_test, np.clip(y_pred, 1e-15, 1 - 1e-15))
        else:
            base_loss = float(np.mean((y_test.to_numpy() - y_pred) ** 2))
        score_raw = base_loss
        score_friction = base_loss + raw_cost / max(n_contracts, 1)

        scores_raw.append(score_raw)
        scores_friction.append(score_friction)
        fold_count += 1

    if fold_count == 0:
        return 0.0, [], [], 0.0

    mean_raw = float(np.mean(scores_raw))
    mean_friction = float(np.mean(scores_friction))
    std_friction = float(np.std(scores_friction)) if fold_count > 1 else 0.0
    return mean_raw, scores_raw, scores_friction, mean_friction


def backtest_with_friction(
    returns: pd.Series,
    friction: float = EXECUTION_FRICTION,
) -> pd.Series:
    friction_cost = np.where(returns != 0, friction * np.sign(returns), 0.0)
    return returns - friction_cost
