# Polymarket Strategy Coverage

Updated: 2026-05-20

## Couverture

| Famille | Statut | Module |
| --- | --- | --- |
| Market making passif | Integre | `PassiveMarketMakingStrategy` |
| Market making dynamique | Integre | `DynamicMarketMakingStrategy` |
| Momentum / trend following | Integre | `MomentumBreakoutStrategy`, `MacroTrendMLStrategy` |
| Mean reversion | Integre | `MeanReversionStrategy` |
| Scalping micro-spreads | Integre | `MicroScalpingStrategy` |
| Swing trading | Integre | `SwingCatalystStrategy` |
| Buy-and-hold directionnel | Integre | `DirectionalConvictionStrategy` |
| Contrarian | Integre | `ContrarianExcessStrategy` |
| Arbitrage inter-market | Integre | `InterMarketArbitrageStrategy` |
| Arbitrage intra-market | Integre | `IntraMarketArbitrageStrategy` |
| Arbitrage bundles/spreads combines | Integre | `BundleSpreadArbitrageStrategy` |
| Oracle/off-chain public lag | Integre, public-data only | `PublicOracleLagStrategy` |
| Sentiment analysis | Integre | `SemanticMomentumStrategy` |
| News-driven trading | Integre | `NewsDrivenStrategy` |
| Event/calendar trading | Integre | `CalendarEventStrategy` |
| Public on-chain signal following | Integre | `PublicOnchainFlowStrategy` |
| Expected value betting | Integre | `ExpectedValueStrategy` |
| Kelly sizing | Existant | `PortfolioRiskEngine` |
| Bayesian updating | Integre | `BayesianUpdateStrategy` |
| Monte Carlo scenarios | Integre | `MonteCarloEdgeStrategy` |
| Reinforcement learning loop | Existant | `scripts/reinforcement_optimization_loop.py` |
| Stop-loss / take-profit | Existant | `AutonomousTradingLoop` + `Ledger` |
| Hedging / correlated markets | Integre | `PairsTradingStrategy`; risk hedge modules exist separately |
| Exposure limits / diversification | Existant | `PortfolioRiskEngine`, `Ledger` |
| TWAP/VWAP style execution | Existant | `FragmentedOrderExecutor` |
| Limit / market / post-only | Existant | `PassiveExecutor`, `PolymarketOrderManager` |
| Monitoring / alerting | Existant | PM2, health supervisor, notifier, dashboards |
| Backtesting / paper trading | Existant | `StrategyLifecycleManager`, `PolymarketPaperEngine` |
| Fees / slippage | Existant | risk/backtest/execution modules |
| Security / resilience | Existant | Vault, RBAC, circuit breakers, websocket reconnect |
| Compliance / ethics | Guarded | private/abusive tactics are not implemented |

## Explicitement Non Implémente

- Sandwich-like tactics: non implemente par conception. Risque de manipulation de marche, interdiction de plateforme et comportement abusif.
- Exploitation d'informations privees: non implemente. Seuls signaux publics/news/on-chain publics sont autorises.

## Point D'Integration

Le catalogue standard est `build_default_polymarket_strategies()` dans `user_data/strategies/polymarket_strategy_factory.py`.
Chaque strategie retourne un `StrategySignal` convertible en signal d'execution standard, puis passe par le lifecycle manager, le mode controller, le ledger et le risk engine.
