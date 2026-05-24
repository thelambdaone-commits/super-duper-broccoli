def test_wallet_pnl_format_matches_plain_layout() -> None:
    wallet_name = "default"
    active_address = "0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E"
    proxy_address = "0xa005088ba69014581d6460db325627600887590b"
    usdc_direct = 0.0
    usdc_proxy = 16.74
    open_current_value = 0.0
    total_capital = 16.74
    total_trades = 5
    win_rate = 20.0
    total_realized_pnl = -2.90
    open_cash_pnl = 0.0
    closed_emoji = "🔴"
    closed_sign = ""

    lines = [
        "<b>🎯 Polymarket Cockpit</b>",
        "───────────────────",
        "💰 <b>PnL Metrics (Real-Time)</b>:",
        f"• Wallet: {wallet_name}",
        f"• EOA: {active_address}",
        f"• Proxy: {proxy_address}",
        "",
        f"• USDC Direct: {usdc_direct:.2f}",
        f"• Polymarket pUSD: {usdc_proxy:.2f}",
        f"• Open Value: ${open_current_value:.2f}",
        f"• Total Capital: <b>${total_capital:.2f}</b>",
        "───────────────────",
        "• Net Gain: N/A (reference missing)",
        f"• Trades: {total_trades} (WR: {win_rate:.1f}%)",
        f"• Realized: {closed_emoji} <b>{closed_sign}${total_realized_pnl:.2f}</b>",
        f"• Floating: <b>${open_cash_pnl:.2f}</b>",
        "───────────────────",
    ]

    text = "\n".join(lines)

    assert "• Wallet: default" in text
    assert "• EOA: 0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E" in text
    assert "• Net Gain: N/A (reference missing)" in text
    assert "<code>" not in text

