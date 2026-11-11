"""test_engine — the office storage as an engine of «קבצים» (DGO-1500, apps/drive/ENGINES.md).

    python3 apps/drive-local/test_engine.py        (flask + requests: the engine's image has them)

What is held: names and paths (moved here from apps/drive/test_core.py with the code they test); /ops
says drive-engine.v1, the private protocol, and the prefixes «קבצים» hands over; a key is checked here —
an unknown one 401, another profile's 403, its own passes; the accounts are said in a person's words, the
first admin is the default, a row whose profile is gone says so; a drive_local account is added only with
a verified key and never removed from here; describe lists what a profile's drive can do, its pictures and
waveforms included; a call reaches the adapter and its errors keep their status; the share link serves the
bytes with the office's own serving headers; the acting profile is the bound drive «קבצים» names, or the
key. The database is never reached: profiles and the share link's read are stood in.
"""
import importlib
import io
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("DRIVE_LEDGER_PATH", os.path.join(tempfile.mkdtemp(prefix="drive-local-"), "ledger.json"))
os.environ.setdefault("DRIVE_CACHE_DIR", tempfile.mkdtemp(prefix="drive-local-cache-"))


def _have(name, **attrs):
    try:
        importlib.import_module(name)
    except Exception:                               # noqa: BLE001 — a driver nothing here calls
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod


class _NoDB(Exception):
    pass


def _refuse(**_kw):
    raise _NoDB("no database in this test")


_have("psycopg2", OperationalError=_NoDB, InterfaceError=_NoDB, connect=_refuse)
_have("psycopg2.pool", ThreadedConnectionPool=lambda *a, **kw: _refuse())
sys.modules["psycopg2"].pool = sys.modules["psycopg2.pool"]

import requests  # noqa: E402

requests.get = requests.post = lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("no network"))
import engine  # noqa: E402
import local  # noqa: E402
import profiles  # noqa: E402

FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


PROFILES = {"admin": {"id": "admin", "display_name": "מנהל", "is_admin": True, "status": "active", "instance_id": "drive_local-admin"},
            "user2": {"id": "user2", "display_name": "משתמש 2", "is_admin": False, "status": "active", "instance_id": "drive_local-user2"}}
KEYS = {"k-admin": "admin", "k-user2": "user2"}
VAULT = [{"id": "drive_local-admin", "protocol": "drive_local", "label": "admin", "account_hint": "admin"},
         {"id": "drive_local-user2", "protocol": "drive_local", "label": "user2", "account_hint": "user2"},
         {"id": "drive_local-gone", "protocol": "drive_local", "label": "gone", "account_hint": "gone"}]
profiles.by_key = lambda key: PROFILES.get(KEYS.get(key))
profiles.get = lambda pid: PROFILES.get(pid)
profiles.by_instance = lambda iid: next((p for p in PROFILES.values() if p["instance_id"] == iid), None)
profiles.first_admin = lambda: PROFILES["admin"]
engine.cx.get_instance = lambda cid: next((i for i in VAULT if i["id"] == cid), None)
ADDED = []
engine.cx.add_instance = lambda proto, label, secret, hint=None: (ADDED.append((proto, label, hint)) or {"id": "drive_local-new"}, 201)
c = engine.app.test_client()


