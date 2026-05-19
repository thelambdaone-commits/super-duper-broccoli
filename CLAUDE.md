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
