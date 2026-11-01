"""/documents — business-document management API (Green-Invoice / morning.com style).

Backed by doc_data.store (Postgres source of truth). No OCR.

  POST   /documents                 create a DRAFT   (body: a doc model; ?issue=1 to issue now)
  GET    /documents                 list / search    (?type=&status=&customer_id=&limit=&offset=)
  GET    /documents/<id>            fetch one
  PATCH  /documents/<id>            edit a draft
  POST   /documents/<id>/issue      draft -> issued  (?series=A&force=1)
  GET    /documents/<id>/download   pdf/png          (?format=pdf|png; מקור once, then העתק)
  POST   /documents/<id>/send       issued -> sent   (body: {to})
  POST   /documents/<id>/pay        -> paid
  POST   /documents/<id>/cancel     -> cancelled + credit document (body: {reason})
  GET    /documents/<id>/events     audit trail
  POST   /documents/<id>/allocation attach מספר הקצאה (body: {allocation_number,status})
  POST   /documents/consent         record recipient consent (body: {customer_id,method})
  GET    /documents/verify          sequence continuity + tamper-chain self-check
"""
from flask import jsonify, make_response

from src.doc_data import store


def _err(e, code):
    return jsonify({'error': type(e).__name__, 'message': str(e)}), code


def create(request):
    body = request.get_json(force=True, silent=True) or {}
    try:
        rec = store.create(body)
    except (ValueError, TypeError) as e:
        return _err(e, 400)
    if request.args.get('issue') in ('1', 'true'):
        try:
            rec = store.issue(rec['id'], series=request.args.get('series', 'A'),
                              force=request.args.get('force') in ('1', 'true'))
        except ValueError as e:
            return jsonify({'error': 'not_compliant', 'message': str(e),
                            'document': rec}), 422
    return jsonify(rec), 201


def list_docs(request):
    return jsonify(store.query(
        doc_type=request.args.get('type'), status=request.args.get('status'),
        customer_id=request.args.get('customer_id'), issuer_id=request.args.get('issuer_id'),
        date_from=request.args.get('from'), date_to=request.args.get('to'),
        limit=request.args.get('limit', 100), offset=request.args.get('offset', 0)))


def get_doc(doc_id):
    rec = store.get(doc_id)
    return (jsonify(rec) if rec else (jsonify({'error': 'not_found'}), 404))


def update_doc(doc_id, request):
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(store.update(doc_id, body))
    except KeyError:
        return jsonify({'error': 'not_found'}), 404
    except PermissionError as e:
        return _err(e, 409)
    except (ValueError, TypeError) as e:
        return _err(e, 400)


def issue_doc(doc_id, request):
    try:
        return jsonify(store.issue(doc_id, series=request.args.get('series', 'A'),
                                   force=request.args.get('force') in ('1', 'true')))
    except KeyError:
        return jsonify({'error': 'not_found'}), 404
    except PermissionError as e:
        return _err(e, 409)
    except ValueError as e:
        return jsonify({'error': 'not_compliant', 'message': str(e)}), 422


def download_doc(doc_id, request):
    try:
        data, fname, label = store.download(doc_id, fmt=request.args.get('format'))
    except KeyError:
        return jsonify({'error': 'not_found'}), 404
    resp = make_response(data)
    resp.headers['Content-Type'] = 'application/pdf' if fname.endswith('.pdf') else 'image/png'
    resp.headers['Content-Disposition'] = 'inline; filename="%s"' % fname
    resp.headers['X-Document-Label'] = {'מקור': 'original', 'העתק': 'copy',
                                        'טיוטה': 'draft'}.get(label, label)
    return resp


def _act(fn, doc_id, request, **extra):
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(fn(doc_id, **{k: body.get(k, d) for k, d in extra.items()}))
    except KeyError:
        return jsonify({'error': 'not_found'}), 404
    except PermissionError as e:
        return _err(e, 409)


def send_doc(doc_id, request):
    return _act(store.send, doc_id, request, to='')


def pay_doc(doc_id, request):
    return _act(store.pay, doc_id, request, detail='')


def cancel_doc(doc_id, request):
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(store.cancel(doc_id, body.get('reason', '')))
    except KeyError:
        return jsonify({'error': 'not_found'}), 404
    except PermissionError as e:
        return _err(e, 409)


def events_doc(doc_id):
    return jsonify(store.events(doc_id))


def convert_doc(doc_id, request):
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(store.convert(doc_id, body.get('to_type'))), 201
    except KeyError:
        return jsonify({'error': 'not_found'}), 404
    except ValueError as e:
        return _err(e, 400)


def allocation_doc(doc_id, request):
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(store.attach_allocation(doc_id, body['allocation_number'],
                                               body.get('status', 'granted')))
    except KeyError as e:
        return _err(e, 400)


def consent(request):
    body = request.get_json(force=True, silent=True) or {}
    try:
        store.record_consent(body['customer_id'], body.get('method', 'computerized'))
        return jsonify({'ok': True})
    except KeyError as e:
        return _err(e, 400)


def verify(request):
    from src.doc_data import signing
    return jsonify({'sequence': store.verify_sequence(), 'chain': store.verify_chain(),
                    'signer': signing.status()})


def signature_doc(doc_id):
    try:
        return jsonify(store.signature(doc_id))
    except KeyError:
        return jsonify({'error': 'not_found'}), 404


def pcn874_report(request):
    biz = request.args.get('business_id')
    if not biz:
        return jsonify({'error': 'business_id required'}), 400
    from flask import make_response
    txt = store.pcn874_report(biz, request.args.get('from'), request.args.get('to'))
    resp = make_response(txt)
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="PCN874.txt"'
    return resp


# ── single-business entities: settings, customers, items ────────────────────
from src.doc_data import entities


def business_get(request):
    return jsonify(entities.get_business())


def business_save(request):
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(entities.save_business(body))


def _crud(request, kind, rid=None):
    listf = {'customers': entities.list_customers, 'items': entities.list_items}[kind]
    getf = {'customers': entities.get_customer, 'items': entities.get_item}[kind]
    createf = {'customers': entities.create_customer, 'items': entities.create_item}[kind]
    updatef = {'customers': entities.update_customer, 'items': entities.update_item}[kind]
    deletef = {'customers': entities.delete_customer, 'items': entities.delete_item}[kind]
    if rid is None:
        if request.method == 'POST':
            return jsonify(createf(request.get_json(force=True, silent=True) or {})), 201
        return jsonify(listf(request.args.get('q')))
    if request.method == 'GET':
        r = getf(rid); return jsonify(r) if r else (jsonify({'error': 'not_found'}), 404)
    if request.method == 'PATCH':
        return jsonify(updatef(rid, request.get_json(force=True, silent=True) or {}))
    if request.method == 'DELETE':
        return jsonify(deletef(rid))


def customers(request, rid=None):
    return _crud(request, 'customers', rid)


def items(request, rid=None):
    return _crud(request, 'items', rid)
