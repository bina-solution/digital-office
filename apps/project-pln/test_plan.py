"""test_plan.py — plan.py against a fake Plane that counts every request (DGO-559).

    cd apps/project-pln && python -m pytest test_plan.py -q        # or: python test_plan.py

Why a fake and not the office: what this proves is a COUNT — the second apply of an unchanged plan
writes nothing, one changed field is one PATCH, `--only` reads one item and not the project — and a
count needs every request seen. The fake answers the routes plan.py uses the way Plane's v1 API does
where it matters here: an item's `description_stripped` is Django's strip_tags over the stored HTML
(adjacent blocks glued: `<p>A</p><p>B</p>` → "AB"), the item payload names no module, and a lookup by
(external_source, external_id) answers the one item or 404. Each run loads plan.py afresh, the plan on
stdin, the RESULT line read back — the same contract hooks/plan speaks.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN_PY = os.environ.get("PLAN_UNDER_TEST") or os.path.join(HERE, "plan.py")   # another plan.py, to measure it
WS = "/api/v1/workspaces/bina"
PAGE = 3                                   # small pages, so the cursor path of plan.py's page() is walked


def strip_tags(s: str) -> str:
    """What Django's strip_tags leaves: tags gone, nothing in their place, entities as they were."""
    return re.sub(r"<[^>]*>", "", s or "")


class Store:
    def __init__(self):
        self.calls: list = []              # (method, path?query) — every request, in order
        self.lookup = True                 # answers the (external_source, external_id) pair; False = an API that pages instead
        self.refuse: list = []             # [(method, path pattern, HTTP code)] — requests this Plane turns away
        self.projects, self.states, self.labels, self.modules, self.issues, self.members = {}, {}, {}, {}, {}, {}
        self.relations: dict = {}          # issue id -> the ids it `relates_to` (symmetric, as Plane keeps it)
        self.seq = 0

    def since(self, mark: int) -> list:
        return self.calls[mark:]

    @staticmethod
    def count(calls: list, method: str, pattern: str) -> int:
        return sum(1 for m, p in calls if m == method and re.search(pattern, p))

    @staticmethod
    def writes(calls: list) -> list:
        return [(m, p) for m, p in calls if m != "GET"]

    def item(self, key: str) -> dict:
        return next(i for pid in self.issues for i in self.issues[pid].values() if i.get("external_id") == key)


