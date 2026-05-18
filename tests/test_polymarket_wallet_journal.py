import json

import pytest

from utils.polymarket_wallet_journal import PolymarketWalletJournal, WalletIdentity


def test_wallet_journal_builds_precise_snapshot(tmp_path) -> None:
    journal = PolymarketWalletJournal(tmp_path / "wallet.jsonl")
    identity = WalletIdentity(
        chat_id="7413500821",
        wallet_name="import",
        eoa_address="0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E",
        proxy_address="0xa005088ba69014581d6460db325627600887590b",
    )

    snapshot = journal.build_snapshot(
        identity,
        positions=[{"currentValue": 2.5, "cashPnl": 0.4, "title": "Open", "asset": "a"}],
        closed_positions=[
            {"realizedPnl": 1.25, "title": "Win", "asset": "b"},
            {"realizedPnl": -0.5, "title": "Loss", "asset": "c"},
        ],
        activity=[
            {"usdcSize": 1.2, "timestamp": 10, "side": "BUY"},
            {"size": 2, "price": 0.5, "timestamp": 20, "side": "SELL"},
        ],
        value_rows=[{"value": 2.5}],
        balances={"usdc_direct": 10, "usdc_proxy": 6.74, "eth_balance": 19.9},
    )

    assert snapshot["wallet"]["data_user"] == "0xa005088ba69014581d6460db325627600887590b"
    assert snapshot["balances"]["total_capital"] == pytest.approx(19.24)
    assert snapshot["pnl"]["closed_realized"] == 0.75
    assert snapshot["pnl"]["closed_wins"] == 1
    assert snapshot["pnl"]["closed_losses"] == 1
    assert snapshot["flow"]["trade_volume_usdc"] == 2.2


def test_wallet_journal_appends_jsonl_and_reads_latest(tmp_path) -> None:
    path = tmp_path / "wallet.jsonl"
    journal = PolymarketWalletJournal(path)

    journal.append({"schema_version": 1, "seq": 1})
    journal.append({"schema_version": 1, "seq": 2})

    lines = path.read_text().splitlines()
    assert [json.loads(line)["seq"] for line in lines] == [1, 2]
    assert journal.latest()["seq"] == 2


def test_wallet_journal_records_balance_errors(tmp_path) -> None:
    journal = PolymarketWalletJournal(tmp_path / "wallet.jsonl")
    snapshot = journal.build_snapshot(
        WalletIdentity(eoa_address="0xabc"),
        positions=[],
        closed_positions=[],
        activity=[],
        value_rows=[],
        balances={"error": "TimeoutError"},
    )

    assert snapshot["errors"] == [{"component": "balances", "error": "TimeoutError"}]
