#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-container half of scripts/refresh-corpus-dates.py — runs INSIDE apitools.

apitools is the only place in the deployment that has both the OCR engine the product
actually uses and the raster/PDF toolchain (fitz + pillow), so the stamping happens
there rather than on the host: a fresh clone needs nothing installed beyond the stack
it already runs.

Contract (stdin JSON on argv[1], result JSON on argv[2]):
  {"path": "/tmp/x.pdf", "ext": "pdf", "replacements": [{"from": "22/04/25", "to": "05/07/26"}, ...]}
  -> {"ok": bool, "engine": str, "md5": str, "stamped": [...], "still_present": [...],
      "now_present": [...], "passes": int}

Every replacement is verified by re-OCRing the stamped file through the SAME apitools
endpoint the pipeline uses (`/documentOcr?cache=false`): the old token must be gone and
the new token must be readable. A replacement that cannot be verified is reported, never
silently accepted — the corpus this produces is the ground truth two E2E suites assert
against, so "probably stamped" is worthless.
"""
import hashlib
import io
import json
import os
import sys
import time

import fitz  # pymupdf
import requests
from PIL import Image, ImageDraw, ImageFont

OCR_URL = 'http://127.0.0.1:8080/documentOcr?cache=false'
# apitools rasterises PDFs at APITOOLS_PDF_DPI — src/pdf_core/pdf_to_jpg.py:
#     PDF_OCR_DPI = int(os.getenv('APITOOLS_PDF_DPI', '300'))
# The env var is normally unset, so the default IS the value; get it wrong and every
# raster-OCR box maps to the wrong place on the page. (scripts/gen-unique-corpus.py still
# falls back to 200 here — stale, and worth fixing when that script is next touched.)
try:
    sys.path.insert(0, '/app')
    from src.pdf_core.pdf_to_jpg import PDF_OCR_DPI as _DPI   # authoritative
    PDF_DPI = float(_DPI)
except Exception:
    PDF_DPI = float(os.environ.get('APITOOLS_PDF_DPI') or 300.0)
MIME = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg'}


def md5(b):
    return hashlib.md5(b).hexdigest()


def ocr(path, ext):
    """OCR through the running apitools engine, retrying the transport.

    apitools restarts (memory ladder, another lane's run) drop the connection mid-request
    and return an empty body; `r.json()` then dies with a decode error that says nothing
    about the real cause. Retry, and if it still fails surface the status and body — a
    corpus generator that reports "JSONDecodeError" instead of "apitools was restarting"
    costs the next reader an hour.
    """
    with open(path, 'rb') as fh:
        data = fh.read()
    last = ''
    for attempt in range(5):
        try:
            r = requests.post(OCR_URL,
                              files={'file': ('f.' + ext, data, MIME.get(ext, 'image/jpeg'))},
                              timeout=900)
            j = r.json()
            return (j.get('ocr_json') or {},
                    j.get('ocr_engine') or (j.get('ocr_json') or {}).get('ocr_engine'))
        except Exception as ex:
            last = '%s: %s' % (type(ex).__name__, ex)
            try:
                last += ' | HTTP %s body=%r' % (r.status_code, r.text[:200])
            except Exception:
                pass
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('apitools /documentOcr failed 5x for %s — %s' % (path, last))


def tokens(oj):
    """(text, x0, y0, x1, y1) for every OCR word box."""
    out = []
    for a in (oj.get('textAnnotations') or [])[1:]:
        t = (a.get('description') or '').strip()
        vs = (a.get('boundingPoly') or {}).get('vertices') or []
        if not t or not vs:
            continue
        xs = [v.get('x', 0) for v in vs]
        ys = [v.get('y', 0) for v in vs]
        out.append((t, min(xs), min(ys), max(xs), max(ys)))
    return out


def full_text(oj):
    anns = oj.get('textAnnotations') or [{}]
    return anns[0].get('description', '') or ''


def scale_for(engine):
    """OCR box units -> PDF points.

    `pdf_textlayer` reads the PDF's own text objects, so its boxes are already in PDF
    user space (72/inch). `local` (Tesseract) reads a raster rendered at PDF_DPI, so its
    boxes are raster pixels. Getting this backwards silently white-outs the wrong part of
    the page, which is why the caller re-OCRs and asserts instead of trusting the maths.
    """
    return 1.0 if engine == 'pdf_textlayer' else 72.0 / PDF_DPI


def stamp_pdf(path, hits, engine):
    doc = fitz.open(path)
    s = scale_for(engine)
    heights = [p.rect.height / s for p in doc]   # per-page height in OCR box units

    def locate(y):
        # multi-page PDFs are OCRed as one vertically stacked image; map back to a page
        acc = 0.0
        for i, h in enumerate(heights):
            if y < acc + h:
                return i, y - acc
            acc += h
        return len(heights) - 1, y - (acc - heights[-1])

    pad = 2
    jobs = []
    for (new, x0, y0, x1, y1) in hits:
        pi, ly0 = locate(y0)
        ly1 = ly0 + (y1 - y0)
        rect = fitz.Rect(x0 * s - pad, ly0 * s - pad, x1 * s + pad, ly1 * s + pad)
        fs = max(6.0, rect.height * 0.72)
        need = len(new) * fs * 0.55 + 2 * pad
        if need > rect.width:            # keep the stamp inside its own box: shrink, do not
            fs = fs * rect.width / need  # widen — dates sit inside ruled table cells here
        jobs.append((doc[pi], rect, new, fs))
    # REDACT, do not paint over. Half this corpus is born-digital: apitools reads those
    # through `pdf_textlayer`, straight off the content stream, so a white rectangle drawn
    # on top leaves the old date perfectly readable to the extractor while looking replaced
    # to a human. add_redact_annot + apply_redactions removes the text objects themselves;
    # PDF_REDACT_IMAGE_NONE keeps the scan underneath intact for the raster documents.
    for page, rect, _, _ in jobs:
        page.add_redact_annot(rect, fill=(1, 1, 1))
    for page in {id(p): p for p, _, _, _ in jobs}.values():
        page.apply_redactions(images=getattr(fitz, 'PDF_REDACT_IMAGE_NONE', 0))
    for page, rect, new, fs in jobs:
        page.insert_text(fitz.Point(rect.x0 + pad, rect.y1 - rect.height * 0.25),
                         new, fontsize=fs, fontname='hebo', color=(0, 0, 0))
    tmp = path + '.tmp'
    doc.save(tmp)
    doc.close()
    os.replace(tmp, path)


def stamp_pdf_raster(path, hits, _engine):
    """Stamp a SCANNED pdf by re-rendering its pages as images.

    Do NOT use the text route here. apitools picks its engine per document: a PDF with no
    text layer goes to Tesseract (`local`), but `insert_text` gives the file a text layer
    containing ONLY the stamped dates — apitools then switches to `pdf_textlayer` and the
    document reads as ~9 tokens instead of ~460. Measured: by-gy-4.plb.pdf came back
    TYPE=GARBAGE (the <3-words rule) after a text-route stamp. Rendering the page, drawing
    on the pixels and putting the raster back keeps the document a scan, which is what it is.

    OCR boxes are raster pixels at PDF_DPI here, so they map 1:1 onto the pixmap — no
    scaling, which is also one less thing to get wrong.
    """
    doc = fitz.open(path)
    dpi = PDF_DPI
    pix = [p.get_pixmap(dpi=int(dpi)) for p in doc]
    imgs = [Image.frombytes('RGB', (p.width, p.height), p.samples) for p in pix]
    heights = [im.height for im in imgs]

    def locate(y):
        acc = 0
        for i, h in enumerate(heights):
            if y < acc + h:
                return i, y - acc
            acc += h
        return len(heights) - 1, y - (acc - heights[-1])

    per_page = {}
    for (new, x0, y0, x1, y1) in hits:
        pi, ly0 = locate(y0)
        per_page.setdefault(pi, []).append((new, x0, ly0, x1, ly0 + (y1 - y0)))
    for pi, items in per_page.items():
        _draw(imgs[pi], items)
    out = fitz.open()
    for im, page in zip(imgs, doc):
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=92)
        np = out.new_page(width=page.rect.width, height=page.rect.height)
        np.insert_image(np.rect, stream=buf.getvalue())
    tmp = path + '.tmp'
    out.save(tmp)
    out.close()
    doc.close()
    os.replace(tmp, path)


def _draw(im, items):
    dr = ImageDraw.Draw(im)
    for (new, x0, y0, x1, y1) in items:
        X0, Y0, X1, Y1 = int(x0) - 2, int(y0) - 2, int(x1) + 2, int(y1) + 2
        h = Y1 - Y0
        font = None
        for fp in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                   '/app/src/doc_gen/fonts/DejaVuSans.ttf'):
            try:
                font = ImageFont.truetype(fp, max(10, int(h * 0.85)))
                break
            except Exception:
                pass
        tw = int(dr.textlength(new, font=font)) if font else len(new) * h // 2
        X1 = max(X1, X0 + tw + 4)     # widen the white-out so the stamp is never clipped
        dr.rectangle([X0, Y0, X1, Y1], fill='white')
        dr.text((X0 + 2, Y0 + 1), new, fill='black', font=font)


def stamp_img(path, hits, _engine):
    im = Image.open(path).convert('RGB')
    fmt = Image.open(path).format
    _draw(im, hits)
    # write-then-replace: `docker cp` lands the file root-owned 0644, so re-opening it for
    # write fails as the container's own user even though the directory is writable — the
    # same reason the PDF branch saves to a temp name. (PermissionError on /tmp/_rcd.png.)
    tmp = path + '.tmp'
    im.save(tmp, format=fmt)
    os.replace(tmp, path)


def main():
    job = json.load(open(sys.argv[1], encoding='utf-8'))
    path, ext = job['path'], job['ext']
    reps = {r['from']: r['to'] for r in job['replacements']}
    oj, engine = ocr(path, ext)
    # Route on the engine apitools chose for the ORIGINAL file, and keep routing that way:
    # after the first raster stamp the file is still a scan, and after the first text stamp
    # it is still born-digital. Re-deciding from the post-stamp engine is how a scan ends up
    # on the text route on pass 2.
    origin_engine = engine
    n_tokens0 = len(tokens(oj))
    if ext != 'pdf':
        stamper = stamp_img
    elif origin_engine == 'pdf_textlayer':
        stamper = stamp_pdf
    else:
        stamper = stamp_pdf_raster
    passes = 0
    for passes in range(1, 5):
        hits = [(reps[t], x0, y0, x1, y1) for (t, x0, y0, x1, y1) in tokens(oj) if t in reps]
        if not hits:
            break
        stamper(path, hits, origin_engine)
        oj, engine = ocr(path, ext)
    txt = full_text(oj)
    still = sorted({o for o in reps if o in txt})
    now = sorted({n for n in reps.values() if n in txt})
    with open(path, 'rb') as fh:
        digest = md5(fh.read())
    # Content-loss guard. Stamping must change three dates, not the document: a stamp that
    # halves the readable token count has broken the file even when both date checks pass.
    # This is the check that would have caught by-gy-4 (463 tokens -> 9, TYPE=GARBAGE)
    # before it reached a suite.
    kept = len(tokens(oj))
    lost = kept < max(10, int(n_tokens0 * 0.7))
    json.dump({'ok': not still and len(now) == len(set(reps.values())) and not lost,
               'tokens_before': n_tokens0, 'tokens_after': kept,
               'content_lost': lost,
               'engine': engine, 'md5': digest, 'passes': passes,
               'still_present': still, 'now_present': now,
               'expected': sorted(set(reps.values()))},
              open(sys.argv[2], 'w', encoding='utf-8'))


if __name__ == '__main__':
    main()
