import pytest
import numpy as np

try:
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from schemas.risk.bsm_pricing import bsm_call, bsm_delta, bartlett_delta
from schemas.risk.sabr_sim import SABRSimulator
from schemas.risk.envs import HedgingEnv


class TestBSMPricing:
    def test_bsm_call_atm(self):
        price = bsm_call(S=100, K=100, T=1.0, r=0.0, sigma=0.2)
        assert price > 0

    def test_bsm_call_itm(self):
        price = bsm_call(S=110, K=100, T=0.5, r=0.0, sigma=0.2)
        itm_value = max(0, 110 - 100)
        assert price >= itm_value * 0.5

    def test_bsm_delta_atm(self):
        delta = bsm_delta(S=100, K=100, T=1.0, r=0.0, sigma=0.2)
        assert 0 < delta < 1

    def test_bartlett_delta(self):
        delta = bartlett_delta(S=100, K=100, T=1.0, r=0.0, sigma=0.2, alpha=0.3, rho=-0.4, nu=0.6)
        assert isinstance(delta, float)


class TestSABRSimulator:
    def test_simulate_single_path(self):
        sim = SABRSimulator(S0=100, alpha=0.3, beta=1.0, rho=-0.4, nu=0.6)
        result = sim.simulate(n_steps=10, n_paths=1, seed=42)
        assert result["S"].shape == (1, 11)
        assert result["S"][0, 0] == 100.0
        assert result["n_paths"] == 1

    def test_simulate_multiple_paths(self):
        sim = SABRSimulator()
        result = sim.simulate(n_steps=5, n_paths=3, seed=42)
        assert result["S"].shape == (3, 6)


class TestHedgingEnv:
    def test_reset(self):
        env = HedgingEnv()
        state = env.reset(seed=42)
        assert state.shape == (3,)

    def test_step(self):
        env = HedgingEnv()
        state = env.reset(seed=42)
        next_state, reward, done, _ = env.step(action=0.5)
        assert isinstance(reward, float)
        assert next_state.shape == (3,)

    def test_step_until_done(self):
        env = HedgingEnv(S0=100, T=5.0 / 252)
        state = env.reset(seed=42)
        done = False
        steps = 0
        while not done:
            state, reward, done, _ = env.step(action=0.5)
            steps += 1
        assert steps > 0


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")
class TestDDPGAgent:
    def test_agent_init(self):
        from schemas.risk.ddpg_agent import DDPGHedgingAgent
        agent = DDPGHedgingAgent()
        assert agent.actor is not None
        assert agent.critic is not None

    def test_select_action(self):
        from schemas.risk.ddpg_agent import DDPGHedgingAgent
        agent = DDPGHedgingAgent()
        state = np.array([100.0, 0.0, 0.5], dtype=np.float32)
        action = agent.select_action(state)
        assert 0 <= action <= 1.0

    def test_replay_buffer(self):
        from schemas.risk.ddpg_agent import ReplayBuffer
        buf = ReplayBuffer(capacity=100)
        buf.push(np.array([1.0, 2.0, 3.0]), 0.5, 1.0, np.array([1.1, 2.1, 2.9]), False)
        assert len(buf) == 1
        sample = buf.sample(1)
        assert len(sample) == 5

    def test_train_step(self):
        from schemas.risk.ddpg_agent import DDPGHedgingAgent
        env = HedgingEnv(T=3.0 / 252)
        agent = DDPGHedgingAgent()
        state = env.reset(seed=42)
        done = False
        while not done:
            action = agent.select_action(state, noise=0.5)
            next_state, reward, done, _ = env.step(action)
            agent.replay.push(state, action, reward, next_state, done)
            state = next_state
        losses = agent.train_step(batch_size=4)
        assert "loss_actor" in losses
        assert "loss_critic" in losses
