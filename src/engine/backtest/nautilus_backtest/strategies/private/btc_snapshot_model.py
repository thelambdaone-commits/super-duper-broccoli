from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.currencies import pUSD
from nautilus_trader.model.enums import BookType, LiquiditySide, OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events.order import OrderFilled
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId, TradeId, VenueOrderId
from nautilus_trader.model.objects import Money
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backtests.private.telonex_btc_5m_snapshot_model_research import (
    _FEATURE_COLUMNS,
    LogisticModel,
    _load_btc_features,
    _predict,
)
from prediction_market_extensions.adapters.prediction_market.order_tags import (
    format_order_intent_tag,
    format_visible_liquidity_tag,
)
from prediction_market_extensions.live.btc_features import LiveBtcFeatureStore
from prediction_market_extensions.live.settlement import (
    fetch_clob_token_settlement,
    split_polymarket_instrument_id,
)
from strategies._validation import (
    require_finite_nonnegative_float,
    require_positive_decimal,
    require_positive_int,
    require_probability,
)

_WINDOW_SECONDS = 300
_NANOSECONDS_PER_SECOND = 1_000_000_000
_ENTRY_AFFORDABILITY_BUFFER = Decimal("0.90")
_MOMENTUM_ALIGNMENT_MODES = {
    "none",
    "m15_m30",
    "pdiff_m15_m30",
    "momentum_vote",
    "reject_m15_m30_opposed",
    "reject_two_of_three_opposed",
}


class BookBtcSnapshotModelConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg]
    instrument_ids: tuple[InstrumentId, ...]
    model_path: str
    btc_instrument_id: InstrumentId | None = None
    extra_spot_instrument_ids: tuple[InstrumentId, ...] = ()
    trade_size: Decimal = Decimal("2")
    edge: float = 0.06
    snapshot_seconds: tuple[int, ...] = (180, 120, 60, 30, 10)
    max_ask_price: float = 0.70
    max_spread: float = 0.20
    min_ask_price: float = 0.0
    max_book_age_seconds: float = 8.0
    depth_levels: int = 5
    max_expected_slippage: float = 0.02
    min_visible_size: float = 1.0
    min_selected_probability: float = 0.0
    expensive_ask_floor: float = 1.0
    expensive_min_selected_probability: float = 0.0
    expensive_min_signed_momentum_30s: float = 0.0
    adverse_price_diff_floor: float = 0.0
    adverse_min_signed_momentum_30s: float = 0.0
    exhausted_price_diff_floor: float = 0.0
    exhausted_min_selected_probability: float = 0.0
    volatile_price_diff_floor: float = 0.0
    volatile_min_selected_probability: float = 0.0
    max_yes_no_ask_cost: float = 0.0
    diagnostics_path: str | None = None
    momentum_alignment: str = "none"
    live_btc_buffer_seconds: int = 900
    max_btc_feature_age_seconds: float = 0.0
    market_buy_quote_quantity: bool = False
    min_market_buy_quote_amount: Decimal = Decimal("0")
    daily_stop_loss: float = 0.0
    settlement_poll_seconds: float = 15.0
    settlement_grace_seconds: float = 10.0
    settlement_timeout_seconds: float = 5.0
    settlement_base_url: str = "https://clob.polymarket.com"
    settlement_path: str | None = None
    dynamic_instrument_scan_seconds: float = 0.0
    market_retention_seconds: float = 0.0
    heartbeat_log_seconds: float = 300.0

    def __post_init__(self) -> None:
        require_positive_decimal("trade_size", self.trade_size)
        if self.min_market_buy_quote_amount < 0:
            raise ValueError(
                f"min_market_buy_quote_amount must be >= 0, got {self.min_market_buy_quote_amount}"
            )
        require_finite_nonnegative_float("edge", self.edge)
        require_probability("max_ask_price", self.max_ask_price)
        require_probability("min_ask_price", self.min_ask_price)
        if self.min_ask_price > self.max_ask_price:
            raise ValueError("min_ask_price must be <= max_ask_price")
        require_probability("max_spread", self.max_spread)
        require_finite_nonnegative_float("max_book_age_seconds", self.max_book_age_seconds)
        require_positive_int("depth_levels", self.depth_levels)
        require_finite_nonnegative_float("max_expected_slippage", self.max_expected_slippage)
        require_finite_nonnegative_float("min_visible_size", self.min_visible_size)
        require_probability("min_selected_probability", self.min_selected_probability)
        require_probability("expensive_ask_floor", self.expensive_ask_floor)
        require_probability(
            "expensive_min_selected_probability",
            self.expensive_min_selected_probability,
        )
        require_finite_nonnegative_float(
            "expensive_min_signed_momentum_30s",
            self.expensive_min_signed_momentum_30s,
        )
        require_finite_nonnegative_float("adverse_price_diff_floor", self.adverse_price_diff_floor)
        require_finite_nonnegative_float(
            "adverse_min_signed_momentum_30s",
            self.adverse_min_signed_momentum_30s,
        )
        require_finite_nonnegative_float(
            "exhausted_price_diff_floor",
            self.exhausted_price_diff_floor,
        )
        require_probability(
            "exhausted_min_selected_probability",
            self.exhausted_min_selected_probability,
        )
        require_finite_nonnegative_float(
            "volatile_price_diff_floor", self.volatile_price_diff_floor
        )
        require_probability(
            "volatile_min_selected_probability",
            self.volatile_min_selected_probability,
        )
        require_finite_nonnegative_float("max_yes_no_ask_cost", self.max_yes_no_ask_cost)
        if self.momentum_alignment.strip().casefold() not in _MOMENTUM_ALIGNMENT_MODES:
            modes = ", ".join(sorted(_MOMENTUM_ALIGNMENT_MODES))
            raise ValueError(f"momentum_alignment must be one of: {modes}")
        require_positive_int("live_btc_buffer_seconds", self.live_btc_buffer_seconds)
        require_finite_nonnegative_float(
            "max_btc_feature_age_seconds",
            self.max_btc_feature_age_seconds,
        )
        require_finite_nonnegative_float("daily_stop_loss", self.daily_stop_loss)
        require_finite_nonnegative_float("settlement_poll_seconds", self.settlement_poll_seconds)
        require_finite_nonnegative_float("settlement_grace_seconds", self.settlement_grace_seconds)
        require_finite_nonnegative_float(
            "settlement_timeout_seconds",
            self.settlement_timeout_seconds,
        )
        require_finite_nonnegative_float(
            "dynamic_instrument_scan_seconds",
            self.dynamic_instrument_scan_seconds,
        )
        require_finite_nonnegative_float("market_retention_seconds", self.market_retention_seconds)
        require_finite_nonnegative_float("heartbeat_log_seconds", self.heartbeat_log_seconds)
        if len(self.instrument_ids) < 2 or len(self.instrument_ids) % 2 != 0:
            raise ValueError("instrument_ids must contain paired UP/DOWN instruments")
        if not self.snapshot_seconds:
            raise ValueError("snapshot_seconds must not be empty")
        if any(value <= 0 or value >= _WINDOW_SECONDS for value in self.snapshot_seconds):
            raise ValueError("snapshot_seconds values must be inside the 5m window")


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    if callable(value):
        value = value()
    as_double = getattr(value, "as_double", None)
    if callable(as_double):
        return float(as_double())
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _is_buy_order_side(value: object) -> bool:
    if value is OrderSide.BUY:
        return True
    name = getattr(value, "name", None)
    if isinstance(name, str) and name.upper() == "BUY":
        return True
    try:
        return int(value) == int(OrderSide.BUY)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    text = str(value).strip().upper()
    return text in {"BUY", "ORDER_SIDE_BUY"} or text.endswith(".BUY")


def _spot_prefix_from_instrument_id(instrument_id: InstrumentId) -> str:
    symbol = str(instrument_id).split(".", 1)[0].strip().lower()
    if symbol.endswith("usdt"):
        symbol = symbol[:-4]
    return symbol


def _extra_spot_prefixes_from_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    prefixes: list[str] = []
    suffix = "_return_since_start"
    for column in columns:
        if not column.endswith(suffix):
            continue
        prefix = column[: -len(suffix)]
        if prefix and prefix not in {"btc"} and prefix not in prefixes:
            prefixes.append(prefix)
    return tuple(prefixes)


def _has_spot_quote_columns(columns: tuple[str, ...]) -> bool:
    return any("_quote_" in column for column in columns)


def _bps_return(current: float, prior: float) -> float:
    if not math.isfinite(current) or not math.isfinite(prior) or prior <= 0.0:
        return math.nan
    return ((current / prior) - 1.0) * 10_000.0


def _load_model(path: str) -> LogisticModel:
    payload = json.loads(Path(path).read_text())
    model = payload["model"]
    return LogisticModel(
        columns=tuple(str(value) for value in model["columns"]),
        means=tuple(float(value) for value in model["means"]),
        scales=tuple(float(value) for value in model["scales"]),
        weights=tuple(float(value) for value in model["weights"]),
        bias=float(model["bias"]),
    )


