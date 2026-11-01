#!/usr/bin/env python3
"""Local OCR engine validation entry point using the shared validation harness."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from lib.validate_feature_base import run_feature  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    feature_root = Path(__file__).resolve().parent
    return run_feature(feature_root, argv)


if __name__ == "__main__":
    sys.exit(main())
