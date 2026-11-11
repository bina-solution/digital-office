"""test_pdf_dpi_constant_unit.py — the PDF rasterization DPI is a product constant (DGO-216).

    python3 apps/apitools/tests/test_pdf_dpi_constant_unit.py

The owner (2026-07-13): «stop dangling apitools pdf dpi in env and blaming it.. it should be fixed value this is config
not to play with or changed in tests». So: PDF_OCR_DPI is one literal in src/pdf_core/pdf_to_jpg.py, and no file of
the office reads the retired APITOOLS_PDF_DPI knob — not apitools, not a script, not a compose file. Read with `ast`
and as text, so the test needs none of apitools' own dependencies.
"""
import ast
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent
APITOOLS = HERE.parent
REPO = APITOOLS.parent.parent
SRC = APITOOLS / "src" / "pdf_core" / "pdf_to_jpg.py"
SKIP_DIRS = {"node_modules", ".git", "legacy", "ci-artifacts", "__pycache__", "dist", "build"}
CODE = {".py", ".sh", ".yml", ".yaml", ".ts", ".mjs", ".js", ".json"}
# a READ (or a SET) of the knob, in any of the office's languages — not a sentence that names it (a docstring, a
# plan item): python getenv/environ, shell $VAR / ${VAR} / export, node process.env, a Dockerfile ENV, and a compose
# or JSON entry (`- APITOOLS_PDF_DPI=…`, `- "APITOOLS_PDF_DPI=…"`, a bare passthrough `- APITOOLS_PDF_DPI`, a key)
READ = re.compile(r"getenv\(\s*['\"]APITOOLS_PDF_DPI|environ(?:\.get\(|\[)\s*['\"]APITOOLS_PDF_DPI"
                  r"|\$\{?APITOOLS_PDF_DPI|process\.env(?:\.APITOOLS_PDF_DPI|\[\s*['\"]APITOOLS_PDF_DPI)"
                  r"|^\s*-?\s*['\"]?APITOOLS_PDF_DPI['\"]?\s*(?:[=:]|$)|^\s*(?:export|ENV)\s+APITOOLS_PDF_DPI\b")
HASH_COMMENT = re.compile(r"(^|\s)#.*$")                   # python, shell, yaml, Dockerfile
SLASH_COMMENT = re.compile(r"(^|\s)//.*$")                 # js, ts


def reads(line: str, suffix: str) -> bool:
    """Whether this line of code reads or sets the knob — its trailing comment does not count."""
    code = (SLASH_COMMENT if suffix in (".ts", ".mjs", ".js") else HASH_COMMENT).sub("", line)
    return bool(READ.search(code))


def dpi_assignments(text: str):
    return [n.value for n in ast.parse(text).body
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PDF_OCR_DPI" for t in n.targets)]


class PdfDpiIsAConstant(unittest.TestCase):
    def test_the_dpi_is_one_literal_300(self):
        values = dpi_assignments(SRC.read_text(encoding="utf-8"))
        self.assertEqual(len(values), 1, "PDF_OCR_DPI is assigned once")
        self.assertIsInstance(values[0], ast.Constant, "PDF_OCR_DPI must be a literal — read from nowhere (no env)")
        self.assertEqual(values[0].value, 300)

    def test_the_check_tells_a_literal_from_an_env_read(self):
        # the shape this replaced must fail the check above: an env read is a Call, not a Constant
        old = "import os\nPDF_OCR_DPI = int(os.getenv('APITOOLS_PDF_DPI', '300'))\n"
        self.assertNotIsInstance(dpi_assignments(old)[0], ast.Constant)

    @unittest.skipUnless((REPO / "scripts").is_dir() and (REPO / "platform").is_dir(),
                         "the office's tree is not here (run inside the app's image)")
    def test_nothing_in_the_office_reads_the_retired_knob(self):
        readers = []
        for base in ("apps", "platform", "platform-base", "scripts"):
            for p in (REPO / base).rglob("*"):
                is_dockerfile = p.name.startswith("Dockerfile")
                if (p.suffix not in CODE and not is_dockerfile) or not p.is_file() or SKIP_DIRS & set(p.parts) \
                        or p == pathlib.Path(__file__).resolve():
                    continue
                if "project-pln" in p.parts and "plans" in p.parts:    # work items' words, which quote old code
                    continue
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if reads(line, p.suffix):
                        readers.append(f"{p.relative_to(REPO)}: {line.strip()[:120]}")
        self.assertEqual(readers, [], "the DPI is a constant now; these still read the env knob:\n  " + "\n  ".join(readers))

    def test_the_reader_pattern_tells_a_read_from_a_mention(self):
        for line, suffix in (("PDF_OCR_DPI = int(os.getenv('APITOOLS_PDF_DPI', '300'))", ".py"),
                             ("os.environ.get('APITOOLS_PDF_DPI')", ".py"),
                             ("sh -c 'echo -n \"$APITOOLS_PDF_DPI\"'", ".sh"),
                             ("      - APITOOLS_PDF_DPI=${APITOOLS_PDF_DPI:-300}", ".yml"),
                             ('      - "APITOOLS_PDF_DPI=300"', ".yml"),
                             ("      - APITOOLS_PDF_DPI", ".yml"),
                             ("  APITOOLS_PDF_DPI: '200'", ".yml"),
                             ('  "APITOOLS_PDF_DPI": 300,', ".json"),
                             ("const d = process.env['APITOOLS_PDF_DPI'];", ".mjs"),
                             ("export APITOOLS_PDF_DPI=150", ".sh"),
                             ("ENV APITOOLS_PDF_DPI=300", "")):
            self.assertTrue(reads(line, suffix), line)
        for line, suffix in (("`APITOOLS_PDF_DPI`=300, see apps/apitools/src/pdf_core/pdf_to_jpg.py), and apitools keeps", ".py"),
                             ("מצב (חלקי): pdf_to_jpg.py:26 still env-overridable (APITOOLS_PDF_DPI)", ".yaml"),
                             ("dpi = 300  # was os.getenv('APITOOLS_PDF_DPI') before DGO-216", ".py"),
                             ("const dpi = 300; // not process.env.APITOOLS_PDF_DPI any more", ".ts")):
            self.assertFalse(reads(line, suffix), line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
