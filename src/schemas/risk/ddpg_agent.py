import random
from collections import deque
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim


class Actor(nn.Module):
    def __init__(self, state_dim: int = 3, action_dim: int = 1, max_action: float = 1.0):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Linear(64, action_dim),
            nn.Sigmoid(),
        )
        self.max_action = max_action

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state) * self.max_action


class Critic(nn.Module):
    def __init__(self, state_dim: int = 3, action_dim: int = 1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim + action_dim, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Linear(64, 1),
        )

    def forward(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        return self.net(torch.cat([state, action], dim=-1))


class ReplayBuffer:
    def __init__(self, capacity: int = 100000):
        self.buffer = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        batch = random.sample(self.buffer, min(batch_size, len(self.buffer)))
        state = torch.tensor(np.array([b[0] for b in batch]), dtype=torch.float32)
        action = torch.tensor(np.array([b[1] for b in batch]), dtype=torch.float32).unsqueeze(-1)
        reward = torch.tensor(np.array([b[2] for b in batch]), dtype=torch.float32).unsqueeze(-1)
        next_state = torch.tensor(np.array([b[3] for b in batch]), dtype=torch.float32)
        done = torch.tensor(np.array([b[4] for b in batch]), dtype=torch.float32).unsqueeze(-1)
        return state, action, reward, next_state, done

    def __len__(self):
        return len(self.buffer)


class DDPGHedgingAgent:
    def __init__(
        self,
        state_dim: int = 3,
        action_dim: int = 1,
        max_action: float = 1.0,
        lr_actor: float = 1e-4,
        lr_critic: float = 1e-3,
        gamma: float = 0.99,
        tau: float = 1e-5,
        buffer_capacity: int = 100000,
        device: Optional[str] = None,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_action = max_action
        self.gamma = gamma
        self.tau = tau

        self.actor = Actor(state_dim, action_dim, max_action).to(self.device)
        self.actor_target = Actor(state_dim, action_dim, max_action).to(self.device)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.actor_opt = optim.Adam(self.actor.parameters(), lr=lr_actor)

        self.critic = Critic(state_dim, action_dim).to(self.device)
        self.critic_target = Critic(state_dim, action_dim).to(self.device)
        self.critic_target.load_state_dict(self.critic.state_dict())
        self.critic_opt = optim.Adam(self.critic.parameters(), lr=lr_critic)

        self.replay = ReplayBuffer(buffer_capacity)
        self.mse = nn.MSELoss()

    def select_action(self, state: np.ndarray, noise: float = 0.0) -> float:
        s = torch.tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
        self.actor.eval()
        with torch.no_grad():
            action = self.actor(s).cpu().numpy()[0, 0]
        self.actor.train()
        if noise > 0:
            action += np.random.randn() * noise
        return float(np.clip(action, 0.0, self.max_action))

    def train_step(self, batch_size: int = 128) -> dict:
        if len(self.replay) < batch_size:
            return {"loss_actor": 0.0, "loss_critic": 0.0}
        state, action, reward, next_state, done = self.replay.sample(batch_size)
        state = state.to(self.device)
        action = action.to(self.device)
        reward = reward.to(self.device)
        next_state = next_state.to(self.device)
        done = done.to(self.device)

        with torch.no_grad():
            next_action = self.actor_target(next_state)
            target_q = self.critic_target(next_state, next_action)
            target = reward + (1 - done) * self.gamma * target_q

        current_q = self.critic(state, action)
        critic_loss = self.mse(current_q, target)
        self.critic_opt.zero_grad()
        critic_loss.backward()
        self.critic_opt.step()

        actor_loss = -self.critic(state, self.actor(state)).mean()
        self.actor_opt.zero_grad()
        actor_loss.backward()
        self.actor_opt.step()

        for tp, p in zip(self.actor_target.parameters(), self.actor.parameters()):
            tp.data.copy_(self.tau * p.data + (1 - self.tau) * tp.data)
        for tp, p in zip(self.critic_target.parameters(), self.critic.parameters()):
            tp.data.copy_(self.tau * p.data + (1 - self.tau) * tp.data)

        return {
            "loss_actor": round(float(actor_loss.detach()), 6),
            "loss_critic": round(float(critic_loss.detach()), 6),
        }

    def save(self, path: str):
        torch.save({
            "actor": self.actor.state_dict(),
            "critic": self.critic.state_dict(),
        }, path)

    def load(self, path: str):
        ckpt = torch.load(path, map_location=self.device, weights_only=True)
        self.actor.load_state_dict(ckpt["actor"])
        self.critic.load_state_dict(ckpt["critic"])
