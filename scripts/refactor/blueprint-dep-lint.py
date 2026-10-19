#!/usr/bin/env python3
"""
blueprint-dep-lint — gate G13: an app that SHIPS automations must DECLARE that it needs the automation engine.

`blueprints.n8n` means "these workflows are mine; import them when I'm installed". That is only
true if the workflow engine is actually part of the app's closure. drive, mail and
chat each shipped an API-router workflow while declaring no `use: workflow`, so the
capability graph allowed enabling them with n8n absent: the app would come up, its router would
never be imported, and every caller (indox calls all three) would fail at runtime against a route
that silently does not exist.

The provider itself is exempt — the n8n app supplies `workflow`, it does not consume it.

    python3 scripts/refactor/blueprint-dep-lint.py [--strict]
"""
import json, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
ROOTS = ("apps", "platform-base")
CAP = "workflow"          # capability the n8n app provides
HARD = {"requires", "requisite", "binds_to"}


def caps_of(app):
    out = set()
    for c in app.get("capabilities") or []:
        out.add(c if isinstance(c, str) else c.get("name"))
    return out


def main():
    bad, checked = [], 0
    for root in ROOTS:
        for m in sorted((REPO / root).glob("*/app.json")):
            try:
                app = json.loads(m.read_text(encoding="utf-8"))
            except Exception as e:
                bad.append(f"{m.relative_to(REPO).as_posix()}: unreadable ({e})")
                continue
            if not ((app.get("blueprints") or {}).get("n8n") or "").strip():
                continue
            checked += 1
            aid = app.get("id", m.parent.name)
            if CAP in caps_of(app):      # the engine itself
                continue
            hard = {(u if isinstance(u, str) else u.get("capability"))
                    for u in (app.get("use") or [])
                    if isinstance(u, str) or u.get("strength", "requires") in HARD}
            if CAP not in hard:
                bad.append(f"{aid}: declares blueprints.n8n but does not `use` "
                           f"'{CAP}' with a hard strength — its workflows would never be "
                           f"imported if the engine is disabled")

    if bad:
        print(f"G13 FAIL — {len(bad)} app(s) ship automations without depending on the engine:")
        for b in bad:
            print(f"  {b}")
        print("  -> add {\"capability\": \"workflow\", \"strength\": \"requires\", \"after\": true} to use[]")
        return 1
    print(f"G13 PASS — every app shipping a blueprint depends on the workflow engine "
          f"({checked} blueprint-shipping app(s) checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
