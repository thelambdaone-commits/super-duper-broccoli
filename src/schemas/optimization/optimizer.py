import logging
from typing import Any, Optional

logger = logging.getLogger("PortfolioOptimizer")


class PortfolioOptimizer:
    def __init__(self, method: str = "mean_variance"):
        self.method = method
        self._skportfolio: Any = None
        self._riskfoliolib: Any = None
        self._pyportfolioopt: Any = None
        self._try_imports()

    def _try_imports(self) -> None:
        try:
            import skportfolio as sp
            self._skportfolio = sp
            logger.info("scikit-portfolio available")
        except ImportError:
            pass
        try:
            import riskfolio as rp
            self._riskfoliolib = rp
            logger.info("Riskfolio-Lib available")
        except ImportError:
            pass
        try:
            import pypfopt
            self._pyportfolioopt = pypfopt
            logger.info("PyPortfolioOpt available")
        except ImportError:
            pass

    def optimize_weights(
        self,
        prices_df: Any,
        method: Optional[str] = None,
        risk_aversion: float = 1.0,
        **kwargs,
    ) -> dict:
        use_method = method or self.method
        try:
            if self._skportfolio is not None:
                return self._optimize_skportfolio(prices_df, use_method, **kwargs)
            elif self._pyportfolioopt is not None:
                return self._optimize_pypfopt(prices_df, use_method, risk_aversion, **kwargs)
            elif self._riskfoliolib is not None:
                return self._optimize_riskfolio(prices_df, use_method, **kwargs)
            else:
                return self._optimize_equal_weight(prices_df)
        except Exception as e:
            logger.warning("Portfolio optimization error: %s", e)
            return self._optimize_equal_weight(prices_df)

    def _optimize_skportfolio(self, prices_df: Any, method: str, **kwargs) -> dict:
        models = {
            "min_volatility": "MinimumVolatility",
            "max_sharpe": "MaximumSharpeRatio",
            "risk_parity": "RiskParity",
            "cvar": "ConditionalValueAtRisk",
        }
        model_name = models.get(method, "MinimumVolatility")
        try:
            model_cls = getattr(self._skportfolio, model_name)
            model = model_cls()
            model.fit(prices_df)
            weights = model.weights_.to_dict() if hasattr(model, "weights_") else {}
            return {"method": method, "weights": weights, "library": "scikit-portfolio"}
        except Exception as e:
            logger.warning("skportfolio error: %s", e)
            return self._optimize_equal_weight(prices_df)

    def _optimize_pypfopt(self, prices_df: Any, method: str, risk_aversion: float, **kwargs) -> dict:
        try:
            from pypfopt import EfficientFrontier, risk_models, expected_returns
            mu = expected_returns.mean_historical_return(prices_df)
            S = risk_models.sample_cov(prices_df)
            ef = EfficientFrontier(mu, S)
            if method == "max_sharpe":
                weights = ef.max_sharpe(risk_free_rate=kwargs.get("risk_free_rate", 0.0))
            else:
                weights = ef.min_volatility()
            return {
                "method": method,
                "weights": {k: round(v, 4) for k, v in weights.items() if abs(v) > 1e-6},
                "library": "PyPortfolioOpt",
            }
        except Exception as e:
            logger.warning("PyPortfolioOpt error: %s", e)
            return self._optimize_equal_weight(prices_df)

    def _optimize_riskfolio(self, prices_df: Any, method: str, **kwargs) -> dict:
        return self._optimize_equal_weight(prices_df)

    def _optimize_equal_weight(self, prices_df: Any) -> dict:
        try:
            cols = list(prices_df.columns) if hasattr(prices_df, "columns") else []
            n = len(cols)
            weights = {c: round(1.0 / n, 4) for c in cols} if n > 0 else {}
            return {"method": "equal_weight", "weights": weights, "library": "builtin"}
        except Exception:
            return {"method": "equal_weight", "weights": {}, "library": "builtin"}

    def get_status(self) -> dict:
        return {
            "scikit_portfolio": self._skportfolio is not None,
            "riskfolio_lib": self._riskfoliolib is not None,
            "pypfopt": self._pyportfolioopt is not None,
            "default_method": self.method,
        }
