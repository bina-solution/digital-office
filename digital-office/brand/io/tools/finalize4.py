"""Pick 100 diverse versions scoring >= 95, render the real SVGs in Chrome, re-verify, draw the sheets."""
import csv, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from iomark import Design  # noqa: E402
from search3 import design as design3  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "final")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MIN_SCORE, MIN_MARGIN, N = 95, 0.4, int(os.environ.get("IO_N", 100))
CENTRE = os.environ.get("IO_CENTRE", "median")
FACTORS = ("rho", "ro", "ri", "rc", "pol", "k", "centre")


def label(r):
    box = "disc" if r["rc"] < 0 else ("square" if r["rc"] == 0 else f"tile r{r['rc']:g}")
    return (f"caps {r['rho']:g} · o {r['ro']:g}/{r['ri']:g} · curves {r['factors']['curves']:.2f}",
            f"{box} · {'black' if r['pol'] == 'pos' else 'white'} · k{r['k']:g} · {'halves' if r['centre'] == 'median' else 'grid'}")


def pick(rows, n):
    rows = sorted(rows, key=lambda r: (-r["score"], -r["ws"]))
    sel = [rows[0]]
    rest = rows[1:]
    while len(sel) < n and rest:
        best, bi = None, -1
        for i, c in enumerate(rest):
            d = min(sum(c[f] != s[f] for f in FACTORS) for s in sel)
            key = (min(d, 3), c["score"], c["ws"])
            if best is None or key > best:
                best, bi = key, i
        sel.append(rest.pop(bi))
    return sel


