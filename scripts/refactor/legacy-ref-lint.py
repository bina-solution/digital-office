#!/usr/bin/env python3
"""legacy-ref-lint — gate G34: a reference INTO legacy/ must be DECLARED.

    python3 scripts/refactor/legacy-ref-lint.py [--self-test]

WHY THIS EXISTS. `attic/` was the previous parked tree: 293 files, 17 projects, and a README that
said nothing referenced it. That sentence was false. Two things read out of `attic/` the whole time:

  * `.github/workflows/indox-e2e.yml` booted a compose stack from `attic/feature-validation/`
  * `digital-office/sim/build.mjs` read `attic/feature-validation/api/dashboard.html`

So the one document a reader would consult before deleting the tree was the document that would
have made them break CI and renumber every panel in the sim. `attic/` was in fact deleted — its 16
genuinely-unreferenced projects went to git history, and its one live tenant moved to
`legacy/feature-validation` — and `legacy/README.md` now opens with a TABLE of its live consumers
precisely so the attic mistake cannot repeat.

A table in a README is prose, and prose rots the moment someone adds a reference without reading it.
This gate is the mechanical half: every reference from live code into `legacy/` must appear in
ALLOWED below, with a reason. A NEW, undeclared one fails. The point is not to forbid reading from
`legacy/` — two lanes legitimately did, until the suites they read moved to `apps/apitools/` where
they belonged — it is that "parked" and "unreferenced" are different claims, and only one of them
can be checked by a machine. This checks it.

ALLOWED is now EMPTY, and it emptied ITSELF — which is the design working, not the gate becoming
pointless. Its last entry was an n8n stickyNote naming `legacy/n8n/google-integration-health/`; when
that directory was deleted the declaration stopped matching, this gate FAILED, and that is what
forced the stickyNote to be repointed at git history instead of left dangling into a directory that
no longer exists. `legacy/` came BACK (13 tracked files under legacy/n8n and legacy/indox-workflows as of
2026-08-21), which is precisely the case this gate was left in place for. The gate stays because the INVARIANT outlives the
directory: recreate an archive here, have a lane read from it, and the first undeclared reference
fails — which is exactly how `attic/` reached 293 files behind a README swearing nothing used it.

WHAT COUNTS AS A REFERENCE, and what emphatically does not:

  violation   a path INTO the tree — `legacy/<something>` — in a line of live code: a compose `-f`,
              a `bash …`, a source path in a build script, a filename in a config.
  fine        a COMMENT mentioning it. `ops/prejob_fixperms.sh` explains which directories the
              runner cannot chmod and names `legacy/feature-validation` doing so; that is a human
              telling another human where the files are, not a program opening one.
  fine        anything in a `.md` doc. `legacy/README.md` and the migration notes exist to talk
              about this tree; a gate that flagged them would forbid documenting the thing.
  fine        the bare directory name with nothing after it — `startswith("legacy/")`, "candidates
              for legacy/" — that names the directory, it does not reach into it.
  fine        the refactor lints' own SKIP lists (see SKIP_LIST_REFERRER).

LIVE CODE is every tracked file except: `legacy/` itself (it may refer to itself), `ai/`, `.ci-cd/`
and `issues/` (notes and plans — prose in .txt/.yaml clothing), `*.md`, and this gate, whose ALLOWED
table necessarily spells out every path it is guarding.

THE LIST CANNOT ROT. An ALLOWED entry that matches nothing FAILS, exactly as in G31's DEBT list. If
a consumer is retired, its declaration must go with it — otherwise the allow-list quietly becomes a
permanent blanket exemption, which is how you get back to a README nobody can trust.
"""
import argparse
import fnmatch
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SELF = "scripts/refactor/legacy-ref-lint.py"

#: Trees that are notes-about-the-repo rather than the repo. `ai/` is context dumps, `.ci-cd/` and
#: `issues/` are plans and tickets. They talk about the estate for a living; they do not run.
EXCLUDED_PREFIXES = ("legacy/", "ai/", ".ci-cd/", "issues/")
EXCLUDED_SUFFIXES = (".md",)

#: `legacy/` followed by at least one path character — i.e. a path INTO the tree. The bare name with
#: nothing after it deliberately does not match: `EXCLUDE_PREFIXES = ("legacy/",)` and the print
#: string "candidates for legacy/)" both name the directory without reaching into it.
#: `*` is in the class ON PURPOSE, so a glob like `legacy/**/docker-compose.yml` is SEEN and then
#: explicitly excused below, rather than slipping through on a technicality.
#: The lookbehind stops `mylegacy/x` from matching but allows `./legacy/x` and `/mnt/c/legacy/x`.
REF = re.compile(r"(?<![A-Za-z0-9._-])legacy/([A-Za-z0-9._*/-]+)")

