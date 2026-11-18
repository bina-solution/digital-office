#!/usr/bin/env python3
"""plane_move — carry a client's Plane projects, or chosen items of one, from one office's Plane to another's (DGO-1924).

Runs INSIDE an office's project-pln container, like plan.py: the API at PLANE_API_URL (default http://127.0.0.1,
the app's caddy → api), the key from PLANE_LOCAL_API_TOKEN or the credential plane (plane_local_api_token-local).
README.md has the commands that put it there.

    snapshot-sql SPEC…                            the read-only query of the SOURCE Plane's database (psql -At)
    export SPEC… [--redact REGEX] < snapshot > bundle.json
                                                  SPEC: EXX (the whole project, its modules too) · MEET:30,31,32
                                                  (those items) · DGO:1827,1828=BINA (those items, into project BINA)
    import BUNDLE [--as EXX=XTRS …] [--rewrite OLD=NEW …] [--dry-run] [--update]
                                                  create what is missing, never duplicate; an item that differs is
                                                  KEPT and counted («differs») unless --update — once people work on
                                                  the target, a re-run never undoes them
    verify BUNDLE [--as …] [--rewrite …]           the target against the bundle; exit 0 only when they match

WHAT MAKES A SECOND RUN CHANGE NOTHING — every object is found again by its identity, never by its name alone:
- an item keeps the source's own (external_source, external_id): plan.py's `dgo-plan` key, meet's `meet-recording`
  key (`<session>/<file>`) — so the target office's own `plan` and meet find it as theirs and never file it twice.
  An item with none (made by hand) gets (dgo-move, <IDENT>-<n>).
- a comment: (dgo-move, <the source comment's id>); its author and date are its first line (the API writes every
  comment as the key's own account, now).
- a file: by name and size, as tasks.py attach does.
- a WHOLE project keeps its numbers: its items are created in the source's order, and each created number is checked
  against the source's. The first that differs stops the run — a project that already holds other items is not a
  copy of this one, and a silent renumbering would break every «EXX-n» in the texts, the meeting pages and the code.
- chosen items (MEET:30,31,32) take the target's next numbers; each says where it came from (an «origin» comment),
  and the run's RESULT line gives the map (MEET-30 → MEET-1).

THE REDACTION (--redact): another client's name never reaches this client's office (the Exampleu move's rule, DGO-1873).
Every match in an item's name, description, comments and file names, a module's name, the project's description and
the keys of related items left behind (EXU-12) is replaced by «[לקוח אחר]» in the bundle, and counted.

REFUSED AT EXPORT, never half-moved: an archived or intake item (the API cannot put one there), and two items of one
project sharing an identity (the target would hold only one).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FORMAT = "dgo-plane-move/1"
MOVE = "dgo-move"                          # external_source of what this tool itself identifies
BASE = (os.environ.get("PLANE_API_URL") or "http://127.0.0.1").rstrip("/")
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
TOKEN_INSTANCE = os.environ.get("PLANE_TOKEN_INSTANCE") or "plane_local_api_token-local"
WORKSPACE = os.environ.get("PLANE_WORKSPACE") or "bina"
PACE = float(os.environ.get("PLANE_MOVE_PACE") or 1.1)   # seconds between requests, READS TOO: Plane limits each key
#                       (PLANE_API_KEY_RATE_LIMIT: 60 upstream, 300 on our offices since 5c9ee7fd0), and an office's
#                       agents share its one key
GONE = (429, 502, 503, 504)
OTHER = "[לקוח אחר]"
REVERSE = {"blocked_by": "blocking", "blocking": "blocked_by", "start_before": "start_after",
           "start_after": "start_before", "finish_before": "finish_after", "finish_after": "finish_before"}


def log(msg: str) -> None:
    print(f"[plane-move] {msg}", file=sys.stderr, flush=True)


def token() -> str:
    tok = os.environ.get("PLANE_LOCAL_API_TOKEN")
    if tok:
        return tok
    with urllib.request.urlopen(f"{VAULT}/api/instances/{TOKEN_INSTANCE}/secret", timeout=30) as r:
        tok = ((json.load(r) or {}).get("secret") or {}).get("token")
    if not tok:
        sys.exit(f"[plane-move] no Plane API key in the credential plane ({TOKEN_INSTANCE})")
    return tok


class Plane:
    def __init__(self, ws: str):
        self.ws = f"{BASE}/api/v1/workspaces/{ws}"
        self.h = {"X-API-Key": token()}
        self.reads = self.writes = 0
        self.last_write = 0.0

    def _req(self, method: str, path: str, body=None, raw: bool = False):
        url = path if path.startswith("http") else self.ws + path
        data = None if body is None else json.dumps(body).encode()
        h = dict(self.h, **({"Content-Type": "application/json"} if data is not None else {}))
        for attempt in range(6):
            wait = PACE - (time.time() - self.last_write)
            if wait > 0:
                time.sleep(wait)
            self.last_write = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h),
                                            timeout=180) as r:
                    b = r.read()
                    if method == "GET":
                        self.reads += 1
                    else:
                        self.writes += 1
                    return r.status, (b if raw else (json.loads(b) if b else {}))
            except urllib.error.HTTPError as e:
                b = e.read()
                if e.code in GONE and attempt < 5:
                    time.sleep(5 * (attempt + 1))
                    continue
                try:
                    return e.code, json.loads(b)
                except ValueError:
                    return e.code, {"error": b[:300].decode(errors="replace")}
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 5:
                    time.sleep(5 * (attempt + 1))
                    continue
                return -1, {"error": f"{type(e).__name__}: {e}"}
        return -1, {"error": "gave up"}

    def get(self, path: str):
        code, out = self._req("GET", path)
        if code != 200:
            raise SystemExit(f"[plane-move] GET {path}: HTTP {code} {out}")
        return out

    def page(self, path: str) -> list:
        sep = "&" if "?" in path else "?"
        out, cursor = [], ""
        while True:
            d = self.get(f"{path}{sep}per_page=100" + (f"&cursor={cursor}" if cursor else ""))
            if isinstance(d, list):
                return d
            out += d.get("results") or []
            if not d.get("next_page_results"):
                return out
            cursor = d.get("next_cursor")

    def write_ex(self, method: str, path: str, body):
        """(code, answer) — for a caller that reads a refusal (409: the identity exists) instead of failing on it."""
        return self._req(method, path, body)

    def write(self, method: str, path: str, body):
        code, out = self._req(method, path, body)
        if code not in (200, 201, 204):
            raise RuntimeError(f"{method} {path}: HTTP {code} {json.dumps(out, ensure_ascii=False)[:300]}")
        return out


def words(s: str) -> str:
    """What a person reads — Plane rewrites the markup it stores, so markup never compares equal (plan.py)."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    return " ".join(html.unescape(s).split())


