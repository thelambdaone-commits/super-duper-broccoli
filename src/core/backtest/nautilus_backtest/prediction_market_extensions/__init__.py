"""Prediction market extensions for NautilusTrader."""

from __future__ import annotations

_COMMISSION_PATCH_INSTALLED = False


def install_commission_patch() -> None:
    """
    Install the repo's Polymarket commission rounding policy.

    Nautilus 1.226 uses the current curved fee formula and pUSD currency
    model. This startup hook keeps this repository's fee rounding centralized
    while targeting the 1.226 function signature directly.
    """
    global _COMMISSION_PATCH_INSTALLED
    if _COMMISSION_PATCH_INSTALLED:
        return

    import nautilus_trader.adapters.polymarket.common.parsing as upstream_parsing

    from prediction_market_extensions.adapters.polymarket import parsing as pm_parsing

    upstream_parsing.calculate_commission = pm_parsing.calculate_commission
    _COMMISSION_PATCH_INSTALLED = True


install_commission_patch()
