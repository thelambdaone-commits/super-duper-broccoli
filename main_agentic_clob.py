import argparse
import asyncio
import logging
import os
import sys

from bootstrap.factories import build_access_control
from bootstrap.initializer import prepare_runtime_context
from bootstrap.lifecycle import BotLifecycle
from utils.exceptions import QuantFatal
from utils.local_dependency_loader import normalize_project_path_env
from utils.localization_sync import apply_backward_compatible_aliases
from utils.logging_setup import setup_logging
from utils.telegram_helpers import parse_private_chat_ids
from bootstrap.security import (
    PROD_CONFIRMATION_TEXT,
    require_production_confirmation,
    telegram_single_instance_lock,
)

logger = logging.getLogger("Main")


def resolve_execution_mode(args_mode: str | None = None) -> str:
    real_env = os.getenv("REAL", "false").lower() == "true"
    paper_env = os.getenv("PAPER", "false").lower() == "true"

    if real_env and paper_env:
        logger.warning(
            "Both REAL=true and PAPER=true are set; resolving automatically to PROD "
            "(REAL takes precedence)."
        )
        paper_env = False

    # 1. If CLI specified, always use it
    if args_mode:
        logger.info("Execution mode selected from CLI: %s", args_mode)
        return args_mode

    # 2. Check environment variables
    if real_env:
        logger.info("Execution mode resolved from env: PROD")
        return "PROD"
    if paper_env:
        logger.info("Execution mode resolved from env: PAPER")
        return "PAPER"

    # 3. Default fallback
    logger.info("Execution mode fallback: PAPER")
    return "PAPER"

async def archive_maintenance():
    from utils.feature_store import FeatureStore
    store = FeatureStore()
    try:
        from bootstrap.helpers import run_blocking
        from continuous_improvement.microstructure_archiver import archive_old_microstructure
        await run_blocking("archive microstructure", archive_old_microstructure, store)
    finally:
        store.close()

async def resolve_chat():
    from bootstrap.factories import build_access_control
    from utils.config_loader import get_secrets
    secrets = get_secrets()
    build_access_control(secrets, "PAPER")
    print("Chat resolution complete.")

def main_sync():
    normalize_project_path_env()
    setup_logging()
    apply_backward_compatible_aliases()

    parser = argparse.ArgumentParser(description="Lobstar Quant Agentic Trading Bot")
    parser.add_argument("--mode", type=str, default=None, choices=["REPLAY", "PAPER", "SHADOW", "PROD"])
    parser.add_argument("--dry-run", action="store_true", help="Initialize and validate but do not start loops")
    parser.add_argument("--resolve-chat", action="store_true", help="Resolve CHAT_ID for current bot token and exit")
    parser.add_argument("--maintenance", action="store_true", help="Run archive microstructure cycle and exit")
    parser.add_argument("--tui", action="store_true", help="Start the professional Terminal User Interface (Bloomberg-style)")
    args = parser.parse_args()

    resolved_mode = resolve_execution_mode(args.mode)

    try:
        require_production_confirmation(resolved_mode)
        if args.resolve_chat:
            with telegram_single_instance_lock():
                asyncio.run(resolve_chat())
        elif args.maintenance:
            asyncio.run(archive_maintenance())
        elif args.tui:
            from tui.app import LobstarTerminal
            app = LobstarTerminal()
            os.environ["TELEGRAM_DISABLED"] = "true"
            async def run_with_tui():
                context = prepare_runtime_context(resolved_mode)
                lifecycle = BotLifecycle(context, resolved_mode)
                bg_task = asyncio.create_task(lifecycle.start())
                await app.run_async()
                await lifecycle.stop()
                bg_task.cancel()
            asyncio.run(run_with_tui())
        else:
            if args.dry_run:
                context = prepare_runtime_context(resolved_mode)
                lifecycle = BotLifecycle(context, resolved_mode)
                asyncio.run(lifecycle.dry_run_report())
            else:
                async def run_bot():
                    context = prepare_runtime_context(resolved_mode)
                    lifecycle = BotLifecycle(context, resolved_mode)
                    await lifecycle.start()
                with telegram_single_instance_lock():
                    asyncio.run(run_bot())
    except QuantFatal as e:
        logger.critical("FATAL: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except Exception as e:
        logger.exception("Unhandled system error: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main_sync()
