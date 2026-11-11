#!/usr/bin/env python3
"""test_context_index — ai/context/README.md covers every document of its folder, once (DGO-1062).

    python3 scripts/test_context_index.py

The folder's index is how an agent finds the deeper material without reading the whole folder: a document the
index does not name is one nobody finds, and one with two rows is two answers to «where is X». So: every file and
directory directly in ai/context (but the README and dotfiles) is named in the README, as a whole name; no entry
has two index rows (a table row whose first cell names it); no row names an entry that is not there. A document
that has no place in the index does not belong in the folder — it moves to legacy/ or ai/obsidian/; until it does,
it is in TO_MOVE below, a list that may only shrink (an entry there that is gone, or indexed, fails too).
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "ai" / "context"
#: the first cell of a table row: `name` or [name](target) — a path out of the folder (../../bbox) is not an entry
ROW = re.compile(r"^\|\s*(?:`([^`]+)`|\[([^\]]+)\]\([^)]*\))\s*\|")

#: documents found here with no place in the index, waiting to move. Empty since DGO-1062's second step: the 29 dated
#: reports, QA runs and plans it held went to legacy/ai-context-20261110/, its three working notes to
#: ai/obsidian/Sessions/. A name added here is a document that must leave, and the list must reach empty again.
TO_MOVE = set()  # entry names, as entries() lists them


def entries() -> list[str]:
    return sorted(p.name for p in CONTEXT.iterdir() if not p.name.startswith(".") and p.name != "README.md")


def readme() -> str:
    return (CONTEXT / "README.md").read_text(encoding="utf-8")


def rows() -> list[str]:
    out = []
    for line in readme().splitlines():
        m = ROW.match(line)
        if m:
            name = (m.group(1) or m.group(2)).strip().rstrip("/")
            if "/" not in name:                     # ../../bbox, archive/x.md: pointers past the folder's top
                out.append(name)
    return out


def named(entry: str, text: str) -> bool:
    return re.search(r"(?<![\w./-])" + re.escape(entry) + r"(?![\w-])", text) is not None


class ContextIndex(unittest.TestCase):
    def test_every_entry_is_in_the_index(self):
        text = readme()
        missing = [e for e in entries() if e not in TO_MOVE and not named(e, text)]
        self.assertEqual(missing, [], f"{len(missing)} document(s) of ai/context the README does not name")

    def test_no_entry_has_two_rows(self):
        r = rows()
        self.assertEqual(sorted({e for e in r if r.count(e) > 1}), [])

    def test_no_row_names_an_entry_that_is_not_there(self):
        there = set(entries())
        self.assertEqual(sorted({n for n in rows() if n not in there}), [])

    def test_to_move_only_shrinks(self):
        there, text = set(entries()), readme()
        self.assertEqual(sorted(TO_MOVE - there), [], "moved: take it off TO_MOVE")
        self.assertEqual(sorted(e for e in TO_MOVE if named(e, text)), [], "indexed after all: take it off TO_MOVE")


if __name__ == "__main__":
    unittest.main(verbosity=1)
