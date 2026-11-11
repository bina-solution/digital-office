#!/usr/bin/env python3
"""one-claude-lint — gate G105: Bina Claude is ONLY the official Claude Desktop app, with ONE login.

    python3 scripts/refactor/one-claude-lint.py              # exit 1 on a finding
    python3 scripts/refactor/one-claude-lint.py --self-test

WHY. The owner, 2026-11-09 (DGO-1684): «Bullshit why are you keep obsessing on the claude terminal its
bullshit dont use it find a way to use only the offical fullapllication i said milion times one login in the
pffical claude desktop and we should have full cli controll over it and all other 4 channles» — and then:
«Delete the terminal and make sure nobody gets mixed up again!!!!». Bina Claude had a second Claude next to
the app: the tile «בינה קלוד · מסוף» (Claude Code in a web terminal, `claude-terminal`), with its own sign-in
(`/login` in the terminal) and Remote Control's server. Agents kept sending the owner to it. It is deleted;
this gate keeps it deleted, and keeps every page from sending anyone back to it.

WHAT FAILS
  A. a declared tile of a terminal: a routing entry whose host, alias or id is `claude-terminal`, or that
     listens on 7681 (the terminal's port), in any app.json — and the same names in the UI capture manifest;
  B. bina-claude declaring more than ONE tile (the desktop is its only screen);
  C. bina-claude's own build and start files bringing a terminal back: ttyd, the Claude Code CLI package,
     Remote Control's server, tmux;
  D. a page or a brief that tells anyone to sign in in a terminal: the tile's name «בינה קלוד · מסוף», or an
     instruction to type `/login` or `/remote-control` on a line about Claude. A line that FORBIDS it
     («never propose /login») gives no instruction and is not read as one.
NOT READ: history (issues/, legacy/, ai/obsidian/, apps/project-pln/plans/, data/), session notes (.claude/),
this file. `herd.yaml`'s `admin_apps` is a DENY list: naming the terminal there keeps an office that still
runs it from giving it away, and is allowed.
A scan that read no app.json or no page FAILS: an empty scan proves nothing.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
SKIP = ("issues/", "legacy/", "ai/obsidian/", "apps/project-pln/plans/", "data/", ".claude/",
        "scripts/refactor/one-claude-lint.py")
TERMINAL_NAMES = {"claude-terminal"}
TERMINAL_PORT = 7681
TILE_NAME = "בינה קלוד · מסוף"
#: bina-claude's own files that build and start its containers.
BINA_CLAUDE_BUILD = ("apps/bina-claude/Dockerfile", "apps/bina-claude/Dockerfile.desktop",
                     "apps/bina-claude/docker-compose.yml", "apps/bina-claude/entrypoint.sh")
#: the programs, not words: the brief's own sentence «never propose /login, /remote-control» runs nothing.
BUILD_TERMINAL = re.compile(r"\bttyd\b|@anthropic-ai/claude-code|claude remote-control|bina-claude/remote-control"
                            r"|\./remote-control\b|\btmux\b", re.I)
#: an instruction to type a slash command of the CLI's sign-in…
INSTRUCT = re.compile(r"(\b(type|run|enter|press|send|use)\b|הקלד|הקש|כתוב)[^.\n]{0,40}`?/(login|remote-control)\b", re.I)
#: …on a line about Claude…
ABOUT_CLAUDE = re.compile(r"claude|קלוד", re.I)
#: …that does not forbid it.
FORBIDS = re.compile(r"\b(never|don'?t|do not)\b[^.\n]{0,30}/(login|remote-control)|\bthere is no terminal\b|אל ת", re.I)
PAGES = (".md", ".html", ".txt")


def tracked(root: pathlib.Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True).stdout
        return [p for p in out.splitlines() if p]
    except (OSError, subprocess.CalledProcessError):
        return [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]


def skipped(path: str) -> bool:
    return any(path == s or path.startswith(s) for s in SKIP)


def tiles(manifest: dict) -> list[dict]:
    return [r for r in manifest.get("routing") or [] if isinstance(r, dict)]


def tile_findings(path: str, manifest: dict) -> list[str]:
    out = []
    for r in tiles(manifest):
        module = r.get("module") or {}
        names = {str(r.get("host") or ""), str(module.get("alias") or ""), str(module.get("id") or ""), str(r.get("name") or "")}
        if names & TERMINAL_NAMES:
            out.append(f"{path}: a terminal tile ({sorted(names & TERMINAL_NAMES)[0]}) — Bina Claude has no terminal (A)")
        elif r.get("port") == TERMINAL_PORT and manifest.get("id") == "bina-claude":
            out.append(f"{path}: a tile on {TERMINAL_PORT}, the terminal's port (A)")
    if manifest.get("id") == "bina-claude" and len(tiles(manifest)) > 1:
        out.append(f"{path}: bina-claude declares {len(tiles(manifest))} tiles — its ONE screen is the desktop app (B)")
    return out


def scan(root: pathlib.Path) -> tuple[list[str], dict]:
    findings, counts = [], {"app.json": 0, "pages": 0, "build": 0}
    files = [p for p in tracked(root) if not skipped(p)]
    for path in files:
        full = root / path
        if not full.is_file():
            continue
        if path.endswith("/app.json") and (path.startswith("apps/") or path.startswith("platform-base/")):
            counts["app.json"] += 1
            try:
                findings += tile_findings(path, json.loads(full.read_text(encoding="utf-8")))
            except (OSError, ValueError) as e:
                findings.append(f"{path}: not readable JSON ({e}) — a manifest nothing can check")
        elif path == "scripts/ui-coverage/manifest.yaml":
            for n, line in enumerate(full.read_text(encoding="utf-8").splitlines(), 1):
                if re.match(r"\s*claude-terminal\s*:", line):
                    findings.append(f"{path}:{n}: the terminal tile is captured as a screen (A)")
        if path in BINA_CLAUDE_BUILD:
            counts["build"] += 1
            for n, line in enumerate(full.read_text(encoding="utf-8").splitlines(), 1):
                if BUILD_TERMINAL.search(line) and not line.lstrip().startswith("#"):
                    findings.append(f"{path}:{n}: a terminal brought back: {line.strip()[:90]} (C)")
        if path.endswith(PAGES) or path in ("apps/bina-claude/entrypoint.sh", "AGENTS.md"):
            if path.endswith(PAGES):
                counts["pages"] += 1
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if TILE_NAME in line:
                    findings.append(f"{path}:{n}: names the terminal tile «{TILE_NAME}» (D)")
                elif INSTRUCT.search(line) and ABOUT_CLAUDE.search(line) and not FORBIDS.search(line):
                    findings.append(f"{path}:{n}: tells someone to sign in in a terminal: {line.strip()[:90]} (D)")
    return findings, counts


def main() -> int:
    findings, counts = scan(REPO)
    print(f"one-claude-lint — G105: {counts['app.json']} app.json · {counts['pages']} page(s) · "
          f"{counts['build']} bina-claude build file(s) read")
    if not counts["app.json"] or not counts["pages"] or not counts["build"]:
        print("G105 FAIL — the scan read nothing of one kind; an empty scan proves nothing")
        return 1
    if findings:
        print("G105 FAIL — Bina Claude is ONLY the official Claude Desktop app, with ONE login; there is no terminal:")
        for f in findings:
            print(f"  {f}")
        return 1
    print("G105 PASS — one Claude: the desktop app's one tile, no terminal in its build, and no page that sends anyone to one")
    return 0


def self_test() -> int:
    ok = True

    def check(name: str, files: dict, want: int) -> None:
        nonlocal ok
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            for p, body in files.items():
                (root / p).parent.mkdir(parents=True, exist_ok=True)
                (root / p).write_text(body, encoding="utf-8")
            got = len(scan(root)[0])
            mark = "ok " if got == want else "BAD"
            ok &= got == want
            print(f"  {mark} {name}: {got} finding(s), want {want}")

    desk = {"host": "claude", "port": 3000, "service": "bina-claude-desktop", "module": {"alias": "bina-claude"}}
    term = {"host": "claude-terminal", "port": 7681, "service": "bina-claude", "module": {"alias": "claude-terminal"}}
    one = json.dumps({"id": "bina-claude", "routing": [desk]})
    two = json.dumps({"id": "bina-claude", "routing": [desk, term]})
    base = {"apps/x/README.md": "nothing here\n", "apps/bina-claude/Dockerfile": "FROM node\n"}
    check("the desktop alone", {**base, "apps/bina-claude/app.json": one}, 0)
    check("the terminal tile back", {**base, "apps/bina-claude/app.json": two}, 2)              # A + B
    check("a terminal in another app", {**base, "apps/bina-claude/app.json": one,
                                        "apps/other/app.json": json.dumps({"id": "other", "routing": [term]})}, 1)
    check("ttyd in the build", {**base, "apps/bina-claude/app.json": one,
                                "apps/bina-claude/Dockerfile": "FROM node\nRUN curl -o /usr/local/bin/ttyd x\n# ttyd was here\n"}, 1)
    check("a page that sends him to /login", {**base, "apps/bina-claude/app.json": one,
                                               "apps/x/README.md": "Open the Claude tile and type `/login`.\n"}, 1)
    check("the tile's name on a page", {**base, "apps/bina-claude/app.json": one,
                                        "ai/context/x.md": "פתח את «בינה קלוד · מסוף»\n"}, 1)
    check("a page that forbids it", {**base, "apps/bina-claude/app.json": one,
                                     "apps/x/README.md": "Bina Claude: there is no terminal; never propose /login or a terminal.\n"}, 0)
    check("another app's own /login page", {**base, "apps/bina-claude/app.json": one,
                                            "apps/x/README.md": "The portal: type the user at /login and submit.\n"}, 0)
    check("history is not read", {**base, "apps/bina-claude/app.json": one,
                                   "issues/old.md": "type /login in «בינה קלוד · מסוף»\n"}, 0)
    with tempfile.TemporaryDirectory() as t:
        empty_ok = not scan(pathlib.Path(t))[1]["app.json"]
    print(f"  {'ok ' if empty_ok else 'BAD'} an empty tree reads no app.json (main() fails it)")
    ok &= empty_ok
    print("G105 self-test " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8")
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
