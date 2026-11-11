#!/usr/bin/env python3
"""reporter-target-lint — gate G98: an error reporter runs only when its target is configured, and the
office's own notice board is always one of its targets.

    python3 scripts/refactor/reporter-target-lint.py [<tree>] [--self-test]

WHY THIS EXISTS. Measured on Exampleu, a client office, 2026-11-09 (DGO-1574, with DGO-1495): the
blueprint's Error Handler (`errorHandler01`) sent every error's text to Telegram with whatever
`TELEGRAM_BOT_TOKEN` held — on that office a placeholder — so the text reached Telegram's servers
before the token was refused, and to GlitchTip at a host the office does not run. The CI probe
`ciHelloWebhook01` was active with a public webhook on an office whose CI runs elsewhere. None of the
three had any business running there, and two of the three sent text OFF the office.

WHAT MAKES IT STAY FIXED — the committed default, not the hook. `bbox n8n push all` runs
`apps/n8n/hooks/push`, which rewrites the staged files from `.env` (`gate_telegram_notifier`,
`gate_glitchtip_reporter`, `gate_ci_hello`). The everyday verb `bbox n8n push <app>` does NOT — it
compiles the blueprint and updates it. So a gate that lived only in the hook would be one verb away
from being bypassed, and the safe answer has to be the FILE. That is what this gate reads:

  1. `errorHandler01`: the Telegram node is committed `disabled: true`, and the GlitchTip send sits
     behind a `GEN:REPORT_GATE` block whose committed verdict is `REPORTING_ENABLED = false` (plus a
     `DISABLED_REASON` a person can read). The hook may only flip those two from an explicit `.env`.
  2. `errorHandler01`: a node posts the error to the office's OWN notifications
     (`http://notifications:8977/api/notifications`) — the one sink every office runs, so a failure is
     never lost when both reporters are off. It must be `onError: continueRegularOutput`: an error
     reporter that can itself raise re-entered this handler in a measured 1,205:1,481 cycle (RCA
     2026-08-06).
  3. `ciHelloWebhook01`: committed `active: false`. `gate_ci_hello` is the only thing that turns it on.
  4. `apps/n8n/hooks/push` CALLS all three reporter gates. A definition nobody calls is a gate that
     does not run — the failure mode this repo has already paid for once.

It deliberately does not enumerate "every node that can reach the internet": a list nobody maintains
is a list that lies. What it holds is the three reporters whose destination was measured wrong.
"""
import argparse
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLER = "apps/n8n/blueprint/n8n/errorHandler01.workflow.ts"
CI_PROBE = "apps/n8n/blueprint/n8n/ciHelloWebhook01.workflow.ts"
PUSH = "apps/n8n/hooks/push"
GATE_CALLS = ("gate_telegram_notifier", "gate_glitchtip_reporter", "gate_ci_hello")
LOCAL_NOTICE_URL = "http://notifications:8977/api/notifications"


