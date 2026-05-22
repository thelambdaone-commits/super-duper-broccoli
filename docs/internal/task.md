# Tâches d'Implémentation Sécurité & Résilience

- `[x]` 1. Implémenter le "Drawdown Circuit Breaker"
  - `[x]` Ajouter la méthode `get_global_drawdown()` dans `ledger_db.py`.
  - `[x]` Intégrer l'évaluation du drawdown dans `portfolio_risk_engine.py` et appeler `emergency_circuit_breaker`.
- `[x]` 2. Implémenter le "API Latency Watchdog"
  - `[x]` Ajouter les compteurs de latence dans `passive_executor.py`.
  - `[x]` Timer les appels réseau de `freqai`.
  - `[x]` Déclencher un freeze local (60 secondes) après 3 dépassements > 2000ms.
- `[x]` 3. Implémenter le "Fallback IA Déterministe"
  - `[x]` Ajouter le tracking d'échecs (consecutive_failures) dans `lobstar_agent.py`.
  - `[x]` Créer une méthode de fallback regex dans `LobstarAgent`.
  - `[x]` Activer le fallback en cas d'erreurs répétées.
- `[x]` 4. Vérification
  - `[x]` Lancer la suite de tests (`pytest`).
  - `[x]` Effectuer le Security Scan (`make bandit`).
