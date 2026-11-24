#!/usr/bin/env python3
"""test_image_refresh.py — after an `up`, a container runs the image its tag names now (DGO-2123).

    python3 scripts/test_image_refresh.py        (G72 runs it; bash and python3 only)

On vps1, 2026-11-20 11:12Z, `./scripts/dc up -d --build --no-deps autoheal|apitools` printed «Built» and then «Running»:
the containers kept their old images while :latest moved on, and only --force-recreate put them on the new ones
(issues/dc-up-build-builds-a-new-image-and-leaves-the-container-on-the-old-one.yaml). dcx now runs image_refresh after
every successful `up`. This lifts image_refresh and _image_stale out of scripts/lib.sh as they are; docker and compose
are played from a state file (the containers, the images their tags name, the declared services), and every compose
call is logged, so a decision is read from what was RECREATED. On lib.sh before DGO-2123 there is no such function and
every case fails.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FAILS: list[str] = []


def function(src: str, name: str) -> str:
    m = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}\n", src, re.M | re.S)
    return m.group(0) if m else ""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


SRC = (REPO / "scripts" / "lib.sh").read_text(encoding="utf-8")
FUNCS = function(SRC, "image_refresh") + function(SRC, "_image_stale")

# docker and compose, from the state file: `docker image ls`, `docker inspect`, and compose's `ps -q`,
# `config --services` and `up` — an `up --force-recreate` puts a service's containers on the image its tag names now
# (unless the state says the engine keeps them: the case where even a forced recreate did not take)
WORLD = r'''
import json, os, sys
state_path, log_path = os.environ["STATE"], os.environ["LOG"]
st = json.load(open(state_path))
args = sys.argv[1:]

def norm(ref):
    for p in ("docker.io/library/", "docker.io/"):
        if ref.startswith(p):
            ref = ref[len(p):]
            break
    return ref if ":" in ref.rsplit("/", 1)[-1] else ref + ":latest"

if args[0] == "docker":
    if args[1:3] == ["image", "ls"]:
        # as docker writes it: the full id only with --no-trunc (else 12 hex, which never equals a container's Image)
        full = "--no-trunc" in args
        for ref, iid in st["images"].items():
            print(ref, iid if full else iid.replace("sha256:", "")[:12])
    elif args[1] == "inspect":
        rows = [{"Id": c["id"], "Image": c["image"], "State": {"Running": c.get("running", True)},
                 "Config": {"Image": c["ref"], "Labels": {"com.docker.compose.service": c["service"]}}}
                for c in st["containers"] if c["id"] in args[2:]]
        print(json.dumps(rows))
    sys.exit(0)
# compose
with open(log_path, "a") as log:
    log.write(" ".join(args[1:]) + "\n")
if args[1:3] == ["ps", "-q"]:
    print("\n".join(c["id"] for c in st["containers"]))
elif args[1:3] == ["config", "--services"]:
    print("\n".join(st["declared"]))
elif args[1] == "up" and "--force-recreate" in args:
    named = [a for a in args[2:] if not a.startswith("-")]
    for c in st["containers"]:
        if c["service"] in named and not st.get("engine_keeps"):
            c["image"] = st["images"].get(norm(c["ref"]), c["image"])
    json.dump(st, open(state_path, "w"))
'''

HARNESS = r'''
set -uo pipefail
cr="" cy="" c0=""
say() { echo "[bbox] $*"; }
bbox_self_service() { echo "${SELF:-}"; }
_dcx_run() { python3 "$WORLD" compose "$@"; }
'''


def run(state: dict, *up_args: str, self_service: str = "", compose_self: str = "", in_container: bool = False,
        mode: str = "set -uo pipefail", held: tuple = ()) -> tuple[str, list[str], dict]:
    with tempfile.TemporaryDirectory() as d:
        dpath = Path(d)
        # the office's checkout, as lib.sh's REPO_ROOT: its data/.held notes (DGO-2129) are the case's own
        (dpath / "repo" / "data" / ".held").mkdir(parents=True)
        for s in held:
            (dpath / "repo" / "data" / ".held" / s).write_text("idle\tbusy\t-\tbuild\t-\n")
        (dpath / "world.py").write_text(WORLD)
        (dpath / "state.json").write_text(json.dumps(state))
        bindir = dpath / "bin"
        bindir.mkdir()
        (bindir / "docker").write_text('#!/bin/sh\nexec python3 "$WORLD" docker "$@"\n')
        os.chmod(bindir / "docker", 0o755)
        # «this runs in a container» is the case's own, never the host's: the CI runner IS a container, and a test that
        # read the real /.dockerenv passed on the Mac and failed there (batch 95, G72)
        dockerenv = dpath / "dockerenv"
        if in_container:
            dockerenv.write_text("")
        env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}", WORLD=str(dpath / "world.py"),
                   STATE=str(dpath / "state.json"), LOG=str(dpath / "log"), SELF=self_service,
                   BBOX_DOCKERENV=str(dockerenv), REPO_ROOT=str(dpath / "repo"))
        script = (HARNESS.replace("set -uo pipefail", mode) + f'COMPOSE_SELF="{compose_self}"\n' + FUNCS
                  + '\nimage_refresh "$@"\necho "rc=$?"\n')
        r = subprocess.run(["bash", "-c", script, "bash", *up_args], capture_output=True, text=True, env=env, timeout=60)
        log = (dpath / "log").read_text().splitlines() if (dpath / "log").exists() else []
        return r.stdout + r.stderr, log, json.loads((dpath / "state.json").read_text())


def recreated(log: list[str]) -> list[str]:
    return [ln for ln in log if "--force-recreate" in ln]


def world(*containers, images=None, declared=None, **extra) -> dict:
    cs = [dict(zip(("id", "service", "image", "ref"), c)) for c in containers]
    return dict(containers=cs, images=images or {}, declared=declared or sorted({c["service"] for c in cs}), **extra)


# vps1's autoheal of 2026-11-20: built under :latest (new), the container on the image before (old)
AUTOHEAL = ("c1", "autoheal", "sha256:old", "digital-office-autoheal")
APITOOLS = ("c2", "apitools", "sha256:same", "digital-office-apitools")
IMAGES = {"digital-office-autoheal:latest": "sha256:new", "digital-office-apitools:latest": "sha256:same"}


def main() -> int:
    if not FUNCS.count("() {") == 2:
        check("image_refresh and _image_stale are in scripts/lib.sh", False, "not found")
        return 1
    out, log, st = run(world(AUTOHEAL, APITOOLS, images=IMAGES), "up", "-d", "--build", "--no-deps", "autoheal")
    check("a container left on the image before its tag moved is recreated, alone",
          recreated(log) == ["up -d --no-deps --force-recreate autoheal"], f"{log}\n{out}")
    check("…and runs the image its tag names now", st["containers"][0]["image"] == "sha256:new", json.dumps(st))
    check("…and it is said, with why", "recreating autoheal — its image was rebuilt under the same tag" in out, out)
    check("…and nothing is left to say in red", "still running an image" not in out and "rc=0" in out, out)

    out, log, _ = run(world(APITOOLS, images=IMAGES), "up", "-d")
    check("a container on its tag's image: nothing recreated, nothing said", recreated(log) == [] and "[bbox]" not in out,
          f"{log}\n{out}")

    out, log, _ = run(world(AUTOHEAL, APITOOLS, images=IMAGES), "up", "-d")
    check("a bare `up` names every service: the stale one is recreated", recreated(log) == ["up -d --no-deps --force-recreate autoheal"],
          f"{log}\n{out}")

    out, log, _ = run(world(AUTOHEAL, APITOOLS, images=IMAGES), "up", "-d", "--no-deps", "apitools")
    check("an `up` of another service never recreates this one (filemount_refresh's bound)", recreated(log) == [],
          f"{log}\n{out}")

    gone = world(("c3", "chat", "sha256:old", "digital-office-chat"),
                 images={"digital-office-chat:pre-vps1dgo-20261101T114645Z": "sha256:old"})
    out, log, _ = run(gone, "up", "-d")
    check("a tag that no longer resolves is no reason (vps1's chat-staging): nothing recreated", recreated(log) == [],
          f"{log}\n{out}")

    pinned = world(("c4", "db", "sha256:old", "postgres@sha256:abc"), ("c5", "x", "sha256:old", "sha256:old"),
                   images={"postgres:latest": "sha256:new"})
    out, log, _ = run(pinned, "up", "-d")
    check("a ref pinned to a digest or an image id is its own image", recreated(log) == [], f"{log}\n{out}")

    hub = world(("c6", "site", "sha256:old", "docker.io/library/nginx:1.27-alpine"),
                images={"nginx:1.27-alpine": "sha256:new"})
    out, log, _ = run(hub, "up", "-d")
    check("Docker Hub's long name is read as `docker image ls` writes it", recreated(log) == ["up -d --no-deps --force-recreate site"],
          f"{log}\n{out}")

    orphan = world(AUTOHEAL, images=IMAGES, declared=["apitools"])
    out, log, _ = run(orphan, "up", "-d")
    check("a container the config no longer declares is not recreated (`up <it>` would fail them all)",
          recreated(log) == [], f"{log}\n{out}")

    out, log, _ = run(world(AUTOHEAL, images=IMAGES), "up", "-d", self_service="autoheal")
    check("never the container this runs in", recreated(log) == [], f"{log}\n{out}")

    stopped = world(AUTOHEAL, images=IMAGES)
    stopped["containers"][0]["running"] = False
    out, log, _ = run(stopped, "up", "-d")
    check("a stopped container is not this pass's", recreated(log) == [], f"{log}\n{out}")

    out, log, _ = run(world(AUTOHEAL, images=IMAGES, engine_keeps=True), "up", "-d")
    check("still on the image before after the recreate: said in red, and the `up` stays a success",
          "autoheal still running an image that is not the one its tag names" in out and "rc=0" in out, out)

    # the second reader of image_refresh
    port = world(("c7", "reg", "sha256:old", "localhost:5000/x"), images={"localhost:5000/x:latest": "sha256:new"})
    out, log, _ = run(port, "up", "-d")
    check("a registry with a port (localhost:5000/x): its implicit :latest read after the last slash",
          recreated(log) == ["up -d --no-deps --force-recreate reg"], f"{log}\n{out}")

    dangling = world(AUTOHEAL, APITOOLS, images=dict(IMAGES, **{"<none>:<none>": "sha256:dangling",
                                                                "digital-office-apitools:<none>": "sha256:x"}))
    out, log, _ = run(dangling, "up", "-d")
    check("dangling <none> rows change nothing", recreated(log) == ["up -d --no-deps --force-recreate autoheal"],
          f"{log}\n{out}")

    scaled = world(AUTOHEAL, ("c1b", "autoheal", "sha256:old", "digital-office-autoheal"), images=IMAGES)
    out, log, st = run(scaled, "up", "-d")
    check("a scaled service: recreated once, every container of it back on its tag's image",
          recreated(log) == ["up -d --no-deps --force-recreate autoheal"]
          and all(c["image"] == "sha256:new" for c in st["containers"]), f"{log}\n{out}")

    out, log, _ = run(world(AUTOHEAL, images=IMAGES), "up", "-d", compose_self="autoheal")
    check("the self guard's own answer (COMPOSE_SELF) is never recreated, whatever docker says", recreated(log) == [],
          f"{log}\n{out}")

    # inside a container: one whose own service cannot be named recreates nothing (a recreate from inside it would stop
    # the very command), and says so; one whose service is named recreates the others as anywhere else
    out, log, _ = run(world(AUTOHEAL, APITOOLS, images=IMAGES), "up", "-d", in_container=True)
    check("in a container whose own service cannot be named: nothing recreated, and said",
          recreated(log) == [] and "not recreating autoheal" in out and "rc=0" in out, f"{log}\n{out}")
    out, log, _ = run(world(AUTOHEAL, APITOOLS, images=IMAGES), "up", "-d", in_container=True, compose_self="apitools")
    check("in a container whose own service is named: the stale others recreated",
          recreated(log) == ["up -d --no-deps --force-recreate autoheal"], f"{log}\n{out}")

    # a still-stale service that is not recreated (this one's own) sorting LAST: the loop that names what is left used
    # to end non-zero there, and under `set -e` killed the caller — bbox apply, bbox rollback — right after the recreate
    last = world(("c8", "aaa", "sha256:old", "digital-office-aaa"), ("c9", "zzz", "sha256:old", "digital-office-zzz"),
                 images={"digital-office-aaa:latest": "sha256:new", "digital-office-zzz:latest": "sha256:new"})
    out, log, _ = run(last, "up", "-d", self_service="zzz", mode="set -euo pipefail")
    check("under `set -e`, a stale service left out sorting last: the caller lives on", "rc=0" in out
          and recreated(log) == ["up -d --no-deps --force-recreate aaa"], f"{log}\n{out}")

    # DGO-2129's «when-idle»: a service HELD for a quiet cycle (data/.held/<service>) is never recreated here, even when
    # a take built its image before the `up` and it reads stale — batch 105's merged dcx hands this every service the
    # command was asked, the held ones included (the review of 182377a6e). The cycle that brings it up refreshes it.
    out, log, st = run(world(AUTOHEAL, images=IMAGES), "up", "-d", held=("autoheal",))
    check("a held «when-idle» service is not recreated under its people, and it is said",
          recreated(log) == [] and "not recreating autoheal — held for a quiet cycle" in out
          and st["containers"][0]["image"] == "sha256:old", f"{log}\n{out}")
    out, log, _ = run(last, "up", "-d", held=("zzz",), mode="set -euo pipefail")
    check("…and the stale ones not held are recreated beside it, under `set -e` too",
          recreated(log) == ["up -d --no-deps --force-recreate aaa"] and "rc=0" in out
          and "not recreating zzz — held for a quiet cycle" in out, f"{log}\n{out}")

    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
