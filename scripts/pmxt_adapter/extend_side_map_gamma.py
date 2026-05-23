"""
Extend a side-map JSON file with entries fetched from Polymarket's Gamma API.

Use this when `build-side-map` (a subcommand of `v2_to_v1_adapter.py`) can't
cover markets that exist only in v2 — typically ephemeral markets created
after the v1 ingest cutoff. Gamma is the authoritative source for the
(conditionId → asset_ids) mapping.

This script is intentionally kept separate from the main adapter:

- It has no third-party dependencies (Python 3.11+ stdlib only), so it can
  run in minimal environments.
- It is a pure network-fetch utility; there is no parquet I/O involved.
- It operates on the same side-map JSON file that `build-side-map` produces,
  so the two tools compose cleanly.

Typical workflow:

    # 1) Identify condition IDs missing from an existing map. One way:
    python -c "
    import json, polars as pl
    m = set(json.load(open('side_map.json')).keys())
    cids = (pl.scan_parquet('v2_hour.parquet')
            .filter(~pl.col('asset_id').is_in(list(m)))
            .select(pl.col('market').cast(pl.String)).unique()
            .collect(engine='streaming')['market'].to_list())
    open('missing.txt','w').write('\\n'.join(cids))
    "

    # 2) Extend the map via Gamma.
    python extend_side_map_gamma.py \\
        --side-map side_map.json \\
        --condition-ids missing.txt

See SIDE_MAP.md for the full workflow and a discovery one-liner.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


GAMMA_URL = "https://gamma-api.polymarket.com/markets"
USER_AGENT = "pmxt-v2-adapter/side-map-extender-1.0"


DEFAULT_BATCH_SIZE = 100  # ~8 KB URL at 100 × 66-char condition IDs; Gamma rejects at ~200 with HTTP 414.


def _derive_yes_no(market: dict) -> dict | None:
    """Derive {"yes": str, "no": str} from one Gamma market object.

    v1's YES/NO convention, empirically characterized against 48,100 shared
    asset_ids vs v1 ground truth on the 2026-04-15T17 hour:
      - Outcomes = {"Yes", "No"} (case-insensitive): match by name.
          "Yes" token is YES, "No" token is NO. 100% agreement with v1.
      - Any other outcome pair: YES = clobTokenIds[1]; NO = clobTokenIds[0].
        Correct for spreads, totals, moneyline, team vs team, bare
        "Over"/"Under", and ~half of "Up"/"Down" crypto markets.

    Known limitation (~0.16% label error rate on this sample):
    v1's convention for "Up"/"Down" crypto markets was internally
    inconsistent — 15-minute markets labeled "Up" as YES, while hourly
    markets labeled "Down" as YES. This cannot be reproduced from Gamma's
    market metadata alone without slug-based discrimination; the slug
    pattern differs between generations ("btc-updown-15m-..." vs
    "bitcoin-up-or-down-april-15-11am-et"). The positional-inversion
    fallback chosen here matches the hourly convention, which gives a
    lower overall flip count than any single named-pair rule. Downstream
    consumers that require exact v1 labels should use the hybrid path
    (v1-scan + Gamma extension) — v1's own labels win wherever present.

    Returns None for malformed entries or markets without exactly 2 outcomes.
    """
    outcomes_raw = market.get("outcomes", "[]")
    tokens_raw = market.get("clobTokenIds", "[]")
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw
    except json.JSONDecodeError:
        return None
    if not (isinstance(outcomes, list) and isinstance(tokens, list)):
        return None
    if len(outcomes) != 2 or len(tokens) != 2:
        return None
    lowered = [str(o).strip().lower() for o in outcomes]
    if set(lowered) == {"yes", "no"}:
        return {"yes": str(tokens[lowered.index("yes")]),
                "no":  str(tokens[lowered.index("no")])}
    return {"yes": str(tokens[1]), "no": str(tokens[0])}


def _gamma_query(condition_ids: list[str], timeout: float, closed: bool) -> list[dict]:
    """Single Gamma /markets call scoped to open- or closed-only markets."""
    params = [f"condition_ids={c}" for c in condition_ids]
    params.append(f"limit={len(condition_ids)}")
    params.append(f"closed={'true' if closed else 'false'}")
    url = f"{GAMMA_URL}?{'&'.join(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        print(
            f"[batch-error] {len(condition_ids)} IDs (closed={closed}) "
            f"starting {condition_ids[0][:16]}…: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return []
    return payload if isinstance(payload, list) else []


def fetch_markets_batch(condition_ids: list[str], timeout: float) -> dict[str, dict]:
    """Fetch YES/NO tokens for a batch of condition IDs from Gamma.

    Gamma's `/markets` endpoint exposes an exclusive `closed` filter: the
    default response is open-only, `closed=true` returns closed-only, and
    there is no documented "both" value (combined modes return HTTP 422).
    To cover the full universe this function issues TWO requests per batch,
    one scoped to open markets and one to closed, and merges the results.
    This doubles API traffic but is necessary — closed markets carry roughly
    7× more events per market than open ones in recent hours (crypto 5m/15m
    markets resolve quickly and end up in the closed set).

    Uses Gamma's repeat-parameter form `?condition_ids=A&condition_ids=B&...`
    with an explicit `&limit=N` to override the default page size of 20.

    Returns a dict keyed by lowercased condition_id with `{"yes": str, "no": str}`
    values for markets Gamma actually returned. Condition IDs not present in
    either response (archived, missing, pre-CLOB-v2, etc.) are absent — callers
    must track them as misses.

    Safety notes:
    - The `condition_ids` param name is snake_case plural. Singular `conditionId`
      is silently ignored by Gamma and returns an unfiltered default page.
    - URL length must stay under Gamma's limit; with 66-char condition IDs
      the practical batch ceiling is ~100 (batches of 200 return HTTP 414).
    """
    if not condition_ids:
        return {}

    out: dict[str, dict] = {}
    for closed in (False, True):
        for market in _gamma_query(condition_ids, timeout=timeout, closed=closed):
            cid = str(market.get("conditionId", "")).lower()
            if not cid or cid in out:
                continue
            tokens = _derive_yes_no(market)
            if tokens is not None:
                out[cid] = tokens
    return out


def fetch_market(condition_id: str, timeout: float) -> dict | None:
    """Single-market convenience wrapper around `fetch_markets_batch`.

    Returns {"yes": str, "no": str} on success, or None on any failure.
    Retained as a stable entry point for callers that want to resolve one
    market at a time; internally delegates to the batched fetcher.
    """
    result = fetch_markets_batch([condition_id], timeout=timeout)
    return result.get(condition_id.lower())


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"existing side-map at {path} is not valid JSON: {e}")


def read_condition_ids(path: Path | None) -> list[str]:
    """Read condition IDs either from a file (one per line) or from stdin."""
    if path:
        text = path.read_text()
    else:
        text = sys.stdin.read()
    return [line.strip() for line in text.splitlines() if line.strip()]


def extend(
    side_map_path: Path,
    condition_ids: list[str],
    rate_limit_sec: float = 0.1,
    timeout: float = 15.0,
    skip_known: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    """Build or extend a side-map. Condition IDs are fetched from Gamma in
    batches; see `fetch_markets_batch` for batch semantics.

    Progress is printed to stderr every ~500 condition IDs processed; the
    side-map is flushed to disk every ~1000, so a crash or ^C never loses
    more than one checkpoint's worth of work.
    """
    mapping = load_existing(side_map_path)

    # Mark a market as "known" if at least one asset_id maps to it — skipping
    # these cheaply when re-running against a superset of condition IDs.
    known_markets = {entry["market_id"] for entry in mapping.values()}

    if skip_known:
        pending = [c for c in condition_ids if c not in known_markets]
        pre_skipped = len(condition_ids) - len(pending)
    else:
        pending = list(condition_ids)
        pre_skipped = 0

    stats = {
        "requested": 0,
        "skipped_known": pre_skipped,
        "added": 0,
        "failed": 0,
    }
    total = len(pending)
    start = time.time()
    last_progress = 0
    last_checkpoint = 0

    def _flush() -> None:
        side_map_path.parent.mkdir(parents=True, exist_ok=True)
        side_map_path.write_text(json.dumps(mapping))

    for batch_start in range(0, total, batch_size):
        batch = pending[batch_start:batch_start + batch_size]
        stats["requested"] += len(batch)
        returned = fetch_markets_batch(batch, timeout=timeout)
        for cid in batch:
            tokens = returned.get(cid.lower())
            if tokens is None:
                stats["failed"] += 1
                continue
            mapping[tokens["yes"]] = {"market_id": cid, "side": "YES"}
            mapping[tokens["no"]]  = {"market_id": cid, "side": "NO"}
            stats["added"] += 1

        time.sleep(rate_limit_sec)
        processed = min(batch_start + batch_size, total)

        if processed - last_progress >= 500 or processed == total:
            elapsed = time.time() - start
            rate = processed / elapsed if elapsed else 0.0
            eta = (total - processed) / rate if rate else 0.0
            print(
                f"[progress] {processed}/{total}  "
                f"added={stats['added']} failed={stats['failed']} "
                f"skipped_known={stats['skipped_known']}  "
                f"rate={rate:.1f}/s  eta={eta/60:.1f}m",
                file=sys.stderr, flush=True,
            )
            last_progress = processed

        if processed - last_checkpoint >= 1000:
            _flush()
            last_checkpoint = processed

    _flush()
    stats["total_entries"] = len(mapping)
    stats["distinct_markets"] = len({v["market_id"] for v in mapping.values()})
    return stats


def main():
    ap = argparse.ArgumentParser(
        description="Extend a side-map JSON file via Polymarket's Gamma API.",
    )
    ap.add_argument(
        "--side-map", required=True, type=Path,
        help="Path to side_map.json. Created if it doesn't exist; extended if it does.",
    )
    ap.add_argument(
        "--condition-ids", type=Path, default=None,
        help="Text file with one condition ID per line. "
             "If omitted, reads from stdin.",
    )
    ap.add_argument(
        "--rate-limit", type=float, default=0.1,
        help="Sleep this many seconds between Gamma API batches (default: 0.1).",
    )
    ap.add_argument(
        "--timeout", type=float, default=15.0,
        help="Per-request timeout in seconds (default: 15).",
    )
    ap.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Condition IDs per Gamma request (default: {DEFAULT_BATCH_SIZE}). "
             f"Gamma rejects batches that push the URL past ~16 KB (HTTP 414) — "
             f"keep this at or below 100 with standard 66-char condition IDs.",
    )
    ap.add_argument(
        "--no-skip-known", action="store_true",
        help="Re-fetch condition IDs whose markets are already in the map. "
             "Default is to skip them.",
    )
    args = ap.parse_args()

    cids = read_condition_ids(args.condition_ids)
    if not cids:
        print("no condition IDs supplied", file=sys.stderr)
        sys.exit(2)

    stats = extend(
        side_map_path=args.side_map,
        condition_ids=cids,
        rate_limit_sec=args.rate_limit,
        timeout=args.timeout,
        skip_known=not args.no_skip_known,
        batch_size=args.batch_size,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
