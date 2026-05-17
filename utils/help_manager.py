import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger("HelpManager")

class HelpManager:
    PAGES = {
        1: {
            "title": "💼 WALLET",
            "icon": "💼",
            "content": """💼 *WALLET — Gestion des portefeuille*
─────────────────────────────────────────
• `/wallet add` ↳ Créer wallet généré (defaut)
• `/wallet import` ↳ Importer wallet existant
• `/wallet use [defaut|import]` ↳ Choisir wallet actif
• `/wallet swap` ↳ Permuter wallet actif
• `/wallet backup` ↳ Sauvegarder wallet actif
• `/wallet status` ↳ Status wallet actif
• `/wallet delete [defaut|import]` ↳ Supprimer wallet

• `/transfer [adresse] [montant]` ↳ Transférer USDC
• `/polymarket [id] [montant]` ↳ Parier sur marché
• `/signals` ↳ Voir signaux actifs
─────────────────────────────────────────"""
        },
        2: {
            "title": "📈 MARKETS",
            "icon": "📈",
            "content": """📈 *MARKETS — Analyse de marché*
─────────────────────────────────────────
*AI Scoring:*
• `/markets discover [limit]` ↳ Meilleurs marchés IA
• `/markets opportunities [min_edge]` ↳ Paris edge %
• `/markets contrarian [limit]` ↳ Setup contrarien

*Screening:*
• `/markets vcp [limit]` ↳ Volatility Contraction
• `/markets canslim [limit]` ↳ CANSLIM patterns

*Market Info:*
• `/markets list [limit]` ↳ Top markets volume
• `/markets feed` ↳ Feed + crypto intel
• `/markets info <id>` ↳ Détails marché
• `/markets search <query>` ↳ Rechercher

• `/feed` ↳ Feed unifié
• `/whales` ↳ Suivi baleines
─────────────────────────────────────────"""
        },
        3: {
            "title": "⚡ TRADING",
            "icon": "⚡",
            "content": """⚡ *TRADING — Exécution & Signaux*
─────────────────────────────────────────
• `/trade [ticker] [size] [side]` ↳ Executer trade
• `/paper [ticker]` ↳ Tester paper engine
• `/clob [ticker]` ↳ Statut CLOB
• `/ai [prompt]` ↳ Question IA trading
• `/model [action]` ↳ Gestion modèle ML

• `/btc5`, `/btc15`, `/btc1h` ↳ BTC horizons
• `/eth5`, `/eth15`, `/eth1h` ↳ ETH horizons
• `/sol5`, `/sol15`, `/sol1h` ↳ SOL horizons
• `/xrp5`, `/xrp15`, `/xrp1h` ↳ XRP horizons
─────────────────────────────────────────"""
        },
        4: {
            "title": "👑 ADMIN",
            "icon": "👑",
            "content": """👑 *ADMIN — Contrôle système*
─────────────────────────────────────────
• `/risk` ↳ Stats risque portfolio
• `/risk freeze` ↳ BloquerTrading
• `/risk resume` ↳ ReprendreTrading
• `/risk kill` ↳ Kill switch global

• `/liquidate [user]` ↳ Liquider position
• `/audit` ↳ Audit système complet
• `/mcp [cmd]` ↳ Commands MCP
• `/dev [cmd]` ↳ Commands dev
─────────────────────────────────────────"""
        }
    }

    MAX_PAGE = 4

    @staticmethod
    async def send_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int, is_admin: bool = False) -> None:
        if page < 1 or page > HelpManager.MAX_PAGE:
            return

        if page == 4 and not is_admin:
            page = 1

        page_data = HelpManager.PAGES[page]

        keyboard = []
        row = []

        if page > 1:
            row.append(InlineKeyboardButton("◀️ Prec", callback_data=f"help_page_{page-1}"))

        row.append(InlineKeyboardButton("📖 Menu", callback_data="help_menu"))

        if page < HelpManager.MAX_PAGE:
            row.append(InlineKeyboardButton("Suiv ▶️", callback_data=f"help_page_{page+1}"))

        keyboard.append(row)

        other_pages = []
        if page != 1:
            other_pages.append(InlineKeyboardButton("💼", callback_data="help_page_1"))
        if page != 2:
            other_pages.append(InlineKeyboardButton("📈", callback_data="help_page_2"))
        if page != 3:
            other_pages.append(InlineKeyboardButton("⚡", callback_data="help_page_3"))
        if is_admin and page != 4:
            other_pages.append(InlineKeyboardButton("👑", callback_data="help_page_4"))

        if other_pages:
            keyboard.append(other_pages)

        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=page_data["content"],
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    @staticmethod
    async def send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_admin: bool = False) -> None:
        keyboard = [
            [
                InlineKeyboardButton("💼 Wallet", callback_data="help_page_1"),
                InlineKeyboardButton("📈 Markets", callback_data="help_page_2"),
            ],
            [
                InlineKeyboardButton("⚡ Trading", callback_data="help_page_3"),
            ]
        ]

        if is_admin:
            keyboard[1].append(InlineKeyboardButton("👑 Admin", callback_data="help_page_4"))

        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📖 *MANUEL — Menu principal*\n\nChoisis une catégorie:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )