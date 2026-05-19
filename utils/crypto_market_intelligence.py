from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from utils.polymarket_client import Market


DEFAULT_CRYPTO_KEYWORDS = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum", "ether"),
    "SOL": ("sol", "solana"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("doge", "dogecoin"),
    "HYPE": ("hype", "hyperliquid"),
    "BNB": ("bnb", "binance coin"),
    "CRYPTO": ("crypto", "cryptocurrency", "blockchain", "coinbase", "binance"),
}


@dataclass
class IntelligenceSignal:
    market_slug: str
    question: str
    asset: str
    signal_type: str
    direction: str
    score: float
    confidence: float
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    rationale: list[str] = field(default_factory=list)


@dataclass
class IntelligenceReport:
    generated_at: str
    source: str
    market_count: int
    crypto_market_count: int
    opportunities: list[IntelligenceSignal] = field(default_factory=list)
    risk_flags: list[IntelligenceSignal] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)
    summary: dict[str, float | int | str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "source": self.source,
            "market_count": self.market_count,
            "crypto_market_count": self.crypto_market_count,
            "opportunities": [asdict(signal) for signal in self.opportunities],
            "risk_flags": [asdict(signal) for signal in self.risk_flags],
            "watchlist": self.watchlist,
            "summary": self.summary,
        }


