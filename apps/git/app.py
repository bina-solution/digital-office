"""git — the office's git accounts, as ONE platform service.

What this app is
----------------
The office acts on GitHub and GitLab with the OWNER's identity: it opens issues, creates projects,
raises PR/MR, publishes releases — and, through the proxy in proxy.py, clones and pushes real code.
Before this app, every one of those actions needed a token in someone's shell, which meant the
credential lived in a file on a machine and in whatever got printed that day.

Where the facts live (and where they deliberately do not)
--------------------------------------------------------
EVERY account is a connection INSTANCE in the credential plane (platform-base/connections), protocol
`git_github_token` or `git_gitlab_token`, secret `{token, host?, namespace?}`. That is the whole
design, and it is the same one drive, mail and computers use (ai/context/platform-service-contract.md
§1): the vault is the one copy of the account, the console renders its switcher from the service
contract, and this app holds no token in its config, its environment or its volume. The only thing it
persists is which account is ACTIVE, and even that is a pointer.

Two doors, one contract
-----------------------
  * the platform service contract (§2): /manifest, /readyz, /connections, /connections/select,
    /providers — what the console's account bar and connect wizard are built from;
  * the canonical op surface: POST /<op> with `{…params, account?}` — provider-agnostic
    (repos, issues, PR/MR, releases, branches, files), so a consumer never learns whether the account
    behind it is GitHub or GitLab.

And one door that is not an op at all: /git/<gh|gl>/<account>/<owner>/<repo>.git, the smart-HTTP
remote a real `git` client talks to, so the agent can clone and push without ever holding a token.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import accounts
import credentials
import mirrors
import proxy
import repoindex
from adapters import GitError, adapter_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("git")

DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "bina-deployment")
READONLY_OPS = {"createRepo", "deleteRepo", "createIssue", "updateIssue", "commentIssue",
                "createPR", "mergePR", "commentPR", "submitReview", "createRelease",
                "deleteRelease", "putFile", "createBranch"}

_STATIC = Path(__file__).parent / "static"

app = FastAPI(title="git", docs_url=None, redoc_url=None)
app.include_router(proxy.router, prefix="/git")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """An unexpected failure answers JSON, never a bare "Internal Server Error".

    Written after a real one: `mergePR` had a two-names-one-variable bug in its own argument check
    and every call returned Starlette's plain-text 500 with the traceback only in the container log —
    so a caller (an agent, the console, another app) saw a failure with no cause and no op name. The
    sentence names the op and the exception type; the traceback still goes to the log, where it is
    actionable.
    """
    log.exception("unhandled error in %s %s", request.method, request.url.path)
    return JSONResponse(
        {"ok": False, "op": request.url.path.strip("/"), "error":
         "שגיאה פנימית בטיפול בבקשה — הפרטים בלוג של השירות."},
        status_code=500)

# ── health / contract ────────────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "git"}


@app.get("/manifest")
def manifest():
    """The platform service contract (§2). `protocols` is what this service can connect; the console
    builds its connect wizard from /providers and its account bar from /connections — never from a
    list inside the console."""
    insts, err = accounts.vault_list()
    active = accounts.active_id()
    return {
        "service": "git",
        "protocols": accounts.OWNED_PROTOCOLS,
        "providers": [p["id"] for p in accounts.PROVIDERS],
        "ops": sorted(OPS),
        "connection": {"active": active},
        "capabilities": {
            "multi_connection": True,
            "smart_http_proxy": True,
            "remote_template": "http://git:8978/git/<gh|gl|any|lc>/<account>/<owner>/<repo>.git",
            "vault_available": err is None,
            "vault_error": err,
            "accounts": len(insts) if err is None else None,
            # The office's own forge, and the only funded answer to "where do I SEE all of this".
            # `local_forge.public` is the browser origin; `internal` is what an op calls.
            "local_forge": {"provider": "forgejo",
                            "internal": mirrors.internal_base(),
                            "public": mirrors.public_base()},
            "mirrors": len(mirrors.load()),
            "display_provider": "forge",
        },
    }


@app.get("/readyz")
def readyz():
    """Ready = the vault is up AND at least one account is VERIFIED (its token answers whoami).

    "One account connected but its token is dead" is not ready: every op would 401, and reporting
    ready there would make the platform's own health the last place the problem shows up.
    """
    insts, err = accounts.vault_list()
    if err:
        return JSONResponse({"ready": False, "reason": err}, status_code=503)
    if not insts:
        return JSONResponse({"ready": False,
                             "reason": "לא מחובר אף חשבון Git — חבר חשבון במסך „ניהול גרסאות”."},
                            status_code=503)
    active = accounts.active_id() or insts[0]["id"]
    inst = next((i for i in insts if i.get("id") == active), insts[0])
    probe = accounts.probe_instance(inst, accounts.vault_secret(inst["id"]) or {})
    if probe.get("git_only"):
        return {"ready": True, "connection_id": inst["id"], "login": None,
                "code_only": True, "accounts": len(insts)}
    if not probe.get("ok"):
        return JSONResponse({"ready": False, "reason": probe.get("reason") or "החשבון אינו מאומת",
                             "connection_id": inst["id"]}, status_code=503)
    return {"ready": True, "connection_id": inst["id"], "login": probe.get("login"),
            "accounts": len(insts)}


@app.get("/providers")
def providers():
    """The service's OWN provider catalogue (§4b: the owner picks a PROVIDER, never a protocol)."""
    return {"providers": accounts.PROVIDERS}


