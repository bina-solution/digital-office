#!/usr/bin/env python3
"""Generate CONTENT-UNIQUE per-suite corpus variants (true-parallel suites).

For each shared inv/ord/shp doc: locate the printed doc-number via the apitools OCR
word coordinates (300-DPI raster), white-out the region and stamp a suite-mutated
number (digit rotation on the trailing 4 — bijective, format/length preserved).
Tesseract then genuinely reads the NEW number: KW extraction, AI cache (cloned with
the number string-replaced) and GT all agree, and the COMPANY_ID+SHORT_DOC_ID dedup
can no longer collide across suites.

Usage: python scripts/gen-unique-corpus.py [--only khpr-mnhm-5]  (default: all)
Requires: pymupdf, pillow; docker exec access to the apitools container (OCR cache).
"""
import hashlib, json, os, re, subprocess, sys, tempfile

import fitz  # pymupdf
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _pdf_dpi():
    o = subprocess.run(['docker', 'exec', 'apitools', 'sh', '-c', 'echo -n "$APITOOLS_PDF_DPI"'],
                       capture_output=True)
    v = o.stdout.decode().strip()
    return float(v) if v else 200.0   # apitools default (src/pdf_core/pdf_to_jpg.py)
PDF_DPI = _pdf_dpi()
# [2026-08-23] REPOINTED. This read production/n8n/demo-docs, a tree the platform-OS refactor
# moved to apps/indox/blueprint/demo-docs. The script has therefore been unrunnable since
# that migration -- FileNotFoundError on the first source document -- which is exactly why
# shipment/files/mbnh-drvm-1.plp.pdf still prints the ORIGINAL id while
# fixtures/unique-corpus-map.json records the renumbering it was supposed to receive. The map
# recorded intent; the generator that was meant to realise it could not open its own inputs.
# Same class as the twelve gates that globbed *.json after the blueprints became .workflow.ts:
# a path left behind by a migration, in a tool nobody ran often enough to notice.
DOCS = os.path.join(ROOT, 'apps', 'indox', 'blueprint', 'demo-docs')

# (source rel path, full doc_id printed on the doc)
CORPUS = [
    ('invoice/files/khpr-mnhm-5.pdf', 'SI256006146'),
    ('invoice/files/nbl-3.pdf', 'SI256000443'),
    ('invoice/files/agn-3.pdf', 'SI256001661'),
    ('invoice/files/arkhh-3.pdf', '20342503040'),
    ('invoice/files/ysh-krtvn-4.pdf', 'SI266000818'),
    ('order/files/PO25010001.png', 'PO25010001'),
    ('order/files/PO25010002.png', 'PO25010002'),
    ('order/files/PO25010003.png', 'PO25010003'),
    ('order/files/PO25010004.png', 'PO25010004'),
    ('order/files/PO25010005.png', 'PO25010005'),
    ('shipment/files/by-gy-4.pdf', '02TSH25017987'),
    ('shipment/files/dyavr-4.pdf', 'SH26000378'),
    # Tesseract splits/misreads this doc's number ('SHM2501'+'512', the shp3 pin) —
    # aliases catch the fragments; short ones are white-out-only
    ('shipment/files/mbnh-drvm-1.pdf', 'SHM2501512', ['SHM2501', '512']),
    ('shipment/files/sbh-5.pdf', 'SH2611624'),
    ('shipment/files/pvlyrn-5.pdf', 'S0125005179'),
]
# suite tag -> digit rotation for the trailing 4 digits
SUITES = {'plp': 4, 'dbf': 7, 'plb': 2}
# which files each tag applies to (None = all of CORPUS)
SHARED3 = {'invoice/files/agn-3.pdf', 'order/files/PO25010001.png', 'shipment/files/by-gy-4.pdf'}
TAG_FILES = {'plp': None, 'dbf': SHARED3, 'plb': SHARED3}

def md5(b): return hashlib.md5(b).hexdigest()

def mutate(doc_id, rot):
    digs = [i for i, c in enumerate(doc_id) if c.isdigit()][-4:]
    out = list(doc_id)
    for i in digs: out[i] = str((int(out[i]) + rot) % 10)
    return ''.join(out)

