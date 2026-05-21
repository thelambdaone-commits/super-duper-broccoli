import pytest
from ledger.ledger_db import Ledger
from utils.access_control import AccessControlManager

@pytest.fixture
def temp_ledger(tmp_path):
    db_path = tmp_path / "test_ledger_access.db"
    # The Ledger automatically applies schemas and alter tables
    ledger = Ledger(db_path=str(db_path))
    return ledger

def test_access_control_manager_initialization():
    ac = AccessControlManager(admin_chat_ids=[123, 456])
    assert ac.est_admin(123) is True
    assert ac.est_admin(456) is True
    assert ac.est_admin(789) is False

def test_access_control_wallet_assignment():
    ac = AccessControlManager(admin_chat_ids=[123])
    # Verify default mapping
    assert ac.obtenir_wallet_associe(789) == "DEFAULT_ISOLATED_WALLET_789"

    # Assign wallet
    ac.assigner_wallet_a_chat(789, "0xMyTenantWallet")
    assert ac.obtenir_wallet_associe(789) == "0xMyTenantWallet"

def test_ledger_multi_tenant_columns(temp_ledger):
    # Verify positions and paper_positions schemas have tenant_wallet
    cursor = temp_ledger.conn.cursor()

    cursor.execute("PRAGMA table_info(positions)")
    pos_cols = [row["name"] for row in cursor.fetchall()]
    assert "tenant_wallet" in pos_cols

    cursor.execute("PRAGMA table_info(paper_positions)")
    paper_cols = [row["name"] for row in cursor.fetchall()]
    assert "tenant_wallet" in paper_cols

def test_ledger_record_order_tenant_wallet(temp_ledger):
    # Setup capital allocation
    cursor = temp_ledger.conn.cursor()
    cursor.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) "
        "VALUES (10000.0, 10000.0, 10.0)"
    )
    temp_ledger.conn.commit()

    # Record order with tenant wallet
    temp_ledger.record_order("pos-tenant", "SOL", "BUY", 0.5, 1000, tenant_wallet="0xTenantA")

    # Verify storage
    cursor.execute("SELECT tenant_wallet FROM positions WHERE position_id = 'pos-tenant'")
    row = cursor.fetchone()
    assert row is not None
    assert row["tenant_wallet"] == "0xTenantA"

def test_ledger_record_paper_order_tenant_wallet(temp_ledger):
    # Record paper order with tenant wallet
    res = temp_ledger.record_paper_order(
        ticker="SOL", side="BUY", price=0.5, size=1000,
        confidence=0.8, regime_label="BULLISH", signal_source="test",
        tenant_wallet="0xTenantB"
    )

    position_id = res["position_id"]

    # Verify storage
    cursor = temp_ledger.conn.cursor()
    cursor.execute("SELECT tenant_wallet FROM paper_positions WHERE position_id = ?", (position_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row["tenant_wallet"] == "0xTenantB"


