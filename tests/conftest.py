import os
import sys

# Ensure repository root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.localization_sync import apply_backward_compatible_aliases

# Apply backward-compatible French quantitative hook aliases
apply_backward_compatible_aliases()
