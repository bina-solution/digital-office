#!/usr/bin/env python3
"""herd_map — what runs on each office of the herd, against where it should run (DGO-915).

`./bbox computers herd` gathers one bundle and runs this on it (the path is argv[1]):

    {"self": "macbook", "read_at": "2026-10-21T15:00:00Z",
     "offices": {"macbook":   {"local": true, "inspect": [<docker inspect>…], "df": <docker system df -v>,
                               "follow_state": <the text of data/follow/state, or null>},
                 "hp-laptop": {"label": "HP", "overview": <machine /api/overview>, "storage": <machine /api/storage>},
                 "vps1":      {"label": "…", "error": "…"}}}

The target is apps/computers/herd.yaml: one office per business app, the base everywhere. Every
container and volume is given to the app that declares it, read from every app.json and compose
file of this checkout, so the answer names apps rather than containers.

For each office it prints:
- whether it takes dgo-stable by itself: its follow's last cycle, or that it does not follow, stopped, is blocked or
  has not been up to date for a day (each of those is a difference);
- the apps in their place;
- the apps running where they do not belong, and where they go;
- what is left of apps that do not run there (stopped containers, data);
- the apps that belong there and do not run;
- another deployment on the same machine;
- anything no manifest names.

Then it prints the apps that run on more than one office. Exit 0 when nothing differs, 1 when
something does, 2 when the bundle or the target cannot be read. `--json` prints the same as data.

`--map` (`./bbox computers map`, DGO-1960) answers instead with the network as it IS — every office the reads or the
links name, its link (as dgo-extend measures it, `bundle["links"]`), its engine, what runs and what is stopped, its
follow — with no target: from the declaration it takes only how to name a container, and does without it. Exit 0.
"""
from __future__ import annotations

import calendar
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "apps" / "computers" / "herd.yaml"
ANON = re.compile(r"^[0-9a-f]{64}$")          # an anonymous volume: nobody named it, nobody owns it
MIN_UNKNOWN = 10_000_000                      # an unnamed-app volume under 10 MB is noise, not data


def gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


# ── what this checkout declares ──────────────────────────────────────────────────────────────────
def manifests(root: Path) -> tuple[dict, dict, dict]:
    """(apps, compose service → app, volume key → app), from every app.json and its compose file."""
    apps: dict = {}
    svc2app: dict = {}
    vol2app: dict = {}
    for layer_dir in ("platform-base", "apps"):
        for mf in sorted((root / layer_dir).glob("*/app.json")):
            try:
                a = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            aid = a.get("id") or mf.parent.name
            apps[aid] = {"layer": a.get("layer")}
            comp = mf.parent / (a.get("compose") or "docker-compose.yml")
            doc: dict = {}
            if comp.exists():
                try:
                    doc = yaml.safe_load(comp.read_text(encoding="utf-8")) or {}
                except (OSError, yaml.YAMLError):
                    doc = {}
            for name, svc in (doc.get("services") or {}).items():
                svc2app.setdefault(name, aid)
                cname = str((svc or {}).get("container_name") or "")
                if cname:
                    svc2app.setdefault(cname.split("-${")[0], aid)
            for v in list((doc.get("volumes") or {}).keys()) + list((a.get("data") or {}).get("volumes") or []):
                vol2app.setdefault(v, aid)
    return apps, svc2app, vol2app


