"""The site's guards over real HTTP (DGO-1893): the doors a stranger, a buyer, an admin and a node each knock on.

    python3 -m unittest apps/dgo-cloud/tests/test_site_http.py
"""
import base64
import http.cookiejar
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


class Browser:
    def __init__(self, base):
        self.base = base
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None, headers=None, site=True):
        h = {"Content-Type": "application/json"}
        if site:
            h["X-DGO"] = "1"
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.op.open(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw[:200]}


class TestSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update({"DGOCLOUD_DATA": tempfile.mkdtemp(), "CARDCOM_SIMULATE": "1",
                           "DGOCLOUD_PROVIDER": "simulate", "DGOCLOUD_SMTP_HOST": "off",
                           "DGOCLOUD_ADMINS": "boss@example.test"})
        import accounts
        accounts._TRIES.clear()
        import server
        cls.S = server
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{srv.server_address[1]}"

    def test_1_a_browser_write_needs_the_site_header(self):
        st, d = Browser(self.base).call("POST", "/api/auth/signup", {"email": "x@example.test", "name": "x",
                                                                    "password": "olive-grove-12"}, site=False)
        self.assertEqual(st, 403)

    def test_2_buyer_pays_and_the_webhook_is_only_a_trigger(self):
        b = Browser(self.base)
        st, d = b.call("POST", "/api/auth/signup", {"email": "buyer@example.test", "name": "קונה",
                                                    "password": "olive-grove-12"})
        self.assertEqual(st, 200)
        self.assertFalse(d["data"]["admin"])
        self.assertEqual(b.call("GET", "/api/admin/overview")[0], 403)
        st, d = b.call("POST", "/api/checkout", {"plan": "basic"})
        pid = d["data"]["payment"]
        lp = self.S.store.one("SELECT lp_id FROM payments WHERE id=?", pid)["lp_id"]
        # a webhook that claims payment before Cardcom says so changes nothing
        self.assertEqual(Browser(self.base).call("POST", "/api/cardcom/webhook", {"LowProfileId": lp,
                                                                                    "ResponseCode": 0},
                                                 site=False)[0], 200)
        self.assertEqual(self.S.store.one("SELECT status FROM payments WHERE id=?", pid)["status"], "pending")
        self.S.cardcom.sim_pay(lp, True)
        Browser(self.base).call("POST", "/api/cardcom/webhook", {"ReturnValue": f"p{pid}"}, site=False)
        self.assertEqual(self.S.store.one("SELECT status FROM payments WHERE id=?", pid)["status"], "paid")
        st, d = b.call("GET", "/api/dashboard")
        self.assertEqual((d["data"]["subscription"]["status"], d["data"]["wallet"]["total"]), ("active", 2400))
        # another person cannot verify (or read) this payment
        other = Browser(self.base)
        other.call("POST", "/api/auth/signup", {"email": "other@example.test", "name": "אחר", "password": "olive-grove-34"})
        self.assertEqual(other.call("POST", f"/api/pay/{pid}/verify")[0], 404)

    def test_3_admin_view_as_reads_and_refuses_writes(self):
        boss = Browser(self.base)
        st, d = boss.call("POST", "/api/auth/signup", {"email": "boss@example.test", "name": "מנהל",
                                                       "password": "olive-grove-56"})
        self.assertFalse(d["data"]["admin"])                     # a named address is NOT admin on a bare sign-up
        self.assertEqual(boss.call("GET", "/api/admin/overview")[0], 403)
        tok = self.S.accounts.link(d["data"]["id"], "verify")     # …only once its mailbox is proven
        st, d = boss.call("POST", "/api/auth/verify", {"token": tok})
        self.assertTrue(d["data"]["admin"])
        st, d = boss.call("GET", "/api/admin/accounts?q=buyer")
        buyer = d["data"][0]
        self.assertEqual(boss.call("POST", "/api/admin/view-as", {"account": buyer["id"]})[0], 200)
        st, d = boss.call("GET", "/api/dashboard")
        self.assertEqual(d["data"]["account"]["email"], "buyer@example.test")
        st, d = boss.call("POST", "/api/subscription/cancel")
        self.assertEqual(st, 400)
        self.assertIn("צפייה בתור", d["error"])
        boss.call("POST", "/api/view-as/stop")
        st, d = boss.call("GET", "/api/dashboard")
        self.assertEqual(d["data"]["account"]["email"], "boss@example.test")
        self.assertTrue(self.S.store.one("SELECT 1 x FROM audit WHERE action='admin.view_as'"))

    def test_4_nodes_and_acme_answer_only_to_their_own_secret(self):
        self.S.prov.tick()
        node = self.S.store.one("SELECT * FROM nodes ORDER BY id DESC LIMIT 1")
        boot = None
        path = os.path.join(os.environ["DGOCLOUD_DATA"], f"sim-{node['name']}.sh")
        for line in open(path):
            if line.startswith("BOOT="):
                boot = line.split('"')[1]
        anon = Browser(self.base)
        st, d = anon.call("POST", "/api/node/hello", {"boot": boot, "ip": "127.0.0.1"}, site=False)
        self.assertEqual(st, 200)
        secret, name = d["data"]["secret"], d["data"]["name"]
        self.assertEqual(anon.call("POST", "/api/node/hello", {"boot": boot}, site=False)[0], 400)  # spent
        self.assertEqual(anon.call("POST", "/api/node/poll", {}, site=False)[0], 401)
        self.assertEqual(anon.call("POST", "/api/node/poll", {}, {"Authorization": "Bearer " + secret},
                                   site=False)[0], 200)
        good = "Basic " + base64.b64encode(f"{name}:{secret}".encode()).decode()
        bad = "Basic " + base64.b64encode(f"o-zzzzzz:{secret}".encode()).decode()
        zone = os.environ.get("DGOCLOUD_ZONE", "cloud.digital-office.co.il")
        st, _ = anon.call("POST", "/api/acme/present", {"fqdn": f"_acme-challenge.{name}.{zone}.", "value": "v"},
                          {"Authorization": good}, site=False)
        self.assertEqual(st, 200)
        st, _ = anon.call("POST", "/api/acme/present", {"fqdn": f"_acme-challenge.other.{zone}.", "value": "v"},
                          {"Authorization": good}, site=False)
        self.assertEqual(st, 400)
        st, _ = anon.call("POST", "/api/acme/present", {"fqdn": f"_acme-challenge.{name}.{zone}.", "value": "v"},
                          {"Authorization": bad}, site=False)
        self.assertEqual(st, 403)

    def test_5_the_page_and_its_versioned_assets(self):
        with urllib.request.urlopen(self.base + "/pay/return?p=1", timeout=5) as r:
            page = r.read().decode()
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertRegex(page, r'/static/app\.js\?v=\d+"')
        self.assertEqual(Browser(self.base).call("GET", "/api/dashboard")[0], 401)


if __name__ == "__main__":
    unittest.main()
