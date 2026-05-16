import logging
import os
import json
import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

logger = logging.getLogger("CommandRouter")

class CommandRouter:
    def __init__(self, listener, wallet_manager=None, transfer_manager=None, 
                 order_manager=None, signal_generator=None, market_reader=None):
        self.listener = listener
        self.app = listener.application
        self.wallet_manager = wallet_manager
        self.transfer_manager = transfer_manager
        self.order_manager = order_manager
        self.signal_generator = signal_generator
        self.market_reader = market_reader

    def register_all(self):
        # WALLET / BALANCE (NEW)
        self._add_cmd("wallet", self._cmd_wallet)
        
        # TRANSFER / PROXY WALLET (NEW)
        self._add_cmd("transfer", self._cmd_transfer)
        
        # POLYMARKET / BETTING (NEW)
        self._add_cmd("polymarket", self._cmd_polymarket)
        
        # SIGNALS / TRADING ALERTS (NEW)
        self._add_cmd("signals", self._cmd_signals)
        
        # MARKETS / DATA (NEW)
        self._add_cmd("markets", self._cmd_markets)
        
        # AI / AGENTS
        self._add_cmd("ai", self._cmd_ai)
        
        # QUANT / ML
        self._add_cmd("model", self._cmd_model)
        
        # PORTFOLIO / RISK
        self._add_cmd("risk", self._cmd_risk)
        
        # POLYMARKET / CLOB
        self._add_cmd("clob", self._cmd_clob)
        
        # WHALE TRACKER (NEW)
        self._add_cmd("whales", self._cmd_whales)
        
        # TRADING
        self._add_cmd("trade", self._cmd_trade)
        
        # DEVOPS / MCP
        self._add_cmd("mcp", self._cmd_mcp)
        self._add_cmd("dev", self._cmd_dev)
        self._add_cmd("audit", self._cmd_audit)
        
        # CRITICAL
        self._add_cmd("freeze", self._cmd_freeze)
        self._add_cmd("unfreeze", self._cmd_unfreeze)
        self._add_cmd("liquidate", self._cmd_liquidate)

    def _add_cmd(self, name, func):
        self.app.add_handler(CommandHandler(name, func))

    async def _cmd_ai(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        args = context.args
        sub = args[0] if args else "status"
        
        if sub == "status":
            from utils.ai_specialists import list_ai_specialists
            specialists = list_ai_specialists()
            msg = "🧠 *AI Agents Status*\n\n"
            msg += f"• Specialists: {len(specialists)}\n"
            msg += "• LLM Council: Active (OpenRouter)\n"
            msg += "• Memory: Persistent (SQLite/DuckDB)\n"
            await self.listener.reply_to(msg, update)
        elif sub == "errors":
            # Tail logs/pm2-error.log
            try:
                with open("logs/pm2-error.log", "r") as f:
                    lines = f.readlines()[-10:]
                msg = "🚨 *Latest AI/System Errors*\n\n```\n" + "".join(lines) + "\n```"
                await self.listener.reply_to(msg, update)
            except Exception as e:
                await self.listener.reply_to(f"Failed to read logs: {e}", update)
        else:
            await self.listener.reply_to(f"Unknown AI subcommand: {sub}", update)

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.listener._hmm:
            await self.listener.reply_to("HMM Filter not attached.", update)
            return
        
        args = context.args
        sub = args[0] if args else "status"
        
        if sub == "status":
            # Logic from MCP get_market_regime
            from utils.regime_utils import get_regime_label
            label = get_regime_label(self.listener._hmm, "SOL")
            msg = "📊 *Model Status (HMM Filter)*\n\n"
            msg += f"• Current Regime: `{label}`\n"
            msg += f"• Trading Allowed: {'✅' if self.listener._hmm.is_trading_allowed(None)[0] else '❌'}\n"
            await self.listener.reply_to(msg, update)
        elif sub == "metrics":
            if not self.listener._store:
                await self.listener.reply_to("Feature Store not attached.", update)
                return
            stats = self.listener._store.get_stats()
            msg = "📈 *Model Metrics (Feature Store)*\n\n"
            for k, v in stats.items():
                msg += f"• {k}: `{v}`\n"
            await self.listener.reply_to(msg, update)
        elif sub == "validate":
            from utils.model_validator import ModelValidator
            validator = ModelValidator(self.listener._store)
            ticker = args[1] if len(args) > 1 else "SOL"
            report = validator.run_health_check(ticker, "default_v1")
            msg = f"🧪 *Model Validation: {ticker}*\n\n"
            msg += f"• Health: `{report.get('health', 'UNKNOWN')}`\n"
            msg += f"• P-Value: `{report.get('drift_report', {}).get('p_value', 0):.4f}`\n"
            msg += f"• Drift: `{'YES' if report.get('drift_report', {}).get('drift_detected') else 'NO'}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown model subcommand: {sub}", update)

    async def _cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.listener._ledger:
            await self.listener.reply_to("Ledger not attached.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            cap = self.listener._ledger.get_capital_summary()
            msg = "🛡️ *Risk & Capital Status*\n\n"
            msg += f"• Total: `${cap.get('total_capital', 0):,.2f}`\n"
            msg += f"• Available: `${cap.get('available_capital', 0):,.2f}`\n"
            msg += f"• Allocated: `{cap.get('allocated_pct', 0)}%`\n"
            await self.listener.reply_to(msg, update)
        elif sub in ("kill", "freeze"):
            # Mocking the MCP emergency_circuit_breaker
            from mcp_agents.mcp_server import emergency_circuit_breaker
            res = emergency_circuit_breaker("ENGAGE")
            await self.listener.reply_to(f"🛑 *CIRCUIT BREAKER ENGAGED*\n\n{res.get('message')}", update)
        elif sub in ("resume", "unfreeze"):
            from mcp_agents.mcp_server import emergency_circuit_breaker
            res = emergency_circuit_breaker("DISENGAGE")
            await self.listener.reply_to(f"✅ *CIRCUIT BREAKER DISENGAGED*\n\n{res.get('message')}", update)
        elif sub == "exposure":
            if not self.listener._risk:
                await self.listener.reply_to("Risk Engine not attached.", update)
                return
            msg = "📉 *Portfolio Exposure*\n\n"
            msg += f"• Net Beta Exposure: `{self.listener._risk.net_beta_exposure_pct:.2f}%`\n"
            msg += f"• Positions: `{len(self.listener._risk._exposures)}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown risk subcommand: {sub}", update)

    async def _cmd_clob(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        args = context.args
        sub = args[0] if args else "arb"

        if sub == "arb":
            # Call MCP get_arbitrage_opportunities
            from mcp_agents.mcp_server import get_arbitrage_opportunities
            res = get_arbitrage_opportunities()
            count = res.get("opportunity_count", 0)
            msg = f"⚖️ *CLOB Arbitrage Scanner*\n\nFound `{count}` opportunities.\n"
            if count > 0:
                for opp in res.get("opportunities", [])[:5]:
                    msg += f"• {opp.get('type')}: `{opp.get('market_id')}` (Conf: {opp.get('confidence'):.2f})\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown CLOB subcommand: {sub}", update)

    async def _cmd_whales(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        args = context.args
        sub = args[0] if args else "leaderboard"

        from utils.polymarket_crawler.traders import discover_top_traders
        from utils.polymarket_crawler.trader_formatters import fmt_expert_leaderboard, fmt_trader_alert_html

        if sub == "leaderboard":
            cat = args[1].upper() if len(args) > 1 else "OVERALL"
            msg_wait = await self.listener.reply_to(f"🔍 Fetching {cat} leaderboard...", update)
            results = discover_top_traders(categories=[cat], limit=5)
            traders = results.get(cat, [])
            report = fmt_expert_leaderboard(traders, cat, 5)
            await self.listener.reply_to(f"🏆 *Top Traders: {cat}*\n\n{report}", update)
        elif sub == "analyze":
            if len(args) < 2:
                await self.listener.reply_to("Usage: `/whales analyze <address>`", update)
                return
            wallet = args[1]
            msg_wait = await self.listener.reply_to(f"🔍 Analyzing whale: `{wallet[:10]}...`", update)
            from utils.polymarket_crawler.traders import TraderScraper
            scraper = TraderScraper()
            # Simplified analysis for Telegram
            positions = scraper.fetch_closed_positions(wallet)
            total_pnl = sum(p.realized_pnl for p in positions)
            msg = f"🐋 *Whale Analysis: {wallet[:10]}...*\n\n"
            msg += f"• Positions: `{len(positions)}`\n"
            msg += f"• Total PnL: `${total_pnl:,.2f}`\n\n"
            msg += "*Recent Wins:*\n"
            for p in positions[:5]:
                msg += f"• {p.title[:30]}... | `${p.realized_pnl:,.0f}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown whales subcommand: {sub}. Use `leaderboard` or `analyze`.", update)

    async def _cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.listener._ledger:
            await self.listener.reply_to("Ledger not attached.", update)
            return

        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            mode = self.listener._ledger.get_execution_mode()
            metrics = self.listener._executor.get_metrics() if self.listener._executor else {}
            msg = "🎯 *Trading Engine Status*\n\n"
            msg += f"• Mode: `{mode}`\n"
            msg += f"• Fill Rate: `{metrics.get('fill_rate_pct', 0)}%`\n"
            msg += f"• Queue Depth: `{metrics.get('queue_depth', 0)}`\n"
            await self.listener.reply_to(msg, update)
        elif sub in ("paper", "shadow", "prod"):
            if len(args) > 1 and args[1] == "on":
                new_mode = sub.upper()
                self.listener._ledger.set_execution_mode(new_mode)
                await self.listener.reply_to(f"🔄 Execution mode changed to: `{new_mode}`", update)
            else:
                await self.listener.reply_to(f"Usage: `/trade {sub} on`", update)
        elif sub == "pnl":
            # Basic PnL summary
            cap = self.listener._ledger.get_capital_summary()
            total = cap.get("total_capital", 10000)
            avail = cap.get("available_capital", 10000)
            pnl = total - 10000 # Mocking initial capital
            msg = "💰 *PnL Report*\n\n"
            msg += f"• Net PnL: `${pnl:,.2f}`\n"
            msg += f"• Current Value: `${total:,.2f}`\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown trade subcommand: {sub}", update)

    async def _cmd_mcp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        args = context.args
        sub = args[0] if args else "status"

        if sub == "status":
            from mcp_agents.mcp_server import mcp
            msg = "🔌 *MCP Status*\n\n"
            msg += f"• Server: `quant-agentic-mcp`\n"
            msg += f"• Transport: `stdio`\n"
            msg += f"• Tools: `{len(mcp.list_tools())}`\n"
            await self.listener.reply_to(msg, update)
        elif sub == "tools":
            from mcp_agents.mcp_server import mcp
            tools = mcp.list_tools()
            msg = "🛠️ *MCP Tools*\n\n"
            for t in tools:
                msg += f"• `{t.name}`: {t.description[:50]}...\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown MCP subcommand: {sub}", update)

    async def _cmd_dev(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        args = context.args
        sub = args[0] if args else "metrics"

        if sub == "metrics":
            # System metrics
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            msg = "⚙️ *Dev Systems Metrics*\n\n"
            msg += f"• CPU Usage: `{cpu}%`\n"
            msg += f"• RAM Usage: `{mem}%`\n"
            msg += f"• Uptime: `{self.listener._fmt_uptime()}`\n"
            if self.listener._executor:
                metrics = self.listener._executor.get_metrics()
                msg += f"• Slippage (Sim): `${metrics.get('simulated_slippage_usd', 0):,.2f}`\n"
                msg += f"• Spread (Sim): `${metrics.get('simulated_spread_usd', 0):,.2f}`\n"
            await self.listener.reply_to(msg, update)
        elif sub == "logs":
            try:
                with open("logs/pm2-out.log", "r") as f:
                    lines = f.readlines()[-20:]
                msg = "📜 *System Logs*\n\n```\n" + "".join(lines) + "\n```"
                await self.listener.reply_to(msg, update)
            except Exception as e:
                await self.listener.reply_to(f"Failed to read logs: {e}", update)
        elif sub == "cleanup":
            from utils.data_archiver import DataArchiver
            archiver = DataArchiver()
            res = archiver.run_maintenance_cycle()
            msg = "🧹 *Maintenance Cycle Complete*\n\n"
            msg += f"• Tables Archived: `{len(res['microstructure'].get('tables_exported', []))}`\n"
            msg += f"• Log Files: `{res['logs'].get('files_compressed', 0)}` compressed\n"
            await self.listener.reply_to(msg, update)
        else:
            await self.listener.reply_to(f"Unknown dev subcommand: {sub}", update)

    async def _cmd_audit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        from utils.snapshot_manager import get_snapshot_manager
        sm = get_snapshot_manager()
        
        args = context.args
        cat = args[0] if args else "TRADING"
        
        snap = sm.get_latest(cat)
        if not snap:
            await self.listener.reply_to(f"No snapshots found for category: `{cat}`", update)
            return
            
        msg = f"🔍 *Snapshot Audit: {cat}*\n\n"
        msg += f"```json\n{json.dumps(snap, indent=2)[:3000]}\n```"
        await self.listener.reply_to(msg, update)

    async def _cmd_freeze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._cmd_risk(update, context=context) # Alias to risk kill

    async def _cmd_unfreeze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._cmd_risk(update, context=context) # Alias to risk resume

    async def _cmd_liquidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.listener._executor:
            await self.listener.reply_to("Executor not attached.", update)
            return
        
        res = await self.listener._executor.liquidate_all()
        msg = "🚨 *LIQUIDATION EXECUTED*\n\n"
        msg += f"• Status: `{res.get('status')}`\n"
        msg += f"• Orders Cancelled: `{res.get('cancelled_orders')}`\n"
        msg += f"• Message: {res.get('message')}\n"
        await self.listener.reply_to(msg, update)

    # NEW WALLET / TRANSFER / POLYMARKET / SIGNALS / MARKETS COMMANDS

    async def _cmd_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.wallet_manager:
            await self.listener.reply_to("💾 Wallet manager not attached.", update)
            return
        
        args = context.args
        sub = args[0].lower() if args else "help"
        
        if sub == "balance":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_balance
            await handle_wallet_balance(update, context, self.wallet_manager)
        elif sub == "health":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_health
            await handle_wallet_health(update, context, self.wallet_manager)
        elif sub == "help":
            from telegram_scraper.handlers.wallet_handler import handle_wallet_help
            await handle_wallet_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown wallet subcommand: {sub}. Use `/wallet help`", update)

    async def _cmd_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.transfer_manager:
            await self.listener.reply_to("📤 Transfer manager not attached.", update)
            return
        
        args = context.args
        sub = args[0].lower() if args else "help"
        
        if sub == "help":
            from telegram_scraper.handlers.transfer_handler import handle_transfer_help
            await handle_transfer_help(update, context)
        else:
            # Assume it's an amount (they forgot to use help)
            from telegram_scraper.handlers.transfer_handler import handle_transfer
            await handle_transfer(update, context, self.transfer_manager)

    async def _cmd_polymarket(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.order_manager:
            await self.listener.reply_to("🎲 Polymarket order manager not attached.", update)
            return
        
        args = context.args
        sub = args[0].lower() if args else "help"
        
        if sub == "bet":
            from telegram_scraper.handlers.polymarket_handler import handle_polymarket_bet
            await handle_polymarket_bet(update, context, self.order_manager)
        elif sub == "claim":
            from telegram_scraper.handlers.polymarket_handler import handle_polymarket_claim
            await handle_polymarket_claim(update, context, self.order_manager)
        elif sub == "help":
            from telegram_scraper.handlers.polymarket_handler import handle_polymarket_help
            await handle_polymarket_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown polymarket subcommand: {sub}. Use `/polymarket help`", update)

    async def _cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.signal_generator:
            await self.listener.reply_to("📊 Signal generator not attached.", update)
            return
        
        args = context.args
        sub = args[0].lower() if args else "help"
        
        if sub == "all":
            from telegram_scraper.handlers.signals_handler import handle_signals_all
            await handle_signals_all(update, context, self.signal_generator)
        elif sub == "help":
            from telegram_scraper.handlers.signals_handler import handle_signals_help
            await handle_signals_help(update, context)
        else:
            from telegram_scraper.handlers.signals_handler import handle_signals
            await handle_signals(update, context, self.signal_generator)

    async def _cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.listener._check_auth(update): return
        if not self.market_reader:
            await self.listener.reply_to("📈 Market reader not attached.", update)
            return
        
        args = context.args
        sub = args[0].lower() if args else "help"
        
        if sub == "list":
            from telegram_scraper.handlers.markets_handler import handle_markets_list
            await handle_markets_list(update, context, self.market_reader)
        elif sub == "info":
            from telegram_scraper.handlers.markets_handler import handle_markets_info
            await handle_markets_info(update, context, self.market_reader)
        elif sub == "search":
            from telegram_scraper.handlers.markets_handler import handle_markets_search
            await handle_markets_search(update, context, self.market_reader)
        elif sub == "help":
            from telegram_scraper.handlers.markets_handler import handle_markets_help
            await handle_markets_help(update, context)
        else:
            await self.listener.reply_to(f"Unknown markets subcommand: {sub}. Use `/markets help`", update)
