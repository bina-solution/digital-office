"""my-docs — a thin production frontend service for the business-document API.

A small BFF: serves the SPA (static/) and proxies /api/* to apitools' /documents +
/docGen endpoints. Auth is handled upstream by Authentik forward-auth (Traefik
middleware) — this service just reads the identity headers Authentik injects and
exposes them at /api/me. No business logic here; the source of truth is apitools
+ Postgres/Supabase.
"""
import json
import os
import re
import threading
import time

import requests
from flask import Flask, request, Response, send_from_directory, jsonify

import errors_he

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
            return _unreachable(e)
        body, ct = _in_hebrew(r)
        if r.status_code < 400:                  # never cache a failed create — it should be retryable
            with _IDEM_GUARD:
                _IDEM[key] = (now, r.status_code, body, ct)
        out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP and k.lower() != 'content-type'}
        out['Content-Type'] = ct
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


def _unreachable(e, who='מאגר המסמכים'):
    """No answer: one Hebrew sentence on the screen, the exception in the log — never `requests`' English there
    (the code audit, A.7)."""
    app.logger.warning('my-docs: %s did not answer: %s', who, e)
    return _say('upstream_unreachable', f'{who} לא ענה — נסו שוב בעוד רגע', 502)


def _in_hebrew(r):
    """The ledger's answer as the screen gets it, (bytes, content type): a refusal's words in Hebrew with its own
    kept as `detail` (errors_he), and a refusal that is not JSON — a proxy's HTML 502 — made one, so the screen never
    reads «no answer» from an answer (A.8). Anything below 400 goes as it came."""
    ct = r.headers.get('Content-Type', 'application/json')
    if r.status_code < 400:
        return r.content, ct
    try:
        payload = r.json() if 'json' in ct else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        app.logger.warning('my-docs: the ledger answered %s, not JSON: %r', r.status_code, r.content[:300])
        payload = {'error': 'upstream_error'}
    return json.dumps(errors_he.body(payload, r.status_code, request.path), ensure_ascii=False).encode(), 'application/json'


def _days(v, default):
    """A link's term in days, 1–365 — or None when it is no number: a word, NaN, or 1e400 (JSON reads it as infinity,
    and int() of it raised OverflowError, a 500: the second reader). Said by the caller, never a 500."""
    try:
        return max(1, min(int(v or default), 365))
    except (TypeError, ValueError, OverflowError):
        return None


@app.post('/api/sign/<doc_id>')
def sign_start(doc_id):
    """Send an issued deal document for the customer's signature: its PDF becomes an esign envelope, the
    ledger records the send, and the screen gets the one link. Delivering the link is the owner's act."""
    body = request.get_json(force=True, silent=True) or {}
    signer = (body.get('signer') or '').strip()
    if not signer:
        return _say('no_signer', 'שם החותם חסר', 400)
    days = _days(body.get('days'), 14)               # before the reads: a bad term costs no two-minute PDF read
    if days is None:
        return _say('bad_days', 'תוקף הקישור הוא מספר ימים', 400)
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
    # `ref`: the ledger document the envelope is of — «חתימות» lists it under its document, never as a file of its
    # own (the reader of DGO-2169 step 4). _views() keeps only kind=view, so a signature with a ref is not a view link
    form = {'signer': signer, 'email': (body.get('email') or '').strip(), 'sender': sender, 'name': name,
            'days': str(days), 'ref': doc_id}
    if body.get('password'):
        form['password'] = str(body['password'])
    try:
        e = requests.post(f'{ESIGN}/api/envelopes', files={'file': (name, pdf.content, 'application/pdf')},
                          data=form, timeout=60)
        answer = e.json()
    except (requests.RequestException, ValueError):
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה', 502)
    if not answer.get('ok'):
        return _esign_refused(answer)
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


