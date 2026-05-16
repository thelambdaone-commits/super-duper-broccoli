from typing import Optional
from utils.feature_store import FeatureStore

def get_storage_tools(mcp, store: Optional[FeatureStore]):
    @mcp.tool(
        name="get_feature_store_stats",
        description="Returns row counts for each table in the DuckDB feature store.",
    )
    def get_feature_store_stats() -> dict:
        if store is None:
            return {"error": "FeatureStore not initialized"}
        return {
            "stats": store.get_stats(),
        }

    @mcp.tool(
        name="get_feature_history",
        description="Returns historical feature values for a given ticker and feature name.",
    )
    def get_feature_history(
        ticker: str,
        feature_name: str,
        since_timestamp: float = 0.0,
        limit: int = 100,
    ) -> dict:
        if store is None:
            return {"error": "FeatureStore not initialized"}
        features = store.get_feature_history(ticker, feature_name, since_timestamp, limit)
        return {
            "ticker": ticker,
            "feature": feature_name,
            "count": len(features),
            "samples": features[:limit],
        }
