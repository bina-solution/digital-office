#!/usr/bin/env python3
"""engine-bypass-lint — gate G32: nothing may address the engine or compose except through bbox's.

    python3 scripts/refactor/engine-bypass-lint.py [--self-test]

Two bypasses, one consequence: work silently lands on Docker Desktop's engine instead of the
project's, or on Desktop's compose plugin instead of the pinned one.

  1. `docker compose` is a plugin SEARCH, not a binary. Where Docker Desktop is installed it
     resolves to Desktop's plugin, which speaks to Desktop's daemon. Use ${BBOX_COMPOSE}, or
     scripts/dc / dcx() which wrap it.
  2. `/var/run/docker.sock` as a HOST-side bind source is Desktop's socket wherever Desktop's WSL
     integration is on — the exact hijack that made traefik discover zero routers while reporting
     healthy, and every gated host 404. Use ${BBOX_DOCKER_SOCK}.

G7 already covers the other half of (1): compose invoked without the compiled -f list resolves zero
services and exits 0. This covers WHICH compose and WHICH engine.

It is not hypothetical. `packaging/make-runtime-compose.py` — the tool that produces the compose
file the SHIPPED ARTIFACT boots from — called bare `docker compose` for months, in a repo whose
whole architecture forbids it, because no gate looked outside the shell scripts.
"""
import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# Directories that are not first-party, are captured snapshots, or are prose about the problem.
# `issues/` is the issue tracker and `.refactor/` holds local RECORDINGS of what compose rendered
# (`candidate.yml`, the default input of auth-lint/paths-exist) — flagging either would be flagging
# a description of the bug as the bug.
SKIP = ("/node_modules/", "/_archive/", "/attic/", "/legacy/", "/.git/", "/ci-artifacts/",
        "/_v2_precentralize_bak/", "/workflows-archive/", "/issues/", "/.refactor/",
        "/examples/", "/digital-office/sim/")

# A gate is only as good as its false-positive rate. The first cut of this one produced 57
# findings, of which ~all were prose: docstrings explaining the trap, `bbox reset`'s confirmation
# message quoting the command it runs, and — best of all — gate G7's own PASS message. A gate that
# flags the explanation of the rule teaches people to disable the gate. Hence: command position only.
#
# Command position = start of line, or immediately after a shell operator. Inside a quote, after a
# word, or in a comment is prose.
# NOTE: `(` is deliberately NOT a command start. `echo "This DESTROYS all data (docker compose
# down -v)"` is a warning message, and treating the paren as a subshell flagged bbox for describing
# what it is about to do. `$(` still covers real command substitution.
CMD_START = r"""(?:^|[;&|]|\$\(|&&|\|\||^\s*RUN\s+|\bthen\s+|\bdo\s+|\belse\s+)\s*"""
#: ACTIONS only. `docker compose version` is a capability PROBE — debian-install.sh asks it before
#: BBOX_COMPOSE can possibly exist, and app-management's Dockerfile asserts with it at build time.
#: Neither addresses this stack, so neither is a bypass.
COMPOSE_ACTIONS = {"up", "down", "build", "config", "ps", "restart", "exec", "logs", "pull",
                   "run", "stop", "start", "rm", "kill", "create", "images", "cp", "top"}
#: Match the invocation; the ACTION is then found by walking past flags and their values, because
#: `docker compose -f a.yml config` puts a filename between the flag and the verb.
BARE_COMPOSE = re.compile(CMD_START + r"""docker\s+compose\s+(?P<rest>.*)""")

#: Lines that name a compose command inside a string the program SENDS somewhere else. Recorded
#: explicitly rather than pattern-matched, so each one is a visible decision.
PROSE_EXEMPT = {
    "apps/openhands/dispatcher/server.js":
        "instructs the user about THEIR /workspace/project, not this stack",
}


def _is_bypass(rest):
    """True when what follows `docker compose` is an action rather than a capability probe."""
    for tok in rest.replace('"', " ").replace("'", " ").split():
        if tok.startswith("-"):
            continue                      # a flag…
        if tok in COMPOSE_ACTIONS:
            return True
        if tok == "version":
            return False
        # a flag's VALUE (a.yml, ./dir) — keep walking
    return False

#: the host socket as a compose bind SOURCE (`- /var/run/docker.sock:/…`).
HOST_SOCK = re.compile(r"""^\s*-\s*["']?/var/run/docker\.sock:""")

#: Files whose SUBJECT is the host socket — they name it because they detect, compare, or migrate
#: it. Rewriting these to ${BBOX_DOCKER_SOCK} would defeat what they do.
SOCK_SUBJECT = ("packaging/linux/adapt-host.py", "packaging/linux/check-coexistence.sh",
                "platform/manager/catalog_selftest.py", "platform-base/connections/identity.py")

