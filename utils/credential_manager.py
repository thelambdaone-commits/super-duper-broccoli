import os
import json
import logging
from typing import Dict, Optional
from cryptography.fernet import Fernet
from eth_account import Account
from utils.derive_clob_creds import derive_clob_credentials

logger = logging.getLogger("CredentialManager")

DEFAULT_DATA_DIR = os.getenv("DATA_PATH", "data")
DEFAULT_ENC_PATH = os.path.join(DEFAULT_DATA_DIR, "defaut.enc")
WALLET_ENC_PATH = os.path.join(DEFAULT_DATA_DIR, "clob_wallet.enc")

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
        if not os.path.exists(path):
            raise FileNotFoundError(f"Encrypted credentials not found at {path}")
        
        with open(path, "rb") as f:
            encrypted = f.read()
        
        decrypted = self.fernet.decrypt(encrypted)
        return json.loads(decrypted.decode())

    def get_or_generate_creds(self, private_key: str, path: str = DEFAULT_ENC_PATH) -> Dict[str, str]:
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
        self.encrypt_and_save(creds, path)
        return creds

    def get_or_generate_private_key(self, path: str = WALLET_ENC_PATH) -> str:
        if os.path.exists(path):
            try:
                data = self.load_and_decrypt(path)
                logger.info(f"Loaded private key from {path}")
                return data["CLOB_PRIVATE_KEY"]
            except Exception as e:
                logger.warning(f"Failed to decrypt {path}: {e}")
        
        logger.info("Generating new institutional ETH/POL wallet...")
        new_acc = Account.create()
        pk = new_acc._private_key.hex()
        self.encrypt_and_save({"CLOB_PRIVATE_KEY": pk, "address": new_acc.address}, path)
        logger.info(f"New wallet saved to {path}: {new_acc.address}")
        return pk

    def save_private_key(self, private_key: str, path: str = WALLET_ENC_PATH) -> str:
        """Manually save and encrypt a provided private key."""
        try:
            acc = Account.from_key(private_key)
            self.encrypt_and_save({"CLOB_PRIVATE_KEY": private_key, "address": acc.address}, path)
            logger.info(f"Wallet imported and saved to {path}: {acc.address}")
            # Also reset CLOB credentials to match new key
            self.get_or_generate_creds(private_key)
            return acc.address
        except Exception as e:
            logger.error(f"Failed to import wallet: {e}")
            raise ValueError(f"Invalid private key: {e}")