#: A line whose FIRST non-space characters open a comment. Deliberately leading-only: a `#` in the
#: middle of a line is as likely to be inside a string as to start a comment, and every real mention
#: in this tree is a whole-line comment.
COMMENT = re.compile(r"^\s*(#|//|/\*|\*/|\*\s|<!--|;|--\s)")

#: (referrer, path into legacy/, why it is allowed to be there).
#: This is the machine-readable twin of the consumer table at the top of `legacy/README.md`. If you
#: are adding a row here, add it there too — the README is what a human reads before deleting a
#: directory, and the whole reason this gate exists is that the two disagreed once.
#:
#: The three feature-validation entries that used to head this list are GONE, and their absence is
#: the point: two live lanes (indox-e2e and the sim build) read out of the parked tree, which is the
#: exact shape that kept `attic/` alive. The suites validate apitools, so they moved to
#: `apps/apitools/feature-validation/` and their harness became `apps/apitools/hooks/test`. A
#: reference into `legacy/feature-validation/` is now an ordinary, undeclared violation again — see
#: the first SELF_TEST case, which proves it.
# EMPTY — and it emptied itself, which is the whole design.
#
# The list held one entry: an n8n stickyNote in indoxHealth00001.json naming
# `legacy/n8n/google-integration-health/`, where a predecessor workflow was parked. When `legacy/n8n`
# was deleted, that declaration stopped matching and this gate FAILED — "declared reference matching
# nothing" — which is exactly what forced the stickyNote to be repointed at git history rather than
# left pointing into a directory that no longer exists. A dangling reference is worse than a
# declared one, and prose could not have caught it.
#
# `legacy/` was gone; it is back (13 tracked files, 2026-08-21) and two lanes read from it — both
# now declared above. The invariant did its job: a recreated archive with lanes reading from it
# failed on the first undeclared reference — which is precisely how `attic/` grew to 293 files
# behind a README asserting that nothing referenced it.
ALLOWED = [
    ("scripts/refactor/app-tag-lint.py",
     "legacy/n8n/indox-sheets-era/indoxDocUploader01.json",
     "G47's EXTRA_FILES maps this parked blueprint to its expected app tag. It is a READ of the "
     "archive and it is deliberate: the workflow is still active=true in the live n8n DB, so it "
     "must carry `indox-app` like everything else indox owns. Delete the archive and G47 loses "
     "its only out-of-tree case — which is exactly what this declaration exists to make visible."),
    ("scripts/ops/rename-from-office-to-warehouse.py",
     "legacy/n8n/indox-sheets-era/**",
     "Names the archive in its EXCLUSION table, so the rename sweep does not rewrite column names "
     "in files that record what those columns WERE called. A reference that means 'do not touch', "
     "which the gate cannot distinguish from a read, and should not have to."),
]

#: The refactor lints each NAME `legacy/` as a directory to skip — `compile-lint` excludes it from
#: the parse sweep, `layering-lint` drops it from the reference set, `ownership-lint` excuses
#: `legacy/**/docker-compose.yml` from the "nothing outside apps/" rule. Those are the opposite of a
#: reference: they exist to NOT look at the tree. Only wildcard forms reach this rule at all (a bare
#: `"legacy/"` prefix never matches REF), and a wildcard is a pattern — nothing opens it.
SKIP_LIST_REFERRER = "scripts/refactor/*lint*.py"


def is_live(rel):
    """Is this tracked path live code, i.e. something the gate should hold to the allow-list?"""
    if rel == SELF:
        return False
    if rel.startswith(EXCLUDED_PREFIXES):
        return False
    return not rel.endswith(EXCLUDED_SUFFIXES)


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    return [r for r in out.stdout.splitlines() if r]


def is_declared(rel, target):
    return any(f == rel and t == target for f, t, _ in ALLOWED)


def is_skip_list(rel, target):
    return fnmatch.fnmatch(rel, SKIP_LIST_REFERRER) and "*" in target


def scan(virtual=None):
    """Return (findings, declared_hits).

    virtual: {rel: text} — scan exactly these, from memory. --self-test uses it to plant a reference
    without ever writing one into the real tree. Files that are not live code are filtered here too,
    so passing a `.md` proves the exclusion rather than merely asserting it.
    """
    items = ([(rel, None) for rel in tracked()] if virtual is None
             else list(virtual.items()))
    findings, hits = [], set()
    for rel, text in items:
        if not is_live(rel):
            continue
        if text is None:
            p = REPO / rel
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # binary (fixtures are .png/.pdf) or unreadable — no references in either
        if "legacy/" not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if COMMENT.match(line):
                continue
            for m in REF.finditer(line):
                # Trailing sentence punctuation is not part of the path.
                target = ("legacy/" + m.group(1)).rstrip(".")
                if is_declared(rel, target):
                    hits.add((rel, target))
                elif not is_skip_list(rel, target):
                    findings.append((rel, i, target, line.strip()[:110]))
    return findings, hits


