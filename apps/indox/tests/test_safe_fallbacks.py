"""test_safe_fallbacks.py — an owner's rule is held by its fallback, not only by a settings row.

    python3 apps/indox/tests/test_safe_fallbacks.py

Two of the owner's rules were held by one setting each, and the code behind the setting fell back to the
other side of the rule (DGO-1792):

  1. no outside AI without his word — INDOX's extraction ran the Gemini workflow unless the settings row
     `extraction_ai_enabled` said false (the queries' fallback was 'true'), and apitools' OCR went to Google
     Vision unless OCR_ENGINE said local (the compose default and the code default were 'google');
  2. drain B stays 500 — the drain read `indox.statemachine.driver.batch` with a fallback of 2000.

An office whose settings row or env line is missing therefore sent client documents out, or drained four
times the rule. What holds now, read from the sources themselves (no n8n, no docker, no .env):

  a. every blueprint that reads `extraction_ai_enabled` falls back to 'false', and reads the row only when it
     says true (any case, trimmed) — the gate after it skips the model only on the exact word 'false', so a
     stored 'False', 'off' or '0' used to run Gemini; there are at least the five readers that call an
     outside model, so a scan that finds nothing fails instead of passing;
  b. the drain's `indox.statemachine.driver.batch` falls back to '500', and every setting the drain reads
     falls back to the value the seed gives it — in the SQL (a missing row) and in the code after it
     (`num(cfg.<x>, N)`: a row that is empty, not a number or <= 0);
  c. the seed (blueprint/fixtures/settings.json) says the same two values;
  d. apitools' engine is local unless 'google' is asked for BY NAME: the compose default, the code default,
     and the resolver that turns unset, empty or a misspelt value into local;
  e. the unsafe value still works when it is said: the fallback SQL, run on SQLite, answers the row's
     value when the row exists and the safe value only when it is absent.

SAFE_FALLBACKS_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old code).
"""
import ast
import json
import os
import pathlib
import re
import sqlite3
import unittest

ROOT = pathlib.Path(os.environ.get("SAFE_FALLBACKS_ROOT") or pathlib.Path(__file__).resolve().parents[3])
BLUEPRINTS = ROOT / "apps/indox/blueprint/n8n"
SEED = ROOT / "apps/indox/blueprint/fixtures/settings.json"
APITOOLS_COMPOSE = ROOT / "apps/apitools/docker-compose.yml"
OCR_PROCESSOR = ROOT / "apps/apitools/src/ocr_core/ocr_processor.py"

# the blueprints whose extraction calls an outside model; each must be found by the scan
OUTSIDE_AI_READERS = {"BsDocEx01", "BaseDocEx01", "InvoiceDocEx01", "ShipmentDocEx01", "indoxV2ExtractInvoiceGemini01",
                      "indoxV2ExtractBalanceSheet01"}   # its own gate since 2026-11-11 (test_bs_extractor_ai_gate.py)

AI_FALLBACK = re.compile(r"key\s*=\s*'extraction_ai_enabled'(\s+AND\s+lower\(trim\(value\)\)\s*=\s*'true')?\s*\)\s*,\s*'([^']*)'\s*\)")
AI_GATE = re.compile(r"leftValue:\s*'=\{\{\s*\$json\.ai_enabled\s*\}\}',\s*rightValue:\s*'([^']*)',\s*operator:\s*\{\s*type:\s*'string',\s*operation:\s*'([a-z]+)'")
BATCH_FALLBACK = re.compile(r"g\(\s*'indox\.statemachine\.driver\.batch'\s*,\s*'([^']*)'\s*\)")
DRAIN_FALLBACK = re.compile(r"g\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\)")
# the code's second fallback, for a row that exists but is empty, not a number or <= 0: num(cfg.<alias>, N)
CODE_FALLBACK = re.compile(r"(?:num\(|\}\)\()\s*cfg\.([a-z_]+)\s*,\s*(\d+)\s*\)")   # num(cfg.x, N) and (function …)(cfg.x, N)
ALIAS = re.compile(r"g\(\s*'([^']+)'\s*,\s*'[^']*'\s*\)\s*\+\s*\"\s*AS\s+([a-z_]+)")


def blueprint_texts():
    return {p.name[: -len(".workflow.ts")]: p.read_text(encoding="utf-8") for p in sorted(BLUEPRINTS.glob("*.workflow.ts"))}


def seed_value(key):
    rows = json.loads(SEED.read_text(encoding="utf-8"))
    values = [r.get("value") for r in rows if r.get("key") == key]
    return values[0] if len(values) == 1 else values


def coalesce(fallback, row_value):
    """The fallback query's shape, on SQLite: the row's value when the row exists, else the fallback."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    if row_value is not None:
        db.execute("INSERT INTO settings VALUES ('k', ?)", (row_value,))
    return db.execute("SELECT coalesce((SELECT value FROM settings WHERE key = 'k'), ?)", (fallback,)).fetchone()[0]


def only_true_word(row_value):
    """The extraction readers' query, on SQLite: the row's value only when it reads true, else 'false'."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    if row_value is not None:
        db.execute("INSERT INTO settings VALUES ('extraction_ai_enabled', ?)", (row_value,))
    return db.execute("SELECT COALESCE((SELECT value FROM settings WHERE key='extraction_ai_enabled' "
                      "AND lower(trim(value)) = 'true'), 'false')").fetchone()[0]


