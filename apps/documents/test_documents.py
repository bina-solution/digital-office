"""test_documents.py — ONE documents app over the two halves that exist today (DGO-1630).

    python3 apps/documents/test_documents.py

Against stand-ins for the two providers that answer their REAL API shapes and their real quirks (apitools' ledger
`GET /documents`: doc_date DD/MM/YYYY, timestamps as HTTP dates, drafts; INDOX's `GET /instances` — 200 with an empty
list when its registry fails — and `POST /repos/<repo>/documents/query`: no stable order unless asked, a page clamp
under the asked limit, `truncated` computed against the asked limit), with the real documents_core and server:
  1. the office has ONE app that declares `documents` and reads BOTH halves (the ledger and INDOX) — on today's
     split there is none, and this fails;
  2. one list holds both directions, and one search finds both;
  3. the providers are READ: a write is blocked before a byte leaves, and a sync sends nothing but reads;
  4. a provider that does not answer degrades ITS half, by name, keeping its last rows;
  5. the index rebuilds from the providers with no loss and no duplicate, and a second sync changes nothing;
  6. resolve() is one choke point: an explicit provider > the binding > a refusal, never a fallback;
  7. a search over N rows answers under 300 ms;
  8. the ops answer {"ok":true,"op":…,"data":…}, a refusal one Hebrew sentence, a bad body a 400 — never silence;
  9. dates from every provider land as YYYY-MM-DD, so "newest first" is newest first;
 10. INDOX is read in a total order, through a clamp below the page, asking only the mapped columns — nothing lost;
 11. a failed instance registry degrades the incoming half, and never flips its ids; the test instance is not the
     business's;
 12. a truncated answer degrades its half by name, and the other half still syncs;
 13. a document is told on the flow once per kind: none on the first sync, a draft only when issued, never again
     when a row drops out and comes back;
 14. a provider that lists half the list or less is refused and the rows kept, unless the shrink is accepted;
 15. a second sync of the same set writes nothing;
 16. a sync holds a page, not the book: N rows through it stay under 12 MB of Python heap.
"""
import glob
import http.client
import http.server
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "server"))
import documents_core as core  # noqa: E402

# the ledger as apitools answers it: doc_date is the model's DD/MM/YYYY (my-docs writes isoToHe), issued_at and
# created_at are TIMESTAMPTZ through Flask's jsonify — HTTP dates; one draft
LEDGER = [{"id": i, "doc_number": 1000 + i, "doc_type": "INVOICE" if i % 2 else "RECEIPT", "status": "issued",
           "customer_name": "חברת החשמל" if i == 1 else f"לקוח {i}", "total": 100.0 * i, "currency": "ILS",
           "allocation_number": "", "issued_at": f"Mon, 0{i} Nov 2026 08:00:00 GMT",
           "created_at": f"Mon, 0{i} Nov 2026 07:00:00 GMT", "doc_date": f"0{i}/11/2026"} for i in range(1, 6)]
LEDGER[4]["doc_date"] = None                               # no doc_date: the issue time decides
LEDGER.append({"id": 6, "doc_number": None, "doc_type": "QUOTE", "status": "draft", "customer_name": "קבוצת אורן",
               "total": 8500.0, "currency": "ILS", "allocation_number": "", "issued_at": None,
               "created_at": "Tue, 03 Nov 2026 09:00:00 GMT", "doc_date": "03/11/2026"})
# INDOX: DOC_DATE "in mixed formats", TIMESTAMP strict ISO
INDOX = [{"ID": f"d{i}", "TYPE": "INVOICE", "SHORT_DOC_ID": f"S{i}", "COMPANY_NAME": "חברת החשמל לישראל" if i == 2 else f"ספק {i}",
          "DOC_DATE": (f"1{i}.10.2026", f"2026-10-1{i}", f"1{i}/10/26")[i % 3], "TIMESTAMP": f"2026-10-1{i}T10:00:00.000Z",
          "DOC_TOTAL_AMOUNT": 50.0 * i, "STATUS": "COMPLETED", "REQUIRED_ACTION": "" if i % 3 else "CHECK",
          "EXTRA_WIDE_COLUMN": "x" * 200} for i in range(1, 8)]
INDOX[6]["DOC_DATE"] = ""                                  # no DOC_DATE: TIMESTAMP decides
# «קבצים» as the drive answers GET /api/fs?path= (DGO-2029): the office's own folders, as DGO-2027 laid them out
_F = lambda path, folders=(), files=(): {"kind": "folder", "path": path, "folder": {"id": path},
                                         "folders": [{"name": n} for n in folders], "files": list(files)}
