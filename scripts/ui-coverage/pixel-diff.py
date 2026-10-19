#!/usr/bin/env python3
"""pixel-diff — where, exactly, does the live platform stop looking like the simulation.

    python3 scripts/ui-coverage/pixel-diff.py --sim digital-office/sim/ui-map/desktop \
                                              --live ci-artifacts/ui-map/desktop
    python3 scripts/ui-coverage/pixel-diff.py --sim .ci-cd/ui-map/screenshots \
                                              --live ci-artifacts/screenshots-ui --pair stem
    python3 scripts/ui-coverage/pixel-diff.py --list-pair-maps

Out: ci-artifacts/pixel-diff/ — one <NN>-<slug>.png per panel (SIM | LIVE | marked DIFF),
     an index.html contact sheet sorted worst-first, and summary.json.

WHY THIS EXISTS ALONGSIDE sim-live-parity.py
--------------------------------------------
sim-live-parity.py answers "is the component THERE" by comparing visible class tokens. That is the
right question for the port and it is the number that has to reach zero, but it is blind to
everything a class token cannot express: a rail that is 238px in the sim and 260px live, a card with
the wrong radius, a table whose rows are 4px taller, a header that lost its border. Every one of
those renders the same class vocabulary and passes parity while looking wrong.

This tool answers the other half: "does it LOOK the same, and if not, WHERE". Its output is
deliberately a picture, because the finding "the toolbar is 6px lower" is instantly obvious in a
marked-up screenshot and nearly unreadable as a number.

WHY IT NEVER TOUCHES A BROWSER
------------------------------
Everything here operates on ALREADY-RENDERED PNGs. Two reasons, and the second is the load-bearing
one:

  1. Rendering and comparing are separate concerns. The renderers already exist (`./bbox ui-map`
     for live, `digital-office/sim/ui-map.py` for the sim) and both are slow, stateful and need a
     running stack. A comparator that re-renders cannot be run on last week's artifacts, cannot be
     run in a PR that only has the artifact download, and cannot be run at all on a machine where
     the stack is down.
  2. This repo is under a standing instruction NOT to drive Playwright. sim-live-parity.py and
     ui-map.py both do, which is why neither can be invoked here. Note in particular that the panel
     labels below are read by PARSING digital-office/sim/ui-map.py as source, never by importing it
     — that module does `from playwright.sync_api import sync_playwright` at top level, so an
     import would drag the banned dependency in through the back door and would ALSO hard-fail on
     any machine that simply doesn't have it. Parsing keeps the single source of truth (a panel
     added to PANELS shows up here with its label, no second list to maintain) without the import.

THE THREE THINGS THAT MAKE A NAIVE PIXEL DIFF USELESS
-----------------------------------------------------
A raw "are these bytes equal" comparison of two real screenshots reports ~100% differing on every
panel and is therefore worth nothing. Each of the three causes is handled explicitly, and each
handler is a place where a real difference could be hidden — so each one is narrow and reported.

  * DIFFERENT SIZE. Live shots come out at the profile's deviceScaleFactor and the sim's come out
    at dsf 1, so desktop live panels are genuinely 2880x1800 against the sim's 1440x900. Rescaling
    is correct here (same layout, more samples). Different ASPECT is not the same thing — that
    means the two captures used different viewports, so the tool letterboxes rather than distorting
    and says so in the verdict, because a squashed comparison invents differences everywhere.

  * ANTI-ALIASING. Text rendered by two Chromium instances differs on the edge pixel of nearly every
    glyph. Handled twice over: a per-channel tolerance (--tol, default 28 — the same constant
    scripts/refactor/ui-pixel-diff.py settled on) and a morphological OPENING of the difference
    mask, which deletes features thinner than the structuring element. A one-pixel glyph fringe
    disappears; a one-pixel border that live is missing along a whole edge does not, because it is
    long even though it is thin, and opening preserves it.

  * LIVE DATA vs FIXTURES. The sim renders mock messages; live renders whatever is seeded, with
    real timestamps and generated ids. Those pixels differ forever and no amount of porting fixes
    them. If they are left in, a text-dense Hebrew panel floors at 5-6% differing (measured, see
    digital-office/context/HANDOFF.md) and the actual layout bug is 0.3% of the image — the signal
    drowns. Hence ignore-regions, declared in pixel-diff.yaml as FRACTIONS of the panel (0..1) so
    one declaration survives every profile and every dsf. Ignored area is excluded from the
    denominator, drawn in blue on the output, and its size is printed — an ignore list that quietly
    grows to cover the whole screen must be visible in the report.

WHAT A "REGION" IS
------------------
Not a pixel and not the whole panel: a cluster. The mask is reduced to a grid of 8x8-pixel blocks
(a block counts as differing if >= --block-cov of its pixels do), blocks within --merge-gap of each
other are unioned, and each cluster's bounding box is drawn in red. That is deliberate — a human
looking at the picture wants "the toolbar area is wrong" as ONE box, not 400 boxes around 400
glyphs. The count of regions is consequently a better headline than the percentage: a 0.9% diff in
one region is a moved element, and a 0.9% diff in 60 regions is a font change.

READ THE OUTPUT AS
------------------
    IDENTICAL   under --identical-pct   pixel-equal for practical purposes
    CLOSE       under --close-pct       AA / sub-pixel noise only; look if you care
    DIFFERS     over it                 real visual divergence — open the picture
    MAJOR       over --major-pct, or    structurally different screens; usually a wrong pair,
                over --major-struct     a blank render, or a lost stylesheet. Check that first.
                                        (The AREA measure is what catches a blank render: see
                                        STRUCT_BLOCK in the source for why pixels alone cannot.)
    SIZE        aspect mismatch         captured at different viewports — fix the capture, the
                                        percentage below it is not meaningful
    UNPAIRED    one side only           reported, never dropped. A panel that exists only in the
                                        sim is unported; one that exists only live is undocumented.

Exit code is 0 unless --gate is passed. This is a report, not yet a gate: which live view
corresponds to which sim panel is a curated judgement (see pixel-diff.yaml), and a gate whose
denominator is a judgement call fails for the wrong reasons.
"""
from __future__ import annotations

