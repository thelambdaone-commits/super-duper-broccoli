import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from utils.wallet_manager import WalletManager, TokenBalance, WalletSnapshot
from web3.exceptions import Web3ValidationError


@pytest.fixture
def wallet_manager():
    """Create a mock WalletManager for testing."""
    with patch('utils.wallet_manager.Web3'):
        manager = WalletManager.__new__(WalletManager)
        manager.w3 = Mock()
        manager.chain_id = 137
        manager.rpc_url = "https://polygon-rpc.com"
        manager._token_contracts = {}
        manager._token_decimals = {"USDC": 6, "POL": 18}
        return manager


def test_wallet_manager_init():
    """Test WalletManager initialization."""
    with patch('utils.wallet_manager.Web3') as MockWeb3:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = True
        MockWeb3.return_value = mock_w3
        
        with patch('utils.wallet_manager.resolve_rpc_with_fallback') as mock_rpc:
            mock_rpc.return_value = "https://polygon-rpc.com"
            manager = WalletManager()
            assert manager.chain_id == 137
            assert manager.rpc_url == "https://polygon-rpc.com"


def test_wallet_manager_is_valid_address():
    """Test address validation."""
    with patch('utils.wallet_manager.Web3') as MockWeb3:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = True
        MockWeb3.return_value = mock_w3
        
        with patch('utils.wallet_manager.resolve_rpc_with_fallback') as mock_rpc:
            mock_rpc.return_value = "https://polygon-rpc.com"
            manager = WalletManager()
            
            # Valid address
            with patch('utils.wallet_manager.Web3.to_checksum_address') as mock_checksum:
                mock_checksum.return_value = "0x742d35Cc6634C0532925a3b844Bc9e7595f42dE"
                assert manager.is_valid_address("0x742d35Cc6634C0532925a3b844Bc9e7595f42dE")
            
            # Invalid address
            with patch('utils.wallet_manager.Web3.to_checksum_address') as mock_checksum:
                mock_checksum.side_effect = Web3ValidationError("Invalid address")
                assert not manager.is_valid_address("invalid_address")


def test_wallet_manager_health_check():
    """Test health check."""
    with patch('utils.wallet_manager.Web3') as MockWeb3:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = True
        mock_block = {"number": 12345}
        mock_w3.eth.get_block.return_value = mock_block
        MockWeb3.return_value = mock_w3
        
        with patch('utils.wallet_manager.resolve_rpc_with_fallback') as mock_rpc:
            mock_rpc.return_value = "https://polygon-rpc.com"
            manager = WalletManager()
            health = manager.health_check()
            
            assert health["status"] == "healthy"
            assert health["connected"] == True
            assert health["chain_id"] == 137
            assert health["latest_block"] == 12345


def test_get_eth_balance():
    """Test ETH/MATIC balance retrieval."""
    with patch('utils.wallet_manager.Web3') as MockWeb3:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.get_balance.return_value = 1000000000000000000  # 1 MATIC
        mock_w3.from_wei.return_value = 1.0
        mock_w3.to_checksum_address.return_value = "0x742d35Cc6634C0532925a3b844Bc9e7595f42dE"
        MockWeb3.return_value = mock_w3
        
        with patch('utils.wallet_manager.resolve_rpc_with_fallback') as mock_rpc:
            mock_rpc.return_value = "https://polygon-rpc.com"
            manager = WalletManager()
            balance = manager.get_eth_balance("0x742d35Cc6634C0532925a3b844Bc9e7595f42dE")
            
            assert balance == 1.0


def test_format_balance_report():
    """Test balance report formatting."""
    with patch('utils.wallet_manager.Web3') as MockWeb3:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = True
        MockWeb3.return_value = mock_w3
        
        with patch('utils.wallet_manager.resolve_rpc_with_fallback') as mock_rpc:
            mock_rpc.return_value = "https://polygon-rpc.com"
            manager = WalletManager()
            
            with patch.object(manager, 'get_snapshot') as mock_snapshot:
                snapshot = WalletSnapshot(
                    wallet_address="0x742d35Cc6634C0532925a3b844Bc9e7595f42dE",
                    timestamp=1234567890,
                    balances={
                        "USDC": TokenBalance(
                            token="USDC",
                            address="0x742d35Cc6634C0532925a3b844Bc9e7595f42dE",
                            raw_balance=1000000000,
                            decimals=6,
                            formatted_balance=1000.0,
                        )
                    },
                    eth_balance=1.5,
                )
                mock_snapshot.return_value = snapshot
                
                report = manager.format_balance_report("0x742d35Cc6634C0532925a3b844Bc9e7595f42dE")
                
                assert "💰" in report
                assert "Wallet Balances" in report
                assert "MATIC" in report
                assert "USDC" in report
