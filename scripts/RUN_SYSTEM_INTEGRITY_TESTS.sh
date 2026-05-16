#!/bin/bash
# System Integrity Test Suite - Execution Script
# Runs comprehensive end-to-end integration tests for all 10 architectural layers

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_FILE="${PROJECT_ROOT}/tests/test_system_integrity.py"

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                                                                        ║"
echo "║     QUANT-AGENTIC-TRADING-CORE: SYSTEM INTEGRITY TEST SUITE            ║"
echo "║                                                                        ║"
echo "║  Verifying all 10 architectural layers operate in sandbox environment  ║"
echo "║                                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

cd "${PROJECT_ROOT}"

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}[TEST SUITE DETAILS]${NC}"
echo "  Test File:      $TEST_FILE"
echo "  Tests Total:    19"
echo "  Test Classes:   10 (one per architectural layer)"
echo "  Framework:      pytest + pytest-asyncio"
echo "  Python Version: $(python3 --version)"
echo ""

echo -e "${BLUE}[EXECUTION MODE 1: FULL VERBOSE OUTPUT]${NC}"
echo "Running with complete logging and assertions..."
echo ""

python3 -m pytest "${TEST_FILE}" -v --tb=short -s 2>&1 | tee test_integrity_output.log

echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                     TEST EXECUTION COMPLETE                           ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Extract summary
PASSED=$(grep -c "PASSED" test_integrity_output.log || true)
FAILED=$(grep -c "FAILED" test_integrity_output.log || true)
ERRORS=$(grep -c "ERROR" test_integrity_output.log || true)

if [ "$FAILED" -eq 0 ] && [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}✓ ALL TESTS PASSED${NC}"
    echo "  Passed: $PASSED"
    exit 0
else
    echo -e "${YELLOW}✗ SOME TESTS FAILED${NC}"
    echo "  Passed: $PASSED"
    echo "  Failed: $FAILED"
    echo "  Errors: $ERRORS"
    exit 1
fi
