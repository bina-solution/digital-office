"""test_engine — Google Drive as an engine of «קבצים» (DGO-1500, apps/drive/ENGINES.md).

    python3 apps/drive-google/test_engine.py        (flask + requests: the engine's image has them)

What is held: /ops says drive-engine.v1, kind external, its two protocols (neither private), the consent
door «קבצים» opens for it (/oauth/google/*, connections' google-workspace-grant) and its rows of the connect
dialog, whose consent way names that grant (EXU-19); a service account is added only from a JSON that is one, under its own address, and its secret
is the parsed key; a service account's drive says it cannot create files; an account of another engine is
not this engine's to say; an unknown account is a 404; Google's refusals keep their status. The vault and
Google are stood in; nothing reaches the network.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import requests  # noqa: E402

requests.get = requests.post = lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("no network"))
import engine  # noqa: E402
import gdrive  # noqa: E402

FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


VAULT = [{"id": "drive_google_oauth-1", "protocol": "drive_google_oauth", "label": "g", "account_hint": "owner@example.com"},
         {"id": "drive_google_service_account-2", "protocol": "drive_google_service_account", "label": "sa",
          "account_hint": "person29@example.com"}]
ADDED = []
engine.cx.get_instance = lambda cid: next((i for i in VAULT if i["id"] == cid), None)
engine.cx.add_instance = lambda proto, label, secret, hint=None: (ADDED.append((proto, label, secret, hint)) or {"id": proto + "-9"}, 201)
c = engine.app.test_client()


def main() -> int:
    o = c.get("/ops").get_json()
    check(o["ok"] and o["interface"] == "drive-engine.v1" and o["kind"] == "external" and o["for"] == "drive",
          "/ops: drive-engine.v1, an external engine of «קבצים»")
    check(o["protocols"] == {"drive_google_oauth": {"private": False}, "drive_google_service_account": {"private": False}},
          "…its two protocols, neither private")
    check(o["oauth"]["google"]["grant"] == "google-workspace-grant" and o["routes"] == [],
          "…the consent door «קבצים» opens for it, and nothing of its own to hand over")
    ways = {m["id"]: m for m in o["providers"][0]["auth_methods"]}
    check(ways["oauth"]["start_url"] == "oauth/google/start" and "העלאת קבצים אינה אפשרית" in ways["service_account"]["can"],
          "…its rows of the connect dialog, a service account's limit said in them")
    # a screen with no tile of «קבצים» here asks connections' own start, and only by a name its catalog has (EXU-19:
    # the console sent the protocol, drive_google_oauth, and was answered 404 «not an oauth connection» four times)
    check(ways["oauth"].get("grant") == o["oauth"]["google"]["grant"],
          "…and its consent way names the grant its door opens, connections' catalog id")
    # `needs` is what a connect screen asks for (the console reads it; `fields` are Files' own words for the same
    # keys): a way that said `needs: []` was drawn as the office's own storage, «אין מה להזין», with no key asked
    check(ways["service_account"]["needs"] == [f["name"] for f in ways["service_account"]["fields"]] == ["service_account_json"],
          "…and its shared-address way says what it needs: the key's JSON")
    check([r["rung"] for r in o["ladder"]] == ["official-api", "webapp-api", "browser"], "…and its ladder, highest first")

    E = engine.ENGINE
    body, st = E.connect({"protocol": "drive_google_service_account", "label": "sa", "secret": {"service_account_json": "{nope"}})
    check(st == 400 and "אינו תקין" in body["error"] and not ADDED, "a service account's JSON that is not JSON is refused")
    body, st = E.connect({"protocol": "drive_google_service_account", "label": "sa",
                          "secret": {"service_account_json": json.dumps({"type": "authorized_user"})}})
    check(st == 400 and not ADDED, "…and a JSON that is not a service account")
    key = {"type": "service_account", "client_email": "person29@example.com", "private_key": "-----BEGIN"}
    body, st = E.connect({"protocol": "drive_google_service_account", "label": "sa", "secret": {"service_account_json": json.dumps(key)}})
    check(st == 201 and ADDED[-1][2] == key and ADDED[-1][3] == key["client_email"],
          "a service account is added with its parsed key, under its own address")
    body, st = E.connect({"protocol": "drive_local", "label": "x", "secret": {}})
    check(st == 400, "an account of another engine's protocol is not added here")

    rows = E.accounts(VAULT + [{"id": "drive_local-admin", "protocol": "drive_local"}])
    check([r["id"] for r in rows] == [v["id"] for v in VAULT] and all(r["is_private"] is False for r in rows),
          "accounts: its own rows, none private; another engine's are not its to say")

    d = c.post("/v1/describe", json={"connection_id": "drive_google_service_account-2"}).get_json()
    check(d["ok"] and d["creates"] is False and d["protocol"] == "drive_google_service_account" and "shared_folders" in d["methods"],
          "a service account's drive says it cannot create files, and that it has what was shared")
    d = c.post("/v1/describe", json={"connection_id": "drive_google_oauth-1"}).get_json()
    check(d["ok"] and d["creates"] is True and "thumb" in d["streams"], "a person's account creates, and Google draws its pictures")
    a = E.adapter("drive_google_oauth-1")
    got = {}
    a.store_file = lambda src, size, md5, name, mime, folder="", oid=None: (got.update(n=len(src.read()), size=size) or {"id": "f1"})
    a._json = lambda method, url, params=None, **kw: {"id": "f1", "md5Checksum": "m", "kind": "drive#file"} if "f1" in url else {}
    E_adapter, E.adapter = E.adapter, (lambda cid: a)
    r = c.put("/v1/op_upload?connection_id=drive_google_oauth-1&size=5&name=x.bin", data=b"12345")
    E.adapter = E_adapter
    check(r.status_code == 200 and r.get_json()["result"]["kind"] == "drive#file" and got == {"n": 5, "size": 5},
          "the §3 upload streams into Drive's resumable upload and answers Drive's own resource (no 64 MB cap)")
    r = c.post("/v1/describe", json={"connection_id": "drive_google_oauth-404"})
    check(r.status_code == 404, "an unknown account is a 404")

    def refused(*_a, **_kw):
        raise gdrive.GoogleAuthError("הקובץ אינו קיים ב־Drive", 404)
    gdrive.GoogleDriveAdapter.folders = refused
    r = c.post("/v1/call/folders", json={"connection_id": "drive_google_oauth-1"})
    check(r.status_code == 404 and r.get_json()["kind"] == "auth", "Google's refusal keeps its status (a missing object is a 404)")
    body, st = E.disconnect("drive_google_oauth-404")
    check(st == 404, "disconnecting an account that is not there is a 404")

    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
