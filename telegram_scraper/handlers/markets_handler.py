import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.market_data_reader import MarketDataReader

logger = logging.getLogger("MarketsHandler")


async def handle_markets_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_reader: MarketDataReader,
) -> None:
    """Handle /markets list command."""
    try:
        args = context.args
        limit = 10
        sort_by = "volume"

        if args and args[0].isdigit():
            limit = int(args[0])
        if len(args) > 1:
            sort_by = args[1]

        # Get top markets
        markets = market_reader.list_top_markets(limit=limit, sort_by=sort_by)

        if not markets:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ No markets found",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Format and send
        markets_msg = market_reader.format_markets_list(markets, limit)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=markets_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in markets list handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_reader: MarketDataReader,
) -> None:
    """Handle /markets info command."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/markets info <market_id_or_slug>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        market_id = args[0]

        # Get market snapshot
        snapshot = market_reader.get_market_snapshot(market_id)

        if not snapshot:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Market not found: {market_id}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Format and send
        market_msg = market_reader.format_market_snapshot(snapshot)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=market_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in markets info handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_reader: MarketDataReader,
) -> None:
    """Handle /markets search command."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/markets search <query>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        query = " ".join(args)

        # Search markets
        markets = market_reader.search_markets(query, limit=5)

        if not markets:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"No markets found for: {query}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Format and send
        markets_msg = market_reader.format_markets_list(markets, limit=5)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=markets_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in markets search handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /markets help command."""
    help_text = """
📈 **Polymarket Commands**

• `/markets list [limit] [sort]` — List top markets (default: 10, sort: volume/liquidity)
• `/markets info <id>` — Get market details
• `/markets search <query>` — Search markets
• `/markets help` — Show this help

**Examples:**
• `/markets list` — Show top 10 by volume
• `/markets list 5 liquidity` — Show top 5 by liquidity
• `/markets info bitcoin` — Get Bitcoin market info
• `/markets search "2025 election"` — Search for election markets
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )
