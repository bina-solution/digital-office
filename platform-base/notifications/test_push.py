"""test_push — the office's notices on the owners' phones (push.py), proven end to end without a phone.

A local fake push service stands where FCM/Mozilla/Apple stand. Every message it receives is DECRYPTED here
with the fake phone's own private key by an implementation of RFC 8291 written in this file (not the
sender's library), and the VAPID header is checked against the office's public key (RFC 8292) — so a
pass means a real push service would have accepted it and a real phone could have read it.

    python -m unittest -v test_push          (from this directory; stdlib + the image's own packages)
"""
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix="push-test-")
os.environ.update(NOTIFICATIONS_DB=os.path.join(TMP, "notifications.db"), PUSH_KEY_FILE=os.path.join(TMP, "vapid.pem"),
                  PUSH_ALLOW_HTTP="1", PUSH_ENDPOINT_HOSTS="127.0.0.1", GLITCHTIP_URL="http://127.0.0.1:9",
                  PUSH_ENABLED="1", PUSH_LEVELS="error", PUSH_MAX_PER_HOUR="1000")
os.environ.pop("SENTRY_DSN", None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG = io.StringIO()
_h = logging.StreamHandler(LOG)
_h.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_h)
logging.getLogger().setLevel(logging.DEBUG)

import app as appmod   # noqa: E402 — after the environment above
import push            # noqa: E402

from cryptography.hazmat.primitives import hashes, serialization                       # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec                               # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature       # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM                         # noqa: E402

appmod.app.logger.addHandler(_h)
appmod.app.logger.setLevel(logging.DEBUG)


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── the fake push service ────────────────────────────────────────────────────────────────────────
GOT = []
GOT_LOCK = threading.Lock()


class Push(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.startswith("/slow"):
            time.sleep(3)
        with GOT_LOCK:
            GOT.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        code = 410 if self.path.startswith("/gone") else 404 if self.path.startswith("/missing") else 201
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()


SRV = ThreadingHTTPServer(("127.0.0.1", 0), Push)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % SRV.server_address[1]


class Phone:
    """A browser's half of a subscription: its own P-256 key and auth secret."""

    def __init__(self, path):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.endpoint = BASE + path

    def sub(self):
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}}

    def decrypt(self, body):
        """RFC 8291 + RFC 8188 (aes128gcm), one record — written here, independent of the sender."""
        salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        keyid, ct = body[21:21 + idlen], body[21 + idlen:]
        assert idlen == 65 and rs >= 18 and len(ct) <= rs, "aes128gcm header"
        server_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), keyid)
        shared = self.key.exchange(ec.ECDH(), server_pub)
        h = lambda k, m: hmac.new(k, m, hashlib.sha256).digest()   # noqa: E731
        ikm = h(h(self.auth, shared), b"WebPush: info\x00" + self.pub + keyid + b"\x01")
        prk = h(salt, ikm)
        cek = h(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
        nonce = h(prk, b"Content-Encoding: nonce\x00\x01")[:12]
        pt = AESGCM(cek).decrypt(nonce, ct, None).rstrip(b"\x00")
        assert pt[-1:] == b"\x02", "last-record delimiter"
        return json.loads(pt[:-1].decode("utf-8"))


def as_(user):
    return {"X-authentik-username": user, "X-authentik-email": user + "@example.test", "User-Agent":
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/27.0 Chrome/125.0 Mobile Safari/537.36"}


class PushTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = appmod.app.test_client()

    def setUp(self):
        with GOT_LOCK:
            GOT.clear()
        with push._db() as c:
            c.execute("DELETE FROM push_devices")
            c.execute("DELETE FROM push_rung")
            c.execute("DELETE FROM notifications")
        push._storm.update(window=0, count=0, told=False)
        os.environ.update(PUSH_LEVELS="error", PUSH_MAX_PER_HOUR="1000", PUSH_CLEAR_QUIETLY="1", PUSH_ENABLED="1")

    def subscribe(self, user, path):
        ph = Phone(path)
        r = self.c.post("api/push/subscribe", json={"subscription": ph.sub()}, headers=dict(as_(user), Origin="https://console.example.test"))
        self.assertEqual(r.status_code, 201, r.get_json())
        return ph

    def notice(self, **kw):
        b = dict(source="office-watch", source_id="cpu", title="The CPU is at its limit", body="98 % for 5 min",
                 level="error", link="", meta={})
        b.update(kw)
        r = self.c.post("api/notifications", json=b)
        self.assertIn(r.status_code, (200, 201))
        self.assertTrue(push.flush(15), "the push queue did not drain")
        return r

    def got(self):
        with GOT_LOCK:
            return list(GOT)

    # 1 ─ the key
    def test_key_made_once_mode_600_never_logged(self):
        k1 = push.load_key()
        push._KEY.clear()
        k2 = push.load_key()
        self.assertTrue(k1)
        self.assertEqual(k1, k2, "a second start must read the same key, not make a new one")
        self.assertEqual(len(unb64u(k1)), 65)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(os.environ["PUSH_KEY_FILE"]).st_mode), 0o600)
        with open(os.environ["PUSH_KEY_FILE"], "rb") as f:
            pem = f.read()
        priv = serialization.load_pem_private_key(pem, None)
        d = priv.private_numbers().private_value.to_bytes(32, "big")
        secret_forms = [b64u(d), base64.b64encode(d).decode(), d.hex()] + [ln for ln in pem.decode().splitlines() if "-----" not in ln]
        r = self.c.get("api/push/key", headers=as_("william"))
        j = r.get_json()
        self.assertEqual(j["key"], k1)
        self.assertTrue(j["enabled"] and j["ready"])
        self.notice()   # a send happens, its log lines too
        logs, body = LOG.getvalue(), r.get_data(as_text=True)
        for s in secret_forms:
            self.assertNotIn(s, logs, "a part of the private key is in the log")
            self.assertNotIn(s, body, "a part of the private key left through the API")

    # 2 ─ who may subscribe, and what
    def test_subscribe_needs_a_person_a_push_service_and_json(self):
        ph = Phone("/a")
        self.assertEqual(self.c.post("api/push/subscribe", json={"subscription": ph.sub()}).status_code, 401)
        bad = dict(ph.sub(), endpoint="http://10.0.0.5:8080/x")
        self.assertEqual(self.c.post("api/push/subscribe", json={"subscription": bad}, headers=as_("william")).status_code, 400)
        os.environ["PUSH_ALLOW_HTTP"] = "0"
        try:
            self.assertEqual(self.c.post("api/push/subscribe", json={"subscription": ph.sub()}, headers=as_("william")).status_code, 400)
        finally:
            os.environ["PUSH_ALLOW_HTTP"] = "1"
        short = dict(ph.sub(), keys={"p256dh": "AAAA", "auth": "AAAA"})
        self.assertEqual(self.c.post("api/push/subscribe", json={"subscription": short}, headers=as_("william")).status_code, 400)
        r = self.c.post("api/push/subscribe", data=json.dumps({"subscription": ph.sub()}), headers=as_("william"),
                        content_type="text/plain")
        self.assertEqual(r.status_code, 400, "a form-like post must not subscribe")

    def test_devices_are_each_persons_own(self):
        a = self.subscribe("william", "/w1")
        self.subscribe("shlomo", "/s1")
        j = self.c.get("api/push/devices?endpoint=" + a.endpoint, headers=as_("william")).get_json()
        self.assertEqual(len(j["devices"]), 1)
        self.assertTrue(j["devices"][0]["this"])
        self.assertIn("Samsung Internet", j["devices"][0]["label"])
        r = self.c.post("api/push/unsubscribe", json={"endpoint": a.endpoint}, headers=as_("shlomo")).get_json()
        self.assertEqual(r["removed"], 0, "one person removed another's phone")
        self.assertEqual(self.c.get("api/push/devices", headers={}).status_code, 401)

    # 3 ─ the fan-out, decrypted
    def test_error_notice_rings_every_phone_decrypted(self):
        w = self.subscribe("william", "/w1")
        s = self.subscribe("shlomo", "/s1")
        self.notice(link="/#/m/meet")
        got = self.got()
        self.assertEqual(sorted(g["path"] for g in got), ["/s1", "/w1"])
        key = self.c.get("api/push/key").get_json()["key"]
        for g in got:
            ph = w if g["path"] == "/w1" else s
            m = ph.decrypt(g["body"])
            n = m["notification"]
            self.assertEqual(n["title"], "The CPU is at its limit")
            self.assertEqual(n["body"], "98 % for 5 min")
            self.assertEqual(n["navigate"], "/#/m/meet")
            self.assertEqual(n["tag"], "notice-office-watch:cpu")
            self.assertFalse(n["silent"])
            self.assertEqual(m["level"], "error")
            hd = g["headers"]
            self.assertEqual(hd["content-encoding"], "aes128gcm")
            self.assertEqual(hd["urgency"], "high")
            self.assertEqual(hd["topic"], push.topic_of("notice-office-watch:cpu"))
            self.assertTrue(int(hd["ttl"]) >= 60)
            # RFC 8292: "vapid t=<jwt>, k=<the office's public key>", signed by that key, for this push service
            auth = hd["authorization"]
            self.assertTrue(auth.startswith("vapid "), auth[:12])
            parts = dict(p.strip().split("=", 1) for p in auth[6:].split(","))
            self.assertEqual(parts["k"], key)
            h64, c64, s64 = parts["t"].split(".")
            claims = json.loads(unb64u(c64))
            self.assertEqual(claims["aud"], BASE)
            self.assertEqual(claims["sub"], "https://console.example.test")
            self.assertGreater(claims["exp"], time.time())
            sig = unb64u(s64)
            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(key))
            pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                       (h64 + "." + c64).encode(), ec.ECDSA(hashes.SHA256()))

    def test_only_the_levels_set_ring(self):
        self.subscribe("william", "/w1")
        self.notice(source_id="a", level="info")
        self.notice(source_id="b", level="warning")
        self.assertEqual(self.got(), [])
        os.environ["PUSH_LEVELS"] = "error,warning"
        self.notice(source_id="c", level="warning")
        self.assertEqual(len(self.got()), 1)

    def test_back_to_normal_replaces_quietly_and_a_reopen_rings(self):
        w = self.subscribe("william", "/w1")
        self.notice()
        self.notice(level="info", title="Back to normal: the CPU")
        got = self.got()
        self.assertEqual(len(got), 2)
        m = w.decrypt(got[1]["body"])["notification"]
        self.assertTrue(m["silent"])
        self.assertEqual(m["tag"], "notice-office-watch:cpu")
        self.assertEqual(got[1]["headers"]["urgency"], "normal")
        self.notice(level="info", title="Back to normal: the CPU")     # still fine: nothing more
        self.assertEqual(len(self.got()), 2)
        self.notice(title="The CPU is at its limit again")              # re-opened: rings
        got = self.got()
        self.assertEqual(len(got), 3)
        self.assertFalse(w.decrypt(got[2]["body"])["notification"]["silent"])

    def test_a_recurring_notice_is_baselined_then_rings_at_most_every_repeat(self):
        os.environ["PUSH_ENABLED"] = "0"
        self.notice(meta={"lastSeen": "2026-10-29T06:00:00+00:00"})    # existed before push was on
        os.environ["PUSH_ENABLED"] = "1"
        self.subscribe("william", "/w1")
        self.notice(meta={"lastSeen": "2026-10-29T06:10:00+00:00"})    # recurs: recorded, not rung
        self.notice(meta={"lastSeen": "2026-10-29T06:20:00+00:00"})    # recurs inside PUSH_REPEAT_MIN
        self.assertEqual(self.got(), [])
        now = time.time()
        self.assertEqual(push.decide(False, "error", "error", True, (now - 241 * 60, "error"), now), "again")
        self.assertIsNone(push.decide(False, "error", "error", True, (now - 60, "error"), now))
        self.assertEqual(push.decide(True, None, "fatal", False, None, now), "new")
        self.assertEqual(push.decide(False, "info", "error", False, None, now), "reopened")

    def test_a_phone_that_left_is_removed(self):
        self.subscribe("william", "/gone1")
        self.subscribe("william", "/missing1")
        keep = self.subscribe("william", "/w1")
        self.notice()
        with push._db() as c:
            left = [r["endpoint"] for r in c.execute("SELECT endpoint FROM push_devices")]
        self.assertEqual(left, [keep.endpoint])

    def test_meta_to_addresses_one_person(self):
        self.subscribe("william", "/w1")
        self.subscribe("shlomo", "/s1")
        self.notice(meta={"to": "shlomo"})
        self.assertEqual([g["path"] for g in self.got()], ["/s1"])

    def test_the_post_answers_at_once_whatever_the_push_service_does(self):
        self.subscribe("william", "/slow1")
        t = time.time()
        r = self.c.post("api/notifications", json={"source": "office-watch", "source_id": "disk", "title": "Disk", "level": "error"})
        took = time.time() - t
        self.assertEqual(r.status_code, 201)
        self.assertLess(took, 0.5, "the POST waited for the push service")
        self.assertTrue(push.flush(15))
        self.assertEqual(len(self.got()), 1)

    def test_a_post_while_the_next_phone_is_slow_does_not_wait_on_the_database(self):
        # R4 08:45Z: deliver() used to hold ONE write transaction across every device, so after the first phone's
        # row was updated, a slow second push service kept the database locked and a notice POSTed meanwhile waited
        self.subscribe("william", "/a1")        # answers at once -> its row is written
        self.subscribe("shlomo", "/slow2")      # the push service takes 3 s
        self.c.post("api/notifications", json={"source": "office-watch", "source_id": "cpu", "title": "CPU", "level": "error"})
        time.sleep(1.0)                          # the worker is now inside the slow push of the second phone
        t = time.time()
        r = self.c.post("api/notifications", json={"source": "office-watch", "source_id": "disk2", "title": "Disk", "level": "warning"})
        took = time.time() - t
        self.assertIn(r.status_code, (200, 201))
        self.assertLess(took, 0.5, "a POST waited %.1f s on the database while a push service was slow" % took)
        self.assertTrue(push.flush(15))
        self.assertEqual(sorted(g["path"] for g in self.got()), ["/a1", "/slow2"])

    def test_send_a_test_to_this_phone(self):
        w = self.subscribe("william", "/w1")
        self.subscribe("william", "/w2")
        j = self.c.post("api/push/test", json={"endpoint": w.endpoint}, headers=as_("william")).get_json()
        self.assertEqual(j["sent"], 1)
        got = self.got()
        self.assertEqual([g["path"] for g in got], ["/w1"])
        self.assertTrue(w.decrypt(got[0]["body"])["notification"]["title"].startswith("בדיקה"))
        self.assertEqual(self.c.post("api/push/test", json={}, headers=as_("nobody")).status_code, 404)

    def test_a_storm_becomes_one_summary(self):
        os.environ["PUSH_MAX_PER_HOUR"] = "2"
        w = self.subscribe("william", "/w1")
        for i in range(5):
            self.notice(source_id="svc-%d" % i, title="down %d" % i)
        got = self.got()
        self.assertEqual(len(got), 3, "two notices, then one summary, then quiet")
        self.assertEqual(w.decrypt(got[2]["body"])["notification"]["tag"], "notice-storm")

    def test_push_off_sends_nothing_and_says_so(self):
        os.environ["PUSH_ENABLED"] = "0"
        self.subscribe("william", "/w1")
        self.notice()
        self.assertEqual(self.got(), [])
        self.assertFalse(self.c.get("api/push/key").get_json()["enabled"])

    def test_the_page_carries_the_card_and_the_worker_is_served(self):
        r = self.c.get("/")
        page = r.get_data(as_text=True)
        r.close()
        self.assertIn('href="push.css"', page)
        self.assertIn('src="push.js"', page)
        for f in ("sw.js", "push.js", "push.css"):
            r = self.c.get(f)
            self.assertEqual(r.status_code, 200, f)
            if f == "sw.js":
                self.assertIn("javascript", r.content_type)
            r.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
