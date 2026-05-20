
from utils.macro_intelligence import MacroIntelligence


class TestMacroIntelligence:
    def setup_method(self):
        self.macro = MacroIntelligence()

    def test_taylor_rule_1993(self):
        result = self.macro.taylor_rule(inflation=3.0, unemployment=4.0, current_rate=4.5, variant="1993")
        assert result.implied_rate > 0
        assert result.stance in ("HAWKISH", "DOVISH", "NEUTRAL")
        assert "natural_rate" in result.components

    def test_taylor_rule_1999(self):
        result = self.macro.taylor_rule(inflation=2.0, unemployment=5.0, current_rate=3.0, variant="1999")
        assert result.implied_rate > 0

    def test_taylor_rule_nonlinear(self):
        result = self.macro.taylor_rule(inflation=4.0, unemployment=3.5, current_rate=5.0, variant="nonlinear")
        assert result.implied_rate > 0

    def test_gdp_nowcast(self):
        indicators = {
            "industrial_production": 102.5,
            "retail_sales": 101.0,
            "employment_change": 200,
            "manufacturing_pmi": 52.0,
            "services_pmi": 51.0,
            "consumer_confidence": 105.0,
        }
        result = self.macro.gdp_nowcast(indicators)
        assert result.gdp_growth > 0
        assert result.confidence_interval[0] < result.confidence_interval[1]
        assert result.r_squared > 0

    def test_risk_off_score_hawkish(self):
        taylor = self.macro.taylor_rule(inflation=5.0, unemployment=3.0, current_rate=3.0)
        risk = self.macro.risk_off_score(taylor_result=taylor, vix=35.0)
        assert risk["risk_off_score"] > 0
        assert "regime" in risk

    def test_risk_off_score_dovish(self):
        taylor = self.macro.taylor_rule(inflation=2.0, unemployment=5.5, current_rate=5.0)
        risk = self.macro.risk_off_score(taylor_result=taylor, vix=12.0)
        assert risk["risk_on_score"] > risk["risk_off_score"]

    def test_status(self):
        status = self.macro.get_status()
        assert "fred_api_configured" in status
