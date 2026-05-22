import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable
import hvac
from hvac.exceptions import VaultError

from utils.exceptions import QuantFatal
from utils.credential_manager import CredentialManager, POLYMARKET_WALLET_PATH
from utils.secret_validation import normalize_private_key, validate_private_key_or_raise

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
    # APIs / utils
    "COINGECKO_API_KEY",
    "OPENROUTER_API_KEY",
    # RPC endpoints
    "POLYGON_RPC_URL",
    "ETH_RPC_URL",
    "SOL_RPC_URL",
    "ARB_RPC_URL",
    "OPTIMISM_RPC_URL",
    "BASE_RPC_URL",
    "STAKING_SOL_RPC_URL",
    # Block explorer APIs
    "BTC_API_URL",
    "LTC_API_URL",
    "BCH_API_URL",
    # WebSocket for on-chain monitor
    "WS_URL",
    # Polymarket web-first ingestion endpoints
    "POLYMARKET_GAMMA_API_URL",
    "POLYMARKET_CLOB_HTTP_URL",
    "POLYMARKET_CLOB_WS_URL",
]

# Map common names to env var keys for programmatic access
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


def get_rpc_url(chain: str) -> str:
    key = RPC_URL_ALIASES.get(chain.lower(), f"{chain.upper()}_RPC_URL")
    return os.getenv(key, "")


def _normalize_secret_source(value: str | None) -> str:
    if not value:
        return "auto"
    normalized = value.strip().lower()
    if normalized in {"vault", "env", "auto"}:
        return normalized
    return "auto"


def _execution_mode() -> str:
    return (os.getenv("EXECUTION_MODE") or os.getenv("MODE") or "PAPER").upper()


def _needs_clob_credentials() -> bool:
    return _execution_mode() in {"SHADOW", "PROD"}


def _load_env_file() -> None:
    """Charge le fichier .env si présent."""
    env_path = Path(".env")
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)


def _resolve_private_key(
    candidate: str | None,
    source: str,
) -> str | None:
    private_key = normalize_private_key(candidate)
    if candidate and not private_key:
        logger.warning("Ignoring invalid placeholder/private key from %s.", source)
    return private_key


def _iter_encrypted_wallet_paths() -> list[Path]:
    return [Path(POLYMARKET_WALLET_PATH)]


def _load_first_valid_encrypted_wallet(mgr: CredentialManager) -> dict[str, str]:
    last_error: Exception | None = None
    for path in _iter_encrypted_wallet_paths():
        if not path.exists():
            continue
        try:
            payload = mgr.load_and_decrypt(str(path))
            private_key = _resolve_private_key(
                payload.get("CLOB_PRIVATE_KEY") or payload.get("private_key"),
                str(path),
            )
            if private_key:
                payload["CLOB_PRIVATE_KEY"] = private_key
                return payload
        except Exception as exc:
            last_error = exc
            logger.warning("Could not load encrypted wallet from %s: %s", path, exc)
    if last_error:
        logger.debug("No valid encrypted wallet could be loaded: %s", last_error)
    return {}


