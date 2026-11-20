"""«ישויות»' API end to end, behind the office's real door (platform-base/forward-auth/signin.py) — DGO-2101.

  * who may call: nobody without a token or a session (401); a signed-in person who is not an admin (403); an admin
    reads the screen and its API and changes records — as JSON exactly (a form post, or a type that only contains
    application/json, is refused, 415), from the app's own page (a sibling host's request, 403); the token can;
  * who changed what: the admin by the session's name (an `X-Actor` they send changes nothing), a service by the
    name it gives with the token, and each field's before and after;
  * the patterns hold: an unknown field, a role a kind may not hold, a kind of business off the list — refused;
  * party(): the block a document prints (the number's digits, the tax status, the address as street/city, the
    contact person through the relation);
  * archive keeps the record answering by id; an import keeps nothing twice; every change is in the history;
  * the door's default is unchanged: an app that names no `person_writes` still refuses an admin's write (the guard
    for loans, assets and examplem-io).

    python3 apps/entities/tests/test_api.py      (in the app's image: fastapi + uvicorn; signin.py on the path)
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.update(ENTITIES_DATA=tempfile.mkdtemp(prefix="entities-"), ENTITIES_API_TOKEN="tok-test",
                  ENTITIES_TRUST_LOOPBACK="0", no_proxy="127.0.0.1,localhost", NO_PROXY="127.0.0.1,localhost")
sys.path.insert(0, str(HERE.parent))
for _up in HERE.parents:                                  # signin.py: the tree's copy; in the app's image, /opt/dgo's
    if (_up / "platform-base" / "forward-auth" / "signin.py").is_file():
        sys.path.insert(0, str(_up / "platform-base" / "forward-auth"))
        break

FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class WhoAmI(http.server.BaseHTTPRequestHandler):
    """forward-auth's /whoami, as the door asks it: the cookie names who is signed in."""

    def do_GET(self):
        c = self.headers.get("Cookie", "")
        who = {"dgo_session=admin": ("owner", ["admins"]), "dgo_session=staff": ("staff", [])}.get(c)
        if not who:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"signed_in": True, "username": who[0], "groups": who[1]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


wp = free_port()
threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", wp), WhoAmI).serve_forever, daemon=True).start()
os.environ["ENTITIES_WHOAMI_URL"] = f"http://127.0.0.1:{wp}/whoami"

import uvicorn  # noqa: E402

import app as entities_app  # noqa: E402

