#!/usr/bin/env python3
"""make-runtime-compose — emit a compose file that RUNS images instead of building them.

    python3 packaging/make-runtime-compose.py --out .generated/compose.runtime.yml

WHY THIS EXISTS

The first real install on a foreign machine got all 26 images loaded, then died with:

    unable to prepare context: path "/opt/binaos/apps/mail/mailapi" not found

12 of this stack's 16 first-party services declare `build:` and no `image:`. Compose treats such a
service as something to BUILD, so on a customer's machine it went looking for source trees that
were deliberately never shipped — the images were already in the engine, sitting unused.

This is the same root cause as the bundle that silently omitted 12 of 29 images: a service with
only `build:` has no image name anywhere in the YAML, so anything reading the file rather than
asking compose cannot see it. There the fix was `compose config --images`; here it is to write the
name down.

WHAT IT PRODUCES

Every service gets an explicit `image:` — the exact tag compose would have built, which is the tag
`docker load` restored — and `build:` is removed entirely. The result is a compose file that can
only run, never build, which is the correct shape for a machine with no source and no registry.

Anything else (networks, volumes, env, labels, depends_on, healthchecks) is passed through
untouched: this changes how services are OBTAINED, not how they behave.
"""
import argparse
import json
import pathlib
import subprocess
import sys

try:
    import yaml
except ImportError:
    print("make-runtime-compose: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".generated/compose.runtime.yml", type=pathlib.Path)
    # MUST match the project the images were tagged under, because `docker load` restores the tag
    # verbatim. The bundle is built from `compose config --images` on this repo, where the project
    # is the directory name — deployment-hacohen. Naming it anything else here produces a compose
    # file referencing images that were never loaded, and every first-party service fails to start
    # with "no such image" on the customer's machine.
    ap.add_argument("--project", default="deployment-hacohen",
                    help="compose project name; decides the <project>-<service> fallback tag")
    args = ap.parse_args()

    # Ask compose, do not parse the YAML ourselves. It resolves includes, interpolation, overrides
    # and the build->image naming — all the things a hand-rolled reader gets subtly wrong.
    #
    # Via scripts/dc, which is the ONE way this stack invokes compose. Two bugs lived in the three
    # lines this replaces, in the tool that produces the file the SHIPPED ARTIFACT boots from:
    #
    #   1. It hardcoded the -f list, duplicating reconcile.compose_files(). connections.override.yml
    #      is emitted only when some app declares a broker, so on an estate without one this passed
    #      `-f` a file that does not exist and compose failed outright; and any file the compiler
    #      starts emitting later would silently be missing from the bundle.
    #   2. It called bare `docker compose` — a plugin SEARCH that resolves to Docker Desktop's
    #      binary wherever Desktop is installed. That is precisely what gate G7 exists to forbid,
    #      and this file was bypassing it.
    proc = subprocess.run(["bash", "scripts/dc", "config", "--format", "json"],
                          cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        print("make-runtime-compose: compose config failed:\n" + proc.stderr[-1500:], file=sys.stderr)
        return 1

    doc = json.loads(proc.stdout)
    services = doc.get("services") or {}

    stripped, named = 0, 0
    for name, spec in services.items():
        if "build" in spec:
            del spec["build"]
            stripped += 1
        if not spec.get("image"):
            # Exactly what compose names a built image: <project>-<service>. `docker load` restored
            # these tags, so naming them here is what lets the service start without a build.
            spec["image"] = f"{args.project}-{name}"
            named += 1

    # RELATIVISE BIND MOUNTS. `compose config` absolutises every relative bind source against the
    # machine that generated the file. Generated on Windows that yields
    #   C:\Users\...\apps\indox\storage:/app/.storage
    # which Docker on the customer's Linux box rejects outright as an invalid volume specification;
    # generated on the build server it yields /home/<builder>/... , a path that simply does not
    # exist there. Either way the artifact is bound to the machine that built it, which is the one
    # thing a distributable installer cannot be.
    #
    # Rewriting them back to `./`-relative makes the file portable: compose resolves them against
    # --project-directory, which the unit points at the install prefix.
    repo_win = str(REPO).replace("/", "\\")
    repo_posix = REPO.as_posix()
    rewritten = 0

    def relativise(src: str) -> str:
        nonlocal rewritten
        norm = src.replace("\\", "/")
        for root in (repo_posix, repo_win.replace("\\", "/")):
            if norm.lower().startswith(root.lower() + "/"):
                rewritten += 1
                return "./" + norm[len(root) + 1:]
            if norm.lower() == root.lower():
                rewritten += 1
                return "."
        return src

    for spec in services.values():
        vols = spec.get("volumes") or []
        for v in vols:
            if isinstance(v, dict) and v.get("type") == "bind" and v.get("source"):
                v["source"] = relativise(v["source"])
            elif isinstance(v, str) and ":" in v:
                head, _, rest = v.partition(":")
                if "/" in head or "\\" in head:
                    spec["volumes"][spec["volumes"].index(v)] = relativise(head) + ":" + rest

    # A surviving absolute host path means the artifact only works on the build machine.
    # Genuine HOST paths stay absolute and are fine: the machine app mounts / for host metrics,
    # several services mount the docker socket. What is NOT fine is a path under the BUILD tree,
    # which exists only on the machine that produced the artifact.
    HOST_OK = ("/", "/var/run", "/run", "/proc", "/sys", "/etc", "/dev")
    leftovers = []
    for name, spec in services.items():
        for v in (spec.get("volumes") or []):
            src = v.get("source") if isinstance(v, dict) else (v.split(":")[0] if isinstance(v, str) else None)
            if not src or not isinstance(src, str):
                continue
            if src.startswith("/") and src not in HOST_OK and not any(
                    src.startswith(h + "/") for h in HOST_OK if h != "/"):
                leftovers.append(f"{name}: {src}")
            if len(src) > 2 and src[1] == ":":       # C:\...
                leftovers.append(f"{name}: {src}")

    # `name:` in the output pins the project, so the customer's containers land in one project
    # regardless of the directory the unit happens to run from.
    doc["name"] = args.project
    for key in ("include",):          # already resolved by `config`; keeping it re-triggers includes
        doc.pop(key, None)

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, sort_keys=False, width=4096, allow_unicode=True),
                   encoding="utf-8", newline="\n")

    if leftovers:
        print("make-runtime-compose: FAIL — absolute host paths would bind this artifact to the "
              "build machine:", file=sys.stderr)
        for l in leftovers[:10]:
            print(f"    {l}", file=sys.stderr)
        return 1

    # A build key surviving here means the customer's install tries to compile something.
    left = [n for n, s in services.items() if "build" in s]
    if left:
        print(f"make-runtime-compose: FAIL — build: survived on {left}", file=sys.stderr)
        return 1

    print(f"{args.out}: {len(services)} service(s), {stripped} build section(s) removed, "
          f"{named} image name(s) written, {rewritten} bind path(s) relativised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
