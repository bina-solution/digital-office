# V2 side-by-side composer: for each flow present in BOTH the mock manifest and a real manifest,
# stack the two webm videos horizontally (real | mock) with ffmpeg, and build a checkpoint
# diff contact-sheet. Until the real platform is captured, this runs mock-only (labels the
# real side "pending stack") so the harness is ready the moment `bbox run` is healthy.
import os, json, pathlib, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]
FLOWS = ROOT / 'verify/out/flows'
REAL = ROOT / 'verify/out/flows-real'   # produced by the real-side harness (flow_real.py), when available
OUT = ROOT / 'verify/out/flows-compare'
FFMPEG = "/opt/pw-browsers/ffmpeg-1011/ffmpeg-linux"  # bundled; falls back to PATH

def ffmpeg_bin():
    return FFMPEG if os.path.exists(FFMPEG) else 'ffmpeg'

def compose():
    OUT.mkdir(parents=True, exist_ok=True)
    mock = json.load(open(FLOWS / 'manifest.json')) if (FLOWS / 'manifest.json').exists() else {}
    real = json.load(open(REAL / 'manifest.json')) if (REAL / 'manifest.json').exists() else {}
    made = []
    for flow, m in mock.items():
        mv = ROOT / m['video'] if m.get('video') else None
        rv = ROOT / real[flow]['video'] if flow in real and real[flow].get('video') else None
        if not mv or not mv.exists():
            print(f'· {flow}: no mock video, skip'); continue
        # bundled ffmpeg is libvpx-only → output webm (vp9)
        if rv and rv.exists():
            outv = OUT / f'{flow}.webm'
            vf = "[0:v]scale=720:-1[l];[1:v]scale=720:-1[r];[l][r]hstack=inputs=2"
            cmd = [ffmpeg_bin(), '-y', '-i', str(rv), '-i', str(mv), '-filter_complex', vf,
                   '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '32', str(outv)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            ok = r.returncode == 0 and outv.exists()
            print(f'{"✓" if ok else "✗"} {flow}: real|mock -> {outv.name}')
            if not ok: print('   ', r.stderr[-300:])
            else: made.append(str(outv.relative_to(ROOT)))
        else:
            # mock-only until the real stack is captured — the recorded webm is already the artifact
            print(f'· {flow}: mock-only (real side pending) -> {m["video"]}')
            made.append(m['video'])
    json.dump({'composed': made, 'has_real': bool(real)}, open(OUT / 'index.json', 'w'), indent=1)
    print(f'\n{len(made)} composed. Real side present: {bool(real)}')
    if not real:
        print('Real side pending: run `bbox run` → `python3 verify/flow_real.py` to capture the real platform, then re-run this.')

if __name__ == '__main__':
    compose()
