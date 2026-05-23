#!/bin/bash
# Fetch market metadata from Gamma API

set -e

echo "Fetching market data from Gamma API..."
python -m polymarket.cli fetch-markets
echo "✓ Market data fetched successfully"