port = free_port()
server = uvicorn.Server(uvicorn.Config(entities_app.app, host="127.0.0.1", port=port, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)
BASE = f"http://127.0.0.1:{port}"


def call(method, path, body=None, *, token=None, cookie=None, form=False, ctype=None, headers=None):
    data, headers = None, dict(headers or {})
    if body is not None:
        if form:
            data, headers["content-type"] = urllib.parse.urlencode(body).encode(), "application/x-www-form-urlencoded"
        else:
            data, headers["content-type"] = json.dumps(body).encode(), ctype or "application/json"
    if token:
        headers["authorization"] = f"Bearer {token}"
    if cookie:
        headers["cookie"] = cookie
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, (json.loads(raw) if raw.startswith(("{", "[")) else raw)


T = "tok-test"
# 1. who may call
check(call("GET", "/api/entities")[0] == 401, "no token, no session → 401")
check(call("GET", "/")[0] == 401, "the screen with no session → 401 (a page)")
check(call("GET", "/healthz")[0] == 200, "/healthz is open")
check(call("GET", "/api/entities", cookie="dgo_session=staff")[0] == 403, "a non-admin person → 403")
check(call("POST", "/api/entities", {"kind": "person", "name": "x"}, cookie="dgo_session=staff")[0] == 403,
      "a non-admin may not write")
check(call("GET", "/", cookie="dgo_session=admin")[0] == 200, "an admin opens the screen")
check(call("GET", "/e/ent_any", cookie="dgo_session=admin")[0] == 200, "a link to a card opens the screen")
check(call("GET", "/api/patterns", cookie="dgo_session=admin")[0] == 200, "an admin reads the patterns")

# 2. create through the token, with patterns
s, oren = call("POST", "/api/entities", {
    "kind": "organization", "name": "קבוצת אורן", "fields": {"phone": "03-000-0002", "street": "שדרות רוטשילד 45",
                                                             "city": "תל אביב-יפו"},
    "roles": {"customer": {"customer_no": "1042", "billing_email": "billing@oren.example"},
              "company": {"legal_name": "קבוצת אורן בע״מ", "business_number": "51-612345-7", "entity_type": "חברה בע״מ"}}},
    token=T)
check(s == 200 and oren["roles"]["customer"]["customer_no"] == "1042", f"create an organization: {s} {oren}")
check(call("POST", "/api/entities", {"kind": "organization", "name": "x", "fields": {"nope": "1"}}, token=T)[0] == 400,
      "an unknown field is refused")
check(call("POST", "/api/entities", {"kind": "organization", "name": "x", "roles": {"salesperson": {}}}, token=T)[0] == 400,
      "an organization is not a salesperson")
check(call("POST", "/api/entities", {"kind": "organization", "name": "x",
                                     "roles": {"company": {"entity_type": "פטור"}}}, token=T)[0] == 400,
      "a kind of business off the list is refused")
check(call("POST", "/api/entities", {"kind": "organization", "name": ""}, token=T)[0] == 400, "a name is required")
check(call("POST", "/api/entities", {"kind": "person", "name": "x"}, token=T, form=True)[0] == 415,
      "a change is JSON only")

# 3. an admin changes from the screen (JSON); a form post with the admin's cookie is refused
s, dana = call("POST", "/api/entities", {"kind": "person", "name": "דנה לוי", "roles": {"contact": {"title": "סמנכ״לית תפעול"}}},
               cookie="dgo_session=admin")
check(s == 200 and dana["kind"] == "person", f"an admin creates: {s} {dana}")
check(call("POST", "/api/entities", {"kind": "person", "name": "y"}, cookie="dgo_session=admin", form=True)[0] == 415,
      "an admin's form post is refused (no cross-site write with the cookie)")
check(call("POST", "/api/entities", {"kind": "person", "name": "y"}, cookie="dgo_session=admin",
           ctype="text/plain; charset=application/json")[0] == 415,
      "a type that only CONTAINS application/json is refused (a page may send text/plain unasked)")
check(call("POST", "/api/entities", {"kind": "person", "name": "y"}, cookie="dgo_session=admin",
           headers={"sec-fetch-site": "same-site"})[0] == 403,
      "a change from a sibling host of the office's domain is refused, the cookie notwithstanding")
s, z = call("POST", "/api/entities", {"kind": "person", "name": "זיו"}, cookie="dgo_session=admin",
            headers={"sec-fetch-site": "same-origin", "x-actor": "someone-else"})
check(s == 200, f"a change from the app's own page passes: {s} {z}")
zev = call("GET", f"/api/events?entity={z['id']}", token=T)[1]["events"]
check(zev[0]["actor"] == "owner (המסך)", f"the admin is named from the session, not from X-Actor: {zev}")
s, _ = call("PATCH", f"/api/entities/{z['id']}", {"fields": {"phone": "050-0000000"}}, token=T,
            headers={"x-actor": "documents"})
zev = call("GET", f"/api/events?entity={z['id']}", token=T)[1]["events"]
check(zev[0]["actor"] == "service:documents" and zev[0]["detail"] == {"phone": ["", "050-0000000"]},
      f"a service with the token, by the name it gives, and what it changed: {zev[0]}")
call("POST", f"/api/entities/{z['id']}/archive", {"archived": True}, token=T)
s, _ = call("POST", "/api/relations", {"from": dana["id"], "to": oren["id"], "kind": "works_at", "title": "סמנכ״לית תפעול"},
            cookie="dgo_session=admin")
check(s == 200, f"relate a person to an organization: {s}")
check(call("POST", "/api/relations", {"from": oren["id"], "to": dana["id"], "kind": "works_at"}, token=T)[0] == 400,
      "an organization does not work at a person")

# 4. party: what a document prints
s, p = call("GET", f"/api/entities/{oren['id']}/party", token=T)
check(s == 200 and p["company_id"] == "516123457" and p["tax_status"] == "company", f"party number/status: {p}")
check((p["street"], p["city"]) == ("שדרות רוטשילד 45", "תל אביב-יפו"), f"party address: {p}")
check(p["name"] == "קבוצת אורן בע״מ" and p["email"] == "billing@oren.example" and p["customer_no"] == "1042", f"party: {p}")
check(p["contact_person"] == "דנה לוי" and p["contact_title"] == "סמנכ״לית תפעול", f"party contact: {p}")
s, ps = call("GET", "/api/parties?role=customer", token=T)
check(s == 200 and [x["entity_id"] for x in ps["parties"]] == [oren["id"]] and ps["parties"][0] == p,
      f"parties: the customers, each as party() prints it: {ps}")

# 5. list, search, roles, patch
s, lst = call("GET", "/api/entities?role=customer", token=T)
check([e["name"] for e in lst["entities"]] == ["קבוצת אורן"], f"list by role: {lst}")
check([e["name"] for e in call("GET", "/api/entities?q=" + urllib.parse.quote("billing@oren"), token=T)[1]["entities"]] == ["קבוצת אורן"],
      "search reaches a role's field")
s, o2 = call("PUT", f"/api/entities/{oren['id']}/roles/supplier", {"fields": {"bank_name": "לאומי"}}, token=T)
check(s == 200 and set(o2["roles"]) == {"company", "customer", "supplier"}, "one organization: customer and supplier")
s, o3 = call("PATCH", f"/api/entities/{oren['id']}", {"fields": {"phone": ""}}, token=T)
check(s == 200 and "phone" not in o3["fields"], "an empty value removes a field")
s, o4 = call("DELETE", f"/api/entities/{oren['id']}/roles/supplier", token=T)
check(s == 200 and "supplier" not in o4["roles"], "a role comes off")
# the kind is corrected through the same PATCH, and refused in words when a role no longer fits
s, p1 = call("POST", "/api/entities", {"kind": "person", "name": "ספק בלי מספר", "roles": {"supplier": {}}}, token=T)
s, p2 = call("PATCH", f"/api/entities/{p1['id']}", {"kind": "organization"}, token=T)
check(s == 200 and p2["kind"] == "organization", f"PATCH takes the kind: {s} {p2}")
s, p3 = call("PATCH", f"/api/entities/{p1['id']}", {"kind": "robot"}, token=T)
check(s == 400 and "סוג" in json.dumps(p3, ensure_ascii=False), f"an unknown kind is a 400 in words: {s} {p3}")
s, c1 = call("POST", "/api/entities", {"kind": "person", "name": "איש קשר", "roles": {"contact": {}}}, token=T)
s, c2 = call("PATCH", f"/api/entities/{c1['id']}", {"kind": "organization"}, token=T)
check(s == 400 and "«איש קשר»" in json.dumps(c2, ensure_ascii=False), f"a contact stays a person, said: {s} {c2}")
# a kind sent as a list or an object is a refusal in words (400), never an unhashable 500
for path, method, body in ((f"/api/entities/{p1['id']}", "PATCH", {"kind": ["person"]}),
                           ("/api/entities", "POST", {"kind": {"k": 1}, "name": "x"}),
                           ("/api/relations", "POST", {"from": c1["id"], "to": p1["id"], "kind": ["works_at"]})):
    s, _ = call(method, path, body, token=T)
    check(s == 400, f"{method} {path} with a kind that is not a string: {s}")

# 6. archive keeps answering by id
call("POST", f"/api/entities/{oren['id']}/archive", {"archived": True}, token=T)
check(oren["id"] not in [e["id"] for e in call("GET", "/api/entities", token=T)[1]["entities"]], "archived: out of the list")
check(call("GET", f"/api/entities/{oren['id']}", token=T)[1]["archived"] is True, "archived: still answers by id")
call("POST", f"/api/entities/{oren['id']}/archive", {"archived": False}, token=T)

# 7. import keeps nothing twice
rows = [{"kind": "organization", "name": "מעבדת שקד", "roles": {"customer": {}}, "source": "ledger:cus_1"},
        {"kind": "person", "name": "אלון", "source": "ledger:cus_2"}, {"kind": "person", "name": "no source"}]
s, r1 = call("POST", "/api/import", {"rows": rows}, token=T)
s, r2 = call("POST", "/api/import", {"rows": rows}, token=T)
check((r1["created"], r1["kept"], len(r1["refused"])) == (2, 0, 1), f"first import: {r1}")
check((r2["created"], r2["kept"]) == (0, 2), f"second import keeps nothing twice: {r2}")

# 8. the history
ev = call("GET", f"/api/events?entity={oren['id']}", token=T)[1]["events"]
check(len(ev) >= 5 and any(e["kind"] == "archived" for e in ev), f"history: {len(ev)} events")

# 9. the shared door's default is unchanged (loans, assets, examplem-io name no person_writes)
import signin  # noqa: E402
from fastapi import FastAPI  # noqa: E402

plain = FastAPI()
plain.middleware("http")(signin.door(signin.SignIn(os.environ["ENTITIES_WHOAMI_URL"]), token="t", loopback_env="X_LOOP",
                                     person_reads={"/r"}, words=entities_app.WORDS))
plain.post("/r")(lambda: {"ok": True})
plain.get("/r")(lambda: {"ok": True})
os.environ["X_LOOP"] = "0"
pp = free_port()
ps = uvicorn.Server(uvicorn.Config(plain, host="127.0.0.1", port=pp, log_level="warning"))
threading.Thread(target=ps.run, daemon=True).start()
for _ in range(100):
    if ps.started:
        break
    time.sleep(0.05)
BASE = f"http://127.0.0.1:{pp}"
check(call("GET", "/r", cookie="dgo_session=admin")[0] == 200, "default door: an admin reads")
check(call("POST", "/r", {"a": 1}, cookie="dgo_session=admin")[0] == 403, "default door: an admin may NOT write")

server.should_exit = ps.should_exit = True
if FAIL:
    print("FAIL", *FAIL, sep="\n  ")
    sys.exit(1)
print("ok — test_api: the door, the patterns, party, relations, archive, import, history, the door's default")
