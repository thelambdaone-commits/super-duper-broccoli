#!/bin/bash
# Clean and process raw on-chain data

set -e

echo "Processing on-chain data..."
python -m polymarket.cli process
echo "✓ Data processing completed"