def _market_start_from_slug(slug: str) -> int | None:
    try:
        return int(slug.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


def _market_prune_due_ns(*, market_start: int, post_end_retention_seconds: float) -> int:
    due_seconds = market_start + _WINDOW_SECONDS + max(0.0, post_end_retention_seconds)
    return int(due_seconds * _NANOSECONDS_PER_SECOND)


def _log_float(value: object, *, digits: int = 4) -> str:
    as_float = _as_float(value)
    if as_float is None or not math.isfinite(as_float):
        return "na"
    return f"{as_float:.{digits}f}"


def _book_features(order_book: OrderBook, *, levels: int) -> dict[str, float] | None:
    bid = _as_float(order_book.best_bid_price())
    ask = _as_float(order_book.best_ask_price())
    bid_size = _as_float(order_book.best_bid_size())
    ask_size = _as_float(order_book.best_ask_size())
    if bid is None or ask is None or bid_size is None or ask_size is None:
        return None
    if bid <= 0.0 or ask <= 0.0 or bid >= ask or bid_size <= 0.0 or ask_size <= 0.0:
        return None

    bid_depth = 0.0
    ask_depth = 0.0
    for level in order_book.bids()[:levels]:
        size = _as_float(getattr(level, "size", None))
        if size is not None and size > 0.0:
            bid_depth += size
    for level in order_book.asks()[:levels]:
        size = _as_float(getattr(level, "size", None))
        if size is not None and size > 0.0:
            ask_depth += size
    depth_total = bid_depth + ask_depth
    size_total = bid_size + ask_size
    if depth_total <= 0.0 or size_total <= 0.0:
        return None
    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2.0,
        "spread": ask - bid,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_imbalance": (bid_depth - ask_depth) / depth_total,
        "microprice": ((ask * bid_size) + (bid * ask_size)) / size_total,
    }


