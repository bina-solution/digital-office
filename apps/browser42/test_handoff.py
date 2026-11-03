"""The human hand-off (DGO-571): one address, the right tab in front — unit tests, no browser, no network."""
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent


def load(name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stub_websockets() -> None:
    """group-manager.py and broker.py import websockets at the top; the native tests carry none."""
    for name, attr in (("websockets.sync.client", "connect"), ("websockets.asyncio.client", "connect"),
                       ("websockets.asyncio.server", "serve")):
        try:
            __import__(name)
        except ImportError:
            parts = name.split(".")
            for depth in range(1, len(parts) + 1):
                sys.modules.setdefault(".".join(parts[:depth]), types.ModuleType(".".join(parts[:depth])))
            setattr(sys.modules[name], attr, getattr(sys.modules[name], attr, None))


stub_websockets()
MODULE = load("handoff.py", "browser42_handoff")
TOKEN = "test-token"


def write_json(root: Path, relative: str, payload: dict) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RouteShapeTests(unittest.TestCase):
    def test_slug_is_read_from_the_route_and_nothing_else(self):
        self.assertEqual(MODULE.slug_from_path("/handoff/whatsapp-pair"), "whatsapp-pair")
        self.assertEqual(MODULE.slug_from_path("/handoff/whatsapp-pair/"), "whatsapp-pair")
        self.assertEqual(MODULE.slug_from_path("/handoff/task-7?x=1"), "task-7")
        for bad in ("/handoff/", "/handoff/../etc", "/handoff/Upper", "/handoff/a b", "/handoff/a--b",
                    "/handoff/-a", "/handoff/a/b", "/view/", "/handoffs/a"):
            self.assertIsNone(MODULE.slug_from_path(bad), bad)

    def test_redirect_is_pinned_to_the_view_or_the_mount_and_says_what_was_lost(self):
        self.assertEqual(MODULE.redirect_target(False), "/view/")
        # The console mounts /view/ AT /a/browser42/ (app.json module.url): behind it the view IS the
        # mount — and the mount is this app's constant, whatever the forwarded header said.
        self.assertEqual(MODULE.redirect_target(True), "/a/browser42/")
        self.assertEqual(MODULE.redirect_target(False, "pair"), "/view/?lost=pair")
        self.assertEqual(MODULE.redirect_target(True, "pair"), "/a/browser42/?lost=pair")

    def test_links_are_console_deep_links_from_what_the_office_declares(self):
        self.assertEqual(MODULE.handoff_link("s", {}), "http://console.localhost:8080/a/browser42/handoff/s")
        self.assertEqual(MODULE.handoff_link("s", {"CONSOLE_BASE_URL": "console.hacohen.example", "AUTH_PROTOCOL": "https"}),
                         "https://console.hacohen.example/a/browser42/handoff/s")
        self.assertEqual(MODULE.handoff_link("s", {"CONSOLE_BASE_URL": "console.localhost:8080"}),
                         "http://console.localhost:8080/a/browser42/handoff/s")
        self.assertEqual(MODULE.handoff_link("s", {"CONSOLE_BASE_URL": "https://console.x/"}),
                         "https://console.x/a/browser42/handoff/s")
        self.assertEqual(MODULE.view_link({"CONSOLE_BASE_URL": "console.localhost:8080"}), "http://console.localhost:8080/a/browser42/")


class RecordTests(unittest.TestCase):
    def test_a_session_group_or_a_task_names_the_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, "groups/pair/group.json", {"slug": "pair", "tab_id": 42, "group_id": 7, "color": "cyan", "url": "https://web.whatsapp.com"})
            write_json(root, "tasks/job/task.json", {"slug": "job", "tab_id": 43, "native_group": {"id": 8, "color": "pink"}})
            self.assertEqual(MODULE.group_record("pair", root)["tab_id"], 42)
            self.assertEqual((MODULE.group_id_of(MODULE.group_record("pair", root)), MODULE.group_color_of(MODULE.group_record("pair", root))), (7, "cyan"))
            self.assertEqual(MODULE.group_record("job", root)["tab_id"], 43)
            self.assertEqual((MODULE.group_id_of(MODULE.group_record("job", root)), MODULE.group_color_of(MODULE.group_record("job", root))), (8, "pink"))
            self.assertIsNone(MODULE.group_record("never", root))
            (root / "groups" / "broken").mkdir()
            (root / "groups" / "broken" / "group.json").write_text("{not json")
            self.assertIsNone(MODULE.group_record("broken", root))


