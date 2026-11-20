"""test_pinned_login — the entry every office has, shown first: the office's main Google account (DGO-1825).

    python3 platform-base/connections/test_pinned_login.py

The owner: «חיבורים ומפתחות» comes, by default, with an entry for the office's main Google account; he types its
user and password there once, and the office browser signs in with them. Its provider (apps/browser42/app.json,
`browser42-login-google`) says `pin`, its words (`purpose_he`, `about_he`), a field it FIXES (the sign-in address,
which browser42's logins take a login's origin from) and a label of its own. What holds here:
  * the row carries `pin`, `purpose_he` and `about_he`; a row whose provider says none carries `pin: false`;
  * the row shows the user name saved for it (its USER companion), and only a pinned row is given one this way;
  * the fixed field is its value, clear, marked `fixed`, never a secret; the user field has the provider's label;
    the password stays a secret and is never in the fields' answer;
  * /api/set refuses to write a fixed field, by name, and stores nothing.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CONN_DATA_DIR", tempfile.mkdtemp(prefix="pinned-"))
import app  # noqa: E402

CID = "browser42-login-google"
PW = "Zq9-pinned-THEREALPASSWORD-for-this-test"       # not shaped like any provider's key (G92 reads tracked files)
PROV = {"id": CID, "group": "Apps", "kind": "password", "pillar": "app-password",
        "title": "Google — the office's main account", "title_he": "חשבון Google הראשי של הלשכה",
        "env": "BROWSER42_LOGIN_GOOGLE_PASSWORD",
        "envs_extra": ["BROWSER42_LOGIN_GOOGLE_USER", "BROWSER42_LOGIN_GOOGLE_URL"],
        "fixed": {"BROWSER42_LOGIN_GOOGLE_URL": "https://accounts.google.com/"},
        "labels": {"BROWSER42_LOGIN_GOOGLE_USER": "כתובת Gmail"},
        "reveal_to": ["browser42-task-runner"],
        "pin": True, "purpose_he": "הדפדפן של הלשכה נכנס איתו ל-Google לבד.", "about_he": "הסיסמה נשמרת בכספת.",
        "probe": {"type": "present"}}
STORE = {CID: PW, f"{CID}:BROWSER42_LOGIN_GOOGLE_USER": "person8.x@example.com"}


def _row(prov, store):
    real = (app.resolve, app.probe)
    app.resolve, app.probe = (lambda *a, **k: ("db", store.get(prov["id"]))), (lambda *a, **k: ("healthy", ""))
    try:
        return app._row(prov["id"], dict(prov), {}, dict(store))
    finally:
        app.resolve, app.probe = real


def test_the_pinned_row_says_what_it_is_and_whose_it_is():
    row = _row(PROV, STORE)
    assert row["pin"] is True and row["purpose_he"] == PROV["purpose_he"] and row["about_he"] == PROV["about_he"], row
    assert (row["app"] or {}).get("user") == "person8.x@example.com", row["app"]
    assert PW not in repr(row), "the password is in the row"


def test_a_row_whose_provider_says_nothing_is_not_pinned_and_gets_no_user_this_way():
    plain = {k: v for k, v in PROV.items() if k not in ("pin", "purpose_he", "about_he")}
    row = _row(plain, STORE)
    assert row["pin"] is False and row["purpose_he"] is None and row["app"] is None, row


def test_the_fixed_field_is_its_value_and_the_labels_are_the_providers():
    real = app.resolve
    app.resolve = lambda *a, **k: ("db", PW)
    try:
        fields = {f["key"]: f for f in app._cred_fields(CID, dict(PROV), dict(STORE))}
    finally:
        app.resolve = real
    url = fields["BROWSER42_LOGIN_GOOGLE_URL"]
    assert url == {**url, "fixed": True, "secret": False, "clear": "https://accounts.google.com/", "source": "env"}, url
    assert fields["BROWSER42_LOGIN_GOOGLE_USER"]["label"] == "כתובת Gmail"
    assert fields["BROWSER42_LOGIN_GOOGLE_USER"]["clear"] == "person8.x@example.com"
    pw = fields["BROWSER42_LOGIN_GOOGLE_PASSWORD"]
    assert pw["secret"] is True and pw["clear"] is None and "fixed" not in pw, pw
    assert PW not in repr(fields), "the password is in the fields' answer"


def test_writing_a_fixed_field_is_refused_and_stores_nothing():
    written = []
    real = (app.catalog, app.vault_read, app.vault_write)
    app.catalog = lambda: {CID: dict(PROV)}
    app.vault_read = lambda: dict(STORE)
    app.vault_write = lambda store: written.append(store)
    try:
        r = app.app.test_client().post(f"/api/set/{CID}",
                                       json={"field": "BROWSER42_LOGIN_GOOGLE_URL", "value": "https://evil.example/"})
        ok = app.app.test_client().post(f"/api/set/{CID}",
                                        json={"field": "BROWSER42_LOGIN_GOOGLE_USER", "value": "person90@example.com"})
    finally:
        app.catalog, app.vault_read, app.vault_write = real
    assert r.status_code == 400 and "fixed" in (r.get_json() or {}).get("error", ""), (r.status_code, r.get_data())
    assert ok.status_code == 200, ok.get_data()
    # (the audit line is a write of its own: what matters is what any write holds)
    assert any(w.get(f"{CID}:BROWSER42_LOGIN_GOOGLE_USER") == "person90@example.com" for w in written), written
    assert not any(f"{CID}:BROWSER42_LOGIN_GOOGLE_URL" in w for w in written), "a fixed field was stored"


VERIFIED = "container-id+ip"          # identity.py: the container id the caller sent owns its address
OFFICE = "office-a"                   # this vault's compose project (identity.own_project asks docker; not here)
app.identity.own_project = lambda: OFFICE


def _reveal_as(service, method=VERIFIED, headers=None, project=OFFICE):
    """POST /api/reveal as a caller the broker identifies as `service` by `method` (None: one it cannot name)."""
    audited = []
    real = (app.catalog, app.vault_read, app.broker.caller, app.broker.audit)
    app.catalog = lambda: {CID: dict(PROV)}
    app.vault_read = lambda: dict(STORE)
    app.broker.caller = lambda: ({"ok": True, "method": method, "service": service, "project": project} if service
                                 else {"ok": False, "method": "none"})
    app.broker.audit = lambda *a, **k: audited.append((a, k))
    try:
        r = app.app.test_client().post(f"/api/reveal/{CID}", json={}, headers=headers or {})
        return r.status_code, r.get_data(as_text=True), audited
    finally:
        app.catalog, app.vault_read, app.broker.caller, app.broker.audit = real


def test_the_password_is_revealed_to_the_task_runner_and_to_nobody_else():
    # NOT the browser's own container: the agent drives that Chrome, and whatever its container may fetch, a page in it
    # can fetch too (the third reader: /api/broker/whoami gives the id, a same-origin http fetch sends no Sec-Fetch)
    for service in ("bina-ds", "console", "browser42-browser", None):
        status, raw, audited = _reveal_as(service)
        assert status == 403 and PW not in raw, (service, status)
        assert audited and audited[0][1].get("reason", "").startswith("revealed only to"), (service, audited)
    status, raw, _ = _reveal_as("browser42-task-runner")
    assert status == 200 and PW in raw, status
    status, raw, _ = _reveal_as("connections", method="loopback")      # the operator, inside this container
    assert status == 200 and PW in raw, status


def test_an_address_alone_or_a_page_is_refused_even_from_the_named_service():
    # an address can be borrowed (identity.py: `ip` is the fallback); a request a page made says so
    status, raw, _ = _reveal_as("browser42-task-runner", method="ip")
    assert status == 403 and PW not in raw, status
    for header in ({"Origin": "https://example.com"}, {"Sec-Fetch-Mode": "cors"}, {"Sec-Fetch-Site": "cross-site"}):
        status, raw, _ = _reveal_as("browser42-task-runner", headers=header)
        assert status == 403 and PW not in raw, (header, status)


def test_another_offices_task_runner_is_refused():
    # one docker host, one office network, two offices: the other office's runner is the same service, verified
    # (the fifth reader). A vault that cannot tell its own project gives it to no container either.
    status, raw, _ = _reveal_as("browser42-task-runner", project="office-b")
    assert status == 403 and PW not in raw, status
    status, raw, _ = _reveal_as("browser42-task-runner", project="")
    assert status == 403 and PW not in raw, status
    real = app.identity.own_project
    app.identity.own_project = lambda: ""
    try:
        status, raw, _ = _reveal_as("browser42-task-runner", project="")
        assert status == 403 and PW not in raw, status
    finally:
        app.identity.own_project = real


def test_resolve_says_no_character_of_it_either():
    real = (app.catalog, app.vault_read, app.resolve)
    app.catalog = lambda: {CID: dict(PROV)}
    app.vault_read = lambda: dict(STORE)
    app.resolve = lambda *a, **k: ("db", PW)
    try:
        r = app.app.test_client().post(f"/api/resolve/{CID}")
    finally:
        app.catalog, app.vault_read, app.resolve = real
    raw = r.get_data(as_text=True)
    assert r.status_code == 200 and app.mask(PW) not in raw and PW[:3] not in raw, raw


def test_a_lease_gives_the_password_only_to_a_verified_caller_it_names():
    real = (app.catalog, app.service_requires, app.vault_read, app.resolve)
    app.catalog = lambda: {CID: dict(PROV)}
    app.vault_read = lambda: dict(STORE)
    app.service_requires = lambda service: [{"id": CID, "required": False}]
    app.resolve = lambda *a, **k: ("db", PW)
    try:
        for caller in (None, {"ok": False, "method": "none"}, {"ok": True, "method": "ip", "service": "browser42-task-runner"},
                       {"ok": True, "method": VERIFIED, "service": "bina-ds", "project": OFFICE},
                       {"ok": True, "method": VERIFIED, "service": "browser42-task-runner", "project": "office-b"}):
            env = app.export_env("browser42-task-runner", caller=caller)
            assert PW not in repr(env) and not env, (caller, env)
        env = app.export_env("browser42-task-runner",
                             caller={"ok": True, "method": VERIFIED, "service": "browser42-task-runner",
                                     "project": OFFICE})
        assert env.get("BROWSER42_LOGIN_GOOGLE_PASSWORD") == PW, env
    finally:
        app.catalog, app.service_requires, app.vault_read, app.resolve = real


def test_a_row_revealed_only_to_named_services_says_no_character_of_it():
    row = _row(PROV, STORE)
    assert row["masked"] == "•••" and row["reveal_ok"] is False, (row["masked"], row["reveal_ok"])
    # what the row used to say (its first three and last two, `mask`) and the password's own start
    assert app.mask(PW) not in repr(row) and PW[:3] not in repr(row), "a piece of the password is in the row"
    real = app.resolve
    app.resolve = lambda *a, **k: ("db", PW)
    try:
        pw = {f["key"]: f for f in app._cred_fields(CID, dict(PROV), dict(STORE))}["BROWSER42_LOGIN_GOOGLE_PASSWORD"]
    finally:
        app.resolve = real
    assert pw["masked"] == "•••" and pw["reveal"] is False, pw


def test_a_lease_carries_the_fixed_address_not_another():
    real = (app.catalog, app.service_requires, app.vault_read, app.resolve)
    app.catalog = lambda: {CID: dict(PROV)}
    app.vault_read = lambda: {**STORE, f"{CID}:BROWSER42_LOGIN_GOOGLE_URL": "https://evil.example/"}
    app.service_requires = lambda service: [{"id": CID, "required": False}]
    app.resolve = lambda *a, **k: ("db", PW)
    os.environ["BROWSER42_LOGIN_GOOGLE_URL"] = "https://evil.example/"
    try:
        env = app.export_env("browser42-task-runner",
                             caller={"ok": True, "method": "container-id+ip", "service": "browser42-task-runner",
                                     "project": OFFICE})
    finally:
        app.catalog, app.service_requires, app.vault_read, app.resolve = real
        os.environ.pop("BROWSER42_LOGIN_GOOGLE_URL", None)
    assert env.get("BROWSER42_LOGIN_GOOGLE_URL") == "https://accounts.google.com/", env.get("BROWSER42_LOGIN_GOOGLE_URL")


if __name__ == "__main__":
    ran = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); ran += 1
            print("ok ", name)
    print(f"test_pinned_login: {ran} passed")