def project_by_ident(p: Plane, ident: str):
    return next((x for x in p.page("/projects/") if x.get("identifier") == ident), None)


# ── export ───────────────────────────────────────────────────────────────────────────────────────────────────────
def parse_spec(spec: str):
    """EXX · MEET:30,31 · DGO:1827,1828=BINA → (source ident, item numbers or None, target ident)."""
    m = re.fullmatch(r"([A-Z][A-Z0-9]{0,11})(?::([0-9,\-]+))?(?:=([A-Z][A-Z0-9]{0,11}))?", spec.strip())
    if not m:
        raise SystemExit(f"[plane-move] not a SPEC: {spec!r} (EXX · MEET:30,31 · DGO:1827=BINA)")
    nums = None
    if m.group(2):
        nums = set()
        for part in m.group(2).split(","):
            a, _, b = part.partition("-")
            nums.update(range(int(a), int(b or a) + 1))
    return m.group(1), nums, m.group(3) or m.group(1)


def snapshot_sql(specs: list) -> str:
    """One read-only query of the SOURCE Plane's database that returns everything the specs name, as one JSON line.

    Why the database and not the API: Plane limits the requests a minute PER KEY (60 upstream; 300 on our offices
    since 5c9ee7fd0), and every agent of the office shares the office's key — an export of ~120 items through the API
    (comments, files and relations are one GET each) held the whole office's Plane at 429 for minutes while the limit
    was 60 (measured 2026-11-17, DGO-1924). The database is read once, exactly,
    for nothing. The files' bytes are the one thing it does not hold: those come through the API, paced (export)."""
    where = []
    for spec in specs:
        ident, nums, _ = parse_spec(spec)
        cond = f"p.identifier = '{ident}'"
        if nums is not None:
            cond += " and i.sequence_id in (" + ",".join(str(n) for n in sorted(nums)) + ")"
        where.append(f"({cond})")
    idents = ",".join(f"'{parse_spec(x)[0]}'" for x in specs)
    chosen = (f"select i.id from issues i join projects p on p.id = i.project_id "
              f"where i.deleted_at is null and p.deleted_at is null and ({' or '.join(where)})")
    return f"""begin read only;
with chosen as ({chosen}),
rel as (select r.issue_id, r.related_issue_id, r.relation_type from issue_relations r
        where r.deleted_at is null and (r.issue_id in (select id from chosen) or r.related_issue_id in (select id from chosen)))
select json_build_object(
 'projects', (select coalesce(json_agg(json_build_object('id', p.id, 'identifier', p.identifier, 'name', p.name,
              'description', p.description)), '[]') from projects p where p.deleted_at is null and p.identifier in ({idents})),
 'states', (select coalesce(json_agg(json_build_object('id', s.id, 'project', s.project_id, 'name', s.name,
            'group', s."group", 'color', s.color, 'sequence', s.sequence)), '[]') from states s join projects p on p.id = s.project_id
            where s.deleted_at is null and p.identifier in ({idents})),
 'labels', (select coalesce(json_agg(json_build_object('id', l.id, 'project', l.project_id, 'name', l.name, 'color', l.color)), '[]')
            from labels l join projects p on p.id = l.project_id where l.deleted_at is null and p.identifier in ({idents})),
 'modules', (select coalesce(json_agg(json_build_object('id', m.id, 'project', m.project_id, 'name', m.name,
             'description', m.description)), '[]') from modules m join projects p on p.id = m.project_id
             where m.deleted_at is null and p.identifier in ({idents})),
 'module_issues', (select coalesce(json_agg(json_build_object('module', mi.module_id, 'issue', mi.issue_id)), '[]')
                   from module_issues mi where mi.deleted_at is null and mi.issue_id in (select id from chosen)),
 'all_seqs', (select coalesce(json_agg(json_build_object('project', i.project_id, 'seq', i.sequence_id)), '[]')
              from issues i join projects p on p.id = i.project_id where i.deleted_at is null and p.identifier in ({idents})),
 'issues', (select coalesce(json_agg(json_build_object('id', i.id, 'project', i.project_id, 'seq', i.sequence_id,
            'name', i.name, 'description_html', i.description_html, 'priority', i.priority, 'state', i.state_id,
            'start_date', i.start_date, 'target_date', i.target_date, 'parent', i.parent_id, 'created_at', i.created_at,
            'archived_at', i.archived_at, 'external_source', i.external_source, 'external_id', i.external_id)
            order by i.sequence_id), '[]') from issues i where i.id in (select id from chosen)),
 'issue_labels', (select coalesce(json_agg(json_build_object('issue', il.issue_id, 'label', il.label_id)), '[]')
                  from issue_labels il where il.deleted_at is null and il.issue_id in (select id from chosen)),
 'comments', (select coalesce(json_agg(json_build_object('id', c.id, 'issue', c.issue_id, 'html', c.comment_html,
              'created_at', c.created_at, 'actor', coalesce(u.display_name, '')) order by c.created_at), '[]')
              from issue_comments c left join users u on u.id = c.actor_id
              where c.deleted_at is null and c.issue_id in (select id from chosen)),
 'relations', (select coalesce(json_agg(json_build_object('issue', rel.issue_id, 'related', rel.related_issue_id,
               'type', rel.relation_type)), '[]') from rel),
 'keys', (select coalesce(json_agg(json_build_object('id', i.id, 'key', p.identifier || '-' || i.sequence_id)), '[]')
          from issues i join projects p on p.id = i.project_id
          where i.id in (select issue_id from rel union select related_issue_id from rel
                         union select parent_id from issues where id in (select id from chosen) and parent_id is not null)),
 'files', (select coalesce(json_agg(json_build_object('id', a.id, 'issue', a.issue_id, 'project', a.project_id,
           'name', a.attributes->>'name', 'type', a.attributes->>'type', 'size', a.size)), '[]') from file_assets a
           where a.deleted_at is null and a.is_uploaded and a.entity_type = 'ISSUE_ATTACHMENT'
             and a.issue_id in (select id from chosen))
);
commit;"""


