#!/bin/bash
# Stop continuous blockchain data fetching

set -e

PID_FILE="logs/continuous_fetch.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "✗ PID file not found: $PID_FILE"
    echo "  Process may not be running"
    exit 1
fi

PID=$(cat "$PID_FILE")

echo "Stopping continuous fetch process (PID: $PID)..."

if kill -0 "$PID" 2>/dev/null; then
    kill -SIGTERM "$PID"
    echo "✓ Stop signal sent, waiting for graceful shutdown..."

    # Wait up to 30 seconds for process to stop
    for i in {1..30}; do
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "✓ Process stopped successfully"
            rm -f "$PID_FILE"
            exit 0
        fi
        sleep 1
    done

    echo "⚠ Process did not stop gracefully, forcing..."
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
else
    echo "✗ Process not running"
    rm -f "$PID_FILE"
fi
