"""my-docs — a thin production frontend service for the business-document API.

A small BFF: serves the SPA (static/) and proxies /api/* to apitools' /documents +
/docGen endpoints. Auth is handled upstream by Authentik forward-auth (Traefik
middleware) — this service just reads the identity headers Authentik injects and
exposes them at /api/me. No business logic here; the source of truth is apitools
+ Postgres/Supabase.
"""
import os
import threading
import time

import requests
from flask import Flask, request, Response, send_from_directory, jsonify

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# MY_DOCS_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset.
_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
            release=os.getenv("SENTRY_RELEASE"),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # never let telemetry break the app
        pass

APITOOLS = os.getenv('APITOOLS_URL', 'http://apitools:8080')
# the office's signing app (esign.v1): a proposal, a quote or an agreement goes out for signature from here
ESIGN = os.getenv('ESIGN_URL', 'http://esign:8080').rstrip('/')
# the documents index (documents.v1): the issued, the incoming and the office's files, one Hebrew search («ארכיון»)
DOCUMENTS = os.getenv('DOCUMENTS_URL', 'http://documents:8080').rstrip('/')
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

#: the documents a customer signs to close a deal (DGO-2029); a document of the books is never sent to sign
SIGNABLE = {'PROPOSAL', 'QUOTE', 'SERVICE_AGREEMENT', 'NDA', 'WORK_ORDER', 'ORDER'}

app = Flask(__name__, static_folder=None)

# ── idempotent document creation (bank-standard: a document must never be created twice) ──
# The SPA sends a stable Idempotency-Key per create session. We serialize same-key requests on a
# per-key lock (so simultaneous double-POSTs collapse to ONE create) and replay the first successful
# response for any later request with the same key within the TTL — covering double-clicks, network
# re-sends, and two tabs. Only *successful* creates are cached (a validation error stays retryable).
_IDEM = {}            # key -> (ts, status, body_bytes, content_type)
_IDEM_KEYS = {}       # key -> threading.Lock (serialize concurrent same-key creates)
_IDEM_GUARD = threading.Lock()
_IDEM_TTL = 900       # 15 minutes


def _idempotent_create(sub):
    key = request.headers.get('Idempotency-Key', '').strip()
    now = time.time()
    with _IDEM_GUARD:
        for k in [k for k, v in _IDEM.items() if now - v[0] > _IDEM_TTL]:
            _IDEM.pop(k, None); _IDEM_KEYS.pop(k, None)
        hit = _IDEM.get(key)
        lock = None if hit else _IDEM_KEYS.setdefault(key, threading.Lock())
    if hit:
        _, status, body, ct = hit
        return Response(body, status=status, headers={'Content-Type': ct, 'X-Idempotent-Replay': '1'})
    with lock:                                   # only one thread per key forwards to apitools
        with _IDEM_GUARD:
            hit = _IDEM.get(key)
        if hit:
            _, status, body, ct = hit
            return Response(body, status=status, headers={'Content-Type': ct, 'X-Idempotent-Replay': '1'})
        fwd = {k: v for k, v in request.headers if k.lower() not in _HOP}
        try:
            r = requests.request('POST', f'{APITOOLS}/{sub}', params=request.args,
                                 data=request.get_data(), headers=fwd, timeout=120)
        except requests.RequestException as e:
            return jsonify({'error': 'upstream_unreachable', 'message': str(e)}), 502
        body, ct = r.content, r.headers.get('Content-Type', 'application/json')
        if r.status_code < 400:                  # never cache a failed create — it should be retryable
            with _IDEM_GUARD:
                _IDEM[key] = (now, r.status_code, body, ct)
        out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
        return Response(body, status=r.status_code, headers=out)

# headers Authentik forward-auth injects about the signed-in user
_AUTH_HEADERS = ('X-authentik-username', 'X-authentik-email', 'X-authentik-name',
                 'X-authentik-groups', 'X-authentik-uid')
_HOP = {'content-length', 'connection', 'keep-alive', 'transfer-encoding', 'host'}


@app.get('/healthz')
def healthz():
    return {'ok': True}


@app.get('/api/me')
def me():
    u = {k.replace('X-authentik-', ''): request.headers.get(k) for k in _AUTH_HEADERS}
    return jsonify({'user': u.get('username') or 'guest',
                    'email': u.get('email'), 'name': u.get('name') or u.get('username') or 'אורח',
                    'groups': (u.get('groups') or '').split('|') if u.get('groups') else []})


