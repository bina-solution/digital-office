"""test_drain_cli.py — `bbox indox main` / `bbox indox decide` (DGO-231), against stand-ins.

    python3 apps/indox/tests/test_drain_cli.py

No docker, no n8n, no .env: the drain webhook and every psql read are replaced by recorders. What holds:
  1. decide is ALWAYS dry; main acts unless --dry — the one difference between the verbs;
  2. the four modes of the drain API, picked from the arguments, and the refusals;
  3. --company is one SELECT in the instance's own schema (quotes escaped), turned into ids;
  4. the webhook is called with THE credential the drain's webhook node uses — read from the drain blueprint and
     apps/n8n/blueprint.yml, not assumed — and no answer is said as "unknown", never a traceback;
  5. a drain of the instance already alive refuses a second start unless --force; a dry FULL sweep is asked about;
  6. the follower reads n8n's own tables, ends on the drain's end, survives a missed read, stops on a vanished row,
     and on a non-terminal output prints only when the counts change;
  7. lanes are THIS drain's: matched by DRAINER_ID "drain:<id>", once each, then followed by id;
  8. the verdict is the drain's Summarize output, read from flatted execution data; ATTENTION exits non-zero;
  9. the contract is the drain's own: path, modes, `dry`, DRAINER_ID and Summarize's fields read from its blueprint.
"""
import base64
import importlib.util
import io
import json
import pathlib
import re
import types
import unittest
import unittest.mock

HERE = pathlib.Path(__file__).resolve().parent
INDOX = HERE.parent
REPO = INDOX.parent.parent
spec = importlib.util.spec_from_file_location("drain", INDOX / "hooks" / "drain.py")
drain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drain)

ENV = {"BS_WEBHOOK_USER": "bsu", "BS_WEBHOOK_PASS": "bsp", "N8N_WEBHOOK_USER": "WRONG", "N8N_WEBHOOK_PASS": "WRONG",
       "DEPLOYMENT_NAME": "office", "POSTGRES_USER": "root", "POSTGRES_DB": "n8n", "DEPLOYMENT_DOMAIN": "x.co.il"}
drain.env = lambda k, d="": ENV.get(k, d)


def args(**kw):
    base = dict(instance="main", ids=[], company=None, status=None, changed=False, dry=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


class Http:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, path, method="GET", body=None, headers=None, timeout=90):
        self.calls.append((method, path, body, headers or {}))
        return self.answer


