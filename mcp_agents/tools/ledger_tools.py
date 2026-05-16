from typing import Optional
from ledger.ledger_db import Ledger

def get_ledger_tools(mcp, ledger: Optional[Ledger]):
    @mcp.tool(
        name="get_ledger_state",
        description="Reads active positions, capital allocation, and available capital from the SQLite ledger.",
    )
    def get_ledger_state() -> dict:
        if ledger is None:
            return {"error": "Ledger not initialized"}
        return {
            "capital_summary": ledger.get_capital_summary(),
            "open_positions": ledger.get_open_positions(),
        }

    @mcp.tool(
        name="set_execution_mode",
        description="Changes the execution mode: REPLAY, PAPER, SHADOW, or PROD.",
    )
    def set_execution_mode(mode: str) -> dict:
        if ledger is None:
            return {"error": "Ledger not initialized"}
        mode_upper = mode.upper().strip()
        if mode_upper not in ("REPLAY", "PAPER", "SHADOW", "PROD"):
            return {"error": f"Invalid mode: {mode}. Choose from REPLAY, PAPER, SHADOW, PROD."}
        ledger.set_execution_mode(mode_upper)
        return {
            "status": "OK",
            "execution_mode": mode_upper,
            "message": f"Execution mode set to {mode_upper}.",
        }

    @mcp.tool(
        name="get_execution_mode",
        description="Returns the current execution mode: REPLAY, PAPER, SHADOW, or PROD.",
    )
    def get_execution_mode() -> dict:
        if ledger is None:
            return {"error": "Ledger not initialized"}
        return {
            "execution_mode": ledger.get_execution_mode(),
        }

    @mcp.tool(
        name="get_paper_positions",
        description="Returns all open paper trading positions from the virtual ledger.",
    )
    def get_paper_positions() -> dict:
        if ledger is None:
            return {"error": "Ledger not initialized"}
        return {
            "paper_positions": ledger.get_paper_positions(status="OPEN"),
        }
