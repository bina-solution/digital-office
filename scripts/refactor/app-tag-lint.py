#!/usr/bin/env python3
"""app-tag-lint — gate G47: every n8n workflow blueprint carries its owning app's tag.

    python3 scripts/refactor/app-tag-lint.py [--self-test]

WHY THIS EXISTS. n8n's `tag_entity` had grown to 28 ad hoc, overlapping tags (`indox` on 49
workflows, `sm-refactore-v2.1` — a typo — on 29, `api` and `main` both meaning "callable sub-workflow
entrypoint" on 4 each, ...) with zero enforcement: nothing said a workflow had to be tagged at all,
and nothing said a tag had to mean the same thing on every workflow that carried it. 12 of the then-82
live workflows carried NO tag whatsoever. There was no way to answer "which app owns this workflow"
from n8n's own UI/API without reading the blueprint tree by hand.

The fix (2026-08-06) consolidated the vocabulary onto app/role/lifecycle axes (see
`apps/n8n/blueprint.yml` and the workflow files themselves for the full tag list) and gave
every workflow exactly one APP tag, derived from the blueprint directory that owns it — never
guessed from the workflow's name. This gate is what keeps that true going forward: a new workflow
committed without its app tag, or moved between app blueprint dirs without updating it, fails here
instead of silently reverting to "which app owns this?" being an archaeology question again.

WHAT COUNTS: the app tag expected for a workflow is determined by the blueprint directory it lives
in (the same directory-to-app mapping `platform/manager/reconcile.py blueprints` resolves for
`bbox n8n push`) — never by name-sniffing. A workflow fails if its `tags` array does not contain an
object whose `name` equals that directory's expected app tag.

WHICH TAG, AND WHAT HAPPENED TO THIS GATE. It was written for the 2026-08-06 vocabulary
(`indox-app`, `n8n-app`, `gwa-app` …). Ten days later the owner made ONE tag the ownership signal:
`app:<id>`, cut to tag_entity's varchar(24) — it is what `apps/n8n/hooks/pull` routes
every exported workflow home by, and `app:n8n` is the central blueprint. The gate never followed,
and nobody noticed, because from that same day (2026-08-16, blueprints became `.workflow.ts`) its
`*.json` globs matched nothing: it read the one legacy file below and said "all 1 workflow(s) carry
their app tag" for seven weeks. Read through the one reader on 2026-10-07, the old rule fails 34
workflows — 20 of them INDOX workflows created since, correctly tagged `app:indox`, for lacking a
tag nothing uses. So it checks the tag that routes. Under that rule 18 fail, and each is real:
workflows parked in the central blueprint with no `app:` tag at all (four scratch probes, two
retired ones, a draft that never ran, and six of INDOX's), the mail scheduler, and four of the
workspace agent's.

TWO FILES ARE NOT under `apps/*/blueprint/n8n/` or `apps/n8n/blueprint/n8n/` at all, so no glob
would find them, but both are LIVE in n8n today and are exactly the kind of orphan this gate exists
to keep visible instead of invisible:
  * `legacy/n8n/indox-sheets-era/indoxDocUploader01.json` — retired by an app consolidation but
    still active live (see `ai/context/archive/indox-pre-2026-09/ERROR-RCA-2026-08-05.md`); no blueprint owns it, so
    `bbox n8n push` never stages it and a tag written here does not reach the live instance on its
    own (it was additionally applied directly to the DB — see the task report). Expected: `indox-app`.
  * (until 2026-09-03) `apps/mail/tests/ztestMailDiscovery01.json` — the harness of a workflow
    retired with the sync-item architecture; both files are gone, the entry with them.
They are checked explicitly (EXTRA_FILES below) rather than left out the way G38's docstring left
`indoxDocUploader01` out — a static gate CAN check a file it knows the path of, it just can't check
a live-DB-only value it has no file for at all.

A workflow whose id/path is not recognized by either mechanism does not exist as far as this repo's
git tree is concerned and is not this gate's problem (a live-only workflow with no blueprint file
anywhere, e.g. a hand-created scratch/probe workflow, cannot be found by a gate that only reads
git — same limitation the module docstring above already explains for the two named exceptions).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)


def expected_tag(rel: str) -> str:
    """The tag that routes a blueprint home, from the directory it lives in: `app:<app id>` for
    apps/<id>/blueprint/n8n, `app:n8n` for the central blueprint — cut to 24 characters exactly
    as hooks/pull cuts it (`app:google-workspace-age`)."""
    parts = rel.split("/")
    return ("app:" + (parts[1] if parts[0] == "apps" else "n8n"))[:24]

# path (relative to REPO) -> expected app tag, for files outside every dir above — see docstring.
EXTRA_FILES = {
    "legacy/n8n/indox-sheets-era/indoxDocUploader01.json": "indox-app",
    # apps/mail/tests/ztestMailDiscovery01.json was listed here until 2026-09-03: the harness (and
    # the mailDiscovery01 it drove) went with the sync-item cut, and the tests/ dir with the mail
    # consolidation.
}


def _tag_names(doc: dict) -> set[str]:
    out = set()
    for t in doc.get("tags") or []:
        n = t.get("name") if isinstance(t, dict) else t
        if n:
            out.add(str(n))
    return out


def check(records: list[tuple[str, dict, str]]) -> list[str]:
    """records: list of (relpath, parsed_json, expected_app_tag). Returns violation strings."""
    violations = []
    for relpath, doc, expected in records:
        have = _tag_names(doc)
        if expected not in have:
            wf_id = doc.get("id", "?")
            wf_name = doc.get("name", "?")
            violations.append(
                f"{relpath}  (id={wf_id!r} name={wf_name!r}): missing app tag {expected!r} "
                f"(has: {sorted(have) or '[]'})"
            )
    return violations


def collect_real() -> list[tuple[str, dict, str]]:
    records = []
    for pattern in BLUEPRINT_GLOBS:
        for p in sorted(REPO.glob(pattern)):
            rel = p.relative_to(REPO).as_posix()
            try:
                doc = load_blueprint(str(p))
            except (OSError, ValueError, CompileError) as e:
                records.append((rel, {"id": "?", "name": f"<UNREADABLE: {e}>"}, expected_tag(rel)))
                continue
            records.append((rel, doc, expected_tag(rel)))
    for relpath, tag in EXTRA_FILES.items():
        p = REPO / relpath
        if not p.exists():
            continue  # moved/renamed — not this gate's job to notice (see legacy-ref-lint, G34)
        doc = json.loads(p.read_text(encoding="utf-8"))
        records.append((relpath, doc, tag))
    return records


def self_test() -> int:
    """Prove the gate can fail: a synthetic workflow with the WRONG (missing) app tag must be
    flagged, and a correctly-tagged one must pass — run purely in-memory, no repo files touched."""
    good = {
        "id": "selftestGood01",
        "name": "Self-test Good",
        "nodes": [{"type": "n8n-nodes-base.noOp"}],
        "tags": [{"id": "x", "name": "app:indox"}, {"id": "y", "name": "role:api"}],
    }
    bad_missing = {
        "id": "selftestBad01",
        "name": "Self-test Bad (no app tag at all)",
        "nodes": [{"type": "n8n-nodes-base.noOp"}],
        "tags": [{"id": "y", "name": "role:api"}],
    }
    bad_wrong_app = {
        "id": "selftestBad02",
        "name": "Self-test Bad (wrong app tag for its dir)",
        "nodes": [{"type": "n8n-nodes-base.noOp"}],
        "tags": [{"id": "z", "name": "app:mail"}, {"id": "w", "name": "indox-app"}],  # under apps/indox below
    }
    paths = ["apps/indox/blueprint/n8n/selftest%s.workflow.ts" % s for s in ("Good01", "Bad01", "Bad02")]
    records = [(p, doc, expected_tag(p)) for p, doc in zip(paths, (good, bad_missing, bad_wrong_app))]
    violations = check(records)
    bad_paths = {v.split("  ")[0] for v in violations}
    ok = (
        paths[0] not in bad_paths and paths[1] in bad_paths and paths[2] in bad_paths
        and len(violations) == 2
        and expected_tag("apps/indox/blueprint/n8n/x.workflow.ts") == "app:indox"
        and expected_tag("apps/n8n/blueprint/n8n/x.workflow.ts") == "app:n8n"
        and expected_tag("apps/google-workspace-agent/blueprint/n8n/x.workflow.ts") == "app:google-workspace-age"
    )
    print(f"G47 self-test: detected {len(violations)}/2 known-bad fixtures, "
          f"{'0' if 'selftestGood01' not in str(bad_paths) else '1+'} false positive(s) on the good one")
    for v in violations:
        print("  [self-test violation]", v)
    if not ok:
        print("G47 self-test FAILED — the gate cannot be trusted to catch a missing/wrong app tag.")
        return 1
    print("G47 self-test passed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    records = collect_real()
    shipped = sum(1 for rel, _doc, _tag in records if rel.endswith(".workflow.ts"))
    if not shipped:
        print("G47 FAILED: read ZERO shipped blueprint workflows, so nothing was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1
    violations = check(records)
    if violations:
        print(f"G47 FAILED: {len(violations)} workflow(s) missing their app tag:\n")
        for v in violations:
            print(" ", v)
        print(f"\n{len(records)} workflow(s) checked, {len(violations)} failed.")
        return 1
    print(f"G47 passed: all {len(records)} workflow(s) carry their app tag.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
