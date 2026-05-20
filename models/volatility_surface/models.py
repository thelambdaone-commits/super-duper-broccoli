
import torch
import torch.nn as nn


class ReconstructionMLP(nn.Module):
    def __init__(self, input_dim: int = 4, hidden_dims: list[int | None] = None):
        super().__init__()
        if hidden_dims is None:
            hidden_dims = [64, 64, 32]
        prev = input_dim
        layers = []
        for h in hidden_dims:
            layers.extend([
                nn.Linear(prev, h),
                nn.GELU(),
                nn.Dropout(0.05),
            ])
            prev = h
        layers.append(nn.Linear(prev, 1))
        layers.append(nn.Softplus())
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


class ForecastGRU(nn.Module):
    def __init__(
        self,
        input_dim: int = 4,
        hidden_dim: int = 64,
        num_layers: int = 2,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.gru = nn.GRU(
            input_dim, hidden_dim, num_layers,
            batch_first=True, dropout=dropout,
        )
        self.linear = nn.Linear(hidden_dim, input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        last = x[:, -1:, :]
        out, _ = self.gru(x)
        delta = self.linear(out[:, -1:, :])
        return (last + delta).squeeze(1)
