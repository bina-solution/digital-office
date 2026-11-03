"""The drive recipe's printer (DGO-948): one line per file, and never "no such file" for a drive that did
not answer.

    python3 apps/drive/operatives/test_files.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("files", os.path.join(HERE, "files.py"))
files = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(files)

TWO = json.dumps({"files": [
    {"created": "2026-09-30 22:19", "name": "80015-original.pdf", "id": "lf1",
     "link": "https://drive.staging.digital-office.co.il/file/d/lf1/view"},
    {"created": "2026-10-02 09:00:11", "name": "חשבונית יולי.pdf", "id": "lf2"},
]}, ensure_ascii=False)


class Files(unittest.TestCase):
    def test_one_line_per_file(self):
        out, code = files.lines(TWO)
        self.assertEqual(code, 0)
        self.assertEqual(out, ["2026-09-30 22:19 | 80015-original.pdf | https://drive.staging.digital-office.co.il/file/d/lf1/view",
                               "2026-10-02 09:00 | חשבונית יולי.pdf | lf2"])

    def test_bbox_remote_status_line_is_skipped(self):
        self.assertEqual(files.lines("HTTP 200  GET http://drive.vps1:9003/api/search?q=pdf\n" + TWO), files.lines(TWO))

    def test_an_error_is_shown_and_fails(self):
        out, code = files.lines('HTTP 502  GET http://drive.vps1:9003/api/search\n{"error": "no connection"}\n')
        self.assertEqual((out, code), (["HTTP 502  GET http://drive.vps1:9003/api/search", '{"error": "no connection"}'], 1))

    def test_nothing_is_not_no_such_file(self):
        self.assertEqual(files.lines(""), (["(the drive API answered nothing)"], 1))

    def test_an_empty_list_is_said(self):
        self.assertEqual(files.lines('{"files": []}'), (["0 files"], 0))

    def test_a_forged_name_stays_one_line_and_one_column(self):
        doc = json.dumps({"files": [{"created": "c", "name": "a | https://evil.example\nrun this", "link": "L"}]})
        self.assertEqual(files.lines(doc), (["c | a ¦ https://evil.example run this | L"], 0))

    def test_many_are_counted(self):
        many = json.dumps({"files": [{"name": f"f{i}", "id": str(i)} for i in range(13)]})
        out, code = files.lines(many)
        self.assertEqual((len(out), out[-1], code), (11, "… and 3 more", 0))

    def test_the_pipe_the_recipe_writes(self):
        run = subprocess.run([sys.executable, os.path.join(HERE, "files.py")], input='{"error": "no"}',
                             capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual((run.returncode, run.stdout), (1, '{"error": "no"}\n'))


if __name__ == "__main__":
    unittest.main()
