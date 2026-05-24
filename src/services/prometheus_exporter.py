"""
Prometheus Metrics Exporter pour Lobstar Bot
Expose le PnL, la latence, l'état du wallet et l'état de l'orchestrateur.
"""
import errno
import socket
import logging
from typing import Optional

try:
    from prometheus_client import start_http_server, Gauge, Counter, Histogram
except ModuleNotFoundError:
    start_http_server = None
    Gauge = Counter = Histogram = None

logger = logging.getLogger("PrometheusExporter")

# Metrics
if Gauge is not None:
    LOBSTAR_MODE = Gauge('lobstar_execution_mode', 'Mode actuel du bot (0=PAPER, 1=SHADOW, 2=PROD)')
    WALLET_BALANCE = Gauge('lobstar_wallet_balance_usdc', 'Balance courante en USDC')
    ACTIVE_POSITIONS = Gauge('lobstar_active_positions', 'Nombre de positions ouvertes')
    TOTAL_TRADES = Counter('lobstar_total_trades', 'Nombre total de trades exécutés')
    PNL_REALIZED = Gauge('lobstar_pnl_realized_usdc', 'PnL Réalisé en USDC')
    API_LATENCY = Histogram('lobstar_api_latency_seconds', 'Latence API Polymarket')
else:
    LOBSTAR_MODE = WALLET_BALANCE = ACTIVE_POSITIONS = TOTAL_TRADES = PNL_REALIZED = API_LATENCY = None

class PrometheusExporter:
    def __init__(self, port: int = 8000):
        self.port = port
        self._started = False

    def _port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", self.port)) == 0

    def start(self):
        if self._started:
            return
        if start_http_server is None:
            logger.warning("Prometheus exporter disabled: prometheus_client is not installed.")
            return
        if self._port_in_use():
            logger.warning(
                "Prometheus exporter port %s already in use; assuming another process already exposes metrics.",
                self.port,
            )
            return
        if not self._started:
            try:
                start_http_server(self.port)
                self._started = True
                logger.info(f"✅ Prometheus Exporter démarré sur le port {self.port}")
            except Exception as e:
                if isinstance(e, OSError) and e.errno == errno.EADDRINUSE:
                    logger.warning(
                        "Prometheus exporter port %s already in use during startup; skipping local exporter.",
                        self.port,
                    )
                    return
                logger.error(f"❌ Impossible de démarrer Prometheus Exporter: {e}")

    def update_mode(self, mode: str):
        if LOBSTAR_MODE is None:
            return
        mapping = {"PAPER": 0, "SHADOW": 1, "PROD": 2}
        if mode.upper() in mapping:
            LOBSTAR_MODE.set(mapping[mode.upper()])

    def update_wallet(self, balance: float):
        if WALLET_BALANCE is None:
            return
        WALLET_BALANCE.set(balance)

    def update_positions(self, count: int):
        if ACTIVE_POSITIONS is None:
            return
        ACTIVE_POSITIONS.set(count)

    def record_trade(self):
        if TOTAL_TRADES is None:
            return
        TOTAL_TRADES.inc()

    def update_pnl(self, pnl: float):
        if PNL_REALIZED is None:
            return
        PNL_REALIZED.set(pnl)

    def record_latency(self, seconds: float):
        if API_LATENCY is None:
            return
        API_LATENCY.observe(seconds)

# Instance globale
exporter = PrometheusExporter()
