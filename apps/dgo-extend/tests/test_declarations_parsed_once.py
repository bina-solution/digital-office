#!/usr/bin/env python3
"""test_declarations_parsed_once — a peer's declaration is parsed again only when its file changes (DGO-2111, root 6).

Measured on the HP 2026-11-20: one catalog build called declarations() 23 times and spent 6.5 of its 11.3 s re-parsing
the same YAML, so a peer's pull missed its 8 s under load. This proves the copy is used for a settled file, renewed for
a changed one, never trusted for a file written just now (git's «racily clean», give.RACY_S), and never shared with a
caller who edits what it got.

Run: python3 apps/dgo-extend/tests/test_declarations_parsed_once.py   (needs PyYAML, as dgo-extend does)
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import converge as cv  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def settle() -> None:
    """Wait out give.RACY_S: a file's ctime is «now» after any write or utime, and only an older one is trusted."""
    import give
    time.sleep(give.RACY_S + 0.2)


def main() -> int:
    parses = {"n": 0}
    real = cv.yaml.safe_load

    def counting(text):
        parses["n"] += 1
        return real(text)

    cv.yaml.safe_load = counting
    try:
        with tempfile.TemporaryDirectory() as d:
            cv.DECL_DIR = Path(d)
            f = Path(d) / "hp-laptop.yaml"
            f.write_text("id: hp-laptop\nlabel: HP\n")
            settle()                                     # settled: ctime too (utime cannot age it: it moves ctime)
            getattr(cv, "_PARSED", {}).clear()           # (absent before the fix: then every read parses)
            first = cv.declarations()
            n1 = parses["n"]
            for _ in range(22):
                cv.declarations()
            check(n1 == 1 and parses["n"] == 1, f"23 reads of a settled file parse it once: {parses['n']}")
            first[0]["label"] = "edited by a caller"
            check(cv.declarations()[0]["label"] == "HP", "a caller's edit never reaches the copy")
            f.write_text("id: hp-laptop\nlabel: The HP\n")  # changed now: young, so read every time until settled
            check(cv.declarations()[0]["label"] == "The HP", "a changed file is read again")
            young = parses["n"]
            cv.declarations()
            check(parses["n"] == young + 1, "a file written just now is never trusted to its key (racily clean)")
            settle()
            cv.declarations()
            settled = parses["n"]
            cv.declarations()
            check(parses["n"] == settled, "once settled, it is the copy again")
            f.unlink()
            check(cv.declarations() == [], "a removed file is gone")
    finally:
        cv.yaml.safe_load = real
    print("PASS test_declarations_parsed_once" if not FAIL else "FAIL test_declarations_parsed_once")
    for x in FAIL:
        print("FAIL", x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
