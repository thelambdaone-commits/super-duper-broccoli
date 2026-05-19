# Rapport d'Audit : WebSockets & Optimisation de la Latence

## 1. Diagnostic des Flux de Données

| Flux de Données | Méthode Actuelle | Latence Estimée | Impact | Recommandation |
| :--- | :--- | :--- | :--- | :--- |
| **Orderbook (Top 25)** | WebSocket (CLOB) | ~50-200ms | Faible | Maintenir |
| **Orderbook (Autres)** | HTTP Polling | 60s (SL/TP loop) | **CRITIQUE** | Basculer sur abonnement WS dynamique |
| **Copy Trading** | HTTP Polling | 10s | **ÉLEVÉ** | Utiliser `PolymarketMonitor` (WS On-chain) |
| **Exécution (User)** | HTTP Polling | N/A (Manquant) | **MOYEN** | Intégrer WebSocket `user` pour les fills |
| **Signaux On-chain** | WebSocket (Public) | Variable (Public RPC) | **MOYEN** | Utiliser un RPC Privé (Alchemy/Infura) |
| **News Telegram** | HTTP Polling | ~1-5s | Faible | Utiliser Telethon/Pyrogram (Streaming) |

## 2. Défaillances Critiques Identifiées

### 2.1 Latence du Stop-Loss / Take-Profit (60s)
Le script `main_agentic_clob.py` surveille les positions toutes les 60 secondes via des requêtes HTTP. Sur un marché volatil comme Polymarket, le prix peut varier de 10% à 50% en une minute.
*   **Risque :** Exécution avec un slippage massif ou échec de fermeture de position.

### 2.2 Limitation du CLOBListener
Le `CLOBListener` n'écoute que 25 marchés au démarrage. Si l'IA détecte une opportunité sur un 26ème marché, le bot ne dispose pas de flux temps réel pour ce marché spécifique.

### 2.3 Absence de Flux "User" (Fills)
Le bot ne sait pas instantanément quand son ordre est exécuté. Il doit attendre le prochain cycle de vérification du ledger, ce qui retarde les stratégies de hedging ou de rééquilibrage.

## 3. Recommandations d'Intégration

### 3.1 Intégration du WebSocket User (Polymarket CLOB)
Pour recevoir les événements `order_filled` instantanément.

```python
# Squelette suggéré pour scrapers/user_clob_listener.py
import asyncio
from py_clob_client_v2 import ClobClient

async def listen_user_events(client: ClobClient):
    # L'API User nécessite une signature d'authentification (déjà gérée par ClobClient)
    async for event in client.get_user_events_stream():
        if event["type"] == "order_filled":
            logger.info(f"✅ Ordre exécuté: {event['order_id']} | Taille: {event['size']}")
            # Update ledger instantanément
```

### 3.2 Optimisation du RPC Polygon
Remplacer le RPC public par un flux WS Alchemy gratuit pour réduire la latence des signaux on-chain de ~500ms.
*   **URL recommandée :** `wss://polygon-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`

### 3.3 Dynamic WebSocket Subscription
Modifier `CLOBListener` pour permettre l'ajout dynamique de `token_ids` sans redémarrer la connexion, permettant de suivre n'importe quel marché dès qu'un signal est détecté.

## 4. Statut de l'Implémentation (Phase 1 & 2)
✅ **TERMINE** :
1.  **Réduction de l'intervalle SLTP** : Passé de 60s à 10s dans le loop de secours.
2.  **Fast-Path SL/TP (WebSocket)** : Implémenté directement dans le callback du `CLOBListener`. Le bot réagit désormais en **sub-seconde** aux mouvements de prix pour fermer les positions.
3.  **UserEvents Listener & Ledger Sync** : Nouveau module `scrapers/user_clob_listener.py` intégré. Le Ledger est mis à jour instantanément lors des fills via `exchange_order_id`.
4.  **Migration CopyTrading** : Fast Path via `PolymarketMonitor` (On-chain WS).
5.  **Abonnement Dynamique & Persistance** : Le bot surveille automatiquement toutes les positions ouvertes dès le démarrage via WebSocket.

## 5. Prochaines Étapes Recommandées
1.  **RPC Privé** : Remplacer `wss://polygon-rpc.com/ws` par une clé Alchemy/Infura pour éviter le throttling du mempool.
2.  **MTProto (Telethon)** : Pour les signaux Telegram, passer du Bot API (Polling) à un Userbot (Streaming) pour gagner ~1-2 secondes sur l'ingestion.
