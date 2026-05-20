import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from cryptography.fernet import Fernet
from eth_account import Account
from utils.derive_clob_creds import derive_clob_credentials
from utils.secret_validation import validate_private_key_or_raise

logger = logging.getLogger("CredentialManager")

# Single canonical wallet file for mono-compte operation.
# All import/generate/switch operations overwrite this one file.
# DATA_PATH env var lets you relocate the data directory per environment.
DEFAULT_DATA_DIR = os.getenv("DATA_PATH", "data")
POLYMARKET_WALLET_PATH = os.path.join(DEFAULT_DATA_DIR, "polymarket.wallet.enc")

class CredentialManager:
    def __init__(self, encryption_key: Optional[str] = None) -> None:
        if not encryption_key:
            encryption_key = os.getenv("ENCRYPTION_KEY")

        if not encryption_key:
            # Generate a temporary key if none provided (for development, but warn)
            logger.warning("ENCRYPTION_KEY not set. Generating a temporary key.")
            self.key = Fernet.generate_key()
        else:
            self.key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key

        try:
            self.fernet = Fernet(self.key)
        except Exception as e:
            logger.error(f"Invalid ENCRYPTION_KEY: {e}")
            raise ValueError(f"Invalid encryption key: {e}")

    @staticmethod
    def _resolve_enc_path(path: str) -> Path:
        resolved = Path(path).resolve()
        data_dir = Path(DEFAULT_DATA_DIR).resolve()
        if not str(resolved).startswith(str(data_dir)):
            raise ValueError(f"Encrypted path must be within {DEFAULT_DATA_DIR}: {path}")
        return resolved

    def encrypt_and_save(self, creds: Dict[str, str], path: str = POLYMARKET_WALLET_PATH) -> None:
        target = self._resolve_enc_path(path)
        data = json.dumps(creds).encode()
        encrypted = self.fernet.encrypt(data)
        os.makedirs(str(target.parent), exist_ok=True)
        with open(str(target), "wb") as f:
            f.write(encrypted)
        logger.info(f"Credentials encrypted and saved to {target}")

    def load_and_decrypt(self, path: str = POLYMARKET_WALLET_PATH) -> Dict[str, str]:
        target = self._resolve_enc_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Encrypted credentials not found at {target}")

        with open(str(target), "rb") as f:
            encrypted = f.read()

        decrypted = self.fernet.decrypt(encrypted)
        return json.loads(decrypted.decode())

    def get_or_generate_creds(self, private_key: str, path: str = POLYMARKET_WALLET_PATH) -> Dict[str, str]:
        private_key = validate_private_key_or_raise(private_key, source=path)
        if os.path.exists(path):
            try:
                creds = self.load_and_decrypt(path)
                logger.info(f"Loaded credentials from {path}")
                return creds
            except Exception as e:
                logger.warning(f"Failed to decrypt {path}: {e}. Re-generating...")

        # Generate new credentials
        logger.info("Generating new CLOB credentials...")
        creds = derive_clob_credentials(private_key)
        creds["CLOB_PRIVATE_KEY"] = private_key
        creds["POLYMARKET_WALLET_ADDRESS"] = os.getenv("POLYMARKET_WALLET_ADDRESS") or creds.get("address")
        self.encrypt_and_save(creds, path)
        return creds

    def derive_ephemeral_clob_session(self, private_key: str) -> Dict[str, str]:
        """
        Derive a CLOB API session strictly in RAM.

        This intentionally avoids `encrypt_and_save()` and should be used by
        web-first ingestion/execution services that receive secrets from Vault
        at process start.
        """
        private_key = validate_private_key_or_raise(private_key, source="ephemeral session")
        creds = derive_clob_credentials(private_key)
        creds["CLOB_PRIVATE_KEY"] = private_key
        creds["POLYMARKET_WALLET_ADDRESS"] = (
            os.getenv("POLYMARKET_WALLET_ADDRESS") or creds.get("address", "")
        )
        return creds

    @staticmethod
    def destroy_secret_map(secrets: Dict[str, str]) -> None:
        """Best-effort RAM cleanup for mutable secret dictionaries."""
        for key in list(secrets.keys()):
            secrets[key] = ""
        secrets.clear()

    def get_or_generate_private_key(self, path: str = POLYMARKET_WALLET_PATH) -> str:
        if os.path.exists(path):
            try:
                data = self.load_and_decrypt(path)
                logger.info(f"Loaded private key from {path}")
                pk = validate_private_key_or_raise(data["CLOB_PRIVATE_KEY"], source=path)
                try:
                    self.add_wallet(pk)
                except Exception:
                    pass
                return pk
            except Exception as e:
                logger.warning(f"Failed to decrypt {path}: {e}")

        logger.info("Generating new institutional ETH/POL wallet...")
        new_acc = Account.create()
        pk = validate_private_key_or_raise(new_acc._private_key.hex(), source="generated wallet")
        self.encrypt_and_save({"CLOB_PRIVATE_KEY": pk, "address": new_acc.address}, path)
        logger.info(f"New wallet saved to {path}: {new_acc.address}")
        try:
            self.add_wallet(pk)
        except Exception:
            pass
        return pk

    def save_private_key(self, private_key: str, path: str = POLYMARKET_WALLET_PATH) -> str:
        """Manually save and encrypt a provided private key."""
        try:
            private_key = validate_private_key_or_raise(private_key, source=path)
            acc = Account.from_key(private_key)
            self.encrypt_and_save({"CLOB_PRIVATE_KEY": private_key, "address": acc.address}, path)
            logger.info(f"Wallet imported and saved to {path}: {acc.address}")
            # Also reset CLOB credentials to match new key
            self.get_or_generate_creds(private_key)
            try:
                self.add_wallet(private_key)
            except Exception:
                pass
            return acc.address
        except Exception as e:
            logger.error(f"Failed to import wallet: {e}")
            raise ValueError(f"Invalid private key: {e}")

    def list_wallets(self) -> list[Dict[str, str]]:
        if not os.path.exists(POLYMARKET_WALLET_PATH):
            return []

        try:
            data = self.load_and_decrypt(POLYMARKET_WALLET_PATH)
            pk = data.get("CLOB_PRIVATE_KEY") or data.get("private_key")
            addr = data.get("POLYMARKET_WALLET_ADDRESS") or data.get("address")
            if pk and addr:
                return [{"address": addr, "private_key": pk}]
        except Exception as e:
            logger.warning(f"Failed to load polymarket.wallet.enc: {e}")

    def add_wallet(self, private_key: str) -> str:
        private_key = validate_private_key_or_raise(private_key, source="polymarket wallet")
        acc = Account.from_key(private_key)
        creds = derive_clob_credentials(private_key)
        data = {
            "CLOB_PRIVATE_KEY": private_key,
            "address": acc.address,
            "clob_api_key": creds.get("CLOB_API_KEY", ""),
            "clob_api_secret": creds.get("CLOB_API_SECRET", ""),
            "clob_api_passphrase": creds.get("CLOB_API_PASSPHRASE", ""),
        }
        self.encrypt_and_save(data, POLYMARKET_WALLET_PATH)
        logger.info(f"Wallet saved to {POLYMARKET_WALLET_PATH}: {acc.address}")
        return acc.address

    def set_active_wallet(self, address: str) -> bool:
        wallets = self.list_wallets()
        target_wallet = None
        for w in wallets:
            if w.get("address").lower() == address.lower():
                target_wallet = w
                break

        if not target_wallet:
            return False

        # Save private key as active
        self.save_private_key(target_wallet["private_key"])
        return True

    def get_user_file_path(self, chat_id: int | str, wallet_type: str = "default") -> str:
        return POLYMARKET_WALLET_PATH

    def user_exists(self, chat_id: int | str, wallet_type: str = "default") -> bool:
        return os.path.exists(POLYMARKET_WALLET_PATH)

    def user_has_any_wallet(self, chat_id: int | str) -> bool:
        return self.user_exists(chat_id)

    def load_user(self, chat_id: int | str, wallet_type: str = "default") -> Dict[str, str]:
        return self.load_and_decrypt(POLYMARKET_WALLET_PATH)

    def save_user(self, chat_id: int | str, data: Dict[str, str], wallet_type: str = "default") -> None:
        self.encrypt_and_save(data, POLYMARKET_WALLET_PATH)

    def generate_user_wallet(self, chat_id: int | str, profile_name: str, wallet_type: str = "default") -> Dict[str, str]:
        logger.info(f"Generating new wallet for user {chat_id} (profile: {profile_name}, type: {wallet_type})")

        new_acc = Account.create()
        private_key = validate_private_key_or_raise(new_acc._private_key.hex(), source="user wallet generation")
        address = new_acc.address

        creds = derive_clob_credentials(private_key)

        user_data = {
            "private_key": private_key,
            "address": address,
            "proxy_wallet": "",
            "clob_api_key": creds.get("CLOB_API_KEY", ""),
            "clob_api_secret": creds.get("CLOB_API_SECRET", ""),
            "clob_api_passphrase": creds.get("CLOB_API_PASSPHRASE", ""),
            "profile_name": profile_name,
            "wallet_type": wallet_type,
        }

        self.save_user(chat_id, user_data, wallet_type)
        logger.info(f"User wallet created: {address} for chat_id {chat_id} ({wallet_type})")

        return user_data

    def import_user_wallet(self, chat_id: int | str, profile_name: str, private_key: str, wallet_type: str = "import") -> Dict[str, str]:
        logger.info(f"Importing wallet for user {chat_id} (profile: {profile_name}, type: {wallet_type})")

        acc = Account.from_key(private_key)
        address = acc.address

        creds = derive_clob_credentials(private_key)

        user_data = {
            "private_key": private_key,
            "address": address,
            "proxy_wallet": "",
            "clob_api_key": creds.get("CLOB_API_KEY", ""),
            "clob_api_secret": creds.get("CLOB_API_SECRET", ""),
            "clob_api_passphrase": creds.get("CLOB_API_PASSPHRASE", ""),
            "profile_name": profile_name,
            "wallet_type": wallet_type,
        }

        self.save_user(chat_id, user_data, wallet_type)
        logger.info(f"User wallet imported: {address} for chat_id {chat_id} ({wallet_type})")

        return user_data

    def set_user_proxy(self, chat_id: int | str, proxy_wallet: str, wallet_type: str = "default") -> Dict[str, str]:
        if not self.user_exists(chat_id, wallet_type):
            raise FileNotFoundError(f"User {chat_id} ({wallet_type}) not found")

        user_data = self.load_user(chat_id, wallet_type)
        user_data["proxy_wallet"] = proxy_wallet
        self.save_user(chat_id, user_data, wallet_type)
        logger.info(f"Proxy wallet set for {chat_id} ({wallet_type}): {proxy_wallet}")

        return user_data

    def delete_user(self, chat_id: int | str, wallet_type: str = "default") -> bool:
        try:
            if os.path.exists(POLYMARKET_WALLET_PATH):
                archive_dir = os.path.join(DEFAULT_DATA_DIR, "archives")
                os.makedirs(archive_dir, exist_ok=True)
                from datetime import datetime
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                archive_path = os.path.join(archive_dir, f"polymarket_wallet_{timestamp}.enc")
                import shutil
                shutil.move(POLYMARKET_WALLET_PATH, archive_path)
                logger.info(f"Wallet archived to {archive_path}")
                return True
        except Exception as exc:
            logger.error(f"Failed to archive wallet: {exc}")
            if os.path.exists(POLYMARKET_WALLET_PATH):
                os.remove(POLYMARKET_WALLET_PATH)
        return False

    def list_users(self) -> List[Dict[str, str]]:
        if not os.path.exists(POLYMARKET_WALLET_PATH):
            return []
        try:
            data = self.load_and_decrypt(POLYMARKET_WALLET_PATH)
            return [{
                "chat_id": "local",
                "address": data.get("address", ""),
                "proxy_wallet": data.get("proxy_wallet", ""),
            }]
        except Exception as e:
            logger.warning(f"Failed to load polymarket.wallet.enc: {e}")
            return []

    def get_user_credentials(self, chat_id: int | str) -> Dict[str, str]:
        wallet_type = self.get_active_wallet_type(chat_id)
        return self.get_user_credentials_for_type(chat_id, wallet_type)

    def get_user_credentials_for_type(self, chat_id: int | str, wallet_type: str = "default") -> Dict[str, str]:
        user_data = self.load_user(chat_id, wallet_type)

        required_keys = [
            "CLOB_PRIVATE_KEY",
            "CLOB_API_KEY",
            "CLOB_API_SECRET",
            "CLOB_API_PASSPHRASE",
        ]

        creds = {}
        for key in required_keys:
            if key == "CLOB_PRIVATE_KEY":
                creds[key] = user_data.get("private_key", "")
            elif key == "CLOB_API_KEY":
                creds[key] = user_data.get("clob_api_key", "")
            elif key == "CLOB_API_SECRET":
                creds[key] = user_data.get("clob_api_secret", "")
            elif key == "CLOB_API_PASSPHRASE":
                creds[key] = user_data.get("clob_api_passphrase", "")

        if user_data.get("proxy_wallet"):
            creds["POLYMARKET_WALLET_ADDRESS"] = user_data["proxy_wallet"]
        elif user_data.get("address"):
            creds["POLYMARKET_WALLET_ADDRESS"] = user_data["address"]

        return creds

    def _load_active_wallets(self) -> Dict[str, str]:
        return {"default": "default"}

    def _save_active_wallets(self, wallets: Dict[str, str]) -> None:
        pass

    def get_active_wallet_type(self, chat_id: int | str) -> str:
        return "default"

    def set_active_wallet_type(self, chat_id: int | str, wallet_type: str) -> bool:
        return True

    def _clear_active_wallet(self, chat_id: int | str) -> None:
        pass

    def get_user_info(self, chat_id: int | str) -> Dict[str, any]:
        info = {
            "chat_id": str(chat_id),
            "active_wallet_type": "default",
        }
        if os.path.exists(POLYMARKET_WALLET_PATH):
            try:
                data = self.load_and_decrypt(POLYMARKET_WALLET_PATH)
                info["default"] = {
                    "address": data.get("address", ""),
                    "proxy_wallet": data.get("proxy_wallet", ""),
                    "profile_name": data.get("profile_name", ""),
                }
            except Exception:
                pass
        return info

    def list_all_user_wallets(self, chat_id: int | str) -> List[Dict[str, str]]:
        if not os.path.exists(POLYMARKET_WALLET_PATH):
            return []
        try:
            data = self.load_and_decrypt(POLYMARKET_WALLET_PATH)
            return [{
                "type": "default",
                "address": data.get("address", ""),
                "proxy_wallet": data.get("proxy_wallet", ""),
                "profile_name": data.get("profile_name", ""),
                "is_active": True,
            }]
        except Exception as e:
            logger.warning(f"Failed to load polymarket.wallet.enc: {e}")
            return []
