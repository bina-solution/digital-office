#!/usr/bin/env python3
"""compile-lint — gate G12: every first-party Python file must parse.

    python3 scripts/refactor/compile-lint.py

The cheapest possible check, and it still caught five shipped files. An automated UTF-8 pass across
the tree inserted

    import sys as _sys
    if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

ABOVE `from __future__ import annotations`, which Python requires to be the first statement. Every
one of scripts/ui-coverage/{inventory,capture,compose_map,resolve_params,seed_demo,test_guards}.py
then failed to parse — so ui-map ran degraded — and nothing noticed, because no gate ever asked the
most basic question: does the file even compile? G1 diffs config, G9/G10 read source as text, G0
checks paths. None of them parse the Python.

WARNINGS ARE ERRORS HERE. What the compiler warns about today it refuses tomorrow: an invalid
escape sequence (a backslash-s in a string that is not raw) was silent, became a DeprecationWarning, is a
SyntaxWarning on 3.12 and is announced as a SyntaxError. Three literals had one on 2026-10-07 —
JavaScript kept in ordinary strings in apps/domains — which would have taken that app's import
down on the interpreter upgrade that turns the page. They are raw strings now, and this gate
compiles with every warning promoted, so the next one fails here instead of there.

`legacy/` is excluded: archived, sometimes-py2 code kept for reference, not shipped or run.
(`attic/` was the same thing and is gone — its one live tenant, feature-validation, moved here.)
"""
import pathlib, subprocess, sys, warnings

REPO = pathlib.Path(__file__).resolve().parents[2]
EXCLUDE_PREFIXES = ("legacy/",)


def tracked_py():
    """Tracked .py files, EXCLUDING symlinks (git mode 120000).

    A symlink is not source. On a Windows checkout git materialises one as a small text file
    containing the TARGET PATH, so `compile()` sees `../balance-sheet-extraction/validate-feature.py`
    and reports `line 1: invalid syntax` — a real parse failure for a file that contains no Python
    and whose target parses fine.

    This surfaced the moment feature-validation moved from the archive (excluded) into `apps/`
    (scanned): two of its three tracked symlinks are `.py`. Excluding the directory would have
    silenced a whole live app tree to hide a checkout artefact, so the gate learns what a symlink is
    instead. `-s` gives the mode; asking git rather than the filesystem is the same rule that made
    G31's executable-hook check correct — on WSL's /mnt/c the filesystem does not preserve either.
    """
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-s", "*.py"],
                         capture_output=True, text=True).stdout
    files = []
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) != 4 or parts[0] == "120000":
            continue
        rel = parts[3].strip()
        if rel and not rel.startswith(EXCLUDE_PREFIXES):
            files.append(rel)
    return files


def tracked_issue_yaml():
    """The issue tracker's own files. Same question this gate already asks of Python - DOES IT
    PARSE - so it is answered here rather than in a 70th lint nobody reads.

    WHY IT IS WORTH ASKING. Measured 2026-08-24: FOUR of the 63 files in issues/ did not parse, and
    had not for some time. An issue file that yaml.safe_load cannot read is invisible to every tool
    that reads the tracker, while still looking completely fine in an editor and in review - which
    is why nobody noticed. Two causes, both silent: a block scalar whose indentation is pinned by
    its first line (a later, less-indented paragraph falls out of the block), and a mapping key
    sitting at the same indent as the sequence items above it.

    Four MORE were added the same day by a session adopting files from another clone, so this is
    not a historical one-off - it recurs whenever someone hand-writes one.
    """
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-s", "issues/*.yaml"],
                         capture_output=True, text=True).stdout
    files = []
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        # Same symlink rule as tracked_py above, for the same reason.
        if len(parts) != 4 or parts[0] == "120000":
            continue
        rel = parts[3].strip()
        if rel:
            files.append(rel)
    return sorted(files)


def main() -> int:
    broken = []
    files = tracked_py()
    for rel in files:
        f = REPO / rel
        try:
            # compile(), NOT ast.parse(): ast.parse accepts a MISPLACED `from __future__`, which is
            # the exact bug this gate exists for. compile() enforces the same rules the interpreter
            # does at import time, so it fails on everything a real run would.
            with warnings.catch_warnings():
                warnings.simplefilter("error")      # the compiler turns a promoted warning into a SyntaxError
                compile(f.read_text(encoding="utf-8"), rel, "exec")
        except SyntaxError as e:
            broken.append((rel, e.lineno, e.msg))
        except (UnicodeDecodeError, OSError) as e:
            broken.append((rel, None, str(e)))

    # The tracker, same question. yaml is guarded: if PyYAML is absent this gate must not turn a
    # missing optional dependency into a red, so it says so and skips rather than failing.
    yaml_files, yaml_note = [], ""
    try:
        import yaml  # noqa: PLC0415
        yaml_files = tracked_issue_yaml()
        for rel in yaml_files:
            try:
                yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                mark = getattr(e, "problem_mark", None)
                broken.append((rel, (mark.line + 1) if mark else None,
                               getattr(e, "problem", str(e))))
            except (UnicodeDecodeError, OSError) as e:
                broken.append((rel, None, str(e)))
    except ImportError:
        yaml_note = " (PyYAML absent — issue files NOT checked)"

    if not broken:
        print(f"G12 PASS — all {len(files)} first-party Python file(s) compile without a warning and "
              f"{len(yaml_files)} issue file(s) parse.{yaml_note}")
        return 0

    print(f"G12 FAIL — {len(broken)} file(s) do not parse, or compile only with a warning. A Python "
          f"file here would crash on import (a warned one: on a coming interpreter); an issue file is "
          f"invisible to every tool that reads the tracker:")
    for rel, line, msg in broken:
        where = f":{line}" if line else ""
        print(f"  {rel}{where}: {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
