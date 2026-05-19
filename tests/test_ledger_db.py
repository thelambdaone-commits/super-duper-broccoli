import os
import pytest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from ledger.ledger_db import Ledger
from utils.exceptions import QuantFatal

@pytest.fixture
def temp_ledger(tmp_path):
    db_path = tmp_path / "test_ledger.db"
    # Copy schema to temp location if needed, but Ledger uses relative path to find it.
    # We need to make sure the schema path is correct relative to the test runner.
    # Actually, Ledger class derives SCHEMA_PATH relative to its own file.
    ledger = Ledger(db_path=str(db_path))
    return ledger

def test_ledger_initialization(temp_ledger):
    assert os.path.exists(temp_ledger.db_path)
    # Check if tables exist
    cursor = temp_ledger.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='capital_allocation'")
    assert cursor.fetchone() is not None

def test_execution_mode_persistence(temp_ledger):
    temp_ledger.set_execution_mode("SHADOW")
    assert temp_ledger.get_execution_mode() == "SHADOW"
    
    temp_ledger.set_execution_mode("PROD")
    assert temp_ledger.get_execution_mode() == "PROD"


def test_execution_mode_can_be_read_from_worker_threads(temp_ledger):
    temp_ledger.set_execution_mode("SHADOW")

    with ThreadPoolExecutor(max_workers=8) as executor:
        modes = list(executor.map(lambda _: temp_ledger.get_execution_mode(), range(32)))

    assert modes == ["SHADOW"] * 32

def test_capital_allocation_and_reserve(temp_ledger):
    # Initialize allocation
    cursor = temp_ledger.conn.cursor()
    cursor.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) "
        "VALUES (10000.0, 10000.0, 10.0)"
    )
    temp_ledger.conn.commit()
    
    # Test valid reservation (10% of 10000 = 1000)
    res = temp_ledger.validate_and_reserve("SOL", "BUY", 0.5, 1000)
    assert res["authorized"] is True
    assert res["size"] == 1000
    
    # Test adjustment by circuit breaker (2000 > 1000 hard cap)
    res = temp_ledger.validate_and_reserve("SOL", "BUY", 0.5, 4000)
    assert res["authorized"] is True
    assert res["size"] == 2000 # 1000 / 0.5
    assert "adjusted" in res["reason"].lower()

    # Test insufficient funds
    res = temp_ledger.validate_and_reserve("SOL", "BUY", 1.0, 15000)
    assert res["authorized"] is False
    assert "Insufficient" in res["reason"]

def test_record_order_updates_capital(temp_ledger):
    # Initialize allocation
    cursor = temp_ledger.conn.cursor()
    cursor.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) "
        "VALUES (10000.0, 10000.0, 10.0)"
    )
    temp_ledger.conn.commit()
    
    temp_ledger.record_order(
        "pos-1",
        "SOL",
        "BUY",
        0.5,
        1000,
        requested_qty=1000,
        filled_qty=1000,
        execution_price=0.5,
        notional_usd=500.0,
    )
    
    summary = temp_ledger.get_capital_summary()
    assert summary["available_capital"] == 9500.0 # 10000 - (0.5 * 1000)
    
    positions = temp_ledger.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "SOL"
    assert positions[0]["requested_qty"] == 1000.0
    assert positions[0]["filled_qty"] == 1000.0
    assert positions[0]["execution_price"] == 0.5
    assert positions[0]["notional_usd"] == 500.0

    tx = temp_ledger.conn.execute("SELECT * FROM transactions WHERE position_id = ?", ("pos-1",)).fetchone()
    assert tx["requested_qty"] == 1000.0
    assert tx["filled_qty"] == 1000.0
    assert tx["execution_price"] == 0.5
    assert tx["notional_usd"] == 500.0


def test_record_order_rolls_back_on_mid_transaction_failure(temp_ledger):
    cursor = temp_ledger.conn.cursor()
    cursor.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) "
        "VALUES (10000.0, 10000.0, 10.0)"
    )
    cursor.execute(
        """
        CREATE TRIGGER fail_transaction_insert
        BEFORE INSERT ON transactions
        BEGIN
            SELECT RAISE(ABORT, 'forced transaction failure');
        END;
        """
    )
    temp_ledger.conn.commit()

    with pytest.raises(QuantFatal):
        temp_ledger.record_order(
            "pos-fail",
            "SOL",
            "BUY",
            0.5,
            1000,
            requested_qty=1000,
            filled_qty=1000,
            execution_price=0.5,
            notional_usd=500.0,
        )

    assert temp_ledger.get_capital_summary()["available_capital"] == 10000.0
    tx_count = temp_ledger.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert tx_count == 0