class FrontTests(unittest.TestCase):
    def test_the_command_carries_what_recovers_the_tab_after_a_sleep(self):
        sent = []
        MODULE.front("pair", {"url": "https://web.whatsapp.com/", "color": "cyan"}, budget=1,
                     send=lambda command: sent.append(command) or {"ok": True}, clock=lambda: 0.0, sleep=lambda s: None)
        MODULE.front("job", {"url": "https://claude.ai/x", "native_group": {"color": "pink"}}, budget=1,
                     send=lambda command: sent.append(command) or {"ok": True}, clock=lambda: 0.0, sleep=lambda s: None)
        MODULE.front("bare", None, budget=1, send=lambda command: sent.append(command) or {"ok": True}, clock=lambda: 0.0, sleep=lambda s: None)
        self.assertEqual(sent, [
            {"action": "front", "slug": "pair", "url": "https://web.whatsapp.com/", "label": "pair", "color": "cyan"},
            {"action": "front", "slug": "job", "url": "https://claude.ai/x", "label": "job", "color": "pink"},
            {"action": "front", "slug": "bare", "url": "", "label": "bare"},
        ])

    def test_front_waits_for_the_extension_then_returns_its_answer(self):
        answers = [ConnectionRefusedError("broker restarting"),
                   {"ok": False, "error": {"code": "extension_unavailable", "message": "extension is not connected"}},
                   {"ok": True, "tabId": 42, "groupId": 7, "recovered": True}]
        sent, slept, now = [], [], [0.0]

        def send(command):
            sent.append(command["slug"])
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        result = MODULE.front("pair", {}, budget=20, send=send, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
        self.assertEqual(result, {"ok": True, "tabId": 42, "groupId": 7, "recovered": True})
        self.assertEqual((sent, slept), (["pair"] * 3, [1, 1]))

    def test_a_lost_tab_is_a_definite_answer_returned_at_once(self):
        slept = []
        lost = {"ok": False, "error": {"code": "tab_lost", "message": "no live tab for gone, and none at its last address"}}
        result = MODULE.front("gone", {}, budget=20, send=lambda command: lost, clock=lambda: 0.0, sleep=slept.append)
        self.assertEqual((result["error"]["code"], slept), ("tab_lost", []))
        legacy = MODULE.front("gone", {}, budget=20, send=lambda command: {"ok": False, "error": "no live tab"}, clock=lambda: 0.0, sleep=slept.append)
        self.assertEqual((legacy["ok"], slept), (False, []))

    def test_the_budget_ends_the_wait(self):
        now = [0.0]
        result = MODULE.front("pair", {}, budget=3, send=lambda command: {"ok": False, "error": {"code": "extension_unavailable"}},
                              clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
        self.assertEqual(result["error"]["code"], "extension_unavailable")
        self.assertGreaterEqual(now[0], 3)


class WakerTests(unittest.TestCase):
    def test_one_launch_is_shared_by_every_request_that_arrives_while_it_runs(self):
        release, calls = threading.Event(), []

        def slow_wake():
            calls.append(1)
            release.wait(5)
            return True

        waker = MODULE.Waker(wake=slow_wake)
        self.assertIsNone(waker.ensure(0.05))            # the first request: still waking
        self.assertIsNone(waker.ensure(0.05))            # a reload joins the same launch
        self.assertEqual(len(calls), 1, "cloakserve was asked ONCE")
        release.set()
        result = waker.ensure(5)
        self.assertTrue(result["awake"])
        self.assertGreaterEqual(result["took"], 0.0)
        self.assertEqual(len(calls), 1)

    def test_an_awake_browser_answers_at_once_and_a_failed_wake_is_reported(self):
        self.assertEqual(MODULE.Waker(wake=lambda: True).ensure(5)["awake"], True)
        self.assertEqual(MODULE.Waker(wake=lambda: False).ensure(5)["awake"], False)

    def test_after_a_finished_launch_the_next_request_asks_again(self):
        calls = []
        waker = MODULE.Waker(wake=lambda: calls.append(1) or True)
        waker.ensure(5)
        waker.ensure(5)
        self.assertEqual(len(calls), 2, "a later sleep must be woken by a later request")


class FakeWaker:
    def __init__(self, result):
        self.result = result

    def ensure(self, timeout):
        return self.result


class PresentationTests(unittest.TestCase):
    def test_only_a_fullscreen_chromium_window_gets_f11(self):
        calls = []

        def run(argv):
            calls.append(argv)
            if argv[0] == "wmctrl":
                return ("0x01 0 chromium.Chromium      host chromium\n"
                        "0x02 0 fluxbox.fluxbox        host toolbar\n"
                        "0x03 0 chromium.Chromium      host other\n")
            if argv[0] == "xprop":
                return "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN" if argv[2] == "0x01" else "_NET_WM_STATE(ATOM) = _NET_WM_STATE_MAXIMIZED_VERT"
            return ""

        self.assertEqual(MODULE.present_standard(run), 1)
        keys = [argv for argv in calls if argv[0] == "xdotool"]
        self.assertEqual(keys, [["xdotool", "windowactivate", "--sync", "0x01", "key", "--window", "0x01", "F11"]])

    def test_no_x_tools_means_nothing_switched(self):
        self.assertEqual(MODULE.present_standard(lambda argv: ""), 0)


class PerformTests(unittest.TestCase):
    def test_while_the_browser_is_still_waking_nothing_else_happens(self):
        touched = []
        result = MODULE.perform("pair", {"tab_id": 1}, waker=FakeWaker(None),
                                front=lambda slug, record: touched.append("front"), present=lambda: touched.append("present"),
                                touch=lambda: touched.append("touch"), sleep=lambda s: touched.append("sleep"))
        self.assertEqual((result, touched), ({"slug": "pair", "waking": True}, []))

    def test_awake_order_is_wake_then_use_then_front_then_strip_and_a_failed_front_is_lost_not_fatal(self):
        order = []
        result = MODULE.perform(
            "pair", {"tab_id": 42, "group_id": 7, "state": "active"}, waker=FakeWaker({"awake": True, "took": 0.01}),
            front=lambda slug, record: order.append(f"front:{slug}:{record['tab_id']}") or {"ok": False, "error": {"code": "tab_lost"}},
            present=lambda: order.append("present") or 1,
            touch=lambda: order.append("touch"),
            sleep=lambda s: order.append(f"sleep:{s}"))
        self.assertEqual(order, ["touch", "front:pair:42", "present"])
        self.assertEqual((result["waking"], result["awake"], result["cold"], result["front"], result["lost"]), (False, True, False, False, True))
        self.assertEqual((result["presentation_switched"], result["tab_id"], result["group_id"], result["state"]), (1, 42, 7, "active"))

    def test_after_a_cold_launch_the_compact_press_is_given_time_before_the_look(self):
        order = []
        result = MODULE.perform("pair", {"tab_id": 1}, waker=FakeWaker({"awake": True, "took": MODULE.COLD_LAUNCH_S + 1}),
                                front=lambda slug, record: {"ok": True}, present=lambda: order.append("present") or 0,
                                touch=lambda: order.append("touch"), sleep=lambda s: order.append(f"sleep:{s}"))
        self.assertEqual(order, ["touch", f"sleep:{MODULE.COMPACT_SETTLE_S}", "present"])
        self.assertEqual((result["cold"], result["front"], result["lost"]), (True, True, False))


class NoticeTests(unittest.TestCase):
    def post(self, **kwargs):
        posts = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout=None):
            posts.append((request.full_url, json.loads(request.data.decode("utf-8")), timeout))
            return Response()

        with patch.object(MODULE, "urlopen", side_effect=fake_urlopen):
            ok = MODULE.notify_human(**kwargs)
        return ok, posts

    def test_the_notice_is_one_per_slug_in_hebrew_with_the_link(self):
        link = "http://console.localhost:8080/a/browser42/handoff/pair"
        ok, posts = self.post(slug="pair", body="נדרש אדם", link=link, url="http://notifications:8977/")
        self.assertTrue(ok)
        url, body, timeout = posts[0]
        self.assertEqual(url, "http://notifications:8977/api/notifications")
        self.assertEqual((body["source"], body["source_id"], body["level"], body["link"]), ("browser42", "handoff:pair", "warning", link))
        self.assertIn("pair", body["title"])
        self.assertTrue(any("֐" <= ch <= "׿" for ch in body["title"]), "the title is Hebrew")
        self.assertIn(link, body["body"])
        self.assertEqual(body["meta"], {"app": "browser42", "slug": "pair"})
        self.assertLessEqual(timeout, 5)

    def test_an_episode_is_the_same_last_seen_so_a_repeat_is_not_new_again(self):
        _, first = self.post(slug="pair", body="x", link="y", url="http://n", since=1_790_000_000)
        _, again = self.post(slug="pair", body="x", link="y", url="http://n", since=1_790_000_000)
        _, later = self.post(slug="pair", body="x", link="y", url="http://n", since=1_790_000_060)
        self.assertEqual(first[0][1]["meta"]["lastSeen"], "2026-09-21T14:13:20+00:00")   # the centre's own isoformat, UTC
        self.assertEqual(first[0][1]["meta"]["lastSeen"], again[0][1]["meta"]["lastSeen"])
        self.assertGreater(later[0][1]["meta"]["lastSeen"], first[0][1]["meta"]["lastSeen"])

    def test_no_address_means_no_notice_and_a_failure_is_swallowed(self):
        with patch.object(MODULE, "urlopen", side_effect=AssertionError("must not be called")):
            self.assertFalse(MODULE.notify_human("pair", "x", "y", url=""))
        with patch.object(MODULE, "urlopen", side_effect=urllib.error.URLError("down")):
            self.assertFalse(MODULE.notify_human("pair", "x", "y", url="http://notifications:8977"))


class ServerTests(unittest.TestCase):
    """The route itself, over HTTP on a loopback port — the browser work replaced by fakes."""

    @classmethod
    def setUpClass(cls):
        cls.server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self._token = MODULE.TOKEN
        MODULE.TOKEN = TOKEN

    def tearDown(self):
        MODULE.TOKEN = self._token

    def get(self, path, headers=None, token=TOKEN):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        sent = dict(headers or {})
        if token is not None:
            sent[MODULE.TOKEN_HEADER] = token
        request = urllib.request.Request(self.base + path, headers=sent)
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def test_a_known_slug_is_performed_and_sent_to_the_view_or_the_pinned_mount(self):
        performed = []
        with patch.object(MODULE, "group_record", return_value={"tab_id": 42, "group_id": 7}), \
                patch.object(MODULE, "perform", side_effect=lambda slug, record: performed.append((slug, record)) or {"slug": slug, "waking": False, "lost": False}), \
                contextlib.redirect_stdout(io.StringIO()):
            status, headers, _ = self.get("/handoff/pair")
            self.assertEqual((status, headers["Location"]), (302, "/view/"))
            status, headers, _ = self.get("/handoff/pair", {"X-Forwarded-Prefix": "/a/browser42"})
            self.assertEqual((status, headers["Location"]), (302, "/a/browser42/"))
            status, headers, _ = self.get("/handoff/pair", {"X-Forwarded-Prefix": "//evil.example/x"})
            self.assertEqual((status, headers["Location"]), (302, "/a/browser42/"), "the header is a hint, never the address")
        self.assertEqual(performed, [("pair", {"tab_id": 42, "group_id": 7})] * 3)

    def test_a_tab_that_could_not_be_fronted_is_said_not_pretended(self):
        with patch.object(MODULE, "group_record", return_value={"tab_id": 42}), \
                patch.object(MODULE, "perform", return_value={"slug": "pair", "waking": False, "lost": True}), \
                contextlib.redirect_stdout(io.StringIO()):
            status, headers, _ = self.get("/handoff/pair")
            self.assertEqual((status, headers["Location"]), (302, "/view/?lost=pair"))
            status, headers, _ = self.get("/handoff/pair", {"X-Forwarded-Prefix": "/a/browser42"})
            self.assertEqual((status, headers["Location"]), (302, "/a/browser42/?lost=pair"))

    def test_while_waking_the_page_says_so_and_reloads_itself(self):
        with patch.object(MODULE, "group_record", return_value={"tab_id": 42}), \
                patch.object(MODULE, "perform", return_value={"slug": "pair", "waking": True}), \
                contextlib.redirect_stdout(io.StringIO()):
            status, headers, body = self.get("/handoff/pair")
        self.assertEqual((status, headers["Refresh"]), (200, "5"))
        self.assertIn("text/html", headers["Content-Type"])
        text = body.decode("utf-8")
        self.assertIn('http-equiv="refresh" content="5"', text)
        self.assertIn("«pair»", text)
        self.assertIn('dir="rtl"', text)
        self.assertNotIn("#", text.split("<body>", 1)[1], "no colour of its own")

    def test_without_the_edge_token_the_hand_off_is_refused(self):
        with patch.object(MODULE, "perform", side_effect=AssertionError("must not perform")), \
                patch.object(MODULE, "group_record", return_value={"tab_id": 42}):
            status, _, body = self.get("/handoff/pair", token=None)
            self.assertEqual((status, json.loads(body)["error"]["code"]), (403, "forbidden"))
            status, _, _ = self.get("/handoff/pair", token="wrong")
            self.assertEqual(status, 403)
            with patch.object(MODULE, "TOKEN", ""):
                status, _, _ = self.get("/handoff/pair", token="")
                self.assertEqual(status, 403, "an empty token refuses everything")
        status, _, body = self.get("/healthz", token=None)
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))

    def test_an_unknown_slug_and_a_wrong_path_are_404_by_name(self):
        with patch.object(MODULE, "group_record", return_value=None), \
                patch.object(MODULE, "perform", side_effect=AssertionError("nothing to perform")):
            status, _, body = self.get("/handoff/never")
            error = json.loads(body)["error"]
            self.assertEqual((status, error["code"]), (404, "no_such_group"))
            self.assertIn("was ever opened", error["message"])
            self.assertNotIn("or it was closed", error["message"])
            status, _, body = self.get("/handoff/../etc")
            self.assertEqual(status, 404)
            status, _, body = self.get("/view/")
            self.assertEqual((status, json.loads(body)["error"]["code"]), (404, "not_found"))


