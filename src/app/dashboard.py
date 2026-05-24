import os
import sys
from datetime import datetime
from typing import Any

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from database.ledger_db import Ledger
from utils.feature_store import FeatureStore
from services.portfolio_risk_engine import PortfolioRiskEngine
from strategies.hmm_filter import HMMRegimeFilter
from strategies.arbitrage_scanner import ArbitrageScanner
from strategies.sentiment_nlp import SentimentAnalyzer
st.set_page_config(
    page_title="Quant Agentic Trading",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 Quant Agentic Trading Core — Dashboard")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


@st.cache_resource
def init_components() -> dict[str, Any]:
    ledger = Ledger()
    store = FeatureStore()
    hmm = HMMRegimeFilter()
    risk = PortfolioRiskEngine(ledger=ledger, hmm_filter=hmm)
    arb = ArbitrageScanner()
    sentiment = SentimentAnalyzer()
    return {
        "ledger": ledger,
        "store": store,
        "hmm": hmm,
        "risk": risk,
        "arb": arb,
        "sentiment": sentiment,
    }


comps = init_components()
ledger: Ledger = comps["ledger"]
store: FeatureStore = comps["store"]
hmm: HMMRegimeFilter = comps["hmm"]
risk: PortfolioRiskEngine = comps["risk"]
arb: ArbitrageScanner = comps["arb"]
sentiment: SentimentAnalyzer = comps["sentiment"]


col1, col2, col3, col4 = st.columns(4)

with col1:
    cap = ledger.get_capital_summary()
    total = cap.get("total_capital", 0)
    avail = cap.get("available_capital", 0)
    pct = cap.get("allocated_pct", 0)
    st.metric("Total Capital", f"${total:,.0f}", help="Total capital allocated")
    st.metric("Available", f"${avail:,.0f}", delta=f"{((avail/total)-1)*100:.1f}%" if total > 0 else None)

with col2:
    mode = ledger.get_execution_mode()
    st.metric("Execution Mode", mode)
    open_positions = ledger.get_open_positions()
    st.metric("Open Positions", len(open_positions))

with col3:
    net_beta = risk.net_beta_exposure_pct
    st.metric("Net Beta Exposure", f"{net_beta:.1f}%")
    try:
        import numpy as np
        _, regime_label = hmm.predict_with_label(np.zeros(100, dtype=np.float32))
    except Exception:
        regime_label = "UNKNOWN"
    st.metric("Market Regime", regime_label)

with col4:
    try:
        stats = store.get_stats()
        total_rows = sum(stats.values())
        st.metric("Feature Store Rows", f"{total_rows:,}")
    except Exception:
        st.metric("Feature Store", "N/A")


st.subheader("📈 Performance Summary")
perf_col1, perf_col2, perf_col3, perf_col4 = st.columns(4)
try:
    summary = ledger.get_performance_summary(mode=mode)
    if summary and summary.get("total_trades", 0) > 0:
        with perf_col1:
            st.metric("Total Trades", summary["total_trades"])
            st.metric("Win Rate", f"{summary['win_rate'] * 100:.1f}%")
        with perf_col2:
            st.metric("Net PnL", f"${summary['total_net_pnl']:.2f}")
            st.metric("Profit Factor", f"{summary['profit_factor']:.2f}")
        with perf_col3:
            st.metric("Avg Win", f"${summary['avg_win']:.2f}")
            st.metric("Avg Loss", f"${summary['avg_loss']:.2f}")
        with perf_col4:
            st.metric("Wins", summary["winning_trades"])
            st.metric("Losses", summary["losing_trades"])
    else:
        st.info("No performance data yet. Close some paper trades to see metrics.")
except Exception as e:
    st.warning(f"Performance data unavailable: {e}")

st.subheader("📋 Closed Positions")
try:
    closed = ledger.get_paper_positions(status="CLOSED")[:20]
    if closed:
        df_closed = pd.DataFrame(closed)
        st.dataframe(df_closed, use_container_width=True)
    else:
        st.info("No closed positions yet")
except Exception as e:
    st.warning(f"Cannot load closed positions: {e}")

st.subheader("Open Positions")
positions = ledger.get_open_positions()
if positions:
    df = pd.DataFrame(positions)
    st.dataframe(df, use_container_width=True)
else:
    st.info("No open positions")


st.subheader("Feature Store Stats")
try:
    stats = store.get_stats()
    fs_df = pd.DataFrame([
        {"Table": k, "Rows": v} for k, v in stats.items()
    ])
    st.dataframe(fs_df, use_container_width=True)
except Exception as e:
    st.warning(f"Cannot read feature store: {e}")


st.subheader("🧪 Sentiment Analyzer")
sentiment_text = st.text_area("Enter text for sentiment analysis:", height=80)
if sentiment_text:
    result = sentiment.analyze(sentiment_text)
    score = result["score"]
    label = "🟢 Bullish" if score > 0.05 else ("🔴 Bearish" if score < -0.05 else "⚪ Neutral")
    st.metric("Sentiment", label, delta=f"{score:+.4f}")
    cols = st.columns(3)
    with cols[0]:
        st.metric("Score", f"{result['score']:+.4f}")
    with cols[1]:
        st.metric("Magnitude", f"{result['magnitude']:.4f}")
    with cols[2]:
        st.metric("Confidence", f"{result['confidence']:.2f}")
    if result["matches"]:
        st.caption(f"Keywords matched: {', '.join(result['matches'])}")


st.subheader("🔎 Arbitrage Scanner")
arb_type = st.selectbox("Scan type", ["mispricing_ipv", "sum_inefficiency", "conditional_overpricing"])
if st.button("Run Scan", type="primary"):
    with st.spinner("Scanning..."):
        if arb_type == "mispricing_ipv":
            for _ in range(30):
                arb.record_price("SOL", 0.50 + np.random.randn() * 0.02)
            opps = arb.scan_mispricing({"SOL": 0.55})
        elif arb_type == "sum_inefficiency":
            opps = arb.scan_sum_inefficiency({"MKT": {"YES": 0.52, "NO": 0.52}})
        else:
            opps = arb.scan_conditional_overpricing("parent", 0.50, {"YES": 0.55, "NO": 0.45})
    if opps:
        st.success(f"Found {len(opps)} opportunity(ies)")
        st.json(opps)
    else:
        st.info("No opportunities found")


st.subheader("⚙️ Execution Controls")
mode_col, breaker_col = st.columns(2)
with mode_col:
    new_mode = st.selectbox(
        "Change execution mode",
        ["REPLAY", "PAPER", "SHADOW", "PROD"],
        index=["REPLAY", "PAPER", "SHADOW", "PROD"].index(mode) if mode in ["REPLAY", "PAPER", "SHADOW", "PROD"] else 1,
    )
    if st.button("Apply Mode"):
        try:
            ledger.set_execution_mode(new_mode)
            st.success(f"Mode changed to {new_mode}")
            st.rerun()
        except Exception as e:
            st.error(str(e))

with breaker_col:
    st.metric("Circuit Breaker", "DISENGAGED" if risk is not None else "N/A")
    st.caption("Use MCP or API to toggle")
