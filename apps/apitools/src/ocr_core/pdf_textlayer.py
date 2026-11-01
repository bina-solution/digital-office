# -*- coding: utf-8 -*-
"""Born-digital PDF extraction — read the embedded text layer instead of OCR.

Real-world-correct and robust: a PDF that already carries a text layer (an
e-invoice, a system-generated document) should NOT be rasterised and OCR'd —
that only injects OCR error (mangled Hebrew, ₪→1, dropped digits). We read the
text layer directly with PyMuPDF and emit the SAME Google-Vision-shaped result
(``textAnnotations`` word boxes + ``fullTextAnnotation.text``) the rest of the
pipeline expects, so the keyword-query engine runs on perfect input. Scanned
images (no text layer) still fall through to Tesseract/Vision.

Hebrew typography is normalised on the way out — gershayim ״→", geresh ׳→', and
bidi control marks stripped — so keyword anchors written with ASCII quotes match
regardless of how the source typeset them.
"""
from __future__ import annotations

import os
import fitz  # pymupdf

from src.utils.logging_config import get_logger

logger = get_logger('apitools.pdf_textlayer')

# gershayim/geresh -> ASCII quotes; drop bidi controls (LRM/RLM/ALM/embeds)
_MAP = {'״': '"', '׳': "'", '‎': '', '‏': '', '؜': '',
        '‪': '', '‫': '', '‬': '', '⁦': '', '⁧': '', '⁨': '', '⁩': ''}
_TRANS = {ord(k): v for k, v in _MAP.items()}


def heb_norm(s: str) -> str:
    """Normalise Hebrew punctuation + strip bidi marks so ASCII-quote anchors match."""
    return (s or '').translate(_TRANS)


def has_text_layer(pdf_path: str, min_chars: int = 40) -> bool:
    """True if the PDF carries a usable embedded text layer (i.e. born-digital)."""
    try:
        with fitz.open(pdf_path) as d:
            return sum(len((p.get_text() or '').strip()) for p in d) >= min_chars
    except Exception:
        return False


def _rect(x0, y0, x1, y1):
    return [{"x": int(x0), "y": int(y0)}, {"x": int(x1), "y": int(y0)},
            {"x": int(x1), "y": int(y1)}, {"x": int(x0), "y": int(y1)}]


# Vocabulary for detecting visually-stored (reversed) Hebrew text layers.
_HEB_VOCAB = ['סה"כ', 'תאריך', 'חשבונית', 'בע"מ', 'לתשלום', 'לכבוד', 'טלפון', 'מספר',
              'עוסק', 'מורשה', 'כולל', 'הנחה', 'כמות', 'פריט', 'תעודה', 'משלוח', 'ישראל']


def _has_heb(t):
    return any('א' <= c <= 'ת' for c in t)


def _layer_reversed(tokens):
    """True when common Hebrew words appear reversed more often than forward."""
    fwd = rev = 0
    for t in tokens:
        if not _has_heb(t):
            continue
        for v in _HEB_VOCAB:
            if v in t:
                fwd += 1
            if v[::-1] in t:
                rev += 1
    return rev > fwd and rev >= 2


def _unreverse(t):
    return t[::-1] if _has_heb(t) else t