class Namer:
    """Gives a container or a volume to the app that declares it ("" when none does)."""

    def __init__(self, apps: dict, svc2app: dict, vol2app: dict, names: dict, volume_names: dict):
        self.apps, self.svc2app, self.names = apps, svc2app, names
        self.vol2app = {**vol2app, **volume_names}

    def _known(self, cand: str) -> str:
        return self.names.get(cand) or self.svc2app.get(cand) or (cand if cand in self.apps else "")

    def container(self, r: dict) -> str:
        cands = [r["service"]] if r["service"] else []
        parts = r["name"].split("-")
        cands += ["-".join(parts[:i]) for i in range(len(parts), 0, -1)]     # the longest declared prefix wins
        tail = r["image"].split("@")[0].rsplit(":", 1)[0].rsplit("/", 1)[-1]
        cands += [tail, re.sub(r"^(digital-office|platform-os-net|digital-office|mydgo)-", "", tail)]
        for cand in cands:
            app = self._known(cand) if cand else ""
            if app:
                return app
        return ""

    def volume(self, v: dict) -> str:
        n = v["name"]
        cands = [v["key"]] if v["key"] else []
        if v["project"] and n.startswith(v["project"] + "_"):
            cands.append(n[len(v["project"]) + 1:])
        cands += [n, n.split("_", 1)[-1]]
        for cand in cands:
            if cand in self.vol2app:
                return self.vol2app[cand]
        return ""


# ── what an office says about itself ─────────────────────────────────────────────────────────────
def size_of(v) -> int:
    if isinstance(v, (int, float)):
        return max(0, int(v))
    m = re.match(r"\s*([\d.]+)\s*([kKMGT]?)i?B", str(v or ""))
    if not m:
        return 0
    return int(float(m.group(1)) * {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)])