class Sql:
    """Stands in for `docker exec … psql`: answers by the first pattern the query matches."""

    def __init__(self, *answers):
        self.answers, self.queries = list(answers), []

    def __call__(self, argv, **kw):
        q = argv[-1]
        self.queries.append((argv[:3], q))
        for rx, out in self.answers:
            if re.search(rx, q):
                out = out() if callable(out) else out
                return types.SimpleNamespace(returncode=0 if out is not None else 1, stdout=out or "", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def flatted(obj):
    """The `flatted` encoding n8n uses for execution data — enough of it to round-trip a plain JSON tree."""
    out, memo = [], {}

    def put(v):
        if isinstance(v, (dict, list)) or isinstance(v, str):
            out.append(None)
            i = len(out) - 1
            if isinstance(v, dict):
                out[i] = {k: (str(put(x)) if isinstance(x, (dict, list, str)) else x) for k, x in v.items()}
            elif isinstance(v, list):
                out[i] = [(str(put(x)) if isinstance(x, (dict, list, str)) else x) for x in v]
            else:
                out[i] = v
            return i
        return v
    put(obj)
    return json.dumps(out)


class DrainCli(unittest.TestCase):
    def test_decide_is_always_dry_and_main_acts_unless_asked(self):
        self.assertTrue(drain.body_for("decide", args())["dry"])
        self.assertFalse(drain.body_for("main", args())["dry"])
        self.assertTrue(drain.body_for("main", args(dry=True))["dry"])

    def test_the_four_modes_and_the_refusals(self):
        self.assertEqual(drain.body_for("main", args())["mode"], "all")
        self.assertEqual(drain.body_for("main", args(ids=["a1", "a2"])),
                         {"__instance": "main", "dry": False, "mode": "ids", "ids": ["a1", "a2"]})
        self.assertEqual(drain.body_for("main", args(status="MISSING_LINK"))["status"], "MISSING_LINK")
        self.assertEqual(drain.body_for("main", args(changed=True))["mode"], "changed")
        for bad in (args(instance=""), args(instance="Main-1"), args(status="X", changed=True), args(ids=["a"], status="X")):
            with self.assertRaises(SystemExit):
                drain.body_for("main", bad)

    def test_company_is_one_select_in_the_instance_schema(self):
        sql = Sql((r"incoming_documents", "d1\nd2\n"))
        self.assertEqual(drain.company_ids("main", "51'4", run=sql), ["d1", "d2"])
        argv3, q = sql.queries[0]
        self.assertEqual(argv3, ["docker", "exec", "supabase-db-office"])
        self.assertTrue(q.lower().startswith("select ") and "indox_main.incoming_documents" in q and "'51''4'" in q, q)
        with self.assertRaises(SystemExit):
            drain.company_ids("main", "x", run=Sql((r".", None)))

    def test_the_webhook_gets_the_credential_its_node_uses(self):
        bp = (INDOX / "blueprint" / "n8n" / "indoxV2BaseDrain01.workflow.ts").read_text(encoding="utf-8")
        node = bp[bp.find("name: 'Drain Webhook'"):][:2000]
        cred = re.search(r"credentials:\s*\{\s*httpBasicAuth:\s*\{\s*id:\s*'([^']+)'", node).group(1)
        mapping = (REPO / "apps" / "n8n" / "blueprint.yml").read_text(encoding="utf-8")
        line = next(l for l in mapping.splitlines() if l.strip().startswith(cred + ":"))
        user_key, pass_key = re.search(r'"user":"\$\{(\w+)\}","password":"\$\{(\w+)\}"', line).groups()
        http = Http((200, {}, json.dumps({"accepted": True, "drain_execution": 4242})))
        self.assertEqual(drain.start({"mode": "all", "dry": True, "__instance": "main"}, http=http), "4242")
        sent = http.calls[0][3]["Authorization"]
        self.assertEqual(sent, "Basic " + base64.b64encode(f"{ENV[user_key]}:{ENV[pass_key]}".encode()).decode(),
                         f"the drain webhook's credential {cred} is {user_key}/{pass_key} — drain.py must send those")
        self.assertEqual(http.calls[0][:2], ("POST", "/webhook/indox-drain"))

    def test_no_answer_is_unknown_and_a_refusal_is_said(self):
        with self.assertRaises(SystemExit) as gone:
            drain.start({"mode": "all"}, http=Http((0, {}, "URLError: refused")))
        self.assertIn("UNKNOWN", str(gone.exception))
        with self.assertRaises(SystemExit) as denied:
            drain.start({"mode": "all"}, http=Http((401, {}, "Authorization data is wrong!")))
        self.assertIn("BS_WEBHOOK_USER", str(denied.exception))
        for refusal in ((500, {}, "oops"), (200, {}, json.dumps({"accepted": False})), (200, {}, "not json")):
            with self.assertRaises(SystemExit):
                drain.start({"mode": "all"}, http=Http(refusal))

    def test_an_alive_drain_refuses_a_second_and_a_dry_full_sweep_needs_sweep(self):
        with unittest.mock.patch.object(drain, "alive_drains", return_value=["311"]), \
             unittest.mock.patch.object(drain, "start") as st:
            with self.assertRaises(SystemExit) as busy:
                drain.main(["main", "--instance", "main", "--id", "a1"])
            with self.assertRaises(SystemExit):                       # --sweep is not --force: the guard stays
                drain.main(["decide", "--instance", "main", "--sweep"])
            st.assert_not_called()
        self.assertIn("311", str(busy.exception))
        with unittest.mock.patch.object(drain, "alive_drains", return_value=None), \
             unittest.mock.patch.object(drain, "start") as st:
            with self.assertRaises(SystemExit) as unknown:             # an unreadable database is "maybe alive"
                drain.main(["main", "--instance", "main", "--id", "a1"])
            st.assert_not_called()
        self.assertIn("unknown", str(unknown.exception))
        with unittest.mock.patch.object(drain, "alive_drains", return_value=[]), \
             unittest.mock.patch.object(drain, "start") as st, unittest.mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(drain.main(["decide", "--instance", "main"]), 2)
            self.assertEqual(drain.main(["decide", "--instance", "main", "--force"]), 2, "--force is not --sweep")
            st.assert_not_called()

    def test_alive_reads_the_drains_instance_not_any_string_main(self):
        mine = flatted({"__instance": "main", "mode": "ids", "connections": {"main": [[]]}})
        other = flatted({"__instance": "example", "connections": {"main": [[]]}, "note": "main"})
        sql = Sql((r"indoxV2BaseDrain01", f"311|{mine}\n312|{other}\n313|\n"))
        self.assertEqual(drain.alive_drains("main", run=sql), ["311", "313"],
                         "312 is example's drain — every execution holds the string \"main\"; 313 has no data yet")
        self.assertEqual(drain.alive_drains("example", run=sql), ["312", "313"])
        self.assertIsNone(drain.alive_drains("main", run=Sql((r".", None))))
        with unittest.mock.patch.object(drain, "alive_drains", return_value=["311"]), \
             unittest.mock.patch.object(drain, "start") as st, unittest.mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(drain.main(["main", "--instance", "main", "--alive"]), 0)
            st.assert_not_called()
        self.assertIn("311", out.getvalue())

    def test_the_no_answer_hint_starts_nothing(self):
        with self.assertRaises(SystemExit) as gone:
            drain.start({"mode": "ids"}, http=Http((0, {}, "timed out")))
        hint = re.search(r"`(bbox indox [^`]+)`", str(gone.exception)).group(1)
        self.assertIn("--alive", hint, "the look after a timeout must not be a command that starts a sweep")

    def test_the_follower_reads_n8ns_tables_and_ends_with_the_drain(self):
        rows = iter([("running", "2026-11-10 01:00:00"), None, ("running", "2026-11-10 01:00:00"),
                     ("success", "2026-11-10 01:00:00")])
        counts = iter([{"running": 2}, {"running": 2}, {"success": 3, "error": 1}])
        out = io.StringIO()
        lanes = types.SimpleNamespace(poll=lambda since: next(counts))
        self.assertEqual(drain.follow("77", row=lambda e: next(rows), lanes=lanes, sleep=lambda s: None, out=out,
                                      tty=False), "success")
        printed = out.getvalue().strip().splitlines()
        self.assertEqual(len(printed), 2, printed)            # unchanged counts are not printed again off a terminal
        self.assertIn("lanes 3/4 done, 1 failed", printed[-1])
        self.assertEqual(drain.follow("9", row=lambda e: (), lanes=lanes, sleep=lambda s: None, out=io.StringIO()), "gone")
        self.assertEqual(drain.follow("9", row=lambda e: None, lanes=lanes, sleep=lambda s: None, out=io.StringIO(),
                                      misses_max=3), "unreadable")

    def test_lanes_are_this_drains_and_each_run_is_read_once(self):
        # 501 is ours, 502 another drain's, 503 ours, 504 not written yet (and 505 behind it): the cursor passes every
        # written run, ours or not, and stops at the first unwritten one — so no finished run is re-read every poll
        found = iter(["501|t|t\n502|t|f\n503|t|t\n504|f|f\n505|t|t\n", "504|t|t\n505|t|t\n"])
        sql = Sql((r"from execution_entity e left join execution_data", lambda: next(found)),
                  (r"group by status", "success|2\nrunning|1\n"))
        lanes = drain.Lanes("500", run=sql)
        self.assertEqual(lanes.poll("2026-11-10 01:00:00"), {"success": 2, "running": 1})
        self.assertEqual((lanes.mine, lanes.last_id), (["501", "503"], 503))
        self.assertIn('"drain:500"', sql.queries[0][1])
        self.assertIn("e.id > 500", sql.queries[0][1])
        lanes.poll("2026-11-10 01:00:00")
        self.assertIn("e.id > 503", sql.queries[2][1])
        self.assertEqual((lanes.mine, lanes.last_id), (["501", "503", "504", "505"], 505))
        self.assertIn("id in (501,503,504,505)", sql.queries[3][1])
        self.assertEqual(sql.queries[0][0], ["docker", "exec", "n8n-postgres-office"])
        self.assertEqual(drain.Lanes("1", run=Sql()).poll("'; drop table x; --"), {})

    def test_the_verdict_is_the_drains_summarize_read_in_postgres(self):
        summary = {"RESULT": "ATTENTION", "documentsSelected": 7, "documentsDispatched": 7, "nonSuccess": 1,
                   "nonSuccessDetail": "g1:error:88", "batchesCompleted": 1, "batchesTotal": 1}
        sql = Sql((r"Summarize", json.dumps(summary, ensure_ascii=False) + "\n"))
        self.assertEqual(drain.verdict("88", run=sql, sleep=lambda s: None), summary)
        q = sql.queries[0][1]
        for step in ("resultData", "runData", "Summarize", "'data'", "'main'", "'json'", "jsonb_object_agg"):
            self.assertIn(step, q)
        self.assertIn('"executionId" = 88', q)
        tries = iter(["", json.dumps(summary)])                 # status before data: read again once
        self.assertEqual(drain.verdict("88", run=Sql((r"Summarize", lambda: next(tries))), sleep=lambda s: None), summary)
        self.assertIsNone(drain.verdict("88", run=Sql((r"Summarize", "")), sleep=lambda s: None))
        self.assertIsNone(drain.verdict("8;8", run=Sql(), sleep=lambda s: None))
        line_sep = dict(summary, nonSuccessDetail="a b")    # JSON keeps U+2028 raw; a row must not be cut there
        self.assertEqual(drain.verdict("88", run=Sql((r"Summarize", json.dumps(line_sep, ensure_ascii=False))),
                                       sleep=lambda s: None)["nonSuccessDetail"], "a b")
        with unittest.mock.patch.object(drain, "alive_drains", return_value=[]), \
             unittest.mock.patch.object(drain, "start", return_value="88"), \
             unittest.mock.patch.object(drain, "follow", return_value="success"), \
             unittest.mock.patch.object(drain, "verdict", return_value=summary), \
             unittest.mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(drain.main(["main", "--instance", "main", "--id", "a1"]), 1, "ATTENTION must not exit 0")
            self.assertIn("1 not successful: g1:error:88", out.getvalue())
        with unittest.mock.patch.object(drain, "alive_drains", return_value=[]), \
             unittest.mock.patch.object(drain, "start", return_value="88"), \
             unittest.mock.patch.object(drain, "follow", return_value="success"), \
             unittest.mock.patch.object(drain, "verdict", return_value=dict(summary, RESULT="OK", nonSuccess=0)), \
             unittest.mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(drain.main(["main", "--instance", "main", "--id", "a1"]), 0)

    def test_the_contract_is_the_drains_own(self):
        flat = lambda p: re.sub(r"\s+", " ", (INDOX / "blueprint" / "n8n" / p).read_text(encoding="utf-8"))
        bp, drv = flat("indoxV2BaseDrain01.workflow.ts"), flat("indoxV2Driver01.workflow.ts")
        for what, rx in (("the webhook path", r"path: 'indox-drain'"),
                         ("basic auth", r"authentication: 'basicAuth'"),
                         ("the answer names the drain execution", r'"drain_execution": \$execution\.id'),
                         ("the four modes", r"mode = all \| ids \| status \| changed"),
                         ("`dry` read from the body", r"const dry = \(body\.dry === true"),
                         ("DRAINER_ID on each lane", r"name: 'DRAINER_ID', value: '=\{\{ \"drain:\" \+ \$execution\.id \}\}'"),
                         ("Summarize's verdict fields", r"RESULT: .*'OK' : 'ATTENTION'.*documentsSelected.*documentsDispatched.*nonSuccess")):
            self.assertTrue(re.search(rx, bp), f"indoxV2BaseDrain01 no longer has {what} — drain.py speaks to it")
        self.assertTrue(re.search(r"this\.IfDry\.out\(0\)\.to\(this\.DrySkipPark\.in\(0\)\)", drv) and
                        re.search(r"this\.IfDry\.out\(1\)\.to\(this\.TakingAction\.in\(0\)\)", drv),
                        "the driver's dry gate is no longer wired dry → park, wet → Taking Action — "
                        "`bbox indox decide` relies on a dry lane acting on nothing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