# ── the account surface (what the console's account bar reads) ────────────────────────────────────
@app.get("/connections")
def connections_list(probe: int = 1):
    insts, err = accounts.vault_list()
    if err:
        return JSONResponse({"active": None, "connections": [], "reason": err}, status_code=200)
    rows = []
    for i in insts:
        if probe:
            rows.append(accounts.account_row(i))
        else:
            rows.append({"id": i.get("id"), "label": i.get("label"),
                         "provider": accounts.provider_kind(i.get("protocol") or "")[0],
                         "account_hint": i.get("account_hint") or "", "state": "unknown"})
    rows.sort(key=lambda r: (not r.get("ok"), r.get("label") or ""))
    active = accounts.active_id()
    if active and not any(r["id"] == active for r in rows):
        active = None
    return {"active": active, "connections": rows, "protocols": accounts.OWNED_PROTOCOLS}


@app.post("/connections/select")
async def connections_select(request: Request):
    body = (await request.json()) if await request.body() else {}
    cid = (body or {}).get("id")
    inst, sec, err = accounts.resolve(cid or "")
    if err:
        return JSONResponse({"error": err}, status_code=404)
    accounts.set_active(inst["id"])
    return {"ok": True, "active": inst["id"], "label": inst.get("label"),
            "login": accounts.probe_instance(inst, sec or {}).get("login")}


@app.post("/connections")
async def connections_add(request: Request):
    body = (await request.json()) if await request.body() else {}
    return await api_accounts_post(body or {})


@app.delete("/connections/{cid}")
async def connections_delete(cid: str):
    return await api_accounts_delete(cid)


@app.post("/connections/{cid}/probe")
async def connections_probe(cid: str):
    return await api_accounts_probe(cid)


# ── accounts, as the UI uses them ────────────────────────────────────────────────────────────────
@app.get("/api/accounts")
def api_accounts(probe: int = 1):
    return connections_list(probe)


