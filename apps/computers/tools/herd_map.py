#!/usr/bin/env python3
"""herd_map — what runs on each office of the herd, against where it should run (DGO-915).

`./bbox computers herd` gathers one bundle and runs this on it (the path is argv[1]):

    {"self": "macbook", "read_at": "2026-10-21T15:00:00Z",
     "offices": {"macbook":   {"local": true, "inspect": [<docker inspect>…], "df": <docker system df -v>},
                 "hp-laptop": {"label": "HP", "overview": <machine /api/overview>, "storage": <machine /api/storage>},
                 "vps1":      {"label": "…", "error": "…"}}}

The target is apps/computers/herd.yaml: one office per business app, the base everywhere. Every
container and volume is given to the app that declares it, read from every app.json and compose
file of this checkout, so the answer names apps rather than containers.

For each office it prints:
- the apps in their place;
- the apps running where they do not belong, and where they go;
- what is left of apps that do not run there (stopped containers, data);
- the apps that belong there and do not run;
- another deployment on the same machine;
- anything no manifest names.

Then it prints the apps that run on more than one office. Exit 0 when nothing differs, 1 when
something does, 2 when the bundle or the target cannot be read. `--json` prints the same as data.
"""
from __future__ import annotations

import json
import re
import sys
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
        cands += [tail, re.sub(r"^(deployment-hacohen|platform-os-net|digital-office|mydgo)-", "", tail)]
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


def compare(bundle: dict, target: Target, namer: Namer) -> dict:
    offices = {}
    for oid, o in (bundle.get("offices") or {}).items():
        key = target.office(oid)
        if o.get("error"):
            offices[key] = {"office": oid, "error": o["error"]}
            continue
        offices[key] = read_office(oid, o, namer)
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


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: herd_map.py <bundle.json> [--json]", file=sys.stderr)
        return 2
    try:
        bundle = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        target = Target(yaml.safe_load(TARGET.read_text(encoding="utf-8")) or {})
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"herd: cannot read the bundle or the target: {e}", file=sys.stderr)
        return 2
    apps, svc2app, vol2app = manifests(ROOT)
    namer = Namer(apps, svc2app, vol2app, target.names, target.volume_names)
    res = compare(bundle, target, namer)
    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=list))
    else:
        print(render(res, target, bundle))
    return 1 if res["drift"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
