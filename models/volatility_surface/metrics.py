import numpy as np


def surface_rmse(pred: np.ndarray, target: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - target) ** 2)))


def surface_mae(pred: np.ndarray, target: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - target)))


def surface_mape(pred: np.ndarray, target: np.ndarray) -> float:
    mask = np.abs(target) > 1e-8
    return float(np.mean(np.abs((pred[mask] - target[mask]) / target[mask]))) * 100


def atm_rmse(pred: np.ndarray, target: np.ndarray, atm_idx: int = -1) -> float:
    atm_col = pred.shape[1] // 2 if atm_idx < 0 else atm_idx
    return float(np.sqrt(np.mean((pred[:, atm_col] - target[:, atm_col]) ** 2)))


def smile_slope_rmse(pred: np.ndarray, target: np.ndarray, eps: float = 1e-4) -> float:
    k = np.arange(pred.shape[1], dtype=float)
    pred_slope = np.gradient(pred, k, axis=1)
    target_slope = np.gradient(target, k, axis=1)
    atm_col = pred.shape[1] // 2
    return float(np.sqrt(np.mean((pred_slope[:, atm_col] - target_slope[:, atm_col]) ** 2)))
