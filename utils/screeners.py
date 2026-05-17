import logging
from dataclasses import dataclass
from typing import Optional
from utils.polymarket_client import PolymarketClient, Market

logger = logging.getLogger("VCPScreener")


@dataclass
class VCPCandidate:
    market: Market
    vcp_score: float = 0.0
    contraction_pct: float = 0.0
    volume_trend: str = "STABLE"
    stage: int = 0


class VCPScreener:
    """
    Screen markets for Volatility Contraction Patterns (VCP) - Mark Minervini style.
    Finds markets where price has contracted significantly with declining volatility.
    """
    
    MIN_VOLUME = 5000
    MIN_LIQUIDITY = 2000
    
    def __init__(self, client: Optional[PolymarketClient] = None):
        self.client = client or PolymarketClient()
    
    def _score_contraction(self, market: Market) -> float:
        yes_price = market.yes_price
        no_price = market.no_price
        
        if yes_price == 0 or no_price == 0:
            return 0.0
        
        midpoint = (yes_price + no_price) / 2
        spread = abs(yes_price - no_price)
        
        if spread >= midpoint * 0.5:
            return 30.0
        
        contraction_pct = spread / midpoint * 100
        
        if contraction_pct < 5:
            return 90.0
        elif contraction_pct < 10:
            return 70.0
        elif contraction_pct < 20:
            return 50.0
        else:
            return 30.0
    
    def _score_liquidity(self, market: Market) -> float:
        if market.liquidity < self.MIN_LIQUIDITY:
            return 0.0
        if market.liquidity >= 50000:
            return 100.0
        return min(100.0, (market.liquidity / 50000) * 100)
    
    def _score_volume(self, market: Market) -> float:
        if market.volume < self.MIN_VOLUME:
            return 0.0
        if market.volume >= 100000:
            return 100.0
        return min(100.0, (market.volume / 100000) * 100)
    
    def _score_stage(self, market: Market) -> float:
        yes_price = market.yes_price
        
        if yes_price >= 0.80:
            return 40.0
        elif yes_price >= 0.40:
            return 100.0
        elif yes_price >= 0.20:
            return 70.0
        else:
            return 40.0
    
    def screen(self, limit: int = 20) -> list[VCPCandidate]:
        markets = self.client.list_markets(limit=limit * 2, sort_by="volume")
        
        candidates = []
        for market in markets:
            if not market.active or market.closed:
                continue
            
            if market.volume < self.MIN_VOLUME or market.liquidity < self.MIN_LIQUIDITY:
                continue
            
            contraction_score = self._score_contraction(market)
            liquidity_score = self._score_liquidity(market)
            volume_score = self._score_volume(market)
            stage_score = self._score_stage(market)
            
            total_score = (
                contraction_score * 0.40 +
                liquidity_score * 0.25 +
                volume_score * 0.20 +
                stage_score * 0.15
            )
            
            if total_score >= 40.0:
                candidate = VCPCandidate(
                    market=market,
                    vcp_score=total_score,
                    contraction_pct=abs(market.yes_price - market.no_price) / ((market.yes_price + market.no_price) / 2) * 100,
                    stage=2 if 0.30 <= market.yes_price <= 0.70 else 1,
                )
                candidates.append(candidate)
        
        candidates.sort(key=lambda x: x.vcp_score, reverse=True)
        return candidates[:limit]