def ocr_json(orig_bytes, ext='pdf'):
    # [2026-08-23] THE FILE CACHE IS GONE, so a miss is no longer a reason to refuse.
    # This read /app/.storage/ocr_cache/<md5>.json and raised "run the suites once first" when it
    # was absent. Measured: that directory is EMPTY (0 files) on a stack that has just run the
    # whole battery, and a fresh POST to /documentOcr returns 200 with the right file_hash and
    # still writes nothing there -- the OCR cache moved to Postgres. So the instruction in the
    # error message could never be satisfied and this script could not get past its first
    # document. Second stale assumption in the same file from the same migration (see DOCS
    # above), and together they are why the .plp. variants never received the ids the map
    # records for them.
    # The fallback is not new machinery: ocr_live() below already fetches exactly this shape
    # from the same endpoint. A cache hit is now an optimisation rather than a precondition.
    h = md5(orig_bytes)
    o = subprocess.run(['docker', 'exec', 'apitools', 'cat', f'/app/.storage/ocr_cache/{h}.json'],
                       capture_output=True)
    if o.stdout:
        return json.loads(o.stdout.decode('utf-8', errors='replace'))
    fd, tmp = tempfile.mkstemp(suffix='.' + ext)
    os.close(fd)
    try:
        with open(tmp, 'wb') as f:
            f.write(orig_bytes)
        return ocr_live(tmp, ext)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

def ocr_live(path, ext):
    """Fresh Tesseract OCR of a file via apitools (cache bypassed)."""
    mime = 'application/pdf' if ext == 'pdf' else 'image/png'
    subprocess.run(['docker', 'cp', path, 'apitools:/tmp/_stampchk'], capture_output=True, check=True)
    code = ("import requests,json;"
            "r=requests.post('http://127.0.0.1:8080/documentOcr?cache=false',"
            f"files={{'file':('f.{ext}',open('/tmp/_stampchk','rb').read(),'{mime}')}});"
            "print(json.dumps(r.json().get('ocr_json') or {}))")
    o = subprocess.run(['docker', 'exec', 'apitools', 'python3', '-c', code], capture_output=True)
    return json.loads(o.stdout.decode('utf-8', errors='replace') or '{}')

def find_bbox(ocr, needle, aliases=()):
    """bboxes of tokens carrying the doc number (or a known misread fragment)."""
    cands = []
    for a in ocr.get('textAnnotations', [])[1:]:
        t = a.get('description', '')
        hit = (needle in t or
               (len(needle) >= 5 and needle[-5:] in t and sum(c.isdigit() for c in t) >= 5) or
               any(al in t for al in aliases))
        if hit:
            vs = a['boundingPoly']['vertices']
            xs = [v.get('x', 0) for v in vs]; ys = [v.get('y', 0) for v in vs]
            cands.append((min(xs), min(ys), max(xs), max(ys), t))
    if not cands:
        raise RuntimeError(f'doc number {needle} not found in OCR tokens')
    # the number often appears MORE THAN ONCE (title line + field) — stamp every occurrence
    return cands

def tokens_at_risk(ocr, cands, pad=6):
    """Every ORIGINAL token that a stamp box will land on, except the id being replaced.

    [2026-08-23] Generalises find_dates. Restoring only the date was not enough: after the id
    stamp the date read back under a raw regex but q_v3_date_base still answered None, because
    that query is anchored -- it finds the Hebrew label and takes the value after it, and the
    LABEL was under the box too. Redrawing the value without its anchor puts the text back and
    leaves the field unfindable, which is the same outcome from the reader's side.

    THE INVARIANT: a stamp may remove the token it replaces and nothing else. So capture every
    token whose box overlaps a box we are about to draw over -- while they are still readable --
    and put them all back afterwards.
    """
    boxes = []
    for (x0, y0, x1, y1, tok) in cands:
        # stamp_pdf widens to the right to fit the new token; assume the worst case
        boxes.append((x0 - pad, y0 - pad, x1 + pad + (x1 - x0), y1 + pad))
    out = []
    for a in (ocr.get('textAnnotations') or [])[1:]:
        t = (a.get('description') or '').strip()
        if not t:
            continue
        vs = a.get('boundingPoly', {}).get('vertices') or []
        if len(vs) < 4:
            continue
        xs = [v.get('x', 0) for v in vs]; ys = [v.get('y', 0) for v in vs]
        ax0, ay0, ax1, ay1 = min(xs), min(ys), max(xs), max(ys)
        for (bx0, by0, bx1, by1) in boxes:
            if ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0:
                out.append((ax0, ay0, ax1, ay1, t))
                break
    return out


