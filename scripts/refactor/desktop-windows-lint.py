#!/usr/bin/env python3
"""desktop-windows-lint — gate G81: every screen is looked at in the window desktop mode opens it in.

    python3 scripts/refactor/desktop-windows-lint.py            # the static half
    python3 scripts/refactor/desktop-windows-lint.py --live     # …and the suites, run on this office
    python3 scripts/refactor/desktop-windows-lint.py --self-test

THE BUG (the owner, 2026-10-07: «כל מקביל כרגע ממש בלתי שמיש בדסקטופ ובמובייל… אתה חייב להתחיל
לעשות צילומי מסך כשהקונסול במצב דסקטופ»). Desktop mode opens an app in a window of about 580 x 530,
and a person drags its corner in to 380 x 260. Every flow suite and both maps looked at a screen in
the classic shell's full frame, and all of them were green while the timeline had 2 of its window's
530 pixels. flow-qa's `windows` suite looks where a person does — but a suite is run by whoever
remembers it: `connect`, the other one only a running office can answer, was red for a day and
broken again by a card's change before anybody ran it.

WHAT THIS CHECKS, in two halves:

  * STATIC (every gate run, no stack): what the suite stands on is still there —
      - flow-qa.py has the `windows` suite and it is not live-only (the default run covers it);
      - the simulation's builder runs a page's scripts as script ELEMENTS: through `(0,eval)` the
        shell's desktop.js could not see app.js's `let MODULES`, and every window was empty;
      - the three shared blocks keep their short-frame tiers (the page block: a one-line heading and
        the numbers as a strip; the side menu: a short panel scrolls whole; the question: its title
        and its buttons stay in sight and only what is read scrolls);
      - a screen's own dialog is whole: its card has a bound (unbounded, «הוספת סוד חדש» had its
        title and both buttons outside the smallest window with nothing to scroll), and where the
        card scrolls whole its header (`.modal-h`, or the card's own `h3`) is sticky — a form
        taller than its window ended at its last field with neither the title nor the way out
        (measured 2026-10-09: 11 dialog/size pairs on two screens).
  * LIVE (`--live`, the live lane): the suites are RUN against this office, in a browser of the
    gate's own behind the edge — `windows` (every screen the shell offers, in the window as opened
    and in its smallest, photographed to digital-office/sim/ui-map/windows-live/) and `connect` at
    both sizes when the office has dgo-extend. A failed check fails. A console error fails — unless
    its page is one that cannot work behind the edge (BEHIND_THE_EDGE), which is named and not
    counted. A run with no checks is not a pass.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

import office_browser

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
SUITE = "digital-office/sim/flow-qa.py"

#: (suite, extra flags, the service it is aimed at, its port, must the office have it)
RUNS = [
    ("windows", [], "console", 8000, True),
    ("connect", [], "dgo-extend", 8983, False),
    ("connect", ["--mobile"], "dgo-extend", 8983, False),
]

#: A framed page that cannot work where this gate stands. The gate comes in BEHIND the edge — no
#: TLS, and none of the edge's own routes — so that it needs no one's session. Named on every run.
BEHIND_THE_EDGE = {
    "browser42": "noVNC needs TLS and the edge's websocket route; behind the edge there is neither "
                 "(the tile's raw failure page is DGO-437)",
}


def read(rel: str) -> str:
    try:
        return (REPO / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


#: a dialog's header as a page's stylesheet names it: a header row of its own, or the card's own heading
DIALOG_HEAD = r"(?m)^\.modal(?:-h| h3)\{([^}]*)\}"


def dialog_pages() -> dict[str, str]:
    """Every screen that has a dialog header of its own, by path -> its page."""
    found: dict[str, str] = {}
    for pattern in ("apps/*/static/index.html", "apps/*/*/static/index.html", "platform-base/*/static/index.html",
                    "platform-base/*/ui.html"):
        for p in sorted(REPO.glob(pattern)):
            text = p.read_text(encoding="utf-8", errors="replace")
            if re.search(DIALOG_HEAD, text):
                found[p.relative_to(REPO).as_posix()] = text
    return found


def static_findings(suite: str, builder: str, page: str, nav: str, ask: str, dialogs: dict[str, str]) -> list[str]:
    bad: list[str] = []
    if not re.search(r"SUITES\s*=\s*\{[^}]*'windows'\s*:\s*window_flows", suite):
        bad.append(f"{SUITE} has no `windows` suite in SUITES — nothing looks at a screen in desktop mode")
    live_only = re.search(r"LIVE_ONLY\s*=\s*\{([^}]*)\}", suite)
    if live_only and "'windows'" in live_only.group(1):
        bad.append(f"{SUITE} marks `windows` live-only — the simulation's default run would skip desktop mode")
    inline = re.search(r"const inlineJs\s*=.*", builder)
    if not inline:
        bad.append("digital-office/sim/build.mjs no longer defines inlineJs — how a page's scripts are inlined changed its name")
    elif "eval)(" in inline.group(0) or 'createElement("script")' not in inline.group(0):
        bad.append("digital-office/sim/build.mjs runs a page's scripts through eval, not as script elements: "
                   "a file's top-level let/const is hidden from the others, and every desktop-mode window is empty")
    if not re.search(r"@media \(max-height:699px\)\{[^@]*\.pg-sub:not\(\[data-live\]\)\{display:none\}", page):
        bad.append("bina-page.css lost its short-frame heading (one line, the sentence steps aside)")
    if not re.search(r"@media \(max-height:699px\),\(max-width:700px\)\{\s*\.pg-kpis\{gap:1px", page):
        bad.append("bina-page.css lost the strip its leading numbers become in a short frame")
    if not re.search(r"@media \(max-height:399px\)\{[^@]*\.bnv-scroll\{flex:none;overflow:visible\}", nav):
        bad.append("bina-nav.css lost the short panel that scrolls whole")
    if ".bask-read{overflow:auto}" not in ask or "@media (max-height:399px){.bask{padding:8px}" not in ask:
        bad.append("bina-ask.js lost the question's short frame (the title and the buttons stay, only what is read scrolls)")
    for rel, text in dialogs.items():
        card = re.search(r"(?m)^\.modal\{([^}]*)\}", text)
        head = re.search(DIALOG_HEAD, text)
        if not card or not head:
            continue
        if "max-height" not in card.group(1):
            bad.append(f"{rel}: its dialog's card has no bound — taller than its frame, its title and its buttons are "
                       "outside it and nothing scrolls")
        elif "flex-direction:column" not in card.group(1) and "position:sticky" not in head.group(1):
            bad.append(f"{rel}: its dialog scrolls whole and the header is not sticky — at the end of a long form "
                       "the title and the way out are out of sight")
    return bad


def verdict(out: str) -> tuple[bool, str, list[str]]:
    """(passed, one line, the pages named and not counted) from a flow-qa run's output."""
    m = re.search(r"(\d+)/(\d+) flows passed", out)
    if not m:
        last = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
        return False, "the suite did not finish" + (f": {last[0][:140]}" if last else ""), []
    passed, total = int(m.group(1)), int(m.group(2))
    if total == 0:
        return False, "ran no check — a suite that looked at nothing is not a pass", []
    failed = [ln.strip()[6:].strip() for ln in out.splitlines() if ln.startswith("  FAIL  ")]
    errors = re.findall(r"(?m)^\s+x\d+\s+(.*)$", out)
    named: set[str] = set()
    own: list[str] = []
    for e in errors:
        page = re.match(r"console:\[a/([\w.-]+)/", e)
        if page and page.group(1) in BEHIND_THE_EDGE:
            named.add(page.group(1))
        else:
            own.append(e[:150])
    said = f"{passed} of {total} checks"
    if failed:
        return False, f"{said} — {len(failed)} failed, first: {failed[0][:150]}", sorted(named)
    if own:
        return False, f"{said}, and {len(own)} error(s) of the office's own pages, first: {own[0]}", sorted(named)
    return True, said, sorted(named)


