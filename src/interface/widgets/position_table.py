from __future__ import annotations

from textual.widgets import DataTable, Static

class PositionTable(Static):
    def _table(self) -> DataTable:
        return self.query_one(DataTable)

    def on_mount(self) -> None:
        self.table = DataTable(id="positions-dt")
        self.table.add_columns("Ticker", "Side", "Size", "Entry", "Current", "PnL %")
        self.mount(self.table)

    def update_positions(self, positions: list[dict]) -> None:
        table = self._table()
        table.clear()
        for p in positions:
            current = float(p.get("current_price", p.get("entry_price", 0.0)) or 0.0)
            entry = float(p.get("entry_price", 0.0) or 0.0)
            pnl_pct = p.get("pnl_pct")
            if pnl_pct is None and entry > 0:
                pnl_pct = ((current - entry) / entry) * 100.0
            table.add_row(
                p.get("ticker", "N/A"),
                p.get("side", "N/A"),
                f"{p.get('size', 0):.2f}",
                f"{entry:.4f}",
                f"{current:.4f}",
                f"{float(pnl_pct or 0.0):+.2f}%"
            )
