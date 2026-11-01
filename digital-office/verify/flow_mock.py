# V2 functional-flow harness (mock side): drive canonical per-app flows on the simulator,
# record a webm video + checkpoint screenshots per flow, and a contact-sheet montage.
# Real-platform counterpart runs the SAME flow ids when the stack is healthy; the two videos
# are composed side-by-side (ffmpeg) and checkpoints diffed. See ROADMAP V2.
import os, pathlib, json
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = 'file://' + str(ROOT / 'platform-mockup.html')
OUT = ROOT / 'verify/out/flows'
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
VW, VH = 1440, 900

# Each flow = a list of (label, fn) steps. fn(pg) performs the step; a checkpoint screenshot
# is taken after each. Steps use DO's public API + real DOM clicks so the video shows real motion.
def step_wait(ms):
    return lambda pg: pg.wait_for_timeout(ms)

def goto(id):
    return lambda pg: (pg.evaluate("i=>window.go(i)", id), pg.wait_for_timeout(500))

FLOWS = {
    "mydocs-create-invoice": [
        ("open my-docs", goto("mydocs-docs")),
        ("open new-doc modal", lambda pg: (pg.eval_on_selector('[data-open="new-doc"]', 'e=>e.click()'), pg.wait_for_timeout(500))),
        ("fill amount", lambda pg: (pg.fill('#nd-total', '4200'), pg.wait_for_timeout(400))),
        ("submit → new row + toast", lambda pg: (pg.eval_on_selector('[data-action="submit-new-doc"]', 'e=>e.click()'), pg.wait_for_timeout(900))),
    ],
    "indox-pipeline-moves": [
        ("open INDOX dashboard", goto("indox-root")),
        ("tick — a doc enters processing", lambda pg: (pg.evaluate("DO.tick()"), pg.wait_for_timeout(700))),
        ("tick — a doc completes", lambda pg: (pg.evaluate("DO.tick()"), pg.wait_for_timeout(700))),
        ("open the repo documents grid", goto("indox-repo-docs")),
        ("tick — grid grows", lambda pg: ([pg.evaluate("DO.tick()") for _ in range(3)], pg.wait_for_timeout(700))),
    ],
    "drive-drag-move": [
        ("open drive", goto("drive-root")),
        ("select folder gdoc", lambda pg: (pg.evaluate("DO.actions.selectFolder({folder:'gdoc'})"), pg.wait_for_timeout(500))),
        ("move a file to bs", lambda pg: (pg.evaluate("DO.actions.moveFile({file:'d2', to:'bs'})"), pg.wait_for_timeout(700))),
        ("upload a new file", lambda pg: (pg.evaluate("DO.actions.uploadFile()"), pg.wait_for_timeout(700))),
    ],
    "mail-read": [
        ("open inbox", goto("mail-inbox")),
        ("tick — new mail arrives", lambda pg: ([pg.evaluate("DO.tick()") for _ in range(3)], pg.wait_for_timeout(700))),
        ("mark all read", lambda pg: (pg.evaluate("DO.actions.readAll && DO.actions.readAll()"), pg.wait_for_timeout(700))),
    ],
    "command-palette": [
        ("open palette (Ctrl-K)", lambda pg: (pg.keyboard.down('Control'), pg.keyboard.press('k'), pg.keyboard.up('Control'), pg.wait_for_timeout(500))),
        ("type a query", lambda pg: (pg.keyboard.type('מכונה'), pg.wait_for_timeout(500))),
        ("Enter → jump to screen", lambda pg: (pg.keyboard.press('Enter'), pg.wait_for_timeout(700))),
    ],
}

def run():
    manifest = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        for flow, steps in FLOWS.items():
            fdir = OUT / flow
            (fdir / 'checkpoints').mkdir(parents=True, exist_ok=True)
            ctx = b.new_context(viewport={'width': VW, 'height': VH},
                                record_video_dir=str(fdir), record_video_size={'width': VW, 'height': VH})
            pg = ctx.new_page()
            pg.goto(URL, wait_until='load'); pg.wait_for_timeout(600)
            pg.add_style_tag(content='#navBtn{display:none!important}')
            cps = []
            for i, (label, fn) in enumerate(steps):
                try:
                    fn(pg)
                except Exception as e:
                    print(f'  [{flow}] step {i} "{label}" ERR: {e}')
                shot = fdir / 'checkpoints' / f'{i:02d}.png'
                pg.screenshot(path=str(shot))
                cps.append({'i': i, 'label': label, 'shot': str(shot.relative_to(ROOT))})
            ctx.close()  # flush video
            vids = list(fdir.glob('*.webm'))
            manifest[flow] = {'video': str(vids[0].relative_to(ROOT)) if vids else None, 'checkpoints': cps}
            print(f'✓ {flow}: {len(cps)} checkpoints, video={"yes" if vids else "NO"}')
        b.close()
    (OUT).mkdir(parents=True, exist_ok=True)
    json.dump(manifest, open(OUT / 'manifest.json', 'w'), ensure_ascii=False, indent=1)
    print('manifest ->', OUT / 'manifest.json')

if __name__ == '__main__':
    run()