class CliTests(unittest.TestCase):
    def test_link_prints_the_address_and_what_it_brings_to_the_front(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "DATA", Path(directory)), \
                patch.dict("os.environ", {"CONSOLE_BASE_URL": "console.localhost:8080", "AUTH_PROTOCOL": "http"}):
            write_json(Path(directory), "groups/pair/group.json", {"slug": "pair", "tab_id": 42, "group_id": 7, "url": "https://web.whatsapp.com"})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(MODULE.main(["handoff.py", "link", "pair"]), 0)
            answer = json.loads(out.getvalue())
            self.assertEqual((answer["ok"], answer["url"], answer["tab_id"], answer["group_id"], answer["page"]),
                             (True, "http://console.localhost:8080/a/browser42/handoff/pair", 42, 7, "https://web.whatsapp.com"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(MODULE.main(["handoff.py", "link", "never"]), 2)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "no_such_group")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(MODULE.main(["handoff.py", "link", "Not A Slug"]), 2)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "usage")


class WiringTests(unittest.TestCase):
    """The pieces the route depends on, read where they live."""

    def test_the_broker_accepts_front(self):
        broker = load("broker.py", "browser42_broker_for_handoff")
        self.assertIn("front", broker.SUPPORTED_ACTIONS)

    def test_the_extension_fronts_in_the_same_window_and_recovers_a_tab_by_its_last_address(self):
        source = (HERE / "extension" / "worker-1.2.js").read_text(encoding="utf-8")
        self.assertIn("? frontSession(command)", source)
        body = source[source.index("async function frontSession"):source.index("async function listSessions")]
        self.assertIn("recoverSession(slug, stored, command)", body)
        self.assertIn("chrome.tabs.update(existing.tab.id, { active: true })", body)
        self.assertIn("code: 'tab_lost'", body)
        for never in ("tabs.create", "windows.create"):
            self.assertNotIn(never, body)
        recover = source[source.index("async function recoverSession"):source.index("async function frontSession")]
        self.assertIn("stored?.lastUrl, command.url", recover)
        self.assertIn("entry.title === slug", recover, "the restored group's NAME decides first")
        self.assertIn("others.has(title)", recover, "another session's restored tab is never a candidate")
        self.assertIn("if (exact.length > 1) return null", recover, "ambiguity is lost, not a guess")
        self.assertIn("await claimTab(id, slug)", recover, "the recovered tab is re-tagged")
        self.assertIn("session.lastUrl = changeInfo.url", source.replace("current.lastUrl", "session.lastUrl"), "the last address is kept current")
        self.assertIn("lastUrl: command.url", source)

    def test_caddy_routes_the_handoff_with_the_token_and_carries_the_lost_marker(self):
        caddyfile = (HERE / "caddy" / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("handle /handoff/*", caddyfile)
        handle = caddyfile[caddyfile.index("handle /handoff/*"):caddyfile.index("redir / /view/")]
        # The internal-only alias: the browser's hand-off listens on browser42's network alone, and
        # caddy sits on both networks, where the bare service name may resolve to the other (DGO-983).
        # Caddy takes it from its compose environment, so a change of it recreates Caddy.
        self.assertIn("reverse_proxy {$BROWSER42_UPSTREAM}:8767", handle)
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("BROWSER42_UPSTREAM: browser42-browser-internal", compose)
        self.assertIn("header_up X-Browser42-Handoff {$MCP_TOKEN}", handle)
        self.assertIn("path=websockify&{query}", caddyfile, "the /view/ redir keeps ?lost=")

    def test_the_viewer_says_what_was_lost(self):
        navigation = (HERE / "browser-navigation.js").read_text(encoding="utf-8")
        self.assertIn('get("lost")', navigation)
        self.assertIn("UI.showStatus", navigation)

    def test_the_console_passthrough_strips_the_mount_for_the_handoff_prefix(self):
        manifest = json.loads((HERE / "app.json").read_text(encoding="utf-8"))
        passthroughs = manifest["routing"][0]["module"]["passthrough"]
        handoff = [spec for spec in passthroughs if spec["path"] == "/handoff"]
        self.assertEqual(handoff, [{"path": "/handoff", "transport": "http", "match": "prefix", "strip_mount_prefix": True}])

    def test_every_browser42_container_that_speaks_of_the_handoff_mounts_the_file(self):
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertEqual(compose.count("- ./handoff.py:/handoff.py:ro"), 3, "browser, task runner, watchdog")
        self.assertIn("- '8767'", compose)
        self.assertIn("BROWSER42_MCP_TOKEN: ${BROWSER42_MCP_TOKEN:-}", compose, "the browser holds the token Caddy sends")
        self.assertIn("python3 /handoff.py serve &", (HERE / "start-browser.sh").read_text(encoding="utf-8"))


class ExtensionLogicTests(unittest.TestCase):
    """The worker's own functions, run in node against a fake `chrome` (test_worker.mjs)."""

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine — the rule is stated in recoverSession's comment")
    def test_two_groups_on_one_address_never_swap_tabs(self):
        run = subprocess.run([shutil.which("node"), str(HERE / "test_worker.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("6 cases ok", run.stdout)


class CaptchaHandoffTests(unittest.TestCase):
    def test_exhausted_rounds_hand_the_owner_the_link_and_tell_him_once_per_task(self):
        gm = load("group-manager.py", "browser42_group_manager_for_handoff")
        notices = []
        task = {"slug": "whatsapp-pair", "state": "active", "created_at": 1_790_000_000,
                "captcha": {"attempts": gm.CAPTCHA_MAX_ATTEMPTS, "history": []}}
        with patch.object(gm, "read_task", return_value=task), \
                patch.object(gm, "task_connection", return_value=(None, None, None)), \
                patch.object(gm.handoff, "notify_human", side_effect=lambda slug, body, link, **kw: notices.append((slug, body, link, kw.get("since"))) or True), \
                patch.dict("os.environ", {"CONSOLE_BASE_URL": "console.localhost:8080", "AUTH_PROTOCOL": "http"}):
            with self.assertRaises(gm.BrowserTaskError) as caught:
                gm.task_captcha("whatsapp-pair", "click", "0")
        link = "http://console.localhost:8080/a/browser42/handoff/whatsapp-pair"
        self.assertEqual(caught.exception.code, "captcha_attempts_exhausted")
        self.assertIn(link, str(caught.exception))
        self.assertNotIn("browser42.localhost:8080/view/", str(caught.exception))
        self.assertEqual([(slug, found, since) for slug, _, found, since in notices], [("whatsapp-pair", link, 1_790_000_000)])
        self.assertIn("captcha", notices[0][1])


if __name__ == "__main__":
    unittest.main()
