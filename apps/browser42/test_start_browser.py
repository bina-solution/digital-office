"""start-browser.sh never copies the profile, counts its cookies, or waits on a copy to stop (DGO-2188).

Until 2026-11-24 its §4h — the «profile guard» — copied the cookie store into /tmp to count it, copied the whole
profile to data/browser42/profile-snapshot every 30 minutes, at every sleep and at every stop, and restored that copy
at boot. On 2026-11-20 the HP's C: answered I/O errors under it and the office browser was down for four days. The
script is a boot script that cannot be run outside its image, so what is pinned here is its text: the code lines (never
the comments, which tell the history) hold none of the guard's verbs, and a stop does one thing.

    python3 -m unittest apps/browser42/test_start_browser.py
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

SCRIPT = pathlib.Path(__file__).with_name("start-browser.sh")


def code_lines() -> list:
    """The script without its comment lines and its here-documents' prose — what bash runs."""
    return [line for line in SCRIPT.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


class NoProfileCopy(unittest.TestCase):
    def test_it_parses(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash here")
        # On Windows the first `bash` on PATH can be System32's — WSL's launcher: it would open a session in the
        # live guest and hand it a C:\ path it cannot read (the second reader, DGO-2188). Never from a test.
        if os.name == "nt" and os.path.normcase(bash).startswith(os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))):
            self.skipTest("the only bash here is WSL's launcher")
        done = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_nothing_copies_the_profile_or_its_cookie_store(self):
        code = "\n".join(code_lines())
        for verb in ("copytree", "shutil.copy", "sqlite3", "cp -a", "profile-snapshot", "snapshot_profile",
                     "cookie_count", "restore_profile"):
            self.assertNotIn(verb, code, f"start-browser.sh runs «{verb}» again: §4h was retired (DGO-2188)")

    def test_a_stop_forwards_the_signal_waits_for_chrome_and_ends(self):
        traps = [line.strip() for line in code_lines() if line.strip().startswith("trap ") and " TERM" in line]
        self.assertEqual(traps, ["""trap 'kill -TERM "${B42_CHILD}" 2>/dev/null; wait "${B42_CHILD}"; exit 0' TERM INT"""])

    def test_after_chrome_ends_the_script_ends(self):
        code = code_lines()
        at = max(i for i, line in enumerate(code) if line.startswith('wait "${B42_CHILD}"'))
        tail = [line for line in code[at + 1:] if line.strip()]
        self.assertEqual(len(tail), 3, tail)                      # the exit status, one line said, the exit
        self.assertTrue(tail[0].startswith("B42_EXIT=") and tail[2] == 'exit "${B42_EXIT}"', tail)

    def test_going_to_sleep_ends_with_the_profile_prepared_and_nothing_after(self):
        text = "\n".join(code_lines())
        body = re.search(r"^do_sleep\(\) \{\n(.*?)^\}", text, re.S | re.M)
        self.assertIsNotNone(body)
        last = [line.strip() for line in body.group(1).splitlines() if line.strip()][-2:]
        self.assertEqual(last, ['[ -z "$(chrome_pid)" ] && prepare_profile', "return 0"])

    def test_the_retired_section_keeps_its_number_and_says_so(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^# 4h\. ", text, re.M)), 1)
        self.assertIn("# 4h. (RETIRED 2026-11-24, DGO-2188", text)


if __name__ == "__main__":
    unittest.main()
