#!/usr/bin/env python3
"""The drive API's answer, one line per file: created | name | link (DGO-948).

The drive recipes pipe into it — `curl -s "http://drive:8975/api/search?q=…" | python3
apps/drive/operatives/files.py`, or the same path through `./bbox remote <office> <alias> "…"`, whose first
line (`HTTP <status>  GET <url>`) it skips. An answer that holds no file list (an error, a refusal,
nothing at all) is printed as it came and exits 1, so nobody is told "no such file" when the drive did
not answer; an empty list is said as "0 files".
"""
import json
import sys

SHOWN = 600   # how much of an answer that is not a file list is printed
MOST = 10     # files listed; the rest are counted


def field(value, most=None):
    """One column of a line: a file is named by whoever made it, and a name «a | https://elsewhere» or one
    with a line break would forge a column or a line, so it stays one line, its `|` made `¦`."""
    flat = " ".join(str(value if value is not None else "").split()).replace("|", "¦")
    return flat[:most] if most else flat


def lines(text):
    """(the lines to print, the exit code) for what the drive API printed."""
    head = ""
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list):
        said = text.strip()[:SHOWN] or "(the drive API answered nothing)"
        return [x for x in (head.strip(), said) if x], 1
    if not files:
        return ["0 files"], 0
    out = []
    for f in files[:MOST]:
        f = f if isinstance(f, dict) else {}
        out.append(" | ".join((field(f.get("created") or f.get("modified"), 16), field(f.get("name"), 80),
                               field(f.get("link") or f.get("id")))))
    if len(files) > MOST:
        out.append(f"… and {len(files) - MOST} more")
    return out, 0


def main():
    printed, code = lines(sys.stdin.read())
    print("\n".join(printed))
    return code


if __name__ == "__main__":
    sys.exit(main())
