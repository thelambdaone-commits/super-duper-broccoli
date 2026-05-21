import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.polymarket_order_manager import PolymarketOrderManager
from utils.market_data_reader import MarketDataReader

logger = logging.getLogger("PolymarketHandler")


async def handle_polymarket_bet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_manager: PolymarketOrderManager,
) -> None:
    """Handle /polymarket bet command."""
    try:
        args = context.args
        
        if len(args) < 4:
            help_text = """
Usage: `/polymarket bet <market_id> <outcome> <amount> [--dry-run]`

**Outcomes:** YES, NO

**Example:**
`/polymarket bet 0x123abc YES 10`
`/polymarket bet 0x123abc NO 5 --dry-run`
"""
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=help_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        market_id = args[0]
        outcome = args[1].upper()
        amount_str = args[2]
        dry_run = "--dry-run" in args

        if outcome not in ("YES", "NO"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Outcome must be YES or NO",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        try:
            amount = float(amount_str)
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Invalid amount: {amount_str}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Get market price
        if hasattr(order_manager, '_clob_client') and order_manager._clob_client:
            price = 0.5  # Default midpoint
        else:
            price = 0.5

        # Place bet
        order = await order_manager.place_order(
            market_id=market_id,
            token_id="",  # Would get from market
            outcome=outcome,
            side="BUY",
            price=price,
            amount=amount,
            dry_run=dry_run,
        )

        # Send order confirmation
        order_msg = order_manager.format_order(order)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=order_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in polymarket bet handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_polymarket_claim(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_manager: PolymarketOrderManager,
) -> None:
    """Handle /polymarket claim command."""
    try:
        args = context.args
        
        if len(args) < 2:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/polymarket claim <market_id> <outcome>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        market_id = args[0]
        outcome = args[1].upper()

        dry_run = "--dry-run" in args

        # Claim winnings
        receipt = await order_manager.claim_winnings(
            market_id=market_id,
            outcome=outcome,
            dry_run=dry_run,
        )

        # Send claim receipt
        receipt_msg = order_manager.format_claim_receipt(receipt)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=receipt_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in polymarket claim handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_polymarket_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /polymarket help command."""
    help_text = """
🎲 **Polymarket Commands**

• `/polymarket bet <market_id> <YES|NO> <amount> [--dry-run]` — Place a bet
• `/polymarket claim <market_id> <YES|NO> [--dry-run]` — Claim winnings
• `/polymarket help` — Show this help

**Fee Structure:**
• Taker: 2.0%
• Maker: 0.0%

**Examples:**
• `/polymarket bet 0xabcd YES 10` — Bet 10 USDC on YES
• `/polymarket claim 0xabcd YES --dry-run` — Simulate claiming
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )
