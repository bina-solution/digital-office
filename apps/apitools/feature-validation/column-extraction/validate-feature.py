#!/usr/bin/env python3
"""Column extraction feature validation runner."""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.validate_feature_base import run_feature

if __name__ == "__main__":
    raise SystemExit(run_feature(Path(__file__).parent))