def read(root, rel):
    p = pathlib.Path(root) / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def scan(root, min_blueprints=40):
    findings = []
    handler = read(root, HANDLER)
    if handler is None:
        return [f"{HANDLER}: missing — the Error Handler is where every reporter is declared"], 0

    # 1a. the Telegram node is committed OFF
    tg = re.search(r"name: 'Telegram',(.*?)\n    \}\)", handler, re.S)
    if not tg:
        findings.append(f"{HANDLER}: no 'Telegram' node — if the reporter is gone, delete this rule with it")
    elif not re.search(r"^\s*(?:/\*__n8n__\*/\s*)?disabled: true,\s*$", tg.group(1), re.M):
        # anchored to a PARAMETER LINE: the node's notes quote the words "disabled:true" in prose, and
        # a file-wide search for them passed a node that was actually enabled (found in review).
        findings.append(f"{HANDLER}: the Telegram node is not committed `disabled: true` — a push that "
                        f"does not run hooks/push would send every error's text to Telegram")

    # 1b. the GlitchTip verdict is a committed `false`, inside a marker the hook rewrites
    if handler.count("GEN:REPORT_GATE:BEGIN") != 1 or handler.count("GEN:REPORT_GATE:END") != 1:
        findings.append(f"{HANDLER}: expected exactly one GEN:REPORT_GATE block (found "
                        f"{handler.count('GEN:REPORT_GATE:BEGIN')} begin / {handler.count('GEN:REPORT_GATE:END')} end) "
                        f"— without it gate_glitchtip_reporter rewrites nothing and the reporter stays as committed")
    else:
        block = handler.split("GEN:REPORT_GATE:BEGIN", 1)[1].split("GEN:REPORT_GATE:END", 1)[0]
        if "const REPORTING_ENABLED = false;" not in block:
            findings.append(f"{HANDLER}: GEN:REPORT_GATE must commit `const REPORTING_ENABLED = false;`")
        if not re.search(r"const DISABLED_REASON = [\'\"].+[\'\"]", block):
            findings.append(f"{HANDLER}: GEN:REPORT_GATE carries no DISABLED_REASON — a skip must say why")

    # 2. the office's own notice board, always on, never able to raise
    # ANCHORED TO THE `url:` PARAMETER, not to any occurrence of the string: the node's own notes quote
    # the address in prose, so a file-wide search passed a node whose url was pointed elsewhere
    # (proven in review by pointing it at an outside host — G98 still said PASS).
    url_params = re.findall(r"url:\s*'([^']+)'", handler)
    if LOCAL_NOTICE_URL not in url_params:
        findings.append(f"{HANDLER}: no node's `url:` is {LOCAL_NOTICE_URL} — with both reporters off, an "
                        f"error would land nowhere a person in this office can see")
    # the decorator's options sit ABOVE the node body, so look on both sides of that url parameter
    i = handler.find(f"url: '{LOCAL_NOTICE_URL}'")
    around = handler[max(0, i - 900):i + 900] if i >= 0 else ""
    if around and "onError: 'continueRegularOutput'" not in around:
        findings.append(f"{HANDLER}: the local-notice node must carry onError: 'continueRegularOutput'")

    # 3. the CI probe is committed OFF
    probe = read(root, CI_PROBE)
    if probe is None:
        findings.append(f"{CI_PROBE}: missing")
    else:
        act = re.search(r"^\s*active: (true|false),", probe, re.M)
        if not act:
            findings.append(f"{CI_PROBE}: no `active:` line")
        elif act.group(1) != "false":
            findings.append(f"{CI_PROBE}: committed `active: true` — it would register a public webhook "
                            f"on every office that runs no CI (gate_ci_hello is the only thing to turn it on)")

    # 4. the three gates are CALLED, not merely defined
    push = read(root, PUSH)
    if push is None:
        findings.append(f"{PUSH}: missing — nothing would decide a reporter's target at push time")
    else:
        for fn in GATE_CALLS:
            if not re.search(rf"^{fn}\s*$", push, re.M):
                findings.append(f"{PUSH}: {fn}() is not called (a definition alone decides nothing)")

    files = list(pathlib.Path(root).glob("apps/*/blueprint/n8n/*.workflow.ts"))
    blueprints = len(files)
    if not files:
        # A gate that passes on an empty scan is green and blind at the same time (unread-error-lint's
        # rule [C], which flagged this file): say it and FAIL, never return a clean list over nothing.
        print("reporter-target-lint — FAIL: no blueprint file was read; a scan that finds nothing "
              "proves nothing")
        raise SystemExit(1)
    elif blueprints < min_blueprints:
        findings.append(f"only {blueprints} blueprint files were read — the tree does not look like this repo")
    return findings, blueprints


