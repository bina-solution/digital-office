"""entities — «ישויות»: everyone the business deals with, people and organizations, and the roles each holds (DGO-2101).

The office's domains (ai/context/business-domains.md): «זהות» is the business itself (digital-assets, brand.v1);
«ישויות» is everyone else; «מסמכים» holds documents only and names its parties by their id here, keeping a snapshot
of each when it issues. This app is the one place a customer, a supplier, a company, a salesperson or a contact
person is defined — no other app keeps a table of them.

The model (patterns.py, store.py): an entity is a person or an organization; it holds roles («דפוסים»): company,
customer, supplier, salesperson, contact — each with its own fields; relations link a person to an organization (a
title) and a salesperson to a customer. `party(id)` is the block a document prints.

Who may call (the office's one door for a Python app, platform-base/forward-auth/signin.py):
  * the app's own CLI, inside its container (loopback) — `bbox entities …` (hooks/cli → cli.py);
  * a service with the app's token (`Authorization: Bearer`, ENTITIES_API_TOKEN, minted per office by
    scripts/env-secrets.py) — the documents' ledger, an n8n flow;
  * a PERSON who is an admin of the office: the screen and its reads, and the changes the screen makes
    (`person_writes`, JSON only). Nobody else: the people a business works with are not open to every container.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

import patterns
import store

sys.path.insert(0, "/opt/dgo")                              # the office's door, built into the image (Dockerfile)
import signin  # noqa: E402

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
TOKEN = os.environ.get("ENTITIES_API_TOKEN", "")


class _Under:
    """`path in it`: the screen's own files and everything under the given prefixes."""

    def __init__(self, exact: set[str], prefixes: tuple[str, ...]):
        self.exact, self.prefixes = exact, prefixes

    def __contains__(self, path) -> bool:
        return path in self.exact or any(str(path).startswith(p) for p in self.prefixes)


PERSON_READS = _Under({"/", "/app.css", "/app.js"}, ("/api/", "/r/", "/e/"))
PERSON_WRITES = _Under(set(), ("/api/entities", "/api/relations"))
WORDS = signin.Words(
    title="ישויות",
    no_grant="«ישויות» פתוחה למנהלי הלשכה. מנהל יכול לפתוח לך אותה.",
    no_session="הכניסה שלך ללשכה לא אומתה. «ישויות» נפתחת מתוך הלשכה, למי שמחובר אליה.",
    api_no_grant="«ישויות» is read and changed by the office's admins",
    api_no_session="entities answers its own CLI and a caller with its token")
SIGNIN = signin.SignIn(os.environ.get("ENTITIES_WHOAMI_URL", signin.WHOAMI_URL))

app = FastAPI(title="entities", docs_url=None, redoc_url=None, openapi_url=None)
app.middleware("http")(signin.door(SIGNIN, token=lambda: TOKEN, loopback_env="ENTITIES_TRUST_LOOPBACK",
                                   person_reads=PERSON_READS, person_writes=PERSON_WRITES, words=WORDS))


@app.on_event("startup")
def _startup() -> None:
    store.init()


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def _actor(request: Request) -> str:
    """Who made the change, from what proved it — never from what the caller says alone: the admin the door let in
    (by name), a service with the token (and the name it gives itself, `X-Actor`), or the app's own CLI."""
    person = request.scope.get("dgo.person")
    if person:
        return f"{person} (המסך)"
    if signin.bearer_ok(request.headers.get("authorization"), TOKEN):
        said = (request.headers.get("x-actor") or "").strip()[:40]
        return f"service:{said}" if said else "service"
    return "cli"


async def _body(request: Request) -> dict | JSONResponse:
    """A change is JSON or nothing — the media type exactly, not a text that contains it («text/plain;
    charset=application/json» is a type a page of another site may send unasked, with the admin's cookie)."""
    ctype = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype != "application/json":
        return _err("a change is sent as JSON (content-type: application/json)", 415)
    try:
        body = await request.json()
    except ValueError:
        return _err("the body is not JSON")
    return body if isinstance(body, dict) else _err("the body is a JSON object")


