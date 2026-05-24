# Référence Écosystème Prediction Markets

Document généré à partir des awesome lists et sources externes.
Utilisé comme catalogue de référence pour les intégrations futures.

---

## 1. Awesome Polymarket Tools (harish-garg)
**Repo**: https://github.com/harish-garg/Awesome-Polymarket-Tools
**Focus**: Polymarket uniquement — 11 catégories (99 stars)

### Outils remarquables pour intégration future

| Catégorie | Outil | Utilité |
|---|---|---|
| SDK Python | `py-clob-client` | Déjà intégré |
| SDK JS/TS | `@polymarket/clob-client` | Référence architecture |
| IA Agents | `Polymarket/agents` | Framework agent officiel — pattern à suivre |
| Market Making | `poly-market-maker` | Algo market making officiel |
| Data APIs | `FinFeedAPI`, Gamma, CLOB | Sources de données |
| Browser Extensions | PolyPulse (AI news) | Inspiration features dashboard |
| Telegram Bots | Polycule, Polysight | Pattern bots Telegram existant |
| Plugin Patterns | `@goat-sdk/plugin-polymarket` | Intégration plugin Goat |

---

## 2. Awesome Prediction Market Tools (aarora4)
**Repo**: https://github.com/aarora4/Awesome-Prediction-Market-Tools
**Focus**: Multi-plateforme — 22 catégories, 423 stars

### AI Agents (~30 outils)
- **Alphascope**, **Octagon AI**, **Polytrader**, **BillyBets**, **PolyOracle**
- **Polyseer**, **Simmer**, **TurbineFi**, **oracle3**, **PolyBro**, **PolyRadar**, **Astron**
- **Pattern**: LLM-as-reasoning-layer + exécution CLOB

### Data Infrastructure
- **Marketlens**: SDK Python pour données tick-level
- **PolyRouter**: API unifiée Polymarket/Kalshi/Limitless
- **TREMOR** / **Probalytics**: Accès ClickHouse SQL aux données prediction market
- **PMXT**: Données order book historiques

### DeFi Composability
- **Gondor**: Lend/borrow contre positions prediction market
- **HyperOdd**: Trading avec levier 20x sur prediction markets
- **Robin**: Positions prediction market yield-bearing

### Arbitrage
- **ArbBets**, **Eventarb**, **Polytrage**, **PolyScalping**
- **Prediction Hunt**: Cross-plateforme

---

## 3. Top 10 LaikaLabs (2026)
**Source**: https://laikalabs.ai/prediction-markets/polymarket-github-repos

| Rang | Repo | Focus |
|---|---|---|
| 1 | `alteregoeth-ai/weatherbot` | Weather trading bot débutant |
| 2 | `suislanchez/polymarket-kalshi-weather-bot` | Cross-plateforme météo |
| 5 | `Polymarket/agents` | Agent IA officiel |
| 6 | `caiovicentino/polymarket-mcp-server` | Intégration Claude/MCP |
| 8 | `pydantic/pydantic-ai` | Framework agent IA |

### Insights clés
- **Weather trading domine** : 4/10 top repos sont weather-focused. ROI 22-35% annuels, 58-68% win rate
- **Agents IA >30% des wallets** Polymarket en 2026
- **3 APIs essentielles** : Gamma (metadata), CLOB (execution), Data (historique)
- **Polystrat (Olas)** : 4,200+ trades en 1 mois, 376% return sur un trade

---

## 4. Plan d'intégration futur

### Priorité haute
- `Polymarket/agents` → Framework agent officiel, pattern à copier
- `poly-market-maker` → Amélioration market making existant
- `Marketlens` → SDK Python données tick-level pour feature store

### Priorité moyenne
- `polymarket-mcp-server` → Alternative MCP pour Claude Desktop
- `TREMOR` / `Probalytics` → Analytics ClickHouse
- `PolyRouter` → API unifiée cross-plateforme

### Priorité basse
- Extensions navigateur et bots Telegram additionnels
- Outils DeFi (Gondor, HyperOdd, Robin)
