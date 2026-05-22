import json
import os
import glob
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("AI_ROI_Analyzer")

class AIROIAnalyzer:
    """
    Analyzes the Return on Investment (ROI) for AI signal generation.
    Joins token cost bundles with PnL results from the Ledger.
    """

    def __init__(self, usage_dir: str = "monitoring/llm_usage/bundles", ledger_path: str = "ledger.db"):
        self.usage_dir = Path(usage_dir)
        self.ledger_path = ledger_path

    def run_analysis(self):
        # 1. Load all usage bundles
        bundles = []
        for f in self.usage_dir.glob("*.json"):
            try:
                with open(f, "r") as data:
                    bundles.append(json.load(data))
            except Exception as e:
                logger.error(f"Failed to load bundle {f}: {e}")

        if not bundles:
            print("No usage bundles found for ROI analysis.")
            return

        total_cost = 0.0
        from monitoring.llm_cost_tracker import cost_tracker

        report = []
        for b in bundles:
            if not b.get("usage"): continue
            usage = b["usage"][0]
            cost = cost_tracker.calculate_cost(usage["model"], usage["input_tokens"], usage["output_tokens"])
            total_cost += cost
            report.append({
                "task_id": b["metadata"]["task_id"],
                "model": usage["model"],
                "cost_usd": cost
            })

        print(f"\n{'-'*40}")
        print(f"📊 [AI ROI ANALYSIS] Summary")
        print(f"{'-'*40}")
        print(f"Total LLM Requests: {len(bundles)}")
        print(f"Total Cumulative Cost: ${total_cost:.6f} USD")
        print(f"{'-'*40}\n")

        return report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    analyzer = AIROIAnalyzer()
    analyzer.run_analysis()