@app.post("/api/accounts")
async def api_accounts_post(request: Request):
    """Connect an account: provider + method → the secret → VERIFY → store.

    The order matters and is the whole point of §4b: the token is proven against the provider BEFORE
    it is written to the vault, so a connection is never "added" — it is verified. A token that does
    not answer `whoami` is rejected here, with the provider's own reason, instead of becoming a red
    row that fails later in the middle of a push.
    """
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    provider = (body.get("provider") or "").strip()
    method_id = (body.get("method") or "").strip()
    label = (body.get("label") or "").strip()
    if not accounts.provider_entry(provider):
        return JSONResponse({"error": f"ספק לא מוכר: {provider!r}"}, status_code=400)
    method = accounts.auth_method(provider, method_id)
    if not method:
        return JSONResponse({"error": f"שיטת חיבור לא מוכרת: {method_id!r}"}, status_code=400)
    kind = method.get("kind") or "pat"
    protocol = method.get("protocol") or accounts.protocol_of(provider, kind)

    secret: dict = {"kind": kind}
    for f in (method.get("fields") or []):
        val = body.get(f["name"])
        if isinstance(val, str) and val.strip():
            secret[f["name"]] = val.strip() if f["name"] != "private_key" else val
    for field in method.get("needs") or []:
        if not secret.get(field):
            return JSONResponse({"error": f"חסר שדה חובה: {field}"}, status_code=400)
    if body.get("readonly"):
        secret["readonly"] = True

    # VERIFY BEFORE STORING — a connection is never merely "added" (§4b). A code-only credential has
    # no API to verify against, and that is stated rather than dressed up as a pass.
    who: dict = {}
    verified = False
    if method.get("kind") in credentials.API_KINDS:
        try:
            adapter = adapter_for(provider, secret)
            who = adapter.whoami()
            verified = True
        except GitError as e:
            return JSONResponse({"verified": False, **e.body()}, status_code=e.status)

    host = secret.get("host") or ("github.com" if provider == "github" else "gitlab.com")
    account_hint = who.get("login") or secret.get("username") or ""
    if account_hint:
        account_hint = f"{account_hint}@{host}"
    default_label = f"{provider}: {who.get('login') or secret.get('username') or host}"
    if kind in ("deploy_token", "generic_token"):
        default_label = f"{provider}: {secret.get('namespace') or host}"
    stored, status = accounts.vault_add(protocol, label or default_label, secret, account_hint)
    if status >= 300:
        return JSONResponse({"verified": verified, "stored": False,
                             "error": stored.get("error") or "שמירת החשבון בוולט נכשלה",
                             "detail": stored}, status_code=status)
    cid = stored.get("id")
    if not accounts.active_id():
        accounts.set_active(cid)
    accounts.forget_probe(cid)
    return {"ok": True, "verified": verified, "stored": True, "id": cid,
            "protocol": protocol, "kind": kind,
            "login": who.get("login"), "scopes": who.get("scopes"),
            "capabilities": who.get("capabilities") or {},
            "note": None if verified else
                    "חיבור לקוד בלבד — אין API לאימות; יאומת בפעולת ה-git הראשונה.",
            "active": accounts.active_id()}


@app.get("/api/accounts/{cid}/probe")
async def api_accounts_probe(cid: str):
    inst, sec, err = accounts.resolve(cid)
    if err:
        return JSONResponse({"error": err}, status_code=404)
    accounts.forget_probe(cid)
    return {"id": cid, **accounts.probe_instance(inst, sec or {}, max_age=0)}


@app.delete("/api/accounts/{cid}")
async def api_accounts_delete(cid: str):
    inst, _sec, err = accounts.resolve(cid)
    if err:
        return JSONResponse({"error": err}, status_code=404)
    out, status = accounts.vault_delete(cid)
    if status < 300:
        accounts.forget_probe(cid)
        if accounts.active_id() == cid:
            rest, _ = accounts.vault_list()
            accounts.set_active(rest[0]["id"] if rest else None)
    return JSONResponse(out or {"ok": status < 300}, status_code=status)


# ── mirrors: external repositories, made visible in the office's own forge ────────────────────────
#
# The one screen the owner asked for is the FORGE's screen — every repository, local and external,
# rendered by Forgejo. What this service adds is the missing half: it COPIES an external repository
# into the forge (see mirrors.py for why the copy runs here and not in Forgejo's native mirror), and
# it never puts a provider token anywhere near Forgejo's database.
#
# Every route here is a `def`, never `async def`: a clone takes minutes and FastAPI runs a plain
# `def` endpoint in the threadpool, so a slow sync cannot freeze the health check or the account bar
# (the failure mode apps/domains wrote down after a 40s panel read froze its whole event loop).
def _forge_card() -> dict:
    """Is the local forge up, where is it, and how does the owner get in. Never raises."""
    import httpx
    base = mirrors.public_base()
    internal = (os.environ.get("FORGE_URL") or "http://forge:3000").rstrip("/")
    up, detail = False, ""
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{internal}/api/healthz")
        up = r.status_code == 200
        detail = "" if up else f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        detail = type(e).__name__
    return {"up": up, "detail": detail, "url": base, "internal": internal,
            "account": next((i["id"] for i in (accounts.vault_list()[0] or [])
                             if (i.get("protocol") or "") == "git_forge_local"), None)}


@app.get("/api/repos")
def api_repos(account: str = "", q: str = "", limit: int = 100, refresh: int = 0):
    """EVERY repository the office can act on, in one list — the app's home screen.

    This is the call that makes the app a repository browser rather than a settings panel: GitHub's
    repositories, GitLab's and the ones in the office's own forge, each tagged with the account it
    came from and marked when a local mirror of it exists. An account that fails is reported BESIDE
    the others (see repoindex.py) instead of emptying the screen.
    """
    return repoindex.index(account=account, q=q, limit=max(1, min(limit, 200)),
                           refresh=bool(refresh))


