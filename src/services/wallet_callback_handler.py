import logging
from typing import Any, Optional

logger = logging.getLogger("WalletCallbackHandler")


class WalletCallbackHandler:
    def __init__(
        self,
        wallet_manager: Any = None,
        history: Any = None,
        ledger: Any = None,
        broadcaster: Any = None,
        notifier: Any = None,
        scanner: Any = None,
    ) -> None:
        self.wallet_manager = wallet_manager
        self.history = history
        self.ledger = ledger
        self.broadcaster = broadcaster
        self.notifier = notifier
        self.scanner = scanner

    async def handle_callback(self, update: Any, context: Any) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        query = update.callback_query
        await query.answer()
        action = query.data
        chat_id = query.message.chat_id
        message_id = query.message.message_id

        logger.info("Wallet callback: %s from user %s", action, query.from_user.id)

        if action == "wallet_refresh":
            await self._handle_refresh(query, chat_id, message_id, context)
        elif action == "wallet_history":
            await self._handle_history(query, chat_id, message_id)
        elif action == "wallet_orders":
            await self._handle_orders(query, chat_id, message_id)
        elif action == "wallet_positions":
            await self._handle_positions(query, chat_id, message_id)
        elif action == "wallet_pnl":
            await self._handle_pnl(query, chat_id, message_id)
        elif action == "wallet_show_key":
            await self._handle_show_key(query, chat_id, message_id, context)
        elif action == "wallet_reveal_key_confirmed":
            await self._handle_reveal_key(query, chat_id, message_id, context)
        elif action == "wallet_change":
            await self._handle_change(query, chat_id, message_id, context)
        elif action == "wallet_disconnect":
            await self._handle_disconnect(query, chat_id, message_id, context)
        elif action == "wallet_disconnect_confirmed":
            await self._handle_disconnect_confirmed(query, chat_id, message_id, context)
        elif action == "wallet_settings":
            await self._handle_settings(query, chat_id, message_id, context)
        elif action == "menu_main":
            await self._handle_menu_main(query, chat_id, message_id, context)

    async def _handle_refresh(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        wallet_manager = self.wallet_manager
        vault = getattr(wallet_manager, "vault", None) if wallet_manager else None
        session = (
            vault.obtenir_wallet_session(chat_id)
            if vault and hasattr(vault, "obtenir_wallet_session")
            else None
        )
        wallet_address = (session or {}).get("POLYMARKET_WALLET_ADDRESS", "")
        proxy_address = (
            (session or {}).get("POLYMARKET_PROXY_WALLET_ADDRESS")
            or (session or {}).get("PROXY_WALLET_ADDRESS")
            or (session or {}).get("proxy_wallet", "")
        )
        if wallet_manager and wallet_address:
            soldes = await wallet_manager.recuperer_soldes_on_chain(
                wallet_address,
                proxy_address=proxy_address,
            )
        else:
            soldes = {"usdc_direct": 0.0, "usdc_proxy": 0.0, "eth_balance": 0.0}
        texte_mis_a_jour, keyboard = wallet_manager.generer_layout_telegram(
            wallet_name="session",
            wallet_address=wallet_address or "unavailable",
            soldes=soldes,
            total_connections=1,
        )
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texte_mis_a_jour,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    async def _handle_history(self, query: Any, chat_id: int, message_id: int) -> None:
        history_service = self.history
        if history_service:
            history = history_service.get_historical_performance(limit=10)
            if history:
                lines = [
                    f"\u2022 {t['ticker']} {t['side']}: ${t['net_pnl']:+.2f} ({'W' if t['is_win'] else 'L'})"
                    for t in history
                ]
                text = "<b>\U0001f4dc Historique</b>\n" + "\n".join(f"\u2022 {line}" for line in lines)
            else:
                text = "<b>\U0001f4dc Historique</b>\nAucune transaction compl\u00e9t\u00e9e."
        else:
            text = "<b>\U0001f4dc Historique</b>\nLedger non disponible."
        await query.message.edit_text(text, parse_mode="HTML")

    async def _handle_orders(self, query: Any, chat_id: int, message_id: int) -> None:
        text = "<b>\U0001f4cb Ordres</b>\nConsulte <code>/trade pnl</code> dans le chat pour les m\u00e9triques."
        await query.message.edit_text(text, parse_mode="HTML")

    async def _handle_positions(self, query: Any, chat_id: int, message_id: int) -> None:
        history_service = self.history
        if history_service:
            positions = history_service.get_open_positions()
            if positions:
                lines = []
                for p in positions[:12]:
                    ticker = str(p['ticker'])
                    
                    # Resolve ID to human-readable name
                    display_ticker = ticker
                    if ticker.isdigit() and self.scanner:
                        resolved = self.scanner.resolve_token_id_to_ticker(ticker)
                        if resolved:
                            display_ticker = resolved
                            
                    # Truncate if still long ID
                    if len(display_ticker) > 20 and display_ticker.isdigit():
                        display_ticker = f"ID:..{display_ticker[-6:]}"
                        
                    side = str(p['side']).upper()
                    side_emoji = "🟢" if side == "BUY" else "🔴"
                    
                    lines.append(f"{side_emoji} <b>{display_ticker}</b> {side} \u2014 <code>{p['size']:.1f}</code> @ <code>${p['entry_price']:.3f}</code>")
                
                text = "<b>\U0001f4ca Positions ouvertes</b>\n" + "\n".join(lines)
                if len(positions) > 12:
                    text += f"\n<i>... et {len(positions) - 12} autres.</i>"
            else:
                text = "<b>\U0001f4ca Positions ouvertes</b>\nAucune position ouverte."
        else:
            text = "<b>\U0001f4ca Positions ouvertes</b>\nLedger non disponible."
        await query.message.edit_text(text, parse_mode="HTML")

    async def _handle_pnl(self, query: Any, chat_id: int, message_id: int) -> None:
        history_service = self.history
        ledger = self.ledger
        if history_service and ledger:
            perf = history_service.get_performance_summary(mode=ledger.get_execution_mode())
            if perf and perf.get("total_trades", 0) > 0:
                wr = perf["win_rate"] * 100
                text = (
                    "<b>\U0001f4b0 PnL</b>\n"
                    f"Net: <code>${perf['total_net_pnl']:+.2f}</code>\n"
                    f"WR: <code>{wr:.1f}%</code> ({perf['winning_trades']}W/{perf['losing_trades']}L)\n"
                    f"PF: <code>{perf['profit_factor']:.2f}</code>"
                )
            else:
                text = "<b>\U0001f4b0 PnL</b>\nAucune donn\u00e9e. Fais du paper trading d'abord."
        else:
            text = "<b>\U0001f4b0 PnL</b>\nLedger non disponible."
        await query.message.edit_text(text, parse_mode="HTML")

    async def _handle_show_key(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        text = (
            "<b>\u26a0\ufe0f S\u00c9CURIT\u00c9 CL\u00c9 PRIV\u00c9E</b>\n"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            "Voulez-vous vraiment afficher la cl\u00e9 priv\u00e9e ?\n"
            "Assurez-vous d\u2019\u00eatre seul et \u00e0 l\u2019abri des regards."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 Confirmer", callback_data="wallet_reveal_key_confirmed")],
            [InlineKeyboardButton("\u274c Annuler", callback_data="wallet_settings")],
        ])
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    async def _handle_reveal_key(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                "<b>\U0001f512 Cl\u00e9 priv\u00e9e prot\u00e9g\u00e9e</b>\n"
                "La cl\u00e9 priv\u00e9e ne peut pas \u00eatre affich\u00e9e dans Telegram. "
                "R\u00e9importe le wallet si n\u00e9cessaire."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2b05\ufe0f Retour", callback_data="wallet_settings")]
            ]),
            parse_mode="HTML",
        )

    async def _handle_change(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="<b>\U0001f500 Changer de portefeuille</b>\nS\u00e9lectionnez un portefeuille sauvegard\u00e9 ou importez-en un nouveau.",
            parse_mode="HTML",
        )

    async def _handle_disconnect(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        text = (
            "<b>\u274c D\u00c9CONNEXION</b>\n"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            "Voulez-vous d\u00e9connecter le portefeuille ?\n"
            "Les cl\u00e9s seront purg\u00e9es de la RAM."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 D\u00e9connecter", callback_data="wallet_disconnect_confirmed")],
            [InlineKeyboardButton("\u274c Annuler", callback_data="wallet_settings")],
        ])
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    async def _handle_disconnect_confirmed(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        wallet_manager = self.wallet_manager
        vault = getattr(wallet_manager, "vault", None) if wallet_manager else None
        if not vault or not hasattr(vault, "supprimer_wallet_session"):
            logger.warning("Wallet disconnect requested but no session vault is attached.")
        else:
            vault.supprimer_wallet_session(chat_id)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="\u274c <b>Portefeuille d\u00e9connect\u00e9</b>.\nLes cl\u00e9s ont \u00e9t\u00e9 purg\u00e9es.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f3e0 Menu Principal", callback_data="menu_main")]
            ]),
            parse_mode="HTML",
        )

    async def _handle_settings(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("\U0001f511 Show Private Key", callback_data="wallet_show_key"),
                InlineKeyboardButton("\U0001f500 Switch Wallet", callback_data="wallet_change"),
            ],
            [
                InlineKeyboardButton("\u274c Disconnect", callback_data="wallet_disconnect"),
            ],
            [
                InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="wallet_refresh"),
            ],
        ])
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="<b>\u2699\ufe0f Wallet Settings</b>\nChoisis une action sensible:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    async def _handle_menu_main(self, query: Any, chat_id: int, message_id: int, context: Any) -> None:
        from utils.message_formatter import format_main_menu

        main_text, main_keyboard = format_main_menu()
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=main_text,
            reply_markup=main_keyboard,
            parse_mode="HTML",
        )