# ── sign and close: a ledger document goes out as esign's one link (DGO-2029) ───────────────────────
def _ledger(path, **kw):
    try:
        r = requests.get(f'{APITOOLS}/{path}', timeout=kw.pop('timeout', 30), **kw)
    except requests.RequestException:
        return None
    return r if r.status_code < 400 else None


def _say(error, message, code):
    return jsonify({'error': error, 'message': message}), code


@app.post('/api/sign/<doc_id>')
def sign_start(doc_id):
    """Send an issued deal document for the customer's signature: its PDF becomes an esign envelope, the
    ledger records the send, and the screen gets the one link. Delivering the link is the owner's act."""
    body = request.get_json(force=True, silent=True) or {}
    signer = (body.get('signer') or '').strip()
    if not signer:
        return _say('no_signer', 'שם החותם חסר', 400)
    r = _ledger(f'documents/{doc_id}')
    if r is None:
        return _say('not_found', 'המסמך לא נמצא', 404)
    doc = r.json()
    if doc.get('doc_type') not in SIGNABLE:
        return _say('not_signable', 'מסמך מסוג זה אינו נשלח לחתימה', 400)
    if doc.get('status') == 'draft':
        return _say('draft', 'יש להפיק את המסמך לפני שליחתו לחתימה', 409)
    if doc.get('status') == 'cancelled':
        return _say('cancelled', 'המסמך בוטל', 409)
    pdf = _ledger(f'documents/{doc_id}/download', timeout=120)
    if pdf is None or not pdf.content.startswith(b'%PDF'):
        return _say('no_pdf', 'לא התקבל קובץ המסמך ממאגר המסמכים', 502)
    biz = _ledger('business')
    sender = (biz.json().get('name') if biz is not None else '') or 'הלשכה'
    name = f"{doc.get('doc_number') or doc_id} — {doc.get('customer_name') or ''}".strip(' —') + '.pdf'
    form = {'signer': signer, 'email': (body.get('email') or '').strip(), 'sender': sender, 'name': name,
            'days': str(int(body.get('days') or 14))}
    if body.get('password'):
        form['password'] = str(body['password'])
    try:
        e = requests.post(f'{ESIGN}/api/envelopes', files={'file': (name, pdf.content, 'application/pdf')},
                          data=form, timeout=60)
        answer = e.json()
    except (requests.RequestException, ValueError):
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה', 502)
    if not answer.get('ok'):
        return _say('esign_refused', answer.get('detail') or 'אפליקציית החתימות סירבה', 502)
    env = answer['data']['envelope']
    # the ledger's own trail: sent, to whom, by which envelope — the only way the document finds its envelope again
    # (sign_status). A link the trail does not hold is closed, never handed out (DGO-2029, the second reader).
    try:
        logged = requests.post(f'{APITOOLS}/documents/{doc_id}/send',
                               json={'to': f'חתימה · {signer} · {env["id"]}'}, timeout=30).status_code < 400
    except requests.RequestException:
        logged = False
    if not logged:
        _close_envelope(env['id'], 'מאגר המסמכים לא רשם את השליחה')
        return _say('ledger_unwritten', 'מאגר המסמכים לא רשם את השליחה — הקישור בוטל; נסו שוב', 502)
    return jsonify({'ok': True, 'link': answer['data']['link'], 'envelope': env})


def _close_envelope(eid, reason):
    try:
        requests.post(f'{ESIGN}/api/envelopes/{eid}/cancel', data={'reason': reason}, timeout=15)
    except requests.RequestException:
        pass                                    # esign keeps its own expiry; nothing more to do from here


def _envelopes(doc_id):
    """The envelopes a document went out in, newest first, by the envelope ids its ledger trail recorded when it was
    sent; None when the ledger or esign does not answer — never an empty list that reads as «sent to nobody» (the
    third reader). Matching by its number found another type's document of the same number, with numbering from a
    start every type shares (DGO-2029, the second reader)."""
    r = _ledger(f'documents/{doc_id}/events')
    if r is None:
        return None
    ids = []
    for e in r.json() or []:
        detail = str(e.get('detail') or '')
        if e.get('action') == 'send' and detail.startswith('חתימה · '):
            eid = detail.rsplit(' · ', 1)[-1].strip()
            if eid and eid not in ids:
                ids.append(eid)
    mine = []
    for eid in reversed(ids):
        try:
            g = requests.get(f'{ESIGN}/api/envelopes/{eid}', timeout=15)
            if g.status_code == 404:
                continue
            mine.append(g.json()['data']['envelope'])
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return None
    return mine