@app.get("/api/repo")
def api_repo(account: str = "", repo: str = "", ref: str = ""):
    """One repository's page in one call: its metadata, its branches, its recent commits, the root
    listing and its README — each section carrying its OWN error.

    Written as an aggregate because the alternative is five round trips from a browser that then has
    to decide what to show while four of them are in flight; here the screen can render the moment
    the slowest part answers, and a repository that has no README is not an error at all.
    """
    inst, sec, err = accounts.resolve(account or "")
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=409)
    if not repo:
        return JSONResponse({"ok": False, "error": "חסר repo."}, status_code=400)
    out: dict = {"ok": True, "account": inst.get("id"), "repo": repo, "sections": {}}
    try:
        ad = accounts.adapter_for_instance(inst, sec or {})
    except Exception as e:                          # noqa: BLE001
        return JSONResponse({"ok": False, "error": getattr(e, "he_message", None) or str(e)},
                            status_code=409)
    branch = ref

    def section(name: str, fn):
        try:
            out["sections"][name] = fn()
        except Exception as e:                      # noqa: BLE001 — reported per section
            out["sections"][name] = None
            out.setdefault("errors", {})[name] = getattr(e, "he_message", None) or str(e)

    section("meta", lambda: ad.get_repo(repo))
    meta = out["sections"].get("meta")
    if not isinstance(meta, dict):
        # FAIL FAST on the repository itself. Its metadata is the one section nothing else can work
        # without, and answering `ok: true` with five empty sections and a per-section error costs
        # FOUR more provider calls to say what the first one already said — against a rate limit that
        # the office shares with everything else. The caller gets the real reason instead.
        return JSONResponse({"ok": False, "account": inst.get("id"), "repo": repo,
                             "error": (out.get("errors") or {}).get("meta")
                                      or "המאגר לא נמצא או שאין אליו גישה."}, status_code=404)
    branch = branch or meta.get("default_branch") or ""
    out["ref"] = branch
    section("branches", lambda: ad.list_branches(repo, limit=100))
    section("commits", lambda: ad.list_commits(repo, branch, "", 12))
    section("tree", lambda: ad.list_dir(repo, "", branch))
    # The README's name is looked up in the listing we ALREADY have, not guessed by probing four
    # spellings against the provider: a repository without a README used to cost five API calls, and
    # a 404 is a call like any other.
    entries = ((out["sections"].get("tree") or {}).get("entries") or [])
    section("readme", lambda: _readme(ad, repo, branch, entries))
    mirror = next((m for m in mirrors.load()
                   if m.get("source_account") == inst.get("id")
                   and (m.get("source_repo") or "").lower() == repo.lower()), None)
    out["mirror"] = None if not mirror else {
        "id": mirror.get("id"), "status": mirror.get("last_status"),
        "error": mirror.get("last_error"), "last_run": mirror.get("last_run"),
        "bytes": mirror.get("bytes"),
        "browse_url": mirrors.public_base() + "/" + (mirror.get("target_owner") or "") + "/"
                      + (mirror.get("target_repo") or ""),
        "target": f"{mirror.get('target_owner')}/{mirror.get('target_repo')}"}
    # The forge's own host, for the "open it in the code library" action — the SAME origin the
    # mirrors use, so a repository page and a mirror row can never point at two different forges.
    out["forge"] = mirrors.public_base()
    return out


def _readme(ad, repo: str, ref: str, entries: list | None = None) -> dict | None:
    """The repository's README, whichever of its several spellings exists. Absent is not an error.

    When the root listing is available (it always is by the time this runs) the spelling is read OFF
    it — case-insensitively, and preferring `.md` — so a repository that has one costs exactly one
    call, and a repository that has none costs none.
    """
    names = [e.get("name") for e in (entries or []) if (e.get("type") or "file") == "file"]
    ranked = sorted([n for n in names if n and n.lower().startswith("readme")],
                    key=lambda n: (not n.lower().endswith(".md"), len(n)))
    for name in ranked or ["README.md", "README.rst", "README.txt", "README", "readme.md"]:
        try:
            f = ad.get_file(repo, name, ref)
            return {"path": name, "content": f.get("content") or "",
                    "truncated": bool(f.get("truncated"))}
        except Exception:                           # noqa: BLE001 — the next spelling, or nothing
            continue
    return None


