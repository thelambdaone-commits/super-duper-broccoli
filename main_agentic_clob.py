import argparse
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Establish secure logging filters BEFORE any other imports to protect all modules
from utils.security_utils import setup_secure_logging
setup_secure_logging()

# Apply quantitative hook backward-compatible aliases early
from utils.localization_sync import apply_backward_compatible_aliases
apply_backward_compatible_aliases()

from utils.exceptions import QuantFatal
from utils.logging_setup import setup_logging
from bootstrap.factories import build_access_control
from bootstrap.initializer import prepare_runtime_context
from bootstrap.lifecycle import BotLifecycle
from bootstrap.security import (
    PROD_CONFIRMATION_TEXT,
    require_production_confirmation,
    telegram_single_instance_lock,
)
from utils.telegram_helpers import parse_private_chat_ids

logger = setup_logging()

async def main(
    dry_run: bool = False,
    execution_mode: str = "PAPER",
) -> None:
    context = prepare_runtime_context(execution_mode)
    lifecycle = BotLifecycle(context, execution_mode)
    if dry_run:
        await lifecycle.dry_run_report()
    else:
        await lifecycle.start()
    return


async def resolve_chat() -> None:
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters
    from utils.vault_handler import VaultHandler

    vault = VaultHandler()
    secrets = vault.fetch_quantum_secrets()
    app = Application.builder().token(secrets["TELEGRAM_BOT_TOKEN"]).build()

    found: list[dict] = []

    async def handler(update: Update, _ctx) -> None:
        msg = update.channel_post or update.message
        if msg and msg.chat:
            chat = msg.chat
            found.append({"id": chat.id, "type": chat.type, "title": chat.title, "username": chat.username})
            logger.info(f"Chat detected — id={chat.id} type={chat.type} title={chat.title}")

    app.add_handler(MessageHandler(filters.TEXT, handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    logger.info("Send a message in the target channel now...")
    for i in range(15, 0, -1):
        logger.info("Waiting for chat discovery: %ss remaining", i)
        await asyncio.sleep(1)

    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    if not found:
        logger.warning("No messages received. Is the bot admin in the channel?")
        return

    logger.info(f"Detected {len(found)} chat(s). Set CHAT_ID={found[0]['id']} to use it.")


async def archive_maintenance() -> None:
    from utils.data_archiver import DataArchiver
    archiver = DataArchiver()
    result = archiver.run_maintenance_cycle()
    logger.info(f"Maintenance cycle complete: {result}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quant Agentic Trading Core")
    parser.add_argument("--dry-run", action="store_true", help="Validate pipeline components")
    parser.add_argument("--resolve-chat", action="store_true", help="Detect chat ID from incoming messages")
    parser.add_argument(
        "--mode", type=str, default=None,
        choices=["REPLAY", "PAPER", "SHADOW", "PROD"],
        help="Execution mode: REPLAY (backtest), PAPER (simulated), SHADOW (mini-size), PROD (real capital)",
    )
    parser.add_argument("--maintenance", action="store_true", help="Run archive maintenance cycle and exit")
    args = parser.parse_args()

    # 1. Deterministic Execution Mode Conflict Checking
    real_env = os.getenv("REAL", "false").lower() == "true"
    paper_env = os.getenv("PAPER", "false").lower() == "true"

    if real_env and paper_env:
        logger.critical("🚨 CONFLICT: Both REAL=true and PAPER=true are defined in the environment!")
        raise QuantFatal("Conflicting environment variables: Both REAL=true and PAPER=true are defined!")

    # Exclusive Priority: CLI Argument > Environment Variable > Database (Ledger) > Fallback ("PAPER")
    resolved_mode = None
    if args.mode is not None:
        resolved_mode = args.mode
    elif real_env:
        resolved_mode = "PROD"
    elif paper_env:
        resolved_mode = "PAPER"
    else:
        try:
            from ledger.ledger_db import Ledger
            from core.autonomous_mode_controller import select_autonomous_execution_mode
            startup_ledger = Ledger()
            decision = select_autonomous_execution_mode(startup_ledger)
            resolved_mode = decision.mode
            logger.info(
                "Autonomous execution mode selected: `%s` (%s)",
                resolved_mode,
                decision.reason,
            )
        except Exception as e:
            logger.debug(f"Failed to resolve autonomous execution mode: {e}")
            resolved_mode = "PAPER"

    try:
        require_production_confirmation(resolved_mode)
        if args.resolve_chat:
            with telegram_single_instance_lock():
                asyncio.run(resolve_chat())
        elif args.maintenance:
            asyncio.run(archive_maintenance())
        else:
            if args.dry_run:
                asyncio.run(main(dry_run=args.dry_run, execution_mode=resolved_mode))
            else:
                with telegram_single_instance_lock():
                    asyncio.run(main(dry_run=args.dry_run, execution_mode=resolved_mode))
    except QuantFatal as e:
        logger.critical(f"FATAL: {e}")
        raise SystemExit(1)
