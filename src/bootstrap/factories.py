from __future__ import annotations

import os
from typing import Any, Callable

from agents.copy_trading_agent import CopyTradingAgent, CopyConfig
from core.lobstar_cognitive_brain import LobstarCognitiveBrain
from telegram_scraper.telegram_listener import TelegramListener
from utils.access_control import AccessControlManager
from utils.exceptions import QuantFatal
from utils.telegram_helpers import parse_chat_ids, parse_private_chat_ids

from bootstrap.security import _derive_public_wallet


def build_access_control(secrets: dict, execution_mode: str) -> tuple[AccessControlManager, int | None]:
    raw_admin_ids = secrets.get("TELEGRAM_ADMIN_CHAT_IDS") or os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
    admin_chat_ids = parse_chat_ids(raw_admin_ids) or set()
    if execution_mode.upper() == "PROD" and not admin_chat_ids:
        raise QuantFatal("TELEGRAM_ADMIN_CHAT_IDS is required in PROD mode.")

    access_control = AccessControlManager(admin_chat_ids=sorted(admin_chat_ids))
    raw_chat_id = os.getenv("CHAT_ID", "")
    chat_id = int(raw_chat_id) if raw_chat_id else None

    private_key_raw = secrets.get("CLOB_PRIVATE_KEY")
    tenant_wallet = _derive_public_wallet(private_key_raw)
    if chat_id and tenant_wallet:
        access_control.assigner_wallet_a_chat(chat_id, tenant_wallet)
    return access_control, chat_id


def build_copy_trading_agent(risk_engine: Any = None) -> CopyTradingAgent | None:
    copy_wallet = os.getenv("COPY_WALLET", "").strip()
    if not copy_wallet:
        return None
    copy_config = CopyConfig(
        target_wallet=copy_wallet,
        copy_multiplier=float(os.getenv("COPY_MULTIPLIER", "0.1")),
        max_copy_notional=float(os.getenv("COPY_MAX_NOTIONAL", "100.0")),
        buy_only=os.getenv("COPY_BUY_ONLY", "true").lower() == "true",
    )
    return CopyTradingAgent(copy_config, risk_engine=risk_engine)


def build_telegram_listener(
    secrets: dict,
    on_signal: Callable[[dict], None],
    chat_id: int | None,
    access_control: AccessControlManager,
) -> TelegramListener:
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise QuantFatal("TELEGRAM_BOT_TOKEN is missing from Vault/Environment.")
    raw_private = secrets.get("TELEGRAM_PRIVATE_CHAT_IDS") or os.getenv("TELEGRAM_PRIVATE_CHAT_IDS", "")
    raw_admin = secrets.get("TELEGRAM_ADMIN_CHAT_IDS") or os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
    admin_chat_ids = parse_chat_ids(raw_admin) or set()
    if not raw_private:
        if admin_chat_ids:
            raw_private = ",".join(str(chat_id) for chat_id in sorted(admin_chat_ids))
        elif chat_id and chat_id > 0:
            raw_private = str(chat_id)
    private_chat_ids = parse_private_chat_ids(raw_private)
    listener_chat_id = chat_id if chat_id and chat_id > 0 else None
    if listener_chat_id is None and admin_chat_ids:
        listener_chat_id = sorted(admin_chat_ids)[0]
    return TelegramListener(
        bot_token=token,
        on_signal=on_signal,
        chat_id=listener_chat_id,
        private_chat_ids=private_chat_ids,
        admin_chat_ids=admin_chat_ids,
        access_control=access_control,
        allow_private_messages=True,
    )


def build_broadcaster(notifier: Any, training_pipeline: Any, market_scanner: Any) -> Any:
    from scrapers.telegram_broadcaster import TelegramBroadcaster

    return TelegramBroadcaster(
        notifier=notifier,
        training_pipeline=training_pipeline,
        market_client=getattr(market_scanner, "client", market_scanner),
    )


def build_cognitive_brain(store: Any, market_scanner: Any, training_pipeline: Any) -> LobstarCognitiveBrain:
    return LobstarCognitiveBrain(
        store=store,
        scanner=market_scanner,
        training_pipeline=training_pipeline,
    )
