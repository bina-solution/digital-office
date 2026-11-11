"""POST /api/language: the control plane's write of the office's language (DGO-971).

    python -m pytest platform-base/app-management/test_language.py -q      (in the app's image: it needs Flask)

The write is reconcile.py's (`lang`, set_language(), gate G33's one writer), then the render that compiles
.generated/registry/locale.json. Here the REAL reconcile.py writes a throwaway office's platform.state.yaml;
only the render is a stand-in, which compiles locale.json with the real module's locale_doc(). What is held:
  * a linked caller is refused in the plane's own words, and nothing is written (G85);
  * a known code is written, every comment of the file kept, and the answer is the compiled document;
  * an unknown code is refused BY NAME (400) and nothing is written;
  * a write that fails is said (500), never answered as a switch.
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_language", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_language"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()
STATE = "# the model, in comments\nschema_version: 1\napps:\n  drive: { state: enabled, by: user }\n"


def _office():
    """A throwaway office: the real compiler and a state file. The plane is pointed at it."""
    repo = pathlib.Path(tempfile.mkdtemp(prefix="dgo971-plane-"))
    (repo / "platform" / "manager").mkdir(parents=True)
    for f in ("reconcile.py", "serve.py"):
        shutil.copy(ROOT / "platform" / "manager" / f, repo / "platform" / "manager" / f)
    (repo / "platform.state.yaml").write_text(STATE, encoding="utf-8")
    app.REPO, app.RECONCILE = str(repo), str(repo / "platform" / "manager" / "reconcile.py")

    def render():                                  # the stand-in: locale.json by the real locale_doc()
        code = ("import sys, json, yaml; sys.path.insert(0, 'platform/manager'); import reconcile as r; "
                "import pathlib; p = pathlib.Path('.generated/registry'); p.mkdir(parents=True, exist_ok=True); "
                "(p / 'locale.json').write_text(json.dumps(r.locale_doc(yaml.safe_load(open('platform.state.yaml'))), "
                "ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')")
        subprocess.run([sys.executable, "-c", code], cwd=repo, check=True, capture_output=True)
        return []
    app._render = render
    return repo


def test_a_linked_caller_is_refused_and_nothing_is_written():
    repo = _office()
    try:
        r = app.app.test_client().post("/api/language", json={"lang": "en"}, headers={app.OFFICE_HEADER: "macbook"})
        assert r.status_code == 403 and r.get_json()["error"] == "a linked office does not switch this office's language"
        assert (repo / "platform.state.yaml").read_text(encoding="utf-8") == STATE
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_a_known_code_is_written_by_the_one_writer_and_the_answer_is_compiled():
    repo = _office()
    try:
        r = app.app.test_client().post("/api/language", json={"lang": "EN", "by": "console"})
        body = r.get_json()
        assert r.status_code == 200 and body["ok"] is True and body["changed"] is True, body
        assert (body["active"], body["dir"]) == ("en", "ltr"), body
        after = (repo / "platform.state.yaml").read_text(encoding="utf-8")
        assert after == STATE.replace("schema_version: 1\n", "schema_version: 1\n\nlanguage: en   # by console\n"), after
        again = app.app.test_client().post("/api/language", json={"lang": "en", "by": "console"}).get_json()
        assert again["ok"] is True and again["changed"] is False, again
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_an_unknown_code_is_refused_by_name_and_nothing_is_written():
    repo = _office()
    try:
        for bad in ("eng", "", "he; rm -rf /"):
            r = app.app.test_client().post("/api/language", json={"lang": bad})
            body = r.get_json()
            assert r.status_code == 400 and body["error"] == "unknown_language", (bad, body)
            assert "expected one of en, he" in body["detail"], body
        assert (repo / "platform.state.yaml").read_text(encoding="utf-8") == STATE
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_what_a_caller_sends_never_makes_a_500_and_writes_nothing():
    """The second reader of slice 4, every one measured as a 500 on the first draft: a body that is not an object,
    a code (or a `by`) that argparse read as a flag, a NUL byte, a 3 MB code. Each is a 400 that says why."""
    repo = _office()
    c = app.app.test_client()
    try:
        for body in (["en"], "en", 3):
            r = c.post("/api/language", data=json.dumps(body), content_type="application/json")
            assert r.status_code == 400 and "JSON object" in r.get_json()["error"], (body, r.status_code, r.get_json())
        for code in ("-x", "--help"):
            r = c.post("/api/language", json={"lang": code})
            assert r.status_code == 400 and r.get_json()["error"] == "unknown_language", (code, r.get_json())
            assert "expected one of en, he" in r.get_json()["detail"], r.get_json()
        r = c.post("/api/language", json={"lang": "en", "by": "-x"})
        assert r.status_code == 200 and r.get_json()["ok"] is True, r.get_json()
        for code in ("he\x00", "e" * (3 << 20), "\ud800", "he\nen"):
            r = c.post("/api/language", json={"lang": code})
            assert r.status_code == 400 and r.get_json()["error"] == "unknown_language", (len(code), r.get_json())
        after = (repo / "platform.state.yaml").read_text(encoding="utf-8")
        assert after == STATE.replace("schema_version: 1\n", "schema_version: 1\n\nlanguage: en   # by -x\n"), after
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_a_lifecycle_under_way_is_a_409_not_a_wait():
    """The lower finding: the switch waited on the lifecycle lock with no timeout while the console waits 90 s."""
    import threading
    repo = _office()
    app.BRINGUP_WAIT_S, was = 0.2, app.BRINGUP_WAIT_S
    held = threading.Event()
    gone = threading.Event()

    def holder():                       # another thread holds the lifecycle, as a bring-up does
        with app._LIFECYCLE:
            held.set()
            gone.wait(10)
    t = threading.Thread(target=holder, daemon=True)
    t.start()
    held.wait(5)
    got = {}
    asker = threading.Thread(target=lambda: got.update(r=app.app.test_client().post("/api/language", json={"lang": "en"})),
                             daemon=True)
    asker.start()
    asker.join(5)                       # code that waits with no timeout fails here instead of hanging the run
    gone.set()
    t.join(5)
    try:
        assert "r" in got, "the switch was still waiting on the lifecycle lock after 5 s"
        assert got["r"].status_code == 409, (got["r"].status_code, got["r"].get_json())
        assert (repo / "platform.state.yaml").read_text(encoding="utf-8") == STATE
    finally:
        app.BRINGUP_WAIT_S = was
        shutil.rmtree(repo, ignore_errors=True)


def test_a_write_that_fails_is_said():
    repo = _office()
    try:
        (repo / "platform.state.yaml").write_text("apps: {}\n", encoding="utf-8")     # no schema_version to anchor
        r = app.app.test_client().post("/api/language", json={"lang": "en"})
        assert r.status_code == 500 and r.get_json()["error"] == "state_write_failed", r.get_json()
    finally:
        shutil.rmtree(repo, ignore_errors=True)
