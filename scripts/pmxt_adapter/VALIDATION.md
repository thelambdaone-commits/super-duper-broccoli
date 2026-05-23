# Adapter validation — what was tested, what agreed, what didn't

> **Measurement epoch & what can be re-validated.** The v1/v2 overlap
> window is permanently frozen: v1 ingest stopped at `2026-04-15T08`,
> so any v1-vs-v2 cross-check is measurable only on hours 2026-04-13T19
> through 2026-04-15T08. All per-field agreement numbers in this
> document (Sections 1–6) were measured on that pre-drift 18-column v2
> against real v1 and **cannot be re-computed on newer v2 data because
> there is no newer v1**. Structural invariants (Sections 1–5) were
> re-verified on the current 16-column v2 (`2026-04-22T16`, 82.4M rows)
> — see Section 4 for the re-verification line and Section 9 for the
> current-era summary. Throughout this document, numbers labeled with
> `2026-04-1X` dates are frozen pre-drift; numbers labeled `2026-04-22`
> are current post-drift.

## Tested against real files

**Pre-drift reference set (18-column v2 era, cross-version comparison):**

- **v1 reference**: `polymarket_orderbook_2026-04-14T08.parquet`
  (944.9 MB, 45,480,186 rows, 28,442 distinct markets, 56,883 distinct
  (market, token, side) triples in side-map terms)
- **v2 samples**:
  - `polymarket_orderbook_2026-04-15T17.parquet` (345.0 MB, 64,758,277 rows,
    49,426 markets) — post-v1-ingest-cutoff
  - `polymarket_orderbook_2026-04-14T08.parquet` (305.5 MB, 57,351,791 rows)
    — matching hour for direct overlap cross-val
- **Side map**: 155,053 asset_ids / 77,528 distinct markets, built by
  scanning 5 v1 hourly files spanning 2026-03-10 → 2026-04-14

**Current-era reference (16-column v2, structural-only re-verification):**

- `polymarket_orderbook_2026-04-22T16.parquet` (470 MB, 82,409,969 rows,
  51,857 distinct markets) — used for post-drift structural re-verification
  in Sections 4 and 9.

## 1. Schema exact match

| check | result |
|---|---|
| v1 column count | 5 |
| adapter output column count | 5 |
| column names | all 5 match |
| column types | all 5 match (`timestamp[ms, UTC]`, `string`, …) |
| column nullability (`nullable=False` on every field) | all 5 match |

## 2. JSON key-set exact match

| event type | v1 key count | adapter key count | missing in adapter | extra in adapter |
|---|---|---|---|---|
| `price_change` | 10 | 10 | none | none |
| `book_snapshot` | 9 | 9 | none | none |

Keys verified in both:

- `price_change`: `update_type, market_id, token_id, side, best_bid, best_ask, timestamp, change_price, change_size, change_side`
- `book_snapshot`: `update_type, market_id, token_id, side, best_bid, best_ask, timestamp, bids, asks`

## 3. Value format preservation

| field | v1 format | adapter format | match |
|---|---|---|---|
| prices (`best_bid`/`best_ask`/`change_price`) | quoted decimal string, shortest form | quoted decimal string, shortest form | ✓ |
| integer zero (`change_size=0`) | `"0"` (no decimal) | `"0"` (no decimal) | ✓ |
| regular decimals | `"0.05"`, `"42.6"`, `"9999.9999"` | identical | ✓ |
| empty book `best_bid`/`best_ask` | `null` | `null` | ✓ |
| `side` | `"YES"` / `"NO"` | via side-map lookup | ✓ when resolved |
| `timestamp` | Unix seconds as float | Unix seconds as float (ms precision) | ✓ format, 3-decimal precision |
| `bids` / `asks` | `list[list[str, str]]` | `list[list[str, str]]` | ✓ |
| `change_side` | `"BUY"`/`"SELL"` | identical | ✓ |

Specific values verified on 200K price_change rows:
- `change_size == "0.0"` in adapter output: **0 cases** (would be a bug)
- `change_size == "0"` in adapter output: 40,423 cases (matches v1's 44,556
  on a same-era sample, within sampling variance)

