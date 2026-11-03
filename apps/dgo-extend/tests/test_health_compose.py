#!/usr/bin/env python3
"""test_health_compose — the health step asks compose itself whether the office's project is valid.

rel10 on fireplace: every container healthy, the health step green, and every `dc` failing («service
"chimney-services" has neither an image nor a build context specified») — the step counted containers
and never asked compose. The HEALTH script, run for real in bash against a scratch `scripts/dc` that
answers as compose and dc do: the line kept is compose's own (or dc's error), never a warning or a bbox
notice, never a value from a file compose could not parse; and a project with no services is said too.

Run: python3 apps/dgo-extend/tests/test_health_compose.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

FAIL = []


def facts_with(config_q: str, services: str = "echo console\necho auth\n") -> dict:
    """`scripts/dc config -q` runs `config_q`; `scripts/dc config --services` runs `services`."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "scripts").mkdir()
        Path(d, "scripts/dc").write_text("#!/bin/bash\n"
                                         'if [ "$1 $2" = "config -q" ]; then\n' + config_q + "\nfi\n"
                                         'if [ "$1 $2" = "config --services" ]; then\n' + services + "\nexit 0\nfi\n"
                                         "exit 9\n")
        os.chmod(Path(d, "scripts/dc"), 0o755)
        out = subprocess.run(["bash", "-c", converge.HEALTH], cwd=d, capture_output=True, text=True, timeout=30,
                             env={**os.environ, "TMPDIR": d})
        return converge.parse_facts(out.stdout)


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    bad = facts_with("echo '[bbox] the docker config names the credential helper desktop.exe' >&2\n"
                     "echo 'time=\"x\" level=warning msg=\"noise\"' >&2\n"
                     "echo 'service \"chimney-services\" has neither an image nor a build context specified: "
                     "invalid compose project' >&2\nexit 15")
    check(bad.get("compose") == "invalid" and bad.get("compose_error", "").startswith('service "chimney-services"'),
          f"an invalid project is said with compose's own line — not its warnings, not a bbox notice: {bad}")
    leak = facts_with("echo 'failed to read /opt/o/.env: line 7: unexpected character \"-\" in variable name "
                      "\"API-KEY=sk-live-SECRETVALUE\"' >&2\nexit 1")
    check(leak.get("compose") == "invalid" and "SECRETVALUE" not in str(leak) and "sk-live" not in str(leak)
          and leak.get("compose_error") == "failed to read /opt/o/.env: line 7 — malformed",
          f"an env file compose cannot parse is named by file and line only — never its value: {leak}")
    for wording in ("failed to load /o/apps/x/x.env: line 3: unterminated quoted value \"sk-live-abcSECRET",
                    "failed to read /o/.env: unterminated quoted value \"sk-live-abcSECRET"):
        unterminated = facts_with(f"echo '{wording}' >&2\nexit 1")
        check(unterminated.get("compose") == "invalid" and "SECRET" not in str(unterminated)
              and "sk-live" not in str(unterminated),
              f"an unterminated quoted value never leaks, whatever the wording or its line number: {unterminated}")
    flaky = facts_with("exit 0", services="exit 1")
    check(flaky.get("compose") == "ok", f"a second call that failed is not «no services»: {flaky}")
    quoted = facts_with("echo 'service \"x\" refers to \"PASS=hunter2\" which is undefined' >&2\nexit 1")
    check("hunter2" not in str(quoted) and quoted.get("compose_error", "").startswith('service "x"'),
          f"any quoted text holding = is blanked: {quoted}")
    dc = facts_with("echo '[bbox] error: .env has no DEPLOYMENT_NAME' >&2\nexit 1")
    check(dc.get("compose") == "invalid" and dc.get("compose_error", "").startswith("[bbox] error"),
          f"dc's own refusal is the line kept: {dc}")
    empty = facts_with("exit 0", services="true")
    check(empty.get("compose") == "empty", f"a valid project with no services is said: {empty}")
    good = facts_with("exit 0")
    check(good.get("compose") == "ok" and "compose_error" not in good, f"a valid project is ok: {good}")
    print("PASS test_health_compose" if not FAIL else "FAIL test_health_compose")
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
