#!/usr/bin/env python3
"""batch_files — the `"comment": "@<file>"` of a `tasks batch` line, read on the caller's machine.

    python3 batch_files.py <actions.jsonl>

hooks/tasks reads `batch @<file>` and `--comment @<file>` before the applier runs, because the applier runs
in a container (or on the herd's hub) that cannot see the caller's files. A batch LINE's comment was never
read: it reached tasks.py as `--comment @<file>` and was posted as its path (issues/a-comment-given-as-at-
file-is-posted-as-the-path-…). This reads each such file, relative to where the caller ran.

Out (stdout): nothing when no line names a file; else the path of a copy (mode 600) whose lines carry the
files' text. A file that is missing: exit 2 with the line number and the path, and nothing is sent. Lines
that are not JSON objects are copied as they are; the applier says what is wrong with them.
"""
import json
import os
import re
import sys
import tempfile

AT_FILE = re.compile(r"@\S+")


def resolve(text: str) -> tuple[str, int]:
    """(the actions with each `@<file>` comment replaced by the file's text, how many were read)."""
    out, read = [], 0
    for n, line in enumerate(text.lstrip("﻿").split("\n"), 1):
        try:
            act = json.loads(line) if line.strip() else None
        except ValueError:
            act = None
        c = act.get("comment") if isinstance(act, dict) else None
        if isinstance(c, str) and AT_FILE.fullmatch(c.strip()):
            path = c.strip()[1:]
            if not os.path.isfile(path):
                raise FileNotFoundError(f"line {n}: comment {c.strip()}: no such file")
            with open(path, encoding="utf-8") as f:
                act["comment"] = f.read()
            if not act["comment"].strip():      # tasks.py drops an empty comment without a word
                raise FileNotFoundError(f"line {n}: comment {c.strip()}: the file is empty")
            line = json.dumps(act, ensure_ascii=False)
            read += 1
        out.append(line)
    return "\n".join(out), read


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: batch_files.py <actions.jsonl>")
        return 2
    with open(argv[0], encoding="utf-8") as f:
        text = f.read()
    try:
        resolved, read = resolve(text)
    except FileNotFoundError as e:
        print(e)
        return 2
    if not read:
        return 0
    fd, path = tempfile.mkstemp(prefix="pln-batch-", suffix=".jsonl")   # mkstemp: mode 600
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(resolved)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