import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import ast
import json
import math
import pathlib
import re
import sys
from collections import deque

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
except ImportError:                                             # noqa: PERF203
    sys.exit("Pillow required: pip install pillow   (nothing else is — no numpy, no playwright)")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SIM_UI_MAP = REPO / "digital-office" / "sim" / "ui-map.py"
CONFIG = HERE / "pixel-diff.yaml"
OUT_DEFAULT = REPO / "ci-artifacts" / "pixel-diff"

# Per-channel delta at or below this is rendering noise, not change. Same value as
# scripts/refactor/ui-pixel-diff.py — two tools disagreeing about what counts as "the same pixel"
# would be a fine way to produce two contradictory reports about one screenshot.
PIXEL_TOL = 28

# STRUCTURE — what the tolerance above cannot see. This design system's surfaces differ from the
# page by 7-11 levels (a white card on #f4f6f8), so at 28 a card, its border and its grey text are
# all "the same pixel" as an empty background: the simulation's BLANK apps panel against the live
# apps screen (a heading, counters, six cards, a side list) came out "0.69% differing · CLOSE", and
# every parity number this tool had produced had that floor under it. Structure is measured apart
# from pixels: each side is averaged over STRUCT_BLOCK-pixel blocks of luminance — which removes
# glyph edges and anti-aliasing by construction — and a block differs when the two averages are
# more than STRUCT_TOL apart. Measured on pairs whose answer is known (hp-laptop, 2026-10-06,
# 1440px; per-pixel % in brackets):
#     the same capture twice                     0.00   [0.00]
#     one screen, the same data, twice           0.00 - 0.02   [0.00]
#     one screen, other data (a live timeline)   6.0    [4.1]
#     one screen, other data (a table re-sorted) 24.6   [3.9]
#     two different screens                      44.4   [2.8]
#     a blank panel against the full screen      61.4   [3.1]
# The per-pixel column cannot tell the last four apart; this one can.
STRUCT_BLOCK = 8
STRUCT_TOL = 4

BLOCK = 8               # region grid, in pixels of the compared (normalised) image
CELL_MAX_W = 620        # width of one panel inside the side-by-side sheet


# ─────────────────────────────────────────────────────────────────────────────
# panel labels — parsed, not imported (see the header for why)
# ─────────────────────────────────────────────────────────────────────────────
def load_panel_labels():
    """{index: (hebrew_label, module_hash)} read out of the sim's PANELS literal.

    ast.parse over the file text: PANELS is a list of tuples whose first two members are string
    literals and whose third is a call/name we neither need nor can evaluate. Walking the AST takes
    exactly the two literals and never executes a line of the module, so the labels stay in sync
    with the sim's own list without importing Playwright.

    A missing or unparseable ui-map.py is NOT fatal — the tool still diffs whatever images it is
    handed, it just captions them by filename. Refusing to compare pictures because a label file
    moved would be the tail wagging the dog.
    """
    if not SIM_UI_MAP.exists():
        return {}
    try:
        tree = ast.parse(SIM_UI_MAP.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "PANELS" for t in node.targets):
            continue
        out = {}
        for i, el in enumerate(getattr(node.value, "elts", [])):
            parts = getattr(el, "elts", [])
            lbl = parts[0].value if parts and isinstance(parts[0], ast.Constant) else ""
            mod = parts[1].value if len(parts) > 1 and isinstance(parts[1], ast.Constant) else ""
            out[i] = (str(lbl), str(mod))
        return out
    return {}


# The PNG caption is drawn by Pillow, which does no bidi reordering and no complex shaping. Hebrew
# would come out reversed and disjointed, which is worse than absent. Every panel label in PANELS
# carries a latin parenthetical for exactly this kind of consumer — take it for the image, and keep
# the full Hebrew for index.html, where the browser reorders it correctly.
LATIN_IN_PARENS = re.compile(r"\(([\x20-\x7E·]+)\)")


