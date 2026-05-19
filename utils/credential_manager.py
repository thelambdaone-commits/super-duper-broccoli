import os
import json
import logging
from typing import Dict, Optional, List
from cryptography.fernet import Fernet
from eth_account import Account
from utils.derive_clob_creds import derive_clob_credentials
from utils.secret_validation import validate_private_key_or_raise

logger = logging.getLogger("CredentialManager")

DEFAULT_DATA_DIR = os.getenv("DATA_PATH", "data")
DEFAULT_ENC_PATH = os.path.join(DEFAULT_DATA_DIR, "default.enc")
WALLET_ENC_PATH = os.path.join(DEFAULT_DATA_DIR, "clob_wallet.enc")
CONFIGURED_WALLETS_PATH = os.path.join(DEFAULT_DATA_DIR, "configured_wallets.enc")
ACTIVE_WALLET_PATH = os.path.join(DEFAULT_DATA_DIR, "active_wallet.enc")

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

    def encrypt_and_save(self, creds: Dict[str, str], path: str = DEFAULT_ENC_PATH) -> None:
        data = json.dumps(creds).encode()
        encrypted = self.fernet.encrypt(data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(encrypted)
        logger.info(f"Credentials encrypted and saved to {path}")

    def load_and_decrypt(self, path: str = DEFAULT_ENC_PATH) -> Dict[str, str]:
        resolved_path = path
        if path == os.path.join(DEFAULT_DATA_DIR, "default.enc") and not os.path.exists(path):
            legacy_path = os.path.join(DEFAULT_DATA_DIR, "defaut.enc")
            if os.path.exists(legacy_path):
                logger.info("Migrating legacy defaut.enc to default.enc")
                try:
                    os.rename(legacy_path, path)
                    logger.info("Successfully renamed defaut.enc to default.enc")
                except Exception as e:
                    logger.warning(f"Could not rename legacy file: {e}")
                    resolved_path = legacy_path

        if not os.path.exists(resolved_path):
            raise FileNotFoundError(f"Encrypted credentials not found at {resolved_path}")
        
        with open(resolved_path, "rb") as f:
            encrypted = f.read()
        
        decrypted = self.fernet.decrypt(encrypted)
        return json.loads(decrypted.decode())

    def get_or_generate_creds(self, private_key: str, path: str = DEFAULT_ENC_PATH) -> Dict[str, str]:
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

    def get_or_generate_private_key(self, path: str = WALLET_ENC_PATH) -> str:
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

    def save_private_key(self, private_key: str, path: str = WALLET_ENC_PATH) -> str:
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
        wallets_path = os.path.join(DEFAULT_DATA_DIR, "configured_wallets.enc")
        if not os.path.exists(wallets_path):
            wallet_path = WALLET_ENC_PATH
            if os.path.exists(wallet_path):
                try:
                    data = self.load_and_decrypt(wallet_path)
                    pk = data.get("CLOB_PRIVATE_KEY")
                    addr = data.get("address")
                    if pk and addr:
                        wallets = [{"address": addr, "private_key": pk}]
                        self.encrypt_and_save(wallets, wallets_path)
                        return wallets
                except Exception as e:
                    logger.warning(f"Failed to load clob_wallet.enc: {e}")
            return []
        
        try:
            with open(wallets_path, "rb") as f:
                encrypted = f.read()
            decrypted = self.fernet.decrypt(encrypted)
            return json.loads(decrypted.decode())
        except Exception as e:
            logger.error(f"Failed to load configured_wallets.enc: {e}")
            return []

    def add_wallet(self, private_key: str) -> str:
        private_key = validate_private_key_or_raise(private_key, source="configured wallet")
        acc = Account.from_key(private_key)
        wallets = self.list_wallets()
        for w in wallets:
            if w.get("address").lower() == acc.address.lower():
                return acc.address
        
        wallets.append({"address": acc.address, "private_key": private_key})
        wallets_path = os.path.join(DEFAULT_DATA_DIR, "configured_wallets.enc")
        data = json.dumps(wallets).encode()
        encrypted = self.fernet.encrypt(data)
        with open(wallets_path, "wb") as f:
            f.write(encrypted)
        logger.info(f"Added wallet {acc.address} to configured_wallets")
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
        return os.path.join(DEFAULT_DATA_DIR, f"{wallet_type}{chat_id}.enc")

    def user_exists(self, chat_id: int | str, wallet_type: str = "default") -> bool:
        path = self.get_user_file_path(chat_id, wallet_type)
        if os.path.exists(path):
            return True
        # Backward compatibility fallback
        if wallet_type == "default":
            legacy_path = self.get_user_file_path(chat_id, "defaut")
            if os.path.exists(legacy_path):
                return True
        return False

    def user_has_any_wallet(self, chat_id: int | str) -> bool:
        return self.user_exists(chat_id, "default") or self.user_exists(chat_id, "import")

    def load_user(self, chat_id: int | str, wallet_type: str = "default") -> Dict[str, str]:
        path = self.get_user_file_path(chat_id, wallet_type)
        if not os.path.exists(path) and wallet_type == "default":
            legacy_path = self.get_user_file_path(chat_id, "defaut")
            if os.path.exists(legacy_path):
                logger.info(f"Migrating legacy wallet 'defaut' to 'default' for chat_id {chat_id}")
                data = self.load_and_decrypt(legacy_path)
                self.save_user(chat_id, data, "default")
                try:
                    os.remove(legacy_path)
                    logger.info(f"Successfully deleted legacy wallet file: {legacy_path}")
                except Exception as e:
                    logger.warning(f"Could not delete legacy file {legacy_path}: {e}")
                return data
        return self.load_and_decrypt(path)

    def save_user(self, chat_id: int | str, data: Dict[str, str], wallet_type: str = "default") -> None:
        path = self.get_user_file_path(chat_id, wallet_type)
        self.encrypt_and_save(data, path)

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
        path = self.get_user_file_path(chat_id, wallet_type)
        if not os.path.exists(path):
            # Try to see if legacy path exists to delete it
            if wallet_type == "default":
                legacy_path = self.get_user_file_path(chat_id, "defaut")
                if os.path.exists(legacy_path):
                    path = legacy_path
                else:
                    return False
            else:
                return False
        
        try:
            archive_dir = os.path.join(DEFAULT_DATA_DIR, "archives")
            os.makedirs(archive_dir, exist_ok=True)
            from datetime import datetime
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = os.path.basename(path)
            archive_filename = f"{os.path.splitext(filename)[0]}_{timestamp}.enc"
            archive_path = os.path.join(archive_dir, archive_filename)
            import shutil
            shutil.move(path, archive_path)
            logger.info(f"User wallet archived and deleted: chat_id {chat_id} ({wallet_type}) -> {archive_path}")
        except Exception as exc:
            logger.error(f"Failed to archive wallet for user {chat_id} ({wallet_type}): {exc}")
            if os.path.exists(path):
                os.remove(path)
        
        if self.get_active_wallet_type(chat_id) == wallet_type:
            self._clear_active_wallet(chat_id)
        
        return True

    def list_users(self) -> List[Dict[str, str]]:
        users = []
        if not os.path.exists(DEFAULT_DATA_DIR):
            return users
        
        seen_chat_ids = set()
        for prefix in ["default", "defaut"]:
            for filename in os.listdir(DEFAULT_DATA_DIR):
                if filename.startswith(prefix) and filename.endswith(".enc") and filename != f"{prefix}.enc":
                    try:
                        chat_id = filename.replace(prefix, "").replace(".enc", "")
                        if chat_id in seen_chat_ids:
                            continue
                        seen_chat_ids.add(chat_id)
                        user_data = self.load_and_decrypt(os.path.join(DEFAULT_DATA_DIR, filename))
                        users.append({
                            "chat_id": chat_id,
                            "address": user_data.get("address", ""),
                            "proxy_wallet": user_data.get("proxy_wallet", ""),
                            "profile_name": user_data.get("profile_name", ""),
                        })
                    except Exception as e:
                        logger.warning(f"Failed to load user {filename}: {e}")
        
        return users

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
        if not os.path.exists(ACTIVE_WALLET_PATH):
            return {}
        try:
            data = self.load_and_decrypt(ACTIVE_WALLET_PATH)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_active_wallets(self, wallets: Dict[str, str]) -> None:
        self.encrypt_and_save(wallets, ACTIVE_WALLET_PATH)

    def get_active_wallet_type(self, chat_id: int | str) -> str:
        chat_id_str = str(chat_id)
        wallets = self._load_active_wallets()
        wallet_type = wallets.get(chat_id_str, "default")
        
        if wallet_type == "defaut":
            wallet_type = "default"
            wallets[chat_id_str] = "default"
            self._save_active_wallets(wallets)

        if not self.user_exists(chat_id, wallet_type):
            if self.user_exists(chat_id, "default"):
                return "default"
            elif self.user_exists(chat_id, "import"):
                return "import"
            return "default"
        return wallet_type

    def set_active_wallet_type(self, chat_id: int | str, wallet_type: str) -> bool:
        chat_id_str = str(chat_id)
        
        if not self.user_exists(chat_id, wallet_type):
            logger.warning(f"Cannot set active wallet: {wallet_type} not found for chat_id {chat_id}")
            return False
        
        wallets = self._load_active_wallets()
        wallets[chat_id_str] = wallet_type
        self._save_active_wallets(wallets)
        logger.info(f"Active wallet set to {wallet_type} for chat_id {chat_id}")
        return True

    def _clear_active_wallet(self, chat_id: int | str) -> None:
        chat_id_str = str(chat_id)
        wallets = self._load_active_wallets()
        if chat_id_str in wallets:
            del wallets[chat_id_str]
            self._save_active_wallets(wallets)

    def get_user_info(self, chat_id: int | str) -> Dict[str, any]:
        wallet_type = self.get_active_wallet_type(chat_id)
        
        info = {
            "chat_id": str(chat_id),
            "active_wallet_type": wallet_type,
        }
        
        if self.user_exists(chat_id, "default"):
            try:
                data = self.load_user(chat_id, "default")
                info["default"] = {
                    "address": data.get("address", ""),
                    "proxy_wallet": data.get("proxy_wallet", ""),
                    "profile_name": data.get("profile_name", ""),
                }
            except Exception:
                pass
        
        if self.user_exists(chat_id, "import"):
            try:
                data = self.load_user(chat_id, "import")
                info["import"] = {
                    "address": data.get("address", ""),
                    "proxy_wallet": data.get("proxy_wallet", ""),
                    "profile_name": data.get("profile_name", ""),
                }
            except Exception:
                pass
        
        return info

    def list_all_user_wallets(self, chat_id: int | str) -> List[Dict[str, str]]:
        wallets = []
        
        for wt in ["default", "import"]:
            if self.user_exists(chat_id, wt):
                try:
                    data = self.load_user(chat_id, wt)
                    wallets.append({
                        "type": wt,
                        "address": data.get("address", ""),
                        "proxy_wallet": data.get("proxy_wallet", ""),
                        "profile_name": data.get("profile_name", ""),
                        "is_active": self.get_active_wallet_type(chat_id) == wt,
                    })
                except Exception as e:
                    logger.warning(f"Failed to load {wt} wallet for {chat_id}: {e}")
        
        return wallets
