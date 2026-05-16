import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.wallet_manager import WalletManager

logger = logging.getLogger("WalletHandler")


async def handle_wallet_balance(
    update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_manager: WalletManager
) -> None:
    """Handle /wallet balance command."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet balance <wallet_address>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        wallet_address = args[0]
        
        # Validate address
        if not wallet_manager.is_valid_address(wallet_address):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid Ethereum address",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Get balance report
        report = wallet_manager.format_balance_report(wallet_address)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in wallet balance handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_health(
    update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_manager: WalletManager
) -> None:
    """Handle /wallet health command."""
    try:
        health = wallet_manager.health_check()
        
        status_emoji = "✅" if health["connected"] else "❌"
        status_text = health["status"].upper()
        
        lines = [
            f"{status_emoji} **Wallet Manager Health**",
            f"• Status: `{status_text}`",
            f"• Chain ID: `{health['chain_id']}`",
            f"• Latest Block: `{health.get('latest_block', 'N/A')}`",
        ]
        
        if "error" in health:
            lines.append(f"• Error: `{health['error'][:100]}`")
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in wallet health handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet help command."""
    help_text = """
🏦 **Wallet Commands**

• `/wallet balance <address>` — Check token balances (MATIC, USDC, POL)
• `/wallet health` — Check wallet manager health
• `/wallet help` — Show this help

**Supported Tokens:**
• MATIC (native)
• USDC (0x2791...Aa84174)
• POL (0x455e...1693313)

**Example:**
`/wallet balance 0x742d35Cc6634C0532925a3b844Bc9e7595f42dE`
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )
