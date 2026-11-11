"""DGO-1755: the console's own doors ask who may go through them, since /a/<alias>/ reaches an app's container past
traefik's `authentik-admins@file`. Runs the real app.py under Flask's test client.

    python3 -m pytest platform-base/console/test_admins_doors.py -q      (or: python3 <this file>)
"""
import json
import pathlib
import sys
import tempfile
import types

MODULE_PATH = pathlib.Path(__file__).with_name("app.py")
app = types.ModuleType("console_app_admins_under_test")
app.__file__ = str(MODULE_PATH)
exec(compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec"), app.__dict__)

OWNER = {"X-authentik-username": "owner", "X-authentik-groups": "admins"}
DEV = {"X-authentik-username": "akadmin", "X-authentik-groups": "authentik Admins"}   # the SSO off
INVITED = {"X-authentik-username": "tamar", "X-authentik-groups": "people"}
NOBODY = {"X-authentik-username": "clerk", "X-authentik-groups": ""}


class Answer:
    status_code, is_redirect = 200, False
    headers = {"Content-Type": "text/html; charset=utf-8"}
    content = b"<html><head></head><body>APP-SCREEN-7f3a</body></html>"

    def iter_content(self, chunk_size=None):
        return iter((self.content,))

    def close(self):
        pass


def office(bases, doors=None):
    """The console with this compiled console.app_bases.json and these linked offices' doors; returns the restore."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="console-bases-"))
    (d / "console.app_bases.json").write_text(json.dumps(bases))
    real = (app._BASES_FILE, dict(app._BASES_SEEN), app._remote_doors, app._peer_entries, app.requests.request,
            app._proxy)
    app._BASES_FILE = str(d / "console.app_bases.json")
    app._BASES_SEEN.update(mtime=None, peers=None)
    app._remote_doors = lambda: doors or {}
    app._peer_entries = lambda: []
    app.requests.request = lambda *a, **k: Answer()
    app._proxy = lambda url: app.jsonify(proxied=url)

    def restore():
        app._BASES_FILE = real[0]
        app._BASES_SEEN.clear()
        app._BASES_SEEN.update(real[1])
        app._remote_doors, app._peer_entries, app.requests.request, app._proxy = real[2:]
    return restore


BASES = {"hostapp": {"env": None, "default": "http://hostapp:8080", "people": "admins"},
         "workapp": {"env": None, "default": "http://workapp:8975"}}


def test_an_admins_app_through_the_console_is_refused_to_anyone_but_an_admin():
    restore = office(BASES)
    try:
        c = app.app.test_client()
        page = c.get("/a/hostapp/", headers={**INVITED, "Accept": "text/html"})
        call = c.get("/a/hostapp/api/shell", headers={**INVITED, "Accept": "application/json"})
        nobody = c.get("/a/hostapp/", headers={**NOBODY, "Accept": "text/html"})
        owner = c.get("/a/hostapp/", headers={**OWNER, "Accept": "text/html"})
        dev = c.get("/a/hostapp/", headers={**DEV, "Accept": "text/html"})
        renamed = c.get("/a/hostapp/", headers={"X-authentik-username": "o", "X-authentik-groups": "x|authentik-admins",
                                                   "Accept": "text/html"})
        near = c.get("/a/hostapp/", headers={"X-authentik-username": "o", "X-authentik-groups": "admins-not|xadmins",
                                                "Accept": "text/html"})
        work = c.get("/a/workapp/", headers={**INVITED, "Accept": "text/html"})
        posted = c.post("/a/hostapp/api/exec", headers=INVITED, data=b"rm -rf /")
    finally:
        restore()
    assert page.status_code == 403 and "למנהלי הלשכה בלבד" in page.get_data(as_text=True)
    assert "APP-SCREEN-7f3a" not in page.get_data(as_text=True)
    assert call.status_code == 403 and call.get_json()["error"] == "admins_only"
    assert nobody.status_code == 403
    assert posted.status_code == 403, "every method"
    assert owner.status_code == 200 and "APP-SCREEN-7f3a" in owner.get_data(as_text=True)
    assert dev.status_code == 200, "the SSO off names authentik's admins group"
    assert renamed.status_code == 200, "a migration's authentik-admins is the admin group"
    assert near.status_code == 403, "a group is matched whole, never by a part of its name"
    assert work.status_code == 200, "an everyone app opens for an invited person"


def test_a_linked_offices_app_is_the_admins_until_its_office_says_who_opens_it():
    doors = {"workapp.macbook": {"base": "http://link:9000/workapp/", "office": "macbook", "oid": "macbook", "user": "u"}}
    restore = office(BASES, doors)
    try:
        c = app.app.test_client()
        invited = c.get("/a/workapp.macbook/", headers={**INVITED, "Accept": "text/html"})
    finally:
        restore()
    assert invited.status_code == 403


def test_the_credential_plane_and_a_services_accounts_are_the_admins_but_reads_stay_everyones():
    restore = office(BASES)
    app.SVC_BASES["svcdemo"] = "http://svcdemo:8970"     # a made-up service (G9: no layer-3 name here)
    try:
        c = app.app.test_client()
        cases = [
            ("GET", "/api/connections", INVITED, 403), ("GET", "/api/connections/x", INVITED, 403),
            ("POST", "/api/connections/x/set", INVITED, 403), ("GET", "/api/conn/oauth/g/start", INVITED, 403),
            ("POST", "/api/conn/regenerate", INVITED, 403),
            ("POST", "/api/svc/svcdemo/connections", INVITED, 403), ("DELETE", "/api/svc/svcdemo/connections/a1", INVITED, 403),
            ("POST", "/api/svc/svcdemo/connections/select", INVITED, 403),
            ("POST", "/api/language", INVITED, 403),
            # INDOX reads these from the browser for whoever uses it
            ("GET", "/api/svc/svcdemo/readyz", INVITED, 200), ("GET", "/api/svc/svcdemo/connections/a1/probe", INVITED, 200),
            ("GET", "/api/language", INVITED, 200),
            ("GET", "/api/me", INVITED, 200),
            ("GET", "/api/connections", OWNER, 200), ("POST", "/api/conn/regenerate", OWNER, 200),
            ("POST", "/api/svc/svcdemo/connections/select", OWNER, 200),
        ]
        got = [(m, p, h["X-authentik-username"], c.open(p, method=m, headers=h).status_code) for m, p, h, _ in cases]
    finally:
        restore()
        app.SVC_BASES.pop("svcdemo", None)
    want = [(m, p, h["X-authentik-username"], s) for m, p, h, s in cases]
    assert got == want, [g for g, w in zip(got, want) if g != w]


def test_the_compiled_file_says_who_and_a_file_that_does_not_read_keeps_the_last_word():
    restore = office(BASES)
    try:
        assert app._admins_alias("hostapp") and app._admins_alias("connections")
        assert not app._admins_alias("workapp")
        pathlib.Path(app._BASES_FILE).write_text("{ half a file")
        app._BASES_SEEN["mtime"] = -1                      # changed on disk: read again, and it does not read
        assert app._admins_alias("hostapp"), "a broken file must not open the door"
    finally:
        restore()


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, e)
    print("test_admins_doors:", "all passed" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