def render_all(recs, work):
    """One Chrome launch per 4x4 page of 1024 px <img> tiles, then sliced back into one PNG per icon."""
    per, T = 16, 1024
    for b in range(0, len(recs), per):
        batch = recs[b:b + per]
        cells = "".join(f'<img src="file://{r["svg"]}" width="{T}" height="{T}">' for r in batch)
        page = os.path.join(work, f"page{b // per}.html")
        open(page, "w").write('<!doctype html><style>html,body{margin:0;background:#888}'
                              f'div{{display:grid;grid-template-columns:repeat(4,{T}px);width:{4 * T}px}}img{{display:block}}</style>'
                              f"<div>{cells}</div>")
        shot = page[:-5] + ".png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--allow-file-access-from-files", f"--window-size={4 * T},{4 * T}", "--virtual-time-budget=3000",
                        f"--screenshot={shot}", f"file://{page}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=240)
        im = Image.open(shot).convert("RGB")
        for i, r in enumerate(batch):
            x, y = (i % 4) * T, (i // 4) * T
            im.crop((x, y, x + T, y + T)).save(r["png"])
        os.remove(shot); os.remove(page)


def audit(png):
    g = np.asarray(Image.open(png).convert("L"), dtype=np.float64) / 255.0
    ink = 1 - g
    h, w = ink.shape
    ys, xs = np.mgrid[0:h, 0:w]
    tot = ink.sum()
    L, R = ink[:, : w // 2].sum(), ink[:, w // 2:].sum()
    T, B = ink[: h // 2].sum(), ink[h // 2:].sum()
    return dict(white=float(g.mean()), lr=float(min(L, R) / max(L, R)), tb=float(min(T, B) / max(T, B)),
                cx=float(((xs * ink).sum() / tot - (w - 1) / 2) / w), cy=float(((ys * ink).sum() / tot - (h - 1) / 2) / h))


def font(size, bold=False):
    return ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", size, index=1 if bold else 0)


def sheet(recs, path, cols=10, icon=160, title=""):
    pad, gap_x, text_h, head = 40, 24, 58, 110
    cw = icon + gap_x
    ch = icon + text_h + 22
    rows = (len(recs) + cols - 1) // cols
    W = pad * 2 + cols * cw - gap_x
    H = head + rows * ch + pad
    im = Image.new("RGB", (W, H), "#f4f5f6")
    d = ImageDraw.Draw(im)
    d.text((pad, 34), title, fill="#111", font=font(30, True))
    d.text((pad, 74), "1:1 canvas · square anchors 0·2·4·6 · black = white · ink left = right · ink top = bottom · all measured on the Chrome render · ranked by beautiful logo (with curve repetition)",
           fill="#666", font=font(17))
    for i, r in enumerate(recs):
        x = pad + (i % cols) * cw
        y = head + (i // cols) * ch
        th = Image.open(r["png"]).convert("RGB").resize((icon, icon), Image.LANCZOS)
        im.paste(th, (x, y))
        d.rectangle([x - 1, y - 1, x + icon, y + icon], outline="#d6d9dc")
        l1, l2 = label(r)
        d.text((x, y + icon + 8), f"#{i + 1}", fill="#111", font=font(17, True))
        d.text((x + icon, y + icon + 8), f"{r['vexact']:.2f}", fill="#0a7a4f", font=font(17, True), anchor="ra")
        d.text((x, y + icon + 30), l1, fill="#333", font=font(12))
        d.text((x, y + icon + 45), l2, fill="#777", font=font(12))
    im.save(path, optimize=True)


if __name__ == "__main__":
    rows = [json.loads(l) for f in ("results3.jsonl", "results4.jsonl") for l in open(os.path.join(HERE, f))]
    exact = lambda r: 1 + 99 / (1 + np.exp(-8 * (r["ws"] - 0.55))) - sum(r["penalties"].values())
    ok = [r for r in rows if r.get("score") is not None and r["centre"] == "median" and exact(r) >= MIN_SCORE
          and r["margin"] >= MIN_MARGIN]
    print(f"{len(rows)} scored, {len(ok)} halves-centred at exact >= {MIN_SCORE} with margin >= {MIN_MARGIN}")
    order = pick(ok, min(len(ok), int(N * 1.5)))        # diversity order, 50 % spare for verification failures
    os.makedirs(os.path.join(OUT, "svg"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "png"), exist_ok=True)
    from beautiful import beauty
    sel, rejected, pos = [], [], 0
    while len(sel) < N and pos < len(order):
        batch = order[pos:pos + (N - len(sel) + 15) // 16 * 16]
        pos += len(batch)
        for r in batch:
            d = design3(r)
            r["svg"] = os.path.join(OUT, "svg", r["key"] + ".svg")
            open(r["svg"], "w").write(d.svg())
            r["png"] = os.path.join(OUT, "png", r["key"] + ".png")
        render_all(batch, os.path.join(OUT, "png"))
        for r in batch:
            r.update(audit(r["png"]))
            b = beauty(r["png"], "logo")
            r["vscore"], r["vws"] = b["score"], b["weighted_sum"]
            r["vexact"] = 1 + 99 / (1 + np.exp(-8 * (b["weighted_sum"] - 0.55))) - sum(b["penalties"].values())
            r["factors"], r["vpen"] = b["factors"], b["penalties"]
            halves_ok = r["centre"] != "median" or (r["lr"] >= 0.995 and r["tb"] >= 0.995)
            good = r["vexact"] >= MIN_SCORE and abs(r["white"] - 0.5) <= 0.001 and halves_ok
            if good and len(sel) < N:
                sel.append(r)
            else:
                if not good:
                    rejected.append(r)
                os.remove(r["svg"]); os.remove(r["png"])
        print(f"verified {pos} rendered, {len(sel)} kept, {len(rejected)} rejected", flush=True)
    for r in rejected:
        print("  rejected", r["key"], "score", r["vscore"], r.get("vpen"), f"white {r['white']:.4f} lr {r['lr']:.3f} tb {r['tb']:.3f}")
    sel.sort(key=lambda r: (-r["vexact"], -r["vscore"]))
    # rename to rank order
    for i, r in enumerate(sel, 1):
        for ext in ("svg", "png"):
            new = os.path.join(OUT, ext, f"{i:03d}.{ext}")
            os.replace(r[ext], new)
            r[ext] = new
    with open(os.path.join(OUT, "scores.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "score", "curves", "distinct_radii", "cap_radius", "o_outer", "o_inner", "tile_radius", "polarity", "clearance",
                    "centring", "white_share", "left_right", "top_bottom", "composition", "svg"])
        for i, r in enumerate(sel, 1):
            w.writerow([i, f"{r['vexact']:.3f}", r["factors"]["curves"], r.get("distinct"), r["rho"], r["ro"], r["ri"],
                        "disc" if r["rc"] < 0 else r["rc"], "black" if r["pol"] == "pos" else "white", r["k"],
                        "halves" if r["centre"] == "median" else "grid", f"{r['white']:.4f}", f"{r['lr']:.3f}", f"{r['tb']:.3f}",
                        r["factors"]["composition"], f"versions/{i:03d}.svg"])
    json.dump([{k: v for k, v in r.items() if k not in ("png", "svg")} for r in sel],
              open(os.path.join(OUT, "selected.json"), "w"), indent=1)
    lo, hi = min(r["vscore"] for r in sel), max(r["vscore"] for r in sel)
    print("exact range", f"{min(r['vexact'] for r in sel):.2f}..{max(r['vexact'] for r in sel):.2f}")
    sheet(sel, os.path.join(OUT, "sheet.png"), title=f"io · 100 versions · every one scores {min(r['vexact'] for r in sel):.2f}–{max(r['vexact'] for r in sel):.2f}")
    sheet(sel[:12], os.path.join(OUT, "top12.png"), cols=4, icon=300, title=f"io · the top 12 ({sel[min(11, len(sel) - 1)]['vscore']}–{hi})")
    wv = [r["white"] for r in sel]
    print("verified scores", lo, hi, "| white share", f"{min(wv):.4f}..{max(wv):.4f}",
          "| L:R", f"{min(r['lr'] for r in sel):.3f}", "| T:B", f"{min(r['tb'] for r in sel):.3f}")
    print("score drift (search raster -> chrome):", sorted({r["vscore"] - r["score"] for r in sel}))
    print("factor coverage:", {f: sorted({str(r[f]) for r in sel}) for f in FACTORS})
    print("halves-centred:", sum(r["centre"] == "median" for r in sel), "| curves = 1.00:", sum(r["factors"]["curves"] >= 0.995 for r in sel))
