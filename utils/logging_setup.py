import logging
import os
import re
import sys
from datetime import datetime, timezone

class TelegramTokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value):
            if isinstance(value, str):
                value = re.sub(r"/bot[^/\s]+", "/bot<redacted>", value)
                value = re.sub(r"(?i)\b(?:0x)?[0-9a-f]{64}\b", "<redacted_hex_key>", value)
                value = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]{16,}\b", "<redacted_secret>", value)
                value = re.sub(r"(?i)\bgsk_[A-Za-z0-9_-]{16,}\b", "<redacted_secret>", value)
            return value

        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


class PrivateKeyRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value):
            if isinstance(value, str):
                return re.sub(r"(?i)\b(?:0x)?[0-9a-f]{64}\b", "<redacted_hex_key>", value)
            return value

        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True

def setup_logging(name: str = "QuantAgenticCore") -> logging.Logger:
    _log_handler = logging.StreamHandler(sys.stdout)
    _log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _log_handler.setFormatter(_log_formatter)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[_log_handler],
        force=True,
    )

    _file_log = os.getenv("LOG_FILE", "")
    if _file_log:
        _fh = logging.FileHandler(_file_log)
        _fh.setFormatter(_log_formatter)
        logging.getLogger().addHandler(_fh)

    # Redaction filters for security
    redaction_filter = TelegramTokenRedactionFilter()
    private_key_filter = PrivateKeyRedactionFilter()
    logging.getLogger("httpx").addFilter(redaction_filter)
    logging.getLogger("httpcore").addFilter(redaction_filter)
    logging.getLogger().addFilter(private_key_filter)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger = logging.getLogger(name)
    logger.info(f"Logging initialized at {datetime.now(timezone.utc).isoformat()}")
    return logger
