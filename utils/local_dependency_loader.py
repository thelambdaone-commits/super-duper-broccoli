import importlib.util
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FREQTRADE_REPO_PATH = PROJECT_ROOT / "freqtrade"
DEFAULT_NLTK_DATA_PATH = PROJECT_ROOT / "data" / "nltk_data"


def ensure_local_freqtrade_available(repo_path: str | os.PathLike | None = None) -> bool:
    """Expose a local freqtrade checkout when freqtrade is not installed."""
    if importlib.util.find_spec("freqtrade") is not None:
        return True

    path = Path(repo_path or os.getenv("FREQTRADE_REPO_PATH", DEFAULT_FREQTRADE_REPO_PATH))
    package_marker = path / "freqtrade" / "__init__.py"
    if not package_marker.exists():
        return False

    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    return importlib.util.find_spec("freqtrade") is not None


def configure_nltk_data_path(data_path: str | os.PathLike | None = None) -> Path | None:
    """Register local nltk_data without requiring runtime downloads."""
    path = Path(data_path or os.getenv("NLTK_DATA", DEFAULT_NLTK_DATA_PATH))
    if not path.exists():
        return None

    current_paths = [p for p in os.getenv("NLTK_DATA", "").split(os.pathsep) if p]
    path_str = str(path)
    if path_str not in current_paths:
        os.environ["NLTK_DATA"] = os.pathsep.join([path_str, *current_paths])

    try:
        import nltk

        if path_str not in nltk.data.path:
            nltk.data.path.insert(0, path_str)
    except ImportError:
        pass
    return path