def _esign_refused(answer):
    """esign said no: a Hebrew sentence on the screen, its own words (English: «the file is not a PDF») in the log."""
    app.logger.warning('my-docs: esign refused: %s', (answer or {}).get('detail') or (answer or {}).get('message'))
    return _say('esign_refused', 'אפליקציית החתימות לא יצרה את הקישור — נסו שוב בעוד רגע', 502)


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
    """Cancel in the ledger, then close every open link of the document: a cancelled deal is not signed afterwards
    (DGO-2029, the second reader), and a cancelled document is not shown as if it stood — its VIEW links were left
    open, esign kept its own copy, and the customer went on seeing it for up to a year (the second reader of
    DGO-2047). The ledger's answer is the answer."""
    try:
        r = requests.post(f'{APITOOLS}/documents/{doc_id}/cancel', data=request.get_data(),
                          headers={'Content-Type': 'application/json'}, timeout=120)
    except requests.RequestException as e:
        return _unreachable(e)
    if r.status_code < 400:
        for env in _envelopes(doc_id) or []:
            if env.get('status') not in ('signed', 'cancelled', 'expired'):
                _close_envelope(env['id'], 'המסמך בוטל')
        for env in _views(doc_id) or []:
            if _state(env) in ('sent', 'opened'):
                _close_envelope(env['id'], 'המסמך בוטל')
        fill_bff.close_events(doc_id)            # and its «מילוי וחתימה» links (DGO-2139)
    content, ct = _in_hebrew(r)
    return Response(content, status=r.status_code, headers={'Content-Type': ct})


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


# ── living documents: a view link to send, the links a document went out in, and a draft whose view follows it ──────
# (DGO-2047, the owner: «מסמכים חיים שאפשר לשתף לערוך לשלוח קישור להחתמה»). A view link is esign's own envelope of
# kind `view` — the same one public door (/s/<token>), expiry, password and revoke as a signature, and never a
# signature. Its file is replaced when the draft behind it is saved or issued, so the customer's link shows the
# document as it now stands; a document out for SIGNATURE is never replaced under its signer (esign refuses it).

_TYPE_HE = {}


def _type_he(code):
    """A type's Hebrew name, as the house catalogue says it (read once); the code itself when it cannot be read."""
    if not _TYPE_HE:
        r = _ledger('docGen/house/types')
        try:
            for t in ((r.json() or {}).get('types') or []) if r is not None else []:
                _TYPE_HE[t['code']] = t.get('he') or t['code']
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    return _TYPE_HE.get(code) or code or 'מסמך'


def _view_name(doc):
    """What the customer's page and file call it: «הצעת מחיר QT-2026-00031 — קבוצת אורן.pdf» — never an id."""
    what = _type_he(doc.get('doc_type'))
    head = f"{what} {doc['doc_number']}" if doc.get('doc_number') else f'{what} (טיוטה)'
    return f"{head} — {doc.get('customer_name') or ''}".strip(' —') + '.pdf'


def _sender():
    biz = _ledger('business')
    return ((biz.json() or {}).get('name') if biz is not None else '') or 'הלשכה'


def _doc_pdf(doc):
    """The bytes a view link shows, exactly as the ledger serves them: a draft drawn now («טיוטה» on it), a deal
    document as issued, and a document of the books with its «מקור» on its first serving and «העתק» on every one
    after — the ledger decides which, once, so no link ever makes a second original (Instruction 36). The bytes are
    read once per link and kept by esign; opening the link again reads nothing from the ledger. None when not given."""
    r = _ledger(f"documents/{doc['id']}/download", timeout=120)
    return r.content if r is not None and r.content.startswith(b'%PDF') else None


def _esign_call(method, path, **kw):
    """esign's answer, (answered, data): data is its JSON `data` when it said yes, None when it refused; answered is
    False when it did not answer at all — «esign is down» is not «the link is closed» (the second reader)."""
    try:
        r = requests.request(method, f'{ESIGN}{path}', timeout=kw.pop('timeout', 30), **kw)
        j = r.json()
    except (requests.RequestException, ValueError):
        return False, None
    return True, (j.get('data') if isinstance(j, dict) and j.get('ok') else None)


def _esign(method, path, **kw):
    """esign's answer as its JSON `data`, or None when it does not answer or refuses."""
    return _esign_call(method, path, **kw)[1]


def _esign_up():
    """esign answers now — asked before a document of the books is read for a link, since that read spends its
    «מקור» (the second reader: a 502 after the read left the original served to nobody)."""
    try:
        return requests.get(f'{ESIGN}/healthz', timeout=5).status_code < 400
    except requests.RequestException:
        return False


def _views(doc_id):
    """The view links one document went out in (esign's envelopes of kind `view` whose ref is the document), newest
    first; None when esign does not answer."""
    data = _esign('GET', '/api/envelopes', params={'ref': doc_id, 'limit': 50}, timeout=15)
    if data is None:
        return None
    return [e for e in data.get('items') or [] if (e.get('kind') or 'sign') == 'view']


def _state(env):
    """An envelope as the screen says it: signed and cancelled stay; an open one past its date is `expired`."""
    st = env.get('status') or ''
    if st in ('signed', 'cancelled', 'declined'):
        return st
    if (env.get('expires_at') or '') and env['expires_at'] <= time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()):
        return 'expired'
    return st


def _follow(doc_id):
    """After a draft is saved or issued: every OPEN view link of it is given the document as it now stands. The save
    is the answer either way; this says how many links followed («2/2»), so the screen can tell."""
    views = [e for e in (_views(doc_id) or []) if _state(e) in ('sent', 'opened')]
    if not views:
        return '0/0'
    r = _ledger(f'documents/{doc_id}')
    if r is None:
        return f'0/{len(views)}'
    doc = r.json()
    name = _view_name(doc)
    # A draft's bytes are one drawing, the same for every link. An ISSUED document's are read once PER LINK: the
    # ledger serves a document of the books as «מקור» once and «העתק» after, so one read handed to every open link
    # put the original in two hands (the second reader of DGO-2047) — now the oldest link holds it, the rest a copy
    per_link = doc.get('status') != 'draft'
    pdf = None if per_link else _doc_pdf(doc)
    if not per_link and pdf is None:
        return f'0/{len(views)}'
    done = 0
    for e in sorted(views, key=lambda v: v.get('created_at') or ''):
        bytes_ = _doc_pdf(doc) if per_link else pdf
        if bytes_ is not None and _esign('PUT', f"/api/envelopes/{e['id']}/file",
                                         files={'file': (name, bytes_, 'application/pdf')},
                                         data={'name': name}, timeout=60) is not None:
            done += 1
    return f'{done}/{len(views)}'


@app.post('/api/share/<doc_id>')
def share_start(doc_id):
    """A view link to this document — for the customer, or anyone it is sent to: they open it without signing in,
    see it and download it; it signs nothing, ends on its date, and is closed from the drawer. A draft may be
    shared for a look before it is issued (it says «טיוטה»), and its link follows it until then."""
    body = request.get_json(force=True, silent=True) or {}
    r = _ledger(f'documents/{doc_id}')
    if r is None:
        return _say('not_found', 'המסמך לא נמצא', 404)
    doc = r.json()
    if doc.get('status') == 'cancelled':
        return _say('cancelled', 'המסמך בוטל', 409)
    days = _days(body.get('days'), 30)
    if days is None:
        return _say('bad_days', 'תוקף הקישור הוא מספר ימים', 400)
    if not _esign_up():                          # before the read: it may spend the «מקור» (the second reader)
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה — הקישור לא נוצר, והמסמך לא נקרא', 502)
    pdf = _doc_pdf(doc)
    if pdf is None:
        return _say('no_pdf', 'לא התקבל קובץ המסמך ממאגר המסמכים', 502)
    name = _view_name(doc)
    form = {'kind': 'view', 'ref': doc_id, 'signer': (body.get('to') or doc.get('customer_name') or '').strip(),
            'sender': _sender(), 'name': name, 'days': str(days)}
    if body.get('password'):
        form['password'] = str(body['password'])
    try:
        e = requests.post(f'{ESIGN}/api/envelopes', files={'file': (name, pdf, 'application/pdf')}, data=form,
                          timeout=60)
        answer = e.json()
    except (requests.RequestException, ValueError):
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה', 502)
    if not answer.get('ok'):
        return _esign_refused(answer)
    return jsonify({'ok': True, 'link': answer['data']['link'], 'envelope': answer['data']['envelope']})


@app.get('/api/links/<doc_id>')
def links_of(doc_id):
    """Every link this document went out in — to look at it and to sign it — each with its state, newest first.
    `ok` is false when esign did not answer: never an empty list that reads as «no links»."""
    views, signs = _views(doc_id), _envelopes(doc_id)
    rows = [dict(e, kind='view', state=_state(e)) for e in views or []] + \
           [dict(e, kind='sign', state=_state(e)) for e in signs or []]
    rows.sort(key=lambda e: e.get('created_at') or '', reverse=True)
    return jsonify({'ok': views is not None and signs is not None, 'links': rows})


@app.post('/api/links/<eid>/again')
def link_again(eid):
    """A link is never kept in the clear (esign stores its hash), so «the link again» is a NEW one — and the one
    handed out before stops working. The screen says so before it asks."""
    answered, data = _esign_call('POST', f'/api/envelopes/{eid}/link', data={'by': 'my-docs'})
    if not answered:
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה — לא נוצר קישור חדש', 502)
    if data is None:
        return _say('esign_refused', 'לא נוצר קישור חדש — ייתכן שהקישור סגור', 409)
    return jsonify({'ok': True, 'link': data.get('link'), 'envelope': data.get('envelope')})


@app.post('/api/links/<eid>/revoke')
def link_revoke(eid):
    """Close one link now: the page answers one sentence and serves no bytes. A signed envelope stays signed."""
    answered, data = _esign_call('POST', f'/api/envelopes/{eid}/cancel', data={'reason': 'הקישור בוטל מהמסמך'})
    if not answered:
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה — הקישור לא נסגר', 502)
    if data is None:
        return _say('esign_refused', 'הקישור לא בוטל — ייתכן שכבר נחתם', 409)
    return jsonify({'ok': True, 'envelope': data.get('envelope')})


# ── «חתימות» inside «מסמכים» (DGO-2169, step 4; the owner: «זה לא אמור להיות אפלקציה נפרדת זה הכל פיצר מובנה של
# מסמכים»). Every link the office sent — to sign, to fill and sign, to look — in one list, and a file of its own sent
# to be signed: what esign's separate screen did, so its tile can leave the home. esign keeps the links; this reads.
_ROW_STATE = {'signed': 'signed', 'cancelled': 'closed', 'declined': 'closed', 'expired': 'expired',
              'sent': 'sent', 'opened': 'opened', 'signing': 'signing'}
_LIST_ENVELOPES, _LIST_EVENTS = 300, 200            # what one reading takes; more than that is said, never cut silently
# esign's own limit (server.py MAX_UPLOAD, the same variable in both composes) is on the WHOLE request: the form's other
# fields and its boundaries take a little of it, so the file is held to the limit less a margin (the reader)
_MAX_FILE = int(os.getenv('ESIGN_MAX_UPLOAD', str(40 * 1024 * 1024))) - 64 * 1024


def _doc_titles():
    """{ledger id: «הצעת מחיר 10001 — קבוצת אורן»} for the documents a link can belong to; {} when the ledger is silent."""
    r = _ledger('documents', params={'limit': 500})
    out = {}
    for d in (r.json() if r is not None else None) or []:
        if isinstance(d, dict) and d.get('id'):
            head = ' '.join(x for x in (_type_he(d.get('doc_type')), d.get('doc_number') or '') if x)
            out[d['id']] = f"{head} — {d['customer_name']}" if d.get('customer_name') else head
    return out


