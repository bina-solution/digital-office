"""חשבוניות ישראל — the ITA invoice allocation-number regime (מספר הקצאה).

Under the Economic Efficiency Law 2023, a tax invoice above a threshold requires an
allocation number from the ITA (SHAAM) online system — a *precondition* for the buyer's
input-VAT deduction. Verified threshold schedule (pre-VAT, in force as of 2026-07):

    2024 pilot   NIS 25,000     (deduction enforcement from 5.5.2024)
    2025         NIS 20,000
    from 1.1.2026  NIS 10,000
    from 1.6.2026  NIS  5,000    ← current

Backend via env ALLOCATION_BACKEND:
  stub (default)  deterministic 9-digit number — dev/demo, clearly non-authoritative
  live            POST to the ITA endpoint (ITA_ALLOCATION_URL + ITA_ALLOCATION_TOKEN);
                  real request/response shape per the Israel Invoice API spec.

On a substantive (non-technical) denial/delay the invoice is "held": the software must
offer the 4 alternatives (spec §2.2.2) — we return status='held' + the alternatives so
the caller/UI can decide; the doc can still be issued but flagged (buyer can't deduct
until resolved).
"""
from __future__ import annotations

import hashlib
import os
import re

# threshold effective-date schedule (pre-VAT NIS). (yyyy, mm, dd) -> threshold
_SCHEDULE = [
    ((2026, 6, 1), 5000),
    ((2026, 1, 1), 10000),
    ((2025, 1, 1), 20000),
    ((2024, 5, 5), 25000),
]

HELD_ALTERNATIVES = [
    'issue_without_number_report_later',   # הפקה ללא מספר, השלמה מאוחרת
    'retry_allocation',                    # ניסיון נוסף לקבלת מספר
    'save_as_draft',                       # שמירה כטיוטה
    'cancel',                              # ביטול
]


def _parse_date(d):
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', str(d or ''))
    if not m:
        import time
        return time.localtime()[:3]
    dd, mm, yy = (int(x) for x in m.groups())
    yy = 2000 + yy if yy < 100 else yy
    return (yy, mm, dd)


def threshold_for(date) -> int:
    ymd = _parse_date(date)
    for eff, thr in _SCHEDULE:
        if ymd >= eff:
            return thr
    return 25000


def needs_allocation(doc_type: str, total_pre_vat, date) -> bool:
    """Tax invoices at/above the current threshold need an allocation number."""
    if doc_type not in ('INVOICE', 'INVOICE_RECEIPT'):
        return False
    try:
        return float(total_pre_vat or 0) >= threshold_for(date)
    except (TypeError, ValueError):
        return False


def _stub_number(model_doc_id, business_id):
    """Deterministic 9-digit allocation number for dev/demo (non-authoritative)."""
    h = hashlib.sha256(f'{business_id}|{model_doc_id}'.encode()).hexdigest()
    return str(int(h[:12], 16))[-9:].rjust(9, '0')


def request_allocation(doc_id, business_id, customer_id, total, date, invoice_ref):
    """Return {status, number?, alternatives?, backend}. status in
    granted | not_required | held | error."""
    backend = os.getenv('ALLOCATION_BACKEND', 'stub').lower()
    if backend == 'live':
        return _request_live(business_id, customer_id, total, date, invoice_ref)
    # stub
    return {'status': 'granted', 'number': _stub_number(invoice_ref or doc_id, business_id),
            'backend': 'stub', 'note': 'DEV allocation number — not from the ITA'}


def _request_live(business_id, customer_id, total, date, invoice_ref):
    url = os.getenv('ITA_ALLOCATION_URL')
    token = os.getenv('ITA_ALLOCATION_TOKEN')
    if not url or not token:
        return {'status': 'error', 'message': 'ITA_ALLOCATION_URL / ITA_ALLOCATION_TOKEN not set'}
    import requests
    # request shape per the Israel Invoice Model API spec (Invoice_ID mandatory since 2025)
    payload = {
        'Invoice_ID': invoice_ref, 'Invoice_Type': 305,      # 305 = tax invoice
        'Vat_Number': business_id, 'Client_Vat_Number': customer_id,
        'Invoice_Date': date, 'Amount_Before_Discount': total, 'Payment_Amount': total,
    }
    try:
        r = requests.post(url, json=payload, headers={'Authorization': f'Bearer {token}'}, timeout=30)
        j = r.json()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
    num = j.get('Confirmation_Number') or j.get('allocation_number')
    if num:
        return {'status': 'granted', 'number': ''.join(c for c in str(num) if c.isdigit())[-9:],
                'backend': 'live'}
    # substantive denial / delay -> held with the mandated alternatives
    return {'status': 'held', 'backend': 'live', 'alternatives': HELD_ALTERNATIVES,
            'message': j.get('error') or 'no allocation number returned'}