def labels_of(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return dict(kv.split("=", 1) for kv in str(raw or "").split(",") if "=" in kv)


def containers_of(o: dict) -> list:
    """[{name, status, service, project, image}] from docker inspect (this office) or machine's overview."""
    rows = []
    for c in o.get("inspect") or []:
        cfg = c.get("Config") or {}
        lab = cfg.get("Labels") or {}
        rows.append({"name": (c.get("Name") or "").lstrip("/"), "status": (c.get("State") or {}).get("Status") or "",
                     "service": lab.get("com.docker.compose.service") or "",
                     "project": lab.get("com.docker.compose.project") or "", "image": cfg.get("Image") or ""})
    for c in (o.get("overview") or {}).get("containers") or []:
        lab = c.get("labels") or {}
        # machine's rows carry the labels; security's carry the compose service as `name` and the
        # container's own name as `raw_name`
        service = lab.get("com.docker.compose.service") or ("" if lab else (c.get("name") or ""))
        rows.append({"name": c.get("raw_name") or c.get("name") or "", "status": c.get("status") or "",
                     "service": service, "project": lab.get("com.docker.compose.project") or "",
                     "image": c.get("image") or ""})
    return rows


def volumes_of(o: dict) -> list:
    """[{name, size, refs, project, key}] from `docker system df -v` (this office) or machine's storage."""
    df = o.get("df") or (o.get("storage") or {}).get("docker_df") or {}
    rows = []
    for v in df.get("Volumes") or []:
        name = v.get("Name") or ""
        if not name:                         # security's figures carry sizes only: nothing to give to an app
            continue
        lab = labels_of(v.get("Labels"))
        use = v.get("UsageData") or {}
        refs = use.get("RefCount") if use else v.get("Links")
        try:
            refs = int(refs)
        except (TypeError, ValueError):
            refs = -1
        rows.append({"name": name, "size": size_of(use.get("Size") if use else v.get("Size")), "refs": refs,
                     "project": lab.get("com.docker.compose.project") or "", "key": lab.get("com.docker.compose.volume") or ""})
    return rows


# ── the comparison ───────────────────────────────────────────────────────────────────────────────
class Target:
    def __init__(self, doc: dict):
        self.offices = doc.get("offices") or {}
        self.base = set(doc.get("base") or [])
        self.per_office = {k: set(v or []) for k, v in (doc.get("per_office") or {}).items()}
        self.apps = doc.get("apps") or {}
        self.off = set(doc.get("retired") or [])
        self.names = doc.get("names") or {}
        self.volume_names = doc.get("volume_names") or {}
        self.alias = {}
        for key, o in self.offices.items():
            self.alias[key] = key
            for a in (o or {}).get("aliases") or []:
                self.alias[a] = key

    def office(self, oid: str) -> str:
        return self.alias.get(oid, oid)

    def place(self, app: str, office: str) -> str:
        """'here' | 'base' | 'off' | '<office it belongs to>' | '' (the target does not name it)"""
        if app in self.base:
            return "base"
        if app in self.per_office:
            return "here" if office in self.per_office[app] else "off"
        if app in self.off:
            return "off"
        want = self.apps.get(app)
        if not want:
            return ""
        return "here" if want == office else want


def own_project(ctrs: list) -> str:
    """The deployment this office IS: the compose project most of its running containers belong to."""
    c = Counter(r["project"] for r in ctrs if r["status"] == "running" and r["project"])
    return c.most_common(1)[0][0] if c else ""


def read_office(oid: str, o: dict, namer: Namer) -> dict:
    ctrs, vols = containers_of(o), volumes_of(o)
    own = own_project(ctrs)
    apps: dict = defaultdict(lambda: {"running": 0, "total": 0, "data": 0, "vols": 0})
    foreign: dict = defaultdict(lambda: {"running": 0, "total": 0, "data": 0, "vols": 0, "unmounted": 0, "unmounted_data": 0})
    unknown_ctrs, unknown_vols, anon = [], [], [0, 0]
    for r in ctrs:
        if r["project"] and own and r["project"] != own:
            f = foreign[r["project"]]
            f["total"] += 1
            f["running"] += r["status"] == "running"
            continue
        app = namer.container(r)
        if not app:
            unknown_ctrs.append(r["name"])
            continue
        apps[app]["total"] += 1
        apps[app]["running"] += r["status"] == "running"
    for v in vols:
        if v["project"] and own and v["project"] != own:
            f = foreign[v["project"]]
            f["vols"] += 1
            f["data"] += v["size"]
            if v["refs"] == 0:
                f["unmounted"] += 1
                f["unmounted_data"] += v["size"]
            continue
        if ANON.match(v["name"]):
            anon[0] += 1
            anon[1] += v["size"]
            continue
        app = namer.volume(v)
        if not app:
            if v["size"] >= MIN_UNKNOWN:
                unknown_vols.append((v["name"], v["size"], v["refs"]))
            continue
        apps[app]["vols"] += 1
        apps[app]["data"] += v["size"]
    return {"office": oid, "own": own, "apps": dict(apps), "foreign": dict(foreign),
            "unknown_containers": unknown_ctrs, "unknown_volumes": unknown_vols, "anonymous": anon,
            "running": sum(1 for r in ctrs if r["status"] == "running"), "containers": len(ctrs),
            "volumes": len(vols), "data": sum(v["size"] for v in vols)}


# ── does the office take dgo-stable by itself ─────────────────────────────────────────────────────
# The Dell never followed and nobody saw it: it kept link code from before the herd's withholding and served the public
# hub every app it had (DGO-1838; issues/an-office-that-does-not-follow-…yaml). A linked office's machine serves its
# follow's last cycle in the overview (`follow`, platform-base/machine/app.py); this office's own is its state file,
# which the hook passes as text and is read here with the same keys.
FOLLOW_KEYS = {"LAST_AT": "at", "LAST_RESULT": "result", "LAST_DETAIL": "detail", "CURRENT_EPOCH": "current_epoch",
               "FAILED_TARGET": "failed_target", "FAILED_AT": "failed_at", "TAKING": "taking"}
# A cycle comes 30 minutes after the last one ended (both the host timer and the follow-runner add up to 5), and one
# that is put off still writes its line: two hours with none is a follow that stopped. The Dell's follow-runner was
# declared but never created — no cycle for 2 h while two batches went green, and the herd called it healthy for 6
# (DGO-1838, 2026-11-13). Two hours, not less: a laptop back from sleep or a boot runs its first cycle 15–35 min in, a
# `--dry-run` at the timer's minute drops one line, and `now` is this office's clock while `at` is the other's.
FOLLOW_SILENT_S = 2 * 3600
# …but a take writes its cycle's line only when it ends: its unit's own bound (6 h, scripts/follow.sh) counted from
# the cycle's start, which comes up to a cycle after the last line
TAKE_SILENT_S = 6 * 3600 + FOLLOW_SILENT_S
BEHIND_S = 24 * 3600         # a day since it was last up to date: green has reached the others and not this one


def follow_state_of(text) -> dict | None:
    """A follow state file's text → the overview's `follow` shape (only the keys read here); None for no file."""
    if not isinstance(text, str):
        return None
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in FOLLOW_KEYS and value.strip():
            out[FOLLOW_KEYS[key]] = value.strip()
    return out or None


def _epoch(value) -> float | None:
    """`2026-11-13 01:03:31 UTC`, `2026-11-13 01:03 UTC`, `2026-10-21T15:00:00Z` or an epoch → seconds; None if neither."""
    s = str(value or "").strip()
    if s.isdigit():
        return float(s)
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return float(calendar.timegm(time.strptime(s, fmt)))
        except ValueError:
            continue
    return None


def _ago(seconds: float) -> str:
    # minutes under three hours: «2 h» for 2 h 59 min hid how far past the two-hour line a follow is
    if seconds < 3 * 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 86400:.1f} days" if seconds >= 2 * 86400 else f"{seconds / 3600:.0f} h"


