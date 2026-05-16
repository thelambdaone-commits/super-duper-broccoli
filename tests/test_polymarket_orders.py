import pytest
from unittest.mock import Mock, MagicMock
from utils.polymarket_order_manager import PolymarketOrderManager, PolymarketOrder, ClaimReceipt
from utils.wallet_manager import WalletManager
from datetime import datetime


@pytest.fixture
def wallet_manager():
    """Create a mock wallet manager."""
    manager = Mock(spec=WalletManager)
    manager.wallet_address = "0x742d35Cc6634C0532925a3b844Bc9e7595f42dE"
    return manager


@pytest.fixture
def order_manager(wallet_manager):
    """Create a polymarket order manager."""
    return PolymarketOrderManager(
        wallet_manager=wallet_manager,
        private_key="0x0000000000000000000000000000000000000000000000000000000000000001",
    )


def test_order_manager_init(wallet_manager):
    """Test PolymarketOrderManager initialization."""
    manager = PolymarketOrderManager(wallet_manager=wallet_manager)
    assert manager.wallet_manager == wallet_manager
    assert len(manager._pending_orders) == 0


def test_estimate_bet_cost_buy():
    """Test bet cost estimation for BUY."""
    estimate = PolymarketOrderManager.estimate_bet_cost(None, 10, 0.5, "BUY")
    
    assert estimate["side"] == "BUY"
    assert estimate["amount"] == 10
    assert estimate["price"] == 0.5
    assert estimate["collateral_or_proceeds"] == 5.0  # 10 * 0.5
    assert estimate["fee_rate_bps"] == 200  # 2%
    assert estimate["fee_amount"] > 0
    assert estimate["potential_profit"] == 5.0  # 10 * (1 - 0.5)


def test_estimate_bet_cost_sell():
    """Test bet cost estimation for SELL."""
    estimate = PolymarketOrderManager.estimate_bet_cost(None, 10, 0.5, "SELL")
    
    assert estimate["side"] == "SELL"
    assert estimate["amount"] == 10
    assert estimate["price"] == 0.5
    assert estimate["collateral_or_proceeds"] == 5.0  # 10 * 0.5


def test_estimate_bet_cost_zero_price():
    """Test bet cost with zero price."""
    estimate = PolymarketOrderManager.estimate_bet_cost(None, 10, 0.0, "BUY")
    
    assert estimate["collateral_or_proceeds"] == 0.0
    assert estimate["fee_amount"] == 0.0
    assert estimate["total_cost"] == 0.0


def test_estimate_bet_cost_high_price():
    """Test bet cost with high price."""
    estimate = PolymarketOrderManager.estimate_bet_cost(None, 10, 0.9, "BUY")
    
    assert estimate["collateral_or_proceeds"] == 9.0  # 10 * 0.9
    assert abs(estimate["potential_profit"] - 1.0) < 0.001  # 10 * (1 - 0.9) with floating point tolerance
    assert estimate["roi_percent"] > 0


@pytest.mark.asyncio
async def test_place_order_dry_run(order_manager):
    """Test placing an order in dry run mode."""
    order = await order_manager.place_order(
        market_id="0xabcd1234",
        token_id="0xtoken123",
        outcome="YES",
        side="BUY",
        price=0.55,
        amount=10,
        dry_run=True,
    )
    
    assert order.market_id == "0xabcd1234"
    assert order.outcome == "YES"
    assert order.side == "BUY"
    assert order.price == 0.55
    assert order.amount == 10
    assert order.status == "pending"


@pytest.mark.asyncio
async def test_place_order_no_client(wallet_manager):
    """Test placing order when ClobClient not initialized."""
    manager = PolymarketOrderManager(wallet_manager=wallet_manager, clob_client=None)
    
    order = await manager.place_order(
        market_id="0xabcd",
        token_id="0xtoken",
        outcome="NO",
        side="SELL",
        price=0.40,
        amount=5,
    )
    
    assert order.status == "failed"
    assert order.error_message is not None


@pytest.mark.asyncio
async def test_claim_winnings_dry_run(order_manager):
    """Test claiming winnings in dry run mode."""
    receipt = await order_manager.claim_winnings(
        market_id="0xabcd1234",
        outcome="YES",
        dry_run=True,
    )
    
    assert receipt.market_id == "0xabcd1234"
    assert receipt.outcome == "YES"
    assert receipt.status == "pending"


@pytest.mark.asyncio
async def test_claim_winnings_no_client(wallet_manager):
    """Test claiming when ClobClient not initialized."""
    manager = PolymarketOrderManager(wallet_manager=wallet_manager, clob_client=None)
    
    receipt = await manager.claim_winnings(
        market_id="0xabcd",
        outcome="YES",
    )
    
    assert receipt.status == "failed"
    assert receipt.error_message is not None


def test_check_balance_for_bet(order_manager):
    """Test balance check for betting."""
    can_bet, msg = order_manager.check_balance_for_bet(10, 0.5, "BUY")
    
    assert can_bet is True
    assert "$" in msg or "USDC" in msg or "Need" in msg


def test_polymarket_order_potential_profit_buy():
    """Test potential profit calculation for BUY."""
    order = PolymarketOrder(
        order_id="order1",
        market_id="market1",
        token_id="token1",
        outcome="YES",
        side="BUY",
        price=0.6,
        amount=10,
        collateral_value=6,
        status="pending",
        created_at=datetime.utcnow(),
    )
    
    profit = order.potential_profit
    assert profit == 4.0  # 10 * (1 - 0.6)


def test_polymarket_order_potential_profit_sell():
    """Test potential profit calculation for SELL."""
    order = PolymarketOrder(
        order_id="order1",
        market_id="market1",
        token_id="token1",
        outcome="NO",
        side="SELL",
        price=0.4,
        amount=10,
        collateral_value=4,
        status="pending",
        created_at=datetime.utcnow(),
    )
    
    profit = order.potential_profit
    assert profit == 4.0  # 10 * 0.4


def test_format_order():
    """Test order formatting for display."""
    order = PolymarketOrder(
        order_id="order123",
        market_id="market456",
        token_id="token789",
        outcome="YES",
        side="BUY",
        price=0.60,
        amount=10,
        collateral_value=6.12,
        status="pending",
        created_at=datetime.utcnow(),
    )
    
    manager = PolymarketOrderManager(wallet_manager=Mock())
    formatted = manager.format_order(order)
    
    assert "📊" in formatted
    assert "order123" in formatted
    assert "BUY" in formatted
    assert "YES" in formatted
    assert "10" in formatted
    assert "0.60" in formatted


def test_format_claim_receipt():
    """Test claim receipt formatting."""
    receipt = ClaimReceipt(
        market_id="market123",
        outcome="YES",
        amount_claimed=10.50,
        status="pending",
    )
    
    manager = PolymarketOrderManager(wallet_manager=Mock())
    formatted = manager.format_claim_receipt(receipt)
    
    assert "🎉" in formatted
    assert "market123" in formatted
    assert "YES" in formatted
    assert "10.50" in formatted


def test_order_string_representation():
    """Test order string representation."""
    order = PolymarketOrder(
        order_id="order1",
        market_id="market1",
        token_id="token1",
        outcome="NO",
        side="SELL",
        price=0.35,
        amount=20,
        collateral_value=7,
        status="pending",
        created_at=datetime.utcnow(),
    )
    
    string_repr = str(order)
    assert "SELL" in string_repr
    assert "20" in string_repr
    assert "NO" in string_repr
    assert "0.35" in string_repr
