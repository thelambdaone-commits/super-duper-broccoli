# Macro Intelligence Skill

## Purpose
Estimate central bank policy rates via Taylor Rule variants, nowcast GDP from high-frequency indicators, and assess macro risk-on/risk-off regimes for portfolio positioning.

## Triggers
- `/macro taylor —inflation 3.0 --unemployment 4.0` — Estimate policy rate
- `/macro gdp --indicators {...}` — GDP nowcast
- `/macro risk` — Overall macro risk assessment

## Execution Steps
1. Load `MacroIntelligence` from `utils.macro_intelligence`
2. Call `taylor_rule()` with inflation, unemployment, current rate
3. Call `gdp_nowcast()` with high-frequency indicators (PMI, industrial production, retail sales, employment)
4. Call `risk_off_score()` to combine Taylor + GDP + VIX into regime signal
5. Feed macro regime into HMM regime detector for enriched signal

## Behavioral Boundaries
- Taylor Rule is a normative model, not a perfect predictor of central bank actions
- GDP nowcasting has R² ~0.83 (US) and ~0.46 (Canada) — use with confidence intervals
- FRED API key required for live data; manual parameter input for testing
