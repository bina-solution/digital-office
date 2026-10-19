#!/usr/bin/env python3
# Render ONE screen from an isolated dist build and diff vs the real screenshot.
# usage: python3 one.py <myid> <basename> [tag]
import sys, os, asyncio, subprocess, numpy as np
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright
myid, base = sys.argv[1], sys.argv[2]
tag = sys.argv[3] if len(sys.argv)>3 else myid
BZ="/home/claude/bizcenter"; UM="/home/claude/uimap"
dist=f"/tmp/dist_{tag}.html"; outpng=f"{UM}/mine/screenshots-ui/{base}.png"
subprocess.run(["node", f"{BZ}/assemble.js", dist], check=True, capture_output=True)
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        pg=await b.new_page(viewport={"width":1440,"height":900})
        await pg.goto("file://"+dist); await pg.wait_for_timeout(500)
        await pg.add_style_tag(content="#navBtn{display:none!important}")
        await pg.evaluate("id=>go(id)", myid); await pg.wait_for_timeout(300)
        await pg.screenshot(path=outpng)
        await b.close()
asyncio.run(main())
r=np.array(Image.open(f"{UM}/real/screenshots-ui/{base}.png").convert("RGB")).astype(int)
m=np.array(Image.open(outpng).convert("RGB")).astype(int)
dd=np.abs(r-m).max(axis=2).astype(np.uint8)
pct=100.0*(dd>28).mean()
# triptych
rr=Image.fromarray(r.astype('uint8')).resize((520,325)); mm=Image.fromarray(m.astype('uint8')).resize((520,325))
heat=np.zeros((900,1440,3),np.uint8); heat[...,0]=dd; heat[...,2]=(255-dd)//3
hh=Image.fromarray(heat).resize((520,325))
c=Image.new("RGB",(520*3+40,350),(20,20,24)); d=ImageDraw.Draw(c)
d.text((8,2),"REAL",fill=(120,200,255)); d.text((540,2),"MINE",fill=(120,255,170)); d.text((1070,2),f"DIFF {pct:.1f}%",fill=(255,150,150))
c.paste(rr,(8,24)); c.paste(mm,(538,24)); c.paste(hh,(1068,24))
c.save(f"{UM}/diff_{tag}.png")
print(f"{base}: DIFF {pct:.2f}%  -> {UM}/diff_{tag}.png")
