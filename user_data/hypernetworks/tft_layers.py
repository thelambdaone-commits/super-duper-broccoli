import torch
import torch.nn as nn
import math
from typing import Optional, Tuple


class GatedLinearUnit(nn.Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.gate = nn.Linear(dim, dim)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x) * torch.sigmoid(self.gate(x))


class GatedResidualNetwork(nn.Module):
    def __init__(self, d_input: int, d_hidden: int, d_output: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(d_input, d_hidden)
        self.gelu = nn.GELU()
        self.glu = GatedLinearUnit(d_hidden)
        self.fc2 = nn.Linear(d_hidden, d_output)
        self.dropout = nn.Dropout(0.1)
        self.skip = nn.Linear(d_input, d_output) if d_input != d_output else nn.Identity()
        self.ln = nn.LayerNorm(d_output)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skip = self.skip(x)
        out = self.fc1(x)
        out = self.gelu(out)
        out = self.glu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        return self.ln(skip + out)


class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int) -> None:
        super().__init__()
        assert d_model % n_heads == 0
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads
        self.q = nn.Linear(d_model, d_model)
        self.k = nn.Linear(d_model, d_model)
        self.v = nn.Linear(d_model, d_model)
        self.out = nn.Linear(d_model, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, D = x.shape
        Q = self.q(x).view(B, T, self.n_heads, self.d_k).transpose(1, 2)
        K = self.k(x).view(B, T, self.n_heads, self.d_k).transpose(1, 2)
        V = self.v(x).view(B, T, self.n_heads, self.d_k).transpose(1, 2)
        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(self.d_k)
        attn = torch.softmax(scores, dim=-1)
        out = torch.matmul(attn, V).transpose(1, 2).contiguous().view(B, T, D)
        return self.out(out)


class TemporalFusionTransformer(nn.Module):
    def __init__(
        self,
        d_features: int,
        d_model: int = 128,
        n_heads: int = 4,
        n_lstm_layers: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if d_model % n_heads != 0:
            raise ValueError(f"d_model ({d_model}) must be divisible by n_heads ({n_heads})")
        if d_features < 1:
            raise ValueError(f"d_features must be positive, got {d_features}")
        self.input_proj = nn.Linear(d_features, d_model)
        self.lstm = nn.LSTM(
            d_model, d_model, n_lstm_layers, batch_first=True, dropout=dropout
        )
        self.grn = GatedResidualNetwork(d_model, d_model, d_model)
        self.attention = MultiHeadAttention(d_model, n_heads)
        self.ln = nn.LayerNorm(d_model)
        self.output_proj = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.input_proj(x)
        lstm_out, _ = self.lstm(x)
        grn_out = self.grn(lstm_out)
        attn_out = self.attention(grn_out)
        out = self.ln(grn_out + attn_out)
        return self.output_proj(out[:, -1, :])
