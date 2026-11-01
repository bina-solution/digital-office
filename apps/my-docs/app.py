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
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

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


@app.route('/api/<path:sub>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def proxy(sub):
    """Forward /api/<sub> -> apitools/<sub>, streaming the response (PDFs included)."""
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
