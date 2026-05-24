from __future__ import annotations

import argparse
import os
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

if __package__ in {None, ""}:
    import importlib.util

    _HELPER_PATH = Path(__file__).resolve().parents[1] / "_script_helpers.py"
    _SPEC = importlib.util.spec_from_file_location("_script_helpers", _HELPER_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError(f"Unable to load script helper from {_HELPER_PATH}")
    _HELPER = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(_HELPER)
    ensure_repo_root = _HELPER.ensure_repo_root
else:
    from backtests._script_helpers import ensure_repo_root

ensure_repo_root(__file__)

DEFAULT_ROOT_BASE = Path.home() / ".cache/nautilus_trader/telonex-binance/raw/binance"
CHANNELS = ("trades", "quotes", "book_snapshot_25")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _dates(start: date, end: date) -> list[date]:
    values: list[date] = []
    cursor = start
    while cursor <= end:
        values.append(cursor)
        cursor += timedelta(days=1)
    return values


def _target_path(root: Path, channel: str, day: date) -> Path:
    return root / channel / f"{day.isoformat()}.parquet"


def _download_one(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    root: Path,
    market_id: str,
    channel: str,
    day: date,
    overwrite: bool,
    retries: int,
) -> str:
    target = _target_path(root, channel, day)
    if target.exists() and target.stat().st_size > 0 and not overwrite:
        return "skipped"

    url = (
        f"{base_url.rstrip('/')}/v1/downloads/binance/{channel}/{day.isoformat()}"
        f"?market_id={market_id}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "prediction-market-backtesting/telonex-binance-spot-download",
    }
    for attempt in range(retries + 1):
        try:
            response = client.get(url, headers=headers)
            if response.status_code == 404:
                return "missing"
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                sleep_seconds = float(retry_after) if retry_after else min(60.0, 2.0**attempt)
                time.sleep(sleep_seconds)
                continue
            response.raise_for_status()
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(".tmp")
            temp.write_bytes(response.content)
            temp.replace(target)
            return "downloaded"
        except httpx.HTTPError:
            if attempt >= retries:
                raise
            time.sleep(min(60.0, 2.0**attempt))
    return "failed"


def main() -> int:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(
        description="Download Telonex Binance spot trades, quotes, and book_snapshot_25 parquet days.",
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--market-ids",
        nargs="+",
        default=["btcusdt"],
        help="Binance market ids to download, for example btcusdt ethusdt solusdt xrpusdt.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Optional single-market root. Use only when downloading one market id.",
    )
    parser.add_argument("--root-base", type=Path, default=DEFAULT_ROOT_BASE)
    parser.add_argument("--base-url", default="https://api.telonex.io")
    parser.add_argument("--channels", nargs="+", choices=CHANNELS, default=list(CHANNELS))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()

    api_key = os.getenv("TELONEX_API_KEY")
    if not api_key:
        raise RuntimeError("TELONEX_API_KEY is required in .env or environment.")

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    if start > end:
        raise ValueError("--start-date must be <= --end-date")
    market_ids = tuple(market_id.strip().lower() for market_id in args.market_ids)
    if not market_ids or any(not market_id for market_id in market_ids):
        raise ValueError("--market-ids must not be empty")
    if args.root is not None and len(market_ids) != 1:
        raise ValueError("--root can only be used with exactly one --market-ids value")

    counts: dict[str, int] = {}
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120.0)) as client:
        for market_id in market_ids:
            root = args.root or (args.root_base / market_id)
            for day in _dates(start, end):
                for channel in args.channels:
                    status = _download_one(
                        client=client,
                        base_url=args.base_url,
                        api_key=api_key,
                        root=root,
                        market_id=market_id,
                        channel=channel,
                        day=day,
                        overwrite=args.overwrite,
                        retries=max(0, args.retries),
                    )
                    counts[status] = counts.get(status, 0) + 1
                    print(f"{market_id} {day.isoformat()} {channel} {status}", flush=True)
                    if args.sleep > 0:
                        time.sleep(args.sleep)

    print("summary " + " ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    return 1 if counts.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
