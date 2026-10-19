#!/usr/bin/env python3
"""compose-invocation-lint — gate G7: nobody may invoke docker compose the wrong way.

    python3 scripts/refactor/compose-invocation-lint.py

Under the app model the stack is COMPILED into .generated/ from apps/*/app.json plus
platform.state.yaml. The root compose.yml declares only the shared network, so a bare

    ( cd "${REPO_ROOT}" && docker compose restart n8n )

resolves ZERO services. Docker prints "no such service: n8n" and exits 0, and the `|| true`
that call sites wrap these in swallows even that. Nothing fails; the command does nothing.

That is exactly how this shipped broken once: scripts/n8n-push's restart step became a
silent no-op, so after every push n8n kept serving its pre-import state — no trigger or
webhook ever re-registered. Gates that compare RENDERED CONFIG (G1) cannot see this,
because the config was never wrong; the invocation was. Hence a separate gate.

The one correct form is dcx() from scripts/lib.sh, which supplies both required arguments:
the compiled -f list (from `reconcile.py compose-files`) and --project-directory, neither of
which has an env-var equivalent.

Scope is deliberately narrow — only files that actually RUN commands against this stack:
scripts/, bbox, and .github/workflows/. Prose, issue write-ups, vendored trees and
self-contained app compose files are not invocations and are not linted.
"""
import pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[2]

TARGETS = ["bbox"]
TARGET_DIRS = ["scripts", ".github/workflows"]

EXEMPT = {
    "scripts/lib.sh",                                  # defines dcx() itself
    "scripts/refactor/compose-invocation-lint.py",     # this file
    # (compose-equiv.py was exempt here — it rendered both sides of the G1 diff. G1 was deleted
    #  2026-07-30, so the entry went with it rather than sit here as a dead exemption.)
    # G32's self-test fixtures are strings that MUST contain a bare invocation — proving it catches
    # one is the whole point. A gate cannot treat another gate's evidence as the offence.
    "scripts/refactor/engine-bypass-lint.py",
}

# Only match `docker compose` in COMMAND POSITION — at the start of a line or right after a
# shell separator / `run:`. This is what keeps prose out: a help string like
# "(docker compose down -v)" or a docstring's `docker compose up -d` is never in command
# position, so it is not a finding and needs no exemption list.
#
# TWO invocation forms are policed, because the stack no longer says `docker compose`:
#   docker compose ...        — the plugin SEARCH. Where Docker Desktop is installed this resolves
#                               to Desktop's binary (measured: v2.34.0-desktop.1 shadowing the
#                               distro's v5.3.1), so the stack does not use it any more.
#   "${BBOX_COMPOSE}" ...     — the plugin this project installs, named by path. See scripts/lib.sh.
# Both must still carry the compiled file list; a bare invocation of EITHER resolves zero services
# and exits 0, which is the silent no-op this gate exists to prevent. Policing only the first form
# would have quietly retired the gate the moment the call sites changed.
CALL = re.compile(
    r"(?:^|[;&|]\s|&&\s|\|\|\s|\bif\s|\bthen\s|\belse\s|\bdo\s|\brun:\s)\s*"
    r"(?:docker\s+compose\b|(?:exec\s+)?[\"']?\$\{BBOX_COMPOSE[:}][^\"']*[\"']?)")
# Safe when the call names the compiled file list, or is a plugin-capability probe
# (`docker compose version` queries the CLI itself and needs no project).
#
# NOTE: COMPOSE_FILE alone is deliberately NOT accepted. It supplies -f but cannot supply
# --project-directory, which then defaults to the first file's directory (.generated/) — and
# the generated file's `- compose.yml` include resolves against it, self-includes, and docker
# fails with "include cycle detected". Both arguments or neither.
SAFE = re.compile(r"(-f\s|--file[\s=]|--project-directory|compose_args|compose\s+version)")


def files_to_lint():
    out = []
    for t in TARGETS:
        p = REPO / t
        if p.is_file():
            out.append(p)
    for d in TARGET_DIRS:
        for p in sorted((REPO / d).rglob("*")):
            if p.is_file() and p.suffix in ("", ".sh", ".bash", ".py", ".yml", ".yaml"):
                out.append(p)
    return out


def main() -> int:
    bad = []
    for f in files_to_lint():
        rel = f.relative_to(REPO).as_posix()
        if rel in EXEMPT:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "docker compose" not in text:
            continue
        # A CI workflow that exports COMPOSE_FILE for the job has supplied the file list to
        # every step in it, so its individual `docker compose` lines are correctly targeted.
        if rel.startswith(".github/workflows/") and "COMPOSE_FILE" in text:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if not CALL.search(line) or SAFE.search(line):
                continue
            bad.append((rel, n, line.strip()[:96]))

    if not bad:
        print("G7 PASS — every docker compose invocation carries the compiled file list.")
        return 0

    print(f"G7 FAIL — {len(bad)} bare `docker compose` invocation(s); each is a silent no-op:")
    for rel, n, line in bad:
        print(f"  {rel}:{n}: {line}")
    print("\nUse dcx (scripts/lib.sh) — it supplies -f <compiled files> and --project-directory.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
