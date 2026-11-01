"""/docGen — generate realistic synthetic INDOX documents from data models.

POST /docGen
  body: a doc-model dict ({"doc_type": "INVOICE", ...} — see src/doc_models/models.py)
  query: ?format=pdf|png (default pdf), ?truth=1 to get JSON {truth, file_b64} instead
         of raw bytes.

GET /docGen/sample?type=INVOICE&seed=7&format=pdf|png[&truth=1]
  Seeded realistic sample ("the average of the demo corpus"). Deterministic per seed.
  With truth=1 returns {"model": ..., "truth": ..., "file_b64": ...} — the model IS
  the ground truth, which is what makes a synthetic test suite provable to 100%.
"""
import base64
import dataclasses

from flask import jsonify, make_response

from src.doc_models import sample, DOC_TYPES, validate_compliance
from src.doc_models.models import Party, LineItem, BankDetails, BSLine
from src.doc_gen import render


def _from_dict(d: dict):
    doc_type = (d.get('doc_type') or '').upper()
    cls = DOC_TYPES.get(doc_type)
    if cls is None:
        raise ValueError(f'unknown doc_type {doc_type!r} — one of {sorted(DOC_TYPES)}')
    kw = {k: v for k, v in d.items() if k != 'doc_type'}
    for pk in ('supplier', 'customer'):
        if isinstance(kw.get(pk), dict):
            kw[pk] = Party(**kw[pk])
    if isinstance(kw.get('bank'), dict):
        kw['bank'] = BankDetails(**kw['bank'])
    line_cls = BSLine if doc_type == 'BALANCE_SHEET' else LineItem
    if isinstance(kw.get('lines'), list):
        kw['lines'] = [line_cls(**l) if isinstance(l, dict) else l for l in kw['lines']]
    return cls(**kw)


def _respond(model, request):
    fmt = request.args.get('format', 'pdf')
    data = render(model, fmt)
    if request.args.get('truth') in ('1', 'true'):
        return jsonify({
            'model': dataclasses.asdict(model) | {'doc_type': model.DOC_TYPE},
            'truth': model.extraction_truth(),
            'short_doc_id': model.short_doc_id,
            'format': fmt,
            'file_b64': base64.b64encode(data).decode(),
        })
    resp = make_response(data)
    resp.headers['Content-Type'] = 'application/pdf' if fmt == 'pdf' else 'image/png'
    ident = model.doc_id or model.short_doc_id or 'doc'
    resp.headers['Content-Disposition'] = f'inline; filename="{model.DOC_TYPE}_{ident}.{fmt}"'
    return resp


def generate_document(request):
    """Render a document from a model (stateless). ?validate=1 returns the compliance
    report; ?truth=1 returns model+truth+file. To PERSIST + issue a document, use the
    /documents API (DB-backed lifecycle) instead."""
    body = request.get_json(force=True, silent=True) or {}
    model = _from_dict(body)
    if request.args.get('validate') in ('1', 'true'):
        issues = validate_compliance(model)
        return jsonify({'compliant': not issues, 'violations': issues,
                        'doc_type': model.DOC_TYPE})
    return _respond(model, request)


def generate_sample(request):
    typ = request.args.get('type', 'INVOICE').upper()
    seed = int(request.args.get('seed', '1'))
    model = sample(typ, seed)
    return _respond(model, request)
