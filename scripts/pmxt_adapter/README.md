# PMXT Adapter

This directory vendors the essential pieces of `pinglucid/pmxt_v2_adapter`
into the main repository so PMXT v2 archive conversion can be run locally
without maintaining a second project.

Included:

- `v2_to_v1_adapter.py`
- `extend_side_map_gamma.py`
- `SCHEMA_DIFF.md`
- `SIDE_MAP.md`
- `VALIDATION.md`

Purpose:

- Convert PMXT v2 hourly Parquet into the legacy v1 event schema.
- Build or extend the `asset_id -> {market_id, side}` side-map.
- Prepare historical orderbook archives for replay tooling.

Non-goals:

- This is not part of the live trading loop.
- This does not replace the repo's CLOB websocket ingestion.

Quick start:

```bash
python scripts/pmxt_adapter/v2_to_v1_adapter.py extract-market-ids \
  --input v2_hour.parquet \
  --output condition_ids.txt

python scripts/pmxt_adapter/extend_side_map_gamma.py \
  --side-map side_map.json \
  --condition-ids condition_ids.txt

python scripts/pmxt_adapter/v2_to_v1_adapter.py convert \
  --input v2_hour.parquet \
  --output v1_shape.parquet \
  --side-map side_map.json
```

