import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ledger.ledger_db import Ledger

def main():
    ledger = Ledger()
    print("=======================================")
    print("📊 LOBSTAR PERFORMANCE & WIN-RATE AUDIT")
    print("=======================================")
    
    # 1. PAPER TRADING
    print("\n[PAPER TRADING]")
    try:
        summary_paper = ledger.get_performance_summary(mode="PAPER")
        if summary_paper:
            for k, v in summary_paper.items():
                print(f"  • {k}: {v}")
        else:
            print("  • No summary found for PAPER mode.")
    except Exception as e:
        print(f"  • Error: {e}")

    # 2. PROD TRADING
    print("\n[PRODUCTION TRADING]")
    try:
        summary_prod = ledger.get_performance_summary(mode="PROD")
        if summary_prod:
            for k, v in summary_prod.items():
                print(f"  • {k}: {v}")
        else:
            print("  • No summary found for PROD mode.")
    except Exception as e:
        print(f"  • Error: {e}")

if __name__ == "__main__":
    main()
