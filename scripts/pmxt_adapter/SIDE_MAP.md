# The side-map

This document explains what the side-map is, why it's needed, how to build one, and how to extend it for markets that don't appear in the v1 archive.

## Why it exists

v1 stored the outcome token label (`YES` or `NO`) directly in its JSON payload. v2 drops that field and stores only the numeric `asset_id`. Recovering the label requires a lookup against the market's `(conditionId, outcomeIndex) → asset_id` mapping, because YES/NO is a property of the market, not of the event.

The adapter resolves this at conversion time using an optional `--side-map` file. When an `asset_id` is missing from the map, the adapter emits `side=""`; downstream consumers that filter on `side ∈ {"YES", "NO"}` will simply skip those rows.

## File format

The side-map is a plain JSON object keyed by `asset_id` (the numeric ERC-1155 token ID as a string):

```json
{
  "44554681108074793313893626424278471150091658237406724818592366780413111952248": {
    "market_id": "0x00000977017fa72fb6b1908ae694000d3b51f442c2552656b10bdbbfd16ff707",
    "side": "YES"
  },
  "114528627098181527180076013437205839368323282497361602702800503052375432480589": {
    "market_id": "0x281565cae359040475640be8bc20f4efe15245fe0251805fd338fb1a3e45ffae",
    "side": "NO"
  }
}
```

Each market contributes exactly two entries — one for the YES token and one for the NO token.

## Building from scratch using Polymarket's Gamma API (v2-only)

This is the primary path when no v1 files are available. Every market's YES/NO token IDs are authoritative in Polymarket's Gamma API, so any v2 file can seed a full side-map without touching the v1 archive.

### The pipeline

```bash
# Step 1 — enumerate distinct condition IDs in your v2 input.
python v2_to_v1_adapter.py extract-market-ids \
    --input v2_hour.parquet \
    --output condition_ids.txt

# Step 2 — fetch YES/NO tokens from Gamma for each condition ID.
python extend_side_map_gamma.py \
    --side-map side_map.json \
    --condition-ids condition_ids.txt
```

`extract-market-ids` accepts multiple files or glob patterns and writes distinct condition IDs one per line, sorted for reproducibility. On a typical v2 hour it completes in roughly 2 seconds. Observed market counts: 49,426 distinct markets on `2026-04-15T17` (pre-drift); 51,857 on `2026-04-22T16` (current) — the market universe grows slowly, ~5% in the week following the schema drift.

`extend_side_map_gamma.py` creates the file if it does not exist, or extends an existing file. It skips condition IDs whose markets are already covered (unless `--no-skip-known` is passed). The default rate limit is 100 ms between API batches; with the current 100-ID batch size and doubled open/closed requests per batch, throughput is ~30 markets/s, so a fresh 50K-market build takes ~25–30 minutes end-to-end (sample-verified `2026-04-22`). Tune with `--rate-limit` if needed.

### Endpoint details

The Gamma API responds at:

```
https://gamma-api.polymarket.com/markets?condition_ids=<condition_id>
https://gamma-api.polymarket.com/markets?slug=<market-slug>
```

Two response fields matter: `outcomes` (the human-readable labels) and `clobTokenIds` (the two token IDs). Both are JSON-encoded strings containing two-element arrays in the same order.

**Important — Gamma query parameter naming.** The extender uses `?condition_ids=` (plural, snake_case). The singular `conditionId` is silently ignored by Gamma: requests that use it return the default unfiltered market list, with no error. The extender guards against this by comparing the `conditionId` of the returned market to the one requested and skipping any mismatch.

### YES/NO derivation rule

v1's `side` label is not a simple function of `clobTokenIds` position alone. The adapter encodes the following empirical rule in `_derive_yes_no()` in `extend_side_map_gamma.py`:

- If `outcomes` is `["Yes", "No"]` (case-insensitive, either order): match the token to the named outcome — the token at the "Yes" index is YES, the token at the "No" index is NO.
- For any other outcome pair (spreads, totals, moneyline, team vs team, "Over"/"Under", "Up"/"Down", political parties, etc.): `YES = clobTokenIds[1]` and `NO = clobTokenIds[0]`. The positional assignment inverts relative to the Yes/No case.

