#!/usr/bin/env python3
"""
Proof that the inventory's anti-drift guards actually fire.

A coverage denominator is only trustworthy if it CANNOT silently shrink. The failure
mode we're defending against is: someone edits a UI, the extractor's regex stops
matching, the inventory quietly returns fewer views, and coverage reports a beautiful
100% over a denominator that lost half its screens.

So each case here mutates a source file in memory (never on disk), re-runs the
extractor, and asserts it RAISES instead of returning a smaller list.

Run: python3 scripts/ui-coverage/test_guards.py
"""
from __future__ import annotations
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inv  # noqa: E402

import yaml  # noqa: E402

MAN = yaml.safe_load(inv.MANIFEST.read_text(encoding="utf-8"))
CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


class _Patch:
    """Swap inventory._read for one that mutates a chosen file's contents."""

    def __init__(self, target_rel, mutate):
        self.target_rel, self.mutate, self.orig = target_rel, mutate, inv._read

    def __enter__(self):
        orig = self.orig

        def fake(rel):
            src = orig(rel)
            return self.mutate(src) if rel == self.target_rel else src

        inv._read = fake
        return self

    def __exit__(self, *a):
        inv._read = self.orig


def expect_drift(extractor, target_rel, mutate, why):
    with _Patch(target_rel, mutate):
        try:
            got = extractor(MAN)
        except inv.DriftError as e:
            return True, f"raised DriftError: {str(e)[:90]}"
        except Exception as e:
            return True, f"raised {type(e).__name__} (acceptable: still fails loudly)"
        return False, (f"SILENTLY RETURNED {len(got)} views — {why}")


# ── the guards ───────────────────────────────────────────────────────────────

@case("console: modules.yaml truncated to 2 modules")
def _():
    return expect_drift(
        inv.x_console, "platform-base/console/modules.yaml",
        lambda s: "\n".join(s.splitlines()[:8]),
        "a gutted registry must not pass as a valid inventory")


@case("console: hash-router shape removed from app.js")
def _():
    # (the mutation follows the anchor: the extractor reads the ONE parser of the grammar now, and
    #  breaking the comparison an older router spelled changed nothing — this case had stopped firing)
    return expect_drift(
        inv.x_console, "platform-base/console/static/app.js",
        lambda s: s.replace("parseModuleHash", "parseModuleXX"),
        "if the router changed, #/m/<id> URLs are wrong and must not be emitted")


@case("my-docs: a view deleted from VIEWS but left in the nav")
def _():
    return expect_drift(
        inv.x_my_docs, "apps/my-docs/static/app.js",
        lambda s: s.replace("customers: 'לקוחות', ", ""),
        "the app.js/index.html cross-check must catch a one-sided edit")


@case("my-docs: VIEWS object renamed")
def _():
    return expect_drift(
        inv.x_my_docs, "apps/my-docs/static/app.js",
        lambda s: s.replace("const VIEWS =", "const SCREENS ="),
        "a renamed registry must fail, not yield zero views")


@case("connections: PILLARS array renamed")
def _():
    return expect_drift(
        inv.x_connections, "platform-base/connections/ui.html",
        lambda s: s.replace("const PILLARS=[", "const TABS=["),
        "tab source gone -> extractor must fail")


@case("connections: setTab() removed (tab model changed)")
def _():
    return expect_drift(
        inv.x_connections, "platform-base/connections/ui.html",
        lambda s: s.replace("function setTab(", "function pickTab("),
        "the click recipe would be stale -> must fail")


@case("INDOX: route table shrunk below the floor")
def _():
    def mutate(s):
        out, kept = [], 0
        for ln in s.splitlines():
            if "<Route path=" in ln:
                kept += 1
                if kept > 3:
                    continue
            out.append(ln)
        return "\n".join(out)
    return expect_drift(
        inv.x_incoming, "apps/indox/app/webapp/src/App.tsx",
        mutate, "losing routes must fail rather than shrink the denominator")


@case("mailview: pushState URL shape removed")
def _():
    return expect_drift(
        inv.x_mailview, "apps/mail/mailview/static/app.js",
        lambda s: s.replace("applyUrl", "applyRoute").replace("/^\\/message\\/", "/^\\/msg\\/"),
        "route shape changed -> emitted URLs would 404")


@case("drive: parseUrl() removed")
def _():
    return expect_drift(
        inv.x_localdrive, "apps/drive/static/app.js",
        lambda s: s.replace("function parseUrl()", "function readUrl()"),
        "route parser gone -> must fail")


@case("chat: a modal opener renamed in chat.ejs")
def _():
    # Was: "dashboard sections removed from index.ejs". That page no longer exists — #connect,
    # #users, #settings and #actions were folded into the chat app as modals — so the guard now
    # plants the equivalent mutation one layer over. Renaming an opener is the dangerous case
    # precisely because it is not an error: the view still captures, it just captures the LANDING
    # state and reports coverage of a modal nobody opened.
    return expect_drift(
        inv.x_chat, "apps/chat/src/api/ui/chat.ejs",
        lambda s: s.replace("function openTools(", "function openUtilities("),
        "a renamed opener must fail, not silently screenshot the landing state")


@case("single-view app grows navigation (machine gains tabs)")
def _():
    return expect_drift(
        inv.x_single_view, "platform-base/machine/static/index.html",
        lambda s: s + '\n<a data-view="containers">containers</a>\n',
        "a 'single view' app that grew tabs must force a real extractor")


def main() -> int:
    print("anti-drift guard proof — each case breaks a source shape and expects a failure\n")
    passed = failed = 0
    for name, fn in CASES:
        ok, detail = fn()
        print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {detail}")
        passed, failed = passed + ok, failed + (not ok)
    print(f"\n{passed}/{len(CASES)} guards fire correctly"
          + (f"; {failed} DO NOT — the denominator can silently shrink" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
