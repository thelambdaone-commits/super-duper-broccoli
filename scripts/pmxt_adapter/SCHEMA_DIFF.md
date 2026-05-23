# PMXT v1 vs v2 — schema diff

**Schema source of truth:** [archive.pmxt.dev/docs/v2-data-overview](https://archive.pmxt.dev/docs/v2-data-overview). This document is the adapter's internal mapping from that spec to the legacy v1 shape — if the spec drifts, this document (and the adapter) must be updated to match.

Derived from direct inspection of real files (pre-drift reference set, 18-column v2 era — used for v1-vs-v2 comparison, which is only possible within the `2026-04-13T19` → `2026-04-15T08` overlap window because v1 ingest stopped at the cutoff):
- v1 reference: `polymarket_orderbook_2026-04-14T08.parquet` (944.9 MB, 45,480,186 rows, 28,442 distinct markets)
- v2 reference: `polymarket_orderbook_2026-04-15T17.parquet` (345.0 MB, 64,758,277 rows, 49,426 distinct markets)

Current-era sample (16-column v2, used for post-drift structural validation only — no v1 counterpart to compare against):
- `polymarket_orderbook_2026-04-22T16.parquet` (470 MB, 82,409,969 rows, 51,857 distinct markets)

## Summary

v1 = 5 columns, data-blob-in-JSON style.
v2 = **16 typed columns** with pre-serialized JSON depth strings, per-event
fee rate, transaction hash, and two new event types.

> **Schema history.** An earlier generation of v2 carried 18 columns with four typed list columns
> for book depth (`bid_prices`, `bid_sizes`, `ask_prices`, `ask_sizes`). In a later revision those four
> were replaced by two JSON string columns (`bids`, `asks`) containing pre-serialized
> `[["price_str","size_str"], ...]` arrays in shortest-form decimal format. This document describes the
> current 16-column schema; the adapter supports only this form.

Byte-for-byte, v2 is still smaller than v1 per event because scalar fields
are typed decimals; book depth storage is approximately equivalent between
the two formats now that v2 uses JSON strings.

## Column-by-column

| v1 column | v1 type | v2 equivalent | v2 type | change |
|---|---|---|---|---|
| `timestamp_received` | `timestamp[ms, UTC]` | `timestamp_received` | `timestamp[ms, UTC]` | unchanged |
| `timestamp_created_at` | `timestamp[ms, UTC]` | `timestamp` | `timestamp[ms, UTC]` | renamed |
| `market_id` | `String` ("0x…") | `market` | `fixed_size_binary[66]` (ASCII "0x" + 64 hex) | renamed, retyped |
| `update_type` | `String` | `event_type` | `String` | renamed |
| `data` | `String` (JSON blob) | _deleted_ — exploded into columns below | — | breaking |
| — | — | `asset_id` | `String` | extracted from JSON |
| — | — | `bids` | `String` (JSON `[["price","size"], ...]`, worst-first/best-last) | NEW — replaces the four typed list columns |
| — | — | `asks` | `String` (JSON `[["price","size"], ...]`, worst-first/best-last) | NEW — replaces the four typed list columns |
| — | — | `price` | `decimal128(9, 4)` | NEW typed |
| — | — | `size` | `decimal128(18, 6)` | NEW typed |
| — | — | `side` | `String` (`BUY`/`SELL`/`""`) | NEW — note: v2's `side` = trade/change direction, NOT v1's YES/NO outcome |
| — | — | `best_bid` | `decimal128(9, 4)` | NEW typed NBBO |
| — | — | `best_ask` | `decimal128(9, 4)` | NEW typed NBBO |
| — | — | `fee_rate_bps` | `uint16` | NEW — per-event fee rate |
| — | — | `transaction_hash` | `String` | NEW — per-trade onchain ref |
| — | — | `old_tick_size` | `decimal128(9, 4)` | NEW — tick-size-change events |
| — | — | `new_tick_size` | `decimal128(9, 4)` | NEW — tick-size-change events |

## Event-type mapping

| v2 `event_type` | maps to v1 `update_type` | populated v2 columns |
|---|---|---|
| `price_change` | `price_change` | `price`, `size`, `side`, `best_bid`, `best_ask` |
| `book` | `book_snapshot` | `bids`, `asks` (JSON strings). **`best_bid`/`best_ask` columns are NULL on book events** — derive from `bids[-1][0]` / `asks[-1][0]` (worst-first/best-last ordering). |
| `last_trade_price` | _no v1 equivalent; dropped_ | `price`, `size`, `side`, `transaction_hash` |
| `tick_size_change` | _no v1 equivalent; dropped_ | `old_tick_size`, `new_tick_size` |

### Observed distribution on 2026-04-15T17 (64,758,277 events, pre-drift 18-column schema; event-type names are stable under the current 16-column schema)

| event_type | count | % |
|---|---|---|
| `price_change` | 64,558,762 | 99.692% |
| `last_trade_price` | 134,420 | 0.208% |
| `book` | 64,497 | 0.100% |
| `tick_size_change` | 598 | 0.001% |

### v1 Apr 14 equivalent, for reference (45,480,186 events)

| update_type | count | % |
|---|---|---|
| `price_change` | 45,192,782 | 99.368% |
| `book_snapshot` | 287,404 | 0.632% |

**`book_snapshot` rate is ~6× higher in v1 than in v2**, proportionally.
Probable cause: v1 emitted a full book snapshot periodically; v2 only emits
one on book-rebuild events. Reconstruction pipelines that relied on frequent
full snapshots may need to fall back to `price_change` replay more often
under v2.

## v1 JSON payload shapes (reconstructed by the adapter)

`price_change` (10 keys, values are strings except `timestamp`):

```json
{"update_type":"price_change",
 "market_id":"0x281565cae359040475640be8bc20f4efe15245fe0251805fd338fb1a3e45ffae",
 "token_id":"114528627098181527180076013437205839368323282497361602702800503052375432480589",
 "side":"NO",
 "best_bid":"0.043",
 "best_ask":"0.045",
 "timestamp":1776155953.6701021,
 "change_price":"0.047",
 "change_size":"42.6",
 "change_side":"SELL"}
```

`book_snapshot` (9 keys):

```json
{"update_type":"book_snapshot",
 "market_id":"0x282a1555d32dcaecce57e09b4f0549029fa876fe3147531178292957cc61dd0a",
 "token_id":"95758635281560609299150793682973642148624820841234459654531015628769746970425",
 "side":"YES",
 "best_bid":"0.05",
 "best_ask":"0.5",
 "timestamp":1776154972.2491374,
 "bids":[["0.01","2228.02"],["0.02","256.03"],["0.03","30"],["0.04","28.54"],["0.05","14.48"]],
 "asks":[["0.99","3763"],["0.98","59.68"],…,["0.5","…"]]}
```

Important format details (verified):

- Prices and sizes are **quoted decimal strings**, not numbers (`"0.043"`
  not `0.043`).
- Shortest round-trip float format — no trailing zeros (`"0.05"` not
  `"0.0500"`).
- `timestamp` is a Python float in Unix seconds with sub-second precision.
  v1 had up to microsecond precision; v2 carries milliseconds, so converted
  output loses 3 decimal places.
- `bids` and `asks` are arrays of 2-element string arrays (`[price, size]`).
  Ordered **worst-first, best-last**: `bids[-1][0]` is best_bid,
  `asks[-1][0]` is best_ask.
- `side` means YES or NO (the outcome token), not BUY or SELL (that's
  `change_side` in a `price_change` event).

## File size comparison (same hour, Apr 14T08 UTC)

| | v1 (raw R2) | v2 (raw R2) | v2→v1 adapted |
|---|---|---|---|
| 2026-04-14T08 | 944.9 MB | 305.5 MB | 2,051.8 MB |

v2 is ~3× smaller than v1 at the raw level (typed decimals vs JSON). Adapted
output balloons because it re-serializes as JSON strings, but this is fine —
the adapter exists to feed v1-shaped consumers, not to save disk space. If
disk is a concern, feed v2 directly into a new-style consumer.

## Other observed differences

- **Market coverage has expanded and continues growing.** v1 Apr 14T08 had
  28,442 distinct markets; v2 Apr 15T17 has 49,426 (+74%); v2 Apr 22T16
  has 51,857 (+4.9% week-over-week post-drift). Any whitelist/filter that
  ran against v1 needs re-application on v2.
- **v1 ingest stopped** between 2026-04-15T08 (last full 678 MB file) and
  2026-04-15T16 (214 B placeholder — schema-only, zero rows). v2 files exist
  from 2026-04-13T19 onward, providing a ~36-hour parallel-run overlap that
  is the **only window available for apples-to-apples cross-version
  validation** — all v1-vs-v2 agreement numbers in this repo are anchored
  there and cannot be re-measured on later hours.
- **CLOB v2 (Polymarket's on-chain exchange upgrade, 2026-04-07)** is the
  underlying driver. Event payloads from the new exchange have different
  shapes than the old one, which is why v1 ingest had to be replaced and the
  new event types (`last_trade_price`, `tick_size_change`) were introduced.
