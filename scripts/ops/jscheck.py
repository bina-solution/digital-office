#!/usr/bin/env python3
"""Syntax-check every jsCode block in a .workflow.ts the way n8n will run it.

`bbox n8n code validate` checks the WORKFLOW SCHEMA, not the JavaScript -- it passed a node that
died at runtime with "SyntaxError: Illegal return statement". n8n wraps jsCode in a function, so
the check has to do the same or a bare `return` looks illegal.

[2026-08-23] THE EXTRACTOR WAS THE BUG, AND IT CRIED WOLF.
This used to find blocks with the regex  jsCode: `(.*?)`,\\n  -- non-greedy, and blind to
backslash escapes. Any block containing a backtick-comma-newline sequence was cut short, and the
truncated fragment then failed `node --check` for reasons that had nothing to do with the code:
indoxApi01 reported 6 blocks with syntax errors while all 16 of its live bodies parsed fine.

A gate that reports false failures is worse than no gate -- it trains you to push past it. So the
extraction now reuses verify_live_parity.literal_span/unescape, which walks the literal honouring
escapes and resolves every escape the compiler resolves. One implementation, used by both tools.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "verify_live_parity", os.path.join(_HERE, "verify_live_parity.py"))
vlp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vlp)


is_sql = vlp.looks_like_sql       # one definition, shared with the parity gate


def check(body):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write("async function __n8n_node() {\n" + body + "\n}\n")
        tmp = fh.name
    try:
        p = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        return p.returncode == 0, (p.stderr or "")
    finally:
        os.unlink(tmp)


def main(argv):
    if len(argv) < 2:
        print("usage: jscheck.py <file.workflow.ts> [more...]")
        return 2
    total = bad = skipped = 0
    for path in argv[1:]:
        bodies = vlp.repo_bodies(path)
        print("  %d code/query block(s) in %s" % (len(bodies), os.path.basename(path)))
        for name, body in bodies.items():
            if is_sql(body):
                skipped += 1
                continue
            total += 1
            ok, err = check(body)
            if not ok:
                bad += 1
                print("  FAIL  %s" % name)
                for line in [l for l in err.splitlines() if "Error" in l or "^" in l][:3]:
                    print("          %s" % line.strip()[:120])
    print("  %d JS block(s) checked, %d SQL skipped -- %s"
          % (total, skipped, "ALL OK" if bad == 0 else "%d WITH SYNTAX ERRORS" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
