from pathlib import Path
import sys

# Ensure src/ is in the python path
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.main import main_sync

if __name__ == "__main__":
    main_sync()
