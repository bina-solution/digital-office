"""Static blueprint that serves the built Vite SPA at the app root (``/``).

The SPA is built with ``base: './'`` (relative hashed asset URLs), so serving
it at the root lets it work both standalone (``incoming.localhost/``) and
embedded same-origin in the console under ``/a/incoming/`` — where the console
injects ``<base href="/a/incoming/">`` and the relative asset/API URLs resolve
back through the proxy.

The Dockerfile copies the webapp's compiled `dist/` into a directory
specified by ``INCOMING_DOCS_WEBAPP_DIST`` (default
``/app/incoming_documents_dist``). The blueprint reads from there at
request time. Hashed asset filenames get long-cache; ``index.html`` and
the SPA fallback get ``no-cache`` so the latest deploy is always served.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, abort, send_from_directory


def _dist_dir() -> Path:
    return Path(
        os.getenv("INCOMING_DOCS_WEBAPP_DIST", "/app/incoming_documents_dist")
    )


def create_webapp_blueprint(*, url_prefix: str | None = None) -> Blueprint:
    # Mount at the app root by default so the SPA is reachable at ``/`` and, when
    # the console proxies ``/a/incoming/`` -> this service's ``/``, the SPA + its
    # relative assets resolve correctly. A ``url_prefix`` may still be passed to
    # mount it under a sub-path (e.g. in tests).
    base = "" if url_prefix is None else url_prefix
    bp = Blueprint(
        "incoming_documents_webapp_bp", __name__, url_prefix=base or None
    )

    @bp.get("/")
    def root():
        return _serve("index.html")

    # Catch-all: serve hashed static assets from dist, and fall back to
    # index.html for unknown paths so client-side deep-links survive a refresh.
    # More specific routes (the API blueprint at ``/incomingDocuments/…`` and the
    # app-level ``/health``) outrank this low-weight ``<path>`` rule in Werkzeug.
    @bp.get("/<path:subpath>")
    def any_path(subpath: str):
        return _serve(subpath)

    return bp


def _serve(subpath: str):
    dist = _dist_dir()
    if not dist.exists():
        abort(503, description="webapp bundle missing — run `vite build`")

    candidate = (dist / subpath).resolve()
    try:
        candidate.relative_to(dist.resolve())
    except ValueError:
        abort(404)

    if candidate.is_file():
        cache = "public, max-age=31536000, immutable" if "/assets/" in f"/{subpath}" else "no-cache"
        resp = send_from_directory(dist, subpath)
        resp.headers["Cache-Control"] = cache
        return resp

    # Vite emits RELATIVE asset URLs (base './', needed for the console's
    # <base href> embed), so a hard refresh on a NESTED route requests e.g.
    # /extraction/invoice/assets/index-*.js. Resolve any */assets/* tail back
    # to the real dist/assets file instead of falling through to index.html
    # (which would hand HTML to a <script type=module> and mount nothing).
    if "assets/" in subpath:
        tail = "assets/" + subpath.rsplit("assets/", 1)[1]
        deep = (dist / tail).resolve()
        try:
            deep.relative_to(dist.resolve())
            if deep.is_file():
                resp = send_from_directory(dist, tail)
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return resp
        except ValueError:
            pass

    # SPA fallback — anything unknown returns index.html so client-side
    # routing works on hard refresh.
    resp = send_from_directory(dist, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp
