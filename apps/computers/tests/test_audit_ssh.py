#!/usr/bin/env python3
"""test_audit_ssh — the machine audit reads SSH the way sshd does (DGO-415).

Measured 2026-11-10 from the MacBook's «מחשבים» against Exampleu's server (93.184.216.11):
- the audit said «SSH מקבל סיסמאות» (error) and «התחברות root ב-SSH מותרת» (warn);
- `sshd -T` there says `passwordauthentication no` and `permitrootlogin without-password`;
- the collector had concatenated sshd_config with its drop-ins and taken the LAST matching line.

This test runs the collector's SSH part (AUDIT_SSH_SH, taken from app.py without importing it) against
config trees, with `sshd -T` unavailable, so the files path is the one read. The trees:
- Exampleu's shape: an Include first, a later yes in the main file, a Match block;
- a Match inside an included file (sshd restores the parent's state after it);
- an Include that matches nothing or ends in a comment;
- an unreadable drop-in;
- empty files (sshd's defaults);
- `keyword=value` and quoted values;
- a Match block that loosens.
Each is run under every shell here (sh, dash, bash, zsh; zsh as a login shell broke the word splitting).
The judgement (`audit_findings`, also taken by `ast`) reads `without-password` as key-only and flags the
partial and Match cases.

Run: python3 tests/test_audit_ssh.py   (from apps/computers; needs only a POSIX sh)
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
FAIL: list[str] = []
SRC = (HERE / "app.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def const(name: str) -> str:
    for n in TREE.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name:
            return n.value.value
    raise SystemExit(f"{name} not found in app.py")


SSH_SH = const("AUDIT_SSH_SH")
ZSH_LINE = re.search(r"^\[ -n \"\$\{ZSH_VERSION.*$", SRC, re.M).group(0)   # AUDIT_SH's first line
SHELLS = [s for s in ("sh", "dash", "bash", "zsh") if shutil.which(s)]


def run(root: Path, shell: str = "sh") -> dict:
    line = "sshdc=$( (sshd -T || /usr/sbin/sshd -T) 2>/dev/null )"
    assert line in SSH_SH, "the collector's sshd -T line moved: update this test with it"
    sh = ZSH_LINE + "\n" + SSH_SH.replace(line, "sshdc=''").replace("/etc/ssh", str(root))
    out = subprocess.run([shell, "-c", sh], capture_output=True, text=True, timeout=60).stdout
    return dict(l.split("=", 1) for l in out.splitlines() if l.startswith("ssh_") and "=" in l)


def tree(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sshd-"))
    (root / "sshd_config.d").mkdir()
    for name, text in files.items():
        (root / name).write_text(text.replace("{root}", str(root)))
    return root


def judge(facts: dict) -> dict:
    want = {"_num", "audit_findings", "RISKY_PORTS"}
    nodes = [n for n in TREE.body if (isinstance(n, ast.FunctionDef) and n.name in want)
             or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in want)]
    ns: dict = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app", "exec"), ns)
    return {x["code"]: x["severity"] for x in ns["audit_findings"](facts)}


CASES = [
    ("Exampleu's shape: the first value wins, the Include read where it stands",
     {"sshd_config": "Include {root}/sshd_config.d/*.conf\nPort 22\nPermitRootLogin yes\nPasswordAuthentication yes\n"
                     "Match User backup\n    PasswordAuthentication yes\n    PermitRootLogin yes\n",
      "sshd_config.d/50-cloud-init.conf": "PasswordAuthentication no\n",
      "sshd_config.d/60-dgo.conf": "PasswordAuthentication yes\n"},
     {"ssh_config_from": "files", "ssh_password_auth": "no", "ssh_root_login": "yes", "ssh_port": "22",
      "ssh_match_loosens": "2"}),
    ("a Match inside an included file ends that file only",
     {"sshd_config": "Include sshd_config.d/*.conf\nPermitRootLogin no\n",
      "sshd_config.d/10-sftp.conf": "Match Group sftp\n  ChrootDirectory /srv\n",
      "sshd_config.d/50-cloud-init.conf": "PasswordAuthentication yes\n"},
     {"ssh_password_auth": "yes", "ssh_root_login": "no", "ssh_match_loosens": "0"}),
    ("an Include that matches nothing, or ends in a comment, does not stop the reading",
     {"sshd_config": "Include sshd_config.d/*.conf # drop-ins\nPasswordAuthentication yes\n",
      "sshd_config.d/10-a.conf": "Include /nothing/*.conf\n"},
     {"ssh_password_auth": "yes"}),
    ("an unreadable drop-in makes the reading partial, never «absent»",
     {"sshd_config": "Include sshd_config.d/*.conf\n",
      "sshd_config.d/50-secret.conf": "PasswordAuthentication no\n"},
     {"ssh_config_from": "files-partial", "ssh_password_auth": ""}),
    ("where the files say nothing, sshd's own defaults",
     {"sshd_config": "#PasswordAuthentication yes\n"},
     {"ssh_password_auth": "yes", "ssh_root_login": "prohibit-password", "ssh_empty_pw": "0"}),
    ("keyword=value and quotes, as sshd reads them",
     {"sshd_config": "PasswordAuthentication=no\nPermitRootLogin = \"no\"\nPermitEmptyPasswords yes\n"},
     {"ssh_password_auth": "no", "ssh_root_login": "no", "ssh_empty_pw": "1"}),
]


def main() -> int:
    root_user = os.geteuid() == 0
    for shell in SHELLS:
        for what, files, want in CASES:
            if "unreadable" in what and root_user:
                continue                     # root reads a 000 file: the case cannot be made as root
            r = tree(files)
            if "unreadable" in what:
                os.chmod(r / "sshd_config.d" / "50-secret.conf", 0)
            try:
                got = run(r, shell)
            finally:
                for p in r.rglob("*"):
                    os.chmod(p, 0o755 if p.is_dir() else 0o644)
                shutil.rmtree(r)
            bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
            check(not bad, f"[{shell}] {what}" + (f" — got/want {bad}" if bad else ""))

    codes = judge({"ssh_config_from": "sshd", "ssh_password_auth": "no", "ssh_root_login": "without-password"})
    check(codes.get("ssh_root_login_key") == "ok" and "ssh_root_login" not in codes,
          f"sshd -T's `without-password` reads as root by key only ({codes})")
    check(codes.get("ssh_password_off") == "ok", "passwords off reads as ok")
    codes = judge({"ssh_config_from": "files-partial", "ssh_match_loosens": "2"})
    check(codes.get("ssh_config_partial") == "info", "a partial reading is said, not silent")
    check(codes.get("ssh_match_loosens") == "warn", "a Match block that loosens a login is a warning")

    print(f"test_audit_ssh ({', '.join(SHELLS)}):", "FAIL" if FAIL else "PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
