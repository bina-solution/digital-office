"""INDOX's CSV export exports the table the grid shows, not the default one (DGO-1815).

    python3 apps/indox/tests/test_export_follows_the_table.py

The document browser shows any table of the instance (`tableParam = params.get('table')`) and its grid reads that
table, but `exportDocumentsCsv` posted with no `table=`, so the CSV held the default table's rows. The BFF's export
route already honours it (`repo_for(cfg, request.args.get("instance"), request.args.get("table"))`). What holds, read
from the sources: the export takes a table and sends it as `?table=` the way `queryDocuments` does, through
`withInstance`; the browser's one export call passes `tableParam`; the BFF's export route reads `table`.

EXPORT_TABLE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(os.environ.get("EXPORT_TABLE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
SRC = ROOT / "apps/indox/app/webapp/src"


class ExportFollowsTheTable(unittest.TestCase):
    def test_the_export_sends_the_table_through_with_instance(self):
        api = (SRC / "api.ts").read_text(encoding="utf-8")
        body = api[api.index("exportDocumentsCsv: async ("):]
        body = body[:body.index("if (!res.ok)")]
        self.assertIn("table?: string | null,", body)
        # through the one helper every table-scoped call uses (test_browser_writes_name_the_table.py runs it)
        self.assertIn("withTable(`/repos/${encodeURIComponent(repo)}/documents/export`, table)", body)
        self.assertIn("withInstance(path)", body)

    def test_the_browser_passes_the_table_it_shows(self):
        page = (SRC / "pages/DocumentBrowserPage.tsx").read_text(encoding="utf-8")
        # the whole argument list, to the call's own `);` (its first argument holds a call of its own)
        calls = re.findall(r"api\.exportDocumentsCsv\((.*)\);", page)
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0].strip().endswith("tableParam"), calls[0])
        # …and the memoized callback is rebuilt when the table changes, or a switch exports the old one
        cb = page[page.index("const exportSelection = useCallback("):]
        deps = re.search(r"\n  \}, \[([^\]]*)\]\);", cb)
        self.assertIsNotNone(deps)
        self.assertIn("tableParam", [d.strip() for d in deps.group(1).split(",")], deps.group(0))

    def test_a_selection_is_cleared_when_the_table_or_instance_changes(self):
        page = (SRC / "pages/DocumentBrowserPage.tsx").read_text(encoding="utf-8")
        effect = re.search(r"useEffect\(\(\) => \{\s*resetSel\(\);\s*\}, \[([^\]]*)\]\);", page)
        self.assertIsNotNone(effect, "an ids selection made in one table would name other rows in the next")
        self.assertEqual({d.strip() for d in effect.group(1).split(",")}, {"instanceParam", "tableParam", "resetSel"})

    def test_the_bff_export_reads_the_table(self):
        py = (ROOT / "apps/indox/app/incoming_documents/api/__init__.py").read_text(encoding="utf-8")
        body = py[py.index('@bp.post("/repos/<repo>/documents/export")'):]
        body = body[:body.index("@bp.", 10)]
        self.assertIn('repo_for(cfg, request.args.get("instance"), request.args.get("table"))', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
