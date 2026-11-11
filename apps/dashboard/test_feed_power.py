"""test_feed_power.py — a laptop's last word on sleep, for the office that posts to the group (feed.power_brief, DGO-1357).

    python3 apps/dashboard/test_feed_power.py

What is asked: the power agent's record (packaging/macos/power-agent.py status.json) is cut to what group.asleep judges
— when it was written, whether the OWNER'S POLICY lets the laptop sleep when locked or closed (`wanted`, never what
macOS happens to do), the guards that released it, and its battery — and nothing else of it leaves the machine; an
office with no power agent, or a record that cannot be read, gives None, so no data/power.json is written there.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402

STATUS = {"version": 1, "platform": "macos", "host": "a-mac", "updated_at": 1793888748, "agent_pid": 77,
          "engine_running": True, "power": {"source": "battery", "percent": 14, "state": "discharging"},
          "lid": {"closed": False, "causes_sleep": True}, "screen_locked": True, "sleep_disabled": False,
          "effective": {"lock": "sleep", "lid": "sleep", "source": "battery", "guards": ["battery below 15%"]},
          "wanted": {"lock": "sleep", "lid": "sleep"}, "notes": ["x"], "setup": ["sudo …"],
          "events": [{"at": "2026-11-01 11:09:37", "kind": "Sleep", "cause": "lid-closed", "on": "battery"}]}


class PowerBriefTest(unittest.TestCase):
    def write(self, doc):
        path = os.path.join(tempfile.mkdtemp(), "status.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))
        return path

    def test_the_word_is_what_the_judgement_needs_and_nothing_else(self):
        self.assertEqual(feed.power_brief(self.write(STATUS)),
                         {"at": 1793888748, "lock": "sleep", "lid": "sleep", "guards": ["battery below 15%"],
                          "source": "battery", "percent": 14})

    def test_the_policy_is_the_owners_not_what_macos_happens_to_do(self):
        # SleepDisabled cleared outside the agent: macOS would sleep on a closed lid, the owner's policy says run
        doc = dict(STATUS, sleep_disabled=False, effective={"lock": "run", "lid": "sleep", "guards": []},
                   wanted={"lock": "run", "lid": "run"})
        self.assertEqual(feed.power_brief(self.write(doc))["lid"], "run")

    def test_no_agent_or_no_record_is_no_word(self):
        self.assertIsNone(feed.power_brief(os.path.join(tempfile.mkdtemp(), "absent.json")))
        self.assertIsNone(feed.power_brief(self.write("{half")))
        self.assertIsNone(feed.power_brief(self.write([1, 2])))
        self.assertIsNone(feed.power_brief(self.write({"effective": {"lock": "run"}})))   # never written by the agent
        self.assertIsNone(feed.power_brief(self.write(dict(STATUS, updated_at="soon"))))
        self.assertEqual(feed.power_brief(self.write(dict(STATUS, effective={"guards": 5})))["guards"], [])

    def test_the_word_is_written_whole_beside_the_state(self):
        out = os.path.join(tempfile.mkdtemp(), "power.json")
        feed.write(feed.power_brief(self.write(STATUS)), out)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["guards"], ["battery below 15%"])
        self.assertFalse(os.path.exists(out + ".tmp"))


if __name__ == "__main__":
    unittest.main()