def find_dates(ocr):
    """Date tokens in the ORIGINAL OCR, captured BEFORE any stamping can cover them.

    [2026-08-23] The id stamp erases the date. Two stampers write the same page --
    refresh-corpus-dates puts the current date on the SOURCE, then this script regenerates the
    variant from that source and draws the new id over it, up to four passes deep -- and the date
    does not survive. Measured on mbnh-drvm-1.plp.pdf: after stamping, the new id read back
    cleanly while NO date pattern matched the page at all, and the document reached STATUS:GARBAGE
    in the pipeline suite because nothing could date it.

    The repair is not to search for the date afterwards -- by then there is nothing to find, which
    is exactly why re-running refresh-corpus-dates cannot fix it. It is to remember where the date
    WAS while it is still readable, and write it back afterwards. stamp_pdf/stamp_png already draw
    given text into a given box; passing needle == newid makes them redraw a token as itself.
    """
    pat = re.compile(r'^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$')
    out = []
    for a in (ocr.get('textAnnotations') or [])[1:]:
        t = (a.get('description') or '').strip()
        if not pat.match(t):
            continue
        vs = a.get('boundingPoly', {}).get('vertices') or []
        if len(vs) < 4:
            continue
        xs = [v.get('x', 0) for v in vs]; ys = [v.get('y', 0) for v in vs]
        out.append((min(xs), min(ys), max(xs), max(ys), t))
    return out

# docs where widening the white-out clips NEIGHBORING labels (RTL layouts) — keep orig box
NOWIDEN = {'pvlyrn-5'}

def stamp_pdf(path, cands, needle, newid):
    doc = fitz.open(path)
    s = 72.0 / PDF_DPI   # match apitools' actual PDF raster DPI
    # apitools OCRs multi-page PDFs as vertically STACKED page images —
    # map a raster y to (page index, local y) via cumulative page heights
    heights = [p.rect.height / s for p in doc]   # per-page raster heights
    def locate(y):
        acc = 0.0
        for i, h in enumerate(heights):
            if y < acc + h: return i, y - acc
            acc += h
        return len(heights) - 1, y - (acc - heights[-1])
    pad = 4
    jobs = []
    for (x0, y0, x1, y1, tok) in cands:
        pi, ly0 = locate(y0)
        ly1 = ly0 + (y1 - y0)
        page = doc[pi]
        rect = fitz.Rect(x0 * s - pad, ly0 * s - pad, x1 * s + pad, ly1 * s + pad)
        newtok = tok.replace(needle, newid) if needle in tok else newid
        fs = max(9.0, rect.height * 0.70)
        if not any(k in path for k in NOWIDEN):
            need_w = len(newtok) * fs * 0.60 + 2 * pad
            if need_w > rect.width:
                rect = fitz.Rect(rect.x0, rect.y0, rect.x0 + need_w, rect.y1)
        else:
            fs = min(fs, rect.width / (len(newtok) * 0.60))   # shrink text into the box instead
        jobs.append((page, rect, newtok, fs))
    # merge overlapping candidates (duplicate tokens over the same print) — stacked
    # stamp texts garble each other
    merged = []
    for page, rect, newtok, fs in jobs:
        for m in merged:
            if m[0] is page and m[1].intersects(rect):
                m[1] |= rect
                break
        else:
            merged.append([page, rect, newtok, fs])
    # ALL white-outs first — overlapping candidates must not erase each other's text
    for page, rect, _, _ in merged:
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
    for page, rect, newtok, fs in merged:
        page.insert_text(fitz.Point(rect.x0 + pad, rect.y1 - rect.height * 0.28),
                         newtok, fontsize=fs, fontname='hebo', color=(0, 0, 0))
    tmp = path + '.tmp'
    doc.save(tmp); doc.close()
    for attempt in range(6):   # Windows: transient locks from AV/indexer/docker cp
        try:
            os.replace(tmp, path); break
        except PermissionError:
            import time; time.sleep(0.5 * (attempt + 1))
    else:
        os.replace(tmp, path)

