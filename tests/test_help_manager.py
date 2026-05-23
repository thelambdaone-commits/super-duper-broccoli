from utils.help_manager import HelpManager


def test_trading_manual_mentions_btc_launch_commands() -> None:
    content = HelpManager.PAGES[3]["content"]

    assert "/btc5" in content
    assert "/btc15" in content
    assert "/launchbtc5up" in content
    assert "/launchbtc15down" in content
    assert "/crypto" in content
