import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("LLMCostTracker")

class LLMCostTracker:
    """
    Lobstar LLM Cost Tracker (Inspired by jovd83/token-usage-cost-report).
    Implements Normalized Usage Bundle contract for auditable AI costs.
    """

    def __init__(self, output_dir: str = "monitoring/llm_usage/bundles"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Simplified pricing (Price per 1M tokens)
        self.pricing = {
            "gpt-4o": {"in": 5.0, "out": 15.0},
            "gpt-4o-mini": {"in": 0.15, "out": 0.60},
            "claude-3-5-sonnet": {"in": 3.0, "out": 15.0},
            "deepseek-chat": {"in": 0.14, "out": 0.28},
            "llama-3.3-70b-versatile": {"in": 0.59, "out": 0.79},
        }

    def record_usage(self, task_id: str, model: str, input_tokens: int, output_tokens: int, provider: str = "unknown"):
        """Records a normalized usage bundle for a specific task (signal)."""
        bundle = {
            "metadata": {
                "repository": "quant-agentic-trading-core",
                "runtime": "lobstar-signal-generator",
                "task_id": task_id,
                "provider": provider
            },
            "usage": [
                {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                }
            ],
            "sources": ["internal-llm-logger"]
        }

        filename = f"usage_{task_id}_{int(time.time())}.json"
        filepath = self.output_dir / filename

        try:
            with open(filepath, "w") as f:
                json.dump(bundle, f, indent=2)
            logger.info(f"💾 [LLM USAGE] Bundle saved for task {task_id}: {model} ({input_tokens} in / {output_tokens} out)")
        except Exception as e:
            logger.error(f"Failed to save usage bundle: {e}")

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculates USD cost based on internal pricing table."""
        rates = self.pricing.get(model)
        if not rates:
            # Check if model has a prefix (e.g. 'groq/llama...')
            base_model = model.split("/")[-1] if "/" in model else model
            rates = self.pricing.get(base_model, {"in": 1.0, "out": 2.0}) # Conservative default

        cost_in = (input_tokens / 1_000_000) * rates["in"]
        cost_out = (output_tokens / 1_000_000) * rates["out"]
        return cost_in + cost_out

# Instance globale
cost_tracker = LLMCostTracker()
