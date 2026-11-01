#!/usr/bin/env python3
"""n8n_blueprint — THE way a gate reads a workflow blueprint. There is one form: code.

    from n8n_blueprint import load, CompileError
    wf = load("apps/indox/blueprint/n8n/indoxV2BSTest01.workflow.ts")   # -> dict

WHY THIS EXISTS. Commit 52b32aa4 ("blueprints are code: 96 workflows as *.workflow.ts, JSON era
removed") moved every blueprint and deleted the JSON. Eight consumers were never repointed, and
each one broke differently:

    G39/G41/G48/G50/G53   report "blueprint file not found" AS A FINDING — so they inspect
                          nothing while looking merely red
    bbox n8n push all     aborted on every invocation, with an error naming the wrong cause
    G64                   a HARD pre-flight — blocked the entire INDOX E2E battery
    hooks/sync-engine     a safety guard that could only ever refuse

They were found one failure at a time over a single session. The lesson is not "fix the paths":
repointing G64 at the .workflow.ts made it fail one line later, on

    blueprints[rel] = json.loads(p.read_text(encoding="utf-8"))

because a TypeScript file is not JSON. Every one of those gates wants the same thing — the
compiled workflow dict — and each was about to grow its own parser. Six private parsers is how
this drifts again, so there is one, here.

DELIBERATELY NOT A DUAL-FORMAT READER. Accepting `.json` "for compatibility" would keep the
retired era alive in the exact places that failed to notice it had ended. If a caller hands us a
`.json` path we say so and name the `.workflow.ts` it should be asking for instead.

HOW. There is already exactly one compiler — `apps/n8n/tooling/wrap.mjs`, the same one
`bbox n8n push` uses — so this shells out to it rather than reimplementing the transformer. It
compiles a whole DIRECTORY at a time (69 workflows in one call for apps/indox/blueprint/n8n), so
results are cached per directory: a gate reading twenty blueprints from one app pays for one
compile, not twenty.
"""
import atexit
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
WRAP = REPO / "apps" / "n8n" / "tooling" / "wrap.mjs"

#: dir (absolute, resolved) -> {stem: dict}. One compile per directory, for the process lifetime.
_CACHE: "dict[pathlib.Path, dict]" = {}
_TMP: "list[str]" = []


class CompileError(RuntimeError):
    """The blueprint could not be turned into a dict. The message says which and why."""


def _cleanup():
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup)


def _node():
    """Find a node binary. PATH is not enough: a gate invoked from a hook or a test harness
    inherits whatever PATH that caller had, and a userland install (~/.local/bin) is invisible
    to it. That is not hypothetical — it is how `bbox indox test` came to refuse to run: G64
    could not read a blueprint, reported ten findings that were all the same missing binary,
    and blocked the whole battery.

    $NODE_BIN wins, then PATH, then the usual install locations. Same shape as the
    UI_CHROME_BIN resolution in the sim scripts, for the same reason.
    """
    env = os.environ.get("NODE_BIN")
    if env and os.access(env, os.X_OK):
        return env
    found = shutil.which("node")
    if found:
        return found
    for cand in (os.path.expanduser("~/.local/bin/node"),
                 os.path.expanduser("~/.local/opt/node/bin/node"),
                 "/usr/local/bin/node", "/usr/bin/node"):
        if os.access(cand, os.X_OK):
            return cand
    return None