async def _run(fn, *args, **kw):
    try:
        return await run_in_threadpool(fn, *args, **kw)
    except store.Refused as e:
        return _err(str(e))
    except LookupError as e:
        return _err(f"no such entity or relation: {e}", 404)


# ── the screen ───────────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def screen():
    return FileResponse(STATIC / "index.html")


@app.get("/r/{role}")
@app.get("/e/{eid}")
def screen_at(role: str = "", eid: str = ""):
    """A link to a list (r/<role>) or to one entity's card (e/<id>) opens the screen there (G83)."""
    return FileResponse(STATIC / "index.html")


@app.get("/app.css")
def css():
    return FileResponse(STATIC / "app.css", media_type="text/css")


@app.get("/app.js")
def js():
    return FileResponse(STATIC / "app.js", media_type="text/javascript")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "entities"}


# ── entities.v1 ──────────────────────────────────────────────────────────────────────────────────────
@app.get("/api/patterns")
def api_patterns():
    return patterns.as_json()


@app.get("/api/entities")
async def api_list(role: str = "", q: str = "", kind: str = "", archived: int = 0):
    return {"entities": await run_in_threadpool(store.listing, role, q, kind, bool(archived))}


@app.post("/api/entities")
async def api_create(request: Request):
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b
    return await _run(store.create, b.get("kind", ""), b.get("name", ""), b.get("fields"), b.get("roles"),
                      actor=_actor(request), source=str(b.get("source") or ""))


@app.get("/api/entities/{eid}")
async def api_get(eid: str):
    e = await run_in_threadpool(store.view, eid)
    return e if e else _err(f"no such entity: {eid}", 404)


@app.patch("/api/entities/{eid}")
async def api_update(eid: str, request: Request):
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b
    return await _run(store.update, eid, b.get("name"), b.get("fields"), actor=_actor(request), kind=b.get("kind"))


@app.put("/api/entities/{eid}/roles/{role}")
async def api_set_role(eid: str, role: str, request: Request):
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b
    return await _run(store.set_role, eid, role, b.get("fields"), actor=_actor(request))


@app.delete("/api/entities/{eid}/roles/{role}")
async def api_remove_role(eid: str, role: str, request: Request):
    return await _run(store.remove_role, eid, role, actor=_actor(request))


@app.post("/api/entities/{eid}/archive")
async def api_archive(eid: str, request: Request):
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b
    return await _run(store.archive, eid, bool(b.get("archived", True)), actor=_actor(request))


@app.get("/api/entities/{eid}/party")
async def api_party(eid: str):
    return await _run(store.party, eid)


@app.get("/api/parties")
async def api_parties(role: str = "", q: str = ""):
    """Every entity the list shows (by role, by search), each as a document prints it — the documents' picker."""
    return {"parties": await run_in_threadpool(store.parties, role, q)}


@app.post("/api/relations")
async def api_relate(request: Request):
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b
    return await _run(store.relate, b.get("from", ""), b.get("to", ""), b.get("kind", ""), b.get("title", ""),
                      actor=_actor(request))


@app.delete("/api/relations/{rid}")
async def api_unrelate(rid: str, request: Request):
    r = await _run(store.unrelate, rid, actor=_actor(request))
    return r if isinstance(r, JSONResponse) else {"ok": True}


@app.get("/api/events")
async def api_events(entity: str = "", limit: int = 50):
    return {"events": await run_in_threadpool(store.events, entity, limit)}


@app.post("/api/import")
async def api_import(request: Request):
    """Many entities at once, each with its `source` («ledger:cus_…»): a second run keeps nothing twice."""
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b
    if not isinstance(b.get("rows"), list):
        return _err("rows: a list of entities, each naming its source")
    # in one worker thread, whole: a SQLite connection belongs to the thread that opened it (store.conn)
    return await _run(store.import_rows, b["rows"], actor=_actor(request))
