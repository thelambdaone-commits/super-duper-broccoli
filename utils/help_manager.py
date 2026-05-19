import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger("HelpManager")

class HelpManager:
    PAGES = {
        1: {
            "title": "💼 WALLET",
            "icon": "💼",
            "content": (
                "```\n"
                "┌─────────────────────────┐\n"
                "│    💼 WALLET MANUAL     │\n"
                "└─────────────────────────┘\n"
                "```\n"
                "• `/wallet add` ↳ Créer wallet généré\n"
                "• `/wallet import` ↳ Importer wallet existant\n"
                "• `/wallet use [default|import]` ↳ Activer\n"
                "• `/wallet swap` ↳ Permuter wallet actif\n"
                "• `/wallet backup` ↳ Sauvegarder wallet\n"
                "• `/wallet status` ↳ Status wallet actif\n"
                "• `/wallet delete` ↳ Supprimer un wallet\n\n"
                "• `/transfer [adresse] [montant]` ↳ USDC\n"
                "• `/polymarket [id] [montant]` ↳ Parier\n"
                "• `/signals` ↳ Voir signaux actifs\n"
                "─────────────────────────"
            )
        },
        2: {
            "title": "📈 MARKETS",
            "icon": "📈",
            "content": (
                "```\n"
                "┌─────────────────────────┐\n"
                "│    📈 MARKETS MANUAL    │\n"
                "└─────────────────────────┘\n"
                "```\n"
                "*AI Scoring:*\n"
                "• `/markets discover` ↳ Meilleurs marchés IA\n"
                "• `/markets opportunities` ↳ Paris edge %\n"
                "• `/markets contrarian` ↳ Setup contrarien\n\n"
                "*Screening:*\n"
                "• `/markets vcp` ↳ Volatility Contraction\n"
                "• `/markets canslim` ↳ CANSLIM patterns\n\n"
                "*Market Info:*\n"
                "• `/markets list` ↳ Top markets volume\n"
                "• `/markets feed` ↳ Feed + crypto intel\n"
                "• `/markets info <id>` ↳ Détails marché\n"
                "• `/markets search <q>` ↳ Rechercher\n\n"
                "• `/feed` ↳ Feed unifié\n"
                "• `/whales` ↳ Suivi baleines\n"
                "─────────────────────────"
            )
        },
        3: {
            "title": "⚡ TRADING",
            "icon": "⚡",
            "content": (
                "```\n"
                "┌─────────────────────────┐\n"
                "│    ⚡ TRADING MANUAL    │\n"
                "└─────────────────────────┘\n"
                "```\n"
                "• `/trade [ticker] [size] [side]` ↳ Exécuter\n"
                "• `/paper [ticker]` ↳ Paper engine\n"
                "• `/clob [ticker]` ↳ Statut CLOB\n"
                "• `/ai [prompt]` ↳ Question IA trading\n"
                "• `/model [action]` ↳ Gestion modèle ML\n\n"
                "• `/btc5`, `/btc15`, `/btc1h` ↳ BTC horizons\n"
                "• `/eth5`, `/eth15`, `/eth1h` ↳ ETH horizons\n"
                "• `/sol5`, `/sol15`, `/sol1h` ↳ SOL horizons\n"
                "• `/xrp5`, `/xrp15`, `/xrp1h` ↳ XRP horizons\n"
                "─────────────────────────"
            )
        },
        4: {
            "title": "👑 ADMIN",
            "icon": "👑",
            "content": (
                "```\n"
                "┌─────────────────────────┐\n"
                "│     👑 ADMIN MANUAL     │\n"
                "└─────────────────────────┘\n"
                "```\n"
                "• `/risk` ↳ Stats risque portfolio\n"
                "• `/risk freeze` ↳ Bloquer trading\n"
                "• `/risk resume` ↳ Reprendre trading\n"
                "• `/risk kill` ↳ Kill switch global\n\n"
                "• `/liquidate [user]` ↳ Liquider position\n"
                "• `/audit` ↳ Audit système complet\n"
                "• `/mcp [cmd]` ↳ Commandes MCP\n"
                "• `/dev [cmd]` ↳ Commandes dev\n"
                "─────────────────────────"
            )
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

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=page_data["content"],
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
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

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="📖 *MANUEL — Menu principal*\n\nChoisis une catégorie :",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="📖 *MANUEL — Menu principal*\n\nChoisis une catégorie :",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )