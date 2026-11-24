"""my-docs — «מילוי וחתימה» (DGO-2139): the documents app's side of one signing link for every party.

The drawer's «מילוי וחתימה» sends the document's PDF from the ledger to esign as an event DRAFT; esign proposes the
sides and places it reads in the document; the office's editor (static/fill-editor.js) changes them and sends; this
side records the send in the document's own trail («חתימה · <sides> · <event>», as an envelope's send is recorded —
a link the trail does not hold is closed, never handed out); the drawer shows each side's state from esign.

    register(app, ledger=_ledger, say=_say, signable=SIGNABLE, esign=ESIGN, apitools=APITOOLS, hop=_HOP)
"""
import hashlib
import json
from datetime import date

import requests
from flask import Response, jsonify, request

#: what a deal document is called on its link, by type (the ledger's codes)
TITLE_HE = {'PROPOSAL': 'הצעה', 'QUOTE': 'הצעת מחיר', 'SERVICE_AGREEMENT': 'הסכם שירות', 'NDA': 'הסכם סודיות',
            'WORK_ORDER': 'הזמנת עבודה', 'ORDER': 'הזמנה'}
_CTX = {}


def _days(doc):
    """A link lives as long as its document's offer: until its «בתוקף עד», else 30 days."""
    for k in ('valid_until', 'valid'):
        v = doc.get(k) or (doc.get('model') or {}).get(k)
        try:
            left = (date.fromisoformat(str(v)[:10]) - date.today()).days
            if left > 0:
                return left
        except (TypeError, ValueError):
            continue
    return 30


def _esign(method, path, **kw):
    try:
        r = requests.request(method, _CTX['esign'] + path, timeout=kw.pop('timeout', 60), **kw)
    except requests.RequestException:
        return None, {'ok': False, 'message': 'אפליקציית החתימות לא ענתה'}
    try:
        body = r.json()
    except ValueError:
        body = {'ok': r.status_code < 400}
    return r, body


def _pages(ev):
    """esign's page addresses, as this app serves them to its own screen (relative: the console's base)."""
    for i, p in enumerate((ev or {}).get('pages') or []):
        p['src'] = 'api/fill/event/%s/page/%d' % (ev['id'], i + 1)
    return ev


def close_events(doc_id, reason='המסמך בוטל'):
    """A cancelled deal is not signed afterwards: its open events are closed (as its envelopes are)."""
    r, body = _esign('GET', '/api/events', params={'ref': doc_id}, timeout=15)
    for ev in (body.get('items') or []) if r is not None and r.ok else []:
        if ev.get('status') in ('draft', 'open'):
            _esign('POST', '/api/events/%s/cancel' % ev['id'], data={'reason': reason}, timeout=15)


def register(app, *, ledger, say, signable, esign, apitools, hop):
    _CTX.update(esign=esign.rstrip('/'), apitools=apitools.rstrip('/'))

    @app.post('/api/fill/<doc_id>/prepare')
    def fill_prepare(doc_id):
        r = ledger(f'documents/{doc_id}')
        if r is None:
            return say('not_found', 'המסמך לא נמצא', 404)
        doc = r.json()
        if doc.get('doc_type') not in signable:
            return say('not_signable', 'מסמך מסוג זה אינו נשלח לחתימה', 400)
        if doc.get('status') == 'draft':
            return say('draft', 'יש להפיק את המסמך לפני שליחתו לחתימה', 409)
        if doc.get('status') == 'cancelled':
            return say('cancelled', 'המסמך בוטל', 409)
        pdf = ledger(f'documents/{doc_id}/download', timeout=120)
        if pdf is None or not pdf.content.startswith(b'%PDF'):
            return say('no_pdf', 'לא התקבל קובץ המסמך ממאגר המסמכים', 502)
        # the editor opened again on the same bytes goes on with the draft it made before — not one more draft and one
        # more copy of the document on esign's volume every time the drawer's button is pressed
        sha = hashlib.sha256(pdf.content).hexdigest()
        r, have = _esign('GET', '/api/events', params={'ref': doc_id}, timeout=15)
        for ev in (have.get('items') or []) if r is not None and r.ok else []:
            if ev.get('status') == 'draft' and ev.get('doc_sha256') == sha:
                return jsonify({'ok': True, 'event': _pages(ev), 'parties': ev['parties'], 'fields': ev['fields'],
                                'found': {'page': next((f['page'] for f in ev['fields'] if f.get('page')), None)}})
        biz = ledger('business')
        office = ((biz.json().get('name') if biz is not None else '') or '').strip()
        customer = (doc.get('customer_name') or '').strip()
        number = doc.get('doc_number') or doc_id
        title = ('%s %s — %s' % (TITLE_HE.get(doc.get('doc_type'), ''), number, customer)).strip(' —')
        name = f"{number} — {customer}".strip(' —') + '.pdf'
        resp, body = _esign('POST', '/api/events', timeout=120,
                            files={'file': (name, pdf.content, 'application/pdf')},
                            data={'title': title, 'name': name, 'sender': office or 'הלשכה', 'ref': doc_id,
                                  'days': str(_days(doc)), 'hints': json.dumps([h for h in (customer, office) if h])})
        if resp is None or not body.get('ok'):
            return say('esign_refused', body.get('message') or 'אפליקציית החתימות סירבה', 502)
        return jsonify({'ok': True, 'event': _pages(body['event']), 'parties': body['parties'], 'fields': body['fields'],
                        'found': body.get('found')})

    @app.get('/api/fill/event/<eid>/page/<int:n>')
    def fill_page(eid, n):
        resp, _ = _esign('GET', '/api/events/%s/page/%d' % (eid, n), params={'w': request.args.get('w', '1100')})
        if resp is None or not resp.ok:
            return say('no_page', 'הדף לא נטען', 502)
        return Response(resp.content, mimetype=resp.headers.get('Content-Type', 'image/webp'),
                        headers={'Cache-Control': 'private, max-age=86400'})

    @app.post('/api/fill/event/<eid>/send')
    def fill_send(eid):
        payload = request.get_json(force=True, silent=True) or {}
        payload['by'] = 'my-docs'
        resp, body = _esign('POST', '/api/events/%s/send' % eid, json=payload)
        if resp is None or not body.get('ok'):
            return say('esign_refused', body.get('message') or 'הקישור לא נוצר', 400 if resp is not None else 502)
        ev = body['event']
        sides = ' + '.join(p['label'] for p in ev.get('parties') or [])
        try:
            logged = ev.get('ref') and requests.post(f"{_CTX['apitools']}/documents/{ev['ref']}/send",
                                                     json={'to': f'חתימה · {sides} · {eid}'}, timeout=30).status_code < 400
        except requests.RequestException:
            logged = False
        if ev.get('ref') and not logged:
            _esign('POST', '/api/events/%s/cancel' % eid, data={'reason': 'מאגר המסמכים לא רשם את השליחה'}, timeout=15)
            return say('ledger_unwritten', 'מאגר המסמכים לא רשם את השליחה — הקישור בוטל; נסו שוב', 502)
        return jsonify({'ok': True, 'link': body['link'], 'event': _pages(ev)})

    @app.get('/api/fill/<doc_id>')
    def fill_status(doc_id):
        """The events this document went out in, newest first, each side with its state; ok false when esign does
        not answer (never an empty list that reads as «sent to nobody»)."""
        resp, body = _esign('GET', '/api/events', params={'ref': doc_id}, timeout=15)
        if resp is None or not resp.ok:
            return jsonify({'ok': False, 'events': [], 'message': 'אפליקציית החתימות לא ענתה'})
        return jsonify({'ok': True, 'events': [_pages(e) for e in body.get('items') or [] if e.get('status') != 'draft']})

    @app.post('/api/fill/event/<eid>/link')
    def fill_relink(eid):
        resp, body = _esign('POST', '/api/events/%s/link' % eid, data={'by': 'my-docs'})
        if resp is None or not body.get('ok'):
            return say('esign_refused', 'לא נוצר קישור חדש — ייתכן שהאירוע סגור', 409)
        return jsonify({'ok': True, 'link': body['link']})

    @app.post('/api/fill/event/<eid>/complete')
    def fill_reseal(eid):
        """Make the signed copy again from the kept signatures, when making it failed (the drawer's «הפקה מחדש»)."""
        resp, body = _esign('POST', '/api/events/%s/complete' % eid, timeout=60)
        if resp is None or not body.get('ok'):
            return say('esign_refused', body.get('message') or 'העותק לא הופק', 409 if resp is not None else 502)
        return jsonify({'ok': True, 'started': bool(body.get('started'))})

    @app.post('/api/fill/event/<eid>/cancel')
    def fill_cancel(eid):
        resp, body = _esign('POST', '/api/events/%s/cancel' % eid, data={'reason': 'הקישור בוטל מהמסמך'})
        if resp is None or not body.get('ok'):
            return say('esign_refused', 'הקישור לא בוטל — ייתכן שכל הצדדים כבר חתמו', 409)
        return jsonify({'ok': True})

    @app.get('/api/fill/event/<eid>/download')
    def fill_download(eid):
        try:
            r = requests.get(f"{_CTX['esign']}/api/events/{eid}/download", timeout=120, stream=True)
        except requests.RequestException:
            return say('esign_unreachable', 'אפליקציית החתימות לא ענתה', 502)
        out = {k: v for k, v in r.headers.items() if k.lower() not in hop}
        return Response(r.iter_content(chunk_size=65536), status=r.status_code, headers=out)
