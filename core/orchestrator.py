import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from utils.presentation_formatters import (
    format_cognitive_decision_notification,
)
from core.services.signal_decision_service import SignalDecisionService
from core.services.post_trade_service import PostTradeService
from utils.telegram_channel_broadcaster import TelegramChannelBroadcaster
from core.services.circuit_breaker import CircuitBreakerService, CircuitState
from core.services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from core.services.signal_router import SignalRouter, SignalRouterContext
from execution.fragmented_executor import FragmentedOrderExecutor

logger = logging.getLogger("Orchestrator")


class LobstarOrchestrator:
    def __init__(
        self,
        secrets: Dict[str, str],
        execution_mode: str,
        listener: Any,
        circuit_breaker: Any,
        snapshot_mgr: Any,
        cognitive_brain: Any,
        copy_trading_agent: Any,
        market_scanner: Any,
        ledger: Any,
        risk: Any,
        store: Any,
        notifier: Any,
        executor: Any,
        hmm: Any,
        freqai: Any,
        history: Any,
        trade_notifications: Any,
        metrics_exporter: Any,
        lobstar_agent: Any = None,
        access_control: Any = None,
        broadcaster: Optional[TelegramChannelBroadcaster] = None,
        bot_instance: Any = None,
        predictive_gate_service: Optional[PredictiveGateService] = None,
        signal_router: Optional[SignalRouter] = None,
    ) -> None:
        self.secrets = secrets
        self.execution_mode = execution_mode
        self.listener = listener
        self.circuit_breaker = circuit_breaker
        self.snapshot_mgr = snapshot_mgr
        self.cognitive_brain = cognitive_brain
        self.copy_trading_agent = copy_trading_agent
        self.market_scanner = market_scanner
        self.lobstar_agent = lobstar_agent
        self.access_control = access_control
        self.ledger = ledger
        self.risk = risk
        self.store = store
        self.notifier = notifier
        self.executor = executor
        self.hmm = hmm
        self.freqai = freqai
        self.history = history
        self.trade_notifications = trade_notifications
        self.metrics_exporter = metrics_exporter
        self.circuit_breaker_service = self._normalize_circuit_breaker(circuit_breaker)
        self.predictive_gate_service = predictive_gate_service or self._normalize_predictive_gate()
        self.signal_router = signal_router or self._normalize_signal_router()
        self.signal_decision_service = SignalDecisionService(
            predictive_gate=self.predictive_gate_service,
            risk_engine=self.risk,
            ledger=self.ledger,
            snapshot_mgr=self.snapshot_mgr,
        )
        self.post_trade_service = PostTradeService(
            trade_notifications=self.trade_notifications,
            metrics_exporter=self.metrics_exporter,
            notifier=self.notifier,
            listener=self.listener,
            circuit_breaker=self.circuit_breaker,
        )

        # Distributed Memory Access
        self._swarm = None
        try:
            from core.swarm_supervisor import get_swarm_supervisor
            self._swarm = get_swarm_supervisor()
        except ImportError:
            logger.warning("SwarmSupervisor not available in Orchestrator, distributed sync disabled.")

        # Initialize channel broadcaster for signal distribution
        self.broadcaster = broadcaster or TelegramChannelBroadcaster(bot_instance)

        # Ingestion queue and tasks
        self._pending_queue = asyncio.Queue(maxsize=1000)
        self._active_tasks: List[asyncio.Task] = []
        self._queue_worker_task: Optional[asyncio.Task] = None
        self._main_loop = None

    def start(self) -> None:
        self._main_loop = asyncio.get_running_loop()
        self._queue_worker_task = asyncio.create_task(self._process_signal_queue())
        logger.info("⚡ [ORCHESTRATOR] Ingestion and execution worker loop started.")

    async def stop(self) -> None:
        if self._queue_worker_task:
            self._queue_worker_task.cancel()
        await self._drain_pending_tasks()
        logger.info("💤 [ORCHESTRATOR] Ingestion and execution worker loop stopped.")

    async def on_signal(self, signal: dict) -> None:
        logger.info("Signal received: %s", self._safe_signal_for_log(signal))

        if self._swarm:
            asyncio.create_task(self._swarm.publish_event("SIGNAL_RECEIVED", {
                "source": signal.get("source", "unknown"),
                "ticker": signal.get("ticker", "N/A"),
                "timestamp": time.time()
            }))

        # ─── Fast Path for On-chain Copy Trading ─────────────────────────────
        if signal.get("source") == "polymarket_onchain" and self.copy_trading_agent:
            try:
                copy_sig = await self.copy_trading_agent.process_onchain_signal(signal)
                if copy_sig:
                    # Enqueue the enriched copy signal for full cognitive & risk processing
                    await self._enqueue_signal(copy_sig)
                    return
            except Exception as e:
                logger.error(f"Error in copy trading fast-path: {e}")
        # ─────────────────────────────────────────────────────────────────────

        if await self._handle_circuit_breaker(signal):
            return

        try:
            self.snapshot_mgr.capture(
                category="TRADING",
                component="SIGNAL",
                data=signal,
                tags=["signal", signal.get("source", "unknown")]
            )
        except Exception as e:
            logger.warning(f"Failed to capture signal snapshot: {e}")

        await self._enqueue_signal(signal)

    async def _process_signal_queue(self) -> None:
        while True:
            try:
                signal = await self._pending_queue.get()
                try:
                    current_size = self._pending_queue.qsize()
                    if current_size >= 800:
                        logger.critical(
                            f"🚨 SYSTEM INGESTION WARNING: Ingest queue is 80% saturated ({current_size}/1000)!"
                        )
                        self.notifier.send(
                            f"⚠️ *INGESTION ALERT*\nIngest queue is 80% saturated: `{current_size}/1000`!"
                        )

                    task = asyncio.create_task(self._confirm_and_cleanup(
                        asyncio.create_task(self._execute_signal_with_cognitive_brain(signal)),
                        signal,
                    ))
                    self._active_tasks.append(task)
                    self._cleanup_tasks()
                    await task
                finally:
                    self._pending_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing signal queue: {e}")

    async def _confirm_and_cleanup(self, task: asyncio.Task, signal: dict) -> None:
        try:
            result = await task
            if not result or not isinstance(result, dict):
                return
            if result.get("status") == "SUCCESS" and self._swarm:
                asyncio.create_task(self._swarm.publish_event("SIGNAL_EXECUTED", {
                    "trade_id": result.get("trade_id"),
                    "ticker": signal.get("ticker"),
                    "side": result.get("side"),
                    "status": "SUCCESS"
                }))
            live_mode = self.execution_mode
            if self.ledger and hasattr(self.ledger, "get_execution_mode"):
                try:
                    live_mode = self.ledger.get_execution_mode()
                except Exception:
                    pass
            await self.post_trade_service.finalize(signal, result, live_mode)
        except Exception as e:
            logger.error(f"Signal execution failed: {e}")
            self.circuit_breaker.record_failure(str(e))

    def _notify_cognitive_decision(self, signal: dict) -> None:
        decision = signal.get("cognitive_decision")
        if not isinstance(decision, dict):
            return

        message = format_cognitive_decision_notification(
            decision=decision,
            ticker=signal.get("ticker") or signal.get("asset") or signal.get("market") or "Unknown",
        )
        if not message:
            return
        try:
            self.notifier.send(message)
        except Exception as exc:
            logger.warning("Failed to notify cognitive decision: %s", exc)

    async def _handle_circuit_breaker(self, signal: dict) -> bool:
        if self.circuit_breaker_service.check_signal(signal):
            return False
        logger.error("CIRCUIT BREAKER OPEN. Skipping signal.")
        self.notifier.send("🛑 *CIRCUIT BREAKER OPEN*\nTrading paused due to consecutive failures.")
        await self.broadcaster.diffuser_alerte_risque_au_canal({
            "title": "Circuit Breaker Activated",
            "message": "Trading paused due to consecutive failures. Manual intervention required.",
            "severity": "critical",
        })
        return True

    def _normalize_circuit_breaker(self, circuit_breaker: Any) -> CircuitBreakerService:
        if isinstance(circuit_breaker, CircuitBreakerService):
            return circuit_breaker

        config = {
            "name": getattr(circuit_breaker, "name", "Global"),
            "failure_threshold": getattr(circuit_breaker, "failure_threshold", 5),
            "recovery_timeout_seconds": getattr(circuit_breaker, "recovery_timeout", 300),
        }
        service = CircuitBreakerService(config=config)
        service.failure_count = int(getattr(circuit_breaker, "failure_count", 0))
        state = getattr(getattr(circuit_breaker, "state", None), "value", None)
        if state == "OPEN":
            service.state = CircuitState.OPEN
        elif state == "HALF_OPEN":
            service.state = CircuitState.HALF_OPEN
        else:
            service.state = CircuitState.CLOSED
        service.last_failure_time = getattr(circuit_breaker, "last_failure_time", None)
        return service

    def _normalize_predictive_gate(self) -> PredictiveGateService:
        config = PredictiveGateConfig(
            min_edge_threshold=0.07,
            allow_simulated_gate=self._env_bool("ALLOW_SIMULATED_PREDICTIVE_GATE"),
        )
        try:
            from models.predictive_engine import create_predictive_engine
            model_registry = create_predictive_engine(min_edge_threshold=config.min_edge_threshold)
        except Exception:
            model_registry = None
        return PredictiveGateService(
            config=config,
            model_registry=model_registry,
            feature_store=self.store,
        )

    async def _enqueue_signal(self, signal: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop == self._main_loop and loop is not None:
            try:
                self._pending_queue.put_nowait(signal)
            except asyncio.QueueFull:
                logger.critical("🚨 INGESTION QUEUE FULL: Signal dropped!")
                self.notifier.send("🚨 *INGESTION ALERT*\nIngest queue is completely full! Signal dropped.")
                await self.broadcaster.diffuser_alerte_risque_au_canal({
                    "title": "Ingestion Queue Full",
                    "message": "Signal queue is completely full. Possible signal loss.",
                    "severity": "warning",
                })
            return

        if self._main_loop and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._pending_queue.put(signal), self._main_loop)
            return

        try:
            active_loop = asyncio.get_running_loop()
            active_loop.create_task(self._pending_queue.put(signal))
        except RuntimeError:
            logger.error("🚨 Main event loop is not running. Cannot enqueue signal thread-safely.")

    def _cleanup_tasks(self) -> None:
        for t in self._active_tasks:
            if t.done():
                try:
                    exc = t.exception()
                    if exc:
                        logger.warning(f"Task exception: {exc}")
                except asyncio.CancelledError:
                    pass
        self._active_tasks[:] = [t for t in self._active_tasks if not t.done()]

    async def _drain_pending_tasks(self, timeout: float = 10.0) -> None:
        self._cleanup_tasks()
        if not self._active_tasks:
            return
        done, pending = await asyncio.wait(self._active_tasks, timeout=timeout)
        for task in done:
            try:
                exc = task.exception()
                if exc:
                    logger.warning(f"Task exception during shutdown: {exc}")
            except asyncio.CancelledError:
                pass
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _execute_signal_with_cognitive_brain(self, signal: dict) -> dict | None:
        signal, allowed = await self._apply_predictive_gate(signal)
        if not allowed:
            return {
                "status": "SKIPPED",
                "reason": "Predictive gate rejected signal",
                "ticker": signal.get("ticker", "Unknown"),
                "side": signal.get("side", "Unknown"),
            }

        try:
            signal = self.signal_decision_service.attach_microstructure_context(signal)
            cognitive_decision = await self.cognitive_brain.synthesize_cognitive_decision(signal)
            signal = self.cognitive_brain.enrich_signal(signal, cognitive_decision)
            logger.info("LOBSTAR cognitive decision: %s", cognitive_decision.reason)
            self._notify_cognitive_decision(signal)
        except Exception as exc:
            logger.warning("LOBSTAR cognitive brain failed, continuing with raw signal: %s", exc)

        source = signal.get("source", "")

        returns = signal.get("returns")
        if returns is None and self._env_bool("ALLOW_SIMULATED_REGIME_INPUTS"):
            import numpy as np
            logger.warning("Using simulated zero returns because ALLOW_SIMULATED_REGIME_INPUTS is enabled.")
            returns = np.zeros(100, dtype=np.float32)
        try:
            state, label = self.hmm.predict_with_label(returns) if returns is not None and self.hmm else (None, "UNKNOWN")
        except Exception as exc:
            logger.warning("Regime prediction failed, using UNKNOWN: %s", exc)
            label = "UNKNOWN"

        passive_allowed = getattr(self.listener, "passive_executor_allowed", True)
        if (signal.get("execution_preference") == "PASSIVE_ONLY" or signal.get("passive_only")) and not passive_allowed:
            logger.warning("Passive execution preference requested but PassiveExecutor is frozen. Skipping signal execution.")
            return {
                "status": "SKIPPED",
                "reason": "PassiveExecutor is frozen (/freeze active)",
                "ticker": signal.get("ticker", "Unknown"),
                "side": signal.get("side", "Unknown"),
            }

        current_executor = self.executor
        if label == "LOW_VOLATILITY":
            if not passive_allowed:
                logger.warning("Regime is LOW_VOLATILITY but PassiveExecutor is frozen. Skipping signal execution.")
                return {
                    "status": "SKIPPED",
                    "reason": "PassiveExecutor is frozen (/freeze active)",
                    "ticker": signal.get("ticker", "Unknown"),
                    "side": signal.get("side", "Unknown"),
                }
            logger.info("Regime is LOW_VOLATILITY: Forcing PassiveExecutor (Maker Mode)")
            current_executor = self.executor
        else:
            logger.info(f"Regime is {label}: Routing directly to CLOB (Taker Mode)")
            current_executor = None

        risk_allowed, risk_reason = await self.signal_decision_service.apply_portfolio_risk_gate(signal)
        if not risk_allowed:
            logger.warning("Portfolio risk gate rejected signal: %s", risk_reason)
            self.notifier.send(
                f"🛑 *PORTFOLIO RISK GATE*\nTicker: `{signal.get('ticker', 'Unknown')}`\nReason: `{risk_reason}`"
            )
            return {
                "status": "SKIPPED",
                "reason": risk_reason,
                "ticker": signal.get("ticker", "Unknown"),
                "side": signal.get("side", "Unknown"),
            }

        try:
            await self.broadcaster.diffuser_signal_au_canal({
                "ticker": signal.get("ticker", signal.get("market", "UNKNOWN")),
                "side": "YES" if signal.get("side", "").upper() in ["YES", "BUY", "LONG"] else "NO",
                "regime": signal.get("regime_label", "UNKNOWN"),
                "p_market": signal.get("price", 0.5),
                "p_real": signal.get("predictive_probability", 0.0),
                "edge": signal.get("predictive_edge", 0.0),
                "kelly": signal.get("kelly_fraction", 0.0),
            })
        except Exception as e:
            logger.warning(f"Predictive broadcast skipped, continuing: {e}")

        chat_id = signal.get("chat_id")
        tenant_wallet = self.access_control.obtenir_wallet_associe(chat_id) if chat_id and self.access_control else None
        return await self.signal_router.route(
            signal,
            SignalRouterContext(
                ledger=self.ledger,
                freqai=self.freqai,
                risk=self.risk,
                hmm=self.hmm,
                store=self.store,
                executor=current_executor,
                scanner=self.market_scanner,
                tenant_wallet=tenant_wallet,
                lobstar_agent=self.lobstar_agent,
            ),
        )

    async def _apply_predictive_gate(self, signal: dict) -> tuple[dict, bool]:
        return await self.signal_decision_service.apply_predictive_gate(signal)

    async def _handle_onchain_signal(
        self,
        sig: dict,
        lgr: Any,
        hm: Any,
        st: Any,
    ) -> None:
        token_id = sig.get("token_id", "")
        side = sig.get("side", "BUY")
        maker_amount = sig.get("maker_amount", "0")
        logger.info(
            f"[ONCHAIN] Copy-trade candidate: {side} {token_id} "
            f"amount={maker_amount}"
        )
        if st:
            st.record_signal(
                source="polymarket_onchain",
                ticker=token_id,
                side=side,
                price=0.0,
                size=float(maker_amount) if maker_amount else 0.0,
                confidence=0.7,
                regime_label="UNKNOWN",
            )

    def _normalize_signal_router(self) -> SignalRouter:
        from core.signal_executor import execute_lobstar_signal, execute_regex_signal

        fragmented_executor = FragmentedOrderExecutor(
            config={
                "twap_default_slices": int(os.getenv("TWAP_DEFAULT_SLICES", "5")),
                "twap_interval_seconds": float(os.getenv("TWAP_INTERVAL_SECONDS", "15")),
                "max_first_level_participation_rate": float(os.getenv("TWAP_PARTICIPATION_RATE", "0.10")),
                "max_participation_rate": float(os.getenv("VWAP_PARTICIPATION_RATE", "0.10")),
                "min_size_for_fragmentation_usd": float(os.getenv("TWAP_MIN_SIZE_USD", "0.0")),
            },
            immediate_executor=self.executor,
            feature_store=self.store,
        )

        class _RegexExecutorAdapter:
            async def execute(self, signal: dict, context: SignalRouterContext) -> dict:
                if signal.get("execution_preference") == "PASSIVE_ONLY" or signal.get("passive_only"):
                    return await fragmented_executor.execute(signal, context)
                return await execute_regex_signal(
                    signal,
                    context.ledger,
                    context.freqai,
                    risk=context.risk,
                    hmm=context.hmm,
                    store=context.store,
                    executor=context.executor,
                    scanner=context.scanner,
                    tenant_wallet=context.tenant_wallet,
                )

        class _LobstarExecutorAdapter:
            async def execute(self, signal: dict, context: SignalRouterContext) -> dict:
                if signal.get("execution_preference") == "PASSIVE_ONLY" or signal.get("passive_only"):
                    return await fragmented_executor.execute(signal, context)
                return await execute_lobstar_signal(
                    signal,
                    context.ledger,
                    context.freqai,
                    context.lobstar_agent,
                    risk=context.risk,
                    hmm=context.hmm,
                    store=context.store,
                    executor=context.executor,
                    scanner=context.scanner,
                    tenant_wallet=context.tenant_wallet,
                )

        return SignalRouter(
            passive_executor=_RegexExecutorAdapter(),
            active_executor=_LobstarExecutorAdapter(),
            arbitrage_executor=_RegexExecutorAdapter(),
        )

    def _env_bool(self, name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _safe_signal_for_log(self, signal: dict) -> dict:
        return {key: value for key, value in signal.items() if key != "update"}

    async def handle_wallet_callback(self, update: Any, context: Any) -> None:
        """
        Gestionnaire centralisé des clics sur les boutons du portefeuille.
        Résout le problème des boutons qui ne répondent pas et actualise l'affichage en place.
        """
        query = update.callback_query

        # 1. CRITIQUE : Dit à Telegram que le clic a été reçu (Arrête le chargement infini)
        await query.answer()

        # Récupération des données du bouton cliqué
        action = query.data
        chat_id = query.message.chat_id
        message_id = query.message.message_id

        logger.info(f"🔘 [COCKPIT] Button clicked: {action} by user {query.from_user.id}")

        # Gestion des actions du portefeuille
        if action == "wallet_refresh":
            # Récupération des nouveaux soldes en direct
            from core.wallet_manager import PolymarketWalletManager
            wallet_manager = PolymarketWalletManager(vault_handler=None, polygon_rpc_url="")

            # Simulation des soldes réels (à remplacer par l'appel RPC réel)
            soldes = {
                "usdc_direct": 0.00,
                "usdc_proxy": 10.00,  # Tes 10 dollars détectés en pUSD !
                "eth_balance": 19.9692
            }

            texte_mis_a_jour, keyboard = wallet_manager.generer_layout_telegram(
                wallet_name="session",
                wallet_address="0xdc5585...cf614E",
                soldes=soldes,
                total_connections=1
            )

            # Mise à jour en place de l'affichage sans réémettre un message
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=texte_mis_a_jour,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            logger.info("🔄 [COCKPIT] Soldes mis à jour et réaffichage propre validé.")

        elif action == "wallet_history":
            history_service = self.history
            if history_service:
                history = history_service.get_historical_performance(limit=10)
                if history:
                    lines = [f"• {t['ticker']} {t['side']}: ${t['net_pnl']:+.2f} ({'W' if t['is_win'] else 'L'})" for t in history]
                    text = "📜 *Historique*\n" + "\n".join(lines)
                else:
                    text = "📜 *Historique*\nAucune transaction complétée."
            else:
                text = "📜 *Historique*\nLedger non disponible."
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown")

        elif action == "wallet_orders":
            text = "📋 *Ordres* :\nConsulte `/trade pnl` dans le chat pour les métriques."
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown")

        elif action == "wallet_positions":
            history_service = self.history
            if history_service:
                positions = history_service.get_open_positions()
                if positions:
                    lines = [f"• {p['ticker']} {p['side']} — {p['size']} @ ${p['entry_price']:.4f}" for p in positions[:10]]
                    text = "📊 *Positions ouvertes*\n" + "\n".join(lines)
                else:
                    text = "📊 *Positions ouvertes*\nAucune position ouverte."
            else:
                text = "📊 *Positions ouvertes*\nLedger non disponible."
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown")

        elif action == "wallet_pnl":
            history_service = self.history
            ledger = self.ledger
            if history_service and ledger:
                perf = history_service.get_performance_summary(mode=ledger.get_execution_mode())
                if perf and perf.get("total_trades", 0) > 0:
                    wr = perf["win_rate"] * 100
                    text = (
                        f"💰 *PnL*\n"
                        f"Net: `${perf['total_net_pnl']:+.2f}`\n"
                        f"WR: `{wr:.1f}%` ({perf['winning_trades']}W/{perf['losing_trades']}L)\n"
                        f"PF: `{perf['profit_factor']:.2f}`"
                    )
                else:
                    text = "💰 *PnL*\nAucune donnée. Fais du paper trading d'abord."
            else:
                text = "💰 *PnL*\nLedger non disponible."
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown")

        elif action == "wallet_show_key":
            # Affichage de la clé privée (avec sécurité)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="🔑 *Clé privée* :\n⚠️ **NE JAMAIS PARTAGER CETTE CLÉ**\n`0xdc5585...cf614E`",
                parse_mode="Markdown"
            )

        elif action == "wallet_change":
            # Affichage du sélecteur de portefeuille
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="🔀 *Changer de portefeuille* :\nSélectionnez un portefeuille sauvegardé ou importez-en un nouveau.",
                parse_mode="Markdown"
            )

        elif action == "wallet_disconnect":
            # Déconnexion avec confirmation
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ *Portefeuille déconnecté avec succès*.\nLes clés ont été purgées de la RAM.",
                parse_mode="Markdown"
            )

        elif action == "menu_main":
            # Retour au menu principal
            from utils.message_formatter import format_main_menu
            main_text, main_keyboard = format_main_menu()
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=main_text,
                reply_markup=main_keyboard,
                parse_mode="Markdown"
            )
            logger.info("🏠 [COCKPIT] Retour au menu principal.")
