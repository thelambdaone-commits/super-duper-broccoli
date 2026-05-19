# Earnings Call Sentiment Skill

## Purpose
Analyze earnings call transcripts for sentiment signals using FinBERT/FinancialBERT and optional earnings-analyzer package. Correlate sentiment with post-earnings stock performance.

## Triggers
- `/earnings status` — Check pipeline status
- `/earnings analyze --ticker AAPL` — Analyze latest earnings call

## Execution Steps
1. Use `EarningsSentimentPipeline` from `utils.earnings_sentiment_pipeline`
2. Fetch transcripts (via earnings-analyzer or Motley Fool scraper)
3. Run FinBERT sentiment analysis (ProsusAI/finbert or ahmedrachid/FinancialBERT)
4. Convert sentiment scores to features stored in FeatureStore
5. Track post-earnings performance windows (1w/1m/3m)

## Behavioral Boundaries
- Requires GEMINI_API_KEY and/or FMP_API_KEY for full earnings-analyzer features
- Falling back to FinBERT-only mode requires no external API keys
- Do NOT use earnings sentiment as sole trading signal
