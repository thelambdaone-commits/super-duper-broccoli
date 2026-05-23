from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.enums import BookType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import StrategyConfig

from prediction_market_extensions.adapters.prediction_market.order_tags import (
    format_order_intent_tag,
    format_visible_liquidity_tag,
)
from strategies._validation import (
    require_finite_nonnegative_float,
    require_less,
    require_nonnegative_int,
    require_positive_decimal,
    require_positive_int,
    require_probability,
)
from strategies.binary_pair_arbitrage import (
    ENTRY_AFFORDABILITY_BUFFER,
    BookBinaryPairArbitrageStrategy,
    _as_float,
    _decimal_or_none,
    _fee_per_share,
)


class BookPassivePairAccumulationConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg]
    """
    Passive complementary-token pair accumulation.

    Instruments must be ordered as complementary pairs. The strategy rests
    post-only buy limits on both legs when the fee-adjusted passive pair cost
    is below one unit, then holds matched shares to resolution. Any unmatched
    leg is flattened after a bounded completion window.
    """

    instrument_ids: tuple[InstrumentId, ...]
    trade_size: Decimal = Decimal("5")
    min_settlement_edge: float = 0.02
    max_total_cost: float = 0.98
    min_leg_price: float = 0.01
    max_leg_price: float = 0.98
    min_spread: float = 0.005
    max_spread: float = 0.10
    min_visible_size: float = 1.0
    depth_levels: int = 1
    min_bid_depth: float = 0.0
    min_pair_updates_before_entry: int = 0
    max_leg_update_gap: int = 0
    quote_improvement_ticks: int = 0
    ask_buffer_ticks: int = 1
    entry_refresh_updates: int = 50
    pair_completion_timeout_updates: int = 120
    exit_unmatched_surplus: bool = True
    cancel_pair_on_leg_failure: bool = False
    max_entries_per_pair: int = 1
    reentry_cooldown_updates: int = 100
    include_maker_fees_in_signal: bool = True
    pairing_mode: str = "sequential"

    def __post_init__(self) -> None:
        require_positive_decimal("trade_size", self.trade_size)
        require_finite_nonnegative_float("min_settlement_edge", self.min_settlement_edge)
        require_probability("max_total_cost", self.max_total_cost)
        require_probability("min_leg_price", self.min_leg_price)
        require_probability("max_leg_price", self.max_leg_price)
        require_less("min_leg_price", self.min_leg_price, "max_leg_price", self.max_leg_price)
        require_probability("min_spread", self.min_spread)
        require_probability("max_spread", self.max_spread)
        require_less("min_spread", self.min_spread, "max_spread", self.max_spread)
        require_finite_nonnegative_float("min_visible_size", self.min_visible_size)
        require_positive_int("depth_levels", self.depth_levels)
        require_finite_nonnegative_float("min_bid_depth", self.min_bid_depth)
        require_nonnegative_int(
            "min_pair_updates_before_entry",
            self.min_pair_updates_before_entry,
        )
        require_nonnegative_int("max_leg_update_gap", self.max_leg_update_gap)
        require_nonnegative_int("quote_improvement_ticks", self.quote_improvement_ticks)
        require_positive_int("ask_buffer_ticks", self.ask_buffer_ticks)
        require_positive_int("entry_refresh_updates", self.entry_refresh_updates)
        require_positive_int(
            "pair_completion_timeout_updates", self.pair_completion_timeout_updates
        )
        if not isinstance(self.exit_unmatched_surplus, bool):
            raise TypeError("exit_unmatched_surplus must be a bool")
        if not isinstance(self.cancel_pair_on_leg_failure, bool):
            raise TypeError("cancel_pair_on_leg_failure must be a bool")
        require_nonnegative_int("max_entries_per_pair", self.max_entries_per_pair)
        require_nonnegative_int("reentry_cooldown_updates", self.reentry_cooldown_updates)
        if self.pairing_mode != "sequential":
            raise ValueError("pairing_mode currently supports only 'sequential'")
        if len(self.instrument_ids) < 2 or len(self.instrument_ids) % 2 != 0:
            raise ValueError(
                "instrument_ids must contain an even number of instruments ordered as pairs"
            )


