#!/usr/bin/env python3
"""score.py — the "beauty score": turn the capture's in-page audit into one number per view.

WHY A SCORE AT ALL. "The apps should look unified and not break at any size" is not a
measurable statement, and a redesign driven by taste cannot be verified — every session would
declare victory. So the audit in capture.py measures the things a broken layout actually
produces (a page wider than its frame, text cut with no way to reach it, a 26px target on a
phone, four greens that are not the same green), and this file weighs them into 0-100.

It is a DIAGNOSTIC, not a grade of taste: it cannot see whether a screen is pleasant, only
whether it is intact and consistent. That is exactly the part of "looks perfect everywhere"
that can be automated, and it is the part that regresses silently today.

Dimensions (see ai/context/ui-program-plan.md §1):
   layout      25  the document is not wider than its frame; nothing is painted past the edge
   clipping    15  no content is cut off inside a box with no scrollbar
   touch       10  interactive targets are big enough for the pointer in use
   type        15  no sub-11px text, no crushed line-height, a short font-size list
   contrast    15  text meets AA against its own effective background
   consistency 10  headings/buttons/colours match the platform's own mode      (cross-app)
   states      10  the screen actually rendered something usable

Run:  python3 scripts/ui-coverage/score.py [--data data/ui-map] [--out ci-artifacts]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DIMENSIONS = ["layout", "clipping", "touch", "type", "contrast", "consistency", "states"]
MAX = {"layout": 25, "clipping": 15, "touch": 10, "type": 15,
       "contrast": 15, "consistency": 10, "states": 10}

# Touch: a coarse pointer (phone/tablet) gets the 44px WCAG target; a mouse gets slack.
TARGET_PX = {"mobile": 44, "tablet": 44, "desktop": 28}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def load_results(data: Path) -> tuple[list, str]:
    merged = data / "ui-capture-results.json"
    if merged.exists():
        return json.loads(merged.read_text(encoding="utf-8")).get("results", []), "merged"
    out = []
    for f in sorted(data.glob("ui-capture-results.*.json")):
        out += json.loads(f.read_text(encoding="utf-8")).get("results", [])
    return out, "shards"


def per_view(r: dict, profile: str) -> dict | None:
    """The five dimensions that need only this view's own audit."""
    a = r.get("audit")
    if not isinstance(a, dict) or not a.get("ok"):
        return None
    target = TARGET_PX.get(profile, 28)

    # layout — a page wider than its frame is the failure the whole program exists for
    overflow = int(a.get("pageOverflow") or 0)
    layout = MAX["layout"] * (1.0 if overflow == 0 else _clamp(1 - overflow / 160))

    # Counts, not the displayed samples. `counts` is absent on captures taken before it existed —
    # fall back to the sample list so an old artefact still scores something instead of crashing.
    c = a.get("counts") or {}
    elements = int(a.get("elements") or 0)
    interactive = int(a.get("interactive") or 0)
    text_nodes = int(a.get("textNodes") or 0)

    # clipping — content cut inside a non-scrollable box, or painted past the edge.
    # RATIO, because three cuts in a 2,600-element screen is a much smaller defect than three in 40.
    cut = int(c.get("clip", len(a.get("clipped") or []))) + int(c.get("spill", len(a.get("spilling") or [])))
    denom_clip = max(40, elements)
    clipping = MAX["clipping"] * _clamp(1 - cut / (denom_clip * 0.02))

    # touch — share of interactive targets that are big enough
    small = int(c.get("small", len(a.get("smallTargets") or [])))
    touch = MAX["touch"] * (1.0 if interactive == 0 else _clamp(1 - small / interactive + 0.1))

    # type — SHARE of text that is below 11px, crushed leading, and a font-size list that has
    # stopped being a scale. A screen may legitimately carry a 10.5px badge; carrying 400 of them
    # is the defect, and only a share can tell those apart.
    tiny = int(c.get("tiny", len(a.get("tinyText") or [])))
    squeezed = int(c.get("squeezed", len(a.get("lowLineHeight") or {})))
    fonts = len(a.get("fonts") or {})
    tiny_share = (tiny / text_nodes) if text_nodes else 0.0
    # Crushed leading is also a SHARE: a page of 213 text blocks with 31 tight ones is a different
    # screen from one with 31 tight ones out of 34, and the first version scored them the same.
    squeeze_share = (squeezed / text_nodes) if text_nodes else 0.0
    type_ = (MAX["type"] * _clamp(1 - tiny_share * 1.6)
             - MAX["type"] * 0.5 * _clamp(squeeze_share * 3)
             - max(0, fonts - 8))
    type_ = max(0, min(MAX["type"], type_))

    # contrast — share of text that misses AA, plus a penalty for a page that invented its own palette
    fails = int(c.get("contrast", len(a.get("contrastFails") or [])))
    colours = int(a.get("distinctTextColors") or 0)
    fail_share = (fails / text_nodes) if text_nodes else 0.0
    contrast = MAX["contrast"] * _clamp(1 - fail_share * 2.0) - max(0, colours - 6)
    contrast = max(0, min(MAX["contrast"], contrast))

    # states — did a screen render at all
    elements = int(a.get("elements") or 0)
    states = MAX["states"] * _clamp(elements / 120) if elements else 0.0

    return {"layout": round(layout, 1), "clipping": round(clipping, 1),
            "touch": round(touch, 1), "type": round(type_, 1),
            "contrast": round(contrast, 1), "states": round(states, 1),
            "_raw": {"overflow": overflow, "cut": cut, "small": small, "interactive": interactive,
                     "tiny": tiny, "texts": text_nodes, "squeezed": squeezed, "fonts": fonts,
                     "target": (a.get("target") or TARGET_PX.get(profile, 28)),
                     "contrast": fails, "colours": colours, "elements": elements}}


