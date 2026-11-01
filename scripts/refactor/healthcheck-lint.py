#!/usr/bin/env python3
"""healthcheck-lint — gate G18: a healthcheck must probe the app, not itself.

`chat` ran `curl -f http://localhost:3000` against a `node:22-slim` image. There is
no curl in that image, so every probe died with

    OCI runtime exec failed: exec: "curl": executable file not found in $PATH

and the container reported **unhealthy forever** while the admin panel served 200s perfectly well.
Nothing failed loudly. `bbox run` waited out its whole 300s health window, dependents that wait on
it were held back, and the app-management card showed a red dot for a healthy app — the probe was
reporting on the probe.

That is worth a gate for two reasons. It is silent: the only symptom is a status nobody can act on.
And it is invisible on a warm machine — the failure needs a fresh image to show up, which is the
same blind spot the fresh-machine lane exists for.

What this checks, and the deliberate limit: only services this repo BUILDS, because only for those
can the Dockerfile answer "is the binary there". A third-party image's contents are not knowable
from the tree; those are covered at runtime by scripts/healthcheck-audit.sh against a live stack.

Exit 1 if any first-party healthcheck names a binary its own Dockerfile never provides.
"""
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

# Binaries a healthcheck commonly shells out to. `sh`/`test`/`[` are in every base image and are
# not worth checking; these are the ones that are routinely absent from slim and alpine bases.
CHECKED = ("curl", "wget", "nc", "netcat", "psql", "pg_isready", "redis-cli", "mysqladmin")

# Interpreters that ship WITH the base image whenever the image is that language's official image.
# `python:3.12-slim` has python; `node:22-slim` has node. Treating these as present avoids flagging
# the correct fix for this very bug.
LANG_BINS = {"python": ("python", "python3"), "node": ("node",), "ruby": ("ruby",),
             "golang": ("go",), "php": ("php",), "openjdk": ("java",), "eclipse-temurin": ("java",)}


def compose_files():
    return sorted(list((REPO / "apps").glob("*/docker-compose.yml"))
                  + list((REPO / "platform-base").glob("*/docker-compose.yml")))


def test_tokens(hc):
    """The words of a healthcheck test, whatever form it was written in."""
    t = (hc or {}).get("test")
    if not t:
        return []
    if isinstance(t, str):
        return t.split()
    parts = []
    for x in t:
        if x in ("CMD", "CMD-SHELL", "NONE"):
            continue
        parts += str(x).split()
    return parts


def dockerfile_for(app_dir, svc):
    b = svc.get("build")
    if not b:
        return None
    if isinstance(b, str):
        return (app_dir / b / "Dockerfile")
    ctx = app_dir / b.get("context", ".")
    return ctx / b.get("dockerfile", "Dockerfile")


# Bases whose contents are knowable from the outside: the official language images, the distro
# bases, and the datastore images. Anything else is a vendor image this tree cannot inspect.
KNOWN_BASES = {"python", "node", "ruby", "golang", "php", "openjdk", "eclipse-temurin",
               "debian", "ubuntu", "alpine", "busybox", "postgres", "redis", "nginx", "caddy"}


def known_base(df_text):
    """Can we reason about what the FINAL stage's base image contains?"""
    froms = re.findall(r"^\s*FROM\s+(\S+)", normalise(df_text), re.M | re.I)
    if not froms:
        return False
    stages = {m.group(1).lower()
              for m in re.finditer(r"^\s*FROM\s+\S+\s+AS\s+(\S+)", normalise(df_text),
                                   re.M | re.I)}
    base = froms[-1].split("@")[0].split(":")[0].split("/")[-1].lower()
    return base in KNOWN_BASES or base in stages


def normalise(df_text):
    """One logical line per instruction, comments gone.

    Package installs in this repo are written as multi-line RUNs with backslash continuations and
    a `# why` comment beside half the packages. Matching against the raw text made the linter
    report apitools — whose Dockerfile installs curl six lines below the `apt-get install` — as
    missing it. A linter with false positives is one people learn to skip, so the join happens
    before any matching.
    """
    text = re.sub(r"\\\s*\n", " ", df_text)          # fold continuations
    return "\n".join(re.sub(r"\s+#.*$", "", ln) for ln in text.split("\n"))


def provides(df_text, binary):
    """Does this Dockerfile put `binary` in the image?"""
    df_text = normalise(df_text)
    # installed explicitly
    if re.search(rf"(apt-get|apt|apk|dnf|yum|microdnf)\s+(install|add)[^\n]*\b{re.escape(binary)}\b",
                 df_text):
        return True
    # busybox applets. Alpine's busybox provides wget and nc, so an alpine-based image has them
    # without installing anything — n8n's official image probes itself with wget on exactly this
    # basis, and flagging it would be wrong.
    if binary in ("wget", "nc", "netcat") and re.search(r"^\s*FROM\s+\S*alpine", df_text,
                                                        re.M | re.I):
        return True
    # copied or built in
    if re.search(rf"COPY[^\n]*\b{re.escape(binary)}\b", df_text):
        return True
    # shipped by the base image because the base IS that language's official image
    for m in re.finditer(r"^\s*FROM\s+(\S+)", df_text, re.M | re.I):
        base = m.group(1).split("@")[0].split(":")[0].split("/")[-1].lower()
        if binary in LANG_BINS.get(base, ()):
            return True
        # a database image ships its own client tools
        if base in ("postgres", "supabase-postgres") and binary in ("psql", "pg_isready"):
            return True
        if base == "redis" and binary == "redis-cli":
            return True
    return False


def main():
    bad, checked = [], 0
    for f in compose_files():
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"  ! {f.relative_to(REPO)}: {e}")
            continue
        for name, svc in (doc.get("services") or {}).items():
            if not isinstance(svc, dict):
                continue
            toks = test_tokens(svc.get("healthcheck"))
            wanted = next((b for b in CHECKED for t in toks
                           if t == b or t.endswith("/" + b)), None)
            if not wanted:
                continue
            df = dockerfile_for(f.parent, svc)
            if df is None or not df.exists():
                continue                       # third-party image: runtime audit's job, not ours
            text = df.read_text(encoding="utf-8", errors="replace")
            if not known_base(text):
                # e.g. `FROM n8nio/n8n:${N8N_VERSION}` — a vendor image whose contents this tree
                # cannot see. n8n really does have wget (busybox), and flagging it would be a false
                # positive; guessing in either direction is worse than declining to answer, so
                # unknown bases are left to the runtime audit.
                continue
            checked += 1
            if not provides(text, wanted):
                bad.append((f.relative_to(REPO).as_posix(), name, wanted,
                            df.relative_to(REPO).as_posix()))

    if bad:
        print("HEALTHCHECKS THAT CAN NEVER PASS")
        print("-" * 74)
        for path, svc, binary, df in bad:
            print(f"  {svc:28} needs `{binary}`, absent from {df}")
            print(f"  {'':28} declared in {path}")
        print("-" * 74)
        print("  -> install it in the Dockerfile, or probe with a binary the image already has\n"
              "     (an official language image always has its own interpreter).")
        print(f"\nG18 FAIL — {len(bad)} healthcheck(s) probe a binary that is not in the image.")
        return 1

    print(f"G18 PASS — every first-party healthcheck uses a binary its image provides "
          f"({checked} checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
