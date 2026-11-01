import re
from typing import Any


def validation_equals(value: Any, validation_value: Any) -> bool:
    return value == validation_value


def validation_length_equals(value: str, length: int) -> bool:
    return len(value) == length


def validation_has_letter(value: str) -> bool:
    return any(char.isalpha() for char in value)


def validation_has_number(value: str) -> bool:
    return any(char.isdigit() for char in value)


def validation_is_number(value: str) -> bool:
    return value.isdigit()


def validation_length_greater_than(value: str, length: int) -> bool:
    return len(value) > length


def validation_length_less_than(value: str, length: int) -> bool:
    return len(value) < length


def validation_not_equals(value: Any, validation_value: Any) -> bool:
    return value != validation_value


def validation_starts_with(value: str, validation_value: str) -> bool:
    return value.startswith(validation_value)


def validation_ends_with(value: str, validation_value: str) -> bool:
    return value.endswith(validation_value)


def validation_not_ends_with(value: str, validation_value: str) -> bool:
    return not value.endswith(validation_value)


def _canonical_amount(s: str):
    """Normalize a GROUPED number that uses dot/space/comma thousands separators to a
    canonical 'digits[.dd]' string. Only fires on 2+ separators, so single-separator tokens
    keep their existing meaning. The LAST separator is the decimal iff it precedes 1-2 digits;
    every earlier separator is a thousands group. Handles US (1,234.56), EU (1.234,56) and the
    comma->dot OCR misread (1.589.00 -> 1589.00). Returns None when it is not a grouped number."""
    t = s.replace(' ', ' ')
    seps = [c for c in t if c in ' .,']
    if len(seps) < 2 or not re.fullmatch(r'\d{1,3}(?:[ .,]\d{3})+(?:[.,]\d{1,2})?', t):
        return None
    last = max(t.rfind('.'), t.rfind(','), t.rfind(' '))
    tail = t[last + 1:]
    if len(tail) in (1, 2):                       # last separator is the decimal point
        return re.sub(r'[ .,]', '', t[:last]) + '.' + tail
    return re.sub(r'[ .,]', '', t)                # every separator is a thousands group


def _as_number(value: Any):
    """Parse a document money/number token: strips ₪, שח, thousands separators and supports
    the accounting trailing-minus ("1,234.56-" == -1234.56). Grouped numbers with dot/space
    thousands (EU style, or a comma mis-OCR'd as a dot -> "1.589.00") are normalized so the
    LAST separator becomes the decimal point. Returns None if not numeric."""
    s = str(value or '').replace('₪', '').replace('שח', '').strip()
    neg = s.endswith('-')
    if neg:
        s = s[:-1].strip()
    canon = _canonical_amount(s)
    s = canon if canon is not None else s.replace(',', '')
    s = re.sub(r'[^0-9.\-]', '', s)
    if not re.search(r'\d', s):
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def validation_numeric_greater_than(value: Any, validation_value: Any) -> bool:
    """True when the token parses as a number strictly greater than validation_value.

    Needed to reject a discount line (-0.17) or a stray 0 when hunting a grand total:
    the query engine retries the NEXT anchor match whenever a validation fails, so this
    walks past subtotal/discount rows to the real total.
    """
    n = _as_number(value)
    if n is None:
        return False
    try:
        return n > float(validation_value)
    except (TypeError, ValueError):
        return False


def validation_digit_count_equals(value: Any, validation_value: Any) -> bool:
    """True when the token contains exactly N digit characters.

    ``length_equals`` counts CHARACTERS, so a garbage token like ``*1262976*`` (9 chars,
    7 digits) passes a 9-length test for a 9-digit company id. This checks the digits.
    """
    digits = re.sub(r'\D', '', str(value or ''))
    try:
        return len(digits) == int(validation_value)
    except (TypeError, ValueError):
        return False


def validation_not_starts_with(value: Any, validation_value: Any) -> bool:
    """True when the token does NOT start with the given prefix.

    An Israeli company/VAT id never begins with 0, but a phone number always does — and a
    phone like ``03-7797090`` carries exactly 9 digits, so it sails through a 9-digit test
    and gets returned as the supplier id. This rejects it.
    """
    return not str(value or '').strip().startswith(str(validation_value))


def validation_not_contains(value: Any, validation_value: Any) -> bool:
    """True when the token does not contain the given substring (e.g. '-' for phone numbers)."""
    return str(validation_value) not in str(value or '')


_MONEY_RE = re.compile(
    r'^-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?-?$'          # 1,234.56  (comma thousands / plain)
    r'|^-?\d+(?:\.\d{1,2})?-?$'                          # 1234.56
    r'|^-?\d{1,3}(?:[ ., ]\d{3})+[ ., ]\d{1,2}-?$')  # 1.234,56 / 1.589.00 / 1 234.56 (grouped, dot/space thousands)


def validation_is_money(value: Any) -> bool:
    """True when the token is a money-shaped number (optional thousands commas, optional
    decimals, optional accounting trailing-minus) — and NOT a date or bank-account number.
    Rejects '17/3/2025', '893300/59', Hebrew garbage, and bare zeros."""
    s = str(value or '').strip()
    if '/' in s or ':' in s or any('א' <= c <= 'ת' for c in s):
        return False
    if not _MONEY_RE.match(s):
        return False
    n = _as_number(s)
    return n is not None and abs(n) > 0.0001


def validation_matches_regex(value: Any, validation_value: Any) -> bool:
    """True when the token matches the given regular expression (fullmatch)."""
    try:
        return re.fullmatch(str(validation_value), str(value or '').strip()) is not None
    except re.error:
        return False
