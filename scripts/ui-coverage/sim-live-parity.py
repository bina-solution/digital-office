#!/usr/bin/env python3
"""sim-live-parity — every panel, every component: what the simulation renders and live does not.

    python3 scripts/ui-coverage/sim-live-parity.py --profile desktop
    python3 scripts/ui-coverage/sim-live-parity.py --all --json ci-artifacts/parity.json

WHY NOT EYEBALLING
------------------
"Port until the ui-map is identical" is only a finishable task if there is a number that has to
reach zero. Comparing screenshots by eye finds the differences someone happened to look for, and
silently passes every panel nobody opened. This computes the difference instead.

THE DENOMINATOR IS NOT WRITTEN HERE
-----------------------------------
The panel list is IMPORTED from digital-office/sim/ui-map.py, the same list that generates the sim
map — so the comparison cannot examine a different set of panels than the map contains, and a panel
added there joins this report without anyone remembering to. That is the same trick view-profiles.yaml
plays for viewports: declare the thing once, read it twice.

Coverage is reported against that full list. A panel whose live counterpart could not be reached is
reported as UNREACHED with the reason, never dropped — a comparison that quietly skips what it could
not open reports 100% and means nothing.

WHAT A "COMPONENT" IS HERE
--------------------------
The visible class tokens of the rendered DOM, per panel. Concretely: for every element that is
actually visible (has layout boxes), every class token it carries, unioned into a set.

Class tokens are the right granularity because this codebase's UI IS its class vocabulary — .acctbar,
.gm-star, .dosw-menu, .hc-reason are components, and their presence is exactly the question "did the
port bring this component across". Deliberately a SET, not counts: a panel showing 3 rows in the sim
and 40 live is the same component, and counting would drown the signal in data volume.

Text is not compared. Two panels showing different messages are the same component rendering
different data, and the live platform legitimately holds different data from the fixtures — which
PORT-PLAN.md is explicit about not porting.

READ THE OUTPUT AS
------------------
    missing   in the sim, not live   -> port work remaining. This is the number that must reach 0.
    extra     in live, not the sim   -> live is ahead, or drifted. Each needs a decision, not a fix.
"""
from __future__ import annotations

import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SIM_DIR = REPO / "digital-office" / "sim"
SIM_HTML = REPO / "digital-office" / "platform-sim.html"
PROFILES_YAML = HERE / "view-profiles.yaml"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# Class tokens that say nothing about which COMPONENT is on screen: state flags, layout utilities and
# the framework noise every panel carries. Comparing these produces a diff that is technically true
# and completely useless — "live is missing .hidden" is not port work.
NOISE = re.compile(
    r"^(hidden|active|on|off|open|closed|sel|selected|cur|current|done|show|hide|is-|has-|"
    r"ng-|v-|js-|sw|chk|grow|muted|num|spin|row|col|left|right|top|bottom|center|"
    r"[a-z]{1,2}|.*\d{3,}|.*[0-9a-f]{6,})$"
)