def consistency_scores(views: list[dict]) -> None:
    """The ONE cross-app dimension: does an app use the platform's own vocabulary?

    Measured against the platform's own mode, not an ideal we wrote down: the most common h1
    size, the most common button height and the most common text colour across every app are,
    by definition, what the platform already looks like. An app that disagrees is the outlier
    a person actually notices ("this screen looks like a different product").
    """
    h1 = Counter(), Counter()
    btns, cols, btn_heights = Counter(), Counter(), []
    for r in views:
        a = r.get("audit") or {}
        if not a.get("ok"):
            continue
        h = (a.get("headings") or {}).get("H1")
        if h:
            h1[0][h] += 1
        for c, n in (a.get("textColors") or []):
            cols[c] += n
        heights = [int(h) for h, _ in (a.get("buttonHeights") or [])]
        btn_heights.append(heights)
        for hgt, n in (a.get("buttonHeights") or []):
            btns[int(hgt)] += n
    mode_h1 = h1[0].most_common(1)[0][0] if h1[0] else None
    # The platform's button height is the MEDIAN of each view's own most-common height, not the
    # global count mode: one screen with two hundred 15px inline buttons would otherwise define
    # "the platform's button" and mark every honest 36px button as the outlier.
    per_view_btn = [int(Counter(hh).most_common(1)[0][0]) for hh in btn_heights if hh]
    mode_btn = int(statistics.median(per_view_btn)) if per_view_btn else None
    mode_cols = {c for c, _ in cols.most_common(8)}

    for r in views:
        a = r.get("audit") or {}
        s = r.get("_score")
        if not s or not a.get("ok"):
            continue
        score = MAX["consistency"]
        h = (a.get("headings") or {}).get("H1")
        if h and mode_h1 and abs(h - mode_h1) > 2:
            score -= 3
        heights = [int(x) for x, _ in (a.get("buttonHeights") or [])]
        if heights and mode_btn and all(abs(x - mode_btn) > 6 for x in heights):
            score -= 3
        own = {c for c, _ in (a.get("textColors") or [])[:3]}
        if own and not (own & mode_cols):
            score -= 2
        s["consistency"] = round(max(0, score), 1)
    return {"h1": mode_h1, "button": mode_btn, "palette": sorted(mode_cols)[:8]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/ui-map")
    ap.add_argument("--out", default="ci-artifacts")
    ap.add_argument("--profile", default="")
    a = ap.parse_args()

    data = Path(a.data)
    # `--profile` wins; otherwise the data dir's own name carries it (data/ui-map/mobile);
    # otherwise desktop. The first version wrote this as a one-liner whose precedence
    # silently threw --profile away and scored a phone run against mouse thresholds.
    profile = a.profile or (data.name if data.name in TARGET_PX else "desktop")
    if profile not in TARGET_PX:
        profile = "desktop"
    results, source = load_results(data)
    if not results:
        print(f"no capture results in {data} — run `bbox ui-map` first")
        return 2

    scored = []
    for r in results:
        if r.get("status") != "captured":
            continue
        s = per_view(r, profile)
        if not s:
            continue
        r["_score"] = s
        scored.append(r)
    if not scored:
        print("no audited views — the capture may predate the audit probe")
        return 2

    modes = consistency_scores(scored)

    for r in scored:
        s = r["_score"]
        s["total"] = round(sum(s[k] for k in DIMENSIONS), 1)

    by_app = defaultdict(list)
    for r in scored:
        by_app[r["app"]].append(r["_score"]["total"])
    app_med = {app: round(statistics.median(v), 1) for app, v in by_app.items()}
    platform = round(statistics.median([r["_score"]["total"] for r in scored]), 1)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": profile,
        "source": source,
        "platform_score": platform,
        "apps": app_med,
        "views": [{"app": r["app"], "id": r["id"], "title": r.get("title"),
                   "score": r["_score"]["total"], **{k: r["_score"][k] for k in DIMENSIONS},
                   "raw": r["_score"]["_raw"]} for r in sorted(scored, key=lambda x: x["_score"]["total"])],
        "platform_modes": modes,
    }
    (out / "ui-score.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"profile={profile}  views scored={len(scored)}  platform median={platform}/100")
    print(f"platform modes: h1={modes['h1']}px button={modes['button']}px palette={len(modes['palette'])} colours\n")
    print(f"{'app':22s} {'median':>6s} {'worst':>6s}  views")
    for app, med in sorted(app_med.items(), key=lambda kv: kv[1]):
        worst = min(r["_score"]["total"] for r in scored if r["app"] == app)
        n = len([r for r in scored if r["app"] == app])
        flag = "  <-- below 70" if worst < 70 else ""
        print(f"{app:22s} {med:6.1f} {worst:6.1f}  {n:5d}{flag}")
    worst5 = sorted(scored, key=lambda x: x["_score"]["total"])[:8]
    print("\nworst views:")
    for r in worst5:
        s = r["_score"]
        print(f"  {s['total']:5.1f}  {r['app']:20s} {r['id']:24s} "
              f"L{s['layout']:.0f} C{s['clipping']:.0f} T{s['touch']:.0f} "
              f"Y{s['type']:.0f} K{s['contrast']:.0f} U{s['consistency']:.0f} S{s['states']:.0f} "
              f"| {s['_raw']}")
    print(f"\nwrote {out/'ui-score.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