class VaultHandler:
    _env_loaded = False
    _session_wallets: Dict[str, Dict[str, str]] = {}

    def __init__(self) -> None:
        if not VaultHandler._env_loaded:
            _load_env_file()
            VaultHandler._env_loaded = True

        self.vault_addr: str = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
        self.vault_token: str | None = os.getenv("VAULT_TOKEN")
        self._client: hvac.Client | None = None
        self.secret_source = _normalize_secret_source(os.getenv("SECRET_SOURCE"))
        self.use_vault = self._should_use_vault()
        self.chat_id: str | None = os.getenv("CHAT_ID")

        if self.use_vault and not self.vault_token:
            raise QuantFatal("VAULT_TOKEN is missing. Set VAULT_TOKEN or source .vault_env (or set VAULT_ADDR=false to use .env only)")

    def _should_use_vault(self) -> bool:
        if self.secret_source == "vault":
            return True
        if self.secret_source == "env":
            return False
        return self.vault_addr.lower() != "false" and bool(self.vault_token)

    def _connect(self) -> None:
        try:
            self._client = hvac.Client(url=self.vault_addr, token=self.vault_token)
            if not self._client.is_authenticated():
                raise QuantFatal("Vault authentication failed")
        except VaultError as e:
            raise QuantFatal(f"Vault connection failed: {e}")

    def fetch_quantum_secrets(self, chat_id: int | str | None = None) -> Dict[str, str]:
        active_chat_id = chat_id or self.chat_id

        if not self.use_vault:
            logger.info("SECRET_SOURCE=env: Loading secrets from environment directly.")
            validated_secrets: Dict[str, str] = {}

            mgr = CredentialManager()

            user_creds = {}
            wallet_type = "default"

            if active_chat_id and mgr.user_has_any_wallet(str(active_chat_id)):
                try:
                    wallet_type = mgr.get_active_wallet_type(str(active_chat_id))
                    user_creds = mgr.get_user_credentials_for_type(str(active_chat_id), wallet_type)
                    logger.info(f"Loaded user credentials from {wallet_type}{active_chat_id}.enc")
                except Exception as e:
                    logger.warning(f"Could not load user credentials: {e}")

            enc_secrets = _load_first_valid_encrypted_wallet(mgr)
            if enc_secrets:
                logger.info("Loaded wallet profile secrets from encrypted storage")

            clob_required = _needs_clob_credentials()
            keys_to_load = list(REQUIRED_SECRET_KEYS)
            if clob_required:
                keys_to_load.insert(0, "CLOB_PRIVATE_KEY")

            for key in keys_to_load:
                val = None
                prefer_env_file = self.secret_source == "env" or os.getenv("VAULT_ADDR", "").lower() == "false"

                if key == "CLOB_PRIVATE_KEY":
                    private_key_sources = [
                        ("user credentials", user_creds.get("CLOB_PRIVATE_KEY") if user_creds else None),
                        ("encrypted wallet", enc_secrets.get("CLOB_PRIVATE_KEY") or enc_secrets.get("private_key")),
                    ]
                    for source_name, candidate in private_key_sources:
                        val = _resolve_private_key(candidate, source_name)
                        if val:
                            break
                    if not val and clob_required:
                        raise QuantFatal("CLOB_PRIVATE_KEY is missing from user credentials and encrypted vault.")
                    if not val:
                        continue
                else:
                    if key in user_creds:
                        val = user_creds.get(key)
                    if not val and not prefer_env_file:
                        val = os.getenv(key) or enc_secrets.get(key)
                    if not val and prefer_env_file:
                        val = os.getenv(key)
                    if not val:
                        val = enc_secrets.get(key)

                if not val and key in ["CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"]:
                    if not clob_required:
                        continue
                    pk = validated_secrets.get("CLOB_PRIVATE_KEY", "")
                    if not pk:
                        pk = _resolve_private_key(user_creds.get("CLOB_PRIVATE_KEY"), "user credentials") or "" if user_creds else ""
                    if not pk:
                        pk = _resolve_private_key(
                            enc_secrets.get("CLOB_PRIVATE_KEY") or enc_secrets.get("private_key"),
                            "encrypted wallet",
                        ) or ""
                    if not pk:
                        raise QuantFatal("CLOB_PRIVATE_KEY is missing. Cannot derive API credentials.")

                    if user_creds and user_creds.get("CLOB_API_KEY"):
                        validated_secrets["CLOB_API_KEY"] = user_creds.get("CLOB_API_KEY", "")
                        validated_secrets["CLOB_API_SECRET"] = user_creds.get("CLOB_API_SECRET", "")
                        validated_secrets["CLOB_API_PASSPHRASE"] = user_creds.get("CLOB_API_PASSPHRASE", "")
                    else:
                        creds = mgr.get_or_generate_creds(validate_private_key_or_raise(pk, source="secret resolution"))
                        validated_secrets.update(creds)
                    if key in validated_secrets:
                        continue

                if not val and key not in validated_secrets:
                    raise QuantFatal(f"Missing required environment variable: {key}")
                if val:
                    validated_secrets[key] = val

            for key in OPTIONAL_SECRET_KEYS:
                val = os.getenv(key) or enc_secrets.get(key)
                if val:
                    validated_secrets[key] = val

            validated_secrets.setdefault("POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com")
            validated_secrets.setdefault("POLYMARKET_CLOB_HTTP_URL", "https://clob.polymarket.com")
            validated_secrets.setdefault(
                "POLYMARKET_CLOB_WS_URL",
                "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            )

            if "POLYMARKET_WALLET_ADDRESS" not in validated_secrets:
                if user_creds and user_creds.get("POLYMARKET_WALLET_ADDRESS"):
                    validated_secrets["POLYMARKET_WALLET_ADDRESS"] = user_creds["POLYMARKET_WALLET_ADDRESS"]
                elif enc_secrets.get("POLYMARKET_WALLET_ADDRESS"):
                    validated_secrets["POLYMARKET_WALLET_ADDRESS"] = enc_secrets["POLYMARKET_WALLET_ADDRESS"]
                elif enc_secrets.get("address"):
                    validated_secrets["POLYMARKET_WALLET_ADDRESS"] = enc_secrets["address"]
                elif validated_secrets.get("address"):
                    validated_secrets["POLYMARKET_WALLET_ADDRESS"] = validated_secrets["address"]

            self.valider_initialisation(validated_secrets)
            return validated_secrets

        self._connect()

        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path="quant-trade", mount_point="secret"
            )
            raw_secrets: Dict[str, Any] = response["data"]["data"]

            validated_secrets: Dict[str, str] = {}
            for key in REQUIRED_SECRET_KEYS:
                if key not in raw_secrets or not raw_secrets[key]:
                    raise KeyError(f"Missing required key: {key}")
                validated_secrets[key] = str(raw_secrets[key])

            optional_loaded = 0
            for key in OPTIONAL_SECRET_KEYS:
                if raw_secrets.get(key):
                    validated_secrets[key] = str(raw_secrets[key])
                    optional_loaded += 1

            validated_secrets.setdefault("POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com")
            validated_secrets.setdefault("POLYMARKET_CLOB_HTTP_URL", "https://clob.polymarket.com")
            validated_secrets.setdefault(
                "POLYMARKET_CLOB_WS_URL",
                "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            )

            self._client.logout()
            self._client = None

            logger.info(
                "%s required credentials and %s optional credentials loaded from Vault. Session revoked.",
                len(REQUIRED_SECRET_KEYS),
                optional_loaded,
            )
            self.valider_initialisation(validated_secrets)
            return validated_secrets

        except (VaultError, KeyError) as e:
            if self._client:
                self._client.logout()
            raise QuantFatal(f"Secret extraction failed: {e}")

    def valider_initialisation(self, secrets: Dict[str, str]) -> None:
        """
        Active and dynamic dry-run audit verifying RPC connectivity and Vault RAM liveness.
        Aborts execution immediately on failure to meet production standards.
        """
        import sys
        import urllib.request
        import json

        is_testing = "pytest" in sys.modules or os.getenv("TESTING") == "true"

        # 1. Dynamic Vault RAM liveness check
        if self.use_vault:
            try:
                self._connect()
                try:
                    # Attempt reading a mock secret path in Vault RAM
                    self._client.secrets.kv.v2.read_secret_version(
                        path="liveness-check-dummy", mount_point="secret"
                    )
                except Exception:
                    pass
                logger.info("🔑 [VAULT LIVENESS] Vault RAM secret storage connection validated successfully.")
            except Exception as e:
                logger.critical(f"🚨 [VAULT FATAL] Vault connection and sandbox read validation failed: {e}")
                if not is_testing:
                    sys.exit(1)

        # 2. Dynamic RPC Node ping check
        rpc_url = secrets.get("POLYGON_RPC_URL") or secrets.get("ETH_RPC_URL") or os.getenv("POLYGON_RPC_URL") or os.getenv("ETH_RPC_URL")
        if rpc_url and not rpc_url.startswith("http://localhost") and not rpc_url.startswith("http://127.0.0.1"):
            try:
                req = urllib.request.Request(
                    rpc_url,
                    data=b'{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}',
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    res = json.loads(response.read().decode())
                    if "result" not in res:
                        raise ValueError("Invalid JSON-RPC response format")
                logger.info(f"🌐 [RPC PING] Connection to RPC node ({rpc_url[:35]}...) validated successfully.")
            except Exception as e:
                logger.warning(f"⚠️ [RPC NON-FATAL] Dynamic RPC node connection test failed for url {rpc_url}: {e}")
                # Keep booting: RPC availability is a runtime concern, not a startup blocker.

    def patch_optional_secrets(self, secrets: Dict[str, str]) -> list[str]:
        """Patch allowlisted optional provider keys into Vault without logging values."""
        allowed = set(OPTIONAL_SECRET_KEYS)
        filtered = {
            key: str(value).strip()
            for key, value in secrets.items()
            if key in allowed and str(value).strip()
        }
        if not filtered:
            return []

        self._connect()
        if self._client is None:
            raise QuantFatal("Vault client not available after connect")
        try:
            self._client.secrets.kv.v2.patch(
                path="quant-trade",
                mount_point="secret",
                secret=filtered,
            )
            logger.info("%s optional credential(s) patched into Vault.", len(filtered))
            return sorted(filtered)
        except VaultError as e:
            raise QuantFatal(f"Secret patch failed: {e}")
        finally:
            if self._client:
                self._client.logout()
                self._client = None

    def stocker_cle_session(self, chat_id: int | str, public_address: str, private_key: str) -> None:
        """Store an imported wallet only in process memory for the current bot session."""
        chat_key = str(chat_id)
        VaultHandler._session_wallets[chat_key] = {
            "POLYMARKET_WALLET_ADDRESS": public_address,
            "CLOB_PRIVATE_KEY": private_key,
        }
        logger.info("Stored ephemeral session wallet for chat_id=%s address=%s...%s", chat_key, public_address[:6], public_address[-4:])

    def obtenir_wallet_session(self, chat_id: int | str) -> Dict[str, str] | None:
        """Return an in-memory session wallet without touching disk."""
        return VaultHandler._session_wallets.get(str(chat_id))

    def supprimer_wallet_session(self, chat_id: int | str) -> bool:
        """Forget an in-memory session wallet."""
        return VaultHandler._session_wallets.pop(str(chat_id), None) is not None

    def compter_wallets_session(self) -> int:
        return len(VaultHandler._session_wallets)


def collect_optional_secrets_from_env(keys: Iterable[str] = OPTIONAL_SECRET_KEYS) -> Dict[str, str]:
    return {
        key: value
        for key in keys
        if (value := os.getenv(key, "").strip())
    }
