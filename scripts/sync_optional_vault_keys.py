#!/usr/bin/env python
"""Sync allowlisted optional provider keys from the environment into Vault."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.vault_handler import (
    OPTIONAL_SECRET_KEYS,
    VaultHandler,
    collect_optional_secrets_from_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch optional AI/provider keys from env into Vault without printing values."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which allowlisted keys would be patched, without writing to Vault.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    secrets = collect_optional_secrets_from_env()
    key_names = sorted(secrets)

    if args.dry_run:
        print({"available_env_keys": key_names, "allowlist": OPTIONAL_SECRET_KEYS})
        return 0

    if not secrets:
        print({"patched": [], "message": "No optional provider keys found in environment."})
        return 0

    patched = VaultHandler().patch_optional_secrets(secrets)
    print({"patched": patched})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
