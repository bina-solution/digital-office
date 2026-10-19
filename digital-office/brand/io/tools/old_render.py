import json, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from oldstyle import svg, VERSIONS
from beautiful import beauty
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "old")
CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
recs = []
for i, (o, acc, pal) in enumerate(VERSIONS, 1):
    p = os.path.join(OUT, "svg", f"{i:02d}.svg"); open(p, "w").write(svg(o, acc, pal))
    recs.append(dict(n=i, o=o, accent=acc, palette=pal, svg=p, png=os.path.join(OUT, "png", f"{i:02d}.png")))
T = 1024
for b in range(0, len(recs), 16):
    batch = recs[b:b + 16]
    page = os.path.join(OUT, f"page{b // 16}.html")
    open(page, "w").write('<!doctype html><style>html,body{margin:0}div{display:grid;grid-template-columns:repeat(4,1024px);width:4096px}img{display:block}</style><div>'
                          + "".join(f'<img src="file://{r["svg"]}" width="{T}" height="{T}">' for r in batch) + "</div>")
    shot = page[:-5] + ".png"
    subprocess.run([CH, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files", "--force-device-scale-factor=1",
                    f"--window-size=4096,{((len(batch) + 3) // 4) * T}", "--virtual-time-budget=3000", f"--screenshot={shot}", f"file://{page}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=240)
    im = Image.open(shot).convert("RGB")
    for i, r in enumerate(batch):
        x, y = (i % 4) * T, (i // 4) * T
        im.crop((x, y, x + T, y + T)).save(r["png"])
for r in recs:
    b = beauty(r["png"], "logo")
    r["score"] = round(1 + 99 / (1 + np.exp(-8 * (b["weighted_sum"] - 0.55))) - sum(b["penalties"].values()), 2)
    r["curves"] = b["factors"]["curves"]; r["harmony"] = b["factors"]["harmony"]; r["pen"] = b["penalties"]
    print(r["n"], r["o"], r["accent"], r["palette"], r["score"], "curves", r["curves"], "harmony", r["harmony"], r["pen"])
json.dump(recs, open(os.path.join(OUT, "versions.json"), "w"), indent=1)
F = lambda s, b=False: ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", s, index=1 if b else 0)
icon, cols = 240, 5
cw, ch = icon + 26, icon + 70
rows = (len(recs) + cols - 1) // cols
W, H = 40 + cols * cw, 110 + rows * ch + 20
sheet = Image.new("RGB", (W, H), "#ffffff"); d = ImageDraw.Draw(sheet)
d.text((30, 26), "i0 in the old icon's style · tile #1b5e4a r22% · ink #fbfcfc · mint #7ecfad · caps 0.27 × stroke", fill="#111", font=F(24, True))
d.text((30, 62), "rows 1–3: o corners boxy / nested / stadium × which parts are mint · rows 4–5: palettes · score = beautiful logo (curve-aware)", fill="#666", font=F(16))
for i, r in enumerate(recs):
    x, y = 30 + (i % cols) * cw, 100 + (i // cols) * ch
    sheet.paste(Image.open(r["png"]).resize((icon, icon), Image.LANCZOS), (x, y))
    d.text((x, y + icon + 8), f"#{r['n']}", fill="#111", font=F(16, True))
    d.text((x + icon, y + icon + 8), f"{r['score']:.1f}", fill="#0a7a4f", font=F(16, True), anchor="ra")
    d.text((x, y + icon + 30), f"o {r['o']} · mint: {r['accent']}", fill="#333", font=F(13))
    d.text((x, y + icon + 47), f"palette {r['palette']}", fill="#777", font=F(13))
sheet.save(os.path.join(OUT, "sheet.png"), optimize=True)