@app.get("/api/overview")
def api_overview(probe: int = 1):
    """Everything the control panel shows, in one call: accounts, mirrors, and the local repository
    list — each half reporting its OWN failure instead of taking the whole answer down."""
    insts, vault_err = accounts.vault_list()
    local = next((i for i in insts if (i.get("protocol") or "") == "git_forge_local"), None)
    repos, repos_err = [], None
    if local and probe:
        try:
            ad = adapter_for("forgejo", accounts.vault_secret(local["id"]) or {}, local["id"])
            repos = (ad.list_repos(limit=100) or {}).get("repos") or []
        except Exception as e:                      # noqa: BLE001 — reported, not raised
            repos_err = getattr(e, "he_message", None) or f"{type(e).__name__}"
    return {"ok": True,
            "service": "git", "title": "ניהול גרסאות",
            "forge": _forge_card(),
            "local_account": local,
            "local_repos": repos, "local_repos_error": repos_err,
            "accounts": connections_list(probe=probe),
            "mirrors": mirrors.list_mirrors(),
            "vault_error": vault_err}


@app.get("/api/mirrors")
def api_mirrors():
    return {"ok": True, **mirrors.list_mirrors()}


@app.post("/api/mirrors")
async def api_mirror_create(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    account = (body.get("source_account") or body.get("account") or "").strip()
    repo = (body.get("repo") or "").strip()
    if not account or not repo:
        return JSONResponse({"ok": False, "error": "חסרים source_account ו-repo."}, status_code=400)
    try:
        row = mirrors.create(account, repo,
                             target_owner=(body.get("owner") or ""),
                             target_repo=(body.get("name") or ""),
                             private=bool(body.get("private", True)),
                             note=(body.get("note") or ""))
    except mirrors.MirrorError as e:
        return JSONResponse({"ok": False, "error": e.he_message}, status_code=e.status)
    # The first sync runs in the BACKGROUND and the caller polls: a first clone of a real repository
    # is minutes, and a request that waits for it is a request that times out at the edge.
    mirrors.sync_in_background(row["id"])
    return {"ok": True, "mirror": row,
            "note": "הסנכרון הראשון רץ ברקע — המאגר יופיע בפורג' תוך כדי."}


@app.post("/api/mirrors/{mid:path}/sync")
def api_mirror_sync(mid: str, wait: int = 0):
    """Start one sync. `wait=0` (the default) returns AT ONCE and the sync runs in the background.

    Not a convenience: a first clone of a real repository is measured in tens of minutes (the
    office's own: 1263 MB, 24 minutes), and a request that stays open for it is a request that dies
    at the console's proxy long before the sync does. `wait=1` is for a caller that genuinely wants
    the answer — the op surface uses it — and it is honored with the process-wide lock, so it waits
    for a running sync rather than starting a second clone.
    """
    if not mirrors._find(mid):
        return JSONResponse({"ok": False, "error": "מראה כזו אינה רשומה."}, status_code=404)
    if wait:
        return mirrors.sync(mid, wait=True)
    mirrors.sync_in_background(mid)
    return {"ok": True, "status": "started", "id": mid,
            "note": "הסנכרון רץ ברקע — מצב ההתקדמות ב-GET /api/mirrors."}


@app.delete("/api/mirrors/{mid:path}")
def api_mirror_delete(mid: str, delete_repo: int = 0):
    try:
        return mirrors.delete(mid, delete_repo=bool(delete_repo))
    except mirrors.MirrorError as e:
        return JSONResponse({"ok": False, "error": e.he_message}, status_code=e.status)


# ── the canonical op surface ─────────────────────────────────────────────────────────────────────
def _run(op: str, body: dict, fn):
    """Resolve the account, refuse a write on a read-only account, run, and normalize the failure."""
    cid = body.get("account") or body.get("connection_id")
    inst, sec, err = accounts.resolve(cid)
    if err:
        return JSONResponse({"ok": False, "op": op, "error": err}, status_code=409)
    provider, kind = accounts.provider_kind(inst.get("protocol") or "")
    if kind in ("deploy_token", "generic_token"):
        return JSONResponse(
            {"ok": False, "op": op, "provider": provider,
             "error": "החיבור הזה הוא קוד בלבד (clone/push) ואינו תומך בפעולות API."},
            status_code=400)
    if op in READONLY_OPS and (sec or {}).get("readonly"):
        return JSONResponse({"ok": False, "op": op,
                             "error": "החשבון מוגדר לקריאה בלבד — הפעולה נדחתה."}, status_code=403)
    try:
        adapter = adapter_for(provider, sec or {}, inst.get("id"))
        data = fn(adapter)
    except GitError as e:
        log.info("op %s failed on %s: %s", op, inst.get("id"), e.he_message)
        return JSONResponse({"ok": False, "op": op, "provider": provider,
                             "account": inst.get("id"), **e.body()}, status_code=e.status)
    return {"ok": True, "op": op, "provider": provider, "account": inst.get("id"),
            "kind": kind, "data": data}


def _need(body: dict, *names: str) -> tuple[list, JSONResponse | None]:
    vals = []
    for n in names:
        v = body.get(n)
        if isinstance(v, str):
            v = v.strip()
        if v in (None, ""):
            return [], JSONResponse({"ok": False, "error": f"חסר שדה: {n}"}, status_code=400)
        vals.append(v)
    return vals, None


@app.post("/whoami")
async def op_whoami(request: Request):
    body = (await request.json()) if await request.body() else {}
    return _run("whoami", body or {}, lambda a: a.whoami())


@app.post("/listRepos")
async def op_list_repos(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    return _run("listRepos", body, lambda a: a.list_repos(
        limit=int(body.get("limit") or 50), search=(body.get("search") or "").strip()))


@app.post("/getRepo")
async def op_get_repo(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("getRepo", body, lambda a: a.get_repo(repo))


@app.post("/createRepo")
async def op_create_repo(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (name,), bad = _need(body, "name")
    if bad:
        return bad
    return _run("createRepo", body, lambda a: a.create_repo(
        name, owner=(body.get("owner") or ""), private=bool(body.get("private", True)),
        description=(body.get("description") or ""), readme=bool(body.get("readme", True)),
        license_key=(body.get("license") or ""), gitignore=(body.get("gitignore") or ""),
        default_branch=(body.get("default_branch") or "")))


@app.post("/deleteRepo")
async def op_delete_repo(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("deleteRepo", body, lambda a: a.delete_repo(repo))


@app.post("/listBranches")
async def op_list_branches(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("listBranches", body, lambda a: a.list_branches(repo,
                                                                limit=int(body.get("limit") or 50)))


@app.post("/createBranch")
async def op_create_branch(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, name), bad = _need(body, "repo", "branch")
    if bad:
        return bad
    return _run("createBranch", body, lambda a: a.create_branch(repo, name,
                                                                (body.get("from") or "")))


@app.post("/listCommits")
async def op_list_commits(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("listCommits", body, lambda a: a.list_commits(
        repo, (body.get("ref") or ""), (body.get("path") or ""), int(body.get("limit") or 20)))


@app.post("/getFile")
async def op_get_file(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, path), bad = _need(body, "repo", "path")
    if bad:
        return bad
    return _run("getFile", body, lambda a: a.get_file(repo, path, (body.get("ref") or "")))


@app.post("/listDir")
async def op_list_dir(request: Request):
    """The entries of one directory. `path` may be empty — that is the ROOT of the repository, which
    is what a file browser opens on."""
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("listDir", body, lambda a: a.list_dir(
        repo, (body.get("path") or ""), (body.get("ref") or "")))


@app.post("/putFile")
async def op_put_file(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, path), bad = _need(body, "repo", "path")
    if bad:
        return bad
    if body.get("content") is None:
        return JSONResponse({"ok": False, "error": "חסר שדה: content"}, status_code=400)
    return _run("putFile", body, lambda a: a.put_file(
        repo, path, body.get("content") or "", (body.get("message") or ""),
        (body.get("branch") or ""), (body.get("sha") or "")))


@app.post("/listIssues")
async def op_list_issues(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("listIssues", body, lambda a: a.list_issues(
        repo, (body.get("state") or "open"), (body.get("labels") or ""),
        int(body.get("limit") or 30)))


@app.post("/createIssue")
async def op_create_issue(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, title), bad = _need(body, "repo", "title")
    if bad:
        return bad
    return _run("createIssue", body, lambda a: a.create_issue(
        repo, title, (body.get("body") or ""), body.get("labels"), body.get("assignees")))


@app.post("/updateIssue")
async def op_update_issue(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, issue), bad = _need(body, "repo", "issue")
    if bad:
        return bad
    try:
        number = int(issue)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "issue חייב להיות מספר"}, status_code=400)
    return _run("updateIssue", body, lambda a: a.update_issue(
        repo, number, title=(body.get("title") or ""), body=(body.get("body") or ""),
        state=(body.get("state") or ""), labels=body.get("labels")))


@app.post("/commentIssue")
async def op_comment_issue(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, issue, text), bad = _need(body, "repo", "issue", "body")
    if bad:
        return bad
    try:
        number = int(issue)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "issue חייב להיות מספר"}, status_code=400)
    return _run("commentIssue", body, lambda a: a.comment_issue(repo, number, text))


@app.post("/listPRs")
async def op_list_prs(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("listPRs", body, lambda a: a.list_prs(
        repo, (body.get("state") or "open"), int(body.get("limit") or 30)))


@app.post("/getPR")
async def op_get_pr(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, pr), bad = _need(body, "repo", "pr")
    if bad:
        return bad
    return _run("getPR", body, lambda a: a.get_pr(repo, int(pr)))


@app.post("/createPR")
async def op_create_pr(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, title, head, base), bad = _need(body, "repo", "title", "head", "base")
    if bad:
        return bad
    return _run("createPR", body, lambda a: a.create_pr(
        repo, title, head, base, (body.get("body") or ""), bool(body.get("draft"))))


@app.post("/mergePR")
async def op_merge_pr(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, pr), bad = _need(body, "repo", "pr")
    if bad:
        return bad
    return _run("mergePR", body, lambda a: a.merge_pr(
        repo, int(pr), (body.get("method") or "merge"),
        (body.get("title") or ""), (body.get("message") or "")))


@app.post("/commentPR")
async def op_comment_pr(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, pr, text), bad = _need(body, "repo", "pr", "body")
    if bad:
        return bad
    return _run("commentPR", body, lambda a: a.comment_pr(repo, int(pr), text))


@app.post("/submitReview")
async def op_submit_review(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, pr, verdict), bad = _need(body, "repo", "pr", "verdict")
    if bad:
        return bad
    return _run("submitReview", body, lambda a: a.submit_review(
        repo, int(pr), verdict, (body.get("body") or "")))


@app.post("/listReleases")
async def op_list_releases(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    return _run("listReleases", body, lambda a: a.list_releases(repo,
                                                                limit=int(body.get("limit") or 20)))


@app.post("/createRelease")
async def op_create_release(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, tag), bad = _need(body, "repo", "tag")
    if bad:
        return bad
    return _run("createRelease", body, lambda a: a.create_release(
        repo, tag, name=(body.get("name") or ""), body=(body.get("body") or ""),
        target=(body.get("target") or ""), publish=bool(body.get("publish", True)),
        prerelease=bool(body.get("prerelease"))))


@app.post("/deleteRelease")
async def op_delete_release(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo, tag), bad = _need(body, "repo", "tag")
    if bad:
        return bad
    return _run("deleteRelease", body, lambda a: a.delete_release(repo, tag))


@app.post("/listMirrors")
async def op_list_mirrors(request: Request):
    body = (await request.json()) if await request.body() else {}
    _ = body or {}
    return {"ok": True, "op": "listMirrors", "provider": "forgejo", "data": mirrors.list_mirrors()}


@app.post("/createMirror")
async def op_create_mirror(request: Request):
    """Register an external repository as a mirror inside the office's forge.

    `source_account` is a connection id and it is REQUIRED — the op deliberately has no "use the
    active account" default, because the active account changes under a browser tab and a mirror
    that followed it would silently copy a different repository into the same project.
    """
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (account, repo), bad = _need(body, "source_account", "repo")
    if bad:
        return bad
    try:
        row = mirrors.create(account, repo, target_owner=(body.get("owner") or ""),
                             target_repo=(body.get("name") or ""),
                             private=bool(body.get("private", True)))
    except mirrors.MirrorError as e:
        return JSONResponse({"ok": False, "op": "createMirror", "error": e.he_message},
                            status_code=e.status)
    if body.get("sync", True):
        mirrors.sync_in_background(row["id"])
    return {"ok": True, "op": "createMirror", "provider": "forgejo", "data": {"mirror": row}}


@app.post("/syncMirror")
async def op_sync_mirror(request: Request):
    """Start a sync. `wait` unset → it runs in the BACKGROUND and the answer says `started`.

    Same reason as the REST twin above: a first clone of a real repository is tens of minutes, so an
    op that blocked on it would be an op every caller times out on. `{"wait": true}` is the explicit
    "I want to know the outcome" form, and it waits on the process-wide lock rather than starting a
    second clone next to a running one.
    """
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (mid,), bad = _need(body, "id")
    if bad:
        return bad
    if not mirrors._find(mid):
        return JSONResponse({"ok": False, "op": "syncMirror",
                             "error": "מראה כזו אינה רשומה."}, status_code=404)
    if not body.get("wait"):
        mirrors.sync_in_background(mid)
        return {"ok": True, "op": "syncMirror", "provider": "forgejo",
                "data": {"id": mid, "status": "started",
                         "note": "הסנכרון רץ ברקע — מצב ההתקדמות ב-listMirrors."}}
    res = mirrors.sync(mid, wait=True)
    return JSONResponse({"ok": bool(res.get("ok")), "op": "syncMirror", "provider": "forgejo",
                         "data": res}, status_code=200 if res.get("ok") else 409)


@app.post("/deleteMirror")
async def op_delete_mirror(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (mid,), bad = _need(body, "id")
    if bad:
        return bad
    try:
        data = mirrors.delete(mid, delete_repo=bool(body.get("delete_repo")))
    except mirrors.MirrorError as e:
        return JSONResponse({"ok": False, "op": "deleteMirror", "error": e.he_message},
                            status_code=e.status)
    return {"ok": True, "op": "deleteMirror", "provider": "forgejo", "data": data}


OPS = {
    "whoami": op_whoami, "listRepos": op_list_repos, "getRepo": op_get_repo,
    "createRepo": op_create_repo, "deleteRepo": op_delete_repo,
    "listBranches": op_list_branches, "createBranch": op_create_branch,
    "listCommits": op_list_commits, "getFile": op_get_file, "listDir": op_list_dir,
    "putFile": op_put_file,
    "listIssues": op_list_issues, "createIssue": op_create_issue,
    "updateIssue": op_update_issue, "commentIssue": op_comment_issue,
    "listPRs": op_list_prs, "getPR": op_get_pr, "createPR": op_create_pr,
    "mergePR": op_merge_pr, "commentPR": op_comment_pr, "submitReview": op_submit_review,
    "listReleases": op_list_releases, "createRelease": op_create_release,
    "deleteRelease": op_delete_release,
    # Mirrors. These are the one part of the op surface that is about the OFFICE'S forge rather than
    # about a provider account, so they take `source_account` explicitly and never an `account`.
    "listMirrors": op_list_mirrors, "createMirror": op_create_mirror,
    "syncMirror": op_sync_mirror, "deleteMirror": op_delete_mirror,
}


@app.get("/ops")
def ops_index():
    """The op surface, machine-readable. An app that declares `use: git` reads THIS to learn what it
    may call — the same way /providers spares the console a hardcoded catalogue."""
    return {"service": "git", "interface": "git.v1",
            "ops": sorted(OPS), "read_only_safe": sorted(set(OPS) - READONLY_OPS),
            "params": {
                "repo": "owner/name (GitLab: group/subgroup/name)",
                "account": "connection id from /connections (default: the active account)",
            }}


@app.post("/remote")
async def api_remote(request: Request):
    """The git remote to actually use for a repository — credential-free, in-network.

    This is how a caller gets a working remote: it asks, and the answer is a URL that contains the
    ACCOUNT (so the proxy knows which token to inject) and no secret at all.
    """
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    (repo,), bad = _need(body, "repo")
    if bad:
        return bad
    inst, _sec, err = accounts.resolve(body.get("account"))
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=409)
    provider, _kind = accounts.provider_kind(inst.get("protocol") or "")
    url = proxy.remote_url(inst["id"], provider, repo)
    return {"ok": True, "account": inst["id"], "provider": provider, "repo": repo,
            "remote": url,
            "clone": f"git clone {url}",
            "note": "הסוכן משתמש בכתובת הזו כמו בכל remote — הטוקן מוזרק בצד השרת ואינו נדרש."}


# ── the UI ───────────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.on_event("startup")
def _startup():
    log.info("git service up — deployment=%s, vault=%s", DEPLOYMENT_NAME, accounts.CONNECTIONS_URL)
    # The mirror scheduler is part of the service, not of a workflow engine: it needs this process's
    # per-request credential resolution, and one container with one volume cannot run two syncs at
    # once — which is the property that keeps a 5 GiB engine from being filled by two clones.
    mirrors.start_scheduler()
