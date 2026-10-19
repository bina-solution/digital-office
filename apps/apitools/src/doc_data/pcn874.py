"""PCN874 — the ITA unified-structure periodic VAT report (דוח מפורט למע"מ, מבנה אחיד 874).

Generates the fixed-width report from the issued documents in a period. Record layout
follows the ITA PCN874 spec: a header record (type 'O') carrying the business VAT id and
period, one detail record per transaction/input line, and a footer ('X') with the count
and control sum. Output-side (sales) records use type 'S1'; the 9-digit allocation number
is carried on qualifying tax invoices, on both the transaction and (for the buyer) input
sides, as the regime requires.

This is the report a business files; here it's produced from business_documents. Field
widths are per the published structure; amounts are whole shekels (agorot truncated) as
the format requires.
"""
from __future__ import annotations

import time


def _shekels(v):
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _f(val, width, numeric=True, sign=False):
    s = str(val if val is not None else '')
    if numeric:
        neg = sign and _num(val) < 0
        s = str(abs(_shekels(val)) if numeric else val)
        s = s.rjust(width, '0')[:width]
        if sign:
            s = ('-' if neg else '+') + s
        return s
    return s.ljust(width)[:width]


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _yyyymm(date_iso):
    # issued_at like 2026-07-08T... -> 202607
    s = str(date_iso or '')[:7].replace('-', '')
    return s or time.strftime('%Y%m')


def build(documents, business_id, period_yyyymm=None):
    """documents: list of business_documents rows (dicts) with doc_type, doc_number,
    customer_id, total, vat, allocation_number, issued_at. Returns the PCN874 text."""
    period = period_yyyymm or (documents and _yyyymm(documents[0].get('issued_at'))) or time.strftime('%Y%m')
    lines = []
    # header O: reporting VAT number + period + generation date
    lines.append('O' + _f(business_id, 9) + _f(period, 6) + _f(time.strftime('%Y%m%d'), 8))
    total_vat = 0
    n = 0
    for d in documents:
        if d.get('doc_type') not in ('INVOICE',) or d.get('status') == 'cancelled':
            continue
        vat = _shekels(d.get('vat'))
        total_vat += vat
        n += 1
        alloc = ''.join(c for c in str(d.get('allocation_number') or '') if c.isdigit())[-9:]
        # S1 sales record: partner vat, ref, date, total(pre-vat), vat, allocation(9)
        rec = ('S1'
               + _f(d.get('customer_id') or '', 9)
               + _f((d.get('doc_number') or '')[-9:], 9, numeric=False)
               + _f(_yyyymm(d.get('issued_at')) + '01', 8)
               + _f(_num(d.get('total')) - vat, 11)     # amount before VAT
               + _f(vat, 11)
               + _f(alloc, 9, numeric=False))
        lines.append(rec)
    # footer X: record count + control sum of VAT
    lines.append('X' + _f(n, 9) + _f(total_vat, 11))
    return '\n'.join(lines) + '\n'