### Historical limitation — "Up"/"Down" crypto markets (largely resolved upstream)

> **Measurement history.** Two measurement epochs exist for this comparison; both use the same v1 reference (`2026-04-14T08.parquet`, which is still available in the v1 archive).
>
> - **Original measurement** (when this repo was built): 48,100 shared asset_ids, **99.68% agreement**, 154 flipped asset_ids across **77 markets** — almost entirely `["Up","Down"]` crypto markets where v1's ingest-time convention varied by slug generation.
> - **Re-validation (2026-04-23)** against the same archive files: 43,138 shared asset_ids, **99.995% agreement**, **2 flipped asset_ids across 1 market** (an NBA Over/Under outlier, not an Up/Down crypto market). The 77 previously-flipped Up/Down markets all now match v1's labels — Gamma reconciled its `outcomes` encoding for that cluster upstream.

The original Up/Down ambiguity, preserved below for reference since older side-maps built before Gamma's reconciliation may still carry the 77 flipped labels:

- 15-minute markets (slug pattern `*-updown-15m-*`): v1 labels "Up" as YES.
- Hourly markets (slug pattern `*-up-or-down-*`): v1 labels "Down" as YES.

Neither a named-pair rule (Up → YES) nor the positional fallback (`tokens[1]` → YES) reproduces both conventions from Gamma's `outcomes` field alone. The adapter ships with the positional fallback. **Under current Gamma state, this fallback agrees with v1 on essentially all Up/Down markets** — the issue appears resolved without any adapter code change. If you are still using a side-map built before the reconciliation, rebuild it to pick up the fix.

