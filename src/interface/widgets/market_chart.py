from __future__ import annotations

from textual.widgets import Static

try:
    from textual_plotext import PlotextPlot
except Exception:  # pragma: no cover - optional dependency fallback
    PlotextPlot = None

try:
    import plotext as plt
except Exception:  # pragma: no cover - optional dependency fallback
    plt = None

class MarketChart(Static):
    """Widget pour afficher un graphique temps réel via Plotext."""

    def on_mount(self) -> None:
        self.plot = None
        if PlotextPlot is not None:
            self.plot = PlotextPlot()
            self.mount(self.plot)
        self.data_x = list(range(100))
        self.data_y = [0] * 100
        self._render_chart()

    def update_chart(self, new_val: float = 0.0, label: str = "Live Asset Price") -> None:
        self.data_y.pop(0)
        self.data_y.append(new_val)
        self._render_chart(label=label)

    def _render_chart(self, label: str = "Live Asset Price") -> None:
        if self.plot is None or plt is None:
            self.update(f"{label}: {self.data_y[-1]:.4f}")
            return

        renderer = self.plot.plt
        renderer.clear_terminal()
        renderer.clear_figure()
        renderer.theme("dark")
        renderer.plot(self.data_x, self.data_y, color="cyan")
        renderer.title(label)
        renderer.xlabel("Ticks")
        renderer.ylabel("Price")
        self.plot.refresh()
