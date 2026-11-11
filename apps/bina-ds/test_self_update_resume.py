#!/usr/bin/env python3
"""After a bina-ds update, no conversation is told to continue by itself (the owner's rule; issues/after-every-bina-ds-
update-the-harness-tells-recent-sessions-to-continue-and-re-arm-their-goals.yaml).

Runs the REAL `resume_sessions` and `RESUME_MODE` of apps/bina-ds/self-update.sh in bash, with `bbox`, `curl`,
`notify` and `log` stubbed: by default the cut conversations are named in one notice and none is sent a turn; only
an explicit BINA_DS_SELF_UPDATE_RESUME=send writes into them — and even then never «continue without approval»
and never «re-arm your goal».

    python3 apps/bina-ds/test_self_update_resume.py
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("self-update.sh")
TEXT = SCRIPT.read_text(encoding="utf-8")


def piece():
    """The mode line and the function, as the script has them."""
    mode = re.search(r"^RESUME_MODE=.*$", TEXT, re.M).group(0)
    start = TEXT.index("resume_sessions() {")
    end = TEXT.index("\n}\n", start) + 3
    return mode + "\n" + TEXT[start:end]


class Resume(unittest.TestCase):
    def run_it(self, env_mode=None):
        d = pathlib.Path(tempfile.mkdtemp())
        events = d / "events"
        (d / "bbox").write_text(f'#!/bin/sh\nprintf "SEND %s\\n" "$*" >> "{events}"\n')
        os.chmod(d / "bbox", 0o755)
        harness = (f'set -euo pipefail\nREPO="{d}"\nLOG="{d}/log"\n'
                   f'log() {{ printf "LOG %s\\n" "$*" >> "{events}"; }}\n'
                   f'notify() {{ printf "NOTIFY %s|%s|%s|%s|%s\\n" "$1" "$2" "$3" "${{4:-self-update}}" "${{5:-}}" >> "{events}"; }}\n'
                   'curl() { return 0; }\nsleep() { :; }\n' + piece() +
                   '\nresume_sessions "$(printf \'session-aaa\\nsession-bbb\\n\')"\n')   # live_sessions\'s shape
        env = {k: v for k, v in os.environ.items() if k != "BINA_DS_SELF_UPDATE_RESUME"}
        if env_mode is not None:
            env["BINA_DS_SELF_UPDATE_RESUME"] = env_mode
        r = subprocess.run(["bash", "-c", harness], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return events.read_text(encoding="utf-8") if events.exists() else ""

    def test_by_default_nobody_is_sent_a_turn_and_every_cut_one_is_named(self):
        out = self.run_it()
        self.assertNotIn("SEND", out)
        notices = [ln for ln in out.splitlines() if ln.startswith("NOTIFY")]
        self.assertEqual(len(notices), 1, out)
        self.assertIn("session-aaa", notices[0])
        self.assertIn("session-bbb", notices[0])
        self.assertIn("אף אחת לא קיבלה הוראה להמשיך", notices[0])

    def test_the_cut_list_keeps_its_own_notice_and_links_each_conversation(self):
        for mode in (None, "send"):
            notices = [ln.split("|") for ln in self.run_it(mode).splitlines() if ln.startswith("NOTIFY")]
            self.assertEqual(len(notices), 1, notices)
            _, _, body, key, link = notices[0]
            # the door's «updated and healthy» follows on key `self-update`; on the same key it replaces this one
            self.assertNotEqual(key, "self-update")
            self.assertTrue(key.startswith("self-update-cut-"), key)
            self.assertEqual(link, "/go/bina?s=session-aaa")      # the ONE form a person is given (G95)
            for sid in ("session-aaa", "session-bbb"):
                self.assertIn("/go/bina?s=" + sid, body)
            self.assertNotIn("#/m/", body + link)

    def test_the_door_notice_after_the_cut_list_uses_the_door_key(self):
        # the apply's own success notice must not take a key argument: it is the one that may be replaced
        line = next(ln for ln in TEXT.splitlines() if "בינה עודכנה והופעלה מחדש" in ln)
        self.assertNotIn("self-update-cut", line)
        self.assertLess(TEXT.index('resume_sessions "${live}"'), TEXT.index(line))

    def test_the_helper_is_handed_the_mode_so_send_can_be_said(self):
        run = TEXT[TEXT.index('docker run -d --rm --name "${HELPER}"'):]
        run = run[: run.index("--entrypoint bash")]
        self.assertIn('-e BINA_DS_SELF_UPDATE_RESUME="${RESUME_MODE}"', run)

    def test_an_unknown_mode_is_the_default_not_a_send(self):
        self.assertNotIn("SEND", self.run_it("yes-please"))

    def test_only_an_explicit_send_writes_in_and_never_says_continue_or_resume_a_goal(self):
        out = self.run_it("send")
        sends = [ln for ln in out.splitlines() if ln.startswith("SEND")]
        self.assertEqual(len(sends), 2, out)
        for s in sends:
            self.assertIn("agent send", s)
            self.assertNotIn("ואל תמתין לאישור", s)
            self.assertNotIn("goal", s.split("אל תמשיך")[0])          # the only goal word is the «do not re-arm»
            self.assertNotIn("resume", s)
            self.assertIn("חכה להוראה", s)
        self.assertNotIn("ממשיכות לבד", out)

    def test_the_script_holds_no_self_continue_sentence_anywhere(self):
        for said in ("ואל תמתין לאישור", "goal ${id} resume", "ממשיכות לבד", "להמשיך מאליהן",
                     "חוזרות מעצמן", "come back through resume_sessions", "told to carry on (`bbox agent send`)"):
            self.assertNotIn(said, TEXT, said)
        host = (SCRIPT.parents[2] / "scripts/app-update.sh").read_text(encoding="utf-8")
        self.assertNotIn("continues whoever was mid-turn", host)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=1).result.wasSuccessful() else 1)
