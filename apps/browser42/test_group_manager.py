import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


PATH = Path(__file__).with_name("group-manager.py")
if "websockets.sync.client" not in sys.modules:
    websockets = types.ModuleType("websockets")
    sync = types.ModuleType("websockets.sync")
    client = types.ModuleType("websockets.sync.client")
    client.connect = None
    sys.modules.setdefault("websockets", websockets)
    sys.modules.setdefault("websockets.sync", sync)
    sys.modules.setdefault("websockets.sync.client", client)
SPEC = importlib.util.spec_from_file_location("browser42_group_manager", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeSocket:
    def __init__(self, result):
        self.result = result
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def send(self, message):
        self.sent = message

    def recv(self, timeout):
        return self.result


class GroupManagerTests(unittest.TestCase):
    def test_broker_command_returns_success(self):
        socket = FakeSocket('{"ok": true, "tabId": 42}')
        with patch.object(MODULE, "websocket_connect", return_value=socket):
            result = MODULE.broker_command({"action": "allocate"})
        self.assertEqual(result["tabId"], 42)
        self.assertIn('"role": "client"', socket.sent)

    def test_broker_command_raises_explicit_error(self):
        socket = FakeSocket('{"ok": false, "error": "extension is not connected"}')
        with patch.object(MODULE, "websocket_connect", return_value=socket), patch.object(MODULE.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "extension is not connected"):
                MODULE.broker_command({"action": "allocate"})

    def test_open_rejects_missing_direct_url_before_allocation(self):
        with self.assertRaisesRegex(ValueError, "direct http"):
            MODULE.cmd_open("task", "about:blank")

    def test_open_rejects_implicit_slug(self):
        with self.assertRaisesRegex(ValueError, "explicit slug"):
            MODULE.cmd_open(None, "https://example.com")

    def test_handles_round_trip_without_site_specific_selector(self):
        original = {"kind": "role", "role": "button", "name": "Continue", "nth": 1}
        self.assertEqual(MODULE.parse_handle(MODULE.handle(original)), original)

    def test_container_handle_round_trip(self):
        original = {"kind": "tag", "tag": "article", "nth": 2}
        self.assertEqual(MODULE.parse_handle(MODULE.handle(original)), original)

    def test_task_slug_is_never_rewritten(self):
        self.assertEqual(MODULE.canonical_slug("task-20260803"), "task-20260803")
        with self.assertRaisesRegex(ValueError, "never rewritten"):
            MODULE.canonical_slug("Task 20260803")

    def test_task_error_has_stable_code(self):
        error = MODULE.BrowserTaskError("task_not_found", "missing")
        self.assertEqual(error.code, "task_not_found")
        self.assertEqual(str(error), "missing")

    def test_invalid_url_has_machine_readable_code(self):
        with self.assertRaises(MODULE.BrowserTaskError) as caught:
            MODULE.direct_url("file:///tmp/nope")
        self.assertEqual(caught.exception.code, "invalid_url")

    def test_a_refused_lease_is_reported_as_itself(self):
        # The two `except` clauses named classes this file never imported, so a refusal — the
        # branch the docstring promises is "reported AS ITSELF" — surfaced as a NameError.
        refusal = urllib.error.HTTPError("http://connections/api/broker/lease", 403, "Forbidden", {},
                                         io.BytesIO(b'{"error": "not declared"}'))
        with patch.object(MODULE, "_self_container_id", return_value=""), \
             patch.object(MODULE, "urlopen", side_effect=refusal):
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.lease_connection("some-site")
        self.assertEqual(caught.exception.code, "credential_refused")
        self.assertIn("403", str(caught.exception))
        self.assertIn("not declared", str(caught.exception))

    def test_an_unreachable_credential_plane_is_reported_as_itself(self):
        with patch.object(MODULE, "_self_container_id", return_value=""), \
             patch.object(MODULE, "urlopen", side_effect=urllib.error.URLError("no route to host")):
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.lease_connection("some-site")
        self.assertEqual(caught.exception.code, "credential_unreachable")
        self.assertIn("no route to host", str(caught.exception))

    def test_error_code_classifies_transient_cdp_failure(self):
        self.assertEqual(MODULE.error_code(RuntimeError("CDP connection returned 502")), "transient_cdp_failure")

    def test_retry_safe_retries_only_transient_failure(self):
        task = {"slug": "task", "state": "active"}
        calls = []

        def flaky():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("CDP 502")
            return "ok"

        with patch.object(MODULE.time, "sleep"), patch.object(MODULE, "journal"):
            self.assertEqual(MODULE.retry_safe(task, "inspect", flaky), "ok")
        self.assertEqual(len(calls), 2)

    def test_numeric_start_requirements_need_records_and_urls(self):
        self.assertEqual(MODULE.parse_start_requirements("5"), {
            "minimum_extractions": 1,
            "minimum_records": 5,
            "required_record_fields": ["text", "url"],
        })

    def test_invalid_start_requirements_have_stable_error(self):
        with self.assertRaises(MODULE.BrowserTaskError) as caught:
            MODULE.parse_start_requirements("{broken")
        self.assertEqual(caught.exception.code, "invalid_requirements")

    def test_task_start_response_has_top_level_identity(self):
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        self.assertIn('"ownership_generation": task["ownership_generation"]', source)

    def test_terminal_task_cannot_transition_again(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            task = {"slug": "task", "state": "accepted", "created_at": 1, "updated_at": 1, "heartbeat_at": 1}
            MODULE.write_task(task)
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.transition(task, "active", "acted")
            self.assertEqual(caught.exception.code, "terminal_task")

    def test_stalled_task_cannot_be_resurrected_by_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            stale = {
                "slug": "task",
                "state": "active",
                "stage": "inspecting",
                "updated_at": 1,
                "heartbeat_at": 1,
                "revision": 0,
                "evidence": {"screenshots": [], "extractions": []},
            }
            current = {**stale, "state": "stalled", "revision": 1}
            MODULE.write_task(current)
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.transition(stale, "active", "inspected", stage="inspecting")
            self.assertEqual(caught.exception.code, "terminal_task")
            self.assertEqual(MODULE.read_task("task")["state"], "stalled")

    def _verify_with_extension(self, extension_session):
        """Runs task_verify against a fake extension status and returns the checks map."""
        from types import SimpleNamespace

        screenshot = b"evidence"
        task = {
            "slug": "task",
            "state": "active",
            "stage": "verifying",
            "created_at": 1,
            "updated_at": 1,
            "heartbeat_at": 1,
            "native_group": {"id": 7, "color": "blue", "label": "task"},
            "ownership_generation": "gen-1",
            "tab_id": 1,
            "evidence": {
                "screenshots": [{"path": "tasks/task/screenshots/final.png", "sha256": MODULE.hashlib.sha256(screenshot).hexdigest()}],
                "extractions": [[{"text": "Story", "url": "https://example.com/1"}]],
            },
            "requirements": {"minimum_extractions": 1, "minimum_records": 1, "required_record_fields": ["text", "url"]},
        }
        page = SimpleNamespace(url="https://example.com/", startswith=lambda prefix: True)
        browser = SimpleNamespace()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(MODULE, "TASKS", Path(directory)), \
                patch.object(MODULE, "task_connection", return_value=(None, browser, page)), \
                patch.object(MODULE, "broker_command", return_value={"ok": True, "session": extension_session}):
            evidence = Path(directory) / "task" / "screenshots" / "final.png"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(screenshot)
            MODULE.write_task(task)
            return MODULE.task_verify("task")

    def test_verify_detects_extension_ownership_drift(self):
        result = self._verify_with_extension(None)
        self.assertFalse(result["checks"]["extension_ownership"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "rejected")

    def test_verify_passes_when_extension_ownership_matches(self):
        result = self._verify_with_extension({
            "tabId": 1,
            "groupId": 7,
            "generation": "gen-1",
            "ownedTabIds": [1],
        })
        self.assertTrue(result["checks"]["extension_ownership"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "accepted")

    def test_tab_census_warns_above_threshold(self):
        with patch.object(MODULE, "broker_command_fast", return_value={"ok": True, "sessions": [
            {"slug": "a", "openTabs": 3},
            {"slug": "b", "openTabs": 2},
        ]}):
            census = MODULE.tab_census()
        self.assertEqual(census["openTabs"], 5)
        self.assertIn("warning", census)
        self.assertIn("browser tabs are open", census["warning"])

    def test_tab_census_silent_below_threshold(self):
        with patch.object(MODULE, "broker_command_fast", return_value={"ok": True, "sessions": [
            {"slug": "a", "openTabs": 1},
        ]}):
            census = MODULE.tab_census()
        self.assertEqual(census["openTabs"], 1)
        self.assertNotIn("warning", census)

    def test_tab_census_survives_broker_failure(self):
        with patch.object(MODULE, "broker_command_fast", side_effect=RuntimeError("down")):
            census = MODULE.tab_census()
        self.assertEqual(census["openTabs"], 0)
        self.assertNotIn("warning", census)

    def test_done_attaches_census_and_pushes_span_when_cli_set(self):
        MODULE._CLI = {"started_at": 1, "argv": ["start", "task-1"], "command": "start", "slug": "task-1"}
        pushed = []

        def fake_span_push(payload):
            pushed.append(payload)

        with patch.object(MODULE, "span_push", side_effect=fake_span_push), \
                patch.object(MODULE, "tab_census", return_value={"sessions": 1, "openTabs": 1, "slugs": ["task-1"]}), \
                patch.object(MODULE, "emit") as fake_emit:
            MODULE.done({"ok": True, "slug": "task-1"}, 0)
        payload, code = fake_emit.call_args.args
        self.assertEqual(code, 0)
        self.assertEqual(payload["tabs"]["openTabs"], 1)
        self.assertNotIn("warning", payload)
        self.assertEqual(len(pushed), 1)
        self.assertEqual(pushed[0]["meta"]["command"], "start")
        self.assertTrue(pushed[0]["status"], "ok")
        MODULE._CLI = {}

    def test_done_attaches_warning_when_census_says_so(self):
        MODULE._CLI = {"started_at": 1, "argv": ["status", "task-1"], "command": "status", "slug": "task-1"}
        with patch.object(MODULE, "span_push"), \
                patch.object(MODULE, "tab_census", return_value={"sessions": 2, "openTabs": 9, "warning": "⚠️ 9 browser tabs are open"}), \
                patch.object(MODULE, "emit") as fake_emit:
            MODULE.done({"ok": True, "slug": "task-1"}, 0)
        payload, _ = fake_emit.call_args.args
        self.assertEqual(payload["tabs"]["openTabs"], 9)
        self.assertEqual(payload["warning"], "⚠️ 9 browser tabs are open")
        MODULE._CLI = {}

    def test_resolve_slug_explicit_name_wins(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(MODULE, "GROUPS", Path(directory)), \
                patch.object(MODULE, "CURRENT", Path(directory) / ".current"), \
                patch.dict(MODULE.os.environ, {"BROWSER42_SESSION": "env-session", "PATH": MODULE.os.environ.get("PATH", "")}):
            slug, source = MODULE.resolve_slug("my-task", return_source=True)
            self.assertEqual((slug, source), ("my-task", "name"))

    def test_resolve_slug_env_is_stable_and_beats_current(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(MODULE, "GROUPS", Path(directory)), \
                patch.object(MODULE, "CURRENT", Path(directory) / ".current"), \
                patch.dict(MODULE.os.environ, {"BROWSER42_SESSION": "wave1-ai", "PATH": MODULE.os.environ.get("PATH", "")}):
            first, source = MODULE.resolve_slug(return_source=True)
            second = MODULE.resolve_slug()
            self.assertEqual((first, source, second), ("wave1-ai", "env", "wave1-ai"))

    def test_resolve_slug_reuses_fresh_current(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / ".current"
            current.write_text("my-session")
            with patch.object(MODULE, "GROUPS", Path(directory)), \
                    patch.object(MODULE, "CURRENT", current), \
                    patch.dict(MODULE.os.environ, {"PATH": MODULE.os.environ.get("PATH", "")}):
                current.touch()
                slug, source = MODULE.resolve_slug(return_source=True)
                self.assertEqual((slug, source), ("my-session", "current"))

    def test_resolve_slug_mints_when_current_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / ".current"
            current.write_text("stale-session")
            old = time.time() - MODULE.SESSION_TTL_SECONDS - 10
            os.utime(current, (old, old))
            with patch.object(MODULE, "GROUPS", Path(directory)), \
                    patch.object(MODULE, "CURRENT", current), \
                    patch.dict(MODULE.os.environ, {"PATH": MODULE.os.environ.get("PATH", "")}):
                slug, source = MODULE.resolve_slug(return_source=True)
                self.assertEqual(source, "minted")
                self.assertTrue(slug.startswith("auto-"))
                self.assertNotEqual(slug, "stale-session")

    def test_session_fresh_clears_group_but_keeps_slug(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / ".current"
            current.write_text("my-session")
            printed = []
            with patch.object(MODULE, "GROUPS", Path(directory)), \
                    patch.object(MODULE, "CURRENT", current), \
                    patch.object(MODULE, "touch"), \
                    patch.object(MODULE, "clear_group") as fake_clear, \
                    patch("builtins.print", side_effect=lambda *a, **k: printed.append(a[0])), \
                    patch.dict(MODULE.os.environ, {"PATH": MODULE.os.environ.get("PATH", "")}):
                MODULE.cmd_session("--fresh")
            slug = printed[0]
            fake_clear.assert_called_once_with("my-session")
            # Session identity NEVER changes within a session — --fresh clears the group,
            # not the slug.
            self.assertEqual(slug, "my-session")


class FakeFrame:
    def __init__(self, url, main=False):
        self.url = url
        self._main = main


class FakePage:
    def __init__(self, frames, main):
        self.frames = frames
        self.main_frame = main


class CaptchaChallengeTests(unittest.TestCase):
    """A human-verification challenge is an IFRAME — and a page that merely NAMES one is not a
    challenge. The rule exists because of a measured mistake: on 2026-10-09 the demo page
    `google.com/recaptcha/api2/demo` matched its own main frame, and the scan read the form."""

    def test_a_turnstile_iframe_is_found(self):
        main = FakeFrame("https://claude.ai/login", main=True)
        widget = FakeFrame("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv/xyz")
        self.assertEqual(MODULE._captcha_frame(FakePage([main, widget], main)), ("turnstile", widget))

    def test_a_demo_page_that_names_recaptcha_is_not_a_challenge(self):
        main = FakeFrame("https://www.google.com/recaptcha/api2/demo", main=True)
        self.assertEqual(MODULE._captcha_frame(FakePage([main], main)), (None, None))

    def test_the_recaptcha_anchor_iframe_is_found(self):
        main = FakeFrame("https://www.google.com/recaptcha/api2/demo", main=True)
        widget = FakeFrame("https://www.google.com/recaptcha/api2/anchor?ar=1&k=6Le-wvkSAAAAA")
        self.assertEqual(MODULE._captcha_frame(FakePage([main, widget], main)), ("recaptcha", widget))

    def test_cloudflares_interstitial_is_the_challenge_itself(self):
        main = FakeFrame("https://site.example/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1", main=True)
        self.assertEqual(MODULE._captcha_frame(FakePage([main], main)), ("turnstile", main))

    def test_a_page_without_a_challenge_says_so(self):
        main = FakeFrame("http://console.localhost:8080/", main=True)
        self.assertEqual(MODULE._captcha_frame(FakePage([main], main)), (None, None))

    def test_an_offset_only_matters_inside_a_frame(self):
        main = FakeFrame("https://app.example/", main=True)
        self.assertEqual(MODULE._captcha_offset(FakePage([main], main), main), (0.0, 0.0))


class AwaitConditionTests(unittest.TestCase):
    """`await` is the human handoff, so its ANSWERS are the contract: each condition must say what it
    saw, and a typo must fail as a typo rather than waiting out its budget for a typo. Written after
    the WhatsApp pairing of 2026-10-14, where one call with eight candidates answered which markers
    the pairing screen has and which it does not."""

    class Locator:
        def __init__(self, count, visible):
            self._count, self._visible = count, visible

        def count(self):
            return self._count

        @property
        def first(self):
            return self

        def is_visible(self):
            return self._visible

    class ProbePage:
        url = "https://web.whatsapp.com/"

        def __init__(self, nodes=0, visible=False, stored=None, body="Scan the QR code"):
            self._nodes, self._visible, self._stored, self._body = nodes, visible, stored, body

        def locator(self, _css):
            return AwaitConditionTests.Locator(self._nodes, self._visible)

        def evaluate(self, _js, arg=None):
            return self._stored if arg is not None else self._body

    def probe(self, condition, **page):
        return MODULE._await_probe(self.ProbePage(**page), condition)

    def test_selector_needs_present_and_visible(self):
        self.assertFalse(self.probe("selector:#pane-side")["met"])
        self.assertTrue(self.probe("selector:#pane-side", nodes=1, visible=True)["met"])
        # present but hidden is NOT the element the caller meant
        self.assertFalse(self.probe("selector:#pane-side", nodes=1, visible=False)["met"])
        self.assertEqual(self.probe("selector:#pane-side", nodes=2, visible=True)["seen"], "2 node(s), visible")

    def test_gone_is_the_pairing_screens_own_signal(self):
        self.assertTrue(self.probe("gone:[data-ref]")["met"])                 # absent
        self.assertFalse(self.probe("gone:[data-ref]", nodes=1, visible=True)["met"])

    def test_text_and_notext_read_the_visible_text(self):
        self.assertTrue(self.probe("text:Scan the QR code")["met"])
        self.assertFalse(self.probe("notext:Scan the QR code")["met"])
        self.assertTrue(self.probe("notext:Scan the QR code", body="Chat list")["met"])
        # "the sign-in screen is gone" is the transition a QR pairing is watched for
        self.assertTrue(self.probe("notext:Scan the QR code", body="")["met"])

    def test_url_and_storage(self):
        self.assertTrue(self.probe("url:web.whatsapp.com")["met"])
        self.assertFalse(self.probe("url:accounts.google.com")["met"])
        self.assertTrue(self.probe("storage:last-wid-md", stored="972@c.us_abc")["met"])
        self.assertFalse(self.probe("storage:last-wid-md", stored=None)["met"])

    def test_a_typo_fails_now_and_says_what_is_allowed(self):
        with self.assertRaises(MODULE.BrowserTaskError) as caught:
            self.probe("selectr:#pane-side")
        self.assertEqual(caught.exception.code, "unknown_condition")
        self.assertIn("selector", str(caught.exception))
        with self.assertRaises(MODULE.BrowserTaskError) as caught:
            self.probe("selector:")
        self.assertEqual(caught.exception.code, "empty_condition")

    def test_a_page_that_throws_is_reported_not_crashed(self):
        class Angry(self.ProbePage):
            def locator(self, _css):
                raise RuntimeError("detached target")

        probe = MODULE._await_probe(Angry(), "selector:#pane-side")
        self.assertFalse(probe["met"])
        self.assertIn("detached target", probe["seen"])


class StitchTests(unittest.TestCase):
    """`read`'s join of a walk's steps (`_stitch`)."""

    def test_a_whole_page_read_at_every_step_is_kept_once(self):
        # an ordinary page: each step's innerText is the whole document, longer than the window
        page = "\n".join(f"שורה {i} של הדף, עם מספיק טקסט כדי להיות ארוכה" for i in range(300))
        self.assertGreater(len(page), 4000)
        acc = ""
        for _ in range(5):
            acc = MODULE._stitch(acc, page)
        self.assertEqual(acc, page)

    ROWS = "\n".join(f"שורה {i} של הדף, עם מספיק טקסט כדי להיות ארוכה" for i in range(300))

    def test_a_page_that_changes_a_little_between_steps_is_kept_once(self):
        # the document read at every step, a slider's line different each time (bina-solutions.co.il
        # came back six times before this); the newest reading is the one kept
        acc = ""
        for step in range(6):
            acc = MODULE._stitch(acc, f"תפריט\nבית\nאודות\n{self.ROWS}\nהשקופית הנוכחית: {step}", document=True)
        self.assertEqual(acc.count("שורה 7 של הדף"), 1)
        self.assertTrue(acc.startswith("תפריט\nבית\nאודות\n") and acc.endswith("השקופית הנוכחית: 5"))

    def test_a_page_whose_first_line_changes_is_kept_once(self):
        # a clock or a countdown at the very top of the document
        acc = ""
        for step in range(6):
            acc = MODULE._stitch(acc, f"00:00:{step:02d} עד ההשקה\n{self.ROWS}", document=True)
        self.assertEqual(acc.count("שורה 7 של הדף"), 1)

    def test_a_page_that_loads_more_as_it_is_scrolled_keeps_the_newer_reading(self):
        first = f"שעון 1\n{self.ROWS}"
        later = f"שעון 2\n{self.ROWS}\n" + "\n".join(f"פריט שנטען {i}" for i in range(20))
        acc = MODULE._stitch(MODULE._stitch("", first, document=True), later, document=True)
        self.assertEqual((acc.count("שורה 7 של הדף"), acc.count("פריט שנטען 19")), (1, 1))

    def test_an_inner_list_under_a_pinned_header_loses_no_row(self):
        # a scroller that shows the same long header at every step: a virtualised list read in windows
        # of 30 rows, 24 rows apart — every row seen is kept (the header may repeat)
        header = "כותרת קבועה של הרשימה " * 10
        self.assertGreater(len(header), 200)
        acc = ""
        for start in range(0, 101, 24):
            window = "\n".join(f"row {i}: something said in the chat that runs on" for i in range(start, start + 30))
            acc = MODULE._stitch(acc, f"{header}\n{window}")
        rows = {line.split(":")[0] for line in acc.splitlines() if line.startswith("row ")}
        self.assertEqual(rows, {f"row {i}" for i in range(126)})

    def test_too_few_lines_are_never_the_same_reading(self):
        self.assertFalse(MODULE._same_reading("a\nb\nc", "a\nb\nc\nd"))
        self.assertTrue(MODULE._same_reading("a\nb\nc\nd\ne\nf\ng\nh\ni\nj", "a\nb\nc\nd\ne\nf\ng\nh\ni\nX"))

    def test_a_virtualised_list_scrolled_past_its_top_is_still_joined_by_overlap(self):
        first = "\n".join(f"message {i}: something said in the chat that runs on" for i in range(0, 60))
        second = "\n".join(f"message {i}: something said in the chat that runs on" for i in range(40, 100))
        acc = MODULE._stitch(first, second)
        self.assertEqual([line.split(":")[0] for line in acc.splitlines()], [f"message {i}" for i in range(100)])

    def test_a_step_that_holds_everything_so_far_replaces_it(self):
        self.assertEqual(MODULE._stitch("the head", "the head, and the rest"), "the head, and the rest")

    def test_overlapping_steps_join_at_their_overlap(self):
        self.assertEqual(MODULE._stitch("a\nb\nc\nd", "c\nd\ne\nf"), "a\nb\nc\nd\ne\nf")
        self.assertEqual(MODULE._stitch("a\nb", "x\ny"), "a\nb\nx\ny")

    def test_a_repeated_line_in_the_new_part_is_kept(self):
        self.assertEqual(MODULE._stitch("hello\nworld", "world\nhello\nhello"), "hello\nworld\nhello\nhello")


class TotpTests(unittest.TestCase):
    """The second factor: the plane mints, the runner types, nobody holds the secret."""

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    def test_a_missing_secret_is_a_named_refusal_with_the_field_and_the_handoff(self):
        missing = urllib.error.HTTPError(
            "http://connections/api/totp/browser42-totp-facebook", 404, "Not Found", {},
            io.BytesIO(b'{"error": "no TOTP secret stored", "field": "BROWSER42_LOGIN_FACEBOOK_TOTP"}'))
        with patch.object(MODULE, "_self_container_id", return_value=""), \
             patch.object(MODULE, "urlopen", side_effect=missing), \
             patch.dict(os.environ, {"AUTH_PROTOCOL": "https", "CONSOLE_BASE_URL": "console.example.test"}):
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.totp_code("facebook", "task-1")
        self.assertEqual(caught.exception.code, "needs_totp_secret")
        said = str(caught.exception)
        self.assertIn("browser42-totp-facebook", said)
        self.assertIn("BROWSER42_LOGIN_FACEBOOK_TOTP", said)
        self.assertIn("https://console.example.test/a/browser42/view/", said)

    def test_a_minted_code_comes_back_and_a_refusal_is_reported_as_itself(self):
        sent = {}

        def fake_urlopen(request, timeout):
            sent["url"] = request.full_url
            sent["headers"] = dict(request.header_items())
            return self.Response({"id": "browser42-totp-facebook", "code": "123456",
                                  "next": "654321", "expires_in": 7})

        with patch.object(MODULE, "_self_container_id", return_value="ab" * 32), \
             patch.object(MODULE, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(MODULE.totp_code("facebook", "task-1"), "123456")
        self.assertIn("/api/totp/browser42-totp-facebook?service=", sent["url"])
        self.assertEqual(sent["headers"].get("X-conn-container"), "ab" * 32)
        refused = urllib.error.HTTPError("http://connections/api/totp/x", 403, "Forbidden", {},
                                         io.BytesIO(b'{"error": "not declared", "decision": "refuse"}'))
        with patch.object(MODULE, "_self_container_id", return_value=""), \
             patch.object(MODULE, "urlopen", side_effect=refused):
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.totp_code("facebook", "task-1")
        self.assertEqual(caught.exception.code, "totp_refused")
        self.assertIn("not declared", str(caught.exception))

    def test_the_code_field_is_seen_before_a_vanished_form_counts_as_signed_in(self):
        class Page:
            def __init__(self, visible):
                self.visible = visible

            def locator(self, css):
                page = self

                class Located:
                    def count(self):
                        return 0                          # the password field is gone either way

                    def is_visible(self):
                        return css in page.visible

                located = Located()
                located.first = located
                return located

        self.assertEqual(MODULE.await_login_or_otp(Page({"input[name=totpPin]"}), "input[name=pass]", grace_ms=0),
                         "input[name=totpPin]")
        self.assertIsNone(MODULE.await_login_or_otp(Page(set()), "input[name=pass]", grace_ms=0))

    def test_the_handoff_link_is_the_console_view_of_the_browser(self):
        with patch.dict(os.environ, {"AUTH_PROTOCOL": "", "CONSOLE_BASE_URL": ""}):
            self.assertEqual(MODULE.handoff_link("task-1"), "http://console.localhost/a/browser42/view/")

    @staticmethod
    def _page(visible, form_present=False):
        class Page:
            def locator(self, css):
                class Located:
                    def count(self_inner):
                        return 1 if form_present else 0

                    def is_visible(self_inner):
                        return css in visible

                located = Located()
                located.first = located
                return located

        return Page()

    def test_a_code_field_on_a_page_that_still_has_the_password_form_is_not_typed_into(self):
        # The login page's own `input[name=code]` (a promo box, a phone field) must never get a code:
        # with the password form present the OTP selectors are not even read, and the wait runs out.
        page = self._page({"input[name=code]"}, form_present=True)
        with self.assertRaises(TimeoutError):
            MODULE.await_login_or_otp(page, "input[name=pass]", timeout_ms=0, grace_ms=0)

    def test_a_rejected_code_is_not_a_success(self):
        class Field:
            def wait_for(self, **_):
                return None                               # the POST went out: the node detached

        # A rejected code re-renders the same prompt with a fresh field: that is the refusal.
        with self.assertRaises(MODULE.BrowserTaskError) as caught:
            MODULE.second_factor_outcome(self._page({"input[name=approvals_code]"}), Field(),
                                         "input[name=pass]", "facebook", grace_ms=0)
        self.assertEqual(caught.exception.code, "totp_rejected")
        self.assertIn("again", str(caught.exception))
        # No form and no code field after the detach is the accepted sign-in.
        self.assertIsNone(MODULE.second_factor_outcome(self._page(set()), Field(), "input[name=pass]",
                                                       "facebook", grace_ms=0))

    def test_a_plane_without_the_route_is_named_and_not_blamed_on_the_owner(self):
        old_image = urllib.error.HTTPError("http://connections/api/totp/x", 404, "Not Found", {},
                                           io.BytesIO(b"<html><title>404 Not Found</title></html>"))
        with patch.object(MODULE, "_self_container_id", return_value=""), \
             patch.object(MODULE, "urlopen", side_effect=old_image):
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.totp_code("facebook", "task-1")
        self.assertEqual(caught.exception.code, "totp_unavailable")
        self.assertIn("rebuild", str(caught.exception))
        not_rendered = urllib.error.HTTPError("http://connections/api/totp/x", 404, "Not Found", {},
                                              io.BytesIO(b'{"error": "not a totp connection"}'))
        with patch.object(MODULE, "_self_container_id", return_value=""), \
             patch.object(MODULE, "urlopen", side_effect=not_rendered):
            with self.assertRaises(MODULE.BrowserTaskError) as caught:
                MODULE.totp_code("facebook", "task-1")
        self.assertEqual(caught.exception.code, "totp_unavailable")
        self.assertIn("reconcile", str(caught.exception))


class LoadErrorTests(unittest.TestCase):
    """A tab that could not load its URL is named with its error (DGO-913), and only that tab."""

    class Session:
        def __init__(self, target, tried, code):
            self.target, self.tried, self.code, self.detached = target, tried, code, False

        def send(self, method, params=None):
            if method == "Target.getTargetInfo":
                return {"targetInfo": {"targetId": self.target, "url": self.tried}}
            return {"result": {"value": self.code}}

        def detach(self):
            self.detached = True

    def browser(self, *pages):
        context = types.SimpleNamespace(pages=[], new_cdp_session=lambda page: page.session)
        for i, (url, tried, code) in enumerate(pages):
            context.pages.append(types.SimpleNamespace(url=url, context=context, session=self.Session(f"T{i}", tried, code)))
        return types.SimpleNamespace(contexts=[context]), context

    def test_an_error_page_open_before_the_start_is_not_its_own(self):
        b, _ = self.browser(("chrome-error://chromewebdata/", "https://example.com/", "ERR_INTERNET_DISCONNECTED"),
                            ("chrome-error://chromewebdata/", "https://example.com/", "DNS_PROBE_FINISHED_NXDOMAIN"))
        self.assertEqual(MODULE.load_error(b, "https://example.com", {"T0"}), "DNS_PROBE_FINISHED_NXDOMAIN")
        self.assertEqual(MODULE.load_error(b, "https://example.com", {"T0", "T1"}), "")

    def test_same_url_as_chrome_writes_it(self):
        self.assertTrue(MODULE.same_url("https://Example.COM", "https://example.com/"))
        self.assertTrue(MODULE.same_url("https://example.com:443/a/", "https://example.com/a"))
        self.assertTrue(MODULE.same_url("http://example.com:80?q=1", "http://example.com/?q=1"))
        self.assertTrue(MODULE.same_url("https://דוגמה.ישראל/דף", "https://xn--6dbbec0c.xn--4dbrk0ce/%D7%93%D7%A3"))
        self.assertFalse(MODULE.same_url("https://example.com/a", "https://example.com/b"))
        self.assertFalse(MODULE.same_url("http://example.com/", "https://example.com/"))
        self.assertFalse(MODULE.same_url("https://example.com:8443/", "https://example.com/"))
        self.assertFalse(MODULE.same_url("https://example.com:99999/", "https://example.com/"))
        self.assertTrue(MODULE.same_url("https://example.com/s?q=שלום עולם", "https://example.com/s?q=%D7%A9%D7%9C%D7%95%D7%9D%20%D7%A2%D7%95%D7%9C%D7%9D"))
        self.assertTrue(MODULE.same_url("https://example.com/%d7%93", "https://example.com/%D7%93"))

    def test_a_page_that_cannot_be_read_does_not_hide_the_error(self):
        b, context = self.browser(("chrome-error://chromewebdata/", "https://example.com/", "ERR_X"),
                                  ("chrome-error://chromewebdata/", "https://example.com/", "DNS_PROBE_FINISHED_NXDOMAIN"))

        def broken(method, params=None):
            raise RuntimeError("target closed")
        context.pages[0].session.send = broken
        self.assertEqual(MODULE.load_error(b, "https://example.com"), "DNS_PROBE_FINISHED_NXDOMAIN")
        self.assertTrue(context.pages[0].session.detached)

    def test_an_unreadable_tab_list_is_unknown_not_empty(self):
        with patch.object(MODULE, "urlopen", side_effect=urllib.error.URLError("asleep")):
            self.assertIsNone(MODULE.page_targets("https://example.com"))

    def test_tab_list_is_read_twice_and_joined(self):
        reads = iter([[{"type": "page", "id": "A", "url": "https://example.com/"}],
                      [{"type": "page", "id": "B", "url": "https://example.com/"},
                       {"type": "page", "id": "C", "url": "https://other.example/"}]])

        def fake_urlopen(url, timeout=None):
            return io.BytesIO(json.dumps(next(reads)).encode())
        with patch.object(MODULE, "urlopen", side_effect=fake_urlopen), patch.object(MODULE.time, "sleep"):
            self.assertEqual(MODULE.page_targets("https://example.com"), {"A", "B"})

    def test_error_page_for_the_url_names_its_error(self):
        b, context = self.browser(("https://www.google.com/", "https://www.google.com/", ""),
                                  ("chrome-error://chromewebdata/", "https://example.com/", "DNS_PROBE_FINISHED_NXDOMAIN"))
        self.assertEqual(MODULE.load_error(b, "https://example.com"), "DNS_PROBE_FINISHED_NXDOMAIN")
        self.assertTrue(context.pages[1].session.detached)

    def test_error_page_for_another_url_is_not_ours(self):
        b, _ = self.browser(("chrome-error://chromewebdata/", "https://other.example/", "ERR_CONNECTION_REFUSED"))
        self.assertEqual(MODULE.load_error(b, "https://example.com"), "")

    def test_loaded_pages_have_no_error(self):
        b, _ = self.browser(("https://example.com/", "https://example.com/", ""))
        self.assertEqual(MODULE.load_error(b, "https://example.com"), "")

    def test_error_page_without_a_code_still_fails(self):
        b, _ = self.browser(("chrome-error://chromewebdata/", "https://example.com/", ""))
        self.assertEqual(MODULE.load_error(b, "https://example.com/"), "the browser's error page")

    def test_a_broken_scan_is_no_error(self):
        self.assertEqual(MODULE.load_error(types.SimpleNamespace(contexts=None), "https://example.com"), "")


if __name__ == "__main__":
    unittest.main()