def _fill_row(ev, titles):
    """A «מילוי וחתימה» event as a row: its state from its sides (one opened or signed → «נפתח»), its parties counted."""
    parties = ev.get('parties') or []
    signed = sum(1 for p in parties if p.get('state') == 'signed')
    st = ev.get('status')
    if st in ('complete', 'completing'):
        state = 'signed'
    elif st == 'cancelled':
        state = 'closed'
    elif (ev.get('expires') or '9999') < time.strftime('%Y-%m-%d', time.gmtime()):
        state = 'expired'                            # (esign shows the date alone: a link dead since this morning
        #                                              still reads open until the day turns — said, not hidden)
    else:
        state = 'opened' if any(p.get('state') in ('filling', 'signed') for p in parties) else 'sent'
    return {'id': ev.get('id'), 'kind': 'fill', 'ref': ev.get('ref'), 'doc': titles.get(ev.get('ref')),
            'name': ev.get('doc_name') or ev.get('title'), 'who': ', '.join(p.get('signer') or p.get('label') or ''
                                                                            for p in parties if p.get('signer') or p.get('label')),
            'state': state, 'signed': signed, 'parties': len(parties), 'created_at': ev.get('created_at'),
            'signed_at': ev.get('completed_at'), 'expires_at': ev.get('expires')}


@app.get('/api/signatures')
def signatures():
    """Every link, newest first, each with the document it belongs to when it belongs to one. `ok` is false when
    esign did not answer — never an empty list that reads as «nothing was sent»."""
    answered, data = _esign_call('GET', '/api/envelopes', params={'limit': _LIST_ENVELOPES}, timeout=20)
    try:
        f = requests.get(f'{ESIGN}/api/events', params={'limit': _LIST_EVENTS}, timeout=20)
        fills = (f.json() or {}).get('items') if f.ok else None
    except (requests.RequestException, ValueError):
        fills = None
    if not answered or data is None or fills is None:
        return jsonify({'ok': False, 'links': [], 'message': 'אפליקציית החתימות לא ענתה — הרשימה לא נטענה'})
    titles = _doc_titles()
    envs = data.get('items') or []
    # a DRAFT was never sent: «מילוי וחתימה» makes one each time its editor opens on new bytes, and the drawer hides
    # it — listed, it read «נשלח» and counted as waiting for a link that never existed (the reader)
    rows = [{'id': e.get('id'), 'kind': e.get('kind') or 'sign', 'ref': e.get('ref'), 'doc': titles.get(e.get('ref')),
             'name': e.get('doc_name'), 'who': e.get('signer_name') or '', 'state': _ROW_STATE.get(_state(e), 'sent'),
             'created_at': e.get('created_at'), 'opened_at': e.get('opened_at'), 'signed_at': e.get('signed_at'),
             'expires_at': e.get('expires_at'), 'password': bool(e.get('password'))}
            for e in envs if e.get('status') != 'draft']
    rows += [_fill_row(ev, titles) for ev in fills or [] if ev.get('status') != 'draft']
    rows.sort(key=lambda r: r.get('created_at') or '', reverse=True)
    # a reading full to its limit may hold more: the screen says «האחרונים», never a count that stops being true
    more = len(envs) >= _LIST_ENVELOPES or len(fills or []) >= _LIST_EVENTS
    return jsonify({'ok': True, 'links': rows, 'more': more})


