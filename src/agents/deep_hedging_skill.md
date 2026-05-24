# Deep Hedging RL Skill

## Purpose
Hedge options using deep reinforcement learning (DDPG) with SABR stochastic volatility simulation. Minimize mean-variance hedging error vs classical Black-Scholes delta hedging.

## Triggers
- `/hedge simulate --episodes 100 --s0 100` — Run DDPG hedging simulation
- `/hedge compare --ticker SPY` — Compare RL vs delta hedging

## Execution Steps
1. Create `HedgingEnv` with S0, K, T, sigma, spread parameters
2. Initialize `DDPGHedgingAgent` with actor/critic networks
3. For each episode: reset env → select actions → step → store replay → train
4. Track episode rewards and convergence
5. Compare with BSM delta and Bartlett delta baselines

## Behavioral Boundaries
- Simulation only — requires paper trading validation before any real use
- Default: 20-day option, daily rebalancing, spread cost model
- DDPG uses mean-variance objective; not suitable for path-dependent options
- SABR simulator supports beta=1 (stochastic vol lognormal), beta=0 (stochastic vol normal)
