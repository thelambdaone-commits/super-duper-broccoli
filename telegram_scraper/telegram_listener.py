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
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram_scraper.command_router import CommandRouter
from core.command_router import LobstarCommandRouter
from utils.telegram_helpers import split_telegram_message, parse_private_chat_ids

from config.constants import EXECUTION_MODES
from utils.rpc_provider import get_all_configured_chains, get_rpc_url, resolve_rpc_with_fallback
from utils.signal_parser import SignalParser

logger = logging.getLogger("TelegramListener")


def _safe_signal_for_log(signal: dict) -> dict:
    return {key: value for key, value in signal.items() if key != "update"}


def _effective_user_id(update: Update) -> int | None:
    user = getattr(update, "effective_user", None)
    return getattr(user, "id", None) if user else None


def _callback_user_id(query: Any) -> int | None:
    user = getattr(query, "from_user", None)
    return getattr(user, "id", None) if user else None


def _is_private_chat_id(chat_id: int | None) -> bool:
    return chat_id is not None and chat_id > 0

CMD_HELP = (
    "```\n"
    "┌─────────────────────────┐\n"
    "│   🤖 SYSTEM MANUAL V2   │\n"
    "└─────────────────────────┘\n"
    "```\n"
    "⚙️ *Contrôles Système :*\n"
    "  • `/help` | `/h` ↳ Aide & Commandes\n"
    "  • `/s` ↳ État de santé du système\n"
    "  • `/m [MODE]` ↳ Mode d'exécution `[PAPER/PROD]`\n"
    "  • `/ck` ↳ Diagnostic API & RPC endpoints\n\n"
    "📈 *Gestion des Positions & Risques :*\n"
    "  • `/b` ↳ Capital & Répartition des fonds\n"
    "  • `/p` ↳ Positions de trading ouvertes\n"
    "  • `/risk` ↳ Exposition totale du portefeuille\n"
    "  • `/cb` ↳ État des disjoncteurs (Circuit Breaker)\n\n"
    "🧠 *Intelligence & Régimes :*\n"
    "  • `/r` ↳ Régime de marché en direct (HMM)\n"
    "  • `/whales` ↳ Leaderboard des traders baleines\n"
    "  • `/copy [start|stop|set]` ↳ Contrôle du copy trading\n\n"
    "🔐 *Sécurité & Comptes :*\n"
    "  • `/gen` ↳ Créer un nouveau portefeuille chiffré\n"
    "  • `/import [PK]` ↳ Importer une clé privée Polygon\n\n"
    "💬 *Signal:* `BUY BTC @ 0.50`\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━"
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
        self._market_reader = None
        self.command_router = LobstarCommandRouter(platform_core=self)
        self.passive_executor_allowed = True
        self._high_value_trade_approval_until: float = 0.0
        self._high_value_trade_approved_by: Optional[int] = None
        self._ready = asyncio.Event()

    def attach_components(
        self,
        ledger=None,
        risk=None,
        hmm=None,
        store=None,
        executor=None,
        scanner=None,
        copy_agent=None,
        market_reader=None,
        order_manager=None,
    ) -> None:
        self._ledger = ledger
        self._risk = risk
        self._hmm = hmm
        self._store = store
        self._executor = executor
        self._scanner = scanner
        self._copy_agent = copy_agent
        self._market_reader = market_reader
        self._order_manager = order_manager

    @property
    def wallet_manager(self):
        return self._get_wallet_manager()

    @property
    def wallet_address(self) -> str:
        try:
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            pk = mgr.get_or_generate_private_key()
            if pk:
                from eth_account import Account
                return Account.from_key(pk).address
        except Exception:
            pass
        return "0x0000000000000000000000000000000000000000"

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

    def authorize_high_value_trades(self, approver_id: int | None, ttl_seconds: int = 900) -> float:
        ttl = max(60, int(ttl_seconds))
        self._high_value_trade_approval_until = time.time() + ttl
        self._high_value_trade_approved_by = approver_id
        return self._high_value_trade_approval_until

    def high_value_trades_authorized(self) -> bool:
        return time.time() < self._high_value_trade_approval_until

    def revoke_high_value_trade_authorization(self) -> None:
        self._high_value_trade_approval_until = 0.0
        self._high_value_trade_approved_by = None

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
        reply_markup: Any | None = None,
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
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                await self._telegram_call_with_retry(
                    self.application.bot.send_message,
                    **kwargs,
                )
            return True
        except Exception as e:
            logger.warning(f"send_message failed: {e}")
            return False

    async def wait_until_ready(self, timeout: float = 30.0) -> bool:
        if self._ready.is_set():
            return True
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
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

        user_id = _effective_user_id(update)

        if self.chat_id is None:
            if self.private_chat_ids is not None or self.admin_chat_ids or self.access_control:
                if self._is_authorized_private_message(update) or self._is_admin_chat(update):
                    return True
                await self.reply_to("Unauthorized.", update)
                return False
            return True

        if (
            _is_private_chat_id(self.chat_id)
            and (msg.chat_id == self.chat_id or (user_id is not None and user_id == self.chat_id))
        ) or self._is_admin_chat(update):
            return True

        await self.reply_to("Unauthorized.", update)
        return False

    async def _check_admin_auth(self, update: Update) -> bool:
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None) or getattr(update, "channel_post", None)
        if not msg:
            return False

        user_id = _effective_user_id(update)

        is_admin = False
        if _is_private_chat_id(self.chat_id) and (
            msg.chat_id == self.chat_id or (user_id is not None and user_id == self.chat_id)
        ):
            is_admin = True
        elif self.access_control:
            is_admin = self.access_control.est_admin(msg.chat_id) or (user_id is not None and self.access_control.est_admin(user_id))
        else:
            is_admin = msg.chat_id in self.admin_chat_ids or (user_id is not None and user_id in self.admin_chat_ids)

        if is_admin:
            return True
        await self.reply_to("Unauthorized.", update)
        return False

    async def _handle_error(self, update: object, context: object) -> None:
        error = getattr(context, "error", None)
        if isinstance(error, BadRequest) and (
            "query is too old" in str(error).lower() or "query id is invalid" in str(error).lower()
        ):
            logger.info("Ignoring expired Telegram callback query: %s", error)
            return
        logger.exception("Telegram handler failed", exc_info=error)
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
                f"🎯 <b>Copy Trading Status</b>\n"
                f"───────────────────\n"
                f"Target: <code>{stats['target_wallet'][:10]}...</code>\n"
                f"Status: {status}\n"
                f"Multiplier: <code>{stats['multiplier']*100}%</code>\n"
                f"Trades: <code>{stats['trades_copied']}</code>\n"
                f"Session: <b>${stats['session_notional']:.2f}</b>\n\n"
                "<i>/copy start|stop|set &lt;wallet&gt;</i>"
            )
            await self.reply_to(msg, update, parse_mode="HTML")
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
            await self.reply_to(f"✅ Target wallet updated to <code>{wallet[:10]}...</code>", update, parse_mode="HTML")
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

    def _load_pnl_reference_capital(
        self,
        *,
        chat_id: int | str | None,
        active_address: str,
        proxy_address: str,
    ) -> float | None:
        state_path = os.getenv("POLYMARKET_PNL_STATE_PATH", "data/polymarket_pnl_state.json")
        try:
            with open(state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("Unable to load PnL state from %s: %s", state_path, exc)
            return None

        wallets = state.get("wallets", {}) if isinstance(state, dict) else {}
        candidates = [
            proxy_address.lower() if proxy_address else "",
            active_address.lower() if active_address else "",
            str(chat_id) if chat_id is not None else "",
        ]
        for key in candidates:
            if not key:
                continue
            entry = wallets.get(key)
            if not isinstance(entry, dict):
                continue
            value = entry.get("reference_capital")
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                logger.warning("Invalid reference_capital for PnL state wallet %s", key)
        return None

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
        proxy_address = ""
        if session_wallet:
            wallet_address = session_wallet.get("POLYMARKET_WALLET_ADDRESS", "")
        else:
            try:
                from eth_account import Account
                from utils.credential_manager import CredentialManager
                mgr = CredentialManager()
                if chat_id is not None and mgr.user_has_any_wallet(str(chat_id)):
                    wallet_type = mgr.get_active_wallet_type(str(chat_id))
                    user_data = mgr.load_user(str(chat_id), wallet_type)
                    wallet_address = user_data.get("address", "")
                    proxy_address = user_data.get("proxy_wallet", "")
                    wallet_name = wallet_type
                if not wallet_address:
                    wallet_address = Account.from_key(mgr.get_or_generate_private_key()).address
                    wallet_name = "default"
            except Exception as exc:
                logger.debug("Unable to resolve wallet cockpit address: %s", exc)

        if not wallet_address:
            await self.reply_to("Aucun wallet actif. Envoyez une cle privee ou seed phrase en DM.", update)
            return

        # Resolve proxy from Gamma API if not stored locally
        if not proxy_address and wallet_address:
            try:
                import httpx
                r = httpx.get(f"https://gamma-api.polymarket.com/public-profile?address={wallet_address}", timeout=5.0)
                if r.status_code == 200:
                    resolved = r.json().get("proxyWallet", "")
                    if resolved:
                        proxy_address = resolved
                        try:
                            mgr.set_user_proxy(chat_id, resolved, wallet_type=wallet_type)
                        except Exception:
                            pass
            except Exception:
                pass

        manager = self._get_wallet_manager()
        soldes = await manager.recuperer_soldes_on_chain(wallet_address, proxy_address=proxy_address)
        text, reply_markup = manager.generer_layout_telegram(
            wallet_name=wallet_name,
            wallet_address=wallet_address,
            soldes=soldes,
            total_connections=vault.compter_wallets_session(),
            proxy_address=proxy_address,
        )

        if getattr(update, "callback_query", None):
            try:
                await update.callback_query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception as exc:
                logger.debug("Wallet cockpit edit failed: %s", exc)

        await self.reply_to(text, update, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

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
                parse_mode=ParseMode.HTML,
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
        wallet_label = "Unresolved"
        try:
            from utils.credential_manager import CredentialManager
            mgr = CredentialManager()
            pk = mgr.get_or_generate_private_key()
            if pk:
                from eth_account import Account
                wallet_addr = Account.from_key(pk).address
                try:
                    wallet_label = mgr.get_active_wallet_type(str(getattr(update.effective_chat, "id", ""))).upper()
                except Exception:
                    wallet_label = "ACTIVE"
        except Exception as exc:
            logger.debug("Unable to resolve active wallet for /start: %s", exc)
            wallet_label = "ACTIVE"

        mode = self._get_mode()
        uptime = self._fmt_uptime()
        from datetime import timezone
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        regime = "READY"
        if self._hmm:
            try:
                labels = self._hmm.get_regime_labels()
                if labels:
                    regime = labels[0]
            except Exception as exc:
                logger.debug("Unable to resolve regime for /start: %s", exc)

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

        wallet_display = f"{wallet_addr[:6]}...{wallet_addr[-4:]}" if len(wallet_addr) > 10 else wallet_addr
        if wallet_addr == "UNKNOWN":
            wallet_display = "unavailable"

        welcome = (
            "🦞 *LOBSTAR QUANT CONTROL PANEL*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome to the steering console of the Lobstar Agentic OS.\n"
            "Use the control grid below to inspect status, markets, risk, and signals.\n\n"
            f"⏰ *System Time* : `{current_time}`\n"
            f"⏱️ *System Uptime* : `{uptime}`\n"
            f"💬 *Active Wallet* : `{wallet_label}` | `{wallet_display}`\n"
            f"🔗 *Wallet Address* : `{wallet_addr}`\n"
            f"⚙️ *Execution Mode* : `{mode}`\n"
            f"📊 *System Regime* : `{regime}`\n"
            "────────────────────────\n"
            "Tip: start with `📡 Status` or `📈 Markets`."
        )

        query = getattr(update, "callback_query", None)
        if query:
            try:
                await query.edit_message_text(
                    welcome,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            except Exception as exc:
                logger.debug("Failed to edit start menu: %s", exc)

        sent = await self.reply_to(welcome, update, reply_markup=reply_markup)
        if not sent:
            try:
                msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
                if msg:
                    await msg.reply_text(welcome, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as exc:
                logger.error("Failed to deliver /start menu: %s", exc)
                await self.send_message("❌ Impossible d'ouvrir le cockpit pour le moment.", parse_mode=ParseMode.MARKDOWN)

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

    async def _get_btc_returns(self, n: int = 100) -> Any | None:
        try:
            import numpy as np
            now = time.time()
            rows = []
            if self._store:
                rows = self._store.get_microstructure_range(now - 86400, now, ticker="BTC")
            if not rows:
                rows = []
                if self._store:
                    rows = self._store.get_microstructure_range(0, now, ticker="BTC")
            if len(rows) >= n:
                prices = [r["mid_price"] for r in rows if r.get("mid_price", 0) > 0]
                if len(prices) >= n:
                    arr = np.array(prices[-n:], dtype=np.float64)
                    rets = np.diff(arr) / arr[:-1]
                    return rets[-n+1:] if len(rets) >= 2 else None
            return None
        except Exception:
            return None

    async def _cmd_regime(self, update: Update, _context) -> None:
        if not self._hmm:
            await self.reply_to("HMM Filter not available.", update)
            return
        try:
            from user_data.strategies.hmm_filter import REGIME_LABELS
            import numpy as np
            returns = await self._get_btc_returns()
            if returns is not None and len(returns) > 0:
                state = self._hmm.predict_regime(returns)
                regime = REGIME_LABELS.get(state, "UNKNOWN")
            else:
                regime = "WAITING_FOR_DATA"

            sentiment_text = ""
            if self._scanner:
                agg = self._scanner.get_aggregate_sentiment()
                emoji = "📈" if agg["sentiment"] == "BULLISH" else "📉" if agg["sentiment"] == "BEARISH" else "⚖️"
                sentiment_text = f"📊 {emoji} `{agg['sentiment']}` (`{agg['bullish_pct']:.1f}%` Bullish)"

            text = (
                f"🧠 *VOLATILITY REGIME*\n"
                f"📈 `{regime}`\n"
                f"{sentiment_text}"
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
                returns = await self._get_btc_returns()
                if returns is not None and len(returns) > 0:
                    state = self._hmm.predict_regime(returns)
                    regime = REGIME_LABELS.get(state, "UNKNOWN")
                else:
                    regime = "WAITING_FOR_DATA"
            except Exception as exc:
                logger.debug("Regime unavailable for status command: %s", exc)
        from datetime import timezone
        now = datetime.now(timezone.utc)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")

        start_str = self._start_time.strftime("%Y-%m-%d %H:%M:%S UTC") if self._start_time else "N/A"

        if isinstance(total, (int, float)):
            total_str = f"${total:,.2f}"
        else:
            total_str = f"${total}"

        swarm_status = ""
        try:
            from core.swarm_supervisor import get_swarm_supervisor
            sup = get_swarm_supervisor()
            status = sup.get_status()
            avg_brier = status["metrics"].get("avg_brier")
            avg_brier_text = f"{avg_brier:.4f}" if avg_brier is not None else "N/A"

            ticks = status['paper_ticks']
            req = status['paper_ticks_required']
            pct_prog = (ticks / req * 100) if req > 0 else 0
            if pct_prog > 100: pct_prog = 100
            tick_bar_len = min(max(int(pct_prog / 10), 0), 10)
            tick_bar = "█" * tick_bar_len + "░" * (10 - tick_bar_len)

            swarm_status = (
                f"\n🐙 *RUFLO SWARM*\n"
                f"• State: `{status['state']}`\n"
                f"• Production Ready: `{status['production_ready']}`\n"
                f"• Avg Brier: `{avg_brier_text}` | Ticks: `{ticks}/{req}`\n"
                f"• PROD: `{pct_prog:.1f}%`\n"
                f"{tick_bar}\n"
            )
            if status['data_gaps']:
                gaps = [k for k, v in status['data_gaps'].items() if v]
                if gaps:
                    swarm_status += f"• ⚠️ Gaps: `{', '.join(gaps)}`\n"
            if status.get('edge_override'):
                swarm_status += f"• Edge Override: `{status['edge_override']:.1%}`\n"
        except Exception as e:
            swarm_status = f"\n🐙 *RUFLO SWARM* : Error (`{e}`)"

        text = (
            f"🤖 *QUANT COCKPIT V2*\n"
            f"🟢 `Active` ⏰ `{current_time}`\n"
            f"⏱️ `{uptime}` 🎯 `{mode}`\n"
            f"💰 `{total_str}` 🛡️ `{net_beta}`\n"
            f"📈 `{regime}`"
            f"{swarm_status}"
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

        query = getattr(update, "callback_query", None)
        if query:
            try:
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            except Exception as exc:
                logger.debug("Failed to edit status cockpit: %s", exc)

        await self.reply_to(
            text,
            update,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_mode(self, update: Update, context) -> None:
        if not await self._check_auth(update):
            return
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
            engaged = total - available

            pct = 100.0
            bar_len = min(max(int(pct / 10), 0), 10)
            bar = "█" * bar_len + "░" * (10 - bar_len)

            total_str = f"{total:,.2f}"
            available_str = f"{available:,.2f}"
            engaged_str = f"{engaged:,.2f}"

            text = (
                "💎 Portfolio\n"
                "──────────────\n"
                f"💰 Total: {total_str} USD\n"
                f"💵 Cash: {available_str} USD\n"
                f"🔒 Engagé: {engaged_str} USD\n\n"
                f"📊 Risque: {pct:.0f}%\n"
                f"[{bar}]"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [[InlineKeyboardButton("⬅️ Retour Cockpit", callback_data="start_status")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            query = getattr(update, "callback_query", None)
            if query:
                try:
                    await query.edit_message_text(
                        text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return
                except Exception as exc:
                    logger.debug("Failed to edit balance: %s", exc)

            await self.reply_to(text, update, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
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
                await self.reply_to("🔍 Aucune position ouverte.", update)
                return
            lines = [
                "```\n"
                "┌─────────────────────────┐\n"
                f"│   💼 OPEN POSITIONS     │\n"
                "└─────────────────────────┘\n"
                "```\n"
                f"💼 *Positions Ouvertes ({len(positions)})*",
                "────────────────────────"
            ]
            for p in positions[:10]:
                ticker = p.get("ticker", "?")
                side = p.get("side", "?").upper()
                side_emoji = "🟢 BUY" if side == "BUY" else "🔴 SELL"
                size = p.get("size", 0)
                entry = p.get("entry_price", 0)
                if mode in ("PAPER", "REPLAY"):
                    lines.append(
                        f"  {side_emoji} `{size:.2f}` {ticker} @ `${entry:.3f}`"
                    )
                else:
                    cap = p.get("capital_engaged", 0)
                    lines.append(
                        f"  {side_emoji} `{size:.2f}` {ticker} @ `${entry:.3f}` (`${cap:.2f}`)"
                    )
            if len(positions) > 10:
                lines.append(f"  ... and {len(positions) - 10} more")
            lines.append("────────────────────────")
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
                from user_data.strategies.hmm_filter import REGIME_LABELS
                returns = await self._get_btc_returns()
                if returns is not None and len(returns) > 0:
                    state = self._hmm.predict_regime(returns)
                    regime = REGIME_LABELS.get(state, "UNKNOWN")
                else:
                    regime = "WAITING_FOR_DATA"
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
            f"📊 *Portfolio Summary*\n"
            f"🎯 `{mode}` 💰 `${cap:.2f}` 💵 `${available:.2f}`\n"
            f"📦 `{pos_count}` 🛡️ `{net_beta}` 📈 `{regime}`"
        )
        await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)

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

            status_emoji = "🟢 HEALTHY" if status == "HEALTHY" else "⚠️ WARNING" if status == "WARNING" else "🚨 BREACHED"
            text = (
                "```\n"
                "┌─────────────────────────┐\n"
                "│  ⚡ CIRCUIT BREAKER OS  │\n"
                "└─────────────────────────┘\n"
                "```\n"
                f"🛡️ *Breaker Status* : `{status_emoji}`\n"
                f"💰 *Total Capital* : `{total:.2f} $`\n"
                f"📈 *Allocated Limit* : `{allocated_pct:.1f}%`\n"
                f"🛑 *Hard Cap Limit* : `{hard_cap_pct:.2f} $`\n"
                f"🔒 *Engaged Funds* : `{engaged:.2f} $` (`{ratio:.1f}%` du Cap)\n"
                f"💵 *Available Funds* : `{available:.2f} $`\n"
                "────────────────────────"
            )
            await self.reply_to(text, update, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await self.reply_to(f"Error: {e}", update)

    async def _cmd_check(self, update: Update, _context) -> None:
        lines = [
            "```\n"
            "┌─────────────────────────┐\n"
            "│  🛠️ CONNECTIVITY CHECK  │\n"
            "└─────────────────────────┘\n"
            "```\n"
            "────────────────────────"
        ]
        timeout = httpx.Timeout(5.0, connect=3.0)
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

        try:
            telegram_token_prefix = self.bot_token[:8] + "..."
            bot_state = "RUNNING" if self.application else "STOPPED"
            lines.append(f"💬 *Telegram* : `token={telegram_token_prefix}` | `{bot_state}`")

            vault_ok = bool(os.getenv("VAULT_TOKEN"))
            lines.append(f"🛡️ *HashiCorp Vault* : `{'CONNECTED 🟢' if vault_ok else 'MISSING TOKEN 🔴'}`")

            clob_url = "https://clob.polymarket.com"
            try:
                r = await client.get(f"{clob_url}/", timeout=3.0)
                clob_status = "ONLINE 🟢" if r.status_code < 500 else f"HTTP {r.status_code} 🟡"
            except Exception as e:
                clob_status = f"OFFLINE 🔴 ({e.__class__.__name__})"
            lines.append(f"🌐 *Polymarket CLOB* : `{clob_status}`")

            gamma_url = "https://gamma-api.polymarket.com"
            try:
                r = await client.get(f"{gamma_url}/tags?limit=1", timeout=3.0)
                gamma_status = "ONLINE 🟢" if r.status_code < 500 else f"HTTP {r.status_code} 🟡"
            except Exception as e:
                gamma_status = f"OFFLINE 🔴 ({e.__class__.__name__})"
            lines.append(f"📈 *Polymarket Gamma* : `{gamma_status}`")

            coingecko_key = os.getenv("COINGECKO_API_KEY", "")
            cg_status = "CONFIGURED 🟢" if coingecko_key else "NOT CONFIGURED 🟡"
            lines.append(f"💰 *CoinGecko API* : `{cg_status}`")

            ws_url = os.getenv("WS_URL", "")
            ws_status = f"ONLINE 🟢 ({ws_url[:20]}...)" if ws_url else "NOT CONFIGURED 🟡"
            lines.append(f"🔌 *Websocket Feed* : `{ws_status}`")

            chains = []
            for chain_key in ("polygon", "eth", "sol", "arb", "opt", "base"):
                primary = get_rpc_url(chain_key)
                fallback = resolve_rpc_with_fallback(chain_key)
                if primary:
                    chains.append(f"  • {chain_key.capitalize()} : `env` ({primary[:15]}...)")
                elif fallback:
                    chains.append(f"  • {chain_key.capitalize()} : `fallback` ({fallback[:15]}...)")
                else:
                    chains.append(f"  • {chain_key.capitalize()} : `not configured` 🔴")
            if chains:
                lines.append("\n⛓️ *RPC Endpoints :*")
                lines.extend(chains)

            explorers = []
            for asset_key in ("btc", "ltc", "bch"):
                url = os.getenv(f"{asset_key.upper()}_API_URL", "")
                if url:
                    try:
                        r = await client.get(url, timeout=3.0)
                        explorer_status = "ONLINE 🟢" if r.status_code < 500 else f"HTTP {r.status_code} 🟡"
                    except Exception as e:
                        explorer_status = f"OFFLINE 🔴 ({e.__class__.__name__})"
                    explorers.append(f"  • {asset_key.upper()} Explorer : `{explorer_status}`")
            if explorers:
                lines.append("\n🔍 *Block Explorers :*")
                lines.extend(explorers)

        finally:
            await client.aclose()

        lines.append("────────────────────────")
        text = "\n".join(lines)
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

        user_id = _effective_user_id(update)

        if _is_private_chat_id(self.chat_id) and (
            msg.chat_id == self.chat_id or (user_id is not None and user_id == self.chat_id)
        ):
            return True

        if self.access_control:
            return self.access_control.est_admin(msg.chat_id) or (user_id is not None and self.access_control.est_admin(user_id))

        return msg.chat_id in self.admin_chat_ids or (user_id is not None and user_id in self.admin_chat_ids)

    async def _handle_photo(self, update: Update, _context) -> bool:
        msg = update.message or update.channel_post
        if not msg or not getattr(msg, "photo", None):
            return False

        if _is_private_chat_id(self.chat_id) and msg.chat_id != self.chat_id and not self._is_admin_chat(update):
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
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        query = update.callback_query
        chat_id = query.message.chat_id

        user_id = _callback_user_id(query)

        is_admin = False
        if _is_private_chat_id(self.chat_id) and (
            chat_id == self.chat_id or (user_id is not None and user_id == self.chat_id)
        ):
            is_admin = True
        elif self.access_control:
            is_admin = self.access_control.est_admin(chat_id) or (user_id is not None and self.access_control.est_admin(user_id))
        else:
            is_admin = chat_id in self.admin_chat_ids or (user_id is not None and user_id in self.admin_chat_ids)

        if not is_admin:
            logger.warning(
                "🚨 [SECURITY WARNING: Unauthorized Callback Attempt] Chat ID: %s User ID: %s (callback: %s)",
                chat_id,
                user_id,
                query.data,
            )
            await query.answer("Unauthorized.", show_alert=True)
            return

        async def safe_edit_callback(q, text, reply_markup=None, parse_mode=None):
            if hasattr(q, "edit_message_text"):
                try:
                    kwargs = {}
                    if reply_markup is not None:
                        kwargs["reply_markup"] = reply_markup
                    if parse_mode is not None:
                        kwargs["parse_mode"] = parse_mode
                    await q.edit_message_text(text, **kwargs)
                    return
                except Exception as exc:
                    logger.debug("edit_message_text failed, falling back: %s", exc)

            msg = getattr(q, "message", None)
            if msg and hasattr(msg, "reply_text"):
                kwargs = {}
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                if parse_mode is not None:
                    kwargs["parse_mode"] = parse_mode
                await msg.reply_text(text, **kwargs)

        if query.data.startswith("help_page_") or query.data == "help_menu":
            try:
                await query.answer()
            except Exception as exc:
                logger.debug("Callback answer failed (ignored): %s", exc)
            from utils.help_manager import HelpManager
            if query.data == "help_menu":
                await HelpManager.send_menu(update, context, is_admin)
            else:
                page = int(query.data.split("_")[-1])
                await HelpManager.send_page(update, context, page, is_admin)
            return

        if query.data.startswith("wallet_") or query.data == "menu_main":
            try:
                await query.answer()
            except Exception as exc:
                logger.debug("Callback answer failed (ignored): %s", exc)
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
            if query.data == "wallet_settings":
                manager = self._get_wallet_manager()
                text, reply_markup = manager.generer_settings_layout()
                await safe_edit_callback(query, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
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
                    # Fetch active wallet details exactly matching cockpit strategy
                    vault = self._get_wallet_vault()
                    session_wallet = vault.obtenir_wallet_session(chat_id) if chat_id is not None else None

                    wallet_name = "session"
                    active_address = ""
                    proxy_address = ""

                    if session_wallet:
                        active_address = session_wallet.get("POLYMARKET_WALLET_ADDRESS", "")
                        proxy_address = session_wallet.get("proxy_wallet", "")
                    else:
                        try:
                            from utils.credential_manager import CredentialManager
                            mgr = CredentialManager()
                            if chat_id is not None and mgr.user_has_any_wallet(str(chat_id)):
                                wallet_type = mgr.get_active_wallet_type(str(chat_id))
                                user_data = mgr.load_user(str(chat_id), wallet_type)
                                active_address = user_data.get("address", "")
                                proxy_address = user_data.get("proxy_wallet", "")
                                wallet_name = wallet_type
                            if not active_address:
                                active_address = mgr.get_active_wallet() or ""
                                wallet_name = "Global"
                        except Exception as exc:
                            logger.debug("Unable to resolve active address in callbacks: %s", exc)

                    # If proxy address not defined, attempt dynamic profile resolution from Gamma API
                    if active_address and not proxy_address:
                        try:
                            import httpx
                            r_prof = httpx.get(f"https://gamma-api.polymarket.com/public-profile?address={active_address}", timeout=3.0)
                            if r_prof.status_code == 200:
                                pdata = r_prof.json()
                                resolved = pdata.get("proxyWallet")
                                if resolved:
                                    proxy_address = resolved
                                    try:
                                        wtype = mgr.get_active_wallet_type(chat_id)
                                        mgr.set_user_proxy(chat_id, resolved, wallet_type=wtype)
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                    target_address = proxy_address if proxy_address else active_address

                    if not target_address:
                        no_wallet_text = (
                            "🎯 *Polymarket Cockpit*\n"
                            "────────────────────────\n"
                            "⚠️ *No Wallet found.*\n"
                            "Please import or switch to an active wallet first.\n"
                            "────────────────────────"
                        )
                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")]])
                        await query.edit_message_text(no_wallet_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                        return

                    if query.data == "wallet_history":
                        import httpx
                        open_pos = []
                        closed_pos = []
                        activity = []

                        try:
                            async with httpx.AsyncClient(timeout=8.0) as client:
                                r_open = await client.get(f"https://data-api.polymarket.com/positions?user={target_address}&limit=50")
                                if r_open.status_code == 200:
                                    open_pos = r_open.json()
                                r_closed = await client.get(f"https://data-api.polymarket.com/closed-positions?user={target_address}&limit=50")
                                if r_closed.status_code == 200:
                                    closed_pos = r_closed.json()
                                r_act = await client.get(f"https://data-api.polymarket.com/activity?user={target_address}&limit=50&type=TRADE")
                                if r_act.status_code == 200:
                                    activity = r_act.json()
                        except Exception as e:
                            logger.error("Failed to query Polymarket API history: %s", e)

                        # Compute metrics robustly to prevent crashes
                        volume_total = 0.0
                        if isinstance(activity, list):
                            for x in activity:
                                try:
                                    u_sz = x.get("usdcSize")
                                    if u_sz is not None:
                                        volume_total += float(u_sz)
                                    else:
                                        sz = x.get("size")
                                        pr = x.get("price")
                                        if sz is not None and pr is not None:
                                            volume_total += float(sz) * float(pr)
                                except Exception:
                                    pass

                        realized_pnl = 0.0
                        if isinstance(closed_pos, list):
                            for x in closed_pos:
                                try:
                                    val = x.get("realizedPnl")
                                    if val is not None:
                                        realized_pnl += float(val)
                                except Exception:
                                    pass

                        pnl_emoji = "🟢" if realized_pnl >= 0 else "🔴"
                        pnl_sign = "+" if realized_pnl > 0 else ""

                        # Layout exactly matching user format
                        lines = [
                            "<b>📜 POLYMARKET HISTORY</b>",
                            "───────────────────",
                            f"⭐ <b>Wallet</b>: {self._html(wallet_name.capitalize())}",
                            f"📬 <code>{self._html(target_address)}</code>",
                            f"💵 <b>Volume Total</b>: <code>${volume_total:.2f}</code>",
                            f"📦 <b>Open Positions</b>: <code>{len(open_pos) if isinstance(open_pos, list) else 0}</code>",
                            f"✅ <b>Closed Positions</b>: <code>{len(closed_pos) if isinstance(closed_pos, list) else 0}</code>",
                            f"{pnl_emoji} <b>PnL Réalisé</b>: <b>{pnl_sign}${realized_pnl:.2f}</b>",
                            "───────────────────"
                        ]

                        if not activity or not isinstance(activity, list):
                            lines.append("\n<i>Aucune transaction récente sur pUSD détectée.</i>")
                        else:
                            # Show up to 6 trades
                            for act in activity[:6]:
                                try:
                                    title = self._html(act.get("title", "Unknown Market"))
                                    side = self._html(str(act.get("side", "BUY")).upper())
                                    outcome = self._html(act.get("outcome", "YES"))

                                    size_val = act.get("size", 0.0)
                                    size = float(size_val) if size_val is not None else 0.0

                                    price_val = act.get("price", 0.0)
                                    price = float(price_val) if price_val is not None else 0.0

                                    ts = act.get("timestamp", 0)
                                    date_str = ""
                                    if ts:
                                        try:
                                            from datetime import datetime
                                            date_str = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
                                        except Exception:
                                            pass

                                    lines.extend([
                                        f"🎯 <b>{title}</b>",
                                        f"• <b>{side}</b> <code>{outcome}</code>",
                                        f"• Size: <code>{size:.2f}</code>",
                                        f"• Price: <code>${price:.3f}</code>",
                                    ])
                                    if date_str:
                                        lines.append(f"• Date: <code>{date_str}</code>")
                                    lines.append("───────────────────")
                                except Exception:
                                    pass

                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")]])
                        await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode=ParseMode.HTML)

                    elif query.data == "wallet_orders":
                        orders_text = (
                            "<b>🎯 Polymarket Cockpit</b>\n"
                            "───────────────────\n"
                            "📋 <b>Active Orders</b>:\n"
                            "No active pending orders detected on-chain.\n"
                            "───────────────────"
                        )
                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")]])
                        await query.edit_message_text(orders_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

                    elif query.data == "wallet_positions":
                        import httpx
                        open_pos = []
                        try:
                            async with httpx.AsyncClient(timeout=8.0) as client:
                                r_open = await client.get(f"https://data-api.polymarket.com/positions?user={target_address}&limit=50")
                                if r_open.status_code == 200:
                                    open_pos = r_open.json()
                        except Exception as e:
                            logger.error("Failed to query open positions: %s", e)

                        lines = [
                            "<b>🎯 Polymarket Cockpit</b>",
                            "───────────────────",
                            "📊 <b>Open Positions</b>:"
                        ]

                        if not open_pos or not isinstance(open_pos, list):
                            lines.append("No active open positions on Polymarket found.")
                        else:
                            for pos in open_pos[:10]:
                                try:
                                    title = self._html(pos.get("title", "Unknown Market"))
                                    outcome = self._html(pos.get("outcome", "YES"))

                                    size_val = pos.get("size", 0.0)
                                    size = float(size_val) if size_val is not None else 0.0

                                    avg_val = pos.get("avgPrice", 0.0)
                                    avg_price = float(avg_val) if avg_val is not None else 0.0

                                    cur_val = pos.get("curPrice", 0.0)
                                    cur_price = float(cur_val) if cur_val is not None else 0.0

                                    cash_pnl = 0.0
                                    pnl_val = pos.get("cashPnl")
                                    if pnl_val is None:
                                        pnl_val = pos.get("unrealizedPnl")
                                    if pnl_val is not None:
                                        cash_pnl = float(pnl_val)

                                    pnl_emoji = "🟢" if cash_pnl >= 0 else "🔴"
                                    pnl_sign = "+" if cash_pnl > 0 else ""

                                    lines.extend([
                                        f"🎯 <b>{title}</b>",
                                        f"• Outcome: <code>{outcome}</code>",
                                        f"• Size: <code>{size:.2f}</code> shares",
                                        f"• Entry: <code>${avg_price:.3f}</code>",
                                        f"• Mark: <code>${cur_price:.3f}</code>",
                                        f"• PnL: {pnl_emoji} <b>{pnl_sign}${cash_pnl:.2f}</b>",
                                        "───────────────────"
                                    ])
                                except Exception:
                                    pass

                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")]])
                        await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode=ParseMode.HTML)

                    elif query.data == "wallet_pnl":
                        import httpx
                        closed_pos = []
                        open_pos = []
                        try:
                            async with httpx.AsyncClient(timeout=8.0) as client:
                                r_open = await client.get(f"https://data-api.polymarket.com/positions?user={target_address}&limit=500&sizeThreshold=0")
                                if r_open.status_code == 200:
                                    open_pos = r_open.json()
                                r_closed = await client.get(f"https://data-api.polymarket.com/closed-positions?user={target_address}&limit=50")
                                if r_closed.status_code == 200:
                                    closed_pos = r_closed.json()
                        except Exception as e:
                            logger.error("Failed to query closed positions for PnL: %s", e)

                        total_wins = 0
                        total_losses = 0
                        total_realized_pnl = 0.0
                        open_cash_pnl = 0.0
                        open_current_value = 0.0

                        if isinstance(closed_pos, list):
                            for x in closed_pos:
                                try:
                                    val = x.get("realizedPnl")
                                    if val is not None:
                                        pnl_val = float(val)
                                        total_realized_pnl += pnl_val
                                        if pnl_val > 0:
                                            total_wins += 1
                                        elif pnl_val < 0:
                                            total_losses += 1
                                except Exception:
                                    pass

                        if isinstance(open_pos, list):
                            for x in open_pos:
                                try:
                                    open_cash_pnl += float(x.get("cashPnl") or 0.0)
                                    open_current_value += float(x.get("currentValue") or 0.0)
                                except Exception:
                                    pass

                        wallet_balances = {}
                        try:
                            manager = self._get_wallet_manager()
                            wallet_balances = await manager.recuperer_soldes_on_chain(
                                active_address,
                                proxy_address=proxy_address,
                            )
                        except Exception as e:
                            logger.warning("Failed to query wallet balances for PnL: %s", e)

                        usdc_direct = float(wallet_balances.get("usdc_direct", 0.0) or 0.0)
                        usdc_proxy = float(wallet_balances.get("usdc_proxy", 0.0) or 0.0)
                        total_capital = usdc_direct + usdc_proxy + open_current_value

                        reference_capital = self._load_pnl_reference_capital(
                            chat_id=chat_id,
                            active_address=active_address,
                            proxy_address=proxy_address or target_address,
                        )
                        net_capital_pnl = total_capital - reference_capital if reference_capital is not None else None

                        total_trades = len(closed_pos) if isinstance(closed_pos, list) else 0
                        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
                        closed_emoji = "🟢" if total_realized_pnl >= 0 else "🔴"
                        closed_sign = "+" if total_realized_pnl > 0 else ""
                        net_emoji = "🟢" if (net_capital_pnl or 0.0) >= 0 else "🔴"
                        net_sign = "+" if net_capital_pnl is not None and net_capital_pnl > 0 else ""

                        lines = [
                            "<b>🎯 Polymarket Cockpit</b>",
                            "───────────────────",
                            "💰 <b>PnL Metrics (Real-Time)</b>:",
                            f"• Wallet: <code>{self._html(wallet_name)}</code>",
                            f"• EOA: <code>{self._html(active_address)}</code>",
                            f"• Proxy: <code>{self._html(proxy_address or target_address)}</code>",
                            "",
                            f"• USDC Direct: <code>{usdc_direct:.2f}</code>",
                            f"• Polymarket pUSD: <code>{usdc_proxy:.2f}</code>",
                            f"• Open Value: <code>${open_current_value:.2f}</code>",
                            f"• Total Capital: <b>${total_capital:.2f}</b>",
                            "───────────────────"
                        ]
                        if net_capital_pnl is not None:
                            lines.extend([
                                f"• Capital Basis: <code>${reference_capital:.2f}</code>",
                                f"• Net Gain: {net_emoji} <b>{net_sign}${net_capital_pnl:.2f}</b>",
                                "───────────────────"
                            ])
                        else:
                            lines.append("• Net Gain: <code>N/A (reference missing)</code>")

                        lines.extend([
                            f"• Trades: <code>{total_trades}</code> (WR: <code>{win_rate:.1f}%</code>)",
                            f"• Realized: {closed_emoji} <b>{closed_sign}${total_realized_pnl:.2f}</b>",
                            f"• Floating: <b>{'+' if open_cash_pnl > 0 else ''}${open_cash_pnl:.2f}</b>",
                            "───────────────────"
                        ])

                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")]])
                        await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode=ParseMode.HTML)
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

        elif query.data.startswith("crypto_asset:"):
            await query.answer()
            asset_key = query.data.split(":", 1)[1].lower()
            context.args = [asset_key]
            await self.command_router._cmd_crypto_markets(update, context)
            return

        elif query.data.startswith("crypto_horizon:"):
            await query.answer()
            parts = query.data.split(":")
            if len(parts) == 3:
                asset, horizon = parts[1].lower(), parts[2]
                context.args = [asset, horizon]
                await self.command_router._cmd_crypto_horizon(update, context)
            return

        elif query.data == "crypto_menu":
            await query.answer()
            await self.command_router._cmd_crypto(update, context)
            return

        await query.answer()

        if query.data == "scan":
            # Trigger a manual scan report in-place
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour Cockpit", callback_data="start_status")]])
            if self._scanner:
                result = self._scanner.scan_markets()
                from utils.message_formatter import format_scan_report
                text = format_scan_report(result)
                await safe_edit_callback(query, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                await safe_edit_callback(query, "Scanner not available.", reply_markup=reply_markup)
        elif query.data == "improve":
           # Trigger self-improvement agent in-place
           from ai.agents.self_improvement_agent import SelfImprovementAgent
           agent = SelfImprovementAgent()
           report = agent.generate_improvement_report()
           reply_markup = InlineKeyboardMarkup([
               [InlineKeyboardButton("🛡️ Security Audit", callback_data="vibe_audit_security_hardener")],
               [InlineKeyboardButton("⚡ Perf Audit", callback_data="vibe_audit_performance_profiler")],
               [InlineKeyboardButton("⬅️ Retour Cockpit", callback_data="start_status")]
           ])
           await safe_edit_callback(query, report, reply_markup=reply_markup, parse_mode="HTML")
        elif query.data.startswith("vibe_audit_"):
           persona_id = query.data.replace("vibe_audit_", "")
           from ai.agents.self_improvement_agent import SelfImprovementAgent
           agent = SelfImprovementAgent()
           result = await agent.run_vibe_audit(persona_id)
           reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour Cockpit", callback_data="start_status")]])
           await safe_edit_callback(query, f"🦞 **Vibe Protocol: {persona_id.upper()}**\n\n{result}", reply_markup=reply_markup, parse_mode="Markdown")
        elif query.data == "balance":

            await self._cmd_balance(update, context)
        elif query.data == "wallet":
            await self._cmd_wallet_cockpit(update, context)
        elif query.data == "settings":
            mode = self._get_mode()
            msg = (
                f"⚙️ *SYSTEM SETTINGS*\n"
                f"📂 Mode: `{mode}`\n\n"
                f"`/mode PAPER` ou `/mode PROD`"
            )
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour Cockpit", callback_data="start_status")]])
            await safe_edit_callback(query, msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif query.data == "start_status":
            await self._cmd_status(update, context)
        elif query.data == "start_positions":
            await self._cmd_positions(update, context)
        elif query.data == "risk":
            await self._cmd_portfolio(update, context)
        elif query.data == "mode":
            await self._cmd_mode(update, context)
        elif query.data == "signal":
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour Cockpit", callback_data="start_status")]])
            await safe_edit_callback(
                query,
                "📡 *Signal Interface*\n\nSend a trading signal in format:\n`BUY BTC 0.50`",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

    async def _handle_command_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._check_auth(update):
            return
        await self.command_router.route_telegram_command(update, context)

    async def start(self) -> None:
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        consecutive_errors = 0
        self._ready.clear()

        while self._running:
            worker: Optional[asyncio.Task] = None
            polling_started = False
            app_started = False

            try:
                builder = Application.builder().token(self.bot_token)
                if self.proxy_url:
                    builder.proxy_url(self.proxy_url)
                self.application = builder.build()

                listen_all_chats = False
                allowed_private_chat_ids = set(self.private_chat_ids or set()) | set(self.admin_chat_ids)
                if allowed_private_chat_ids:
                    chat_filter = filters.Chat(chat_id=sorted(allowed_private_chat_ids))
                    target = f"private/admin chat_ids={sorted(allowed_private_chat_ids)}"
                elif _is_private_chat_id(self.chat_id):
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
                router = CommandRouter(self, market_reader=self._market_reader, order_manager=getattr(self, '_order_manager', None))
                router.register_all()

                # Register new Lobstar Command Router MessageHandler
                self.application.add_handler(
                    MessageHandler(
                        (chat_filter | filters.ChatType.PRIVATE) & filters.TEXT & filters.Regex(r"^/"),
                        self._handle_command_router
                    ),
                    group=0,
                )

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
                self.application.add_error_handler(self._handle_error)

                await self.application.initialize()
                await self.application.start()
                app_started = True
                await self.application.updater.start_polling()
                polling_started = True
                self._ready.set()
                worker = asyncio.create_task(self._lobstar_worker())

                logger.info(f"TELEGRAM BOT: Listening to {target}")
                consecutive_errors = 0

                while self._running:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Telegram listener crash (consecutive={consecutive_errors}): {e}")
                sleep_for = min(2.0 * (2 ** (consecutive_errors - 1)), 120.0)
                logger.warning(f"⚠️ [TELEGRAM] Backoff: sleeping {sleep_for:.1f}s before restart")
                await asyncio.sleep(sleep_for)
            finally:
                self._ready.clear()
                if worker:
                    worker.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await worker
                if polling_started:
                    with contextlib.suppress(Exception):
                        await self.application.updater.stop()
                if app_started:
                    with contextlib.suppress(Exception):
                        await self.application.stop()
                if self.application:
                    with contextlib.suppress(Exception):
                        await self.application.shutdown()
                self.application = None

    async def stop(self) -> None:
        self._running = False
        self._ready.clear()
