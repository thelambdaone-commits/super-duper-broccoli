import logging
from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from web3.contract import Contract
from web3.exceptions import Web3ValidationError, BlockNotFound

from utils.rpc_provider import resolve_rpc_with_fallback

logger = logging.getLogger("WalletManager")

# Token addresses on Polygon (MATIC mainnet, chain_id=137)
POLYGON_TOKENS = {
    "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDC_E": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDC_NATIVE": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    "POL": "0x455e53CBB86018Ac2B8092FDD3C0b784F1693313",
    "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
}

# ERC20 ABI (minimal for balanceOf + decimals)
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]


@dataclass
class TokenBalance:
    """Represents a token balance."""
    token: str
    address: str
    raw_balance: int
    decimals: int
    formatted_balance: float

    @property
    def human_readable(self) -> str:
        return f"{self.formatted_balance:.4f} {self.token}"


@dataclass
class WalletSnapshot:
    """Snapshot of wallet state at a moment."""
    wallet_address: str
    timestamp: float
    balances: dict[str, TokenBalance]
    eth_balance: float
    total_usd_value: Optional[float] = None


class WalletManager:
    """Manages wallet balance tracking on Polygon."""

    def __init__(self, polygon_rpc_url: Optional[str] = None, chain_id: int = 137):
        self.chain_id = chain_id
        self.rpc_url = polygon_rpc_url or resolve_rpc_with_fallback("polygon")
        
        if not self.rpc_url:
            raise ValueError("Could not resolve Polygon RPC URL. Check env vars.")
        
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.w3.is_connected():
                logger.warning(f"Web3 not connected to {self.rpc_url}. Retrying...")
                self.rpc_url = resolve_rpc_with_fallback("polygon", force_fallback=True)
                self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        except Exception as e:
            logger.error(f"Failed to initialize Web3: {e}")
            raise
        
        self._token_contracts: dict[str, Contract] = {}
        self._token_decimals: dict[str, int] = {}
        self._balance_cache: dict[str, tuple[float, TokenBalance]] = {}
        self._eth_balance_cache: dict[str, tuple[float, float]] = {}
        self._load_token_contracts()

    def _load_token_contracts(self):
        """Load ERC20 contract interfaces for known tokens."""
        for token_name, token_address in POLYGON_TOKENS.items():
            try:
                contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=ERC20_ABI,
                )
                self._token_contracts[token_name] = contract
                decimals = contract.functions.decimals().call()
                self._token_decimals[token_name] = decimals
                logger.debug(f"Loaded {token_name} contract with {decimals} decimals")
            except Exception as e:
                logger.warning(f"Failed to load {token_name} contract: {e}")

    def get_eth_balance(self, wallet_address: str) -> float:
        """Get native ETH balance (actually MATIC on Polygon)."""
        import time
        now = time.time()
        if wallet_address in self._eth_balance_cache:
            ts, cached_bal = self._eth_balance_cache[wallet_address]
            if now - ts < 10.0:
                return cached_bal

        try:
            address = Web3.to_checksum_address(wallet_address)
            wei_balance = self.w3.eth.get_balance(address)
            balance = float(self.w3.from_wei(wei_balance, "ether"))
            self._eth_balance_cache[wallet_address] = (now, balance)
            return balance
        except Web3ValidationError as e:
            logger.error(f"Invalid address {wallet_address}: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Failed to get ETH balance for {wallet_address}: {e}")
            return 0.0

    def get_token_balance(
        self, wallet_address: str, token: str
    ) -> Optional[TokenBalance]:
        """Get ERC20 token balance."""
        token_upper = token.upper()
        
        if token_upper not in self._token_contracts:
            logger.error(f"Token {token} not found. Supported: {list(POLYGON_TOKENS.keys())}")
            return None

        import time
        now = time.time()
        cache_key = f"{wallet_address}:{token_upper}"
        if cache_key in self._balance_cache:
            ts, cached_bal = self._balance_cache[cache_key]
            if now - ts < 10.0:
                return cached_bal
        
        try:
            address = Web3.to_checksum_address(wallet_address)
            contract = self._token_contracts[token_upper]
            raw_balance = contract.functions.balanceOf(address).call()
            decimals = self._token_decimals[token_upper]
            formatted = raw_balance / (10 ** decimals)
            
            balance = TokenBalance(
                token=token_upper,
                address=wallet_address,
                raw_balance=raw_balance,
                decimals=decimals,
                formatted_balance=formatted,
            )
            self._balance_cache[cache_key] = (now, balance)
            return balance
        except Web3ValidationError as e:
            logger.error(f"Invalid address {wallet_address}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get {token_upper} balance: {e}")
            return None

    def get_balances(self, wallet_address: str, tokens: list[str]) -> dict[str, TokenBalance]:
        """Get multiple token balances at once."""
        balances = {}
        for token in tokens:
            bal = self.get_token_balance(wallet_address, token)
            if bal:
                balances[token.upper()] = bal
        return balances

    def get_all_balances(self, wallet_address: str) -> dict[str, TokenBalance | float]:
        """Get all tracked balances for a wallet."""
        balances = {}
        
        # ETH/MATIC balance
        eth_bal = self.get_eth_balance(wallet_address)
        balances["MATIC"] = eth_bal
        
        # Token balances
        for token in POLYGON_TOKENS.keys():
            bal = self.get_token_balance(wallet_address, token)
            if bal:
                balances[token] = bal
        
        return balances

    def get_snapshot(self, wallet_address: str) -> WalletSnapshot:
        """Get a full wallet snapshot."""
        import time
        
        balances = {}
        eth_balance = self.get_eth_balance(wallet_address)
        
        for token in POLYGON_TOKENS.keys():
            bal = self.get_token_balance(wallet_address, token)
            if bal:
                balances[token] = bal
        
        return WalletSnapshot(
            wallet_address=Web3.to_checksum_address(wallet_address),
            timestamp=time.time(),
            balances=balances,
            eth_balance=eth_balance,
        )

    def format_balance_report(self, wallet_address: str) -> str:
        """Generate a human-readable balance report."""
        lines = [f"💰 **Wallet Balances** (`{wallet_address[:6]}...{wallet_address[-4:]}`)\n"]
        
        snapshot = self.get_snapshot(wallet_address)
        
        lines.append(f"• MATIC: `{snapshot.eth_balance:.6f}`")
        for token, bal in snapshot.balances.items():
            if isinstance(bal, TokenBalance):
                lines.append(f"• {token}: `{bal.formatted_balance:.6f}`")
        
        return "\n".join(lines)

    def is_valid_address(self, address: str) -> bool:
        """Check if address is valid Ethereum address."""
        try:
            Web3.to_checksum_address(address)
            return True
        except Web3ValidationError:
            return False

    def health_check(self) -> dict:
        """Check wallet manager health."""
        try:
            block = self.w3.eth.get_block("latest")
            return {
                "status": "healthy",
                "rpc_url": self.rpc_url,
                "chain_id": self.chain_id,
                "latest_block": block.get("number", 0),
                "connected": True,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "rpc_url": self.rpc_url,
                "chain_id": self.chain_id,
                "connected": False,
            }
