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
    """Handle /markets list command with Lobstar style."""
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
                text="🔍 *RECHERCHE MARCHÉS*\n━━━━━━━━━━━━━━━━━━━━\n\nAucun marché actif trouvé pour le moment.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Format and send
        markets_msg = market_reader.format_markets_list(markets, limit)
        
        # Add Header if missing
        if "━━━━━━━━━" not in markets_msg:
            markets_msg = (
                f"📈 *TOP {limit} MARCHÉS ({sort_by.upper()})*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{markets_msg}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=markets_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in markets list handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ *ERREUR MARCHÉS*\n\nImpossible de lister les marchés : `{str(e)[:100]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_reader: MarketDataReader,
) -> None:
    """Handle /markets info command with Lobstar style."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "ℹ️ *DÉTAILS MARCHÉ*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Usage: `/markets info <slug_ou_id>`\n\n"
                    "💡 _Exemple: /markets info solana-price-prediction_"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        market_id = args[0]

        # Get market snapshot
        snapshot = market_reader.get_market_snapshot(market_id)

        if not snapshot:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ *MARCHÉ INTROUVABLE*\n\nAucun marché correspondant à `{market_id}` n'a été trouvé.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Format and send
        market_msg = market_reader.format_market_snapshot(snapshot)
        
        if "━━━━━━━━━" not in market_msg:
            market_msg = (
                f"📊 *ANALYSE DE MARCHÉ*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{market_msg}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=market_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in markets info handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ *ERREUR ANALYSE*\n\nÉchec de la récupération des détails : `{str(e)[:100]}`",
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

*Market Discovery (AI Scored):*
• `/markets discover [limit] [-category]` — Find best markets by AI scoring
• `/markets opportunities [min_edge]` — Find best betting edges (spread > min_edge%)
• `/markets contrarian [limit]` — Find contrarian betting opportunities

*Screening (VCP/CANSLIM):*
• `/markets vcp [limit]` — Volatility Contraction Pattern screener
• `/markets canslim [limit]` — CANSLIM methodology screener

*Market Info:*
• `/markets list [limit] [sort]` — List top markets (volume/liquidity)
• `/markets feed` — Show unified market feed + crypto intelligence
• `/markets info <id>` — Get market details
• `/markets search <query>` — Search markets
• `/markets help` — Show this help

**Examples:**
• `/markets discover` — Show top 10 scored markets
• `/markets vcp` — Find VCP patterns
• `/markets canslim` — Find CANSLIM opportunities
• `/markets opportunities 10` — Find edges > 10%
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_markets_feed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market_reader: MarketDataReader,
) -> None:
    """Handle /feed or /markets feed command."""
    try:
        # 1. Fetch top 8 general markets by volume for the general feed
        markets_general = market_reader.client.list_markets(limit=8, sort_by="volume")
        
        # 2. Fetch top 100 markets to analyze for crypto intelligence
        markets_all = market_reader.client.list_markets(limit=100, sort_by="volume")
        
        # 3. Initialize CryptoMarketIntelligence with default parameters
        import os
        from utils.crypto_market_intelligence import CryptoMarketIntelligence
        
        watchlist_str = os.getenv("CRYPTO_INTELLIGENCE_WATCHLIST", "BTC,ETH,SOL")
        watchlist = [t.strip().upper() for t in watchlist_str.split(",") if t.strip()]
        min_volume = float(os.getenv("CRYPTO_INTELLIGENCE_MIN_VOLUME", "10000"))
        min_liquidity = float(os.getenv("CRYPTO_INTELLIGENCE_MIN_LIQUIDITY", "1000"))
        
        crypto_intelligence = CryptoMarketIntelligence(
            watchlist=watchlist,
            min_volume=min_volume,
            min_liquidity=min_liquidity,
        )
        
        intelligence_report = crypto_intelligence.analyze(markets_all)
        
        # 4. Format using format_unified_feed_report
        from utils.message_formatter import format_unified_feed_report
        report_text = format_unified_feed_report(markets_general, intelligence_report)
        
        # 5. Send message to Telegram
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report_text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error in markets feed handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error generating feed: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_discover(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /markets discover command - find best markets by scoring."""
    try:
        from utils.market_discovery import MarketDiscovery, format_market_discovery
        
        args = context.args
        limit = 10
        category = None
        
        if args and args[0].isdigit():
            limit = int(args[0])
        if len(args) > 1 and args[1].startswith("-"):
            category = args[1].lstrip("-")
        
        discovery = MarketDiscovery()
        scored_markets = discovery.discover_markets(limit=limit, min_score=40.0, category=category)
        
        text = format_market_discovery(scored_markets)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except ImportError as e:
        logger.warning(f"Market discovery not available: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Market discovery module not available.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error in markets discover handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_opportunities(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /markets opportunities command - find best betting edges."""
    try:
        from utils.market_discovery import MarketDiscovery, format_betting_opportunities
        
        args = context.args
        min_edge = 5.0
        limit = 10
        if args:
            if args[0].replace(".", "").isdigit():
                min_edge = float(args[0])
            if len(args) > 1 and args[1].isdigit():
                limit = int(args[1])
        
        discovery = MarketDiscovery()
        opportunities = discovery.find_betting_opportunities(
            min_edge_percent=min_edge,
            limit=limit,
            max_days_to_resolution=3.0,
        )
        
        text = format_betting_opportunities(opportunities)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except ImportError as e:
        logger.warning(f"Market discovery not available: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Market discovery module not available.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error in markets opportunities handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_contrarian(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /markets contrarian command - find contrarian betting opportunities."""
    try:
        from utils.market_discovery import MarketDiscovery
        
        args = context.args
        limit = 10
        if args and args[0].isdigit():
            limit = int(args[0])
        
        discovery = MarketDiscovery()
        contrarian_opps = discovery.get_contrarian_opportunities(limit=limit)
        
        if not contrarian_opps:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ No contrarian opportunities found.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        lines = [
            "🎭 *CONTRARIAN OPPORTUNITIES* 🎭",
            "────────────────────────",
        ]
        
        for i, opp in enumerate(contrarian_opps, 1):
            horizon = ""
            if isinstance(opp.get("days_to_resolution"), (int, float)):
                horizon = f" | T- {opp['days_to_resolution']:.1f}j"
            lines.extend([
                f"{i}. *{opp['question'][:50]}...*",
                f"   📊 Current: `{opp['current_odds']}`",
                f"   🎯 Bet: `{opp['contrarian_bet']}`",
                f"   💡 {opp['reason']}",
                f"   💰 Vol: `${opp['volume']:,.0f}`{horizon}",
                "",
            ])
        
        lines.append("────────────────────────")
        lines.append(f"Found {len(contrarian_opps)} contrarian opportunities")
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except ImportError as e:
        logger.warning(f"Market discovery not available: {e}")
    except Exception as e:
        logger.error(f"Error in markets contrarian handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_vcp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /markets vcp command - VCP screener."""
    try:
        from utils.screeners import VCPScreener, format_vcp_results
        
        args = context.args
        limit = 10
        if args and args[0].isdigit():
            limit = int(args[0])
        
        screener = VCPScreener()
        candidates = screener.screen(limit=limit)
        
        text = format_vcp_results(candidates)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except ImportError as e:
        logger.warning(f"Screeners not available: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Screener module not available.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error in markets vcp handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_markets_canslim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /markets canslim command - CANSLIM screener."""
    try:
        from utils.screeners import CANSLIMScreener, format_canslim_results
        
        args = context.args
        limit = 10
        if args and args[0].isdigit():
            limit = int(args[0])
        
        screener = CANSLIMScreener()
        results = screener.screen(limit=limit)
        
        text = format_canslim_results(results)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except ImportError as e:
        logger.warning(f"Screeners not available: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Screener module not available.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error in markets canslim handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )
