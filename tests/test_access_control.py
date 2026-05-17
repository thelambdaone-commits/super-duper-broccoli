import os
import pytest
import sqlite3
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ledger.ledger_db import Ledger
from utils.access_control import AccessControlManager
from telegram_scraper.telegram_listener import TelegramListener

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

@pytest.mark.asyncio
async def test_telegram_listener_admin_command_intercept():
    # Setup listener with AccessControlManager
    ac = AccessControlManager(admin_chat_ids=[123])
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        admin_chat_ids={123},
        access_control=ac
    )
    
    # Test unauthorized call
    msg_unauth = SimpleNamespace(chat_id=999, chat=SimpleNamespace(type="private"), reply_text=AsyncMock())
    update_unauth = SimpleNamespace(message=msg_unauth, channel_post=None)
    
    # Assert intercept blocks and replies Unauthorized
    assert await listener._check_admin_auth(update_unauth) is False
    msg_unauth.reply_text.assert_awaited_once_with("Unauthorized.", parse_mode="Markdown")
    
    # Test authorized call
    msg_auth = SimpleNamespace(chat_id=123, chat=SimpleNamespace(type="private"), reply_text=AsyncMock())
    update_auth = SimpleNamespace(message=msg_auth, channel_post=None)
    
    assert await listener._check_admin_auth(update_auth) is True

@pytest.mark.asyncio
async def test_telegram_listener_callback_intercept():
    ac = AccessControlManager(admin_chat_ids=[123])
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        admin_chat_ids={123},
        access_control=ac
    )
    
    # Test unauthorized callback
    query_unauth = SimpleNamespace(
        message=SimpleNamespace(chat_id=999),
        data="balance",
        answer=AsyncMock()
    )
    update_unauth = SimpleNamespace(callback_query=query_unauth)
    
    await listener._handle_callback(update_unauth, None)
    
    # Should reply showing alert
    query_unauth.answer.assert_awaited_once_with("Unauthorized.", show_alert=True)
