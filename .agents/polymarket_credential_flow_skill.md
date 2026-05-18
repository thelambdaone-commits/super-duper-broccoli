# 🔐 Polymarket Credential & Execution Flow

*How the bot authenticates, checks balances, and places trades on Polymarket CLOB.*

---

## 1. Credential Architecture

### Principle — Zero plaintext secrets in `.env`

| What | Where | Format |
|---|---|---|
| CLOB Private Key (EOA) | `data/import{chat_id}.enc` | Fernet-chiffré |
| CLOB API Key / Secret / Passphrase | `data/default.enc` | Fernet-chiffré, auto-dérivé |
| Proxy Wallet Address | Dans le fichier wallet `.enc`, champ `proxy_wallet` | Chiffré |
| Config / RPC / API keys | `.env` | En clair (non sensibles) |

### Load chain (`VaultHandler.fetch_quantum_secrets()`)

```
1. CHAT_ID → cherche le wallet actif dans data/*.enc
   → user_creds = { private_key, address, clob_api_key, proxy_wallet, ... }

2. Si pas de wallet actif → fallback sur data/default.enc
   → contient CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE, CLOB_PRIVATE_KEY

3. Si toujours pas → os.getenv("CLOB_PRIVATE_KEY") (dernier recours)
```

### Auto-dérivation CLOB

Quand `CLOB_API_KEY` / `CLOB_API_SECRET` / `CLOB_API_PASSPHRASE` ne sont pas dans `.env` :
1. `CredentialManager.get_or_generate_creds(private_key)` est appelé
2. Vérifie si `data/default.enc` existe → le déchiffre et retourne
3. Sinon → `derive_clob_credentials(private_key)` via `py-clob-client`
4. Sauvegarde le résultat chiffré dans `data/default.enc`

---

## 2. Wallet Architecture (EOA + Proxy)

Polymarket utilise un **proxy wallet (Gnosis Safe)** pour détenir le collatéral :

```
User EOA (0xdc5585FC...)
├── Native USDC   : 10.00   ← fonds disponibles pour dépôt
├── MATIC         : 19.97   ← gas fees
│
└── Proxy Wallet (0xa005088ba...)
    └── pUSDC     : 6.99    ← collatéral Polymarket V2
```

- **EOA** signe les transactions et paie le gas
- **Proxy** détient le pUSDC utilisé comme marge pour les trades
- Les ordres CLOB sont placés via l'API (pas de tx on-chain), mais le collatéral vient du proxy

### Résolution du proxy

```
GET https://gamma-api.polymarket.com/public-profile?address={eoa}
→ { "proxyWallet": "0xa005088ba..." }
```

Le proxy est auto-résolu à l'import d'un wallet (`/wallet import` ou `/wallet add`) et stocké dans le fichier `.enc`.

---

## 3. Balance Checking

### EOA (commandes `/wallet balance <addr>` ou `/wallet`)

| Token | Contrat Polygon | Checké par |
|---|---|---|
| NATIVE USDC | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` | `PolymarketWalletManager.recuperer_soldes_on_chain()` |
| USDC.e (bridged) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | `utils/wallet_manager.WalletManager` |
| MATIC | NATIF | `eth_getBalance` |
| POL | `0x455e53CBB86018Ac2B8092FDD3C0b784F1693313` | `WalletManager.get_token_balance()` |

### Proxy Wallet (uniquement via `/wallet` cockpit)

| Token | Checké par |
|---|---|
| pUSDC | `get_erc20_balance(pusd_contract, proxy_address)` |
| Native USDC | `get_erc20_balance(usdc_native_contract, proxy_address)` |
| USDC.e | `get_erc20_balance(usdc_e_contract, proxy_address)` |

---

## 4. Order Placement Pipeline

### Flow complet : signal → exécution

```
Telegram Signal / API
       │
       ▼
SignalParser / LobstarAgent  ← parse le signal (déterministe ou LLM)
       │
       ▼
PortfolioRiskEngine          ← Kelly sizing, HMM regime, concentration, drawdown
       │
       ▼
SignalExecutor._execute_guarded()
       │
       ├── Mode REPLAY  → log only (feature store)
       ├── Mode PAPER   → PassiveExecutor simulé (paper_engine.py)
       ├── Mode SHADOW  → PassiveExecutor réel, 1% taille
       └── Mode PROD    → PassiveExecutor réel, taille complète
                │
                ▼
         PassiveExecutor.execute()
                │
                ├── Maker first : FreqAIEngine.post_order()  → post_only
                └── Taker fallback : FreqAIEngine.clob_execute()  → market
```

### FreqAIEngine (connexion CLOB)

```python
self.client = ClobClient(
    host="https://clob.polymarket.com",
    key=private_key,       # CLOB_PRIVATE_KEY (signe les ordres)
    chain_id=137,          # Polygon mainnet
    signature_type=2,
)
self.client.set_api_creds(ApiCreds(
    api_key=api_key,
    api_secret=api_secret,
    api_passphrase=api_passphrase,
))
```

### Modes d'exécution

| Mode | Capital réel | Ordres réels | Use case |
|---|---|---|---|
| REPLAY | Aucun | Non | Backtest |
| PAPER | Virtuel | Non | Validation |
| SHADOW | 1% du réel | Oui (maker-first) | Dry-run |
| PROD | 100% | Oui (maker-first) | Production |

---

## 5. Env vars still in `.env` (non sensibles)

| Variable | Rôle |
|---|---|
| `SECRET_SOURCE=env` | Dit à VaultHandler d'utiliser les fichiers `.enc` |
| `VAULT_ADDR=false` | Désactive HashiCorp Vault |
| `CHAT_ID` | ID du chat Telegram (sélectionne le wallet actif) |
| `POLYGON_RPC_URL` | RPC Polygon pour les lectures on-chain |
| `ENCRYPTION_KEY` | Clé Fernet pour déchiffrer les `.enc` |

---

## 6. Behavioral Constraints

- **NE JAMAIS** écrire `CLOB_PRIVATE_KEY` dans `.env` ou un fichier en clair
- **NE JAMAIS** logger les valeurs des secrets (le `VaultHandler` et le logging filter les expurgent)
- **TOUJOURS** passer par `VaultHandler.fetch_quantum_secrets()` pour obtenir les credentials
- **TOUJOURS** vérifier le mode d'exécution avant d'envoyer un ordre réel
- **Le proxy wallet** est requis pour le trading Polymarket V2 — le vérifier via Gamma API
- **MATIC** est requis sur l'EOA pour le gas — minimum ~0.1 MATIC par ordre