If you need exact v1 parity on Up/Down markets, use the hybrid path: build from v1 first (which carries v1's labels directly), then extend with Gamma only for condition IDs that remain uncovered. v1 entries always take precedence over Gamma-derived entries because they carry v1's ingest-time label unchanged.

If you find a flipped market outside the Up/Down pattern, please file an issue with the condition ID so the rule can be refined.

## Building from v1 archive files (offline, faster if v1 is available)

When v1 Parquet files are already available, scanning them is faster and requires no network. Each v1 event carries `(market_id, token_id, side)` inside its JSON payload, so a distinct scan recovers the mapping for all markets that were active during the scanned window.

### Source

The v1 PMXT archive is available at Cloudflare R2 under the URL template:

```
https://r2.pmxt.dev/polymarket_orderbook_{YYYY-MM-DDTHH}.parquet
```

A browsable listing lives at [`https://archive.pmxt.dev/Polymarket/`](https://archive.pmxt.dev/Polymarket/). Hourly files are typically 300 MB – 1 GB each.

### Command

Download the v1 files you want to scan, then run:

```bash
python v2_to_v1_adapter.py build-side-map \
    --input /path/to/v1_files/*.parquet \
    --output side_map.json
```

The `--input` flag accepts glob patterns or an explicit list of paths. Each file is scanned independently; distinct `(asset_id, market_id, side)` triples are merged across all inputs. Running the command again with additional files extends the map cumulatively (existing entries are preserved; new ones are added).

### Minimal example end-to-end

```bash
# Download four v1 hours spanning a cross-month window for broad coverage.
mkdir -p v1_scan
for stamp in 2026-03-10T12 2026-03-25T00 2026-04-05T12 2026-04-10T00; do
  curl -sL --max-time 300 \
    "https://r2.pmxt.dev/polymarket_orderbook_${stamp}.parquet" \
    -o "v1_scan/${stamp}.parquet"
done

# Build the map.
python v2_to_v1_adapter.py build-side-map \
    --input v1_scan/*.parquet \
    --output side_map.json
```

The output is a standalone JSON file. No database, no schema, no external state.

### Expected coverage

> **Measurement epoch.** Coverage figures below are from the pre-drift 18-column v2 era. The v1-scan path has not been re-measured against post-drift (16-column) v2 — the `asset_id` column is unchanged by the drift, so methodology still applies, but the event-level hit rates will diverge over time because the side-map cannot grow past the v1 ingest cutoff (`2026-04-15T08`). Expect monotonically-decreasing hit rates the further a v2 hour is from that cutoff; use the Gamma path (or hybrid) for current data.

On a cross-month sample of five v1 hours (March 10 – April 14, 2026), the resulting map contained:

- 155,053 distinct `asset_id` entries
- 77,528 distinct `market_id` entries

Measured against real v2 files:

| v2 hour | Event-level hit rate | Notes |
|---|---|---|
| 2026-04-14T08 | ~78% | within v1 ingest window |
| 2026-04-15T17 | ~45% | ~9 hours after v1 cutoff |
| post-drift v2 hours (e.g. 2026-04-22) | expected <30% and falling | markets churn; use Gamma to bridge |

April 15 coverage is lower because roughly half the markets active in that hour came online after the v1 ingest cutoff. The Gamma API path above is the definitive source for those markets.

## Hybrid: combine both paths

For maximum coverage with minimum network calls, run the v1 scan first (offline, no rate limits), then use Gamma extension only for the condition IDs that remain uncovered. The two commands are idempotent and write to the same `side_map.json`.

### Discovering which condition IDs are missing after a v1 scan

```bash
python -c "
import json, polars as pl
known = set(json.load(open('side_map.json')).keys())
missing = (pl.scan_parquet('v2_hour.parquet')
           .filter(~pl.col('asset_id').is_in(list(known)))
           .select(pl.col('market').cast(pl.String))
           .unique()
           .collect(engine='streaming')['market']
           .to_list())
open('missing.txt','w').write('\n'.join(missing))
print(f'{len(missing)} condition IDs still missing → missing.txt')
"

python extend_side_map_gamma.py --side-map side_map.json --condition-ids missing.txt
```

Alternatively, use the `side_map_miss` count printed by `v2_to_v1_adapter.py convert` to gauge whether the extension step is worthwhile before running the discovery query.

## Extender reference

`extend_side_map_gamma.py` flags:

- `--side-map <path>` — the JSON file to create or extend. Required.
- `--condition-ids <file>` — text file with one condition ID per line. If omitted, reads from stdin.
- `--rate-limit <sec>` — seconds to sleep between Gamma API calls. Default `0.1`.
- `--timeout <sec>` — per-request timeout. Default `10`.
- `--no-skip-known` — re-fetch condition IDs whose markets are already in the map. Default is to skip them.

The script is idempotent: existing entries are preserved, new ones are added, already-covered condition IDs are skipped by default. On completion it prints a JSON summary with `requested`, `added`, `failed`, `skipped_known`, `total_entries`, and `distinct_markets`.

### Dependencies

`extend_side_map_gamma.py` imports only Python stdlib modules (`argparse`, `json`, `sys`, `time`, `urllib.request`, `urllib.error`, `pathlib`). No setup step — runs under any Python 3.11+ interpreter.

## Verifying coverage against a v2 file

The `convert` subcommand reports side-map hit statistics as part of its JSON output:

```json
{
  "rows_out": 64623259,
  "side_map_hit": 28832237,
  "side_map_miss": 35791022,
  "side_map_hit_pct": 44.62
}
```

A low hit rate means many events will emit `side=""` and be skipped by downstream YES/NO filters. Build a broader side-map (more v1 hours or Gamma extension) before relying on the converted output.

## External references

- **PMXT archive landing page** — [`https://archive.pmxt.dev/Polymarket/`](https://archive.pmxt.dev/Polymarket/)
- **v1 archive URL template** — `https://r2.pmxt.dev/polymarket_orderbook_{YYYY-MM-DDTHH}.parquet`
- **v2 archive URL template** — `https://r2v2.pmxt.dev/polymarket_orderbook_{YYYY-MM-DDTHH}.parquet`
- **Polymarket Gamma API** — `https://gamma-api.polymarket.com/markets` (supports `?slug=…` and `?condition_ids=…` (plural, snake_case); the singular `?conditionId=` is silently ignored by Gamma — see §"Endpoint details")
- **Polymarket developer docs** — [`https://docs.polymarket.com/`](https://docs.polymarket.com/)
