#!/usr/bin/env python3
"""client_repo — the commit a client's private apps repository takes, cut from the line by a script (DGO-1924).

A client's office takes code only from the public release, which holds the client's own apps back
(scripts/release/public/exclude.txt); `bbox client-apps pull` places them from the client's private repository
(scripts/client-apps.sh). This builds that repository's next commit from a line commit, never from a working copy:

    client_repo.py --git <dir> --line <ref> --app examplex [--context "research_notes/Examplex v1 2026-11-12"]
                   [--exclude <path>…] [--redact REGEX] [--parent <commit>] [--ref refs/heads/examplex-apps]

- apps/<id>/ is the line's tree AS IS (the same tree id: `git rev-parse <line>:apps/<id>`) — or, with --redact, the
  line's tree with exactly the counted redactions (`git diff <line>:apps/<id> <commit>:apps/<id>` shows only them);
- context/<path>/ holds the client's documents at the path they have in the company tree (client-apps places them
  back there, so an app's AGENT.md that names them finds them). Another client's name never goes: --exclude drops a
  file, --redact replaces each match in a text file with «[לקוח אחר]», and a markdown table row that links an excluded
  file is dropped. Every change is counted on stderr;
- author, committer and date are fixed and the message names the line commit, so the same input is the same commit.
Prints the commit id; with --ref, the ref is set to it (in <dir>, a scratch repository — never the office's checkout).
"""
import argparse
import re
import subprocess
import sys

OTHER = "[לקוח אחר]"
WHO = {"GIT_AUTHOR_NAME": "DGO client-move", "GIT_AUTHOR_EMAIL": "person97@example.com",
       "GIT_COMMITTER_NAME": "DGO client-move", "GIT_COMMITTER_EMAIL": "person97@example.com"}


def git(d, *args, data=None, env=None):
    import os
    r = subprocess.run(["git", "-C", d, *args], input=data, capture_output=True,
                       env=dict(os.environ, **(env or {})))
    if r.returncode:
        raise SystemExit(f"[client-repo] git {' '.join(args[:3])}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def mktree(d, entries):
    """entries: [(mode, type, sha, name)] → tree id."""
    body = "".join(f"{m} {t} {s}\t{n}\n" for m, t, s, n in sorted(entries, key=lambda e: e[3]))
    return git(d, "mktree", data=body.encode()).decode().strip()


def nest(d, path, tree):
    """a tree holding `tree` at `path` (a/b/c), as nested trees."""
    for part in reversed(path.strip("/").split("/")):
        tree = mktree(d, [("040000", "tree", tree, part)])
    return tree


def merge(d, trees):
    """one tree from several single-path trees (their top entries are distinct, or merged one level down)."""
    top = {}
    for t in trees:
        for line in git(d, "ls-tree", t).decode().splitlines():
            meta, name = line.split("\t", 1)
            m, ty, sha = meta.split()
            if name in top and ty == "tree" and top[name][1] == "tree":
                top[name] = (m, ty, merge(d, [top[name][2], sha]), name)
            else:
                top[name] = (m, ty, sha, name)
    return mktree(d, list(top.values()))


def context_tree(d, line, path, excluded, rx, counts):
    """the line's <path>, minus excluded files, other clients' names redacted in text files."""
    entries = []
    for line_ in git(d, "ls-tree", f"{line}:{path}").decode().splitlines():
        meta, name = line_.split("\t", 1)
        m, ty, sha = meta.split()
        full = f"{path}/{name}"
        if full in excluded or name in excluded:
            counts["excluded"] += 1
            continue
        if ty == "tree":
            entries.append((m, ty, context_tree(d, line, full, excluded, rx, counts), name))
            continue
        blob = git(d, "cat-file", "blob", sha)
        try:
            text = None if b"\0" in blob else blob.decode("utf-8")   # a text file: UTF-8, no NUL
        except UnicodeDecodeError:
            text = None
        if rx and text is not None:
            kept = []
            for ln in text.split("\n"):
                # a table row or list line that links an excluded file goes with it
                if any(f"({x.rsplit('/', 1)[-1]})" in ln or f"]({x.rsplit('/', 1)[-1]}" in ln for x in excluded):
                    counts["rows"] += 1
                    continue
                ln, n = rx.subn(OTHER, ln)
                counts["redacted"] += n
                kept.append(ln)
            new = "\n".join(kept).encode("utf-8")
            if new != blob:
                sha = git(d, "hash-object", "-w", "--stdin", data=new).decode().strip()
                print(f"[client-repo] {full}: changed (another client's name, or a link to a file left out)",
                      file=sys.stderr)
        entries.append((m, ty, sha, name))
    return mktree(d, entries)


def main():
    for stream in (sys.stdout, sys.stderr):    # Hebrew on every line: UTF-8 whatever the console's code page (G10)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="client_repo")
    ap.add_argument("--git", required=True, help="a scratch repository that has the line's objects")
    ap.add_argument("--line", required=True)
    ap.add_argument("--app", action="append", required=True)
    ap.add_argument("--context", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--redact")
    ap.add_argument("--parent")
    ap.add_argument("--ref")
    ap.add_argument("--date", default="2026-11-17T00:00:00Z", help="the commit's fixed date (reproducible)")
    a = ap.parse_args()
    d, line = a.git, a.line
    sha = git(d, "rev-parse", "--short=9", f"{line}^{{commit}}").decode().strip()
    rx = re.compile(a.redact) if a.redact else None
    counts = {"excluded": 0, "rows": 0, "redacted": 0}
    # the app's tree is the line's own; with --redact, a text file naming another client is the one change (counted)
    parts = [nest(d, f"apps/{app}", context_tree(d, line, f"apps/{app}", set(), rx, counts) if rx
                  else git(d, "rev-parse", f"{line}:apps/{app}").decode().strip()) for app in a.app]
    in_apps = counts["redacted"]
    parts += [nest(d, f"context/{p}", context_tree(d, line, p, set(a.exclude), rx, counts)) for p in a.context]
    tree = merge(d, parts)
    msg = (f"{', '.join('apps/' + x for x in a.app)} from {line} {sha}"
           + (f" ({in_apps} other-client name(s) redacted)" if rx else "")
           + (f"; context: {', '.join(a.context)} ({counts['excluded']} file(s) left out, {counts['rows']} row(s) "
              f"dropped, {counts['redacted'] - in_apps} other-client name(s) redacted)" if a.context else ""))
    env = dict(WHO, GIT_AUTHOR_DATE=a.date, GIT_COMMITTER_DATE=a.date)
    commit = git(d, "commit-tree", tree, *(["-p", a.parent] if a.parent else []), "-m", msg, env=env).decode().strip()
    if a.ref:
        git(d, "update-ref", a.ref, commit)
    print(f"[client-repo] {msg}", file=sys.stderr)
    print(commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
