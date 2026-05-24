# Advanced Feature Engineering Skill

## Purpose
Compute 40+ technical features from OHLCV data including momentum indicators, volatility measures, mean-reversion oscillators, volume analysis, and calendar effects for ML model training.

## Triggers
- `/features compute --ticker AAPL` — Compute all features for a ticker
- `/features list` — List available feature categories

## Execution Steps
1. Load `FeatureFactory` from `utils.feature_factory` with OHLCV DataFrame
2. Automatic computation across 5 categories:
   - Momentum: returns at 1/2/3/5/10/21/63d, MA ratios
   - Volatility: realized/downside/upside vol, ATR, vol regime
   - Mean-Reversion: Bollinger Bands, RSI, MACD, Stochastic
   - Volume: Z-score, MA ratios, OBV
   - Calendar: day-of-week, month, quarter dummies
3. Return feature matrix (numpy array) or DataFrame
4. Store selected features in FeatureStore for model training

## Behavioral Boundaries
- All features computed with lookahead-bias prevention (shift/expand semantics)
- RSI and Bollinger Band features use standard 14 and 20-period windows
- Calendar features require DatetimeIndex
- Features are NOT validated for stationarity — apply differencing if needed