@app.post('/api/documents/<doc_id>/cancel')
def cancel_document(doc_id):
    """Cancel in the ledger, then close the document's open signing links: a cancelled deal is not signed afterwards
    (DGO-2029, the second reader). The ledger's answer is the answer."""
    try:
        r = requests.post(f'{APITOOLS}/documents/{doc_id}/cancel', data=request.get_data(),
                          headers={'Content-Type': 'application/json'}, timeout=120)
    except requests.RequestException as e:
        return jsonify({'error': 'upstream_unreachable', 'message': str(e)}), 502
    if r.status_code < 400:
        for env in _envelopes(doc_id) or []:
            if env.get('status') not in ('signed', 'cancelled', 'expired'):
                _close_envelope(env['id'], 'המסמך בוטל')
    return Response(r.content, status=r.status_code,
                    headers={'Content-Type': r.headers.get('Content-Type', 'application/json')})


@app.get('/api/sign/<doc_id>')
def sign_status(doc_id):
    """The envelopes this document went out in, newest first (see _envelopes)."""
    mine = _envelopes(doc_id)
    if mine is None:
        return jsonify({'ok': False, 'envelopes': [], 'message': 'אפליקציית החתימות לא ענתה'})
    return jsonify({'ok': True, 'envelopes': mine})


@app.get('/api/sign/envelope/<eid>/download')
def sign_download(eid):
    """The signed copy (the document, the stamp, the certificate, the PAdES signature)."""
    try:
        r = requests.get(f'{ESIGN}/api/envelopes/{eid}/download', timeout=120, stream=True)
    except requests.RequestException:
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה', 502)
    out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    return Response(r.iter_content(chunk_size=65536), status=r.status_code, headers=out)


@app.get('/api/archive')
def archive():
    """«ארכיון»: every document the office has — issued (the ledger), incoming (INDOX) and its files («קבצים») — in
    one list with one Hebrew search, read from the documents index (DGO-2029). A read; it forwards only these keys."""
    params = {k: request.args[k] for k in ('q', 'direction', 'provider', 'type', 'limit', 'offset') if request.args.get(k)}
    try:
        r = requests.get(f'{DOCUMENTS}/api/documents', params=params, timeout=30)
        return Response(r.content, status=r.status_code, headers={'Content-Type': 'application/json'})
    except requests.RequestException:
        return _say('documents_unreachable', 'אפליקציית המסמכים (האינדקס) לא ענתה', 502)


@app.route('/api/<path:sub>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def proxy(sub):
    """Forward /api/<sub> -> apitools/<sub>, streaming the response (PDFs included)."""
    # the history import writes issued documents and their statuses: it is the shell's alone
    # (`./bbox my-docs import-history`, which calls the ledger itself), never a browser's (DGO-2042, the fifth reader)
    if sub.strip('/').lower().startswith('documents/import'):
        return _say('shell_only', 'ייבוא מסמכים ממערכת אחרת נעשה מהמעטפת: ./bbox my-docs import-history', 403)
    # money path: any POST carrying an Idempotency-Key is a create the client wants deduped — a document,
    # a convert-into-new-draft, or a customer/item — so it is never created twice (double-click / re-send).
    if request.method == 'POST' and request.headers.get('Idempotency-Key', '').strip():
        return _idempotent_create(sub)
    url = f'{APITOOLS}/{sub}'
    fwd = {k: v for k, v in request.headers if k.lower() not in _HOP}
    try:
        r = requests.request(request.method, url, params=request.args,
                             data=request.get_data(), headers=fwd, stream=True, timeout=120)
    except requests.RequestException as e:
        return jsonify({'error': 'upstream_unreachable', 'message': str(e)}), 502
    out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    # apitools sends X-Frame-Options: DENY on every response; that blocks the SPA
    # from rendering a proxied PDF in its own (same-origin) preview iframe. Downgrade
    # to SAMEORIGIN so our drawer can frame it while cross-origin framing stays blocked.
    if any(k.lower() == 'x-frame-options' for k in out):
        out = {k: ('SAMEORIGIN' if k.lower() == 'x-frame-options' else v) for k, v in out.items()}
    return Response(r.iter_content(chunk_size=65536), status=r.status_code, headers=out)


@app.route('/', defaults={'p': 'index.html'})
@app.route('/<path:p>')
def spa(p):
    full = os.path.join(STATIC, p)
    resp = send_from_directory(STATIC, p) if os.path.isfile(full) \
        else send_from_directory(STATIC, 'index.html')   # SPA fallback
    # single-business app is updated in place — force browsers to revalidate
    # (ETag) so a rebuilt app.js/index.html is picked up, never served stale
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


if __name__ == '__main__':
    app.run('0.0.0.0', 8000)
