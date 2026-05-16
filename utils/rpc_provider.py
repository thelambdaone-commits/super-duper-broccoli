import os
from typing import Optional

RPC_ENV_KEYS: dict[str, str] = {
    "polygon": "POLYGON_RPC_URL",
    "eth": "ETH_RPC_URL",
    "ethereum": "ETH_RPC_URL",
    "sol": "SOL_RPC_URL",
    "solana": "SOL_RPC_URL",
    "arb": "ARB_RPC_URL",
    "arbitrum": "ARB_RPC_URL",
    "opt": "OPTIMISM_RPC_URL",
    "optimism": "OPTIMISM_RPC_URL",
    "base": "BASE_RPC_URL",
}

BLOCK_EXPLORER_KEYS: dict[str, str] = {
    "btc": "BTC_API_URL",
    "ltc": "LTC_API_URL",
    "bch": "BCH_API_URL",
}

STAKING_RPC_KEYS: dict[str, str] = {
    "sol": "STAKING_SOL_RPC_URL",
    "solana": "STAKING_SOL_RPC_URL",
}

CHAIN_IDS: dict[str, int] = {
    "polygon": 137,
    "eth": 1,
    "ethereum": 1,
    "arb": 42161,
    "arbitrum": 42161,
    "opt": 10,
    "optimism": 10,
    "base": 8453,
    "sol": 901,
    "solana": 901,
}

FALLBACK_RPC_URLS: dict[str, list[str]] = {
    "polygon": [
        "https://polygon-rpc.com",
        "https://rpc-mainnet.maticvigil.com",
        "https://rpc-mainnet.matic.network",
    ],
    "eth": [
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
        "https://ethereum.publicnode.com",
    ],
    "ethereum": [
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
        "https://ethereum.publicnode.com",
    ],
    "arb": [
        "https://arb1.arbitrum.io/rpc",
        "https://rpc.ankr.com/arbitrum",
    ],
    "arbitrum": [
        "https://arb1.arbitrum.io/rpc",
        "https://rpc.ankr.com/arbitrum",
    ],
    "opt": [
        "https://mainnet.optimism.io",
        "https://rpc.ankr.com/optimism",
    ],
    "optimism": [
        "https://mainnet.optimism.io",
        "https://rpc.ankr.com/optimism",
    ],
    "base": [
        "https://mainnet.base.org",
        "https://rpc.ankr.com/base",
    ],
}


def get_rpc_url(chain: str, staking: bool = False) -> str:
    if staking:
        key = STAKING_RPC_KEYS.get(chain.lower())
        if key:
            return os.getenv(key, "")
    key = RPC_ENV_KEYS.get(chain.lower())
    if key:
        return os.getenv(key, "")
    return os.getenv(f"{chain.upper()}_RPC_URL", "")


def get_block_explorer_url(asset: str) -> str:
    key = BLOCK_EXPLORER_KEYS.get(asset.lower())
    if key:
        return os.getenv(key, "")
    return os.getenv(f"{asset.upper()}_API_URL", "")


def get_ws_url() -> str:
    return os.getenv("WS_URL", "")


def get_rpc_map() -> dict[str, str]:
    result: dict[str, str] = {}
    for chain, key in RPC_ENV_KEYS.items():
        val = os.getenv(key, "")
        if val:
            result[chain] = val
    return result


def resolve_rpc_from_secrets(
    chain: str,
    secrets: Optional[dict[str, str]] = None,
    staking: bool = False,
) -> str:
    if staking:
        staking_key = STAKING_RPC_KEYS.get(chain.lower())
        if staking_key and secrets:
            val = secrets.get(staking_key)
            if val:
                return val
    key = RPC_ENV_KEYS.get(chain.lower())
    if not key:
        key = f"{chain.upper()}_RPC_URL"
    if secrets and key in secrets:
        return secrets[key]
    return os.getenv(key, "")


def resolve_rpc_with_fallback(chain: str) -> str:
    primary = get_rpc_url(chain)
    if primary:
        return primary
    chain_key = chain.lower()
    if chain_key in FALLBACK_RPC_URLS:
        for fallback in FALLBACK_RPC_URLS[chain_key]:
            if fallback:
                return fallback
    return ""


def get_fallback_urls(chain: str) -> list[str]:
    return FALLBACK_RPC_URLS.get(chain.lower(), [])


def get_all_configured_chains() -> list[str]:
    chains: list[str] = []
    for chain, key in RPC_ENV_KEYS.items():
        val = os.getenv(key, "")
        if val:
            label = chain.capitalize() if chain not in ("eth", "opt", "arb") else chain.upper()
            chains.append(f"{label} (env)")
        elif FALLBACK_RPC_URLS.get(chain):
            label = chain.capitalize() if chain not in ("eth", "opt", "arb") else chain.upper()
            chains.append(f"{label} (fallback)")
    for asset, key in BLOCK_EXPLORER_KEYS.items():
        if os.getenv(key, ""):
            chains.append(f"{asset.upper()} explorer")
    return chains
