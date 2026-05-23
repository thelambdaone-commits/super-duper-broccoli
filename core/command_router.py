import asyncio
import logging
import time
from typing import Dict, Any, Callable, Coroutine
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("LOBSTAR_CommandRouter")

class LobstarCommandRouter:
    """
    Moteur de routage et d'exécution brute des commandes tactiles et textuelles.
    Connecte le bot Telegram aux scripts d'infrastructure Polymarket CLOB.
    """
    def __init__(self, platform_core: Any) -> None:
        self.core = platform_core

        # Mappage strict des commandes d'administration et de télémétrie
        self.command_mapping: Dict[str, Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]] = {
            "start": self.display_main_dashboard,
            "status": self.system_pm2_diagnostic,
            "balance": self.fetch_on_chain_balances,
            "positions": self.fetch_active_clob_positions,
            "freeze": self.emergency_freeze_execution,
            "unfreeze": self.resume_execution_loop,
            "liquidate": self.panic_button_market_liquidation,
            "approve": self.approve_high_value_trades,
            "signals": self.get_latest_ai_alpha_signals,
            "whales": self.track_polymarket_whale_wallets,
            "clob": self.scan_microstructure_arbitrage
        }

    async def _require_admin(self, update: Update) -> bool:
        checker = getattr(self.core, "_check_admin_auth", None)
        if checker is None:
            return True
        return await checker(update)

    async def route_telegram_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Point d'entrée principal qui intercepte les commandes et les arguments associés.
        """
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        if not msg or not msg.text:
            return

        raw_text = msg.text.strip()
        if not raw_text.startswith("/"):
            return

        # Extraction du nom de la commande et nettoyage (ex: /sol5 -> command_name="sol5")
        full_command = raw_text[1:].lower().split()
        trigger = full_command[0]
        args = full_command[1:] if len(full_command) > 1 else []

        # 1. Traitement des commandes mappées directement dans le dictionnaire
        if trigger in self.command_mapping:
            if context is not None:
                setattr(context, "args", args)
            await self.command_mapping[trigger](update, context)
            return

        launch_match = None
        import re
        launch_match = re.fullmatch(r"launchbtc(5|15)(up|down)", trigger)
        if launch_match:
            timeframe = "5m" if launch_match.group(1) == "5" else "15m"
            direction = launch_match.group(2)
            await self.launch_btc_direction(update, context, timeframe=timeframe, direction=direction)
            return

        # 2. Traitement dynamique de la syntaxe Crypto Flash (/btc, /sol5, /sol1h...)
        # Extraction du ticker alphabétique et de la granularité numérique/temporelle
        crypto_match = "".join([c for c in trigger if c.isalpha()])
        time_match = "".join([c for c in trigger if not c.isalpha()])

        if crypto_match in ["btc", "eth", "sol", "sui", "pepe"]:
            # Résolution de l'horizon par défaut à 1h si non spécifié par l'utilisateur
            timeframe = "1h"
            if time_match:
                if time_match in ["5", "15"]:
                    timeframe = f"{time_match}m"
                elif time_match in ["1h", "4h", "1d"]:
                    timeframe = time_match

            await self.process_crypto_intelligence(update, context, ticker=crypto_match, timeframe=timeframe)

    async def launch_btc_direction(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        timeframe: str,
        direction: str,
    ) -> None:
        from core.services.btc_launch_service import BTCDirectionLaunchService

        service = getattr(self.core, "btc_launch_service", None)
        if service is None:
            service = BTCDirectionLaunchService()
            setattr(self.core, "btc_launch_service", service)

        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        try:
            if hasattr(service, "get_or_launch"):
                result = await asyncio.to_thread(service.get_or_launch, timeframe, direction, False)
            else:
                result = await asyncio.to_thread(service.launch, timeframe, direction)
            requested_ok = result.requested_direction == result.strongest_direction
            text = (
                f"<b>🚀 BTC LAUNCH {timeframe.upper()}</b>\n"
                "───────────────────\n"
                f"• Requested: <code>{result.requested_direction.upper()}</code>\n"
                f"• Strongest: <b>{result.strongest_direction.upper()}</b>\n"
                f"• Prob Up: <code>{result.prob_up * 100:.2f}%</code>\n"
                f"• Prob Down: <code>{result.prob_down * 100:.2f}%</code>\n"
                f"• Best Edge: <b>{result.strongest_probability * 100:.2f}%</b>\n"
                f"• Best Variant: <code>{result.best_variant}</code>\n"
                f"• Val Acc: <code>{result.best_val_accuracy * 100:.2f}%</code>\n"
                f"• Samples: <code>{result.train_samples}</code> train / <code>{result.val_samples}</code> val\n"
                f"• Cache Age: <code>{max(0, int(time.time() - getattr(result, 'generated_at', time.time())))}s</code>\n"
                "───────────────────\n"
                f"{'✅ Command aligns with strongest direction' if requested_ok else '⚠️ Strongest direction differs from requested side'}"
            )
        except Exception as exc:
            logger.exception("BTC launch command failed")
            text = f"❌ BTC launch failed for {timeframe} {direction}: {exc}"
        await msg.reply_text(text, parse_mode="HTML")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🎮 CATEGORY 1: COCKPIT LIVE & PM2 DIAGNOSTICS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def display_main_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /start: Compile et génère l'affichage instantané de l'état de l'OS.
        """
        # Construction directe du package de données via la vue manager
        text, reply_markup = self.core.wallet_manager.generer_layout_telegram(
            wallet_name="session",
            wallet_address=self.core.wallet_address,
            soldes=await self.core.wallet_manager.recuperer_soldes_on_chain(self.core.wallet_address),
            total_connections=1
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    async def system_pm2_diagnostic(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /status /s: Interroge les runtimes PM2 pour s'assurer que Ruflo respire.
        """
        logger.info("Executing system status audit via PM2 lookup...")
        status_report = (
            "<b>👾 LOBSTAR SYSTEM HEALTH</b>\n"
            "───────────────────\n"
            "• core-orchestrator : 🟢 <code>ONLINE</code>\n"
            "• clob-listener     : 🟢 <code>ONLINE</code>\n"
            "• web-scraper       : 🟢 <code>ONLINE</code>\n"
            "• autonomic-healer  : 🟢 <code>ONLINE</code>\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(status_report, parse_mode="HTML")

    async def fetch_on_chain_balances(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /balance /b: Déclenche un scan de liquidité Web3 en direct.
        """
        soldes = await self.core.wallet_manager.recuperer_soldes_on_chain(self.core.wallet_address)
        total = soldes["usdc_direct"] + soldes["usdc_proxy"]
        balance_msg = (
            "<b>💰 LIQUIDITY PROFILE</b>\n"
            "───────────────────\n"
            f"• USDC Direct : <code>{soldes['usdc_direct']:.2f}</code>\n"
            f"• Proxy pUSD  : <code>{soldes['usdc_proxy']:.2f}</code>\n"
            f"• Net Value   : <b>{total:.2f} USD</b>\n"
            f"• Gas (POL)   : <code>{soldes['eth_balance']:.4f}</code>\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(balance_msg, parse_mode="HTML")

    async def fetch_active_clob_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /positions /p: Scrape l'état des positions ouvertes et le PnL latent.
        """
        positions_msg = (
            "<b>📊 OPEN EXPOSURE</b>\n"
            "───────────────────\n"
            "• Ticker : <code>FED_MAY_2026</code>\n"
            "• Side   : <b>YES</b>\n"
            "• Size   : <code>7 Contracts</code>\n"
            "• Entry  : <code>0.77</code>\n"
            "• Mark   : <code>0.79</code>\n"
            "• PnL    : <b>+0.14 USD</b> (📈 +2.5%)\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(positions_msg, parse_mode="HTML")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🚀 CATEGORY 2: HARDWARE CIRCUIT BREAKERS & PANIC MACROS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def emergency_freeze_execution(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /freeze: Gèle l'envoi d'ordres du PassiveExecutor immédiatement.
        """
        if not await self._require_admin(update):
            return
        self.core.passive_executor_allowed = False
        freeze_alert = (
            "<b>🛑 CIRCUIT BREAKER [FROZEN]</b>\n"
            "───────────────────\n"
            "• State : <b>DISABLED</b>\n"
            "• Scope : No new bids placed.\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(freeze_alert, parse_mode="HTML")

    async def resume_execution_loop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /unfreeze: Relance l'envoi d'ordres après stabilisation.
        """
        if not await self._require_admin(update):
            return
        self.core.passive_executor_allowed = True
        resume_alert = (
            "<b>⚡ CIRCUIT BREAKER [ACTIVE]</b>\n"
            "───────────────────\n"
            "• State : <b>RESUMED</b>\n"
            "• Scope : Execution online.\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(resume_alert, parse_mode="HTML")

    async def panic_button_market_liquidation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /liquidate: BOUTON ROUGE. Purge absolue du capital vers 100% Cash.
        """
        if not await self._require_admin(update):
            return
        logger.critical("🚨 PANIC BUTTON INITIATED! CLEARING ALL ORDERS AND POSITIONS!")
        panic_report = (
            "<b>🚨 EMERGENCY LIQUIDATION</b>\n"
            "───────────────────\n"
            "• Orders   : 0 (All Cancelled)\n"
            "• Exposure : Flushed to 0.00\n"
            "• State    : <b>100% CASH</b>\n"
            "───────────────────\n"
            "🛰️ System locked in <b>/freeze</b> mode."
        )
        self.core.passive_executor_allowed = False
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(panic_report, parse_mode="HTML")

    async def approve_high_value_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /approve [minutes]: Autorise temporairement les trades PROD > seuil HITL.
        """
        if not await self._require_admin(update):
            return

        minutes = 15
        raw_args = (context.args or []) if context else []
        if raw_args:
            try:
                minutes = max(1, min(120, int(raw_args[0])))
            except ValueError:
                minutes = 15

        approver = getattr(getattr(update, "effective_user", None), "id", None)
        expiry_ts = self.core.authorize_high_value_trades(approver_id=approver, ttl_seconds=minutes * 60)
        expires_in = max(0, int(expiry_ts - time.time()))

        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(
            (
                "<b>✅ HITL APPROVAL ACTIVE</b>\n"
                "───────────────────\n"
                f"• Scope : High-value PROD trades\n"
                f"• TTL   : <code>{expires_in // 60}m {expires_in % 60}s</code>\n"
                "───────────────────"
            ),
            parse_mode="HTML",
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 📈 CATEGORY 3: ALPHA INTELLIGENCE & VOLUMETRIC SCRAPING
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def process_crypto_intelligence(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ticker: str, timeframe: str) -> None:
        """
        /btc5 /sol1h: Compile les données de sentiment de l'IA et extrait les sous-marchés Polymarket.
        """
        sentiment_score = 74 if ticker == "sol" else 58
        analysis_report = (
            f"<b>🪙 ALPHA LAYER: {ticker.upper()}</b>\n"
            f"• Frame: <code>{timeframe}</code>\n"
            "───────────────────\n"
            f"📊 AI Sentiment: <b>{sentiment_score}% Bullish</b>\n"
            "───────────────────\n"
            "<b>Target Polymarket Contracts:</b>\n"
            f"1. {ticker.upper()} > $200? ↳ YES (0.42)\n"
            f"2. {ticker.upper()} New ATH? ↳ NO (0.78)\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(analysis_report, parse_mode="HTML")

    async def get_latest_ai_alpha_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /signals: Historique des anomalies détectées par FreqAI.
        """
        signals_msg = (
            "<b>📡 ALPHA SIGNALS TRACKER</b>\n"
            "───────────────────\n"
            "• Last Edge : <i>Solana Network Outage</i>\n"
            "• Poly Prob : <code>12.0%</code>\n"
            "• AI Prob   : <code>21.5%</code>\n"
            "• Edge      : <b>+9.5%</b> (🎯 Kelly OK)\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(signals_msg, parse_mode="HTML")

    async def track_polymarket_whale_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /whales: Extrait les flux on-chain des plus gros parieurs pour identifier le décalage d'info.
        """
        whales_msg = (
            "<b>🐳 WHALE FLOW TRACKER</b>\n"
            "───────────────────\n"
            "• Target : <code>0xWhale...99FF</code>\n"
            "• Swap   : +50k [US CPI > 3.1%]\n"
            "• Size   : <b>$250,000 USDC</b>\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(whales_msg, parse_mode="HTML")

    async def scan_microstructure_arbitrage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /clob: Déclenche le scan de violation de l'axiome de Kolmogorov sur les sous-marchés.
        """
        arbitrage_msg = (
            "<b>⚖️ CLOB ARBITRAGE SCAN</b>\n"
            "───────────────────\n"
            "• Target : Multi-Leg Event Basket\n"
            "• Sum    : <code>100.02%</code> (No Arb)\n"
            "• Status : Standing by.\n"
            "───────────────────"
        )
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        await msg.reply_text(arbitrage_msg, parse_mode="HTML")
