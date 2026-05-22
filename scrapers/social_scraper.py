import asyncio
import logging
import subprocess
import json
from typing import List, Dict, Any

logger = logging.getLogger("SocialScraper")

class SocialScraper:
    """
    Free Social Data Ingestion using snscrape (CLI wrapper).
    Supports Twitter/X search without official API keys.
    """

    async def search_twitter(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Executes snscrape via subprocess to fetch recent tweets.
        """
        cmd = ["snscrape", "--jsonl", "--max-results", str(limit), "twitter-search", query]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"snscrape failed: {stderr.decode()}")
                return []

            results = []
            for line in stdout.decode().splitlines():
                if line.strip():
                    results.append(json.loads(line))

            logger.info(f"✅ Fetched {len(results)} tweets for query: {query}")
            return results

        except FileNotFoundError:
            logger.warning("snscrape not found in PATH. Please install it: pip install snscrape")
            return []
        except Exception as e:
            logger.error(f"Social scraping error: {e}")
            return []

    async def get_crypto_sentiment_context(self, ticker: str) -> str:
        """
        Returns a concatenated string of recent tweets for LLM context.
        """
        tweets = await self.search_twitter(f"{ticker} crypto", limit=5)
        if not tweets:
            return ""

        context = "\n".join([f"- {t.get('content', '')}" for t in tweets])
        return f"Recent Social Sentiment for {ticker}:\n{context}"

# Instance globale
social_scraper = SocialScraper()
