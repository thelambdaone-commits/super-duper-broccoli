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
    """Handle /signals command with Lobstar style."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
            text=(
                "📊 <b>FLUX DE SIGNAUX</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Usage: <code>/signals &lt;asset&gt; [timeframe]</code>\n\n"
                "💎 <b>Assets</b>: <code>BTC</code>, <code>SOL</code>, <code>ETH</code>\n"
                "⏱️ <b>Timeframes</b>: <code>5m</code>, <code>15m</code>, <code>1h</code>"
            ),
                parse_mode=ParseMode.HTML,
            )
            return

        asset = args[0].upper()
        timeframe = args[1] if len(args) > 1 else "15m"

        # Get signal
        signals = signal_generator.get_latest_signals(asset)
        
        if not signals:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🔍 <b>AUCUN SIGNAL</b>\n\nAucun signal disponible pour <code>{asset}</code> actuellement.",
                parse_mode=ParseMode.HTML,
            )
            return

        if timeframe not in signals:
            available = list(signals.keys())
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ <b>TIMEFRAME INCORRECT</b>\n\nL'horizon <code>{timeframe}</code> n'est pas disponible.\nDisponibles: <code>{', '.join(available)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Send signal
        signal = signals[timeframe]
        signal_msg = signal.to_markdown()
        
        if "━━━━━━━━━" not in signal_msg:
            signal_msg = (
                f"📡 <b>SIGNAL DE TRADING DETECTÉ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{signal_msg}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=signal_msg,
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Error in signals handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ <b>ERREUR SIGNAL</b>\n\nÉchec du traitement du signal : <code>{str(e)[:100]}</code>",
            parse_mode=ParseMode.HTML,
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
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Error in signals_all handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_signals_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /signals help command."""
    help_text = """
📊 <b>Trading Signals Commands</b>

• <code>/signals &lt;asset&gt; [timeframe]</code> — Get signal for asset/timeframe
• <code>/signals_all</code> — Show all available signals
• <code>/signals matrix &lt;ticker&gt;</code> — Cognitive matrix decision
• <code>/signals help</code> — Show this help

<b>Supported Assets:</b>
• BTC (Bitcoin)
• SOL (Solana)
• ETH (Ethereum)

<b>Supported Timeframes:</b>
• 5m (5 minutes)
• 15m (15 minutes)
• 1h (1 hour)

<b>Signal Types:</b>
• 🚀 STRONG_BUY — Confidence &gt; 75%
• 📈 BUY — Bullish signal
• ⏸️ NEUTRAL — Mixed signals
• 📉 SELL — Bearish signal
• 💥 STRONG_SELL — Confidence &gt; 75% bearish
• ⏳ WAIT — Trading not allowed

<b>Examples:</b>
• <code>/signals BTC 15m</code>
• <code>/signals SOL 1h</code>
• <code>/signals_all</code>
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.HTML,
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
    emit_status = f"✅ <b>EMIT SIGNAL</b>" if emit else f"❌ <b>BLOCKED</b>"

    final_output = f"{matrix_output}\n\n{emit_status}"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=final_output,
        parse_mode=ParseMode.HTML,
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
        f"🧪 <b>PAPER ENGINE TEST</b>\n"
        f"────────────────────────\n"
        f"🎯 <code>{ticker}</code> | SIDE: YES | TYPE: MARKET\n"
        f"💰 Capital: <code>$500</code>\n\n"
        f"📊 <b>RESULT:</b> <code>{result.status}</code>\n"
        f"📦 <b>Fill Price:</b> <code>${result.fill_price:.4f}</code>\n"
        f"📦 <b>Size:</b> <code>{result.size_contracts:.2f}</code> contracts\n"
        f"💵 <b>Friction:</b> <code>${result.friction_cost:.4f}</code>\n"
        f"📉 <b>Slippage:</b> <code>{result.slippage:.4f}</code> ({result.slippage_pct:.2f}%)\n"
        f"⏱️ <b>Exec Time:</b> <code>{result.execution_time_ms:.1f}ms</code>\n"
    )

    if result.partial_fill:
        output += f"\n⚠️ <b>PARTIAL FILL:</b> <code>${result.filled_volume_usdc:.2f}</code> / <code>${result.requested_volume_usdc:.2f}</code>"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=output,
        parse_mode=ParseMode.HTML,
    )
