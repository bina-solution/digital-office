#!/usr/bin/env python3
"""
compose_map.py — assemble every captured view into ONE big mockup image of the platform.

Layout follows the product's own information architecture rather than an arbitrary grid:
sections come from the console's `modules.yaml` groups (ראשי / עסק / תשתית / הגדרות),
then first-party apps that aren't console modules, then third-party. Seeing the map
should feel like seeing the system, not like seeing a directory listing.

Each tile is a captured screenshot with a caption and a status-coloured border.
The banner carries the two numbers that make the image a claim rather than a poster:
  VIEW coverage   — captured / declared (from ui-inventory.json)
  UI-CODE coverage— % of view-code lines that ran while these shots were taken

Outputs:
    ci-artifacts/ui-map/ui-map.png    the one big image
    ci-artifacts/ui-map/index.html    zoomable gallery (full-res per tile)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]

TILE_W, TILE_H = 480, 300
PAD, CAP_H = 18, 34
COLS = 6
BG = (14, 16, 22)
FG = (232, 236, 244)
MUTED = (140, 150, 168)
SECTION = (86, 160, 255)
OK, BAD, SKIP = (64, 190, 120), (226, 88, 88), (150, 130, 60)

GROUP_ORDER = ["ראשי", "עסק", "תשתית", "הגדרות"]


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf", "seguisb.ttf") if bold else ("arial.ttf", "segoeui.ttf")):
        for base in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu",
                     "/usr/share/fonts/truetype/liberation"):
            p = Path(base) / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
              else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _rtl(s: str) -> str:
    """Hebrew passthrough.

    An earlier version reversed Hebrew strings on the theory that Pillow lacks bidi
    shaping. It does lack shaping, but the raw text already renders in the right visual
    order here, so reversing produced mirrored garbage ("ראשי" -> "ישאר"). Left as a
    seam: if a font/stack ever does need reordering, do it with python-bidi rather than
    a naive slice, which also mangles mixed Hebrew/Latin/digit captions.
    """
    return s


def group_of(view: dict, inv_by_key: dict) -> str:
    if view["app"] == "console":
        return inv_by_key.get(("console", view["id"]), {}).get("group") or "המרכז"
    if view.get("tier") == "third_party":
        return "מערכות חיצוניות"
    return "אפליקציות"


def build(results: list[dict], inv: dict, cov: dict | None, out_dir: Path) -> Path:
    inv_by_key = {(v["app"], v["id"]): v for v in inv["views"]}

    sections: dict[str, list[dict]] = {}
    for r in results:
        sections.setdefault(group_of(r, inv_by_key), []).append(r)

    ordered = [g for g in GROUP_ORDER if g in sections] + \
              [g for g in ("המרכז", "אפליקציות", "מערכות חיצוניות") if g in sections] + \
              [g for g in sections if g not in GROUP_ORDER +
               ["המרכז", "אפליקציות", "מערכות חיצוניות"]]

    # geometry
    head_h = 150
    rows_per = {g: (len(sections[g]) + COLS - 1) // COLS for g in ordered}
    height = head_h + sum(46 + rows_per[g] * (TILE_H + CAP_H + PAD) for g in ordered) + PAD
    width = PAD + COLS * (TILE_W + PAD)

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    f_title, f_sec = _font(40, True), _font(26, True)
    f_cap, f_small = _font(16), _font(15)

    cap = sum(1 for r in results if r["status"] == "captured")
    tot = len(results)
    vpct = round(100.0 * cap / tot, 1) if tot else 0.0

    d.text((PAD, 24), "AutomateOS — Platform UI Map", font=f_title, fill=FG)
    sub = f"{cap}/{tot} views captured  ·  view coverage {vpct}%"
    if cov:
        sub += (f"  ·  UI-code coverage {cov['overall_js_pct']}% JS / "
                f"{cov['overall_css_pct']}% CSS  "
                f"({cov['covered_lines']}/{cov['executable_lines']} lines)")
    d.text((PAD, 78), sub, font=f_sec, fill=SECTION)
    d.text((PAD, 112), _rtl("כל תצוגות המערכת — נלכד אוטומטית מהקוד"), font=f_small, fill=MUTED)

    y = head_h
    for g in ordered:
        d.text((PAD, y + 8), _rtl(g), font=f_sec, fill=SECTION)
        d.line([(PAD, y + 40), (width - PAD, y + 40)], fill=(46, 52, 66), width=1)
        y += 46
        for i, r in enumerate(sections[g]):
            cx = PAD + (i % COLS) * (TILE_W + PAD)
            cy = y + (i // COLS) * (TILE_H + CAP_H + PAD)
            colour = {"captured": OK, "skipped": SKIP}.get(r["status"], BAD)
            png = r.get("png")
            src = (out_dir / ".." / "screenshots-ui" / Path(png).name) if png else None
            placed = False
            if png:
                for cand in (out_dir.parent / "screenshots-ui" / Path(png).name,
                             ROOT / "data" / "browser42" / "output" / png):
                    if cand.exists():
                        try:
                            s = Image.open(cand).convert("RGB")
                            s.thumbnail((TILE_W, TILE_H))
                            box = Image.new("RGB", (TILE_W, TILE_H), (24, 27, 35))
                            box.paste(s, ((TILE_W - s.width) // 2, 0))
                            img.paste(box, (cx, cy))
                            placed = True
                            break
                        except Exception:
                            pass
            if not placed:
                d.rectangle([cx, cy, cx + TILE_W, cy + TILE_H], fill=(30, 24, 26))
                d.text((cx + 14, cy + TILE_H // 2 - 10),
                       r["status"].upper(), font=f_cap, fill=colour)
            d.rectangle([cx, cy, cx + TILE_W, cy + TILE_H], outline=colour, width=2)
            d.text((cx + 2, cy + TILE_H + 6),
                   _rtl(f"{r['app']} · {r['id']}")[:64], font=f_cap, fill=FG)
            note = r.get("note") or ""
            if r["status"] != "captured" and note:
                d.text((cx + 2, cy + TILE_H + 22), note[:58], font=f_small, fill=MUTED)
        y += rows_per[g] * (TILE_H + CAP_H + PAD)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "ui-map.png"
    img.save(out, optimize=True)
    return out


def write_index(results, cov, out_dir: Path):
    cap = sum(1 for r in results if r["status"] == "captured")
    rows = "\n".join(
        f'<figure class="{r["status"]}"><img loading="lazy" src="../screenshots-ui/'
        f'{Path(r["png"]).name if r.get("png") else ""}" alt="{r["app"]}/{r["id"]}">'
        f'<figcaption>{r["app"]} · {r["id"]}<small>{r.get("note","")}</small></figcaption></figure>'
        for r in results)
    covline = (f"UI-code {cov['overall_js_pct']}% JS / {cov['overall_css_pct']}% CSS"
               if cov else "")
    (out_dir / "index.html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>Platform UI Map</title><style>
body{{background:#0e1016;color:#e8ecf4;font:14px system-ui;margin:24px}}
h1{{margin:0 0 6px}} .sub{{color:#56a0ff;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
figure{{margin:0;background:#181b23;border:2px solid #40be78;border-radius:8px;overflow:hidden}}
figure.failed{{border-color:#e25858}} figure.skipped{{border-color:#967c3c}}
img{{width:100%;display:block}} figcaption{{padding:8px;font-size:13px}}
small{{display:block;color:#8c96a8}}</style>
<h1>AutomateOS — Platform UI Map</h1>
<div class="sub">{cap}/{len(results)} views · {covline}</div>
<div class="grid">{rows}</div>""", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "ci-artifacts" / "ui-capture-results.json"))
    ap.add_argument("--inventory", default=str(ROOT / "ci-artifacts" / "ui-inventory.json"))
    ap.add_argument("--coverage", default=str(ROOT / "ci-artifacts" / "ui-code-coverage.json"))
    ap.add_argument("--out", default=str(ROOT / "ci-artifacts" / "ui-map"))
    a = ap.parse_args()

    results = json.loads(Path(a.results).read_text(encoding="utf-8"))["results"]
    inv = json.loads(Path(a.inventory).read_text(encoding="utf-8"))
    cov = None
    if Path(a.coverage).exists():
        cov = json.loads(Path(a.coverage).read_text(encoding="utf-8"))

    out_dir = Path(a.out)
    png = build(results, inv, cov, out_dir)
    write_index(results, cov, out_dir)
    sz = png.stat().st_size / 1e6
    im = Image.open(png)
    print(f"ui-map: {png}  {im.width}x{im.height}px  {sz:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