def main() -> int:
    # ── names and paths ──
    check(local.split_path("/פגישות//2026-10-28/") == ["פגישות", "2026-10-28"], "a path splits into NFC segments")
    for bad, what in (("/a/../b", "'..' is refused"),):
        try:
            local.split_path(bad)
            check(False, what)
        except Exception as e:      # AdapterError
            check(getattr(e, "status", 0) == 400, what)
    try:
        local.clean_name("a/b")
        check(False, "a name with / is refused")
    except Exception as e:
        check(getattr(e, "status", 0) == 400, "a name with / is refused")
    ids = {local.new_id("lf") for _ in range(2000)}
    check(len(ids) == 2000 and all(i.startswith("lf") for i in ids), "ids are unique and carry their kind")

    # ── /ops ──
    o = c.get("/ops").get_json()
    check(o["ok"] and o["interface"] == "drive-engine.v1" and o["for"] == "drive" and o["kind"] == "engine",
          "/ops: drive-engine.v1, an engine of «קבצים»")
    check(o["protocols"] == {"drive_local": {"private": True}} and o["routes"] == ["/engine/", "/file/d/"],
          "…its private protocol, and the prefixes «קבצים» hands over")
    check(o["providers"][0]["auth_methods"][0]["protocol"] == "drive_local" and o["ladder"][0]["state"] == "in-use",
          "…its row of the connect dialog's catalogue, and its ladder")

    # ── a key ──
    E = engine.ENGINE
    for key, cid, want, what in (("nope", "drive_local-admin", 401, "an unknown key is a 401"),
                                 ("k-user2", "drive_local-admin", 403, "another profile's key is a 403"),
                                 ("k-admin", "drive_local-admin", 0, "the profile's own key passes")):
        try:
            E.check_key(cid, key)
            check(want == 0, what)
        except profiles.ProfileError as e:
            check(e.status == want, what)

    # ── accounts ──
    rows = {r["id"]: r for r in E.accounts(VAULT + [{"id": "drive_google_oauth-1", "protocol": "drive_google_oauth"}])}
    check(rows["drive_local-admin"]["label"] == "מנהל" and rows["drive_local-admin"]["is_admin"] and rows["drive_local-admin"]["default"],
          "an account is said in a person's words, and the first admin is the default")
    check(not rows["drive_local-user2"]["default"] and rows["drive_local-user2"]["profile_id"] == "user2", "…another profile is not")
    check(rows["drive_local-gone"]["status"] == "needs_action" and "אינו קיים" in rows["drive_local-gone"]["reason"],
          "a row whose profile is gone says so, instead of looking healthy")
    check("drive_google_oauth-1" not in rows, "an account of another engine is not this engine's to say")

    # ── connect / disconnect ──
    body, st = E.connect({"protocol": "drive_local", "label": "x", "secret": {"api_key": "nope"}})
    check(st == 400 and not ADDED, "a drive_local account with a key that is not verified is not added")
    body, st = E.connect({"protocol": "drive_local", "label": "x", "secret": {"api_key": "k-user2"}, "account_hint": "admin"})
    check(st == 400 and not ADDED, "…nor one whose hint names another profile")
    body, st = E.connect({"protocol": "drive_local", "label": "x", "secret": {"api_key": "k-user2"}})
    check(st == 201 and ADDED[-1] == ("drive_local", "x", "user2"), "a verified key is added, under its own profile")
    body, st = E.disconnect("drive_local-user2")
    check(st == 400 and body.get("profile_id") == "user2", "a profile is never removed from here (only in «ניהול פרופילים»)")

    # ── describe and a call, through the protocol ──
    ad = engine.EngineAdapter(VAULT[0], secret={"api_key": "k-admin", "profile_id": "admin"})
    engine.adapter_for = lambda cid: ad
    d = c.post("/v1/describe", json={"connection_id": "drive_local-admin"}).get_json()
    check(d["ok"] and d["private"] and d["profile_id"] == "admin" and "peaks" in d["methods"] and "file" in d["methods"]
          and {"thumb", "store_file", "content", "op_upload"} <= set(d["streams"]),
          "describe: a profile's drive, its pictures and waveforms included")
    ad.search = lambda term, limit=200: [{"id": "lf1", "name": term}]
    r = c.post("/v1/call/search", json={"connection_id": "drive_local-admin", "args": ["חוזה"]}).get_json()
    check(r["ok"] and r["result"] == [{"id": "lf1", "name": "חוזה"}], "a call reaches the adapter with its arguments")

    def missing(*_a, **_kw):
        raise local.AdapterError("הקובץ אינו קיים בדרייב של הפרופיל הזה", 404)
    ad.content = missing
    r = c.get("/v1/content?connection_id=drive_local-admin&id=x")
    check(r.status_code == 404 and r.headers.get("X-Drive-Engine-Error") == "adapter" and r.get_json()["kind"] == "adapter",
          "a byte answer that is an error says so in its header, with its status")
    r = c.post("/v1/call/nothing", json={"connection_id": "drive_local-admin"})
    check(r.status_code == 404, "a method outside the interface is not reached")
    r = c.post("/v1/call/search", json={"connection_id": "drive_local-admin"}, headers={"X-Drive-Profile-Key": "k-user2"})
    check(r.status_code == 403 and r.get_json()["kind"] == "profile", "a presented key of another profile is refused before the call")

    # ── the share link ──
    class Up:
        status_code, headers = 200, {"Content-Length": "4"}

        def iter_content(self, n):
            yield b"<b>x"

        def close(self):
            pass
    engine.public_stream = lambda oid, rng=None: (Up(), "page.html", "text/html", "m5") if oid == "lf1" else None
    r = c.get("/file/d/lf1/view")
    check(r.status_code == 200 and r.get_data() == b"<b>x" and r.headers.get("Content-Type", "").startswith("text/plain")
          and "sandbox" in (r.headers.get("Content-Security-Policy") or ""),
          "a share link serves the bytes; a user's page never runs (plain text, sandboxed)")
    check(c.get("/file/d/nope/view").status_code == 404, "…and a link to nothing (or to the trash) is a 404")

    # ── who is acting ──
    engine.bound = lambda: {"id": "drive_local-user2", "bound": "drive_local-user2", "is_private": True}
    with engine.app.test_request_context("/engine/whoami", headers={"X-Drive-Acting-Connection": "drive_local-admin"}):
        check((engine.acting_profile() or {}).get("id") == "user2",
              "without a key, the drive «קבצים» says it is bound to acts — a header naming another is ignored")
    with engine.app.test_request_context("/engine/whoami", headers={"X-Drive-Profile-Key": "k-admin"}):
        check((engine.acting_profile() or {}).get("id") == "admin", "a key is authoritative over the bound drive")
    engine.bound = lambda: {}
    with engine.app.test_request_context("/engine/whoami"):
        check(engine.acting_profile() is None, "when «קבצים» does not answer, a keyless request acts as nobody")
    r = c.post("/engine/profiles/admin/key", headers={"X-Drive-Acting-Connection": "drive_local-admin"})
    check(r.status_code == 401, "…so a direct caller cannot rotate a profile's key by naming it")

    # ── the profile's own instance, and the default ──
    extra = {"id": "drive_local-admin-2", "protocol": "drive_local", "label": "admin", "account_hint": "admin"}
    rows = {r["id"]: r for r in E.accounts(VAULT + [extra])}
    check(rows["drive_local-admin"]["primary"] and not rows["drive_local-admin-2"]["primary"]
          and rows["drive_local-admin"]["default"] and not rows["drive_local-admin-2"]["default"],
          "a second row with the same hint is not the profile's own (primary) and never the default")

    # ── the ledger on the engine's own volume ──
    import bootstrap
    profiles.listing = lambda: list(PROFILES.values())
    if os.path.exists(bootstrap.LEDGER_PATH):
        os.unlink(bootstrap.LEDGER_PATH)
    decl = [{"id": "admin"}, {"id": "user2"}, {"id": "not-made-yet"}]
    bootstrap._adopt_on_first_start(decl)
    check(bootstrap.ours("admin") and bootstrap.ours("user2") and not bootstrap.ours("not-made-yet"),
          "first start without a ledger: the declared profiles that exist are the reconciler's, as before the split")
    PROFILES["ops"] = {"id": "ops", "display_name": "ops", "is_admin": False, "status": "active", "instance_id": None}
    bootstrap._adopt_on_first_start(decl + [{"id": "ops"}])
    check(not bootstrap.ours("ops"), "…once: an existing ledger is never adopted again")
    PROFILES.pop("ops")

    # ── every error is an answer of the protocol ──
    def boom(*_a, **_kw):
        raise RuntimeError("a bug")
    ad.content = boom
    r = c.get("/v1/content?connection_id=drive_local-admin&id=x")
    check(r.status_code == 500 and r.headers.get("X-Drive-Engine-Error") == "internal" and r.is_json,
          "an error the engine does not know is JSON with the error header, never a page passed on as the file")

    def too_big(*_a, **_kw):
        e = requests.HTTPError("413")
        e.response = type("R", (), {"status_code": 413})()
        raise e
    ad.store_file = too_big
    r = c.put("/v1/store?connection_id=drive_local-admin&size=3&name=a.bin", data=b"abc")
    check(r.status_code == 413 and "גדול מהמותר" in r.get_json()["error"],
          "the store's 413 is said as «too large», not as an engine's 500")

    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
