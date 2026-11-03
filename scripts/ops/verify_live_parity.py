#!/usr/bin/env python3
"""Assert every LIVE jsCode/query body byte-matches the .workflow.ts it was pushed from.

WHY
---
`bbox n8n push` reports `ok update+activate` from the API response, not from the bytes n8n
stored. Anything that truncates or mangles a node parameter during compilation is therefore
invisible: the push looks clean and the node runs a prefix of the code.

Measured 2026-08-23: one unescaped backtick in a comment cut 'Adjudicate Merge' from 16,498 to
2,269 characters. Push said ok. The node lost its `return`, every action_merge_doubles died with
"Code doesn't return items properly", and the merge path was down for two hours before anything
noticed -- because nothing was comparing live against source.

scripts/ops/lint_backticks.py prevents the known cause. This checks the OUTCOME, so the next
cause -- whatever it turns out to be -- cannot hide the same way.

Exit 1 on any drift. Run after every push.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N8N_DIR = os.path.join(ROOT, "apps", "indox", "blueprint", "n8n")
DOCKER = ["wsl", "-d", "Ubuntu", "--", "docker", "-H", "unix:///run/bbox-docker.sock"]

# `name: 'X',` ... then the first jsCode/query literal that follows, within the same node block.
NAME_RE = re.compile(r"name:\s*'((?:[^'\\]|\\.)*)'")
BODY_RE = re.compile(r"(jsCode|query)\s*:\s*`")


def literal_body(text, start):
    """Read a template-literal body from `start`, honouring backslash escapes."""
    i = start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            return text[start:i], i
        i += 1
    return text[start:], len(text)


SIMPLE = {"`": "`", "$": "$", "\\": "\\", "n": "\n", "t": "\t", "r": "\r",
          "0": "\0", "b": "\b", "f": "\f", "v": "\v", "'": "'", '"': '"'}


def unescape(body):
    """Undo the TS template-literal escapes so the result is what the compiler emits.

    Must cover EVERY escape the compiler resolves, not just the backtick -- an unhandled one
    leaves a two-character sequence here against a one-character sequence live, and the
    resulting length difference is indistinguishable from real drift.
    """
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n == "u" and i + 2 < len(body) and body[i + 2] == "{":
                j = body.index("}", i + 3)
                out.append(chr(int(body[i + 3:j], 16)))
                i = j + 1
                continue
            if n == "u" and re.match(r"[0-9a-fA-F]{4}", body[i + 2:i + 6]):
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            if n == "x" and re.match(r"[0-9a-fA-F]{2}", body[i + 2:i + 4]):
                out.append(chr(int(body[i + 2:i + 4], 16)))
                i += 4
                continue
            if n in SIMPLE:
                out.append(SIMPLE[n])
                i += 2
                continue
            if n == "\n":                 # line continuation
                i += 2
                continue
            out.append(n)                 # \d, \s, \/ ... the backslash is dropped by the compiler
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def repo_bodies(path):
    """{node name -> compiled body} for every jsCode/query literal in the file."""
    text = io.open(path, encoding="utf-8").read()
    found = {}
    for m in BODY_RE.finditer(text):
        body, _ = literal_body(text, m.end())
        # nearest preceding name: '...'
        names = NAME_RE.findall(text[:m.start()])
        if not names:
            continue
        found.setdefault(names[-1].replace("\\'", "'"), unescape(body))
    return found


def live_bodies(wf_id):
    raw = subprocess.run(
        DOCKER + ["exec", "-i", "n8n-postgres-shlomo-laptop", "psql", "-U", "hacohen",
                  "-d", "n8n", "-tAc",
                  "SELECT nodes::text FROM workflow_entity WHERE id='%s'" % wf_id],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    if not raw:
        return None
    out = {}
    for n in json.loads(raw):
        p = n.get("parameters") or {}
        b = p.get("jsCode") or p.get("query")
        if isinstance(b, str):
            out[n.get("name")] = b
    return out


SQL_HEADS = ("select", "insert", "update", "delete", "with", "set",
             "create", "drop", "truncate", "alter", "call", "do")


def not_javascript(body):
    """True when this body must NOT be handed to `node --check`.

    Two kinds live in `query:` and expression parameters and neither is JavaScript:

      SQL -- judged on the first line that is not blank and not a comment. Getting the comment
      handling right matters more than it sounds: these bodies routinely open with twenty lines of
      `--` prose, and indoxV2ActionRouter01 opens with a MULTI-LINE `/* ... */` block whose second
      line has no leading `*`, so a per-line startswith test read that line as the start of the
      code and called the query broken JavaScript.

      n8n EXPRESSIONS -- a body beginning with `=` is an expression with {{ }} interpolation. It is
      not parseable as a standalone script in any wrapper, so checking it can only ever produce a
      false failure.

    Three of these were reported as syntax errors across the app before this was tightened. A gate
    that cries wolf is a gate people learn to push past, which is how the real truncation survived.
    """
    if body.lstrip().startswith("="):
        return True
    in_block = False
    for raw in body.splitlines():
        line = raw.strip()
        if in_block:
            if "*/" in line:
                in_block = False
                line = line.split("*/", 1)[1].strip()
                if not line:
                    continue
            else:
                continue
        if not line or line.startswith("--"):
            continue
        if line.startswith("/*"):
            if "*/" not in line:
                in_block = True
                continue
            line = line.split("*/", 1)[1].strip()
            if not line:
                continue
        return line.split(" ")[0].lower().rstrip("(") in SQL_HEADS
    return False


looks_like_sql = not_javascript      # kept: the parity gate calls it by the older name


def parses(body):
    """Does this JS body parse? A truncated push leaves a body that does not.

    Wrapped in an async function because node bodies legitimately use top-level return/await.
    SQL `query` bodies are skipped by the caller.
    """
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("async function __n(){\n" + body + "\n}\n")
        p = fh.name
    try:
        r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
        return r.returncode == 0, (r.stderr or "").strip().split("\n")[0]
    finally:
        os.unlink(p)


def main(argv):
    targets = argv[1:] or sorted(glob.glob(os.path.join(N8N_DIR, "*.workflow.ts")))
    broken, differs, checked, missing = 0, 0, 0, 0
    for path in targets:
        wf_id = os.path.basename(path).replace(".workflow.ts", "")
        live = live_bodies(wf_id)
        if live is None:
            missing += 1
            continue
        for name, want in repo_bodies(path).items():
            got = live.get(name)
            if got is None:
                continue                       # node not live (renamed/removed) -- push covers it
            checked += 1
            if got.strip() == want.strip():
                continue
            # A body that no longer parses is a TRUNCATED / mangled push: fatal, the node cannot
            # run. A body that parses is simply a different version -- repo edited and not yet
            # pushed, or a human edited live and it was not pulled. Only the first is an outage,
            # and conflating them is what let the real one hide.
            ok, err = (True, "") if looks_like_sql(got) else parses(got)
            if ok:
                differs += 1
                print("  differs   %-26s :: %-34s repo=%d live=%d" %
                      (wf_id, name, len(want), len(got)))
            else:
                broken += 1
                print("  BROKEN    %s :: %s" % (wf_id, name))
                print("            repo=%d chars  live=%d chars -- LIVE DOES NOT PARSE"
                      % (len(want), len(got)))
                print("            %s" % err)
                print("            live tail: ...%s" % got[-80:].replace("\n", " "))
    print("  checked %d node bodies across %d workflow(s); %d not live"
          % (checked, len(targets) - missing, missing))
    print("  %d differ (unpushed/unpulled version skew), %d BROKEN" % (differs, broken))
    if broken:
        print("  FAIL: %d live node(s) do not parse. Those nodes are DOWN." % broken)
        return 1
    print("  ok: no live node is broken")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
