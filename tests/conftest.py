import os
import sys

# Ensure repository root and src/ are in python path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_root = os.path.join(repo_root, "src")
sys.path.insert(0, repo_root)
sys.path.insert(0, src_root)

from utils.localization_sync import apply_backward_compatible_aliases

# Ensure tests run in PAPER mode by default
os.environ["EXECUTION_MODE"] = "PAPER"
os.environ["REAL"] = "false"
os.environ["PAPER"] = "true"
os.environ["AUTONOMOUS_FORCE_PROD"] = "false"
os.environ["FORCE_PROD"] = "false"

# Apply backward-compatible French quantitative hook aliases
apply_backward_compatible_aliases()
