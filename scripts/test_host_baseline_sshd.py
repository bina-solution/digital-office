#!/usr/bin/env python3
"""host-baseline's sshd check holds what DGO-879 asks: keys only, no password, and root by key alone. It also
FAILS on a config that gives a password, which is proven here rather than described.

    python3 scripts/test_host_baseline_sshd.py

`scripts/ops/host-baseline.sh check` asks sshd for its effective answer: for a stranger's connection
(`sshd -T -C user=…,addr=203.0.113.9,…`) and for every account that can log in. This test runs the real script
with stubs first on PATH. `sshd` answers from a fixture; id, ip, ss, nft, systemctl and getent answer as a quiet
Linux server would. Only the check's sshd lines are judged. Its other facts, the host table and the units, are
drift on a machine that never applied the baseline, as this one has not. It needs no root, no network and no
sshd. HOST_BASELINE_SCRIPT points it at another copy of the script, which is how a mutant is run.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.environ.get("HOST_BASELINE_SCRIPT") or os.path.join(HERE, "ops", "host-baseline.sh")

KEYS_ONLY = """port 22
passwordauthentication no
kbdinteractiveauthentication no
pubkeyauthentication yes
authenticationmethods any
permitrootlogin without-password
x11forwarding no
"""

STUBS = {
    # root, for the script's own check; anything else is the real id
    "id": '[ "$1" = -u ] && { echo 0; exit 0; }; exec /usr/bin/id "$@"\n',
    "ip": """case "$*" in
  *"-6 route show default"*) ;;
  *"route show default"*) echo "default via 203.0.113.1 dev eth0 proto static" ;;
  *"link show dev eth0"*) echo "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500" ;;
  *"addr show dev eth0"*) echo "2: eth0    inet 203.0.113.5/24 brd 203.0.113.255 scope global eth0" ;;
esac
exit 0
""",
    # `sshd -T` alone, or `sshd -T -C user=…,…`: the fixture, each keyword once, as sshd prints it.
    # SSHD_USER_SET=<user>:<keyword>=<value>[;…] changes that user's answer in place, as a provider's
    # `Match User deploy` block would.
    "sshd": """spec=""
while [ $# -gt 0 ]; do [ "$1" = -C ] && { spec="$2"; shift; }; shift; done
user="$(printf '%s' "${spec}" | sed -n 's/.*user=\\([^,]*\\).*/\\1/p')"
out="$(cat "${SSHD_FIXTURE}")"
IFS=';'
for set in ${SSHD_USER_SET:-}; do
  u="${set%%:*}"; kv="${set#*:}"; k="${kv%%=*}"; v="${kv#*=}"
  [ -n "${user}" ] && [ "${u}" = "${user}" ] && out="$(printf '%s\\n' "${out}" | sed "s/^${k} .*/${k} ${v}/")"
done
printf '%s\\n' "${out}"
""",
    "getent": """[ "$1" = passwd ] || exit 2
printf 'root:x:0:0:root:/root:/bin/bash\\ndeploy:x:1000:1000::/home/deploy:/bin/bash\\nnobody:x:65534:65534::/:/usr/sbin/nologin\\n'
""",
    "ss": "exit 0\n",
    "nft": "exit 1\n",
    "systemctl": "exit 1\n",
    "wg": "exit 1\n",
}


class SshdCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="host-baseline-sshd-")
        cls.bin = os.path.join(cls.tmp, "bin")
        os.makedirs(cls.bin)
        for name, body in STUBS.items():
            p = os.path.join(cls.bin, name)
            with open(p, "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        cls.env_file = os.path.join(cls.tmp, ".env")
        with open(cls.env_file, "w") as f:
            f.write("DEPLOYMENT_NAME=t\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def sshd_lines(self, fixture, user_set=""):
        path = os.path.join(self.tmp, "sshd-T")
        with open(path, "w") as f:
            f.write(fixture)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DGO_", "HOST_", "OFFICE_"))}
        env.update({"PATH": self.bin + os.pathsep + env.get("PATH", "/usr/bin:/bin"), "SSHD_FIXTURE": path,
                    "SSHD_USER_SET": user_set, "OFFICE_ENV": self.env_file, "LC_ALL": "C"})
        p = subprocess.run(["bash", SCRIPT, "check"], capture_output=True, text=True, env=env, timeout=120)
        lines = []
        for line in p.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].startswith("sshd:"):
                lines.append(line)
        self.assertTrue(lines, f"the check said nothing about sshd (rc {p.returncode}): {p.stdout[-600:]!r} "
                               f"{p.stderr[-600:]!r}")
        return lines

    def assertDrift(self, lines, pattern, why):
        rx = re.compile(r"^DRIFT\s+sshd:.*" + pattern)
        self.assertTrue(any(rx.search(l) for l in lines), f"{why}: no drift line matches {pattern!r} in {lines}")

    def test_keys_only_is_held(self):
        lines = self.sshd_lines(KEYS_ONLY)
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r"^ok\s+sshd:", lines)

    def test_every_rule_for_a_stranger_fails_on_its_bad_value(self):
        # each line of the fixture the check holds, given the value a password-capable or looser sshd has
        for keyword, good, bad in (("passwordauthentication", "no", "yes"),
                                   ("kbdinteractiveauthentication", "no", "yes"),   # with PAM, a password prompt
                                   ("pubkeyauthentication", "yes", "no"),
                                   ("authenticationmethods", "any", "password"),
                                   ("permitrootlogin", "without-password", "yes"),
                                   ("x11forwarding", "no", "yes")):
            with self.subTest(keyword=keyword):
                # root's answer alone (the stranger's query asks as root): the per-user check of `deploy` sees the
                # good value, so only the stranger's rule can catch this one
                self.assertIn(f"{keyword} {good}\n", KEYS_ONLY)
                lines = self.sshd_lines(KEYS_ONLY, user_set=f"root:{keyword}={bad}")
                self.assertDrift(lines, rf"\b{keyword}={bad}\b", f"a stranger given {keyword} {bad}")
                self.assertFalse(any("deploy" in l for l in lines), lines)

    def test_a_password_for_one_login_user_fails(self):
        # root's own answer stays right; a `Match User deploy` that gives a password is still one on the host
        for keyword in ("passwordauthentication", "kbdinteractiveauthentication"):
            with self.subTest(keyword=keyword):
                lines = self.sshd_lines(KEYS_ONLY, user_set=f"deploy:{keyword}=yes")
                self.assertDrift(lines, rf"\bdeploy\b.*\b{keyword}=yes\b", f"deploy given {keyword}")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
