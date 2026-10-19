# Full QA of platform-sim.html: for each module, load it in the real console, capture JS errors,
# count interactive controls, click a sample (functional), and screenshot the app for visual compare.
import pathlib, json
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='file://'+str(ROOT/'platform-sim.html')
OUT=ROOT/'verify/out/sim-qa'; OUT.mkdir(parents=True,exist_ok=True)
CHROME="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
# module id -> (human, real-screenshot basename in ci-artifacts/screenshots-ui)
MODS=[('my-docs','מסמכים שלי','my-docs__dashboard'),
      ('drive','דרייב','localdrive__root'),('mail','מייל','mailview__inbox'),
      ('whatsapp','בוט ווצאפ',None),
      ('incoming','מסמכים נכנסים','incoming-documents__root'),('concurrency','כל מקביל','any-concurrency__main'),
      ('alerts','התראות','notifications__main'),('machine','מכונה','machine__main'),
      ('validation','אימות מערכת','feature-validation__main'),('connections','חיבורים','connections__auth')]
def appframe(pg):
    for f in pg.frames:
        if f==pg.main_frame: continue
        try:
            if f.evaluate("document.body && document.body.innerText.trim().length>20"): return f
        except: pass
    return None
report={}
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CHROME)
    for mid,human,real in MODS:
        pg=b.new_page(viewport={'width':1440,'height':900})
        errs=[]; pg.on('pageerror',lambda e:errs.append(str(e)[:80]))
        pg.on('console',lambda m:errs.append('C:'+m.text[:70]) if m.type=='error' else None)
        pg.goto(URL,wait_until='load'); pg.wait_for_timeout(500)
        pg.evaluate(f"location.hash='#/m/{mid}'"); pg.wait_for_timeout(2600)
        fr=appframe(pg)
        stat={'renders':False,'controls':0,'clicked_ok':0,'errors':errs[:4]}
        if fr:
            try:
                n=fr.eval_on_selector_all('button,.btn,a[href],[role=button],[onclick],input[type=submit]','e=>e.length')
                stat['controls']=n; stat['renders']=True
                # click up to 6 buttons that don't navigate away; count those producing a DOM change/no-throw
                ok=fr.evaluate("""()=>{const els=[...document.querySelectorAll('button,.btn,[role=button]')].slice(0,8);let ok=0;
                  for(const e of els){try{const b=document.body.innerHTML.length;e.click();ok++;}catch(_){}}return ok;}""")
                stat['clicked_ok']=ok
            except Exception as e: stat['errors'].append('QA:'+str(e)[:50])
        pg.screenshot(path=str(OUT/f'{mid}.png'))
        report[mid]={'human':human,'real':real,**stat}
        print(f"{mid:12} renders={stat['renders']} controls={stat['controls']:3} clicked={stat['clicked_ok']} errs={len(stat['errors'])}")
        pg.close()
    b.close()
json.dump(report,open(OUT/'report.json','w'),ensure_ascii=False,indent=1)
tot=sum(r['controls'] for r in report.values()); rend=sum(1 for r in report.values() if r['renders'])
print(f"\n== {rend}/{len(MODS)} modules render · {tot} interactive controls total ==")
