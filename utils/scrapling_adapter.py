import logging
from typing import Any

logger = logging.getLogger("ScraplingAdapter")


class ScraplingUnavailable(RuntimeError):
    pass


def _load_fetcher() -> Any:
    try:
        from scrapling.fetchers import Fetcher
    except ImportError as exc:
        raise ScraplingUnavailable(
            'Scrapling fetchers are not installed. Install with: pip install "scrapling[fetchers]"'
        ) from exc
    return Fetcher


def scrape_text(url: str, css_selector: str = "body") -> list[str]:
    """Fetch a page with Scrapling and return text values for a CSS selector."""
    Fetcher = _load_fetcher()
    page = Fetcher.get(url)
    values = page.css(f"{css_selector}::text").getall()
    logger.info("Scraped %s values from %s with selector %s", len(values), url, css_selector)
    return [value.strip() for value in values if value and value.strip()]