def _compile_dir(src: pathlib.Path) -> dict:
    """Compile every .workflow.ts in `src` once; return {stem: workflow-dict}."""
    if src in _CACHE:
        return _CACHE[src]
    if not WRAP.exists():
        raise CompileError(
            "the transformer is missing at %s — cannot read blueprints as code" % WRAP)
    node = _node()
    if node is None:
        raise CompileError(
            "no `node` found, and blueprints are TypeScript. Gates that read a blueprint need "
            "the same toolchain `bbox n8n push` uses. Looked at $NODE_BIN, PATH, "
            "~/.local/bin/node, /usr/local/bin/node, /usr/bin/node. Install node or set "
            "NODE_BIN=/path/to/node.")
    out = tempfile.mkdtemp(prefix="n8n-bp-")
    _TMP.append(out)
    # wrap.mjs self-installs its toolchain (npm ci) on first use and is chatty about it; its
    # stdout is progress, not data, so it is captured and only surfaced when it fails.
    r = subprocess.run([node, str(WRAP), "compile", str(src), out],
                       capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        raise CompileError("wrap.mjs could not compile %s:\n%s"
                           % (src.relative_to(REPO) if src.is_relative_to(REPO) else src,
                              (r.stdout + r.stderr).strip()[-2000:]))
    got = {}
    for p in pathlib.Path(out).glob("*.json"):
        try:
            got[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ex:      # a compiler that emits non-JSON is a real bug
            raise CompileError("wrap.mjs emitted invalid JSON for %s: %s" % (p.name, ex))
    _CACHE[src] = got
    return got


def load(path) -> dict:
    """Read one blueprint. `path` may be repo-relative or absolute, and MUST be .workflow.ts."""
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = REPO / p
    name = p.name

    if name.endswith(".json"):
        raise CompileError(
            "%s is a JSON blueprint path. Blueprints are code since 52b32aa4 — ask for "
            "%s instead." % (path, name[:-len(".json")] + ".workflow.ts"))
    if not name.endswith(".workflow.ts"):
        raise CompileError("%s is not a .workflow.ts blueprint" % path)
    if not p.exists():
        raise CompileError("no such blueprint: %s" % path)

    stem = name[:-len(".workflow.ts")]
    compiled = _compile_dir(p.parent.resolve())
    if stem not in compiled:
        raise CompileError(
            "%s compiled, but produced no %s.json — the workflow id inside the file does not "
            "match its filename." % (path, stem))
    return compiled[stem]


def load_many(paths) -> dict:
    """{path: dict} for several blueprints; directories are still compiled once each."""
    return {str(x): load(x) for x in paths}


# ── self-test ────────────────────────────────────────────────────────────────────────────────
#: Proving a reader CAN fail is part of shipping it (GATES.md, "Adding a gate", step 3).
def _self_test() -> int:
    fails = []

    def check(label, cond):
        if not cond:
            fails.append(label)

    # A .json path must be REFUSED with a message naming the .workflow.ts to ask for instead —
    # this is the whole "no dual-format reader" decision, so it is the first thing asserted.
    try:
        load("apps/indox/blueprint/n8n/indoxV2BSTest01.json")
        check("json path refused", False)
    except CompileError as ex:
        check("json path refused", "indoxV2BSTest01.workflow.ts" in str(ex))

    for bad, label in ((REPO / "README.md", "non-blueprint refused"),
                       ("apps/indox/blueprint/n8n/doesNotExist01.workflow.ts", "missing refused")):
        try:
            load(bad)
            check(label, False)
        except CompileError:
            check(label, True)

    # The real thing, if the toolchain is here. Skipped (not failed) where node is absent, so
    # this stays runnable on a host that cannot compile.
    if _node() and WRAP.exists():
        try:
            wf = load("apps/indox/blueprint/n8n/indoxV2BSTest01.workflow.ts")
            check("returns a dict", isinstance(wf, dict))
            check("has nodes", isinstance(wf.get("nodes"), list) and len(wf["nodes"]) > 0)
            check("has connections", "connections" in wf)
            check("node shape", all({"name", "type"} <= set(n) for n in wf["nodes"]))
            d = (REPO / "apps/indox/blueprint/n8n").resolve()
            check("directory cached once", d in _CACHE)
            load("apps/indox/blueprint/n8n/indoxV2DocBaseTest01.workflow.ts")
            check("second read reuses the cache", len(_CACHE) == 1)
        except CompileError as ex:
            fails.append("compile round-trip: %s" % str(ex)[:200])
    else:
        print("  (no node found — compile round-trip skipped, refusal cases still checked)")

    total = 8 if _node() else 3
    print("n8n_blueprint self-test: %d/%d passed" % (total - len(fails), total))
    for f in fails:
        print("  FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    # Blueprints carry Hebrew and emoji (node names like "🏁 Test Summary"). A Windows
    # console defaults to the ANSI codepage - cp1255 on a Hebrew install - and dumping there dies
    # with UnicodeEncodeError partway through, which reads as a compile failure when the compile
    # in fact succeeded. Force UTF-8 on our own streams; the platform must behave the same on all
    # three OSes.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # already-wrapped or non-tty stream
            pass
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    if len(sys.argv) > 1:
        json.dump(load(sys.argv[1]), sys.stdout, indent=2, ensure_ascii=False)
        sys.exit(0)
    sys.exit(__doc__ and print(__doc__.strip()) or 0)
