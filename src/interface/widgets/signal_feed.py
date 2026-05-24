from __future__ import annotations

from textual.widgets import Log, Static

class SignalFeed(Static):
    def on_mount(self) -> None:
        self.log_widget = Log(highlight=True)
        self.mount(self.log_widget)

    def add_signal(self, signal: dict) -> None:
        ticker = signal.get("ticker", "???")
        side = signal.get("side", signal.get("direction", "???"))
        prob = float(signal.get("p_real", signal.get("confidence", 0.0)) or 0.0)
        source = signal.get("source", "signal")
        self.log_widget.write_line(
            f"[{source}] [{ticker}] {side} | Conf: {prob:.1%} | {signal.get('timestamp', '')}"
        )