def processor_module():
    """ocr_processor.py's default and resolver, without importing cv2/PIL: the module's own AST, executed alone."""
    tree = ast.parse(OCR_PROCESSOR.read_text(encoding="utf-8"))
    default = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OCR_ENGINE" for t in node.targets):
            call = node.value
            if isinstance(call, ast.Call) and len(call.args) == 2 and isinstance(call.args[1], ast.Constant):
                default = call.args[1].value
    resolver = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_engine"]
    namespace = {}
    if resolver:
        exec(compile(ast.Module(body=resolver, type_ignores=[]), str(OCR_PROCESSOR), "exec"), namespace)
    init_line = re.search(r"self\.ocr_engine\s*=\s*(.+)", OCR_PROCESSOR.read_text(encoding="utf-8"))
    return default, namespace.get("resolve_engine"), init_line.group(1).strip() if init_line else None


class OutsideAiNeedsHisWord(unittest.TestCase):
    def test_every_extraction_reader_falls_back_to_false(self):
        found = {}
        for name, text in blueprint_texts().items():
            for only_true, value in AI_FALLBACK.findall(text):
                found.setdefault(name, []).append((bool(only_true), value))
        self.assertTrue(OUTSIDE_AI_READERS <= set(found), "scan missed: %s" % sorted(OUTSIDE_AI_READERS - set(found)))
        unsafe = {n: v for n, v in found.items() if any(value != "false" for _, value in v)}
        self.assertEqual(unsafe, {}, "extraction_ai_enabled must fall back to 'false'")
        # the five that gate a model read the row only when it says true; the test workflows only report it
        loose = {n: v for n, v in found.items() if n in OUTSIDE_AI_READERS and not all(t for t, _ in v)}
        self.assertEqual(loose, {}, "a model's gate must read only a true-word")

    def test_every_gate_skips_the_model_on_false(self):
        # the query answers 'false' for everything but a true-word; the gate must be the one that skips on it
        for name in OUTSIDE_AI_READERS:
            gates = AI_GATE.findall(blueprint_texts()[name])
            self.assertTrue(gates, name)
            self.assertEqual(set(gates), {("false", "equals")}, name)

    def test_only_a_true_word_turns_the_model_on(self):
        # the shape every reader now has, run on SQLite: a stored 'False', 'off', '0' or ' false' used to
        # pass the gate (it skips only on the exact word 'false') and ran Gemini
        for stored, on in (("true", True), ("TRUE", True), (" true ", True), ("True", True),
                           ("false", False), ("False", False), (" false", False), ("off", False),
                           ("0", False), ("no", False), ("", False), (None, False)):
            got = only_true_word(stored)
            self.assertEqual(got != "false", on, repr(stored))

    def test_seed_says_false(self):
        self.assertEqual(seed_value("extraction_ai_enabled"), "false")

    def test_ocr_compose_default_is_local(self):
        lines = [l.strip() for l in APITOOLS_COMPOSE.read_text(encoding="utf-8").splitlines() if "OCR_ENGINE=" in l]
        self.assertEqual(lines, ["- OCR_ENGINE=${OCR_ENGINE:-local}"])

    def test_ocr_code_default_is_local_and_google_must_be_named(self):
        default, resolve, init = processor_module()
        self.assertEqual(default, "local")
        self.assertIsNotNone(resolve, "ocr_processor.py has no resolve_engine()")
        self.assertEqual(init, "resolve_engine(ocr_engine or OCR_ENGINE)")
        for said in (None, "", "local", "LOCAL", "gogle", "vision", "tesseract", " "):
            self.assertEqual(resolve(said), "local", repr(said))
        for said in ("google", " Google ", "GOOGLE"):
            self.assertEqual(resolve(said), "google", repr(said))

    def test_ai_on_still_works_when_the_row_says_so(self):
        self.assertEqual(coalesce("false", None), "false")
        self.assertEqual(coalesce("false", "true"), "true")


class DrainBStays500(unittest.TestCase):
    def test_drain_batch_falls_back_to_500(self):
        found = [v for text in blueprint_texts().values() for v in BATCH_FALLBACK.findall(text)]
        self.assertTrue(found, "scan found no driver.batch fallback")
        self.assertEqual(set(found), {"500"})

    def test_every_drain_fallback_is_the_seeded_value(self):
        drain = (BLUEPRINTS / "indoxV2BaseDrain01.workflow.ts").read_text(encoding="utf-8")
        pairs = DRAIN_FALLBACK.findall(drain)
        self.assertGreaterEqual(len(pairs), 7, "scan found %d drain settings" % len(pairs))
        differ = {k: (d, seed_value(k)) for k, d in pairs if seed_value(k) != d}
        self.assertEqual(differ, {}, "drain fallback != seed (fallback, seed)")

    def test_the_codes_second_fallback_is_the_seeded_value_too(self):
        # a row that exists but is empty or not a number passes the SQL and lands on num(cfg.<alias>, N)
        drain = (BLUEPRINTS / "indoxV2BaseDrain01.workflow.ts").read_text(encoding="utf-8")
        key_of = {alias: key for key, alias in ALIAS.findall(drain)}
        found = CODE_FALLBACK.findall(drain)
        self.assertGreaterEqual(len(found), 5, "scan found %d code fallbacks" % len(found))
        unknown = sorted(a for a, _ in found if a not in key_of)
        self.assertEqual(unknown, [], "num(cfg.<alias>) with no settings alias")
        differ = {a: (n, seed_value(key_of[a])) for a, n in found if seed_value(key_of[a]) != n}
        self.assertEqual(differ, {}, "code fallback != seed (fallback, seed)")

    def test_seed_says_500(self):
        self.assertEqual(seed_value("indox.statemachine.driver.batch"), "500")

    def test_a_larger_batch_still_works_when_the_row_says_so(self):
        self.assertEqual(coalesce("500", None), "500")
        self.assertEqual(coalesce("500", "2000"), "2000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
