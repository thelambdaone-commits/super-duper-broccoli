from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PMXT_DIR = PROJECT_ROOT / "scripts" / "pmxt_adapter"


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PMXT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_gamma_side_map_derives_yes_no_named_outcomes() -> None:
    gamma = _load_module("test_pmxt_gamma", "extend_side_map_gamma.py")

    result = gamma._derive_yes_no(
        {
            "outcomes": "[\"Yes\", \"No\"]",
            "clobTokenIds": "[\"tok_yes\", \"tok_no\"]",
        }
    )

    assert result == {"yes": "tok_yes", "no": "tok_no"}


def test_gamma_side_map_derives_yes_no_fallback_order() -> None:
    gamma = _load_module("test_pmxt_gamma_fallback", "extend_side_map_gamma.py")

    result = gamma._derive_yes_no(
        {
            "outcomes": "[\"Up\", \"Down\"]",
            "clobTokenIds": "[\"tok0\", \"tok1\"]",
        }
    )

    assert result == {"yes": "tok1", "no": "tok0"}


@pytest.mark.skipif(
    importlib.util.find_spec("polars") is None,
    reason="polars is not installed in the local test environment",
)
def test_v2_adapter_formats_numbers_like_v1() -> None:
    adapter = _load_module("test_pmxt_v2_adapter", "v2_to_v1_adapter.py")

    assert adapter._fmt_num("0.050000") == "0.05"
    assert adapter._fmt_num("42.600000") == "42.6"
    assert adapter._fmt_num(-0.0) == "0"
