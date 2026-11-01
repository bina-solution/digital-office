#!/usr/bin/env python3
"""compose-pin-lint — gate G74: everyone who runs docker compose runs the SAME docker compose.

    python3 scripts/refactor/compose-pin-lint.py
    python3 scripts/refactor/compose-pin-lint.py --self-test

WHY THIS EXISTS. Compose is run from more than one place in an office: the host (`bbox`), and every
container that brings other containers up — the control plane for an install from the apps screen,
the agent's shell for `./bbox run`. Each carries its own copy of the plugin, and a container's
identity is the hash of what compose made of its service: two VERSIONS of compose normalise the same
file differently (a short-syntax bind is `create_host_path: true` to one and absent to the other),
so the same service is one container to the apps screen and another to `bbox run`, and each
re-creates what the other made.

Measured 2026-10-06. MacBook: the agent's image 2.40.3, the control plane 5.5.1 (its Dockerfile
said `docker-compose-plugin`, unpinned, under a comment promising "the same package the host
gets") — 18 of 25 services differed on that one key, and an install of a one-container app
re-created the sign-in's worker. hp-laptop: host 5.3.1 (its package had moved off the installer's
number), control plane 5.6.0, agent and archiver 2.40.3 — three versions among four callers.

THE RULE. The compose a HOST runs is the fact (scripts/lib.sh exports its version as
BBOX_COMPOSE_VERSION); an image that installs the plugin is BUILT WITH THAT VERSION — its
Dockerfile takes `ARG COMPOSE_VERSION`, its compose file passes the host's. Nothing is installed,
downgraded or held on a machine to match a number written in a file: a host's package may be shared
with another stack. What a number in a file IS good for is the default — what a fresh machine gets
from the installers, and what an image built with no host at hand (CI) carries.

WHAT IT CHECKS, statically:
  * the installers name ONE version — debian-install.sh, packaging/macos/engine.yaml,
    packaging/linux/fetch-runtime.sh;
  * a Dockerfile that installs `docker-compose-plugin` declares `ARG COMPOSE_VERSION=<that version>`,
    installs by it (or by that same literal), never unpinned — and the compose file beside it hands
    the build `${BBOX_COMPOSE_VERSION:-<that version>}`;
  * a Dockerfile that COPIES the plugin out of an image stage names the exact docker CLI release
    debian-install.sh installs (`docker:28-cli` is a moving tag).
A running office is asked by `scripts/config-by-caller.sh`, which compares what every caller compiles.
"""
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
INSTALLERS = (
    ("debian-install.sh", r"^COMPOSE_VER=([0-9.]+)\s*$"),
    ("packaging/macos/engine.yaml", r"^\s*C='([0-9.]+)-"),
    ("packaging/linux/fetch-runtime.sh", r'^COMPOSE_VERSION="\$\{COMPOSE_VERSION:-([0-9.]+)\}"'),
)
ENGINE = ("debian-install.sh", r"^DOCKER_VER=(?:[0-9]+:)?([0-9.]+)\s*$")
SKIP = ("node_modules", "attic", "legacy", "digital-office", ".generated", "ci-artifacts")
ARG = "COMPOSE_VERSION"


def named(text, pattern):
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else None


def dockerfile(text, pin, engine):
    """(installs the plugin?, [problems]) for one Dockerfile."""
    text = re.sub(r"\\\r?\n", " ", text)                       # a RUN is one instruction, however it is wrapped
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    problems, installs = [], False
    for m in re.finditer(r"\bdocker-compose-plugin(=(\S+?)(?=[-\"'\s]|$))?", code):
        installs = True
        how = m.group(2)
        if how is None:
            problems.append("installs docker-compose-plugin with no version")
        elif how not in ("${%s}" % ARG, "$%s" % ARG, pin):
            problems.append(f"installs docker-compose-plugin {how}, the installers install {pin}")
    if installs:
        default = named(code, r"^ARG\s+%s=([0-9.]+)\s*$" % ARG)
        if default is None:
            problems.append(f"installs the plugin and declares no `ARG {ARG}` — it cannot be built with the host's compose")
        elif default != pin:
            problems.append(f"`ARG {ARG}` defaults to {default}, the installers install {pin}")
    for m in re.finditer(r"^COPY\s+--from=(\S+)\s+\S*cli-plugins/docker-compose\b", code, re.M):
        stage = re.search(r"^FROM\s+(\S+)\s+AS\s+%s\s*$" % re.escape(m.group(1)), code, re.M | re.I)
        image = stage.group(1) if stage else m.group(1)
        if image != f"docker:{engine}-cli":
            problems.append(f"copies the plugin out of `{image}` — a moving tag; the stage must be "
                            f"`docker:{engine}-cli`, the release debian-install.sh installs")
    return installs, problems


def hands_it(compose_text, pin):
    """Does this compose file hand its build the host's compose version (default: the pin)?"""
    return re.search(r"^\s*%s:\s*\$\{BBOX_COMPOSE_VERSION:-%s\}\s*$" % (ARG, re.escape(pin)), compose_text, re.M) is not None


