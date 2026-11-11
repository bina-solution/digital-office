#!/usr/bin/env python3
"""tile-screen-lint — gate G106: a tile opens a screen, never an API.

    python3 scripts/refactor/tile-screen-lint.py              # measure the office running here
    python3 scripts/refactor/tile-screen-lint.py --self-test

WHY. Exampleu's own Claude measured its office on 2026-11-09 (EXU-21, DGO-1684): the tile «מודלים מקומיים»
showed one line, «Ollama is running», and nothing else. Its manifest framed the Ollama API's root
(`http://ollama:11434`) as if it were a page — Ollama ships no screen at all. A person who opens a tile must
get a screen; an API is for agents (`capabilities[].endpoint`), and it stays reachable there.

WHAT IT MEASURES. A tile is only known to be a screen by what it answers, so this asks the office that runs
here, the way a person's browser comes in: through the console's own proxy (`/a/<alias>/`, every tile the
console frames, from its `/api/modules`), asking for HTML. A tile that answers 2xx with something that is not
a page (text/plain, JSON, …) FAILS — that is an API where a screen should be. A 3xx/4xx/5xx is not this
gate's business (a sign-in, a missing route, a dead app have their own checks) and is listed, not failed.
Measured on Exampleu, 2026-11-09: of 21 tiles, `ollama` alone answered 200 text/plain.
WHERE IT RUNS. On an office (`bbox baseline`, scripts/ci/gates.sh): the measure. Where no console runs (CI, a
fresh clone) there is nothing to measure and it says so and passes — `--self-test` is what proves there that
it can fail.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: Run INSIDE the console container: its own /api/modules, then each framed tile through its own proxy.
PROBE = r'''
import json, urllib.request
class _Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                                # a redirect is answered as it is, never followed off the office
opener = urllib.request.build_opener(_Stay)
mods = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/modules", timeout=15))
mods = mods.get("modules", mods) if isinstance(mods, dict) else mods
out, seen = [], set()
for m in mods:
    name = m.get("alias") or m.get("id")
    # A linked office's tile is framed at its proxy path (the shell's own rule, console/static/app.js); its
    # `embed` names the local alias, which would ask THIS office's app instead.
    mount = m.get("proxy") if m.get("external") else m.get("embed")
    if not isinstance(mount, str) or not mount.startswith("/") or mount in seen:
        continue                                   # not framed by the console (its own screen, its own host), or asked
    seen.add(mount)
    try:
        r = opener.open(urllib.request.Request("http://127.0.0.1:8000" + mount,
                        headers={"Accept": "text/html", "X-authentik-username": "tile-screen-lint"}), timeout=8)
        out.append({"tile": name, "status": r.status, "type": r.headers.get("Content-Type", ""), "head": r.read(80).decode("utf-8", "replace")})
    except urllib.error.HTTPError as e:
        out.append({"tile": name, "status": e.code, "type": "", "head": ""})
    except Exception as e:
        out.append({"tile": name, "status": 0, "type": "", "head": str(e)[:80]})
print(json.dumps(out))
'''


def judge(rows: list[dict]) -> tuple[list[str], list[str]]:
    """(failures: an API where a screen should be, notes: answers that are other checks' business)."""
    fails, notes = [], []
    for r in rows:
        ok2xx = 200 <= int(r.get("status") or 0) < 300
        is_page = "html" in (r.get("type") or "").lower()
        if ok2xx and not is_page:
            fails.append(f"{r['tile']}: answers {r['status']} {r.get('type') or 'no type'} — not a page "
                         f"({(r.get('head') or '').strip()[:50]!r}); a tile must open a screen, an API is for agents")
        elif not ok2xx:
            notes.append(f"{r['tile']}: {r.get('status')} (not this gate's business)")
    return fails, notes


REPO = Path(__file__).resolve().parents[2]


def console_container() -> str | None:
    """THIS checkout's console only — the compose project's working dir is the checkout that started it. A CI
    runner on an office's machine (the Dell's) can reach that office's docker: without this filter the gate
    would measure the office in production instead of the commit under test (the second reader)."""
    try:
        out = subprocess.run(["docker", "ps", "--filter", "label=com.docker.compose.service=console",
                              "--filter", f"label=com.docker.compose.project.working_dir={REPO}",
                              "--format", "{{.Names}}"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.split()[0] if out.split() else None


def main() -> int:
    c = console_container()
    if not c:
        print("tile-screen-lint — G106: no console runs here, nothing to measure (an office measures; --self-test proves it can fail)")
        return 0
    try:
        p = subprocess.run(["docker", "exec", "-i", c, "python3", "-"], input=PROBE, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        print(f"G106 FAIL — the console ({c}) did not finish asking its tiles in 900 s")
        return 1
    try:
        rows = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(f"G106 FAIL — the console ({c}) did not answer its tiles: {p.stderr.strip()[-200:]}")
        return 1
    fails, notes = judge(rows)
    print(f"tile-screen-lint — G106: {len(rows)} framed tile(s) asked through {c}")
    for n in notes:
        print(f"  note  {n}")
    if not rows:
        print("G106 FAIL — the console frames no tile; an empty answer proves nothing")
        return 1
    if fails:
        print("G106 FAIL — a tile opens an API, not a screen:")
        for f in fails:
            print(f"  {f}")
        return 1
    print("G106 PASS — every framed tile answers a page")
    return 0


def self_test() -> int:
    #: (case, rows, failures wanted, notes wanted): what it fails, and what it leaves to the checks that own it.
    cases = [
        ("a page", [{"tile": "drive", "status": 200, "type": "text/html; charset=utf-8", "head": "<!doctype html>"}], 0, 0),
        ("Ollama's root", [{"tile": "ollama", "status": 200, "type": "text/plain; charset=utf-8", "head": "Ollama is running"}], 1, 0),
        ("an API's JSON", [{"tile": "x", "status": 200, "type": "application/json", "head": "{}"}], 1, 0),
        ("no type at all", [{"tile": "x", "status": 204, "type": "", "head": ""}], 1, 0),
        ("a sign-in redirect is not its business", [{"tile": "x", "status": 302, "type": "", "head": ""}], 0, 1),
        ("a missing route is not its business", [{"tile": "n8n", "status": 404, "type": "", "head": ""}], 0, 1),
    ]
    ok = True
    for name, rows, want_fail, want_note in cases:
        fails, notes = judge(rows)
        good = (len(fails), len(notes)) == (want_fail, want_note)
        ok &= good
        print(f"  {'ok ' if good else 'BAD'} {name}: {len(fails)} failure(s), {len(notes)} note(s); want {want_fail}, {want_note}")
    print("G106 self-test " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8")
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
