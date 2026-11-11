#!/usr/bin/env python3
"""The port-80 answer's own test (DGO-1595) — run by the image's build and by hand.

    python3 platform-base/https-redirect/test_redirect.py

What is proven here is the part that decides where a caller is sent: the host and the path come from
traefik's `X-Forwarded-*` (a client cannot write them through the edge), a request with no host is a
400 rather than a redirect to nowhere, and the status is 308 for GET **and for POST** — the one
property the whole service exists for, because traefik's own redirects answer 301/302 and a 301
turns a webhook's POST into a GET at the client.
"""
import http.client
import importlib.util
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("https_redirect", os.path.join(HERE, "server.py"))
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


class Target(unittest.TestCase):
    def test_forwarded_host_and_uri_are_the_destination(self):
        h = {"X-Forwarded-Host": "n8n.example.com", "X-Forwarded-Uri": "/rest/settings?x=1"}
        self.assertEqual(MODULE.target(h, "/ignored"), "https://n8n.example.com/rest/settings?x=1")

    def test_the_request_path_is_the_fallback(self):
        self.assertEqual(MODULE.target({"Host": "a.example.com"}, "/deep/path"), "https://a.example.com/deep/path")

    def test_no_host_is_a_refusal_not_a_redirect(self):
        self.assertIsNone(MODULE.target({}, "/x"))

    def test_a_host_that_would_make_another_origin_is_refused(self):
        for bad in ("evil.com/", "evil.com\\x", "person180@example.com", " ", ".leading"):
            self.assertIsNone(MODULE.target({"X-Forwarded-Host": bad}, "/x"), bad)

    def test_a_path_that_does_not_start_with_a_slash_is_made_one(self):
        self.assertEqual(MODULE.target({"Host": "h"}, "x"), "https://h/x")


class Live(unittest.TestCase):
    """The real handler, on a real socket: the status and the Location, for both methods."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, headers):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, headers=headers)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status, r.getheader("Location")

    def test_get_is_308_to_https(self):
        status, loc = self.call("GET", "/a?b=1", {"Host": "console.example.com"})
        self.assertEqual((status, loc), (308, "https://console.example.com/a?b=1"))

    def test_post_is_308_and_the_method_is_kept(self):
        status, loc = self.call("POST", "/webhook/x", {"Host": "n8n.example.com", "Content-Length": "0"})
        self.assertEqual((status, loc), (308, "https://n8n.example.com/webhook/x"))

    def test_healthz_answers_and_does_not_redirect(self):
        status, loc = self.call("GET", "/healthz", {"Host": "https-redirect"})
        self.assertEqual((status, loc), (200, None))

    def test_a_request_with_no_host_is_400(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("GET", "/x", skip_host=True)
        c.putheader("X-Forwarded-Host", "")
        c.endheaders()
        r = c.getresponse()
        status = r.status
        r.read()
        c.close()
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