def _flush_chars(chs):
    """Word bbox from its chars — clamped to the VISIBLE glyph band. The rawdict char
    bbox is the font-METRICS box (full ascent/descent + leading); for fonts with tall
    metrics the box floats a whole gap above digit ink, which reads as "the boxes are
    too high" on every overlay. Using each char's baseline (origin), clamp the top to
    ~cap-height and the bottom to a normal descent — clamp only, never expand."""
    x0 = min(c['bbox'][0] for c in chs)
    y0 = min(c['bbox'][1] for c in chs)
    x1 = max(c['bbox'][2] for c in chs)
    y1 = max(c['bbox'][3] for c in chs)
    bases = [c['origin'][1] for c in chs if isinstance(c.get('origin'), (list, tuple))]
    if bases:
        base = sorted(bases)[len(bases) // 2]
        sizes = [c.get('_sz') or 0 for c in chs]
        sz = sorted(sizes)[len(sizes) // 2] or (y1 - y0)
        ty0 = base - 0.80 * sz
        ty1 = base + 0.24 * sz
        if ty1 > ty0:
            y0 = max(y0, ty0)
            y1 = min(y1, ty1)
            if y1 <= y0:                     # degenerate clamp — fall back to raw
                y0 = min(c['bbox'][1] for c in chs)
                y1 = max(c['bbox'][3] for c in chs)
    return (x0, y0, x1, y1, ''.join(c['c'] for c in chs))


def _words_from_chars(page, gap_ratio: float = 0.38):
    """Rebuild word tokens from CHARACTER data, preserving punctuation.

    ``page.get_text("words")`` splits on punctuation, shattering Hebrew abbreviations:
    ``ח.פ.`` becomes ``ח`` + ``פ`` and ``סה"כ`` becomes ``סה`` + ``כ``. Every KW anchor
    is such an abbreviation, so nothing ever matched on born-digital PDFs. Grouping
    characters by visual gap keeps ``ח.פ``/``סה"כ``/``בע"מ`` intact (and is RTL-safe,
    since the gap is measured as the distance between boxes in either direction)."""
    out = []
    for blk in page.get_text('rawdict').get('blocks', []):
        for ln in blk.get('lines', []):
            # accumulate across SPANS within the line: a gershayim inside סה"כ is often
            # emitted as its own span (different font run), and flushing per-span would
            # split the word before the joiner logic can see the quote at all.
            # Hebrew lines: some generators emit spans in VISUAL (left-to-right) order,
            # i.e. reversed reading order — סה"כ arrives as [כ][״][סה] and assembles to
            # כ"סה. Walk the spans right-to-left for Hebrew-dominant lines so tokens
            # assemble in logical reading order (each span is internally logical).
            spans = ln.get('spans', [])
            line_txt = ''.join(sp.get('text', '') or ''.join(c['c'] for c in sp.get('chars', [])) for sp in spans)
            if any('א' <= c <= 'ת' for c in line_txt):
                spans = sorted(spans, key=lambda sp: -(sp.get('bbox') or [0])[0])
            cur = []
            for sp in spans:
                sp_sz = sp.get('size')
                for ch in sp.get('chars', []):
                    ch['_sz'] = sp_sz            # font size for the glyph-band clamp
                    c, bb = ch['c'], ch['bbox']
                    if c.isspace():
                        if cur:
                            out.append(_flush_chars(cur)); cur = []
                        continue
                    if cur:
                        pb = cur[-1]['bbox']
                        gap = max(bb[0] - pb[2], pb[0] - bb[2])
                        h = max(1.0, bb[3] - bb[1])
                        # quote-family glyphs (gershayim/geresh) inside a Hebrew word may
                        # carry an oversized advance in some generators (Wise-Electric),
                        # splitting סה"כ into סה + כ — and the lone quote then gets dropped
                        # by the punctuation filter, so the anchor can never assemble.
                        # Never split at or right after a quote glyph.
                        joiner = c in '"\'׳״' or cur[-1]['c'] in '"\'׳״'
                        if gap > gap_ratio * h and not joiner:
                            out.append(_flush_chars(cur)); cur = []
                    cur.append(ch)
            if cur:
                out.append(_flush_chars(cur))
    return out


def _render_stacked(pdf_path: str, max_w: float, total_h: float):
    """Render all pages stacked vertically AT THE OCR COORDINATE SCALE, so OcrDrawings
    can draw query overlays directly. (max_w, total_h) is the word-coordinate space:
    points (zoom 1) for the text-layer path, but a SCANNED pdf is OCR'd on a 300-DPI
    raster so its coordinates are (300/72)x the page rect. The zoom is derived from the
    requested canvas width vs the page geometry and applied UNIFORMLY to both axes — a
    document render must never be stretched. Returns the saved path or None on failure."""
    try:
        import hashlib
        from PIL import Image
        from src.utils.storage import files_path
        with fitz.open(pdf_path) as d:
            page_w = max((p.rect.width for p in d), default=1.0) or 1.0
            zoom = float(max_w) / page_w if page_w else 1.0
            if abs(zoom - 1.0) < 0.15:
                zoom = 1.0            # text-layer coords ARE points — keep exact 1:1
            pages = []
            for page in d:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples) if pix.n < 4 \
                    else Image.frombytes('RGBA', (pix.width, pix.height), pix.samples).convert('RGB')
                pages.append(img)
            W = max(max(1, int(round(max_w))), max((im.width for im in pages), default=1))
            H = max(max(1, int(round(total_h))), sum(im.height for im in pages))
            canvas = Image.new('RGB', (W, H), 'white')
            y = 0
            for im in pages:
                canvas.paste(im, (0, y))
                y += im.height
        h = hashlib.md5(open(pdf_path, 'rb').read()).hexdigest()
        out = os.path.join(files_path(), f"{h}_tl.png")
        canvas.save(out)
        return out
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"pdf_textlayer stacked render failed: {e}")
        return None


