"""`month_key_of` and `month_key_regex` must be the SAME rule.

Month navigation counts with the first (in Python, in the month-index endpoint) and
filters with the second (in the database, via the `month` query operator). The bug
this file exists to prevent is the two drifting apart: before `core.month_key`, the
index bucketed `D/M/YY(YY)` dates and the filter sent a raw `startswith 'YYYY-MM'`
prefix, so on the live corpus a chip advertising 38 documents opened onto 3.

The equivalence is checked with Python's own regex engine, which is not the engine
that will evaluate it — Postgres is. That is why `month_key_regex` is written
ASCII-only and without `{n,m}` bounds: the subset both engines agree on. The
end-to-end check against Postgres over the live corpus lives outside pytest (it needs
a stack); this locks the rule itself.
"""
import re

import pytest

from incoming_documents.core.month_key import month_key_of, month_key_regex

# Shapes taken from the live corpus plus every boundary the rule names.
SAMPLES = [
    # ISO, prefix semantics
    "2026-10-05", "2026-10", "2026-10-05T11:22:33Z", "2026-01-01 00:00:00+00",
    "1990-01-31", "2100-12-01",
    # ISO, out of range -> no date (and NOT retried as D/M/Y)
    "2026-13-01", "2026-00-01", "1989-12-31", "2101-01-01",
    # D/M/Y, both separators, 1- and 2-digit day/month, 2- and 4-digit year
    "5/3/2026", "05/03/2026", "31/12/26", "1.1.26", "01.01.2026", "30/06/2026",
    "9/9/99", "10/10/2026", "29/2/24",
    # D/M/Y, out of range -> no date
    "0/1/2026", "32/1/2026", "1/0/2026", "1/13/2026", "1/1/1989", "1/1/2101",
    "00/00/00", "99/99/99",
    # not a date at all
    "", "   ", "unknown", "N/A", "2026", "2026/10", "10-2026", "1/1", "1/1/1/1",
    "abc/1/2026", "1/1/2026extra", " 1/1/2026 ",
    # the live corpus's one non-ASCII value: both engines must call it "no date"
    "۰۸/۰۲/۲٦",
]


def _py(rx: str) -> str:
    """The one spelling Python's `re` does not share with Postgres: `[[:space:]]`
    is a POSIX class there and a literal character set here."""
    return rx.replace("[[:space:]]", r"\s")


def test_regex_selects_exactly_what_the_index_buckets():
    keys = sorted({k for k in (month_key_of(s) for s in SAMPLES) if k})
    assert keys, "fixture produced no month keys"
    for s in SAMPLES:
        want = month_key_of(s)
        hit = [k for k in keys if re.search(_py(month_key_regex(k)), s)]
        assert hit == ([want] if want in keys else []), (
            f"{s!r}: index says {want!r}, filter matches {hit!r}")


@pytest.mark.parametrize("key", ["2026-01", "2026-09", "2026-10", "2026-12",
                                 "1990-01", "2100-12", "1999-07"])
def test_regex_is_postgres_safe(key):
    rx = month_key_regex(key)
    # a comma is a list separator inside a PostgREST filter value, and `{n,m}`
    # bounds would smuggle one in; quotes would need escaping the transport does
    # not do. Staying out of all three is what lets the regex travel unquoted.
    assert "," not in rx and '"' not in rx and "'" not in rx
    assert "{" not in rx and "\\" not in rx
    assert not re.search(r"[^\x20-\x7e]", rx)   # printable ASCII only


@pytest.mark.parametrize("bad", ["", "2026", "2026-1", "26-01", "2026-13", "1989-01",
                                 "2101-01", "abc", None])
def test_regex_refuses_a_non_key(bad):
    # a malformed month must never become a regex that quietly matches everything
    with pytest.raises(ValueError):
        month_key_regex(bad)


def test_two_digit_year_only_exists_for_2000s():
    assert "|26)" in month_key_regex("2026-05")      # 2026 also reachable as '26'
    assert "|99)" in month_key_regex("2099-05")
    assert month_key_of("1/5/95") == "2095-05"       # 95 -> 2095, never 1995
    assert not re.search(_py(month_key_regex("1995-05")), "1/5/95")
