import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.feature_store import FeatureStore

def main():
    store = FeatureStore()
    print("=======================================")
    print("🧠 LOBSTAR MLOPS & PREDICTION TRACKING AUDIT")
    print("=======================================")
    
    # 1. Store stats
    stats = store.get_stats()
    print("\n[DB TABLE COUNTS]")
    for table, count in stats.items():
        print(f"  • {table}: {count} rows")
        
    # 2. Query decisions
    print("\n[LATEST DECISIONS LOGGED]")
    try:
        decisions = store._conn.execute("SELECT timestamp, mode, ticker, side, price, sized, executed_size, regime_label, authorized, reason FROM decisions_log ORDER BY timestamp DESC LIMIT 10").fetchall()
        if decisions:
            for d in decisions:
                print(f"  • TS: {d[0]} | Mode: {d[1]} | Ticker: {d[2]} | Side: {d[3]} | Price: {d[4]} | Sized: {d[5]} | Executed: {d[6]} | Regime: {d[7]} | Auth: {d[8]} | Reason: {d[9]}")
        else:
            print("  • No decisions logged in decisions_log yet.")
    except Exception as e:
        print(f"  • Error: {e}")

    # 3. Query signals ingested
    print("\n[LATEST SIGNALS INGESTED]")
    try:
        signals = store._conn.execute("SELECT timestamp, source, ticker, side, price, size, confidence, regime_label FROM signals_ingested ORDER BY timestamp DESC LIMIT 10").fetchall()
        if signals:
            for s in signals:
                print(f"  • TS: {s[0]} | Source: {s[1]} | Ticker: {s[2]} | Side: {s[3]} | Price: {s[4]} | Size: {s[5]} | Conf: {s[6]} | Regime: {s[7]}")
        else:
            print("  • No signals recorded in signals_ingested yet.")
    except Exception as e:
        print(f"  • Error: {e}")

if __name__ == "__main__":
    main()
