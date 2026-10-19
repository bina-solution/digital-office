import sys
from pathlib import Path

# Make ``import src...`` work the same way the gunicorn process does.
APITOOLS_ROOT = Path(__file__).resolve().parents[3]
if str(APITOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(APITOOLS_ROOT))
