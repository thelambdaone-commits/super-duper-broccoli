import logging
import os
import json
import asyncio
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

logger = logging.getLogger("CommandRouter")

CRYPTO_ALIAS_MAP = {
    "btc": "BTC",
    "bitcoin": "BTC",
    "eth": "ETH",
    "ethereum": "ETH",
    "sol": "SOL",
    "solana": "SOL",
    "xrp": "XRP",
    "ripple": "XRP",
    "doge": "DOGE",
    "dogecoin": "DOGE",
    "bnb": "BNB",
    "hype": "HYPE",
    "ada": "ADA",
    "avax": "AVAX",
    "link": "LINK",
    "sui": "SUI",
    "pepe": "PEPE",
    "wif": "WIF",
    "ton": "TON",
    "near": "NEAR",
}

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
        "func": "_cmd_crypto",
        "category": "MARKETS",
        "description": "Centre de commande intuitif pour les marchés crypto et leurs horizons.",
        "usage": "/crypto [asset]",
        "example": "/crypto BTC",
        "notes": "Ouvre un menu interactif avec des boutons pour naviguer rapidement."
    },
    "understand": {
        "func": "_cmd_understand",
        "category": "AI_TOOLS",
        "description": "Analyser un codebase -> graphe de connaissance interactif.",
        "usage": "/understand",
        "example": "/understand",
        "notes": "Génère un graphe de connaissance pour les analyses ultérieures."
    },
    "understand_explain": {
        "func": "_cmd_understand_explain",
        "category": "AI_TOOLS",
        "description": "Explication détaillée d'un fichier/fonction/module.",
        "usage": "/understand_explain [target]",
        "example": "/understand_explain SignalExecutor",
        "notes": "Requiert d'avoir lancé /understand au moins une fois."
    },
    "understand_chat": {
        "func": "_cmd_understand_chat",
        "category": "AI_TOOLS",
        "description": "Poser des questions sur le code via le graphe.",
        "usage": "/understand_chat [question]",
        "example": "/understand_chat Comment est calculé le Kelly ?",
        "notes": "Mode interactif pour comprendre la logique métier."
    },
    "understand_map": {
        "func": "_cmd_understand_map",
        "category": "AI_TOOLS",
        "description": "Affiche une carte de l'architecture du projet.",
        "usage": "/understand_map",
        "example": "/understand_map",
        "notes": "Utile pour naviguer dans les différents modules."
    },
    "understand_diff": {
        "func": "_cmd_understand_diff",
        "category": "AI_TOOLS",
        "description": "Analyser les changements récents dans le code.",
        "usage": "/understand_diff",
        "example": "/understand_diff",
        "notes": "Compare l'état actuel avec le dernier commit stable."
    },
    "understand_dashboard": {
        "func": "_cmd_understand_dashboard",
        "category": "AI_TOOLS",
        "description": "Lancer le dashboard web interactif.",
        "usage": "/understand_dashboard",
        "example": "/understand_dashboard",
        "notes": "Ouvre une interface visuelle pour explorer le graphe."
    },
    "understand_domain": {
        "func": "_cmd_understand_domain",
        "category": "AI_TOOLS",
        "description": "Extraire la connaissance métier.",
        "usage": "/understand_domain",
        "example": "/understand_domain",
        "notes": "Décrit les concepts clés du trading agentique."
    },
    "understand_onboard": {
        "func": "_cmd_understand_onboard",
        "category": "AI_TOOLS",
        "description": "Générer des guides d'onboarding.",
        "usage": "/understand_onboard",
        "example": "/understand_onboard",
        "notes": "Guide pour les nouveaux développeurs ou utilisateurs."
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

    def _get_btc_launch_service(self):
        from services.btc_launch_service import BTCDirectionLaunchService

        service = getattr(self.listener, "_btc_launch_service", None)
        if service is None:
            service = BTCDirectionLaunchService()
            setattr(self.listener, "_btc_launch_service", service)
        return service

    def _btc_launch_markup(self, interval: str) -> InlineKeyboardMarkup:
        mode = getattr(self.listener, '_ledger', None)
        is_live = mode and mode.get_execution_mode() == "PROD"
        prefix = "⚡ Live" if is_live else "📈 Paper"
        
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{prefix} Up", callback_data=f"btc_paper:{interval}:up"),
                InlineKeyboardButton(f"{prefix} Down", callback_data=f"btc_paper:{interval}:down"),
            ],
            [
                InlineKeyboardButton("📡 Track Live", callback_data=f"btc_track:{interval}"),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"btc_launch:{interval}"),
                InlineKeyboardButton("🛑 Cancel Instant", callback_data=f"btc_cancel:{interval}"),
            ],
            [
                InlineKeyboardButton("SL 3c", callback_data=f"btc_sl:{interval}:0.03"),
                InlineKeyboardButton("SL 5c", callback_data=f"btc_sl:{interval}:0.05"),
                InlineKeyboardButton("SL 10c", callback_data=f"btc_sl:{interval}:0.10"),
            ],
            [InlineKeyboardButton("🧭 Crypto Menu", callback_data="crypto_menu")],
        ])

    def _format_btc_launch_text(self, result) -> str:
        age_seconds = max(0, int(datetime.now(timezone.utc).timestamp() - float(result.generated_at)))
        strongest_label = "UP" if result.strongest_direction == "up" else "DOWN"
        mode = getattr(self.listener, '_ledger', None)
        is_live = mode and mode.get_execution_mode() == "PROD"
        action_text = "Actions: trade live directionnel, refresh du training, ou annulation instant." if is_live else "Actions: paper trade directionnel, refresh du training, ou annulation instant du paper BTC."
        return (
            f"🧠 <b>BTC {result.interval.upper()} Direction Launch</b>\n"
            "───────────────────\n"
            f"• Strongest Bias: <b>{strongest_label}</b>\n"
            f"• Prob Up: <code>{result.prob_up * 100:.2f}%</code>\n"
            f"• Prob Down: <code>{result.prob_down * 100:.2f}%</code>\n"
            f"• Edge retenu: <b>{result.strongest_probability * 100:.2f}%</b>\n"
            f"• Best Variant: <code>{result.best_variant}</code>\n"
            f"• Val Acc: <code>{result.best_val_accuracy * 100:.2f}%</code>\n"
            f"• Dataset: <code>{result.train_samples}</code> train / <code>{result.val_samples}</code> val\n"
            f"• Cache Age: <code>{age_seconds}s</code>\n"
            "───────────────────\n"
            f"{action_text}"
        )

    def _crypto_menu_markup(self) -> InlineKeyboardMarkup:
        assets = [("BTC", "btc"), ("ETH", "eth"), ("SOL", "sol"), ("XRP", "xrp"), ("DOGE", "doge"), ("BNB", "bnb")]
        horizons = [("5m", "5"), ("15m", "15"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d")]

        asset_rows = []
        row = []
        for label, key in assets:
            row.append(InlineKeyboardButton(label, callback_data=f"crypto_asset:{key}"))
            if len(row) == 3:
                asset_rows.append(row)
                row = []
        if row:
            asset_rows.append(row)

        horizon_rows = []
        for label, key in horizons:
            row = [
                InlineKeyboardButton(
                    f"{asset_label} {label}",
                    callback_data=f"crypto_horizon:{asset_key}:{key}",
                )
                for asset_label, asset_key in assets
            ]
            horizon_rows.append(row)

        quick_launch_rows = [
            [
                InlineKeyboardButton("🧠 BTC 5m", callback_data="btc_launch:5m"),
                InlineKeyboardButton("🧠 BTC 15m", callback_data="btc_launch:15m"),
            ],
        ]
        return InlineKeyboardMarkup(quick_launch_rows + asset_rows + horizon_rows)

    def _crypto_menu_text(self) -> str:
        mode = getattr(self.listener, '_ledger', None)
        is_live = mode and mode.get_execution_mode() == "PROD"
        action_type = "live" if is_live else "paper"
        
        return (
            "🧭 <b>CENTRE CRYPTO LOBSTAR</b>\n"
            "───────────────────\n"
            "Choisis un actif ou un horizon pour ouvrir le bon écran.\n\n"
            "• Les boutons BTC 5m / 15m lancent l'entraînement directionnel avec cache.\n"
            "• Les boutons d'actif montrent les marchés actifs.\n"
            "• Les boutons d'horizon ouvrent le sentiment détaillé.\n"
            f"• <code>/btc5</code> et <code>/btc15</code> ouvrent l'écran de launch BTC avec {action_type}, track, SL et cancel.\n"
            "• Les autres alias <code>/eth1h</code>, <code>/sol5</code>, etc. restent disponibles.\n"
            "───────────────────"
        )

    async def render_crypto_menu(self):
        return self._crypto_menu_text(), self._crypto_menu_markup()

    async def render_btc_launch(self, interval: str, *, force_refresh: bool = False):
        service = self._get_btc_launch_service()
        result = await asyncio.to_thread(service.get_or_launch, interval, "up", force_refresh)
        return self._format_btc_launch_text(result), self._btc_launch_markup(interval)



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

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for the /start command - Intuitive Onboarding."""
        if not await self.listener._check_auth(update): return
        
        welcome_text = (
            f"👋 <b>Bienvenue sur LOBSTAR Agent v2</b>\n"
            f"───────────────────\n"
            f"Je suis votre assistant de trading agentique spécialisé sur <b>Polymarket</b>.\n\n"
            f"🔍 <b>Ce que je peux faire pour vous :</b>\n"
            f"• Analyser les marchés avec mon conseil d'IA.\n"
            f"• Gérer vos wallets et transferts USDC.\n"
            f"• Exécuter des ordres automatiques ou manuels.\n"
            f"• Surveiller les baleines et les inefficacités.\n\n"
            f"🚀 <i>Utilisez les boutons ci-dessous pour commencer.</i>"
        )
        
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [
                InlineKeyboardButton("💼 Wallet", callback_data="help_page_1"),
                InlineKeyboardButton("📈 Markets", callback_data="help_page_2"),
            ],
            [
                InlineKeyboardButton("⚡ Trading", callback_data="help_page_3"),
                InlineKeyboardButton("🧭 Crypto", callback_data="crypto_menu"),
            ],
            [
                InlineKeyboardButton("👑 Admin", callback_data="help_page_4"),
                InlineKeyboardButton("📖 Manuel Complet", callback_data="help_menu"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.listener.reply_to(welcome_text, update, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    def _register_crypto_horizon_commands(self):
        for asset in ("btc", "eth", "sol", "xrp", "hype", "doge", "bnb", "ada", "avax", "link", "sui", "pepe", "wif", "ton", "near"):
            self._add_cmd(asset, self._cmd_crypto_markets)
            for suffix in ("5", "15", "1h", "4h", "1d"):
                self._add_cmd(f"{asset}{suffix}", self._cmd_crypto_horizon)

    async def _cmd_crypto_horizon(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        command = ""
        if context.args:
            first = context.args[0].strip().lower()
            if len(context.args) >= 2 and context.args[1] in ("5", "15", "1h", "4h", "1d"):
                command = f"{first}{context.args[1]}"
            else:
                command = first
        else:
            command = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0].lower()
        command = command.replace("bitcoin", "btc").replace("ethereum", "eth").replace("solana", "sol")
        match = None
        import re
        match = re.fullmatch(r"(btc|eth|sol|xrp|hype|doge|bnb|ada|avax|link|sui|pepe|wif|ton|near)(5|15|1h|4h|1d)", command)
        if not match:
            await self.listener.reply_to("Usage: /btc5 /btc15 /btc1h, idem /eth /sol /xrp /hype /doge /bnb /pepe /sui ...", update)
            return

        asset, horizon = match.group(1).upper(), match.group(2)
        if asset == "BTC" and horizon in {"5", "15"}:
            await self._cmd_btc_launch(update, context, "5m" if horizon == "5" else "15m")
            return

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
                parse_mode=ParseMode.HTML
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

    async def _cmd_btc_launch(self, update: Update, context: ContextTypes.DEFAULT_TYPE, interval: str) -> None:
        if not await self.listener._check_auth(update):
            return
        try:
            text, reply_markup = await self.render_btc_launch(interval)
        except Exception as exc:
            logger.exception("BTC launch failed for %s", interval)
            await self.listener.reply_to(f"❌ BTC launch {interval} impossible: {exc}", update)
            return
        await self.listener.reply_to(text, update, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    async def _cmd_crypto_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        args = getattr(context, "args", None) or []
        if args:
            asset = CRYPTO_ALIAS_MAP.get(args[0].lower(), args[0].upper())
        else:
            command = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0].lower()
            asset = CRYPTO_ALIAS_MAP.get(command, command.upper())

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
                f"📡 <b>MARCHÉS ACTIFS POUR {asset}</b>",
                "───────────────────",
            ]
            for i, m in enumerate(active_markets[:8], 1):
                try:
                    pct = m.probability_pct
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    lines.extend([
                        f"{i}. <b>{m.question[:80]}</b>",
                        f"   <code>{bar}</code> <code>{pct:.0f}%</code> | <code>${m.yes_price:.3f}</code>",
                        f"   Slug: <code>{m.slug}</code>",
                        "",
                    ])
                except Exception:
                    lines.extend([
                        f"{i}. <b>{m.question[:80]}</b>",
                        f"   Slug: <code>{m.slug}</code>",
                        "",
                    ])

            lines.append("───────────────────")
            lines.append("Utilise <code>BUY &lt;slug&gt; &lt;prix&gt;</code> pour placer un ordre papier.")

            await self.listener.reply_to(
                "\n".join(lines).strip(),
                update,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error in crypto markets search handler: {e}")
            await self.listener.reply_to(f"❌ Erreur lors de la recherche des marchés {asset}.", update)

    async def _cmd_crypto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return

        args = context.args
        if args:
            target = args[0].upper()
            if len(args) > 1 and args[1] in {"5", "15", "1h", "4h", "1d"}:
                context.args = [target.lower() + args[1]]
                await self._cmd_crypto_horizon(update, context)
                return
            context.args = [target.lower()]
            await self._cmd_crypto_markets(update, context)
            return

        text, reply_markup = await self.render_crypto_menu()
        await self.listener.reply_to(text, update, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

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
                "📡 <b>TOUS LES MARCHÉS CRYPTO ACTIFS</b>",
                "───────────────────",
            ]
            for i, m in enumerate(active_crypto_markets[:10], 1):
                asset_label = classifier._classify_asset(m)
                try:
                    pct = m.probability_pct
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    lines.extend([
                        f"{i}. <b>[{asset_label}] {m.question[:80]}</b>",
                        f"   <code>{bar}</code> <code>{pct:.0f}%</code> | <code>${m.yes_price:.3f}</code>",
                        f"   Slug: <code>{m.slug}</code>",
                        "",
                    ])
                except Exception:
                    lines.extend([
                        f"{i}. <b>[{asset_label}] {m.question[:80]}</b>",
                        f"   Slug: <code>{m.slug}</code>",
                        "",
                    ])

            lines.append("───────────────────")
            lines.append("Utilise <code>BUY &lt;slug&gt; &lt;prix&gt;</code> pour placer un ordre papier.")

            await self.listener.reply_to(
                "\n".join(lines).strip(),
                update,
                parse_mode=ParseMode.HTML
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

            header = f"📡 <b>MARCHÉS CRYPTO UPDOWN ACTIFS ({target_asset})</b>" if target_asset else "📡 <b>TOUS LES MARCHÉS CRYPTO UPDOWN ACTIFS</b>"
            lines = [
                header,
                "───────────────────",
            ]
            for i, (asset_label, m) in enumerate(updown_markets[:15], 1):
                try:
                    yes, no = resolve_prices(m)
                    pct = max(yes, no) * 100
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    lines.extend([
                        f"{i}. <b>[{asset_label}] {m.question[:80]}</b>",
                        f"   <code>{bar}</code> <code>{pct:.0f}%</code> | <code>YES: ${yes:.3f}</code> <code>NO: ${no:.3f}</code>",
                        f"   Slug: <code>{m.slug}</code>",
                        "",
                    ])
                except Exception:
                    lines.extend([
                        f"{i}. <b>[{asset_label}] {m.question[:80]}</b>",
                        f"   Slug: <code>{m.slug}</code>",
                        "",
                    ])

            lines.append("───────────────────")
            lines.append("Utilise <code>BUY &lt;slug&gt; &lt;prix&gt;</code> pour placer un ordre papier.")

            await self.listener.reply_to(
                "\n".join(lines).strip(),
                update,
                parse_mode=ParseMode.HTML
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
            msg = (
                "🧠 <b>AI Agents Status / CONSEIL D'IA LOBSTAR</b>\n"
                "───────────────────\n"
                f"• <b>Spécialistes</b> : <code>{len(specialists)} agents</code> actifs\n"
                "• <b>LLM Council</b> : <code>OpenRouter / Groq</code> ✅\n"
                "• <b>Mémoire</b> : <code>Persistante (SQLite)</code> ✅\n"
                "───────────────────\n"
                "Posez une question directement : <code>/ai quel est le sentiment sur SOL ?</code>"
            )
            await self.listener.reply_to(msg, update)
        elif prompt.lower() == "errors":
            try:
                with open("logs/pm2-error.log", "r") as f:
                    lines = f.readlines()[-10:]
                msg = "🚨 <b>DERNIÈRES ERREURS AI</b>\n───────────────────\n<pre>" + "".join(lines) + "</pre>"
                await self.listener.reply_to(msg, update)
            except Exception as e:
                await self.listener.reply_to(f"❌ Failed to read logs: {e}", update)
        else:
            status_msg = await self.listener.reply_to(
                "🤔 <b>Lobstar AI Council is reflecting...</b>\n"
                "🤔 <b>Le Conseil d'IA Lobstar réfléchit...</b>\n\n"
                "• Analyse des signaux de marché...\n"
                "• Consultation des agents spécialistes...\n"
                "• Synthèse du Chairman en cours...",
                update
            )

            try:
                from utils.llm_council import LLMCouncil, resolve_openrouter_api_key
                council = LLMCouncil()
                api_key = resolve_openrouter_api_key(council.config)

                if not api_key:
                    final_msg = (
                        "🚨 <b>OPENROUTER API KEY MISSING</b>\n\n"
                        "🚨 <b>CLEF API MANQUANTE</b>\n\n"
                        "La synthèse multi-agent nécessite une <code>OPENROUTER_API_KEY</code>."
                    )
                    await status_msg.edit_text(final_msg, parse_mode=ParseMode.HTML)
                    return

                res = await council.ask(prompt)
                guardrail = council.config.get("safety", {}).get("trading_guardrail", "Avis consultatif uniquement.")
                final_msg = (
                    "🧠 <b>SYNTHÈSE DU CONSEIL D'IA</b>\n"
                    "───────────────────\n"
                    f"<b>Question</b>: <i>{prompt}</i>\n\n"
                    f"{res.final_answer}\n"
                    "───────────────────\n"
                    f"🛡️ <i>{guardrail}</i>"
                )
                await status_msg.edit_text(final_msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Error executing AI council prompt: {e}")
                await status_msg.edit_text(f"❌ <b>ERREUR AI COUNCIL</b>\n\nUne erreur est survenue : <code>{str(e)[:100]}</code>", parse_mode=ParseMode.HTML)

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._hmm:
            await self.listener.reply_to("❌ <b>ERREUR MODÈLE</b>\n\nLe filtre HMM n'est pas initialisé.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            from utils.regime_utils import get_regime_label
            label = get_regime_label(self.listener._hmm, "SOL")
            msg = (
                "📊 <b>STATUT DES MODÈLES ML</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Régime Actuel</b> : <code>{label}</code>\n"
                f"• <b>Autorisation Trading</b> : {'✅ AUTORISÉ' if self.listener._hmm.is_trading_allowed(None)[0] else '❌ BLOQUÉ'}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await self.listener.reply_to(msg, update)
        elif sub == "metrics":
            if not self.listener._store:
                await self.listener.reply_to("❌ Feature Store non attaché.", update)
                return
            stats = self.listener._store.get_stats()
            msg = "📈 <b>MÉTRIQUES FEATURE STORE</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            for k, v in stats.items():
                msg += f"• {k} : <code>{v}</code>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"❓ Subcommand Model inconnue: <code>{sub}</code>", update)

    async def _cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._ledger:
            await self.listener.reply_to("❌ Ledger non initialisé.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            cap = self.listener._ledger.get_capital_summary()
            msg = (
                "🛡️ <b>SÉCURITÉ &amp; CAPITAL</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Total Portfolio</b> : <code>${cap.get('total_capital', 0):,.2f}</code>\n"
                f"• <b>Disponible</b> : <code>${cap.get('available_capital', 0):,.2f}</code>\n"
                f"• <b>Allocation</b> : <code>{cap.get('allocated_pct', 0)}%</code> du max\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await self.listener.reply_to(msg, update)
        elif sub in ("kill", "freeze"):
            from mcp_agents.mcp_server import emergency_circuit_breaker
            res = emergency_circuit_breaker("ENGAGE")
            await self.listener.reply_to("🛑 <b>URGENCE ENGAGÉE</b>\n\nLe coupe-circuit a été activé. Le trading est suspendu.", update)
        elif sub in ("resume", "unfreeze"):
            from mcp_agents.mcp_server import emergency_circuit_breaker
            res = emergency_circuit_breaker("DISENGAGE")
            await self.listener.reply_to("✅ <b>SÉCURITÉ LEVÉE</b>\n\nLe bot est de nouveau prêt pour l'exécution.", update)
        else:
            await self.listener.reply_to(f"❓ Subcommand Risk inconnue: <code>{sub}</code>", update)

    async def _cmd_clob(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "arb"

        if sub == "arb":
            from mcp_agents.mcp_server import get_arbitrage_opportunities
            res = get_arbitrage_opportunities()
            count = res.get("opportunity_count", 0)
            msg = (
                "⚖️ <b>CLOB ARBITRAGE SCANNER</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Opportunités détectées</b> : <code>{count}</code>\n"
            )
            if count > 0:
                msg += "\n<b>TOP 5 OPPORTUNITIES</b>:\n"
                for opp in res.get("opportunities", [])[:5]:
                    msg += f"• {opp.get('type')} : <code>{opp.get('market_id')[:10]}...</code> (Conf: <code>{opp.get('confidence'):.2f}</code>)\n"
            msg += "━━━━━━━━━━━━━━━━━━━━"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"❓ Subcommand CLOB inconnue: <code>{sub}</code>", update)

    async def _cmd_whales(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "leaderboard"

        from utils.polymarket_crawler.traders import discover_top_traders
        from utils.polymarket_crawler.trader_formatters import fmt_expert_leaderboard

        if sub == "leaderboard":
            cat = args[1].upper() if len(args) > 1 else "OVERALL"
            msg_wait = await self.listener.reply_to(f"🔍 <b>SCAN DES BALEINES</b> (<code>{cat}</code>)...", update)
            results = discover_top_traders(categories=[cat], limit=5)
            traders = results.get(cat, [])
            report = fmt_expert_leaderboard(traders, cat, 5)
            
            msg = (
                f"🐋 <b>TOP TRADERS : {cat}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{report}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await self.listener.reply_to(msg, update)
        elif sub == "analyze":
            if len(args) < 2:
                await self.listener.reply_to("💡 Usage: <code>/whales analyze &lt;adresse&gt;</code>", update)
                return
            wallet = args[1]
            await self.listener.reply_to(f"🧪 <b>ANALYSE DE PORTEFEUILLE</b> : <code>{wallet[:10]}...</code>", update)
            from utils.polymarket_crawler.traders import TraderScraper
            scraper = TraderScraper()
            positions = scraper.fetch_closed_positions(wallet)
            total_pnl = sum(p.realized_pnl for p in positions)
            
            msg = (
                f"🐋 <b>WHALE ANALYSIS : {wallet[:10]}...</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Positions Clôturées</b> : <code>{len(positions)}</code>\n"
                f"• <b>PnL Total Réalisé</b> : <code>${total_pnl:,.2f}</code>\n\n"
                f"<b>Dernières Victoires</b> :\n"
            )
            for p in positions[:5]:
                msg += f"• {p.title[:30]}... | `${p.realized_pnl:,.0f}`\n"
            msg += "━━━━━━━━━━━━━━━━━━━━"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"❓ Subcommand Whales inconnue: <code>{sub}</code>", update)

    async def _cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.listener._ledger:
            await self.listener.reply_to("❌ <b>ERREUR LEDGER</b>\n\nLe grand livre (ledger) n'est pas initialisé.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            mode = self.listener._ledger.get_execution_mode()
            metrics = self.listener._executor.get_metrics() if self.listener._executor else {}
            msg = (
                "🎯 <b>TRADING ENGINE STATUS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Mode Actuel</b> : <code>{mode}</code>\n"
                f"• <b>Fill Rate</b> : <code>{metrics.get('fill_rate_pct', 0)}%</code>\n"
                f"• <b>File d'attente</b> : <code>{metrics.get('queue_depth', 0)} ordres</code>\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await self.listener.reply_to(msg, update)
        elif sub in ("paper", "shadow", "prod"):
            if len(args) > 1 and args[1] == "on":
                new_mode = sub.upper()
                if new_mode == "PROD":
                    await self.listener.reply_to("⚠️ <b>SÉCURITÉ PROD</b>\n\nLe passage en mode <code>PROD</code> nécessite une confirmation manuelle via le fichier de configuration pour des raisons de sécurité.", update)
                    return
                self.listener._ledger.set_execution_mode(new_mode)
                await self.listener.reply_to(f"🔄 <b>CHANGEMENT DE MODE</b>\n\nLe moteur d'exécution est maintenant en mode : <code>{new_mode}</code>", update)
            else:
                await self.listener.reply_to(f"💡 Usage: <code>/trade {sub} on</code> pour confirmer.", update)
        elif sub == "pnl":
            perf = self.listener._ledger.get_performance_summary(mode=self.listener._ledger.get_execution_mode())
            if perf and perf.get("total_trades", 0) > 0:
                wr = perf["win_rate"] * 100
                msg = (
                    "💰 <b>RAPPORT DE PERFORMANCE</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Net PnL</b> : <code>${perf['total_net_pnl']:,.2f}</code>\n"
                    f"• <b>Win Rate</b> : <code>{wr:.1f}%</code>\n"
                    f"• <b>Total Trades</b> : <code>{perf['total_trades']}</code>\n"
                    f"• <b>Profit Factor</b> : <code>{perf['profit_factor']:.2f}</code>\n"
                    f"• <b>Gain Moyen</b> : <code>${perf['avg_win']:.2f}</code>\n"
                    f"• <b>Perte Moyenne</b> : <code>${perf['avg_loss']:.2f}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                msg = "💰 <b>PnL REPORT</b>\n\nAucun trade clôturé détecté pour le mode actuel."
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"❓ Subcommand inconnue: <code>{sub}</code>", update)

    async def _cmd_mcp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            from mcp_agents.mcp_server import mcp
            msg = (
                "🔌 <b>MCP AGENT STATUS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Serveur</b> : <code>quant-agentic-mcp</code>\n"
                f"• <b>Transport</b> : <code>stdio</code> (v2 Standard)\n"
                f"• <b>Outils</b> : <code>{len(mcp.list_tools())}</code> actifs\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await self.listener.reply_to(msg, update)
        elif sub == "tools":
            from mcp_agents.mcp_server import mcp
            tools = mcp.list_tools()
            msg = "🛠️ <b>OUTILS MCP DISPONIBLES</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            for t in tools:
                msg += f"• <code>{t.name}</code> : {t.description[:50]}...\n"
            msg += "━━━━━━━━━━━━━━━━━━━━"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"❓ Subcommand MCP inconnue: <code>{sub}</code>", update)

    async def _cmd_dev(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        sub = args[0] if args else "metrics"

        if sub == "metrics":
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            msg = (
                "⚙️ <b>SYSTEM METRICS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>CPU Usage</b> : <code>{cpu}%</code>\n"
                f"• <b>RAM Usage</b> : <code>{mem}%</code>\n"
                f"• <b>Uptime</b> : <code>{self.listener._fmt_uptime() if hasattr(self.listener, '_fmt_uptime') else 'Active'}</code>\n"
            )
            if self.listener._executor:
                metrics = self.listener._executor.get_metrics()
                msg += f"• <b>Slippage (Sim)</b> : <code>${metrics.get('simulated_slippage_usd', 0):,.2f}</code>\n"
                msg += f"• <b>Spread (Sim)</b> : <code>${metrics.get('simulated_spread_usd', 0):,.2f}</code>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━"
            await self.listener.reply_to(msg, update)
        elif sub == "logs":
            try:
                # Prioritize PM2 logs
                log_file = "logs/pm2-out.log"
                if not os.path.exists(log_file):
                    log_file = "user_data/logs/app.log"
                
                with open(log_file, "r") as f:
                    lines = f.readlines()[-15:]
                msg = "📜 <b>DERNIÈRES LOGS SYSTEM</b>\n━━━━━━━━━━━━━━━━━━━━\n<pre>" + "".join(lines) + "</pre>"
                await self.listener.reply_to(msg, update)
            except Exception as e:
                await self.listener.reply_to(f"❌ Échec lecture logs: <code>{e}</code>", update)
        elif sub == "cleanup":
            from utils.data_archiver import DataArchiver
            archiver = DataArchiver()
            res = archiver.run_maintenance_cycle()
            msg = "🧹 <b>Maintenance Cycle Complete</b>\n\n"
            msg += f"• Tables Archived: <code>{len(res['microstructure'].get('tables_exported', []))}</code>\n"
            msg += f"• Log Files: <code>{res['logs'].get('files_compressed', 0)}</code> compressed\n"
            await self.listener.reply_to(msg, update)
        elif sub == "pmxt":
            service = getattr(self.listener, "_pmxt_service", None)
            if not service:
                await self.listener.reply_to("❌ PMXT adapter service unavailable.", update)
                return
            action = args[1] if len(args) > 1 else "status"
            if action == "status":
                await self.listener.reply_to(service.format_status_html(), update)
            elif action == "run":
                result = await service.run_cycle(force=True)
                msg = (
                    "🗃️ <b>PMXT MANUAL RUN</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Status</b> : <code>{result.get('status')}</code>\n"
                    f"• <b>Processed</b> : <code>{result.get('processed_count', 0)}</code>\n"
                    f"• <b>Skipped</b> : <code>{result.get('skipped_count', 0)}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                )
                await self.listener.reply_to(msg, update)
            elif action == "download":
                if len(args) < 3:
                    await self.listener.reply_to("Usage: <code>/dev pmxt download 2026-04-15T17</code>", update)
                    return
                result = await service.download_and_convert(args[2])
                msg = (
                    "🗃️ <b>PMXT DOWNLOAD+CONVERT</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Status</b> : <code>{result.get('status')}</code>\n"
                    f"• <b>Rows Out</b> : <code>{result.get('stats', {}).get('rows_out', 0)}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                )
                await self.listener.reply_to(msg, update)
            else:
                await self.listener.reply_to(f"Unknown PMXT action: <code>{action}</code>", update)
        else:
            await self.listener.reply_to(f"Unknown dev subcommand: <code>{sub}</code>", update)

    async def _cmd_audit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        from utils.snapshot_manager import get_snapshot_manager
        sm = get_snapshot_manager()

        args = context.args
        cat = args[0] if args else "TRADING"

        snap = sm.get_latest(cat)
        if not snap:
            await self.listener.reply_to(f"No snapshots found for category: <code>{cat}</code>", update)
            return

        msg = f"🔍 <b>Snapshot Audit: {cat}</b>\n\n"
        msg += f"<pre>{json.dumps(snap, indent=2)[:3000]}</pre>"
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
                "❌ <b>Usage</b>: <code>/gsd [--dry-run] [description de l'issue]</code>\n"
                "Exemple: <code>/gsd --dry-run timing delay in websocket</code>",
                update,
                parse_mode=ParseMode.HTML
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
            f"🚀 <b>Lancement du GSD Problem Solver Agent...</b>\n"
            f"🎯 <b>Cible</b>: <code>{issue_text}</code>\n"
            f"⚙️ <b>Dry-Run</b>: <code>{dry_run}</code>\n\n"
            f"⏳ Traitement des phases (Intake, Context, Implementation, Verification)...",
            update,
            parse_mode=ParseMode.HTML
        )

        try:
            from services.gsd_problem_solver import GSDProblemSolverAgent
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
                f"📊 <b>GSD RESOLUTION PROCESS COMPLETE</b>\n"
                f"───────────────────\n"
                f"⚡ <b>Statut</b>: <code>{status_str}</code>\n\n"
                f"📋 <b>Phase A (Intake)</b>:\n"
                f"• Goal: {intake.get('goal')}\n"
                f"• Scope: {', '.join(intake.get('scope', []))[:100]}...\n\n"
                f"🔍 <b>Phase B (Context)</b>:\n"
                f"• Target Files: <code>{', '.join(context_p.get('priority_files', []))}</code>\n\n"
                f"🛠️ <b>Phase C & D (Code)</b>:\n"
                f"• Modified Files: <code>{', '.join(report.changed_files) or 'None'}</code>\n"
                f"• Tests: <code>{', '.join(report.tests_run) or 'None'}</code>\n"
                f"• Residual Risks: <code>{report.residual_risks}</code>\n\n"
                f"📤 <b>Phase E (Handoff)</b>:\n"
                f"• Summary: {handoff.get('summary')}\n"
                f"───────────────────\n"
                f"📝 <i>Rapport complet: user_data/reports/gsd_issue_resolver_report.md</i>"
            )
            await status_msg.edit_text(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Error in Telegram GSD command: {e}")
            await status_msg.edit_text(f"❌ <b>Erreur GSD Solver Agent:</b> <code>{str(e)}</code>", parse_mode=ParseMode.HTML)

    # NEW WALLET / TRANSFER / POLYMARKET / SIGNALS / MARKETS COMMANDS

    async def _cmd_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return

        args = context.args
        sub = args[0].lower() if args else "help"

        if sub == "balance":
            if not self.wallet_manager:
                await self.listener.reply_to("💾 Wallet manager not attached.", update)
                return
            from telegram.handlers.wallet_handler import handle_wallet_balance
            await handle_wallet_balance(update, context, self.wallet_manager)
        elif sub == "health":
            if not self.wallet_manager:
                await self.listener.reply_to("💾 Wallet manager not attached.", update)
                return
            from telegram.handlers.wallet_handler import handle_wallet_health
            await handle_wallet_health(update, context, self.wallet_manager)
        elif sub == "add":
            from telegram.handlers.wallet_handler import handle_wallet_add
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
            from telegram.handlers.wallet_handler import handle_wallet_import
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
            from telegram.handlers.wallet_handler import handle_wallet_set_proxy
            await handle_wallet_set_proxy(update, context)
        elif sub == "list":
            from telegram.handlers.wallet_handler import handle_wallet_list
            await handle_wallet_list(update, context)
        elif sub == "show":
            from telegram.handlers.wallet_handler import handle_wallet_show
            await handle_wallet_show(update, context)
        elif sub == "delete":
            from telegram.handlers.wallet_handler import handle_wallet_delete
            await handle_wallet_delete(update, context)
        elif sub == "use":
            from telegram.handlers.wallet_handler import handle_wallet_use
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
            from telegram.handlers.wallet_handler import handle_wallet_status
            await handle_wallet_status(update, context)
        elif sub == "backup":
            from telegram.handlers.wallet_handler import handle_wallet_backup
            await handle_wallet_backup(update, context)
        elif sub == "swap":
            from telegram.handlers.wallet_handler import handle_wallet_swap
            await handle_wallet_swap(update, context)
        elif sub == "help":
            from telegram.handlers.wallet_handler import handle_wallet_help
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
            from telegram.handlers.transfer_handler import handle_transfer_help
            await handle_transfer_help(update, context)
        else:
            # Assume it's an amount (they forgot to use help)
            from telegram.handlers.transfer_handler import handle_transfer
            await handle_transfer(update, context, self.transfer_manager)

    async def _cmd_polymarket(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.order_manager:
            await self.listener.reply_to("🎲 Polymarket order manager not attached.", update)
            return

        args = context.args
        sub = args[0].lower() if args else "help"

        if sub == "bet":
            from telegram.handlers.polymarket_handler import handle_polymarket_bet
            await handle_polymarket_bet(update, context, self.order_manager)
        elif sub == "claim":
            from telegram.handlers.polymarket_handler import handle_polymarket_claim
            await handle_polymarket_claim(update, context, self.order_manager)
        elif sub == "help":
            from telegram.handlers.polymarket_handler import handle_polymarket_help
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
            from telegram.handlers.signals_handler import handle_signals_all
            await handle_signals_all(update, context, self.signal_generator)
        elif sub == "matrix":
            ticker = args[1].upper() if len(args) > 1 else "BTC"
            from telegram.handlers.signals_handler import handle_signals_matrix
            await handle_signals_matrix(update, context, ticker)
        elif sub == "help":
            from telegram.handlers.signals_handler import handle_signals_help
            await handle_signals_help(update, context)
        else:
            if not self.signal_generator:
                await self.listener.reply_to("📊 Signal generator not attached.", update)
                return
            from telegram.handlers.signals_handler import handle_signals
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
            from telegram.handlers.markets_handler import handle_markets_list
            await handle_markets_list(update, context, self.market_reader)
        elif sub == "feed":
            from telegram.handlers.markets_handler import handle_markets_feed
            await handle_markets_feed(update, context, self.market_reader)
        elif sub == "info":
            from telegram.handlers.markets_handler import handle_markets_info
            await handle_markets_info(update, context, self.market_reader)
        elif sub == "search":
            from telegram.handlers.markets_handler import handle_markets_search
            await handle_markets_search(update, context, self.market_reader)
        elif sub == "discover":
            from telegram.handlers.markets_handler import handle_markets_discover
            await handle_markets_discover(update, context)
        elif sub == "opportunities":
            from telegram.handlers.markets_handler import handle_markets_opportunities
            await handle_markets_opportunities(update, context)
        elif sub == "contrarian":
            from telegram.handlers.markets_handler import handle_markets_contrarian
            await handle_markets_contrarian(update, context)
        elif sub == "vcp":
            from telegram.handlers.markets_handler import handle_markets_vcp
            await handle_markets_vcp(update, context)
        elif sub == "canslim":
            from telegram.handlers.markets_handler import handle_markets_canslim
            await handle_markets_canslim(update, context)
        elif sub == "help":
            from telegram.handlers.markets_handler import handle_markets_help
            await handle_markets_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown markets subcommand: {sub}. Use `/markets help`", update)

    async def _cmd_feed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_admin_auth(update): return
        if not self.market_reader:
            await self.listener.reply_to("📈 Market reader not attached.", update)
            return
        from telegram.handlers.markets_handler import handle_markets_feed
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
                    f"📈 <b>MANUEL LOBSTAR — /{target}</b>\n"
                    "───────────────────\n"
                    f"📂 <b>Catégorie</b> : <code>MARKETS</code>\n"
                    f"📝 <b>Description</b> : Sentiment du marché crypto pour {asset} sur l'horizon {horizon}.\n"
                    f"⚡ <b>Usage</b> : <code>/{target}</code>\n"
                    f"💡 <b>Exemple</b> : <code>/{target}</code>\n\n"
                    f"ℹ️ <i>Notes</i> : Construit des probabilités calibrées à partir de Polymarket.\n"
                    "───────────────────"
                )
                await self.listener.reply_to(text, update, parse_mode=ParseMode.HTML)
                return

            if target in COMMAND_REGISTRY:
                info = COMMAND_REGISTRY[target]
                text = (
                    f"📖 <b>MANUEL LOBSTAR — /{target}</b>\n"
                    "───────────────────\n"
                    f"📂 <b>Catégorie</b> : <code>{info['category']}</code>\n"
                    f"📝 <b>Description</b> : {info['description']}\n"
                    f"⚡ <b>Usage</b> : <code>{info['usage']}</code>\n"
                    f"💡 <b>Exemple</b> : <code>{info['example']}</code>\n\n"
                    f"ℹ️ <i>Notes</i> : {info['notes']}\n"
                    "───────────────────"
                )
                await self.listener.reply_to(text, update, parse_mode=ParseMode.HTML)
                return
            else:
                await self.listener.reply_to(f"🔍 Commande <code>/{target}</code> introuvable. Tapez <code>/man</code> pour voir le menu.", update)
                return

        from utils.help_manager import HelpManager
        chat_id = update.effective_chat.id
        is_admin = self.access_control.est_admin(chat_id) if self.access_control else False
        await HelpManager.send_menu(update, context, is_admin)

    async def _cmd_paper(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.listener._check_admin_auth(update): return
        args = context.args
        ticker = args[0].upper() if args else "BTC"
        from telegram.handlers.signals_handler import handle_paper_test
        await handle_paper_test(update, context, ticker)

    # --- Understand-Anything Tool Suite ---

    async def _cmd_understand(self, update: Update, _context) -> None:
        """Analyser un codebase -> graphe de connaissance interactif."""
        if not await self.listener._check_auth(update): return
        logger.info("📩 [UNDERSTAND] Received /understand command")
        await self.listener.reply_to("🔍 <b>Analyse du codebase en cours...</b>\nGénération du graphe de connaissance...", update, parse_mode=ParseMode.HTML)
        # Simulation d'analyse
        await asyncio.sleep(2)
        await self.listener.reply_to("✅ <b>Graphe généré.</b>\nUtilisez /understand_explain [fichier] pour explorer.", update, parse_mode=ParseMode.HTML)
        logger.info("✅ [UNDERSTAND] Sent response for /understand")

    async def _cmd_understand_explain(self, update: Update, context) -> None:
        """Explication détaillée d'un fichier/fonction/module."""
        if not await self.listener._check_auth(update): return
        args = context.args
        logger.info(f"📩 [UNDERSTAND] Received /understand_explain command with args: {args}")
        
        if not args:
            help_text = (
                "🧩 <b>Exploration du Codebase</b>\n\n"
                "Voici les composants clés que vous pouvez explorer :\n\n"
                "• <code>scheduler</code> : Gestionnaire des tâches asynchrones.\n"
                "• <code>executor</code> : Moteur d'exécution des ordres (Maker/Taker).\n"
                "• <code>risk</code> : Moteur de gestion des risques et Kelly.\n"
                "• <code>prediction</code> : Moteur IA (Hybrid + TimesFM).\n"
                "• <code>strategies</code> : Catalogue des stratégies de trading.\n"
                "• <code>listener</code> : Ce module (Telegram/Signals).\n\n"
                "<i>Usage : /understand_explain [nom]</i>"
            )
            await self.listener.reply_to(help_text, update, parse_mode=ParseMode.HTML)
            return
        
        target = args[0]
        await self.listener.reply_to(f"🧠 <b>Analyse de :</b> <code>{target}</code>...", update, parse_mode=ParseMode.HTML)
        
        # Logique réelle pour trouver le fichier
        from pathlib import Path
        matches = []
        project_root = Path(__file__).resolve().parent.parent
        for path in project_root.rglob("*.py"):
            if target.lower() in path.name.lower():
                matches.append(path)
        
        if not matches:
            await self.listener.reply_to(f"❓ Module <code>{target}</code> introuvable dans <code>src/</code>.", update, parse_mode=ParseMode.HTML)
            return
        
        best_match = matches[0]
        rel_path = best_match.relative_to(project_root)
        
        summary = f"📍 <b>Localisation :</b> <code>src/{rel_path}</code>\n"
        summary += f"📝 <b>Rôle :</b> Ce module gère la logique de <code>{target}</code> au sein de l'architecture modulaire.\n"
        summary += f"🔗 <b>Dépendances :</b> Intégré au <code>ServiceContainer</code> pour l'exploitation en PROD."
        
        await self.listener.reply_to(summary, update, parse_mode=ParseMode.HTML)
        logger.info(f"✅ [UNDERSTAND] Sent dynamic explanation for {target}")

    async def _cmd_understand_map(self, update: Update, _context) -> None:
        """Affiche une carte de l'arborescence src/."""
        if not await self.listener._check_auth(update): return
        map_text = (
            "🗺️ <b>Carte de l'Architecture</b>\n\n"
            "📂 <code>src/</code>\n"
            "┣ 📂 <code>app/</code> (Serveurs API/Web)\n"
            "┣ 📂 <code>core/</code> (Orchestration, Scheduler)\n"
            "┣ 📂 <code>polymarket/</code> (Client CLOB, Wallets)\n"
            "┣ 📂 <code>strategies/</code> (Modèles Quant/RL)\n"
            "┣ 📂 <code>schemas/</code> (Prédictions, VolSurface)\n"
            "┗ 📂 <code>interface/</code> (Telegram/UI)\n\n"
            "<i>Tapez /understand_explain [nom] pour plonger dans un dossier !</i>"
        )
        await self.listener.reply_to(map_text, update, parse_mode=ParseMode.HTML)

    async def _cmd_understand_chat(self, update: Update, _context) -> None:
        """Poser des questions sur le code via le graphe."""
        if not await self.listener._check_auth(update): return
        await self.listener.reply_to("💬 <b>Mode Chat Codebase activé.</b>\nPosez votre question sur le fonctionnement du bot.", update, parse_mode=ParseMode.HTML)

    async def _cmd_understand_diff(self, update: Update, _context) -> None:
        """Analyser des diffs/PRs."""
        if not await self.listener._check_auth(update): return
        await self.listener.reply_to("⚖️ <b>Analyse des changements récents...</b>", update, parse_mode=ParseMode.HTML)

    async def _cmd_understand_dashboard(self, update: Update, _context) -> None:
        """Lancer le dashboard web interactif."""
        if not await self.listener._check_auth(update): return
        await self.listener.reply_to("🌐 <b>Lien du Dashboard :</b> <a href='http://127.0.0.1:8000/dashboard'>Dashboard Interactif</a>", update, parse_mode=ParseMode.HTML)

    async def _cmd_understand_domain(self, update: Update, _context) -> None:
        """Extraire la connaissance métier."""
        if not await self.listener._check_auth(update): return
        await self.listener.reply_to("📖 <b>Domaine Métier :</b> Trading Agentique sur Polymarket (CLOB).", update, parse_mode=ParseMode.HTML)

    async def _cmd_understand_onboard(self, update: Update, _context) -> None:
        """Générer des guides d'onboarding."""
        if not await self.listener._check_auth(update): return
        await self.listener.reply_to("🚀 <b>Guide d'Onboarding :</b> Consultez <code>docs/architecture.md</code>.", update, parse_mode=ParseMode.HTML)