def live() -> tuple[list[str], list[str], list[str]]:
    """(what passed, what failed, what could not be run) — one line each."""
    ok: list[str] = []
    bad: list[str] = []
    skip: list[str] = []
    run, inside, why = office_browser.lane()
    if run is None:
        return ok, bad, [f"{why} — desktop mode was NOT looked at in this run"]
    for suite, flags, service, port, must in RUNS:
        name = " ".join([suite, *flags])
        url = office_browser.url(service, port, inside)
        if not url:
            (bad if must else skip).append(f"{name}: no running {service} on this office" + ("" if must else " — not run"))
            continue
        try:
            r = subprocess.run([*run, SUITE, suite, *flags, "--url", url], cwd=REPO, capture_output=True,
                               text=True, timeout=1500, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            bad.append(f"{name}: the suite timed out")
            continue
        passed, said, named = verdict((r.stdout or "") + (r.stderr or ""))
        for page in named:
            said += f" · {page}'s own errors named, not counted: {BEHIND_THE_EDGE[page]}"
        (ok if passed else bad).append(f"{name}: {said}")
    return ok, bad, skip


GOOD = "  PASS  windows/alerts has content in its window\n\n154/154 flows passed\nJS errors: 0\n"
SUITE_OK = "SUITES = {'drive': drive_flows, 'windows': window_flows}\nLIVE_ONLY = {'connect'}\n"
BUILD_OK = 'const inlineJs = js => `<script>(s=>{s.text=x})(document.createElement("script"))</script>`;\n'
PAGE_OK = ("@media (max-height:699px){\n  .pg-sub:not([data-live]){display:none}\n}\n"
           "@media (max-height:699px),(max-width:700px){\n  .pg-kpis{gap:1px}\n}\n")
NAV_OK = "@media (max-height:399px){\n  .bnv{overflow-y:auto}\n  .bnv-scroll{flex:none;overflow:visible}\n}\n"
ASK_OK = '+ ".bask-read{overflow:auto}"\n+ "@media (max-height:399px){.bask{padding:8px}.bask-card{padding:12px}}"\n'
#: the two shapes a dialog may have: its card scrolls under a sticky header, or it is a column whose body scrolls
DIALOGS_OK = {"apps/a/static/index.html": ".modal{max-height:92vh;overflow:auto}\n.modal-h{display:flex;position:sticky;\n  top:-22px}\n",
              "apps/b/static/index.html": ".modal{max-height:82vh;display:flex;flex-direction:column}\n.modal-h{display:flex}\n.modal-b{overflow:auto}\n"}


def self_test() -> int:
    noise = ("  PASS  windows/browser42 has content in its window\n\n154/154 flows passed\nJS errors: 2\n"
             "    x1  console:[a/browser42/view/vnc.html] WebSocket connection failed   [first after: x]\n"
             "    x1  console:[a/browser42/app/ui.js] Failed when connecting   [first after: x]\n")
    cases = [
        ("every check passed, no error", verdict(GOOD)[0] is True),
        ("a failed check fails", verdict("  FAIL  windows/concurrency the timeline is most of its window — 2px of 530\n"
                                         "118/119 flows passed\nJS errors: 0\n")[0] is False),
        ("a run with no checks is not a pass", verdict("0/0 flows passed\nJS errors: 0\n")[0] is False),
        ("a suite that did not finish is not a pass", verdict("Traceback (most recent call last):\n  boom\n")[0] is False),
        ("a page that cannot work behind the edge is named, not counted",
         verdict(noise)[0] is True and verdict(noise)[2] == ["browser42"]),
        ("an error of one of the office's own pages fails",
         verdict(noise + "    x1  console:[a/alerts/] TypeError: x is undefined   [first after: y]\n")[0] is False),
        ("an uncaught error with no page fails", verdict(GOOD.replace("JS errors: 0", "JS errors: 1")
                                                         + "    x1  ReferenceError: MODULES is not defined\n")[0] is False),
        ("the tree as it should be has no static finding", static_findings(SUITE_OK, BUILD_OK, PAGE_OK, NAV_OK, ASK_OK, DIALOGS_OK) == []),
        ("scripts run through eval are refused",
         len(static_findings(SUITE_OK, 'const inlineJs = js => `<script>(0,eval)(atob("x"))</script>`;\n', PAGE_OK, NAV_OK, ASK_OK, {})) == 1),
        ("a suite marked live-only is refused",
         len(static_findings(SUITE_OK.replace("{'connect'}", "{'connect', 'windows'}"), BUILD_OK, PAGE_OK, NAV_OK, ASK_OK, {})) == 1),
        ("a missing suite is refused", len(static_findings("SUITES = {'drive': drive_flows}\n", BUILD_OK, PAGE_OK, NAV_OK, ASK_OK, {})) == 1),
        ("a page block without its short tiers is refused (both)", len(static_findings(SUITE_OK, BUILD_OK, "", NAV_OK, ASK_OK, {})) == 2),
        ("a menu without its short panel is refused", len(static_findings(SUITE_OK, BUILD_OK, PAGE_OK, "", ASK_OK, {})) == 1),
        ("a question whose card scrolls whole is refused",
         len(static_findings(SUITE_OK, BUILD_OK, PAGE_OK, NAV_OK, '+ ".bask-card{max-height:calc(100vh - 32px);overflow:auto}"\n', {})) == 1),
        ("a question without its short frame is refused",
         len(static_findings(SUITE_OK, BUILD_OK, PAGE_OK, NAV_OK, '+ ".bask-read{overflow:auto}"\n', {})) == 1),
        ("a dialog that scrolls whole under a header that is not sticky is refused, and named",
         static_findings(SUITE_OK, BUILD_OK, PAGE_OK, NAV_OK, ASK_OK,
                         {"apps/x/static/index.html": ".modal{max-height:92vh;overflow:auto}\n.modal-h{display:flex;margin-bottom:14px}\n"})
         [0].startswith("apps/x/static/index.html: its dialog scrolls whole")),
        ("a dialog whose card has no bound is refused — also when its heading is the card's own h3",
         static_findings(SUITE_OK, BUILD_OK, PAGE_OK, NAV_OK, ASK_OK,
                         {"platform-base/x/ui.html": ".modal{padding:24px;width:min(460px,92vw)}\n.modal h3{margin:0 0 16px}\n"})
         [0].startswith("platform-base/x/ui.html: its dialog's card has no bound")),
    ]
    for name, good in cases:
        print(f"  [{'ok ' if good else 'FAIL'}] {name}")
    n = sum(1 for _, g in cases if g)
    print(f"\ndesktop-windows-lint self-test: {n}/{len(cases)} passed")
    return 0 if n == len(cases) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also run the suites against this office")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    print("desktop-windows-lint — every screen in the window desktop mode opens it in")
    bad = static_findings(read(SUITE), read("digital-office/sim/build.mjs"), read("platform-base/bina-ui/bina-page.css"),
                          read("platform-base/bina-ui/bina-nav.css"), read("platform-base/bina-ui/bina-ask.js"), dialog_pages())
    for b in bad:
        print(f"  FAIL  {b}")
    if not bad:
        print("  PASS  static: the `windows` suite is in the default run, the simulation runs a page's "
              "scripts as script elements, the shared blocks keep their short-frame tiers, and a dialog keeps its header")
    if a.live:
        ok, red, skip = live()
        for line in ok:
            print(f"  PASS  {line}")
        for line in red:
            print(f"  FAIL  {line}")
        for line in skip:
            print(f"  SKIP  {line}")
        bad += red
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