DRIVE = {
    "/": _F("/", ("מסמכים", "לקוחות")),
    "/מסמכים": _F("/מסמכים", ("הצעות מחיר והסכמים",),
                  [{"id": "f1", "name": "בינה סלושנס - מי אנחנו.pdf", "created": "2026-11-19T10:00"}]),
    "/מסמכים/הצעות מחיר והסכמים": _F("/מסמכים/הצעות מחיר והסכמים", (),
                                     [{"id": "f2", "name": "מסמך עקרונות והצעת מחיר לשירותי אוטומציה.docx",
                                       "created": "2025-08-03T09:00"}]),
    "/לקוחות": _F("/לקוחות", ("לקוח לדוגמה",)),
    "/לקוחות/לקוח לדוגמה": _F("/לקוחות/לקוח לדוגמה", (), [{"id": "f3", "name": "הצעת מחיר.pdf", "created": "2026-11-19T13:15"}]),
}
INSTANCES = {"success": True, "instances": [{"id": "levi", "schema_name": "indox_levi", "enabled": True},
                                            {"id": "test", "schema_name": "indox_test", "enabled": True},
                                            {"id": "old", "schema_name": "indox_old", "enabled": False}]}


class Stub(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log, bodies = [], []
    ledger, indox, instances = LEDGER, INDOX, INSTANCES
    drive_big = 0           # >0: that many more files in /מסמכים, saved 23:30 UTC (the drive pages them by 1000)
    big = 0                 # >0: a ledger of that many rows, generated a page at a time
    clamp = None            # INDOX rows per page under the asked limit (PostgREST's db-max-rows)
    cut = False             # INDOX's query answer is cut short (an IncompleteRead)
    unordered = 0           # INDOX pages without an `order`: alternately reversed, as equal created_at allows
    per_instance = None     # {instance: rows}; None = every instance answers `indox`
    lacks = ""              # a column INDOX's table lacks: a `select` naming it is refused (400), as _ident does
    stuck = False           # the ledger ignores the offset: the same page every time

    @classmethod
    def reset(cls):
        cls.log, cls.bodies = [], []
        cls.ledger, cls.indox, cls.instances = LEDGER, INDOX, INSTANCES
        cls.big, cls.clamp, cls.cut, cls.unordered, cls.drive_big = 0, None, False, 0, 0
        cls.per_instance, cls.lacks, cls.stuck = None, "", False

    def log_message(self, *a):
        pass

    def _json(self, code, body, cut=False):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw) + (500 if cut else 0)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def do_GET(self):
        Stub.log.append(("GET", self.path.split("?")[0]))
        p, q = self.path.split("?")[0], dict(x.split("=", 1) for x in (self.path.split("?")[1].split("&") if "?" in self.path else []))
        if p == "/documents":
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 100))
            off = 0 if Stub.stuck else off
            if Stub.big:
                return self._json(200, [{"id": i, "doc_number": i, "doc_type": "INVOICE", "status": "issued",
                                         "customer_name": f"לקוח {i % 300}", "total": float(i), "currency": "ILS",
                                         "allocation_number": "", "issued_at": None, "created_at": None,
                                         "doc_date": f"{1 + i % 28:02d}/{1 + i % 12:02d}/2026"}
                                        for i in range(off, min(off + lim, Stub.big))])
            return self._json(200, Stub.ledger[off:off + lim])
        if p.startswith("/documents/") and p.endswith("/events"):
            return self._json(200, [{"event": "issued"}])
        if p.startswith("/documents/"):
            row = next((r for r in Stub.ledger if str(r["id"]) == p.split("/")[2]), None)
            return self._json(200, row) if row else self._json(404, {"error": "not_found"})
        if p == "/api/fs":
            path = urllib.parse.unquote_plus(q.get("path", "/"))
            return self._json(200, DRIVE[path]) if path in DRIVE else self._json(404, {"error": "אין כלום בנתיב"})
        if p == "/api/folders":            # the drive's folder rows: an id, a name, the parent's id (drive-local's shape)
            rows = [{"id": path, "name": path.rsplit("/", 1)[1], "parent": path.rsplit("/", 1)[0] or None}
                    for path in DRIVE if path.startswith("/") and path != "/"]
            return self._json(200, {"folders": rows + list(getattr(Stub, "extra_folders", []))})
        if p == "/api/files":              # a folder's files, a page at a time
            fid = urllib.parse.unquote_plus(q.get("folder", ""))
            files = list(DRIVE.get(fid, {}).get("files", []))
            if fid == "/מסמכים":
                files += [{"id": f"b{i}", "name": f"סריקה {i}.pdf", "created": "2026-11-18 23:30"}
                          for i in range(Stub.drive_big)]
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
            return self._json(200, {"files": files[off:off + lim], "folders": []})
        if p == "/incomingDocuments/instances":
            return self._json(200, Stub.instances)
        if p.startswith("/incomingDocuments/repos/"):
            return self._json(200, {"ID": p.rsplit("/", 1)[1]})
        self._json(404, {})

    def do_POST(self):
        Stub.log.append(("POST", self.path.split("?")[0]))
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/incomingDocuments/repos/incoming-documents-main/documents/query"):
            Stub.bodies.append(body)
            if Stub.lacks and Stub.lacks in (body.get("select") or []):
                return self._json(400, {"success": False, "error": f"invalid identifier: {Stub.lacks}"})
            off, asked = body.get("offset", 0), body.get("limit", 1000)
            inst = dict(x.split("=", 1) for x in self.path.split("?", 1)[1].split("&")).get("instance") if "?" in self.path else None
            rows = list(Stub.indox if Stub.per_instance is None else Stub.per_instance.get(inst, []))
            if body.get("order") != [{"col": "ID", "dir": "asc"}]:
                Stub.unordered += 1
                if Stub.unordered % 2 == 0:
                    rows.reverse()
            got = rows[off:off + min(asked, Stub.clamp or asked)]
            if body.get("select"):
                got = [{k: r.get(k) for k in body["select"]} for r in got]
            truncated = len(got) >= asked                  # INDOX's own computation, against the ASKED limit
            return self._json(200, {"success": True, "rows": got, "count": len(got), "truncated": truncated,
                                    "next_offset": off + asked if truncated else None}, cut=Stub.cut)
        self._json(405, {"error": "a write reached the stand-in"})


def serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Documents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve()
        base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.env = {"DOCUMENTS_PROVIDERS": "local,indox", "DOCUMENTS_LEDGER_URL": base,
                   "DOCUMENTS_INDOX_URL": base + "/incomingDocuments", "DOCUMENTS_INDOX_REPO": "incoming-documents-main"}
        cls.pages = (core.LedgerProvider.PAGE, core.IndoxProvider.PAGE)
        core.LedgerProvider.PAGE = 2                      # exercise the paging of both providers
        core.IndoxProvider.PAGE = 3

    @classmethod
    def tearDownClass(cls):
        core.LedgerProvider.PAGE, core.IndoxProvider.PAGE = cls.pages
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Stub.reset()

    def fresh(self):
        return core.Index(":memory:")

    def ids(self, idx, **kw):
        return sorted(r["id"] for r in idx.list(limit=1000, **kw))

    # 1
    def test_one_app_declares_documents_and_reads_both_halves(self):
        found = []
        for f in sorted(glob.glob(os.path.join(REPO, "apps", "*", "app.json"))):
            with open(f, encoding="utf-8") as fh:
                m = json.load(fh)
            if any(c.get("name") == "documents" for c in m.get("capabilities") or []):
                found.append((m["id"], {u.get("capability") for u in m.get("use") or []}))
        self.assertEqual(len(found), 1, f"apps declaring `documents`: {found or 'none — the two halves are still split'}")
        app, uses = found[0]
        self.assertTrue({"ledger", "indox-api"} <= uses, f"{app} must read both halves, uses {sorted(uses)}")

    # 2
    def test_one_list_over_both_directions_and_one_search(self):
        idx = self.fresh()
        report = core.sync(idx, core.resolve(env=self.env))
        self.assertEqual([r["ok"] for r in report], [True, True], report)
        rows = idx.list(limit=100)
        self.assertEqual({r["direction"] for r in rows}, {"out", "in"})
        self.assertEqual(len(rows), len(LEDGER) + len(INDOX))
        hits = idx.search("חברת החשמל")
        self.assertEqual({(h["direction"], h["provider"]) for h in hits}, {("out", "local"), ("in", "indox")})
        inc = idx.get("indox:levi:d3")
        self.assertEqual(inc["ref"], {"instance": "levi", "repo": "incoming-documents-main", "doc_id": "d3"})
        self.assertEqual(inc["needs"], "CHECK")
        self.assertEqual(idx.search("__"), [], "an underscore is a letter in a search, not a wildcard")

    # 2b (DGO-2029)
    def test_hebrew_search_reads_past_prefixes_final_letters_and_marks(self):
        idx = self.fresh()
        mk = lambda i, party, typ="INVOICE": {
            "id": f"local:{i}", "provider": "local", "direction": "out", "type": typ, "number": f"PQ-2026-{i:05d}",
            "date": "2026-11-19", "party": party, "total": 1.0, "currency": "ILS", "allocation_number": "",
            "state": "issued", "needs": "", "ref": {"id": i}}
        idx.replace_provider("local", [mk(1, "בינה סולושנס"), mk(2, "חברת החשמל לישראל"), mk(3, "חשבונות ספקים"),
                                       mk(4, "דוח מע״מ"), mk(5, "מסמכי שיווק"), mk(6, "ועדת בחירה"),
                                       mk(7, "המחירון של 2026"), mk(8, "מדינת ישראל")])
        hit = lambda q: sorted(r["id"] for r in idx.search(q))
        # a word is found at the start of a word, never inside one (DGO-2029, the second reader)
        self.assertEqual(hit("מחיר"), ["local:7"], "«מחיר» finds «המחירון», not «בחירה»")
        self.assertEqual(hit("בינה"), ["local:1"], "«בינה» does not find «מדינת»")
        self.assertNotIn("folded", idx.search("בינה")[0], "the search's reading is not a field of the row")
        self.assertEqual(hit("ובינה"), ["local:1"], "a word behind ו is found")
        self.assertEqual(hit("לחברת החשמל"), ["local:2"], "every word, each behind its prefix")
        self.assertEqual(hit("חשבון"), ["local:3"], "a final letter matches its plain form")
        self.assertEqual(hit("מעמ"), ["local:4"], "gershayim are not letters")
        self.assertEqual(hit("בִּינָה"), ["local:1"], "niqqud is not a letter")
        self.assertEqual(hit("מסמכי"), ["local:5"], "a word that starts with a prefix letter still finds itself")
        self.assertEqual(hit("חברת ספקים"), [], "two words must both be there")
        self.assertEqual(hit("pq-2026-00003"), ["local:3"], "a document number, in any case")

    # 2c (DGO-2029)
    def test_the_offices_files_are_listed_and_found_beside_its_documents(self):
        base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        drive = core.make("drive", {"DOCUMENTS_DRIVE_URL": base})
        self.assertEqual(drive.roots, ["/מסמכים", "/לקוחות", "/מחקרים"])
        rows = [r for page in drive.pages() for r in page]
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(sorted(by_id), ["drive:f1", "drive:f2", "drive:f3"], "every file under the roots; /מחקרים absent is no fault")
        self.assertEqual((by_id["drive:f2"]["type"], by_id["drive:f2"]["party"], by_id["drive:f2"]["state"]),
                         ("FILE_WORD", "מסמכים", "/מסמכים/הצעות מחיר והסכמים"))
        self.assertEqual((by_id["drive:f3"]["type"], by_id["drive:f3"]["party"]), ("FILE_PDF", "לקוח לדוגמה"),
                         "a client's folder names the client")
        self.assertEqual(by_id["drive:f3"]["ref"], {"path": "/לקוחות/לקוח לדוגמה/הצעת מחיר.pdf", "id": "f3"})
        self.assertEqual(by_id["drive:f2"]["date"], "2025-08-03")
        idx = self.fresh()
        report = core.sync(idx, [drive])
        self.assertEqual([r["ok"] for r in report], [True], report)
        self.assertEqual(sorted(r["id"] for r in idx.search("הצעת מחיר")), ["drive:f2", "drive:f3"])
        self.assertEqual([r["id"] for r in idx.search("לקוח לדוגמה")], ["drive:f3"])
        self.assertEqual([r["id"] for r in idx.search("בהצעות")], ["drive:f2"], "a folder's words, past a prefix")
        self.assertIsNone(drive.event_kind(rows[0]), "a filed file is not news on the flow")
        self.assertIn("drive", core.PROVIDERS)

    # 2d (DGO-2029, the second reader)
    def test_a_long_folder_is_read_whole_in_one_tree_call_and_a_utc_time_is_the_offices_day(self):
        base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        Stub.drive_big = 5001                                   # N files in /מסמכים: two pages of the drive's 5,000
        drive = core.make("drive", {"DOCUMENTS_DRIVE_URL": base, "DOCUMENTS_DRIVE_PROFILE": "office"})
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "IST-2"                              # the office's clock in November (UTC+2), no tz database
        time.tzset()
        try:
            rows = [r for page in drive.pages() for r in page]
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()
        self.assertEqual(len(rows), 5001 + 3, "no folder cut off at the drive's page")
        scan = next(r for r in rows if r["id"] == "drive:b0")
        self.assertEqual(scan["date"], "2026-11-19", "23:30 UTC is the next morning in the office")
        gets = [p for m, p in Stub.log if m == "GET"]
        self.assertEqual(gets.count("/api/folders"), 1, "the tree is read once, not once per folder")
        self.assertNotIn("/api/fs", gets, "no whole-tree listing per folder")
        self.assertEqual(gets.count("/api/files"), 2 + 3, "/מסמכים in two pages, three folders in one each")

    # 2e (DGO-2029, the third reader)
    def test_two_folders_of_one_name_are_both_read_and_an_underscore_parts_words(self):
        base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        twin = {"id": "twin", "name": "מסמכים", "parent": None}       # another «/מסמכים» (Google allows the twin)
        with mock.patch.object(Stub, "extra_folders", [twin], create=True), \
                mock.patch.dict(DRIVE, {"twin": {"files": [{"id": "t1", "name": "חשבונית_כהן_2025.pdf",
                                                            "created": "2026-11-19 10:00"}]}}):
            drive = core.make("drive", {"DOCUMENTS_DRIVE_URL": base})
            rows = [r for page in drive.pages() for r in page]
        self.assertIn("drive:t1", [r["id"] for r in rows], "the twin folder's files are read too")
        idx = self.fresh()
        idx.replace_provider("drive", rows)
        self.assertEqual([r["id"] for r in idx.search("כהן")], ["drive:t1"], "«_» parts a file name's words")

    # 3
    def test_the_providers_are_read_only(self):
        for method, path in (("POST", "/documents"), ("POST", "/documents/1/issue"), ("DELETE", "/documents/1"),
                             ("PATCH", "/repos/r/documents/d1"), ("POST", "/repos/r/documents/d1")):
            client = core.ReadOnlyClient("http://127.0.0.1:9", reads_by_post=(r"^/repos/[^/]+/documents/query$",))
            with self.assertRaises(core.ReadOnlyViolation, msg=f"{method} {path} was not blocked"):
                client.request(method, path)
        core.sync(self.fresh(), core.resolve(env=self.env))
        writes = [x for x in Stub.log if x[0] != "GET" and not x[1].endswith("/documents/query")]
        self.assertEqual(writes, [], f"a sync sent a write: {writes}")

    # 4
    def test_a_provider_that_does_not_answer_degrades_its_half_by_name(self):
        idx = self.fresh()
        core.sync(idx, core.resolve(env=self.env))
        down = dict(self.env, DOCUMENTS_INDOX_URL="http://127.0.0.1:9/incomingDocuments")
        report = {r["provider"]: r for r in core.sync(idx, core.resolve(env=down))}
        self.assertTrue(report["local"]["ok"])
        self.assertFalse(report["indox"]["ok"])
        self.assertEqual(len(idx.list(direction="in")), len(INDOX), "the incoming half lost its last rows")
        said = {s["provider"]: s["said"] for s in idx.status()}
        self.assertTrue(said["indox"].startswith("לא סונכרן מאז"), said)
        self.assertTrue(said["local"].startswith("סונכרן"), said)
        # G76: the sentence says what happened in words; the raw error keeps a field of its own
        self.assertNotRegex(said["indox"], r"[A-Za-z]+(Error|Exception)|urlopen|Errno", said)
        self.assertIn("URLError", {s["provider"]: s["error"] for s in idx.status()}["indox"])

    # 5
    def test_the_index_rebuilds_with_no_loss_and_no_duplicate(self):
        idx = self.fresh()
        core.sync(idx, core.resolve(env=self.env))
        before = self.ids(idx)
        again = core.sync(idx, core.resolve(env=self.env))
        self.assertEqual([(r["added"], r["changed"], r["removed"]) for r in again], [(0, 0, 0), (0, 0, 0)])
        idx.drop()
        self.assertEqual(idx.list(), [])
        core.sync(idx, core.resolve(env=self.env))
        self.assertEqual(self.ids(idx), before)

    # 6
    def test_resolve_is_one_choke_point(self):
        self.assertEqual([p.id for p in core.resolve("indox", env={})], ["indox"])          # explicit, even unbound
        self.assertEqual([p.id for p in core.resolve(env={"DOCUMENTS_PROVIDERS": "local"})], ["local"])
        with self.assertRaises(core.Refused) as no_binding:
            core.resolve(env={})
        self.assertEqual(no_binding.exception.code, 503)
        with self.assertRaises(core.Refused) as unknown:
            core.resolve("morning", env=self.env)
        self.assertEqual(unknown.exception.code, 404)

    # 7
    def test_a_search_over_5000_rows_is_under_300ms(self):
        idx = self.fresh()
        mk = lambda i, d: {"id": f"{d}:{i}", "provider": "local" if d == "out" else "indox", "direction": d,
                           "type": "INVOICE", "number": str(i), "date": f"2026-{1 + i % 12:02d}-01",
                           "party": "חשמל" if i % 97 == 0 else f"צד {i}", "total": float(i), "currency": "ILS",
                           "allocation_number": "", "state": "x", "needs": "", "ref": {"id": i}}
        idx.replace_provider("local", [mk(i, "out") for i in range(2500)])
        idx.replace_provider("indox", [mk(i, "in") for i in range(2500)])
        t = time.perf_counter()
        hits = idx.search("חשמל", limit=200)
        ms = (time.perf_counter() - t) * 1000
        self.assertLess(ms, 300, f"{ms:.0f} ms")
        self.assertEqual({h["direction"] for h in hits}, {"out", "in"})

    # 8
    def test_the_ops_answer_their_shape_and_refuse_in_hebrew(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, dict(self.env, DOCUMENTS_DB=os.path.join(tmp, "d.sqlite"))):
            server = importlib.import_module("server")
            server.INDEX = core.Index(os.path.join(tmp, "d.sqlite"))
            server.run_sync()
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Door)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"

            def refused(path, data=None):
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(urllib.request.Request(base + path, data=data, method="POST" if data else "GET"),
                                           timeout=10)
                body = json.loads(e.exception.read().decode())
                e.exception.close()
                self.assertFalse(body["ok"])
                return e.exception.code, body["detail"]
            try:
                get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=10).read().decode())
                self.assertEqual(get("/healthz"), {"ok": True})
                lst = get("/api/documents?direction=in")
                self.assertEqual((lst["ok"], lst["op"]), (True, "list"))
                self.assertTrue(lst["data"]["rows"] and all(r["direction"] == "in" for r in lst["data"]["rows"]))
                self.assertEqual(lst["data"]["rows"][0]["type_name"], "חשבונית מס")
                one = get("/api/documents/local:1")
                self.assertEqual((one["op"], one["data"]["live"]["doc_number"]), ("get", 1001))
                code, detail = refused("/api/search?q=x")
                self.assertEqual(code, 400)
                self.assertIn("חיפוש", detail)
                code, detail = refused("/api/sync", b'["local"]')          # a body that is not an object: a 400
                self.assertEqual(code, 400)
                self.assertIn("אובייקט", detail)
                conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                conn.putrequest("POST", "/api/sync")
                conn.putheader("Content-Length", "-1")                     # would block the thread on read(-1)
                conn.endheaders()
                answer = conn.getresponse()
                self.assertEqual(answer.status, 400)
                answer.read()
                conn.close()
                Stub.ledger = LEDGER[1:]                                  # the ledger forgot a document: 404 there
                gone = get("/api/documents/local:1")
                self.assertIsNone(gone["data"]["live"])
                self.assertIn("לא מכיר", gone["data"]["live_said"])
                ready = get("/readyz")
                self.assertTrue(ready["ok"], ready)
            finally:
                srv.shutdown()
                srv.server_close()

    # 9
    def test_dates_land_as_iso_and_newest_is_first(self):
        idx = self.fresh()
        core.sync(idx, core.resolve(env=self.env))
        out = idx.list(direction="out", limit=100)
        self.assertEqual([r["date"] for r in out], ["2026-11-05", "2026-11-04", "2026-11-03", "2026-11-03", "2026-11-02",
                                                    "2026-11-01"], out)
        self.assertEqual(idx.get("local:5")["date"], "2026-11-05", "no doc_date: the issue time decides")
        inc = {r["id"]: r["date"] for r in idx.list(direction="in", limit=100)}
        self.assertEqual(inc["indox:levi:d1"], "2026-10-11")
        self.assertEqual(inc["indox:levi:d3"], "2026-10-13")
        self.assertEqual(inc["indox:levi:d5"], "2026-10-15")
        self.assertEqual(inc["indox:levi:d7"], "2026-10-17", "no DOC_DATE: TIMESTAMP decides")
        self.assertEqual(core.iso_date("31/02/2026"), "")
        self.assertEqual(core.iso_date("Tue, 10 No"), "")

    # 10
    def test_indox_is_read_in_a_total_order_through_a_clamp(self):
        Stub.clamp = 2                                     # db-max-rows below the page INDOX was asked for
        idx = self.fresh()
        report = core.sync(idx, core.resolve("indox", env=self.env))
        self.assertTrue(report[0]["ok"], report)
        self.assertEqual(self.ids(idx), sorted(f"indox:levi:{r['ID']}" for r in INDOX), "a row was lost or doubled")
        self.assertTrue(Stub.bodies and all(b.get("order") == [{"col": "ID", "dir": "asc"}] for b in Stub.bodies))
        self.assertTrue(all(b.get("select") == core.IndoxProvider.COLUMNS for b in Stub.bodies))
        self.assertNotIn("EXTRA_WIDE_COLUMN", core.IndoxProvider.COLUMNS)

    # 11
    def test_a_failed_registry_degrades_the_incoming_half_and_never_flips_it(self):
        idx = self.fresh()
        core.sync(idx, core.resolve(env=self.env))
        self.assertFalse([i for i in self.ids(idx) if i.startswith(("indox:test:", "indox:old:"))],
                         "the test instance (or a disabled one) was indexed as the business's")
        before = self.ids(idx, direction="in")
        Stub.instances = {"success": True, "instances": [], "reason": "connection to server failed"}
        report = {r["provider"]: r for r in core.sync(idx, core.resolve(env=self.env))}
        self.assertFalse(report["indox"]["ok"], report)
        self.assertIn("instances", report["indox"]["error"])
        self.assertEqual(self.ids(idx, direction="in"), before, "the incoming half flipped to another instance's ids")
        Stub.instances = {"success": True, "instances": [], "reason": "no sql transport"}
        core.sync(idx, core.resolve("indox", env=self.env), accept_shrink=True)
        self.assertTrue(all(i.startswith("indox:main:") for i in self.ids(idx, direction="in")),
                        "an INDOX with no registry is its main repo")

    # 12
    def test_a_truncated_answer_degrades_its_half_by_name(self):
        idx = self.fresh()
        Stub.cut = True
        report = {r["provider"]: r for r in core.sync(idx, core.resolve(env=self.env))}
        self.assertTrue(report["local"]["ok"], report)
        self.assertFalse(report["indox"]["ok"], report)
        self.assertTrue(idx.list(direction="out"))
        self.assertEqual(idx.list(direction="in"), [])
        self.assertIn("indox", {s["provider"] for s in idx.status() if not s["ok"]})

    # 13
    def test_a_document_is_told_once_none_on_the_first_sync_a_draft_when_issued(self):
        idx, told = self.fresh(), []
        on = lambda rec, kind: told.append((rec["id"], kind))
        core.sync(idx, core.resolve(env=self.env), on_event=on)
        self.assertEqual(told, [], "the first sync announced the whole book")
        new_in = dict(INDOX[0], ID="d9", REQUIRED_ACTION="")
        Stub.indox = INDOX + [new_in]
        Stub.ledger = [dict(r, status="issued") if r["id"] == 6 else r for r in LEDGER]     # the draft is issued
        core.sync(idx, core.resolve(env=self.env), on_event=on)
        self.assertEqual(sorted(told), [("indox:levi:d9", "document.intake.filed"), ("local:6", "document.issued")])
        Stub.indox = INDOX                                 # d9 drops out of a page …
        core.sync(idx, core.resolve(env=self.env), on_event=on)
        Stub.indox = INDOX + [new_in]                      # … and comes back: not news
        core.sync(idx, core.resolve(env=self.env), on_event=on)
        self.assertEqual(len(told), 2, told)
        Stub.indox = INDOX + [dict(new_in, REQUIRED_ACTION="CHECK")]    # it now needs a hand: that is news
        core.sync(idx, core.resolve(env=self.env), on_event=on)
        self.assertEqual(told[-1], ("indox:levi:d9", "document.intake.needs_review"))
        Stub.ledger = LEDGER + [dict(LEDGER[0], id=100 + i, status="issued") for i in range(30)]
        report = {r["provider"]: r for r in core.sync(idx, core.resolve(env=self.env), on_event=on, budget=20)}
        self.assertEqual((report["local"]["events"], report["local"]["events_dropped"]), (20, 10))

    # 14
    def test_a_set_half_the_size_is_refused_unless_accepted(self):
        idx = self.fresh()
        big = [{"id": f"local:{i}", "provider": "local", "direction": "out", "type": "INVOICE", "number": str(i),
                "date": "2026-11-01", "party": "x", "total": 1.0, "currency": "ILS", "allocation_number": "",
                "state": "issued", "needs": "", "ref": {"id": str(i)}} for i in range(100)]
        idx.replace_provider("local", big)
        report = core.sync(idx, core.resolve("local", env=self.env))       # the ledger lists 6
        self.assertFalse(report[0]["ok"], report)
        self.assertIn("--accept-shrink", report[0]["error"])
        self.assertEqual(len(idx.list(direction="out", limit=1000)), 100, "a short answer emptied the half")
        report = core.sync(idx, core.resolve("local", env=self.env), accept_shrink=True)
        self.assertTrue(report[0]["ok"], report)
        self.assertEqual(len(idx.list(direction="out", limit=1000)), len(LEDGER))

    # 15
    def test_a_second_sync_writes_nothing(self):
        idx = self.fresh()
        core.sync(idx, core.resolve(env=self.env))
        stamp = {r["id"]: r["synced_at"] for r in idx.list(limit=1000)}
        time.sleep(0.01)
        core.sync(idx, core.resolve(env=self.env))
        self.assertEqual({r["id"]: r["synced_at"] for r in idx.list(limit=1000)}, stamp, "an unchanged row was rewritten")

    # 16
    def test_a_sync_holds_a_page_not_the_book(self):
        Stub.big = 20000
        env = dict(self.env, DOCUMENTS_PROVIDERS="local")
        tmp = tempfile.mkdtemp()
        idx = core.Index(os.path.join(tmp, "m.sqlite"))
        page, core.LedgerProvider.PAGE = core.LedgerProvider.PAGE, 500
        try:
            core.sync(idx, core.resolve(env=env))
            tracemalloc.start()
            report = core.sync(idx, core.resolve(env=env))
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
        finally:
            core.LedgerProvider.PAGE = page
            idx.db.close()
        self.assertTrue(report[0]["ok"], report)
        self.assertEqual(report[0]["count"], 20000)
        self.assertLess(peak, 12 * 2 ** 20, f"a N-row sync peaked at {peak / 2 ** 20:.1f} MB of heap")

    # 17
    def test_incoming_is_news_only_when_indox_says_so(self):
        idx, told = self.fresh(), []
        on = lambda rec, kind: told.append((rec["id"], kind))
        core.sync(idx, core.resolve("indox", env=self.env), on_event=on)
        arriving = dict(INDOX[0], ID="d20", STATUS="TO_EXTRACT", REQUIRED_ACTION="", COMPANY_NAME="", SHORT_DOC_ID="")
        old = dict(INDOX[0], ID="d21", STATUS="OLD", REQUIRED_ACTION="CHECK")
        Stub.indox = INDOX + [arriving, old]
        core.sync(idx, core.resolve("indox", env=self.env), on_event=on)
        self.assertEqual(told, [], "a row still being read, or an old one, was told as filed")
        Stub.indox = INDOX + [dict(arriving, STATUS="MISSING_COMPANY_ID"), old]
        core.sync(idx, core.resolve("indox", env=self.env), on_event=on)
        Stub.indox = INDOX + [dict(arriving, STATUS="COMPLETED"), old]
        core.sync(idx, core.resolve("indox", env=self.env), on_event=on)
        self.assertEqual(told, [("indox:levi:d20", "document.intake.needs_review"), ("indox:levi:d20", "document.intake.filed")])

    # 18
    def test_an_empty_reason_from_the_registry_is_a_failure_too(self):
        idx = self.fresh()
        core.sync(idx, core.resolve("indox", env=self.env))
        Stub.instances = {"success": True, "instances": [], "reason": ""}    # str(e)[:200] of an exception with no message
        report = core.sync(idx, core.resolve("indox", env=self.env))
        self.assertFalse(report[0]["ok"], report)
        self.assertEqual(len(idx.list(direction="in")), len(INDOX), "an empty reason emptied the incoming half")

    # 19
    def test_one_instance_vanishing_is_refused_though_the_half_holds(self):
        rows = [dict(INDOX[0], ID=f"x{i}") for i in range(60)]
        Stub.per_instance = {"levi": rows, "cohen": rows, "dan": rows}
        Stub.instances = {"success": True, "instances": [{"id": i, "enabled": True} for i in ("levi", "cohen", "dan")]}
        idx = self.fresh()
        page, core.IndoxProvider.PAGE = core.IndoxProvider.PAGE, 500
        try:
            core.sync(idx, core.resolve("indox", env=self.env))
            self.assertEqual(len(idx.list(direction="in", limit=1000)), 180)
            Stub.instances = {"success": True, "instances": [{"id": i, "enabled": True} for i in ("levi", "cohen")]}
            report = core.sync(idx, core.resolve("indox", env=self.env))          # a third of the half: dan, whole
        finally:
            core.IndoxProvider.PAGE = page
        self.assertFalse(report[0]["ok"], report)
        self.assertIn("«dan»", report[0]["error"])
        self.assertEqual(len(idx.list(direction="in", limit=1000)), 180)

    # 20
    def test_an_instance_whose_table_lacks_a_column_is_read_whole(self):
        Stub.lacks = "TOTAL_AMOUNT"
        idx = self.fresh()
        report = core.sync(idx, core.resolve("indox", env=self.env))
        self.assertTrue(report[0]["ok"], report)
        self.assertEqual(self.ids(idx), sorted(f"indox:levi:{r['ID']}" for r in INDOX))
        self.assertTrue(any("select" not in b for b in Stub.bodies), "it never read without the select")

    # 21
    def test_a_zoned_moment_lands_on_the_office_day(self):
        try:
            with mock.patch.dict(os.environ, {"TZ": "Asia/Jerusalem"}):
                time.tzset()
                self.assertEqual(core.iso_date("2026-10-17T22:30:00.000Z"), "2026-10-18")
                self.assertEqual(core.iso_date("Sat, 17 Oct 2026 22:30:00 GMT"), "2026-10-18")
                self.assertEqual(core.iso_date("2026-10-17"), "2026-10-17")
        finally:
            time.tzset()

    # 22
    def test_a_ledger_that_ignores_the_offset_is_a_fault_not_the_end(self):
        idx = self.fresh()
        core.sync(idx, core.resolve("local", env=self.env))
        Stub.stuck = True
        report = core.sync(idx, core.resolve("local", env=self.env))
        self.assertFalse(report[0]["ok"], report)
        self.assertEqual(len(idx.list(direction="out")), len(LEDGER), "a stuck page cut the list")

    # 23
    def test_temp_stays_in_memory_on_a_read_only_root(self):
        # the container's root and /app are read-only: a sort SQLite spills to a temp FILE fails there (disk I/O
        # error) — the real-container proof is on DGO-1630; this holds the setting that makes it pass
        idx = core.Index(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
        self.assertEqual(idx.db.execute("PRAGMA temp_store").fetchone()[0], 2)
        idx.db.close()

    # 24
    def test_a_failure_is_told_once_and_its_end_once(self):
        tmp = tempfile.mkdtemp()
        down = dict(self.env, DOCUMENTS_INDOX_URL="http://127.0.0.1:9/incomingDocuments", DOCUMENTS_DB=os.path.join(tmp, "s.sqlite"))
        with mock.patch.dict(os.environ, down):
            server = importlib.import_module("server")
            server.INDEX, said = core.Index(os.path.join(tmp, "s.sqlite")), []
            with mock.patch.object(server, "_emit", lambda kind, title, data=None: said.append(kind)):
                for _ in range(3):
                    server.run_sync()
                self.assertEqual(said.count("documents.sync.failed"), 1, said)
                os.environ["DOCUMENTS_INDOX_URL"] = self.env["DOCUMENTS_INDOX_URL"]
                server.run_sync()
                server.run_sync()
                self.assertEqual(said.count("documents.sync.recovered"), 1, said)
            server.INDEX.db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
