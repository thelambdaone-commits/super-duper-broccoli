import sys
import os
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.feature_store import FeatureStore
from utils.model_validator import ModelValidator

def main():
    store = FeatureStore()
    validator = ModelValidator(store)
    
    print("=======================================")
    print("🧪 LOBSTAR MODEL VALIDATION & DRIFT AUDIT")
    print("=======================================")
    
    ticker = "SOL"
    print(f"\n[RUNNING KS-TEST DRIFT CHECK FOR {ticker}]")
    try:
        report = validator.run_health_check(ticker, "default_v1")
        print(f"  • Status: {report.get('health', 'UNKNOWN')}")
        drift_rep = report.get('drift_report', {})
        print(f"  • KS Statistic: {drift_rep.get('ks_stat', 0.0):.6f}")
        print(f"  • P-Value: {drift_rep.get('p_value', 0.0):.6f}")
        print(f"  • Drift Detected: {drift_rep.get('drift_detected', False)}")
        
        # Check actual sample sizes
        current = store.get_feature_history(ticker, "mid_price", limit=100)
        reference = store.get_feature_history(ticker, "mid_price", limit=1000)
        print(f"  • Current Sample Size: {len(current)}")
        print(f"  • Reference Sample Size: {len(reference)}")
    except Exception as e:
        print(f"  • Error: {e}")

if __name__ == "__main__":
    main()
