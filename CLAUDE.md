# Règles de Développement & Maintien du Contexte
Ce fichier agit comme la source de vérité pour tout agent IA (Claude, Cursor, Antigravity) opérant sur ce projet.

## 1. Maintien du Contexte (Anti-Amnésie)
Pour ne jamais perdre le fil du projet entre différentes sessions :
- Lisez TOUJOURS le fichier `MEMORY.md` ou `ARCHITECTURE.md` (s'ils existent) avant de modifier des composants critiques.
- Maintenez à jour le `CONFIGURATION_AUDIT.md` ou `DEEP_AUDIT_REPORT.md` avec chaque décision majeure.
- Documentez les bugs récurrents et leurs solutions dans `docs/troubleshooting.md`.
- Lors d'une modification de code, faites un commit atomique par fichier avec un message descriptif complet.

## 2. Context7 (Documentation à jour)
Ne jamais halluciner d'APIs. Si vous avez un doute sur une syntaxe (Polymarket, Groq, Numpy, FastAPI), utilisez la plateforme **Context7** (`https://github.com/upstash/context7`).

**Règle absolue :** 
Always use Context7 when needing library/API documentation, code generation, setup, or configuration steps without the user having to explicitly ask.

- Utilisez le CLI `ctx7` ou le serveur MCP Context7 pour injecter la documentation officielle dans votre contexte avant de coder.
- Exemple d'utilisation dans vos prompts internes : `Use context7 to find documentation for py-clob-client`.

## 2.1 Portée multi-assistants
Cette consigne Context7 s'applique aussi aux assistants Gemini, Copilot, OpenCode et Codex. Il s'agit d'une règle de documentation seulement, pas d'une dépendance runtime.

## 3. Workflow & Subagents
(Basé sur les standards *claude-code-best-practice*)
- Découpez les tâches complexes en sous-tâches (moins de 50% du contexte).
- Si une exécution d'agent s'allonge, faites un `/compact` (ou l'équivalent) pour rafraîchir la mémoire.
- Utilisez le mode "plan" ou générez un `implementation_plan.md` avant de coder des modifications architecturales (comme les Circuit Breakers).

## 4. Modules Externes Intégrés (Phase 1-4)
### Sous-modules Git
| Path | Repo | Usage |
|---|---|---|
| `agents/polymarket_lp_tool/` | `lihanyu81/polymarket_lp_tool` | Passive LP order repricing |
| `utils/polymarket_data/` | `SII-WANGZJ/Polymarket_data` | On-chain data fetching |
| `engine/backtest/nautilus_backtest/` | `evan-kolberg/prediction-market-backtesting` | Nautilus backtesting |
| `agents/polybot/` | `ent0n29/polybot` | Java trading infra (reference) |

### Dépendances pip
- `pydantic-ai` — Agent framework with structured outputs
- `pydantic-graph` — Graph-based state machines

### Docker Sidecars (docker-compose.integrations.yml)
- `clodds` — CloddsBot AI terminal (Node.js, MCP port 18789)
- `polybot-executor` — Polybot executor service (Java, port 8080)
- `redpanda` — Kafka-compatible event streaming

### Initialisation
```bash
git submodule update --init --recursive
pip install -r requirements.txt
docker compose -f docker-compose.integrations.yml up -d
```

### Python Version Notes
- **Projet principal** : Python ≥3.11 (config actuelle)
- **Polymarket_data** : Requiert Python ≥3.12 — utiliser `.venv_polymarket_data` séparé
- **Nautilus backtesting** : Requiert Python ≥3.12 + Rust toolchain — utiliser `.venv_nautilus_backtest` séparé
