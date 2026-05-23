#!/bin/bash
# Full update: fetch markets, on-chain data, and process

set -e

echo "=== Full Update Pipeline ==="
echo ""

echo "[1/3] Fetching market data..."
python -m polymarket.cli fetch-markets
echo ""

echo "[2/3] Fetching on-chain data..."
python -m polymarket.cli fetch-onchain --continue
echo ""

echo "[3/3] Processing data..."
python -m polymarket.cli process
echo ""

echo "✓ Full update completed"
