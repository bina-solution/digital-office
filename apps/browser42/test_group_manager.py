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


if __name__ == "__main__":
    unittest.main()