def load_panels():
    """Import PANELS from the sim's own map generator, so the two cannot disagree about the list."""
    spec = importlib.util.spec_from_file_location("simuimap", SIM_DIR / "ui-map.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["simuimap"] = mod
    spec.loader.exec_module(mod)
    if not getattr(mod, "PANELS", None):
        raise SystemExit("ui-map.py exposed no PANELS — the denominator would be empty, refusing")
    return mod.PANELS


def load_profiles():
    import yaml
    doc = yaml.safe_load(PROFILES_YAML.read_text(encoding="utf-8"))
    return doc["profiles"], doc.get("default", "desktop")


# Runs inside the page. Walks the console document AND every same-origin frame, because the whole
# point of this shell is that an app renders inside an iframe — a component inventory that stops at
# the frame boundary would report the shell and call it the platform.
COLLECT = r"""
() => {
  const seen = new Set();
  const walk = (doc) => {
    if (!doc || !doc.querySelectorAll) return;
    for (const el of doc.querySelectorAll('*')) {
      // visible = actually laid out. display:none subtrees and never-opened menus are NOT components
      // on this panel; counting them would let a panel "have" every modal it can theoretically open.
      if (!el.getClientRects().length) continue;
      const cls = el.getAttribute && el.getAttribute('class');
      if (!cls || typeof cls !== 'string') continue;
      for (const t of cls.split(/\s+/)) if (t) seen.add(t);
    }
    for (const f of doc.querySelectorAll('iframe')) {
      try { walk(f.contentDocument); } catch (e) { /* cross-origin: nothing to read, not an error */ }
    }
  };
  walk(document);
  return [...seen];
}
"""


# A component that was ported under a different class name is PORTED. Comparing raw tokens would
# report it missing forever and no amount of work would close the gap.
#
# Kept deliberately tiny, explicit, and one-directional (sim token -> live token). It is not a fuzzy
# matcher and must never become one: every entry here is a way for a real gap to disappear, so each
# has to name a component someone can point at in both trees. The `do-` prefix means "digital-office
# overlay" — a sim-ism that has no business in production class names, which is why these differ.
ALIAS = {
    "do-version": "build",          # sim overlay/brand.js  ->  console .side .build
    "do-skip": "skiplink",          # sim overlay/responsive.js -> console .skiplink
}


# Components the simulation still renders that live has DELIBERATELY superseded. These are counted
# and shown, but separately from `missing`, because lumping them in overstates the remaining work by
# a few hundred and — worse — makes the number stop falling as real work lands.
#
# `dosw-*` is the whole in-app account switcher from sim/overlay/switcher.js. C15 moved that control
# into the console's top bar precisely so every app would stop carrying its own; porting it back into
# each app is the opposite of the intended end state. It appears on ~20 panels, so it dominates the
# count while representing no work at all.
#
# `do-theme*` (sim overlay/theme.js) is the second deliberate removal, and the ALIAS entries that
# used to point it at the console's `.themesw` were deleted with the control: on the owner's request
# (2026-09-25) the console's top bar lost its palette MENU, together with #hint and #installPill
# beside it. There is no live counterpart to port toward, so counting it as a gap would report the
# same two tokens on every panel forever.
#
# Anything listed here needs a reason in this comment. A superseded set that grows without
# justification is just a way of making a metric look better.
SUPERSEDED = re.compile(r"^(dosw(-|$)|do-theme(-btn)?$)")


def useful(tokens):
    return {ALIAS.get(t, t) for t in tokens if not NOISE.match(t.lower())}


def split_superseded(missing):
    """(real gaps, deliberately-superseded) — both reported, only the first counted as work."""
    sup = [t for t in missing if SUPERSEDED.match(t)]
    return [t for t in missing if not SUPERSEDED.match(t)], sup


def capture(pw, url, panels, prof, is_live):
    """Return {index: {'tokens': set|None, 'reason': str|None}} for every panel in the list."""
    from playwright.sync_api import Error as PWError

    out = {}
    b = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    for i, (label, mod, action) in enumerate(panels):
        ctx = b.new_context(viewport={"width": prof["width"], "height": prof["height"]},
                            device_scale_factor=prof.get("dsf", 1),
                            is_mobile=prof.get("is_mobile", False),
                            has_touch=prof.get("has_touch", False))
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        rec = {"tokens": None, "reason": None, "action_ok": True,
               "label": label, "module": mod, "js_errors": []}
        try:
            # Navigate EXACTLY the way ui-map.py does: load the bare document, then set the hash.
            # Going straight to url+"#/m/drive" looks equivalent and is not — the hash arrives as part
            # of the initial navigation, so no `hashchange` fires and the console stays on the
            # launcher. The first version of this file did that, and the result was 25 of 43 sim
            # actions timing out against a screen that had never left the dashboard, while the report
            # cheerfully said "43/43 reached".
            pg.goto(url, wait_until="load", timeout=45000)
            pg.wait_for_timeout(500)
            pg.evaluate(f"location.hash = {json.dumps(mod)}")
            pg.wait_for_timeout(2800)
            if action:
                try:
                    action(pg, pg.frame_locator("#frame"))
                    pg.wait_for_timeout(1200)
                except Exception as e:                      # noqa: BLE001 — recorded, not raised
                    # An action that fails is a finding either way: LIVE it means the component is
                    # not reachable there; on the SIM side it means the panel never reached the state
                    # it is named for. Either way the comparison for this panel is between two
                    # screens that are not the panel, so it MUST NOT be scored as a match.
                    rec["action_ok"] = False
                    rec["reason"] = f"action failed: {type(e).__name__}: {str(e)[:120]}"
            rec["tokens"] = sorted(useful(pg.evaluate(COLLECT)))
            rec["js_errors"] = errs[:3]
        except PWError as e:
            rec["reason"] = f"navigation failed: {str(e)[:140]}"
        except Exception as e:                              # noqa: BLE001
            rec["reason"] = f"{type(e).__name__}: {str(e)[:140]}"
        out[i] = rec
        ctx.close()
    b.close()
    return out


def live_base():
    """The console's container IP. Deliberately NOT the traefik host: that is SSO-gated, and this
    tool must never need an operator's password to run.

    WHICH container is one rule for every tool that looks at a running office
    (scripts/refactor/office_browser.py: the compose service of THIS checkout). A harness that
    cannot find a running service is worse than one that fails loudly on a real gap, because the
    message points at the wrong thing.
    """
    _sys.path.insert(0, str(REPO / "scripts" / "refactor"))
    import office_browser
    return office_browser.url("console", 8000, False)


def run_profile(pname, prof, panels, live_url, want_json):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        sim = capture(pw, "file://" + str(SIM_HTML) + "", panels, prof, is_live=False)
        live = capture(pw, live_url, panels, prof, is_live=True)

    rows, tot_missing = [], 0
    reached = 0
    for i, (label, mod, _a) in enumerate(panels):
        s, l = sim[i], live[i]
        st, lt = s.get("tokens"), l.get("tokens")
        row = {"panel": i, "label": label, "module": mod,
               "sim_reason": s.get("reason"), "live_reason": l.get("reason"),
               "live_js_errors": l.get("js_errors") or []}
        raw = sorted(set(st) - set(lt)) if (st is not None and lt is not None) else []
        miss, superseded = split_superseded(raw)
        row["missing"], row["superseded"] = miss, superseded
        row["extra"] = sorted(set(lt) - set(st)) if (st is not None and lt is not None) else []
        if st is None or lt is None:
            row["status"] = "UNREACHED"
        elif not s.get("action_ok", True):
            # The SIM never reached the state this panel is named for, so there is nothing to compare
            # against. Scoring it would be scoring the dashboard twice and calling drive's details
            # pane covered.
            row["status"] = "SIM-ACTION-FAILED"
            row["missing"] = []
            row["extra"] = []
        elif not l.get("action_ok", True):
            # The sim reached it and live did not: that IS the finding. Whatever tokens live did show
            # are not evidence of parity, so the panel counts as unmet, not as a partial match.
            row["status"] = "LIVE-ACTION-FAILED"
            tot_missing += max(len(miss), 1)
            reached += 1
        else:
            reached += 1
            row["status"] = "MATCH" if not miss else "GAP"
            tot_missing += len(miss)
        rows.append(row)

    print(f"\n══ {pname}  ({prof['width']}×{prof['height']})  — {len(panels)} panels")
    marks = {"MATCH": "ok  ", "GAP": "GAP ", "UNREACHED": "MISS",
             "SIM-ACTION-FAILED": "SIM?", "LIVE-ACTION-FAILED": "LIVE"}
    for r in rows:
        detail = ""
        if r["status"] == "GAP":
            show = r["missing"][:8]
            detail = f"  -{len(r['missing'])}: " + " ".join(show) + (" …" if len(r["missing"]) > 8 else "")
        elif r["status"] == "SIM-ACTION-FAILED":
            detail = "  sim never reached this state — not scored: " + (r["sim_reason"] or "")[:70]
        elif r["status"] == "LIVE-ACTION-FAILED":
            detail = "  live could not reach it: " + (r["live_reason"] or "")[:70]
        elif r["status"] == "UNREACHED":
            detail = "  " + (r["live_reason"] or r["sim_reason"] or "unknown")
        print(f"  {marks[r['status']]} {r['panel']:02d}  {r['label'][:46]:46}{detail}")
        for e in r["live_js_errors"]:
            print(f"        live JS error: {e[:110]}")

    matched = sum(1 for r in rows if r["status"] == "MATCH")
    simfail = sum(1 for r in rows if r["status"] == "SIM-ACTION-FAILED")
    tot_sup = sum(len(r.get("superseded") or []) for r in rows)
    print(f"\n  panels scored: {reached}/{len(panels)}"
          f"   ·  component-complete: {matched}/{reached if reached else 1}"
          f"   ·  missing components: {tot_missing}")
    if tot_sup:
        print(f"  (+{tot_sup} deliberately superseded — the sim's in-app switcher, replaced by the "
              f"console-owned one in C15. Shown, not counted as work.)")
    if simfail:
        # Loud, because it is the failure mode that makes this whole report a lie: a panel the SIM
        # could not open is not a passing panel, it is an unmeasured one.
        print(f"  ⚠ {simfail} panel(s) NOT SCORED — the simulation itself never reached the state. "
              f"Those panels are unmeasured, not passing.")
    if want_json:
        want_json.parent.mkdir(parents=True, exist_ok=True)
        want_json.write_text(json.dumps({"profile": pname, "rows": rows}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"  json -> {want_json}")
    return tot_missing, reached, len(panels)


def main():
    profiles, default = load_profiles()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=sorted(profiles), default=default)
    ap.add_argument("--all", action="store_true", help="every profile in view-profiles.yaml")
    ap.add_argument("--json", type=pathlib.Path, help="write the full per-panel report")
    ap.add_argument("--url", help="live console base URL (default: the console container's IP)")
    a = ap.parse_args()

    url = a.url or live_base()
    if not url:
        raise SystemExit("no live console reachable — pass --url")
    panels = load_panels()
    names = sorted(profiles) if a.all else [a.profile]

    total_missing = 0
    for n in names:
        out = a.json if (a.json and len(names) == 1) else (
            a.json.with_name(a.json.stem + f"-{n}" + a.json.suffix) if a.json else None)
        miss, _r, _t = run_profile(n, profiles[n], panels, url, out)
        total_missing += miss

    print(f"\nTOTAL missing components across {len(names)} profile(s): {total_missing}")
    # Non-zero while anything is missing: this is the number the port drives to zero, so it has to be
    # able to fail a pipeline once it reaches it.
    return 1 if total_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
