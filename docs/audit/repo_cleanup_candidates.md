# Repo Cleanup Candidates

Inventaire des éléments suspects repérés pendant l'audit. Rien ici n'a été supprimé
automatiquement sans preuve forte d'innocuité.

## Doublons / architecture parallèle

- `core/command_router.py`
  - Routeur BTC/Telegram legacy, partiellement redondant avec `telegram_scraper/command_router.py`.
  - Conservé pour compatibilité. À fusionner ou retirer seulement après validation des points d'entrée réels.

- `core/swarm_supervisor.py` vs `core/swarm/supervisor.py`
  - Deux emplacements proches pour la notion de superviseur. Vérifier lequel est la source canonique.

- `core/wallet_manager.py` vs `utils/wallet_manager.py`
  - Noms proches, responsabilités potentiellement chevauchantes. Vérifier les imports réels avant toute suppression.

## Scripts potentiellement redondants

- `scripts/Reinforcement_Optimization_Loop.py`
- `scripts/reinforcement_optimization_loop.py`
  - Risque de doublon fonctionnel avec variation de casse/nommage.

- `scripts/autonomous_trading_loop.py`
  - Nom potentiellement redondant avec `core/autonomous_trading_loop.py`.

## Arbres externes / vendored

- `freqtrade/`
  - Sous-projet massif embarqué. À traiter comme dépendance vendored, pas comme code applicatif ordinaire.

- `agents/polybot/`
  - Sous-ensemble multi-service Java très séparé du runtime Python principal.
  - Candidat à documentation/isolement supplémentaire plutôt qu'à suppression aveugle.

## Répertoires de travail / expérimentation

- `scratch/`
  - Scripts d'exploration à revalider un par un.

- `graphify-out/`
  - Artefacts d'analyse, probablement régénérables.

- `Technical_Reviews/`
  - Historique documentaire utile, mais hors runtime.

## Dépendances optionnelles observées

Les modules suivants ont cassé les imports globaux avant découplage lazy:

- crawler Polymarket / `scrapling`
- health monitor web / `uvicorn`, `fastapi`
- on-chain monitor / `websockets`

Règle à garder:
- ne plus importer top-level une brique optionnelle dans le bootstrap principal
- préférer les imports lazy ou les wrappers de capability

## Actions conseillées avant suppression réelle

1. tracer les imports/points d'entrée réels
2. vérifier la couverture de tests sur chaque candidat
3. déplacer d'abord vers un namespace `legacy/` ou `archive/` si l'usage reste incertain
4. supprimer seulement après un run de tests large + validation runtime
