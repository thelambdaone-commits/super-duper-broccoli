import logging
import os
import json
import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

logger = logging.getLogger("CommandRouter")

# ==============================================================================
# COMMAND REGISTRY DIRECTORY
# ==============================================================================
# TO REGISTER A NEW TELEGRAM BOT COMMAND:
# 1. Simply add an entry to the COMMAND_REGISTRY dictionary below.
# 2. Implement the corresponding handler function as an async method on CommandRouter.
# The CommandRouter will automatically load and register the command handler on startup.
# ==============================================================================
COMMAND_REGISTRY = {
    "wallet": {
        "func": "_cmd_wallet",
        "category": "WALLET",
        "description": "Gérer les portefeuilles, soldes et connexions EOA/Proxy.",
        "usage": "/wallet [balance|health|add]",
        "example": "/wallet balance",
        "notes": "Affiche les balances de gaz native, pUSD Polymarket et le statut de connexion."
    },
    "transfer": {
        "func": "_cmd_transfer",
        "category": "WALLET",
        "description": "Transférer des fonds ou retirer du proxy vers l'EOA.",
        "usage": "/transfer [dest_address] [amount_usdc]",
        "example": "/transfer 0x71C...3a9 50",
        "notes": "Vérifie les signatures et exécute la transaction sur la chaîne Polygon."
    },
    "polymarket": {
        "func": "_cmd_polymarket",
        "category": "WALLET",
        "description": "Interagir ou parier sur les marchés Polymarket directement.",
        "usage": "/polymarket [action] [market_id] [amount]",
        "example": "/polymarket buy 0xabc...123 10",
        "notes": "Les ordres sont validés par le module de risque avant envoi."
    },
    "signals": {
        "func": "_cmd_signals",
        "category": "MARKETS",
        "description": "Lister ou déclencher manuellement les signaux de trading.",
        "usage": "/signals",
        "example": "/signals",
        "notes": "Affiche l'edge calculé par l'IA et les probabilités calibrées."
    },
    "markets": {
        "func": "_cmd_markets",
        "category": "MARKETS",
        "description": "Analyseur de marchés IA et indicateurs de screening.",
        "usage": "/markets [discover|opportunities|contrarian|vcp|canslim|help]",
        "example": "/markets opportunities 5",
        "notes": "Utilise l'intelligence artificielle pour screener les opportunités Polymarket."
    },
    "feed": {
        "func": "_cmd_feed",
        "category": "MARKETS",
        "description": "Afficher le flux d'informations unifié et l'intelligence crypto.",
        "usage": "/feed",
        "example": "/feed",
        "notes": "Recommandé pour obtenir une vue d'ensemble en temps réel."
    },
    "crypto": {
        "func": "_cmd_all_crypto_markets",
        "category": "MARKETS",
        "description": "Rechercher globalement tous les marchés crypto actifs par volume.",
        "usage": "/crypto",
        "example": "/crypto",
        "notes": "Affiche les 10 meilleurs marchés avec leur graphique ASCII de probabilité."
    },
    "updown": {
        "func": "_cmd_updown",
        "category": "MARKETS",
        "description": "Rechercher des marchés type Up/Down ou Strike de prix.",
        "usage": "/updown [ticker]",
        "example": "/updown SOL",
        "notes": "Extrêmement utile pour identifier des inefficacités directionnelles."
    },
    "ai": {
        "func": "_cmd_ai",
        "category": "AI",
        "description": "Questionner le Conseil d'IA Lobstar sur le marché ou des logs.",
        "usage": "/ai [prompt|status|errors]",
        "example": "/ai devrais-je acheter du SOL ce matin?",
        "notes": "Compile les avis des agents spécialistes dans une réponse synthétisée."
    },
    "model": {
        "func": "_cmd_model",
        "category": "QUANT",
        "description": "Statut et gestion du modèle HMM et des métriques de drift.",
        "usage": "/model [status|metrics|validate]",
        "example": "/model validate SOL",
        "notes": "Permet de vérifier si le modèle subit un drift ou nécessite une recalibration."
    },
    "risk": {
        "func": "_cmd_risk",
        "category": "ADMIN",
        "description": "Statut des risques, limites et boutons d'urgence.",
        "usage": "/risk [status|kill|freeze|exposure]",
        "example": "/risk status",
        "notes": "Permet de geler ou dégeler immédiatement les transactions automatiques."
    },
    "clob": {
        "func": "_cmd_clob",
        "category": "QUANT",
        "description": "Statut du CLOB et scanner d'opportunités d'arbitrage.",
        "usage": "/clob [arb]",
        "example": "/clob arb",
        "notes": "Scanne les inefficacités microstructures sur le carnet d'ordres."
    },
    "whales": {
        "func": "_cmd_whales",
        "category": "MARKETS",
        "description": "Suivi d'activité et leaderboard des portefeuilles baleines.",
        "usage": "/whales [leaderboard|analyze]",
        "example": "/whales leaderboard OVERALL",
        "notes": "Analyse les transactions passées et les rendements des meilleurs traders."
    },
    "trade": {
        "func": "_cmd_trade",
        "category": "TRADING",
        "description": "Moteur d'exécution, changement de mode (PAPER, SHADOW, PROD) et rapport de PnL.",
        "usage": "/trade [status|pnl|paper|shadow|prod] [on]",
        "example": "/trade pnl",
        "notes": "Modifiez le mode d'exécution uniquement avec un ledger et portefeuille valides."
    },
    "mcp": {
        "func": "_cmd_mcp",
        "category": "ADMIN",
        "description": "Status et listing des outils de l'agent MCP local.",
        "usage": "/mcp [status|tools]",
        "example": "/mcp status",
        "notes": "Réservé aux administrateurs systèmes pour le monitoring."
    },
    "dev": {
        "func": "_cmd_dev",
        "category": "ADMIN",
        "description": "Statut système, CPU, RAM, journalisation des logs et maintenance.",
        "usage": "/dev [metrics|logs|cleanup]",
        "example": "/dev metrics",
        "notes": "Nettoie la base de données et compresse les logs pour libérer de l'espace."
    },
    "audit": {
        "func": "_cmd_audit",
        "category": "ADMIN",
        "description": "Audit système complet et snapshot de l'état de trading.",
        "usage": "/audit [category]",
        "example": "/audit TRADING",
        "notes": "Retourne la configuration complète chiffrée et validée."
    },
    "paper": {
        "func": "_cmd_paper",
        "category": "TRADING",
        "description": "Lancer un test ou un ordre fictif sur le Paper Engine.",
        "usage": "/paper [ticker]",
        "example": "/paper SOL",
        "notes": "Idéal pour simuler le comportement du marché en direct."
    },
    "freeze": {
        "func": "_cmd_freeze",
        "category": "ADMIN",
        "description": "Geler immédiatement toutes les activités d'arbitrage et d'exécution.",
        "usage": "/freeze",
        "example": "/freeze",
        "notes": "Alias pour /risk freeze."
    },
    "unfreeze": {
        "func": "_cmd_unfreeze",
        "category": "ADMIN",
        "description": "Reprendre l'activité de trading gelée.",
        "usage": "/unfreeze",
        "example": "/unfreeze",
        "notes": "Alias pour /risk unfreeze."
    },
    "liquidate": {
        "func": "_cmd_liquidate",
        "category": "ADMIN",
        "description": "Liquider toutes les positions actives et annuler les ordres en attente.",
        "usage": "/liquidate",
        "example": "/liquidate",
        "notes": "Bouton d'urgence ultime pour sortir de tous les marchés."
    },
    "gsd": {
        "func": "_cmd_gsd",
        "category": "ADMIN",
        "description": "Lancer l'agent autonome de résolution de problèmes GSD sur une tâche ou un bug.",
        "usage": "/gsd [--dry-run] [description de l'issue]",
        "example": "/gsd --dry-run timing delay in websocket",
        "notes": "Résout les problèmes et exécute automatiquement les tests pytest avec option de rollback."
    }
}