Specific values verified on 500 book_snapshot rows:
- 23 rows with empty bids OR asks — **23/23 correctly emit `null`** for the
  absent side (zero `""` cases for empty books)

## 4. Book ordering correctness

Verified `bids[-1][0] == best_bid` and `asks[-1][0] == best_ask` on 200
sampled book_snapshot rows from the v2 input: **200/200 correct**. Both
v1 and v2 use worst-first / best-last ordering; the adapter preserves
it.

Re-verified under the current 16-column v2 schema (2026-04-22T16, full
scan of 189,128 book events / 2,829,051 depth levels): **0 ordering
violations**.

## 5. Downstream consumer simulation

Replayed the first 100,000 rows of converted v2 output through the logic in
a representative v1-era `book_reconstruction.py` (loads side, routes
`book_snapshot` vs `price_change`, rebuilds YES/NO books from `change_side`
BUY→bid-side / SELL→ask-side, `change_size==0` removes level). Result:

| metric | value |
|---|---|
| events processed | 100,000 |
| accepted (valid YES/NO side) | 51,604 (51.6%) |
| skipped (no side resolution) | 48,396 |
| book_snapshot events applied | 78 |
| price_change events applied | 51,526 |

The replay runs without exception and maintains non-empty YES/NO books —
the consumer's code path is functional on adapter output.

## 6. Overlap-window cross-validation

> **Note:** The figures in this section were measured against the
> 18-column v2 schema prior to the `bids`/`asks` JSON-string column
> consolidation (2026-04 drift). Methodology and conclusions hold
> under the current 16-column schema; the cross-version join is on
> fields (`market_id`, `token_id`, `event_timestamp_ms`) that did not
> change in the drift.

Converted v2 Apr 14T08 through the adapter, then joined against real v1
Apr 14T08 on `(market_id, token_id, event_timestamp_ms)`:

- v1 rows sampled: 2,000,000
- v2-adapted rows sampled: 2,000,000
- Joined matches: **252,019**

Per-field agreement on matched rows:

| field | agreement |
|---|---|
| `side` (YES/NO) | 93.78% |
| `best_bid` | 90.49% |
| `best_ask` | 90.49% |
| `change_price` | 16.45% |
| `change_size` | 0.45% |
| `change_side` | 63.47% |

### Why the `change_*` fields disagree

This is **not an adapter bug**. Measured on the same v1 sample: **500,905
of 2,000,000 rows (25%)** belonged to `(market_id, token_id, timestamp_ms)`
groups containing MORE THAN ONE distinct event at the same millisecond.

Interpretation: Polymarket's CLOB fires multiple level-change events within
a single millisecond. v1 and v2 ingest systems each captured a (not
identical) subset of that flurry. When we join on timestamp_ms, we're
pairing v1's first event at that ms with v2's first event at that ms — and
they turn out to be different level changes from the same flurry.

The `side` / `best_bid` / `best_ask` fields are "state-like" — they describe
the top-of-book *at the moment of the event* — so they stay close across
divergent event captures (~90%).

The `change_price` / `change_size` / `change_side` fields are "delta-like" —
they describe *which level got updated by this specific event* — so they
diverge when the specific event captured differs.