class CryptoMarketIntelligence:
    """
    Python adaptation of a market-intelligence platform for crypto prediction markets.

    It is advisory only: it ranks and explains crypto-related market situations, but
    does not execute trades. Execution remains behind parser, risk, ledger, and mode
    checks.
    """

    def __init__(
        self,
        watchlist: Iterable[str] = ("BTC", "ETH", "SOL"),
        min_volume: float = 10_000.0,
        min_liquidity: float = 1_000.0,
    ) -> None:
        self.watchlist = [item.upper() for item in watchlist]
        self.min_volume = min_volume
        self.min_liquidity = min_liquidity

    def analyze(self, markets: list[Market], source: str = "polymarket_gamma") -> IntelligenceReport:
        crypto_markets = [
            market
            for market in markets
            if self._classify_asset(market) != "OTHER"
            and not self._is_noise_market(market)
        ]
        signals = [self._score_market(market) for market in crypto_markets]
        signals = [signal for signal in signals if signal is not None]
        signals.sort(key=lambda signal: signal.score, reverse=True)

        # Deduplicate signals by asset to prevent spam/clutter
        seen_opps = set()
        opportunities = []
        for signal in signals:
            if signal.signal_type in {"momentum", "mispricing", "liquidity_focus"}:
                # Limit to 2 opportunities per asset to avoid spam
                key = (signal.asset, signal.signal_type)
                opp_count = sum(1 for s in opportunities if s.asset == signal.asset)
                if key not in seen_opps and opp_count < 2:
                    opportunities.append(signal)
                    seen_opps.add(key)
        opportunities = opportunities[:5]

        seen_risks = set()
        risk_flags = []
        for signal in signals:
            if signal.signal_type in {"thin_liquidity", "crowded_probability"}:
                # Limit to 2 risks per asset to avoid spam
                key = (signal.asset, signal.signal_type)
                risk_count = sum(1 for s in risk_flags if s.asset == signal.asset)
                if key not in seen_risks and risk_count < 2:
                    risk_flags.append(signal)
                    seen_risks.add(key)
        risk_flags = risk_flags[:5]

        avg_confidence = (
            sum(signal.confidence for signal in signals) / len(signals)
            if signals else 0.0
        )
        total_volume = sum(market.volume for market in crypto_markets)
        total_liquidity = sum(market.liquidity for market in crypto_markets)

        return IntelligenceReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source=source,
            market_count=len(markets),
            crypto_market_count=len(crypto_markets),
            opportunities=opportunities,
            risk_flags=risk_flags,
            watchlist=self.watchlist,
            summary={
                "total_crypto_volume": round(total_volume, 2),
                "total_crypto_liquidity": round(total_liquidity, 2),
                "avg_signal_confidence": round(avg_confidence, 4),
                "opportunity_count": len(opportunities),
                "risk_flag_count": len(risk_flags),
            },
        )

    def _score_market(self, market: Market) -> IntelligenceSignal | None:
        asset = self._classify_asset(market)
        if asset == "OTHER":
            return None

        rationale: list[str] = []
        liquidity_score = self._bounded_log_score(market.liquidity, self.min_liquidity)
        volume_score = self._bounded_log_score(market.volume, self.min_volume)
        probability = market.yes_price
        conviction = abs(probability - 0.5) * 2
        spread = abs(market.yes_price - market.no_price)

        if market.volume >= self.min_volume:
            rationale.append(f"volume ${market.volume:,.0f} au-dessus du seuil crypto")
        if market.liquidity >= self.min_liquidity:
            rationale.append(f"liquidite ${market.liquidity:,.0f} suffisante pour surveillance")
        if asset in self.watchlist:
            rationale.append(f"{asset} est dans la watchlist")

        if market.liquidity < self.min_liquidity:
            signal_type = "thin_liquidity"
            direction = "AVOID"
            score = 0.35 + volume_score * 0.25
            rationale.append("liquidite trop faible, probabilite potentiellement deformee")
        elif conviction >= 0.8:
            signal_type = "crowded_probability"
            direction = "WATCH_REVERSAL"
            score = 0.45 + conviction * 0.35 + volume_score * 0.2
            rationale.append("probabilite proche d'un extreme, risque de retournement")
        elif 0.35 <= probability <= 0.65 and market.volume >= self.min_volume:
            signal_type = "liquidity_focus"
            direction = "MONITOR"
            score = 0.45 + liquidity_score * 0.3 + volume_score * 0.25
            rationale.append("probabilite equilibree avec activite exploitable")
        elif spread > 0.15:
            signal_type = "mispricing"
            direction = "REVIEW_BOOK"
            score = 0.50 + min(spread, 0.5) * 0.5
            rationale.append(f"spread YES/NO large {spread:.2f}, carnet a verifier")
        else:
            signal_type = "momentum"
            direction = "BULLISH" if probability > 0.5 else "BEARISH"
            score = 0.4 + conviction * 0.3 + volume_score * 0.2 + liquidity_score * 0.1
            rationale.append("probabilite directionnelle avec activite suffisante")

        confidence = min(max(score, 0.0), 0.99)
        return IntelligenceSignal(
            market_slug=market.slug,
            question=market.question,
            asset=asset,
            signal_type=signal_type,
            direction=direction,
            score=round(score, 4),
            confidence=round(confidence, 4),
            yes_price=round(market.yes_price, 4),
            no_price=round(market.no_price, 4),
            volume=round(market.volume, 2),
            liquidity=round(market.liquidity, 2),
            rationale=rationale[:5],
        )

    def _classify_asset(self, market: Market) -> str:
        text = " ".join([market.slug, market.question, market.description]).lower()
        for asset, keywords in DEFAULT_CRYPTO_KEYWORDS.items():
            if any(self._contains_keyword(text, keyword) for keyword in keywords):
                return asset
        return "OTHER"

    @staticmethod
    def _is_noise_market(market: Market) -> bool:
        text = f"{market.slug} {market.question}".lower()
        noise_markers = ("dev vs", "test", "dummy", "example", "sandbox")
        return any(marker in text for marker in noise_markers)

    @staticmethod
    def _bounded_log_score(value: float, baseline: float) -> float:
        if value <= 0 or baseline <= 0:
            return 0.0
        return min(math.log1p(value) / math.log1p(baseline * 20), 1.0)

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        escaped = re.escape(keyword.lower())
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None


