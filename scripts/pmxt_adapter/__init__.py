"""PMXT archive compatibility tools vendored into the main repo.

This package intentionally stays isolated from the live trading runtime.
It is for offline archive conversion and replay preparation only.
"""

from pathlib import Path


PMXT_ADAPTER_DIR = Path(__file__).resolve().parent