def cmd_snapshot_sql(a) -> int:
    print(snapshot_sql(a.specs))
    return 0


def cmd_export(a) -> int:
    """The bundle, from the database snapshot (stdin or --snapshot) and, for the files' bytes only, the API."""
    raw = sys.stdin.read() if a.snapshot in (None, "-") else open(a.snapshot, encoding="utf-8").read()
    line = next((x for x in raw.splitlines() if x.lstrip().startswith("{")), "")
    if not line:
        raise SystemExit("[plane-move] no snapshot on stdin — `snapshot-sql` | psql -At | export")
    snap = json.loads(line)
    rx = re.compile(a.redact) if a.redact else None
    hits = 0

    def clean(s: str) -> tuple[str, int]:
        if not rx or not s:
            return s or "", 0
        return rx.subn(OTHER, s)

    p = None                                   # the API, only when a file is to be read
    key_of = {k["id"]: k["key"] for k in snap["keys"]}
    bundle = {"format": FORMAT, "source": {"workspace": WORKSPACE, "office": os.environ.get("DGO_OFFICE_ID") or "",
                                            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              "projects": []}
    for spec in a.specs:
        ident, nums, target = parse_spec(spec)
        proj = next((x for x in snap["projects"] if x["identifier"] == ident), None)
        if not proj:
            raise SystemExit(f"[plane-move] no project {ident} in the snapshot")
        pid = proj["id"]
        states = {x["id"]: x for x in snap["states"] if x["project"] == pid}
        labels = {x["id"]: x for x in snap["labels"] if x["project"] == pid}
        whole = nums is None
        chosen = [i for i in snap["issues"] if i["project"] == pid and (whole or i["seq"] in nums)]
        for i in chosen:
            key_of[i["id"]] = f"{ident}-{i['seq']}"
        if not whole and len(chosen) != len(nums):
            raise SystemExit(f"[plane-move] {ident}: no items {sorted(nums - {i['seq'] for i in chosen})}")
        if whole:
            seqs = sorted(x["seq"] for x in snap["all_seqs"] if x["project"] == pid)
            if seqs != list(range(1, len(seqs) + 1)):
                gaps = sorted(set(range(1, max(seqs) + 1)) - set(seqs))
                raise SystemExit(f"[plane-move] {ident} has gaps {gaps[:20]} — a whole copy keeps numbers, which a gap "
                                 f"cannot: carry it as chosen items ({ident}:1-{max(seqs)})")
        ids = {i["id"] for i in chosen}
        held = [f"{ident}-{i['seq']}" for i in chosen if i.get("archived_at") or states[i["state"]]["group"] == "triage"]
        if held:
            raise SystemExit(f"[plane-move] {ident}: {held[:20]} are archived or in intake — accept, decline or unarchive "
                             f"them first: the API cannot put an item there, and a move that drops one is not a move")
        seen: dict = {}
        for i in chosen:
            k = (i.get("external_source") or MOVE, i.get("external_id") or f"{ident}-{i['seq']}")
            seen.setdefault(k, []).append(f"{ident}-{i['seq']}")
        twice = {f"{k[0]}:{k[1]}": v for k, v in seen.items() if len(v) > 1}
        if twice:
            raise SystemExit(f"[plane-move] {ident}: one identity on two items {twice} — the target would hold one of "
                             f"them; give each its own key first")
        lab_of: dict = {}
        for x in snap["issue_labels"]:
            if x["issue"] in ids and x["label"] in labels:
                lab_of.setdefault(x["issue"], []).append(labels[x["label"]]["name"])
        out_mods = []
        # chosen items carry no modules: theirs are the source project's plans, not the target project's
        for m in (x for x in snap["modules"] if x["project"] == pid and whole):
            mine = sorted({next(i["seq"] for i in chosen if i["id"] == mi["issue"])
                           for mi in snap["module_issues"] if mi["module"] == m["id"] and mi["issue"] in ids})
            if mine:
                out_mods.append({"name": clean(m["name"])[0], "description": clean(m.get("description") or "")[0],
                                 "items": mine})
        out_items = []
        for i in chosen:
            name, h1 = clean(i["name"])
            desc, h2 = clean(i.get("description_html") or "")
            comments, h3 = [], 0
            for c in (x for x in snap["comments"] if x["issue"] == i["id"]):
                body, n = clean(c["html"] or "")
                h3 += n
                comments.append({"id": c["id"], "html": body, "created_at": c["created_at"], "actor": c["actor"]})
            files = []
            for f in (x for x in snap["files"] if x["issue"] == i["id"]):
                p = p or Plane(WORKSPACE)
                code, blob = p._req("GET", f"/projects/{pid}/issues/{i['id']}/issue-attachments/{f['id']}/", raw=True)
                if code != 200 or len(blob) != int(f["size"] or 0):
                    raise SystemExit(f"[plane-move] {ident}-{i['seq']}: file {f['name']} could not be read whole "
                                     f"(HTTP {code}, {len(blob) if isinstance(blob, bytes) else 0} of {f['size']} bytes)")
                files.append({"name": clean(f["name"])[0], "type": f["type"] or "", "size": len(blob),
                              "b64": base64.b64encode(blob).decode()})
            relations: dict = {}
            for r in snap["relations"]:
                if i["id"] not in (r["issue"], r["related"]):
                    continue
                other = r["related"] if r["issue"] == i["id"] else r["issue"]
                kind = r["type"]
                if r["issue"] != i["id"]:   # the row is the other's: its reverse, as the API shows it from this side
                    kind = REVERSE.get(kind, kind)
                relations.setdefault(kind, set()).add(other)
            hits += h1 + h2 + h3
            out_items.append({
                "seq": i["seq"], "id": i["id"], "name": name, "description_html": desc,
                "priority": i.get("priority") or "none", "state": states[i["state"]]["name"],
                "labels": sorted(lab_of.get(i["id"], [])),
                "start_date": i.get("start_date"), "target_date": i.get("target_date"),
                "parent": i.get("parent"), "created_at": i.get("created_at") or "",
                "external_source": i.get("external_source") or MOVE,
                "external_id": i.get("external_id") or f"{ident}-{i['seq']}",
                "comments": comments, "files": files, "relations": relations, "redacted": h1 + h2 + h3})
        bundle["projects"].append({
            "identifier": ident, "target": target, "whole": whole, "name": proj["name"],
            "description": clean(proj.get("description") or "")[0],
            "states": [{"name": x["name"], "group": x["group"], "color": x.get("color") or "#888888"}
                       for x in sorted(states.values(), key=lambda x: x.get("sequence") or 0)
                       if whole or x["id"] in {i["state"] for i in chosen}],
            "labels": [{"name": x["name"], "color": x.get("color") or "#888888"}
                       for x in labels.values() if whole or any(x["name"] in lab_of.get(i, []) for i in ids)],
            "modules": out_mods, "items": out_items})
        log(f"{ident}: {len(out_items)} item(s), {sum(len(i['comments']) for i in out_items)} comment(s), "
            f"{sum(len(i['files']) for i in out_items)} file(s), {len(out_mods)} module(s)")
    # relations and parents as «IDENT-n», so the target resolves them inside the bundle and names the rest — a key of
    # another client's project (EXU-12) is a name too, and is redacted like one
    for pr in bundle["projects"]:
        for it in pr["items"]:
            it["relations"] = {k: sorted(clean(key_of.get(x, x))[0] for x in v) for k, v in it["relations"].items()}
            it["parent"] = clean(key_of.get(it["parent"], it["parent"]))[0] if it.get("parent") else None
    bundle["redactions"] = hits
    json.dump(bundle, sys.stdout, ensure_ascii=False)
    log(f"exported; {hits} other-client name(s) redacted; {p.reads if p else 0} API read(s), for files")
    return 0


# ── import / verify ──────────────────────────────────────────────────────────────────────────────────────────────
#: how a relation is stored once, whichever side names it: (kind of pair, first, second) — or an unordered pair
PAIR = {"blocking": ("block", 0), "blocked_by": ("block", 1), "start_before": ("start", 0), "start_after": ("start", 1),
        "finish_before": ("finish", 0), "finish_after": ("finish", 1), "relates_to": ("relates", None),
        "duplicate": ("duplicate", None)}


def pair_of(kind: str, me: str, other: str):
    k, side = PAIR[kind]
    if side is None:
        return (k, frozenset((me, other)))
    return (k, me, other) if side == 0 else (k, other, me)


class Target:
    """One target project, read once: its states, labels, modules and items by their identity."""

    def __init__(self, p: Plane, pr: dict, ident: str, dry: bool, update: bool = False):
        self.p, self.pr, self.ident, self.dry, self.update = p, pr, ident, dry, update
        self.proj = project_by_ident(p, ident)
        self.pid = self.proj["id"] if self.proj else None
        self.made = False                   # this run created the project: its own default states may be renamed
        self.fresh: set = set()             # items this run created: nothing on them to read back
        self.read()

    def read(self) -> None:
        if not self.pid:
            self.states, self.labels, self.mods, self.items, self.all_items = {}, {}, {}, {}, []
            return
        P = f"/projects/{self.pid}"
        self.states = {s["name"]: s for s in self.p.page(f"{P}/states/")}
        self.labels = {x["name"]: x for x in self.p.page(f"{P}/labels/")}
        self.mods = {m["name"]: m for m in self.p.page(f"{P}/modules/")}
        self.all_items = self.p.page(f"{P}/issues/")
        self.items = {(i.get("external_source"), i.get("external_id")): i for i in self.all_items
                      if i.get("external_source") and i.get("external_id")}


def ensure_project(t: Target, r: dict) -> None:
    pr = t.pr
    if t.pid:
        r["kept"] += 1
        if pr["modules"] and not t.proj.get("module_view") and not t.dry:
            # Plane refuses a module on a project whose module view is off (HTTP 400) — a new project's is
            t.p.write("PATCH", f"/projects/{t.pid}/", {"module_view": True})
            r["updated"] += 1
        return
    # a rehearsal (--as) is a scratch project nobody may take for the client's own; items carried into a project of
    # another name (DGO:…=BINA) are «from Bina's office». Plane refuses a name with marks (· ( ) — HTTP 400).
    name = f"מלשכת בינה {pr['identifier']}" if pr.get("renamed") else pr["name"]
    if pr.get("rehearsal"):
        name = f"בדיקת העברה {name} {t.ident}"
    name = re.sub(r"[^\w\s-]", " ", name)
    name = " ".join(name.split())
    if t.dry:
        log(f"would create project {t.ident} «{name}»"); r["created"] += 1
        return
    made = t.p.write("POST", "/projects/", {"name": name, "identifier": t.ident, "description": pr["description"],
                                            "module_view": bool(pr["modules"])})
    t.proj, t.pid, t.made = made, made["id"], True
    r["created"] += 1
    log(f"created project {t.ident} «{name}»")
    t.read()


def ensure_meta(t: Target, r: dict) -> None:
    P = f"/projects/{t.pid}"
    claimed = set()
    for s in t.pr["states"]:
        if s["group"] == "triage":
            continue                        # every project has Plane's own intake state, and Plane refuses a second
        if s["name"] in t.states:
            claimed.add(t.states[s["name"]]["id"]); continue
        # the default of the same group in a project THIS RUN made is renamed, not doubled (plan.py's rule); an existing
        # project's states are its people's, and are never renamed
        spare = next((x for x in t.states.values() if x["group"] == s["group"] and x["id"] not in claimed
                      and x["name"] not in {y["name"] for y in t.pr["states"]}), None) if t.made else None
        if t.dry:
            log(f"would {'rename ' + spare['name'] + ' to' if spare else 'create'} state {s['name']}"); continue
        if spare:
            out = t.p.write("PATCH", f"{P}/states/{spare['id']}/", {"name": s["name"]})
            t.states.pop(spare["name"], None)
        else:
            out = t.p.write("POST", f"{P}/states/", {"name": s["name"], "group": s["group"], "color": s["color"]})
        t.states[s["name"]] = out; claimed.add(out["id"]); r["created"] += 1
    for x in t.pr["labels"]:
        if x["name"] in t.labels:
            continue
        if t.dry:
            log(f"would create label {x['name']}"); continue
        t.labels[x["name"]] = t.p.write("POST", f"{P}/labels/", {"name": x["name"], "color": x["color"]})
        r["created"] += 1
    for m in t.pr["modules"]:
        if m["name"] in t.mods:
            continue
        if t.dry:
            log(f"would create module {m['name']}"); continue
        t.mods[m["name"]] = t.p.write("POST", f"{P}/modules/", {"name": m["name"], "description": m["description"]})
        r["created"] += 1


def item_body(t: Target, it: dict) -> dict:
    return {"name": it["name"], "description_html": it["description_html"] or "<p></p>",
            "priority": it["priority"], "state": t.states[it["state"]]["id"],
            "labels": [t.labels[n]["id"] for n in it["labels"] if n in t.labels],
            "start_date": it["start_date"], "target_date": it["target_date"],
            "external_source": it["external_source"], "external_id": it["external_id"]}


def differs(t: Target, cur: dict, it: dict) -> list:
    body = item_body(t, it)
    out = []
    for k, have, want in (("name", cur.get("name"), body["name"]), ("priority", cur.get("priority"), body["priority"]),
                          ("state", cur.get("state"), body["state"]),
                          ("labels", sorted(cur.get("labels") or []), sorted(body["labels"])),
                          ("start_date", cur.get("start_date") or None, body["start_date"]),
                          ("target_date", cur.get("target_date") or None, body["target_date"]),
                          ("description", words(cur.get("description_html") or ""), words(body["description_html"]))):
        if have != want:
            out.append(k)
    return out


def ensure_items(t: Target, r: dict, new_by_key: dict) -> None:
    P = f"/projects/{t.pid}"
    pr = t.pr
    if pr["whole"]:
        foreign = [i for i in t.all_items if (i.get("external_source"), i.get("external_id")) not in
                   {(x["external_source"], x["external_id"]) for x in pr["items"]}]
        if foreign:
            raise RuntimeError(f"{t.ident} holds {len(foreign)} item(s) that are not {pr['identifier']}'s "
                               f"({t.ident}-{foreign[0]['sequence_id']} first): a whole copy keeps numbers, so it "
                               f"needs a project that holds only this one's items")
    for it in pr["items"]:
        key = (it["external_source"], it["external_id"])
        cur = t.items.get(key)
        src = f"{pr['identifier']}-{it['seq']}"
        if cur is None:
            if t.dry:
                log(f"would create {src} → {t.ident}-?"); r["created"] += 1; continue
            code, out = t.p.write_ex("POST", f"{P}/issues/", item_body(t, it))
            if code == 409:
                # the identity is taken already — a write whose answer was lost, or an item the list does not show
                # (archived, in intake). Plane's 409 names it; it is never posted twice and never guessed.
                got = out.get("id") if isinstance(out, dict) else None
                c2, cur = t.p._req("GET", f"{P}/issues/{got}/") if got else (0, None)
                if c2 != 200:
                    raise RuntimeError(f"{src}: Plane says {key} exists there but does not show it (HTTP 409 → "
                                       f"{got or 'no id'}): an archived or intake item? stopped, nothing guessed")
            elif code not in (200, 201):
                raise RuntimeError(f"POST {P}/issues/ for {src}: HTTP {code} {json.dumps(out, ensure_ascii=False)[:300]}")
            else:
                cur = out
                t.fresh.add(cur["id"])
                r["created"] += 1
                log(f"created {t.ident}-{cur['sequence_id']} ← {src}")
            t.items[key] = cur
            if pr["whole"] and cur["sequence_id"] != it["seq"]:
                raise RuntimeError(f"{src} became {t.ident}-{cur['sequence_id']}: the numbers diverged — stopped")
        else:
            what = differs(t, cur, it)
            if what and t.update and not t.dry:
                cur = t.p.write("PATCH", f"{P}/issues/{cur['id']}/", item_body(t, it))
                t.items[key] = cur
                r["updated"] += 1; log(f"updated {t.ident}-{cur['sequence_id']} ← {src} ({', '.join(what)})")
            elif what:
                # the target's people (or its own meet and plan) may have changed it since: theirs is kept, and said
                r["differs"] += 1
                log(f"{t.ident}-{cur['sequence_id']} differs from {src} ({', '.join(what)}) — kept as it is there"
                    f"{'' if t.update else '; --update takes the source' + chr(39) + 's'}")
            else:
                r["kept"] += 1
            if pr["whole"] and cur["sequence_id"] != it["seq"]:
                raise RuntimeError(f"{src} is {t.ident}-{cur['sequence_id']} there: the numbers diverged — stopped")
        new_by_key[src] = cur["id"]
        r["map"][src] = f"{t.ident}-{cur['sequence_id']}"


def wanted_comments(pr: dict, it: dict, inside: set) -> list:
    """(external_id, html) of every comment the target item carries — the one builder import and verify share."""
    src = f"{pr['identifier']}-{it['seq']}"
    out = []
    if not pr["whole"]:
        out.append((f"origin:{it['id']}", f"<p>הועבר מלשכת בינה: {src} (נוצר {it['created_at'][:10]}).</p>"))
    for c in it["comments"]:
        who = html.escape(c["actor"] or "")
        out.append((c["id"], f"<p><em>— {who + ', ' if who else ''}{c['created_at'][:16].replace('T', ' ')}</em></p>"
                             + c["html"]))
    outside = sorted({x for v in it["relations"].values() for x in v if x not in inside})
    parent = it.get("parent")
    lines = []
    if parent and parent not in inside:
        lines.append(f"פריט האב בלשכת בינה: {parent}.")
    if outside:
        lines.append(f"קשור בלשכת בינה ל: {', '.join(outside)}.")
    if lines:
        out.append((f"relations:{it['id']}", "".join(f"<p>{html.escape(x)}</p>" for x in lines)))
    return out


def ensure_children(t: Target, r: dict, new_by_key: dict, inside: set) -> None:
    """Modules, comments, files, parents — after every item of every project exists."""
    P = f"/projects/{t.pid}"
    pr = t.pr
    for m in pr["modules"]:
        mod = t.mods.get(m["name"])
        if not mod:
            continue
        have = {str(x.get("issue") or x.get("id")) for x in t.p.page(f"{P}/modules/{mod['id']}/module-issues/")}
        want = [t.items[(it["external_source"], it["external_id"])]["id"] for it in pr["items"]
                if it["seq"] in m["items"] and (it["external_source"], it["external_id"]) in t.items]
        new = [x for x in want if str(x) not in have]
        if new and not t.dry:
            t.p.write("POST", f"{P}/modules/{mod['id']}/module-issues/", {"issues": new})
        r["updated" if new else "kept"] += 1
    for it in pr["items"]:
        cur = t.items.get((it["external_source"], it["external_id"]))
        if not cur:
            continue
        src = f"{pr['identifier']}-{it['seq']}"
        CM = f"{P}/issues/{cur['id']}/comments/"
        fresh = cur["id"] in t.fresh
        have = set() if fresh else {(c.get("external_source"), c.get("external_id")) for c in t.p.page(CM)}
        for ext, body in wanted_comments(pr, it, inside):
            if (MOVE, ext) in have:
                r["kept"] += 1; continue
            if t.dry:
                r["created"] += 1; continue
            code, out = t.p.write_ex("POST", CM, {"comment_html": body, "external_source": MOVE, "external_id": ext})
            if code == 409:
                r["kept"] += 1                 # stored by a write whose answer was lost
            elif code in (200, 201):
                r["created"] += 1
            else:
                raise RuntimeError(f"{src}: comment {ext}: HTTP {code} {json.dumps(out, ensure_ascii=False)[:300]}")
        A = f"{P}/issues/{cur['id']}/issue-attachments/"
        if it["files"]:
            got = [] if fresh else (t.p.get(A) or [])
            have_f = {((f.get("attributes") or {}).get("name"), int((f.get("attributes") or {}).get("size") or 0))
                      for f in got if f.get("is_uploaded")}
            for f in it["files"]:
                if (f["name"], f["size"]) in have_f:
                    r["kept"] += 1; continue
                if t.dry:
                    r["created"] += 1; continue
                blob = base64.b64decode(f["b64"])
                made = t.p.write("POST", A, {"name": f["name"], "size": len(blob),
                                             "type": f["type"] or "application/octet-stream"})
                form = made.get("upload_data") or {}
                up = upload(form.get("url") or "", form.get("fields") or {}, f["type"], blob)
                if up not in (200, 201, 204):
                    raise RuntimeError(f"{src}: the store did not take {f['name']} (HTTP {up})")
                t.p.write("PATCH", f"{A}{made['asset_id']}/", {})
                r["created"] += 1; log(f"{t.ident}-{cur['sequence_id']}: {f['name']} ({len(blob)} bytes) attached")
        par = new_by_key.get(it.get("parent") or "")
        if par and cur.get("parent") != par and not t.dry:
            t.p.write("PATCH", f"{P}/issues/{cur['id']}/", {"parent": par}); r["updated"] += 1


def ensure_relations(targets: list, r: dict, new_by_key: dict) -> None:
    """Every relation between moved items, written once from one side; the other side is Plane's reverse."""
    done = set()
    for t in targets:
        for it in t.pr["items"]:
            me = new_by_key.get(f"{t.pr['identifier']}-{it['seq']}")
            if not me or t.dry:
                continue
            cur = None
            for kind, refs in sorted(it["relations"].items()):
                if kind not in PAIR:
                    continue
                mine = [new_by_key[x] for x in refs if x in new_by_key]
                todo = [x for x in mine if pair_of(kind, me, x) not in done]
                for x in mine:
                    done.add(pair_of(kind, me, x))
                if not todo:
                    continue
                if cur is None:
                    cur = {} if me in t.fresh else (t.p.get(f"/projects/{t.pid}/work-items/{me}/relations/") or {})
                have = {x["issue_id"] for x in cur.get(kind) or []}
                new = [x for x in todo if x not in have]
                if new:
                    t.p.write("POST", f"/projects/{t.pid}/work-items/{me}/relations/",
                              {"relation_type": kind, "issues": new})
                    r["created"] += len(new)
                else:
                    r["kept"] += 1


def upload(url: str, fields: dict, kind: str, blob: bytes) -> int:
    """tasks.py's: the store's signed form, its fields first and the file last."""
    edge = "dgo" + os.urandom(12).hex()
    body = b"".join(f'--{edge}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{edge}\r\nContent-Disposition: form-data; name="file"; filename="file"\r\n'
             f"Content-Type: {kind or 'application/octet-stream'}\r\n\r\n").encode() + blob + f"\r\n--{edge}--\r\n".encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST", headers={
                "Content-Type": f"multipart/form-data; boundary={edge}"}), timeout=600) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:                                             # noqa: BLE001 — said by the caller
        return -1


