#!/usr/bin/env python3
"""bbox-caller-lint — every place that calls `bbox` as the office's CLI, counted mechanically (DGO-1235).

    python3 scripts/refactor/bbox-caller-lint.py               # counts per shape, files read, the top files
    python3 scripts/refactor/bbox-caller-lint.py --list        # every hit: path:line  shape  text
    python3 scripts/refactor/bbox-caller-lint.py --check       # FAIL when a shape counts MORE than the baseline
    python3 scripts/refactor/bbox-caller-lint.py --self-test

WHY. The CLI is renamed bbox → dgo (DGO-1236 and after). AGENTS.md rule 8: before a contract is tightened, every
caller is enumerated mechanically, by a tool that says how many files it read — never from memory or a grep someone
ran once (counted 2026-11-03 by hand: CLI 1,261, the socket 213, bbox.cmd 135 — that hand count was `./bbox`
alone; with bare `bbox <verb>` in prose and help text it is about five times that, which is why a tool counts).

WHAT IS COUNTED, by shape (one line may hold several) — MENTIONS of the CLI, not only commands that run it: a
sentence telling a person to type `bbox run` is a line the rename must change too:
  cli       `./bbox`, or `bbox <verb>` — the word `bbox` standing alone, followed by a lowercase word
  cmd       `bbox.cmd` (the Windows entry)
  socket    `bbox-docker.sock` (the engine's socket the guest exposes)
  home      `~/.bbox`, `$HOME/.bbox`, `${HOME}/.bbox` (the CLI's own state)
  func      `bbox_<name>` — lib.sh's functions and every caller of one (also the `bbox_agent` package's imports)
  path      the checkout's `bbox` reached by a path: "${REPO_ROOT}/bbox" run, ../bbox, /workspace/office/bbox,
            f"{p}/bbox" — the callers `./bbox` cannot see (second reader, 2026-11-10)
WHAT IS NOT: a bounding box — OCR code in apps/apitools says `bbox_*` for a rectangle, so the `func` shape alone is
skipped there (its hooks still call `./bbox apitools …`); legacy/ (an archive nobody runs); a state directory named
bbox (/var/lib/bbox, ~/.config/bbox); and `bbox` followed by `=`, `:`, `[`, `)` or a quote (a value, not the CLI).
NOT YET COUNTED, decided: the `BBOX_*` environment variables (≈700 lines) — they are settings, renamed by their own
step of DGO-1236 with an alias, and counting them here would drown the callers; Hebrew-prefixed forms (`ל-bbox run`)
and the bare noun (`bbox` in backticks, «bbox is…», `bbox:701` line references) are prose a person reads, rewritten
with the docs; the log tag `[bbox]` (LOG_TAG, parsed by converge.py and the Android app) and the Lima instance's
default name (BBOX_VM_NAME) are names of their own, renamed in their own steps. The 2026-11-03 hand count may have
swapped its socket and bbox.cmd labels (213/135 there; 184/213 here).
It reads the WORKING TREE of the tracked paths: run it in a clean worktree for a baseline — in a shared checkout
it also counts other writers' uncommitted edits.

A MEASURE NOW, A RATCHET LATER. Until DGO-1236 gives the office `dgo` as its name, every new brief still writes
`./bbox`, so a gate that refused a higher count would turn every lane red for doing the right thing. Run as it is,
this prints and exits 0; `--check` compares with scripts/refactor/bbox-caller-baseline.json (may only fall) and is
what the rename wires into gates.sh, with a number of its own, once the counts start to fall. Until then it is in
run-gates.py's NOT_A_GATE, said there.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

# G10: this file holds Hebrew and quotes callers' lines back; python on Windows would write them in the console's
# codepage and die on its own output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "scripts" / "refactor" / "bbox-caller-baseline.json"
#: the archive nobody runs
SKIP_PREFIXES = ("legacy/",)
#: OCR code, where `bbox_<name>` is a bounding box's function — only THAT shape is skipped there: the same app's
#: hooks and scripts call `./bbox apitools …` and default to `bbox-docker.sock` like any other (second reader)
FUNC_SKIP_PREFIXES = ("apps/apitools/",)
#: this tool and its baseline name every shape on purpose
SELF = {"scripts/refactor/bbox-caller-lint.py", "scripts/refactor/bbox-caller-baseline.json"}
SHAPES = {
    "cli": re.compile(r"(?:(?<![\w./-])\./bbox(?![\w.-])|(?<![\w./$-])bbox(?=[ \t]+[a-z][a-z0-9-]*\b)(?![ \t]+(?:is|of|in|the|a|an|for|and|or|to|from|with|that|which)\b))"),
    "cmd": re.compile(r"(?<![\w-])bbox\.cmd\b"),
    "socket": re.compile(r"bbox-docker\.sock"),
    "home": re.compile(r"(?:~|\$HOME|\$\{HOME\})/\.bbox\b"),
    "func": re.compile(r"(?<![\w.])bbox_[a-z][a-z0-9_]*"),
    # the checkout's own `bbox` reached by a PATH: "${REPO_ROOT}/bbox" run, $(dirname …)/bbox, ../bbox,
    # /workspace/office/bbox "$@", f"{p}/bbox" — the callers `./bbox` cannot see. A state directory named
    # bbox (/var/lib/bbox, /var/backups/bbox, ~/.config/bbox) is not the CLI and is not counted.
    # …and by a language's own join: filepath.Join(d, "bbox"), os.path.join(root, "bbox"), Path(r, "bbox"),
    # h.root+"/bbox", root / "bbox" — the checkout finders and hand-offs that break silently at a rename (the
    # second reader's v2 FAIL: 38 such lines). The Lima instance directory (…/lima/bbox) and a temp dir named bbox
    # are state, not the CLI.
    "path": re.compile(r"(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\{[a-z_]+\}|\)|\.\.|/(?!lib/|backups/|\.?config/|\.?lima/|tmp/)"
                       r"[A-Za-z0-9_.-]+)/bbox(?![\w.-])"
                       r"""|(?:join\([^()]*?,\s*|Join\([^()]*?,\s*|Path\([^()]*?,\s*|[\w)]\s*/\s*|\+\s*)["']/?bbox["']"""),
}


def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def scan_text(text: str):
    """[(line number, shape, the line)] for one file's text."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for shape, rx in SHAPES.items():
            for _ in rx.finditer(line):
                hits.append((n, shape, line.strip()[:160]))
    return hits


#: what a scan did with every tracked path — so the totals add up to `git ls-files` (AGENTS.md rule 8: check
#: what the tool scanned, not only what it found)
SKIPPED = Counter()


def scan(paths=None, root: Path = REPO):
    """(files read, Counter per shape, Counter per file, every hit); SKIPPED says what was not read, and why."""
    files, per_shape, per_file, every = 0, Counter(), Counter(), []
    SKIPPED.clear()
    for rel in (paths if paths is not None else tracked()):
        if rel in SELF:
            SKIPPED["this tool"] += 1
            continue
        if rel.startswith(SKIP_PREFIXES):
            SKIPPED["legacy/"] += 1
            continue
        p = root / rel
        try:
            raw = p.read_bytes()
        except OSError:
            SKIPPED["unreadable"] += 1
            continue
        if b"\0" in raw[:8192]:
            SKIPPED["binary"] += 1                          # a binary file holds no caller
            continue
        files += 1
        for n, shape, line in scan_text(raw.decode("utf-8", "replace")):
            if shape == "func" and rel.startswith(FUNC_SKIP_PREFIXES):
                continue                                    # OCR's bounding box, not lib.sh
            per_shape[shape] += 1
            per_file[rel] += 1
            every.append((rel, n, shape, line))
    return files, per_shape, per_file, every


def self_test() -> int:
    fails = 0

    def check(name, ok, got=""):
        nonlocal fails
        print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f" -> {got}"))
        fails += 0 if ok else 1

    old = ("./bbox run\nbbox apps enable mail\nbbox.cmd run\n/run/bbox-docker.sock\n~/.bbox/state\n"
           "bbox_engine_up \"$@\"\nsource lib.sh; bbox_say hi\n")
    got = Counter(s for _, s, _ in scan_text(old))
    check("every shape of the old name is found",
          got == Counter({"cli": 2, "cmd": 1, "socket": 1, "home": 1, "func": 2}), dict(got))
    renamed = old.replace("bbox", "dgo")
    check("the same text renamed to dgo counts 0", not scan_text(renamed), scan_text(renamed))
    boxes = ("x0, y0 = word.bbox\nbboxes = page.bboxes\nbbox = (1, 2, 3, 4)\nrow['bbox']\nbbox: [1,2]\n"
             "draw(bbox)\nthe bbox is a rectangle\n")
    check("a bounding box is not a caller", not scan_text(boxes), scan_text(boxes))
    paths = ('exec "${REPO_ROOT}/bbox" run "$@"\n"$REPO_ROOT/bbox" via hp\n"$(dirname "$0")/../../bbox" run\n'
             'exec /workspace/office/bbox "$@"\nf"grep -q x {p}/bbox"\n')
    got = Counter(s for _, s, _ in scan_text(paths))
    check("the checkout's bbox reached by a path is a caller (5 shapes)", got == Counter({"path": 5}), dict(got))
    joins = ('isFile(filepath.Join(d, "bbox"))\nos.path.join(REPO, "bbox")\nPath(root, "bbox")\n'
             'cmd := h.root + "/bbox"\nexe = repo / "bbox"\n')
    got = Counter(s for _, s, _ in scan_text(joins))
    check("the checkout's bbox reached by a language's join is a caller (5 shapes)", got == Counter({"path": 5}),
          dict(got))
    state = ("/var/lib/bbox/state\n/var/backups/bbox\n~/.config/bbox/agent.json\nscripts/bbox_agent/x.py\n"
             "~/.lima/bbox/lima.yaml\nBBOX_TMP=/ev/mnt/tmp/bbox\n")
    got = Counter(s for _, s, _ in scan_text(state))
    check("a state directory named bbox, and the bbox_agent package's folder, are not a path caller",
          "path" not in got, dict(got))
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "apps" / "apitools" / "hooks").mkdir(parents=True)
        (root / "apps" / "apitools" / "ocr.py").write_text("def bbox_union(a): pass\n")
        (root / "apps" / "apitools" / "hooks" / "test").write_text('"${REPO_ROOT}/bbox" apitools ocr\n./bbox run\n')
        (root / SKIP_PREFIXES[0]).mkdir()
        (root / SKIP_PREFIXES[0] / "old.sh").write_text("./bbox run\n")
        (root / "doc.md").write_text("Run `./bbox run`, then `bbox help`.\n")
        # the skipped file is made and named from SKIP_PREFIXES itself: the case tests the skip through the constant,
        # and the fixture (a file in a temporary root) is no reference into the real archive for G34 to count
        files, per_shape, _, _ = scan(["apps/apitools/ocr.py", "apps/apitools/hooks/test", SKIP_PREFIXES[0] + "old.sh",
                                       "doc.md"], root)
        check("apitools' OCR bbox_ is skipped but its hooks' callers count; legacy/ is skipped; a doc is read",
              files == 3 and per_shape == Counter({"cli": 3, "path": 1}) and SKIPPED["legacy/"] == 1,
              (files, dict(per_shape), dict(SKIPPED)))
    print("bbox-caller-lint self-test: " + ("PASS" if not fails else f"{fails} FAILED"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="every caller of bbox as the CLI, counted (DGO-1235)")
    ap.add_argument("--list", action="store_true", help="every hit, one per line")
    ap.add_argument("--check", action="store_true", help="fail when a shape counts more than the baseline")
    ap.add_argument("--write-baseline", action="store_true", help="write today's counts as the baseline")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    files, per_shape, per_file, every = scan()
    if files == 0:
        print("bbox-caller-lint — FAIL: no file was read; a count over nothing proves nothing")
        return 1
    if a.list:
        for rel, n, shape, line in every:
            print(f"{rel}:{n}  {shape:6}  {line}")
    total = sum(per_shape.values())
    print(f"bbox-caller-lint — {files} tracked text file(s) read; {total} caller(s) in {len(per_file)} file(s): "
          + ", ".join(f"{s} {per_shape.get(s, 0)}" for s in SHAPES))
    every_path = len(tracked())                          # asked again, not taken from the scan's own count
    seen = files + sum(SKIPPED.values())
    print(f"  not read: {sum(SKIPPED.values())} (" + ", ".join(f"{k} {v}" for k, v in sorted(SKIPPED.items()))
          + f") — read + not read = {seen}; `git ls-files` says {every_path}")
    if seen != every_path:
        print("bbox-caller-lint — FAIL: the scan did not account for every tracked path")
        return 1
    if not a.list:
        for rel, c in per_file.most_common(10):
            print(f"  {c:5}  {rel}")
    counts = {s: per_shape.get(s, 0) for s in SHAPES}
    if a.write_baseline:
        BASELINE.write_text(json.dumps({"counts": counts, "files_read": files, "files_with_callers": len(per_file)},
                                       indent=2) + "\n", encoding="utf-8")
        print(f"  baseline written: {BASELINE.relative_to(REPO)}")
    if a.check:
        try:
            doc = json.loads(BASELINE.read_text(encoding="utf-8"))
            base = doc["counts"]
        except (OSError, ValueError, KeyError):
            print(f"bbox-caller-lint — FAIL: no readable baseline at {BASELINE.relative_to(REPO)}")
            return 1
        # a scan that quietly reads fewer files lowers every count and would pass: the files read are held too —
        # and a baseline that does not say how many it read cannot be held to it
        if "files_read" not in doc:
            print(f"bbox-caller-lint — FAIL: {BASELINE.relative_to(REPO)} does not say how many files it read")
            return 1
        if files < int(doc["files_read"]) * 0.95:
            print(f"bbox-caller-lint — FAIL: {files} file(s) read, the baseline read {doc.get('files_read')} — "
                  f"a count over fewer files proves nothing")
            return 1
        up = {s: (base.get(s, 0), counts[s]) for s in SHAPES if counts[s] > base.get(s, 0)}
        if up:
            print("bbox-caller-lint — FAIL: more callers than the baseline (it may only fall): "
                  + ", ".join(f"{s} {b} → {c}" for s, (b, c) in up.items()))
            return 1
        print("bbox-caller-lint — PASS: no shape counts more than the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
