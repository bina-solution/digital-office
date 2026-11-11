#!/usr/bin/env python3
"""ops-faces-lint — gate G117: every operation an app declares has its faces (DGO-1246).

    python3 scripts/refactor/ops-faces-lint.py              # warn: each op with a face missing, named; exit 0
    python3 scripts/refactor/ops-faces-lint.py --strict     # …and exit 1 when one is missing (the next stage)
    python3 scripts/refactor/ops-faces-lint.py --self-test  # prove each finding can be made, on fixtures

WHY THIS EXISTS. An app declares its operations once, as app.json `ops` (DGO-1244): one route of its API each.
The standard (ai/context/app-cli-api-standard.md §3) wants the same op behind every face: the route, the CLI
verb, the screen's action. Both compilers check what a manifest alone can say (its keys, its endpoint, a verb's
NAME). What needs the rest of the checkout is held here, because validate also runs on trees that carry a
manifest without its hooks (the store's index, the twins' test trees), and it refused all of them when it looked
(measured on vps1, 2026-11-11).

WHAT IT SAYS, per op of every manifest under apps/ and platform-base/:
  verb   no verb: the op is reached by `bbox <app> api` (DGO-1245) and by no verb of its own. Or a verb whose
         hook bbox cannot run. bbox takes the FIRST entry that exists of hooks/<verb>, .sh, .py, .mjs, and when
         that is a directory the verb fails. When none exists, `bbox <app> <verb>` answers «unknown», unless the
         app's `cli.fallback` answers it. A fallback answers only as bbox runs it: text that is not the app's own
         id, with hooks/<fallback> itself a file. The verb `api` is the generic caller's, before any fallback.
  ui     no screen action: the op is reached by no button or tab a person sees.
The ROUTE face (the office answers the op) needs a running office, and is the next stage (the live lane). It
prints the apps and ops it read and each face's count. Reading no manifest at all fails at every stage: a wrong
root is no pass.

STAGES (GATES.md, «Tightening a contract»): this one warns, exit 0, and the report is the parity table. `--strict`
fails on any missing face, for when the ops are filled in. A manifest that cannot be read, or `ops` that is not a
list, is the compilers' own refusal (validate), and is not re-judged here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("apps", "platform-base")
HOOK_EXTS = ("", ".sh", ".py", ".mjs")      # bbox's own order (bbox: the app dispatch)
VERB_NAME = re.compile(r"[a-z][a-z0-9-]{0,40}")   # reconcile.py's: a verb that is not one is validate's refusal


def manifests(root: Path):
    """(app dir, manifest) for every readable app.json, in a stable order."""
    for r in ROOTS:
        for p in sorted((root / r).glob("*/app.json")):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(m, dict):
                yield p.parent, m


def faces(app_dir: Path, m: dict) -> list:
    """[(op id, face, why)] of one app: each face an op lacks."""
    ops = m.get("ops")
    if not isinstance(ops, list):
        return []
    hooks = app_dir / "hooks"
    cli = m.get("cli") if isinstance(m.get("cli"), dict) else {}
    # a fallback answers only as bbox runs it: text, not the app's own id (bbox drops that), and hooks/<fallback>
    # itself a file — bbox runs exactly that path, no extension tried
    fb = cli.get("fallback")
    fallback = isinstance(fb, str) and bool(fb) and fb != m.get("id") and (hooks / fb).is_file()
    out = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        oid = str(op.get("id") or f"ops[{i}]")
        verb = op.get("verb")
        # bbox takes the FIRST entry that exists, in its order ("" .sh .py .mjs), a directory included
        first = (next((hooks / f"{verb}{e}" for e in HOOK_EXTS if (hooks / f"{verb}{e}").exists()), None)
                 if isinstance(verb, str) and VERB_NAME.fullmatch(verb) else None)
        if not isinstance(verb, str) or not verb:
            out.append((oid, "verb", f"no verb: `bbox {m.get('id')} api {op.get('method', '')} {op.get('path', '')}` "
                                     f"reaches it, no verb of its own does"))
        elif not VERB_NAME.fullmatch(verb):
            pass                                      # not a verb's name: validate refuses it (never a path here)
        elif first is not None and not first.is_file():
            out.append((oid, "verb", f"bbox finds hooks/{first.name} first, and it is not a file — "
                                     f"`bbox {m.get('id')} {verb}` fails"))
        elif first is not None:
            pass                                      # its hook is the verb (an app's own hooks/api wins, too)
        elif verb == "api":
            # bbox takes `api` for the generic caller (DGO-1245) before any fallback: the op's verb is never reached
            out.append((oid, "verb", f"`bbox {m.get('id')} api` is the generic caller, not this op: give the op "
                                     f"a verb of its own, or a hooks/api file"))
        elif not fallback:
            out.append((oid, "verb", f"`bbox {m.get('id')} {verb}` has no file in hooks/ — it answers «unknown»"))
        if not isinstance(op.get("ui"), str) or not op.get("ui").strip():
            out.append((oid, "ui", "no screen action reaches it"))
    return out


def report(root: Path) -> tuple:
    """(lines, missing, apps read, apps with ops, ops read)."""
    lines, missing, n_apps, n_with, n_ops = [], 0, 0, 0, 0
    counts = {"verb": 0, "ui": 0}
    for app_dir, m in manifests(root):
        n_apps += 1
        ops = m.get("ops") if isinstance(m.get("ops"), list) else []
        if not ops:
            continue
        n_with += 1
        n_ops += sum(1 for o in ops if isinstance(o, dict))
        for oid, face, why in faces(app_dir, m):
            missing += 1
            counts[face] += 1
            lines.append(f"  {m.get('id')}.{oid}  {face:<4}  {why}")
    head = (f"{n_apps} app(s) read, {n_with} declare ops, {n_ops} op(s): "
            f"{counts['verb']} without a verb face, {counts['ui']} without a screen action")
    return [head] + lines, missing, n_apps, n_with, n_ops


def self_test() -> int:
    import tempfile
    bad = 0
    with tempfile.TemporaryDirectory(prefix="g117-") as d:
        root = Path(d)

        def app(aid, manifest, hooks=(), where="apps"):
            p = root / where / aid
            (p / "hooks").mkdir(parents=True, exist_ok=True)
            for h in hooks:
                if h.endswith("/"):
                    (p / "hooks" / h.rstrip("/")).mkdir()
                else:
                    (p / "hooks" / h).write_text("")
            (p / "app.json").write_text(json.dumps({"id": aid} | manifest), encoding="utf-8")

        op = {"id": "tags", "method": "GET", "path": "/api/tags", "access": "read"}
        fbk = {"cli": {"fallback": "state"}}
        app("full", {"ops": [op | {"verb": "tags", "ui": "the models tab"}]}, hooks=["tags.py"])
        app("nohook", {"ops": [op | {"verb": "tags", "ui": "x"}]}, hooks=["tags/", "tags.py"])   # bbox finds the dir
        app("noverb", {"ops": [op | {"ui": "x"}]})
        app("noui", {"ops": [op | {"verb": "tags"}]}, hooks=["tags"])
        app("fallback", fbk | {"ops": [op | {"verb": "anything", "ui": "x"}]}, hooks=["state"])
        app("fbnofile", fbk | {"ops": [op | {"verb": "anything", "ui": "x"}]})
        app("fbpy", fbk | {"ops": [op | {"verb": "anything", "ui": "x"}]}, hooks=["state.py"])  # bbox runs hooks/state
        app("fbself", {"cli": {"fallback": "fbself"}, "ops": [op | {"verb": "anything", "ui": "x"}]}, hooks=["fbself"])
        app("shadow", fbk | {"ops": [op | {"verb": "api", "ui": "x"}]}, hooks=["state"])
        app("ownapi", {"ops": [op | {"verb": "api", "ui": "x"}]}, hooks=["api.sh"])
        app("mjs", {"ops": [op | {"verb": "tags", "ui": "x"}]}, hooks=["tags.mjs"])
        app("badname", {"ops": [op | {"verb": "Bad Name", "ui": "x"}]})        # validate's refusal, not this gate's
        app("blankui", {"ops": [op | {"verb": "tags", "ui": "   "}]}, hooks=["tags"])
        app("none", {})
        app("broken", {"ops": "not a list"})
        app("pb", {"ops": [op | {"verb": "tags"}]}, hooks=["tags"], where="platform-base")
        (root / "platform-base" / "bad").mkdir(parents=True)
        (root / "platform-base" / "bad" / "app.json").write_text("{not json")
        found = {}
        for app_dir, m in manifests(root):
            found[m["id"]] = [(o, f) for o, f, _ in faces(app_dir, m)]
        verb, ui = [("tags", "verb")], [("tags", "ui")]
        cases = [
            ("an op with every face passes; a .mjs hook is a verb", found.get("full") == [] and found.get("mjs") == []),
            ("a directory bbox finds before the file is said", found.get("nohook") == verb),
            ("an op with no verb is said, as reachable by `api`", found.get("noverb") == verb),
            ("an op with no screen action, or one of blanks, is said", found.get("noui") == ui and
             found.get("blankui") == ui),
            ("cli.fallback answers every verb, only as bbox runs it", found.get("fallback") == [] and
             found.get("fbnofile") == verb and found.get("fbpy") == verb and found.get("fbself") == verb),
            ("a verb `api` the generic caller shadows is said; an app's own hooks/api is its verb",
             found.get("shadow") == verb and found.get("ownapi") == []),
            ("a verb that is not a verb's name is validate's, not said here", found.get("badname") == []),
            ("an app with no ops, or ops that are not a list, holds none", found.get("none") == [] and
             found.get("broken") == []),
            ("platform-base is read; an unreadable manifest is passed over", found.get("pb") == ui
             and "bad" not in found),
        ]
        lines, missing, n_apps, n_with, n_ops = report(root)
        cases.append(("the report counts what it read", (n_apps, n_with, n_ops, missing) == (16, 14, 14, 9)
                      and lines[0].startswith("16 app(s) read, 14 declare ops, 14 op(s): 6 without a verb face, "
                                              "3 without a screen action")))
        # the stage: warn exits 0, --strict exits 1 on a missing face; reading nothing fails at every stage
        cases.append(("warn passes and --strict fails on a missing face",
                      run(root, strict=False) == 0 and run(root, strict=True) == 1))
        cases.append(("reading nothing fails, warn or strict",
                      run(root / "nothing", strict=False) == 1 and run(root / "nothing", strict=True) == 1))
    for name, ok in cases:
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"ops-faces-lint self-test: {len(cases) - bad}/{len(cases)} " + ("passed" if not bad else "FAILED"))
    return 1 if bad else 0


def run(root: Path, strict: bool, out=None) -> int:
    lines, missing, n_apps, *_ = report(root)
    if n_apps == 0:                       # reading nothing is no pass, at any stage (a wrong root, an empty checkout)
        if out is not None:
            print(f"G117 FAIL — read no manifest under {', '.join(ROOTS)} of {root}", file=out)
        return 1
    if out is not None:
        verdict = ("PASS" if not missing else "FAIL" if strict else "PASS (warn)")
        print(f"G117 {verdict} — " + lines[0], file=out)
        for ln in lines[1:]:
            print(ln, file=out)
        if missing and not strict:
            print("  stage 1 warns (DGO-1246): each line is a face to give the op; --strict fails on them", file=out)
    return 1 if (missing and strict) else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
    return run(ROOT, strict="--strict" in argv, out=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
