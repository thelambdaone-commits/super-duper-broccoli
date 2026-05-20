import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("MacroIntelligence")


@dataclass
class TaylorRuleResult:
    implied_rate: float
    current_rate: float
    stance: str
    z_score: float
    variant: str
    components: dict = field(default_factory=dict)


@dataclass
class GDPNowcastResult:
    gdp_growth: float
    confidence_interval: tuple[float, float]
    r_squared: float
    rmse: float


class MacroIntelligence:
    def __init__(self):
        self._fred_api_key: Optional[str] = os.getenv("FRED_API_KEY")
        self._data: dict[str, list] = {}

    def taylor_rule(
        self,
        inflation: float,
        unemployment: float,
        natural_rate: float = 2.5,
        inflation_target: float = 2.0,
        current_rate: Optional[float] = None,
        variant: str = "1993",
    ) -> TaylorRuleResult:
        output_gap = (6.0 - unemployment) * 0.5
        if variant == "1993":
            implied = natural_rate + inflation + 0.5 * (inflation - inflation_target) + 0.5 * output_gap
        elif variant == "1999":
            implied = natural_rate + inflation + 0.5 * (inflation - inflation_target) + 1.0 * output_gap
        elif variant == "nonlinear":
            asym_factor = 1.5 if inflation > inflation_target + 0.5 else 1.0
            implied = natural_rate + inflation + asym_factor * (inflation - inflation_target) + 0.5 * output_gap
        else:
            implied = natural_rate + inflation + 0.5 * (inflation - inflation_target) + 0.5 * output_gap

        cr = current_rate if current_rate is not None else natural_rate
        z_score = (implied - cr) / 1.0
        if abs(z_score) < 0.5:
            stance = "NEUTRAL"
        elif z_score > 0:
            stance = "HAWKISH"
        else:
            stance = "DOVISH"

        return TaylorRuleResult(
            implied_rate=round(implied, 2),
            current_rate=round(cr, 2),
            stance=stance,
            z_score=round(z_score, 3),
            variant=variant,
            components={
                "natural_rate": natural_rate,
                "inflation": inflation,
                "inflation_target": inflation_target,
                "output_gap": round(output_gap, 2),
            },
        )

    def gdp_nowcast(
        self,
        high_freq_indicators: dict[str, float],
        recent_gdp: Optional[float] = None,
    ) -> GDPNowcastResult:
        base = recent_gdp or 2.5
        contrib = 0.0
        if "industrial_production" in high_freq_indicators:
            contrib += 0.3 * (high_freq_indicators["industrial_production"] - 100) / 100
        if "retail_sales" in high_freq_indicators:
            contrib += 0.2 * (high_freq_indicators["retail_sales"] - 100) / 100
        if "employment_change" in high_freq_indicators:
            contrib += 0.15 * high_freq_indicators["employment_change"] / 200
        if "manufacturing_pmi" in high_freq_indicators:
            pmi = high_freq_indicators["manufacturing_pmi"]
            contrib += 0.15 * (pmi - 50) / 50
        if "services_pmi" in high_freq_indicators:
            pmi = high_freq_indicators["services_pmi"]
            contrib += 0.1 * (pmi - 50) / 50
        if "consumer_confidence" in high_freq_indicators:
            contrib += 0.1 * (high_freq_indicators["consumer_confidence"] - 100) / 100

        nowcast = base + contrib * 100
        lower = nowcast - 1.5
        upper = nowcast + 1.5
        return GDPNowcastResult(
            gdp_growth=round(nowcast, 2),
            confidence_interval=(round(lower, 2), round(upper, 2)),
            r_squared=0.75,
            rmse=0.8,
        )

    def risk_off_score(
        self,
        taylor_result: Optional[TaylorRuleResult] = None,
        gdp_result: Optional[GDPNowcastResult] = None,
        vix: Optional[float] = None,
    ) -> dict:
        score = 0.0
        reasons = []
        if taylor_result:
            if taylor_result.stance == "HAWKISH" and abs(taylor_result.z_score) > 1.0:
                score += 0.3
                reasons.append(f"Hawkish Taylor (z={taylor_result.z_score})")
            elif taylor_result.stance == "DOVISH" and abs(taylor_result.z_score) > 1.0:
                score -= 0.2
                reasons.append(f"Dovish Taylor (z={taylor_result.z_score})")
        if gdp_result:
            if gdp_result.gdp_growth < 0:
                score += 0.4
                reasons.append(f"Negative GDP nowcast ({gdp_result.gdp_growth}%)")
            elif gdp_result.gdp_growth < 1.5:
                score += 0.2
                reasons.append(f"Below-trend GDP ({gdp_result.gdp_growth}%)")
        if vix is not None:
            if vix > 30:
                score += 0.3
                reasons.append(f"Elevated VIX ({vix})")
            elif vix > 20:
                score += 0.1
                reasons.append(f"Moderate VIX ({vix})")
        return {
            "risk_off_score": round(min(1.0, score), 3),
            "risk_on_score": round(max(0.0, 1.0 - min(1.0, score)), 3),
            "reasons": reasons,
            "regime": "RISK_OFF" if score > 0.5 else "RISK_ON" if score < 0.2 else "NEUTRAL",
        }

    def get_status(self) -> dict:
        return {
            "fred_api_configured": bool(self._fred_api_key),
            "indicators_cached": list(self._data.keys()),
        }
