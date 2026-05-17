"""
API Key Notifier - Vérification et notification des clés API manquantes
=========================================================================
Vérifie les clés API requises et envoie des alertes Telegram quand des clés
sont manquantes. Aide au diagnostic rapide des problèmes de configuration.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("APIKeyNotifier")


@dataclass
class APIKeyRequirement:
    """Définition d'une exigence de clé API."""
    key_name: str
    description: str
    is_critical: bool
    env_fallback: Optional[str] = None


class APIKeyNotifier:
    """
    Gestionnaire de vérification des clés API.
    Vérifie les clés manquantes et formatte les alertes.
    """

    REQUIRED_KEYS: List[APIKeyRequirement] = [
        APIKeyRequirement(
            key_name="TELEGRAM_BOT_TOKEN",
            description="Bot Telegram pour les commandes",
            is_critical=True,
        ),
        APIKeyRequirement(
            key_name="CHAT_ID",
            description="ID du chat Telegram pour les alertes",
            is_critical=True,
        ),
        APIKeyRequirement(
            key_name="POLYMARKET_API_KEY",
            description="API Polymarket",
            is_critical=True,
        ),
        APIKeyRequirement(
            key_name="POLYMARKET_API_SECRET",
            description="API Secret Polymarket",
            is_critical=True,
        ),
        APIKeyRequirement(
            key_name="POLYMARKET_SECRET",
            description="Wallet Secret Polymarket",
            is_critical=True,
        ),
        APIKeyRequirement(
            key_name="POLYGON_RPC_URL",
            description="RPC Polygon pour données on-chain",
            is_critical=False,
        ),
        APIKeyRequirement(
            key_name="ETH_RPC_URL",
            description="RPC Ethereum",
            is_critical=False,
        ),
        APIKeyRequirement(
            key_name="GROQ_API_KEY",
            description="API Groq pour agent LOBSTAR AI",
            is_critical=False,
        ),
        APIKeyRequirement(
            key_name="CLOB_PRIVATE_KEY",
            description="Clé privée wallet trading",
            is_critical=True,
        ),
    ]

    def __init__(self, env_file: str = ".env"):
        self._checked = False
        self._missing_keys: List[str] = []
        self._critical_missing: List[str] = []
        self._env_file = env_file
        self._env_vars: Dict[str, str] = {}
        self._load_env_file()

    def _load_env_file(self) -> None:
        """Charge les variables du fichier .env directement."""
        env_path = Path(self._env_file)
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        self._env_vars[key] = value

    def _get_from_env_file(self, key: str) -> Optional[str]:
        """Récupère une valeur directement du fichier .env."""
        return self._env_vars.get(key)

    def check_all_keys(self, runtime_secrets: Optional[Dict[str, str]] = None) -> Dict[str, any]:
        """
        Vérifie les clés API:
        1. D'abord dans .env
        2. Si absent de .env, vérifier si disponible via Vault (runtime_secrets)
        3. Si absent partout = manquant
        """
        self._missing_keys = []
        self._critical_missing = []
        self._loaded_from_vault = []
        self._in_env_file = []

        for req in self.REQUIRED_KEYS:
            key_value = self._get_from_env_file(req.key_name)

            if key_value and key_value.lower() != "false":
                self._in_env_file.append(req.key_name)
            elif runtime_secrets and runtime_secrets.get(req.key_name):
                self._loaded_from_vault.append(req.key_name)
                logger.info(f"🔐 {req.key_name} loaded from Vault (runtime)")
            else:
                self._missing_keys.append(req.key_name)
                if req.is_critical:
                    self._critical_missing.append(req.key_name)
                logger.warning(f"⚠️ API Key missing: {req.key_name} - {req.description}")

        self._checked = True

        return {
            "missing": self._missing_keys,
            "critical": self._critical_missing,
            "in_env_file": self._in_env_file,
            "loaded_from_vault": self._loaded_from_vault,
            "total_required": len(self.REQUIRED_KEYS),
            "total_missing": len(self._missing_keys),
            "has_critical": len(self._critical_missing) > 0,
        }

    def is_ready(self) -> bool:
        """Retourne True si toutes les clés critiques sont présentes."""
        if not self._checked:
            self.check_all_keys()
        return len(self._critical_missing) == 0

    def format_telegram_alert(self, check_result: Optional[Dict] = None) -> str:
        """
        Formatte une alerte Telegram pour les clés manquantes.
        """
        if check_result is None:
            check_result = self.check_all_keys()

        if not check_result["missing"]:
            return "✅ *CONFIGURATION OK*\n\nToutes les clés API requises sont présentes."

        missing = check_result["missing"]
        critical = check_result["critical"]

        lines = [
            "⚠️ *CLÉS API MANQUANTES*",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Les clés suivantes sont absentes du fichier `.env`:\n",
        ]

        for req in self.REQUIRED_KEYS:
            if req.key_name in missing:
                status = "🔴" if req.is_critical else "🟡"
                lines.append(f"{status} `{req.key_name}`")
                lines.append(f"   └─ {req.description}")

        if check_result.get("loaded_from_vault"):
            lines.append("\n🔐 *Chargées depuis Vault:*")
            for key in check_result["loaded_from_vault"]:
                lines.append(f"   ✅ `{key}`")

        if check_result.get("in_env_file"):
            lines.append("\n📄 *Dans .env:*")
            for key in check_result["in_env_file"]:
                lines.append(f"   ✅ `{key}`")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        if critical:
            lines.append(f"🔴 *{len(critical)} clés CRITIQUES manquantes*")
            lines.append("Le fonctionnement du bot peut être compromis.")

        lines.append(f"\n🟡 *{len([k for k in missing if k not in critical])} clés optionnelles manquantes*")
        lines.append("Fonctionnement dégradé possible.")

        lines.append("\nℹ️ Pour ajouter une clé, modifiez le fichier `.env` puis redémarrez le bot.")

        return "\n".join(lines)

    def format_console_report(self, check_result: Optional[Dict] = None) -> str:
        """Formatte un rapport pour la console."""
        if check_result is None:
            check_result = self.check_all_keys()

        if not check_result["missing"]:
            return "✅ All required API keys present"

        lines = [
            f"\n⚠️ API Keys Missing: {check_result['total_missing']}/{check_result['total_required']}",
        ]

        if check_result["critical"]:
            lines.append(f"  🔴 Critical: {', '.join(check_result['critical'])}")

        optional = [k for k in check_result["missing"] if k not in check_result["critical"]]
        if optional:
            lines.append(f"  🟡 Optional: {', '.join(optional)}")

        return "\n".join(lines)

    def get_missing_description(self, key: str) -> Optional[str]:
        """Retourne la description d'une clé manquante."""
        for req in self.REQUIRED_KEYS:
            if req.key_name == key:
                return req.description
        return None


_api_notifier_instance: Optional[APIKeyNotifier] = None


def get_api_key_notifier() -> APIKeyNotifier:
    """Factory pour récupérer l'instance singleton."""
    global _api_notifier_instance
    if _api_notifier_instance is None:
        _api_notifier_instance = APIKeyNotifier()
    return _api_notifier_instance


async def notify_missing_keys(listener, chat_id: Optional[int] = None) -> Dict[str, any]:
    """
    Fonction utilitaire pour notifier les clés manquantes via Telegram.
    Appeler cette fonction au démarrage du bot.
    """
    notifier = get_api_key_notifier()
    result = notifier.check_all_keys()

    if result["missing"]:
        logger.warning(notifier.format_console_report(result))

        if listener and chat_id:
            alert = notifier.format_telegram_alert(result)
            await listener.send_message(alert, chat_id=chat_id, parse_mode="Markdown")

    return result


def check_keys_on_startup() -> Dict[str, any]:
    """
    Version synchrone pour vérification rapide au démarrage.
    Retourne le résultat sans envoi de message.
    """
    notifier = get_api_key_notifier()
    return notifier.check_all_keys()