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

# Force project-local runtime paths
CANONICAL_RUNTIME = PROJECT_ROOT / "runtime"
os.environ["RUNTIME_PATH"] = str(CANONICAL_RUNTIME)
os.environ["DATA_PATH"] = str(CANONICAL_RUNTIME / "database")
os.environ["LOG_PATH"] = str(CANONICAL_RUNTIME / "logs")
os.environ["ARTIFACTS_PATH"] = str(CANONICAL_RUNTIME / "artifacts")
os.environ["SECRETS_PATH"] = str(CANONICAL_RUNTIME / "secrets")
os.environ.setdefault("NLTK_DATA", str(CANONICAL_RUNTIME / "database" / "nltk_data"))
