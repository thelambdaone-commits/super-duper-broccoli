from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ExecutionMode = Literal["REPLAY", "PAPER", "SHADOW", "PROD"]
SecretSource = Literal["auto", "env", "vault"]


class AppSettings(BaseSettings):
    """Typed environment contract for new code paths.

    Existing modules still read env vars directly. Use this as the migration
    target for new code so configuration validation can be introduced safely.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    execution_mode: ExecutionMode = "PAPER"
    paper: bool = True
    real: bool = False
    secret_source: SecretSource = "auto"

    data_path: str = "./data"
    log_path: str = "./logs"

    vault_addr: str = "false"
    vault_token: str | None = None
    encryption_key: str | None = None

    telegram_bot_token: str | None = None
    telegram_private_chat_ids: str | None = None
    telegram_admin_chat_ids: str | None = None

    max_binance_staleness_seconds: float = 10.0
    max_polymarket_staleness_seconds: float = 60.0
    max_wallet_drift_usdc: float = 1.0
    max_memory_mb_threshold: float = 2048.0

    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    brave_search_api_key: str | None = None
    coingecko_api_key: str | None = None

    polygon_rpc_url: str | None = None
    eth_rpc_url: str | None = None
    base_rpc_url: str | None = None
    optimism_rpc_url: str | None = None
    sol_rpc_url: str | None = None

    @field_validator("execution_mode", mode="before")
    @classmethod
    def normalize_execution_mode(cls, value: str) -> str:
        return str(value or "PAPER").upper().strip()

    @field_validator("secret_source", mode="before")
    @classmethod
    def normalize_secret_source(cls, value: str) -> str:
        return str(value or "auto").lower().strip()

    @field_validator("real")
    @classmethod
    def reject_real_and_paper_conflict(cls, real: bool, info) -> bool:
        if real and info.data.get("paper"):
            raise ValueError("REAL=true and PAPER=true cannot both be enabled")
        return real

    def effective_execution_mode(self) -> ExecutionMode:
        if self.real:
            return "PROD"
        if self.paper:
            return "PAPER"
        return self.execution_mode


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()

