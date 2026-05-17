import asyncio
import logging
import time
import os
from typing import Dict, Any, List, Optional
from pydantic import SecretStr

from core.signal_executor import execute_lobstar_signal, execute_regex_signal
from utils.exceptions import QuantFatal

logger = logging.getLogger("Orchestrator")


class LobstarOrchestrator:
    def __init__(
        self,
        container: Any,
        secrets: Dict[str, str],
        execution_mode: str,
        listener: Any,
        circuit_breaker: Any,
        snapshot_mgr: Any,
        cognitive_brain: Any,
        copy_trading_agent: Any,
        market_scanner: Any,
        lobstar_agent: Any = None,
        access_control: Any = None,
    ) -> None:
        self.container = container
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
        
        if not self.circuit_breaker.is_allowed():
            logger.error("CIRCUIT BREAKER OPEN. Skipping signal.")
            self.container.notifier.send("🛑 *CIRCUIT BREAKER OPEN*\nTrading paused due to consecutive failures.")
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

        # Thread-safe queue submission
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop == self._main_loop and loop is not None:
            try:
                self._pending_queue.put_nowait(signal)
            except asyncio.QueueFull:
                logger.critical("🚨 INGESTION QUEUE FULL: Signal dropped!")
                self.container.notifier.send("🚨 *INGESTION ALERT*\nIngest queue is completely full! Signal dropped.")
        else:
            # We are in an external thread (e.g. websocket/scraping thread)
            if self._main_loop and self._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(self._pending_queue.put(signal), self._main_loop)
            else:
                # Fallback to current running event loop if main loop is not initialized
                try:
                    active_loop = asyncio.get_running_loop()
                    active_loop.create_task(self._pending_queue.put(signal))
                except RuntimeError:
                    logger.error("🚨 Main event loop is not running. Cannot enqueue signal thread-safely.")

    async def _process_signal_queue(self) -> None:
        while True:
            try:
                signal = await self._pending_queue.get()
                
                # Check for queue saturation warning (80% full)
                current_size = self._pending_queue.qsize()
                if current_size >= 800:
                    logger.critical(f"🚨 SYSTEM INGESTION WARNING: Ingest queue is 80% saturated ({current_size}/1000)!")
                    self.container.notifier.send(f"⚠️ *INGESTION ALERT*\nIngest queue is 80% saturated: `{current_size}/1000`!")
                
                # Execute the signal as a task
                raw_task = asyncio.create_task(self._execute_signal_with_cognitive_brain(signal))
                task = asyncio.create_task(
                    self._confirm_and_cleanup(raw_task, signal)
                )
                self._active_tasks.append(task)
                self._cleanup_tasks()
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

            if result.get("status") == "SUCCESS":
                logger.info(f"Signal executed successfully: {result.get('trade_id', 'N/A')}")
                self.container.notifier.send(
                    f"✅ *Trade Executed*\n"
                    f"Ticker: `{result.get('ticker', 'Unknown')}`\n"
                    f"Side: `{result.get('side', 'Unknown')}`\n"
                    f"Size: `{result.get('executed_size', 0.0):.2f}` @ `{result.get('price', 0.0):.4f}`\n"
                    f"Mode: `{self.execution_mode}`"
                )
                self.circuit_breaker.record_success()
            else:
                reason = result.get("reason_1") or result.get("reason") or "Unknown error"
                logger.warning(f"Signal execution failed: {reason}")
                self.container.notifier.send(f"⚠️ *Execution Failed*\nTicker: `{result.get('ticker', 'Unknown')}`\nReason: `{reason}`")
                self.circuit_breaker.record_failure(reason)

            from utils.message_formatter import InstitutionalMessageFormatter
            confirmation = InstitutionalMessageFormatter.format_trade_execution_html(result)
            
            chat_id = signal.get("chat_id")
            update = signal.get("update")
            
            if update is not None and update.message:
                await self.listener.reply_to(confirmation, update, parse_mode="HTML")
            elif chat_id:
                await self.listener.send_message(confirmation, chat_id=chat_id, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Signal execution failed: {e}")
            self.circuit_breaker.record_failure(str(e))

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
        market_features = signal.get("market_features")
        if market_features is not None or self._env_bool("ALLOW_SIMULATED_PREDICTIVE_GATE"):
            try:
                from models.predictive_engine import create_predictive_engine
                import pandas as pd

                predictive_engine = create_predictive_engine(min_edge_threshold=0.07)
                price = signal.get("price", 0.5)
                ts_res = signal.get("timestamp_resolution", time.time() + 3600)
                if market_features is None:
                    logger.warning("Using simulated predictive-gate features because ALLOW_SIMULATED_PREDICTIVE_GATE is enabled.")
                    market_features = {'price': [0.5], 'volume': [100], 'bid_depth': [50], 'ask_depth': [50]}
                mock_df = pd.DataFrame(market_features)

                # Predictive Engine Call - renamed to predict_winning_bet
                prediction = predictive_engine.predict_winning_bet(
                    df_market_ticks=mock_df,
                    clob_price_yes=price,
                    timestamp_resolution=ts_res
                )

                if not prediction.get("pari_approuve"):
                    logger.info(f"💤 [PREDICTIVE ENGINE] Signal rejected: Edge {prediction.get('absolute_edge', 0):.1%} < 7%")
                    return None

                signal["predictive_probability"] = prediction.get("probability_win")
                signal["predictive_edge"] = prediction.get("absolute_edge")
                logger.info(f"🔮 [PREDICTIVE ENGINE] Signal validated: P(win)={prediction.get('probability_win'):.1%}, Edge={prediction.get('absolute_edge'):+.1%}")

            except Exception as e:
                logger.warning(f"Predictive engine check failed, continuing: {e}")
        else:
            logger.debug("Predictive gate skipped: no real market_features on signal.")
        
        try:
            # Cognitive Brain Call - renamed to synthesize_cognitive_decision
            cognitive_decision = await self.cognitive_brain.synthesize_cognitive_decision(signal)
            signal = self.cognitive_brain.enrich_signal(signal, cognitive_decision)
            logger.info("LOBSTAR cognitive decision: %s", cognitive_decision.reason)
        except Exception as exc:
            logger.warning("LOBSTAR cognitive brain failed, continuing with raw signal: %s", exc)

        source = signal.get("source", "")
        
        if source == "arbitrage" or signal.get("arb_type") is not None:
            logger.info("⚡ ARBITRAGE SIGNAL DETECTED. Executing instant sum-of-outcomes netting...")
            return await execute_regex_signal(
                signal, self.container.ledger, self.container.freqai,
                risk=self.container.risk, hmm=self.container.hmm, store=self.container.store, executor=None,
                scanner=self.market_scanner,
            )

        returns = signal.get("returns")
        if returns is None and self._env_bool("ALLOW_SIMULATED_REGIME_INPUTS"):
            import numpy as np
            logger.warning("Using simulated zero returns because ALLOW_SIMULATED_REGIME_INPUTS is enabled.")
            returns = np.zeros(100, dtype=np.float32)
        try:
            state, label = self.container.hmm.predict_with_label(returns) if returns is not None else (None, "UNKNOWN")
        except Exception as exc:
            logger.warning("Regime prediction failed, using UNKNOWN: %s", exc)
            label = "UNKNOWN"

        current_executor = self.container.executor
        if label == "LOW_VOLATILITY":
            logger.info("Regime is LOW_VOLATILITY: Forcing PassiveExecutor (Maker Mode)")
            current_executor = self.container.executor
        else:
            logger.info(f"Regime is {label}: Routing directly to CLOB (Taker Mode)")
            current_executor = None

        chat_id = signal.get("chat_id")
        tenant_wallet = self.access_control.obtenir_wallet_associe(chat_id) if chat_id and self.access_control else None

        if source == "lobstar_llm":
            if not self.lobstar_agent:
                logger.warning("Lobstar signal received but agent is disabled.")
                return None
            return await execute_lobstar_signal(
                signal, self.container.ledger, self.container.freqai, self.lobstar_agent,
                risk=self.container.risk, hmm=self.container.hmm, store=self.container.store, executor=current_executor,
                scanner=self.market_scanner, tenant_wallet=tenant_wallet,
            )
        if source == "polymarket_onchain":
            await self._handle_onchain_signal(
                signal, self.container.ledger, self.container.hmm, self.container.store,
            )
            return None
        return await execute_regex_signal(
            signal, self.container.ledger, self.container.freqai,
            risk=self.container.risk, hmm=self.container.hmm, store=self.container.store, executor=current_executor,
            scanner=self.market_scanner, tenant_wallet=tenant_wallet,
        )

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

    def _env_bool(self, name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _safe_signal_for_log(self, signal: dict) -> dict:
        return {key: value for key, value in signal.items() if key != "update"}
