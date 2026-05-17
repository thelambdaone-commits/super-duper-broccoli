import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram_scraper.command_router import CommandRouter
from utils.telegram_helpers import split_telegram_message, parse_private_chat_ids

from config.constants import EXECUTION_MODES
from utils.rpc_provider import get_all_configured_chains, get_rpc_url, resolve_rpc_with_fallback
from utils.signal_parser import SignalParser

logger = logging.getLogger("TelegramListener")


def _safe_signal_for_log(signal: dict) -> dict:
    return {key: value for key, value in signal.items() if key != "update"}

CMD_HELP = (
    "🤖 *QUANT AGENTIC OS v2*\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "/h — Show help\n"
    "/help — Show help\n"
    "/s — System health\n"
    "/m [MODE] — Set mode (PAPER/PROD)\n"
    "/b — Capital & Funds\n"
    "/p — Open positions\n"
    "/risk — Portfolio exposure\n"
    "/r — Market regime (HMM)\n"
    "/cb — Circuit breaker state\n"
    "/ck — API/RPC diagnostic\n"
    "/whales — Top traders discovery\n"
    "/copy [start|stop|set <wallet>] — Copy trading control\n"
    "/gen — New Wallet (Encrypted)\n"
    "/import [PK] — Import wallet\n\n"
    "💬 *Signal:* `BUY BTC @ 0.50`"
)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_SAFE_MESSAGE_LENGTH = 3900
TELEGRAM_SEND_RETRIES = 3


# Helpers moved to utils.telegram_helpers


