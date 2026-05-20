"""Polymarket crawler configuration."""


class _CrawlerConfig:
    analytics_timeout: float = 15.0


class _Config:
    leaderboard_url: str = "https://polymarket.com/leaderboard"
    crawler: _CrawlerConfig = _CrawlerConfig()


CONFIG = _Config()