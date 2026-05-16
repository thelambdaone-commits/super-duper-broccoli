import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.signal_generator import SignalGenerator

logger = logging.getLogger("SignalsHandler")


async def handle_signals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    signal_generator: SignalGenerator,
) -> None:
    """Handle /signals command."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/signals <asset> [timeframe]`\n\nAssets: BTC, SOL, ETH\nTimeframes: 5m, 15m, 1h",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        asset = args[0].upper()
        timeframe = args[1] if len(args) > 1 else "15m"

        # Get signal
        signals = signal_generator.get_latest_signals(asset)
        
        if not signals:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"No signals available for {asset}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if timeframe not in signals:
            available = list(signals.keys())
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Timeframe {timeframe} not found.\nAvailable: {', '.join(available)}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Send signal
        signal = signals[timeframe]
        signal_msg = signal.to_markdown()
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=signal_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in signals handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_signals_all(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    signal_generator: SignalGenerator,
) -> None:
    """Handle /signals_all command to show all signals."""
    try:
        report = signal_generator.format_signals_report()
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in signals_all handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_signals_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /signals help command."""
    help_text = """
📊 **Trading Signals Commands**

• `/signals <asset> [timeframe]` — Get signal for asset/timeframe
• `/signals_all` — Show all available signals
• `/signals help` — Show this help

**Supported Assets:**
• BTC (Bitcoin)
• SOL (Solana)
• ETH (Ethereum)

**Supported Timeframes:**
• 5m (5 minutes)
• 15m (15 minutes)
• 1h (1 hour)

**Signal Types:**
• 🚀 STRONG_BUY — Confidence > 75%
• 📈 BUY — Bullish signal
• ⏸️ NEUTRAL — Mixed signals
• 📉 SELL — Bearish signal
• 💥 STRONG_SELL — Confidence > 75% bearish
• ⏳ WAIT — Trading not allowed

**Examples:**
• `/signals BTC 15m`
• `/signals SOL 1h`
• `/signals_all`
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )
