#!/usr/bin/env python3
from __future__ import annotations

import argparse

from utils.env_validation import validate_runtime_env
from utils.exceptions import QuantFatal
from utils.vault_handler import VaultHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate runtime environment for the trading bot.")
    parser.add_argument("--mode", default="PAPER", help="Execution mode to validate: PAPER, SHADOW, PROD")
    args = parser.parse_args()

    secrets = VaultHandler().fetch_quantum_secrets()
    validate_runtime_env(args.mode, secrets)
    print(f"Environment OK for {args.mode.upper()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QuantFatal as exc:
        print(f"Environment validation failed: {exc}")
        raise SystemExit(1)
