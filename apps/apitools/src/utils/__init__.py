"""General utility helpers for apitools.

Currently contains:
	has_index(l, i): Safe Python-style index bounds check supporting negatives.
"""

from typing import Sequence, Any

def has_index(l: Sequence[Any], i: int) -> bool:
	"""Return True if index i is valid for sequence l.

	Supports Python negative indexing semantics.
	Valid indices in Python are: -len(l) <= i < len(l)

	Args:
		l: Any sequence implementing __len__.
		i: The index to validate.

	Returns:
		bool: True if i can be used to index l without raising IndexError.
	"""
	n = len(l)
	return -n <= i < n

__all__ = ["has_index"]

