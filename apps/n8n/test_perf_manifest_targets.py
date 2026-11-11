#!/usr/bin/env python3
"""test_perf_manifest_targets — every knob in apps/n8n/perf-manifest.json aims at a node that exists (DGO-433).

    python3 apps/n8n/test_perf_manifest_targets.py            (the repo only; no office, no docker)

WHY. scripts/perf-profile-apply --stage is the only thing that delivers a profile's workflow knob, and
when the file or node it aims at is missing it prints one "skip" line inside a push and goes on. So
`perf_line_poll_s` aimed at indoxApiSupabase01 :: Poll Line Changes from 2026-08-16 until 2026-11-10. The
owner's order that day removed that poll (the drainer is the only initiator), and its workflow was retired.
Every profile's value for the knob applied to nothing, and nothing said so. This test says so, from the
blueprints, before a push.

WHAT. For each manifest entry:
- its `file` is a blueprint, `apps/<app>/blueprint/n8n/<stem>.workflow.ts`;
- that blueprint declares a node named `node`;
- some profile's `settings:` block in platform/profiles/perf-profiles.yml sets its `knob`. That block is all
  perf-profile-apply reads, so a knob no profile sets there is aimed at nothing from the other end.
- each entry's `node` is a NODE's own name, the `name:` inside an `@node({…})` decorator. A Set field, a
  credential or a string that reads the same does not count.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "apps" / "n8n" / "perf-manifest.json"
PROFILES = ROOT / "platform" / "profiles" / "perf-profiles.yml"
FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def blueprint_for(file_name):
    stem = file_name[:-len(".json")] if file_name.endswith(".json") else file_name
    hits = sorted(ROOT.glob(f"apps/*/blueprint/n8n/{stem}.workflow.ts"))
    return hits[0] if hits else None


def declares_node(src, node):
    """A NODE of that name: the `name:` inside an `@node({…})` decorator, not a credential's, a Set
    field's, or a string in code that happens to read the same."""
    for m in re.finditer(r"@node\(\{(.*?)\}\)", src, re.S):
        nm = re.search(r"\bname:\s*(['\"])(.*?)\1", m.group(1))
        if nm and nm.group(2) == node:
            return True
    return False


def settings_keys(profiles_text):
    """Every key under a profile's `settings:` block. perf-profile-apply reads only prof['settings'],
    so a knob anywhere else in the file (under `env:`, say) applies to nothing."""
    keys, indent = set(), None
    for line in profiles_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lead = len(line) - len(line.lstrip())
        if re.match(r"^\s+settings:\s*(#.*)?$", line):
            indent = lead
            continue
        if indent is not None:
            if lead <= indent:
                indent = None
            else:
                m = re.match(r"^\s+([A-Za-z0-9_]+):", line)
                if m:
                    keys.add(m.group(1))
    return keys


def main():
    entries = [e for e in json.loads(MANIFEST.read_text(encoding="utf-8")) if "file" in e]
    check(len(entries) > 0, f"the manifest lists {len(entries)} knob target(s) (an empty read checks nothing)")
    settings = settings_keys(PROFILES.read_text(encoding="utf-8"))
    check(len(settings) > 0, f"read {len(settings)} settings key(s) from the profiles (an empty read checks nothing)")
    for e in entries:
        where = f"{e['knob']} -> {e['file']} :: {e['node']}"
        bp = blueprint_for(e["file"])
        check(bp is not None, f"{where}: {e['file']} is a blueprint"
              + (f" ({bp.relative_to(ROOT)})" if bp else " - no apps/*/blueprint/n8n holds it (retired?)"))
        if bp is not None:
            check(declares_node(bp.read_text(encoding="utf-8"), e["node"]),
                  f"{where}: the blueprint declares that node")
        check(e["knob"] in settings, f"{where}: a profile's settings: block sets {e['knob']}")

    # The finder must be able to fail: the entry DGO-433 removed is caught by it.
    gone = {"file": "indoxApiSupabase01.json", "node": "Poll Line Changes"}
    check(blueprint_for(gone["file"]) is None,
          "self-check: the retired indoxApiSupabase01.json target is reported as no blueprint")
    real = blueprint_for("indoxV2ActionsBS01.json")
    check(real is not None and not declares_node(real.read_text(encoding="utf-8"), "No Such Node 0"),
          "self-check: a node name a blueprint does not declare is reported as missing")
    fake = ("@node({ id: 'a', name: 'Real Node', type: 'n8n-nodes-base.set' })\n"
            "X = { assignments: { assignments: [{ name: 'Only A Field', value: '=1' }] }, "
            "credentials: { postgres: { name: 'Only A Credential' } } };")
    check(declares_node(fake, "Real Node") and not declares_node(fake, "Only A Field")
          and not declares_node(fake, "Only A Credential"),
          "self-check: only a node's own name counts, not a Set field's or a credential's")
    yml = "p1:\n  env:\n    perf_only_in_env: 1\n  settings:\n    perf_real: 2\np2:\n  settings:\n    perf_other: 3\n"
    check(settings_keys(yml) == {"perf_real", "perf_other"},
          "self-check: a key under env: is not a setting; keys under every profile's settings: are")

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
