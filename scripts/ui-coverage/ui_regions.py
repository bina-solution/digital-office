#!/usr/bin/env python3
"""
ui_regions.py — AUTO-DERIVE the UI-region denominator from source.

The whole point of the map is to work like test coverage: the denominator must come from the
SOURCE, not a hand-written list of views. A hand-list can only contain UI a human remembered —
so a pane nobody listed isn't "0% covered", it's invisible to the metric (exactly how the INDOX
extraction panes looked fine while being completely uncaptured).

This scrapes every first-party app's front-end for the significant, STATE-BEARING regions it can
render — the drawers/modals/panels/tabs/canvases the code shows, hides, or renders into — and
returns them per app with a source file:line. report.py uses this as the visible-region
denominator, so an un-photographed pane surfaces as an *uncovered region with its source location*
instead of disappearing. The reveal-recipes in inventory.py stop being the denominator and become
just "tests" that drive the numerator up.

A region is keyed exactly the way capture.py's REGION_PROBE keys a live element (`#<id>`), so the
static denominator and the runtime numerator are the same universe and the ratio is honest.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The front-end source of each first-party app (same files the inventory extractors trust).
APP_SOURCES: dict[str, list[str]] = {
    "console":         ["platform-base/console/static/index.html",
                        "platform-base/console/static/app.js"],
    "my-docs":         ["apps/my-docs/static/index.html",
                        "apps/my-docs/static/app.js"],
    "connections":     ["platform-base/connections/ui.html"],
    "mailview":        ["apps/mail/mailview/static/index.html",
                        "apps/mail/mailview/static/app.js"],
    "drive":      ["apps/drive/static/index.html",
                        "apps/drive/static/app.js"],
    "machine":         ["platform-base/machine/static/index.html"],
    "notifications":   ["platform-base/notifications/static/index.html"],
    "any-concurrency": ["apps/any-concurrency/static/index.html"],
}

# ids that exist in the DOM but are never a "region a user looks at": the app shell/frame, the
# hidden file inputs behind upload labels, script/style anchors, and pure form fields. Excluding
# them keeps the denominator to things that CAN be shown, so 100% stays reachable.
EXCLUDE = {
    "app", "root", "main", "frame", "content", "body", "page", "shell", "view",
    "csrf", "token", "fileInput", "file", "upload", "uploadInput", "filePicker",
}
EXCLUDE_SUFFIX = ("Input", "Field", "Csrf", "Token", "File")

# a state-bearing region is one the code SHOWS / HIDES / RENDERS INTO. If an id is only ever read
# for its .value it's an input, not a region — these verbs are what separate the two.
VERBS = re.compile(
    r"classList|\.hidden\b|style\.display|style\.opacity|innerHTML|insertAdjacent|append(Child)?|"
    r"showModal\b|\.show\b|\.open\b|removeAttribute\(['\"]hidden|setAttribute\(['\"]open|"
    r"scrollIntoView|\.close\(|hidden\s*=\s*(false|true)|\.style\.")

# significant markup: an id sitting on one of these tags (or a region-ish class) is a region even
# if the JS never toggles it — same significance test the runtime probe uses.
REGION_TAG = re.compile(r"<(dialog|aside|details|canvas|table|form|section|nav)\b[^>]*\bid=", re.I)
REGION_CLS = re.compile(
    r"(drawer|modal|dialog|overlay|panel|card|tab|timeline|accordion|collaps|menu|dropdown|"
    r"popover|sheet|toast|sidebar|hud|detail|editor|list|grid|chart|filter|wizard|step|pane|box)",
    re.I)

_ID_HTML = re.compile(r"""\bid\s*=\s*["']([A-Za-z][\w-]*)["']""")
_ID_JS_GET = re.compile(r"""getElementById\(\s*["']([A-Za-z][\w-]*)["']""")
_ID_JS_SEL = re.compile(r"""querySelector(?:All)?\(\s*["']#([A-Za-z][\w-]*)""")
# NOTE: object-literal `id:"x"` (with a COLON) is intentionally NOT scanned. It is DATA — a tab/chip
# definition like {id:"auth",label:…} or {id:"all",…} that renders class-based nav (onclick="setLevel('all')"),
# never a DOM element with id="auth". Any id that IS a real DOM region already matches _ID_HTML /
# _ID_JS_GET / _ID_JS_SEL, so scanning object literals only ever added phantom regions that can never be
# "shown" — understating coverage (notifications #all/#error/#info/#warning, connections #auth/#infra/
# #app-password were exactly these). The denominator must count regions the DOM can render, not config rows.
# template ids: id="ex_${...}" / id=`it_${...}` / getElementById('pv_'+x) -> component prefix "ex_*"
_ID_TMPL = re.compile(r"""(?:id\s*=\s*|getElementById\(\s*|querySelector\(\s*['"]?#?)"""
                      r"""[`"']([A-Za-z][\w-]*?_)(?:\$\{|['"`]?\s*\+)""")


def _norm(pfx_counts: dict[str, int], key: str) -> str:
    """Collapse a per-row component (#ex_12, #ex_34, …) to one key #ex_* — same rule report.py
    applies to the runtime probe, so the two sides match."""
    if key.startswith("#") and "_" in key:
        pre = key.split("_", 1)[0]
        if pfx_counts.get(pre, 0) >= 3:
            return pre + "_*"
    return key


# an id declared on one of these tags is a control/value/anchor, not a region a user "looks at".
# `datalist` included: a <datalist> is an invisible autocomplete option source, never rendered.
_INPUT_TAG = re.compile(r"""<(input|option|select|textarea|script|style|meta|link|label|template|datalist)\b"""
                        r"""[^>]*\bid\s*=\s*["']%s["']""")


def _is_datalist(idv: str, text: str) -> bool:
    """True if `idv` is a <datalist> — an autocomplete option source that never renders visually,
    whether written as <datalist id=…> or built in JS (createElement('datalist'); el.id=…) and
    referenced by an input's list= attribute. Counting it can never reach 100% (nothing to show)."""
    e = re.escape(idv)
    return bool(
        re.search(r"""<datalist[^>]*\bid\s*=\s*["']%s["']""" % e, text, re.I) or
        re.search(r"""\blist\s*=\s*["'`]%s\b""" % e, text) or
        re.search(r"""setAttribute\(\s*["']list["']\s*,\s*["']%s["']""" % e, text) or
        re.search(r"""createElement\(\s*["']datalist["']\s*\)[^;]{0,120}\.id\s*=\s*["']%s["']""" % e, text)
    )


def _is_region(idv: str, text: str) -> bool:
    """Inclusive by design: a declared id IS a candidate region unless it's an input/wrapper/anchor.

    The earlier version required a show/hide verb within ~200 chars of the id, which dropped real
    panes whose toggle lived far from their markup (e.g. mailview #rDoc). Missing a pane is the one
    failure mode this whole file exists to prevent, so we default to INCLUDE and only subtract the
    things a screenshot metric should never count: the shell/frame, hidden file inputs, form fields,
    and elements declared on a non-visual tag. An always-visible button simply reads as "shown" and
    never blocks 100% — an un-rendered pane is what must stay in the denominator."""
    if idv in EXCLUDE or idv.endswith(EXCLUDE_SUFFIX):
        return False
    if re.search(_INPUT_TAG.pattern % re.escape(idv), text, re.I):
        return False
    if _is_datalist(idv, text):
        return False
    return True


def regions_for(app: str) -> dict[str, str]:
    """Return {region_key: 'file:hint'} for one app, keyed like the runtime probe (#id / #pre_*)."""
    out: dict[str, str] = {}
    raw: dict[str, str] = {}          # id -> source file
    prefixes: dict[str, str] = {}     # 'ex_' -> source file (template components)
    for rel in APP_SOURCES.get(app, []):
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for rx in (_ID_HTML, _ID_JS_GET, _ID_JS_SEL):
            for m in rx.finditer(text):
                idv = m.group(1)
                if idv not in raw and _is_region(idv, text):
                    raw[idv] = rel
        for m in _ID_TMPL.finditer(text):
            prefixes.setdefault(m.group(1), rel)
    # component prefixes always collapse to a single #pre_* key (one editor repeated per row)
    pfx_counts = {("#" + pre.rstrip("_")): 99 for pre in prefixes}
    for idv, rel in raw.items():
        # if this concrete id belongs to a known template prefix, fold it in
        folded = False
        for pre in prefixes:
            if idv.startswith(pre):
                out[_norm(pfx_counts, "#" + idv)] = rel
                folded = True
                break
        if not folded:
            out["#" + idv] = rel
    for pre, rel in prefixes.items():
        out["#" + pre + "*"] = rel
    return out


# floors ~half the observed count: if a source file is moved/renamed the scan would silently
# return few/zero regions, shrinking the denominator and FAKING high coverage. Fail loud instead.
_FLOOR = {"console": 8, "my-docs": 20, "connections": 8, "mailview": 12, "drive": 18,
          "machine": 12, "notifications": 6, "any-concurrency": 10}


class RegionDriftError(RuntimeError):
    pass


def all_regions(check: bool = True) -> dict[str, dict[str, str]]:
    out = {app: regions_for(app) for app in APP_SOURCES}
    if check:
        for app, floor in _FLOOR.items():
            n = len(out.get(app, {}))
            if n < floor:
                raise RegionDriftError(
                    f"{app}: source-region scan found {n} regions (floor {floor}) — a source file "
                    f"likely moved/renamed ({', '.join(APP_SOURCES[app])}); the denominator would "
                    f"be understated and coverage falsely inflated. Fix the path or the floor.")
    return out


if __name__ == "__main__":
    total = 0
    for app, regs in all_regions().items():
        total += len(regs)
        sample = ", ".join(sorted(regs)[:12])
        print(f"{app:<16} {len(regs):>3} regions  | {sample}")
    print(f"\nTOTAL source-derived regions: {total}")
