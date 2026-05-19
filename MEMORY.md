# 🧠 Project Memory (Quant Agentic Trading Core V2)

> **Status:** PROD-READY (Triple-Couche Architecture)
> **Goal:** High-Frequency Trading Bot sur Polymarket & Solana CLOB.

## 🏗️ Core Architecture
1. **Couche Calcul (Math/Risk) :** `PortfolioRiskEngine` dans `core/portfolio_risk_engine.py`. Gère le Kelly Criterion, le Drawdown Circuit Breaker (-10%), et le sizing.
2. **Couche IA Cognitive :** `LobstarAgent` (`mcp_agents/lobstar_agent.py`). Utilise Groq/Llama3 pour parser les signaux Telegram. Équipé d'un Fallback Regex Déterministe en cas d'Inference Hang.
3. **Couche ML :** HMM Regime Filter (`user_data/strategies/hmm_filter.py`). Inférence locale numpy (pas d'API).
4. **Exécution :** `PassiveExecutor` (`execution/passive_executor.py`). Protégé par un API Latency Watchdog (Freeze 60s si lag > 2000ms). Ordres Maker-first.
5. **Base de Données / Ledger :** `Ledger` (SQLite `ledger.db` géré dans `ledger/ledger_db.py`). Gère les positions `PAPER` et `PROD`.

## 🔒 Sécurité & Accès
- HashiCorp Vault ou `.env` pour stocker `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, etc.
- Scan `bandit` propre. Exclusion stricte via `.gitignore` (IDE, Agents).

## 🛠️ Outils Recommandés (Best Practices)
- **Context7** : Si vous devez ajouter une librairie externe (ex: Web3, nouvelles API), utilisez Context7 (via MCP ou CLI) pour obtenir la doc fraîche et éviter les hallucinations.
- **Portée** : cette règle s'applique aussi à Gemini, Copilot, OpenCode et Codex. C'est une consigne documentaire, pas une dépendance runtime.
- **Distributed Shared Memory** : `RufloSwarmSupervisor` supporte désormais **Redis** pour la mémoire partagée et le bus d'événements (via `REDIS_URL`). Utile pour les déploiements distribués multi-instances.
- **Modifications :** Toujours faire un audit avant un gros refactoring, et mettre ce fichier à jour avec les décisions d'architecture.

---
*Ce fichier doit être consulté au début de chaque nouvelle session de dev pour restaurer le contexte !*
