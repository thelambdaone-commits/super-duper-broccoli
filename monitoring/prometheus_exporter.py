"""
Prometheus Metrics Exporter pour Lobstar Bot
Expose le PnL, la latence, l'état du wallet et l'état de l'orchestrateur.
"""
from prometheus_client import start_http_server, Gauge, Counter, Histogram
import logging
from typing import Optional

logger = logging.getLogger("PrometheusExporter")

# Metrics
LOBSTAR_MODE = Gauge('lobstar_execution_mode', 'Mode actuel du bot (0=PAPER, 1=SHADOW, 2=PROD)')
WALLET_BALANCE = Gauge('lobstar_wallet_balance_usdc', 'Balance courante en USDC')
ACTIVE_POSITIONS = Gauge('lobstar_active_positions', 'Nombre de positions ouvertes')
TOTAL_TRADES = Counter('lobstar_total_trades', 'Nombre total de trades exécutés')
PNL_REALIZED = Gauge('lobstar_pnl_realized_usdc', 'PnL Réalisé en USDC')
API_LATENCY = Histogram('lobstar_api_latency_seconds', 'Latence API Polymarket')

class PrometheusExporter:
    def __init__(self, port: int = 8000):
        self.port = port
        self._started = False

    def start(self):
        if not self._started:
            try:
                start_http_server(self.port)
                self._started = True
                logger.info(f"✅ Prometheus Exporter démarré sur le port {self.port}")
            except Exception as e:
                logger.error(f"❌ Impossible de démarrer Prometheus Exporter: {e}")

    def update_mode(self, mode: str):
        mapping = {"PAPER": 0, "SHADOW": 1, "PROD": 2}
        if mode.upper() in mapping:
            LOBSTAR_MODE.set(mapping[mode.upper()])

    def update_wallet(self, balance: float):
        WALLET_BALANCE.set(balance)

    def update_positions(self, count: int):
        ACTIVE_POSITIONS.set(count)

    def record_trade(self):
        TOTAL_TRADES.inc()

    def update_pnl(self, pnl: float):
        PNL_REALIZED.set(pnl)

    def record_latency(self, seconds: float):
        API_LATENCY.observe(seconds)

# Instance globale
exporter = PrometheusExporter()
