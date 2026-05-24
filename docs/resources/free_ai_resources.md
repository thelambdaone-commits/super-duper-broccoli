# Ressources IA Gratuites & Illimitées — Mai 2026

> Dernière mise à jour: 2026-05-23 (v5)
> Stack: OpenCode + GSD + 9Router + Ruflo + OpenViking + Puter MCP

---

## Providers API (Clés dans `.env`)

| Provider | Clé | Endpoint | Status |
|---|---|---|---|
| **OpenRouter** | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | ✅ Principal LLM Council |
| **Groq** | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | ✅ Parsing sémantique |
| **NVIDIA** | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` | ✅ Fallback 1 |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` | ✅ Fallback 2 |
| **Mistral** | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1` | ✅ Fallback 3 |
| **BazaarLink** | `BAZAARLINK_API_KEY` | `https://bazaarlink.ai/api/v1` | ✅ Fallback 4 (gratuit) |
| **UNLI** | `UNLI_API_KEY` | `https://api.unli.dev/v1` | ✅ Fallback 5 (gratuit) |
| **9Router** | `NINEROUTER_API_KEY` | `http://localhost:20128/v1` | ✅ Proxy local multi-providers |
| **Chimera Gateway** | `CHIMERA_GATEWAY_API_KEY` | `https://ai-robot.wiki/v1` | ✅ Fallback 6 (crédits gratuits) |
| **Chimera Ultra** | `CHIMERA_ULTRA_API_KEY` | — | ⏳ Réserve |
| **HuggingFace** | `HUGGINGFACE_API_KEY` | — | ✅ |
| **Gemini** | `GEMINI_API_KEY` | — | ✅ |

**Chaîne de fallback:** GROQ → NVIDIA → MISTRAL → DEEPSEEK → BAZAARLINK → UNLI → CHIMERA

---

## Routeurs / Proxys Multi-Providers

### 9Router (Installé & Configuré)
- **Port:** `http://localhost:20128`
- **Dashboard:** SSH tunnel `ssh -L 20128:localhost:20128 <server>`
- **Smart 3-Tier Routing:** Subscription → Cheap → FREE
- **Providers gratuits:** Kiro AI (Claude illimité), iFlow (8 modèles), Qwen (3 modèles), Gemini CLI
- **RTK Token Saver:** -20-40% tokens sur tool_results

### Chimera AI Gateway (Installé & Configuré)
- **Port:** `http://localhost:8000`
- **84 modèles découverts**, 22 providers
- **Circuit breaker:** 3-state (CLOSED → OPEN → HALF_OPEN)
- **Démarrage:** `python3 /tmp/start_chimera.py`

### Completions.me
- API gratuite illimitée, pas de carte de crédit
- Modèles: Claude Opus 4.6, GPT-5.2, Gemini 3.1 Pro

### Free-Way
- Gateway locale BYOK, OpenAI + Anthropic compatible
- Fallback routing, model discovery, health checks

### FreeIAForge
- 9 LLM gratuits + Ollama, Docker 1 commande
- Smart routing, circuit breaker, MCP Server

### Routerly
- Gateway LLM avec routage multi-policy (9 politiques)
- Cost tracking, dashboard React, CLI admin

---

## Plugins OpenCode Installés

| Plugin | Usage |
|---|---|
| `@ramtinj95/opencode-tokenscope` | Analyse tokens/coûts sessions |
| `openviking-opencode-plugin` | Mémoire long-terme & context retrieval |
| `puter-mcp` | 500+ modèles gratuits (Claude, GPT, Gemini) |
| `prompts-chat-mcp` | Bibliothèque de 50 prompts communauté |

---

## Skills GSD & OpenCode

### GSD Workflow
- **Installé:** `gsd-opencode` + `@opengsd/get-shit-done-redux`
- **Commandes:** `/gsd-new-project`, `/gsd-discuss-phase`, `/gsd-plan-phase`, `/gsd-execute-phase`
- **Config:** `config/gsd_operating_system.json`, `.agents/gsd_execution_skill.md`

### MiroThinker
- **Modèles:** 8B, 30B, 72B, 235B — open-source HuggingFace
- **Context:** 256K tokens, 600 tool calls
- **Benchmarks:** SOTA sur BrowseComp, GAIA, HLE

### Ruflo
- Orchestration multi-agent, 100+ agents spécialisés
- 33 plugins: swarm, autopilot, RAG memory, federation

---

## Utilitaires Web Scraping

| Outil | Description | Stars |
|---|---|---|
| **Firecrawl** | Search, scrape, clean pour AI agents. 96% coverage | 123k★ |
| **Scrapling** | Anti-bot bypass, spiders pause/resume, MCP | 53.7k★ |
| **Webclaw** | Extraction web local-first en Rust, MCP server | 1.2k★ |

---

## Utilitaires Token Saving

- **9Router RTK:** Compression tool_results, -20-40% tokens
- **Puter:** 500+ modèles gratuits via proxy

---

## Références

- **LLM Council (Karpathy):** https://github.com/karpathy/llm-council
- **GSD:** https://github.com/rokicool/gsd-opencode
- **Understand-Anything:** https://github.com/Lum1104/Understand-Anything
- **Ruflo:** https://github.com/ruvnet/ruflo
- **prompts.chat:** https://github.com/f/kapor-eight
