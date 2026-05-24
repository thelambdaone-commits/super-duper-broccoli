import pandas as pd

from schemas.optimization.optimizer import PortfolioOptimizer


class TestPortfolioOptimizer:
    def setup_method(self):
        self.opt = PortfolioOptimizer()

    def test_equal_weight_fallback(self):
        prices = pd.DataFrame({
            "AAPL": [100, 101, 102],
            "MSFT": [200, 202, 204],
            "GOOGL": [150, 151, 152],
        })
        result = self.opt.optimize_weights(prices, method="equal_weight")
        assert "weights" in result
        if result["weights"]:
            total = sum(result["weights"].values())
            assert abs(total - 1.0) < 0.01

    def test_optimize_without_libraries(self):
        self.opt._skportfolio = None
        self.opt._pyportfolioopt = None
        prices = pd.DataFrame({"AAPL": [100, 101]})
        result = self.opt.optimize_weights(prices)
        assert result["library"] == "builtin"

    def test_status(self):
        status = self.opt.get_status()
        assert "scikit_portfolio" in status
        assert "default_method" in status
