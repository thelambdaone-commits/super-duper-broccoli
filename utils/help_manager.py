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
                "<b>💼 WALLET MANUAL</b>\n"
                "───────────────────\n"
                "• <code>/wallet add</code> ↳ Créer wallet\n"
                "• <code>/wallet import</code> ↳ Importer wallet\n"
                "• <code>/wallet use</code> ↳ Activer wallet\n"
                "• <code>/wallet backup</code> ↳ Sauvegarder\n"
                "• <code>/wallet status</code> ↳ Etat actuel\n\n"
                "• <code>/transfer</code> ↳ Envoyer USDC\n"
                "• <code>/signals</code> ↳ Voir signaux\n"
            )
        },
        2: {
            "title": "📈 MARKETS",
            "icon": "📈",
            "content": (
                "<b>📈 MARKETS MANUAL</b>\n"
                "───────────────────\n"
                "<b>AI Scoring:</b>\n"
                "• <code>/markets discover</code> ↳ Meilleurs marchés\n"
                "• <code>/markets opportunities</code> ↳ Paris edge %\n\n"
                "<b>Screening:</b>\n"
                "• <code>/markets vcp</code> ↳ Volatility patterns\n\n"
                "<b>Market Info:</b>\n"
                "• <code>/markets info</code> ↳ Détails marché\n"
                "• <code>/markets search</code> ↳ Rechercher\n"
                "• <code>/whales</code> ↳ Suivi baleines\n"
            )
        },
        3: {
            "title": "⚡ TRADING",
            "icon": "⚡",
            "content": (
                "<b>⚡ TRADING MANUAL</b>\n"
                "───────────────────\n"
                "• <code>/trade [ticker] [size]</code> ↳ Exécuter\n"
                "• <code>/paper [ticker]</code> ↳ Paper engine\n"
                "• <code>/clob [ticker]</code> ↳ Statut CLOB\n"
                "• <code>/ai [prompt]</code> ↳ Assistant IA\n\n"
                "• <code>/btc15</code>, <code>/eth1h</code> ↳ Crypto intel\n"
                "• <code>/crypto</code> ↳ Menu interactif\n"
            )
        },
        4: {
            "title": "👑 ADMIN",
            "icon": "👑",
            "content": (
                "<b>👑 ADMIN MANUAL</b>\n"
                "───────────────────\n"
                "• <code>/risk</code> ↳ Stats portfolio\n"
                "• <code>/risk freeze</code> ↳ Bloquer trading\n"
                "• <code>/risk resume</code> ↳ Reprendre\n"
                "• <code>/risk kill</code> ↳ Kill switch global\n\n"
                "• <code>/audit</code> ↳ Audit complet\n"
                "• <code>/dev</code> ↳ Commandes dev\n"
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

        row.append(InlineKeyboardButton("🏠 Menu", callback_data="menu_main"))

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
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=page_data["content"],
                parse_mode="HTML",
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

        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        text = "<b>📖 LOBSTAR MANUAL</b>\n\nChoisis une catégorie :"

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