def load(a):
    with open(a.bundle, encoding="utf-8") as f:
        b = json.load(f)
    if b.get("format") != FORMAT:
        raise SystemExit(f"[plane-move] {a.bundle} is not a {FORMAT} bundle")
    # --rewrite OLD=NEW: the source office's addresses in the texts become the target's (a recording's page on vps1's
    # console is on the client's console after the move). Literal, applied before import and verify alike.
    pairs = [x.split("=", 1) for x in getattr(a, "rewrite", None) or []]
    if pairs:
        n = 0
        for pr in b["projects"]:
            for it in pr["items"]:
                for old, new in pairs:
                    n += it["description_html"].count(old) + it["name"].count(old)
                    it["description_html"] = it["description_html"].replace(old, new)
                    it["name"] = it["name"].replace(old, new)
                    for c in it["comments"]:
                        n += c["html"].count(old)
                        c["html"] = c["html"].replace(old, new)
        log(f"{n} address(es) rewritten for the target")
    remap = dict(x.split("=", 1) for x in a.as_ or [])
    for pr in b["projects"]:
        to = remap.get(pr["target"], remap.get(pr["identifier"], pr["target"]))
        pr["renamed"] = pr["target"] != pr["identifier"]       # DGO:…=BINA, as exported
        pr["rehearsal"], pr["target"] = to != pr["target"], to
    return b


