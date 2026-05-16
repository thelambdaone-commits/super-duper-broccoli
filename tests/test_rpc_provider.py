import os
from unittest.mock import patch
import pytest
from utils.rpc_provider import (
    get_rpc_url,
    resolve_rpc_with_fallback,
    get_all_configured_chains,
    FALLBACK_RPC_URLS
)

def test_get_rpc_url_from_env():
    with patch.dict(os.environ, {"POLYGON_RPC_URL": "http://polygon-env"}):
        assert get_rpc_url("polygon") == "http://polygon-env"

def test_get_rpc_url_case_insensitive():
    with patch.dict(os.environ, {"ETH_RPC_URL": "http://eth-env"}):
        assert get_rpc_url("ETH") == "http://eth-env"
        assert get_rpc_url("ethereum") == "http://eth-env"

def test_resolve_rpc_with_fallback_uses_env_first():
    with patch.dict(os.environ, {"BASE_RPC_URL": "http://base-env"}):
        assert resolve_rpc_with_fallback("base") == "http://base-env"

def test_resolve_rpc_with_fallback_uses_fallback_when_env_missing():
    with patch.dict(os.environ, {}, clear=True):
        # We need to ensure BASE_RPC_URL is not set in the real environment too if clear=True is not enough
        # Actually clear=True should be enough for os.environ
        fallback = FALLBACK_RPC_URLS["base"][0]
        assert resolve_rpc_with_fallback("base") == fallback

def test_get_all_configured_chains_labels():
    with patch.dict(os.environ, {"POLYGON_RPC_URL": "http://poly", "ETH_RPC_URL": "http://eth"}):
        chains = get_all_configured_chains()
        assert "Polygon (env)" in chains
        assert "ETH (env)" in chains

def test_get_all_configured_chains_fallback_labels():
    # Clear env to force fallback
    with patch.dict(os.environ, {}, clear=True):
        chains = get_all_configured_chains()
        assert "Polygon (fallback)" in chains
        assert "ETH (fallback)" in chains
        assert "Base (fallback)" in chains
