#!/usr/bin/env python3
import argparse
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from utils.ai_specialists import load_free_provider_sources


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "user_data" / "provider_discovery" / "free_ai_candidates.json"


class GitHubRepoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.repos: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", href):
            self.repos.add(f"https://github.com{href}")


def fetch_text(url: str, timeout: int = 20) -> str:
    request = Request(url, headers={"User-Agent": "quant-agentic-provider-discovery/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def discover_candidates() -> dict:
    config = load_free_provider_sources()
    candidates: dict[str, dict] = {}

    for source in config.get("sources", []):
        url = source["url"]
        html = fetch_text(url)
        parser = GitHubRepoParser()
        parser.feed(html)
        for repo in sorted(parser.repos):
            candidates.setdefault(repo, {"repo": repo, "sources": []})
            candidates[repo]["sources"].append(source["id"])

    return {
        "generated_at": time.time(),
        "policy": config.get("policy", {}),
        "reject_if": config.get("reject_if", []),
        "candidate_count": len(candidates),
        "candidates": sorted(candidates.values(), key=lambda item: item["repo"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover public free-tier AI provider candidates without scraping keys or bypassing limits."
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = discover_candidates()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {result['candidate_count']} candidates to {args.output}")


if __name__ == "__main__":
    main()