def ocr_from_pdf_textlayer(pdf_path: str) -> dict:
    """Return a Vision-shaped OCR dict built from the PDF text layer (all pages
    stacked vertically, so word boxes stay globally ordered)."""
    words_out, texts, y_off, max_w = [], [], 0.0, 0.0
    with fitz.open(pdf_path) as d:
        for page in d:
            texts.append(heb_norm(page.get_text()))
            max_w = max(max_w, page.rect.width)
            try:
                page_words = _words_from_chars(page)
            except Exception:                       # defensive: fall back to coarse words
                page_words = [(x0, y0, x1, y1, w) for x0, y0, x1, y1, w, *_ in page.get_text("words")]
            for x0, y0, x1, y1, w in page_words:
                w = heb_norm(w)
                # Drop punctuation-only tokens (":.", ":", "-", "()" …). A PDF text layer
                # emits them as standalone words; they then sit between a label and its
                # value ("ח.פ" | ":." | "516587961") and a find-after lands on the
                # punctuation, fails validation, and the whole extraction gives up.
                # The engine's intro-skip only knows single characters, so filter here.
                if w.strip() and any(c.isalnum() for c in w):
                    words_out.append((x0, y0 + y_off, x1, y1 + y_off, w))
            y_off += page.rect.height
    # Some generators store Hebrew VISUALLY (per-word char-reversed: סה"כ -> כ"סה) even
    # though the page renders correctly — every anchor then fails despite a "perfect"
    # text layer. Detect via vocabulary hit-rate and un-reverse Hebrew tokens; digits
    # and Latin are stored intact and left untouched.
    if _layer_reversed([w[4] for w in words_out]):
        words_out = [(x0, y0, x1, y1, _unreverse(w)) for x0, y0, x1, y1, w in words_out]
        texts = [' '.join(_unreverse(t) for t in tx.split(' ')) for tx in texts]
    full_text = '\n'.join(texts)
    page_w = max_w or 1000
    anns = [{"description": full_text, "boundingPoly": {"vertices": _rect(0, 0, page_w, y_off)}}]
    for x0, y0, x1, y1, w in words_out:
        anns.append({"description": w, "boundingPoly": {"vertices": _rect(x0, y0, x1, y1)}})
    out = {"textAnnotations": anns, "fullTextAnnotation": {"text": full_text},
           "ocr_engine": "pdf_textlayer"}
    # Render a coordinate-aligned raster so the query-overlay drawing works on
    # born-digital PDFs too (word coords are in point space, pages stacked by height).
    img_path = _render_stacked(pdf_path, page_w, y_off)
    if img_path:
        out["image_path"] = img_path
    return out
