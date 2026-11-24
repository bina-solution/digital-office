#!/usr/bin/env python3
"""when_idle.py — the apps whose running containers are recreated only while they are idle (DGO-2129).

An app that hosts work a recreate would kill says so in its app.json: `"recreate": "when-idle"`. Claude Desktop is
one: every agent session of the office runs in its container. On 2026-11-19 the HP's follow recreated it at 18:39Z
mid-work, and nobody was resumed until the morning. Its own hooks/busy says when it is at work. An `up` then brings up
the rest of the office first, and its services after, only while it is idle (lib.sh compose_when_idle_split/_up).
follow recreates them at a quiet cycle. An instance inherits the word from its template's app.json. Its hooks are the
template's, run with DGO_INSTANCE_ID/OF/KEY, as bbox runs them (bbox, `<instance> <verb>`).

A service that needs one of them (depends_on, links, network_mode: service:<x>, volumes_from) goes with them, whatever
app declares it: compose converges a diverged dependency of what it is told to bring up, so an `up` of that service
alone would recreate them under their people all the same. Read from each app's own compose file: a dependency only an
override adds is not seen.

    when_idle.py apps   → one line per ENABLED «when-idle» app, tab-separated:
                          <app id>  <its services>  <the services that need them | ->  <its hooks folder>
                          <instance of | ->  <key | ->  <the hooks it ships: busy,before-recreate,after-recreate | ->
                          (service lists space-separated). The hooks folder is relative to the checkout, so a list
                          kept by one path (lib.sh keeps the last one read) holds from another: inside the desktop the
                          office is /workspace/office, on the HP's host /mnt/c/…. What it ships is said here, so a hook
                          that cannot be read when it is needed (a path gone, a drive answering EIO) holds the app
                          rather than reading as «it has none» (DGO-2129's third reader).
Exit 1 when the catalog cannot be read: the caller holds nothing it cannot name, and says so.
"""
import os
import pathlib
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

HOOKS = ("busy", "before-recreate", "after-recreate")


def needs(svc) -> set:
    """The services a compose service needs running: what compose brings up (and converges) with it."""
    svc = svc if isinstance(svc, dict) else {}
    dep = svc.get("depends_on") or []
    out = set(dep if isinstance(dep, list) else dep)
    out.update(str(link).split(":", 1)[0] for link in svc.get("links") or [])
    mode = str(svc.get("network_mode") or "")
    if mode.startswith("service:"):
        out.add(mode[len("service:"):])
    for v in svc.get("volumes_from") or []:
        v = str(v)
        if not v.startswith("container:"):
            out.add(v.split(":", 1)[0])
    return out


def ships(hooks: pathlib.Path) -> list:
    """The hooks a folder holds. Only «no such file» means not shipped: any other error (a drive answering EIO) is
    raised, so the caller says the catalog cannot be read and lib.sh holds from the last list — never «ships none»."""
    out = []
    for h in HOOKS:
        try:
            if stat.S_ISREG(os.stat(hooks / h).st_mode):
                out.append(h)
        except (FileNotFoundError, NotADirectoryError):
            continue
    return out


def dependents(own, graph: dict) -> list:
    """Every service outside `own` that needs one of them, directly or through another (graph: service → needs)."""
    found, todo = set(), set(own)
    while todo:
        s = todo.pop()
        for d, n in graph.items():
            if s in n and d not in own and d not in found:
                found.add(d)
                todo.add(d)
    return sorted(found)


def main(argv: list) -> int:
    if argv[:1] != ["apps"]:
        print("usage: when_idle.py apps", file=sys.stderr)
        return 2
    try:
        import yaml
        import reconcile as R
        cat, state = R.load_catalog(), R.load_state()
        order, _diags = R.resolve(cat, state)
        graph = {}
        for aid in order:
            m = cat.get(aid) or {}
            if m.get("compose"):
                doc = yaml.safe_load((m["_dir"] / m["compose"]).read_text(encoding="utf-8")) or {}
                for name, svc in (doc.get("services") or {}).items():
                    graph[name] = needs(svc)
    except Exception as e:                       # noqa: BLE001 — any failure is «cannot say», never «nothing to hold»
        print(f"when_idle: the catalog cannot be read ({e})", file=sys.stderr)
        return 1
    lines = []
    try:
        for aid in order:
            m = cat.get(aid) or {}
            if m.get("recreate") != "when-idle":
                continue
            tpl = m.get("instance_of") or ""
            home = (cat.get(tpl) or {}).get("_dir") if tpl else m.get("_dir")
            if not home:
                continue
            own = R.compose_services(m)
            hooks = pathlib.Path(home) / "hooks"
            lines.append("\t".join([aid, " ".join(own), " ".join(dependents(own, graph)) or "-",
                                    os.path.relpath(hooks, R.REPO), tpl or "-", str(m.get("instance_key") or "-"),
                                    ",".join(ships(hooks)) or "-"]))
    except OSError as e:
        print(f"when_idle: the hooks cannot be read ({e})", file=sys.stderr)
        return 1
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
