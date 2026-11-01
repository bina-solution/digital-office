# V2 real-side harness: run the SAME canonical flow ids as flow_mock.py, but against the LIVE
# platform (the routed *.localhost stack that `bbox run` brings up). Records a webm + checkpoints
# per flow into verify/out/flows-real/, mirroring flow_mock's manifest so compose_flows.py can
# stack them real|mock and diff checkpoints.
#
# Prereq: a healthy stack (`./bbox run`). Base URLs below match deployment-context routing; adjust
# the login/nav selectors to the real DOM (the mock's data-* hooks do NOT exist on the real app —
# these steps click real buttons/links by role/text). Left as an explicit, reviewed mapping so the
# real capture is honest rather than auto-generated.
import os, pathlib, json
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'verify/out/flows-real'
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
VW, VH = 1440, 900
BASE = os.environ.get('DO_BASE', 'http://my-docs.localhost')   # per deployment-context.txt

# Map each flow to (entry_url, [steps]) on the REAL app. Selectors are placeholders keyed to the
# real UI; fill/confirm them against the running app before trusting the diff. Kept deliberately
# small so the first real capture is reviewable.
FLOWS = {
    "mydocs-create-invoice": {
        "url": BASE + "/documents",
        "steps": [
            ("open my-docs", lambda pg: pg.wait_for_timeout(800)),
            ("click new document", lambda pg: (pg.get_by_role("button", name="מסמך חדש").first.click(), pg.wait_for_timeout(600))),
            ("fill amount", lambda pg: pg.wait_for_timeout(600)),   # TODO real field selector
            ("submit", lambda pg: pg.wait_for_timeout(800)),        # TODO real submit selector
        ],
    },
    # indox-pipeline-moves / drive-drag-move / mail-read / command-palette:
    # add real entry URLs + selectors once the corresponding real apps are confirmed reachable.
}

def run():
    if not FLOWS:
        print('No real flows defined yet.'); return
    manifest = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        for flow, spec in FLOWS.items():
            fdir = OUT / flow
            (fdir / 'checkpoints').mkdir(parents=True, exist_ok=True)
            ctx = b.new_context(viewport={'width': VW, 'height': VH},
                                record_video_dir=str(fdir), record_video_size={'width': VW, 'height': VH},
                                ignore_https_errors=True)
            pg = ctx.new_page()
            try:
                pg.goto(spec["url"], wait_until='load', timeout=20000)
            except Exception as e:
                print(f'✗ {flow}: cannot reach {spec["url"]} — is the stack up? {e}')
                ctx.close(); continue
            cps = []
            for i, (label, fn) in enumerate(spec["steps"]):
                try: fn(pg)
                except Exception as e: print(f'  [{flow}] step {i} "{label}" ERR: {e}')
                shot = fdir / 'checkpoints' / f'{i:02d}.png'
                pg.screenshot(path=str(shot)); cps.append({'i': i, 'label': label})
            ctx.close()
            vids = list(fdir.glob('*.webm'))
            manifest[flow] = {'video': str(vids[0].relative_to(ROOT)) if vids else None, 'checkpoints': cps}
            print(f'✓ {flow}: {len(cps)} checkpoints, video={"yes" if vids else "NO"}')
        b.close()
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(manifest, open(OUT / 'manifest.json', 'w'), ensure_ascii=False, indent=1)
    print('real manifest ->', OUT / 'manifest.json')

if __name__ == '__main__':
    run()