def follow_of(o: dict, now: float, declared: str = "") -> dict:
    """{ok, line}: whether this office takes dgo-stable by itself, and the one line that says how it stands.
    `declared` is the office's `follow` in herd.yaml: `by-hand` for one that is updated by hand on purpose."""
    if o.get("local"):
        f, known = follow_state_of(o.get("follow_state")), True
    else:
        ov = o.get("overview") or {}
        f, known = ov.get("follow"), "follow" in ov
    if not f and declared == "by-hand":
        return {"ok": True, "line": f"follow           by hand, as {TARGET.name} declares: no follow runs here"}
    if not known:
        return {"ok": False, "line": "FOLLOW UNREAD    its machine does not say (older than 2026-11-12, or not running): "
                                     "nothing tells whether it takes dgo-stable"}
    if not f:
        return {"ok": False, "line": "DOES NOT FOLLOW  no follow cycle has run here: dgo-stable reaches it only by hand"}
    res, at, cur = f.get("result") or "?", _epoch(f.get("at")), _epoch(f.get("current_epoch"))
    when_why = f"at {f.get('at') or '?'}" + (f" — {f['detail']}" if f.get("detail") else "")
    last = f"{res} {when_why}"
    if at is None or now - at > (TAKE_SILENT_S if f.get("taking") else FOLLOW_SILENT_S):
        return {"ok": False, "line": f"FOLLOW SILENT    no cycle for {_ago(now - at) if at else 'ever'}"
                                     f"{' (a take open)' if f.get('taking') else ''}; the last: {last}"}
    # a failed take is said ONCE as `failed`; every cycle after it says `waiting` (or `skipped`) while the target it
    # failed on stays set — until a newer green is tried or a take succeeds (scripts/follow.sh). The second reader.
    if f.get("failed_target"):
        return {"ok": False, "line": f"FOLLOW FAILED    {f['failed_target'][:9]} failed at {f.get('failed_at') or '?'}; "
                                     f"not taken again until a newer one is green — the last cycle: {last}"}
    if res in ("blocked", "failed"):
        return {"ok": False, "line": f"FOLLOW {res.upper():<10}{when_why}"}
    if res not in ("took", "current") and cur is not None and now - cur > BEHIND_S:
        return {"ok": False, "line": f"BEHIND           last up to date {_ago(now - cur)} ago; the last cycle: {last}"}
    return {"ok": True, "line": f"follow           {last}"}


