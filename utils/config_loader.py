import os
import json
import logging

logger = logging.getLogger("LOBSTAR_ConfigLoader")

def load_trading_params() -> dict:
    default_params = {
        "MIN_EDGE_THRESHOLD": 0.07,
        "MAX_KELLY_PCT": 0.25,
        "FRICTION_PER_CONTRACT": 0.005,
        "MAX_POSITION_PCT": 0.05,
        "HMM_REGIME_FILTER": True,
        "MAX_DRAWDOWN_PCT": 0.15,
        "STOP_LOSS_PCT": 0.10,
        "TAKE_PROFIT_PCT": 0.20,
        "BRIER_THRESHOLD": 0.05,
        "PSI_THRESHOLD": 0.20,
        "KL_THRESHOLD": 0.50,
        "DRIFT_CHECK_INTERVAL": 60,
        "ARBITRAGE_TRIGGER_THRESHOLD": 0.015,
        "LEGGING_LIQUIDITY_MIN": 50
    }
    
    # Path relative to project root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "trading_params.json")
    
    if not os.path.exists(config_path):
        logger.warning(f"Config file not found at {config_path}. Using hardcoded default parameters.")
        return default_params
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        flat_params = {}
        for section, params in data.items():
            if isinstance(params, dict):
                for k, v in params.items():
                    flat_params[k] = v
                    
        # Merge defaults for any missing keys
        for k, v in default_params.items():
            if k not in flat_params:
                flat_params[k] = v
                
        return flat_params
    except Exception as e:
        logger.error(f"Error loading {config_path}: {e}. Falling back to default parameters.")
        return default_params

# Expose globally
TRADING_PARAMS = load_trading_params()
