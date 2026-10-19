"""Unit tests for the console's first-run landing — a fresh office meets the install wizard.

`spa()` decides, server-side, from the control plane's record (`/api/office`): no `installed_at` →
`/` is install.html; installed, or a plane that cannot be asked → the shell. A deep link is always
served as asked. And the bridge in `/api/business` (removed with core-003): an installed office with
no ledger names itself, so the shell's OLD landing no longer bounces a bare visit to the screen the
wizard replaced.

Run: python -m pytest platform-base/console/test_install_landing.py -q
"""
import pathlib
import types

MODULE_PATH = pathlib.Path(__file__).with_name("app.py")
app = types.ModuleType("console_landing_under_test")
app.__file__ = str(MODULE_PATH)
exec(compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec"), app.__dict__)

FRESH = {"office": {}, "installed": False}
INSTALLED = {"office": {"name": "הלשכה בחיפה", "animal": "deer", "hue": "lime",
                        "installed_at": "2026-10-09T18:01:00Z"}, "installed": True}


def _client(monkeypatch, record):
    monkeypatch.setattr(app, "_office_record", lambda fresh=False: record)
    return app.app.test_client()


def test_a_fresh_office_meets_the_wizard_not_the_shell(monkeypatch):
    r = _client(monkeypatch, FRESH).get("/")
    assert r.status_code == 200
    assert b'id="wizard"' in r.data and b'id="app"' not in r.data
    assert r.headers["Cache-Control"] == "no-cache"           # a wizard must not outlive its office


def test_an_installed_office_gets_the_shell(monkeypatch):
    r = _client(monkeypatch, INSTALLED).get("/")
    assert r.status_code == 200 and b'id="app"' in r.data and b'id="wizard"' not in r.data


def test_a_plane_that_cannot_be_asked_is_not_a_fresh_office(monkeypatch):
    r = _client(monkeypatch, None).get("/")
    assert r.status_code == 200 and b'id="app"' in r.data


def test_a_deep_link_is_served_as_asked_even_on_a_fresh_office(monkeypatch):
    c = _client(monkeypatch, FRESH)
    assert b"TERMS_VERSION" in c.get("/install.js").data
    assert b".wiz-steps" in c.get("/install.css").data
    # `/index.html` IS `/` to Flask (the rule's default; it answers with its canonical redirect), so
    # the shell's entry has exactly one spelling and the landing decision has exactly one door.
    r = c.get("/index.html")
    assert r.status_code == 308 and r.headers["Location"].endswith("/")


def _plane(monkeypatch, answers):
    """A control plane that answers the given records in order (the last one for ever after)."""
    asked = []

    class R:
        ok = True

        def __init__(self, rec):
            self.rec = rec

        def json(self):
            return dict(self.rec)

    def get(url, timeout):
        asked.append(url)
        return R(answers[min(len(asked) - 1, len(answers) - 1)])
    monkeypatch.setattr(app.requests, "get", get)
    monkeypatch.setattr(app, "_OFFICE", {"at": 0.0, "asked": False, "rec": None})
    return asked


def test_an_installed_office_is_remembered_and_then_asked_again(monkeypatch):
    asked = _plane(monkeypatch, [INSTALLED])
    assert app._first_run() is False
    assert app._first_run() is False
    assert len(asked) == 1 and asked[0].endswith("/api/office")
    app._OFFICE["at"] = 0.0                                  # the memory expired
    assert app._first_run() is False and len(asked) == 2


def test_a_fresh_office_is_asked_on_every_entry_so_the_wizards_last_step_is_seen_at_once(monkeypatch):
    asked = _plane(monkeypatch, [FRESH, FRESH, INSTALLED])
    assert app._first_run() is True                          # cached "fresh" → asked again at once
    assert app._first_run() is False                         # the record the wizard just wrote
    assert len(asked) == 3


def test_a_plane_that_answers_an_error_is_not_asked_on_every_entry(monkeypatch):
    asked = []

    def down(url, timeout):
        asked.append(url)
        raise app.requests.RequestException("refused")
    monkeypatch.setattr(app.requests, "get", down)
    monkeypatch.setattr(app, "_OFFICE", {"at": 0.0, "asked": False, "rec": None})
    assert app._first_run() is False and app._first_run() is False
    assert len(asked) == 1


def test_the_shell_reads_the_offices_own_record_for_its_brand_line(monkeypatch):
    r = _client(monkeypatch, INSTALLED).get("/api/office")
    assert r.status_code == 200
    assert r.get_json() == {"installed": True, "office": INSTALLED["office"]}


def test_a_fresh_office_says_so_and_a_plane_that_cannot_be_asked_says_unknown(monkeypatch):
    assert _client(monkeypatch, FRESH).get("/api/office").get_json() == {"installed": False, "office": {}}
    assert _client(monkeypatch, None).get("/api/office").get_json() == {"installed": None, "office": {}}


def test_the_ledgers_business_profile_is_no_longer_the_shells(monkeypatch):
    # core-003: the old install screen's business-identity step and its proxy are gone — the shell
    # has no /api/business, and nothing in it names the ledger.
    assert _client(monkeypatch, INSTALLED).get("/api/business").status_code in (200, 404)
    assert "APITOOLS_URL" not in dir(app)
    assert b"/api/business" not in (pathlib.Path(__file__).with_name("static") / "app.js").read_bytes()