def cmd_import(a) -> int:
    b = load(a)
    p = Plane(WORKSPACE)
    r = {"created": 0, "updated": 0, "kept": 0, "differs": 0, "map": {}}
    new_by_key, problems, targets = {}, [], []
    inside = {f"{pr['identifier']}-{it['seq']}" for pr in b["projects"] for it in pr["items"]}
    t0 = time.time()
    try:
        for pr in b["projects"]:
            t = Target(p, pr, pr["target"], a.dry_run, a.update)
            ensure_project(t, r)
            if not t.pid:
                continue                                          # a dry run on a project that is not there yet
            ensure_meta(t, r)
            ensure_items(t, r, new_by_key)
            targets.append(t)
        for t in targets:
            ensure_children(t, r, new_by_key, inside)
        ensure_relations(targets, r, new_by_key)
    except RuntimeError as e:
        problems.append(str(e))
    out = dict(r, problems=problems, map={k: v for k, v in r["map"].items() if k != v},
               reads=p.reads, writes=p.writes, seconds=round(time.time() - t0, 1), dry_run=bool(a.dry_run))
    print("RESULT " + json.dumps(out, ensure_ascii=False))
    return 1 if problems else 0


def cmd_verify(a) -> int:
    b = load(a)
    p = Plane(WORKSPACE)
    diffs, n = [], 0
    inside = {f"{pr['identifier']}-{it['seq']}" for pr in b["projects"] for it in pr["items"]}
    tg = {}
    for pr in b["projects"]:
        t = Target(p, pr, pr["target"], True)
        if not t.pid:
            diffs.append(f"{pr['target']}: no such project"); continue
        tg[(pr["identifier"], pr["target"])] = t
    new_id = {f"{pr['identifier']}-{it['seq']}": t.items[(it["external_source"], it["external_id"])]["id"]
              for (_, _), t in tg.items() for pr in [t.pr] for it in pr["items"]
              if (it["external_source"], it["external_id"]) in t.items}
    for t in tg.values():
        pr, P = t.pr, f"/projects/{t.pid}"
        state_name = {s["id"]: s["name"] for s in t.states.values()}
        label_name = {x["id"]: x["name"] for x in t.labels.values()}
        for m in pr["modules"]:
            mod = t.mods.get(m["name"])
            if not mod:
                diffs.append(f"{t.ident}: no module «{m['name']}»"); continue
            members = {str(x.get("issue") or x.get("id")) for x in p.page(f"{P}/modules/{mod['id']}/module-issues/")}
            for it in pr["items"]:
                cur = t.items.get((it["external_source"], it["external_id"]))
                if it["seq"] in m["items"] and cur and str(cur["id"]) not in members:
                    diffs.append(f"{t.ident}-{cur['sequence_id']}: not in module «{m['name']}»")
        for it in pr["items"]:
            n += 1
            src = f"{pr['identifier']}-{it['seq']}"
            cur = t.items.get((it["external_source"], it["external_id"]))
            if not cur:
                diffs.append(f"{src}: missing"); continue
            me = f"{t.ident}-{cur['sequence_id']}"
            if pr["whole"] and cur["sequence_id"] != it["seq"]:
                diffs.append(f"{src}: is {me}")
            for k, have, want in (("name", cur.get("name"), it["name"]), ("priority", cur.get("priority"), it["priority"]),
                                  ("state", state_name.get(cur.get("state")), it["state"]),
                                  ("labels", sorted(label_name.get(x, x) for x in cur.get("labels") or []), sorted(it["labels"])),
                                  ("start_date", cur.get("start_date") or None, it["start_date"]),
                                  ("target_date", cur.get("target_date") or None, it["target_date"]),
                                  ("parent", cur.get("parent"), new_id.get(it.get("parent") or "")),
                                  ("description", words(cur.get("description_html")), words(it["description_html"]))):
                if have != want:
                    diffs.append(f"{me} ({src}): {k} differs")
            got = {(c.get("external_source"), c.get("external_id")): c for c in p.page(f"{P}/issues/{cur['id']}/comments/")}
            for ext, body in wanted_comments(pr, it, inside):
                c = got.get((MOVE, ext))
                if c is None:
                    diffs.append(f"{me} ({src}): comment {ext} missing")
                elif words(c.get("comment_html") or "") != words(body):
                    diffs.append(f"{me} ({src}): comment {ext} differs")
            if it["files"]:
                have_f = {((f.get("attributes") or {}).get("name"), int((f.get("attributes") or {}).get("size") or 0))
                          for f in p.get(f"{P}/issues/{cur['id']}/issue-attachments/") or [] if f.get("is_uploaded")}
                for f in it["files"]:
                    if (f["name"], f["size"]) not in have_f:
                        diffs.append(f"{me} ({src}): file {f['name']} missing")
            me_id = new_id.get(src)
            want = {(k, new_id[x]) for k, v in it["relations"].items() if k in PAIR for x in v if x in new_id}
            if me_id and want:
                rel = p.get(f"/projects/{t.pid}/work-items/{me_id}/relations/") or {}
                have = {(k, x["issue_id"]) for k, v in rel.items() if isinstance(v, list) for x in v}
                if want - have:
                    diffs.append(f"{me} ({src}): {len(want - have)} relation(s) missing")
    print("VERIFY " + json.dumps({"items": n, "diffs": len(diffs), "first": diffs[:40]}, ensure_ascii=False))
    return 1 if diffs else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):    # Hebrew on every line: UTF-8 whatever the console's code page (G10)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="plane_move")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("snapshot-sql")
    q.add_argument("specs", nargs="+")
    q.set_defaults(fn=cmd_snapshot_sql)
    e = sub.add_parser("export")
    e.add_argument("specs", nargs="+")
    e.add_argument("--snapshot", help="the snapshot-sql query's JSON line (default: stdin)")
    e.add_argument("--redact", help="a regular expression of other clients' names, replaced by «[לקוח אחר]»")
    e.set_defaults(fn=cmd_export)
    for name, fn in (("import", cmd_import), ("verify", cmd_verify)):
        s = sub.add_parser(name)
        s.add_argument("bundle")
        s.add_argument("--as", dest="as_", action="append", metavar="SRC=DST",
                       help="carry project SRC into project DST there (a scratch rehearsal: EXX=XTRS)")
        s.add_argument("--rewrite", action="append", metavar="OLD=NEW",
                       help="a literal address in the texts and what it is on the target (repeatable)")
        if name == "import":
            s.add_argument("--dry-run", action="store_true")
            s.add_argument("--update", action="store_true",
                           help="an item there that differs from the bundle takes the bundle's fields (default: kept, "
                                "and counted as «differs» — once people work there, theirs is never overwritten)")
        s.set_defaults(fn=fn)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