class Handler(BaseHTTPRequestHandler):
    store: Store = Store()

    def log_message(self, *a):            # the test's output is the assertion, not the access log
        pass

    def _send(self, code: int, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _page(self, rows: list, q: dict):
        at = int(q.get("cursor") or 0)
        self._send(200, {"results": rows[at:at + PAGE], "next_page_results": at + PAGE < len(rows), "next_cursor": str(at + PAGE)})

    @staticmethod
    def _issue(i: dict, q: dict) -> dict:
        out = {k: v for k, v in i.items()}
        out["description_stripped"] = strip_tags(i.get("description_html") or "")
        if "labels" in (q.get("expand") or ""):
            out["labels"] = [{"id": l, "name": l} for l in i.get("labels") or []]
        return out                          # no module_ids / modules: the v1 payload has none

    def do_GET(self): self._route("GET")        # noqa: E704
    def do_POST(self): self._route("POST")      # noqa: E704
    def do_PATCH(self): self._route("PATCH")    # noqa: E704

    def _route(self, method: str):
        s = self.store
        s.calls.append((method, self.path))
        u = urllib.parse.urlsplit(self.path)
        path, q = u.path, dict(urllib.parse.parse_qsl(u.query))
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else {}
        for rm, rp, rc in s.refuse:
            if rm == method and re.search(rp, path):
                return self._send(rc, {"error": "refused by the test"})
        m = re.fullmatch(r"/api/instances/([^/]+)/secret", path)
        if m:                               # the credential plane: an account per plan name
            return self._send(200, {"secret": {"token": "tok", "user_id": "user-" + m.group(1).rsplit("-", 1)[-1]}})
        if not path.startswith(WS + "/"):
            return self._send(404, {"error": f"no route {path}"})
        rest = path[len(WS):]
        m = re.fullmatch(r"/work-items/([A-Z0-9]+)-(\d+)/", rest)
        if m:                               # one item by its ref, in any project (the API's by-identifier route)
            for pid, pr in s.projects.items():
                hit = next((i for i in s.issues[pid].values() if str(i.get("sequence_id")) == m.group(2)), None)
                if pr.get("identifier") == m.group(1) and hit:
                    return self._send(200, {**hit, "project": pid})
            return self._send(404, {"error": "The required object does not exist."})
        if rest == "/projects/":
            if method == "GET":
                return self._page(list(s.projects.values()), q)
            pid = "proj-" + body["identifier"].lower()
            s.projects[pid] = {"id": pid, **body}
            s.states[pid] = {f"st-{g}-{pid}": {"id": f"st-{g}-{pid}", "name": nm, "group": g} for g, nm in
                             [("backlog", "Backlog"), ("unstarted", "Todo"), ("started", "In Progress"),
                              ("completed", "Done"), ("cancelled", "Cancelled")]}
            s.labels[pid], s.modules[pid], s.issues[pid] = {}, {}, {}
            return self._send(201, s.projects[pid])
        m = re.fullmatch(r"/projects/([^/]+)/(.*)", rest)
        pid, sub = m.group(1), m.group(2)
        if pid not in s.projects:
            return self._send(404, {"error": "no such project"})
        if sub == "":
            if method == "PATCH":
                s.projects[pid].update(body)
            return self._send(200, s.projects[pid])
        if sub == "states/":
            return self._page(list(s.states[pid].values()), q)
        m = re.fullmatch(r"states/([^/]+)/", sub)
        if m:
            s.states[pid][m.group(1)].update(body)
            return self._send(200, s.states[pid][m.group(1)])
        if sub == "labels/":
            if method == "GET":
                return self._page(list(s.labels[pid].values()), q)
            if any(l["name"] == body.get("name") for l in s.labels[pid].values()):      # Plane: IntegrityError → 400
                return self._send(400, {"error": "Label with the same name already exists in the project"})
            lid = "lab-" + uuid.uuid4().hex[:6]
            s.labels[pid][lid] = {"id": lid, **body}
            return self._send(201, s.labels[pid][lid])
        if sub == "modules/":
            if method == "GET":
                return self._page(list(s.modules[pid].values()), q)
            if any(m["name"] == body.get("name") for m in s.modules[pid].values()):     # Plane: 409
                return self._send(409, {"error": "Module with the same name already exists"})
            mid = "mod-" + uuid.uuid4().hex[:6]
            s.modules[pid][mid] = {"id": mid, **body}
            s.members[mid] = set()
            return self._send(201, s.modules[pid][mid])
        m = re.fullmatch(r"modules/([^/]+)/", sub)
        if m:
            s.modules[pid][m.group(1)].update(body)
            return self._send(200, s.modules[pid][m.group(1)])
        m = re.fullmatch(r"modules/([^/]+)/module-issues/", sub)
        if m:
            mid = m.group(1)
            if method == "GET":
                return self._page([self._issue(s.issues[pid][i], q) for i in sorted(s.members[mid])], q)
            s.members[mid] |= set(body.get("issues") or [])
            return self._send(201, [])
        if sub == "issues/":
            if method == "GET":
                if s.lookup and q.get("external_id") and q.get("external_source"):
                    hit = next((i for i in s.issues[pid].values() if i.get("external_id") == q["external_id"]
                                and i.get("external_source") == q["external_source"]), None)
                    return self._send(200, self._issue(hit, q)) if hit else \
                        self._send(404, {"error": "The required object does not exist."})
                return self._page([self._issue(i, q) for i in s.issues[pid].values()], q)
            s.seq += 1
            iid = "iss-" + uuid.uuid4().hex[:6]
            s.issues[pid][iid] = {"id": iid, "sequence_id": s.seq, "assignees": [], "labels": [], **body}
            return self._send(201, self._issue(s.issues[pid][iid], q))
        m = re.fullmatch(r"issues/([^/]+)/", sub)
        if m:
            s.issues[pid][m.group(1)].update(body)
            return self._send(200, self._issue(s.issues[pid][m.group(1)], q))
        m = re.fullmatch(r"work-items/([^/]+)/relations/", sub)
        if m:                               # `relates_to` both ways, as Plane stores one row and shows it on each side
            iid = m.group(1)
            if method == "GET":
                return self._send(200, {"relates_to": [{"project_id": next(p for p in s.issues if o in s.issues[p]),
                                                        "issue_id": o} for o in sorted(s.relations.get(iid, set()))]})
            for o in body.get("issues") or []:
                s.relations.setdefault(iid, set()).add(o)
                s.relations.setdefault(o, set()).add(iid)
            return self._send(201, [])
        return self._send(404, {"error": f"no route {method} {path}"})


_server: list = []
_tmp = tempfile.mkdtemp(prefix="plan-test-")


def world() -> Store:
    """One fake Plane for the whole file, started on first use; every test begins on a fresh store."""
    if not _server:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _server.append(srv)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        os.environ.update({"PLANE_API_URL": base, "CONNECTIONS_URL": base, "PLANE_WORKSPACE": "bina",
                           "TASKS_CACHE": os.path.join(_tmp, "plane-tasks-cache.json"),
                           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    Handler.store = Store()
    for f in (os.environ["TASKS_CACHE"], os.environ["TASKS_CACHE"] + ".tmp"):
        if os.path.exists(f):
            os.remove(f)
    return Handler.store


def load(**env):
    """plan.py as a fresh module (one process per run is the contract; here one module per run)."""
    for k in ("PLANE_PLAN_DRY_RUN", "PLANE_PLAN_ONLY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location(f"plan_{uuid.uuid4().hex}", PLAN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PACE = 0                            # the pace is Plane's limit, not the fake's
    return mod


def run(plan: dict, argv: list | None = None, **env):
    """One apply, the way hooks/plan does it: the plan on stdin, `[project-pln]` lines and RESULT| out."""
    old_argv, old_stdin = sys.argv, sys.stdin
    sys.argv, sys.stdin = ["-c"] + (argv or []), io.StringIO(json.dumps(plan, ensure_ascii=False))
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            load(**env).main()
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    text = out.getvalue()
    result = json.loads(text.rsplit("RESULT|", 1)[1].splitlines()[0])
    return result, text


def a_plan() -> dict:
    return {
        "project": {"identifier": "TST", "name": "the test project", "description": "its text", "network": 0},
        "states": {"backlog": "מלאי", "unstarted": "לביצוע", "started": "בתהליך", "completed": "בוצע", "cancelled": "בוטל"},
        "labels": [{"name": "שער", "color": "#8b5cf6"}, {"name": "באג", "color": "#dc2626"}],
        "people": {"azaria": {"vault": "plane_local_api_token-azaria"}},
        "defaults": {"assignee": ""},
        "modules": [
            {"key": "m1", "name": "שלב 1 · first", "status": "planned", "description": "the first phase", "items": [
                {"key": "a-001", "name": "one", "priority": "high", "labels": ["שער"],
                 "description": "מה נדרש: A & B <x>\nמקור: the session\n- bullet one\n- bullet \"two\""},
                {"key": "a-002", "name": "two", "priority": "none", "labels": [],
                 "description": "second line\n\nthird paragraph"},
                {"key": "a-003", "name": "three", "assignee": "azaria", "labels": ["באג"],
                 "description": "«quoted» 'single'"}]},
            {"key": "m2", "name": "שלב 2 · second", "status": "backlog", "items": [
                {"key": "b-001", "name": "four", "priority": "low", "description": ""}]}]}


ISSUE_LIST = r"/issues/\?(?!.*external_id)"     # the page of every item, as opposed to one item's lookup


# ── the comparison ──────────────────────────────────────────────────────────────
def test_words_compares_content_not_markup():
    world()
    w = load().words
    assert w("<p>A</p><p>B</p>") == w("AB") == w("A\nB") == w(" A  B ")      # Django's strip_tags glues blocks
    assert w("<ul><li>x</li><li>y</li></ul>") == w("xy")
    assert w('x &amp; &quot;y&quot; &#39;z&#39;&nbsp;!') == w("x & \"y\" 'z' !")
    assert w('<p class="editor-paragraph">A</p>') == w("A")                   # the editor's rewrite
    assert w("A") != w("B")


# ── the counts ──────────────────────────────────────────────────────────────────
def test_second_apply_writes_nothing():
    s = world()
    plan = a_plan()
    r1, _ = run(plan)
    assert "project:TST" in r1["created"] and r1["items"] == 4 and r1["problems"] == []
    assert sorted(x for x in r1["created"] if x.startswith("item:")) == ["item:a-001", "item:a-002", "item:a-003", "item:b-001"]
    assert s.count(s.calls, "POST", r"/module-issues/") == 2             # each module filled once
    assert s.item("a-003")["assignees"] == ["user-azaria"]

    mark = len(s.calls)
    r2, text = run(plan)
    assert s.writes(s.since(mark)) == [], s.writes(s.since(mark))
    assert r2["created"] == [] and r2["updated"] == [] and r2["problems"] == []
    assert {"item:a-001", "item:a-002", "item:a-003", "item:b-001", "module:m1", "module:m2", "project:TST"} <= set(r2["kept"])
    assert r2["items"] == 4 and r2["dry_run"] is False
    # the slow reads came from the cache tasks.py keeps
    assert s.count(s.since(mark), "GET", r"/projects/\?") == 0
    assert s.count(s.since(mark), "GET", r"/(states|labels|modules)/\?") == 0
    assert s.count(s.since(mark), "GET", ISSUE_LIST) == 2                    # 4 items, pages of 3
    assert r2["timing"]["writes"] == 0 and r2["timing"]["reads"] >= 1 and r2["timing"]["seconds"] >= 0
    assert re.search(r"\[project-pln\] \d+ reads, 0 writes, [\d.]+ s", text)
    with open(os.environ["TASKS_CACHE"]) as f:
        cache = json.load(f)
    assert cache["bina:projects"]["v"][0]["identifier"] == "TST"
    assert {k.split(":")[1] for k in cache if k != "bina:projects"} == {"states", "labels", "modules"}


def test_each_changed_field_is_one_patch():
    s = world()
    plan = a_plan()
    run(plan); run(plan)
    item = plan["modules"][0]["items"][0]
    for field, value in (("name", "one, renamed"), ("description", "מה נדרש: something else"),
                         ("priority", "urgent"), ("labels", ["שער", "באג"])):
        item[field] = value
        mark = len(s.calls)
        r, _ = run(plan)
        writes = s.writes(s.since(mark))
        assert len(writes) == 1 and writes[0][0] == "PATCH" and f"/issues/{s.item('a-001')['id']}/" in writes[0][1], (field, writes)
        assert r["updated"] == ["item:a-001"] and len([k for k in r["kept"] if k.startswith("item:")]) == 3
    assert s.item("a-001")["name"] == "one, renamed" and s.item("a-001")["priority"] == "urgent"
    mark = len(s.calls)
    r, _ = run(plan)
    assert s.writes(s.since(mark)) == [] and r["updated"] == []


def test_only_applies_the_named_keys():
    s = world()
    plan = a_plan()
    run(plan)
    plan["modules"][0]["items"][0]["name"] = "one, changed"
    plan["modules"][1]["items"][0]["name"] = "four, changed"
    mark = len(s.calls)
    r, _ = run(plan, PLANE_PLAN_ONLY="b-001")
    calls = s.since(mark)
    assert s.count(calls, "GET", ISSUE_LIST) == 0                          # no page of every item
    assert s.count(calls, "GET", r"external_id=b-001") == 1
    assert s.writes(calls) == [("PATCH", f"{WS}/projects/proj-tst/issues/{s.item('b-001')['id']}/")]
    assert r["updated"] == ["item:b-001"] and r["items"] == 1 and r["only"] == ["b-001"]
    assert s.item("a-001")["name"] == "one"                                # not read, not touched
    assert len(calls) <= 6, calls                                          # vault, lookup, members, PATCH — a few requests

    mark = len(s.calls)
    r, _ = run(plan, ["--only", "a-001,b-001"])
    assert s.writes(s.since(mark)) == [("PATCH", f"{WS}/projects/proj-tst/issues/{s.item('a-001')['id']}/")]
    assert r["updated"] == ["item:a-001"] and r["kept"][-1] == "item:b-001"


def test_only_refuses_a_key_the_plan_lacks():
    world()
    try:
        run(a_plan(), ["--only=c-999"])
    except SystemExit as e:
        assert "c-999" in str(e)
    else:
        raise AssertionError("an unknown key was accepted")


def test_lookup_falls_back_to_the_page_when_the_api_ignores_the_pair():
    s = world()
    plan = a_plan()
    run(plan)
    s.lookup = False
    mark = len(s.calls)
    r, _ = run(plan, PLANE_PLAN_ONLY="a-002")
    assert s.count(s.since(mark), "GET", ISSUE_LIST) >= 1
    assert r["created"] == [] and r["kept"][-1] == "item:a-002"            # found on the page, never created twice
    assert sum(1 for i in s.issues["proj-tst"].values() if i["external_id"] == "a-002") == 1


def test_dry_run_changes_nothing_and_says_what_it_would():
    s = world()
    plan = a_plan()
    run(plan)
    plan["modules"][0]["items"][1]["priority"] = "high"
    mark = len(s.calls)
    r, text = run(plan, PLANE_PLAN_DRY_RUN="1")
    assert s.writes(s.since(mark)) == []
    assert r["dry_run"] is True and "would update TST-2 [a-002]" in text
    assert "item:a-002" in r["kept"] and r["updated"] == []


def test_a_miss_rereads_and_a_write_refreshes_the_cache():
    s = world()
    plan = a_plan()
    run(plan)
    other = a_plan()
    other["project"] = {"identifier": "OTH", "name": "another", "description": "", "network": 0}
    mark = len(s.calls)
    r, _ = run(other)
    assert "project:OTH" in r["created"]
    assert s.count(s.since(mark), "GET", r"/projects/\?") == 1            # the cached list missed OTH: read once more
    with open(os.environ["TASKS_CACHE"]) as f:
        assert sorted(x["identifier"] for x in json.load(f)["bina:projects"]["v"]) == ["OTH", "TST"]
    plan["labels"].append({"name": "חדש", "color": "#000000"})
    r, _ = run(plan)
    assert "label:חדש" in r["created"]
    mark = len(s.calls)
    r, _ = run(plan)
    assert s.writes(s.since(mark)) == [] and "label:חדש" in r["kept"]      # the cache learnt the label: no second POST


def test_a_run_that_dies_after_creating_a_module_leaves_a_cache_the_next_run_can_use():
    s = world()
    plan = a_plan()
    run(plan)
    third = "שלב 3 · third"
    plan["modules"].append({"key": "m3", "name": third, "status": "backlog",
                            "items": [{"key": "c-001", "name": "five", "description": "x"}]})
    s.refuse = [("POST", r"/issues/$", 500)]                               # the step after the module: its item
    try:
        run(plan)
    except RuntimeError as e:
        assert "HTTP 500" in str(e)
    else:
        raise AssertionError("the run did not die")
    assert sum(1 for x in s.modules["proj-tst"].values() if x["name"] == third) == 1
    s.refuse = []
    mark = len(s.calls)
    r, _ = run(plan)
    assert s.count(s.since(mark), "POST", r"/modules/$") == 0              # the cache knew m3: not asked again
    assert "module:m3" in r["kept"] and "item:c-001" in r["created"] and r["problems"] == []
    # …and a cache OLDER than the object (the instant between the POST and its write, a person who
    # made it meanwhile) is survived too: asked, refused by name, read fresh, taken — never twice.
    with open(os.environ["TASKS_CACHE"]) as f:
        data = json.load(f)
    data["proj-tst:modules"]["v"] = [x for x in data["proj-tst:modules"]["v"] if x["name"] != third]
    data["proj-tst:labels"]["v"] = [x for x in data["proj-tst:labels"]["v"] if x["name"] != "שער"]
    with open(os.environ["TASKS_CACHE"], "w") as f:
        json.dump(data, f)
    mark = len(s.calls)
    r, text = run(plan)
    assert s.count(s.since(mark), "POST", r"/modules/$") == 1 and s.count(s.since(mark), "POST", r"/labels/$") == 1
    assert "found module " + third in text and "found label שער" in text
    assert "module:m3" in r["kept"] and "label:שער" in r["kept"] and r["created"] == [] and r["problems"] == []
    assert sum(1 for x in s.modules["proj-tst"].values() if x["name"] == third) == 1
    assert sum(1 for x in s.labels["proj-tst"].values() if x["name"] == "שער") == 1
    assert s.count(s.since(mark), "PATCH", r"/issues/") == 0               # a-001 keeps the label it had


# ── an item opened from a meeting (DGO-1005) ───────────────────────────────────
def test_an_item_from_a_meeting_is_related_to_it_once():
    """`meeting: <REF>` relates the item to the meeting's work item, both ways, also for an item that
    already exists; a second apply writes no relation; a meeting that is not there is a problem of the
    plan, said, and the rest still applies."""
    s = world()
    plan = a_plan()
    run(plan)
    meeting = s.item("a-002")                                              # any work item stands in for the meeting
    plan["modules"][0]["items"][0]["meeting"] = "TST-%d" % meeting["sequence_id"]
    mark = len(s.calls)
    run(plan)
    a1 = s.item("a-001")
    assert s.relations.get(a1["id"]) == {meeting["id"]} and s.relations.get(meeting["id"]) == {a1["id"]}, s.relations
    assert s.count(s.since(mark), "POST", r"/relations/$") == 1
    mark = len(s.calls)
    run(plan)
    assert s.count(s.since(mark), "POST", r"/relations/$") == 0
    plan["modules"][0]["items"][0]["meeting"] = "TST-999"
    result, _ = run(plan)
    assert any("meeting TST-999 not found" in p for p in result["problems"]), result["problems"]


def test_a_meeting_is_read_once_a_run_whatever_the_number_of_its_items():
    """Every item of one meeting costs no read of its own: the meeting is looked up once and its own list
    (symmetric) says what is related — an unchanged plan of a meeting's 29 items read 58 times before. An
    item that IS the meeting is never related to itself."""
    s = world()
    plan = a_plan()
    run(plan)
    meeting = s.item("a-002")
    ref = "TST-%d" % meeting["sequence_id"]
    for it in plan["modules"][0]["items"] + plan["modules"][1]["items"]:
        it["meeting"] = ref                                                # a-002 names itself: never related
    mark = len(s.calls)
    run(plan)
    calls = s.since(mark)
    assert s.count(calls, "POST", r"/relations/$") == 3, calls
    assert s.relations.get(meeting["id"]) == {s.item(k)["id"] for k in ("a-001", "a-003", "b-001")}, s.relations
    assert s.count(calls, "GET", r"/work-items/TST-\d+/$") == 1 and s.count(calls, "GET", r"/relations/$") == 1
    mark = len(s.calls)
    r, _ = run(plan)
    calls = s.since(mark)
    assert s.writes(calls) == [] and r["problems"] == []
    assert s.count(calls, "GET", r"/work-items/TST-\d+/$") == 1 and s.count(calls, "GET", r"/relations/$") == 1


def test_a_refused_relation_is_said_and_the_apply_goes_on():
    """A relation is an annotation: Plane refusing it (403, or a 502 that stays one) is a problem of the
    apply, and the items and the module filling after it still happen."""
    s = world()
    plan = a_plan()
    run(plan)
    plan["modules"][0]["items"][0]["meeting"] = "TST-%d" % s.item("a-002")["sequence_id"]
    plan["modules"][0]["items"].append({"key": "a-004", "name": "after", "description": "made after the refusal"})
    s.refuse = [("POST", r"/relations/$", 403)]
    r, _ = run(plan)
    assert any(p.startswith("a-001: not related to meeting TST-") for p in r["problems"]), r["problems"]
    assert "item:a-004" in r["created"] and s.item("a-004")["id"] in s.members[next(iter(s.modules["proj-tst"]))]


def tasks(*argv):
    """tasks.py's main, as `bbox project-pln tasks` runs it, against the same fake (a fresh module a call)."""
    spec = importlib.util.spec_from_file_location(f"tasks_{uuid.uuid4().hex}", os.path.join(os.path.dirname(PLAN_PY), "tasks.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with contextlib.redirect_stdout(io.StringIO()):
        return mod.main(list(argv))


def test_tasks_label_adds_by_name_and_link_relates_once():
    """`tasks label` ADDS a label by name and makes one the project lacks, in the palette's olive; before it
    makes one it reads the labels fresh, so a label made since the cache was written is taken, not refused
    as a duplicate; a flag's value is never a label. `tasks link` relates both ways, once, never to itself."""
    s = world()
    run(a_plan())
    a1, a2, a3 = (s.item(k) for k in ("a-001", "a-002", "a-003"))
    ref = {k: "TST-%d" % s.item(k)["sequence_id"] for k in ("a-001", "a-002", "a-003")}
    assert tasks("label", ref["a-001"], "נותח", "--project", "TST") == 0
    made = [x for x in s.labels["proj-tst"].values() if x["name"] == "נותח"]
    assert len(made) == 1 and made[0]["color"] == "#56693f", made
    assert not any(x["name"] == "TST" for x in s.labels["proj-tst"].values())       # --project's value
    assert made[0]["id"] in s.item("a-001")["labels"] and len(s.item("a-001")["labels"]) == 2   # שער kept
    s.labels["proj-tst"]["lab-other"] = {"id": "lab-other", "name": "אחר", "color": "#56693f"}  # made since
    mark = len(s.calls)
    assert tasks("label", ref["a-002"], "אחר") == 0
    assert s.count(s.since(mark), "POST", r"/labels/$") == 0 and "lab-other" in s.item("a-002")["labels"]
    mark = len(s.calls)
    assert tasks("link", ref["a-001"], ref["a-002"], ref["a-003"], ref["a-001"]) == 0
    assert s.relations.get(a1["id"]) == {a2["id"], a3["id"]} and s.relations.get(a2["id"]) == {a1["id"]}, s.relations
    assert s.count(s.since(mark), "POST", r"/relations/$") == 1
    mark = len(s.calls)
    assert tasks("link", ref["a-001"], ref["a-002"]) == 0
    assert s.count(s.since(mark), "POST", r"/relations/$") == 0


def test_a_dry_run_says_which_items_it_would_relate():
    s = world()
    plan = a_plan()
    run(plan)
    ref = "TST-%d" % s.item("a-002")["sequence_id"]
    plan["modules"][0]["items"][0]["meeting"] = ref
    plan["modules"][1]["items"][0]["meeting"] = "TST-999"
    mark = len(s.calls)
    r, text = run(plan, PLANE_PLAN_DRY_RUN="1")
    assert s.writes(s.since(mark)) == [] and s.relations == {}
    assert f"would relate [a-001] to {ref}" in text, text
    assert any("meeting TST-999 not found" in p for p in r["problems"]), r["problems"]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:                                         # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
