"""Run test_portal_js.py's browser tests against a Chrome reached over CDP — for a machine where Playwright's own
browser is not installed and may not be downloaded, but a Chrome and a Python with Playwright exist in two images
(EXX-29, DGO-1837: 45/45 on vps1 so, 2026-11-12). The Chrome and this runner share one network namespace, so the
tests' local page server on 127.0.0.1 is the browser's too.

    docker run -d --rm --name cdp-chrome --entrypoint google-chrome <image with Chrome> --headless=new --no-sandbox \
        --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir=/tmp/chr about:blank
    docker run --rm --network container:cdp-chrome -v <this folder>:/t:ro -w /t --entrypoint python3 \
        <image with Python Playwright> /t/run_js_tests_cdp.py
    docker rm -f cdp-chrome

CDP_URL names another address (default http://127.0.0.1:9222).
"""
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_portal_js as t  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")


def set_up_class(cls):
    cls.pw = sync_playwright().start()
    cls.browser = cls.pw.chromium.connect_over_cdp(CDP_URL)
    cls.server = ThreadingHTTPServer(("127.0.0.1", 0), t.Served)
    threading.Thread(target=cls.server.serve_forever, daemon=True).start()


def tear_down_class(cls):
    cls.server.shutdown()
    cls.pw.stop()


if __name__ == "__main__":
    t.PanelScriptTests.setUpClass = classmethod(set_up_class)
    t.PanelScriptTests.tearDownClass = classmethod(tear_down_class)
    unittest.main(module=t, argv=[sys.argv[0], "-v"])