def caption_of(label: str, fallback: str) -> str:
    m = LATIN_IN_PARENS.findall(label or "")
    if m:
        return max(m, key=len).strip()
    # No latin parenthetical: keep the latin characters that are there. Drop now-empty brackets and
    # collapse the whitespace the removed Hebrew left behind, or the caption reads "INDOX     ()".
    ascii_only = "".join(c for c in (label or "") if 32 <= ord(c) < 127)
    ascii_only = re.sub(r"\(\s*\)", "", ascii_only)
    ascii_only = re.sub(r"\s+", " ", ascii_only).strip(" ·-")
    return ascii_only or fallback


def rel(p: pathlib.Path) -> str:
    """Repo-relative where possible, absolute otherwise — the tool is explicitly allowed to be
    pointed at directories outside the repo (a downloaded CI artifact, a scratch pair)."""
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def title_of(key: str, cap: str) -> str:
    return key if cap == key else f"{key}  {cap}"


def sheet_name(key: str, cap: str) -> str:
    """<key>-<caption>.png, or just <key>.png when the caption IS the key — which it is
    whenever the images are named by view rather than by panel index, and repeating it would
    give every file a stutter like `my-docs__docs-my-docs-docs.png`."""
    s = re.sub(r"[^a-z0-9]+", "-", cap.lower()).strip("-")[:48]
    k = re.sub(r"[^A-Za-z0-9_.-]+", "-", key)
    return f"{k}.png" if (not s or s == re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:48]) else f"{k}-{s}.png"


# ─────────────────────────────────────────────────────────────────────────────
# config
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CFG = {"ignore_regions": {}, "pair_maps": {}}


def load_config(path: pathlib.Path):
    """pixel-diff.yaml if present, otherwise built-in empty defaults.

    Absent config is a legitimate state, not an error: the tool must work on any two directories a
    person points it at, including ones this repo has never heard of. The config only ever ADDS
    knowledge (which regions to excuse, which names pair with which).
    """
    if not path or not path.exists():
        return dict(DEFAULT_CFG)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        doc = yaml.safe_load(text) or {}
    except ImportError:
        # JSON is a subset of YAML, so a config written as JSON still loads with no PyYAML.
        try:
            doc = json.loads(text)
        except Exception:                                        # noqa: BLE001
            print(f"! {path.name} needs PyYAML (or must be valid JSON) — continuing without it")
            return dict(DEFAULT_CFG)
    cfg = dict(DEFAULT_CFG)
    cfg.update(doc)
    return cfg


def ignores_for(cfg, keys) -> list:
    """Ignore rects that apply to this pair: the '*' entry plus every pattern the pair matches.

    Keys are matched by fnmatch against BOTH sides' stems and against 'panel:<NN>', so a rule can be
    written against whichever naming the run happens to use.
    """
    import fnmatch
    rects = []
    table = cfg.get("ignore_regions") or {}
    for pattern, entries in table.items():
        if pattern != "*" and not any(fnmatch.fnmatch(k, pattern) for k in keys):
            continue
        for e in entries or []:
            box = e.get("rect") if isinstance(e, dict) else e
            if not box or len(box) != 4:
                continue
            rects.append({"rect": [float(v) for v in box],
                          "why": (e.get("why") if isinstance(e, dict) else "") or "",
                          "from": pattern})
    return rects


# ─────────────────────────────────────────────────────────────────────────────
# pairing
# ─────────────────────────────────────────────────────────────────────────────
INDEX_RE = re.compile(r"^(\d{1,3})\b")


def index_of(stem: str):
    m = INDEX_RE.match(stem)
    return int(m.group(1)) if m else None


