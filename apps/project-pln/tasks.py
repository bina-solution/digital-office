#: tasks — read and move work items in this office's Plane, from the CLI
#
# tasks list [--project DGO] [--mine|--assignee <name>] [--state unstarted|started|completed] [--json]
# tasks show DGO-12 [--body]    # …with --body also the item's description, as text
# tasks start DGO-12            # → the state in group `started`
# tasks done DGO-12 [--comment "what was done, where, and the proof"]
# tasks comment DGO-12 "…"
# tasks take DGO-12             # assign it to me (the account behind the chosen token)
# tasks attach DGO-12 <file> [<file>…]   # the files a request came with, on its work item
# tasks label MEET-15 נותח[,<label>…]    # add labels by name; one the project lacks is created
# tasks unlabel DGO-12 בעלים[,<label>…]  # take off exactly the labels named
# tasks link MEET-15 DGO-1003 EXF-2 …    # related both ways, across projects (Plane's `relates_to`)
# tasks new DGO "name" [--comment "description"|@file] [--priority urgent|high|medium|low|none]
#                                        # a new work item; --comment is its description (the request's words)
# tasks edit DGO-12 [--name "…"] [--priority p] [--comment "new description"|@file]
#                                        # the old description is kept first, as a comment on the item
# tasks rm DGO-12 --comment "why"        # NEVER deletes: the item moves to the project's cancelled state with
#                                        # the reason as a comment; `tasks start` brings it back
# …`tasks item new|edit|rm …` is the same (the noun of `dgo <app> <noun> <verb>`, DGO-1252)
# tasks batch @actions.jsonl             # many of the verbs above in ONE run: one JSON object per line,
#                                        # {"verb","ref","comment"?,"words"?[]} — the project is paged once
# …any of the above with `--as <slug>` to act as that office agent (its own vault account + token)
#
# A READ THAT IS SLOW SAYS SO, AND GIVES UP. DGO alone is ~N items and the office's Plane answers a
# page of `issues/?expand=…` in 3–11 s, so `tasks list` could be minutes of silence — indistinguishable
# from a stuck process. From PLANE_PROGRESS_AFTER seconds (default 3) a read prints one progress line to
# STDERR every few seconds (page n, items, seconds — never to stdout: `--json` is a contract), and at
# PLANE_READ_DEADLINE seconds (default 120, 0 = none) it STOPS with a non-zero exit that names the
# address it was asking, how far it got, and how to ask for less. PLANE_PER_PAGE (default 200) is the
# page size it asks Plane for — 50 was four times the round trips for the same rows.
#
# ON AN OFFICE THAT DOES NOT RUN PLANE, the same verbs reach the one that does — through the link and
# with NO key at all: `where.sh` points the run at that office's door, and the door signs the request
# in as the identity its office declared for this one (DGO-545). `--as` is a local-office idea and is
# ignored there: one link carries one identity.
#
# WHY IT EXISTS: `plan` writes a plan INTO Plane; this reads and moves the result, so an agent (or
# the owner through `bbox agent tasks`) can say what is mine, what started, what finished — without
# anyone opening the web UI and without a token ever crossing a shell argument. It is the read/write
# counterpart of the same vault contract: the token comes from the credential plane at run time, and
# a person's name resolves to a Plane account through `plane_local_api_token-<slug>`.
#
# OUTPUT CONTRACT (stable; documented in README.md): `--json` prints
#   {"tasks":[{"ref","id","project","name","state","group","priority","labels","assignees",
#              "module","url","updated_at"}]}
# Every mutating verb prints one line unless `--json` is given, in which case it prints
#   {"ok":true,"ref":"…","state":"…","group":"…","url":"…"}.
import hashlib
import html
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = (os.environ.get("PLANE_API_URL") or "http://127.0.0.1").rstrip("/")
#: Is this run reaching a Plane that runs on a LINKED office? `where.sh` says so by setting
#: `PLANE_API_URL` to that office's link door; the default (`127.0.0.1`) is this office's own app.
REMOTE = bool(os.environ.get("PLANE_API_URL")) and not re.match(
    r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", BASE)
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
WEB = (os.environ.get("WEB_URL") or "http://plane.localhost:8080").rstrip("/")
# The link a PERSON follows is the CONSOLE's, not the app's own host: a console URL opens Plane
# INSIDE the office — framed in the shell, signed in by the office's own SSO, one tab that already
# exists — while `plane.<host>/…` is a bare second tab that asks for a sign-in of its own, because
# on an unregistered TLD every host is its own site and the console's session never travels to it
# (the owner, 2026-10-08: «i need it opening the plane inside the dgo by default (now it opend new
# tab only with plane and required login)»). `WEB_URL` stays the app's address and is still reported,
# as `app_url`, for anything that must talk to the app itself.
CONSOLE = (os.environ.get("CONSOLE_URL") or "").rstrip("/")
CONSOLE_MODULE = os.environ.get("PLANE_CONSOLE_MODULE") or "project-pln"
#: Where a work item's link opens (DGO-1433): the herd's hub console (hooks/tasks, from apps/computers/herd.yaml
#: `hub_console:`) — the one the owner reaches from anywhere — else this office's own. On the HP or the MacBook this
#: office's own console is `console.localhost`: on his phone, his phone.
LINK_BASE = (os.environ.get("LINK_BASE") or CONSOLE).rstrip("/")
#: A work item's key, as Plane writes it.
KEY_RE = re.compile(r"[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}")
#: `attach`'s exit when Plane (or its store) ANSWERED and refused some of the files for good (their type, their
#: size) and the rest landed: sending them again cannot change it — outbox.py's flush says so and lets the write
#: go instead of holding the office's queue behind it. A refusal that may pass (5xx, 429, 401/403, the door's
#: empty 404, no answer) exits 1 instead, and a replay keeps the write. Same number as outbox.py's ANSWERED_REFUSED.
ANSWERED_REFUSED = 4


def item_link(ref: str) -> str:
    """A work item opened INSIDE the office, by its KEY — empty when no console is declared or `ref` is no key.

    `#/m/<module>/<the app's inner route>` is the shell's deep link, and Plane's own key route `<ws>/browse/<KEY>/` is
    the screen — no UUIDs (proven on vps1's console at a phone's size, 2026-11-06: the frame showed the item itself).
    On the hub's console the module resolves by the name the writing office gives it (`plane.<office>` through a
    door, `project-pln` at home: static/module-ref.js reads both). The `/go/<KEY>` path the console resolves
    server-side (DGO-1433) replaces this once the hub answers it; until then a `/go/` link opened the hub's HOME
    (measured 2026-11-08), so it is not written here."""
    if not LINK_BASE or not KEY_RE.fullmatch(ref or ""):
        return ""
    return f"{LINK_BASE}/#/m/{console_module()}/{WS_SLUG}/browse/{ref}/"


def console_module() -> str:
    """The console module id THIS office addresses Plane by.

    A local app's tile carries its own id (`project-pln`). A remote one carries `<alias>.<office>`
    (the compiled `console.modules.yaml` gives the remote entry that id, and its `module_id:
    project-pln` is metadata the shell never reads), and the shell's hash grammar addresses a module
    BY ID — so a link built with the local id names no live module here and `route()` falls through
    to the office's FIRST tile, silently opening another app (measured on vps1, 2026-10-13:
    `#/m/project-pln/…` did not open Plane). The door's own host IS that id.
    """
    if REMOTE:
        host = urllib.parse.urlsplit(BASE).hostname or ""
        if host:
            return host
    return CONSOLE_MODULE
WS_SLUG = os.environ.get("PLANE_WORKSPACE") or "bina"
GROUP_OF = {"backlog": "backlog", "unstarted": "unstarted", "started": "started",
            "completed": "completed", "cancelled": "cancelled", "triage": "triage"}
# `--state` accepts the group word or the Hebrew name of the state; the group word is what a caller
# should use, because the NAME is the owner's to rename.
GROUP_ALIAS = {"todo": "unstarted", "open": "unstarted", "doing": "started", "in_progress": "started",
               "closed": "completed", "finished": "completed"}


def log(msg: str) -> None:
    print(f"[project-pln] {msg}", flush=True)


def say(msg: str) -> None:
    """A line of PROGRESS — stderr, always, so a caller piping `--json` into a parser never sees it."""
    print(f"[project-pln] {msg}", file=sys.stderr, flush=True)


# A READ ON A BIG, SLOW PLANE MUST NOT LOOK LIKE A HANG (the owner, 2026-11-06: «נכשל מהר במקום להיתקע»).
# Measured from vps1 against the HP's Plane: a page of `issues/?expand=labels,assignees` takes 3.3–11.3 s,
# DGO holds ~N items, and `tasks list --project DGO --mine --json` was **112 s of nothing** — no line,
# no error, no clue — while `list` with no `--project` walked all five projects. So a read here has three
# properties it did not have before: it TALKS (stderr, after PROGRESS_AFTER s), it has a CEILING
# (READ_DEADLINE over the whole walk, not per request), and it asks Plane for BIG PAGES (PER_PAGE), which
# is the only saving Plane itself offers — see `Plane.page`.
PROGRESS_AFTER = float(os.environ.get("PLANE_PROGRESS_AFTER") or 3)    # silent this long, then talk
PROGRESS_EVERY = float(os.environ.get("PLANE_PROGRESS_EVERY") or 5)    # …and no more often than this
READ_DEADLINE = float(os.environ.get("PLANE_READ_DEADLINE") or 120)    # 0 = no ceiling at all
#: 50 is the size the API documents; 200 is the size this Plane SERVES. Measured 2026-11-06:
#: `per_page=200` answers 200 rows and drops DGO's total_pages 29 → 8; 500 answers too, but a page is then
#: 23 s and one of them would eat the whole deadline. Same rows, a quarter of the round trips.
PER_PAGE = max(1, int(os.environ.get("PLANE_PER_PAGE") or 200))


class Read:
    """One paging walk over the API: a ceiling over the WHOLE walk, and a line while it runs.

    Armed once per read (`begin`) and stepped by `Plane.page` after every answered request, so the pages
    and items it reports are what actually arrived, never an estimate. Unarmed is the default and does
    nothing at all (no ceiling, no line, plain 90 s requests) — every write path stays exactly as it was.
    """

    def __init__(self) -> None:
        self.label = ""            # "" = not armed: no progress, no ceiling
        self.url = ""              # the address being asked, for the message that gives up
        self.t0 = 0.0
        self.deadline = 0.0
        self.pages = 0
        self.rows = 0
        self.noted = 0.0

    def begin(self, label: str) -> "Read":
        self.label = label
        self.url = ""
        self.t0 = self.noted = time.monotonic()
        self.deadline = READ_DEADLINE
        self.pages = self.rows = 0
        return self

    def spent(self) -> float:
        return time.monotonic() - self.t0

    def left(self):
        """Seconds this read may still spend on one request ('left' capped by the ceiling), or None when
        it is not armed — a request timeout of None is `http`'s own 90 s."""
        if not self.deadline:
            return None
        return max(1.0, self.deadline - self.spent())

    def give_up(self) -> None:
        sys.exit(f"[project-pln] gave up after {self.spent():.0f}s (PLANE_READ_DEADLINE="
                 f"{self.deadline:g}): {self.label or 'read'} — still asking {self.url or '?'} — "
                 f"{self.pages} pages and {self.rows} items so far. Plane is ANSWERING, only slowly. "
                 f"Ask for less: `--project <ID>` (one project, not all of them), `--mine` (only my "
                 f"items), `--state unstarted|started|completed`; or raise the ceiling with "
                 f"PLANE_READ_DEADLINE=<seconds>.")

    def expired(self) -> None:
        """A request that went out with the ceiling's own timeout and failed: say THAT, not a raw URLError."""
        if self.deadline and self.spent() >= self.deadline:
            self.give_up()

    def step(self, url: str, got: int = 0) -> None:
        """Count one answered page: give up past the ceiling, and say where we are once it is slow."""
        self.url = url
        self.pages += 1
        self.rows += got
        now = time.monotonic()
        if self.deadline and now - self.t0 > self.deadline:
            self.give_up()
        if self.label and now - self.t0 >= PROGRESS_AFTER and now - self.noted >= PROGRESS_EVERY:
            self.noted = now
            say(f"{self.label}: page {self.pages}, {self.rows} items, {self.spent():.0f}s so far …")


READ = Read()


# The project list is the slowest read in this API (measured 2026-10-01: ~55 s under load, holding one of
# the two gunicorn workers), and every verb used to start with it; states/labels/modules change only when
# someone edits the project. All four come from a small file inside the container for CACHE_TTL seconds,
# and a miss on a project identifier re-reads once (a project created since the cache was written).
CACHE = os.environ.get("TASKS_CACHE") or "/tmp/plane-tasks-cache.json"
CACHE_TTL = int(os.environ.get("TASKS_CACHE_TTL") or "1800")


def _cache_read() -> dict:
    try:
        with open(CACHE) as f:
            data = json.load(f)
    except Exception:                                          # noqa: BLE001 — no cache yet / corrupt
        data = {}
    return data if isinstance(data, dict) else {}


def cache_peek(key: str):
    """The cached value while it is fresh, else None."""
    hit = _cache_read().get(key)
    if isinstance(hit, dict) and time.time() - hit.get("t", 0) < CACHE_TTL:
        return hit["v"]
    return None


def cache_put(key: str, v) -> None:
    data = _cache_read()
    data[key] = {"t": time.time(), "v": v}
    try:
        with open(CACHE + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(CACHE + ".tmp", CACHE)
    except Exception:                                          # noqa: BLE001 — a cache is never required
        pass


def cached(key: str, fetch, fresh: bool = False):
    if not fresh:
        hit = cache_peek(key)
        if hit is not None:
            return hit
    v = fetch()
    cache_put(key, v)
    return v


def project_list(p, fresh: bool = False) -> list:
    return cached(f"{WS_SLUG}:projects",
                  lambda: [{"id": x["id"], "identifier": x.get("identifier"), "name": x.get("name")}
                           for x in p.page("/projects/")], fresh)


def project_meta(p, pid: str):
    """(states by group, label names by id, module names by id) of one project — cached."""
    P = f"/projects/{pid}"
    states = {s["group"]: s for s in cached(f"{pid}:states", lambda: p.page(f"{P}/states/"))}
    labels = {l["id"]: l["name"] for l in cached(f"{pid}:labels", lambda: p.page(f"{P}/labels/"))}
    modules = {m["id"]: m["name"] for m in cached(f"{pid}:modules", lambda: p.page(f"{P}/modules/"))}
    return states, labels, modules


def members_key(pid: str, module_ids) -> str:
    """The cache key of a project's module membership — the module SET in it, so a module added or removed is a
    new key, and plan.py drops the project's keys after it places items (forget_module_members)."""
    return f"{pid}:module-members:" + hashlib.sha1(",".join(sorted(module_ids)).encode()).hexdigest()[:10]


def _module_items(p, P: str, mid: str):
    """One module's item ids, through http(): None when Plane did not answer it — that module's failure, not the
    verb's (p.page exits on any refusal, and one bad page of ~98 modules ended `tasks show`: the second reader)."""
    ids, cursor = [], ""
    while True:
        out, code = http("GET", f"{p.base}{P}/modules/{mid}/module-issues/?per_page=100"
                         + (f"&cursor={cursor}" if cursor else ""), None, p.h, tries=2)
        if code != 200:
            return None
        rows = out if isinstance(out, list) else (out or {}).get("results") or []
        ids += [str((x.get("issue") or x.get("id")) if isinstance(x, dict) else x) for x in rows]
        if isinstance(out, list) or not (out.get("next_page_results") and out.get("next_cursor")):
            return ids
        cursor = out["next_cursor"]


def module_members(p, pid: str, modules: dict, want: str = "") -> dict:
    """item id → the name of the module it is in, read off each module's own list (`module-issues`, the endpoint
    plan.py fills and reads). The item answers carry no module: the list endpoint has no `module_ids`, so every
    `tasks show` said `module: —` for an item in «דיווח» (DGO-962).

    A project has ~100 modules, so this is many requests. What was read is kept with WHICH modules were read
    (`{"read": [...], "map": {...}, "since": t}` under members_key): `want` (one item id, for `show`) answers from it
    when the item is there, else reads only the modules not read yet and stops at the one that holds it; a module
    Plane did not answer is skipped and asked again next time — its items say «—» rather than the verb failing.
    The whole read is as old as its first module: past the TTL it starts again."""
    P, key = f"/projects/{pid}", members_key(pid, modules)
    hit = cache_peek(key)
    if not (isinstance(hit, dict) and isinstance(hit.get("map"), dict)
            and time.time() - float(hit.get("since") or 0) < CACHE_TTL):
        hit = {"read": [], "map": {}, "since": time.time()}
    read, mp = set(hit["read"]), dict(hit["map"])
    if not (want and want in mp):
        grew = False
        for mid in sorted(modules):
            if mid in read:
                continue
            ids = _module_items(p, P, mid)
            if ids is None:
                continue
            read.add(mid)
            grew = True
            for iid in ids:
                mp.setdefault(iid, mid)
            if want and want in mp:
                break
        if grew:
            cache_put(key, {"read": sorted(read), "map": mp, "since": hit["since"]})
    return {iid: modules.get(mid, "") for iid, mid in mp.items()}


def module_of(it: dict, modules: dict, members=None) -> str:
    """The item's module: what its own answer names, else the modules' lists."""
    for m in (it.get("module_ids") or it.get("modules") or []):
        mid = m if isinstance(m, str) else (m.get("module_id") or m.get("id"))
        if modules.get(mid):
            return modules[mid]
    return (members or {}).get(str(it.get("id") or ""), "")


# A Plane that does not answer must not hold a verb for half an hour: six tries × 90 s per request and several
# requests per verb, with every caller on the Mac's engine queued behind them (measured 2026-11-02 17:40: seven
# calls stuck 20–35 min while the HP, which runs Plane, did not answer, and the engine at load 140). A request
# whose connection fails or times out is tried once more; then this process stops asking (`DOWN`), and every
# later request fails at once with the reason.
DOWN = ""

# A 404 with NO body is not Plane's: Plane says what it did not find, in JSON. It is the door of the office that runs
# Plane (apps/dgo-extend/link-proxy.py, `X-Dgo-Door: no-app`) whose route table did not hold Plane at that moment —
# measured 2026-11-05 from the Mac to the HP: empty 404s on the project list and on the second and the twenty-second
# page of one paging, while twenty reads in a row a little later all answered — and one of them ended the whole verb
# (`tasks show`, `batch`) for every session. The door reads its table every 30 s (DGO_DOOR_ROUTES_TTL), so a table
# without Plane stands that long at least: a READ is asked again over 75 s (5+10+15+20+25), a write is not (it may
# have landed). A 502/503/504 is the same moment seen from the other side (the door or Plane restarting; plan.py's
# GONE) and is asked again the same way. When one read has used up its tries, later ones of this process are
# answered at once (`NO_APP`), with the reason — the door is still asked. plan.py asks again the same way.
EMPTY_404_TRIES = 6
GONE = (502, 503, 504)
NO_APP = ""


def http(method: str, url: str, body=None, headers=None, tries: int = 6, timeout=None):
    global DOWN, NO_APP
    if DOWN:
        return {"error": f"Plane is not answering ({DOWN})"}, -1
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    lost = 0                                                   # connection failures, counted apart from the 404s
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout or 90) as r:   # the project list takes ~55 s under load
                raw = r.read().decode("utf-8", "replace")
            return (json.loads(raw) if raw.strip() else {}), r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:          # Plane's own limit is 60/min per key
                time.sleep(5 * (attempt + 1))
                continue
            try:
                text = e.read().decode("utf-8", "replace")
            except Exception:                                  # noqa: BLE001 — a body cut short is no body
                text = ""
            empty_404 = e.code == 404 and not text.strip()     # not Plane's own 404 (EMPTY_404_TRIES above)
            if empty_404 or e.code in GONE:
                if method == "GET" and not NO_APP and attempt < min(tries, EMPTY_404_TRIES) - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                door = (e.headers.get("X-Dgo-Door") or "") if e.headers else ""
                if method == "GET":
                    NO_APP = door or f"HTTP {e.code}"
                if empty_404:
                    return {"error": "the door answered 404 with no body" + (f" (X-Dgo-Door: {door})" if door else "")}, e.code
            return {"error": text[:300]}, e.code
        except (urllib.error.URLError, OSError) as e:          # no connection, or no answer in time
            lost += 1
            if lost < 2 and attempt < tries - 1:
                time.sleep(2)
                continue
            DOWN = f"{type(e).__name__}: {e}"
            return {"error": DOWN}, -1
        except Exception as e:                                 # noqa: BLE001
            if attempt < tries - 1:
                time.sleep(2)
                continue
            return {"error": f"{type(e).__name__}: {e}"}, -1
    return {"error": "giving up"}, -1


def upload(url: str, fields: dict, kind: str, blob: bytes) -> int:
    """Put one file in the store through the form Plane signed for it: the store's own fields
    first, the file last (the store reads nothing after the file). Returns the HTTP status."""
    edge = "dgo" + os.urandom(12).hex()
    body = b"".join(f'--{edge}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{edge}\r\nContent-Disposition: form-data; name="file"; filename="file"\r\n'
             f"Content-Type: {kind}\r\n\r\n").encode() + blob + f"\r\n--{edge}--\r\n".encode()
    # Plane signs the form for its PUBLIC origin (<WEB_URL netloc>/uploads, USE_MINIO=1), which a
    # LINKED office cannot reach: `plane.localhost` there is itself, so every attach through the link
    # failed with -1 (measured from vps1 and claude-cloud, 2026-10-20/21). That office's link door
    # serves the same /uploads (project-pln's Caddyfile owns the route): the form goes there.
    if REMOTE:
        signed = urllib.parse.urlsplit(url)
        if signed.path.rstrip("/") == "/uploads":
            url = BASE + signed.path + (f"?{signed.query}" if signed.query else "")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={edge}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:                                          # noqa: BLE001 — said by the caller
        return -1


def token_for(slug: str) -> tuple[str, str, str]:
    """(token, user_id, email) for an office agent — the vault instance is the contract.

    …and NO token at all when the app runs on a LINKED office (`where.sh` points this run at that
    office's door, `http://<alias>.<office>:<door>`): there is nothing to read here, and nothing to
    read it for. That office's door replaces the peer's claims with the identity it declared for this
    office and SIGNS it (`apps/dgo-extend/link-proxy.py`, DGO-545), so the request arrives signed in
    as the mapped user — the token API accepts that identity as if it were a key (patches/
    api-door-identity.py). Reading this office's vault instead is what made a linked office's agent
    stop with `no Plane account behind vault instance plane_local_api_token-azaria (HTTP 404)` while
    the link was perfectly healthy (measured on vps1, 2026-10-13)."""
    if REMOTE:
        return ("", "", "")
    if slug == "local" and os.environ.get("PLANE_LOCAL_API_TOKEN"):
        return (os.environ["PLANE_LOCAL_API_TOKEN"], os.environ.get("PLANE_LOCAL_USER_ID") or "",
                os.environ.get("PLANE_LOCAL_EMAIL") or "")
    iid = f"plane_local_api_token-{slug}"
    out, code = http("GET", f"{VAULT}/api/instances/{iid}/secret")
    sec = (out or {}).get("secret") or {}
    if code not in (200, 201) or not sec.get("token"):
        sys.exit(f"[project-pln] no Plane account behind vault instance {iid} (HTTP {code}) — "
                 f"run ./bbox project-pln onboard")
    return sec["token"], sec.get("user_id") or "", sec.get("username") or ""



def collect(p, proj, want_mine, assignee, state_filter, with_modules: bool = False) -> list:
    """The shaped, filtered rows of ONE project — the body `list` runs per project. The modules' lists are read only
    when the output carries `module` (`--json`): the text list does not print it (DGO-962's second reader)."""
    pid, P = proj["id"], f"/projects/{proj['id']}"
    states, labels, modules = project_meta(p, pid)
    members = module_members(p, pid, modules) if modules and with_modules else {}
    rows = []
    for it in p.page(f"{P}/issues/?expand=labels,assignees"):
        names = [(a.get("display_name") or a.get("email") or "") if isinstance(a, dict) else ""
                 for a in (it.get("assignees") or [])]
        ids = [a if isinstance(a, str) else a.get("id") for a in (it.get("assignees") or [])]
        if want_mine and p.me_id and p.me_id not in ids and not (
                p.me_email and any(p.me_email.lower() == str(a.get("email") or "").lower()
                                   for a in (it.get("assignees") or []) if isinstance(a, dict))):
            continue
        if assignee and assignee.strip().lower() not in [n.lower() for n in names if n]:
            continue
        mod = module_of(it, modules, members)
        st_id = it.get("state")
        grp = next((s["group"] for s in states.values() if s["id"] == st_id), "")
        if state_filter and grp != state_filter:
            continue
        rows.append({"ref": f"{proj['identifier']}-{it.get('sequence_id')}", "id": it["id"],
                     "project": proj["identifier"], "name": it.get("name", ""),
                     "state": next((s["name"] for s in states.values() if s["id"] == st_id), ""),
                     "group": grp, "priority": it.get("priority") or "none",
                     "labels": [labels.get(l if isinstance(l, str) else l.get("id"), "") for l in
                                (it.get("label_ids") or it.get("labels") or [])],
                     "assignees": [n for n in names if n], "module": mod,
                     # the item inside the office, by its key, when a console is declared; the app's own host otherwise
                     "url": item_link(f"{proj['identifier']}-{it.get('sequence_id')}")
                            or f"{WEB}/{WS_SLUG}/projects/{pid}/issues/{it['id']}",
                     "updated_at": it.get("updated_at") or ""})
    return rows

def me_from_app() -> tuple[str, str]:
    """(id, email) of whoever this run IS, asked of the app itself — a linked office has no token
    that names the account, and `--mine` has to mean the same thing in both offices."""
    out, code = http("GET", f"{BASE}/api/users/me/")
    if code == 200 and isinstance(out, dict):
        return str(out.get("id") or ""), str(out.get("email") or "")
    return "", ""


class Plane:
    def __init__(self, key: str, me_id: str = "", me_email: str = ""):
        self.base = f"{BASE}/api/v1/workspaces/{WS_SLUG}"
        # No key = a request that is authenticated by the link's door instead (DGO-545/lnk-027).
        self.h = {"X-API-Key": key} if key else {}
        self.me_id = me_id
        self.me_email = me_email

    def call(self, method: str, path: str, body=None, timeout=None):
        out, code = http(method, f"{self.base}{path}", body, self.h, timeout=timeout)
        if code not in (200, 201, 204):
            if code == -1 and timeout is not None:
                READ.expired()          # this request went out on the READ's budget and it ran out
            sys.exit(f"[project-pln] {method} {path} → HTTP {code}: "
                     f"{out.get('error') if isinstance(out, dict) else out}")
        return out

    def page(self, path: str) -> list:
        """Every page, transparently — the public API paginates by cursor.

        A bare JSON ARRAY is an answer too. Most endpoints answer with the cursor envelope
        (`{"results": [...], "next_cursor": …}`), but some — the workspace's own `/members/` among
        them — answer with a plain list, and `(out or {}).get("results")` on a list raised
        `AttributeError: 'list' object has no attribute 'get'`. Measured 2026-10-09: it killed
        `tasks take` (the one verb that asks for a member's name) while list/show/start/done/comment
        all worked, so nothing pointed at the reader.

        Every request here is counted against the armed `READ` (see the class): the page size is
        PER_PAGE, the per-request timeout is what that read has left, and one answered page is one line
        of progress once the walk is slow. A walk that is not armed behaves exactly as it always did.
        """
        sep = "&" if "?" in path else "?"
        ask = f"{path}{sep}per_page={PER_PAGE}"
        shown = f"{self.base}{path}"          # what the person can open to see the same answer
        READ.url = shown                      # …and what the give-up message names, even if page 1 dies
        out = self.call("GET", ask, timeout=READ.left())
        if isinstance(out, list):
            READ.step(shown, len(out))
            return out
        rows = list((out or {}).get("results") or [])
        READ.step(shown, len(rows))
        while isinstance(out, dict) and out.get("next_page_results") and out.get("next_cursor"):
            out = self.call("GET", f"{ask}&cursor={out['next_cursor']}", timeout=READ.left())
            if isinstance(out, list):
                rows += out
                READ.step(shown, len(out))
                break
            got = list((out or {}).get("results") or [])
            rows += got
            READ.step(shown, len(got))
        return rows


#: A project's items, paged once per PROCESS (keyed by the project id): one run of a verb, or one `batch`.
_ISSUES: dict = {}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip() if __doc__ else "")
        return 0
    verb, rest = argv[0], argv[1:]
    if verb == "item" and rest and rest[0] in ("new", "edit", "rm"):   # `item new|edit|rm`: the noun, then the verb
        verb, rest = rest[0], rest[1:]
    project = ""
    new_name = ""
    priority = ""
    slug = os.environ.get("PLANE_AS") or "local"
    want_mine = False
    assignee = ""
    state_filter = ""
    as_json = False
    want_body = False
    comment = ""
    ref = ""
    words = []  # what follows the ref, by POSITION: the files of `attach`, the labels of `label`, the items of `link`
    args = list(rest)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--body":
            want_body = True
        elif a == "--mine":
            want_mine = True
        elif a in ("--project", "--assignee", "--state", "--comment", "--as", "--name", "--priority") and i + 1 < len(args):
            val = args[i + 1]
            i += 1
            if a == "--name":
                new_name = val
            elif a == "--priority":
                priority = val
            elif a == "--project":
                project = val
            elif a == "--assignee":
                assignee = val
            elif a == "--state":
                state_filter = GROUP_ALIAS.get(val, val)
            elif a == "--comment":
                comment = val
            elif a == "--as":
                slug = val
        elif a.startswith("--"):
            # A flag this command does not know was dropped in silence, and ITS VALUE became the next
            # word: `tasks comment X --file r.html` posted the text «r.html» (2026-11-10, the drive
            # split: three reports went in as paths). Every caller in the repo uses the flags above
            # only (git grep, DGO-1727), so an unknown one is refused by name, before anything is sent.
            if a in ("--project", "--assignee", "--state", "--comment", "--as", "--name", "--priority"):
                sys.exit(f"[project-pln] tasks: {a} needs a value")
            sys.exit(f"[project-pln] tasks: unknown flag {a} — this command takes --project --assignee "
                     "--state --comment --as --name --priority --json --body --mine; a comment from a file is "
                     "`--comment @<file>`")
        elif not ref and a:
            ref = a
        elif a and not a.startswith("--"):
            words.append(a)
        i += 1

    # A comment whose whole text is `@<path>` is a file nobody read: the hook reads `@<file>` before the
    # applier runs, so one that reaches here was typed where no file is (or reached Plane another way). Seven
    # handoff comments went onto DGO-1849/1861 as bare paths and the work they carried never arrived (issues/
    # a-comment-given-as-at-file-…). Said loudly, first; refused once every caller is known not to rely on it
    # (AGENTS.md rule 8).
    said = comment or (" ".join(words) if verb == "comment" else "")
    if re.fullmatch(r"@\S+", said.strip()):
        log(f"WARNING: tasks {verb} {ref}: the comment is only «{said.strip()}» — a file that was not read, "
            "posted as typed. Write `--comment @<file>` with a file this bbox can read; this will be refused")

    if verb == "batch":
        # `tasks batch @actions.jsonl` — the hook puts the file's text where the ref would be. Each line
        # runs through the same verbs as the command line, in THIS process, so the project's items are
        # paged once for the whole batch (`_ISSUES`) instead of once per action: with N items at
        # 60 requests a minute, a triage of 200 items was 200 runs of minutes each (2026-11-03).
        if (ref or "").startswith("@"):
            sys.exit(f"[project-pln] batch {ref}: the file was not read — put `@<file>` right after `batch`")
        # split on "\n" only: splitlines() also cuts at U+2028/U+2029, which a comment may carry
        lines = [ln for ln in (ref or "").lstrip("﻿").split("\n") if ln.strip()]
        if not lines:
            sys.exit("[project-pln] tasks batch @<file.jsonl> — one {\"verb\",\"ref\",\"comment\"?,\"words\"?} per line")
        rc = 0
        for n, line in enumerate(lines, 1):
            try:
                act = json.loads(line)
            except ValueError as e:
                print(f"  #{n}: not JSON ({e}) — skipped")
                rc = 1
                continue
            if not isinstance(act, dict):
                print(f"  #{n}: not an object — skipped")
                rc = 1
                continue
            v, r, w = act.get("verb"), str(act.get("ref") or ""), act.get("words") or []
            if (v not in ("done", "start", "comment", "take", "label", "unlabel", "link", "rm")
                    or not re.fullmatch(r"[A-Z][A-Z0-9]*-\d+", r) or not isinstance(w, list)):
                print(f"  #{n}: {v} {r}: not a batch verb, a ref and a list of words — skipped")
                rc = 1
                continue
            one = [v, r] + [str(x) for x in w]
            if act.get("comment"):
                one += ["--comment", str(act["comment"])]
            one += ["--as", slug]
            try:
                rc |= main(one) or 0
            except (SystemExit, Exception) as e:   # one item's failure is that item's, not the batch's
                print(f"  #{n}: {v} {r}: {e}")
                rc = 1
        return rc

    # --name and --priority belong to `new` and `edit` alone: taken by another verb they would be dropped in
    # silence, the very thing DGO-1727 closed for unknown flags
    if (new_name or priority) and verb not in ("new", "edit"):
        sys.exit(f"[project-pln] tasks {verb}: --name and --priority are for `new` and `edit` only")
    # `new` takes a PROJECT where the others take an item: `tasks new DGO "name"`, or `--project DGO "name"`.
    if verb == "new":
        pos = [x for x in [ref] + words if x]
        if pos and project and pos[0] == project:      # `new DGO "name" --project DGO`: the project, said twice
            pos = pos[1:]
        elif pos and not project:
            project, pos = pos[0], pos[1:]
        if new_name and pos:
            sys.exit(f"[project-pln] tasks new: the name is given twice (--name and «{' '.join(pos)}») — give it once")
        new_name = new_name or " ".join(pos)
        ref, words = "", []
        if not re.fullmatch(r"[A-Z][A-Z0-9]*", project or "") or not new_name.strip():
            sys.exit('[project-pln] tasks new <PROJECT> "name" [--comment "description"|@file] [--priority p]')
    if verb in ("edit", "rm"):
        if words:
            sys.exit(f"[project-pln] tasks {verb} {ref}: «{' '.join(words)}» is not a flag's value — the name is "
                     "--name, the words are --comment")
        if project and ref and "-" in ref and ref.rsplit("-", 1)[0] != project:
            sys.exit(f"[project-pln] tasks {verb} {ref}: the ref names {ref.rsplit('-', 1)[0]}, not {project}")
    if priority and priority not in ("urgent", "high", "medium", "low", "none"):
        sys.exit(f"[project-pln] tasks: --priority is urgent|high|medium|low|none, not {priority!r}")
    # A ref NAMES its project: `DGO-12` is in DGO. So `--project` is only needed to list, and a verb
    # that takes one item never has to be told twice which project it is in.
    if not project and ref and "-" in ref:
        project = ref.rsplit("-", 1)[0]
    # No project and no ref: this is "what is mine", and the answer is not "go and name a project".
    # Every project is searched and only the items assigned to me are kept — with `--assignee <name>`
    # the same rule applies to that person. A single project is a convenience default, never a
    # requirement the caller has to remember.
    all_projects = not project and not ref

    key, my_id, my_email = token_for(slug)
    if REMOTE and not my_id:
        my_id, my_email = me_from_app()
    p = Plane(key, my_id, my_email)
    projects = project_list(p)
    if all_projects:
        wanted = projects
    else:
        wanted = [x for x in projects if x.get("identifier") == project]
        if not wanted:                                         # created since the cache was written?
            projects = project_list(p, fresh=True)
            wanted = [x for x in projects if x.get("identifier") == project]
        if not wanted:
            sys.exit(f"[project-pln] no project with identifier {project} (have: "
                     f"{', '.join(sorted(x.get('identifier','?') for x in projects))})")
    if all_projects:
        # ONE ceiling for the whole sweep: with no `--project` this walks every project in the workspace
        # (5 here, ~N items), and a ceiling per project would bound nothing.
        READ.begin(f"items of {len(wanted)} projects")
        cols = []
        for x in wanted:
            cols += collect(p, x, want_mine, assignee, state_filter, with_modules=as_json)
        rows = sorted(cols, key=lambda r: (r["project"], int(r["ref"].rsplit("-", 1)[-1] or 0)))
        if as_json:
            print(json.dumps({"tasks": rows}, ensure_ascii=False))
        else:
            for r in rows:
                who = ", ".join(r["assignees"]) or "—"
                print(f"{r['ref']:>8}  {r['state']:<8} {r['priority']:<7} {who:<12} {r['name']}")
            print(f"  ({len(rows)} items across {len(wanted)} projects)")
        return 0
    proj = wanted[0]
    pid, P = proj["id"], f"/projects/{proj['id']}"
    states, labels, modules = project_meta(p, pid)
    people = {}

    def uid_name(uid: str) -> str:
        """A name for a bare assignee id. The workspace's member list is one request, cached."""
        if not people:
            for m in p.page("/members/") or []:
                mem = m.get("member") or m.get("member_id") or m.get("id")
                if isinstance(mem, str):
                    people[mem] = m.get("display_name") or m.get("email") or mem[:8]
        return people.get(uid, uid[:8])

    def names_of(it: dict) -> list:
        """Assignee display names, from the EXPANDED objects when they are there.

        `?expand=assignees` is not a nicety: resolving each assignee id separately costs one request
        per person per item against a 60-req/min key. `/api/v1/users/<id>/` is not even a route in
        this build — that is why the first version printed a uuid prefix instead of a name.
        """
        out = []
        for a in (it.get("assignees") or []):
            if isinstance(a, dict):
                out.append(a.get("display_name") or a.get("email") or a.get("id", "")[:8])
            else:
                out.append(uid_name(a))
        return out

    def ids_of(it: dict) -> list:
        return [a if isinstance(a, str) else a.get("id") for a in (it.get("assignees") or [])]

    def app_link(iid: str) -> str:
        """The work item on Plane's own host — the address the app itself answers on."""
        return f"{WEB}/{WS_SLUG}/projects/{pid}/issues/{iid}"

    def console_link(ref: str) -> str:
        """The same work item, opened INSIDE the office, by its key (`item_link`)."""
        return item_link(ref)

    def shape(it: dict) -> dict:
        mod = module_of(it, modules, None)   # what the answer itself names; `show` asks the modules' lists
        return {"ref": f"{proj['identifier']}-{it.get('sequence_id')}", "id": it["id"],
                "project": proj["identifier"], "name": it.get("name", ""),
                "state": (it.get("state") or {}).get("name") if isinstance(it.get("state"), dict)
                         else next((s["name"] for s in states.values() if s["id"] == it.get("state")), ""),
                "group": (it.get("state") or {}).get("group") if isinstance(it.get("state"), dict)
                         else next((s["group"] for s in states.values() if s["id"] == it.get("state")), ""),
                "priority": it.get("priority") or "none",
                "labels": [labels.get(l if isinstance(l, str) else l.get("id"), "") for l in
                           (it.get("label_ids") or it.get("labels") or [])],
                "assignees": names_of(it),
                "module": mod,
                # a person's link (DGO-1433): `/go/<KEY>`; the console's own route stays readable as `console_url`
                "url": console_link(f"{proj['identifier']}-{it.get('sequence_id')}") or app_link(it["id"]),
                "console_url": console_link(f"{proj['identifier']}-{it.get('sequence_id')}"),
                "app_url": app_link(it["id"]),
                "updated_at": it.get("updated_at") or ""}

    def issues(query: str = "") -> list:
        """Every item of the project, paged ONCE per run (a `done` used to page them three times) — and
        once per `batch`, whose actions share this process (`_ISSUES`, keyed by the project + query).

        This is the read that can be minutes long, so it ARMS the deadline and the progress line: every
        verb below reaches it first, which is why nothing else has to remember to.

        `query` is left for a SERVER-SIDE filter, and on THIS edition there is none to give it: Plane
        CE answers `filters=`/`pql` with 400 ("PQL and structured filters are not supported on this
        Plane edition … filter results client-side"), measured 2026-11-04, so `list` still pages the
        whole project and filters here. One page is 18-43 s on a loaded host (see the issue), which is
        why every verb that needs ONE item must not come through here — `find()` does not."""
        key = pid + ("?" + query if query else "")
        if key not in _ISSUES:
            READ.begin(f"{proj['identifier']} items")
            q = f"{P}/issues/?expand=labels,assignees" + (f"&{query}" if query else "")
            _ISSUES[key] = list(p.page(q))
        return _ISSUES[key]

    def find(which: str) -> dict:
        """ONE item, ONE request: `/work-items/<PROJECT>-<n>/`.

        The old way resolved a ref by paging the project's `/issues/` and matching `sequence_id` — and
        Plane materialises the WHOLE project on every one of those requests (no LIMIT: every item,
        with its description blobs, paginated in Python), so `show` on DGO (1 340 items, per_page 50)
        needed 27 full passes. Measured 2026-11-04 on hp-laptop: one page 18-25 s, `show` minutes, and
        `show`/`done`/`comment` unusable. The identifier route answers the same item directly (3-7 s
        under the same load) and its payload already carries `state` as an object, which `shape()`
        reads. The paging path stays as the fallback: an office whose app predates the route, or a ref
        that is not `<PROJECT>-<n>`.
        """
        want = which.rsplit("-", 1)[-1]
        out, code = http("GET", f"{p.base}/work-items/{proj['identifier']}-{want}/", None, p.h)
        if code == 200 and isinstance(out, dict) and out.get("id"):
            return out
        for attempt in (0, 1):
            for it in issues():
                if str(it.get("sequence_id")) == want:
                    return it
            if attempt == 0 and any(k.split("?")[0] == pid for k in _ISSUES):
                for k in [k for k in _ISSUES if k.split("?")[0] == pid]:
                    del _ISSUES[k]       # paged earlier in this process: an item made since is not in it yet
        sys.exit(f"[project-pln] no work item {which} in {proj['identifier']}")

    def is_mine(it: dict) -> bool:
        """`--mine` matches the ACCOUNT, by id when the payload carries it and by address otherwise.

        Both are needed: an expanded assignee object carries `id` and `email`, a bare one carries only
        a uuid, and the vault instance records the account's address as well as its id — so a rename
        in Plane cannot silently turn "my tasks" into an empty list.
        """
        if my_id and my_id in ids_of(it):
            return True
        if not my_email:
            return False
        return any(isinstance(a, dict) and str(a.get("email") or "").lower() == my_email.lower()
                   for a in (it.get("assignees") or []))

    if verb == "list":
        raw = issues()
        if want_mine:
            raw = [it for it in raw if is_mine(it)]
        if assignee:
            want = assignee.strip().lower()
            raw = [it for it in raw if want in [n.lower() for n in names_of(it)]]
        rows = [shape(it) for it in raw]
        if state_filter:
            rows = [r for r in rows if r["group"] == state_filter]
        rows.sort(key=lambda r: int(r["ref"].rsplit("-", 1)[-1] or 0))
        if as_json and modules:
            # the JSON carries `module` (the text list does not print it): from the modules' lists (DGO-962)
            members = module_members(p, pid, modules)
            for r in rows:
                r["module"] = r["module"] or members.get(str(r["id"]), "")
        if as_json:
            print(json.dumps({"tasks": rows}, ensure_ascii=False))
        else:
            for r in rows:
                who = ", ".join(r["assignees"]) or "—"
                print(f"{r['ref']:>8}  {r['state']:<8} {r['priority']:<7} {who:<12} {r['name']}")
            print(f"  ({len(rows)} items in {proj['identifier']})")
        return 0

    if verb == "show":
        if not ref:
            sys.exit("[project-pln] tasks show <REF>")
        t = shape(find(ref))
        if not t["module"] and modules:
            t["module"] = module_members(p, pid, modules, want=str(t["id"])).get(str(t["id"]), "")   # DGO-962
        # the files on it — what the store confirmed, by the name and size the item shows
        got, code = http("GET", f"{p.base}{P}/issues/{t['id']}/issue-attachments/", None, p.h)
        t["files"] = [f"{(a.get('attributes') or {}).get('name') or a.get('id')} "
                      f"({(a.get('attributes') or {}).get('size') or 0} bytes)"
                      for a in (got if code == 200 and isinstance(got, list) else [])]
        if want_body:
            # the item's own words — a request quoted verbatim, a meeting's transcript — as plain text
            got, code = http("GET", f"{p.base}{P}/issues/{t['id']}/", None, p.h)
            body = got if code == 200 and isinstance(got, dict) else {}
            t["description"] = body.get("description_stripped") or html.unescape(
                re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", body.get("description_html") or "")).strip()
            t["description"] = re.sub(r"<[^>]+>", "", t["description"]).strip()
        if as_json:
            print(json.dumps({"tasks": [t]}, ensure_ascii=False))
        else:
            print(f"{t['ref']}  {t['name']}\n  state: {t['state']} ({t['group']})   priority: {t['priority']}"
                  f"\n  assignees: {', '.join(t['assignees']) or '—'}"
                  f"\n  labels: {', '.join(l for l in t['labels'] if l) or '—'}"
                  f"\n  module: {t['module'] or '—'}"
                  f"\n  files: {', '.join(t['files']) or '—'}\n  {t['url']}")
            if want_body:
                print("\n" + (t["description"] or "(no description)"))
        return 0

    def para(text: str) -> str:
        """Plain text as Plane's description/comment HTML: escaped, one paragraph per line."""
        return "".join(f"<p>{html.escape(ln)}</p>" for ln in text.split("\n")) or "<p></p>"

    if verb == "new":
        # A request is a work item first (AGENTS.md): before this verb, a new item went through a plan file
        # (DGO-1252 itself had to). The item is the request's own words; its link is printed, as every verb's.
        body = {"name": new_name.strip()[:255]}
        if comment:
            body["description_html"] = para(comment)
        if priority:
            body["priority"] = priority
        made = p.call("POST", f"{P}/issues/", body)
        new_ref = f"{proj['identifier']}-{made.get('sequence_id')}"
        log(f"{new_ref} created")
        t = shape(made)
        if as_json:
            print(json.dumps({"ok": True, **{k: t[k] for k in ("ref", "id", "state", "group", "url")}}, ensure_ascii=False))
        else:
            print(f"  {t['ref']}  {t['state']}  {t['url']}")
        return 0

    if verb not in ("start", "done", "comment", "take", "attach", "label", "unlabel", "link", "edit", "rm"):
        sys.exit(f"[project-pln] unknown verb {verb!r} — see ./bbox project-pln tasks --help")
    if not ref:
        sys.exit(f"[project-pln] tasks {verb} <REF>")

    it = find(ref)
    # The words after the ref (`words`, by position): the files of `attach`, the labels of `label`, the
    # items of `link` — never a flag's value (`--project MEET` made a label «MEET» while they were picked
    # by value, the second reader of DGO-1005).
    more = words
    if verb == "label":
        # A meeting that was read is `נותח` (DGO-1005: «a reference that you paid attention, and that you
        # transformed it into tasks»), after `הקלטה` and `תומלל`. Labels are ADDED by name, a name the
        # project does not have yet is created there, and none is ever taken off.
        names = [n.strip() for a in more for n in a.split(",") if n.strip()]
        if not names:
            sys.exit("[project-pln] tasks label <REF> <label>[,<label>…]")
        by_name = {v: k for k, v in labels.items()}
        have = [l if isinstance(l, str) else l.get("id") for l in (it.get("label_ids") or it.get("labels") or [])]
        for n in names:
            if n not in by_name:
                # The list is a cache (30 min): a label made since — by the owner, or by another office —
                # is read fresh once before one is made, or Plane refuses the second as a duplicate.
                by_name.update({l["name"]: l["id"] for l in cached(f"{pid}:labels", lambda: p.page(f"{P}/labels/"), fresh=True)})
            if n not in by_name:
                # --olive of the one palette (theme-tokens.css): a label's colour is a field of Plane, where
                # no token can be named, so the palette's value is written (G82 counts no other).
                by_name[n] = p.call("POST", f"{P}/labels/", {"name": n, "color": "#56693f"})["id"]
                cached(f"{pid}:labels", lambda: p.page(f"{P}/labels/"), fresh=True)
            if by_name[n] not in have:
                have.append(by_name[n])
        p.call("PATCH", f"{P}/issues/{it['id']}/", {"labels": have})
        it["label_ids"] = it["labels"] = have          # the cached item, for the next action of a `batch`
        log(f"{ref} labelled {', '.join(names)}")
        if as_json:
            print(json.dumps({"ok": True, "ref": ref, "labels": names}, ensure_ascii=False))
        return 0
    if verb == "unlabel":
        # The deliberate inverse of `label`, by name: only the labels named are taken off, never all of them.
        # A label put on wrongly is otherwise there for good — a `בעלים` on an item the owner has nothing to
        # do on puts it in the list he reads as his own work (the owner's order, 2026-11-02, DGO-1117).
        names = [n.strip() for a in more for n in a.split(",") if n.strip()]
        if not names:
            sys.exit("[project-pln] tasks unlabel <REF> <label>[,<label>…]")
        by_name = {v: k for k, v in labels.items()}
        drop = {by_name[n] for n in names if n in by_name}
        have = [l if isinstance(l, str) else l.get("id") for l in (it.get("label_ids") or it.get("labels") or [])]
        keep = [l for l in have if l not in drop]
        if len(keep) != len(have):
            p.call("PATCH", f"{P}/issues/{it['id']}/", {"labels": keep})
            it["label_ids"] = it["labels"] = keep      # the cached item, for the next action of a `batch`
        log(f"{ref} unlabelled {', '.join(names)} ({len(have) - len(keep)} removed)")
        if as_json:
            print(json.dumps({"ok": True, "ref": ref, "removed": len(have) - len(keep)}, ensure_ascii=False))
        return 0
    if verb == "link":
        # A meeting and every item opened from it, RELATED: Plane's `relates_to` is symmetric, so each side
        # shows the other in its own Relations, in any project (DGO-1005: «all the tickets created from
        # that meeting linked to that meeting»). A ref is resolved by its identifier, one request each; an
        # item already related is not related twice.
        if not more:
            sys.exit("[project-pln] tasks link <REF> <REF> [<REF>…]")
        R = f"{P}/work-items/{it['id']}/relations/"
        known = p.call("GET", R)
        known = {str(x.get("issue_id")) for x in (known.get("relates_to") or [])} if isinstance(known, dict) else set()
        new = []
        for o in more:
            got, code = http("GET", f"{p.base}/work-items/{o}/", None, p.h)
            if code != 200 or not isinstance(got, dict) or not got.get("id"):
                sys.exit(f"[project-pln] no work item {o} (HTTP {code})")
            if str(got["id"]) != str(it["id"]) and str(got["id"]) not in known and str(got["id"]) not in new:
                new.append(str(got["id"]))
        if new:
            p.call("POST", R, {"relation_type": "relates_to", "issues": new})
        log(f"{ref} relates to {', '.join(more)} ({len(new)} new)")
        if as_json:
            print(json.dumps({"ok": True, "ref": ref, "related": more, "new": len(new)}, ensure_ascii=False))
        return 0
    if verb == "attach":
        # A request's files belong ON its work item (the owner, 2026-10-07): Plane signs a form for
        # each, the file goes to the store through it, and the item is told it arrived — the same
        # three steps its own screen takes. The paths are this container's (hooks/tasks brings them).
        # …and NOT the value of a flag: `--as azaria` is two arguments, and the second is a name, not
        # a file (measured 2026-10-08: `attach DGO-500 --as azaria shot.png` tried to open `azaria`).
        # Each file is its own: one that Plane or the store refuses is said by its name and the reason, and the
        # rest still go (DGO-1628: Plane takes no .html, the first file of three was a mock, and the run ended
        # there — the two sheets after it never went, and the one line named an API path, not a file). The exit
        # says whether ALL of them landed: 0; ANSWERED_REFUSED when Plane answered and refused some for good; 1 when a
        # refusal may pass another time (`final()` below). Only a
        # Plane that does not ANSWER stops the run, with the words hooks/tasks keeps the write by (nothing after
        # it would get through either).
        paths = words
        if not paths:
            sys.exit("[project-pln] tasks attach <REF> <file> [<file>…]")
        A = f"{P}/issues/{it['id']}/issue-attachments/"

        def no_answer(method: str, path: str, out) -> None:
            sys.exit(f"[project-pln] {method} {path} → HTTP -1: {out.get('error') if isinstance(out, dict) else out}")

        def said(out) -> str:
            """Plane's own words: its refusals are JSON inside the error text `http()` keeps."""
            words_ = out.get("error") if isinstance(out, dict) else out
            try:
                inner = json.loads(words_)
                words_ = (inner.get("error") or inner.get("detail") or words_) if isinstance(inner, dict) else words_
            except (TypeError, ValueError):
                pass
            return str(words_ or "")[:200]

        def final(code: int, out=None) -> bool:
            """A refusal that sending again cannot change: Plane or its store ANSWERED, and about the file (a type
            it takes not, a size). A door between routes (an empty 404), a restart (5xx), a limit (408, 429), a
            sign-in (401, 403) and no answer (-1) pass — a replay that meets one keeps the write (the second
            reader of DGO-1628: a replay runs just as the path comes back, which is when these are seen)."""
            if code in (401, 403, 408, 429) or not 400 <= code < 500:
                return False
            return not (code == 404 and said(out).startswith("the door answered 404 with no body"))

        # What is on the item already, by name and size: a kept attach that the outbox replays, or a person who
        # runs it again after one file was refused, must not put the files that landed there a second time.
        # Plane lists only files whose upload it confirmed. (A name Plane cleans — `..`, a leading dot — never
        # matches, so such a file is sent again; a DIFFERENT file of the same name and size is taken as there.)
        got, code = http("GET", f"{p.base}{A}", None, p.h)
        if code == -1:
            no_answer("GET", A, got)
        if code != 200 or not isinstance(got, list):
            log(f"what is on {ref} already could not be read (HTTP {code}) — every file is sent")

        def size_of(a: dict) -> int:
            try:
                return int((a.get("attributes") or {}).get("size") or 0)
            except (TypeError, ValueError):
                return -1
        have = {((a.get("attributes") or {}).get("name"), size_of(a))
                for a in (got if code == 200 and isinstance(got, list) else []) if isinstance(a, dict)}
        landed, refused, passing = [], [], False   # passing: a failure that may not be one next time
        for path in paths:
            name = os.path.basename(path)
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            try:
                with open(path, "rb") as f:
                    blob = f.read()
            except OSError as e:
                refused.append({"name": name, "why": f"it cannot be read here ({e.strerror or e})"})
                log(f"{name}: NOT attached — {refused[-1]['why']}")
                continue
            if (name, len(blob)) in have:
                landed.append(name)
                log(f"{name} ({len(blob)} bytes) is on {ref} already")
                continue
            made, code = http("POST", f"{p.base}{A}", {"name": name, "size": len(blob), "type": kind}, p.h)
            if code == -1:
                no_answer("POST", A, made)
            why, last = "", True
            if code not in (200, 201, 204) or not isinstance(made, dict) or not made.get("asset_id"):
                why, last = f"Plane refused it (HTTP {code}: {said(made)})", final(code, made)
            else:
                form = made.get("upload_data") or {}
                up = upload(form.get("url") or "", form.get("fields") or {}, kind, blob)
                if up not in (200, 201, 204):
                    # (a 404 from the store is never about the file — it is the link door between routes,
                    # whose empty body upload() does not keep: it passes, like the API's own)
                    why, last = f"the store did not take it (HTTP {up})", final(up) and up != 404
                else:
                    done_out, done = http("PATCH", f"{p.base}{A}{made['asset_id']}/", {}, p.h)
                    if done == -1:
                        no_answer("PATCH", f"{A}{made['asset_id']}/", done_out)
                    if done not in (200, 201, 204):
                        why, last = f"Plane did not confirm it (HTTP {done}: {said(done_out)})", final(done, done_out)
            if why:
                passing = passing or not last
                if not last:
                    why += " — send it again later"
                refused.append({"name": name, "why": why})
                log(f"{name}: NOT attached — {why}")
                continue
            have.add((name, len(blob)))
            landed.append(name)
            log(f"{name} ({len(blob)} bytes) is on {ref}")
        t = shape(it)
        if as_json:
            print(json.dumps({"ok": not refused, "ref": ref, "attached": len(landed), "files": landed,
                              "refused": refused, "url": t["url"]}, ensure_ascii=False))
        elif refused:
            print(f"  {t['ref']}  {len(landed)} of {len(paths)} file(s) attached — not: "
                  f"{', '.join(r['name'] for r in refused)}  {t['url']}")
        else:
            print(f"  {t['ref']}  {len(landed)} file(s) attached  {t['url']}")
        # 0: all of them are on it. ANSWERED_REFUSED: the rest are, and every refusal is final — a replay lets it go.
        # 1: something may yet go another time — a replay keeps the write, a person reads the line above.
        return 0 if not refused else 1 if passing else ANSWERED_REFUSED
    if verb == "comment":
        # the words after the ref, never a flag's VALUE: joining every non-flag argument made `--as azaria`
        # part of the comment ("… azaria"), and a batch action without text post its slug alone
        body = comment or " ".join(words)
        if not body:
            sys.exit("[project-pln] tasks comment <REF> \"…\"")
        p.call("POST", f"{P}/issues/{it['id']}/comments/", {"comment_html": f"<p>{body}</p>"})
        log(f"commented on {ref}")
        if as_json:
            print(json.dumps({"ok": True, "ref": ref, "comment": body}, ensure_ascii=False))
        return 0

    if verb == "edit":
        change = {}
        if new_name.strip():
            change["name"] = new_name.strip()[:255]
        if priority:
            change["priority"] = priority
        if comment:
            # the words being replaced are kept ON the item first: a request quoted verbatim must never be lost
            # to an edit (the owner's own words are the brief, AGENTS.md)
            got, code = http("GET", f"{p.base}{P}/issues/{it['id']}/", None, p.h)
            if code != 200 or not isinstance(got, dict) or "description_html" not in got:
                # an answer without the field is not «no description»: what is there could not be kept
                sys.exit(f"[project-pln] {ref}: its description could not be read (HTTP {code}), so it is not replaced")
            old = got.get("description_html") or ""
            if old.strip() and old.strip() not in ("<p></p>", "<p><br></p>"):   # an image alone is words too
                p.call("POST", f"{P}/issues/{it['id']}/comments/",
                       {"comment_html": "<p>התיאור לפני העריכה:</p>" + old})
            change["description_html"] = para(comment)
        if not change:
            sys.exit('[project-pln] tasks edit <REF> [--name "…"] [--priority p] [--comment "new description"|@file]')
        p.call("PATCH", f"{P}/issues/{it['id']}/", change)
        log(f"{ref} edited: {', '.join(k.replace('_html', '') for k in change)}")
    elif verb == "rm":
        # Never a delete (an item's history, its files and its relations would go with it): the project's
        # cancelled state, with the reason on the item — `tasks start` brings it back.
        if not comment:
            sys.exit('[project-pln] tasks rm <REF> --comment "why" — an item is cancelled with its reason, never deleted')
        st = states.get("cancelled")
        if not st:
            sys.exit(f"[project-pln] {proj['identifier']} has no state in group cancelled — nothing was changed")
        # the reason first: if the second request fails, the item says why it was to be cancelled, and is not
        # cancelled with no reason
        p.call("POST", f"{P}/issues/{it['id']}/comments/", {"comment_html": para(comment)})
        p.call("PATCH", f"{P}/issues/{it['id']}/", {"state": st["id"]})
        log(f"{ref} → {st['name']} (cancelled), with the reason")
    elif verb == "take":
        mine = [my_id] if my_id else []
        others = ids_of(it)
        p.call("PATCH", f"{P}/issues/{it['id']}/", {"assignees": others + mine})
        it["assignees"] = others + mine                # the cached item, for the next action of a `batch`
        log(f"{ref} assigned to {uid_name(my_id) if my_id else slug}")
    else:
        group = "started" if verb == "start" else "completed"
        st = states.get(group)
        if not st:
            sys.exit(f"[project-pln] {proj['identifier']} has no state in group {group}")
        p.call("PATCH", f"{P}/issues/{it['id']}/", {"state": st["id"]})
        log(f"{ref} → {st['name']} ({group})")
        if comment:
            p.call("POST", f"{P}/issues/{it['id']}/comments/", {"comment_html": f"<p>{comment}</p>"})
            log("…with the closing comment")
    # the state AFTER the change: one direct read of this item, not another page through all of them
    fresh, code = http("GET", f"{p.base}{P}/issues/{it['id']}/?expand=labels,assignees", None, p.h)
    after = shape(fresh if code == 200 and isinstance(fresh, dict) and fresh.get("id") else it)
    if as_json:
        print(json.dumps({"ok": True, **{k: after[k] for k in ("ref", "id", "state", "group", "url")}},
                         ensure_ascii=False))
    else:
        print(f"  {after['ref']}  {after['state']}  {after['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