def self_test():
    import tempfile
    good_handler = (
        "@node({\n        name: 'Telegram',\n        /*__n8n__*/ notes: \"GATED (optional, default OFF): a note that says disabled: true is not enough\",\n        /*__n8n__*/ disabled: true,\n    })\n"
        "    Telegram = {};\n"
        "{{ GEN:REPORT_GATE:BEGIN\nconst REPORTING_ENABLED = false;\nconst DISABLED_REASON = \"off\";\nGEN:REPORT_GATE:END }}\n"
        "url: 'http://notifications:8977/api/notifications',\n        onError: 'continueRegularOutput',\n"
    )
    good_probe = "    active: false,\n"
    good_push = "\n".join(GATE_CALLS) + "\n"
    checks = []

    def tree(**over):
        d = tempfile.mkdtemp()
        root = pathlib.Path(d)
        (root / "apps/n8n/blueprint/n8n").mkdir(parents=True)
        (root / "apps/n8n/hooks").mkdir(parents=True)
        (root / HANDLER).write_text(over.get("handler", good_handler), encoding="utf-8")
        (root / CI_PROBE).write_text(over.get("probe", good_probe), encoding="utf-8")
        (root / PUSH).write_text(over.get("push", good_push), encoding="utf-8")
        # the denominator: 45 duck-typed blueprint files
        for i in range(45):
            (root / f"apps/n8n/blueprint/n8n/x{i}.workflow.ts").write_text("", encoding="utf-8")
        return root

    f, n = scan(tree(), min_blueprints=0)
    checks.append(("the good tree passes", not f))

    f, _ = scan(tree(handler=good_handler.replace("disabled: true,", "disabled: false,")), min_blueprints=0)
    checks.append(("Telegram enabled is a finding", any("Telegram node is not committed" in x for x in f)))

    f, _ = scan(tree(handler=good_handler.replace("REPORTING_ENABLED = false;", "REPORTING_ENABLED = true;")), min_blueprints=0)
    checks.append(("GlitchTip left on is a finding", any("REPORTING_ENABLED = false" in x for x in f)))

    f, _ = scan(tree(handler=good_handler.replace("GEN:REPORT_GATE:BEGIN", "").replace("GEN:REPORT_GATE:END", "")), min_blueprints=0)
    checks.append(("a missing report gate is a finding", any("GEN:REPORT_GATE block" in x for x in f)))

    f, _ = scan(tree(handler=good_handler.replace(LOCAL_NOTICE_URL, "http://glitchtip:8000/api/11/store/")), min_blueprints=0)
    checks.append(("no local notice is a finding", any("land nowhere" in x for x in f)))

    f, _ = scan(tree(handler=good_handler.replace("onError: 'continueRegularOutput'", "onError: 'stopWorkflow'")), min_blueprints=0)
    checks.append(("a notice that can raise is a finding", any("continueRegularOutput" in x for x in f)))

    f, _ = scan(tree(probe="    active: true,\n"), min_blueprints=0)
    checks.append(("an active CI probe is a finding", any("committed `active: true`" in x for x in f)))

    f, _ = scan(tree(push=GATE_CALLS[0] + "\n" + GATE_CALLS[1] + "\n"), min_blueprints=0)
    checks.append(("an uncalled gate is a finding", any("gate_ci_hello() is not called" in x for x in f)))

    f, n = scan(tree())
    checks.append(("the denominator is counted", n >= 40))

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    return 0 if not bad else 1


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("tree", nargs="?", default=str(REPO))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--min-blueprints", type=int, default=40,
                    help="floor on the number of blueprint files read (rule 8: the denominator, not the "
                         "findings) — lower it only when running the gate against a subtree on purpose")
    a = ap.parse_args(argv)
    if a.self_test:
        rc = self_test()
        print("self-test OK" if rc == 0 else "self-test FAILED")
        return rc
    findings, blueprints = scan(a.tree, min_blueprints=a.min_blueprints)
    if findings:
        print(f"G98 FAIL — {len(findings)} reporter target(s) would run without one:")
        for f in findings:
            print(f"  - {f}")
        return 1
    print(f"G98 PASS — error reporters run only when their target is configured, the office's own notice "
          f"board is a sink, and the CI probe is committed off ({blueprints} blueprint files read).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
