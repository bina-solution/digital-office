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
        for bad in ("evil.com/", "evil.com\\x", "person93@example.com", " ", ".leading"):
            self.assertIsNone(MODULE.target({"X-Forwarded-Host": bad}, "/x"), bad)

    def test_a_path_that_does_not_start_with_a_slash_is_made_one(self):
        self.assertEqual(MODULE.target({"Host": "h"}, "x"), "https://h/x")


class Moved(unittest.TestCase):
    """An office that moved (DGO-2013): its former names send every host to the same host under the new name."""

    def setUp(self):
        self.saved = (MODULE.SUFFIX, MODULE.FORMER)
        MODULE.SUFFIX, MODULE.FORMER = "bina-solutions.co.il", ("staging.digital-office.co.il",)

    def tearDown(self):
        MODULE.SUFFIX, MODULE.FORMER = self.saved

    def test_a_former_host_goes_to_the_same_host_under_the_new_name(self):
        h = {"X-Forwarded-Host": "console.staging.digital-office.co.il", "X-Forwarded-Uri": "/go/DGO-1?x=1"}
        self.assertEqual(MODULE.target(h, "/"), "https://console.bina-solutions.co.il/go/DGO-1?x=1")

    def test_a_deeper_host_keeps_every_label(self):
        h = {"X-Forwarded-Host": "plane.hp-laptop.console.staging.digital-office.co.il"}
        self.assertEqual(MODULE.target(h, "/a"), "https://plane.hp-laptop.console.bina-solutions.co.il/a")

    def test_the_former_apex_goes_to_the_new_apex_and_a_port_is_dropped(self):
        self.assertEqual(MODULE.target({"Host": "staging.digital-office.co.il:443"}, "/"),
                         "https://bina-solutions.co.il/")

    def test_the_current_name_is_not_moved(self):
        self.assertEqual(MODULE.target({"Host": "console.bina-solutions.co.il"}, "/x"),
                         "https://console.bina-solutions.co.il/x")

    def test_a_name_that_only_ends_like_a_former_one_is_refused(self):
        self.assertIsNone(MODULE.target({"Host": "evilstaging.digital-office.co.il"}, "/x"))

    def test_an_office_moved_into_a_subdomain_of_its_former_name_stays_put(self):
        MODULE.SUFFIX, MODULE.FORMER = "bina.example.com", ("example.com",)
        self.assertEqual(MODULE.target({"Host": "console.bina.example.com"}, "/"), "https://console.bina.example.com/")
        self.assertEqual(MODULE.target({"Host": "console.example.com"}, "/"), "https://console.bina.example.com/")

    def test_an_office_moved_out_of_a_subdomain_takes_the_longer_former_name(self):
        MODULE.SUFFIX, MODULE.FORMER = "example.com", ("staging.example.com",)
        self.assertEqual(MODULE.target({"Host": "n8n.staging.example.com"}, "/w"), "https://n8n.example.com/w")

    def test_no_former_name_moves_nothing(self):
        MODULE.FORMER = ()
        self.assertIsNone(MODULE.target({"Host": "console.staging.digital-office.co.il"}, "/"))

    def test_port_80_upgrades_a_former_host_where_it_is(self):
        # vps1, 2026-11-20: n8n stays on staging, and http://n8n.staging…/healthz was moved to a name nothing serves.
        # On port 80 the former host goes to https on the SAME name; websecure moves it only if nothing serves it there.
        h = {"X-Forwarded-Host": "n8n.staging.digital-office.co.il", "X-Forwarded-Uri": "/webhook/abc?x=1",
             "X-Forwarded-Proto": "http"}
        self.assertEqual(MODULE.target(h, "/"), "https://n8n.staging.digital-office.co.il/webhook/abc?x=1")

    def test_port_80_drops_the_cleartext_port_when_it_upgrades(self):
        # the second reader: `http://host:80/…` (a webhook client keeps the :80) must not become https on port 80
        h = {"X-Forwarded-Host": "n8n.staging.digital-office.co.il:80", "X-Forwarded-Proto": "http"}
        self.assertEqual(MODULE.target(h, "/x"), "https://n8n.staging.digital-office.co.il/x")

    def test_https_moves_a_former_host(self):
        h = {"X-Forwarded-Host": "console.staging.digital-office.co.il", "X-Forwarded-Uri": "/x",
             "X-Forwarded-Proto": "https"}
        self.assertEqual(MODULE.target(h, "/"), "https://console.bina-solutions.co.il/x")

    def test_port_80_still_refuses_a_name_of_no_office(self):
        for bad in ("evilstaging.digital-office.co.il", "evil.com"):
            self.assertIsNone(MODULE.target({"Host": bad, "X-Forwarded-Proto": "http"}, "/x"), bad)

    def test_port_80_keeps_the_current_name_as_before(self):
        self.assertEqual(MODULE.target({"Host": "console.bina-solutions.co.il", "X-Forwarded-Proto": "http"}, "/x"),
                         "https://console.bina-solutions.co.il/x")

    def test_a_query_or_fragment_in_the_host_is_refused(self):
        # the second reader of 0d64d3b23: a direct caller's `evil.com?.staging…` made `https://evil.com?.bina…/`
        for bad in ("evil.com?.staging.digital-office.co.il", "evil.com#.staging.digital-office.co.il"):
            for proto in ("http", "https", ""):
                self.assertIsNone(MODULE.target({"X-Forwarded-Host": bad, "X-Forwarded-Proto": proto}, "/x"), bad)


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

    def test_a_former_hosts_post_is_308_to_the_new_name(self):
        saved = (MODULE.SUFFIX, MODULE.FORMER)
        MODULE.SUFFIX, MODULE.FORMER = "new.example.com", ("old.example.net",)
        try:
            status, loc = self.call("POST", "/webhook/x", {"Host": "n8n.old.example.net", "Content-Length": "0"})
        finally:
            MODULE.SUFFIX, MODULE.FORMER = saved
        self.assertEqual((status, loc), (308, "https://n8n.new.example.com/webhook/x"))

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
