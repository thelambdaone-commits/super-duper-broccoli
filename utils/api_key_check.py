"""
utils/api_key_check.py
======================
Module de vérification des clés API au runtime.
Résout l'erreur: ModuleNotFoundError: No module named 'utils.api_key_check'
"""

import logging
import os
from pathlib import Path
from typing import Any

from utils.secret_validation import normalize_private_key

ENCRYPTED_WALLET_PATH = Path("data/polymarket.wallet.enc")

logger = logging.getLogger("ApiKeyCheck")

# Mapping: nom de la clé → criticité (True = bloquante)
REQUIRED_KEYS: dict[str, bool] = {
    "GROQ_API_KEY": True,
    "TELEGRAM_BOT_TOKEN": True,
    "CLOB_PRIVATE_KEY": True,
    "POLYGON_RPC_URL": True,
    "POLYGON_RPC_URL_HTTP": False,
    "POLYMARKET_CLOB_URL": False,
    "OPENROUTER_API_KEY": False,
    "COINGECKO_API_KEY": False,
    "NVIDIA_API_KEY": False,
    "MISTRAL_API_KEY": False,
    "DEEPSEEK_API_KEY": False,
    "HUGGINGFACE_API_KEY": False,
    "NEWS_FEEDS": False,
    "CHAT_ID": False,
}


class ApiKeyNotifier:
    """Vérifie la présence des clés API critiques et génère des alertes Telegram."""

    @staticmethod
    def _load_secure_runtime_secrets() -> dict[str, str]:
        try:
            from utils.vault_handler import VaultHandler

            return VaultHandler().fetch_quantum_secrets()
        except Exception as exc:
            logger.debug("Unable to load secure runtime secrets: %s", exc)
            return {}

    def check_all_keys(self, runtime_secrets: dict[str, Any] | None = None) -> dict:
        """
        Vérifie toutes les clés API configurées.

        Args:
            runtime_secrets: Dictionnaire de secrets chargés depuis Vault ou .env.

        Returns:
            dict avec les clés 'missing', 'critical', 'ok', 'total'
        """
        secrets = runtime_secrets or self._load_secure_runtime_secrets()
        missing = []
        critical_missing = []
        ok = []

        for key, is_critical in REQUIRED_KEYS.items():
            # Vérifie d'abord dans les secrets runtime, puis dans les variables d'environnement
            value = secrets.get(key) or os.getenv(key, "")
            if key == "POLYMARKET_CLOB_URL" and not value:
                value = os.getenv(key, "https://clob.polymarket.com")
            if key == "CLOB_PRIVATE_KEY":
                value = normalize_private_key(value) or ""
                if not value and ENCRYPTED_WALLET_PATH.exists():
                    ok.append(key)
                    continue
            if not value or value.strip() == "":
                missing.append(key)
                if is_critical:
                    critical_missing.append(key)
                    logger.warning(f"🔴 [CREDENTIALS] CRITICAL key missing: {key}")
                else:
                    logger.info(f"🟡 [CREDENTIALS] Optional key missing: {key}")
            else:
                ok.append(key)

        result = {
            "missing": missing,
            "critical": critical_missing,
            "ok": ok,
            "total": len(REQUIRED_KEYS),
        }

        logger.info(
            f"🔑 API Key Check: {len(missing)} missing, {len(critical_missing)} critical"
        )
        return result

    def format_telegram_alert(self, check_result: dict) -> str:
        """Formate une alerte Telegram pour les clés manquantes."""
        missing = check_result.get("missing", [])
        critical = check_result.get("critical", [])

        if not missing:
            return ""

        lines = ["⚠️ *CREDENTIALS ALERT*\n"]
        if critical:
            lines.append("🔴 *CRITICAL keys missing (bot may fail):*")
            for key in critical:
                lines.append(f"  • `{key}`")
        non_critical = [k for k in missing if k not in critical]
        if non_critical:
            lines.append("\n🟡 *Optional keys missing:*")
            for key in non_critical:
                lines.append(f"  • `{key}`")

        lines.append("\n_Update your `.env` or Vault configuration._")
        return "\n".join(lines)


# Singleton pattern — évite de recréer l'objet à chaque appel
_notifier_instance: ApiKeyNotifier | None = None


def get_api_key_notifier() -> ApiKeyNotifier:
    """Retourne le singleton ApiKeyNotifier."""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = ApiKeyNotifier()
    return _notifier_instance
