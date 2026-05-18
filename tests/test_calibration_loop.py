import os
import pytest
import tempfile
import numpy as np
from unittest.mock import MagicMock

from ledger.ledger_db import Ledger
from core.training_pipeline import TrainingPipeline

def test_online_probability_calibration_loop() -> None:
    # 1. Create an in-memory Ledger database
    ledger = Ledger(db_path=":memory:")
    
    # Verify the schema setup of paper_positions
    cursor = ledger.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_positions'")
    assert cursor.fetchone() is not None

    # 2. Populate exactly 12 closed paper positions to satisfy the loop requirements (len >= 10, unique(is_win) == 2)
    for i in range(12):
        # Alternating wins and losses, with varying confidence levels
        is_win = i % 2
        confidence = 0.55 + (i * 0.03) # 0.55 to 0.91
        position_id = f"paper-sim-pos-{i}"
        
        cursor.execute(
            "INSERT INTO paper_positions (position_id, ticker, side, entry_price, size, capital_virtual, confidence, regime_label, status, is_win, closed_at) "
            "VALUES (?, 'SOL', 'BUY', 0.50, 100.0, 50.0, ?, 'LOW_VOLATILITY', 'CLOSED', ?, CURRENT_TIMESTAMP)",
            (position_id, confidence, is_win)
        )
    ledger.conn.commit()

    # 3. Create a temp directory for model storage to prevent polluting the workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock FeatureStore
        mock_store = MagicMock()
        mock_store.record_calibration = MagicMock()
        
        # Instantiate TrainingPipeline
        pipeline = TrainingPipeline(
            store=mock_store,
            model_dir=tmpdir,
            min_train_samples=10,
        )

        # 4. Trigger the dynamic online calibration loop!
        calibration_log = pipeline.update_calibration_from_paper_trades("SOL", ledger)

        # 5. Assertions: ensure the isotonic regression fits, registers, and stores metadata
        assert calibration_log is not None
        assert "SOL" in pipeline._calibrators
        
        calibrator = pipeline._calibrators["SOL"]
        assert calibrator is not None
        assert os.path.exists(os.path.join(tmpdir, "SOL_calibrator.pkl"))
        
        # Test out-of-sample prediction using the newly fitted online calibrator
        test_proba = np.array([[0.3, 0.7]]) # 70% confidence YES
        calibrated_proba = calibrator.predict_proba(test_proba)
        
        assert calibrated_proba.shape == (1, 2)
        assert 0.0 <= calibrated_proba[0, 1] <= 1.0
        
        # Verify the feature store recorded the calibration update
        assert mock_store.record_calibration.called
        call_kwargs = mock_store.record_calibration.call_args[1]
        assert call_kwargs["ticker"] == "SOL"
        assert call_kwargs["model_version"] == "online_reinforcement"
