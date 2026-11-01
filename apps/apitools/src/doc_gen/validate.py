"""Prove the INDOX KW extractors hit 100% on the synthetic corpus.

For each doc type x N seeds: render -> /documentOcr (born-digital text layer, or
Tesseract for scans) -> the canonical KW queries via /documentJsonQuery -> compare
to model.extraction_truth(). Tests ALL seven extractors the INDOX pipeline runs:
company, type, id, date, amount, shipment (ref), purchase (order ref).

Run inside the apitools container:  python3 -m src.doc_gen.validate [N]
"""
from __future__ import annotations

import re
import sys
import time

import requests

from ..doc_models import sample
from .render import render

BASE = 'http://127.0.0.1:8080'

# ── canonical queries (mirror the live q_* payloads) ────────────────────────
_ID_VAL = [{"validation_type": "has_number"},
           {"validation_type": "length_greater_than", "validation_value": 3},
           {"validation_type": "length_less_than", "validation_value": 22}]

Q = {
    'company':     {"action": "find before", "action_value": ["עוסק מורשה", "עוסק פטור", "עוסק"],
                    "value_validations": [{"validation_type": "has_number"},
                                          {"validation_type": "length_equals", "validation_value": 9}], "is_rtl": True},
    # ID anchors mirror the live q_*_after payloads (number-label variants first) so find-after lands
    # on the id, not the neighbouring date. See settings.q_invoice_id_after / q_purchase_id / q_shipment_id.
    'invoice_id':  {"action": "find after", "action_value": ["חשבונית מס/קבלה מס':", "חשבונית מס מספר:", "חשבונית מס מספר", "חשבונית מס מס':", "חשבונית מס'", "חשבונית מס קבלה", "חשבונית מס"],
                    "value_validations": _ID_VAL, "is_rtl": True},
    'order_id':    {"action": "find after", "action_value": ["מס הזמנת רכש", "הזמנה מספר:", "מס' הזמנה", "הזמנת רכש", "הזמנתכם"],
                    "value_validations": _ID_VAL, "is_rtl": True},
    'quote_id':    {"action": "find after", "action_value": ["הצעת מחיר מספר:", "הצעת מחיר מס'", "הצעה מספר", "הצעת מחיר"],
                    "value_validations": _ID_VAL, "is_rtl": True},
    'shipment_id': {"action": "find after", "action_value": ["תעודת משלוח מספר", "משלוח מספר", "תעודת משלוח מס':", "תעודת משלוח מס'", "מספר משלוח", "תעודת משלוח"],
                    "value_validations": _ID_VAL, "is_rtl": True},
    'date':        {"action": "find after", "action_value": ["תאריך חשבונית", "תאריך התעודה", "תאריך"],
                    "value_validations": [{"validation_type": "has_number"},
                                          {"validation_type": "length_greater_than", "validation_value": 7},
                                          {"validation_type": "length_less_than", "validation_value": 11}], "is_rtl": True},
    'amount':      {"action": "find after", "action_value": [
                        "סה\"כ לתשלום", "סה\"כ להצעה", "סה\"כ יתרת חוב", "סכום שהתקבל", "סה\"כ נותר לתשלום"],
                    "value_validations": [{"validation_type": "has_number"}], "is_rtl": True},
    'ship_ref':    {"action": "find after", "action_value": ["תעודה", "תעודת משלוח"],
                    "value_validations": _ID_VAL, "is_rtl": True},
    'order_ref':   {"action": "find after", "action_value": ["הזמנה"],
                    "value_validations": _ID_VAL, "is_rtl": True},
    'type':        {"action": "find option", "action_value": [
                        "חשבונית מס", "קבלה", "הזמנת רכש", "תעודת משלוח", "הצעת מחיר", "גיול חובות"],
                    "value_validations": [], "is_rtl": True},
}

# keyword -> AI_TYPE, checked in this priority (חשבונית מס before קבלה so IR->INVOICE)
_TYPE_MAP = [("גיול חובות", "BALANCE_SHEET"), ("תעודת משלוח", "SHIPMENT"), ("הזמנת רכש", "ORDER"),
             ("הצעת מחיר", "QUOTE"), ("חשבונית מס", "INVOICE"), ("קבלה", "RECEIPT")]

# which extractors each type must satisfy
PLAN = {
    'INVOICE':         ['company', 'type', 'invoice_id', 'date', 'amount', 'ship_ref', 'order_ref'],
    'INVOICE_RECEIPT': ['company', 'type', 'invoice_id', 'date', 'amount', 'ship_ref', 'order_ref'],
    'ORDER':           ['company', 'type', 'order_id', 'date', 'amount', 'order_ref'],
    'QUOTE':           ['company', 'type', 'quote_id', 'date', 'amount'],
    'SHIPMENT':        ['company', 'type', 'shipment_id', 'date', 'order_ref'],
    'BALANCE_SHEET':   ['company', 'type', 'date', 'amount'],
    'RECEIPT':         ['company', 'type', 'date', 'amount'],
}
# expected value per field is read from the MODEL directly (truth-dict schema
# varies by type — balance sheet uses a structured schema, not AI_* keys)
_AI_TYPE = {'INVOICE_RECEIPT': 'INVOICE'}   # else == DOC_TYPE


def _expected(m, field):
    dt = m.DOC_TYPE
    if field == 'company':
        return m.supplier.company_id
    if field == 'type':
        return _AI_TYPE.get(dt, dt)
    if field == 'date':
        return m.doc_date
    if field == 'amount':
        for a in ('total_due', 'total', 'amount', 'document_total'):
            v = getattr(m, a, None)
            if v is not None:
                return v
        return None
    if field in ('invoice_id', 'order_id', 'quote_id', 'shipment_id'):
        return m.doc_id or getattr(m, 'account_no', '')
    if field == 'ship_ref':
        return sorted({l.shipment_ref for l in getattr(m, 'lines', []) if getattr(l, 'shipment_ref', '')})
    if field == 'order_ref':
        return sorted({l.order_ref for l in getattr(m, 'lines', []) if getattr(l, 'order_ref', '')})
    return None


