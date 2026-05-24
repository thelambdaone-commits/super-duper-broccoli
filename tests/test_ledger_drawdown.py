import sqlite3

from ledger.ledger_db import Ledger


def test_get_global_drawdown_inside_existing_transaction(tmp_path) -> None:
    ledger = Ledger(db_path=str(tmp_path / "ledger.db"))

    with ledger._transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO capital_allocation (total_capital, allocated_pct, available_capital)
            VALUES (?, ?, ?)
            """,
            (1000.0, 100.0, 1000.0),
        )
        drawdown = ledger.get_global_drawdown()

    assert isinstance(drawdown, float)

