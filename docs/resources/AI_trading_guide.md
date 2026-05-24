# 🤖 Guide d'Intégration Quant pour Agent IA : Placer des Trades Facilement

Ce guide a été conçu pour permettre à n'importe quel Agent IA ou script autonome de comprendre instantanément l'architecture du projet et de placer des ordres de trading réels ou simulés de manière extrêmement simple, performante et sans erreur.

---

## 🏛️ 1. L'Architecture en 1 Seule Ligne (Le Singleton)

Toutes les ressources de production (moteur de trading CLOB, base de données SQLite, filtres de régime HMM, notifications Telegram) sont centralisées et managées par un conteneur unique de services : le **`ServiceContainer`**.

Pour y accéder en Python, l'IA n'a besoin que de cette ligne :
```python
from core.container import ServiceContainer

# Récupération de l'instance unique
container = ServiceContainer.get_instance()
```

---

## ⚡ 2. Placer un Ordre Réel sur le CLOB (Polymarket V2 Mainnet)

Le moteur **`FreqAIEngine`** prend en charge de manière totalement autonome la gestion des clés privées, la détection du portefeuille de dépôt (deposit wallet flow via EIP-1271 signatures), la validation du prix par rapport au pas de cotation (*tick size*) et la vérification du notionnel minimum réglementaire de **$5.00 USDC**.

### 📝 Le Code Minimal pour l'IA :
```python
import asyncio
from core.container import ServiceContainer

async def passer_ordre_reel():
    container = ServiceContainer.get_instance()
    freqai = container.freqai
    
    # ⚠️ Activer le mode PROD dans le Ledger pour autoriser le live
    container.ledger.set_execution_mode("PROD")
    
    # Spécifications de l'ordre
    token_id = "84358917457786118111350061347880730021105314335676049736086740763081010842066" # YES Abstract FDV
    price = 0.77 # Prix unitaire en USDC
    size = 7     # Nombre d'actions (sera arrondi à l'entier inférieur automatiquement)
    
    print("Posting order to Polymarket CLOB...")
    result = await freqai.clob_execute(
        ticker=token_id,
        side="BUY", # BUY (ou YES) / SELL (ou NO)
        price=price,
        size=size
    )
    
    print(f"Receipt: {result}")
    
    # 🔒 Toujours restaurer le mode PAPER pour la sécurité du système
    container.ledger.set_execution_mode("PAPER")

if __name__ == "__main__":
    asyncio.run(passer_ordre_reel())
```

---

## 📝 3. Placer un Ordre Simulé (Local Paper Trading)

Si l'Agent IA souhaite tester une stratégie sans engager de capital réel, ou bypasser la limite réglementaire de $5.00 USDC imposée par Polymarket, elle peut enregistrer directement un ordre simulé (Paper Trade) ultra-réaliste dans le Ledger.

### 📝 Le Code Minimal pour l'IA :
```python
from core.container import ServiceContainer
from utils.regime_utils import get_regime_label

container = ServiceContainer.get_instance()
ledger = container.ledger
hmm = container.hmm

# 1. Déterminer le régime de marché HMM (ex: BTC)
regime = get_regime_label(hmm, "BTC")

# 2. Enregistrer l'ordre papier dans la base SQLite
order = ledger.record_paper_order(
    ticker="BTC-5MIN-UP",
    side="YES",                  # YES / NO
    price=0.50,                  # Prix virtuel d'entrée
    size=1.0,                    # Taille virtuelle (ex: 1 action)
    requested_qty=1.0,
    filled_qty=1.0,
    execution_price=0.50,
    notional_usd=0.50,           # Notionnel de $0.50 (autorisé en Paper!)
    confidence=0.85,             # Score de confiance de l'IA (0.00 à 1.00)
    regime_label=regime,
    signal_source="mon_agent_ia",
    tenant_wallet="0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E"
)

print(f"Paper Order Saved: ID={order.get('position_id')}")
```

---

## 📊 4. Lire les Balances et les Carnets d'Ordres Réels

L'IA peut également inspecter l'environnement Polygon mainnet avant de prendre une décision.

### Lire le solde réel (EOA et Proxy/Deposit Wallet) :
```python
from core.container import ServiceContainer
import asyncio

async def voir_les_soldes():
    container = ServiceContainer.get_instance()
    
    # 1. Utiliser le wallet manager pour obtenir un rapport de solde complet
    from core.wallet_manager import WalletManager
    wm = WalletManager()
    
    # Charger l'adresse active
    address = "0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E"
    proxy = "0xa005088ba69014581d6460db325627600887590b"
    
    balances = await wm.recuperer_soldes(address, proxy_address=proxy)
    print(f"Solde total capital : {balances['usdc_proxy']:.2f} pUSD")
    print(f"Solde direct EOA    : {balances['usdc_direct']:.2f} USDC")
    print(f"Solde Gas MATIC/POL : {balances['eth_balance']:.4f} POL")

asyncio.run(voir_les_soldes())
```

### Lire le carnet d'ordres (Order Book) :
```python
from core.container import ServiceContainer

container = ServiceContainer.get_instance()
freqai = container.freqai

# Récupérer le carnet d'ordres live (Bids / Asks)
token_id = "84358917457786118111350061347880730021105314335676049736086740763081010842066"
book = freqai.client.get_order_book(token_id)

print("Meilleurs Bids (Acheteurs) :", book.bids[:3])
print("Meilleurs Asks (Vendeurs) :", book.asks[:3])
```

---

## 🛡️ 5. Les Bonnes Pratiques pour l'IA (Garde-Fous de Production)

Pour préserver la sécurité du capital et éviter les comportements erratiques en cours d'autonomie :
1. **Validation Notionnelle** : N'appelez jamais l'API CLOB directement. Passez **toujours** par `freqai.clob_execute()` car elle contient les verrous d'arrondi de taille et de notionnel minimum requis pour éviter les rejets réseaux.
2. **Restauration Automatique du Mode** : Si vous passez temporairement le Ledger en mode `PROD` pour exécuter un trade réel, utilisez **toujours** un bloc `try...finally` pour forcer le retour en mode `PAPER` juste après, afin d'éviter qu'un signal erroné ultérieur ne déclenche un trade réel non contrôlé.
3. **DuckDB Mutex** : Le `ServiceContainer` gère automatiquement les verrous DuckDB. Si l'IA instancie des sous-processus en parallèle, elle doit s'assurer de ne pas verrouiller le fichier `feature_store.duckdb` simultanément (notre architecture contient déjà un mécanisme de repli automatique en mémoire `:memory:` pour éviter les crashs).
