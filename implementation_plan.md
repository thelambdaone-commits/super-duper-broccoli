# Plan d'Implémentation : Sécurités Avancées (Watchdog, Fallback IA, Drawdown)

Ce plan décrit l'implémentation des trois systèmes de sécurité critiques identifiés dans le rapport d'audit afin d'assurer l'absolue fiabilité du système en production.

## User Review Required

> [!WARNING]
> Ces modifications touchent au cœur de l'exécution et de l'orchestration. Un "Fallback" regex pour l'IA implique que des signaux complexes pourraient être ignorés si l'IA crashe. Le seuil du circuit breaker est fixé arbitrairement à -10% de Drawdown global. Confirme ces règles.

## Open Questions

> [!IMPORTANT]
> - Le **Fallback Déterministe** doit-il utiliser une expression régulière (Regex) basique (ex: `BUY SOL`) ou doit-il complètement ignorer les trades entrants jusqu'au retour de l'IA ? J'opte pour un regex déterministe simple.
> - Le **Watchdog de Latence** (2000ms) doit-il bloquer le bot pendant X minutes, ou doit-il simplement refuser les trades jusqu'au prochain tick sain ? Je choisis de geler pour 60 secondes.

## Proposed Changes

---

### Moteur d'Exécution & Latence

Modifications du système de passage d'ordres pour se protéger contre le "Lag" de la blockchain Polygon.

#### [MODIFY] [passive_executor.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/execution/passive_executor.py)
- **Objectif :** Implémenter le `API Latency Watchdog`.
- **Détails :**
  - Ajout d'une variable `self._consecutive_high_latency_ticks = 0` et `self._latency_freeze_until = 0.0`.
  - Lors des appels à l'API Polymarket (`post_order`, `get_order_status`), mesurer le temps écoulé avec `time.time()`.
  - Si le temps de réponse dépasse `2.0` secondes, incrémenter le compteur. À 3 dépassements consécutifs, activer le freeze (`_latency_freeze_until = time.time() + 60.0`).
  - Toute nouvelle demande de trade durant ce Freeze sera immédiatement rejetée avec le statut `REJECTED_API_LAG`.

---

### Couche IA Cognitive (Agent LOBSTAR)

Modifications de l'Agent Groq/OpenRouter pour éviter le blocage système en cas de panne externe.

#### [MODIFY] [lobstar_agent.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/mcp_agents/lobstar_agent.py)
- **Objectif :** Implémenter le `Fallback IA Déterministe`.
- **Détails :**
  - Ajouter un compteur `self._consecutive_failures = 0` et un état `self._fallback_active = False`.
  - Si l'appel Groq (protégé par `tenacity`) remonte une exception finale, on incrémente le compteur. À 3 échecs, `_fallback_active` passe à `True`.
  - Si `_fallback_active` est True, on ignore l'appel HTTP et on applique un parser Regex strict (ex: `re.search(r"(BUY|SELL)\s+([A-Z]+)", texte)`) pour extraire le signal.
  - On ajoutera un timer pour retenter l'API Groq toutes les 5 minutes et sortir du Fallback si elle répond.

---

### Moteur de Risque & Ledger

Modifications pour protéger le capital d'un Flash Crash.

#### [MODIFY] [ledger_db.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/ledger/ledger_db.py)
- **Objectif :** Calcul du Drawdown Global sur 24h.
- **Détails :**
  - Ajout d'une méthode `get_global_drawdown() -> float` qui compare le plus haut capital des dernières 24h (via une requête sur `capital_allocation`) avec le capital actuel.

#### [MODIFY] [portfolio_risk_engine.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/portfolio_risk_engine.py)
- **Objectif :** Implémenter le `Drawdown Circuit Breaker`.
- **Détails :**
  - Lors de l'évaluation du trade (`evaluate_trade`), vérifier le Drawdown via `ledger.get_global_drawdown()`.
  - Si le Drawdown dépasse `-0.10` (-10%), refuser systématiquement le trade, et appeler dynamiquement `emergency_circuit_breaker("ENGAGE")` depuis le MCP Server pour verrouiller le système au niveau global.

## Verification Plan

### Automated Tests
- Simuler une API lente (mock de `post_order` prenant >2s) et vérifier que le `PassiveExecutor` passe en mode Freeze au bout de 3 appels.
- Simuler un crash de Groq API (mock `chat.completions.create` levant des exceptions) et valider que l'Agent IA bascule sur l'extracteur Regex.
- Insérer des fausses données de PnL négatif dans le Ledger et valider que le Risk Engine déclenche le Circuit Breaker.

### Manual Verification
- Redémarrer le bot en mode `PAPER`.
- Débrancher temporairement le réseau pour valider les comportements de "Hang".
