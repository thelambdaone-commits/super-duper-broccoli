# Troubleshooting

## Bugs Résolus

### 2026-05-23 — IndentationError dans utils/market_scanner.py
- **Symptôme**: `IndentationError: unindent does not match any outer indentation level` dans `_fmt_signal()`
- **Cause**: Mélange d'indentations (espaces/tabs) dans la fonction `_fmt_signal` à la fin du fichier
- **Solution**: Correction de l'indentation dans le commit `fcb8f00`

### 2026-05-23 — Import datetime manquant
- **Symptôme**: `NameError: name 'datetime' is not defined` dans `core/autonomous_trading_loop.py`
- **Cause**: `datetime` utilisé dans `_approved_strategy_signals()` sans import
- **Solution**: Ajout de `from datetime import datetime, timezone` dans le commit `b621461`

### 2026-05-23 — Sélecteur trop restrictif (0/75 signaux passent)
- **Symptôme**: Tous les signaux de trading rejetés par les quality filters
- **Cause**: `min_liquidity_usdc: 25.0` et `ev_min: 0.005` trop élevés pour les petits signaux
- **Solution**: Baisser `min_liquidity_usdc` à 1.0, `ev_min` à 0.001, `sigma_relative_max` à 0.50

## Notes
- Documenter ici les bugs récurrents et leurs solutions