class BookPassivePairAccumulationStrategy(BookBinaryPairArbitrageStrategy):
    """
    Maker-first complementary-token accumulation.

    This variant avoids taker pair entries. It pays the realism cost for
    non-atomic passive fills by flattening unmatched surplus with market sells.
    """

    def __init__(self, config: BookPassivePairAccumulationConfig) -> None:
        super().__init__(config)
        self._updates_seen = 0
        self._updates_by_pair: dict[tuple[InstrumentId, InstrumentId], int] = {}
        self._active_entry_by_instrument: dict[InstrumentId, bool] = {}
        self._cancel_pending_by_instrument: dict[InstrumentId, bool] = {}
        self._last_update_seen_by_instrument: dict[InstrumentId, int] = {}
        self._last_quote_update_by_pair: dict[tuple[InstrumentId, InstrumentId], int] = {}
        self._first_fill_update_by_pair: dict[tuple[InstrumentId, InstrumentId], int] = {}
        self._target_size_by_pair: dict[tuple[InstrumentId, InstrumentId], Decimal] = {}
        self._exit_pending_by_pair: dict[tuple[InstrumentId, InstrumentId], bool] = {}

    def on_start(self) -> None:
        instrument_ids = tuple(self.config.instrument_ids)
        self._pairs = [
            (instrument_ids[i], instrument_ids[i + 1]) for i in range(0, len(instrument_ids), 2)
        ]
        self._pair_by_instrument = {
            instrument_id: pair for pair in self._pairs for instrument_id in pair
        }
        self._pending_by_pair = {pair: 0 for pair in self._pairs}
        self._cooldown_by_pair = {pair: 0 for pair in self._pairs}
        self._entries_by_pair = {pair: 0 for pair in self._pairs}
        self._updates_by_pair = {pair: 0 for pair in self._pairs}
        self._last_quote_update_by_pair = {pair: 0 for pair in self._pairs}
        self._first_fill_update_by_pair = {}
        self._target_size_by_pair = {}
        self._exit_pending_by_pair = {pair: False for pair in self._pairs}
        self._active_entry_by_instrument = {
            instrument_id: False for instrument_id in instrument_ids
        }
        self._cancel_pending_by_instrument = {
            instrument_id: False for instrument_id in instrument_ids
        }
        self._last_update_seen_by_instrument = {}

        for instrument_id in instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"Instrument {instrument_id} not found - stopping.")
                self.stop()
                return
            self._instruments[instrument_id] = instrument
            self.subscribe_order_book_deltas(
                instrument_id=instrument_id,
                book_type=BookType.L2_MBP,
            )

    def on_order_book_deltas(self, deltas) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(deltas, "instrument_id", None)
        if instrument_id not in self._pair_by_instrument:
            return
        if instrument_id not in self._books:
            self._books[instrument_id] = OrderBook(
                instrument_id,
                book_type=BookType.L2_MBP,
            )
        self._books[instrument_id].apply_deltas(deltas)
        pair = self._pair_by_instrument[instrument_id]
        self._updates_seen += 1
        self._last_update_seen_by_instrument[instrument_id] = self._updates_seen
        self._updates_by_pair[pair] = self._updates_by_pair.get(pair, 0) + 1
        self._evaluate_pair(pair)

    def _instrument_fee_rate(self, instrument_id: InstrumentId) -> Decimal:
        instrument = self._instruments.get(instrument_id)
        if instrument is None:
            return Decimal("0")
        maker_fee = _decimal_or_none(getattr(instrument, "maker_fee", None))
        if maker_fee is not None:
            return maker_fee
        return _decimal_or_none(getattr(instrument, "taker_fee", None)) or Decimal("0")

    def _position_size(self, instrument_id: InstrumentId) -> Decimal:
        net_position = self.portfolio.net_position(instrument_id)
        position_size = _decimal_or_none(net_position)
        if position_size is None and hasattr(net_position, "signed_decimal_qty"):
            try:
                position_size = _decimal_or_none(net_position.signed_decimal_qty())
            except TypeError:
                position_size = _decimal_or_none(getattr(net_position, "signed_decimal_qty", None))
        if position_size is None and hasattr(net_position, "signed_qty"):
            position_size = _decimal_or_none(getattr(net_position, "signed_qty", None))
        return max(position_size or Decimal("0"), Decimal("0"))

    def _price_increment(self, instrument_id: InstrumentId) -> float:
        instrument = self._instruments.get(instrument_id)
        if instrument is None:
            return 0.01
        increment = _as_float(getattr(instrument, "price_increment", None))
        return increment if increment is not None and increment > 0.0 else 0.01

    def _depth_sum(self, levels: list[object]) -> float:
        depth = 0.0
        for level in levels[: int(self.config.depth_levels)]:
            size = _as_float(getattr(level, "size", None))
            if size is not None and size > 0.0:
                depth += size
        return depth

    def _best_bid_state(
        self,
        instrument_id: InstrumentId,
    ) -> tuple[float, float, float, float, float]:
        book = self._books[instrument_id]
        bid = _as_float(book.best_bid_price())
        ask = _as_float(book.best_ask_price())
        bid_size = _as_float(book.best_bid_size())
        spread = _as_float(book.spread())
        bid_depth = self._depth_sum(book.bids())
        if bid is None or ask is None or bid_size is None or spread is None:
            raise ValueError("book has no two-sided best bid state")
        return bid, ask, bid_size, spread, bid_depth

    def _passive_price(
        self, instrument_id: InstrumentId, *, bid: float, ask: float
    ) -> float | None:
        tick = self._price_increment(instrument_id)
        improved_bid = bid + (int(self.config.quote_improvement_ticks) * tick)
        price = min(improved_bid, ask - (int(self.config.ask_buffer_ticks) * tick))
        if price <= 0.0 or price >= ask:
            return None
        if price < bid - 1e-12:
            return None
        return price

    def _active_pair_orders(self, pair: tuple[InstrumentId, InstrumentId]) -> bool:
        return any(
            self._active_entry_by_instrument.get(instrument_id, False) for instrument_id in pair
        )

    def _pair_positions(
        self,
        pair: tuple[InstrumentId, InstrumentId],
    ) -> tuple[Decimal, Decimal]:
        return self._position_size(pair[0]), self._position_size(pair[1])

    def _matched_position_size(self, pair: tuple[InstrumentId, InstrumentId]) -> Decimal:
        positions = self._pair_positions(pair)
        return min(positions[0], positions[1])

    def _has_pair_position(self, pair: tuple[InstrumentId, InstrumentId]) -> bool:
        positions = self._pair_positions(pair)
        return positions[0] > 0 or positions[1] > 0

    def _surplus_position_sizes(
        self,
        pair: tuple[InstrumentId, InstrumentId],
    ) -> tuple[Decimal, Decimal]:
        positions = self._pair_positions(pair)
        matched = min(positions[0], positions[1])
        return positions[0] - matched, positions[1] - matched

    def _target_reached(self, pair: tuple[InstrumentId, InstrumentId]) -> bool:
        target = self._target_size_by_pair.get(pair)
        if target is None or target <= 0:
            return self._matched_position_size(pair) > 0
        threshold = target * Decimal("0.999")
        positions = self._pair_positions(pair)
        return positions[0] >= threshold and positions[1] >= threshold

    def _entry_state(
        self,
        pair: tuple[InstrumentId, InstrumentId],
    ) -> tuple[list[float], list[object], float, float, Decimal] | None:
        if int(self.config.max_leg_update_gap) > 0:
            last_updates = [
                self._last_update_seen_by_instrument.get(instrument_id) for instrument_id in pair
            ]
            if any(last_update is None for last_update in last_updates):
                return None
            if max(last_updates) - min(last_updates) > int(self.config.max_leg_update_gap):
                return None

        states: list[tuple[float, float, float, float, float]] = []
        for instrument_id in pair:
            try:
                state = self._best_bid_state(instrument_id)
            except (KeyError, ValueError):
                return None
            bid, ask, bid_size, spread, bid_depth = state
            if ask <= bid or bid <= 0.0 or ask >= 1.0 or bid_size <= 0.0 or spread <= 0.0:
                return None
            if bid < float(self.config.min_leg_price) or bid > float(self.config.max_leg_price):
                return None
            if spread < float(self.config.min_spread) or spread > float(self.config.max_spread):
                return None
            if bid_size < float(self.config.min_visible_size):
                return None
            if bid_depth < float(self.config.min_bid_depth):
                return None
            states.append(state)

        prices: list[float] = []
        for instrument_id, state in zip(pair, states, strict=True):
            price = self._passive_price(instrument_id, bid=state[0], ask=state[1])
            if price is None:
                return None
            prices.append(price)

        visible_sizes = [Decimal(str(state[2])) for state in states]
        desired_size = min(Decimal(str(self.config.trade_size)), visible_sizes[0], visible_sizes[1])
        if desired_size <= 0:
            return None

        fee_rates = (
            [self._instrument_fee_rate(instrument_id) for instrument_id in pair]
            if self.config.include_maker_fees_in_signal
            else [Decimal("0"), Decimal("0")]
        )
        price_decimals = [Decimal(str(price)) for price in prices]
        fees = [_fee_per_share(price=price_decimals[i], taker_fee=fee_rates[i]) for i in range(2)]
        net_unit_cost = price_decimals[0] + price_decimals[1] + fees[0] + fees[1]
        edge = Decimal("1") - net_unit_cost
        if edge < Decimal(str(self.config.min_settlement_edge)):
            return None
        if net_unit_cost > Decimal(str(self.config.max_total_cost)):
            return None

        free_balance = self._free_quote_balance(pair[0])
        if free_balance is not None:
            affordable_size = (free_balance * ENTRY_AFFORDABILITY_BUFFER) / net_unit_cost
            desired_size = min(desired_size, affordable_size)
        if desired_size <= 0:
            return None

        quantities = [self._rounded_quantity(instrument_id, desired_size) for instrument_id in pair]
        if quantities[0] is None or quantities[1] is None:
            return None
        rounded_sizes = [Decimal(str(quantity.as_double())) for quantity in quantities]
        target_size = min(rounded_sizes[0], rounded_sizes[1])
        if target_size <= 0:
            return None
        return (
            prices,
            quantities,
            float(min(visible_sizes[0], visible_sizes[1])),
            float(edge),
            target_size,
        )

    def _evaluate_pair(self, pair: tuple[InstrumentId, InstrumentId]) -> None:
        if self._target_reached(pair):
            if self._active_pair_orders(pair):
                self._cancel_pair_orders(pair)
            return

        if self._has_pair_position(pair):
            pair_updates = self._updates_by_pair.get(pair, 0)
            self._first_fill_update_by_pair.setdefault(pair, pair_updates)
            held_updates = pair_updates - self._first_fill_update_by_pair[pair]
            if held_updates < int(self.config.pair_completion_timeout_updates):
                return
            if self._active_pair_orders(pair):
                self._cancel_pair_orders(pair)
            if not self.config.exit_unmatched_surplus:
                self._exit_pending_by_pair[pair] = True
                return
            if not self._exit_pending_by_pair.get(pair, False):
                self._submit_surplus_exit(pair)
            return

        if self._active_pair_orders(pair):
            pair_updates = self._updates_by_pair.get(pair, 0)
            quote_age = pair_updates - self._last_quote_update_by_pair.get(pair, pair_updates)
            if quote_age >= int(self.config.entry_refresh_updates):
                self._cancel_pair_orders(pair)
                self._cooldown_by_pair[pair] = int(self.config.reentry_cooldown_updates)
            return

        if self._cooldown_by_pair.get(pair, 0) > 0:
            self._cooldown_by_pair[pair] -= 1
            return
        if self._entries_by_pair.get(pair, 0) >= int(self.config.max_entries_per_pair):
            return
        if self._updates_by_pair.get(pair, 0) < int(self.config.min_pair_updates_before_entry):
            return

        entry_state = self._entry_state(pair)
        if entry_state is None:
            return
        prices, quantities, visible_size, edge, target_size = entry_state
        self._submit_pair_entry(
            pair=pair,
            prices=prices,
            quantities=quantities,
            visible_size=visible_size,
            edge=edge,
            target_size=target_size,
        )

    def _submit_pair_entry(
        self,
        *,
        pair: tuple[InstrumentId, InstrumentId],
        prices: list[float],
        quantities: list[object],
        visible_size: float,
        edge: float,
        target_size: Decimal,
    ) -> None:
        tags = [format_order_intent_tag("passive_pair_entry")]
        visible_liquidity_tag = format_visible_liquidity_tag(visible_size)
        if visible_liquidity_tag is not None:
            tags.append(visible_liquidity_tag)

        orders = [
            self.order_factory.limit(
                instrument_id=pair[i],
                order_side=OrderSide.BUY,
                quantity=quantities[i],
                price=self._instruments[pair[i]].make_price(prices[i]),
                time_in_force=TimeInForce.GTC,
                post_only=True,
                tags=tags,
            )
            for i in range(2)
        ]
        self.log.info(
            "Submitting passive pair entry "
            f"pair={pair}, edge={edge:.6f}, visible_size={visible_size:.6f}"
        )
        self._entries_by_pair[pair] = self._entries_by_pair.get(pair, 0) + 1
        self._last_quote_update_by_pair[pair] = self._updates_by_pair.get(pair, 0)
        self._target_size_by_pair[pair] = target_size
        try:
            for order in orders:
                self._active_entry_by_instrument[order.instrument_id] = True
                self._cancel_pending_by_instrument[order.instrument_id] = False
                self.submit_order(order)
        except Exception:
            for instrument_id in pair:
                self._active_entry_by_instrument[instrument_id] = False
                self._cancel_pending_by_instrument[instrument_id] = False
            raise

    def _cancel_pair_orders(self, pair: tuple[InstrumentId, InstrumentId]) -> None:
        for instrument_id in pair:
            if not self._active_entry_by_instrument.get(instrument_id, False):
                continue
            if self._cancel_pending_by_instrument.get(instrument_id, False):
                continue
            self.cancel_all_orders(instrument_id)
            self._cancel_pending_by_instrument[instrument_id] = True

    def _submit_surplus_exit(self, pair: tuple[InstrumentId, InstrumentId]) -> None:
        surplus_sizes = self._surplus_position_sizes(pair)
        orders = []
        for instrument_id, size in zip(pair, surplus_sizes, strict=True):
            if size <= 0:
                continue
            quantity = self._rounded_quantity(instrument_id, size)
            if quantity is None:
                continue
            orders.append(
                self.order_factory.market(
                    instrument_id=instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=quantity,
                    time_in_force=TimeInForce.IOC,
                    reduce_only=True,
                    tags=[format_order_intent_tag("passive_pair_unmatched_exit")],
                )
            )
        if not orders:
            return
        self.log.info(f"Submitting passive pair unmatched exit pair={pair}, orders={len(orders)}")
        self._exit_pending_by_pair[pair] = True
        self._cooldown_by_pair[pair] = int(self.config.reentry_cooldown_updates)
        for order in orders:
            self.submit_order(order)

    def _mark_order_closed(self, event) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(event, "instrument_id", None)
        pair = self._pair_by_instrument.get(instrument_id)
        if pair is None:
            return
        if getattr(event, "order_side", None) == OrderSide.BUY and self._event_order_is_closed(
            event
        ):
            self._active_entry_by_instrument[instrument_id] = False
            self._cancel_pending_by_instrument[instrument_id] = False
        if getattr(event, "order_side", None) == OrderSide.SELL and self._event_order_is_closed(
            event
        ):
            self._exit_pending_by_pair[pair] = self._surplus_position_sizes(pair) != (
                Decimal("0"),
                Decimal("0"),
            )

    def _cancel_pair_after_entry_leg_failure(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self.config.cancel_pair_on_leg_failure:
            return
        if getattr(event, "order_side", None) != OrderSide.BUY:
            return
        if not self._event_order_is_closed(event):
            return
        instrument_id = getattr(event, "instrument_id", None)
        pair = self._pair_by_instrument.get(instrument_id)
        if pair is None or self._has_pair_position(pair):
            return

        canceled = False
        for sibling_id in pair:
            if sibling_id == instrument_id:
                continue
            if not self._active_entry_by_instrument.get(sibling_id, False):
                continue
            if self._cancel_pending_by_instrument.get(sibling_id, False):
                continue
            self.log.info(f"Canceling sibling entry after leg failure pair={pair}")
            self.cancel_all_orders(sibling_id)
            self._cancel_pending_by_instrument[sibling_id] = True
            canceled = True
        if canceled:
            self._cooldown_by_pair[pair] = max(
                self._cooldown_by_pair.get(pair, 0),
                int(self.config.reentry_cooldown_updates),
            )

    def on_order_filled(self, event) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(event, "instrument_id", None)
        pair = self._pair_by_instrument.get(instrument_id)
        if pair is not None and getattr(event, "order_side", None) == OrderSide.BUY:
            self._first_fill_update_by_pair.setdefault(pair, self._updates_by_pair.get(pair, 0))
        self._mark_order_closed(event)

    def on_order_rejected(self, event) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(event, "instrument_id", None)
        if instrument_id in self._active_entry_by_instrument:
            self._active_entry_by_instrument[instrument_id] = False
        self._mark_order_closed(event)
        self._cancel_pair_after_entry_leg_failure(event)

    def on_order_denied(self, event) -> None:  # type: ignore[no-untyped-def]
        self.on_order_rejected(event)

    def on_order_canceled(self, event) -> None:  # type: ignore[no-untyped-def]
        self.on_order_rejected(event)

    def on_order_expired(self, event) -> None:  # type: ignore[no-untyped-def]
        self.on_order_rejected(event)

    def on_stop(self) -> None:
        for pair in self._pairs:
            self._cancel_pair_orders(pair)
            if self._has_pair_position(pair) and not self._target_reached(pair):
                self._submit_surplus_exit(pair)

    def on_reset(self) -> None:
        super().on_reset()
        self._updates_seen = 0
        self._updates_by_pair.clear()
        self._active_entry_by_instrument.clear()
        self._cancel_pending_by_instrument.clear()
        self._last_update_seen_by_instrument.clear()
        self._last_quote_update_by_pair.clear()
        self._first_fill_update_by_pair.clear()
        self._target_size_by_pair.clear()
        self._exit_pending_by_pair.clear()
