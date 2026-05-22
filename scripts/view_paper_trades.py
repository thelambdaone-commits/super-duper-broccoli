#!/usr/bin/env python3
import sqlite3
import argparse
import sys
import os
from colorama import init, Fore, Style

init(autoreset=True)

def fetch_paper_trades(db_path="data/ledger.db"):
    if not os.path.exists(db_path):
        print(f"{Fore.RED}Erreur : Ledger introuvable à {db_path}{Style.RESET_ALL}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if table exists
    try:
        cursor.execute("SELECT * FROM paper_positions ORDER BY opened_at DESC")
        trades = cursor.fetchall()
    except sqlite3.OperationalError:
        print(f"{Fore.RED}Table 'paper_positions' n'existe pas encore ou erreur SQL.{Style.RESET_ALL}")
        sys.exit(0)
    finally:
        conn.close()

    return trades

def display_paper_trades(trades):
    if not trades:
        print(f"{Fore.YELLOW}Aucun paper trade trouvé.{Style.RESET_ALL}")
        return

    print(f"\n{Style.BRIGHT}=== 📈 PAPER TRADING JOURNAL ==={Style.RESET_ALL}\n")
    print(f"{'ID':<6} | {'Date':<19} | {'Ticker':<20} | {'Side':<5} | {'Size':<8} | {'Entry':<8} | {'Exit':<8} | {'PnL':<8} | {'Status':<8}")
    print("-" * 105)

    total_pnl = 0.0
    wins = 0
    closed_trades = 0

    for t in trades:
        pid = str(t['position_id'])[:5]
        date = str(t['opened_at'])[:19]
        ticker = str(t['ticker'])[:19]
        side = t['side']
        size = f"{t['size']:.2f}"
        entry = f"{t['entry_price']:.4f}"
        exit_p = f"{t['exit_price']:.4f}" if t['exit_price'] is not None else "-"
        pnl = t['pnl'] if t['pnl'] is not None else 0.0
        status = t['status']

        # Color coding
        if status == "CLOSED":
            closed_trades += 1
            if pnl > 0:
                color = Fore.GREEN
                wins += 1
            elif pnl < 0:
                color = Fore.RED
            else:
                color = Fore.WHITE
            pnl_str = f"{pnl:+.4f}"
        else:
            color = Fore.YELLOW
            pnl_str = "OPEN"

        total_pnl += pnl

        row = f"{pid:<6} | {date:<19} | {ticker:<20} | {side:<5} | {size:<8} | {entry:<8} | {exit_p:<8} | {color}{pnl_str:<8}{Style.RESET_ALL} | {color}{status:<8}{Style.RESET_ALL}"
        print(row)

    print("-" * 105)
    print(f"\n{Style.BRIGHT}📊 RÉSUMÉ GLOBAL{Style.RESET_ALL}")
    print(f"Total Trades: {len(trades)} (Fermés: {closed_trades})")
    win_rate = (wins / closed_trades * 100) if closed_trades > 0 else 0

    pnl_color = Fore.GREEN if total_pnl > 0 else (Fore.RED if total_pnl < 0 else Fore.WHITE)
    print(f"Win Rate:   {Fore.CYAN}{win_rate:.1f}%{Style.RESET_ALL}")
    print(f"Net PnL:    {pnl_color}{total_pnl:+.4f} USDC{Style.RESET_ALL}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Trading Viewer")
    parser.add_argument("--db", default="data/ledger.db", help="Chemin vers ledger.db")
    args = parser.parse_args()

    trades = fetch_paper_trades(args.db)
    display_paper_trades(trades)