#: (label, path the planted line lives at, the line, must this be caught?). The must-NOT-catch half
#: matters as much as the other: a gate that flagged the README, the comments, or the lints' own
#: skip lists would be switched off inside a week, and then nothing would watch the real thing.
SELF_TEST = [
    # The suites moved to apps/apitools/ (harness: apps/apitools/hooks/test), so this — the exact
    # line indox-e2e used to carry, DECLARED — is a plain violation again. It is first in the list
    # because the whole reason G34 exists is that a live lane was reading from the archive.
    ("the retired indox-e2e reference, now undeclared", "scripts/selftest.sh",
     '  bash legacy/feature-validation/run-suites.sh', True),
    ("a new reference from a workflow", ".github/workflows/selftest.yml",
     '          run: cat legacy/n8n/base-workflows/_pdbg.json', True),
    ("a new reference from python", "scripts/selftest.py",
     '    src = REPO / "legacy/feature-validation/api/server.py"', True),
    ("a new reference from a workflow to the moved suites", ".github/workflows/selftest.yml",
     '          "${BBOX_COMPOSE}" -f legacy/feature-validation/docker-compose.yml up -d', True),
    ("a new reference from the sim build", "digital-office/sim/selftest.mjs",
     "  { id: 'feature-validation', html: 'legacy/feature-validation/api/dashboard.html' },", True),
    # This was the last DECLARED reference — a stickyNote naming where a predecessor workflow was
    # parked — and it was allowed until `legacy/n8n/` was deleted and the declaration went with it.
    # With ALLOWED empty there is nothing left to excuse, so the same line is now a finding: the
    # gate has no permanent exemptions to test, only the rule.
    ("the retired stickyNote declaration", "apps/indox/blueprint/n8n/indoxHealth00001.json",
     '          "content": "predecessor parked at legacy/n8n/google-integration-health/"', True),
    ("a mention inside a .md doc", "docs/selftest.md",
     "The suites live in `legacy/feature-validation/` and run advisory.", False),
    ("a mention in a shell comment", "scripts/selftest.sh",
     "# legacy/feature-validation/run-suites.sh used to be scripts/ci-feature-validation.sh", False),
    ("a mention in a python comment", "scripts/selftest.py",
     "    # legacy/n8n/kafka-retired/ is where the broker workflow went", False),
    ("a mention in a js comment", "digital-office/sim/selftest.mjs",
     "  // retired; its source lives in legacy/feature-validation/api/", False),
    ("a lint's skip-list glob", "scripts/refactor/selftest-lint.py",
     '                "legacy/**/docker-compose.yml",', False),
    ("the bare directory name, nothing after it", "scripts/selftest.py",
     '    EXCLUDE_PREFIXES = ("legacy/",)', False),
]


def self_test():
    bad = 0
    for label, rel, line, should_catch in SELF_TEST:
        findings, _ = scan({rel: line + "\n"})
        caught = bool(findings)
        if caught != should_catch:
            bad += 1
        verb = "caught" if caught else "allowed"
        want = "must catch" if should_catch else "must allow"
        print(f"  [{'ok ' if caught == should_catch else 'FAIL'}] {verb:<8} ({want}): {label}")
    print(f"\nG34 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="prove the gate catches a new reference and allows the declared ones")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings, hits = scan()

    # A declaration matching nothing is a failure, not a harmless leftover: it means the consumer is
    # gone (delete the row, here AND in legacy/README.md) or the path drifted and this gate silently
    # stopped guarding it.
    stale = [(f, t, why) for f, t, why in ALLOWED if (f, t) not in hits]
    if stale:
        print(f"G34 FAIL — {len(stale)} declared reference(s) matching nothing:")
        for f, t, _ in stale:
            print(f"    {f}  ->  {t}")
        print("\n  Consumer retired? Delete the ALLOWED entry and its row in legacy/README.md.")
        print("  Otherwise the path drifted and the allow-list is now a blanket exemption.")
        return 1

    if findings:
        print(f"G34 FAIL — {len(findings)} undeclared reference(s) into legacy/:")
        for rel, i, target, line in findings:
            print(f"    {rel}:{i}  ->  {target}")
            print(f"        {line}")
        print("\n  legacy/ is the PARKED tree. Reading from it is allowed but must be DECLARED, so")
        print("  that whoever deletes it next can see who breaks. attic/ was deleted on the word of")
        print("  a README that said nothing referenced it while CI was booting a compose file out")
        print("  of it. Either point at the live tree instead, or add the reference to ALLOWED in")
        print("  scripts/refactor/legacy-ref-lint.py with a reason, and to the consumer table at")
        print("  the top of legacy/README.md.")
        return 1

    print(f"G34 PASS — all {len(ALLOWED)} reference(s) into legacy/ are declared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
