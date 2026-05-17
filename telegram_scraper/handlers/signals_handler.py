import logging
import time
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.signal_generator import SignalGenerator
from utils.signal_fusion import SignalFusion, MicrostructureSignal, CalibratedSignal, SentimentSignal

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
• `/signals matrix <ticker>` — Cognitive matrix decision
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


async def handle_signals_matrix(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ticker: str,
) -> None:
    """Handle /signals matrix command - cognitive matrix decision."""
    fusion = SignalFusion()

    microstructure = await fusion.get_microstructure_signal(ticker)

    calibrated = fusion.get_calibrated_signal(
        ticker=ticker,
        model_prob=0.68,
        market_price=0.58,
        time_to_resolution=3600,
        model_name="freqai_v2",
        dissimilarity_index=0.2,
    )

    raw_msg = f"BUY {ticker} @ 0.65"
    sentiment = fusion.parse_sentiment_signal(raw_msg)

    regime = "LOW_VOL"
    fused = await fusion.fuse_signals(
        ticker=ticker,
        regime=regime,
        microstructure=microstructure,
        calibrated=calibrated,
        sentiment=sentiment,
    )

    matrix_output = fusion.format_cognitive_matrix(fused)

    emit = fusion.should_emit_signal(fused)
    emit_status = f"✅ *EMIT SIGNAL*" if emit else f"❌ *BLOCKED*"

    final_output = f"{matrix_output}\n\n{emit_status}"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=final_output,
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_paper_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ticker: str,
) -> None:
    """Handle /paper test command - test paper engine execution."""
    from execution.paper_engine import PolymarketPaperEngine

    engine = PolymarketPaperEngine()

    mock_orderbook = {
        "bids": [
            [0.55, 1000],
            [0.54, 2000],
            [0.53, 3000],
            [0.52, 4000],
            [0.51, 5000],
        ],
        "asks": [
            [0.56, 800],
            [0.57, 1500],
            [0.58, 2500],
            [0.59, 3500],
            [0.60, 4500],
        ],
    }

    result = await engine.execute_order(
        ticker=ticker,
        side="YES",
        order_type="MARKET",
        target_price=0.56,
        allocated_capital=500,
        orderbook=mock_orderbook,
    )

    output = (
        f"🧪 *PAPER ENGINE TEST*\n"
        f"────────────────────────\n"
        f"🎯 `{ticker}` | SIDE: YES | TYPE: MARKET\n"
        f"💰 Capital: `$500`\n\n"
        f"📊 *RESULT:* `{result.status}`\n"
        f"📦 *Fill Price:* `${result.fill_price:.4f}`\n"
        f"📦 *Size:* `{result.size_contracts:.2f}` contracts\n"
        f"💵 *Friction:* `${result.friction_cost:.4f}`\n"
        f"📉 *Slippage:* `{result.slippage:.4f}` ({result.slippage_pct:.2f}%)\n"
        f"⏱️ *Exec Time:* `{result.execution_time_ms:.1f}ms`\n"
    )

    if result.partial_fill:
        output += f"\n⚠️ *PARTIAL FILL:* `${result.filled_volume_usdc:.2f}` / `${result.requested_volume_usdc:.2f}`"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=output,
        parse_mode=ParseMode.MARKDOWN,
    )
