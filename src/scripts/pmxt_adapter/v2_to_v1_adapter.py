"""
PMXT v2 → v1 schema adapter.

Converts v2 hourly parquet files (16 typed columns) back into the exact v1
shape (5 columns with a JSON `data` blob) so existing v1-era pipelines ingest
v2 data without modification.

Supports an optional `--side-map` file to resolve v1's YES/NO `side` field
which v2 doesn't carry directly.

Usage:
    # Build a side map by scanning existing v1 files (needed once)
    python v2_to_v1_adapter.py build-side-map \
        --input /path/to/v1_files/*.parquet --output /tmp/side_map.json

    # Convert a local v2 file
    python v2_to_v1_adapter.py convert \
        --input /tmp/v2.parquet --output /tmp/v1_shape.parquet \
        --side-map /tmp/side_map.json

    # Download + convert one hour
    python v2_to_v1_adapter.py download-and-convert \
        --stamp 2026-04-15T17 --output /tmp/v1_shape.parquet \
        --side-map /tmp/side_map.json

Requirements: polars>=1.0, pyarrow>=15
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import socket
import ssl
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterable, Optional

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

V2_HOST = "r2v2.pmxt.dev"

EVENT_MAP = {"price_change": "price_change", "book": "book_snapshot"}

V1_SCHEMA = pa.schema([
    pa.field("timestamp_received",   pa.timestamp("ms", tz="UTC"), nullable=False),
    pa.field("timestamp_created_at", pa.timestamp("ms", tz="UTC"), nullable=False),
    pa.field("market_id",            pa.string(),                   nullable=False),
    pa.field("update_type",          pa.string(),                   nullable=False),
    pa.field("data",                 pa.string(),                   nullable=False),
])


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
#
# r2v2.pmxt.dev was temporarily pointing at a dead Vercel deployment; this
# was fixed upstream on 2026-04-18. The adapter now uses normal urllib.
# If DNS regresses again, fall back to a manual SNI-pinned connection
# (see the `_download_via_cloudflare_ip` function below).

def download_v2(stamp: str, out_path: Path, timeout_sec: int = 300) -> int:
    """Download v2 parquet for one hour stamp (e.g. '2026-04-15T17').

    Returns bytes downloaded. Raises RuntimeError on non-200 or read errors.
    """
    url = f"https://{V2_HOST}/polymarket_orderbook_{stamp}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "pmxt-v2-adapter/1.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {stamp}")
            total = 0
            with open(out_path, "wb") as f:
                while True:
                    chunk = resp.read(1 << 20)  # 1 MiB
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
        return total
    except urllib.error.HTTPError as e:
        # If DNS regresses to pointing at a non-CF deployment, try the IP override.
        if e.code == 404:
            print(
                f"[warn] 404 for {stamp}; attempting Cloudflare-IP override fallback",
                file=sys.stderr,
            )
            return _download_via_cloudflare_ip(stamp, out_path, timeout_sec)
        raise


def _download_via_cloudflare_ip(stamp: str, out_path: Path, timeout_sec: int) -> int:
    """Fallback: connect directly to a Cloudflare anycast IP with correct SNI+Host.

    Used only if the normal DNS path fails (e.g. a repeat of the April 2026
    DNS regression where r2v2.pmxt.dev pointed at an empty Vercel deploy).
    """
    cf_ip = "104.18.32.7"  # arbitrary Cloudflare anycast IP
    path = f"/polymarket_orderbook_{stamp}.parquet"
    raw = socket.create_connection((cf_ip, 443), timeout=timeout_sec)
    try:
        ctx = ssl.create_default_context()
        ssock = ctx.wrap_socket(raw, server_hostname=V2_HOST)
        try:
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {V2_HOST}\r\n"
                f"User-Agent: pmxt-v2-adapter/1.2\r\n"
                f"Connection: close\r\n\r\n"
            ).encode()
            ssock.sendall(req)

            # Read status line + headers
            header_buf = b""
            while b"\r\n\r\n" not in header_buf:
                chunk = ssock.recv(8192)
                if not chunk:
                    raise RuntimeError("connection closed before headers")
                header_buf += chunk
            head, _, body_start = header_buf.partition(b"\r\n\r\n")
            status_line = head.split(b"\r\n", 1)[0].decode(errors="replace")
            if " 200" not in status_line:
                raise RuntimeError(f"bad status: {status_line}")

            out_path.parent.mkdir(parents=True, exist_ok=True)
            total = len(body_start)
            with open(out_path, "wb") as f:
                f.write(body_start)
                while True:
                    chunk = ssock.recv(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
            return total
        finally:
            ssock.close()
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Side-map builder
# ---------------------------------------------------------------------------

def build_side_map(v1_paths: list[Path], out: Path) -> dict:
    """Extract distinct (asset_id → {market_id, side}) from v1 parquet files."""
    mapping: dict = {}
    for f in v1_paths:
        if not f.exists():
            print(f"[skip] missing: {f}", file=sys.stderr)
            continue
        t0 = time.time()
        df = (
            pl.scan_parquet(str(f))
            .select([
                pl.col("market_id"),
                pl.col("data").str.json_path_match("$.token_id").alias("token_id"),
                pl.col("data").str.json_path_match("$.side").alias("side"),
            ])
            .filter(
                pl.col("token_id").is_not_null()
                & pl.col("side").is_in(["YES", "NO"])
            )
            .unique()
            .collect(engine="streaming")
        )
        n0 = len(mapping)
        for row in df.iter_rows(named=True):
            aid = row["token_id"]
            if aid not in mapping:
                mapping[aid] = {"market_id": row["market_id"], "side": row["side"]}
        print(
            f"[scan] {f.name}: +{len(mapping)-n0:,} ({time.time()-t0:.1f}s) "
            f"total={len(mapping):,}",
            file=sys.stderr,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        json.dump(mapping, fh)
    return mapping


# ---------------------------------------------------------------------------
# Conversion — streaming row-group-by-row-group
# ---------------------------------------------------------------------------

def _fmt_num(x) -> Optional[str]:
    """Stringify a number the way v1 does: shortest decimal, no trailing zeros.

    Preferred input is a fixed-point decimal string (from polars
    `decimal128.cast(pl.String)`), which preserves full precision —
    `_fmt_num("999999999999.999999")` → `"999999999999.999999"` exactly,
    and `_fmt_num("0.000001")` → `"0.000001"` (no scientific notation).
    Also accepts int/float as a defensive fallback.

    Returns None for None / NaN / inf (caller emits JSON null) — matches
    v1's "unknown/unavailable" convention and keeps the output valid JSON.

    Matches real v1 output:
      "0"             / 0        → "0"
      "-0.0"          / -0.0     → "0"
      "0.050000"      / 0.05     → "0.05"
      "42.600000"     / 42.6     → "42.6"
      "9999.9999"     / 9999.9999 → "9999.9999"
      "0.000001"                  → "0.000001"
    """
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
    else:
        try:
            f = float(x)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):
            return None
        if f == 0:
            return "0"
        abs_f = abs(f)
        # Python's `str(float)` emits scientific notation for extreme
        # magnitudes. Force fixed-point so the shortest-form stripper
        # below produces a valid v1 decimal string.
        if abs_f < 1e-4 or abs_f >= 1e16:
            s = f"{f:.18f}"
        else:
            s = str(f)
    # Strip trailing zeros from the fractional part (and the decimal
    # point if nothing remains). Never strip digits from the fractional
    # itself — that would corrupt `"0.05"` into `"0.5"`.
    if "." in s:
        int_part, frac_part = s.split(".", 1)
        frac = frac_part.rstrip("0")
        if not frac:
            # "-0" from "-0.000" etc. → "0".
            return "0" if int_part in ("-0", "-", "") else int_part
        return f"{int_part}.{frac}"
    return "0" if s == "-0" else s


def convert_file(
    v2_path: Path,
    v1_out: Path,
    side_map_path: Optional[Path] = None,
    progress_every: int = 5,
) -> dict:
    """Convert a v2 parquet to v1 shape, streaming row-group-by-row-group.

    Uses polars' UDF (map_elements with a Python callable) inside each row
    group. GIL-bound, so effectively single-threaded, but memory is bounded
    to one row group at a time (~1M rows).
    """
    t0 = time.time()

    side_map: Optional[dict] = None
    if side_map_path and side_map_path.exists():
        with open(side_map_path) as fh:
            side_map = json.load(fh)
        print(f"[side_map] loaded {len(side_map):,} asset_ids", file=sys.stderr, flush=True)

    try:
        pf = pq.ParquetFile(str(v2_path))
    except pa.lib.ArrowInvalid as e:
        raise RuntimeError(
            f"not a valid parquet file: {v2_path} ({e}). "
            "This commonly indicates the v2 CDN returned a placeholder/error "
            "response rather than a parquet. Check file size and try again."
        ) from e
    v1_out.parent.mkdir(parents=True, exist_ok=True)

    total_hit = total_miss = total_rows = 0
    ut_total: dict = {}

    def _parse_levels(raw) -> list:
        """Defensively parse a v2 bids/asks JSON string. Malformed or
        non-list results degrade to an empty list so a single bad row
        does not abort the whole row group."""
        if not raw:
            return []
        try:
            v = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return v if isinstance(v, list) else []

    def _build_json(row) -> str:
        e = row["event_type"]
        aid = row["asset_id"]
        mid = row["market_id"]
        ts_ms = row["ts_ms"]
        ts = ts_ms / 1000.0 if ts_ms is not None else None
        side_info = side_map.get(aid) if side_map else None
        side = side_info["side"] if side_info else ""
        if e == "price_change":
            return json.dumps({
                "update_type":  "price_change",
                "market_id":    mid,
                "token_id":     aid,
                "side":         side,
                "best_bid":     _fmt_num(row["best_bid"]),
                "best_ask":     _fmt_num(row["best_ask"]),
                "timestamp":    ts,
                "change_price": _fmt_num(row["price"]),
                "change_size":  _fmt_num(row["size"]),
                "change_side":  row["side_v2"] or "",
            })
        if e == "book":
            # v2 stores bids/asks as pre-serialized JSON strings already in
            # v1 format: quoted shortest-form decimals, worst-first/best-last.
            # Parse defensively via _parse_levels — a single malformed row
            # must not kill the whole row group. Non-list results (null,
            # dict, number) coerce to empty book so bb/ba fall back to None.
            bids = _parse_levels(row["bids"])
            asks = _parse_levels(row["asks"])
            # best_bid/best_ask columns are null on v2 book events —
            # derive from the list tail (matches real v1).
            bb = bids[-1][0] if bids else None
            ba = asks[-1][0] if asks else None
            return json.dumps({
                "update_type": "book_snapshot",
                "market_id":   mid,
                "token_id":    aid,
                "side":        side,
                "best_bid":    bb,
                "best_ask":    ba,
                "timestamp":   ts,
                "bids":        bids,
                "asks":        asks,
            })
        return "{}"

    with pq.ParquetWriter(str(v1_out), V1_SCHEMA, compression="snappy") as writer:
        for rg_idx in range(pf.num_row_groups):
            t_rg = time.time()
            table = pf.read_row_group(rg_idx)
            if table.num_rows == 0:
                continue

            # Convert pyarrow Table → polars (cheap), transform, convert back
            df = pl.from_arrow(table).filter(
                pl.col("event_type").is_in(list(EVENT_MAP.keys()))
            )
            if len(df) == 0:
                continue

            df = df.with_columns([
                # Cast decimals to strings (not Float64) to preserve full
                # d128(18,6) precision. Float64 silently rounds values
                # above ~1e15 and emits scientific notation for values
                # below 1e-4 — both corrupt v1's shortest-decimal format.
                # _fmt_num handles decimal strings directly.
                pl.col("price").cast(pl.String),
                pl.col("size").cast(pl.String),
                pl.col("best_bid").cast(pl.String),
                pl.col("best_ask").cast(pl.String),
                pl.col("market").cast(pl.String).alias("market_id"),
                pl.col("timestamp").dt.epoch("ms").alias("ts_ms"),
                pl.col("side").alias("side_v2"),
            ])

            # Build `data` JSON via polars' parallel UDF
            df = df.with_columns(
                pl.struct([
                    "event_type", "asset_id", "market_id", "ts_ms",
                    "best_bid", "best_ask", "price", "size", "side_v2",
                    "bids", "asks",
                ])
                .map_elements(_build_json, return_dtype=pl.String)
                .alias("data")
            )

            # Map event_type → update_type (cheap expression, no UDF needed)
            df = df.with_columns(
                pl.when(pl.col("event_type") == "price_change")
                .then(pl.lit("price_change"))
                .otherwise(pl.lit("book_snapshot"))
                .alias("update_type")
            )

            v1_df = df.select([
                "timestamp_received",
                pl.col("timestamp").alias("timestamp_created_at"),
                "market_id",
                "update_type",
                "data",
            ])

            # Write this row group to output
            out_table = v1_df.to_arrow().cast(V1_SCHEMA)
            writer.write_table(out_table)

            # Count side map hits
            if side_map is not None:
                aids = df.get_column("asset_id").to_list()
                hits = sum(1 for a in aids if a in side_map)
                total_hit += hits
                total_miss += (len(aids) - hits)

            # Count update_types
            for ut, cnt in df.group_by("update_type").len().iter_rows():
                ut_total[ut] = ut_total.get(ut, 0) + cnt
            total_rows += len(v1_df)

            if rg_idx % progress_every == 0 or rg_idx == pf.num_row_groups - 1:
                print(
                    f"[rg {rg_idx+1}/{pf.num_row_groups}] "
                    f"rows={len(v1_df):,} ({time.time()-t_rg:.1f}s) "
                    f"cum={total_rows:,}",
                    file=sys.stderr, flush=True,
                )

    v1_size = v1_out.stat().st_size
    v2_size = v2_path.stat().st_size
    stats = {
        "v2_file": str(v2_path),
        "v1_file": str(v1_out),
        "v2_MB":   round(v2_size / 1e6, 1),
        "v1_MB":   round(v1_size / 1e6, 1),
        "rows_out": total_rows,
        "update_type_counts": ut_total,
        "seconds": round(time.time() - t0, 1),
    }
    if side_map is not None:
        stats["side_map_hit"]     = total_hit
        stats["side_map_miss"]    = total_miss
        stats["side_map_hit_pct"] = round(100 * total_hit / max(total_rows, 1), 2)
    return stats


def extract_market_ids(v2_paths: list[Path], out: Path) -> dict:
    """Write distinct condition IDs (v2 `market` column) from one or more v2
    parquet files to `out`, one per line.

    This is the bootstrap step for building a side-map from scratch when no
    v1 files are available: pipe the output into `extend_side_map_gamma.py`
    to fetch YES/NO tokens from Polymarket's Gamma API.
    """
    seen: set[str] = set()
    total_rows = 0
    for f in v2_paths:
        if not f.exists():
            print(f"[skip] missing: {f}", file=sys.stderr)
            continue
        t0 = time.time()
        df = (
            pl.scan_parquet(str(f))
            .select(pl.col("market").cast(pl.String).alias("market_id"))
            .unique()
            .collect(engine="streaming")
        )
        n_before = len(seen)
        for cid in df["market_id"].to_list():
            seen.add(cid)
        total_rows += len(df)
        print(
            f"[scan] {f.name}: +{len(seen) - n_before:,} new "
            f"({time.time() - t0:.1f}s) total={len(seen):,}",
            file=sys.stderr,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for cid in sorted(seen):
            fh.write(f"{cid}\n")
    return {
        "distinct_markets": len(seen),
        "files_scanned": len(v2_paths),
        "output": str(out),
    }


def batch_convert(
    in_dir: Path,
    out_dir: Path,
    side_map_path: Optional[Path] = None,
) -> Iterable[dict]:
    files = sorted(in_dir.glob("polymarket_orderbook_*.parquet"))
    for f in files:
        out_file = out_dir / f.name
        if out_file.exists():
            print(f"[skip] {f.name} already converted", file=sys.stderr)
            continue
        try:
            stats = convert_file(f, out_file, side_map_path=side_map_path)
            print(json.dumps(stats), file=sys.stdout, flush=True)
            yield stats
        except Exception as e:
            print(f"[error] {f.name}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="PMXT v2 → v1 schema adapter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_conv = sub.add_parser("convert")
    p_conv.add_argument("--input",    required=True, type=Path)
    p_conv.add_argument("--output",   required=True, type=Path)
    p_conv.add_argument("--side-map", type=Path, default=None)

    p_dl = sub.add_parser("download")
    p_dl.add_argument("--stamp",  required=True)
    p_dl.add_argument("--output", required=True, type=Path)

    p_dlc = sub.add_parser("download-and-convert")
    p_dlc.add_argument("--stamp",    required=True)
    p_dlc.add_argument("--output",   required=True, type=Path)
    p_dlc.add_argument("--side-map", type=Path, default=None)
    p_dlc.add_argument("--keep-raw", action="store_true")

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--input-dir",  required=True, type=Path)
    p_batch.add_argument("--output-dir", required=True, type=Path)
    p_batch.add_argument("--side-map",   type=Path, default=None)

    p_sm = sub.add_parser("build-side-map")
    p_sm.add_argument("--input",  required=True, nargs="+", type=Path,
                      help="v1 parquet files or glob patterns")
    p_sm.add_argument("--output", required=True, type=Path)

    p_em = sub.add_parser(
        "extract-market-ids",
        help="List distinct condition IDs from a v2 parquet, one per line. "
             "Bootstrap step for building a side-map from Gamma when no v1 "
             "files are available.",
    )
    p_em.add_argument("--input",  required=True, nargs="+", type=Path,
                      help="v2 parquet files or glob patterns")
    p_em.add_argument("--output", required=True, type=Path,
                      help="Text file to write (one condition ID per line)")

    args = ap.parse_args()

    if args.cmd == "convert":
        print(json.dumps(
            convert_file(args.input, args.output, side_map_path=args.side_map),
            indent=2,
        ))
    elif args.cmd == "download":
        n = download_v2(args.stamp, args.output)
        print(json.dumps({"stamp": args.stamp, "bytes": n,
                          "path": str(args.output)}))
    elif args.cmd == "download-and-convert":
        raw = args.output.with_suffix(".v2raw.parquet")
        n = download_v2(args.stamp, raw)
        if n < 10_000:
            print(f"[warn] {args.stamp} is only {n} bytes — likely placeholder",
                  file=sys.stderr)
        stats = convert_file(raw, args.output, side_map_path=args.side_map)
        stats["download_bytes"] = n
        print(json.dumps(stats, indent=2))
        if not args.keep_raw:
            raw.unlink(missing_ok=True)
    elif args.cmd == "batch":
        for _ in batch_convert(args.input_dir, args.output_dir,
                               side_map_path=args.side_map):
            pass
    elif args.cmd == "build-side-map":
        paths: list[Path] = []
        for p in args.input:
            s = str(p)
            if any(c in s for c in "*?["):
                paths.extend(Path(x) for x in glob.glob(s))
            else:
                paths.append(p)
        m = build_side_map(paths, args.output)
        print(json.dumps({
            "asset_ids": len(m),
            "distinct_markets": len({v["market_id"] for v in m.values()}),
            "output": str(args.output),
        }, indent=2))
    elif args.cmd == "extract-market-ids":
        paths = []
        for p in args.input:
            s = str(p)
            if any(c in s for c in "*?["):
                paths.extend(Path(x) for x in glob.glob(s))
            else:
                paths.append(p)
        stats = extract_market_ids(paths, args.output)
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
