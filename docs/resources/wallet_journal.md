# Wallet Journal

`data/wallet.jsonl` is the append-only Polymarket wallet journal. It is built for fast reconciliation against the UI without storing private keys, API credentials, or Telegram bot tokens.

## Command

```bash
.venv/bin/python scripts/track_polymarket_wallet.py --chat-id 7413500821
```

Useful options:

- `--output data/wallet.jsonl` writes to the default journal path.
- `--print` prints the full snapshot after appending it.

## Snapshot Shape

Each line is a standalone JSON object. The current schema records:

- `wallet`: chat id, wallet label, EOA, proxy wallet, and the Data API user address.
- `balances`: direct USDC, Polymarket pUSD, open positions value, POL gas, and total capital.
- `pnl`: closed realized PnL, open cash PnL, wins, losses, and closed win rate.
- `counts`: number of open positions, closed positions, and recent trade activity rows.
- `flow`: recent trade volume in USDC and latest activity timestamp.
- `samples`: compact open position, closed position, and trade activity rows for quick inspection.
- `sources`: Polymarket Data API endpoints used to build the snapshot.
- `errors`: optional non-fatal collection errors, for example an RPC balance timeout.

## Data Sources

The journal reconciles Polymarket using the proxy wallet where available:

- Current positions: `https://data-api.polymarket.com/positions`
- Closed positions: `https://data-api.polymarket.com/closed-positions`
- Trade activity: `https://data-api.polymarket.com/activity`
- Portfolio value: `https://data-api.polymarket.com/value`

On-chain balances are fetched through `PolymarketWalletManager.recuperer_soldes_on_chain`, then merged with Data API positions. This separates net capital tracking from closed-trade PnL, which avoids confusing UI capital changes with realized trade-only PnL.

## Quick Checks

Pretty-print the latest snapshot:

```bash
tail -1 data/wallet.jsonl | .venv/bin/python -m json.tool
```

Read only the headline metrics:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

line = next(line for line in reversed(Path("data/wallet.jsonl").read_text().splitlines()) if line.strip())
snapshot = json.loads(line)
print({
    "wallet": snapshot["wallet"]["data_user"],
    "total_capital": snapshot["balances"]["total_capital"],
    "closed_realized": snapshot["pnl"]["closed_realized"],
    "open_positions": snapshot["counts"]["open_positions"],
    "activity": snapshot["counts"]["activity"],
})
PY
```
