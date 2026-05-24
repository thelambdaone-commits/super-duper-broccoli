# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software distributed under the
#  License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#  KIND, either express or implied. See the License for the specific language governing
#  permissions and limitations under the License.
# -------------------------------------------------------------------------------------------------
#  Modified by Evan Kolberg in this repository on 2026-03-11.
#  See the repository NOTICE file for provenance and licensing scope.
#
"""
Polymarket fee calculation policy.

NautilusTrader 1.226 uses Polymarket's curved taker-fee formula directly. This
module centralizes the repository's Decimal rounding behavior while targeting
the 1.226 function signature with no old-version compatibility layer.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from nautilus_trader.model.enums import LiquiditySide


def basis_points_as_decimal(basis_points: Decimal) -> Decimal:
    """
    Convert basis points to a decimal fraction.

    Parameters
    ----------
    basis_points : Decimal
        The fee rate in basis points (1 bp = 0.01%).

    Returns
    -------
    Decimal
        The decimal fraction (e.g., 100 bp -> 0.01).

    """
    return basis_points / Decimal(10_000)


def calculate_commission(
    quantity: Decimal,
    price: Decimal,
    fee_rate: Decimal,
    liquidity_side: LiquiditySide,
) -> float:
    """
    Calculate commission from trade parameters and fee rate.

    Polymarket's current fee formula is::

        fee = C x feeRate x p x (1 - p)

    Where:
    - C = number of shares (quantity)
    - p = share price
    - feeRate = the effective taker rate as a decimal fraction

    The fee peaks at p = 0.50 and decreases symmetrically toward the
    extremes (p -> 0 or p -> 1).

    Polymarket rounds fees to 5 decimal places (0.00001 pUSD minimum).

    References
    ----------
    https://docs.polymarket.com/trading/fees

    Parameters
    ----------
    quantity : Decimal
        The fill quantity.
    price : Decimal
        The fill price (0 to 1).
    fee_rate : Decimal
        The effective fee rate as a decimal fraction, e.g. ``0.03`` for 3%.
    liquidity_side : LiquiditySide
        The liquidity side for this fill. Maker fills pay no fee.

    Returns
    -------
    float
        The commission amount rounded to 5 decimal places.

    """
    if liquidity_side != LiquiditySide.TAKER or fee_rate <= 0:
        return 0.0

    commission = quantity * fee_rate * price * (Decimal(1) - price)
    return float(commission.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))