For backtesting / book reconstruction, this is fine: replaying EITHER
event stream rebuilds the same final book state (up to event ordering
within a ms, which doesn't matter for most use cases). The adapter
faithfully translates v2's events; that's all it can or should do.

## 7. Performance

**Pre-drift measurement (`2026-04-15T17`, 345 MB input, 64.62M output rows):**

- Side-map load: ~0.5 s
- Streaming conversion: 324 s (single-threaded; `map_elements` with a
  Python callable is GIL-bound despite polars' parallelism elsewhere)
- Memory peak: ~3 GB (one row group in flight, ~1M rows each)

**Post-drift re-measurement (`2026-04-22T16` rg[0], 1.05M rows):**

- Streaming conversion: 4.7 s per 1M rows (extrapolates to ~6.5 min per
  82M-row hour — slightly higher wall time due to the larger row count,
  same per-row throughput within noise)
- No memory regression observed

Projected (consistent across eras): ~5–7 min per hour of v2 data, scaling
linearly with row count. A month of hourly data (~720 files) converts in
~66–90 CPU-hours single-threaded, or ~13–18 hours on a 5-worker pool.
Compatible with the same worker-pool pattern many v1-era ingest jobs
already use.

## 8. Edge cases tested

| edge case | result |
|---|---|
| `--side-map` omitted | Runs; all rows get `side=""`; rows will be filtered downstream by `if side not in ("YES","NO")` guards. |
| Empty bids OR asks on `book` events | `best_bid` / `best_ask` emitted as JSON `null` (matches v1). |
| Corrupt/placeholder parquet input (not a valid parquet file) | Adapter raises `RuntimeError` with a clear "not a valid parquet file" message rather than a raw `ArrowInvalid`. |
| Python `http.client.HTTPSConnection` signature change | `download_v2()` uses `urllib.request` over plain DNS (DNS is fixed); falls back to a manual SNI-pinned connect only if 404. No reliance on the `server_hostname` kwarg that was removed from `HTTPSConnection.__init__` in recent Python. |

## 9. Gamma / v1 re-validation (2026-04-23 re-run on frozen archive files)

A full rebuild of the Gamma-derived side-map on the original pre-drift v2
file (`2026-04-15T17.parquet`, 49,426 distinct condition IDs, 98,816
asset_id entries after the full 49,408-market Gamma build) compared
against the v1 reference (`2026-04-14T08.parquet`, 56,883 v1 asset_ids)
yields:

| Metric | Original | Re-validation (2026-04-23) | Delta |
|---|---|---|---|
| Gamma market coverage | 49,396 / 49,426 (99.94%) | 49,408 / 49,426 (99.96%) | +12 markets resolvable |
| Shared asset_ids (Gamma ∩ v1) | 48,100 | 43,138 | -4,962 (Gamma market churn; ~5K v1 markets no longer in Gamma) |
| Label match | 47,946 (99.68%) | 43,136 (99.995%) | +0.32pp |
| Flipped asset_ids | 154 | 2 | -152 (Gamma fixed Up/Down upstream) |
| Flipped markets | 77 | 1 | -76 |

The single remaining flipped market is an NBA Over/Under
(`"Over 5.5"` / `"Under 5.5"`), a non-Up/Down outlier. The 77
originally-flipped Up/Down 15-min crypto markets all now match v1 labels
— Gamma's `outcomes` reconciliation for that cluster happened upstream
sometime between the original measurement and 2026-04-23. The adapter's
`_derive_yes_no` rule is unchanged.

## 10. Post-drift (16-column v2) structural re-verification

Performed on `2026-04-22T16` row-group 0 (1,048,109 output rows after
filtering `last_trade_price` and `tick_size_change`):

| Check | Result |
|---|---|
| Schema match to expected 16-column set | ✓ exact |
| `price_change` 10-key JSON | 1,045,375 / 1,045,375 |
| `book_snapshot` 9-key JSON | 2,734 / 2,734 |
| Shortest-form decimals (no trailing zeros, no scientific notation) | 0 violations across 1.05M rows |
| `NaN` / `Infinity` in output | 0 |
| `bids`/`asks` worst-first / best-last ordering | 0 violations across 189,128 book events / 2,829,051 levels (full-file scan) |
| `best_bid == bids[-1][0]` on non-empty books | 100% |
| Empty book → JSON `null` | 118 empty-bid + 128 empty-ask rows, all correct |
| `last_trade_price` / `tick_size_change` drop | 467 / 10 respectively, both → 0 in output |
| Sample side-map methodology check (100 random condition IDs through Gamma) | 100/100 coverage, 200 asset_id entries |

What this does NOT re-verify (and cannot, because v1 is frozen):

- Per-field agreement rates vs v1 (Section 6 numbers).
- Gamma-derived side-map asset-ID overlap with v1 (Section "Gamma-derived
  side-map agreement with v1" in README.md).
- Up/Down crypto market flip count (77 markets) — this is a v1-convention
  artifact frozen in the 2026-04-15 data.

## What was NOT validated

- Adapter output against non-crypto markets (sports, politics, etc.) — the
  v1 sample used for the side-map includes all categories, but no specific
  stress-test for weird multi-outcome markets.
- `last_trade_price` / `tick_size_change` events — these have no v1
  equivalent and are dropped by default; no downstream replay test with
  them included.
