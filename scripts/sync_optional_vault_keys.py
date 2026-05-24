#!/usr/bin/env python
"""List optional provider keys available in the environment."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.vault_handler import (
    OPTIONAL_SECRET_KEYS,
    collect_optional_secrets_from_env,
)


def main() -> int:
    secrets = collect_optional_secrets_from_env()
    key_names = sorted(secrets)
    print({"available_env_keys": key_names, "allowlist": OPTIONAL_SECRET_KEYS})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
