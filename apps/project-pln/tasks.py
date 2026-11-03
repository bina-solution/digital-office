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
# tasks link MEET-15 DGO-1003 FPG-2 …    # related both ways, across projects (Plane's `relates_to`)
# tasks batch @actions.jsonl             # many of the verbs above in ONE run: one JSON object per line,
#                                        # {"verb","ref","comment"?,"words"?[]} — the project is paged once
# …any of the above with `--as <slug>` to act as that office agent (its own vault account + token)
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


# The project list is the slowest read in this API (measured 2026-10-01: ~55 s under load, holding one of
# the two gunicorn workers), and every verb used to start with it; states/labels/modules change only when
# someone edits the project. All four come from a small file inside the container for CACHE_TTL seconds,
# and a miss on a project identifier re-reads once (a project created since the cache was written).
CACHE = os.environ.get("TASKS_CACHE") or "/tmp/plane-tasks-cache.json"
CACHE_TTL = int(os.environ.get("TASKS_CACHE_TTL") or "1800")


def cached(key: str, fetch, fresh: bool = False):
    try:
        with open(CACHE) as f:
            data = json.load(f)
    except Exception:                                          # noqa: BLE001 — no cache yet / corrupt
        data = {}
    hit = data.get(key)
    if not fresh and isinstance(hit, dict) and time.time() - hit.get("t", 0) < CACHE_TTL:
        return hit["v"]
    v = fetch()
    data[key] = {"t": time.time(), "v": v}
    try:
        with open(CACHE + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(CACHE + ".tmp", CACHE)
    except Exception:                                          # noqa: BLE001 — a cache is never required
        pass
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


# A Plane that does not answer must not hold a verb for half an hour: six tries × 90 s per request and several
# requests per verb, with every caller on the Mac's engine queued behind them (measured 2026-11-02 17:40: seven
# calls stuck 20–35 min while the HP, which runs Plane, did not answer, and the engine at load 140). A request
# whose connection fails or times out is tried once more; then this process stops asking (`DOWN`), and every
# later request fails at once with the reason.
DOWN = ""


def http(method: str, url: str, body=None, headers=None, tries: int = 6):
    global DOWN
    if DOWN:
        return {"error": f"Plane is not answering ({DOWN})"}, -1
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:          # the project list takes ~55 s under load
                raw = r.read().decode("utf-8", "replace")
            return (json.loads(raw) if raw.strip() else {}), r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:          # Plane's own limit is 60/min per key
                time.sleep(5 * (attempt + 1))
                continue
            return {"error": e.read().decode("utf-8", "replace")[:300]}, e.code
        except (urllib.error.URLError, OSError) as e:          # no connection, or no answer in time
            if attempt < min(tries, 2) - 1:
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



def collect(p, proj, want_mine, assignee, state_filter) -> list:
    """The shaped, filtered rows of ONE project — the body `list` runs per project."""
    pid, P = proj["id"], f"/projects/{proj['id']}"
    states, labels, modules = project_meta(p, pid)
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
        mod = ""
        for m in (it.get("module_ids") or []):
            mid = m if isinstance(m, str) else (m.get("module_id") or m.get("id"))
            if modules.get(mid):
                mod = modules[mid]
                break
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
                     "url": f"{WEB}/{WS_SLUG}/projects/{pid}/issues/{it['id']}",
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

    def call(self, method: str, path: str, body=None):
        out, code = http(method, f"{self.base}{path}", body, self.h)
        if code not in (200, 201, 204):
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
        all worked, so nothing pointed at the reader."""
        sep = "&" if "?" in path else "?"
        out = self.call("GET", f"{path}{sep}per_page=50")
        if isinstance(out, list):
            return out
        rows = list((out or {}).get("results") or [])
        while isinstance(out, dict) and out.get("next_page_results") and out.get("next_cursor"):
            out = self.call("GET", f"{path}{sep}per_page=50&cursor={out['next_cursor']}")
            if isinstance(out, list):
                rows += out
                break
            rows += list((out or {}).get("results") or [])
        return rows


#: A project's items, paged once per PROCESS (keyed by the project id): one run of a verb, or one `batch`.
_ISSUES: dict = {}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip() if __doc__ else "")
        return 0
    verb, rest = argv[0], argv[1:]
    project = ""
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
        elif a in ("--project", "--assignee", "--state", "--comment", "--as") and i + 1 < len(args):
            val = args[i + 1]
            i += 1
            if a == "--project":
                project = val
            elif a == "--assignee":
                assignee = val
            elif a == "--state":
                state_filter = GROUP_ALIAS.get(val, val)
            elif a == "--comment":
                comment = val
            elif a == "--as":
                slug = val
        elif not ref and a:
            ref = a
        elif a and not a.startswith("--"):
            words.append(a)
        i += 1

    if verb == "batch":
        # `tasks batch @actions.jsonl` — the hook puts the file's text where the ref would be. Each line
        # runs through the same verbs as the command line, in THIS process, so the project's items are
        # paged once for the whole batch (`_ISSUES`) instead of once per action: with 1,227 items at
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
            if (v not in ("done", "start", "comment", "take", "label", "unlabel", "link")
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
        cols = []
        for x in wanted:
            cols += collect(p, x, want_mine, assignee, state_filter)
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

    def console_link(iid: str) -> str:
        """The same work item, opened INSIDE the office (empty when no console is declared).

        `#/m/<module>/<the app's inner route>` is the shell's deep link: console → module → this
        screen. The shell opens the app in a window of the desktop, frames it on its own host with
        that route, and signs that host in through the office SSO when it has not been shown it yet.
        """
        if not CONSOLE:
            return ""
        return f"{CONSOLE}/#/m/{console_module()}/{WS_SLUG}/projects/{pid}/issues/{iid}"

    def shape(it: dict) -> dict:
        mod = ""
        mids = it.get("module_ids") or it.get("modules") or []
        for m in mids:
            mid = m if isinstance(m, str) else (m.get("module_id") or m.get("id"))
            if modules.get(mid):
                mod = modules[mid]
                break
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
                "url": console_link(it["id"]) or app_link(it["id"]),
                "app_url": app_link(it["id"]),
                "updated_at": it.get("updated_at") or ""}

    def issues() -> list:
        """Every item of the project, paged ONCE per run (a `done` used to page them three times) — and
        once per `batch`, whose actions share this process (`_ISSUES`, keyed by the project)."""
        if pid not in _ISSUES:
            _ISSUES[pid] = list(p.page(f"{P}/issues/?expand=labels,assignees"))
        return _ISSUES[pid]

    def find(which: str) -> dict:
        want = which.rsplit("-", 1)[-1]
        for attempt in (0, 1):
            for it in issues():
                if str(it.get("sequence_id")) == want:
                    return it
            if attempt == 0 and pid in _ISSUES:
                del _ISSUES[pid]         # paged earlier in this process: an item made since is not in it yet
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

    if verb not in ("start", "done", "comment", "take", "attach", "label", "unlabel", "link"):
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
        paths = words
        if not paths:
            sys.exit("[project-pln] tasks attach <REF> <file> [<file>…]")
        A = f"{P}/issues/{it['id']}/issue-attachments/"
        for path in paths:
            name = os.path.basename(path)
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                blob = f.read()
            made = p.call("POST", A, {"name": name, "size": len(blob), "type": kind})
            form = made.get("upload_data") or {}
            code = upload(form.get("url") or "", form.get("fields") or {}, kind, blob)
            if code not in (200, 201, 204):
                sys.exit(f"[project-pln] {name}: the store did not take the file (HTTP {code})")
            p.call("PATCH", f"{A}{made['asset_id']}/", {})
            log(f"{name} ({len(blob)} bytes) is on {ref}")
        t = shape(it)
        print(json.dumps({"ok": True, "ref": ref, "attached": len(paths), "url": t["url"]}, ensure_ascii=False)
              if as_json else f"  {t['ref']}  {len(paths)} file(s) attached  {t['url']}")
        return 0
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

    if verb == "take":
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
