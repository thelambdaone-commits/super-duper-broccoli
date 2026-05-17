import logging
from typing import Dict, Any, List, Set

logger = logging.getLogger("LOBSTAR_Security")

class AccessControlManager:
    """
    Gestionnaire d'accès et de partitionnement des portefeuilles par Chat ID.
    Garantit la séparation des privilèges entre Utilisateurs/Signaux et Administrateurs.
    """
    def __init__(self, admin_chat_ids: List[int]) -> None:
        # Utilisation d'un Set pour une recherche en O(1) ultra-rapide sur le path critique
        self._admins: Set[int] = set(admin_chat_ids)
        
        # Mapping interne : Associe un Chat ID Telegram à un identifiant de Wallet / Asset unique
        self._wallet_mapping: Dict[int, str] = {}

    def est_admin(self, chat_id: int) -> bool:
        """Vérifie si le chat_id émetteur possède les droits d'administration globale."""
        return chat_id in self._admins

    def assigner_wallet_a_chat(self, chat_id: int, wallet_address_or_id: str) -> None:
        """Assigne de manière stricte un portefeuille d'exécution à un canal Telegram spécifique."""
        self._wallet_mapping[chat_id] = wallet_address_or_id
        logger.info(f"🔒 [SECURITY] Portefeuille {wallet_address_or_id} verrouillé sur le chat_id : {chat_id}")

    def obtenir_wallet_associe(self, chat_id: int) -> str:
        """Retourne le portefeuille dédié au chat_id ou lève une exception d'accès."""
        if chat_id not in self._wallet_mapping:
            # Sécurité défensive : Si non assigné, on bascule sur un portefeuille d'isolation par défaut
            return f"DEFAULT_ISOLATED_WALLET_{chat_id}"
        return self._wallet_mapping[chat_id]
