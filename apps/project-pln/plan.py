#!/usr/bin/env python3
"""project-pln/plan.py — apply a DECLARED project plan to the office's Plane, idempotently.

Run by hooks/plan inside the project-pln container — the plan arrives rendered to JSON on STDIN
(an environment variable is one string, and one string is capped at 128 KiB: a plan of ~170 work
items would not have arrived at all), the workspace slug in PLANE_WORKSPACE, and the API key is
fetched from the credential plane at run time (the account bootstrap.py created:
plane_local_api_token-local), or taken from PLANE_LOCAL_API_TOKEN when set.

What a plan declares (apps/project-pln/plans/<name>.yaml):

    project:  { identifier: DGO, name: dgo-dev, description: "...", network: 0 }
              # …or `{ identifier: DGO }` alone: a plan that ADDS modules to a project another plan
              # declares. The project's name, description and lead stay that plan's to state.
    states:   { backlog: מלאי, unstarted: לביצוע, started: בתהליך, completed: בוצע, cancelled: בוטל }
    labels:   [ { name: שער, color: "#8b5cf6" }, ... ]
    modules:
      - key: p1
        name: "שלב 1 · ..."
        status: planned            # backlog | planned | in-progress | paused | completed | cancelled
        description: "..."
        items:
          - key: p1-1              # the work item's stable identity (external_id under source dgo-plan)
            name: "..."
            priority: high         # urgent | high | medium | low | none
            labels: [שער]
            description: |
              free text; "- " lines become a list
        refs: [DGO-311, DGO-476]   # work items that exist already and belong here too: gathered into
                                   # the module, never edited — their words, state and owner stay theirs

Every object is UPSERTED: the project by identifier, a state by its group (Plane creates one per
group with an English name — the plan renames it), a label and a module by name, a work item by
(external_source, external_id) so re-running the hook edits the items in place — titles, priority,
labels, description, module — and never duplicates them. Nothing is ever deleted: a work item that
left the plan stays in Plane with whatever the humans did to it. Work items are created in plan
order, so Plane's sequence numbers (DGO-1, DGO-2, …) follow the phases.

A few keys only: `--only <key>[,<key>…]` on the line, or PLANE_PLAN_ONLY in the environment (the hook's
way in). Those items are looked up by identity and applied; the rest of the plan is not read at all.

Output: `[project-pln] …` lines for the operator and one `RESULT|{json}` line for the hook.
Plane's API is rate-limited (60 requests/minute per key); a 429 is waited out, never failed.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SOURCE = "dgo-plan"                       # external_source every plan-managed work item carries
BASE = (os.environ.get("PLANE_API_URL") or "http://127.0.0.1").rstrip("/")     # caddy → api, in-container
#: Is this run reaching a Plane that runs on a LINKED office? `where.sh` says so by setting PLANE_API_URL to
#: that office's link door; the default (this container's loopback) is the office's own app. Over a link
#: there is NO key to read: the door replaces the peer's claims with the identity it declared for this office
#: and SIGNS it (`apps/dgo-extend/link-proxy.py`, DGO-545), and the token API accepts that identity as if it
#: were a key — exactly what tasks.py does, which shares this contract. Reading this office's vault instead
#: is what stopped `plan office` on vps1 with «no Plane API key … HTTP 404 for plane_local_api_token-local»
#: (DGO-541, measured 2026-10-12).
REMOTE = bool(os.environ.get("PLANE_API_URL")) and not re.match(
    r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", BASE)
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
TOKEN_INSTANCE = os.environ.get("PLANE_TOKEN_INSTANCE") or "plane_local_api_token-local"
DRY = os.environ.get("PLANE_PLAN_DRY_RUN") == "1"

created: list[str] = []
updated: list[str] = []
kept: list[str] = []
problems: list[str] = []
warnings: list[str] = []                  # true, but not a failure: an assignee whose account does not exist yet
READS = WRITES = 0                        # what this run asked of the network, by kind — said in the RESULT
T0 = time.time()


def log(msg: str) -> None:
    print(f"[project-pln] {msg}", flush=True)


def only_keys() -> set:
    """The keys a run is limited to: `--only k1,k2` (or `--only=k1,k2`) on the line, and/or
    PLANE_PLAN_ONLY. Empty means the whole plan."""
    spec = os.environ.get("PLANE_PLAN_ONLY") or ""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            spec += "," + args[i + 1]
        elif a.startswith("--only="):
            spec += "," + a[len("--only="):]
    return {k for k in re.split(r"[,\s]+", spec) if k}


ONLY = only_keys()


# ── the cache ───────────────────────────────────────────────────────────────────
# The project list is the slowest read in this API (tasks.py measured ~55 s under load, 2026-10-01),
# and states, labels and modules change only when a plan or a person edits the project — yet every
# run read all four before touching an item. They come from the file tasks.py keeps (same path, keys
# and TTL: the two tools warm ONE cache), a miss re-reads once, and a run that changes one of them
# (a label it creates, a state it renames) reads it back fresh so the cache never says yesterday.
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


# ── HTTP ────────────────────────────────────────────────────────────────────────
# A Plane that does not answer fails the plan in about two minutes, not in an hour (tasks.py, the same rule
# and why: issues/plane-calls-hang-half-an-hour-when-the-office-that-runs-plane-stalls.yaml).
DOWN = ""


def http(method: str, url: str, body=None, headers=None, tries: int = 6):
    global READS, WRITES, DOWN
    if DOWN:
        return {"error": f"Plane is not answering ({DOWN})"}, -1
    if method == "GET":
        READS += 1
    else:
        WRITES += 1
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
                return (json.loads(raw) if raw else {}), r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt + 1 < tries:
                wait = int(e.headers.get("Retry-After") or 0) or 15
                log(f"rate-limited by Plane — waiting {wait}s")
                time.sleep(wait)
                continue
            if e.code in GONE and method == "GET" and attempt + 1 < tries:
                time.sleep(5 * (attempt + 1))                           # a READ is asked again; a write is not (Transient)
                continue
            return {"error": e.read().decode("utf-8", "replace")[:400]}, e.code
        except (urllib.error.URLError, OSError) as e:                  # no connection, or no answer in time
            if attempt + 1 < min(tries, 2):
                time.sleep(3)
                continue
            DOWN = f"{type(e).__name__}: {e}"
            return {"error": DOWN}, -1
        except Exception as e:                                          # noqa: BLE001
            if attempt + 1 < tries:
                time.sleep(3)
                continue
            return {"error": f"{type(e).__name__}: {e}"}, -1
    return {"error": "gave up"}, -1


def api_key() -> str:
    if REMOTE:                                # the link's door is the key (see REMOTE above)
        return ""
    tok = os.environ.get("PLANE_LOCAL_API_TOKEN")
    if tok:
        return tok
    out, code = http("GET", f"{VAULT}/api/instances/{TOKEN_INSTANCE}/secret")
    tok = ((out or {}).get("secret") or {}).get("token") if code == 200 else ""
    if not tok:
        sys.exit(f"[project-pln] no Plane API key: the credential plane answered HTTP {code} for "
                 f"{TOKEN_INSTANCE} — run `bbox project-pln onboard` first ({out.get('error', '')})")
    return tok


#: What the app's own Caddy answers while the API's workers restart, and how long a write is followed by
#: a pause. Measured 2026-10-06, the first plan of ~300 items: 48 creations in a minute, a 429, and then
#: 502 for the rest — the two gunicorn workers had died under the burst, and the run stopped a sixth of
#: the way in. Plane allows 60 requests a minute per key; one write every 1.1 s stays under it.
GONE = (502, 503, 504)
PACE = 1.1


class Transient(RuntimeError):
    """The API went away under a WRITE — which it may or may not have stored. Never assumed either
    way: the caller asks Plane what is there before it writes again."""


class Plane:
    def __init__(self, slug: str, key: str):
        self.ws = f"{BASE}/api/v1/workspaces/{slug}"
        # No key = a request the link's door authenticates instead (DGO-541/545); never an empty header.
        self.h = {"X-API-Key": key} if key else {}

    def call(self, method: str, path: str, body=None):
        out, code = http(method, f"{self.ws}{path}", body, self.h)
        if code in GONE and method != "GET":
            log(f"Plane's API went away under {method} {path.rsplit('/', 2)[-2]} (HTTP {code}) — waiting for it")
            for _ in range(36):                                         # three minutes, asked every five seconds
                time.sleep(5)
                if http("GET", f"{self.ws}/projects/", headers=self.h, tries=1)[1] == 200:
                    break
            else:
                raise RuntimeError("Plane's API did not come back in three minutes")
            if method == "PATCH":                                       # the same edit twice is the same edit
                return self.call(method, path, body)
            raise Transient(f"{method} {path} → HTTP {code}")
        if code not in (200, 201, 204):
            raise RuntimeError(f"{method} {path} → HTTP {code}: {out.get('error', out)}")
        if method != "GET":
            time.sleep(PACE)
        return out

    def user_id_of(self, person: str, spec: dict) -> str:
        """The Plane user id behind a plan name — from the vault account the plan points at.

        The account's secret carries `user_id` when bootstrap.py stored it; otherwise the account's
        own token answers /users/me. No account yet (the agent's, before onboard created it) is a
        warning, not a failure: the items are created unassigned and the next run assigns them.
        """
        iid = (spec or {}).get("vault") or f"plane_local_api_token-{person}"
        out, code = http("GET", f"{VAULT}/api/instances/{iid}/secret")
        sec = (out or {}).get("secret") or {} if code == 200 else {}
        if sec.get("user_id"):
            return sec["user_id"]
        if sec.get("token"):
            me, c2 = http("GET", f"{BASE}/api/v1/users/me/", headers={"X-API-Key": sec["token"]})
            if c2 == 200 and me.get("id"):
                return me["id"]
        warnings.append(f"{person}: no Plane account behind vault instance {iid} yet — items stay unassigned "
                        f"until it exists (HTTP {code})")
        return ""

    def page(self, path: str) -> list:
        """Every result of a paginated list (Plane: results + next_cursor/next_page_results)."""
        items, cursor = [], None
        while True:
            q = f"{path}{'&' if '?' in path else '?'}per_page=100" + (f"&cursor={cursor}" if cursor else "")
            out = self.call("GET", q)
            if isinstance(out, list):
                return out
            items += out.get("results") or []
            if not out.get("next_page_results"):
                return items
            cursor = out.get("next_cursor")


# ── rendering ───────────────────────────────────────────────────────────────────
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def words(html_or_text: str) -> str:
    """The comparable content of a description: tags, entities and ALL whitespace gone.

    Whitespace is not content, and it is the one thing the two sides never agree on: Plane's
    `description_stripped` is Django's strip_tags over the stored HTML, which glues adjacent blocks
    (`<p>A</p><p>B</p>` → "AB"), while a tag here became a space ("A B") — so an item of more than
    one line (471 of the 498 in plans/office.yaml, counted 2026-10-14) compared unequal on every run
    and was PATCHed, unchanged, 1.1 s each. The editor's own serializer escapes more than the four
    entities that used to be undone (`&quot;`, `&#39;`, `&nbsp;`); html.unescape knows them all.
    The trade, taken on purpose: an edit that changes only whitespace is invisible to this compare."""
    s = html.unescape(re.sub(r"<[^>]+>", " ", html_or_text or ""))
    return "".join(s.split())


def to_html(text: str) -> str:
    """Paragraphs and '- ' bullet lines → the small HTML Plane's editor keeps as is."""
    out, bullets = [], []
    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{esc(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        for line in para.splitlines():
            if line.lstrip().startswith("- "):
                bullets.append(line.lstrip()[2:].strip())
            else:
                flush()
                if line.strip():
                    out.append(f"<p>{esc(line.strip())}</p>")
        flush()
    return "".join(out) or "<p></p>"


# ── the plan ────────────────────────────────────────────────────────────────────
def relate_to_meeting(p, cur: dict, meeting: str, key: str, seen: dict) -> None:
    """An item opened from a meeting is RELATED to that meeting's work item (`meeting: MEET-15` in the
    plan). Plane's `relates_to` is symmetric, so the meeting lists everything that came of it and each
    item names its meeting, across projects — the owner, 2026-10-22 (DGO-1005): «all the tickets created
    from that meeting linked to that meeting». Already related: nothing is written; a dry run says what it
    would relate.

    The meeting is read ONCE a run (`seen`), whatever the number of items it opened: the symmetric list on
    its side says which are related already. Two reads per item made an apply of a meeting's 29 items wait
    out the key's 60 requests a minute (the second reader of DGO-1005). A relation is an annotation, so a
    meeting that cannot be found, or a refused relation call, is a problem of the plan, said — never the
    end of the apply: the items and modules after it still apply."""
    try:
        if meeting not in seen:
            mt, code = http("GET", f"{p.ws}/work-items/{meeting}/", None, p.h)
            if code != 200 or not isinstance(mt, dict) or not mt.get("id"):
                seen[meeting] = f"meeting {meeting} not found (HTTP {code})"
            else:
                R = f"/projects/{mt.get('project') or mt.get('project_id')}/work-items/{mt['id']}/relations/"
                have = p.call("GET", R)
                seen[meeting] = {"id": str(mt["id"]), "R": R,
                                 "related": {str(x.get("issue_id")) for x in (have.get("relates_to") or [])}
                                 if isinstance(have, dict) else set()}
        mt = seen[meeting]
        if isinstance(mt, str):
            problems.append(f"{key}: {mt}")
            return
        if str(cur["id"]) == mt["id"] or str(cur["id"]) in mt["related"]:
            return
        if DRY:
            log(f"would relate [{key}] to {meeting}")
            return
        p.call("POST", mt["R"], {"relation_type": "relates_to", "issues": [str(cur["id"])]})
        mt["related"].add(str(cur["id"]))
        log(f"related [{key}] to {meeting}")
    except RuntimeError as e:          # Transient too: Plane refused or was slow — said, and the apply goes on
        problems.append(f"{key}: not related to meeting {meeting}: {e}")


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit("[project-pln] no plan on stdin — the hook did not render the plan file")
    plan = json.loads(raw)
    slug = os.environ.get("PLANE_WORKSPACE") or "bina"
    p = Plane(slug, api_key())
    decl = plan.get("project") or {}
    ident = decl.get("identifier")
    if not ident:
        sys.exit("[project-pln] the plan needs project.identifier")

    # people — plan names → Plane user ids (each resolved once)
    people = {name: p.user_id_of(name, spec) for name, spec in (plan.get("people") or {}).items()}
    def uid(name):
        if not name:
            return ""
        if name not in people:
            people[name] = p.user_id_of(name, {})
        return people[name]
    default_assignee = uid((plan.get("defaults") or {}).get("assignee"))
    lead = uid(decl.get("lead"))
    if ONLY:
        unknown = ONLY - {it["key"] for m in plan.get("modules") or [] for it in m.get("items") or []}
        if unknown:
            sys.exit(f"[project-pln] --only names keys this plan does not have: {', '.join(sorted(unknown))}")

    # project — by identifier, from the cache (tasks.py's rows: id, identifier, name); a miss is a
    # project created since the cache was written, so the list is read once more — unless this run
    # has just read it. The lead is also the default assignee: what a human creates in this project
    # lands on the agent's desk too.
    read: list = []
    def project_rows() -> list:
        read.append(1)
        return [{"id": x["id"], "identifier": x.get("identifier"), "name": x.get("name")} for x in p.page("/projects/")]
    projects = cached(f"{slug}:projects", project_rows)
    proj = next((x for x in projects if x.get("identifier") == ident), None)
    if proj is None and not read:
        projects = cached(f"{slug}:projects", project_rows, fresh=True)
        proj = next((x for x in projects if x.get("identifier") == ident), None)
    body = {"name": decl.get("name"), "identifier": ident, "description": decl.get("description") or "",
            "network": int(decl.get("network", 0)), "module_view": True, "cycle_view": True}
    if lead:
        body["project_lead"] = lead
        body["default_assignee"] = lead
    if "default_assignee" in decl:
        # Stated on its own, and it may be NOBODY. Plane hands the project's default assignee to every
        # item created with none — so while it was the lead, a plan could not create an unassigned
        # item at all: the 296 items of plans/office.yaml (2026-10-06), each declared nobody's until
        # taken, all landed on the office agent's desk.
        body["default_assignee"] = uid(decl["default_assignee"]) or None
    if not decl.get("name"):
        # a plan that only names the project adds to it: nothing of the project itself is this plan's
        if proj is None:
            sys.exit(f"[project-pln] project {ident} does not exist, and this plan does not declare it "
                     f"(no project.name) — apply the plan that does first")
        body = {}
    if proj is None:
        if DRY:
            log(f"would create project {ident} ({decl['name']}) — dry run, stopping here"); finish(); return
        proj = p.call("POST", "/projects/", body); created.append(f"project:{ident}")
        log(f"created project {ident} — {decl['name']}")
        # the cache is told, not re-read: the list is the ~55 s read this cache exists to spare
        cached(f"{slug}:projects", lambda: projects + [{"id": proj["id"], "identifier": ident, "name": proj.get("name")}], fresh=True)
    else:
        if body:                      # the plan states the project: compared against the project itself, one read
            proj = p.call("GET", f"/projects/{proj['id']}/")
        diff = {k: v for k, v in body.items() if k in ("name", "description", "project_lead", "default_assignee")
                and (proj.get(k) or "") != (v or "")}
        if diff and not DRY:
            p.call("PATCH", f"/projects/{proj['id']}/", diff); updated.append(f"project:{ident}")
            log(f"updated project {ident}: {', '.join(diff)}")
        else:
            kept.append(f"project:{ident}")
    pid = proj["id"]
    P = f"/projects/{pid}"

    # states — one per group, renamed to the plan's word
    want = plan.get("states") or {}
    states = {s["group"]: s for s in cached(f"{pid}:states", lambda: p.page(f"{P}/states/"))}
    for group, name in want.items():
        s = states.get(group)
        if not s:
            problems.append(f"no state in group {group} — Plane created none"); continue
        if s["name"] != name:
            if not DRY:
                p.call("PATCH", f"{P}/states/{s['id']}/", {"name": name})
            updated.append(f"state:{group}"); log(f"state {group}: {s['name']} → {name}")
        else:
            kept.append(f"state:{group}")
    if not DRY and any(x.startswith("state:") for x in updated):
        cached(f"{pid}:states", lambda: p.page(f"{P}/states/"), fresh=True)

    def create(kind: str, body: dict, rows: dict) -> bool:
        """POST one named object (a label, a module) into `rows`, and tell the cache AT ONCE: a run
        that dies a step later leaves a cache the next run can use — told only at the end, a cache
        that still said «no module X» after X was made had the next run POST X again, refused as a
        duplicate name until the TTL ran out. A refusal of the name is the same stale cache the other
        way round (that window, or a person who made it meanwhile): the kind is read fresh and the one
        with that name taken, not failed. Under Transient the object may or may not be stored: asked
        by name, then written if not. Returns whether this run made it."""
        name = body["name"]
        def fresh() -> bool:
            rows.update({x["name"]: x for x in cached(f"{pid}:{kind}", lambda: p.page(f"{P}/{kind}/"), fresh=True)})
            return name in rows
        try:
            rows[name] = p.call("POST", f"{P}/{kind}/", body)
            made = True
        except Transient:
            made = not fresh()
            if made:
                rows[name] = p.call("POST", f"{P}/{kind}/", body)
        except RuntimeError:
            if not fresh():
                raise
            made = False
        cached(f"{pid}:{kind}", lambda: list(rows.values()), fresh=True)
        return made

    # labels — by name
    labels = {l["name"]: l for l in cached(f"{pid}:labels", lambda: p.page(f"{P}/labels/"))}
    for l in plan.get("labels") or []:
        if l["name"] in labels:
            kept.append(f"label:{l['name']}"); continue
        if DRY:
            created.append(f"label:{l['name']}"); log(f"would create label {l['name']}"); continue
        made = create("labels", {"name": l["name"], "color": l.get("color") or "#6b7280"}, labels)
        (created if made else kept).append(f"label:{l['name']}"); log(f"{'created' if made else 'found'} label {l['name']}")

    # modules — by name; work items — by external id, in plan order
    modules = {m["name"]: m for m in cached(f"{pid}:modules", lambda: p.page(f"{P}/modules/"))}
    existing = {}
    _seq: dict = {}

    def read_all() -> None:
        """Every plan-managed item of the project, paged once — how a whole plan is compared."""
        for it in p.page(f"{P}/issues/?expand=labels"):
            _seq[it.get("sequence_id")] = it
            if it.get("external_source") == SOURCE and it.get("external_id"):
                existing[it["external_id"]] = it

    def by_seq() -> dict:
        """Every item of the project by its number — for `refs:`; read once, and only when asked."""
        if not _seq:
            for it in p.page(f"{P}/issues/?expand=labels"):
                _seq[it.get("sequence_id")] = it
        return _seq
    if not ONLY:
        read_all()
    for key in sorted(ONLY):
        # A few keys are asked for one by one, by identity: Plane answers (external_source, external_id)
        # with the item itself and 404 with none — the page of every item is six slow reads a run of
        # one key never needs. An API that ignores the pair answers with a page instead; then the
        # project is read once, as a whole plan is: a lookup that came back empty must never be the
        # reason an item is created twice (nothing here deletes).
        out, code = http("GET", f"{p.ws}{P}/issues/?external_source={SOURCE}&external_id={urllib.parse.quote(key)}&expand=labels", headers=p.h)
        if code == 404:
            continue
        if code != 200 or not isinstance(out, dict):
            raise RuntimeError(f"GET item {key} → HTTP {code}: {out.get('error', out) if isinstance(out, dict) else out}")
        if out.get("id"):
            existing[key] = out
        else:
            read_all(); break
    n_items = 0
    meetings: dict = {}  # meeting ref -> its id, relations route and related ids (or why it is missing), once a run
    for m in plan.get("modules") or []:
        items = [it for it in m.get("items") or [] if not ONLY or it["key"] in ONLY]
        if ONLY and not items:
            continue
        mod = modules.get(m["name"])
        mbody = {"name": m["name"], "description": m.get("description") or "", "status": m.get("status") or "backlog"}
        if mod is None and DRY:
            created.append(f"module:{m['key']}"); log(f"would create module {m['name']}")
        elif mod is None:
            made = create("modules", mbody, modules); mod = modules[m["name"]]
            (created if made else kept).append(f"module:{m['key']}"); log(f"{'created' if made else 'found'} module {m['name']}")
        else:
            diff = {k: v for k, v in mbody.items() if k != "name" and (mod.get(k) or "") != v}
            if diff and not DRY:
                p.call("PATCH", f"{P}/modules/{mod['id']}/", diff); updated.append(f"module:{m['key']}")
                mod.update(diff); cached(f"{pid}:modules", lambda: list(modules.values()), fresh=True)
            else:
                kept.append(f"module:{m['key']}")
        # Who is in the module is asked of the module (one GET, never paced). This API's item payload
        # names no module (`module_ids`/`modules` are the web app's fields), so the old question «is the
        # item in its module?» was «no» for every item on every run, and every module's whole list was
        # POSTed again — a write and a 1.1 s pause per module per run that changed nothing.
        # A dry run asks too (a read): without it, every `refs:` item of an existing module was reported
        # as newly gathered on every dry run (measured 2026-10-19, plans/seo.yaml: all 22).
        members = set()
        if mod is not None and f"module:{m['key']}" not in created:
            members = {str(x.get("issue") or x.get("id")) for x in p.page(f"{P}/modules/{mod['id']}/module-issues/")}
        new_ids = []
        for it in items:
            n_items += 1
            key = it["key"]
            who = uid(it["assignee"]) if "assignee" in it else default_assignee
            ibody = {"name": it["name"], "priority": it.get("priority") or "none",
                     "description_html": to_html(it.get("description") or ""),
                     "labels": [labels[n]["id"] for n in it.get("labels") or [] if n in labels],
                     "assignees": [who] if who else [],
                     "external_source": SOURCE, "external_id": key}
            missing = [n for n in it.get("labels") or [] if n not in labels]
            if missing and not DRY:
                problems.append(f"{key}: labels not declared in the plan: {missing}")
            cur = existing.get(key)
            if cur is None:
                if DRY:
                    log(f"would create {key}: {it['name']}"); continue
                try:
                    cur = p.call("POST", f"{P}/issues/", ibody)
                except Transient:
                    # Stored or not? Asked by the item's own identity — a blind second POST is how one
                    # work item becomes two, and nothing here ever deletes.
                    cur = next((x for x in p.page(f"{P}/issues/") if x.get("external_source") == SOURCE
                                and x.get("external_id") == key), None) or p.call("POST", f"{P}/issues/", ibody)
                created.append(f"item:{key}"); new_ids.append(cur["id"])
                log(f"created {ident}-{cur.get('sequence_id')} [{key}] {it['name']}")
            else:
                cur_labels = sorted(x["id"] if isinstance(x, dict) else x for x in cur.get("labels") or [])
                cur_people = sorted(x["id"] if isinstance(x, dict) else x for x in cur.get("assignees") or [])
                if not who:
                    ibody.pop("assignees")          # nobody to assign: never strip what a human set
                # Plane rewrites the HTML it stores (attributes, wrappers), so the markup never compares
                # equal — measured 2026-09-30: every re-apply PATCHed 39 items and the bursts killed the
                # API workers (gunicorn WORKER TIMEOUT → 502). Compare the WORDS instead.
                changed = (cur.get("name") != ibody["name"] or cur.get("priority") != ibody["priority"]
                           or sorted(ibody["labels"]) != cur_labels
                           or (who and cur_people != [who])
                           or words(cur.get("description_stripped") or cur.get("description_html") or "") != words(ibody["description_html"]))
                if changed and not DRY:
                    p.call("PATCH", f"{P}/issues/{cur['id']}/", ibody)
                    updated.append(f"item:{key}"); log(f"updated {ident}-{cur.get('sequence_id')} [{key}]")
                else:
                    if changed:      # a dry run SAYS what it would change — it used to count it as kept
                        log(f"would update {ident}-{cur.get('sequence_id')} [{key}]")
                    kept.append(f"item:{key}")
                if mod is not None and not DRY and str(cur["id"]) not in members:
                    new_ids.append(cur["id"])
            if str(it.get("meeting") or "").strip():
                relate_to_meeting(p, cur, str(it["meeting"]).strip(), key, meetings)
        # `refs:` — work items that exist already (by their number, DGO-311) and belong in this module
        # too: gathered into it, never edited. They are not plan-managed, so they are found among ALL
        # the project's items, read once for the whole run and only when a module names any.
        for ref in m.get("refs") or []:
            prefix, _, seq = str(ref).rpartition("-")
            cur = by_seq().get(int(seq)) if prefix == ident and seq.isdigit() else None
            if cur is None:
                problems.append(f"{m['key']}: no work item {ref} in {ident}"); continue
            if str(cur["id"]) in members:
                kept.append(f"module:{m['key']}+{ref}"); continue
            if mod is not None and not DRY:
                new_ids.append(cur["id"])
            updated.append(f"module:{m['key']}+{ref}")
            log(f"{'would gather' if DRY else 'gathered'} {ref} into {m['name']}")
        if new_ids and mod is not None and not DRY:
            try:
                p.call("POST", f"{P}/modules/{mod['id']}/module-issues/", {"issues": new_ids})
            except Transient:                           # adding the same items to a module twice is the same module
                p.call("POST", f"{P}/modules/{mod['id']}/module-issues/", {"issues": new_ids})
    finish(project=proj, items=n_items)


def finish(project=None, items: int = 0) -> None:
    timing = {"reads": READS, "writes": WRITES, "seconds": round(time.time() - T0, 1)}
    log(f"{timing['reads']} reads, {timing['writes']} writes, {timing['seconds']} s")
    print("RESULT|" + json.dumps({"created": created, "updated": updated, "kept": kept, "problems": problems, "warnings": warnings,
                                  "project": {"id": (project or {}).get("id"), "identifier": (project or {}).get("identifier")},
                                  "items": items, "dry_run": DRY, "only": sorted(ONLY), "timing": timing}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        problems.append(str(e)); log(f"Plane refused: {e}"); finish(); sys.exit(1)
