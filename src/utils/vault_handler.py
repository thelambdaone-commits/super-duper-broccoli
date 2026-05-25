from dotenv import load_dotenv
import logging
import os
from pathlib import Path
from typing import Dict, Iterable

from utils import credential_manager as credential_manager_module
from utils.credential_manager import CredentialManager
from utils.exceptions import QuantFatal
from utils.secret_validation import normalize_private_key

logger = logging.getLogger("VaultHandler")

REQUIRED_SECRET_KEYS = [
    "CLOB_API_KEY",
    "CLOB_API_SECRET",
    "CLOB_API_PASSPHRASE",
]

OPTIONAL_SECRET_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "COINGECKO_API_KEY",
    "OPENROUTER_API_KEY",
    "POLYGON_RPC_URL",
    "ETH_RPC_URL",
    "SOL_RPC_URL",
    "ARB_RPC_URL",
    "OPTIMISM_RPC_URL",
    "BASE_RPC_URL",
    "STAKING_SOL_RPC_URL",
    "BTC_API_URL",
    "LTC_API_URL",
    "BCH_API_URL",
    "WS_URL",
    "POLYMARKET_GAMMA_API_URL",
    "POLYMARKET_CLOB_HTTP_URL",
    "POLYMARKET_CLOB_WS_URL",
    "POLYMARKET_WALLET_ADDRESS",
    "EOA_ADDRESS",
    "POLYMARKET_PROXY_WALLET_ADDRESS",
    "PROXY_WALLET_ADDRESS",
    "POLYMARKET_FUNDER",
    "POLYMARKET_SIGNATURE_TYPE",
]

RPC_URL_ALIASES: dict[str, str] = {
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

# Backward-compatible patch point for tests and legacy callers.
POLYMARKET_WALLET_PATH = credential_manager_module.POLYMARKET_WALLET_PATH


def get_rpc_url(chain: str) -> str:
    key = RPC_URL_ALIASES.get(chain.lower(), f"{chain.upper()}_RPC_URL")
    return os.getenv(key, "")


def _load_env_file() -> None:
    candidate_paths = [
        Path(".env"),
        Path(os.getenv("SECRETS_PATH", "secrets")) / ".env",
    ]
    for env_path in candidate_paths:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _encrypted_wallet_path() -> Path:
    return Path(globals().get("POLYMARKET_WALLET_PATH", credential_manager_module.POLYMARKET_WALLET_PATH))


class VaultHandler:
    _session_wallets: Dict[str, Dict[str, str]] = {}

    def __init__(self) -> None:
        load_dotenv(override=False)
        self.chat_id: str | None = os.getenv("CHAT_ID") or None

    def fetch_quantum_secrets(self, chat_id: int | str | None = None) -> Dict[str, str]:
        _load_env_file()
        validated_secrets: Dict[str, str] = {}
        execution_mode = str(os.getenv("EXECUTION_MODE", "PAPER")).upper()
        secret_source = str(os.getenv("SECRET_SOURCE", "")).lower()

        enc_wallet_secrets: Dict[str, str] = {}
        wallet_path = _encrypted_wallet_path()
        enc_wallet_exists = wallet_path.exists()
        if enc_wallet_exists:
            try:
                enc_wallet_secrets = CredentialManager().load_and_decrypt(str(wallet_path))
            except Exception as exc:
                raise QuantFatal(f"Failed to load encrypted wallet credentials: {exc}") from exc

        # Runtime policy: when configured for env-only secrets, a raw env private key is not acceptable
        # unless it has already been materialized into the encrypted wallet file.
        if (
            execution_mode not in {"PAPER", "REPLAY"}
            and secret_source == "env"
            and os.getenv("CLOB_PRIVATE_KEY")
            and not enc_wallet_exists
        ):
            raise QuantFatal("CLOB_PRIVATE_KEY is missing from user credentials and encrypted vault")

        raw_pk = enc_wallet_secrets.get("CLOB_PRIVATE_KEY")
        if not raw_pk and execution_mode not in {"PAPER", "REPLAY"}:
            raw_pk = os.getenv("CLOB_PRIVATE_KEY")
        pk = normalize_private_key(raw_pk)
        if pk:
            validated_secrets["CLOB_PRIVATE_KEY"] = pk

        for key in REQUIRED_SECRET_KEYS:
            val = enc_wallet_secrets.get(key) or os.getenv(key) or os.getenv(key.lower())
            if val:
                validated_secrets[key] = val
            elif execution_mode not in {"PAPER", "REPLAY"}:
                raise QuantFatal(f"Missing required environment variable: {key}")

        for key in OPTIONAL_SECRET_KEYS:
            val = enc_wallet_secrets.get(key) or os.getenv(key)
            if val:
                validated_secrets[key] = val

        for alias_key in ("address", "POLYMARKET_WALLET_ADDRESS", "EOA_ADDRESS"):
            if alias_key in enc_wallet_secrets and enc_wallet_secrets[alias_key]:
                value = enc_wallet_secrets[alias_key]
                validated_secrets.setdefault("POLYMARKET_WALLET_ADDRESS", value)
                validated_secrets.setdefault("EOA_ADDRESS", value)

        validated_secrets.setdefault("POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com")
        validated_secrets.setdefault("POLYMARKET_CLOB_HTTP_URL", "https://clob.polymarket.com")
        validated_secrets.setdefault(
            "POLYMARKET_CLOB_WS_URL",
            "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        )

        return validated_secrets

    def stocker_cle_session(self, chat_id: int | str, public_address: str, private_key: str) -> None:
        chat_key = str(chat_id)
        VaultHandler._session_wallets[chat_key] = {
            "POLYMARKET_WALLET_ADDRESS": public_address,
            "EOA_ADDRESS": public_address,
            "CLOB_PRIVATE_KEY": private_key,
        }
        logger.info("Stored ephemeral session wallet for chat_id=%s address=%s...%s", chat_key, public_address[:6], public_address[-4:])

    def set_user_proxy(self, chat_id: int | str, proxy_address: str) -> None:
        chat_key = str(chat_id)
        if chat_key in VaultHandler._session_wallets:
            VaultHandler._session_wallets[chat_key]["proxy_wallet"] = proxy_address
            VaultHandler._session_wallets[chat_key]["POLYMARKET_PROXY_WALLET_ADDRESS"] = proxy_address
            VaultHandler._session_wallets[chat_key]["PROXY_WALLET_ADDRESS"] = proxy_address
            VaultHandler._session_wallets[chat_key]["POLYMARKET_FUNDER"] = proxy_address
            logger.info("Associated proxy %s with session wallet for chat_id=%s", proxy_address[:10], chat_key)

    def obtenir_wallet_session(self, chat_id: int | str) -> Dict[str, str] | None:
        return VaultHandler._session_wallets.get(str(chat_id))

    def supprimer_wallet_session(self, chat_id: int | str) -> bool:
        return VaultHandler._session_wallets.pop(str(chat_id), None) is not None

    def compter_wallets_session(self) -> int:
        return len(VaultHandler._session_wallets)


def collect_optional_secrets_from_env(keys: Iterable[str] = OPTIONAL_SECRET_KEYS) -> Dict[str, str]:
    return {
        key: value
        for key in keys
        if (value := os.getenv(key, "").strip())
    }