def collect(d: pathlib.Path):
    """{stem: path} for every PNG/JPG directly in the directory.

    ui-map.png is skipped by name: it is the composed montage of all the panels, so pairing it would
    compare two contact sheets and produce one meaningless 90%-differing row that dominates the
    summary.
    """
    out = {}
    for p in sorted(d.iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg") or not p.is_file():
            continue
        if p.stem in ("ui-map", "index"):
            continue
        out[p.stem] = p
    return out


def pair_up(sim, live, mode, pair_map):
    """[(key, sim_path|None, live_path|None)] — every image on either side appears exactly once.

    Nothing is silently dropped. An unpaired sim panel is a screen live has not got; an unpaired
    live view is a screen the sim does not document. Both are findings, so both are rows.
    """
    pairs, used_live = [], set()
    if pair_map:
        # Explicit map wins where it speaks, and the two naming schemes are then free to differ.
        for s_key, l_key in pair_map.items():
            s_key = str(s_key)
            sp = sim.get(s_key) or sim.get(s_key.zfill(2))
            lp = live.get(str(l_key)) if l_key else None
            if sp is None and lp is None:
                continue
            if lp is not None:
                used_live.add(lp.stem)
            pairs.append((s_key.zfill(2) if s_key.isdigit() else s_key, sp, lp))
        seen_sim = {k for k, _s, _l in pairs}
        for k, p in sim.items():
            if k not in seen_sim and k.lstrip("0") not in seen_sim and k not in pair_map:
                pairs.append((k, p, None))
        for k, p in live.items():
            if k not in used_live:
                pairs.append((k, None, p))
        return pairs

    if mode == "index":
        by_i_sim = {index_of(k): v for k, v in sim.items() if index_of(k) is not None}
        by_i_live = {index_of(k): v for k, v in live.items() if index_of(k) is not None}
        for i in sorted(set(by_i_sim) | set(by_i_live)):
            pairs.append((f"{i:02d}", by_i_sim.get(i), by_i_live.get(i)))
        for k, v in sim.items():
            if index_of(k) is None:
                pairs.append((k, v, None))
        for k, v in live.items():
            if index_of(k) is None:
                pairs.append((k, None, v))
        return pairs

    for k in sorted(set(sim) | set(live)):
        pairs.append((k, sim.get(k), live.get(k)))
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# the comparison itself
# ─────────────────────────────────────────────────────────────────────────────
def normalise(a: Image.Image, b: Image.Image):
    """Bring both images into one coordinate space. Returns (a, b, note, aspect_ok).

    Same aspect, different size  -> downscale the larger. A dsf-2 capture holds the same layout at
                                    twice the samples; comparing at the smaller size is lossless as
                                    far as "is this element in the same place" is concerned, and it
                                    also halves the work.
    Different aspect             -> letterbox onto a common canvas and SAY SO. Resizing to match
                                    would stretch one image, which shifts every element in it and
                                    paints the whole panel as differing — a wrong answer that looks
                                    like a thorough one.
    """
    a, b = a.convert("RGB"), b.convert("RGB")
    if a.size == b.size:
        return a, b, "", True
    ar, br = a.width / a.height, b.width / b.height
    if abs(ar - br) < 0.01:
        tw, th = (a.size if a.width <= b.width else b.size)
        note = f"scaled {b.width}x{b.height}->{tw}x{th}" if b.size != (tw, th) else \
               f"scaled {a.width}x{a.height}->{tw}x{th}"
        return (a.resize((tw, th), Image.LANCZOS) if a.size != (tw, th) else a,
                b.resize((tw, th), Image.LANCZOS) if b.size != (tw, th) else b,
                note, True)
    tw, th = max(a.width, b.width), max(a.height, b.height)
    pad = lambda im: (lambda c: (c.paste(im, (0, 0)), c)[1])(
        Image.new("RGB", (tw, th), (24, 24, 28)))
    return pad(a), pad(b), f"ASPECT differs {a.width}x{a.height} vs {b.width}x{b.height}", False


def diff_mask(a: Image.Image, b: Image.Image, tol: int, aa_open: int) -> Image.Image:
    """'L' mask, 255 where the two images differ by more than `tol` on any channel.

    The opening (MinFilter then MaxFilter) is what makes the mask readable. MinFilter erodes: any
    white feature narrower than the kernel is eaten entirely, which is precisely the description of
    an anti-aliased glyph edge. MaxFilter then dilates what survived back to its original extent, so
    a real one-pixel-wide-but-long border is not thinned into nothing. Both are C-level Pillow
    filters, so this stays fast without numpy.
    """
    d = ImageChops.difference(a, b)
    r, g, bl = d.split()
    mx = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    mask = mx.point(lambda v: 255 if v > tol else 0, mode="L")
    if aa_open >= 3:
        k = aa_open if aa_open % 2 else aa_open + 1
        mask = mask.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
    return mask


def to_px(rect, w, h):
    """Fractional rect (0..1) -> integer pixel box, clamped. Values > 1 are read as raw pixels, so a
    one-off measured in a screenshot tool can be pasted in without converting it first."""
    x0, y0, x1, y1 = rect
    f = lambda v, n: int(round(v * n)) if 0.0 <= v <= 1.0 else int(round(v))
    box = [f(x0, w), f(y0, h), f(x1, w), f(y1, h)]
    box[0], box[2] = sorted((max(0, box[0]), min(w, box[2])))
    box[1], box[3] = sorted((max(0, box[1]), min(h, box[3])))
    return box


def apply_ignores(mask: Image.Image, rects, w, h):
    """Blank the excused regions and return (mask, boxes, ignored_pixel_count)."""
    if not rects:
        return mask, [], 0
    boxes = [to_px(r["rect"], w, h) for r in rects]
    cover = Image.new("L", (w, h), 0)
    cd = ImageDraw.Draw(cover)
    for bx in boxes:
        if bx[2] > bx[0] and bx[3] > bx[1]:
            cd.rectangle(bx, fill=255)
    ignored = sum(i * n for i, n in enumerate(cover.histogram())) // 255
    mask = ImageChops.subtract(mask, cover)
    return mask, boxes, ignored


def regions(mask: Image.Image, block: int, block_cov: float, merge_gap: int, min_area: int):
    """Bounding boxes of clustered difference, in pixels of the compared image.

    Reduce first, cluster second. `Image.BOX` resize averages each block, so one resize replaces a
    1.3-million-iteration Python loop with a C call and leaves a ~180x113 grid — small enough that a
    plain BFS over it is instant. Clustering at block level is not a performance compromise, it is
    the intended granularity: the answer wanted here is "this AREA is wrong", and per-pixel
    components would return one component per glyph.
    """
    w, h = mask.size
    cols, rows = max(1, math.ceil(w / block)), max(1, math.ceil(h / block))
    small = mask.resize((cols, rows), Image.BOX)
    cut = max(1, int(block_cov * 255))
    on = [v >= cut for v in small.tobytes()]
    if not any(on):
        return []

    seen, out = [False] * (cols * rows), []
    for start in range(cols * rows):
        if not on[start] or seen[start]:
            continue
        seen[start] = True
        q, cells = deque([start]), []
        while q:
            i = q.popleft()
            cells.append(i)
            cy, cx = divmod(i, cols)
            # merge_gap blocks of slack in every direction: adjacent-only clustering returns one
            # region per word on a text-heavy panel, which is unreadable as a picture.
            for dy in range(-merge_gap, merge_gap + 1):
                for dx in range(-merge_gap, merge_gap + 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < rows and 0 <= nx < cols:
                        j = ny * cols + nx
                        if on[j] and not seen[j]:
                            seen[j] = True
                            q.append(j)
        xs = [c % cols for c in cells]
        ys = [c // cols for c in cells]
        bx = [min(xs) * block, min(ys) * block,
              min(w, (max(xs) + 1) * block), min(h, (max(ys) + 1) * block)]
        if (bx[2] - bx[0]) * (bx[3] - bx[1]) >= min_area:
            out.append(bx)
    out.sort(key=lambda b: -((b[2] - b[0]) * (b[3] - b[1])))
    return out


def pct_on(mask: Image.Image, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return 100.0 * (mask.histogram()[255]) / float(denom)


def structure_pct(a: Image.Image, b: Image.Image, rects, block: int, tol: int) -> float:
    """The share of the panel whose AREA differs (see STRUCT_BLOCK). Ignore-regions are fractions of
    the panel, so the same declarations excuse the same places at this scale."""
    sw, sh = max(1, a.width // block), max(1, a.height // block)
    la = a.convert("L").resize((sw, sh), Image.BOX)
    lb = b.convert("L").resize((sw, sh), Image.BOX)
    mask = ImageChops.difference(la, lb).point(lambda v: 255 if v > tol else 0, mode="L")
    mask, _, ignored = apply_ignores(mask, rects, sw, sh)
    return pct_on(mask, sw * sh - ignored)


# ─────────────────────────────────────────────────────────────────────────────
# rendering the picture a human actually looks at
# ─────────────────────────────────────────────────────────────────────────────
def pick_font(size):
    for cand in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:                                        # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                            # Pillow < 9.2
        return ImageFont.load_default()


BG = (18, 18, 22)
FG = (232, 232, 236)
DIM = (150, 150, 158)
RED = (255, 64, 64)
BLUE = (70, 130, 255)


def make_sheet(sim, live, mask, boxes, ign_boxes, title, subtitle, stats):
    """SIM | LIVE | DIFF, captioned, with the differing regions boxed in red on the last two.

    The middle cell carries the boxes as well as the right one on purpose: a reviewer's eye goes to
    the live screenshot, and a box drawn only on an abstract heat map means they have to
    cross-reference two images to find the spot on the real one.
    """
    w, h = sim.size
    sc = min(1.0, CELL_MAX_W / w)
    cw, ch = int(w * sc), int(h * sc)
    R = lambda im: im.resize((cw, ch), Image.LANCZOS) if sc < 1.0 else im.copy()

    # heat: the live panel drained of colour so the red reads, tinted red where the mask is on.
    grey = live.convert("L").point(lambda v: 40 + v // 4).convert("RGB")
    heat = Image.composite(Image.new("RGB", (w, h), (255, 30, 30)), grey, mask)

    cells = [R(sim), R(live), R(heat)]
    dr = [ImageDraw.Draw(c) for c in cells]
    for bx in ign_boxes:                       # excused regions, on every cell, so it is obvious
        s = [int(v * sc) for v in bx]          # what the percentage below is NOT counting
        for d in dr:
            d.rectangle(s, outline=BLUE, width=1)
    for bx in boxes:
        s = [int(v * sc) for v in bx]
        s = [s[0], s[1], max(s[0] + 2, s[2]), max(s[1] + 2, s[3])]
        dr[1].rectangle(s, outline=RED, width=2)
        dr[2].rectangle(s, outline=(255, 220, 0), width=2)

    pad, head, foot, gut = 12, 46, 54, 10
    W = pad * 2 + cw * 3 + gut * 2
    H = pad + head + ch + foot + pad
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    f_t, f_s, f_l = pick_font(19), pick_font(13), pick_font(14)
    d.text((pad, pad), title, font=f_t, fill=FG)
    d.text((pad, pad + 24), subtitle, font=f_s, fill=DIM)
    y = pad + head
    for i, (c, name) in enumerate(zip(cells, ("SIM", "LIVE  (red = differs)",
                                              "DIFF overlay  (blue = ignored)"))):
        x = pad + i * (cw + gut)
        sheet.paste(c, (x, y))
        d.rectangle([x, y, x + cw - 1, y + ch - 1], outline=(70, 70, 78))
        d.text((x + 4, y + ch + 6), name, font=f_l, fill=DIM)
    d.text((pad, H - pad - 14), stats, font=f_l, fill=FG)
    return sheet


def placeholder(size, text):
    """One-sided pairs still get a picture — 'missing' is the loudest finding there is."""
    im = Image.new("RGB", size, (34, 26, 26))
    d = ImageDraw.Draw(im)
    f = pick_font(max(16, size[0] // 34))
    d.text((size[0] // 12, size[1] // 2 - 12), text, font=f, fill=(255, 120, 120))
    return im


# ─────────────────────────────────────────────────────────────────────────────
def verdict_of(pct, nreg, aspect_ok, a, spct=0.0):
    if not aspect_ok:
        return "SIZE"
    if pct >= a.major_pct or spct >= a.major_struct:
        return "MAJOR"
    if pct <= a.identical_pct and nreg == 0 and spct <= a.identical_struct:
        return "IDENTICAL"
    if pct <= a.close_pct and spct <= a.close_struct:
        return "CLOSE"
    return "DIFFERS"


def self_test() -> int:
    """Three drawn pairs whose verdict is not a matter of opinion, in this design system's own
    colours: the same page twice; a BLANK page against a page of cards; one page with other words."""
    import types
    a = types.SimpleNamespace(major_pct=25.0, identical_pct=0.05, close_pct=2.0,
                              identical_struct=0.1, close_struct=2.0, major_struct=35.0)

    def page(cards=True, words=0):
        im = Image.new("RGB", (1200, 760), (244, 246, 248))           # --bg
        d = ImageDraw.Draw(im)
        if cards:
            for r in range(2):
                for c in range(3):
                    x, y = 30 + c * 390, 90 + r * 320
                    d.rectangle((x, y, x + 360, y + 290), fill=(255, 255, 255), outline=(227, 232, 236))
                    for i in range(6):                                  # lines of grey text
                        w = 300 - (i * 37 + words * 53 * (i + c + r)) % 180
                        d.rectangle((x + 20, y + 30 + i * 36, x + 20 + w, y + 38 + i * 36), fill=(101, 114, 126))
        return im

    def judge(x, y):
        mask = diff_mask(x, y, PIXEL_TOL, 3)
        pct = pct_on(mask, x.width * x.height)
        spct = structure_pct(x, y, [], STRUCT_BLOCK, STRUCT_TOL)
        return verdict_of(pct, len(regions(mask, BLOCK, 0.10, 2, 256)), True, a, spct), round(pct, 2), round(spct, 2)

    cases = [("the same page twice", page(), page(), ("IDENTICAL",)),
             ("a blank page against a page of cards", page(cards=False), page(), ("MAJOR",)),
             ("one page with other words", page(words=0), page(words=1), ("DIFFERS", "CLOSE"))]
    bad = 0
    for name, x, y, want in cases:
        got, pct, spct = judge(x, y)
        ok = got in want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got} (pixels {pct}%, structure {spct}%) — expected {' or '.join(want)}")
    # …and the old rule, on the pair it was wrong about: without structure it is not MAJOR.
    blank, full = page(cards=False), page()
    mask = diff_mask(blank, full, PIXEL_TOL, 3)
    old = verdict_of(pct_on(mask, blank.width * blank.height), 1, True, a, 0.0)
    print(f"  {'ok  ' if old != 'MAJOR' else 'FAIL'} the per-pixel rule alone calls blank-against-cards {old} — which is why structure is measured")
    bad += old == "MAJOR"
    print("pixel-diff self-test:", "PASS" if not bad else f"FAIL ({bad})")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", type=pathlib.Path, help="directory of simulation PNGs")
    ap.add_argument("--live", type=pathlib.Path, help="directory of live-platform PNGs")
    ap.add_argument("--out", type=pathlib.Path, default=OUT_DEFAULT)
    ap.add_argument("--pair", choices=("stem", "index"), default="index",
                    help="stem: same filename both sides. index: leading NN both sides (default)")
    ap.add_argument("--pair-map", help="a named map from pixel-diff.yaml, for when the two "
                                       "renderers name their outputs differently")
    ap.add_argument("--list-pair-maps", action="store_true")
    ap.add_argument("--config", type=pathlib.Path, default=CONFIG)
    ap.add_argument("--tol", type=int, default=PIXEL_TOL, help="per-channel delta that still counts "
                                                               "as the same pixel")
    ap.add_argument("--aa-open", type=int, default=3, help="opening kernel; 0 disables it")
    ap.add_argument("--block", type=int, default=BLOCK)
    ap.add_argument("--block-cov", type=float, default=0.10)
    ap.add_argument("--merge-gap", type=int, default=2, help="blocks of slack when clustering")
    ap.add_argument("--min-region-px", type=int, default=256, help="drop regions smaller than this")
    ap.add_argument("--identical-pct", type=float, default=0.05)
    ap.add_argument("--close-pct", type=float, default=2.0)
    ap.add_argument("--major-pct", type=float, default=25.0)
    ap.add_argument("--struct-block", type=int, default=STRUCT_BLOCK,
                    help="side of the block one structure sample averages")
    ap.add_argument("--struct-tol", type=int, default=STRUCT_TOL,
                    help="luminance levels two block averages may differ by")
    ap.add_argument("--identical-struct", type=float, default=0.1)
    ap.add_argument("--close-struct", type=float, default=2.0,
                    help="over this share of differing AREA a pair is not CLOSE")
    ap.add_argument("--major-struct", type=float, default=35.0,
                    help="over this share of differing AREA a pair is MAJOR: a blank render or the wrong screen")
    ap.add_argument("--self-test", action="store_true", help="three drawn pairs with known verdicts")
    ap.add_argument("--no-images", action="store_true", help="numbers only, skip the sheets")
    ap.add_argument("--limit", type=int, help="first N pairs (for a quick look)")
    ap.add_argument("--gate", action="store_true",
                    help="exit non-zero if any pair is DIFFERS/MAJOR/UNPAIRED")
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    cfg = load_config(a.config)
    if a.list_pair_maps:
        maps = cfg.get("pair_maps") or {}
        if not maps:
            print(f"no pair_maps in {a.config}")
        for name, m in maps.items():
            print(f"  {name}  ({len(m.get('pairs', m))} pairs)  {m.get('note','') if isinstance(m, dict) else ''}")
        return 0
    if not a.sim or not a.live:
        ap.error("--sim and --live are required")
    for d in (a.sim, a.live):
        if not d.is_dir():
            sys.exit(f"not a directory: {d}")

    pm = None
    if a.pair_map:
        entry = (cfg.get("pair_maps") or {}).get(a.pair_map)
        if entry is None:
            sys.exit(f"no pair map named {a.pair_map!r} in {a.config} (try --list-pair-maps)")
        pm = entry.get("pairs", entry) if isinstance(entry, dict) else entry
        if isinstance(entry, dict) and entry.get("warning"):
            print(f"! pair map {a.pair_map}: {entry['warning']}\n")
        pm = {str(k): v for k, v in pm.items()}

    labels = load_panel_labels()
    pairs = pair_up(collect(a.sim), collect(a.live), a.pair, pm)
    if a.limit:
        pairs = pairs[:a.limit]
    out = a.out
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for key, sp, lp in pairs:
        idx = index_of(key)
        hebrew, module = labels.get(idx, ("", "")) if idx is not None else ("", "")
        cap = caption_of(hebrew, (sp or lp).stem)
        row = {"key": key, "index": idx, "label": hebrew, "module": module, "caption": cap,
               "sim": rel(sp) if sp else None,
               "live": rel(lp) if lp else None,
               "pct": None, "regions": 0, "boxes": [], "note": "", "ignored_pct": 0.0}

        if sp is None or lp is None:
            row["verdict"] = "UNPAIRED"
            row["note"] = "live only — not in the sim" if sp is None else "sim only — not rendered live"
            if not a.no_images:
                have = Image.open(lp if sp is None else sp).convert("RGB")
                miss = placeholder(have.size, "MISSING: " + ("sim" if sp is None else "live"))
                pairA, pairB = (miss, have) if sp is None else (have, miss)
                sheet = make_sheet(pairA, pairB, Image.new("L", have.size, 0), [], [],
                                   title_of(key, cap), module or row["note"], row["note"])
                fn = out / sheet_name(key, cap)
                sheet.save(fn)
                row["sheet"] = fn.name
            rows.append(row)
            continue

        try:
            A, B = Image.open(sp), Image.open(lp)
            orig = (A.size, B.size)
            A, B, note, aspect_ok = normalise(A, B)
        except OSError as e:
            row["verdict"] = "UNREADABLE"
            row["note"] = str(e)[:120]
            rows.append(row)
            continue

        w, h = A.size
        mask = diff_mask(A, B, a.tol, a.aa_open)
        rects = ignores_for(cfg, [key, sp.stem, lp.stem, f"panel:{key}"])
        mask, ign_boxes, ignored = apply_ignores(mask, rects, w, h)
        denom = w * h - ignored
        pct = pct_on(mask, denom)
        boxes = regions(mask, a.block, a.block_cov, a.merge_gap, a.min_region_px)
        spct = structure_pct(A, B, rects, a.struct_block, a.struct_tol)

        row.update({"pct": round(pct, 3), "structure": round(spct, 2), "regions": len(boxes), "boxes": boxes[:40],
                    "note": note, "sim_size": list(orig[0]), "live_size": list(orig[1]),
                    "ignored_pct": round(100.0 * ignored / float(w * h), 2),
                    "ignore_reasons": sorted({r["why"] for r in rects if r["why"]}),
                    "verdict": verdict_of(pct, len(boxes), aspect_ok, a, spct)})

        if not a.no_images:
            stats = (f"{pct:5.2f}% of pixels   ·   {spct:5.2f}% of the area   ·   {len(boxes)} region(s)   ·   {row['verdict']}"
                     + (f"   ·   {row['ignored_pct']}% ignored" if ignored else "")
                     + (f"   ·   {note}" if note else ""))
            sub = f"{module}    sim {orig[0][0]}x{orig[0][1]}  ·  live {orig[1][0]}x{orig[1][1]}"
            sheet = make_sheet(A, B, mask, boxes, ign_boxes, title_of(key, cap), sub, stats)
            fn = out / sheet_name(key, cap)
            sheet.save(fn)
            row["sheet"] = fn.name
        rows.append(row)

    # ── summary table ───────────────────────────────────────────────────────
    order = {"MAJOR": 0, "SIZE": 1, "UNPAIRED": 2, "UNREADABLE": 2, "DIFFERS": 3,
             "CLOSE": 4, "IDENTICAL": 5}
    ranked = sorted(rows, key=lambda r: (order.get(r["verdict"], 9), -(r["pct"] or 0)))
    print(f"\n══ pixel-diff   sim: {a.sim}   live: {a.live}")
    print(f"   tol {a.tol}  ·  opening {a.aa_open}  ·  block {a.block}px@{a.block_cov:.0%}  "
          f"·  {len(rows)} pair(s)\n")
    print(f"   {'verdict':10} {'%pixels':>7} {'%area':>7} {'regions':>8}  panel")
    for r in ranked:
        p = "   —  " if r["pct"] is None else f"{r['pct']:6.2f}"
        p += "     —  " if r.get("structure") is None else f" {r['structure']:7.2f}"
        extra = f"   {r['note']}" if r["note"] else ""
        # caption falls back to the filename when there is no PANELS label for this pair; printing
        # both would just say the same word twice.
        name = r["key"] if r["caption"] == r["key"] else f"{r['key']}  {r['caption']}"
        print(f"   {r['verdict']:10} {p:>7} {r['regions']:>8}  {name[:64]}{extra}")

    tally = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print("\n   " + "   ".join(f"{k}: {v}" for k, v in sorted(tally.items(), key=lambda kv: order.get(kv[0], 9))))

    summary = {"sim_dir": str(a.sim), "live_dir": str(a.live), "pair_mode": a.pair_map or a.pair,
               "tol": a.tol, "aa_open": a.aa_open, "block": a.block, "block_cov": a.block_cov,
               "tally": tally, "rows": rows}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    if not a.no_images:
        write_index(out, ranked, a)
        print(f"\n   pictures -> {out}\\index.html   ({len(rows)} sheet(s))")
    print(f"   json     -> {out / 'summary.json'}")

    if a.gate:
        bad = sum(tally.get(k, 0) for k in ("MAJOR", "DIFFERS", "UNPAIRED", "UNREADABLE", "SIZE"))
        return 1 if bad else 0
    return 0


CSS = """
body{background:#111;color:#e6e6ea;font:14px/1.5 "Segoe UI",system-ui,"Noto Sans Hebrew",Arial,sans-serif;margin:0;padding:24px}
h1{font-size:20px;margin:0 0 4px} .sub{color:#9a9aa4;margin-bottom:20px}
.card{border:1px solid #2c2c34;border-radius:8px;margin:0 0 22px;overflow:hidden;background:#16161b}
.hd{display:flex;gap:14px;align-items:baseline;padding:10px 14px;border-bottom:1px solid #2c2c34}
.he{direction:rtl;unicode-bidi:embed;color:#e6e6ea;font-weight:600}
.mod{color:#7d7d88;font-family:ui-monospace,Consolas,monospace;font-size:12px}
img{width:100%;display:block}
.v{padding:2px 9px;border-radius:99px;font-size:12px;font-weight:700;letter-spacing:.3px}
.MAJOR{background:#5b1414;color:#ffb0b0}.DIFFERS{background:#5b3a14;color:#ffd9a0}
.CLOSE{background:#14415b;color:#a8d8ff}.IDENTICAL{background:#14401f;color:#a6f0bd}
.UNPAIRED,.UNREADABLE,.SIZE{background:#3a2050;color:#dcb8ff}
.st{color:#9a9aa4;font-size:12px;margin-left:auto}
.why{color:#7d7d88;font-size:12px;padding:6px 14px;border-top:1px solid #2c2c34}
"""


def write_index(out, ranked, a):
    """A single scrollable page, worst first. The whole point of this tool is that a person can look
    at ONE artifact and see every divergence, so the contact sheet is part of the deliverable rather
    than a nicety — 43 loose PNGs in a folder do not get looked at."""
    parts = [f"<title>pixel-diff — sim vs live</title><style>{CSS}</style>",
             "<h1>pixel-diff — simulation vs live platform</h1>",
             f"<div class=sub>sim <code>{a.sim}</code> &nbsp;·&nbsp; live <code>{a.live}</code>"
             f" &nbsp;·&nbsp; tolerance {a.tol} &nbsp;·&nbsp; sorted worst-first. "
             f"Red boxes mark differing regions; blue boxes are ignored regions "
             f"(declared in pixel-diff.yaml) and are excluded from the percentage.</div>"]
    for r in ranked:
        if not r.get("sheet"):
            continue
        pct = "—" if r["pct"] is None else f"{r['pct']:.2f}%"
        why = ("ignored: " + "; ".join(r.get("ignore_reasons") or [])) if r.get("ignore_reasons") else ""
        if r.get("note"):
            why = (why + " · " if why else "") + r["note"]
        parts.append(
            f"<div class=card><div class=hd><span class='v {r['verdict']}'>{r['verdict']}</span>"
            f"<span class=he>{r['label'] or r['caption']}</span>"
            f"<span class=mod>{r['key']} {r['module']}</span>"
            f"<span class=st>{pct} differing · {r['regions']} region(s)</span></div>"
            f"<img loading=lazy src='{r['sheet']}'>"
            + (f"<div class=why>{why}</div>" if why else "") + "</div>")
    (out / "index.html").write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