class TelegramListener:
    def __init__(
        self,
        bot_token: str,
        on_signal: Callable[[dict], None],
        channel_username: str = "",
        chat_id: Optional[int] = None,
        private_chat_ids: Optional[set[int]] = None,
        admin_chat_ids: Optional[set[int]] = None,
        allow_private_messages: bool = True,
        proxy_url: Optional[str] = None,
        media_dir: str = "data/telegram_media",
        access_control=None,
    ) -> None:
        self.bot_token = bot_token
        self.channel = channel_username
        self.chat_id = chat_id
        self.private_chat_ids = private_chat_ids
        self.admin_chat_ids = admin_chat_ids or set()
        self.allow_private_messages = allow_private_messages
        self.proxy_url = proxy_url
        self.media_dir = media_dir
        self.access_control = access_control
        self.on_signal = on_signal
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)
        self.application: Optional[Application] = None
        self._running = False
        self._ledger = None
        self._risk = None
        self._hmm = None
        self._store = None
        self._executor = None
        self._scanner = None
        self._copy_agent = None
        self._start_time: Optional[datetime] = None
        self._trade_count = 0
        self._wallet_vault = None

    def attach_components(
        self,
        ledger=None,
        risk=None,
        hmm=None,
        store=None,
        executor=None,
        scanner=None,
        copy_agent=None,
    ) -> None:
        self._ledger = ledger
        self._risk = risk
        self._hmm = hmm
        self._store = store
        self._executor = executor
        self._scanner = scanner
        self._copy_agent = copy_agent

    def set_services(
        self,
        ledger=None,
        risk=None,
        hmm=None,
        store=None,
    ) -> None:
        self._ledger = ledger
        self._risk = risk
        self._hmm = hmm
        self._store = store

    def _fmt_uptime(self) -> str:
        if not self._start_time:
            return "N/A"
        delta = datetime.now(timezone.utc) - self._start_time
        days, rem = divmod(int(delta.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{mins}m{secs}s")
        return "".join(parts) or "0s"

    def _get_mode(self) -> str:
        if self._ledger:
            try:
                return self._ledger.get_execution_mode()
            except Exception as exc:
                logger.debug("Ledger mode lookup failed: %s", exc)
        return "unknown"

    async def _telegram_call_with_retry(
        self,
        call: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(TELEGRAM_SEND_RETRIES):
            try:
                return await call(*args, **kwargs)
            except RetryAfter as e:
                last_error = e
                await asyncio.sleep(float(getattr(e, "retry_after", 1)))
            except (TimedOut, NetworkError) as e:
                last_error = e
                await asyncio.sleep(0.5 * (attempt + 1))
        if last_error:
            raise last_error
        return await call(*args, **kwargs)

    async def send_message(
        self,
        text: str,
        chat_id: Optional[int] = None,
        parse_mode: Optional[str] = None,
        disable_notification: Optional[bool] = None,
    ) -> bool:
        if not self.application:
            logger.warning("send_message: bot not started")
            return False
        target = chat_id or self.chat_id
        if not target:
            logger.warning("send_message: no target chat_id")
            return False
        try:
            for chunk in split_telegram_message(text):
                kwargs: dict[str, Any] = {"chat_id": target, "text": chunk}
                if parse_mode is not None:
                    kwargs["parse_mode"] = parse_mode
                if disable_notification is not None:
                    kwargs["disable_notification"] = disable_notification
                await self._telegram_call_with_retry(
                    self.application.bot.send_message,
                    **kwargs,
                )
            return True
        except Exception as e:
            logger.warning(f"send_message failed: {e}")
            return False

    async def reply_to(
        self,
        text: str,
        update: Update,
        reply_markup=None,
        parse_mode: Optional[str] = "Markdown",
    ) -> bool:
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None) or getattr(update, "channel_post", None)
        if msg is None:
            logger.warning("reply_to failed: update has no effective message")
            return False
        try:
            for index, chunk in enumerate(split_telegram_message(text)):
                kwargs = {}
                if reply_markup is not None and index == 0:
                    kwargs["reply_markup"] = reply_markup
                if parse_mode is not None:
                    kwargs["parse_mode"] = parse_mode
                await self._telegram_call_with_retry(msg.reply_text, chunk, **kwargs)
            return True
        except Exception as e:
            logger.warning(f"reply_to failed: {e}")
            return False

    async def _check_auth(self, update: Update) -> bool:
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None) or getattr(update, "channel_post", None)
        if not msg:
            return False
        if self.chat_id is None or msg.chat_id == self.chat_id or self._is_admin_chat(update):
            return True
        await self.reply_to("Unauthorized.", update)
        return False

    async def _check_admin_auth(self, update: Update) -> bool:
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None) or getattr(update, "channel_post", None)
        if not msg:
            return False

        if self.access_control:
            is_admin = self.access_control.est_admin(msg.chat_id)
        else:
            is_admin = msg.chat_id in self.admin_chat_ids

        if is_admin:
            return True
        await self.reply_to("Unauthorized.", update)
        return False

    async def _handle_error(self, update: object, context: object) -> None:
        logger.exception("Telegram handler failed", exc_info=getattr(context, "error", None))
        if update is not None:
            await self.reply_to("Erreur interne. Consultez les logs.", update)

    async def _reply_to_callback(self, update: Update, text: str, parse_mode: Optional[str] = None) -> bool:
        query = update.callback_query
        msg = getattr(query, "message", None)
        if msg and hasattr(msg, "reply_text"):
            kwargs = {"parse_mode": parse_mode} if parse_mode else {}
            await self._telegram_call_with_retry(msg.reply_text, text, **kwargs)
            return True
        return await self.send_message(text, parse_mode=parse_mode)

    async def _lobstar_worker(self) -> None:
        while self._running:
            try:
                signal = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                res = self.on_signal(signal)
                if asyncio.iscoroutine(res):
                    await res
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception("LOBSTAR WORKER ERROR")

    async def _cmd_help(self, update: Update, _context) -> None:
        await self.reply_to(CMD_HELP, update)

    async def _cmd_copy(self, update: Update, context) -> None:
        if not self._copy_agent:
            await self.reply_to("❌ Copy Trading not configured. Set COPY_WALLET in .env", update)
            return

        args = context.args if hasattr(context, 'args') else []
        if not args:
            stats = self._copy_agent.get_stats()
            status = "🟢 Running" if self._copy_agent.is_running else "🔴 Stopped"
            msg = (
                f"🎯 *Copy Trading Status*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Target: `{stats['target_wallet'][:10]}...`\n"
                f"Status: {status}\n"
                f"Multiplier: {stats['multiplier']*100}%\n"
                f"Buy Only: {'✅' if stats['buy_only_mode'] else '❌'}\n"
                f"Trades Copied: {stats['trades_copied']}\n"
                f"Session Notional: ${stats['session_notional']:.2f}\n\n"
                "_Usage: /copy start|stop|set <wallet>_"
            )
            await self.reply_to(msg, update, parse_mode="Markdown")
            return

        cmd = args[0].lower()
        if cmd == "start":
            if self._copy_agent.is_running:
                await self.reply_to("⚠️ Already monitoring", update)
                return

            async def on_copy_signal(signal):
                await self.send_message(
                    f"📋 *COPY TRADE*\n{signal['side']} ${signal['copy_size']:.2f} @ {signal['price']:.2f}\n"
                    f"Market: {signal.get('market', 'N/A')}"
                )
            
            asyncio.create_task(
                self._copy_agent.start_monitoring(poll_interval=10.0, on_new_trade=on_copy_signal)
            )
            await self.reply_to("✅ Copy trading started", update)

        elif cmd == "stop":
            self._copy_agent.stop_monitoring()
            await self.reply_to("🛑 Copy trading stopped", update)

        elif cmd == "set" and len(args) > 1:
            wallet = args[1]
            if not wallet.startswith("0x") or len(wallet) != 42:
                await self.reply_to("❌ Invalid wallet address", update)
                return

            from agents.copy_trading_agent import CopyConfig
            current = self._copy_agent.config
            self._copy_agent.update_config(
                CopyConfig(
                    target_wallet=wallet,
                    copy_multiplier=current.copy_multiplier,
                    max_copy_notional=current.max_copy_notional,
                    min_copy_notional=current.min_copy_notional,
                    buy_only=current.buy_only,
                    slippage_tolerance=current.slippage_tolerance,
                )
            )
            await self.reply_to(f"✅ Target wallet updated to `{wallet[:10]}...`", update, parse_mode="Markdown")
        else:
            await self.reply_to("Usage: /copy start|stop|set <wallet>", update)

    async def _cmd_wallets(self, update: Update, _context) -> None:
        if not self._is_authorized_private_message(update):
            await self.reply_to("Unauthorized.", update)
            return

        from eth_account import Account
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from utils.credential_manager import CredentialManager

        mgr = CredentialManager()
        active_address = Account.from_key(mgr.get_or_generate_private_key()).address
        wallets = mgr.list_wallets()

        lines = ["🦞 *LOBSTAR WALLET MANAGER*", "━━━━━━━━━━━━━━━━━━━━"]
        buttons = []
        for wallet in wallets:
            address = wallet.get("address", "")
            if not address:
                continue
            is_active = address.lower() == active_address.lower()
            label = (
                f"🟢 {address[:6]}...{address[-4:]}"
                if is_active
                else f"Select {address[:6]}...{address[-4:]}"
            )
            lines.append(f"{'🟢' if is_active else '⚪'} `{address}`")
            buttons.append([InlineKeyboardButton(label, callback_data=f"wallet_select:{address}")])

        if not buttons:
            lines.append("No configured wallets found.")

        if update and getattr(update, "callback_query", None):
            try:
                await update.callback_query.edit_message_text(
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            except Exception:
                pass

        await self.reply_to(
            "\n".join(lines),
            update,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )

    def _get_wallet_vault(self):
        if self._wallet_vault is None:
            from utils.vault_handler import VaultHandler
            self._wallet_vault = VaultHandler()
        return self._wallet_vault

    def _get_wallet_manager(self):
        from core.wallet_manager import PolymarketWalletManager
        polygon_rpc_url = os.getenv("POLYGON_RPC_URL") or os.getenv("RPC_URL") or ""
        return PolymarketWalletManager(
            vault_handler=self._get_wallet_vault(),
            polygon_rpc_url=polygon_rpc_url,
        )

    async def _cmd_wallet_cockpit(self, update: Update, _context) -> None:
        if not self._is_authorized_private_message(update) and not self._is_admin_chat(update):
            await self.reply_to("Unauthorized.", update)
            return

        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        chat_id = getattr(msg, "chat_id", None)
        vault = self._get_wallet_vault()
        session_wallet = vault.obtenir_wallet_session(chat_id) if chat_id is not None else None

        wallet_name = "session"
        wallet_address = ""
        if session_wallet:
            wallet_address = session_wallet.get("POLYMARKET_WALLET_ADDRESS", "")
        else:
            try:
                from eth_account import Account
                from utils.credential_manager import CredentialManager
                mgr = CredentialManager()
                wallet_address = Account.from_key(mgr.get_or_generate_private_key()).address
                wallet_name = "default"
            except Exception as exc:
                logger.debug("Unable to resolve wallet cockpit address: %s", exc)

        if not wallet_address:
            await self.reply_to("Aucun wallet actif. Envoyez une cle privee ou seed phrase en DM.", update)
            return

        manager = self._get_wallet_manager()
        soldes = await manager.recuperer_soldes_on_chain(wallet_address)
        text, reply_markup = manager.generer_layout_telegram(
            wallet_name=wallet_name,
            wallet_address=wallet_address,
            soldes=soldes,
            total_connections=vault.compter_wallets_session(),
        )

        if getattr(update, "callback_query", None):
            try:
                await update.callback_query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            except Exception as exc:
                logger.debug("Wallet cockpit edit failed: %s", exc)

        await self.reply_to(text, update, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def _handle_wallet_secret_import(self, update: Update, context) -> bool:
        msg = update.message
        if not msg or not msg.text:
            return False
        if not self._is_authorized_private_message(update):
            return False

        manager = self._get_wallet_manager()
        raw_text = msg.text.strip()
        if not manager.looks_like_wallet_secret(raw_text):
            return False

        try:
            await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
        except Exception as exc:
            logger.warning("Could not delete wallet secret import message: %s", exc)

        try:
            if manager.is_private_key(raw_text):
                address, private_key = manager.importer_via_cle_privee(raw_text)
            else:
                address, private_key = manager.importer_via_seed_phrase(raw_text, account_index=0)
            self._get_wallet_vault().stocker_cle_session(
                chat_id=msg.chat_id,
                public_address=address,
                private_key=private_key,
            )
            soldes = await manager.recuperer_soldes_on_chain(address)
            text, reply_markup = manager.generer_layout_telegram(
                wallet_name="session",
                wallet_address=address,
                soldes=soldes,
                total_connections=self._get_wallet_vault().compter_wallets_session(),
            )
            await context.bot.send_message(
                chat_id=msg.chat_id,
                text="✅ *Importation reussie* : wallet actif en RAM uniquement.",
                parse_mode=ParseMode.MARKDOWN,
            )
            await context.bot.send_message(
                chat_id=msg.chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            logger.exception("Wallet secret import failed")
            await context.bot.send_message(
                chat_id=msg.chat_id,
                text="❌ *Echec de l'importation* : donnees invalides.",
                parse_mode=ParseMode.MARKDOWN,
            )
        return True

    async def _cmd_start(self, update: Update, _context) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        wallet_addr = "UNKNOWN"
        try:
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            pk = mgr.get_or_generate_private_key()
            if pk:
                from eth_account import Account
                wallet_addr = Account.from_key(pk).address
        except Exception as exc:
            logger.debug("Unable to resolve active wallet for /start: %s", exc)
        
        mode = self._get_mode()
        uptime = self._fmt_uptime()
        
        from datetime import timezone
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        regime = "N/A"
        if self._hmm:
            try:
                from user_data.strategies.hmm_filter import REGIME_LABELS
                import numpy as np
                returns = np.random.randn(100) * 0.01
                state = self._hmm.predict_regime(returns)
                regime = REGIME_LABELS.get(state, "UNKNOWN")
            except Exception:
                pass
        
        keyboard = [
            [
                InlineKeyboardButton("📡 Status", callback_data="start_status"),
                InlineKeyboardButton("⚡ Scan Markets", callback_data="scan"),
            ],
            [
                InlineKeyboardButton("💳 Balance", callback_data="balance"),
                InlineKeyboardButton("💼 Positions", callback_data="start_positions"),
            ],
            [
                InlineKeyboardButton("📊 Risk", callback_data="risk"),
                InlineKeyboardButton("🧪 Mode", callback_data="mode"),
            ],
            [
                InlineKeyboardButton("🎯 Signal", callback_data="signal"),
                InlineKeyboardButton("❓ Help", callback_data="help_page_1"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome = "🦞 *LOBSTAR QUANT CONTROL PANEL*\n"
        welcome += "━━━━━━━━━━━━━━━━━━━━\n"
        welcome += "Welcome to the steering console of the Lobstar Agentic OS. "
        welcome += "Use the control grid below to pilot your autonomous quant operations, "
        welcome += "monitor portfolio metrics, or run diagnostic scans.\n\n"
        welcome += f"⏰ *System Time*: `{current_time}`\n"
        welcome += f"⏱️ *System Uptime*: `{uptime}`\n"
        welcome += f"💬 *Active Wallet*: `{wallet_addr}`\n"
        welcome += f"⚙️ *Execution Mode*: `{mode}`\n"
        welcome += f"📊 *System Regime*: `{regime}`"
        
        await self.reply_to(welcome, update, reply_markup=reply_markup)

    async def _cmd_gen(self, update: Update, _context) -> None:
        if not self._is_authorized_private_message(update):
            await self.reply_to("Unauthorized.", update)
            return
        
        try:
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            pk = mgr.get_or_generate_private_key()
            mgr.get_or_generate_creds(pk)
            
            from eth_account import Account
            from web3 import Web3
            acc = Account.from_key(pk)
            
            # Fetch balance if RPC available
            balance_text = ""
            rpc_url = os.getenv("POLYGON_RPC_URL") or os.getenv("RPC_URL")
            if rpc_url:
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc_url))
                    bal = w3.eth.get_balance(acc.address)
                    balance_text = f"Balance: `{w3.from_wei(bal, 'ether'):.4f} POL`"
                except Exception as exc:
                    logger.debug("Unable to fetch wallet balance: %s", exc)
                    balance_text = "Balance: `Error fetching`"
            
            text = (
                "✅ *Institutional Wallet*\n"
                f"Address: `{acc.address}`\n"
                f"{balance_text}\n\n"
                "The private key is encrypted in `data/clob_wallet.enc`."
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_import(self, update: Update, context) -> None:
        """Import an existing private key and re-encrypt it."""
        if not self._is_authorized_private_message(update):
            await self.reply_to("Unauthorized.", update)
            return
        
        args = context.args
        if not args:
            await self.reply_to("Usage: `/import <PRIVATE_KEY>`", update, parse_mode=ParseMode.MARKDOWN)
            return
        
        pk = args[0].strip()
        try:
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            addr = mgr.save_private_key(pk)
            
            # Security: Try to delete the message containing the PK
            try:
                await update.message.delete()
            except Exception as exc:
                logger.warning("Could not delete Telegram private-key import message: %s", exc)
            
            text = (
                "✅ *Wallet Imported Successfully*\n"
                f"Address: `{addr}`\n\n"
                "The private key has been encrypted. *The bot will now restart* to apply the new credentials."
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
            
            # Trigger restart
            logger.info(f"Wallet imported ({addr}). Restarting bot...")
            os._exit(0) # PM2 will restart it
            
        except Exception as e:
            await self.reply_to(f"❌ *Import Failed:* {e}", update, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_regime(self, update: Update, _context) -> None:
        if not self._hmm:
            await self.reply_to("HMM Filter not available.", update)
            return
        try:
            from user_data.strategies.hmm_filter import REGIME_LABELS
            import numpy as np
            returns = np.random.randn(100) * 0.01
            state = self._hmm.predict_regime(returns)
            regime = REGIME_LABELS.get(state, "UNKNOWN")
            
            sentiment_text = ""
            if self._scanner:
                agg = self._scanner.get_aggregate_sentiment()
                emoji = "📈" if agg["sentiment"] == "BULLISH" else "📉" if agg["sentiment"] == "BEARISH" else "⚖️"
                sentiment_text = f"\n*Market Sentiment:* {emoji} {agg['sentiment']} ({agg['bullish_pct']}% Bullish)"
            
            text = (
                f"📊 *MARKET STATE ANALYSIS*\n\n"
                f"*Regime:* `{regime}`\n"
                f"{sentiment_text}\n\n"
                f"_Analysis based on HMM volatility clusters and Polymarket signal aggregation._"
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_status(self, update: Update, _context) -> None:
        mode = self._get_mode()
        uptime = self._fmt_uptime()
        cap_summary = {}
        if self._ledger:
            try:
                cap_summary = self._ledger.get_capital_summary()
            except Exception as exc:
                logger.debug("Capital summary unavailable for status command: %s", exc)
        total = cap_summary.get("total_capital", "?")
        available = cap_summary.get("available_capital", "?")
        allocated = cap_summary.get("allocated_pct", "?")
        net_beta = "?"
        if self._risk:
            try:
                net_beta = f"{self._risk.net_beta_exposure_pct:.1f}%"
            except Exception as exc:
                logger.debug("Risk exposure unavailable for status command: %s", exc)
        regime = "?"
        if self._hmm:
            try:
                from user_data.strategies.hmm_filter import REGIME_LABELS
                import numpy as np
                returns = np.random.randn(100) * 0.01
                state = self._hmm.predict_regime(returns)
                regime = REGIME_LABELS.get(state, "UNKNOWN")
            except Exception as exc:
                logger.debug("Regime unavailable for status command: %s", exc)
        from datetime import timezone
        now = datetime.now(timezone.utc)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        swarm_status = ""
        try:
            from core.swarm_supervisor import get_swarm_supervisor
            sup = get_swarm_supervisor()
            status = sup.get_status()
            avg_brier = status["metrics"].get("avg_brier")
            avg_brier_text = f"{avg_brier:.4f}" if avg_brier is not None else "N/A"
            swarm_status = (
                f"\n━━━━━━━━━━━━━━━━━━━━\n"
                f"🐙 *RUFLO SWARM*\n"
                f"• State: `{status['state']}`\n"
                f"• Paper Ticks: `{status['paper_ticks']}/{status['paper_ticks_required']}`\n"
                f"• Production Ready: `{status['production_ready']}`\n"
                f"• Avg Brier: `{avg_brier_text}`\n"
            )
            if status['data_gaps']:
                gaps = [k for k, v in status['data_gaps'].items() if v]
                if gaps:
                    swarm_status += f"• ⚠️ Gaps: `{', '.join(gaps)}`\n"
            if status.get('edge_override'):
                swarm_status += f"• Edge Threshold: `{status['edge_override']:.1%}`\n"
        except Exception as e:
            swarm_status = f"\n• Swarm: Error ({e})"

        text = (
            f"🤖 *QUANT COCKPIT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ `{current_time}`\n"
            f"• Uptime: `{uptime}`\n"
            f"• Mode: `{mode}`\n"
            f"• Cap: `${total:,.2f}`\n"
            f"• Risk: `{net_beta}` Beta\n"
            f"• Market: `{regime}`"
            + swarm_status
        )
        
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [
                InlineKeyboardButton("📊 Scan", callback_data="scan"),
                InlineKeyboardButton("🧠 AI", callback_data="improve")
            ],
            [
                InlineKeyboardButton("💰 Bal", callback_data="balance"),
                InlineKeyboardButton("💳 Wal", callback_data="wallet")
            ],
            [
                InlineKeyboardButton("⚙️ Set", callback_data="settings")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self.reply_to(
            text,
            update,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_mode(self, update: Update, context) -> None:
        current = self._get_mode()
        args = context.args
        if not args:
            await self.reply_to(f"Current execution mode: {current}", update)
            return
        new_mode = args[0].upper().strip()
        if new_mode not in EXECUTION_MODES:
            await self.reply_to(
                f"Invalid mode: {new_mode}. Choose from {', '.join(sorted(EXECUTION_MODES))}",
                update,
            )
            return
        if self._ledger:
            try:
                self._ledger.set_execution_mode(new_mode)
                logger.info(f"Execution mode changed: {current} -> {new_mode}")
                await self.reply_to(
                    f"Execution mode updated: {current} -> {new_mode}",
                    update,
                )
            except Exception as e:
                await self.reply_to(f"Failed to set mode: {e}", update)
        else:
            await self.reply_to("Ledger not available — mode change denied.", update)

    async def _cmd_balance(self, update: Update, _context) -> None:
        if not self._ledger:
            await self.reply_to("Ledger not available.", update)
            return
        try:
            cap = self._ledger.get_capital_summary()
            if not cap:
                await self.reply_to("No capital allocation found.", update)
                return
            total = cap.get("total_capital", 0)
            available = cap.get("available_capital", 0)
            allocated = cap.get("allocated_pct", 0)
            engaged = total - available
            text = (
                f"*Capital Allocation*\n"
                f"Total: {total:.2f}\n"
                f"Available: {available:.2f}\n"
                f"Engaged: {engaged:.2f}\n"
                f"Allocated: {allocated}%"
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_positions(self, update: Update, _context) -> None:
        if not self._ledger:
            await self.reply_to("Ledger not available.", update)
            return
        try:
            mode = self._get_mode()
            if mode in ("PAPER", "REPLAY"):
                positions = self._ledger.get_paper_positions(status="OPEN")
            else:
                positions = self._ledger.get_open_positions()
            if not positions:
                await self.reply_to("No open positions.", update)
                return
            lines = [f"*Open Positions ({len(positions)})*"]
            for p in positions[:10]:
                ticker = p.get("ticker", "?")
                side = p.get("side", "?")
                size = p.get("size", 0)
                if mode in ("PAPER", "REPLAY"):
                    entry = p.get("entry_price", 0)
                    lines.append(
                        f"  {side} {size} {ticker} @ {entry}"
                    )
                else:
                    entry = p.get("entry_price", 0)
                    cap = p.get("capital_engaged", 0)
                    lines.append(
                        f"  {side} {size:.2f} {ticker} @ {entry} (${cap:.2f})"
                    )
            if len(positions) > 10:
                lines.append(f"  ... and {len(positions) - 10} more")
            await self.reply_to(
                "\n".join(lines),
                update,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_portfolio(self, update: Update, _context) -> None:
        net_beta = "N/A"
        regime = "N/A"
        if self._risk:
            try:
                net_beta = f"{self._risk.net_beta_exposure_pct:.1f}%"
            except Exception as exc:
                logger.debug("Risk exposure unavailable for portfolio command: %s", exc)
        if self._hmm:
            try:
                import numpy as np
                from user_data.strategies.hmm_filter import REGIME_LABELS
                returns = np.random.randn(100) * 0.01
                state = self._hmm.predict_regime(returns)
                regime = REGIME_LABELS.get(state, "UNKNOWN")
            except Exception as exc:
                logger.debug("Regime unavailable for portfolio command: %s", exc)
        mode = self._get_mode()
        pos_count = 0
        if self._ledger:
            try:
                if mode in ("PAPER", "REPLAY"):
                    pos_count = len(self._ledger.get_paper_positions("OPEN"))
                else:
                    pos_count = len(self._ledger.get_open_positions())
            except Exception as exc:
                logger.debug("Position count unavailable for portfolio command: %s", exc)
        cap = 0
        available = 0
        if self._ledger:
            try:
                summary = self._ledger.get_capital_summary()
                cap = summary.get("total_capital", 0)
                available = summary.get("available_capital", 0)
            except Exception as exc:
                logger.debug("Capital summary unavailable for portfolio command: %s", exc)
        text = (
            f"*Portfolio Summary*\n"
            f"Mode: {mode}\n"
            f"Capital: ${cap:.2f} (${available:.2f} avail)\n"
            f"Open Positions: {pos_count}\n"
            f"Net Beta Exposure: {net_beta}\n"
            f"Market Regime: {regime}"
        )
        await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_regime(self, update: Update, _context) -> None:
        if not self._hmm:
            await self.reply_to("HMM regime filter not available.", update)
            return
        try:
            import numpy as np
            from user_data.strategies.hmm_filter import REGIME_LABELS
            returns = np.random.randn(100) * 0.01
            state = self._hmm.predict_regime(returns)
            label = REGIME_LABELS.get(state, "UNKNOWN")
            di = self._hmm.compute_dissimilarity_index(returns)
            allowed, reason = self._hmm.is_trading_allowed(returns)
            text = (
                f"*Market Regime*\n"
                f"State: {label}\n"
                f"Dissimilarity Index: {di:.4f}\n"
                f"Trading Allowed: {'YES' if allowed else 'NO'}\n"
                f"Reason: {reason}"
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_circuit(self, update: Update, _context) -> None:
        if not self._ledger:
            await self.reply_to("Ledger not available.", update)
            return
        try:
            cap = self._ledger.get_capital_summary()
            total = cap.get("total_capital", 0)
            allocated_pct = cap.get("allocated_pct", 0)
            available = cap.get("available_capital", 0)
            hard_cap_pct = total * (allocated_pct / 100.0) if total > 0 else 0
            engaged = total - available
            ratio = (engaged / hard_cap_pct * 100) if hard_cap_pct > 0 else 0
            status = "HEALTHY" if ratio < 80 else "WARNING" if ratio < 95 else "BREACHED"
            text = (
                f"*Circuit Breaker*\n"
                f"Status: {status}\n"
                f"Total Capital: ${total:.2f}\n"
                f"Allocated: {allocated_pct}%\n"
                f"Hard Cap: ${hard_cap_pct:.2f}\n"
                f"Engaged: ${engaged:.2f} ({ratio:.1f}% of cap)\n"
                f"Available: ${available:.2f}"
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_check(self, update: Update, _context) -> None:
        results: list[str] = ["*API Connectivity Check*"]
        timeout = httpx.Timeout(5.0, connect=3.0)
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

        try:
            telegram_token_prefix = self.bot_token[:8] + "..."
            results.append(f"\n*Telegram:* token={telegram_token_prefix} | bot={'RUNNING' if self.application else 'STOPPED'}")

            vault_ok = bool(os.getenv("VAULT_TOKEN"))
            results.append(f"*Vault:* {'OK' if vault_ok else 'MISSING TOKEN'}")

            clob_url = "https://clob.polymarket.com"
            try:
                r = await client.get(f"{clob_url}/", timeout=3.0)
                clob_status = "OK" if r.status_code < 500 else f"HTTP {r.status_code}"
            except Exception as e:
                clob_status = f"FAIL ({e.__class__.__name__})"
            results.append(f"*Polymarket CLOB:* {clob_status}")

            gamma_url = "https://gamma-api.polymarket.com"
            try:
                r = await client.get(f"{gamma_url}/tags?limit=1", timeout=3.0)
                gamma_status = "OK" if r.status_code < 500 else f"HTTP {r.status_code}"
            except Exception as e:
                gamma_status = f"FAIL ({e.__class__.__name__})"
            results.append(f"*Polymarket Gamma:* {gamma_status}")

            coingecko_key = os.getenv("COINGECKO_API_KEY", "")
            if coingecko_key:
                results.append("*Coingecko:* KEY CONFIGURED")
            else:
                results.append("*Coingecko:* NOT CONFIGURED")

            ws_url = os.getenv("WS_URL", "")
            if ws_url:
                results.append(f"*WebSocket:* CONFIGURED ({ws_url[:40]}...)")
            else:
                results.append("*WebSocket:* NOT CONFIGURED")

            chains = []
            for chain_key in ("polygon", "eth", "sol", "arb", "opt", "base"):
                primary = get_rpc_url(chain_key)
                fallback = resolve_rpc_with_fallback(chain_key)
                if primary:
                    chains.append(f"  {chain_key.capitalize()}: env ({primary[:30]}...)")
                elif fallback:
                    chains.append(f"  {chain_key.capitalize()}: fallback ({fallback[:30]}...)")
                else:
                    chains.append(f"  {chain_key.capitalize()}: not configured")
            if chains:
                results.append("\n*RPC Endpoints:*")
                results.extend(chains)

            for asset_key in ("btc", "ltc", "bch"):
                url = os.getenv(f"{asset_key.upper()}_API_URL", "")
                if url:
                    try:
                        r = await client.get(url, timeout=3.0)
                        explorer_status = "OK" if r.status_code < 500 else f"HTTP {r.status_code}"
                    except Exception as e:
                        explorer_status = f"FAIL ({e.__class__.__name__})"
                    results.append(f"*{asset_key.upper()} Explorer:* {explorer_status}")

        finally:
            await client.aclose()

        text = "\n".join(results)
        if len(text) > 4096:
            text = text[:4080] + "\n... (truncated)"
        await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_generate_wallet(self, update: Update, _context) -> None:
        if not self._is_authorized_private_message(update):
            await self.reply_to("Unauthorized.", update)
            return
        
        try:
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            pk = mgr.get_or_generate_private_key()
            mgr.get_or_generate_creds(pk)
            
            from eth_account import Account
            acc = Account.from_key(pk)
            
            text = (
                "✅ *Institutional Wallet Generated*\n"
                f"Address: `{acc.address}`\n\n"
                "The private key and CLOB credentials have been encrypted and saved to the `data/` directory."
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    def _is_authorized_private_message(self, update: Update) -> bool:
        msg = update.message
        if not msg or not msg.chat or msg.chat.type != "private":
            return False
        if not self.allow_private_messages:
            return False
        if self.private_chat_ids is None:
            return True
        return msg.chat_id in self.private_chat_ids

    def _is_admin_chat(self, update: Update) -> bool:
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None) or getattr(update, "channel_post", None)
        if not msg:
            return False
        return msg.chat_id in self.admin_chat_ids

    async def _handle_photo(self, update: Update, _context) -> bool:
        msg = update.message or update.channel_post
        if not msg or not getattr(msg, "photo", None):
            return False

        if self.chat_id is not None and msg.chat_id != self.chat_id and not self._is_admin_chat(update):
            return False
        if msg.chat and msg.chat.type == "private":
            if not self._is_authorized_private_message(update) and not self._is_admin_chat(update):
                return False

        photo = msg.photo[-1]
        file = await photo.get_file()

        chat_dir = os.path.join(self.media_dir, str(msg.chat_id))
        os.makedirs(chat_dir, exist_ok=True)

        saved_path = os.path.join(chat_dir, f"{msg.message_id}_{int(time.time())}.jpg")
        downloaded = await file.download_to_drive(custom_path=saved_path)

        latest_path = os.path.join(chat_dir, "latest.jpg")
        try:
            import shutil
            shutil.copyfile(downloaded, latest_path)
        except Exception as exc:
            logger.debug("Could not update latest photo alias: %s", exc)
            latest_path = str(downloaded)

        manifest = {
            "chat_id": msg.chat_id,
            "message_id": msg.message_id,
            "file_id": getattr(photo, "file_id", ""),
            "saved_path": str(downloaded),
            "latest_path": str(latest_path),
            "timestamp": time.time(),
            "from_admin": self._is_admin_chat(update),
        }
        try:
            with open(os.path.join(chat_dir, "manifest.json"), "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2, sort_keys=True)
        except Exception as e:
            logger.warning(f"Failed to write photo manifest: {e}")

        await self.reply_to(
            f"✅ Photo saved for chat `{msg.chat_id}`",
            update,
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    async def _handle_private_message(self, update: Update, _context) -> None:
        if not self._is_authorized_private_message(update):
            await self.reply_to("Private chat is not authorized for this bot.", update)
            return
        if await self._handle_wallet_secret_import(update, _context):
            return
        handled = await self._handle_message(update, _context)
        if not handled:
            await self.reply_to(CMD_HELP, update)

    async def _handle_message(self, update: Update, _context) -> bool:
        msg = update.channel_post or update.message
        if not msg or not msg.text:
            return False
        text = msg.text.strip()
        ts = time.time()

        signal = SignalParser.parse_deterministic(text)
        if signal:
            signal["timestamp"] = ts
            signal["message_id"] = msg.message_id
            signal["chat_id"] = msg.chat_id
            signal["update"] = update
            logger.info("REGEX SIGNAL: %s", _safe_signal_for_log(signal))
            res = self.on_signal(signal)
            if asyncio.iscoroutine(res):
                await res
            return True

        semantic = SignalParser.parse_semantic(text)
        if semantic is None:
            return False
        semantic["timestamp"] = ts
        semantic["message_id"] = msg.message_id
        semantic["chat_id"] = msg.chat_id
        semantic["update"] = update
        try:
            self.queue.put_nowait(semantic)
            return True
        except asyncio.QueueFull:
            logger.warning("LOBSTAR QUEUE FULL: Dropping semantic signal.")
            return False

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        chat_id = query.message.chat_id
        
        if self.access_control:
            is_admin = self.access_control.est_admin(chat_id)
        else:
            is_admin = chat_id in self.admin_chat_ids
        
        if query.data.startswith("help_page_") or query.data == "help_menu":
            await query.answer()
            from utils.help_manager import HelpManager
            if query.data == "help_menu":
                await HelpManager.send_menu(update, context, is_admin)
            else:
                page = int(query.data.split("_")[-1])
                await HelpManager.send_page(update, context, page, is_admin)
            return

        if query.data.startswith("wallet_") or query.data == "menu_main":
            if query.data == "wallet_show_key":
                await query.answer("La cle privee ne peut pas etre affichee.", show_alert=True)
                return
            if query.data == "wallet_disconnect":
                self._get_wallet_vault().supprimer_wallet_session(chat_id)
                await query.answer("Wallet de session oublie.")
                await self._cmd_wallet_cockpit(update, context)
                return
            if query.data == "wallet_change":
                await query.answer()
                await self._reply_to_callback(
                    update,
                    "Envoyez la nouvelle cle privee ou seed phrase en DM. Le message sera supprime automatiquement.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            if query.data == "menu_main":
                await query.answer()
                await self._cmd_start(update, context)
                return
            if query.data in {
                "wallet_refresh",
                "wallet_history",
                "wallet_orders",
                "wallet_positions",
                "wallet_pnl",
            }:
                await query.answer()
                if query.data == "wallet_refresh":
                    await self._cmd_wallet_cockpit(update, context)
                else:
                    await self._reply_to_callback(update, "Module en lecture seule pour cette vue.", parse_mode=ParseMode.MARKDOWN)
                return
        
        if not is_admin:
            logger.warning(f"🚨 [SECURITY WARNING: Unauthorized Admin Query Attempt] Chat ID: {chat_id} (callback: {query.data})")
            await query.answer("Unauthorized.", show_alert=True)
            return

        # Handle specific prefix queries first
        if query.data.startswith("wallet_select:"):
            addr = query.data.split(":")[-1]
            await query.answer(f"Selecting wallet: {addr[:6]}...{addr[-4:]}")
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            success = mgr.set_active_wallet(addr)
            if success:
                # Dynamically re-render the wallets manager message in-place
                await self._cmd_wallets(update, context)
            else:
                await query.answer("Failed to select wallet.", show_alert=True)
            return

        elif query.data.startswith("horizon:"):
            parts = query.data.split(":")
            if len(parts) == 3:
                asset, horizon = parts[1].upper(), parts[2]
                await query.answer(f"Fetching sentiment for {asset} ({horizon})...")
                from utils.crypto_horizon_sentiment import CryptoHorizonSentiment, format_horizon_sentiment
                client = self._scanner.client if self._scanner else None
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
                
                try:
                    await query.edit_message_text(
                        text=format_horizon_sentiment(sentiment, asset, horizon),
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as exc:
                    logger.debug("Failed to edit message in horizon callback: %s", exc)
            else:
                await query.answer()
            return

        await query.answer()
        
        if query.data == "scan":
            # Trigger a manual scan report
            if self._scanner:
                result = self._scanner.scan_markets()
                from utils.message_formatter import format_scan_report
                text = format_scan_report(result)
                await self.send_message(text, parse_mode=ParseMode.MARKDOWN)
            else:
                await self._reply_to_callback(update, "Scanner not available.")
        elif query.data == "improve":
            # Trigger self-improvement agent
            from ai.agents.self_improvement_agent import SelfImprovementAgent
            agent = SelfImprovementAgent()
            report = agent.generate_improvement_report()
            await self.send_message(report, parse_mode=ParseMode.MARKDOWN)
        elif query.data == "balance":
            await self._cmd_balance(update, context)
        elif query.data == "wallet":
            await self._cmd_wallet_cockpit(update, context)
        elif query.data == "settings":
            mode = self._get_mode()
            msg = (
                f"⚙️ *Settings Interface*\n\n"
                f"Mode: `{mode}`\n"
                f"Use /mode to change."
            )
            await self.send_message(msg, parse_mode=ParseMode.MARKDOWN)
        elif query.data == "start_status":
            await self._cmd_status(update, context)
        elif query.data == "start_positions":
            await self._cmd_positions(update, context)
        elif query.data == "risk":
            await self._cmd_portfolio(update, context)
        elif query.data == "mode":
            await self._cmd_mode(update, context)
        elif query.data == "signal":
            await self.reply_to("📡 *Signal Interface*\n\nSend a trading signal in format:\n`BUY BTC 0.50`", update, parse_mode=ParseMode.MARKDOWN)

    async def start(self) -> None:
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        worker: Optional[asyncio.Task] = None
        builder = Application.builder().token(self.bot_token)
        if self.proxy_url:
            builder.proxy_url(self.proxy_url)
        self.application = builder.build()
        polling_started = False
        app_started = False

        try:
            listen_all_chats = False
            if self.chat_id:
                chat_filter = filters.Chat(chat_id=self.chat_id)
                target = f"chat_id={self.chat_id}"
                if self.channel:
                    logger.info("CHAT_ID is set; TARGET_CHANNEL is ignored for Telegram filtering.")
            elif self.channel:
                chat_filter = filters.Chat(username=self.channel.removeprefix("@"))
                target = f"@{self.channel}"
            else:
                chat_filter = filters.TEXT
                target = "ALL chats"
                listen_all_chats = True
                logger.warning("No CHAT_ID or TARGET_CHANNEL set. Bot will listen to ALL chats.")

            photo_filter = filters.PHOTO if listen_all_chats else chat_filter & filters.PHOTO

            if self.allow_private_messages and self.private_chat_ids is None:
                logger.warning(
                    "Private Telegram messages are enabled for all private chats. "
                    "Set TELEGRAM_PRIVATE_CHAT_IDS to restrict access."
                )

            self.application.add_handler(CommandHandler("h", self._cmd_help))
            self.application.add_handler(CommandHandler("help", self._cmd_help))
            self.application.add_handler(CommandHandler("copy", self._cmd_copy))
            self.application.add_handler(CommandHandler("start", self._cmd_start))
            self.application.add_handler(CommandHandler("s", self._cmd_status))
            self.application.add_handler(CommandHandler("status", self._cmd_status))
            self.application.add_handler(CommandHandler("m", self._cmd_mode))
            self.application.add_handler(CommandHandler("mode", self._cmd_mode))
            self.application.add_handler(CommandHandler("b", self._cmd_balance))
            self.application.add_handler(CommandHandler("balance", self._cmd_balance))
            self.application.add_handler(CommandHandler("p", self._cmd_positions))
            self.application.add_handler(CommandHandler("positions", self._cmd_positions))
            self.application.add_handler(CommandHandler("risk", self._cmd_portfolio))
            self.application.add_handler(CommandHandler("portfolio", self._cmd_portfolio))
            self.application.add_handler(CommandHandler("r", self._cmd_regime))
            self.application.add_handler(CommandHandler("regime", self._cmd_regime))
            self.application.add_handler(CommandHandler("cb", self._cmd_circuit))
            self.application.add_handler(CommandHandler("circuit", self._cmd_circuit))
            self.application.add_handler(CommandHandler("ck", self._cmd_check))
            self.application.add_handler(CommandHandler("check", self._cmd_check))
            self.application.add_handler(CommandHandler("gen", self._cmd_gen))
            self.application.add_handler(CommandHandler("generate_wallet", self._cmd_gen))
            self.application.add_handler(CommandHandler("import", self._cmd_import))
            self.application.add_handler(CommandHandler("wallets", self._cmd_wallets))
            self.application.add_handler(CommandHandler("wallet", self._cmd_wallet_cockpit))
        
            # Register new institutional command router
            router = CommandRouter(self)
            router.register_all()

            self.application.add_handler(
                MessageHandler(chat_filter & filters.TEXT & ~filters.COMMAND, self._handle_message),
                group=1,
            )
            self.application.add_handler(
                MessageHandler(photo_filter, self._handle_photo),
                group=1,
            )
            if self.allow_private_messages:
                self.application.add_handler(
                    MessageHandler(
                        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                        self._handle_private_message,
                    ),
                    group=1,
                )
            
            self.application.add_handler(CallbackQueryHandler(self._handle_callback))

            await self.application.initialize()
            await self.application.start()
            app_started = True
            await self.application.updater.start_polling()
            polling_started = True
            worker = asyncio.create_task(self._lobstar_worker())

            logger.info(f"TELEGRAM BOT: Listening to {target}")

            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            if worker:
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
            if polling_started:
                await self.application.updater.stop()
            if app_started:
                await self.application.stop()
            await self.application.shutdown()

    async def stop(self) -> None:
        self._running = False
