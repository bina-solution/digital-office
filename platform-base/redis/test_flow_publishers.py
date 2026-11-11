#!/usr/bin/env python3
"""test_flow_publishers.py — every app that tells the office what it did does it through the ONE publisher,
and «כל מקביל» hears all of them (DGO-1402).

    python3 platform-base/redis/test_flow_publishers.py      (G72 runs it; reads the tree, no stack)

WHAT IT HOLDS, read off the files:
  * DGO-1402's five — sites, meet (its recordings), drive, connections, notifications — each have the fourth
    channel whole: `hooks/flow` (the platform's reader for its stream), the redis password in its compose,
    platform-base/redis/flowpub.py mounted read-only at /opt/dgo, `use: kv`, and code that emits through it
    under ITS OWN id;
  * every OTHER app with a `hooks/flow` publishes the same way, unless it is one of the copies written before
    the one publisher existed (KNOWN_COPIES — moving them onto it is a follow-up of its own, named in DGO-1402's
    report). A NEW copy of the contract (an XADD to `dgo:flow:` anywhere but flowpub.py) fails: a contract
    written twice drifts;
  * «כל מקביל» reads every `dgo:flow:*` stream by default: the `flow` source is in its default lanes, its loop
    is started, and the module that turns an event into a span is in its image.
On the tree before DGO-1402 this fails on every line: there was no flowpub.py, none of the five had a flow
channel, and «כל מקביל» read no stream at all.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAILS: list[str] = []

#: DGO-1402: the apps «כל מקביל» did not hear (DGO-1727's check, 2026-11-09)
REQUIRED = {"sites": "apps/sites", "meet": "apps/meet", "drive": "apps/drive",
            "connections": "platform-base/connections", "notifications": "platform-base/notifications"}
#: their own publisher, written before flowpub.py existed — allowed to stay until they move onto it. EMPTY since
#: telegram (app.py, relay/desk.py) and domain-internic moved onto it (DGO-1402's follow-up): a new name here is
#: a step back, and needs its reason beside it
KNOWN_COPIES: set[str] = {
    # hp-dgo's two, written while this contract was closed on mac-dgo, and taken by the release that carried both
    # lines (DGO-969, 2026-11-10). They move onto flowpub under DGO-1756, and leave this set then.
    "apps/esign/clients.py",       # DGO-1631: an envelope's events
    "apps/newsflow/main.py",       # DGO-1348/1350: a pass's events
}
#: the reader, not a publisher
READERS = {"platform-base/redis"}

PW_RE = re.compile(r"^\s*-?\s*REDIS_PASSWORD\s*[:=]\s*\$\{REDIS_PASSWORD", re.M)
COPY_RE = re.compile(r"""(?:xadd\s*\(|["']XADD["'])""", re.I)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def code_files(app_dir: Path) -> list[Path]:
    return [p for p in app_dir.rglob("*.py")
            if "__pycache__" not in p.parts and not p.name.startswith("test_") and "node_modules" not in p.parts]


def publishes_through_flowpub(app_dir: Path, app_id: str) -> bool:
    """`flowpub.emit("<id>", …)` — or through a module constant that holds the id (`APP = "<id>"` …
    `flowpub.emit(APP, …)`), the shape apps/documents writes."""
    lit = re.compile(r"\b_?flowpub\.(?:emit|span)\(\s*[\"']" + re.escape(app_id) + r"[\"']")
    via = re.compile(r"\b_?flowpub\.(?:emit|span)\(\s*([A-Z_][A-Z0-9_]*)\s*,")
    for p in code_files(app_dir):
        text = read(p)
        if lit.search(text):
            return True
        for const in set(via.findall(text)):
            # `APP = "<id>"`, or the first name of a tuple assignment (`SERVICE, INTERFACE = "<id>", "…"`)
            if re.search(r"^" + re.escape(const) + r"\s*(?:,\s*\w+\s*)*=\s*[\"']" + re.escape(app_id) + r"[\"']",
                         text, re.M):
                return True
    return False


def mounts_flowpub(app_dir: Path) -> tuple[bool, str]:
    """The compose file mounts THE platform file — its source resolved against the compose file's own directory
    (compose `include:` resolves each file there), not merely a path that ends in flowpub.py."""
    compose = app_dir / "docker-compose.yml"
    for src in re.findall(r"^\s*-?\s*['\"]?([^\s'\":]*flowpub\.py):/opt/dgo/flowpub\.py:ro\b", read(compose), re.M):
        if (compose.parent / src).resolve() == (REPO / "platform-base" / "redis" / "flowpub.py").resolve():
            return True, ""
        return False, f"{compose.relative_to(REPO)} mounts `{src}`, which is not platform-base/redis/flowpub.py from there"
    return False, f"{compose.relative_to(REPO)} has no `…/redis/flowpub.py:/opt/dgo/flowpub.py:ro`"


def uses_kv(app_dir: Path) -> bool:
    try:
        doc = json.loads(read(app_dir / "app.json"))
    except ValueError:
        return False
    return any(u.get("capability") == "kv" for u in doc.get("use") or [] if isinstance(u, dict))


def flow_hook(app_dir: Path, app_id: str) -> tuple[bool, str]:
    h = app_dir / "hooks" / "flow"
    if not h.is_file():
        return False, "no hooks/flow"
    body = read(h)
    if not re.search(r"redis/hooks/flow\"?\s+" + re.escape(app_id) + r"\b", body):
        return False, f"hooks/flow does not exec the platform's reader for `{app_id}`"
    if not os.access(h, os.X_OK):
        return False, "hooks/flow is not executable"
    return True, ""


def main() -> int:
    pub = REPO / "platform-base" / "redis" / "flowpub.py"
    check("the one publisher exists: platform-base/redis/flowpub.py", pub.is_file())
    src = read(pub)
    check("…it caps the stream and renews its TTL in one transaction",
          '"MULTI"' in src and '"XADD"' in src and '"MAXLEN", "~"' in src and '"EXPIRE"' in src and '"EXEC"' in src)

    # the five of DGO-1402, each with the fourth channel whole
    for app_id, rel in REQUIRED.items():
        d = REPO / rel
        compose = read(d / "docker-compose.yml")
        ok, why = flow_hook(d, app_id)
        check(f"{app_id}: hooks/flow reads dgo:flow:{app_id}", ok, why)
        mounted, why_not = mounts_flowpub(d)
        check(f"{app_id}: the publisher is mounted read-only from the platform", mounted, why_not)
        check(f"{app_id}: the redis password reaches it", bool(PW_RE.search(compose)), f"{rel}/docker-compose.yml")
        check(f"{app_id}: declares use kv (the stream rides the office redis)", uses_kv(d), f"{rel}/app.json")
        check(f"{app_id}: emits through flowpub under its own id", publishes_through_flowpub(d, app_id),
              f"no `flowpub.emit(\"{app_id}\"…` / `flowpub.span(\"{app_id}\"…` in {rel}")

    # every other app that offers a flow publishes the same way — or is a known copy from before
    for top in ("apps", "platform-base"):
        for d in sorted((REPO / top).iterdir()):
            rel = f"{top}/{d.name}"
            if not (d / "hooks" / "flow").is_file() or rel in READERS or d.name in REQUIRED:
                continue
            own = publishes_through_flowpub(d, d.name)
            copy = any(str(p.relative_to(REPO)) in KNOWN_COPIES for p in code_files(d))
            check(f"{d.name}: offers a flow and publishes it (flowpub, or a known older copy)", own or copy,
                  f"{rel}/hooks/flow exists but nothing in {rel} emits through flowpub")
            if own:
                # code that emits through flowpub publishes NOTHING where the file is not mounted and the password
                # does not reach it — held for every publisher, not only DGO-1402's five (the second reader, DGO-1732)
                mounted, why_not = mounts_flowpub(d)
                check(f"{d.name}: the publisher is mounted read-only from the platform", mounted, why_not)
                check(f"{d.name}: the redis password reaches it", bool(PW_RE.search(read(d / "docker-compose.yml"))),
                      f"{rel}/docker-compose.yml")

    # no NEW copy of the contract
    copies = []
    for top in ("apps", "platform-base"):
        for p in (REPO / top).rglob("*.py"):
            if "__pycache__" in p.parts or p.name.startswith("test_") or p == pub:
                continue
            rel = str(p.relative_to(REPO))
            text = read(p)
            if "dgo:flow:" in text and COPY_RE.search(text) and rel not in KNOWN_COPIES:
                copies.append(rel)
    check("no app writes dgo:flow:* with a publisher of its own (one contract, one copy)", not copies,
          "XADD to dgo:flow: outside flowpub.py: " + ", ".join(copies))

    # «כל מקביל» hears every stream by default
    ac = REPO / "apps" / "any-concurrency"
    app_py, docker = read(ac / "app.py"), read(ac / "Dockerfile")
    check("«כל מקביל» turns events into spans (flow_source.py)", (ac / "flow_source.py").is_file()
          and "from flow_source import" in app_py)
    check("…its `flow` lane is a DEFAULT lane", bool(re.search(r"_BASE_SOURCES\.append\(FLOW_SRC\)", app_py)))
    check("…the loop that reads dgo:flow:* is started", "flow_loop(" in app_py and "create_task(" in app_py
          and re.search(r"flow_loop\(app\.state\.redis", app_py) is not None)
    check("…and the module is in its image", bool(re.search(r"^COPY [^\n]*\bflow_source\.py\b", docker, re.M)))

    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
