"""Inches, as the shop writes them."""
from __future__ import annotations


def inches(x) -> int | float:
    """An inch value without float noise (35.3 − 4 = 31.3, not 31.299999999999997); whole numbers as ints."""
    x = round(float(x), 3)
    return int(x) if x.is_integer() else x
