from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import sys
import tempfile
from pathlib import Path

from pydantic import SecretStr

from utils.exceptions import QuantFatal

logger = logging.getLogger("Security")
PROD_CONFIRMATION_TEXT = "I UNDERSTAND REAL CAPITAL IS AT RISK"
PROD_SECOND_FACTOR_ENV = "LOBSTAR_PROD_CONFIRM_SECRET"


@contextlib.contextmanager
def telegram_single_instance_lock(lock_path: Path | None = None):
    lock_path = lock_path or Path(tempfile.gettempdir()) / "quant_agentic_telegram.lock"
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QuantFatal(
                "Another Telegram polling instance is already running. "
                "Stop the existing PM2/manual bot before starting this command."
            )
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def require_production_confirmation(execution_mode: str) -> None:
    if execution_mode.upper() != "PROD":
        return

    if os.getenv("FORCE_PROD", "").strip().lower() in {"1", "true", "yes", "on"}:
        logger.warning("PROD mode confirmed via FORCE_PROD env var. REAL CAPITAL IS AT RISK.")
        return

    expected_secret = os.getenv(PROD_SECOND_FACTOR_ENV, "").strip()
    if not expected_secret:
        raise QuantFatal(
            f"{PROD_SECOND_FACTOR_ENV} environment variable is required before PROD mode can start. "
            f"Set it to a secret value, or use FORCE_PROD=true to bypass."
        )

    if not sys.stdin.isatty():
        raise QuantFatal(
            "PROD mode requires an interactive terminal or FORCE_PROD=true. "
            "Set FORCE_PROD=true in your environment to bypass interactive confirmation."
        )

    typed_confirmation = input(f"Type '{PROD_CONFIRMATION_TEXT}' to start PROD mode: ").strip()
    if typed_confirmation != PROD_CONFIRMATION_TEXT:
        raise QuantFatal("PROD mode confirmation text did not match.")

    typed_secret = input("Enter PROD second-factor secret: ").strip()
    if typed_secret != expected_secret:
        raise QuantFatal("PROD second-factor secret did not match.")

    logger.warning("PROD mode confirmed interactively. REAL CAPITAL IS AT RISK.")


def _derive_public_wallet(private_key: SecretStr | str | None) -> str | None:
    if not private_key:
        return None
    try:
        from eth_account import Account

        key_str = private_key.get_secret_value() if isinstance(private_key, SecretStr) else private_key
        return Account.from_key(key_str).address
    except Exception:
        return None
