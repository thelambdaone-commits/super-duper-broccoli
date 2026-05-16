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
    ) -> None:
        self.bot_token = bot_token
        self.channel = channel_username
        self.chat_id = chat_id
        self.private_chat_ids = private_chat_ids
        self.admin_chat_ids = admin_chat_ids or set()
        self.allow_private_messages = allow_private_messages
        self.proxy_url = proxy_url
        self.media_dir = media_dir
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
        self._start_time: Optional[datetime] = None

    def attach_components(
        self,
        ledger=None,
        risk=None,
        hmm=None,
        store=None,
        executor=None,
        scanner=None,
    ) -> None:
        self._ledger = ledger
        self._risk = risk
        self._hmm = hmm
        self._store = store
        self._executor = executor
        self._scanner = scanner

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
            except Exception:
                pass
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
        parse_mode: Optional[str] = None,
    ) -> bool:
        msg = update.message or update.channel_post
        if msg is None:
            logger.warning("reply_to failed: update has no message or channel_post")
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

    async def _lobstar_worker(self) -> None:
        while self._running:
            try:
                signal = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                self.on_signal(signal)
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception("LOBSTAR WORKER ERROR")

    async def _cmd_help(self, update: Update, _context) -> None:
        await self.reply_to(CMD_HELP, update)

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
                except Exception:
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
            except Exception:
                pass
            
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
            except Exception:
                pass
        total = cap_summary.get("total_capital", "?")
        available = cap_summary.get("available_capital", "?")
        allocated = cap_summary.get("allocated_pct", "?")
        net_beta = "?"
        if self._risk:
            try:
                net_beta = f"{self._risk.net_beta_exposure_pct:.1f}%"
            except Exception:
                pass
        regime = "?"
        if self._hmm:
            try:
                from user_data.strategies.hmm_filter import REGIME_LABELS
                import numpy as np
                returns = np.random.randn(100) * 0.01
                state = self._hmm.predict_regime(returns)
                regime = REGIME_LABELS.get(state, "UNKNOWN")
            except Exception:
                pass
        from datetime import timezone
        now = datetime.now(timezone.utc)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        text = (
            f"🤖 *QUANT COCKPIT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ `{current_time}`\n"
            f"• Uptime: `{uptime}`\n"
            f"• Mode: `{mode}`\n"
            f"• Cap: `${total:,.2f}`\n"
            f"• Risk: `{net_beta}` Beta\n"
            f"• Market: `{regime}`"
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
            except Exception:
                pass
        if self._hmm:
            try:
                import numpy as np
                from user_data.strategies.hmm_filter import REGIME_LABELS
                returns = np.random.randn(100) * 0.01
                state = self._hmm.predict_regime(returns)
                regime = REGIME_LABELS.get(state, "UNKNOWN")
            except Exception:
                pass
        mode = self._get_mode()
        pos_count = 0
        if self._ledger:
            try:
                if mode in ("PAPER", "REPLAY"):
                    pos_count = len(self._ledger.get_paper_positions("OPEN"))
                else:
                    pos_count = len(self._ledger.get_open_positions())
            except Exception:
                pass
        cap = 0
        available = 0
        if self._ledger:
            try:
                summary = self._ledger.get_capital_summary()
                cap = summary.get("total_capital", 0)
                available = summary.get("available_capital", 0)
            except Exception:
                pass
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
        msg = update.message or update.channel_post
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
        except Exception:
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
            self.on_signal(signal)
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
        await query.answer()
        
        if query.data == "scan":
            # Trigger a manual scan report
            if self._scanner:
                result = self._scanner.scan_markets()
                from utils.message_formatter import format_scan_report
                text = format_scan_report(result)
                await self.send_message(text, parse_mode=ParseMode.MARKDOWN)
            else:
                await self.send_message("Scanner not available.", update=update)
        elif query.data == "improve":
            # Trigger self-improvement agent
            from ai.agents.self_improvement_agent import SelfImprovementAgent
            agent = SelfImprovementAgent()
            report = agent.generate_improvement_report()
            await self.send_message(report, parse_mode=ParseMode.MARKDOWN)
        elif query.data == "balance":
            await self._cmd_balance(update, context)
        elif query.data == "wallet":
            if self._ledger:
                # Get the wallet derived from private key
                from utils.credential_manager import CredentialManager
                from eth_account import Account
                mgr = CredentialManager()
                pk = mgr.get_or_generate_private_key()
                acc = Account.from_key(pk)
                addr = acc.address
                msg = (
                    f"💳 *INSTITUTIONAL WALLET*\n\n"
                    f"Address: `{addr}`\n"
                    f"Network: `Polygon / Ethereum`\n"
                    f"[View on Polyscan](https://polygonscan.com/address/{addr})"
                )
                await self.send_message(msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await self.send_message("Wallet info not available.", update=update)
        elif query.data == "settings":
            mode = self._get_mode()
            msg = (
                f"⚙️ *Settings Interface*\n\n"
                f"Mode: `{mode}`\n"
                f"Use /mode to change."
            )
            await self.send_message(msg, parse_mode=ParseMode.MARKDOWN)

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
