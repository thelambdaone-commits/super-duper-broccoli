from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
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

from prediction_market_extensions._native import telonex_api_cache_relative_path  # noqa: E402

WINDOW_SECONDS = 300
OUTCOMES = ("Up", "Down")
CHANNEL = "book_snapshot_full"
DEFAULT_CACHE_ROOT = Path.home() / ".cache/nautilus_trader/telonex"


@dataclass(frozen=True)
class Job:
    slug: str
    day: date
    outcome: str
    token_index: int


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _floor_5m(ts: int) -> int:
    return ts - (ts % WINDOW_SECONDS)


def _jobs(start: date, end: date) -> list[Job]:
    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    start_ts = _floor_5m(int(start_dt.timestamp()))
    end_ts = _floor_5m(int(end_dt.timestamp()))
    jobs: list[Job] = []
    for market_start in range(start_ts, end_ts, WINDOW_SECONDS):
        day = datetime.fromtimestamp(market_start, UTC).date()
        slug = f"btc-updown-5m-{market_start}"
        for token_index, outcome in enumerate(OUTCOMES):
            jobs.append(Job(slug=slug, day=day, outcome=outcome, token_index=token_index))
    return jobs


def _cache_path(*, cache_root: Path, base_url: str, job: Job) -> Path:
    base_url_key = sha256(base_url.rstrip("/").encode("utf-8")).hexdigest()[:16]
    return cache_root / telonex_api_cache_relative_path(
        base_url_key=base_url_key,
        channel=CHANNEL,
        date=job.day.isoformat(),
        market_slug=job.slug,
        token_index=job.token_index,
        outcome=job.outcome,
    )


def _url(*, base_url: str, job: Job) -> str:
    return (
        f"{base_url.rstrip('/')}/v1/downloads/polymarket/{CHANNEL}/{job.day.isoformat()}"
        f"?slug={job.slug}&outcome={job.outcome}"
    )


async def _download_one(
    *,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    api_key: str,
    base_url: str,
    cache_root: Path,
    job: Job,
    overwrite: bool,
    retries: int,
) -> str:
    target = _cache_path(cache_root=cache_root, base_url=base_url, job=job)
    if target.exists() and target.stat().st_size > 0 and not overwrite:
        return "skipped"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "prediction-market-backtesting/telonex-btc-5m-polymarket-download",
    }
    url = _url(base_url=base_url, job=job)
    async with sem:
        for attempt in range(retries + 1):
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 404:
                    return "missing"
                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    sleep_seconds = float(retry_after) if retry_after else min(60.0, 2.0**attempt)
                    await asyncio.sleep(sleep_seconds)
                    continue
                response.raise_for_status()
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(".tmp")
                temp.write_bytes(response.content)
                temp.replace(target)
                return "downloaded"
            except httpx.HTTPError:
                if attempt >= retries:
                    return "failed"
                await asyncio.sleep(min(60.0, 2.0**attempt))
    return "failed"


async def _run_async(args: argparse.Namespace) -> int:
    load_dotenv(Path(".env"))
    api_key = os.getenv("TELONEX_API_KEY")
    if not api_key:
        raise RuntimeError("TELONEX_API_KEY is required in .env or environment.")

    jobs = _jobs(_parse_date(args.start_date), _parse_date(args.end_date))
    if args.start_offset:
        jobs = jobs[args.start_offset :]
    if args.max_jobs:
        jobs = jobs[: args.max_jobs]
    if not jobs:
        print("summary no_jobs=1")
        return 0

    sem = asyncio.Semaphore(max(1, int(args.workers)))
    counts: dict[str, int] = {}
    timeout = httpx.Timeout(float(args.timeout_seconds))
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        tasks = [
            _download_one(
                client=client,
                sem=sem,
                api_key=api_key,
                base_url=args.base_url,
                cache_root=args.cache_root,
                job=job,
                overwrite=bool(args.overwrite),
                retries=max(0, int(args.retries)),
            )
            for job in jobs
        ]
        for index, task in enumerate(asyncio.as_completed(tasks), start=1):
            status = await task
            counts[status] = counts.get(status, 0) + 1
            if index % max(1, int(args.progress_every)) == 0 or index == len(tasks):
                print(
                    f"progress {index}/{len(tasks)} "
                    + " ".join(f"{key}={counts[key]}" for key in sorted(counts)),
                    flush=True,
                )
    print("summary " + " ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    return 1 if counts.get("failed", 0) else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hydrate Telonex API-day cache for BTC 5m Polymarket book snapshots.",
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--base-url", default="https://api.telonex.io")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--max-jobs", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=100)
    return asyncio.run(_run_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