def compare(bundle: dict, target: Target, namer: Namer) -> dict:
    offices = {}
    now = _epoch(bundle.get("read_at")) or time.time()
    for oid, o in (bundle.get("offices") or {}).items():
        key = target.office(oid)
        if o.get("error"):
            offices[key] = {"office": oid, "error": o["error"]}
            continue
        offices[key] = read_office(oid, o, namer)
        offices[key]["follow"] = follow_of(o, now, str((target.offices.get(key) or {}).get("follow") or ""))
    runs_on: dict = defaultdict(list)                  # app → offices where it runs
    present_on: dict = defaultdict(list)               # app → offices where anything of it is
    for key, r in offices.items():
        for app, a in (r.get("apps") or {}).items():
            if a["running"]:
                runs_on[app].append(key)
            if a["running"] or a["total"] or a["data"]:
                present_on[app].append(key)
    drift = 0
    for key, r in offices.items():
        if r.get("error"):
            continue
        rep = {"in_place": [], "move": [], "left_over": [], "stopped_here": [], "missing": [], "base_stopped": [], "unplaced": []}
        for app, a in sorted(r["apps"].items()):
            where = target.place(app, key)
            if where == "":
                rep["unplaced"].append((app, a))
            elif where in ("here", "base"):
                if a["running"]:
                    rep["in_place"].append(app)
                elif where == "base":
                    rep["base_stopped"].append(app)
                else:
                    rep["stopped_here"].append((app, a))
            elif a["running"]:
                rep["move"].append((app, where, a))
            else:
                rep["left_over"].append((app, where, a))
        for app, want in sorted(target.apps.items()):
            if want == key and app not in r["apps"] and present_on.get(app):
                rep["missing"].append((app, [o for o in runs_on.get(app, [])]))
        r["report"] = rep
        drift += sum(len(rep[k]) for k in ("move", "left_over", "stopped_here", "missing", "unplaced"))
        drift += len(r["foreign"]) + len(r["unknown_containers"]) + len(r["unknown_volumes"])
        drift += 0 if r["follow"]["ok"] else 1
    dupes = {app: on for app, on in runs_on.items()
             if len(on) > 1 and app not in target.base and app not in target.per_office}
    drift += len(dupes)
    return {"offices": offices, "duplicates": dupes, "drift": drift}


# ── the page ─────────────────────────────────────────────────────────────────────────────────────
def figures(a: dict) -> str:
    out = f"{a['running']}/{a['total']}" if a["total"] else "no containers"
    return out + (f", {gb(a['data'])}" if a["data"] >= 10_000_000 else "")


