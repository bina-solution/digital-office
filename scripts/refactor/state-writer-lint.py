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

A FIXTURE IS EXEMPT BY NAME, NOT BY WHAT IT SAYS. `scripts/test_follow.sh` plays a merge of this file
— what `dgo-stable` declares against what an office declares — in throwaway repos it makes with
`mktemp`, so its six writes are to state files it made itself and no office's own file is opened
there. That exemption is the FILE, declared below with this reason, and it is not a licence to write
the real one: a write in that file aimed at a path it did not make (absolute, `~`, the checkout's own
root, or one that climbs out with `../`) is still a finding. Blanket-exempting the file, which is what
a reader would have concluded from the six findings it reported on 2026-11-03, would have hidden the
one thing this gate exists for.
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

#: A test whose fixtures ARE a state file, named one file at a time and never by a pattern: the
#: exemption is a decision someone made about THIS file, and it does not extend to a test written
#: tomorrow or to `*test*` in general. The reason lives here; the limit (a file it MADE, not the
#: office's) is enforced in scan_text — see MADE_HERE.
FIXTURE = {
    # follow.sh's test (r030-201): it plays what dgo-stable and an office each DECLARE by editing the
    # platform.state.yaml of throwaway repos it makes under mktemp, which is what a merge of that file is
    # tested against. No office's own file is opened there.
    "scripts/test_follow.sh",
}

#: A state file a fixture MADE ITSELF: a bare relative path (after its own `cd` into its temp repo) or
#: one built from a variable (`${T}/…`, "${O}/…`, "$STUB/…"). Anything aimed at a path it did not make
#: — absolute, `~`, the checkout's root, or one that climbs out with `../` — is the office's file.
MADE_HERE = re.compile(r"^(?!/|~)(?!\$\{?(?:REPO|REPO_ROOT|PWD|OLDPWD|HOME)\b)(?!\.\./)")


def stated_target(line: str) -> str:
    """The path token in one finding line that names the state file, or '' when none does.

    One form for both shapes of a finding: a redirect (`> platform.state.yaml`) and a mutating tool
    (`sed -i … platform.state.yaml`, `tee …/platform.state.yaml`) both leave the path as a token that
    ENDS with the file's name. Quotes and separators are split off, so `"${O}/platform.state.yaml"`
    comes back as `${O}/platform.state.yaml` — the string the MADE_HERE test then judges.
    """
    toks = re.split(r"""[\s"'`;|&<>()]+""", line)
    return next((t for t in toks if t.endswith(STATE)), "")


SKIP = ("/node_modules/", "/_archive/", "/attic/", "/legacy/", "/.git/", "/ci-artifacts/",
        "/issues/", "/.refactor/", "/_v2_precentralize_bak/")

#: python: open(<…state file…>, "w"|"a"|"r+"), pathlib write_text/write_bytes, yaml.dump to it
PY_WRITE = re.compile(
    # `.*?` not `[^)]*` — the path is usually built with os.path.join(REPO, "platform.state.yaml"),
    # and a nested paren stopped a [^)] class dead, so the commonest spelling went unnoticed.
    r"""open\s*\(.*?platform\.state\.yaml.*?["'][wax+]|"""
    # `\b`: a NAME, whole — `DEFAULT_STATE` is platform.state.default.yaml (DGO-616's ensure_state() copies it into
    # place), another file, and without the boundary its write read as one to the office's state (2026-11-10)
    r"""\b(?:STATE|state_path|STATE_FILE)\s*\.\s*write_(?:text|bytes)\s*\(|"""
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
    # prose, and markup that never runs: an SVG diagram's `<text>platform.state.yaml</text>` read as a shell redirect
    # (`>platform.state.yaml`) — the docs' two diagrams, 2026-11-11 (the release lane's pre-cut sweep); a paper's HTML,
    # `<code>platform.state.yaml</code>` in a figure's caption — DGO-2045's, which kept batch 81 red on 2026-11-19
    if rel.endswith((".md", ".txt", ".svg", ".html", ".htm")) or "/ai/context/" in f"/{rel}":
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
            if rel in FIXTURE:
                # A named fixture may write a state file it MADE — and only that. A target it did not
                # make (or no target the line can be read for) is the office's own file, which no
                # exemption covers, so it is reported like any other writer.
                t = stated_target(code)
                if t and MADE_HERE.match(t):
                    continue
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
    ("a diagram names it (SVG markup, never run)", "docs/public/diagrams/_d.svg",
     '<text x="1" y="2" class="mono">platform.state.yaml</text>\n', False),
    ("…and the same line in a shell file still is a redirect", "scripts/_p.sh",
     '<text x="1" y="2" class="mono">platform.state.yaml</text>\n', True),
    ("a paper names it (HTML markup, never run)", "research_notes/_paper/_p.html",
     '<figcaption>its desired state (<code>platform.state.yaml</code>, block <code>remote:</code>)</figcaption>\n', False),
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
    # a name is matched WHOLE: the module's STATE is caught, its DEFAULT_STATE (the product default) is another file
    ("the compiler's STATE written through a module", "scripts/_p.py",
     'rc.STATE.write_text(STATE_TEXT, encoding="utf-8")\n', True),
    ("DEFAULT_STATE is the product default, not the state", "scripts/_p.py",
     'rc.DEFAULT_STATE.write_text(STATE_TEXT, encoding="utf-8")\n', False),
    # a NAMED fixture writes the state file of a repo it made — and is caught writing the real one
    ("a fixture writes its own temp repo's state file", "scripts/test_follow.sh",
     'echo x > platform.state.yaml\n', False),
    ("a fixture writes it after cd-ing into its temp repo", "scripts/test_follow.sh",
     'sed -i "s/1/2/" "${O}/platform.state.yaml"\n', False),
    ("a fixture writes the OFFICE's state file", "scripts/test_follow.sh",
     'sed -i "s/false/true/" /root/digital-office/platform.state.yaml\n', True),
    ("a fixture writes it through the checkout's root", "scripts/test_follow.sh",
     'echo x > "${REPO}/platform.state.yaml"\n', True),
    ("a fixture climbs out with a relative path", "scripts/test_follow.sh",
     'echo x > ../platform.state.yaml\n', True),
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
