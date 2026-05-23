#!/bin/bash
# Fetch on-chain data from Polygon RPC

set -e

# Default: fetch last 1000 blocks
BLOCKS=${1:-1000}

echo "Fetching on-chain data (last $BLOCKS blocks)..."
python -m polymarket.cli fetch-onchain --blocks "$BLOCKS"
echo "✓ On-chain data fetched successfully"