def render(res: dict, target: Target, bundle: dict) -> str:
    lines = [f"herd — read from {bundle.get('self') or 'this office'} at {bundle.get('read_at', '')} · target {TARGET.relative_to(ROOT)}"]
    order = list(target.offices) + [k for k in res["offices"] if k not in target.offices]
    for key in order:
        r = res["offices"].get(key)
        o = target.offices.get(key) or {}
        title = f"{o.get('label') or key} ({r['office'] if r else key})"
        role = ((o.get("role") or {}).get("en")) or "not in the target"
        lines.append("")
        lines.append(f"== {title} — {role}")
        if r is None:
            lines.append("   not read: no link from this office to it")
            continue
        if r.get("error"):
            lines.append(f"   not read: {r['error']}")
            continue
        rep = r["report"]
        lines.append(f"   {r['running']} running / {r['containers']} containers · {r['volumes']} volumes {gb(r['data'])}"
                     + (f" · the office is compose project '{r['own']}'" if r["own"] else ""))
        lines.append("   " + r["follow"]["line"])
        if rep["in_place"]:
            lines.append("   in place       " + ", ".join(rep["in_place"]))
        if rep["base_stopped"]:
            lines.append("   base, stopped  " + ", ".join(rep["base_stopped"]))
        for app, where, a in rep["move"]:
            lines.append(f"   MOVE           {app} → {'off (retired)' if where == 'off' else where}  ({figures(a)})")
        for app, a in rep["stopped_here"]:
            lines.append(f"   STOPPED HERE   {app} belongs here and does not run  ({figures(a)})")
        for app, on in rep["missing"]:
            lines.append(f"   MISSING        {app} belongs here" + (f"; runs on {', '.join(on)}" if on else "; runs nowhere yet"))
        if rep["left_over"]:
            lines.append("   LEFT OVER      " + " · ".join(f"{app} ({figures(a)})" for app, _w, a in rep["left_over"]))
        for app, a in rep["unplaced"]:
            lines.append(f"   NOT IN TARGET  {app} ({figures(a)}) — give it an office in {TARGET.name}")
        for proj, f in sorted(r["foreign"].items(), key=lambda kv: -kv[1]["data"]):
            lines.append(f"   ANOTHER DEPLOYMENT  '{proj}': {f['running']}/{f['total']} running, {f['vols']} volumes {gb(f['data'])}"
                         + (f" ({f['unmounted']} mounted by nothing: {gb(f['unmounted_data'])})" if f["unmounted"] else ""))
        if r["unknown_containers"]:
            lines.append("   UNKNOWN        containers: " + ", ".join(sorted(r["unknown_containers"])[:12])
                         + (f" (+{len(r['unknown_containers']) - 12})" if len(r["unknown_containers"]) > 12 else ""))
        if r["unknown_volumes"]:
            lines.append("   UNKNOWN        volumes: " + ", ".join(f"{n} {gb(s)}{' (mounted by nothing)' if refs == 0 else ''}"
                                                          for n, s, refs in sorted(r["unknown_volumes"], key=lambda x: -x[1])))
        if r["anonymous"][0]:
            lines.append(f"   anonymous volumes: {r['anonymous'][0]}, {gb(r['anonymous'][1])}")
    lines.append("")
    if res["duplicates"]:
        lines.append("== runs on more than one office")
        for app, on in sorted(res["duplicates"].items()):
            lines.append(f"   {app}: {', '.join(on)} → {target.apps.get(app) or 'off'}")
    lines.append(f"== {res['drift']} difference(s) from the target" if res["drift"] else "== the herd matches the target")
    return "\n".join(lines)


# ── the live map (`./bbox computers map`, DGO-1960): what IS, with no target ──────────────────────────────────────
# The same reads as the comparison, plus the links as dgo-extend measures them (`bundle["links"]`, its GET /api/link),
# answered as they are: an office the link names but no machine answered for is still on the map, as «not read».
def live_map(bundle: dict, namer: Namer) -> dict:
    now = _epoch(bundle.get("read_at")) or time.time()
    read = bundle.get("offices") or {}
    links = {i["office"]: i for i in ((bundle.get("links") or {}).get("items") or []) if isinstance(i, dict) and i.get("office")}
    offices = {}
    for oid in list(read) + [k for k in links if k not in read]:
        o, ln = read.get(oid) or {}, links.get(oid) or {}
        row = {"office": oid, "label": ln.get("label") or o.get("label") or oid, "this_office": bool(o.get("local"))}
        if ln:
            carry = ln.get("carry") or {}
            row["link"] = {"state": ln.get("state"), "transport": ln.get("transport"), "address": ln.get("endpoint"),
                           "direction": ln.get("direction"), "commit": ln.get("commit"),
                           "publishes": len(ln.get("apps") or []), "ok": (ln.get("verdict") or {}).get("ok"),
                           "why": (ln.get("verdict") or {}).get("why") or "",
                           "carry": ({"state": carry.get("state"), "via": carry.get("via"), "rtt_ms": carry.get("rtt_ms"),
                                      "heard_s": carry.get("heard_s")} if carry else None)}
        if not o or o.get("error"):
            row["error"] = o.get("error") or "no machine answered for it through the link"
        else:
            r = read_office(oid, o, namer)
            row.update({k: r[k] for k in ("running", "containers", "volumes", "data")})
            row["project"] = r["own"]
            row["runs"] = sorted(a for a, v in r["apps"].items() if v["running"])
            row["stopped"] = sorted(a for a, v in r["apps"].items() if not v["running"] and (v["total"] or v["data"]))
            row["other_deployments"] = sorted(r["foreign"])
            row["follow"] = follow_of(o, now)["line"].strip()
        offices[oid] = row
    # no `items` at all is a link read that failed (dgo-extend off, or it did not answer): said, never shown as «no links»
    links_read = isinstance((bundle.get("links") or {}).get("items"), list)
    return {"read_from": bundle.get("self"), "read_at": bundle.get("read_at"), "links_read": links_read, "offices": offices}