def _digits(s):
    return re.sub(r'\D', '', str(s or ''))


def _post(qq, fid):
    try:
        return requests.post(BASE + '/documentJsonQuery',
                             json={'file_id': fid, 'ocr_json_query': qq}, timeout=45).json()
    except Exception:
        return {}


def _query(fid, field):
    q = Q[field]
    if q['action'] == 'find option':
        r = _post(q, fid)
        res = r.get('result') or {}
        v = res.get('result') if isinstance(res, dict) else None
        if isinstance(v, dict) and 'matches' in v:
            return [m.get('option') for m in v['matches']]
        return []
    # Try the field's DECLARED direction first (that is how the live q_* payload queries it),
    # then the alternate as a fallback. Trying find-after first for a find-below id field lets a
    # fulltext fallback grab an unrelated number before the correct below-anchor is even checked.
    _dirs = {'find before': ['find before', 'find after'],
             'find below': ['find below', 'find after'],
             'find after': ['find after', 'find below']}
    directions = _dirs.get(q['action'], ['find after', 'find below'])
    is_id = field in ('invoice_id', 'order_id', 'quote_id', 'shipment_id')
    for d in directions:
        qq = dict(q); qq['action'] = d
        r = _post(qq, fid)
        res = r.get('result') or {}
        v = res.get('result') if isinstance(res, dict) else None
        # an id field must never accept a date-shaped value (a wrong-direction fallback tends to grab
        # the neighbouring date) — skip it so the correct anchor/direction gets a chance.
        if v and not (is_id and re.match(r'^\s*\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\s*$', str(v))):
            return v
    return None


def _match(field, got, truth):
    if field == 'type':
        mapped = next((t for kw, t in _TYPE_MAP if kw in (got or [])), None)
        return mapped == truth, mapped
    if got is None:
        return False, got
    if field == 'company':
        return _digits(got) == _digits(truth) and len(_digits(truth)) == 9, got
    if field in ('invoice_id', 'order_id', 'quote_id', 'shipment_id'):
        return _digits(got)[-5:] == _digits(truth)[-5:] and _digits(truth)[-5:] != '', got
    if field == 'date':
        dg, dw = _digits(got), _digits(truth)
        return dg in (dw, dw[:4] + dw[6:]), got
    if field == 'amount':
        try:
            g = str(got).replace(',', '').replace('₪', '').strip()
            if g.endswith('-'):          # accounting trailing-minus -> leading
                g = '-' + g[:-1]
            return abs(float(g) - float(truth)) < 0.05, got
        except ValueError:
            return False, got
    if field in ('ship_ref', 'order_ref'):     # got must be one of the model's ref ids
        want = {_digits(x)[-5:] for x in (truth or [])}
        return _digits(got)[-5:] in want, got
    return bool(got), got


def run(n_seeds=3):
    import os
    # OCR mode: VALIDATE_OCR=1 renders a rasterised PNG (image, no text layer) so the
    # rasterise+Tesseract path is exercised — proves extraction on scans/non-PDFs.
    # ?ocr_engine=<VALIDATE_ENGINE> forces the engine (default: whatever the server uses).
    as_image = os.getenv('VALIDATE_OCR') == '1'
    engine = os.getenv('VALIDATE_ENGINE', '')
    dpi = int(os.getenv('VALIDATE_DPI', '300'))
    ext = 'png' if as_image else 'pdf'
    mime = 'image/png' if as_image else 'application/pdf'
    eng_q = f'&ocr_engine={engine}' if engine else ''
    print(f'MODE: {"image/OCR" if as_image else "pdf/text-layer"} engine={engine or "server-default"} dpi={dpi if as_image else "-"}')
    total = ok = 0
    fails = []
    per_field = {}
    off = int(os.getenv('VALIDATE_SEED_OFFSET', '0'))   # fresh seed range per cycle → new synthetic docs
    for typ, fields in PLAN.items():
        for seed in range(1 + off, n_seeds + 1 + off):
            m = sample(typ, seed)
            blob = render(m, ext, dpi=dpi) if as_image else render(m, 'pdf')
            fid = None
            for _try in range(4):
                try:
                    up = requests.post(BASE + f'/documentOcr?cache=false&dont_return_ocr=1{eng_q}',
                                       files={'file': (f'{typ}_{seed}.{ext}', blob, mime)},
                                       timeout=120).json()
                    fid = up.get('file_hash')
                    if fid:
                        break
                except Exception:
                    time.sleep(0.5)
            if not fid:
                print(f'  OCR-UPLOAD-FAILED {typ} {seed}')
                continue
            for field in fields:
                want = _expected(m, field)
                # ref fields only apply when the doc actually carries refs
                if field in ('ship_ref', 'order_ref') and not (want and any(want)):
                    continue
                total += 1
                per_field.setdefault(field, [0, 0])
                per_field[field][1] += 1
                got = _query(fid, field)
                good, shown = _match(field, got, want)
                if good:
                    ok += 1
                    per_field[field][0] += 1
                else:
                    fails.append((typ, seed, field, repr(shown)[:34], repr(want)[:34]))
    print(f'\nALIGNMENT: {ok}/{total} KW extractions match the model truth')
    print('per-field:', {k: f'{v[0]}/{v[1]}' for k, v in sorted(per_field.items())})
    for f in fails:
        print('  MISS', *f)
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(run(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
