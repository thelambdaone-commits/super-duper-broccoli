# Chart Pattern Detection Skill (YOLOv8)

## Purpose
Detect candlestick chart patterns (Head & Shoulders, Triangles, W-Bottom, M-Head) using YOLOv8 computer vision model. Generate chart images from OHLCV data and run object detection inference.

## Triggers
- `/chart patterns` — List supported patterns
- `/chart detect --ticker AAPL` — Detect patterns on latest price data

## Execution Steps
1. Load `ChartPatternDetector` from `utils.chart_pattern_detector`
2. Prepare OHLCV data (180-candle window recommended)
3. Generate candlestick chart image via mplfinance
4. Run YOLOv8 inference via ultralytics
5. Return detected patterns with confidence scores and bounding boxes

## Behavioral Boundaries
- Requires ultralytics and mplfinance packages
- Model detects only 6 pattern classes (Head and shoulders top/bottom, M_Head, StockLine, Triangle, W_Bottom)
- Confidence threshold default 0.5; adjust for precision vs recall
- Use as confirming signal only, not standalone trading decision