def render_map(m: dict) -> str:
    lines = [f"network map — read live from {m.get('read_from') or 'this office'} at {m.get('read_at', '')}: this office's "
             "engine, each linked office's machine, and the links as dgo-extend measures them"]
    if not m.get("links_read"):
        lines.append("   links: NOT READ — dgo-extend did not answer here, so no link state is shown (`./bbox dgo link status`)")
    for oid, r in sorted(m["offices"].items(), key=lambda kv: (not kv[1]["this_office"], kv[0])):
        lines.append("")
        lines.append(f"== {r['label']} ({oid})" + (" — this office" if r["this_office"] else ""))
        ln = r.get("link")
        if ln:
            c = ln.get("carry") or {}
            via = (f" · carry {c.get('state')} via {c.get('via')}" + (f", rtt {c['rtt_ms']:.1f} ms" if isinstance(c.get("rtt_ms"), (int, float)) else "")
                   if c else "")
            lines.append(f"   link     {ln.get('state') or '?'} · {ln.get('transport') or '?'} · {ln.get('address') or '?'} · "
                         f"{ln.get('direction') or '?'}{via}")
            lines.append(f"            commit {str(ln.get('commit') or '?')[:9]} · publishes {ln['publishes']} app(s) here"
                         + (f" · {ln['why']}" if ln.get("why") and not ln.get("ok") else ""))
        if r.get("error"):
            lines.append(f"   not read: {r['error']}")
            continue
        lines.append(f"   engine   {r['running']} running / {r['containers']} containers · {r['volumes']} volumes {gb(r['data'])}"
                     + (f" · compose project '{r['project']}'" if r["project"] else ""))
        lines.append(f"   {r['follow']}")
        if r["runs"]:
            lines.append(f"   runs     {', '.join(r['runs'])}")
        if r["stopped"]:
            lines.append(f"   stopped  {', '.join(r['stopped'])}")
        if r["other_deployments"]:
            lines.append(f"   also     other deployments on this machine: {', '.join(r['other_deployments'])}")
    return "\n".join(lines)


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: herd_map.py <bundle.json> [--map] [--json]", file=sys.stderr)
        return 2
    try:
        bundle = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        # the map answers with what is: it takes from the declaration only how to NAME a container (`names`), and does
        # without it when there is none
        try:
            doc = yaml.safe_load(TARGET.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            if "--map" not in argv:
                raise
            doc = {}
        target = Target(doc if isinstance(doc, dict) else {})
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"herd: cannot read the bundle or the target: {e}", file=sys.stderr)
        return 2
    apps, svc2app, vol2app = manifests(ROOT)
    namer = Namer(apps, svc2app, vol2app, target.names, target.volume_names)
    if "--map" in argv:
        m = live_map(bundle, namer)
        print(json.dumps(m, ensure_ascii=False, indent=1) if "--json" in argv else render_map(m))
        return 0
    res = compare(bundle, target, namer)
    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=list))
    else:
        print(render(res, target, bundle))
    return 1 if res["drift"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
