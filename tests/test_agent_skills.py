import json
import unittest
from agent_skills.registry import SkillsRegistry
from agent_skills.skillsmp_adapter import SkillsMPAdapter


class TestAgentSkillsSystem(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillsRegistry()
        self.adapter = SkillsMPAdapter()

    def test_registry_discovers_skills(self) -> None:
        """Verifies that the registry dynamically parses manifests in subfolders."""
        skills = self.registry.list_skills()
        self.assertGreaterEqual(len(skills), 6)

        ids = {s.get("id") for s in skills}
        self.assertIn("market_scanner_skill", ids)
        self.assertIn("portfolio_risk_skill", ids)
        self.assertIn("backtest_swarm_skill", ids)
        self.assertIn("crypto_arbitrage_skill", ids)
        self.assertIn("polymarket_market_making_skill", ids)
        self.assertIn("brave_search_skill", ids)

    def test_tool_definitions_compiles_json_schema(self) -> None:
        """Verifies that OpenAI/Anthropic parameter schemas compile correctly."""
        tools = self.registry.get_tool_definitions()
        self.assertGreaterEqual(len(tools), 6)

        names = {t.get("name") for t in tools}
        self.assertIn("scan_polymarket", names)
        self.assertIn("calculate_kelly_size", names)
        self.assertIn("run_swarm_backtest", names)
        self.assertIn("find_arbitrage_opportunities", names)
        self.assertIn("calculate_market_making_spreads", names)
        self.assertIn("search_brave_web", names)

    def test_dispatch_market_scanner_skill(self) -> None:
        """Verifies dynamic execution of the market scanner skill entrypoint."""
        res = self.registry.dispatch_tool(
            skill_id="market_scanner_skill",
            tool_name="scan_polymarket",
            arguments={"limit": 5}
        )
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("limit_scanned"), 5)
        self.assertIn("sentiment_label", res)

    def test_dispatch_portfolio_risk_skill(self) -> None:
        """Verifies dynamic execution of the risk sizing skill entrypoint."""
        res = self.registry.dispatch_tool(
            skill_id="portfolio_risk_skill",
            tool_name="calculate_kelly_size",
            arguments={
                "ticker": "SOL",
                "side": "BUY",
                "price": 0.65,
                "confidence": 0.75,
                "regime": "LOW_VOLATILITY"
            }
        )
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("ticker"), "SOL")
        self.assertGreater(res.get("recommended_size"), 0.0)

    def test_dispatch_backtest_swarm_skill(self) -> None:
        """Verifies dynamic execution of the multi-agent backtesting skill entrypoint."""
        res = self.registry.dispatch_tool(
            skill_id="backtest_swarm_skill",
            tool_name="run_swarm_backtest",
            arguments={"asset": "ETH"}
        )
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("asset"), "ETH")
        self.assertEqual(res.get("orchestrated_scenarios"), 4)

    def test_dispatch_crypto_arbitrage_skill(self) -> None:
        """Verifies dynamic execution of the crypto and Polymarket arbitrage finder skill."""
        res = self.registry.dispatch_tool(
            skill_id="crypto_arbitrage_skill",
            tool_name="find_arbitrage_opportunities",
            arguments={"min_spread_pct": 1.5}
        )
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertGreaterEqual(res.get("arbitrage_count"), 1)
        self.assertIn("opportunities", res)
        self.assertGreaterEqual(res["opportunities"][0]["implied_spread_pct"], 1.5)

    def test_dispatch_polymarket_market_making_skill(self) -> None:
        """Verifies dynamic execution of the Polymarket order-book market-making skill."""
        res = self.registry.dispatch_tool(
            skill_id="polymarket_market_making_skill",
            tool_name="calculate_market_making_spreads",
            arguments={
                "mid_price": 0.55,
                "volatility": 0.03,
                "inventory": 25,
                "target_inventory": 0
            }
        )
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("inventory_delta"), 25)
        self.assertEqual(res.get("skew_direction"), "SHORT_SKEWED")
        self.assertLess(res.get("bid_quote"), 0.55)
        self.assertGreater(res.get("ask_quote"), 0.50)

    def test_dispatch_brave_search_skill(self) -> None:
        """Verifies dynamic execution of the Brave Search web querying capability."""
        res = self.registry.dispatch_tool(
            skill_id="brave_search_skill",
            tool_name="search_brave_web",
            arguments={"query": "Solana prediction market pricing", "count": 2}
        )
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("query"), "Solana prediction market pricing")
        self.assertGreaterEqual(len(res.get("results")), 1)
        self.assertIn("title", res["results"][0])

    def test_skillsmp_leasing_and_rentals(self) -> None:
        """Verifies the Skills Marketplace Provider listing and executing leasing adapter."""
        rentables = self.adapter.list_rentable_skills()
        self.assertGreaterEqual(len(rentables), 6)
        self.assertEqual(rentables[0]["pricing"], "FREE_OS_RENTAL")

        lease_res_str = self.adapter.lease_and_execute_tool(
            skill_id="portfolio_risk_skill",
            tool_name="calculate_kelly_size",
            arguments={
                "ticker": "BTC",
                "side": "BUY",
                "price": 0.58,
                "confidence": 0.65,
                "regime": "HIGH_TREND_VOLATILITY"
            }
        )
        lease_res = json.loads(lease_res_str)
        self.assertEqual(lease_res.get("lease_status"), "COMPLETED")
        self.assertEqual(lease_res.get("result", {}).get("ticker"), "BTC")


if __name__ == "__main__":
    unittest.main()
