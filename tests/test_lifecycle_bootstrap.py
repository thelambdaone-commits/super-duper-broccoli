import inspect
import os
import tempfile

from core.lifecycle import BotLifecycle
from database.ledger_db import Ledger


def test_lifecycle_creates_orchestrator_before_scheduler_registration() -> None:
    source = inspect.getsource(BotLifecycle.start)

    assert source.index("orchestrator = LobstarOrchestrator(") < source.index("_setup_quantum_runner(")


def test_ledger_performance_by_source_handles_prod_schema_columns() -> None:
    db_path = os.path.join(tempfile.gettempdir(), "test_ledger_perf_source.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    ledger = Ledger(db_path=db_path)
    try:
        columns = {
            row[1]
            for row in ledger.conn.execute("PRAGMA table_info(positions)").fetchall()
        }

        assert "signal_source" in columns
        assert "is_win" in columns
        assert ledger.get_performance_summary_by_source(mode="PROD") == {}
    finally:
        ledger.conn.close()
        if os.path.exists(db_path):
            os.remove(db_path)
