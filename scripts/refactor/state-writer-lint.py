#!/usr/bin/env python3
"""state-writer-lint — gate G33: platform.state.yaml has exactly one writer.

    python3 scripts/refactor/state-writer-lint.py [--self-test]

`platform.state.yaml` is the desired state of the whole platform: which apps exist and whether each
is enabled, disabled or archived. It had FOUR writers — the CLI, the control plane, the compiler and
a migration script — and they did not agree on the shape they wrote. Two spellings resulted:

    browser42: { enabled: false }              # boolean
    browser42: { state: enabled, by: user }    # disposition + provenance

which is why `disposition()` has to accept both, and why three inline parsers in app.py drifted from
it (task A1). One writer, one shape, one parser — otherwise every reader needs to know the history
of every writer.

The writer is `reconcile.set_disposition()`. Everything else asks it, including the control plane,
which shells out to `reconcile.py set-state` rather than opening the file.

WHAT COUNTS AS WRITING: opening the state file for write/append, or handing it to a mutating tool
(`sed -i`, `yq -i`, a shell redirect). Reading it is fine and common — the compiler, the CLI and the
control plane all read it constantly.
"""
import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
STATE = "platform.state.yaml"

#: The one writer, plus this gate.
EXEMPT = {
    "platform/manager/reconcile.py",              # set_disposition() — THE writer
    "scripts/refactor/state-writer-lint.py",      # this file
}

SKIP = ("/node_modules/", "/_archive/", "/attic/", "/legacy/", "/.git/", "/ci-artifacts/",
        "/issues/", "/.refactor/", "/_v2_precentralize_bak/")

#: python: open(<…state file…>, "w"|"a"|"r+"), pathlib write_text/write_bytes, yaml.dump to it
PY_WRITE = re.compile(
    # `.*?` not `[^)]*` — the path is usually built with os.path.join(REPO, "platform.state.yaml"),
    # and a nested paren stopped a [^)] class dead, so the commonest spelling went unnoticed.
    r"""open\s*\(.*?platform\.state\.yaml.*?["'][wax+]|"""
    r"""(?:STATE|state_path|STATE_FILE)\s*\.\s*write_(?:text|bytes)\s*\(|"""
    r"""open\s*\(\s*(?:STATE|STATE_FILE)\s*,\s*["'][wax+]""")
#: shell: in-place editors and redirects aimed at the state file
SH_WRITE = re.compile(
    r"""(?:sed\s+-i|yq\s+(?:-i|--inplace)|tee)\b[^\n]*platform\.state\.yaml|"""
    r""">>?\s*["']?[^\s"']*platform\.state\.yaml""")


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    for rel in out.stdout.splitlines():
        rel = rel.strip()
        if rel and rel not in EXEMPT and not any(s in f"/{rel}" for s in SKIP):
            yield rel


#: A NAME is not a file. `STATE` / `STATE_FILE` / `state_path` are matched by name above, and a
#: module may well keep a state file of its own under that name (browser42's logins:
#: `STATE_FILE = os.path.join(DATA, "browser-logins.json")`, reported here as a second writer of the
#: platform's state for as long as it has existed). So the name's own assignment in the same file is
#: read: when it names another file, a write through it is that module's business.
NAMED = re.compile(r"^(STATE|STATE_FILE|state_path)\s*=\s*(.+)$", re.M)


def scan_text(rel, text):
    if rel.endswith((".md", ".txt")) or "/ai/context/" in f"/{rel}":
        return []
    elsewhere = {m.group(1) for m in NAMED.finditer(text) if STATE not in m.group(2)}
    out = []
    in_doc = False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if rel.endswith(".py") and s.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or not s or s.startswith("#"):
            continue
        code = line.split(" #", 1)[0]
        hit = PY_WRITE.search(code)
        if hit and STATE not in hit.group(0) and any(re.search(rf"\b{n}\b", hit.group(0)) for n in elsewhere):
            hit = None                          # written through a name this file points elsewhere
        if hit or SH_WRITE.search(code):
            out.append((rel, i, s[:104]))
    return out


def scan(overrides=None):
    overrides = overrides or {}
    findings = []
    seen = set()
    for rel in tracked():
        seen.add(rel)
        text = overrides.get(rel)
        if text is None:
            try:
                text = (REPO / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        findings += scan_text(rel, text)
    for rel, text in overrides.items():
        if rel not in seen:
            findings += scan_text(rel, text)
    return findings


SELF_TEST = [
    ("python opens it for write", "scripts/_p.py",
     'f = open("/repo/platform.state.yaml", "w")\n', True),
    ("python appends to it", "scripts/_p.py",
     'open(os.path.join(REPO, "platform.state.yaml"), "a").write(x)\n', True),
    ("sed -i on it", "scripts/_p.sh", 'sed -i "s/false/true/" platform.state.yaml\n', True),
    ("shell redirect into it", "scripts/_p.sh", 'echo x > platform.state.yaml\n', True),
    ("yq in place", "scripts/_p.sh", 'yq -i ".apps.x.enabled = true" platform.state.yaml\n', True),
    # reading is normal and must never be flagged
    ("python reads it", "scripts/_p.py", 'yaml.safe_load(open("platform.state.yaml"))\n', False),
    ("shell greps it", "scripts/_p.sh", 'grep -n browser42 platform.state.yaml\n', False),
    ("delegating to the writer", "scripts/_p.sh",
     'python3 platform/manager/reconcile.py set-state --app x --state enabled\n', False),
    ("a comment about writing it", "scripts/_p.sh",
     '# never sed -i platform.state.yaml — use set_disposition\n', False),
    # a name is not a file: the same spelling, pointing at the state file and at another one
    ("a STATE_FILE that IS the state file", "scripts/_p.py",
     'STATE_FILE = os.path.join(REPO, "platform.state.yaml")\nwith open(STATE_FILE, "w") as f: pass\n', True),
    ("a STATE_FILE of the module's own", "scripts/_p.py",
     'STATE_FILE = os.path.join(DATA, "browser-logins.json")\nwith open(STATE_FILE, "w") as f: pass\n', False),
    ("a STATE_FILE assigned nowhere in the file", "scripts/_p.py",
     'with open(STATE_FILE, "w") as f: pass\n', True),
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
    print(f"\nG33 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    findings = scan()
    if findings:
        print(f"G33 FAIL — {len(findings)} writer(s) of {STATE} besides reconcile.set_disposition():")
        for rel, i, s in findings:
            print(f"    {rel}:{i}")
            print(f"        {s}")
        print("\n  Desired state has ONE writer. Call it:")
        print("    python3 platform/manager/reconcile.py set-state --app <id> --state <disposition>")
        print("  Two writers means two shapes, and every reader then needs both.")
        return 1
    print(f"G33 PASS — {STATE} is written only by reconcile.set_disposition().")
    return 0


if __name__ == "__main__":
    sys.exit(main())
