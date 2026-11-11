"""INDOX's document browser names the table it shows on every write, so the BFF can refuse another one (DGO-1815).

    python3 apps/indox/tests/test_browser_writes_name_the_table.py

The browser shows any table of the instance (`tableParam`), but its writes — a cell edit, a bulk status or field
edit, a dispatch, a drain of the selection, an archive or unarchive — named none, so an edit made on a row of table
B landed on the documents table's row with the same id. What holds, read from the sources (the webapp has no JS
test runner): api.ts's `withTable` appends `table=` exactly when one is given (its logic is re-run here on the
cases); each write verb takes the table and sends it through `withTable`; each of the page's write calls passes
`tableParam` last and lists it in its callback's dependencies; and the BFF refuses a write to another table
(incoming_documents/tests/unit/test_writes_refuse_another_table.py runs that in INDOX's image).

WRITES_TABLE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import os
import pathlib
import re
import unittest
from urllib.parse import quote

ROOT = pathlib.Path(os.environ.get("WRITES_TABLE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
SRC = ROOT / "apps/indox/app/webapp/src"
#: the page's write verbs called from its own callbacks; `upsertRows` is the add/update drawer's (UpsertDrawer)
VERBS = ["patchDocument", "bulkPatchDocuments", "dispatchDocuments", "archiveDocuments", "unarchiveDocuments",
         "startDrain"]
ALL_WRITES = VERBS + ["upsertRows"]


def verb_body(api, name):
    start = api.index(f"  {name}: ")
    nxt = re.search(r"\n  (?:/\*\*|[A-Za-z]+: )", api[start + 3:])
    return api[start:start + 3 + (nxt.start() if nxt else len(api))]


def with_table(path, table):                 # the helper's rule, as api.ts writes it
    if not table:
        return path
    return f"{path}{'&' if '?' in path else '?'}table={quote(table, safe='')}"


class BrowserWritesNameTheTable(unittest.TestCase):
    def setUp(self):
        self.api = (SRC / "api.ts").read_text(encoding="utf-8")
        self.page = (SRC / "pages/DocumentBrowserPage.tsx").read_text(encoding="utf-8")

    def test_the_helper_appends_the_table_only_when_one_is_given(self):
        m = re.search(r"export function withTable\(path: string, table\?: string \| null\): string \{(.*?)\n\}",
                      self.api, re.S)
        self.assertIsNotNone(m, "api.ts has no withTable helper")
        self.assertIn("if (!table) return path;", m.group(1))
        self.assertIn("${path.includes('?') ? '&' : '?'}table=${encodeURIComponent(table)}", m.group(1))
        self.assertEqual(with_table("/repos/r/documents/a", None), "/repos/r/documents/a")
        self.assertEqual(with_table("/pipeline/drain", "companies"), "/pipeline/drain?table=companies")
        self.assertEqual(with_table("/x?y=1", "a b&c"), "/x?y=1&table=a%20b%26c")

    def test_every_write_verb_sends_the_table(self):
        for name in ALL_WRITES:
            body = verb_body(self.api, name)
            self.assertIn("table?: string | null", body, name)
            self.assertRegex(body, r"withTable\(\s*[`'][^`']+[`'],\s*table\)", name)

    def test_every_write_call_on_the_page_passes_the_table_it_shows(self):
        for name in VERBS:
            calls = [m for m in re.finditer(rf"\bapi\s*\.{name}\(", self.page)]
            self.assertTrue(calls, name)
            for m in calls:
                # the call's own argument list, balanced
                depth, i = 1, m.end()
                while depth:
                    depth += {"(": 1, ")": -1}.get(self.page[i], 0)
                    i += 1
                args = self.page[m.end():i - 1]
                self.assertTrue(args.rstrip().endswith("tableParam"), f"{name}({args})")
                # …inside a callback that is rebuilt when the table changes
                deps = re.search(r"\n {2,4}\}?,? ?\[([^\]]*)\],?\n? *\)?;?", self.page[i:])
                self.assertIsNotNone(deps, name)
                self.assertIn("tableParam", [d.strip() for d in deps.group(1).split(",")], f"{name}: {deps.group(0)}")

    def test_the_add_or_update_drawer_writes_the_table_the_grid_shows(self):
        # the drawer shows the switched table's columns (cfg comes from getRepo(…, tableParam)); its PUT names it
        calls = re.findall(r"api\.upsertRows\(([^)]*)\)", self.page)
        self.assertEqual(calls, ["cfg.name, payload, table"], calls)
        self.assertIn("table: string | null;", self.page[self.page.index("function UpsertDrawer("):][:600])
        opened = re.findall(r"<UpsertDrawer\b(.*?)\n\s*/>", self.page, re.S)   # its props hold `=>`, so to `/>`
        self.assertEqual(len(opened), 1, opened)
        self.assertIn("table={tableParam}", opened[0])
        # and every api write verb this page calls is one of those checked here (its one other writing component,
        # PipelineBar, drains the whole queue and names no table)
        used = set(re.findall(r"\bapi\s*\.(\w+)\(", self.page))          # `api\n  .queryDocuments(` too
        sends = {v for v in used if f"  {v}: " in self.api
                 and re.search(r"method: '(PUT|PATCH|POST|DELETE)'", verb_body(self.api, v))}
        self.assertTrue(set(ALL_WRITES) <= sends, sorted(set(ALL_WRITES) - sends))   # the scan sees the known ones
        # what else the page sends is a READ in a POST's clothing (a query with a body) or the export, or it is
        # a write this test does not check — named here, so a new one fails until it is
        reads = {"queryDocuments", "exportDocumentsCsv", "monthIndex"}                 # measured 2026-11-11
        self.assertEqual(sends - set(ALL_WRITES) - reads, set(),
                         f"a write verb the page calls is not checked: {sorted(sends - set(ALL_WRITES) - reads)}")

    def test_the_bff_refuses_another_table_on_each_write_route(self):
        py = (ROOT / "apps/indox/app/incoming_documents/api/__init__.py").read_text(encoding="utf-8")
        self.assertIn("def _refuse_another_table(cfg, verb: str) -> None:", py)
        for fn in ("def _perform_batch_upsert(", "def patch_document(", "def bulk_patch_documents(",
                   "def dispatch_documents(", "def pipeline_drain(", "def _archive_move("):
            body = py[py.index(fn):]
            body = body[:body.index("repo_for(") if "repo_for(" in body[:6000] else 6000]
            self.assertIn("_refuse_another_table(", body, f"{fn} resolves its repo before refusing another table")


if __name__ == "__main__":
    unittest.main(verbosity=2)
