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

Every object is UPSERTED: the project by identifier, a state by its group (Plane creates one per
group with an English name — the plan renames it), a label and a module by name, a work item by
(external_source, external_id) so re-running the hook edits the items in place — titles, priority,
labels, description, module — and never duplicates them. Nothing is ever deleted: a work item that
left the plan stays in Plane with whatever the humans did to it. Work items are created in plan
order, so Plane's sequence numbers (DGO-1, DGO-2, …) follow the phases.

Output: `[project-pln] …` lines for the operator and one `RESULT|{json}` line for the hook.
Plane's API is rate-limited (60 requests/minute per key); a 429 is waited out, never failed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SOURCE = "dgo-plan"                       # external_source every plan-managed work item carries
BASE = (os.environ.get("PLANE_API_URL") or "http://127.0.0.1").rstrip("/")     # caddy → api, in-container
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
TOKEN_INSTANCE = os.environ.get("PLANE_TOKEN_INSTANCE") or "plane_local_api_token-local"
DRY = os.environ.get("PLANE_PLAN_DRY_RUN") == "1"

created: list[str] = []
updated: list[str] = []
kept: list[str] = []
problems: list[str] = []
warnings: list[str] = []                  # true, but not a failure: an assignee whose account does not exist yet


def log(msg: str) -> None:
    print(f"[project-pln] {msg}", flush=True)


# ── HTTP ────────────────────────────────────────────────────────────────────────
def http(method: str, url: str, body=None, headers=None, tries: int = 6):
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
        except Exception as e:                                          # noqa: BLE001
            if attempt + 1 < tries:
                time.sleep(3)
                continue
            return {"error": f"{type(e).__name__}: {e}"}, -1
    return {"error": "gave up"}, -1


def api_key() -> str:
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
        self.h = {"X-API-Key": key}

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
    """The comparable content of a description: tags gone, entities and whitespace normalized."""
    s = re.sub(r"<[^>]+>", " ", html_or_text or "")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return " ".join(s.split())


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

    # project — by identifier. The lead is also the default assignee: what a human creates in this
    # project lands on the agent's desk too.
    projects = p.page("/projects/")
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
    else:
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
    states = {s["group"]: s for s in p.page(f"{P}/states/")}
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

    # labels — by name
    labels = {l["name"]: l for l in p.page(f"{P}/labels/")}
    for l in plan.get("labels") or []:
        if l["name"] in labels:
            kept.append(f"label:{l['name']}"); continue
        if not DRY:
            labels[l["name"]] = p.call("POST", f"{P}/labels/", {"name": l["name"], "color": l.get("color") or "#6b7280"})
        created.append(f"label:{l['name']}"); log(f"{'would create' if DRY else 'created'} label {l['name']}")

    # modules — by name; work items — by external id, in plan order
    modules = {m["name"]: m for m in p.page(f"{P}/modules/")}
    existing = {}
    for it in p.page(f"{P}/issues/?expand=labels"):
        if it.get("external_source") == SOURCE and it.get("external_id"):
            existing[it["external_id"]] = it
    n_items = 0
    for m in plan.get("modules") or []:
        mod = modules.get(m["name"])
        mbody = {"name": m["name"], "description": m.get("description") or "", "status": m.get("status") or "backlog"}
        if mod is None:
            if not DRY:
                try:
                    mod = p.call("POST", f"{P}/modules/", mbody)
                except Transient:                       # stored or not? asked by name, then written if not
                    mod = next((x for x in p.page(f"{P}/modules/") if x["name"] == m["name"]), None) \
                        or p.call("POST", f"{P}/modules/", mbody)
                modules[m["name"]] = mod
            created.append(f"module:{m['key']}"); log(f"{'would create' if DRY else 'created'} module {m['name']}")
        else:
            diff = {k: v for k, v in mbody.items() if k != "name" and (mod.get(k) or "") != v}
            if diff and not DRY:
                p.call("PATCH", f"{P}/modules/{mod['id']}/", diff); updated.append(f"module:{m['key']}")
            else:
                kept.append(f"module:{m['key']}")
        new_ids = []
        for it in m.get("items") or []:
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
                if mod is not None and not any((x if isinstance(x, str) else x.get("module_id") or x.get("id")) == mod["id"] for x in cur.get("module_ids") or cur.get("modules") or []):
                    new_ids.append(cur["id"])
        if new_ids and mod is not None and not DRY:
            try:
                p.call("POST", f"{P}/modules/{mod['id']}/module-issues/", {"issues": new_ids})
            except Transient:                           # adding the same items to a module twice is the same module
                p.call("POST", f"{P}/modules/{mod['id']}/module-issues/", {"issues": new_ids})
    finish(project=proj, items=n_items)


def finish(project=None, items: int = 0) -> None:
    print("RESULT|" + json.dumps({"created": created, "updated": updated, "kept": kept, "problems": problems, "warnings": warnings,
                                  "project": {"id": (project or {}).get("id"), "identifier": (project or {}).get("identifier")},
                                  "items": items, "dry_run": DRY}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        problems.append(str(e)); log(f"Plane refused: {e}"); finish(); sys.exit(1)
