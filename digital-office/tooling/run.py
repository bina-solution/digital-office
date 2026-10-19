import asyncio, os, json, shutil, glob
from playwright.async_api import async_playwright
U="/mnt/user-data/uploads/ui/"
MINE="/home/claude/uimap/mine/screenshots-ui/"
REAL="/home/claude/uimap/real/screenshots-ui/"
M=json.load(open("/home/claude/uimap/map.json"))          # myid -> basename
inv={b:i for i,b in M.items()}                            # basename -> myid
# copy real screenshots
for b in M.values():
    src=U+b+".png"
    if os.path.exists(src): shutil.copy(src, REAL+b+".png")
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        pg=await b.new_page(viewport={"width":1440,"height":900})
        await pg.goto("file://"+os.path.abspath("/home/claude/bizcenter/dist.html")); await pg.wait_for_timeout(600)
        await pg.add_style_tag(content="#navBtn{display:none!important}")
        done=0
        for basename,myid in inv.items():
            try:
                await pg.evaluate("id=>go(id)", myid); await pg.wait_for_timeout(200)
                await pg.screenshot(path=MINE+basename+".png"); done+=1
            except Exception as e: print("ERR",myid,e)
        await b.close(); print("rendered mine:",done)
asyncio.run(main())
# synthesize results: flip failed-with-file to captured
res=json.load(open("/home/claude/uimap/results-orig.json"))["results"]
for r in res:
    name=f"{r['app']}__{r['id']}".replace(":","-")
    if os.path.exists(REAL+name+".png"):
        r["status"]="captured"; r["png"]=f"ui/{name}.png"; r["note"]="ok"
json.dump({"results":res}, open("/home/claude/uimap/results-full.json","w"), ensure_ascii=False, indent=1)
cap=sum(1 for r in res if r["status"]=="captured")
print("results captured:",cap,"of",len(res))