@app.post('/api/signatures/file')
def sign_a_file():
    """«חתימה על קובץ»: a PDF the office was given — a lease, a form — goes out to be signed on esign's one link, as
    esign's own screen did before it left the home. The link is handed back; sending it is the owner's act."""
    up = request.files.get('file')
    if up is None:
        return _say('no_file', 'לא נבחר קובץ', 400)
    raw = up.read(_MAX_FILE + 1)
    if len(raw) > _MAX_FILE:                         # esign refuses it with an HTML 413 the screen read as «no answer»
        return _say('too_big', 'הקובץ גדול מדי — עד %d MB' % max(1, _MAX_FILE // (1024 * 1024)), 413)
    if not raw.startswith(b'%PDF'):
        return _say('not_pdf', 'הקובץ אינו PDF — חותמים על קובץ PDF', 415)
    signer = (request.form.get('signer') or '').strip()
    if not signer:
        return _say('no_signer', 'שם החותם חסר', 400)
    days = _days(request.form.get('days'), 14)
    if days is None:
        return _say('bad_days', 'תוקף הקישור הוא מספר ימים', 400)
    name = os.path.basename(up.filename or '') or 'מסמך לחתימה.pdf'
    form = {'kind': 'sign', 'signer': signer, 'email': (request.form.get('email') or '').strip(), 'sender': _sender(),
            'name': name, 'days': str(days)}
    if request.form.get('password'):
        form['password'] = str(request.form['password'])
    try:
        e = requests.post(f'{ESIGN}/api/envelopes', files={'file': (name, raw, 'application/pdf')}, data=form,
                          timeout=60)
        answer = e.json()
    except (requests.RequestException, ValueError):
        return _say('esign_unreachable', 'אפליקציית החתימות לא ענתה — הקישור לא נוצר', 502)
    if not answer.get('ok'):
        return _esign_refused(answer)
    return jsonify({'ok': True, 'link': answer['data']['link'], 'envelope': answer['data']['envelope']})


def _relay(method, sub):
    """This request, forwarded to the ledger as it came; the ledger's answer (or None when it did not answer)."""
    fwd = {k: v for k, v in request.headers if k.lower() not in _HOP}
    try:
        return requests.request(method, f'{APITOOLS}/{sub}', params=request.args, data=request.get_data(),
                                headers=fwd, timeout=120)
    except requests.RequestException:
        return None


def _answer(r, followed=None):
    content, ct = _in_hebrew(r)
    resp = Response(content, status=r.status_code, headers={'Content-Type': ct})
    if followed is not None:
        resp.headers['X-Views-Followed'] = followed
    return resp


@app.patch('/api/documents/<doc_id>')
def save_draft(doc_id):
    """Save a draft where it is (the ledger merges the model and counts again), then its open view links follow."""
    r = _relay('PATCH', f'documents/{doc_id}')
    if r is None:
        return _say('upstream_unreachable', 'מאגר המסמכים לא ענה', 502)
    return _answer(r, _follow(doc_id) if r.status_code < 400 else None)


@app.post('/api/documents/<doc_id>/issue')
def issue_document(doc_id):
    """Issue a draft (number, signature, the stored original), then its open view links show the issued document."""
    r = _relay('POST', f'documents/{doc_id}/issue')
    if r is None:
        return _say('upstream_unreachable', 'מאגר המסמכים לא ענה', 502)
    return _answer(r, _follow(doc_id) if r.status_code < 400 else None)


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


# THE SCREEN'S OWN PATHS, each with the methods the screen uses, and nothing else of apitools (the code audit, B: the
# proxy passed any path and any method — apitools' OCR, its image tools, all of it — with the browser's cookies).
# Every other call of the screen has a route of its own above (signing, links, «חתימות», the archive, «מילוי וחתימה»),
# a draft's save (PATCH) and its issue and cancel too. Each path whole, not by its start: `documents` let through the
# ledger's allocation number and its consent, which neither the screen nor the CLI calls (the second reader).
_ID = r'[A-Za-z0-9_-]+'
_PROXY_ALLOW = ((r'documents(/%s(/(events|preview|download))?)?' % _ID, {'GET'}),   # `verify` too: the CLI's
                (r'documents(/%s/(convert|send|pay))?' % _ID, {'POST'}),           # a new one, the next, its marks
                (r'(customers|items)', {'GET', 'POST'}),
                (r'(customers|items)/%s' % _ID, {'GET', 'PATCH', 'DELETE'}),
                (r'business', {'GET', 'PUT'}),
                (r'docGen/house(/.+)?', {'GET', 'POST'}))                          # types, a template, the fonts


def _proxy_allows(sub, method):
    segs = sub.strip('/').split('/')
    # a dot segment is refused before the path is read: requests collapses it before it sends, and
    # `documents/../documentOcr` passed as a document's path and went out as apitools' OCR (the second reader)
    if any(s in ('.', '..') for s in segs):
        return False
    s = '/'.join(segs)
    return any(method in m and re.fullmatch(p, s) for p, m in _PROXY_ALLOW)


@app.route('/api/<path:sub>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def proxy(sub):
    """Forward /api/<sub> -> apitools/<sub>, streaming the response (PDFs included) — the screen's own paths only."""
    # the history import writes issued documents and their statuses: it is the shell's alone
    # (`./bbox my-docs import-history`, which calls the ledger itself), never a browser's (DGO-2042, the fifth reader)
    if sub.strip('/').lower().startswith('documents/import'):
        return _say('shell_only', 'ייבוא מסמכים ממערכת אחרת נעשה מהמעטפת: ./bbox my-docs import-history', 403)
    if not _proxy_allows(sub, request.method):
        return _say('not_here', 'הכתובת הזאת אינה של «מסמכים»', 404)
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
        return _unreachable(e)
    if r.status_code >= 400:                     # a refusal is small: read whole, said in Hebrew (A.7)
        content, ct = _in_hebrew(r)
        return Response(content, status=r.status_code, headers={'Content-Type': ct})
    out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    # apitools sends X-Frame-Options: DENY on every response; that blocks the SPA
    # from rendering a proxied PDF in its own (same-origin) preview iframe. Downgrade
    # to SAMEORIGIN so our drawer can frame it while cross-origin framing stays blocked.
    if any(k.lower() == 'x-frame-options' for k in out):
        out = {k: ('SAMEORIGIN' if k.lower() == 'x-frame-options' else v) for k, v in out.items()}
    return Response(r.iter_content(chunk_size=65536), status=r.status_code, headers=out)


# «מילוי וחתימה» (DGO-2139): one link for every party of a document — the routes are fill_bff.py's
import fill_bff  # noqa: E402
fill_bff.register(app, ledger=_ledger, say=_say, signable=SIGNABLE, esign=ESIGN, apitools=APITOOLS, hop=_HOP)


# The page's <base> is the prefix it is served under. The screen keeps its place in the address bar (`doc/<id>`,
# history.pushState) and calls its API by RELATIVE urls (`api/…`), which a browser resolves against the base: with no
# <base>, a document opened at `/doc/<id>` sent «שליחה לחתימה» to `/doc/api/sign/<id>` — 405, «הקישור לא נוצר — הבקשה
# נדחתה» — and every load to `/doc/api/…`, the page itself, «הנתונים לא נטענו» (the owner's phone, 2026-11-22 12:12Z,
# DGO-2167: the HP's door recorded `POST /doc/api/sign/doc_74aff3f899bb4c5b 405`). The console injects a <base> only
# where it serves the app under `/a/<alias>/`; at its own host (a phone's full screen, a link) nobody did. A deep link
# (`/doc/<id>` opened cold) also loaded `doc/app.js` — the page again. The prefix comes from X-Forwarded-Prefix (the
# console's `/a/<alias>`); a value that is not a plain path is not trusted, and the page then lives at `/`.
_PREFIX = re.compile(r'^(/[A-Za-z0-9._~-]+)*$')


def _page():
    prefix = (request.headers.get('X-Forwarded-Prefix') or '').rstrip('/')
    if not _PREFIX.fullmatch(prefix):          # fullmatch: `$` alone lets a trailing newline through (the reader)
        prefix = ''
    with open(os.path.join(STATIC, 'index.html'), encoding='utf-8') as f:
        html = f.read()
    if '<base ' not in html.lower():
        # `<head>` itself, never `<header`, should the page's own head tag ever go
        html = re.sub(r'(<head(?:\s[^>]*)?>)', r'\1<base href="' + prefix + '/">', html, count=1, flags=re.I)
    resp = Response(html, content_type='text/html; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/', defaults={'p': 'index.html'})
@app.route('/<path:p>')
def spa(p):
    full = os.path.join(STATIC, p)
    if p == 'index.html' or not os.path.isfile(full):
        return _page()                          # the page, at any route of the screen (SPA fallback), with its <base>
    resp = send_from_directory(STATIC, p)
    # single-business app is updated in place — force browsers to revalidate
    # (ETag) so a rebuilt app.js/index.html is picked up, never served stale
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


if __name__ == '__main__':
    app.run('0.0.0.0', 8000)