def check(repo=REPO):
    problems, pins = [], {}
    engine = named((repo / ENGINE[0]).read_text(encoding="utf-8"), ENGINE[1])
    if not engine:
        problems.append(f"{ENGINE[0]}: no DOCKER_VER — nothing says which engine this project installs")
    for rel, pattern in INSTALLERS:
        v = named((repo / rel).read_text(encoding="utf-8"), pattern) if (repo / rel).is_file() else None
        if v:
            pins[rel] = v
        else:
            problems.append(f"{rel}: the compose version it installs could not be read — the gate's pattern "
                            f"no longer matches the file, so it is measuring nothing")
    if len(set(pins.values())) > 1:
        problems.append("the installers install different versions: " + "; ".join(f"{r} {v}" for r, v in sorted(pins.items())))
    pin = next(iter(pins.values()), "")
    built = 0
    for path in sorted(repo.rglob("Dockerfile*")):
        if any(part in SKIP for part in path.relative_to(repo).parts) or not path.is_file():
            continue
        rel = path.relative_to(repo).as_posix()
        installs, found = dockerfile(path.read_text(encoding="utf-8", errors="replace"), pin, engine)
        problems += [f"{rel}: {p}" for p in found]
        if installs:
            built += 1
            beside = path.parent / "docker-compose.yml"
            if not beside.is_file() or not hands_it(beside.read_text(encoding="utf-8"), pin):
                problems.append(f"{rel}: the compose file beside it does not hand the build "
                                f"`{ARG}: ${{BBOX_COMPOSE_VERSION:-{pin}}}` — the image would keep the default "
                                f"on a host that runs another compose")
    return problems, pin, built


def selftest():
    bad = []
    follows = ("ARG COMPOSE_VERSION=2.40.3\nRUN apt-get install -y \\\n"
               '  "docker-compose-plugin=${COMPOSE_VERSION}-1~debian.12~bookworm"\n')
    late = ("RUN apt-get install -y docker-ce-cli=5:28.5.2-1~debian.12~bookworm \\\n"
            "  docker-compose-plugin=2.40.3-1~debian.12~bookworm\n"
            "ARG COMPOSE_VERSION=2.40.3\n"
            'RUN [ "$(docker compose version --short)" = "${COMPOSE_VERSION}" ] || apt-get install -y '
            '"docker-compose-plugin=${COMPOSE_VERSION}-1~debian.12~bookworm"\n')
    loose = "RUN apt-get install -y --no-install-recommends docker-compose-plugin \\\n && rm -rf /var/lib/apt/lists/*\n"
    fixed = "RUN apt-get install -y docker-compose-plugin=2.40.3-1~debian.12~bookworm\n"
    other = follows.replace("ARG COMPOSE_VERSION=2.40.3", "ARG COMPOSE_VERSION=5.6.0")
    moving = "FROM docker:28-cli AS dockercli\nFROM python:3.12-slim\nCOPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/libexec/docker/cli-plugins/docker-compose\n"
    exact = moving.replace("docker:28-cli", "docker:28.5.2-cli")
    said = "# docker-compose-plugin is what the host installs\nFROM python:3.12-slim\n"
    for name, text, want in (("an image that follows the host", follows, (True, [])),
                             ("the pin first and the host's version last", late, (True, [])),
                             ("an exact CLI image", exact, (False, [])),
                             ("a comment that names the package", said, (False, []))):
        if dockerfile(text, "2.40.3", "28.5.2") != want:
            bad.append(f"{name} must read as {want}, got {dockerfile(text, '2.40.3', '28.5.2')}")
    for name, text in (("an unpinned package", loose), ("a literal the image cannot leave", fixed),
                       ("another default than the installers'", other), ("a moving CLI image", moving)):
        if not dockerfile(text, "2.40.3", "28.5.2")[1]:
            bad.append(f"{name} must be a finding, got {dockerfile(text, '2.40.3', '28.5.2')}")
    if not hands_it("      args:\n        COMPOSE_VERSION: ${BBOX_COMPOSE_VERSION:-2.40.3}\n", "2.40.3") \
            or hands_it("      args:\n        COMPOSE_VERSION: 2.40.3\n", "2.40.3"):
        bad.append("a compose file hands the build the HOST's version, with the pin as the default — a literal is not that")
    for rel, pattern in INSTALLERS + (ENGINE,):
        if (REPO / rel).is_file() and not named((REPO / rel).read_text(encoding="utf-8"), pattern):
            bad.append(f"{rel}: the pattern for its version matches nothing in the file")
    return bad


def main():
    if "--self-test" in sys.argv:
        bad = selftest()
        for b in bad:
            print("FAIL", b)
        print("compose-pin-lint self-test:", "PASS" if not bad else f"{len(bad)} problem(s)")
        return 1 if bad else 0
    problems, pin, built = check()
    if problems:
        print(f"G74 FAIL — {len(problems)} place(s) where a caller of compose can get another compose:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"G74 PASS — the installers install one compose ({pin}), and the {built} image(s) that install it "
          f"are built with the host's.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
