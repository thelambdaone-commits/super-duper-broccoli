from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for candidate in (str(ROOT), str(SRC)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.main_agentic_clob import *  # noqa: F403
from src.main_agentic_clob import main_sync


if __name__ == "__main__":
    main_sync()