class CANSLIMScreener:
    """
    Screen markets using William O'Neil's CANSLIM methodology.
    C=Current Earnings, A=Annual Earnings, N=New Products, S=Supply/Demand, L=Leader, I=Institutional, M=Market Direction
    """
    
    MIN_VOLUME = 10000
    
    def __init__(self, client: Optional[PolymarketClient] = None):
        self.client = client or PolymarketClient()
    
    def _score_current_earnings(self, market: Market) -> float:
        yes_price = market.yes_price
        if yes_price >= 0.70:
            return 90.0
        elif yes_price >= 0.50:
            return 70.0
        elif yes_price >= 0.30:
            return 50.0
        return 30.0
    
    def _score_annual_earnings(self, market: Market) -> float:
        if market.volume >= 100000:
            return 100.0
        elif market.volume >= 50000:
            return 70.0
        elif market.volume >= 20000:
            return 50.0
        return 30.0
    
    def _score_new_news(self, market: Market) -> float:
        question_lower = market.question.lower()
        new_keywords = ["launch", "announce", "release", "breakthrough", "deal", "partnership"]
        if any(kw in question_lower for kw in new_keywords):
            return 80.0
        return 50.0
    
    def _score_supply_demand(self, market: Market) -> float:
        if market.liquidity >= 50000:
            return 100.0
        elif market.liquidity >= 20000:
            return 70.0
        elif market.liquidity >= 10000:
            return 50.0
        return 30.0
    
    def _score_leader(self, market: Market) -> float:
        yes_price = market.yes_price
        if 0.60 <= yes_price <= 0.85:
            return 100.0
        elif 0.40 <= yes_price <= 0.90:
            return 70.0
        return 40.0
    
    def _score_institutional(self, market: Market) -> float:
        if market.volume >= 200000:
            return 90.0
        elif market.volume >= 50000:
            return 70.0
        return 50.0
    
    def _score_market_direction(self, market: Market) -> float:
        yes_price = market.yes_price
        if yes_price >= 0.50:
            return 70.0
        return 50.0
    
    def screen(self, limit: int = 20) -> list[dict]:
        markets = self.client.list_markets(limit=limit * 2, sort_by="volume")
        
        results = []
        for market in markets:
            if not market.active or market.closed:
                continue
            if market.volume < self.MIN_VOLUME:
                continue
            
            scores = {
                "C": self._score_current_earnings(market),
                "A": self._score_annual_earnings(market),
                "N": self._score_new_news(market),
                "S": self._score_supply_demand(market),
                "L": self._score_leader(market),
                "I": self._score_institutional(market),
                "M": self._score_market_direction(market),
            }
            
            total_score = sum(scores.values()) / len(scores)
            
            if total_score >= 50.0:
                results.append({
                    "market": market,
                    "total_score": total_score,
                    "canslim_scores": scores,
                    "avg_probability": market.yes_price * 100,
                })
        
        results.sort(key=lambda x: x["total_score"], reverse=True)
        return results[:limit]


def format_vcp_results(candidates: list[VCPCandidate]) -> str:
    if not candidates:
        return "❌ No VCP candidates found."
    
    lines = [
        "📊 *VCP SCREENER RESULTS* 📊",
        "────────────────────────",
    ]
    
    for i, c in enumerate(candidates[:10], 1):
        m = c.market
        stage_emoji = "📈" if c.stage == 2 else "📉"
        
        lines.extend([
            f"{i}. {stage_emoji} `{m.question[:45]}...`",
            f"   💰 Vol: `${m.volume:,.0f}` | Liq: `${m.liquidity:,.0f}`",
            f"   📈 Yes: `{m.yes_price:.1%}` | Contraction: `{c.contraction_pct:.1f}%`",
            f"   ⭐ VCP Score: `{c.vcp_score:.0f}/100` | Stage: `{c.stage}`",
            "",
        ])
    
    lines.append("────────────────────────")
    lines.append(f"Found {len(candidates)} VCP candidates")
    
    return "\n".join(lines)


def format_canslim_results(results: list[dict]) -> str:
    if not results:
        return "❌ No CANSLIM candidates found."
    
    lines = [
        "🎯 *CANSLIM SCREENER RESULTS* 🎯",
        "────────────────────────",
    ]
    
    for i, r in enumerate(results[:10], 1):
        m = r["market"]
        scores = r["canslim_scores"]
        
        score_bars = "".join([
            f"{k}:{int(v/10)}" for k, v in scores.items()
        ])
        
        lines.extend([
            f"{i}. *{m.question[:40]}...*",
            f"   💰 Vol: `${m.volume:,.0f}` | Prob: `{r['avg_probability']:.0f}%`",
            f"   📊 `{r['total_score']:.0f}/100` | {score_bars}",
            "",
        ])
    
    lines.append("────────────────────────")
    lines.append(f"Found {len(results)} CANSLIM candidates")
    
    return "\n".join(lines)