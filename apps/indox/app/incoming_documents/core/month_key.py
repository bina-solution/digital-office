"""The month-navigation bucketing rule — ONE definition, two renderings.

Month navigation has two halves that MUST agree:

  * the INDEX  (`POST /repos/<r>/documents/month-index`) buckets every row in
    Python, via :func:`month_key_of`;
  * the FILTER (clicking a month chip) is a `documents/query` filter that has to
    run *in the database*, because paging and `with_count` are the database's job.

Before this module those two halves were written independently and disagreed.
:func:`month_key_of` deliberately accepts BOTH live `DOC_DATE` shapes — the ISO
`YYYY-MM-DD…` one and the `D/M/YY(YY)` one the OCR/AI extractors actually write —
while the filter was sent as `{op: 'startswith', value: 'YYYY-MM'}`, a raw string
prefix that only the ISO shape can ever match. So every chip counted rows the
grid then refused to show: measured 2026-08-11 on the live corpus, chip
`אוקטובר 2026` advertised 38 documents and the grid rendered 3, and across the
table 17,296 of 22,641 rows were countable-but-unopenable.

The fix is not to teach the filter a second rule — it is to give the rule ONE
owner and render it into whichever dialect the caller needs:

  * :func:`month_key_of`     — Python, for in-process bucketing (the index, and
    the gsheet backend's in-memory filter);
  * :func:`month_key_regex`  — a POSIX regular expression, for the supabase
    backend, which hands it to PostgREST's `match` operator (`~`).

:func:`month_key_regex` is exact, not approximate: for every string `s`,
``re.match(month_key_regex(k), s) is not None`` iff ``month_key_of(s) == k``.
`tests/unit/test_month_key.py` proves that over the real corpus shapes plus the
boundary cases (day 0/32, month 0/13, year 1989/2101, 2-digit years).
"""
from __future__ import annotations

import re

# Both live shapes. ISO is a PREFIX match (`2026-10-05` -> `2026-10`); D/M/Y is a
# FULL match, because a bare prefix there would bucket `1/2/2026extra` as February.
#
# `[0-9]`, NOT `\d`. In a Python `str` pattern `\d` matches every Unicode decimal
# digit, and `int()` accepts them too, so the old spelling silently bucketed the
# one Eastern-Arabic-numeral value the live corpus carries ('۰۸/۰۲/۲٦') into
# 2026-02 — a bucket no database-side filter could ever open, because Postgres
# regexes are ASCII here. The two halves of month navigation have to be the SAME
# rule, and a rule only one of the two engines can evaluate is not one rule. Such
# a value now reads as "no date", which is both engines' answer and is honest:
# nothing downstream normalises mixed-script digits, so calling it February was a
# guess. Measured 2026-08-12: exactly one distinct value, ASCII-only otherwise.
_ISO_RE = re.compile(r"^([0-9]{4})-([0-9]{2})")
_DMY_RE = re.compile(r"^([0-9]{1,2})[./]([0-9]{1,2})[./]([0-9]{2}|[0-9]{4})$")

MIN_YEAR = 1990
MAX_YEAR = 2100

#: A month key is exactly `YYYY-MM`.
KEY_RE = re.compile(r"^(\d{4})-(\d{2})$")


def month_key_of(raw: object) -> str | None:
    """`YYYY-MM` for a date value, or None for empty/unparsable/out-of-range.

    Two live formats have to resolve here, not one. `TIMESTAMP`/`created_at`
    (and `DOC_DATE` on the rows from the one-time 2026-08-05 bulk restore) are
    ISO-ish (`YYYY-MM-DD...`). But every *live* OCR/AI extracted
    `DOC_DATE`/`LOCAL_DOC_DATE` value — the UI's default month-navigation column
    — is written `DD/MM/YYYY` or `DD/MM/YY`: `q_v3_date_base`'s extraction regex
    (`\\d{1,2}[./]\\d{1,2}[./]\\d{2,4}`) captures the year exactly as printed on
    the source document, 2 or 4 digits, with no normalization, and the per-type
    routers' normalizing `query_doc_date` fallback only fires when `DOC_DATE` is
    still empty — so a slash-format value is never corrected in place.

    Out-of-range values count as "no date" rather than a wrong bucket.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = _ISO_RE.match(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if mo < 1 or mo > 12 or y < MIN_YEAR or y > MAX_YEAR:
            return None
        return f"{m.group(1)}-{m.group(2)}"
    m = _DMY_RE.match(s)
    if m:
        day, mo = int(m.group(1)), int(m.group(2))
        y_raw = m.group(3)
        year = int(("20" + y_raw) if len(y_raw) == 2 else y_raw)
        if 1 <= day <= 31 and 1 <= mo <= 12 and MIN_YEAR <= year <= MAX_YEAR:
            return f"{year:04d}-{mo:02d}"
        return None
    return None


#: Days 1-31, written with or without a leading zero — the exact set
#: `month_key_of` accepts from `[0-9]{1,2}` after its `1 <= day <= 31` check.
_DAY_ALT = "(0?[1-9]|[12][0-9]|3[01])"

#: The POSIX spelling of "whitespace" — see `month_key_regex`. Postgres evaluates
#: this against the same Unicode notion of whitespace `str.strip()` uses, which is
#: why the strip stays Unicode-aware while the DIGITS are pinned to ASCII: only the
#: digits had a live value that disagreed.
_WS = "[[:space:]]"


def month_key_regex(key: str) -> str:
    """POSIX regex matching exactly the raw values that bucket into `key`.

    Rendered for PostgREST's `match` operator, i.e. Postgres `~`. Deliberately
    free of `{n,m}` bounds and of `,` — a comma inside a PostgREST filter value
    is a list separator — so the expression survives the query string unquoted.

    Raises ValueError on anything that is not a `YYYY-MM` key, so a malformed
    month can never be turned into a regex that quietly matches everything.
    """
    m = KEY_RE.match(str(key or ""))
    if not m:
        raise ValueError(f"not a YYYY-MM month key: {key!r}")
    year, mo = int(m.group(1)), int(m.group(2))
    if not (MIN_YEAR <= year <= MAX_YEAR) or not (1 <= mo <= 12):
        raise ValueError(f"month key out of range: {key!r}")

    # ISO branch: a PREFIX, mirroring `_ISO_RE.match`.
    iso = f"{year:04d}-{mo:02d}"
    # D/M/Y branch: a FULL match, mirroring `_DMY_RE.fullmatch` semantics.
    month_alt = f"0?{mo}" if mo < 10 else str(mo)
    # `month_key_of` maps a 2-digit year YY to 20YY, so a 2-digit form exists
    # only for 2000-2099. Outside that range the 4-digit form is the only one.
    years = [f"{year:04d}"]
    if 2000 <= year <= 2099:
        years.append(f"{year % 100:02d}")
    year_alt = "|".join(years)
    dmy = f"{_DAY_ALT}[./]({month_alt})[./]({year_alt}){_WS}*$"
    # `month_key_of` calls `.strip()` before matching, so the regex has to allow
    # the same padding — otherwise a stored " 1/1/2026 " is counted by the index
    # and unreachable by the filter, which is this module's whole bug in
    # miniature. `[[:space:]]` (not `\s`, not a literal class) keeps the
    # expression free of backslashes, commas and quotes so it survives a
    # PostgREST query value unquoted.
    return f"^{_WS}*({iso}|{dmy})"
