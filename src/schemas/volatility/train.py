import logging
import math
import os
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from schemas.volatility.models import ReconstructionMLP, ForecastGRU

logger = logging.getLogger("VolSurfaceTrainer")


def train_reconstruction(
    model: ReconstructionMLP,
    surfaces: np.ndarray,
    strikes: np.ndarray,
    expiries: np.ndarray,
    lr: float = 1e-3,
    epochs: int = 100,
    batch_size: int = 1024,
    val_split: float = 0.2,
    device: Optional[str] = None,
    save_path: Optional[str] = None,
) -> dict:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device)

    n_surfaces, n_T, n_k = surfaces.shape
    atm_vol = np.mean(surfaces[:, :, n_k // 2], axis=1, keepdims=True)
    term_slope = surfaces[:, -1, n_k // 2] - surfaces[:, 0, n_k // 2]

    K_grid, T_grid = np.meshgrid(strikes, expiries)
    X_features = []
    for i in range(n_surfaces):
        for t_idx in range(n_T):
            for k_idx in range(n_k):
                X_features.append([
                    float(K_grid[t_idx, k_idx]),
                    math.sqrt(float(T_grid[t_idx, k_idx])),
                    float(atm_vol[i, 0]),
                    float(term_slope[i]),
                ])
    X = torch.tensor(X_features, dtype=torch.float32)
    y = torch.tensor(surfaces.reshape(-1, 1), dtype=torch.float32)

    n = len(X)
    perm = torch.randperm(n)
    n_val = int(n * val_split)
    val_idx = perm[:n_val]
    train_idx = perm[n_val:]
    train_loader = DataLoader(TensorDataset(X[train_idx], y[train_idx]), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(X[val_idx], y[val_idx]), batch_size=batch_size)

    model = model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    best_val_loss = float("inf")
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = nn.MSELoss()(model(xb), yb.squeeze(-1))
            loss.backward()
            opt.step()
            train_loss += loss.item() * len(xb)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                loss = nn.MSELoss()(model(xb), yb.squeeze(-1))
                val_loss += loss.item() * len(xb)

        train_loss /= len(train_idx)
        val_loss /= len(val_idx)
        if val_loss < best_val_loss and save_path:
            best_val_loss = val_loss
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            torch.save(model.state_dict(), save_path)
            logger.info(f"Epoch {epoch}: saved best model (val_loss={val_loss:.6f})")

    return {"train_loss": train_loss, "val_loss": val_loss, "best_val_loss": best_val_loss}


def train_forecast(
    model: ForecastGRU,
    dataset: np.ndarray,
    seq_len: int = 20,
    lr: float = 1e-3,
    epochs: int = 100,
    batch_size: int = 64,
    val_split: float = 0.2,
    device: Optional[str] = None,
    save_path: Optional[str] = None,
) -> dict:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device)

    params = dataset  # shape: (n_samples, 4)
    mean = params.mean(axis=0)
    std = params.std(axis=0) + 1e-8
    params_norm = (params - mean) / std

    sequences, targets = [], []
    for i in range(len(params_norm) - seq_len):
        sequences.append(params_norm[i:i + seq_len])
        targets.append(params_norm[i + seq_len])
    X = torch.tensor(np.array(sequences), dtype=torch.float32)
    y = torch.tensor(np.array(targets), dtype=torch.float32)

    n = len(X)
    n_val = max(1, int(n * val_split))
    perm = torch.randperm(n)
    train_loader = DataLoader(TensorDataset(X[perm[n_val:]], y[perm[n_val:]]), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(X[perm[:n_val]], y[perm[:n_val]]), batch_size=batch_size)

    model = model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    best_val_loss = float("inf")
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = nn.MSELoss()(model(xb), yb)
            loss.backward()
            opt.step()
            train_loss += loss.item() * len(xb)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                loss = nn.MSELoss()(model(xb), yb)
                val_loss += loss.item() * len(xb)

        train_loss /= max(1, n - n_val)
        val_loss /= max(1, n_val)
        if val_loss < best_val_loss and save_path:
            best_val_loss = val_loss
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            torch.save(model.state_dict(), save_path)

    return {"train_loss": train_loss, "val_loss": val_loss, "best_val_loss": best_val_loss}
