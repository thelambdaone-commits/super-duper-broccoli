import logging
import re
import os
from pathlib import Path
from cryptography.fernet import Fernet

logger = logging.getLogger("SecurityUtils")

class SecretScrubbingFilter(logging.Filter):
    """Redacts common secret patterns from logs."""
    _patterns = [
        re.compile(r"bot\d+:[^/\s\"]+"), # Telegram
        re.compile(r"0x[a-fA-F0-9]{64}"), # EVM Private Key
        re.compile(r"sk-[a-zA-Z0-9]{48}"), # OpenAI
        re.compile(r"CG-[a-zA-Z0-9]{24}"), # CoinGecko
        re.compile(r"(?i)api[-_]?key[=:][^/\s\"]{10,}"), # Generic API Key
        re.compile(r"(?i)password[=:][^/\s\"]{4,}"), # Generic Password
        re.compile(r"(?i)passphrase[=:][^/\s\"]{4,}"), # Generic Passphrase
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in self._patterns:
            redacted = pattern.sub("<REDACTED>", redacted)

        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True

def setup_secure_logging():
    """Applies scrubbing filters to all root handlers."""
    scrubber = SecretScrubbingFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(scrubber)

    # Also apply to common noisy libraries
    for name in ["httpx", "httpcore", "telegram", "telegram.ext", "hvac"]:
        logging.getLogger(name).addFilter(scrubber)

def get_encryption_key() -> bytes:
    """Gets or creates a local encryption key."""
    secrets_dir = Path(os.getenv("SECRETS_PATH", Path(__file__).resolve().parents[2] / "secrets"))
    key_path = secrets_dir / "master.key"
    if key_path.exists():
        with key_path.open("rb") as f:
            key = f.read().strip()
        try:
            Fernet(key)
            return key
        except Exception:
            logger.warning("Invalid Fernet key at %s. Rotating to a valid generated key.", key_path)

    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    with key_path.open("wb") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return key

def encrypt_data(data: str) -> str:
    f = Fernet(get_encryption_key())
    return f.encrypt(data.encode()).decode()

def decrypt_data(token: str) -> str:
    f = Fernet(get_encryption_key())
    return f.decrypt(token.encode()).decode()

def secure_delete(path: str):
    """Overwrites a file with random data before deleting it."""
    if not os.path.exists(path): return
    try:
        size = os.path.getsize(path)
        with open(path, "ba+", buffering=0) as f:
            f.write(os.urandom(size))
        os.remove(path)
        logger.info(f"Securely deleted: {path}")
    except Exception as e:
        logger.error(f"Failed to securely delete {path}: {e}")
        # Fallback to normal delete
        if os.path.exists(path): os.remove(path)