class BookBtcSnapshotModelStrategy(Strategy):
    """
    Batch BTC 5m classifier strategy using Telonex Polymarket L2 and Telonex
    Binance BTC trades.
    """

    def __init__(self, config: BookBtcSnapshotModelConfig) -> None:
        super().__init__(config)
        self._books: dict[InstrumentId, OrderBook] = {}
        self._book_ts_ns: dict[InstrumentId, int] = {}
        self._instruments: dict[InstrumentId, object] = {}
        self._slug_by_instrument: dict[InstrumentId, str] = {}
        self._outcome_by_instrument: dict[InstrumentId, str] = {}
        self._pairs: dict[str, dict[str, InstrumentId]] = {}
        self._market_start_by_slug: dict[str, int] = {}
        self._evaluated_buckets: set[tuple[str, int]] = set()
        self._traded_slugs: set[str] = set()
        self._model: LogisticModel | None = None
        self._btc: Any = None
        self._btc_book: OrderBook | None = None
        self._btc_book_ts_ns = 0
        self._extra_spot_prefixes: tuple[str, ...] = ()
        self._spot_prefix_by_instrument: dict[InstrumentId, str] = {}
        self._spot_store_by_prefix: dict[str, LiveBtcFeatureStore] = {}
        self._spot_book_by_instrument: dict[InstrumentId, OrderBook] = {}
        self._order_diagnostics: dict[str, dict[str, Any]] = {}
        self._fill_diagnostics: list[dict[str, Any]] = []
        self._evaluation_diagnostics: list[dict[str, Any]] = []
        self._settlement_positions: dict[str, dict[str, Any]] = {}
        self._last_settlement_poll_ns = 0
        self._last_instrument_scan_ns = 0
        self._last_heartbeat_log_ns = 0
        self._subscribed_instrument_ids: set[InstrumentId] = set()
        self._pruned_slugs: set[str] = set()
        self._logged_evaluation_events: set[tuple[str, int, str, str]] = set()

    def _diagnostics_enabled(self) -> bool:
        return bool(self.config.diagnostics_path)

    def _record_evaluation(self, payload: dict[str, Any]) -> None:
        self._log_evaluation_event(payload)
        if not self._diagnostics_enabled():
            return
        self._evaluation_diagnostics.append(
            {key: value for key, value in payload.items() if isinstance(value, int | float | str)}
        )

    def _log_evaluation_event(self, payload: dict[str, Any]) -> None:
        slug = str(payload.get("slug") or "")
        seconds_left = int(_as_float(payload.get("seconds_left")) or 0)
        reason = str(payload.get("skip_reason") or "")
        selected = str(payload.get("selected_outcome") or "")
        key = (slug, seconds_left, reason, selected)
        if key in self._logged_evaluation_events:
            return
        self._logged_evaluation_events.add(key)

        event = "SANDBOX_EVAL_SIGNAL" if not reason else "SANDBOX_EVAL_SKIP"
        fields = [
            event,
            f"slug={slug}",
            f"seconds_left={seconds_left}",
        ]
        if selected:
            fields.append(f"selected={selected}")
        if reason:
            fields.append(f"reason={reason}")
        for name in (
            "prob_up",
            "yes_edge",
            "no_edge",
            "yes_ask",
            "no_ask",
            "yes_no_ask_cost",
            "btc_feature_age_seconds",
            "btc_start_age_seconds",
            "max_btc_feature_age_seconds",
            "price_diff",
            "momentum_15s",
            "momentum_30s",
        ):
            if name in payload:
                fields.append(f"{name}={_log_float(payload.get(name))}")
        if "selected_ask" in payload:
            fields.append(f"selected_ask={_log_float(payload.get('selected_ask'))}")
        if "selected_ask_size" in payload:
            fields.append(f"selected_ask_size={_log_float(payload.get('selected_ask_size'))}")
        if "selected_spread" in payload:
            fields.append(f"selected_spread={_log_float(payload.get('selected_spread'))}")
        if "selected_probability" in payload:
            fields.append(f"selected_probability={_log_float(payload.get('selected_probability'))}")
        if "expected_entry_price" in payload:
            fields.append(f"expected_entry_price={_log_float(payload.get('expected_entry_price'))}")
        if "submitted_quote_amount" in payload:
            fields.append(
                f"submitted_quote_amount={_log_float(payload.get('submitted_quote_amount'))}"
            )
        self.log.info(" ".join(fields))

    def _maybe_log_heartbeat(self, *, now_ns: int, btc_price: float | None) -> None:
        heartbeat_seconds = float(self.config.heartbeat_log_seconds)
        if heartbeat_seconds <= 0.0:
            return
        if now_ns <= 0:
            now_ns = self.clock.timestamp_ns()
        heartbeat_ns = int(heartbeat_seconds * _NANOSECONDS_PER_SECOND)
        if heartbeat_ns > 0 and now_ns - self._last_heartbeat_log_ns < heartbeat_ns:
            return
        self._last_heartbeat_log_ns = now_ns
        unsettled_positions = sum(
            1
            for position in self._settlement_positions.values()
            if not bool(position.get("settled"))
        )
        settled_positions = len(self._settlement_positions) - unsettled_positions
        self.log.info(
            "SANDBOX_MODEL_HEARTBEAT "
            f"tracked_markets={len(self._pairs)} "
            f"active_subscriptions={len(self._subscribed_instrument_ids)} "
            f"books={len(self._books)} "
            f"evaluated_buckets={len(self._evaluated_buckets)} "
            f"traded_markets={len(self._traded_slugs)} "
            f"unsettled_positions={unsettled_positions} "
            f"settled_positions={settled_positions} "
            f"latest_btc={_log_float(btc_price, digits=2)} "
            f"btc_age_seconds={_log_float(self._btc_feature_age(now_ns // _NANOSECONDS_PER_SECOND))}",
        )

    def _mark_evaluated(self, slug: str, buckets: list[int]) -> None:
        for due_bucket in buckets:
            self._evaluated_buckets.add((slug, due_bucket))

    def _btc_feature_age(self, ts: int) -> float:
        observation_age_seconds = getattr(self._btc, "observation_age_seconds", None)
        if not callable(observation_age_seconds):
            return 0.0
        try:
            return float(observation_age_seconds(ts))
        except (TypeError, ValueError):
            return math.inf

    def _btc_book_features(self, ts: int) -> dict[str, float] | None:
        book_features_at = getattr(self._btc, "book_features_at", None)
        if not callable(book_features_at):
            return None
        try:
            features = book_features_at(ts)
        except (TypeError, ValueError):
            return None
        if not isinstance(features, dict):
            return None
        return {str(key): float(value) for key, value in features.items()}

    def _register_btc_5m_instrument(
        self,
        *,
        instrument_id: InstrumentId,
        instrument: object,
        strict: bool,
    ) -> bool:
        if instrument_id in self._slug_by_instrument:
            self._instruments[instrument_id] = instrument
            return True

        info = dict(getattr(instrument, "info", None) or {})
        slug = str(info.get("market_slug") or "")
        if not slug.startswith("btc-updown-5m-"):
            return False
        outcome = str(getattr(instrument, "outcome", "") or info.get("outcome") or "")
        normalized_outcome = outcome.strip().casefold()
        if normalized_outcome not in {"up", "down"}:
            message = f"Unexpected BTC 5m outcome {outcome!r} for {instrument_id}."
            if strict:
                self.log.error(message)
            else:
                self.log.warning(message)
            return False
        market_start = _market_start_from_slug(slug)
        if market_start is None:
            message = f"Unable to parse BTC 5m start timestamp from slug {slug!r}."
            if strict:
                self.log.error(message)
            else:
                self.log.warning(message)
            return False
        if slug in self._pruned_slugs:
            return False

        self._instruments[instrument_id] = instrument
        self._slug_by_instrument[instrument_id] = slug
        self._outcome_by_instrument[instrument_id] = normalized_outcome
        self._market_start_by_slug[slug] = market_start
        self._pairs.setdefault(slug, {})[normalized_outcome] = instrument_id
        return True

    def _subscribe_book_if_needed(self, instrument_id: InstrumentId) -> None:
        if instrument_id in self._subscribed_instrument_ids:
            return
        self.subscribe_order_book_deltas(instrument_id=instrument_id, book_type=BookType.L2_MBP)
        self._subscribed_instrument_ids.add(instrument_id)

    def _scan_cached_btc_5m_instruments(self) -> int:
        tracked = 0
        for instrument in self.cache.instruments():
            instrument_id = getattr(instrument, "id", None)
            if not isinstance(instrument_id, InstrumentId):
                continue
            already_tracked = instrument_id in self._slug_by_instrument
            if not self._register_btc_5m_instrument(
                instrument_id=instrument_id,
                instrument=instrument,
                strict=False,
            ):
                continue
            if already_tracked:
                continue
            self._subscribe_book_if_needed(instrument_id)
            tracked += 1
            slug = self._slug_by_instrument[instrument_id]
            pair = self._pairs.get(slug, {})
            if {"up", "down"} <= pair.keys():
                self.log.info(f"SANDBOX_MARKET_TRACKED slug={slug} instruments=2")
        return tracked

    def _maybe_scan_cached_btc_5m_instruments(self, *, now_ns: int) -> None:
        scan_seconds = float(self.config.dynamic_instrument_scan_seconds)
        if scan_seconds <= 0.0:
            return
        if now_ns <= 0:
            now_ns = self.clock.timestamp_ns()
        scan_ns = int(scan_seconds * _NANOSECONDS_PER_SECOND)
        if scan_ns > 0 and now_ns - self._last_instrument_scan_ns < scan_ns:
            return
        self._last_instrument_scan_ns = now_ns
        tracked = self._scan_cached_btc_5m_instruments()
        if tracked:
            self.log.info(f"SANDBOX_MARKET_SCAN tracked_instruments={tracked}")
        self._prune_expired_markets(now_ns=now_ns)

    def _slug_has_unsettled_position(self, slug: str) -> bool:
        return any(
            str(position.get("slug") or "") == slug and not bool(position.get("settled"))
            for position in self._settlement_positions.values()
        )

    def _prune_expired_markets(self, *, now_ns: int) -> None:
        retention_seconds = float(self.config.market_retention_seconds)
        if retention_seconds <= 0.0:
            return
        if now_ns <= 0:
            now_ns = self.clock.timestamp_ns()

        pruned_instruments = 0
        for slug, market_start in list(self._market_start_by_slug.items()):
            if slug in self._pruned_slugs:
                continue
            if now_ns < _market_prune_due_ns(
                market_start=market_start,
                post_end_retention_seconds=retention_seconds,
            ):
                continue
            if self._slug_has_unsettled_position(slug):
                continue
            pruned_instruments += self._prune_market(slug)

        if pruned_instruments:
            self.log.info(
                "SANDBOX_MARKET_PRUNE "
                f"pruned_instruments={pruned_instruments} "
                f"active_subscriptions={len(self._subscribed_instrument_ids)} "
                f"tracked_markets={len(self._pairs)}",
            )

    def _prune_market(self, slug: str) -> int:
        pair = self._pairs.pop(slug, {})
        self._market_start_by_slug.pop(slug, None)
        self._traded_slugs.discard(slug)
        self._evaluated_buckets = {
            evaluated for evaluated in self._evaluated_buckets if evaluated[0] != slug
        }
        self._logged_evaluation_events = {
            logged for logged in self._logged_evaluation_events if logged[0] != slug
        }
        self._pruned_slugs.add(slug)

        pruned = 0
        for instrument_id in tuple(pair.values()):
            if instrument_id in self._subscribed_instrument_ids:
                self.unsubscribe_order_book_deltas(instrument_id)
                self._subscribed_instrument_ids.discard(instrument_id)
            self._books.pop(instrument_id, None)
            self._book_ts_ns.pop(instrument_id, None)
            self._instruments.pop(instrument_id, None)
            self._slug_by_instrument.pop(instrument_id, None)
            self._outcome_by_instrument.pop(instrument_id, None)
            pruned += 1
        return pruned

    def _utc_day_key_from_ns(self, ts_ns: int) -> str:
        if ts_ns <= 0:
            ts_ns = self.clock.timestamp_ns()
        return datetime.fromtimestamp(ts_ns / _NANOSECONDS_PER_SECOND, tz=UTC).date().isoformat()

    def _settled_position_pnl(self, position: dict[str, Any]) -> Decimal:
        quantity = Decimal(str(position.get("quantity") or "0"))
        entry_price = Decimal(str(position.get("entry_price") or "0"))
        commission = Decimal(str(position.get("commission") or "0"))
        payout = Decimal(str(position.get("settlement_payout") or "0"))
        return payout - (quantity * entry_price) - commission

    def _settled_daily_pnl(self, *, day_key: str) -> Decimal:
        total = Decimal("0")
        for position in self._settlement_positions.values():
            if not bool(position.get("settled")):
                continue
            fill_ts_event = int(position.get("fill_ts_event") or 0)
            if self._utc_day_key_from_ns(fill_ts_event) != day_key:
                continue
            total += self._settled_position_pnl(position)
        return total

    def _daily_stop_status(self, *, now_ns: int) -> dict[str, object] | None:
        stop_loss = Decimal(str(self.config.daily_stop_loss))
        if stop_loss <= 0:
            return None
        day_key = self._utc_day_key_from_ns(now_ns)
        daily_pnl = self._settled_daily_pnl(day_key=day_key)
        if daily_pnl > -stop_loss:
            return None
        return {
            "daily_stop_day": day_key,
            "daily_stop_pnl": float(daily_pnl),
            "daily_stop_loss": float(stop_loss),
        }

    def on_start(self) -> None:
        self._model = _load_model(self.config.model_path)
        self._extra_spot_prefixes = _extra_spot_prefixes_from_columns(self._model.columns)
        if _has_spot_quote_columns(self._model.columns):
            self.log.error(
                "Spot quote model columns are not supported by the live sandbox runner. "
                "Use a non-quote model or add live quote subscriptions first.",
            )
            self.stop()
            return
        starts: list[int] = []
        for instrument_id in self.config.instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"Instrument {instrument_id} not found - stopping.")
                self.stop()
                return
            if not self._register_btc_5m_instrument(
                instrument_id=instrument_id,
                instrument=instrument,
                strict=True,
            ):
                self.stop()
                return
            starts.append(self._market_start_by_slug[self._slug_by_instrument[instrument_id]])
            self._subscribe_book_if_needed(instrument_id)

        incomplete = [slug for slug, pair in self._pairs.items() if {"up", "down"} - pair.keys()]
        if incomplete:
            self.log.error(f"Missing UP/DOWN pair legs for {len(incomplete)} BTC markets.")
            self.stop()
            return
        if self.config.btc_instrument_id is not None:
            self._btc = LiveBtcFeatureStore(
                buffer_seconds=int(self.config.live_btc_buffer_seconds),
                book_prefix="btc",
            )
            self.subscribe_trade_ticks(self.config.btc_instrument_id)
            self.subscribe_order_book_deltas(
                instrument_id=self.config.btc_instrument_id,
                book_type=BookType.L2_MBP,
            )
            for instrument_id in self.config.extra_spot_instrument_ids:
                if instrument_id == self.config.btc_instrument_id:
                    continue
                prefix = _spot_prefix_from_instrument_id(instrument_id)
                if prefix in self._spot_store_by_prefix:
                    continue
                self._spot_prefix_by_instrument[instrument_id] = prefix
                self._spot_store_by_prefix[prefix] = LiveBtcFeatureStore(
                    buffer_seconds=int(self.config.live_btc_buffer_seconds),
                    book_prefix=prefix,
                )
                self.subscribe_trade_ticks(instrument_id)
                self.subscribe_order_book_deltas(
                    instrument_id=instrument_id,
                    book_type=BookType.L2_MBP,
                )
            missing_spot_prefixes = [
                prefix
                for prefix in self._extra_spot_prefixes
                if prefix not in self._spot_store_by_prefix
            ]
            if missing_spot_prefixes:
                self.log.error(
                    "Model requires extra spot feature prefixes with no live instrument: "
                    f"{', '.join(missing_spot_prefixes)}",
                )
                self.stop()
                return
        else:
            self._btc = _load_btc_features(min(starts), max(starts) + _WINDOW_SECONDS)

    def on_instrument(self, instrument) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(instrument, "id", None)
        if not isinstance(instrument_id, InstrumentId):
            return
        already_tracked = instrument_id in self._slug_by_instrument
        if not self._register_btc_5m_instrument(
            instrument_id=instrument_id,
            instrument=instrument,
            strict=False,
        ):
            return
        if already_tracked:
            return
        self._subscribe_book_if_needed(instrument_id)
        slug = self._slug_by_instrument[instrument_id]
        pair = self._pairs.get(slug, {})
        if {"up", "down"} <= pair.keys():
            self.log.info(f"SANDBOX_MARKET_TRACKED slug={slug} instruments=2")

    def on_trade_tick(self, tick) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(tick, "instrument_id", None)
        if self.config.btc_instrument_id is None:
            return
        store: LiveBtcFeatureStore | None
        is_btc_tick = instrument_id == self.config.btc_instrument_id
        if is_btc_tick:
            store = self._btc if isinstance(self._btc, LiveBtcFeatureStore) else None
        else:
            prefix = self._spot_prefix_by_instrument.get(instrument_id)
            store = self._spot_store_by_prefix.get(prefix or "")
        if store is None:
            return
        price = _as_float(getattr(tick, "price", None))
        size = _as_float(getattr(tick, "size", None))
        if price is None:
            return
        store.record_trade(
            ts_ns=int(getattr(tick, "ts_event", 0) or 0),
            price=price,
            size=size or 0.0,
        )
        ts_event = int(getattr(tick, "ts_event", 0) or 0)
        if is_btc_tick:
            self._maybe_log_heartbeat(now_ns=ts_event, btc_price=price)
            self._maybe_scan_cached_btc_5m_instruments(now_ns=ts_event)
            self._maybe_poll_settlements(now_ns=ts_event)

    def on_order_book_deltas(self, deltas) -> None:  # type: ignore[no-untyped-def]
        instrument_id = getattr(deltas, "instrument_id", None)
        if instrument_id == self.config.btc_instrument_id:
            if self._btc_book is None:
                self._btc_book = OrderBook(instrument_id, book_type=BookType.L2_MBP)
            self._btc_book.apply_deltas(deltas)
            ts_event_ns = int(getattr(deltas, "ts_event", 0) or 0)
            self._btc_book_ts_ns = ts_event_ns
            if isinstance(self._btc, LiveBtcFeatureStore):
                features = _book_features(self._btc_book, levels=int(self.config.depth_levels))
                if features is not None:
                    self._btc.record_book(
                        ts_ns=ts_event_ns,
                        mid=features["mid"],
                        spread=features["spread"],
                        bid_size=features["bid_size"],
                        ask_size=features["ask_size"],
                        bid_depth=features["bid_depth"],
                        ask_depth=features["ask_depth"],
                        book_imbalance=features["book_imbalance"],
                        microprice=features["microprice"],
                    )
            return
        if instrument_id in self._spot_prefix_by_instrument:
            if instrument_id not in self._spot_book_by_instrument:
                self._spot_book_by_instrument[instrument_id] = OrderBook(
                    instrument_id,
                    book_type=BookType.L2_MBP,
                )
            spot_book = self._spot_book_by_instrument[instrument_id]
            spot_book.apply_deltas(deltas)
            features = _book_features(spot_book, levels=int(self.config.depth_levels))
            if features is not None:
                prefix = self._spot_prefix_by_instrument[instrument_id]
                store = self._spot_store_by_prefix.get(prefix)
                if store is not None:
                    store.record_book(
                        ts_ns=int(getattr(deltas, "ts_event", 0) or 0),
                        mid=features["mid"],
                        spread=features["spread"],
                        bid_size=features["bid_size"],
                        ask_size=features["ask_size"],
                        bid_depth=features["bid_depth"],
                        ask_depth=features["ask_depth"],
                        book_imbalance=features["book_imbalance"],
                        microprice=features["microprice"],
                    )
            return
        if instrument_id not in self._slug_by_instrument:
            return
        if instrument_id not in self._books:
            self._books[instrument_id] = OrderBook(instrument_id, book_type=BookType.L2_MBP)
        self._books[instrument_id].apply_deltas(deltas)
        ts_event_ns = int(getattr(deltas, "ts_event", 0) or 0)
        self._book_ts_ns[instrument_id] = ts_event_ns
        slug = self._slug_by_instrument[instrument_id]
        self._evaluate_market(slug=slug, now_ns=ts_event_ns)
        self._maybe_poll_settlements(now_ns=ts_event_ns)

    def _evaluate_market(self, *, slug: str, now_ns: int) -> None:
        if self._model is None or self._btc is None or slug in self._traded_slugs:
            return
        market_start = self._market_start_by_slug[slug]
        elapsed_seconds = (now_ns // _NANOSECONDS_PER_SECOND) - market_start
        if elapsed_seconds < 0 or elapsed_seconds >= _WINDOW_SECONDS:
            return
        seconds_left = _WINDOW_SECONDS - int(elapsed_seconds)
        due_buckets = [
            bucket
            for bucket in sorted(self.config.snapshot_seconds)
            if seconds_left <= bucket and (slug, bucket) not in self._evaluated_buckets
        ]
        if not due_buckets:
            return
        bucket = due_buckets[0]
        daily_stop_status = self._daily_stop_status(now_ns=now_ns)
        if daily_stop_status is not None:
            self._mark_evaluated(slug, due_buckets)
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": now_ns // _NANOSECONDS_PER_SECOND,
                    "seconds_left": bucket,
                    "skip_reason": "daily_stop_loss",
                    **daily_stop_status,
                }
            )
            return

        pair = self._pairs.get(slug, {})
        if {"up", "down"} - pair.keys():
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": now_ns // _NANOSECONDS_PER_SECOND,
                    "seconds_left": bucket,
                    "skip_reason": "missing_pair_instrument",
                }
            )
            return
        up_id = pair["up"]
        down_id = pair["down"]
        up_book = self._books.get(up_id)
        down_book = self._books.get(down_id)
        if up_book is None or down_book is None:
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": now_ns // _NANOSECONDS_PER_SECOND,
                    "seconds_left": bucket,
                    "skip_reason": "missing_pair_book",
                }
            )
            return
        max_age_ns = int(float(self.config.max_book_age_seconds) * _NANOSECONDS_PER_SECOND)
        up_age_ns = now_ns - self._book_ts_ns.get(up_id, 0)
        down_age_ns = now_ns - self._book_ts_ns.get(down_id, 0)
        if up_age_ns > max_age_ns:
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": now_ns // _NANOSECONDS_PER_SECOND,
                    "seconds_left": bucket,
                    "skip_reason": "stale_up_book",
                    "up_book_age_seconds": up_age_ns / _NANOSECONDS_PER_SECOND,
                }
            )
            return
        if down_age_ns > max_age_ns:
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": now_ns // _NANOSECONDS_PER_SECOND,
                    "seconds_left": bucket,
                    "skip_reason": "stale_down_book",
                    "down_book_age_seconds": down_age_ns / _NANOSECONDS_PER_SECOND,
                }
            )
            return

        up = _book_features(up_book, levels=int(self.config.depth_levels))
        down = _book_features(down_book, levels=int(self.config.depth_levels))
        if up is None or down is None:
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": now_ns // _NANOSECONDS_PER_SECOND,
                    "seconds_left": bucket,
                    "skip_reason": "invalid_book_features",
                }
            )
            return
        snapshot_ts = now_ns // _NANOSECONDS_PER_SECOND
        btc_feature_age_seconds = self._btc_feature_age(snapshot_ts)
        btc_start_age_seconds = self._btc_feature_age(market_start)
        max_btc_age_seconds = float(self.config.max_btc_feature_age_seconds)
        if max_btc_age_seconds > 0.0 and (
            not math.isfinite(btc_feature_age_seconds)
            or btc_feature_age_seconds > max_btc_age_seconds
            or not math.isfinite(btc_start_age_seconds)
            or btc_start_age_seconds > max_btc_age_seconds
        ):
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": snapshot_ts,
                    "seconds_left": bucket,
                    "skip_reason": "stale_btc_features",
                    "btc_feature_age_seconds": btc_feature_age_seconds,
                    "btc_start_age_seconds": btc_start_age_seconds,
                    "max_btc_feature_age_seconds": max_btc_age_seconds,
                }
            )
            return
        row = self._row(
            slug=slug,
            market_start=market_start,
            snapshot_ts=snapshot_ts,
            bucket=bucket,
            up=up,
            down=down,
            up_age_seconds=up_age_ns / _NANOSECONDS_PER_SECOND,
            down_age_seconds=down_age_ns / _NANOSECONDS_PER_SECOND,
            btc_feature_age_seconds=btc_feature_age_seconds,
            btc_start_age_seconds=btc_start_age_seconds,
        )
        if row is None:
            self._record_evaluation(
                {
                    "slug": slug,
                    "snapshot_ts": snapshot_ts,
                    "seconds_left": bucket,
                    "skip_reason": "missing_btc_features",
                }
            )
            return
        prob_up = float(_predict(self._model, [row])[0])
        yes_edge = prob_up - up["ask"]
        no_edge = (1.0 - prob_up) - down["ask"]
        if max(yes_edge, no_edge) < float(self.config.edge):
            self._mark_evaluated(slug, due_buckets)
            self._record_evaluation(
                {
                    **row,
                    "prob_up": prob_up,
                    "yes_edge": yes_edge,
                    "no_edge": no_edge,
                    "skip_reason": "edge_below_threshold",
                }
            )
            return
        if yes_edge >= no_edge:
            if not self._passes_momentum_alignment(row=row, selected_outcome="up"):
                self._mark_evaluated(slug, due_buckets)
                self._record_evaluation(
                    {
                        **row,
                        "prob_up": prob_up,
                        "yes_edge": yes_edge,
                        "no_edge": no_edge,
                        "selected_outcome": "up",
                        "skip_reason": "momentum_alignment",
                    }
                )
                return
            if not self._passes_quality_gates(
                row=row,
                selected_outcome="up",
                ask=up["ask"],
                selected_probability=prob_up,
            ):
                self._mark_evaluated(slug, due_buckets)
                self._record_evaluation(
                    {
                        **row,
                        "prob_up": prob_up,
                        "yes_edge": yes_edge,
                        "no_edge": no_edge,
                        "selected_outcome": "up",
                        "skip_reason": "quality_gate",
                    }
                )
                return
            self._mark_evaluated(slug, due_buckets)
            self._submit_model_entry(
                slug=slug,
                instrument_id=up_id,
                ask=up["ask"],
                ask_size=up["ask_size"],
                edge=yes_edge,
                prob_up=prob_up,
                selected_outcome="up",
                selected_probability=prob_up,
                row=row,
            )
        else:
            if not self._passes_momentum_alignment(row=row, selected_outcome="down"):
                self._mark_evaluated(slug, due_buckets)
                self._record_evaluation(
                    {
                        **row,
                        "prob_up": prob_up,
                        "yes_edge": yes_edge,
                        "no_edge": no_edge,
                        "selected_outcome": "down",
                        "skip_reason": "momentum_alignment",
                    }
                )
                return
            if not self._passes_quality_gates(
                row=row,
                selected_outcome="down",
                ask=down["ask"],
                selected_probability=1.0 - prob_up,
            ):
                self._mark_evaluated(slug, due_buckets)
                self._record_evaluation(
                    {
                        **row,
                        "prob_up": prob_up,
                        "yes_edge": yes_edge,
                        "no_edge": no_edge,
                        "selected_outcome": "down",
                        "skip_reason": "quality_gate",
                    }
                )
                return
            self._mark_evaluated(slug, due_buckets)
            self._submit_model_entry(
                slug=slug,
                instrument_id=down_id,
                ask=down["ask"],
                ask_size=down["ask_size"],
                edge=no_edge,
                prob_up=prob_up,
                selected_outcome="down",
                selected_probability=1.0 - prob_up,
                row=row,
            )

    def _row(
        self,
        *,
        slug: str,
        market_start: int,
        snapshot_ts: int,
        bucket: int,
        up: dict[str, float],
        down: dict[str, float],
        up_age_seconds: float,
        down_age_seconds: float,
        btc_feature_age_seconds: float,
        btc_start_age_seconds: float,
    ) -> dict[str, Any] | None:
        start_price = self._btc.price_at(market_start)
        current_price = self._btc.price_at(snapshot_ts)
        if not math.isfinite(start_price) or not math.isfinite(current_price):
            return None
        btc_book = self._btc_book_features(snapshot_ts) or {}
        btc_book_mid = float(btc_book.get("btc_book_mid", math.nan))
        row = {
            "slug": slug,
            "market_index": 0,
            "market_start_ts": market_start,
            "snapshot_ts": snapshot_ts,
            "seconds_left": bucket,
            "resolved_up": 0.0,
            "btc_price": current_price,
            "btc_start_price": start_price,
            "btc_feature_age_seconds": btc_feature_age_seconds,
            "btc_start_age_seconds": btc_start_age_seconds,
            "price_diff": current_price - start_price,
            "return_since_start": (current_price / start_price) - 1.0,
            "momentum_15s": self._btc.momentum(snapshot_ts, 15),
            "momentum_30s": self._btc.momentum(snapshot_ts, 30),
            "momentum_60s": self._btc.momentum(snapshot_ts, 60),
            "volatility_60s": self._btc.volatility(snapshot_ts, 60),
            "volume_60s": self._btc.volume(snapshot_ts, 60),
            "btc_book_mid": btc_book_mid,
            "btc_book_spread": btc_book.get("btc_book_spread", math.nan),
            "btc_book_spread_bps": btc_book.get("btc_book_spread_bps", math.nan),
            "btc_book_bid_size": btc_book.get("btc_book_bid_size", math.nan),
            "btc_book_ask_size": btc_book.get("btc_book_ask_size", math.nan),
            "btc_book_bid_depth": btc_book.get("btc_book_bid_depth", math.nan),
            "btc_book_ask_depth": btc_book.get("btc_book_ask_depth", math.nan),
            "btc_book_imbalance": btc_book.get("btc_book_imbalance", math.nan),
            "btc_book_microprice": btc_book.get("btc_book_microprice", math.nan),
            "btc_book_microprice_diff": btc_book.get("btc_book_microprice_diff", math.nan),
            "btc_trade_book_diff": current_price - btc_book_mid,
            "btc_book_age_seconds": btc_book.get("btc_book_age_seconds", math.nan),
            "yes_bid": up["bid"],
            "yes_ask": up["ask"],
            "yes_mid": up["mid"],
            "yes_spread": up["spread"],
            "yes_bid_size": up["bid_size"],
            "yes_ask_size": up["ask_size"],
            "yes_bid_depth": up["bid_depth"],
            "yes_ask_depth": up["ask_depth"],
            "yes_book_imbalance": up["book_imbalance"],
            "yes_microprice": up["microprice"],
            "yes_book_age_seconds": up_age_seconds,
            "no_bid": down["bid"],
            "no_ask": down["ask"],
            "no_mid": down["mid"],
            "no_spread": down["spread"],
            "no_bid_size": down["bid_size"],
            "no_ask_size": down["ask_size"],
            "no_bid_depth": down["bid_depth"],
            "no_ask_depth": down["ask_depth"],
            "no_book_imbalance": down["book_imbalance"],
            "no_microprice": down["microprice"],
            "no_book_age_seconds": down_age_seconds,
            "yes_no_ask_cost": up["ask"] + down["ask"],
        }
        for prefix in self._extra_spot_prefixes:
            store = self._spot_store_by_prefix.get(prefix)
            if store is None:
                return None
            spot_features = self._extra_spot_row_features(
                prefix=prefix,
                store=store,
                market_start=market_start,
                snapshot_ts=snapshot_ts,
            )
            if spot_features is None:
                return None
            row.update(spot_features)
        required_columns = self._model.columns if self._model is not None else _FEATURE_COLUMNS
        if not all(math.isfinite(float(row[column])) for column in required_columns):
            return None
        return row

    def _extra_spot_row_features(
        self,
        *,
        prefix: str,
        store: LiveBtcFeatureStore,
        market_start: int,
        snapshot_ts: int,
    ) -> dict[str, float] | None:
        start_price = store.price_at(market_start)
        current_price = store.price_at(snapshot_ts)
        if not math.isfinite(start_price) or not math.isfinite(current_price):
            return None
        book = store.book_features_at(snapshot_ts)
        if book is None:
            return None
        book_mid = float(book.get(f"{prefix}_book_mid", math.nan))
        if not math.isfinite(book_mid) or book_mid <= 0.0:
            return None
        volatility_60s = store.volatility(snapshot_ts, 60)
        return {
            f"{prefix}_return_since_start": (current_price / start_price) - 1.0,
            f"{prefix}_momentum_15s_bps": _bps_return(
                current_price,
                store.price_at(snapshot_ts - 15),
            ),
            f"{prefix}_momentum_30s_bps": _bps_return(
                current_price,
                store.price_at(snapshot_ts - 30),
            ),
            f"{prefix}_momentum_60s_bps": _bps_return(
                current_price,
                store.price_at(snapshot_ts - 60),
            ),
            f"{prefix}_volatility_60s_bps": (
                (volatility_60s / current_price) * 10_000.0
                if math.isfinite(volatility_60s) and current_price > 0.0
                else math.nan
            ),
            f"{prefix}_volume_60s": store.volume(snapshot_ts, 60),
            f"{prefix}_book_spread_bps": book[f"{prefix}_book_spread_bps"],
            f"{prefix}_book_bid_size": book[f"{prefix}_book_bid_size"],
            f"{prefix}_book_ask_size": book[f"{prefix}_book_ask_size"],
            f"{prefix}_book_bid_depth": book[f"{prefix}_book_bid_depth"],
            f"{prefix}_book_ask_depth": book[f"{prefix}_book_ask_depth"],
            f"{prefix}_book_imbalance": book[f"{prefix}_book_imbalance"],
            f"{prefix}_book_microprice_diff_bps": (
                float(book[f"{prefix}_book_microprice_diff"]) / book_mid
            )
            * 10_000.0,
            f"{prefix}_trade_book_diff_bps": ((current_price - book_mid) / book_mid) * 10_000.0,
            f"{prefix}_book_age_seconds": book[f"{prefix}_book_age_seconds"],
        }

    def _passes_momentum_alignment(
        self,
        *,
        row: dict[str, Any],
        selected_outcome: str,
    ) -> bool:
        mode = self.config.momentum_alignment.strip().casefold()
        if mode == "none":
            return True
        direction = 1.0 if selected_outcome == "up" else -1.0
        price_diff = direction * float(row["price_diff"])
        momentum_15s = direction * float(row["momentum_15s"])
        momentum_30s = direction * float(row["momentum_30s"])
        if mode == "m15_m30":
            return momentum_15s >= 0.0 and momentum_30s >= 0.0
        if mode == "pdiff_m15_m30":
            return price_diff > 0.0 and momentum_15s >= 0.0 and momentum_30s >= 0.0
        if mode == "reject_m15_m30_opposed":
            return not (momentum_15s < 0.0 and momentum_30s < 0.0)
        if mode == "reject_two_of_three_opposed":
            return sum(value < 0.0 for value in (price_diff, momentum_15s, momentum_30s)) <= 1
        if mode == "momentum_vote":
            votes = (
                (1 if price_diff > 0.0 else -1 if price_diff < 0.0 else 0)
                + (1 if momentum_15s > 0.0 else -1 if momentum_15s < 0.0 else 0)
                + (1 if momentum_30s > 0.0 else -1 if momentum_30s < 0.0 else 0)
            )
            return votes >= 2
        return True

    def _passes_quality_gates(
        self,
        *,
        row: dict[str, Any],
        selected_outcome: str,
        ask: float,
        selected_probability: float,
    ) -> bool:
        if ask < float(self.config.expensive_ask_floor):
            return self._passes_context_quality_gates(
                row=row,
                selected_outcome=selected_outcome,
                selected_probability=selected_probability,
            )
        min_selected_probability = float(self.config.expensive_min_selected_probability)
        if min_selected_probability > 0.0 and selected_probability < min_selected_probability:
            return False
        min_signed_momentum = float(self.config.expensive_min_signed_momentum_30s)
        if min_signed_momentum <= 0.0:
            return self._passes_context_quality_gates(
                row=row,
                selected_outcome=selected_outcome,
                selected_probability=selected_probability,
            )
        direction = 1.0 if selected_outcome == "up" else -1.0
        signed_momentum_30s = direction * float(row["momentum_30s"])
        if signed_momentum_30s < min_signed_momentum:
            return False
        return self._passes_context_quality_gates(
            row=row,
            selected_outcome=selected_outcome,
            selected_probability=selected_probability,
        )

    def _passes_context_quality_gates(
        self,
        *,
        row: dict[str, Any],
        selected_outcome: str,
        selected_probability: float,
    ) -> bool:
        direction = 1.0 if selected_outcome == "up" else -1.0
        signed_price_diff = direction * float(row["price_diff"])
        signed_momentum_30s = direction * float(row["momentum_30s"])
        signed_momentum_60s = direction * float(row["momentum_60s"])

        max_ask_cost = float(self.config.max_yes_no_ask_cost)
        if max_ask_cost > 0.0 and float(row["yes_no_ask_cost"]) > max_ask_cost:
            return False

        adverse_floor = float(self.config.adverse_price_diff_floor)
        if adverse_floor > 0.0 and signed_price_diff <= -adverse_floor:
            if signed_momentum_30s < float(self.config.adverse_min_signed_momentum_30s):
                return False

        exhausted_floor = float(self.config.exhausted_price_diff_floor)
        exhausted_min_probability = float(self.config.exhausted_min_selected_probability)
        if exhausted_floor > 0.0 and exhausted_min_probability > 0.0:
            if (
                signed_price_diff >= exhausted_floor
                and signed_momentum_60s < 0.0
                and selected_probability < exhausted_min_probability
            ):
                return False

        volatile_floor = float(self.config.volatile_price_diff_floor)
        volatile_min_probability = float(self.config.volatile_min_selected_probability)
        if volatile_floor > 0.0 and volatile_min_probability > 0.0:
            if (
                float(row["volatility_60s"]) >= volatile_floor
                and selected_probability < volatile_min_probability
            ):
                return False

        return True

    def _free_quote_balance(self, instrument_id: InstrumentId) -> Decimal | None:
        instrument = self._instruments.get(instrument_id)
        if instrument is None:
            return None
        account = self.portfolio.account(venue=instrument_id.venue)
        if account is None:
            return None
        free_balance = account.balance_free(instrument.quote_currency)
        if free_balance is None:
            return None
        return _decimal_or_none(free_balance.as_double())

    def _rounded_entry_quantity(
        self, *, instrument_id: InstrumentId, ask: float, ask_size: float
    ) -> object | None:
        instrument = self._instruments[instrument_id]
        desired = min(Decimal(str(self.config.trade_size)), Decimal(str(max(0.0, ask_size))))
        if desired <= 0 or ask_size < float(self.config.min_visible_size):
            return None
        free_balance = self._free_quote_balance(instrument_id)
        if free_balance is not None and ask > 0.0:
            desired = min(desired, (free_balance * _ENTRY_AFFORDABILITY_BUFFER) / Decimal(str(ask)))
        if desired <= 0:
            return None
        try:
            quantity = instrument.make_qty(float(desired), round_down=True)
        except ValueError:
            return None
        if quantity.as_double() <= 0.0:
            return None
        min_quantity = getattr(instrument, "min_quantity", None)
        if min_quantity is not None and quantity.as_double() + 1e-12 < min_quantity.as_double():
            return None
        lot_size = getattr(instrument, "lot_size", None)
        if lot_size is not None and quantity.as_double() + 1e-12 < lot_size.as_double():
            return None
        return quantity

    def _expected_entry_price(
        self, *, instrument_id: InstrumentId, quantity: object
    ) -> float | None:
        book = self._books.get(instrument_id)
        if book is None:
            return None
        avg_px = _as_float(book.get_avg_px_for_quantity(quantity, OrderSide.BUY))
        if avg_px is None or avg_px <= 0.0:
            return None
        return avg_px

    def _submit_model_entry(
        self,
        *,
        slug: str,
        instrument_id: InstrumentId,
        ask: float,
        ask_size: float,
        edge: float,
        prob_up: float,
        selected_outcome: str,
        selected_probability: float,
        row: dict[str, Any],
    ) -> None:
        def record_entry_skip(reason: str, **extra: object) -> None:
            yes_ask = float(row.get("yes_ask", 0.0))
            no_ask = float(row.get("no_ask", 0.0))
            self._record_evaluation(
                {
                    **row,
                    "prob_up": prob_up,
                    "yes_edge": prob_up - yes_ask,
                    "no_edge": (1.0 - prob_up) - no_ask,
                    "model_edge": edge,
                    "selected_outcome": selected_outcome,
                    "selected_ask": ask,
                    "selected_ask_size": ask_size,
                    "selected_probability": selected_probability,
                    "skip_reason": reason,
                    **extra,
                }
            )

        if ask < float(self.config.min_ask_price):
            record_entry_skip("ask_below_min")
            return
        if ask > float(self.config.max_ask_price):
            record_entry_skip("ask_above_max")
            return
        if ask_size < float(self.config.min_visible_size):
            record_entry_skip("visible_size_below_min")
            return
        if selected_probability < float(self.config.min_selected_probability):
            record_entry_skip("probability_below_min")
            return
        book = self._books.get(instrument_id)
        spread = _as_float(book.spread()) if book is not None else None
        if spread is None:
            record_entry_skip("spread_unavailable")
            return
        if spread > float(self.config.max_spread):
            record_entry_skip("spread_above_max", selected_spread=spread)
            return
        quantity = self._rounded_entry_quantity(
            instrument_id=instrument_id,
            ask=ask,
            ask_size=ask_size,
        )
        if quantity is None:
            record_entry_skip("entry_quantity_unavailable", selected_spread=spread)
            return
        expected_entry_price = self._expected_entry_price(
            instrument_id=instrument_id,
            quantity=quantity,
        )
        if expected_entry_price is not None and expected_entry_price - ask > float(
            self.config.max_expected_slippage
        ):
            record_entry_skip(
                "expected_slippage_above_max",
                selected_spread=spread,
                expected_entry_price=expected_entry_price,
                expected_slippage=expected_entry_price - ask,
            )
            return
        order_quantity = quantity
        order_quote_quantity = False
        submitted_base_quantity = _as_float(quantity)
        submitted_quote_amount = None
        if self.config.market_buy_quote_quantity:
            price_for_quote = expected_entry_price or ask
            quote_amount = Decimal(str(quantity.as_double())) * Decimal(str(price_for_quote))
            min_quote_amount = Decimal(str(self.config.min_market_buy_quote_amount))
            if quote_amount < min_quote_amount:
                record_entry_skip(
                    "quote_amount_below_min",
                    selected_spread=spread,
                    expected_entry_price=expected_entry_price,
                    submitted_quote_amount=float(quote_amount),
                )
                return
            free_balance = self._free_quote_balance(instrument_id)
            if free_balance is not None:
                quote_amount = min(quote_amount, free_balance * _ENTRY_AFFORDABILITY_BUFFER)
            if quote_amount < min_quote_amount:
                record_entry_skip(
                    "quote_amount_below_min_after_balance",
                    selected_spread=spread,
                    expected_entry_price=expected_entry_price,
                    submitted_quote_amount=float(quote_amount),
                )
                return
            instrument = self._instruments[instrument_id]
            try:
                order_quantity = instrument.make_qty(float(quote_amount), round_down=True)
            except ValueError:
                record_entry_skip(
                    "quote_quantity_invalid",
                    selected_spread=spread,
                    expected_entry_price=expected_entry_price,
                    submitted_quote_amount=float(quote_amount),
                )
                return
            if order_quantity.as_double() <= 0.0:
                record_entry_skip(
                    "quote_quantity_nonpositive",
                    selected_spread=spread,
                    expected_entry_price=expected_entry_price,
                    submitted_quote_amount=float(quote_amount),
                )
                return
            order_quote_quantity = True
            submitted_quote_amount = _as_float(order_quantity)
        tags = [
            format_order_intent_tag("btc_snapshot_model_entry"),
            f"model_edge={edge:.6f}",
            f"prob_up={prob_up:.6f}",
        ]
        visible_tag = format_visible_liquidity_tag(ask_size)
        if visible_tag is not None:
            tags.append(visible_tag)
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=order_quantity,
            time_in_force=TimeInForce.IOC,
            quote_quantity=order_quote_quantity,
            tags=tags,
        )
        client_order_id = str(getattr(order, "client_order_id", ""))
        self._record_evaluation(
            {
                **row,
                "prob_up": prob_up,
                "yes_edge": prob_up - float(row.get("yes_ask", 0.0)),
                "no_edge": (1.0 - prob_up) - float(row.get("no_ask", 0.0)),
                "model_edge": edge,
                "selected_outcome": selected_outcome,
                "selected_ask": ask,
                "selected_ask_size": ask_size,
                "selected_spread": spread,
                "selected_probability": selected_probability,
                "expected_entry_price": expected_entry_price,
                "submitted_base_quantity": submitted_base_quantity,
                "submitted_quantity": _as_float(order_quantity),
                "submitted_quote_amount": submitted_quote_amount,
                "quote_quantity": str(order_quote_quantity),
                "skip_reason": "",
            }
        )
        self._order_diagnostics[client_order_id] = {
            **{key: value for key, value in row.items() if isinstance(value, int | float | str)},
            "client_order_id": client_order_id,
            "instrument_id": str(instrument_id),
            "selected_outcome": selected_outcome,
            "selected_ask": ask,
            "selected_ask_size": ask_size,
            "selected_spread": spread,
            "selected_probability": selected_probability,
            "expected_entry_price": expected_entry_price,
            "model_edge": edge,
            "prob_up": prob_up,
            "submitted_base_quantity": submitted_base_quantity,
            "submitted_quantity": _as_float(order_quantity),
            "submitted_quote_amount": submitted_quote_amount,
            "quote_quantity": order_quote_quantity,
            "momentum_alignment": self.config.momentum_alignment,
        }
        self._traded_slugs.add(slug)
        self.submit_order(order)

    def on_order_filled(self, event) -> None:  # type: ignore[no-untyped-def]
        client_order_id = str(getattr(event, "client_order_id", ""))
        diagnostic = dict(self._order_diagnostics.get(client_order_id, {}))
        diagnostic.update(
            {
                "client_order_id": client_order_id,
                "fill_instrument_id": str(getattr(event, "instrument_id", "")),
                "fill_order_side": str(getattr(event, "order_side", "")),
                "fill_price": _as_float(getattr(event, "last_px", None)),
                "fill_quantity": _as_float(getattr(event, "last_qty", None)),
                "fill_commission": _as_float(getattr(event, "commission", None)),
                "fill_ts_event": _as_float(getattr(event, "ts_event", None)),
                "fill_ts_init": _as_float(getattr(event, "ts_init", None)),
            }
        )
        self._fill_diagnostics.append(diagnostic)
        try:
            self._record_settlement_position(event=event, diagnostic=diagnostic)
        except Exception as exc:
            self.log.warning(f"Unable to track sandbox settlement fill {client_order_id}: {exc}")

    def _record_settlement_position(self, *, event: Any, diagnostic: dict[str, Any]) -> None:
        order_side = getattr(event, "order_side", "")
        if not _is_buy_order_side(order_side):
            self.log.info(f"SANDBOX_FILL_IGNORED reason=non_buy side={order_side}")
            return
        instrument_id = getattr(event, "instrument_id", None)
        if instrument_id is None:
            self.log.warning("SANDBOX_FILL_IGNORED reason=missing_instrument_id")
            return
        fill_qty = _as_float(getattr(event, "last_qty", None))
        if fill_qty is None or fill_qty <= 0.0:
            self.log.warning(f"SANDBOX_FILL_IGNORED reason=bad_fill_qty value={fill_qty}")
            return
        try:
            condition_id, token_id = split_polymarket_instrument_id(instrument_id)
        except ValueError as exc:
            self.log.warning(f"Unable to parse settlement instrument {instrument_id}: {exc}")
            return
        fill_id = str(getattr(event, "trade_id", "") or getattr(event, "client_order_id", ""))
        if not fill_id:
            fill_id = f"{instrument_id}-{len(self._settlement_positions) + 1}"
        slug = self._slug_by_instrument.get(instrument_id, str(diagnostic.get("slug") or ""))
        self._settlement_positions[fill_id] = {
            "fill_id": fill_id,
            "client_order_id": str(getattr(event, "client_order_id", "")),
            "instrument_id": str(instrument_id),
            "condition_id": condition_id,
            "token_id": token_id,
            "slug": slug,
            "outcome": self._outcome_by_instrument.get(instrument_id, ""),
            "quantity": fill_qty,
            "entry_price": _as_float(getattr(event, "last_px", None)),
            "commission": _as_float(getattr(event, "commission", None)) or 0.0,
            "fill_ts_event": int(getattr(event, "ts_event", 0) or 0),
            "settled": False,
            "winner": None,
            "settlement_payout": 0.0,
            "settlement_ts_event": None,
        }
        self.log.info(
            "SANDBOX_FILL_TRACKED "
            f"fill_id={fill_id} slug={slug} outcome={self._outcome_by_instrument.get(instrument_id, '')} "
            f"qty={fill_qty} entry_price={_as_float(getattr(event, 'last_px', None))}",
        )
        self._write_settlement_ledger()
        self._log_portfolio_value(
            reason="fill",
            now_ns=int(getattr(event, "ts_event", 0) or 0),
        )

    def _maybe_poll_settlements(self, *, now_ns: int) -> None:
        if not self._settlement_positions or float(self.config.settlement_poll_seconds) <= 0.0:
            return
        if now_ns <= 0:
            now_ns = self.clock.timestamp_ns()
        poll_ns = int(float(self.config.settlement_poll_seconds) * _NANOSECONDS_PER_SECOND)
        if poll_ns > 0 and now_ns - self._last_settlement_poll_ns < poll_ns:
            return
        self._last_settlement_poll_ns = now_ns

        now_seconds = now_ns // _NANOSECONDS_PER_SECOND
        grace_seconds = float(self.config.settlement_grace_seconds)
        changed = False
        for position in self._settlement_positions.values():
            if bool(position.get("settled")):
                continue
            market_start = self._market_start_by_slug.get(str(position.get("slug") or ""))
            if (
                market_start is not None
                and now_seconds < market_start + _WINDOW_SECONDS + grace_seconds
            ):
                continue
            changed = self._try_settle_position(position=position, now_ns=now_ns) or changed
        if changed:
            self._write_settlement_ledger()
            self._prune_expired_markets(now_ns=now_ns)

    def _try_settle_position(self, *, position: dict[str, Any], now_ns: int) -> bool:
        condition_id = str(position.get("condition_id") or "")
        token_id = str(position.get("token_id") or "")
        if not condition_id or not token_id:
            return False
        try:
            settlement = fetch_clob_token_settlement(
                condition_id=condition_id,
                token_id=token_id,
                base_url=str(self.config.settlement_base_url),
                timeout_seconds=float(self.config.settlement_timeout_seconds),
            )
        except Exception as exc:
            self.log.warning(
                f"Settlement poll failed for {position.get('slug')} {token_id}: {exc}",
            )
            return False
        if settlement is None:
            return False

        quantity = Decimal(str(position.get("quantity") or "0"))
        payout = quantity if settlement.winner else Decimal("0")
        position.update(
            {
                "settled": True,
                "winner": settlement.winner,
                "settled_outcome": settlement.outcome,
                "settlement_price": None if settlement.price is None else float(settlement.price),
                "settlement_payout": float(payout),
                "settlement_ts_event": now_ns,
            }
        )
        self._close_nautilus_position_for_settlement(
            position=position,
            winner=settlement.winner,
            now_ns=now_ns,
        )
        self.log.info(
            "SANDBOX_SETTLEMENT "
            f"slug={position.get('slug')} outcome={position.get('outcome')} "
            f"winner={settlement.winner} qty={quantity} payout={payout}",
        )
        self._log_portfolio_value(reason="settlement", now_ns=now_ns)
        return True

    def _close_nautilus_position_for_settlement(
        self,
        *,
        position: dict[str, Any],
        winner: bool,
        now_ns: int,
    ) -> None:
        try:
            instrument_id = InstrumentId.from_str(str(position["instrument_id"]))
        except (KeyError, ValueError) as exc:
            position["nautilus_close_status"] = f"invalid_instrument:{exc}"
            return

        open_positions = self.cache.positions_open(
            venue=None,
            instrument_id=instrument_id,
            strategy_id=self.id,
        )
        if not open_positions:
            position["nautilus_close_status"] = "already_flat"
            return

        client_order_id = str(position.get("client_order_id") or "")
        matched_positions = [
            open_position
            for open_position in open_positions
            if client_order_id and str(open_position.opening_order_id) == client_order_id
        ]
        if not matched_positions:
            expected_qty = _as_float(position.get("quantity"))
            matched_positions = [
                open_position
                for open_position in open_positions
                if expected_qty is None
                or abs((_as_float(open_position.quantity) or 0.0) - expected_qty) < 1e-9
            ]
        if not matched_positions:
            position["nautilus_close_status"] = "no_matching_open_position"
            self.log.warning(
                "SANDBOX_NAUTILUS_SETTLEMENT_CLOSE_SKIPPED "
                f"reason=no_matching_open_position slug={position.get('slug')} "
                f"instrument_id={instrument_id}",
            )
            return

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            position["nautilus_close_status"] = "missing_instrument"
            self.log.warning(
                "SANDBOX_NAUTILUS_SETTLEMENT_CLOSE_SKIPPED "
                f"reason=missing_instrument slug={position.get('slug')} "
                f"instrument_id={instrument_id}",
            )
            return

        settlement_px = 1.0 if winner else 0.0
        suffix = str(position.get("fill_id") or position.get("token_id") or "settlement")[-18:]
        closed = 0
        for open_position in matched_positions:
            if open_position.is_closed:
                continue
            fill = OrderFilled(
                trader_id=self.trader_id,
                strategy_id=self.id,
                instrument_id=instrument_id,
                client_order_id=ClientOrderId(f"S-{suffix}"),
                venue_order_id=VenueOrderId(f"S-{suffix}"),
                account_id=open_position.account_id,
                trade_id=TradeId(f"S-{suffix}"),
                position_id=open_position.id,
                order_side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                last_qty=open_position.quantity,
                last_px=instrument.make_price(settlement_px),
                currency=pUSD,
                commission=Money(0, pUSD),
                liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                event_id=UUID4(),
                ts_event=now_ns,
                ts_init=self.clock.timestamp_ns(),
                reconciliation=True,
                info={
                    "source": "polymarket_binary_settlement",
                    "winner": winner,
                    "slug": str(position.get("slug") or ""),
                },
            )
            try:
                open_position.apply(fill)
                self.cache.update_position(open_position)
                closed += 1
            except Exception as exc:
                self.log.warning(
                    "SANDBOX_NAUTILUS_SETTLEMENT_CLOSE_FAILED "
                    f"slug={position.get('slug')} position_id={open_position.id} error={exc}",
                )

        position["nautilus_close_status"] = "closed" if closed else "not_closed"
        position["nautilus_closed_positions"] = closed
        if closed:
            self.log.info(
                "SANDBOX_NAUTILUS_SETTLEMENT_CLOSE "
                f"slug={position.get('slug')} instrument_id={instrument_id} "
                f"positions={closed} settlement_px={settlement_px}",
            )

    def _settlement_cash_balance(self) -> Decimal:
        for position in self._settlement_positions.values():
            try:
                instrument_id = InstrumentId.from_str(str(position["instrument_id"]))
            except (KeyError, ValueError):
                continue
            cash = self._free_quote_balance(instrument_id)
            if cash is not None:
                return cash
        for instrument_id in self._instruments:
            cash = self._free_quote_balance(instrument_id)
            if cash is not None:
                return cash
        return Decimal("0")

    def _settled_payout_value(self) -> Decimal:
        return sum(
            Decimal(str(position.get("settlement_payout") or "0"))
            for position in self._settlement_positions.values()
            if bool(position.get("settled"))
        )

    def _position_mark_value(self, position: dict[str, Any]) -> Decimal:
        if bool(position.get("settled")):
            return Decimal("0")
        quantity = Decimal(str(position.get("quantity") or "0"))
        if quantity <= 0:
            return Decimal("0")
        price: Decimal | None = None
        try:
            instrument_id = InstrumentId.from_str(str(position["instrument_id"]))
        except (KeyError, ValueError):
            instrument_id = None
        if instrument_id is not None:
            book = self._books.get(instrument_id)
            if book is not None:
                bid = _as_float(book.best_bid_price())
                if bid is not None and bid > 0.0:
                    price = Decimal(str(bid))
        if price is None:
            entry_price = _as_float(position.get("entry_price"))
            if entry_price is not None and entry_price > 0.0:
                price = Decimal(str(entry_price))
        if price is None:
            return Decimal("0")
        return quantity * price

    def _open_mark_value(self) -> Decimal:
        return sum(
            self._position_mark_value(position)
            for position in self._settlement_positions.values()
            if not bool(position.get("settled"))
        )

    def _portfolio_value_snapshot(self) -> dict[str, Decimal | int]:
        cash = self._settlement_cash_balance()
        settled_payout = self._settled_payout_value()
        open_mark = self._open_mark_value()
        return {
            "free_cash": cash,
            "settled_payout": settled_payout,
            "open_mark_value": open_mark,
            "synthetic_equity": cash + settled_payout + open_mark,
            "open_positions": sum(
                1
                for position in self._settlement_positions.values()
                if not bool(position.get("settled"))
            ),
            "settled_positions": sum(
                1
                for position in self._settlement_positions.values()
                if bool(position.get("settled"))
            ),
        }

    def _log_portfolio_value(self, *, reason: str, now_ns: int) -> None:
        snapshot = self._portfolio_value_snapshot()
        self.log.info(
            "SANDBOX_PORTFOLIO "
            f"reason={reason} ts_event={now_ns} "
            f"free_cash={snapshot['free_cash']} "
            f"open_mark_value={snapshot['open_mark_value']} "
            f"settled_payout={snapshot['settled_payout']} "
            f"synthetic_equity={snapshot['synthetic_equity']} "
            f"open_positions={snapshot['open_positions']} "
            f"settled_positions={snapshot['settled_positions']}",
        )

    def _write_settlement_ledger(self) -> None:
        if not self.config.settlement_path:
            return
        path = Path(self.config.settlement_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self._portfolio_value_snapshot()
        payload = {
            "summary": {
                "free_cash": str(snapshot["free_cash"]),
                "settled_payout": str(snapshot["settled_payout"]),
                "open_mark_value": str(snapshot["open_mark_value"]),
                "synthetic_equity": str(snapshot["synthetic_equity"]),
                "open_positions": snapshot["open_positions"],
                "settled_positions": snapshot["settled_positions"],
            },
            "positions": list(self._settlement_positions.values()),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))

    def _settled_instrument_ids(self) -> set[InstrumentId]:
        settled: set[InstrumentId] = set()
        for position in self._settlement_positions.values():
            if not bool(position.get("settled")):
                continue
            try:
                settled.add(InstrumentId.from_str(str(position["instrument_id"])))
            except (KeyError, ValueError):
                continue
        return settled

    def _unsettled_instrument_ids(self) -> set[InstrumentId]:
        unsettled: set[InstrumentId] = set()
        for position in self._settlement_positions.values():
            if bool(position.get("settled")):
                continue
            try:
                unsettled.add(InstrumentId.from_str(str(position["instrument_id"])))
            except (KeyError, ValueError):
                continue
        return unsettled

    def on_stop(self) -> None:
        self._maybe_poll_settlements(now_ns=self.clock.timestamp_ns())
        settled_instruments = self._settled_instrument_ids()
        unsettled_instruments = self._unsettled_instrument_ids()
        settled_instrument_values = {str(instrument_id) for instrument_id in settled_instruments}
        unsettled_instrument_values = {
            str(instrument_id) for instrument_id in unsettled_instruments
        }
        order_instrument_ids = {
            order.instrument_id
            for order in (
                self.cache.orders_open(strategy_id=self.id)
                + self.cache.orders_emulated(strategy_id=self.id)
                + self.cache.orders_inflight(strategy_id=self.id)
            )
        }
        for instrument_id in order_instrument_ids:
            instrument_id_value = str(instrument_id)
            settled = (
                instrument_id in settled_instruments
                or instrument_id_value in settled_instrument_values
            )
            unsettled = (
                instrument_id in unsettled_instruments
                or instrument_id_value in unsettled_instrument_values
            )
            if settled and not unsettled:
                self.log.info(
                    "SANDBOX_STOP_CANCEL_SKIPPED "
                    f"reason=settled_order_cache_artifact instrument_id={instrument_id}",
                )
                continue
            self.cancel_all_orders(instrument_id)
        open_positions = self.cache.positions_open(strategy_id=self.id)
        if open_positions:
            self.log.warning(
                "SANDBOX_STOP_OPEN_POSITIONS "
                f"open_positions={len(open_positions)} "
                "note=unresolved binary positions will remain as Nautilus residuals until settlement",
            )
        if self.config.diagnostics_path:
            path = Path(self.config.diagnostics_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "evaluations": self._evaluation_diagnostics,
                "orders": list(self._order_diagnostics.values()),
                "fills": self._fill_diagnostics,
                "settlements": list(self._settlement_positions.values()),
            }
            path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))

    def on_reset(self) -> None:
        self._books.clear()
        self._book_ts_ns.clear()
        self._instruments.clear()
        self._slug_by_instrument.clear()
        self._outcome_by_instrument.clear()
        self._pairs.clear()
        self._market_start_by_slug.clear()
        self._evaluated_buckets.clear()
        self._traded_slugs.clear()
        self._model = None
        self._btc = None
        self._btc_book = None
        self._btc_book_ts_ns = 0
        self._order_diagnostics.clear()
        self._fill_diagnostics.clear()
        self._evaluation_diagnostics.clear()
        self._settlement_positions.clear()
        self._last_settlement_poll_ns = 0
        self._last_instrument_scan_ns = 0
        self._subscribed_instrument_ids.clear()
        self._pruned_slugs.clear()
