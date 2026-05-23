# 🧠 Project Memory (Quant Agentic Trading Core V2)

> **Status:** PROD-READY + EXTENDED (Phase 1-4 Integrations)
> **Goal:** High-Frequency Trading Bot sur Polymarket & Solana CLOB.

## 🏗️ Core Architecture (V2 Original)
1. **Couche Calcul (Math/Risk) :** `PortfolioRiskEngine` dans `core/portfolio_risk_engine.py`. Gère le Kelly Criterion, le Drawdown Circuit Breaker (-10%), et le sizing.
2. **Couche IA Cognitive :** `LobstarAgent` (`mcp_agents/lobstar_agent.py`). Utilise Groq/Llama3 pour parser les signaux Telegram. Équipé d'un Fallback Regex Déterministe en cas d'Inference Hang.
3. **Couche ML :** HMM Regime Filter (`user_data/strategies/hmm_filter.py`). Inférence locale numpy (pas d'API).
4. **Exécution :** `PassiveExecutor` (`execution/passive_executor.py`). Protégé par un API Latency Watchdog (Freeze 60s si lag > 2000ms). Ordres Maker-first.
5. **Base de Données / Ledger :** `Ledger` (SQLite `ledger.db` géré dans `ledger/ledger_db.py`). Gère les positions `PAPER` et `PROD`.

## 🧩 Extensions (Phase 1-4 Integrations)

### Phase 1a — Pydantic AI Agent Framework
- **Dépôt** : `https://github.com/pydantic/pydantic-ai` (dépendance pip)
- **Fichier clé** : `core/pydantic_agent_factory.py`
- **Rôle** : Framework agent typé avec `Agent`, `RunContext` (DI), `Tool`, sorties structurées (`TradeSignal`, `RiskAssessment`, `MarketAnalysis`), multi-modèles, `pydantic-graph` pour workflows state machine.
- **Utilisation** : Agent d'analyse (`create_analysis_agent`), Agent de risque (`create_risk_agent`), Agent de signal (`create_signal_agent`). Bridge via MCP tool `pydantic_agent_analyze`.

### Phase 1b — Polymarket LP Tool
- **Dépôt** : `https://github.com/lihanyu81/polymarket_lp_tool` (sous-module → `agents/polymarket_lp_tool/`)
- **Fichier clé** : `agent_skills/polymarket_market_making_skill/adapter_lp_tool.py`
- **Rôle** : Repricing passif d'ordres limit basé sur le delta de récompense de liquidité CLOB. Implémente `SimplePricePolicy` (coarse/fine tick) et `CustomPricingRulesStore` (règles JSON persistées).
- **Outils MCP** : `clodds_lp_repricing`, `clodds_lp_set_custom_rule`

### Phase 2a — Polymarket On-chain Data
- **Dépôt** : `https://github.com/SII-WANGZJ/Polymarket_data` (sous-module → `utils/polymarket_data/`)
- **Rôle** : Fetching/décodage d'événements `OrderFilled` via Polygon RPC, métadonnées Gamma API, dataset 107GB+ (1.1B records). Requiert Python ≥3.12.
- **Outil MCP** : `polymarket_data_fetch_onchain`

### Phase 2b — Prediction Market Backtesting (NautilusTrader)
- **Dépôt** : `https://github.com/evan-kolberg/prediction-market-backtesting` (sous-module → `engine/backtest/nautilus_backtest/`)
- **Rôle** : Backtesting professionnel avec replay d'order book L2 historique (PMXT/Telonex), optimisation de paramètres (Optuna), charting riche.
- **Tech stack** : Python 3.12+, Rust (extension native), NautilusTrader 1.226.0

### Phase 3a — CloddsBot Sidecar
- **Dépôt** : `https://github.com/alsk1992/CloddsBot` (Docker sidecar)
- **Rôle** : Terminal IA trading avec 119 skills, 21 canaux messaging, 10 plateformes prediction market.
- **Connexion** : MCP server (port 18789), pont via `mcp_agents/mcp_server.py`

### Phase 3b — Polybot Reference
- **Dépôt** : `https://github.com/ent0n29/polybot` (sous-module → `agents/polybot/`)
- **Rôle** : Infrastructure microservices Java + scripts Python research (replication scoring, backtesting, calibration)

### Phase 4 — Awesome Lists & Ecosystem Reference
- **Fichier** : `docs/ecosystem_reference.md`
- **Sources** : `harish-garg/Awesome-Polymarket-Tools`, `aarora4/Awesome-Prediction-Market-Tools`, LaikaLabs

## 🔒 Sécurité & Accès
- HashiCorp Vault ou `.env` pour stocker `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, etc.
- Scan `bandit` propre. Exclusion stricte via `.gitignore` (IDE, Agents).
- Les sidecars externes (CloddsBot, polybot) ont leurs propres credentials isolés dans Docker Compose.

## 🛠️ Outils Recommandés (Best Practices)
- **Context7** : Si vous devez ajouter une librairie externe (ex: Web3, nouvelles API), utilisez Context7 (via MCP ou CLI) pour obtenir la doc fraîche et éviter les hallucinations.
- **Portée** : cette règle s'applique aussi à Gemini, Copilot, OpenCode et Codex. C'est une consigne documentaire, pas une dépendance runtime.
- **Distributed Shared Memory** : `RufloSwarmSupervisor` supporte désormais **Redis** pour la mémoire partagée et le bus d'événements (via `REDIS_URL`). Utile pour les déploiements distribués multi-instances.
- **Nouveaux sous-modules** : `git submodule update --init --recursive` après chaque clone.
- **Intégrations Docker** : `docker compose -f docker-compose.integrations.yml up -d clodds polybot-executor` pour lancer les sidecars.
- **Environnements isolés** : Polymarket_data et Nautilus backtesting nécessitent Python ≥3.12 — utiliser `make setup-integration-envs`.
- **Modifications :** Toujours faire un audit avant un gros refactoring, et mettre ce fichier à jour avec les décisions d'architecture.

## 🔍 Audit Findings (2026-05-23)

### ✅ Composants Vérifiés
| Composant | Statut | Notes |
|---|---|---|
| `core/freqai_engine.py` | **Bug Fix** | `_normalize_and_validate()` → `normalize_and_validate()` dans `create_order()` et `post_order()` (AttributeError à chaque ordre). **Corrigé.** |
| `execution/passive_executor.py` | ✅ OK | Latency watchdog, freeze, strict_maker_only, USDC allowance, order queue. Rien à signaler. |
| `core/orchestrator.py` | ✅ OK | Architecture complète : signal→enqueue→cognitive→risk→HITL→router. Bien structuré. |
| `bootstrap/service_factory.py` | ✅ OK | Minimal, propre. |
| `utils/vault_handler.py` | ✅ OK | Résolution multi-source (env, encrypted wallet, Vault, session wallets). |
| `telegram_scraper/` | ✅ OK | Bot Telegram complet avec routing, wallet management, copy trading, 30+ commandes. |
| `.env` | ⚠️ **Sec** | Secrets en clair (API keys LLM, Telegram token, RPC URLs with keys). Migrer vers Vault recommandé. |

### ⚡ Critical Bug Fix
- **Fichier**: `core/freqai_engine.py:118,160`
- **Symptôme**: `AttributeError: 'FreqAIEngine' object has no attribute '_normalize_and_validate'`
- **Cause**: Les appels `self._normalize_and_validate()` ne correspondent pas à la définition `def normalize_and_validate()` (sans underscore préfixe).
- **Remédiation**: Remplacé `self._normalize_and_validate` par `self.normalize_and_validate` aux deux endroits.

### Blocked (inchangé)
- Polymarket_data et Nautilus backtesting nécessitent Python ≥3.12 (projet en 3.11).
- `.venv` shebangs cassés (chemin `quant-agentic-trading-core-v2`).

---
*Ce fichier doit être consulté au début de chaque nouvelle session de dev pour restaurer le contexte !*
