# Portfolio Optimization Skill

## Purpose
Optimize multi-asset portfolio weights using modern portfolio theory (mean-variance, risk parity, CVaR) via scikit-portfolio, PyPortfolioOpt, or Riskfolio-Lib backends.

## Triggers
- `/portfolio optimize --tickers AAPL,MSFT,GOOGL --method max_sharpe` — Run optimization

## Execution Steps
1. Load `PortfolioOptimizer` from `models.portfolio.optimizer`
2. Prepare historical price DataFrame
3. Select optimization method: min_volatility, max_sharpe, risk_parity, cvar, equal_weight
4. Run optimization — auto-detects available libraries (scikit-portfolio > PyPortfolioOpt > Riskfolio-Lib)
5. Return optimized weights with library used

## Behavioral Boundaries
- Equal-weight fallback always available (no external deps required)
- Mean-variance assumes normal return distributions — use CVaR for fat tails
- All weights are long-only by default
- Do NOT override existing Kelly sizing in portfolio_risk_engine.py
