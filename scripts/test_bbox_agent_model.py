#!/usr/bin/env python3
"""test_bbox_agent_model — `bbox agent model <id> --set` is that session's model; the CLI says what became of the
office's default model, and `show` names the model the next turn runs on (DGO-1731).

    python3 scripts/test_bbox_agent_model.py      (here, not beside scripts/bbox_agent: G72 runs scripts/test_*.py)

The harness's selectModel also rewrites the office's default model. A current agent door puts it back unless
`--default`, and answers `default` (kept / restored / changed + why / unknown + why) with `office_default`; an older
door says nothing, so the CLI reads the default before and after and says it moved. Measured on the HP 2026-11-11:
`show` named the last turn's model after a set, so a set that had taken looked as if it had not. Python 3.9,
standard library only; no network.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bbox_agent import cli, client  # noqa: E402

SID = "session-82633554-c977-42d9-8848-d7840f295836"
DELL4B = {"provider": "dgo-ollama-portable-ubuntu", "model": "qwen3:4b-instruct-2507-q4_K_M"}
DELL17 = {"provider": "dgo-ollama-portable-ubuntu", "model": "qwen3:1.7b"}


class FakeDoor:
    """An agent door: the office's default model, and what its model route answers."""

    def __init__(self, answer_extra: dict, default_after: dict, default_before: dict = DELL17):
        self.default = dict(default_before)
        self.answer_extra, self.default_after = answer_extra, default_after
        self.posts = []

    def call(self, method, path, body=None):
        if method == "GET" and path == "/v1/models":
            return {"default": self.default, "groups": []}
        if method == "POST" and path == f"/v1/sessions/{SID}/model":
            self.posts.append(body)
            self.default = dict(self.default_after)
            return {"id": SID, "provider": body["provider"], "model": body["model"], "effort": body.get("effort"),
                    **self.answer_extra}
        raise AssertionError(f"unexpected call {method} {path}")


def run_set(door: FakeDoor, *extra: str) -> str:
    p = argparse.ArgumentParser()
    p.add_argument("id"); p.add_argument("--set"); p.add_argument("--default", action="store_true"); p.add_argument("--json", action="store_true")
    a = p.parse_args([SID, "--set", "dgo-ollama-portable-ubuntu/qwen3:4b-instruct-2507-q4_K_M@off", *extra])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_model(door, a)
    assert rc == 0
    return buf.getvalue()


class SetKeepsTheOfficeDefault(unittest.TestCase):
    def test_a_current_door_that_put_it_back(self):
        door = FakeDoor({"default": "restored", "office_default": DELL17}, DELL17)
        o = run_set(door)
        self.assertNotIn("default", door.posts[0], "no --default: the door is not asked to keep the new default")
        self.assertIn(f"{SID}: dgo-ollama-portable-ubuntu/qwen3:4b-instruct-2507-q4_K_M@off", o)
        self.assertIn("the office's default model stays dgo-ollama-portable-ubuntu/qwen3:1.7b", o)

    def test_default_asked_for(self):
        door = FakeDoor({"default": "changed", "why": "asked"}, DELL4B)
        o = run_set(door, "--default")
        self.assertIs(door.posts[0].get("default"), True)
        self.assertIn("is now dgo-ollama-portable-ubuntu/qwen3:4b-instruct-2507-q4_K_M too (--default)", o)

    def test_a_door_that_could_not_put_it_back_says_why(self):
        door = FakeDoor({"default": "changed", "why": "the settings lock was not taken (EEXIST)", "office_default": DELL4B}, DELL4B)
        o = run_set(door)
        self.assertIn("is dgo-ollama-portable-ubuntu/qwen3:4b-instruct-2507-q4_K_M (was dgo-ollama-portable-ubuntu/qwen3:1.7b)", o)
        self.assertIn("the settings lock was not taken", o)
        self.assertNotIn("stays", o)

    def test_restored_says_it_was_put_back(self):
        door = FakeDoor({"default": "restored", "office_default": DELL17}, DELL17)
        self.assertIn("stays dgo-ollama-portable-ubuntu/qwen3:1.7b (the harness moved it to this selection; put back)", run_set(door))

    def test_somebody_elses_choice_is_said_never_kept(self):
        z = {"provider": "deepseek-official", "model": "deepseek-v4-pro"}
        why = "the default names deepseek-official/deepseek-v4-pro, not this selection; left as it is"
        o = run_set(FakeDoor({"default": "changed", "why": why, "office_default": z}, z))
        self.assertIn("is deepseek-official/deepseek-v4-pro (was dgo-ollama-portable-ubuntu/qwen3:1.7b): " + why, o)
        self.assertNotIn("stays", o)

    def test_the_door_answer_is_preferred_to_a_second_catalog_read(self):
        class NoSecondRead(FakeDoor):
            reads = 0
            def call(self, method, path, body=None):
                if path == "/v1/models":
                    self.reads += 1
                return super().call(method, path, body)
        door = NoSecondRead({"default": "kept", "office_default": DELL17}, DELL17)
        o = run_set(door)
        self.assertEqual(door.reads, 1, "the default is read once, before; after, the door's own answer says it")
        self.assertIn("stays dgo-ollama-portable-ubuntu/qwen3:1.7b", o)

    def test_unknown_is_said(self):
        o = run_set(FakeDoor({"default": "unknown", "why": "settings.yaml could not be read before the selection"}, DELL17))
        self.assertIn("could not be checked: settings.yaml could not be read before the selection", o)

    def test_default_without_set_is_refused(self):
        p = argparse.ArgumentParser()
        p.add_argument("id"); p.add_argument("--set"); p.add_argument("--default", action="store_true"); p.add_argument("--json", action="store_true")
        with self.assertRaises(client.AgentError):
            cli.cmd_model(FakeDoor({}, DELL17), p.parse_args([SID, "--default"]))

    def test_an_older_door_moves_it_and_the_cli_says_so(self):
        door = FakeDoor({}, DELL4B)      # the HP's door today: no `default` in its answer
        o = run_set(door)
        self.assertIn("this office's agent door is older", o)
        self.assertIn("dgo-ollama-portable-ubuntu/qwen3:1.7b → dgo-ollama-portable-ubuntu/qwen3:4b-instruct-2507-q4_K_M", o)

    def test_an_older_door_that_did_not_move_it_says_nothing_more(self):
        door = FakeDoor({}, DELL17)
        o = run_set(door)
        self.assertEqual(o.strip().count("\n"), 0, o)

    def test_an_unreadable_catalog_never_fails_the_set(self):
        class Unread(FakeDoor):
            def call(self, method, path, body=None):
                if path == "/v1/models":
                    raise client.AgentError("models: not served", 1)
                return super().call(method, path, body)
        o = run_set(Unread({}, DELL4B))
        self.assertIn(f"{SID}: ", o)


class ShowNamesTheNextTurnsModel(unittest.TestCase):
    def test_a_selection_since_the_last_turn_wins(self):
        s = {"sessionId": SID, "projections": {"values": {"modelSelection": {
            "lastUsed": {"provider": "deepseek-official", "model": "deepseek-flash"}, "next": DELL4B}}}}
        self.assertEqual(client.harness_summary(s)["model"], DELL4B)

    def test_no_selection_names_the_last_used(self):
        last = {"provider": "deepseek-official", "model": "deepseek-flash"}
        s = {"sessionId": SID, "projections": {"values": {"modelSelection": {"lastUsed": last}}}}
        self.assertEqual(client.harness_summary(s)["model"], last)

    def test_nothing_names_nothing(self):
        self.assertIsNone(client.harness_summary({"sessionId": SID})["model"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
