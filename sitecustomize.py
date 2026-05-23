from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if SRC_ROOT.exists():
    src_str = str(SRC_ROOT)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)

os.environ.setdefault("PROJECT_ROOT", str(PROJECT_ROOT))
os.environ.setdefault("CONFIG_PATH", str(PROJECT_ROOT / "configs" / "config"))
os.environ.setdefault("DATA_PATH", str(PROJECT_ROOT / "runtime" / "data"))
os.environ.setdefault("LOG_PATH", str(PROJECT_ROOT / "runtime" / "logs"))
os.environ.setdefault("RUNTIME_PATH", str(PROJECT_ROOT / "runtime"))
os.environ.setdefault("ARTIFACTS_PATH", str(PROJECT_ROOT / "artifacts"))
os.environ.setdefault("SECRETS_PATH", str(PROJECT_ROOT / "secrets"))