def stamp_png(path, cands, needle, newid):
    im = Image.open(path).convert('RGB')
    dr = ImageDraw.Draw(im)
    for (x0, y0, x1, y1, tok) in cands:
        X0, Y0, X1, Y1 = int(x0) - 3, int(y0) - 3, int(x1) + 3, int(y1) + 3
        newtok = tok.replace(needle, newid) if needle in tok else newid
        h = Y1 - Y0
        font = None
        for fp in (r'C:\Windows\Fonts\arialbd.ttf', r'C:\Windows\Fonts\arial.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
            try: font = ImageFont.truetype(fp, max(14, int(h * 0.9))); break
            except Exception: pass
        tw = int(dr.textlength(newtok, font=font)) if font else len(newtok) * h
        X1 = max(X1, X0 + tw + 6)   # widen the white-out to fit the stamp
        dr.rectangle([X0, Y0, X1, Y1], fill='white')
        dr.text((X0 + 3, Y0 + 1), newtok, fill='black', font=font)
    im.save(path)

def full_text(ocr):
    anns = ocr.get('textAnnotations') or [{}]
    return anns[0].get('description', '')

def make_variant(rel, doc_id, tag, rot, aliases=()):
    """Copy src -> variant, then iteratively stamp until Tesseract no longer reads
    the OLD number anywhere (misreads split occurrences across passes)."""
    base, ext = rel.rsplit('.', 1)
    vrel = f'{base}.{tag}.{ext}'
    src = os.path.join(DOCS, rel.replace('/', os.sep))
    dst = os.path.join(DOCS, vrel.replace('/', os.sep))
    newid = mutate(doc_id, rot)
    with open(src, 'rb') as f: data = f.read()
    with open(dst, 'wb') as f: f.write(data)
    ocr = ocr_json(data, ext)                  # pass 1 = original OCR (cache, else fresh)
    # [2026-08-23] DATES ONLY, and that is a measured choice, not laziness.
    # tokens_at_risk() below generalises this to 'every token the stamp will land on',
    # which is the correct invariant and made the result WORSE: redrawing N tokens paints N
    # white rectangles first, and the Hebrew labels do not survive a re-render through the
    # default font. Measured on mbnh-drvm-1.plp.pdf --
    #     date-only redraw : id 'SHM2505956' OK, raw date '24/07/26' READABLE
    #     all-token redraw : id OK, no date on the page at all
    # So the generalisation is kept as a function and NOT used. Restoring one high-value
    # token faithfully beats restoring many badly.
    dates_before = find_dates(ocr)             # where the dates are, while still readable
    old5, new5 = doc_id[-5:], newid[-5:]
    for p in range(1, 5):
        try:
            cands = find_bbox(ocr, doc_id, aliases)
        except RuntimeError:
            cands = []
        if not cands:
            break
        (stamp_pdf if ext == 'pdf' else stamp_png)(dst, cands, doc_id, newid)
        ocr = ocr_live(dst, ext)
        txt = full_text(ocr)
        if old5 not in txt and doc_id not in txt:
            break
    # Put every date back where it was. Same token into the same box, so nothing widens
    # and nothing is searched for -- this runs LAST precisely because the id stamp is what
    # covered it.
    for _d in dates_before:
        (stamp_pdf if ext == 'pdf' else stamp_png)(dst, [_d], _d[4], _d[4])
    ocr = ocr_live(dst, ext)                   # re-read AFTER the date redraw
    txt = full_text(ocr)
    ok_new, ok_old = (new5 in txt), (old5 not in txt and doc_id not in txt)
    status = 'OK' if (ok_new and ok_old) else f'CHECK(new={ok_new},old_gone={ok_old})'
    print(f'{tag}: {vrel}  {doc_id} -> {newid}  passes={p}  {status}')
    return vrel, newid, md5(data), md5(open(dst, "rb").read()), (ok_new and ok_old)

def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    plan, bad = [], []
    for entry in CORPUS:
        rel, doc_id = entry[0], entry[1]
        aliases = entry[2] if len(entry) > 2 else ()
        if only and only not in rel: continue
        for tag, rot in SUITES.items():
            allowed = TAG_FILES.get(tag)
            if allowed is not None and rel not in allowed: continue
            if '--tags' in sys.argv and tag not in sys.argv[sys.argv.index('--tags') + 1].split(','): continue
            vrel, newid, om, nm, ok = make_variant(rel, doc_id, tag, rot, aliases)
            plan.append((tag, rel, vrel, doc_id, newid, om, nm))
            if not ok: bad.append(vrel)
    if bad:
        print(f'\n!! {len(bad)} variants need manual review: {bad}')
    mp = os.path.join(DOCS, 'fixtures', 'unique-corpus-map.json')
    try: existing = {e['vrel']: e for e in json.load(open(mp, encoding='utf-8'))}
    except Exception: existing = {}
    for p in plan:
        existing[p[2]] = {'suite': p[0], 'rel': p[1], 'vrel': p[2], 'old_id': p[3],
                          'new_id': p[4], 'orig_md5': p[5], 'new_md5': p[6]}
    json.dump(sorted(existing.values(), key=lambda e: e['vrel']),
              open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{len(plan)} variants stamped; map written to fixtures/unique-corpus-map.json')

if __name__ == '__main__':
    main()