#: Apps that genuinely run containers and therefore need a real engine socket
#: (docker-outside-of-docker). Recorded here so the choice is VISIBLE rather than assumed — each
#: one is a container that can start other containers, which is a real privilege.
SOCK_ALLOWED_APPS = {
    "apps/openhands/docker-compose.yml": "a coding agent that launches its own runtime containers",
    "apps/any-concurrency/docker-compose.standalone.yml": "standalone variant; reads docker for metrics",
}


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    for rel in out.stdout.splitlines():
        rel = rel.strip()
        if not rel or any(s in f"/{rel}" for s in SKIP):
            continue
        if rel.rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "ico", "pdf", "enc",
                                      "gz", "zip", "woff", "woff2", "ttf"):
            continue
        yield rel


def scan_text(rel, text):
    """Findings for one file's content. Comments and docs are exempt: this repo explains the trap
    at length in prose, and a gate that punished the explanation would delete the explanation."""
    if rel.endswith((".md", ".txt", ".json")) or "/ai/context/" in f"/{rel}":
        return []
    sock_exempt = rel in SOCK_SUBJECT or rel in SOCK_ALLOWED_APPS
    prose_exempt = rel in PROSE_EXEMPT
    out = []
    in_doc = False
    heredoc = None
    heredoc_open = re.compile(r"<<-?\s*(['\"]?)(\w+)\1\s*$")
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        # A heredoc body is text handed to a command. `bbox help` is one, and it necessarily
        # DESCRIBES what `bbox run` and `bbox reset` do — in the vocabulary of the thing it wraps.
        if heredoc is not None:
            if s == heredoc:
                heredoc = None
            continue
        m_h = heredoc_open.search(line)
        if m_h:
            heredoc = m_h.group(2)
            continue
        # Python docstrings are prose by definition, and several of this repo's best explanations
        # of exactly this trap live in one.
        if rel.endswith(".py") and s.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or not s or s.startswith("#"):
            continue
        code = line.split(" #", 1)[0]
        m = BARE_COMPOSE.search(code)
        if m and _is_bypass(m.group("rest")) and not prose_exempt:
            out.append((rel, i, s[:104], "bare `docker compose` — use ${BBOX_COMPOSE} / scripts/dc"))
        elif not sock_exempt and HOST_SOCK.search(code) and "BBOX_DOCKER_SOCK" not in line:
            out.append((rel, i, s[:104], "/var/run/docker.sock — use ${BBOX_DOCKER_SOCK}"))
    return out


def scan(overrides=None):
    overrides = overrides or {}
    findings = []
    for rel in tracked():
        if rel in overrides:
            text = overrides[rel]
        else:
            try:
                text = (REPO / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        findings += scan_text(rel, text)
    for rel, text in overrides.items():
        if rel not in set(tracked()):
            findings += scan_text(rel, text)
    return findings


SELF_TEST = [
    # must catch — real invocations and real host-socket mounts
    ("bare compose at line start", "scripts/_probe.sh", 'docker compose up -d\n', True),
    ("bare compose after &&", "scripts/_probe.sh", 'cd x && docker compose build n8n\n', True),
    ("bare compose with flags", "scripts/_probe.sh", 'docker compose -f a.yml config\n', True),
    ("host socket as a bind source", "apps/_probe/docker-compose.yml",
     '      - /var/run/docker.sock:/var/run/docker.sock\n', True),
    # must allow — the correct forms, capability probes, and every shape of prose
    ("compose via BBOX_COMPOSE", "scripts/_probe.sh", '"${BBOX_COMPOSE}" up -d\n', False),
    ("compose via scripts/dc", "scripts/_probe.sh", 'bash scripts/dc up -d\n', False),
    ("socket from the variable", "apps/_probe/docker-compose.yml",
     '      - ${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock\n', False),
    ("`compose version` capability probe", "scripts/_probe.sh",
     'docker compose version >/dev/null 2>&1 || die "no plugin"\n', False),
    ("a comment explaining the trap", "scripts/_probe.sh",
     '# never use bare docker compose up or /var/run/docker.sock\n', False),
    ("a trailing comment", "scripts/_probe.sh", 'bash scripts/dc up -d  # not docker compose up\n', False),
    ("prose in a user-facing message", "scripts/_probe.sh",
     'echo "This DESTROYS all data (docker compose down -v)"\n', False),
    ("prose in a python docstring", "scripts/_probe.py",
     '"""\nRuns docker compose up -d for you.\n"""\nx = 1\n', False),
]


def self_test():
    bad = 0
    for label, rel, text, should in SELF_TEST:
        got = bool(scan_text(rel, text))
        if got != should:
            bad += 1
        print(f"  [{'ok ' if got == should else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG32 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    findings = scan()
    if findings:
        print(f"G32 FAIL — {len(findings)} engine/compose bypass(es):")
        for rel, i, s, why in findings:
            print(f"    {rel}:{i}  {why}")
            print(f"        {s}")
        return 1
    print("G32 PASS — every compose call and engine address goes through bbox's.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
