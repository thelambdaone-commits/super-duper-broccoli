import logging
import os
import importlib.util
from typing import List, Any

logger = logging.getLogger("StrategyManager")

class StrategyManager:
    """
    Orchestrates multiple independent trading strategies.
    Supports dynamic loading of projects/modules from the strategies directory.
    """
    def __init__(self, strategies_dir: str = "user_data/strategies"):
        self.strategies_dir = strategies_dir
        self.loaded_strategies: List[Any] = []

    def load_strategies(self):
        """Discovers and imports all strategies in the directory."""
        if not os.path.exists(self.strategies_dir):
            logger.warning(f"Strategies directory {self.strategies_dir} not found.")
            return

        for filename in os.listdir(self.strategies_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = filename[:-3]
                file_path = os.path.join(self.strategies_dir, filename)

                try:
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Look for a class that ends with 'Strategy'
                    for attr_name in dir(module):
                        if attr_name.endswith("Strategy"):
                            strategy_class = getattr(module, attr_name)
                            strategy_instance = strategy_class()
                            self.loaded_strategies.append(strategy_instance)
                            logger.info(f"Successfully imported strategy project: {attr_name}")
                except Exception as e:
                    logger.error(f"Failed to import strategy {module_name}: {e}")

    def get_all_signals(self, market_data: dict) -> List[dict]:
        """Aggregates signals from all running strategies."""
        all_signals = []
        for strategy in self.loaded_strategies:
            try:
                if hasattr(strategy, "generate_signal"):
                    signal = strategy.generate_signal(market_data)
                    if signal:
                        all_signals.append(signal)
            except Exception as e:
                logger.error(f"Error in strategy {strategy.__class__.__name__}: {e}")
        return all_signals
