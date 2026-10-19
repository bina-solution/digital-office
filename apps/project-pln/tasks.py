#: tasks — read and move work items in this office's Plane, from the CLI
#
# tasks list [--project DGO] [--mine|--assignee <name>] [--state unstarted|started|completed] [--json]
# tasks show DGO-12
# tasks start DGO-12            # → the state in group `started`
# tasks done DGO-12 [--comment "what was done, where, and the proof"]
# tasks comment DGO-12 "…"
# tasks take DGO-12             # assign it to me (the account behind the chosen token)
# tasks attach DGO-12 <file> [<file>…]   # the files a request came with, on its work item
# …any of the above with `--as <slug>` to act as that office agent (its own vault account + token)
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
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = (os.environ.get("PLANE_API_URL") or "http://127.0.0.1").rstrip("/")
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


def http(method: str, url: str, body=None, headers=None, tries: int = 6):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode("utf-8", "replace")
            return (json.loads(raw) if raw.strip() else {}), r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:          # Plane's own limit is 60/min per key
                time.sleep(5 * (attempt + 1))
                continue
            return {"error": e.read().decode("utf-8", "replace")[:300]}, e.code
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
    """(token, user_id, email) for an office agent — the vault instance is the contract."""
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

class Plane:
    def __init__(self, key: str, me_id: str = "", me_email: str = ""):
        self.base = f"{BASE}/api/v1/workspaces/{WS_SLUG}"
        self.h = {"X-API-Key": key}
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
    comment = ""
    ref = ""
    args = list(rest)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
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
        i += 1

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
        return f"{CONSOLE}/#/m/{CONSOLE_MODULE}/{WS_SLUG}/projects/{pid}/issues/{iid}"

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

    _issues: list = []

    def issues() -> list:
        """Every item of the project, paged ONCE per run (a `done` used to page them three times)."""
        if not _issues:
            _issues.extend(p.page(f"{P}/issues/?expand=labels,assignees"))
        return _issues

    def find(which: str) -> dict:
        want = which.rsplit("-", 1)[-1]
        for it in issues():
            if str(it.get("sequence_id")) == want:
                return it
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
        if as_json:
            print(json.dumps({"tasks": [t]}, ensure_ascii=False))
        else:
            print(f"{t['ref']}  {t['name']}\n  state: {t['state']} ({t['group']})   priority: {t['priority']}"
                  f"\n  assignees: {', '.join(t['assignees']) or '—'}"
                  f"\n  labels: {', '.join(l for l in t['labels'] if l) or '—'}"
                  f"\n  module: {t['module'] or '—'}"
                  f"\n  files: {', '.join(t['files']) or '—'}\n  {t['url']}")
        return 0

    if verb not in ("start", "done", "comment", "take", "attach"):
        sys.exit(f"[project-pln] unknown verb {verb!r} — see ./bbox project-pln tasks --help")
    if not ref:
        sys.exit(f"[project-pln] tasks {verb} <REF>")

    it = find(ref)
    if verb == "attach":
        # A request's files belong ON its work item (the owner, 2026-10-07): Plane signs a form for
        # each, the file goes to the store through it, and the item is told it arrived — the same
        # three steps its own screen takes. The paths are this container's (hooks/tasks brings them).
        # …and NOT the value of a flag: `--as azaria` is two arguments, and the second is a name, not
        # a file (measured 2026-10-08: `attach DGO-500 --as azaria shot.png` tried to open `azaria`).
        paths = [a for a in args if a and not a.startswith("--") and a not in (ref, slug, comment)]
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
        body = comment or " ".join(a for a in args if a and not a.startswith("--") and a != ref)
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
