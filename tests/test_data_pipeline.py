import os
import json
import time
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from scrapers.data_pipeline import JSONLStorageEngine, PredictiveOpinionEngine
from scripts.rl_feedback_loop import run_rl_feedback_loop
from ledger.ledger_db import Ledger

@pytest.mark.asyncio
async def test_jsonl_storage_engine_archives_successfully() -> None:
    test_path = "data/test_archive_events.jsonl"
    if os.path.exists(test_path):
        os.remove(test_path)

    payload = {"message_id": 123, "chat_id": 456, "text": "hello", "update": object()}
    
    await JSONLStorageEngine.archiver_evenement("test_event", payload, custom_path=test_path)
    
    # Wait for ThreadPoolExecutor to finish writing
    await asyncio.sleep(0.05)

    assert os.path.exists(test_path)
    with open(test_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["type"] == "test_event"
    assert event["payload"]["message_id"] == 123
    assert event["payload"]["chat_id"] == 456
    assert event["payload"]["text"] == "hello"
    # Ensure "update" was stripped
    assert "update" not in event["payload"]

    os.remove(test_path)

@pytest.mark.asyncio
async def test_predictive_opinion_engine_fallback() -> None:
    engine = PredictiveOpinionEngine(api_key="")
    opinion = await engine.analyse_signal("Signal: BUY SOL", ticker="SOL")
    
    assert isinstance(opinion, dict)
    assert "reasoning" in opinion
    assert "confidence" in opinion
    assert opinion["verdict"] == "HOLD"
    assert opinion["target_asset"] == "SOL"
    assert opinion["recommended_sizing_pct"] == 0.0

@pytest.mark.asyncio
async def test_predictive_opinion_engine_parse_json_result() -> None:
    engine = PredictiveOpinionEngine(api_key="mock")
    content = '{"reasoning": "Regime looks flat.", "confidence": 0.82, "verdict": "BUY", "target_asset": "BTC", "recommended_sizing_pct": 12.5}'
    parsed = engine._parse_json_result(content, "SOL")
    
    assert parsed["reasoning"] == "Regime looks flat."
    assert parsed["confidence"] == 0.82
    assert parsed["verdict"] == "BUY"
    assert parsed["target_asset"] == "BTC"
    assert parsed["recommended_sizing_pct"] == 12.5

@pytest.mark.asyncio
async def test_rl_feedback_loop_updates_weights() -> None:
    mock_positions = [
        {
            "position_id": "test-win-123",
            "ticker": "SOL",
            "pnl": 5.2,
            "is_win": 1,
            "side": "BUY"
        },
        {
            "position_id": "test-loss-456",
            "ticker": "BTC",
            "pnl": -3.5,
            "is_win": 0,
            "side": "SELL"
        }
    ]

    weights_path = "data/ml_weights.json"
    if os.path.exists(weights_path):
        os.remove(weights_path)

    with patch.object(Ledger, "get_paper_positions", return_value=mock_positions):
        run_rl_feedback_loop()

    assert os.path.exists(weights_path)
    with open(weights_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "bias_factors" in data
    # SOL had a win: 1.004 (EWMA with lambda 0.98, +10.4R win reward 1.20)
    assert abs(data["bias_factors"]["SOL"] - 1.004) < 1e-5
    # BTC had a loss: 0.994 (EWMA with lambda 0.98, -7.0R loss reward 0.70)
    assert abs(data["bias_factors"]["BTC"] - 0.994) < 1e-5
    assert "test-win-123" in data["processed_positions"]
    assert "test-loss-456" in data["processed_positions"]
    assert len(data["deviation_reports"]) == 1
    assert data["deviation_reports"][0]["position_id"] == "test-loss-456"

    os.remove(weights_path)