def format_intelligence_report(report: IntelligenceReport) -> str:
    data = report.to_dict()
    summary = data["summary"]
    avg_confidence = float(summary.get("avg_signal_confidence", 0.0))
    bias = _report_bias(report)
    
    bias_emoji = {"BULLISH": "📈 BULLISH", "BEARISH": "📉 BEARISH", "NEUTRAL": "⚖️ NEUTRE", "NEUTRE": "⚖️ NEUTRE"}.get(bias, bias)
    
    vol = summary['total_crypto_volume']
    liq = summary['total_crypto_liquidity']
    
    vol_str = f"${vol/1_000_000:.2f}M" if vol >= 1_000_000 else f"${vol/1_000:.1f}K" if vol >= 1_000 else f"${vol:.0f}"
    liq_str = f"${liq/1_000_000:.2f}M" if liq >= 1_000_000 else f"${liq/1_000:.1f}K" if liq >= 1_000 else f"${liq:.0f}"

    lines = [
        "🤖 Lobstar Crypto Intelligence",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  Biais marché: {bias_emoji} | Confiance {avg_confidence:.0%}",
        f"  Couverture: {data['crypto_market_count']} crypto / {data['market_count']} marchés",
        f"  Flux: {vol_str} Volume | {liq_str} Liquidité",
        "",
        "🔍 OPPORTUNITÉS À SURVEILLER"
    ]

    if report.opportunities:
        for signal in report.opportunities[:4]:
            reason = _signal_reason(signal)
            slug = signal.market_slug
            lines.append(
                f" • [{signal.asset}] {slug}\n"
                f"   └─ YES {signal.yes_price:.0%} / NO {signal.no_price:.0%} | Score: {signal.score:.0%} ({reason})"
            )
    else:
        lines.append(" • Aucun signal liquide prioritaire")

    if report.risk_flags:
        lines.extend(["", "⚠️ VECTEURS DE RISQUE"])
        for signal in report.risk_flags[:4]:
            reason = _signal_reason(signal)
            slug = signal.market_slug
            lines.append(
                f" • [{signal.asset}] {slug}\n"
                f"   └─ Conf: {signal.confidence:.0%} ({reason})"
            )

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "  Commandes rapides: /btc5 /btc15 /btc1h | /eth5 /sol15 /xrp1h | /hype5 /doge5 /bnb5",
        "  Avis consultatif. Pas d'exécution sans parser, risque, ledger et mode valide."
    ])
    return "\n".join(lines)


def _report_bias(report: IntelligenceReport) -> str:
    directional = [
        signal.direction
        for signal in report.opportunities
        if signal.direction in {"BULLISH", "BEARISH"}
    ]
    if not directional:
        return "NEUTRE"
    bullish = sum(1 for direction in directional if direction == "BULLISH")
    bearish = len(directional) - bullish
    if bullish > bearish:
        return "BULLISH"
    if bearish > bullish:
        return "BEARISH"
    return "NEUTRE"


def _direction_label(direction: str) -> str:
    return {
        "BULLISH": "biais haussier 📈",
        "BEARISH": "biais baissier 📉",
        "MONITOR": "zone liquide 🔍",
        "REVIEW_BOOK": "book à vérifier 📚",
        "WATCH_REVERSAL": "surveiller retournement 🔄",
        "AVOID": "éviter 🚫",
    }.get(direction, direction.lower())


def _risk_label(signal_type: str) -> str:
    return {
        "crowded_probability": "probabilité surchargée ⚠️",
        "thin_liquidity": "liquidité faible 🚨",
        "mispricing": "spread anormal ⚖️",
        "liquidity_focus": "zone liquide 🔍",
        "momentum": "momentum ⚡",
    }.get(signal_type, signal_type.replace("_", " "))


def _signal_reason(signal: IntelligenceSignal) -> str:
    if signal.rationale:
        return signal.rationale[-1].rstrip(".")
    if signal.signal_type == "crowded_probability":
        return "probabilite proche d'un extreme, attention au retournement"
    if signal.signal_type == "thin_liquidity":
        return "carnet trop fin pour une lecture robuste"
    return "probabilite et liquidite surveillables"


def report_to_json(report: IntelligenceReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=True)
