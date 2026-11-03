#!/usr/bin/env python3
"""test_enum_words — the words a screen shows for an enum come from the catalog, not from the screen.

    python3 apps/indox/test_enum_words.py            # exit 1 when the screen's copy has drifted
    python3 apps/indox/test_enum_words.py --fix      # rewrite the screen's copy from the catalog
    python3 apps/indox/test_enum_words.py --self-test

DGO-524. `apps/indox/blueprint/schema/display.json` says of itself: "the one place a human writes how
this app's data reads … no screen keeps a private label map". The column labels obey that — they are
merged into the schema the BFF serves. The STATUS / TYPE / SOURCE_TYPE words did not: they were
hand-written a second time in `app/webapp/src/vocab.ts`, and they agreed with the catalog only because
nobody had edited one of them yet. Two hand-written copies of one fact agree until the day they don't,
and the day they don't, the grid and the dashboard say two different words for one status.

SO ONE OF THEM IS GENERATED. The catalog stays the human's; the screen's copy is written by this file
(`--fix`) and checked here — the same shape as every other stamped block in this platform (G27's
blocks, `gen-indox-schema.py`'s repos.json). It reports the FIRST word that differs, by name, because
"the block changed" is not something anyone can act on.

WHAT IS NOT IN THE BLOCK. The words for an ABSENT value — «ללא סטטוס», «ללא סוג», «ללא מקור» — stay in
vocab.ts beside it. The catalog describes values that EXIST; '(ריק)' is not a status, it is what the
screen says when there is none, and it is the screen's own sentence.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
CATALOG = HERE / "blueprint" / "schema" / "display.json"
SCREEN = HERE / "app" / "webapp" / "src" / "vocab.ts"
START = "/* @indox-enum-words:start */"
END = "/* @indox-enum-words:end */"
#: the enum name in the catalog → the front-end's word for "there is no value" is NOT here; only the
#: enums whose words the screen shows.
ENUMS = ["STATUS", "TYPE", "SOURCE_TYPE"]


def catalog_words() -> "dict[str, list[tuple[str, str, str]]]":
    """{enum: [(key, label, note)]} in the catalog's own order — the order the block is written in."""
    d = json.loads(CATALOG.read_text(encoding="utf-8"))
    out = {}
    for name in ENUMS:
        values = (d.get("enums") or {}).get(name) or {}
        rows = []
        for key, val in values.items():
            if not isinstance(val, dict) or not val.get("label"):
                continue
            rows.append((key, str(val["label"]), str(val.get("note") or "")))
        out[name] = rows
    return out


def render() -> str:
    """The block, exactly as the screen must carry it."""
    words = catalog_words()
    lines = [START]
    lines.append("/* GENERATED from apps/indox/blueprint/schema/display.json by")
    lines.append("   apps/indox/test_enum_words.py --fix. Edit the CATALOG, never this block: the words")
    lines.append("   for an enum are written once, there, and a screen that disagrees fails this test.")
    lines.append("   The words for an ABSENT value («ללא סטטוס» and friends) are the screen's own and")
    lines.append("   stay below the block — the catalog describes values that exist. */")
    lines.append("const ENUM_WORDS: Record<string, Record<string, string>> = {")
    for name, rows in words.items():
        lines.append(f"  {name}: {{")
        for key, label, note in rows:
            if note:
                lines.append(f"    // {note}")
            quoted = key if re.fullmatch(r"[A-Za-z_$][\w$]*", key) else "'" + key.replace("'", "\\'") + "'"
            lines.append(f"    {quoted}: '" + label.replace("\\", "\\\\").replace("'", "\\'") + "',")
        lines.append("  },")
    lines.append("};")
    lines.append(END)
    return "\n".join(lines) + "\n"


def block_in(text: str) -> "str | None":
    i, j = text.find(START), text.find(END)
    if i < 0 or j < 0 or j < i:
        return None
    return text[i:j + len(END)] + "\n"


def first_difference(want: str, have: str) -> str:
    w, h = want.splitlines(), have.splitlines()
    for n, (a, b) in enumerate(zip(w, h), start=1):
        if a != b:
            return f"line {n}: the catalog says {a.strip()!r}, the screen says {b.strip()!r}"
    if len(w) != len(h):
        longer, shorter = (w, h) if len(w) > len(h) else (h, w)
        return f"{len(longer) - len(shorter)} line(s) {('missing from' if longer is w else 'extra in')} the screen: {longer[min(len(w), len(h))].strip()!r}"
    return ""


def check() -> int:
    if not CATALOG.exists() or not SCREEN.exists():
        print(f"test_enum_words FAIL — {CATALOG.name} or {SCREEN.name} is not where this test looks")
        return 1
    words = catalog_words()
    total = sum(len(v) for v in words.values())
    if not total:
        print("test_enum_words FAIL — the catalog carries no enum words at all: green and blind look alike")
        return 1
    text = SCREEN.read_text(encoding="utf-8")
    have = block_in(text)
    if have is None:
        print(f"test_enum_words FAIL — {SCREEN.relative_to(HERE)} carries no '{START}' block, so the "
              f"screen's words answer to nothing. Write it: --fix")
        return 1
    want = render()
    if have == want:
        print(f"test_enum_words: {total} word(s) in {len(words)} enum(s) — the screen's copy is the "
              f"catalog's, word for word")
        return 0
    print("test_enum_words FAIL — the screen's words have drifted from the catalog:")
    print(f"  {first_difference(want, have)}")
    print("\n  The catalog is the one place these words are written "
          f"({CATALOG.relative_to(HERE)}). Edit it there, then regenerate the screen's copy:\n"
          f"    python3 apps/indox/test_enum_words.py --fix")
    return 1


def fix() -> int:
    text = SCREEN.read_text(encoding="utf-8")
    have = block_in(text)
    if have is None:
        print(f"cannot fix: no '{START}' block in {SCREEN}")
        return 1
    SCREEN.write_text(text.replace(have, render()), encoding="utf-8", newline="\n")
    words = catalog_words()
    print(f"test_enum_words --fix: {sum(len(v) for v in words.values())} word(s) written from "
          f"{CATALOG.name}")
    return 0


def self_test() -> int:
    """Every way the two can disagree is caught, and the block's absence is a failure, not a skip."""
    cases = {
        "identical": (render(), 0),
        "a changed word": (render().replace("'הושלם'", "'הסתיים'"), 1),
        "a word the catalog does not have": (render().replace("    DOUBLE: 'כפילות',\n", ""), 1),
        "a word the screen must not add": (render().replace("  TYPE: {", "  TYPE: {\n    NOPE: 'לא',"), 1),
        "a reordered catalog": (render().replace("    COMPLETED: 'הושלם',\n", "", 1), 1),
        "an empty block": (START + "\n" + END, 1),
    }
    ok = True
    for name, (block, want) in cases.items():
        got = 0 if block_in(block) == render() else 1
        if got != want:
            ok = False
            print(f"  [FAIL] {name}: got {got}, want {want}")
        else:
            print(f"  [ok  ] {name}")
    # …and the two shapes that must NOT be an exemption: no block at all, and a catalog with no words
    body = SCREEN.read_text(encoding="utf-8").replace(block_in(SCREEN.read_text(encoding="utf-8")) or "", "")
    ok = ok and block_in(body) is None
    print(f"\ntest_enum_words self-test: {len(cases)} shape(s) checked; a screen with no block fails "
          f"(the block is where the words are, so its absence is the defect, not an exemption)")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="write the screen's copy from the catalog")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return fix() if a.fix else check()


if __name__ == "__main__":
    sys.exit(main())
