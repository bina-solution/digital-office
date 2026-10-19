from decimal import Decimal

import pytest

from incoming_documents.core.types import (
    LogicalType,
    normalize_value,
    values_equal,
)


@pytest.mark.parametrize(
    "type_,a,b,equal",
    [
        (LogicalType.INT, "42", 42, True),
        (LogicalType.INT, "42.0", 42, True),
        (LogicalType.INT, "x", "x", True),               # unparseable falls back to ==
        (LogicalType.INT, "1", "2", False),
        (LogicalType.NUMERIC, "1.50", Decimal("1.5"), True),
        (LogicalType.NUMERIC, 0.1, "0.1", True),
        (LogicalType.BOOL, "TRUE", True, True),
        (LogicalType.BOOL, "no", False, True),
        (LogicalType.BOOL, "1", True, True),
        (LogicalType.STRING, 42, "42", True),
        (LogicalType.DATE, "2025-01-02", "2025-01-02T00:00:00Z", True),
        (LogicalType.TIMESTAMP, "2025-01-02T00:00:00+00:00", "2025-01-02T00:00:00Z", True),
        (LogicalType.JSON, {"a": 1}, {"a": 1}, True),
        (LogicalType.JSON, {"a": 1}, {"a": 2}, False),
    ],
)
def test_values_equal(type_, a, b, equal):
    assert values_equal(a, b, type_) is equal


def test_normalize_none_preserved():
    for t in LogicalType:
        assert normalize_value(None, t) is None
