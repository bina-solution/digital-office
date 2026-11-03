# Visual 1:1 gate: diff each rendered mock screen vs the real capture. Writes per-view
# real|mock|diff rows + scores.json + a comparison montage. % = pixels differing (max-channel>28).
import os, json, glob
from PIL import Image, ImageDraw
import numpy as np
ROOT='/home/user/deployment-hacohen'
MOCK='verify/out/mock'
REAL_DIRS=[ROOT+'/ci-artifacts/screenshots-ui', 'reference/real-screenshots']  # prefer latest capture
mp=json.load(open('tooling/map.json'))  # mock-id -> real basename
W,H=1440,900
def load(path):
    im=Image.open(path).convert('RGB')
    if im.size!=(W,H): im=im.resize((W,H))
    return im
def find_real(base):
    for d in REAL_DIRS:
        p=os.path.join(d,base+'.png')
        if os.path.exists(p): return p
    return None
rows=[]; scores={}
for mockpng in sorted(glob.glob(MOCK+'/*.png')):
    sid=os.path.splitext(os.path.basename(mockpng))[0]
    base=mp.get(sid)
    real=find_real(base) if base else None
    if not real: scores[sid]={'diff':None,'real':None}; continue
    a=np.asarray(load(real)).astype(int); b=np.asarray(load(mockpng)).astype(int)
    d=np.abs(a-b).max(axis=2); mask=d>28; pct=round(100*mask.mean(),2)
    scores[sid]={'diff':pct,'real':base}
    # overlay: real in red, mock in green (yellow=match)
    ov=np.zeros((H,W,3),dtype=np.uint8)
    ra=np.asarray(load(real).convert('L')); rb=np.asarray(load(mockpng).convert('L'))
    ov[...,0]=ra; ov[...,1]=rb
    rows.append((sid,pct,load(real),load(mockpng),Image.fromarray(ov)))
# summary
have=[s for s in scores.values() if s['diff'] is not None]
mean=round(sum(s['diff'] for s in have)/max(1,len(have)),2)
med=sorted(s['diff'] for s in have); med=med[len(med)//2] if med else None
json.dump({'mean':mean,'median':med,'n':len(have),'total_screens':len(scores),'scores':scores},
          open('verify/out/scores.json','w'),ensure_ascii=False,indent=1)
# montage: worst-first, rows of [real|mock|overlay]
rows.sort(key=lambda r:-r[1])
tw=440; th=int(H*tw/W); pad=8; lblh=20
mont=Image.new('RGB',(3*tw+4*pad, len(rows)*(th+lblh+pad)+pad),(24,32,28)); dr=ImageDraw.Draw(mont)
for i,(sid,pct,r,m,o) in enumerate(rows):
    y=pad+i*(th+lblh+pad)
    for j,img in enumerate([r,m,o]):
        mont.paste(img.resize((tw,th)),(pad+j*(tw+pad),y+lblh))
    dr.text((pad,y+4),f'{sid}   diff {pct}%   [real | mock | overlay]',fill=(180,220,200))
mont.save('verify/out/ui-map-comparison.png')
print(f'V1 visual gate: mean {mean}% | median {med}% | scored {len(have)}/{len(scores)} screens')
print('worst 8:', [ (s, round(v["diff"],1)) for s,v in sorted(scores.items(), key=lambda kv:-(kv[1]["diff"] or 0))[:8] ])