class CommandRouter:
    def __init__(self, listener, wallet_manager=None, transfer_manager=None,
                 order_manager=None, signal_generator=None, market_reader=None):
        self.listener = listener
        self.app = listener.application
        self.wallet_manager = wallet_manager
        self.transfer_manager = transfer_manager
        self.order_manager = order_manager
        self.signal_generator = signal_generator
        self.market_reader = market_reader
        self.access_control = getattr(listener, 'access_control', None)



    def register_all(self):
        # Dynamically register all commands from the centralized registry
        for cmd_name, cmd_info in COMMAND_REGISTRY.items():
            func_name = cmd_info["func"]
            if hasattr(self, func_name):
                self._add_cmd(cmd_name, getattr(self, func_name))
            else:
                logger.error("Command handler %s not implemented for %s!", func_name, cmd_name)

        # Explicit manual / help command registration
        self._add_cmd("man", self._cmd_manual)
        self._add_cmd("help", self._cmd_manual)

        # Dynamic crypto horizons registration
        self._register_crypto_horizon_commands()

    def _add_cmd(self, name, func):
        self.app.add_handler(CommandHandler(name, func))

    def _register_crypto_horizon_commands(self):
        for asset in ("btc", "eth", "sol", "xrp", "hype", "doge", "bnb", "ada", "avax", "link", "sui", "pepe", "wif", "ton", "near"):
            self._add_cmd(asset, self._cmd_crypto_markets)
            for suffix in ("5", "15", "1h", "4h", "1d"):
                self._add_cmd(f"{asset}{suffix}", self._cmd_crypto_horizon)

    async def _cmd_crypto_horizon(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        command = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0].lower()
        match = None
        import re
        match = re.fullmatch(r"(btc|eth|sol|xrp|hype|doge|bnb|ada|avax|link|sui|pepe|wif|ton|near)(5|15|1h|4h|1d)", command)
        if not match:
            await self.listener.reply_to("Usage: /btc5 /btc15 /btc1h, idem /eth /sol /xrp /hype /doge /bnb /pepe /sui ...", update)
            return

        asset, horizon = match.group(1).upper(), match.group(2)
        chat_id = getattr(update.effective_message, "chat_id", None)
        logger.info("Crypto horizon command received: asset=%s horizon=%s chat_id=%s", asset, horizon, chat_id)
        try:
            from utils.crypto_horizon_sentiment import CryptoHorizonSentiment, format_horizon_sentiment
            client = self.listener._scanner.client if self.listener._scanner else None
            analyzer = CryptoHorizonSentiment(client=client)
            sentiment = analyzer.analyze(asset, horizon)

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = []
            row = []
            for h in ("5", "15", "1h", "4h", "1d"):
                label_map = {"5": "5m", "15": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
                label = label_map[h]
                if h == horizon:
                    label = f"🟢 {label}"
                row.append(InlineKeyboardButton(label, callback_data=f"horizon:{asset.lower()}:{h}"))
            keyboard.append(row)
            reply_markup = InlineKeyboardMarkup(keyboard)

            sent = await self.listener.reply_to(
                format_horizon_sentiment(sentiment, asset, horizon),
                update,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(
                "Crypto horizon command replied: asset=%s horizon=%s found=%s sent=%s",
                asset,
                horizon,
                sentiment is not None,
                sent,
            )
        except Exception as e:
            logger.exception("Crypto horizon sentiment failed")
            await self.listener.reply_to(f"Erreur sentiment {asset} {horizon}: {e}", update)

    async def _cmd_crypto_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        command = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0].lower()
        asset = command.upper()

        logger.info("Crypto markets search command received: asset=%s", asset)

        try:
            client = self.listener._scanner.client if (self.listener and self.listener._scanner) else None
            if not client:
                from utils.polymarket_client import PolymarketClient
                client = PolymarketClient()

            # Resolve user search ticker to full asset name for Polymarket API search
            search_query = {
                "BTC": "Bitcoin",
                "ETH": "Ethereum",
                "SOL": "Solana",
                "XRP": "Ripple"
            }.get(asset, asset)

            # Search active markets for this asset (increased limit to scan more candidates)
            markets = client.search_markets(search_query, limit=40)

            # Use market classifier to filter out unrelated fuzzy search results
            from utils.crypto_market_intelligence import CryptoMarketIntelligence
            classifier = CryptoMarketIntelligence()

            # Filter active, open, and strictly asset-matching markets
            active_markets = [
                m for m in markets
                if m.active and not m.closed and classifier._classify_asset(m) == asset
            ]

            if not active_markets:
                await self.listener.reply_to(f"🔍 Aucun marché actif trouvé pour {asset}.", update)
                return

            lines = [
                f"📡 *MARCHÉS ACTIFS POUR {asset}* 📡",
                "────────────────────────",
            ]
            for i, m in enumerate(active_markets[:8], 1):
                try:
                    pct = m.probability_pct
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    lines.extend([
                        f"{i}. *{m.question[:80]}*",
                        f"   {bar} `{pct:.0f}%` | `${m.yes_price:.3f}`",
                        f"   Slug: `{m.slug}`",
                        "",
                    ])
                except Exception:
                    lines.extend([
                        f"{i}. *{m.question[:80]}*",
                        f"   Slug: `{m.slug}`",
                        "",
                    ])

            lines.append("────────────────────────")
            lines.append(f"Utilise `BUY <slug> <prix>` pour placer un ordre papier.")

            await self.listener.reply_to(
                "\n".join(lines).strip(),
                update,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error in crypto markets search handler: {e}")
            await self.listener.reply_to(f"❌ Erreur lors de la recherche des marchés {asset}.", update)

    async def _cmd_all_crypto_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return

        logger.info("All crypto markets search command received")

        try:
            client = self.listener._scanner.client if (self.listener and self.listener._scanner) else None
            if not client:
                from utils.polymarket_client import PolymarketClient
                client = PolymarketClient()

            # Fetch top 100 markets sorted by volume to get the best ones
            markets = client.list_markets(limit=100, sort_by="volume")

            # Use market classifier to filter for crypto markets
            from utils.crypto_market_intelligence import CryptoMarketIntelligence
            classifier = CryptoMarketIntelligence()

            # Filter active, open, and strictly crypto-classified markets
            active_crypto_markets = [
                m for m in markets
                if m.active and not m.closed and classifier._classify_asset(m) != "OTHER"
            ]

            if not active_crypto_markets:
                await self.listener.reply_to("🔍 Aucun marché crypto actif trouvé parmi les tops volumes.", update)
                return

            lines = [
                "📡 *TOUS LES MARCHÉS CRYPTO ACTIFS* 📡",
                "────────────────────────",
            ]
            for i, m in enumerate(active_crypto_markets[:10], 1):
                asset_label = classifier._classify_asset(m)
                try:
                    pct = m.probability_pct
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    lines.extend([
                        f"{i}. *[{asset_label}] {m.question[:80]}*",
                        f"   {bar} `{pct:.0f}%` | `${m.yes_price:.3f}`",
                        f"   Slug: `{m.slug}`",
                        "",
                    ])
                except Exception:
                    lines.extend([
                        f"{i}. *[{asset_label}] {m.question[:80]}*",
                        f"   Slug: `{m.slug}`",
                        "",
                    ])

            lines.append("────────────────────────")
            lines.append(f"Utilise `BUY <slug> <prix>` pour placer un ordre papier.")

            await self.listener.reply_to(
                "\n".join(lines).strip(),
                update,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error in all crypto markets search handler: {e}")
            await self.listener.reply_to("❌ Erreur lors de la recherche globale des marchés crypto.", update)

    async def _cmd_updown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return

        args = context.args
        target_asset = args[0].upper().strip() if args else None

        logger.info("UpDown crypto markets search command received: target_asset=%s", target_asset)

        try:
            client = self.listener._scanner.client if (self.listener and self.listener._scanner) else None
            if not client:
                from utils.polymarket_client import PolymarketClient
                client = PolymarketClient()

            # Helper to resolve market prices resiliantly
            def resolve_prices(m) -> tuple[float, float]:
                yes = 0.0
                no = 0.0
                try:
                    yes = float(m.yes_price)
                    no = float(m.no_price)
                except Exception:
                    pass
                if yes == 0.0 and no == 0.0:
                    try:
                        if len(m.outcome_prices) >= 2:
                            yes = m.outcome_prices[0]
                            no = m.outcome_prices[1]
                    except Exception:
                        pass
                if yes == 0.0 and no == 0.0:
                    try:
                        yes_token = m.yes_token_id
                        if yes_token:
                            mid = client.get_midpoint(yes_token)
                            if mid > 0.0:
                                yes = mid
                                no = 1.0 - mid
                    except Exception:
                        pass
                return yes, no

            # Fetch candidates from multiple sources to be absolutely exhaustive
            all_markets = []

            try:
                all_markets.extend(client.list_markets(limit=250, sort_by="volume"))
            except Exception as e:
                logger.error(f"Error fetching list_markets: {e}")

            # Always search for the most common target terms to guarantee complete market discoverability
            search_terms = ["updown", "above", "below", "price-at", "price-by", "Bitcoin", "Ethereum", "Solana", "Ripple"]

            # If target_asset is explicitly provided, make sure we also search for its specific full name
            if target_asset:
                full_name = {
                    "BTC": "Bitcoin",
                    "ETH": "Ethereum",
                    "SOL": "Solana",
                    "XRP": "Ripple"
                }.get(target_asset, target_asset)
                if full_name not in search_terms:
                    search_terms.append(full_name)

            for term in search_terms:
                try:
                    all_markets.extend(client.search_markets(term, limit=40))
                except Exception as e:
                    logger.error(f"Error searching {term}: {e}")

            # Deduplicate by slug
            unique_markets = {}
            for m in all_markets:
                if m.active and not m.closed:
                    unique_markets[m.slug] = m

            # Use market classifier to filter for crypto and up-down patterns
            from utils.crypto_market_intelligence import CryptoMarketIntelligence
            classifier = CryptoMarketIntelligence()

            updown_markets = []
            for m in unique_markets.values():
                asset_label = classifier._classify_asset(m)
                if asset_label == "OTHER":
                    continue

                # Check if it matches requested asset (if provided)
                if target_asset and asset_label != target_asset:
                    continue

                # Up-down patterns filter
                text = f"{m.slug} {m.question} {m.description}".lower()
                updown_terms = (
                    "updown", "up-down", "up-or-down", "above", "below",
                    "price-at-", "price-by-", "higher-than", "higher", "lower",
                    "under", "over", "hit", "strike"
                )
                if any(term in text for term in updown_terms) or ("$" in m.question):
                    updown_markets.append((asset_label, m))

            # Sort the final list by volume so the most active ones are first
            updown_markets.sort(key=lambda item: item[1].volume, reverse=True)

            if not updown_markets:
                asset_suffix = f" pour {target_asset}" if target_asset else ""
                await self.listener.reply_to(f"🔍 Aucun marché type UpDown actif trouvé{asset_suffix}.", update)
                return

            header = f"📡 *MARCHÉS CRYPTO UPDOWN ACTIFS ({target_asset})* 📡" if target_asset else "📡 *TOUS LES MARCHÉS CRYPTO UPDOWN ACTIFS* 📡"
            lines = [
                header,
                "────────────────────────",
            ]
            for i, (asset_label, m) in enumerate(updown_markets[:15], 1):
                try:
                    yes, no = resolve_prices(m)
                    pct = max(yes, no) * 100
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    lines.extend([
                        f"{i}. *[{asset_label}] {m.question[:80]}*",
                        f"   {bar} `{pct:.0f}%` | `YES: ${yes:.3f} | NO: ${no:.3f}`",
                        f"   Slug: `{m.slug}`",
                        "",
                    ])
                except Exception:
                    lines.extend([
                        f"{i}. *[{asset_label}] {m.question[:80]}*",
                        f"   Slug: `{m.slug}`",
                        "",
                    ])

            lines.append("────────────────────────")
            lines.append(f"Utilise `BUY <slug> <prix>` pour placer un ordre papier.")

            await self.listener.reply_to(
                "\n".join(lines).strip(),
                update,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error in updown markets search handler: {e}")
            await self.listener.reply_to("❌ Erreur lors de la recherche des marchés type UpDown.", update)

    async def _cmd_ai(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return

        full_text = update.effective_message.text or ""
        parts = full_text.split(None, 1)
        prompt = parts[1].strip() if len(parts) > 1 else ""

        if not prompt or prompt.lower() == "status":
            from utils.ai_specialists import list_ai_specialists
            specialists = list_ai_specialists()
            msg = "🧠 *AI Agents Status*\n\n"
            msg += f"• Specialists: {len(specialists)}\n"
            msg += "• LLM Council: Active (OpenRouter)\n"
            msg += "• Memory: Persistent (SQLite/DuckDB)\n"
            await self.listener.reply_to(msg, update)
        elif prompt.lower() == "errors":
            # Tail logs/pm2-error.log
            try:
                with open("logs/pm2-error.log", "r") as f:
                    lines = f.readlines()[-10:]
                msg = "🚨 *Latest AI/System Errors*\n\n```\n" + "".join(lines) + "\n```"
                await self.listener.reply_to(msg, update)
            except Exception as e:
                await self.listener.reply_to(f"Failed to read logs: {e}", update)
        else:
            # Run the LLM Council
            status_msg = None
            try:
                status_msg = await self.listener.reply_to(
                    "🤔 *Lobstar AI Council is reflecting...*\n\n"
                    "• Stage 1: Independent specialist opinions...\n"
                    "• Stage 2: Anonymized cross-reviews...\n"
                    "• Stage 3: Synthesis by Chairman...",
                    update,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to send initial AI council status msg: {e}")

            try:
                from utils.llm_council import LLMCouncil, resolve_openrouter_api_key
                council = LLMCouncil()
                api_key = resolve_openrouter_api_key(council.config)

                if not api_key:
                    guardrail = council.config.get("safety", {}).get("trading_guardrail", "LLM Council output is advisory only.")
                    mock_res = (
                        "🚨 *OPENROUTER API KEY MISSING*\n"
                        "To enable live multi-agent LLM Council synthesis, set `OPENROUTER_API_KEY` in your `.env` or Vault.\n\n"
                        "💡 *Simulated Council Response:*\n"
                        f"Analyzing prompt: `{prompt}`\n\n"
                        "• *Market Sentiment (Mock)*: The multi-agent swarm detects strong bullish momentum under high volatility. BTC/USD orderbook imbalance favors makers, with short-term support established at key VWAP levels.\n"
                        "• *Specialists Consensus*: ML models project a temporary range-bound consolidation before an upward breakout. Positions should be sized conservatively under the current PAPER mode capital preservation guidelines.\n\n"
                        f"🛡️ _Advisory only: {guardrail}_"
                    )
                    if status_msg:
                        try:
                            await status_msg.edit_text(mock_res, parse_mode=ParseMode.MARKDOWN)
                        except Exception:
                            await self.listener.reply_to(mock_res, update, parse_mode=ParseMode.MARKDOWN)
                    else:
                        await self.listener.reply_to(mock_res, update, parse_mode=ParseMode.MARKDOWN)
                    return

                res = await council.ask(prompt)
                guardrail = council.config.get("safety", {}).get("trading_guardrail", "LLM Council output is advisory only.")
                final_msg = (
                    "🧠 *LOBSTAR AI COUNCIL SYNTHESIS*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"*Question*: {prompt}\n\n"
                    f"{res.final_answer}\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🛡️ _{guardrail}_"
                )
                if status_msg:
                    try:
                        await status_msg.edit_text(final_msg, parse_mode=ParseMode.MARKDOWN)
                    except Exception:
                        await self.listener.reply_to(final_msg, update, parse_mode=ParseMode.MARKDOWN)
                else:
                    await self.listener.reply_to(final_msg, update, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Error executing AI council prompt: {e}")
                err_msg = f"❌ *AI Council Error:* {str(e)}"
                if status_msg:
                    try:
                        await status_msg.edit_text(err_msg, parse_mode=ParseMode.MARKDOWN)
                    except Exception:
                        await self.listener.reply_to(err_msg, update, parse_mode=ParseMode.MARKDOWN)
                else:
                    await self.listener.reply_to(err_msg, update, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._hmm:
            await self.listener.reply_to("HMM Filter not attached.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            # Logic from MCP get_market_regime
            from utils.regime_utils import get_regime_label
            label = get_regime_label(self.listener._hmm, "SOL")
            msg = "📊 *Model Status (HMM Filter)*\n\n"
            msg += f"• Current Regime: `{label}`\n"
            msg += f"• Trading Allowed: {'✅' if self.listener._hmm.is_trading_allowed(None)[0] else '❌'}\n"
            await self.listener.reply_to(msg, update)
        elif sub == "metrics":
            if not self.listener._store:
                await self.listener.reply_to("Feature Store not attached.", update)
                return
            stats = self.listener._store.get_stats()
            msg = "📈 *Model Metrics (Feature Store)*\n\n"
            for k, v in stats.items():
                msg += f"• {k}: `{v}`\n"
            await self.listener.reply_to(msg, update)
        elif sub == "validate":
            from utils.model_validator import ModelValidator
            validator = ModelValidator(self.listener._store)
            ticker = args[1] if len(args) > 1 else "SOL"
            report = validator.run_health_check(ticker, "default_v1")
            msg = f"🧪 *Model Validation: {ticker}*\n\n"
            msg += f"• Health: `{report.get('health', 'UNKNOWN')}`\n"
            msg += f"• P-Value: `{report.get('drift_report', {}).get('p_value', 0):.4f}`\n"
            msg += f"• Drift: `{'YES' if report.get('drift_report', {}).get('drift_detected') else 'NO'}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown model subcommand: {sub}", update)

    async def _cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._ledger:
            await self.listener.reply_to("Ledger not attached.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            cap = self.listener._ledger.get_capital_summary()
            msg = "🛡️ *Risk & Capital Status*\n\n"
            msg += f"• Total: `${cap.get('total_capital', 0):,.2f}`\n"
            msg += f"• Available: `${cap.get('available_capital', 0):,.2f}`\n"
            msg += f"• Allocated: `{cap.get('allocated_pct', 0)}%`\n"
            await self.listener.reply_to(msg, update)
        elif sub in ("kill", "freeze"):
            # Mocking the MCP emergency_circuit_breaker
            from mcp_agents.mcp_server import emergency_circuit_breaker
            res = emergency_circuit_breaker("ENGAGE")
            await self.listener.reply_to(f"🛑 *CIRCUIT BREAKER ENGAGED*\n\n{res.get('message')}", update)
        elif sub in ("resume", "unfreeze"):
            from mcp_agents.mcp_server import emergency_circuit_breaker
            res = emergency_circuit_breaker("DISENGAGE")
            await self.listener.reply_to(f"✅ *CIRCUIT BREAKER DISENGAGED*\n\n{res.get('message')}", update)
        elif sub == "exposure":
            if not self.listener._risk:
                await self.listener.reply_to("Risk Engine not attached.", update)
                return
            msg = "📉 *Portfolio Exposure*\n\n"
            msg += f"• Net Beta Exposure: `{self.listener._risk.net_beta_exposure_pct:.2f}%`\n"
            msg += f"• Positions: `{len(self.listener._risk._exposures)}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown risk subcommand: {sub}", update)

    async def _cmd_clob(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "arb"

        if sub == "arb":
            # Call MCP get_arbitrage_opportunities
            from mcp_agents.mcp_server import get_arbitrage_opportunities
            res = get_arbitrage_opportunities()
            count = res.get("opportunity_count", 0)
            msg = f"⚖️ *CLOB Arbitrage Scanner*\n\nFound `{count}` opportunities.\n"
            if count > 0:
                for opp in res.get("opportunities", [])[:5]:
                    msg += f"• {opp.get('type')}: `{opp.get('market_id')}` (Conf: {opp.get('confidence'):.2f})\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown CLOB subcommand: {sub}", update)

    async def _cmd_whales(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "leaderboard"

        from utils.polymarket_crawler.traders import discover_top_traders
        from utils.polymarket_crawler.trader_formatters import fmt_expert_leaderboard, fmt_trader_alert_html

        if sub == "leaderboard":
            cat = args[1].upper() if len(args) > 1 else "OVERALL"
            msg_wait = await self.listener.reply_to(f"🔍 Fetching {cat} leaderboard...", update)
            results = discover_top_traders(categories=[cat], limit=5)
            traders = results.get(cat, [])
            report = fmt_expert_leaderboard(traders, cat, 5)
            await self.listener.reply_to(f"🏆 *Top Traders: {cat}*\n\n{report}", update)
        elif sub == "analyze":
            if len(args) < 2:
                await self.listener.reply_to("Usage: `/whales analyze <address>`", update)
                return
            wallet = args[1]
            msg_wait = await self.listener.reply_to(f"🔍 Analyzing whale: `{wallet[:10]}...`", update)
            from utils.polymarket_crawler.traders import TraderScraper
            scraper = TraderScraper()
            # Simplified analysis for Telegram
            positions = scraper.fetch_closed_positions(wallet)
            total_pnl = sum(p.realized_pnl for p in positions)
            msg = f"🐋 *Whale Analysis: {wallet[:10]}...*\n\n"
            msg += f"• Positions: `{len(positions)}`\n"
            msg += f"• Total PnL: `${total_pnl:,.2f}`\n\n"
            msg += "*Recent Wins:*\n"
            for p in positions[:5]:
                msg += f"• {p.title[:30]}... | `${p.realized_pnl:,.0f}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown whales subcommand: {sub}. Use `leaderboard` or `analyze`.", update)

    async def _cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._ledger:
            await self.listener.reply_to("Ledger not attached.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            mode = self.listener._ledger.get_execution_mode()
            metrics = self.listener._executor.get_metrics() if self.listener._executor else {}
            msg = "🎯 *Trading Engine Status*\n\n"
            msg += f"• Mode: `{mode}`\n"
            msg += f"• Fill Rate: `{metrics.get('fill_rate_pct', 0)}%`\n"
            msg += f"• Queue Depth: `{metrics.get('queue_depth', 0)}`\n"
            await self.listener.reply_to(msg, update)
        elif sub in ("paper", "shadow", "prod"):
            if len(args) > 1 and args[1] == "on":
                new_mode = sub.upper()
                self.listener._ledger.set_execution_mode(new_mode)
                await self.listener.reply_to(f"🔄 Execution mode changed to: `{new_mode}`", update)
            else:
                await self.listener.reply_to(f"Usage: `/trade {sub} on`", update)
        elif sub == "pnl":
            perf = self.listener._ledger.get_performance_summary(mode=self.listener._ledger.get_execution_mode())
            if perf and perf.get("total_trades", 0) > 0:
                wr = perf["win_rate"] * 100
                msg = "💰 *PnL Report*\n\n"
                msg += f"• Net PnL: `${perf['total_net_pnl']:,.2f}`\n"
                msg += f"• Win Rate: `{wr:.1f}%`\n"
                msg += f"• Trades: `{perf['total_trades']}`\n"
                msg += f"• Profit Factor: `{perf['profit_factor']:.2f}`\n"
                msg += f"• Avg Win: `${perf['avg_win']:.2f}`\n"
                msg += f"• Avg Loss: `${perf['avg_loss']:.2f}`\n"
            else:
                msg = "💰 *PnL Report*\n\nNo closed trades yet. Use paper trading to generate PnL data."
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown trade subcommand: {sub}", update)

    async def _cmd_mcp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            from mcp_agents.mcp_server import mcp
            msg = "🔌 *MCP Status*\n\n"
            msg += f"• Server: `quant-agentic-mcp`\n"
            msg += f"• Transport: `stdio`\n"
            msg += f"• Tools: `{len(mcp.list_tools())}`\n"
            await self.listener.reply_to(msg, update)
        elif sub == "tools":
            from mcp_agents.mcp_server import mcp
            tools = mcp.list_tools()
            msg = "🛠️ *MCP Tools*\n\n"
            for t in tools:
                msg += f"• `{t.name}`: {t.description[:50]}...\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown MCP subcommand: {sub}", update)

    async def _cmd_dev(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "metrics"

        if sub == "metrics":
            # System metrics
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            msg = "⚙️ *Dev Systems Metrics*\n\n"
            msg += f"• CPU Usage: `{cpu}%`\n"
            msg += f"• RAM Usage: `{mem}%`\n"
            msg += f"• Uptime: `{self.listener._fmt_uptime()}`\n"
            if self.listener._executor:
                metrics = self.listener._executor.get_metrics()
                msg += f"• Slippage (Sim): `${metrics.get('simulated_slippage_usd', 0):,.2f}`\n"
                msg += f"• Spread (Sim): `${metrics.get('simulated_spread_usd', 0):,.2f}`\n"
            await self.listener.reply_to(msg, update)
        elif sub == "logs":
            try:
                with open("logs/pm2-out.log", "r") as f:
                    lines = f.readlines()[-20:]
                msg = "📜 *System Logs*\n\n```\n" + "".join(lines) + "\n```"
                await self.listener.reply_to(msg, update)
            except Exception as e:
                await self.listener.reply_to(f"Failed to read logs: {e}", update)
        elif sub == "cleanup":
            from utils.data_archiver import DataArchiver
            archiver = DataArchiver()
            res = archiver.run_maintenance_cycle()
            msg = "🧹 *Maintenance Cycle Complete*\n\n"
            msg += f"• Tables Archived: `{len(res['microstructure'].get('tables_exported', []))}`\n"
            msg += f"• Log Files: `{res['logs'].get('files_compressed', 0)}` compressed\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown dev subcommand: {sub}", update)

    async def _cmd_audit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        from utils.snapshot_manager import get_snapshot_manager
        sm = get_snapshot_manager()

        args = context.args
        cat = args[0] if args else "TRADING"

        snap = sm.get_latest(cat)
        if not snap:
            await self.listener.reply_to(f"No snapshots found for category: `{cat}`", update)
            return

        msg = f"🔍 *Snapshot Audit: {cat}*\n\n"
        msg += f"```json\n{json.dumps(snap, indent=2)[:3000]}\n```"
        await self.listener.reply_to(msg, update)

    async def _cmd_freeze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._cmd_risk(update, context=context) # Alias to risk kill

    async def _cmd_unfreeze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._cmd_risk(update, context=context) # Alias to risk resume

    async def _cmd_liquidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._executor:
            await self.listener.reply_to("Executor not attached.", update)
            return

        res = await self.listener._executor.liquidate_all()
        msg = "🚨 *LIQUIDATION EXECUTED*\n\n"
        msg += f"• Status: `{res.get('status')}`\n"
        msg += f"• Orders Cancelled: `{res.get('cancelled_orders')}`\n"
        msg += f"• Message: {res.get('message')}\n"
        await self.listener.reply_to(msg, update)

    async def _cmd_gsd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return

        args = context.args
        if not args:
            await self.listener.reply_to(
                "❌ *Usage*: `/gsd [--dry-run] [description de l'issue]`\n"
                "Exemple: `/gsd --dry-run timing delay in websocket`",
                update,
                parse_mode=ParseMode.MARKDOWN
            )
            return

        dry_run = False
        if args[0] == "--dry-run":
            dry_run = True
            args = args[1:]

        issue_text = " ".join(args)
        if not issue_text:
            await self.listener.reply_to("❌ Description de l'issue manquante.", update)
            return

        status_msg = await self.listener.reply_to(
            f"🚀 *Lancement du GSD Problem Solver Agent...*\n"
            f"🎯 *Cible*: `{issue_text}`\n"
            f"⚙️ *Dry-Run*: `{dry_run}`\n\n"
            f"⏳ Traitement des phases (Intake, Context, Implementation, Verification)...",
            update,
            parse_mode=ParseMode.MARKDOWN
        )

        try:
            from core.services.gsd_problem_solver import GSDProblemSolverAgent
            solver = GSDProblemSolverAgent()
            report = await solver.solve_issue(
                issue_text=issue_text,
                dry_run=dry_run,
                max_iterations=3,
            )

            status_str = "🟢 RESOLVED & VERIFIED ✅" if report.ok else "🔴 FAILED & ROLLED BACK ❌"

            intake = report.phases.get("intake", {})
            context_p = report.phases.get("context", {})
            handoff = report.phases.get("handoff", {})

            msg = (
                f"📊 *GSD RESOLUTION PROCESS COMPLETE*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ *Statut*: `{status_str}`\n\n"
                f"📋 *Phase A (Intake)*:\n"
                f"• Goal: {intake.get('goal')}\n"
                f"• Scope: {', '.join(intake.get('scope', []))[:100]}...\n\n"
                f"🔍 *Phase B (Context)*:\n"
                f"• Target Files: `{', '.join(context_p.get('priority_files', []))}`\n\n"
                f"🛠️ *Phase C & D (Code)*:\n"
                f"• Modified Files: `{', '.join(report.changed_files) or 'None'}`\n"
                f"• Tests Executed: `{', '.join(report.tests_run) or 'None'}`\n"
                f"• Residual Risks: `{report.residual_risks}`\n\n"
                f"📤 *Phase E (Handoff)*:\n"
                f"• Summary: {handoff.get('summary')}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📝 _Rapport complet enregistré sous user_data/reports/gsd_issue_resolver_report.md_"
            )
            await status_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Error in Telegram GSD command: {e}")
            await status_msg.edit_text(f"❌ *Erreur GSD Solver Agent:* {str(e)}", parse_mode=ParseMode.MARKDOWN)

    # NEW WALLET / TRANSFER / POLYMARKET / SIGNALS / MARKETS COMMANDS

    async def _cmd_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return

        args = context.args
        sub = args[0].lower() if args else "help"

        if sub == "balance":
            if not self.wallet_manager:
                await self.listener.reply_to("💾 Wallet manager not attached.", update)
                return
            from telegram_scraper.handlers.wallet_handler import handle_wallet_balance
            await handle_wallet_balance(update, context, self.wallet_manager)
        elif sub == "health":
            if not self.wallet_manager:
                await self.listener.reply_to("💾 Wallet manager not attached.", update)
                return
            from telegram_scraper.handlers.wallet_handler import handle_wallet_health
            await handle_wallet_health(update, context, self.wallet_manager)
        elif sub == "add":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_add
            await handle_wallet_add(update, context)
            if self.access_control:
                try:
                    from utils.credential_manager import CredentialManager
                    mgr = CredentialManager()
                    chat_id = update.effective_chat.id
                    if mgr.user_exists(chat_id):
                        user_data = mgr.load_user(chat_id)
                        self.access_control.assigner_wallet_a_chat(chat_id, user_data["address"])
                        logger.info(f"Wallet {user_data['address']} assigned to chat_id {chat_id}")
                except Exception as e:
                    logger.warning(f"Failed to assign wallet: {e}")
        elif sub == "import":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_import
            await handle_wallet_import(update, context)
            if self.access_control:
                try:
                    from utils.credential_manager import CredentialManager
                    mgr = CredentialManager()
                    chat_id = update.effective_chat.id
                    if mgr.user_exists(chat_id):
                        user_data = mgr.load_user(chat_id)
                        self.access_control.assigner_wallet_a_chat(chat_id, user_data["address"])
                        logger.info(f"Wallet {user_data['address']} assigned to chat_id {chat_id}")
                except Exception as e:
                    logger.warning(f"Failed to assign wallet: {e}")
        elif sub == "set-proxy":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_set_proxy
            await handle_wallet_set_proxy(update, context)
        elif sub == "list":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_list
            await handle_wallet_list(update, context)
        elif sub == "show":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_show
            await handle_wallet_show(update, context)
        elif sub == "delete":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_delete
            await handle_wallet_delete(update, context)
        elif sub == "use":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_use
            await handle_wallet_use(update, context)
            if self.access_control:
                try:
                    from utils.credential_manager import CredentialManager
                    mgr = CredentialManager()
                    chat_id = update.effective_chat.id
                    if mgr.user_has_any_wallet(chat_id):
                        wallet_type = mgr.get_active_wallet_type(chat_id)
                        user_data = mgr.load_user(chat_id, wallet_type)
                        self.access_control.assigner_wallet_a_chat(chat_id, user_data["address"])
                        logger.info(f"Active wallet {wallet_type} assigned to chat_id {chat_id}")
                except Exception as e:
                    logger.warning(f"Failed to assign wallet: {e}")
        elif sub == "status":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_status
            await handle_wallet_status(update, context)
        elif sub == "backup":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_backup
            await handle_wallet_backup(update, context)
        elif sub == "swap":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_swap
            await handle_wallet_swap(update, context)
        elif sub == "help":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_help
            await handle_wallet_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown wallet subcommand: {sub}. Use `/wallet help`", update)

    async def _cmd_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.transfer_manager:
            await self.listener.reply_to("📤 Transfer manager not attached.", update)
            return

        args = context.args
        sub = args[0].lower() if args else "help"

        if sub == "help":
            from telegram_scraper.handlers.transfer_handler import handle_transfer_help
            await handle_transfer_help(update, context)
        else:
            # Assume it's an amount (they forgot to use help)
            from telegram_scraper.handlers.transfer_handler import handle_transfer
            await handle_transfer(update, context, self.transfer_manager)

    async def _cmd_polymarket(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.order_manager:
            await self.listener.reply_to("🎲 Polymarket order manager not attached.", update)
            return

        args = context.args
        sub = args[0].lower() if args else "help"

        if sub == "bet":
            from telegram_scraper.handlers.polymarket_handler import handle_polymarket_bet
            await handle_polymarket_bet(update, context, self.order_manager)
        elif sub == "claim":
            from telegram_scraper.handlers.polymarket_handler import handle_polymarket_claim
            await handle_polymarket_claim(update, context, self.order_manager)
        elif sub == "help":
            from telegram_scraper.handlers.polymarket_handler import handle_polymarket_help
            await handle_polymarket_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown polymarket subcommand: {sub}. Use `/polymarket help`", update)

    async def _cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return

        args = context.args
        sub = args[0].lower() if args else "help"

        if sub == "all":
            if not self.signal_generator:
                await self.listener.reply_to("📊 Signal generator not attached.", update)
                return
            from telegram_scraper.handlers.signals_handler import handle_signals_all
            await handle_signals_all(update, context, self.signal_generator)
        elif sub == "matrix":
            ticker = args[1].upper() if len(args) > 1 else "BTC"
            from telegram_scraper.handlers.signals_handler import handle_signals_matrix
            await handle_signals_matrix(update, context, ticker)
        elif sub == "help":
            from telegram_scraper.handlers.signals_handler import handle_signals_help
            await handle_signals_help(update, context)
        else:
            if not self.signal_generator:
                await self.listener.reply_to("📊 Signal generator not attached.", update)
                return
            from telegram_scraper.handlers.signals_handler import handle_signals
            await handle_signals(update, context, self.signal_generator)

    async def _cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return

        args = context.args
        sub = args[0].lower() if args else "help"

        standalone_commands = {"discover", "opportunities", "contrarian", "vcp", "canslim", "help"}

        if sub not in standalone_commands and not self.market_reader:
            await self.listener.reply_to("📈 Market reader not attached.", update)
            return

        if sub == "list":
            from telegram_scraper.handlers.markets_handler import handle_markets_list
            await handle_markets_list(update, context, self.market_reader)
        elif sub == "feed":
            from telegram_scraper.handlers.markets_handler import handle_markets_feed
            await handle_markets_feed(update, context, self.market_reader)
        elif sub == "info":
            from telegram_scraper.handlers.markets_handler import handle_markets_info
            await handle_markets_info(update, context, self.market_reader)
        elif sub == "search":
            from telegram_scraper.handlers.markets_handler import handle_markets_search
            await handle_markets_search(update, context, self.market_reader)
        elif sub == "discover":
            from telegram_scraper.handlers.markets_handler import handle_markets_discover
            await handle_markets_discover(update, context)
        elif sub == "opportunities":
            from telegram_scraper.handlers.markets_handler import handle_markets_opportunities
            await handle_markets_opportunities(update, context)
        elif sub == "contrarian":
            from telegram_scraper.handlers.markets_handler import handle_markets_contrarian
            await handle_markets_contrarian(update, context)
        elif sub == "vcp":
            from telegram_scraper.handlers.markets_handler import handle_markets_vcp
            await handle_markets_vcp(update, context)
        elif sub == "canslim":
            from telegram_scraper.handlers.markets_handler import handle_markets_canslim
            await handle_markets_canslim(update, context)
        elif sub == "help":
            from telegram_scraper.handlers.markets_handler import handle_markets_help
            await handle_markets_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown markets subcommand: {sub}. Use `/markets help`", update)

    async def _cmd_feed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.market_reader:
            await self.listener.reply_to("📈 Market reader not attached.", update)
            return
        from telegram_scraper.handlers.markets_handler import handle_markets_feed
        await handle_markets_feed(update, context, self.market_reader)

    async def _cmd_manual(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args
        if args:
            target = args[0].lower().lstrip("/")

            # Special case for dynamic crypto horizons
            import re
            horizon_match = re.fullmatch(r"([a-z]+)(5|15|1h|4h|1d)", target)
            if horizon_match:
                asset, horizon = horizon_match.group(1).upper(), horizon_match.group(2)
                text = (
                    f"📈 *MANUEL LOBSTAR — /{target}*\n"
                    "────────────────────────\n"
                    f"📂 *Catégorie* : `MARKETS`\n"
                    f"📝 *Description* : Sentiment du marché crypto pour {asset} sur l'horizon {horizon}.\n"
                    f"⚡ *Usage* : `/{target}`\n"
                    f"💡 *Exemple* : `/{target}`\n\n"
                    f"ℹ️ *Notes* : Construit des probabilités calibrées à partir de Polymarket.\n"
                    "────────────────────────"
                )
                await self.listener.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
                return

            if target in COMMAND_REGISTRY:
                info = COMMAND_REGISTRY[target]
                text = (
                    f"📖 *MANUEL LOBSTAR — /{target}*\n"
                    "────────────────────────\n"
                    f"📂 *Catégorie* : `{info['category']}`\n"
                    f"📝 *Description* : {info['description']}\n"
                    f"⚡ *Usage* : `{info['usage']}`\n"
                    f"💡 *Exemple* : `{info['example']}`\n\n"
                    f"ℹ️ *Notes* : {info['notes']}\n"
                    "────────────────────────"
                )
                await self.listener.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
                return
            else:
                await self.listener.reply_to(f"🔍 Commande `/{target}` introuvable. Tapez `/man` pour voir le menu.", update)
                return

        from utils.help_manager import HelpManager
        chat_id = update.effective_chat.id
        is_admin = self.access_control.est_admin(chat_id) if self.access_control else False
        await HelpManager.send_menu(update, context, is_admin)

    async def _cmd_paper(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        ticker = args[0].upper() if args else "BTC"
        from telegram_scraper.handlers.signals_handler import handle_paper_test
        await handle_paper_test(update, context, ticker)
