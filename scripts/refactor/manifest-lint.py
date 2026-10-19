#!/usr/bin/env python3
"""manifest-lint — gate G73: every app manifest is one the compiler accepts.

    python3 scripts/refactor/manifest-lint.py
    python3 scripts/refactor/manifest-lint.py --self-test

WHY THIS EXISTS. `platform/manager/reconcile.py validate` is what every render runs first, and a
refused manifest is a refused render: `bbox run` stops with "reconcile render failed — refusing to
bring up a stale .generated/" on every office that pulled the commit. CI runs it, as a step of its
own further down ci-verify.yml — so the one list that calls itself "every gate" (scripts/ci/gates.sh,
which is what `bbox baseline` and a local run before a push execute) did not.

2026-10-06: 3248b705 took an agent brief from 5863 to 6791 bytes against a budget of 6000. A
clean-clone run of gates.sh reported "the same nine red as the base", the commit was pushed, and
the first bring-up after it — forty minutes later — is what found it. This gate is that step, in
the list. It adds no rule of its own: what a manifest may say is the compiler's to decide, once.

THE SELF-TEST holds the compiler's validator to the case it once could not see. It checked types at
the top level of a manifest only, so a tile whose `routing[].module.name` was written as an
`{en, he}` object passed, was compiled as written, and reached a console as the sidebar entry
`[object Object]share-2` — three layers from the file that was wrong (2026-08-24,
issues/reconcile-type-validator-never-recurses.yaml). The validator recurses since; the self-test
puts that same object into a copy of a real manifest and requires the refusal to name the full
path. A validator only ever seen passing has not been tested.
"""
import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]


def self_test() -> int:
    import copy
    sys.path.insert(0, str(REPO / "platform" / "manager"))
    import reconcile  # noqa: PLC0415 — the compiler's own validator, not a copy of it
    cat = reconcile.load_catalog()
    aid, i = next((a, n) for a, m in sorted(cat.items()) for n, r in enumerate(m.get("routing") or [])
                  if isinstance(r, dict) and isinstance(r.get("module"), dict))
    cases = []
    bad = copy.deepcopy(cat)
    bad[aid]["routing"][i]["module"]["name"] = {"en": "Network", "he": "רשת"}
    cases.append(("a tile's name written as an {en, he} object", bad, f"{aid}: field 'routing'[{i}].module.name must be string"))
    bad = copy.deepcopy(cat)
    bad[aid]["title"] = "a plain string"
    cases.append(("a title written as a plain string", bad, f"{aid}: field 'title' must be"))
    failed = 0
    for name, doc, want in cases:
        errs = reconcile.validate(doc)[0]
        ok = any(e.startswith(want) for e in errs)
        failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name} -> {next((e for e in errs if e.startswith(want)), errs[:1] or 'accepted')}")
    clean = reconcile.validate(cat)[0]
    failed += bool(clean)
    print(f"  {'ok  ' if not clean else 'FAIL'} the catalog as it is: {len(cat)} manifests, {len(clean)} refused")
    print("manifest-lint self-test:", "PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if "--self-test" in sys.argv:
    sys.exit(self_test())

run = subprocess.run([sys.executable, str(REPO / "platform/manager/reconcile.py"), "validate"],
                     capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
said = (run.stdout + run.stderr).strip()
if run.returncode:
    print("G73 FAIL — the compiler refuses a manifest, so every render on this commit fails:\n" + said)
    sys.exit(1)
print("G73 PASS — " + (said.splitlines() or ["validated"])[-1][:110])
