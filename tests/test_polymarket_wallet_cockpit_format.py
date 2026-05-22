from core.wallet_manager import PolymarketWalletManager


def test_wallet_cockpit_layout_is_telegram_html_and_escapes_values() -> None:
    manager = PolymarketWalletManager(vault_handler=None, polygon_rpc_url="")

    text, _ = manager.generer_layout_telegram(
        wallet_name="default <prod>",
        wallet_address="0xabc&def",
        proxy_address="0xproxy<bad>",
        soldes={"usdc_direct": 10.0, "usdc_proxy": 6.74, "eth_balance": 19.9692},
        total_connections=1,
    )

    assert "<b>🎯 Polymarket Cockpit</b>" in text
    assert "<code>default &lt;prod&gt;</code>" in text
    assert "<code>0xabc&amp;def</code>" in text
    assert "<code>0xproxy&lt;bad&gt;</code>" in text
    assert "💰 <b>Total Cap</b>: <b>16.74 $</b>" in text
    assert "*Polymarket Cockpit*" not in text
