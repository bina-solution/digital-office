"""Local OCR engine using Tesseract, producing output in Google Vision API format.

This module replaces the Google Cloud Vision API with a local Tesseract-based OCR engine.
It produces an identical JSON structure so all downstream code (OcrData, AnnotationObject,
BoundingBox, alignment, etc.) works without modification.
"""

import base64
import io
import re
import tempfile
import os

import pytesseract
from PIL import Image, ImageFile

from src.utils.logging_config import get_logger

logger = get_logger('apitools.local_ocr_engine')

# Let Pillow decode slightly-truncated images instead of throwing — poppler can emit
# an incomplete rasterization under memory pressure (the "only under load" symptom).
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Image container formats Tesseract (via pytesseract) accepts. Anything else
# (MPO from phone cameras, HEIC from iPhones, exotic PDF rasterizations) is rejected
# with TypeError('Unsupported image format/type') deep inside pytesseract.prepare().
_SUPPORTED_FORMATS = getattr(pytesseract.pytesseract, 'SUPPORTED_FORMATS', set())

# Default Tesseract language — Hebrew + English for mixed documents
DEFAULT_LANG = 'heb+eng'
# Minimum confidence to include a word (0-100)
MIN_CONFIDENCE = 1
TESSERACT_TIMEOUT = int(os.getenv('APITOOLS_TESSERACT_TIMEOUT', '120'))

# ── engine config ──────────────────────────────────────────────────────────
# Use the high-accuracy tessdata_best Hebrew/English models (float LSTM) when
# present — the standard 2019 heb model mangles common words (סה"כ לתשלום ->
# לתעולום). Bundled at src/ocr_core/tessdata/; override with APITOOLS_TESSDATA_DIR.
# PSM 11 (sparse text — find as much text as possible) reads these mixed-direction
# Hebrew documents best: PSM 3/4 fragment the RTL labels, PSM 6 fragments the LTR
# amounts (bidi number-splitting), PSM 11 gets BOTH. Override with APITOOLS_TESSERACT_PSM.
_TESSDATA_DIR = os.getenv('APITOOLS_TESSDATA_DIR') or os.path.join(os.path.dirname(__file__), 'tessdata')
_TESS_PSM = os.getenv('APITOOLS_TESSERACT_PSM', '11')


def _tess_config():
    parts = []
    if _TESSDATA_DIR and os.path.isdir(_TESSDATA_DIR):
        parts.append('--tessdata-dir ' + _TESSDATA_DIR)
    if _TESS_PSM:
        parts.append('--psm ' + str(_TESS_PSM))
    return ' '.join(parts)


TESS_CONFIG = _tess_config()
logger.info(f"Tesseract config: '{TESS_CONFIG}' (best_models={os.path.isdir(_TESSDATA_DIR)})")


# ── resident engine shim ───────────────────────────────────────────────────
# pytesseract spawns the `tesseract` BINARY per call: fork+exec + dynamic-link +
# re-parse of the traineddata into an LSTM + a PNG round-trip through /tmp. Measured
# here: ~132 ms of that ceremony per call, of which a 1-word crop's actual recognition
# was ~0 ms. A photo makes ~251 calls => ~33 s of pure tax and ~4.8 GB of redundant
# model loading to extract ~25 bytes.
#
# This object is a DROP-IN for the pytesseract module (same call signatures), routing to
# a resident libtesseract handle instead. Proven bit-identical to the subprocess path —
# text, confidence AND boxes, 10/10 across raw crops, 3x zoom, zoom+contrast and a full
# 131-word page — after matching three subtle behaviours: SetImage(crop) (never
# SetRectangle), int() conf truncation (not round), and lstrip of the leading bidi mark.
# Measured 7.3x per call. Falls back to the subprocess on ANY error. APITOOLS_TESS_API=0
# disables it.
from src.ocr_core import tess_api as _tess_api

_pytesseract = pytesseract


def _parse_cfg(config: str):
    """Extract (psm, tessdata_dir, variables) from a pytesseract `config` string.

    CLI SEMANTICS — LAST FLAG WINS. The engine builds configs by CONCATENATION
    (TESS_CONFIG already holds '--psm 11', call sites append '--psm 7 ...'), so a
    config can legally carry the same flag twice and tesseract-the-binary honors
    the LAST one. Taking the FIRST match was THE S1 integration bug: the
    number-recovery "single line" probe (--psm 7 + digits whitelist) ran as
    --psm 11 full-page-sparse under the resident engine, flooding the merge logic
    with a digits-only read of the whole page → 176 tokens collapsed to 31.
    """
    cfg = config or ''
    ms = re.findall(r'--psm\s+(\d+)', cfg)
    psm = int(ms[-1]) if ms else 3             # tesseract's own default
    ms = re.findall(r'--tessdata-dir\s+(\S+)', cfg)
    td = ms[-1] if ms else None                # None => system default (fast models)
    # note: value may be EMPTY ("-c tessedit_char_whitelist=" resets the whitelist)
    variables = {k: v for k, v in re.findall(r'-c\s+([A-Za-z_]+)=(\S*)', cfg)}
    return psm, td, variables


class _TessAPIShim:
    Output = _pytesseract.Output

    @staticmethod
    def image_to_string(image, lang=None, config='', timeout=0, **kw):
        if _tess_api.available():
            try:
                psm, td, v = _parse_cfg(config)
                return _tess_api.image_to_text(image, lang or 'eng', td, psm, v)
            except Exception as e:
                logger.warning('tess_api image_to_string fell back to subprocess: %s', e)
        return _pytesseract.image_to_string(image, lang=lang, config=config, timeout=timeout, **kw)

    @staticmethod
    def image_to_data(image, lang=None, config='', output_type=None, timeout=0, **kw):
        if _tess_api.available():
            try:
                psm, td, v = _parse_cfg(config)
                return _tess_api.image_to_words(image, lang or 'eng', td, psm, v)
            except Exception as e:
                logger.warning('tess_api image_to_data fell back to subprocess: %s', e)
        return _pytesseract.image_to_data(image, lang=lang, config=config,
                                          output_type=output_type or _pytesseract.Output.DICT,
                                          timeout=timeout, **kw)


if _tess_api.available():
    pytesseract = _TessAPIShim()
    logger.info('local_ocr_engine: resident libtesseract engine ACTIVE (subprocess fallback armed)')

# Preprocessing for low-quality inputs (esp. phone photos from WhatsApp): raw Tesseract on
# camera images scores near-zero because of low effective resolution + uneven lighting. We
# upscale small images and apply adaptive thresholding, then scale the resulting word
# coordinates BACK to the original image space so all downstream alignment is unchanged.
# Toggle with APITOOLS_OCR_PREPROCESS=0. Fail-safe: any error falls back to the raw image.
OCR_PREPROCESS = os.getenv('APITOOLS_OCR_PREPROCESS', '1') == '1'
OCR_TARGET_MIN_DIM = int(os.getenv('APITOOLS_OCR_TARGET_MIN_DIM', '1800'))
# Tesseract reads best when glyphs are ~30px tall. The preprocessor scales the image to bring
# the ESTIMATED text height into a legible band [LO, HI] — NOT by image dimensions. Sizing by
# dimensions was a bug: a clean small render whose text is already well sized got upscaled
# until Tesseract's layout analysis dropped it (an 800x400 table reads at native, vanishes at
# 3x). Text already in-band is passed through untouched.
OCR_TEXT_TARGET_H = float(os.getenv('APITOOLS_OCR_TEXT_TARGET_H', '30'))
OCR_TEXT_H_LO = float(os.getenv('APITOOLS_OCR_TEXT_H_LO', '18'))
OCR_TEXT_H_HI = float(os.getenv('APITOOLS_OCR_TEXT_H_HI', '42'))
OCR_SCALE_CAP = float(os.getenv('APITOOLS_OCR_SCALE_CAP', '4.0'))
# Minimum tilt (degrees) to actually deskew. Below this a document is treated as straight
# and left un-rotated — deskewing a near-straight page shifts its word boxes without helping
# OCR, which destabilises positional queries. Only genuine (multi-degree) tilts are corrected.
OCR_DESKEW_MIN_DEG = float(os.getenv('APITOOLS_OCR_DESKEW_MIN_DEG', '4.0'))
# Erase non-text solid marks (paid-badges, stamps, logo glyphs, filled bullets) that
# touch/crowd text: Tesseract groups such a mark into the adjacent word and corrupts it
# (a ✓ badge fused to a label makes "סכום שהתקבל" read as "סו"). We detect them by shape
# — large, round/square, solid, convex — which no Hebrew letter is, and (critically) which
# a decimal-point or comma is NOT (too small). Toggle with APITOOLS_OCR_REMOVE_MARKS=0.
OCR_REMOVE_MARKS = os.getenv('APITOOLS_OCR_REMOVE_MARKS', '1') == '1'
# Erase long table BORDER LINES before OCR. On photographed documents Tesseract's layout
# analysis can discard an entire bordered cell — a crisp bold "סה\"כ מחיר 2,337.00" inside
# a heavy table frame OCRs to NOTHING with the frame in place, and reads perfectly with it
# stripped. Kernels are long (>=1/12 of the dimension) so glyph strokes and barcode bars
# are never touched. Toggle with APITOOLS_OCR_REMOVE_LINES=0.
OCR_REMOVE_LINES = os.getenv('APITOOLS_OCR_REMOVE_LINES', '1') == '1'
# Shadow-cell zoom: a photographed table cell often collapses to a lone stray glyph
# ("PO26002620" read as "0") while its neighbors read fine. A tiny token alone in a
# wide cell-gap marks such a cell; cropping it and re-OCRing at 3x recovers the id.
OCR_ZOOM_SHADOW = os.getenv('APITOOLS_OCR_ZOOM_SHADOW', '1') == '1'
# PSM-4 (single-column) recovery for PHOTOS: our primary read uses PSM 11 (sparse
# text), which reads scattered Hebrew+numbers best but DROPS structured header content
# on curled/tilted phone photos — a legible "תאריך 15/05/2025" / "חשבונית מס 697512"
# vanishes. PSM 4 reads a document as a single column and catches them. We run it only
# on smallish images (photos) and ADD tokens the primary missed. Toggle with =0.
OCR_PSM4_RECOVER = os.getenv('APITOOLS_OCR_PSM4_RECOVER', '1') == '1'


def _remove_table_lines(gray: 'Image.Image') -> 'Image.Image':
    """Strip long horizontal/vertical rule lines and repair glyph strokes they cut.
    Used ONLY by the bordered-cell RECOVERY pass in ocr_from_image (never on the
    primary pass): Tesseract's layout analysis discards bordered-cell content on
    photographed documents — a crisp "סה\"כ מחיר 2,337.00" OCRs to nothing with the
    frame in place and reads perfectly with it stripped. Returns the input unchanged
    when no lines exist or on any error."""
    try:
        import numpy as np
        import cv2
        a = np.array(gray)
        h, w = a.shape
        inv = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 12), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, h // 12)))
        hl = cv2.morphologyEx(inv, cv2.MORPH_OPEN, hk)
        vl = cv2.morphologyEx(inv, cv2.MORPH_OPEN, vk)
        lines = cv2.bitwise_or(hl, vl)
        if not lines.any():
            return gray
        text = cv2.bitwise_and(inv, cv2.bitwise_not(lines))
        # repair strokes the line removal cut (descenders crossing an underline):
        # close small vertical gaps, but only restore pixels that were real ink
        rep = cv2.morphologyEx(text, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7)))
        keep = cv2.bitwise_or(text, cv2.bitwise_and(rep, inv))
        out = a.copy()
        out[(inv > 0) & (keep == 0)] = 255
        logger.info("table-line removal (recovery pass): lines stripped, strokes repaired")
        return Image.fromarray(out)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"table-line removal skipped: {e}")
        return gray


def _remove_nontext_marks(gray: 'Image.Image') -> 'Image.Image':
    """Paint over solid non-text marks so they can't corrupt adjacent OCR. Best-effort;
    returns the input unchanged on any error. Never touches small marks (dots/commas)."""
    try:
        import numpy as np
        import cv2
        a = np.array(gray)
        th = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        n, lab, stats, _c = cv2.connectedComponentsWithStats(th, 8)
        hs = [stats[i][3] for i in range(1, n) if 8 < stats[i][3] < 140]
        if not hs:
            return gray
        med = float(np.median(hs))
        out = a.copy()
        removed = 0
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if h < 12 or w < 12:
                continue                       # never a large mark — spares dots/commas
            fill = area / float(w * h)
            ar = w / float(h)
            mask = (lab[y:y + h, x:x + w] == i).astype('uint8') * 255
            cnts, _hh = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            per = cv2.arcLength(cnts[0], True)
            circ = 4 * np.pi * area / (per * per) if per > 0 else 0
            hull = cv2.convexHull(cnts[0])
            hullA = cv2.contourArea(hull)
            sol = area / hullA if hullA > 0 else 0
            # large + round/square + solid + convex = badge / stamp / logo, not a glyph
            if h > med * 1.3 and circ > 0.7 and 0.7 < ar < 1.45 and fill > 0.55 and sol > 0.85:
                out[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2] = 255
                removed += 1
        if removed:
            logger.info(f"Local OCR erased {removed} non-text mark(s) before OCR")
        return Image.fromarray(out)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"non-text mark removal failed, using raw image: {e}")
        return gray


def _estimate_text_height(arr) -> float:
    """Median height (px) of text-like connected components — a cheap, OCR-free estimate of
    glyph size. Excludes dots/specks (too short) and rules/borders/large blobs (too tall or
    too wide). Returns 0.0 when indeterminate."""
    try:
        import cv2
        import numpy as np
        th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(th, 8)
        hs = [stats[i][3] for i in range(1, n)
              if 6 < stats[i][3] < 120 and 2 < stats[i][2] < 400 and stats[i][4] > 15]
        return float(np.median(hs)) if hs else 0.0
    except Exception:  # pragma: no cover - defensive
        return 0.0


def _preprocess_for_ocr(image: 'Image.Image'):
    """Return (preprocessed PIL image, scale_factor). Coords from OCR must be divided by
    scale_factor to map back to the original image. Falls back to (image, 1.0) on any error."""
    try:
        gray = image.convert('L')
        if OCR_REMOVE_MARKS:
            gray = _remove_nontext_marks(gray)
        # NOTE: table-line removal is deliberately NOT applied here. It helps bordered
        # cells but harms underline-adjacent text, so it runs as a separate RECOVERY
        # pass in ocr_from_image that can only ADD tokens, never lose them.
        w, h = gray.size
        import numpy as np
        import cv2
        # Scale to normalize TEXT HEIGHT to Tesseract's sweet spot, NOT image dimensions.
        # Text already in a legible band is passed through as-is (this is the common case
        # for clean renders and good scans — thresholding/rescaling them only HURTS). Only
        # genuinely small text is enlarged; oversized text is shrunk.
        est = _estimate_text_height(np.array(gray))
        if not est or OCR_TEXT_H_LO <= est <= OCR_TEXT_H_HI:
            return gray, 1.0
        scale = max(1.0 / OCR_SCALE_CAP, min(OCR_SCALE_CAP, OCR_TEXT_TARGET_H / est))
        gray = gray.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        arr = np.array(gray)
        if scale <= 1.0:
            return gray, scale          # oversized clean text: downscale only, keep grayscale
        # ENLARGING genuinely-small text (low-res scan / phone photo): correct a real tilt.
        # (Adaptive thresholding was removed here — it fragments strokes and, empirically,
        # loses text even at the corrected size; grayscale at the right height reads best.)
        # PHOTO deskew: a phone photo is typically tilted a few degrees; a 5-6° tilt
        # makes Tesseract read nothing. Estimate the angle from Hough lines measured on
        # the PAPER region only (Otsu bright-mask -> largest contour) — full-frame lines
        # follow the background (keyboard edges) and give a wrong angle. Rotate only on
        # a confident consensus, and only for real tilts (2°..30°), so near-straight
        # scans are untouched. Order matters: upscale first, then rotate.
        try:
            th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            cnts, _h = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                big = max(cnts, key=cv2.contourArea)
                mask = np.zeros_like(arr)
                cv2.drawContours(mask, [big], -1, 255, -1)
                edges = cv2.Canny(cv2.bitwise_and(arr, mask), 50, 150)
                lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80,
                                        minLineLength=arr.shape[1] // 6, maxLineGap=12)
                if lines is not None and len(lines) >= 5:
                    angs = []
                    for l in lines[:80]:
                        x1, y1, x2, y2 = l[0]
                        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                        if abs(a) <= 30 or abs(abs(a) - 180) <= 30:
                            angs.append(a if abs(a) <= 30 else a - 180 * np.sign(a))
                    if len(angs) >= 5:
                        ang = float(np.median(angs))
                        # +0.7deg bias: creased-paper photos measure slightly under
                        # the true tilt (empirical: Hough said 5.33, best OCR at 6.0)
                        ang = ang + (0.7 if ang > 0 else -0.7)
                        # Only deskew a REAL tilt. A near-straight render (a clean digital
                        # invoice measured at ~2 deg) must not be rotated: warpAffine there
                        # only jitters the word boxes off their glyphs and destabilises the
                        # positional queries, for no OCR gain. Genuine phone-photo tilts are
                        # several degrees. Override with APITOOLS_OCR_DESKEW_MIN_DEG.
                        if OCR_DESKEW_MIN_DEG <= abs(ang) <= 30.0:
                            hh, ww = arr.shape
                            M = cv2.getRotationMatrix2D((ww / 2, hh / 2), ang, 1.0)
                            arr = cv2.warpAffine(arr, M, (ww, hh), flags=cv2.INTER_CUBIC,
                                                 borderMode=cv2.BORDER_REPLICATE)
                            logger.info(f"photo deskew applied: {ang:.1f} deg")
        except Exception as _e:  # pragma: no cover - defensive
            logger.warning(f"photo deskew skipped: {_e}")
        return Image.fromarray(arr), scale
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"OCR preprocess failed, using raw image: {e}")
        return image, 1.0


def _normalize_image(image: 'Image.Image') -> 'Image.Image':
    """Return a PIL image guaranteed to be OCR-able by Tesseract.

    pytesseract raises ``TypeError('Unsupported image format/type')`` for any image
    whose ``.format`` is not in its ``SUPPORTED_FORMATS`` set — e.g. ``MPO`` (phone
    multi-picture JPEG), ``HEIC`` (iPhone), or odd PDF rasterizations. This was the
    ROOT of the high-load OCR churn: each such doc 500s and is retried forever. We
    force a full decode (surfacing truncation here, cleanly) and, when the source
    format/mode is unsupported, re-wrap the pixels — a converted/copied image has
    ``format=None`` (pytesseract treats it as PNG) and a standard mode, so OCR
    always succeeds regardless of the original container format."""
    try:
        image.load()  # force decode now instead of lazily inside pytesseract
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"image.load() failed ({e}); attempting conversion anyway")
    if image.mode not in ('L', 'RGB'):
        return image.convert('RGB')
    if image.format and image.format not in _SUPPORTED_FORMATS:
        return image.convert(image.mode)  # same pixels/mode, drops the rogue format
    return image


def _bbox_to_vertices(left: int, top: int, width: int, height: int) -> list:
    """Convert (left, top, width, height) to 4-vertex polygon (clockwise from top-left)."""
    return [
        {"x": left, "y": top},
        {"x": left + width, "y": top},
        {"x": left + width, "y": top + height},
        {"x": left, "y": top + height},
    ]


# Large display numbers (a receipt's hero amount, a grand-total band) are ~2.5x the
# body text size and often sit next to a ₪ glyph. Tesseract's page-level layout
# analysis rejects such outlier-large lines (it collapses "14,385.08 ₪" to "8"), yet
# the SAME digits read perfectly when the line is cropped and OCR'd in isolation with
# a numeric whitelist. This second pass finds outlier-tall text lines, re-OCRs each
# with a digit whitelist, and returns the recovered numbers as extra word annotations
# so downstream KW extraction (find-after an amount label) can locate them. Toggle
# with APITOOLS_OCR_RECOVER_NUMBERS=0. Fail-safe: any error yields no extra words.
OCR_RECOVER_NUMBERS = os.getenv('APITOOLS_OCR_RECOVER_NUMBERS', '1') == '1'
# Re-OCR each money-shaped token with a digit whitelist to correct single-digit slips.
OCR_REFINE_MONEY = os.getenv('APITOOLS_OCR_REFINE_MONEY', '1') == '1'
_NUM_RE = None


def _recover_large_numbers(gray_image, config: str) -> list:
    """Return [(token, left, top, width, height), ...] for outlier-large numeric lines,
    in the coordinate space of ``gray_image``. Best-effort; returns [] on any failure."""
    global _NUM_RE
    try:
        import re
        import numpy as np
        import cv2
        if _NUM_RE is None:
            _NUM_RE = re.compile(r'[0-9][0-9.,]{2,}')
        arr = np.array(gray_image if gray_image.mode == 'L' else gray_image.convert('L'))
        th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        # dilate horizontally so glyphs of a line merge into one blob
        dil = cv2.dilate(th, cv2.getStructuringElement(cv2.MORPH_RECT, (45, 5)), iterations=1)
        cnts, _h = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rects = [cv2.boundingRect(c) for c in cnts]
        heights = [h for (_x, _y, _w, h) in rects if h > 8]
        if not heights:
            return []
        med = float(np.median(heights))
        num_cfg = config + ' --psm 7 -c tessedit_char_whitelist=0123456789.,'
        out = []
        # Each candidate costs TWO Tesseract crop calls; on a number-dense table
        # dozens qualify and the pass balloons to a minute+. Cap to the N tallest
        # (hero amounts are the outlier-large lines this targets) so the cost is
        # bounded regardless of how busy the document is.
        cand = sorted((r for r in rects if r[3] > med * 1.6 and r[2] > 40),
                      key=lambda r: r[3], reverse=True)[:int(os.getenv('APITOOLS_OCR_BIGNUM_CAP', '12'))]
        for (x, y, w, h) in cand:
            pad = int(h * 0.2)
            crop = gray_image.crop((max(0, x - pad), max(0, y - pad), x + w + pad, y + h + pad))
            txt = pytesseract.image_to_string(crop, lang='eng', config=num_cfg,
                                              timeout=TESSERACT_TIMEOUT).strip()
            # box-plausibility guard: the (45px) horizontal dilation can merge an entire
            # table ROW into one full-width blob (a hero amount never is), and that blob's
            # box then owns every recovered token — its drop-region would wipe the whole
            # row (dyavr-5: the value row's ids clobbered by a 2300px-wide "17099"). A real
            # number's box is proportional to its digit count; skip blobs far wider.
            def _plausible(tok_):
                return w <= max(60, len(tok_) * h * 1.2)
            for tok in _NUM_RE.findall(txt):
                # accept only cleanly-shaped numbers (integer or <=2 decimals). A merged
                # string like "2,095.29210310" (the dilated row spanned a table column) is
                # rejected, so the primary token flows to the money-refine pass instead.
                if re.match(r'^\d[\d,]*(\.\d{1,2})?$', tok) and _plausible(tok):
                    out.append((tok, x, y, w, h))
            # Latin doc-number re-read: heb+eng competition misreads a Latin id embedded
            # in a Hebrew title line (SH26001884 -> "ח5..."). An eng-only pass on the same
            # band is stable; accept only prefix+digits shaped ids.
            try:
                txt_en = pytesseract.image_to_string(
                    crop, lang='eng',
                    config=config + ' --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    timeout=TESSERACT_TIMEOUT).strip()
                for tok in re.findall(r'\b[A-Z]{1,4}\d{6,12}\b', txt_en):
                    if _plausible(tok):
                        out.append((tok, x, y, w, h))
            except Exception:
                pass
        return out
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"large-number recovery pass failed: {e}")
        return []


import re as _re


def _decode_barcodes(image: 'Image.Image'):
    """Decode 1-D barcodes (Code39/128/EAN…) and return [(text, x0, y0, x1, y1)] in
    ORIGINAL image space. Delivery notes barcode their tracking/shipment id, which
    Tesseract cannot read off the bars — but a barcode reader can. Only doc-id-shaped
    payloads (letter-prefixed or long numeric) are kept, so decorative EANs are ignored.
    Best-effort: returns [] if zxing-cpp is absent or nothing decodes."""
    try:
        import zxingcpp
        import numpy as _np
        arr = _np.array(image.convert('L'))
        out = []
        for b in zxingcpp.read_barcodes(arr):
            txt = (getattr(b, 'text', '') or '').strip()
            if not (_re.fullmatch(r'[A-Z]{1,4}\d{5,14}', txt) or _re.fullmatch(r'\d{8,14}', txt)):
                continue
            p = getattr(b, 'position', None)
            try:
                xs = [p.top_left.x, p.top_right.x, p.bottom_left.x, p.bottom_right.x]
                ys = [p.top_left.y, p.top_right.y, p.bottom_left.y, p.bottom_right.y]
                bb = (min(xs), min(ys), max(xs), max(ys))
            except Exception:
                bb = (0, 0, arr.shape[1], 40)
            out.append((txt, *bb))
        if out:
            logger.info(f"Local OCR decoded {len(out)} barcode(s): {[o[0] for o in out]}")
        return out
    except Exception as e:  # pragma: no cover - defensive
        logger.info(f"barcode decode skipped: {e}")
        return []


def _photo_recover_fulltext(image: 'Image.Image'):
    """For small photos (folded/tilted phone shots), the default single pass can miss
    the letterhead id. Do a bounded raw-gray (no threshold) upscale+angle sweep and
    return the set of 9-digit company/VAT ids found, to be appended to the full text so
    a find-option company lookup can still resolve them. Bounded to genuinely small
    images so it never touches clean renders/scans. Returns a set of id strings."""
    try:
        import numpy as _np
        import cv2 as _cv2
        g0 = _np.array(image.convert('L'))
        h, w = g0.shape
        if min(h, w) >= 1100 or min(h, w) < 300:
            return set()
        ids = set()
        # A trimmed sweep: 1 scale x 3 angles (was 2x4=8) — each pass is a full-image OCR,
        # so this drops the pass count from 8 to 3 (~60% cheaper) while still covering the
        # small tilt range where a folded letterhead's id becomes legible.
        for scale in (2.75,):
            g = _cv2.resize(g0, (int(w * scale), int(h * scale)), interpolation=_cv2.INTER_CUBIC)
            for ang in (0.0, 5.0, 6.5):
                if ang:
                    M = _cv2.getRotationMatrix2D((g.shape[1] / 2, g.shape[0] / 2), ang, 1.0)
                    r = _cv2.warpAffine(g, M, (g.shape[1], g.shape[0]),
                                        flags=_cv2.INTER_CUBIC, borderMode=_cv2.BORDER_REPLICATE)
                else:
                    r = g
                try:
                    txt = pytesseract.image_to_string(Image.fromarray(r), lang='heb+eng',
                                                      config=TESS_CONFIG, timeout=40)
                except Exception:
                    continue
                for m in _re.findall(r'(?<!\d)\d{9}(?!\d)', txt):
                    if m[0] != '0':          # Israeli company/VAT ids never start with 0
                        ids.add(m)
        if ids:
            logger.info(f"photo-recover found id candidate(s): {ids}")
        return ids
    except Exception as e:  # pragma: no cover
        logger.info(f"photo-recover skipped: {e}")
        return set()


# Photo zoom-verify: on blurry phone shots the full-page pass misreads tiny digit runs
# ("697512" -> "669764") or shatters one value into two OVERLAPPING partial tokens
# ("15/05/2025" -> "15/05/20" + "5/05/20,"). The same Tesseract reads both perfectly when
# the region ALONE is re-OCR'd zoomed (crop + 3x upscale + contrast + PSM 6) — proven on
# yhzkal-ahrvn-1.jpg where Google Vision reads them and the full-page pass doesn't.
# Toggle with OCR_ZOOM_VERIFY=0.
OCR_ZOOM_VERIFY = os.environ.get('OCR_ZOOM_VERIFY', '1') != '0'


def _tess_data(im2, psm, lang):
    try:
        return pytesseract.image_to_data(im2, lang=lang, config='--psm %d' % psm,
                                          output_type=pytesseract.Output.DICT, timeout=15)
    except Exception:
        return None


def _zoom_votes(image: 'Image.Image', x0: int, y0: int, x1: int, y1: int, lang: str):
    """Re-OCR one suspect region across a small variant grid (3 pads x 4 preprocess/PSM
    recipes) and return {token: [votes, sum_conf]} for digit-rich tokens. A single zoom
    recipe is crop-sensitive on marginal blur (reads flip between pads); the TRUE value
    is what repeats across variants while misreads scatter — measured on yhzkal:
    '697512' 2-6 votes vs one-off '697519'/'697542'/'697545'. The 12 Tesseract calls run
    in a thread pool (each releases the GIL in its subprocess) — ~2.6x on 4 cores."""
    from PIL import ImageEnhance
    tasks = []
    for pad in (8, 12, 16):
        c = image.crop((max(0, int(x0) - pad), max(0, int(y0) - pad),
                        min(image.width, int(x1) + pad), min(image.height, int(y1) + pad)))
        if c.width < 8 or c.height < 8 or c.width > 600 or c.height > 300:
            return {}
        up3 = c.resize((c.width * 3, c.height * 3), Image.LANCZOS)
        ctr = ImageEnhance.Contrast(up3.convert('L')).enhance(2.0)
        # 3 pads x 4 recipes = 12: the full grid is load-bearing for CONSENSUS accuracy —
        # trimming it flips the winner (measured: 6-recipe gave 697519 not 697512). The
        # calls run in a thread pool below, so the cost is wall-time ~/4 not ~/12.
        tasks += [(c, 6), (up3, 11), (up3, 6), (ctr, 6)]
    # Parallelism is engine-dependent:
    #  - SUBPROCESS path (default): each call is a separate `tesseract` process that
    #    releases the GIL, so a 4-way pool wins ~1.8-2.6x (measured: 6 calls 1.8s -> 0.7s).
    #  - RESIDENT C API path: a TessBaseAPI handle is per-thread, so a fresh pool per vote
    #    re-pays a 108 ms LSTM init per thread — measured SLOWER (53 s -> 65 s). Go serial
    #    there; a 12-call vote is only ~310 ms at ~26 ms/call anyway.
    votes: dict = {}
    if _tess_api.available():
        results = (_tess_data(t[0], t[1], lang) for t in tasks)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(lambda t: _tess_data(t[0], t[1], lang), tasks))
    for d in results:
        if not d:
            continue
        for i in range(len(d['text'])):
            w = d['text'][i].strip().strip('.,;:|"\'')
            cf = int(d['conf'][i])
            if not w or cf < 40 or sum(ch.isdigit() for ch in w) < 4:
                continue
            v = votes.setdefault(w, [0, 0])
            v[0] += 1
            v[1] += cf
    return votes


def ocr_from_image(image: Image.Image, lang: str = DEFAULT_LANG) -> dict:
    """Run Tesseract OCR on a PIL Image and return a Google Vision API-compatible dict.

    The returned dict has the same structure as ``responses[0]`` from the
    Vision API ``DOCUMENT_TEXT_DETECTION`` endpoint:

    - ``textAnnotations``: list of word-level annotations with bounding polygons
    - ``fullTextAnnotation``: dict with ``text`` (full page text)
    """
    # Normalize to a guaranteed Tesseract-supported PIL image (fixes the
    # 'Unsupported image format/type' churn on MPO/HEIC/exotic inputs).
    image = _normalize_image(image)
    width, height = image.size

    # Preprocess (upscale + adaptive threshold) for OCR; keep a scale factor to map
    # word coordinates back to the ORIGINAL image space (page bbox stays original).
    ocr_image, scale = _preprocess_for_ocr(image) if OCR_PREPROCESS else (image, 1.0)

    # Full page text
    full_text = pytesseract.image_to_string(ocr_image, lang=lang, config=TESS_CONFIG,
                                            timeout=TESSERACT_TIMEOUT)

    # Word-level data
    data = pytesseract.image_to_data(
        ocr_image,
        lang=lang,
        config=TESS_CONFIG,
        output_type=pytesseract.Output.DICT,
        timeout=TESSERACT_TIMEOUT,
    )

    text_annotations = []

    # First annotation: full document text with page-level bounding box
    text_annotations.append({
        "locale": "iw",
        "description": full_text,
        "boundingPoly": {
            "vertices": _bbox_to_vertices(0, 0, width, height),
        },
    })

    # Word-level annotations
    for i in range(len(data['text'])):
        word = data['text'][i].strip()
        conf = int(data['conf'][i])
        if not word or conf < MIN_CONFIDENCE:
            continue

        # Map coords back to original-image space (OCR ran on an upscaled copy).
        inv = 1.0 / scale if scale else 1.0
        text_annotations.append({
            "description": word,
            "_conf": conf,  # consumed by the photo zoom-verify pass; stripped before return
            "boundingPoly": {
                "vertices": _bbox_to_vertices(
                    int(round(data['left'][i] * inv)),
                    int(round(data['top'][i] * inv)),
                    int(round(data['width'][i] * inv)),
                    int(round(data['height'][i] * inv)),
                ),
            },
        })

    # PSM-3 recovery pass (generic): the primary read uses PSM 11 (sparse text) — best for
    # scattered Hebrew+numbers, but its layout analysis DISCARDS whole framed table cells
    # (a crisp "PO26002198" reads as nothing on the full page). PSM 3 (full automatic page
    # segmentation) reads those cells — proven across single-page bordered tables AND
    # multi-page scanned stacks where no rule line even survives. So re-OCR at PSM 3 on a
    # line-stripped copy (borders otherwise re-confuse PSM 3; _remove_table_lines is a
    # no-op when there are none) and ADD tokens only where the primary produced nothing,
    # plus a guarded shadow-word replacement for under-read cells. This subsumes the old
    # per-cell grid-recovery — no table-geometry assumptions, works on any layout.
    if OCR_REMOVE_LINES:
        try:
            stripped = _remove_table_lines(ocr_image)
            cfg3 = (TESS_CONFIG.replace('--psm 11', '--psm 3')
                    if '--psm' in TESS_CONFIG else TESS_CONFIG + ' --psm 3')
            if True:
                d2 = pytesseract.image_to_data(
                    stripped, lang=lang, config=cfg3,
                    output_type=pytesseract.Output.DICT, timeout=TESSERACT_TIMEOUT)
                inv = 1.0 / scale if scale else 1.0

                def _box_of(a):
                    vs = a["boundingPoly"]["vertices"]
                    xs = [v.get("x", 0) for v in vs]; ys = [v.get("y", 0) for v in vs]
                    return min(xs), min(ys), max(xs), max(ys)

                n_primary = len(text_annotations)
                added_words = []
                drop_idx = set()
                recrop_budget = 24           # cap tight re-reads on a text-heavy page
                for i in range(len(d2['text'])):
                    wd = d2['text'][i].strip()
                    conf = int(d2['conf'][i])
                    if not wd or conf < MIN_CONFIDENCE:
                        continue
                    x = int(round(d2['left'][i] * inv)); y = int(round(d2['top'][i] * inv))
                    w_ = int(round(d2['width'][i] * inv)); h_ = int(round(d2['height'][i] * inv))
                    cx, cy = x + w_ / 2.0, y + h_ / 2.0
                    covering = []                # live pass-1 anns whose box covers the candidate center
                    inside = []                  # live pass-1 anns whose own center sits inside the candidate box
                    for j in range(1, n_primary):
                        if j in drop_idx:
                            continue
                        bx0, by0, bx1, by1 = _box_of(text_annotations[j])
                        if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                            covering.append(j)
                        pcx, pcy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
                        if x <= pcx <= x + w_ and y <= pcy <= y + h_:
                            inside.append(j)
                    overlapped = set(covering) | set(inside)
                    frag_len = sum(len(text_annotations[j]["description"]) for j in overlapped)
                    # a cell the primary already filled with SUBSTANTIAL content is left
                    # alone; only EMPTY cells and cells under-read to a tiny fragment (a lone
                    # "0" where the cell says "2,337.00", a junk "rN" over "PO26000613") are
                    # candidates for recovery.
                    if covering and frag_len > 3:
                        continue
                    # tight-crop RE-READ from the NON-stripped image: line removal nicks
                    # border-adjacent glyphs (PSM 3 read "PO26002198" as "0026002198") and a
                    # bordered cell prefixes a "|" from the frame. Take the run carrying the
                    # most digits so border pipes and bled neighbour glyphs drop
                    # ("| PO26000613" -> "PO26000613"); a Hebrew cell (no Latin/digit run)
                    # keeps its full read. PSM 3 gives the WHERE, the crop the accurate WHAT.
                    # clean OCR junk off the raw recovered id first: line removal leaves a
                    # border "|" or a stray Hebrew letter / dot on a Latin id ("026000613ם.").
                    # Take the run carrying the most digits; Hebrew text (no Latin/digit run)
                    # is kept whole, and a short token isn't over-trimmed.
                    def _clean_run(txt):
                        r = re.findall(r'[A-Za-z0-9][A-Za-z0-9.,/-]*', txt)
                        if not r:
                            return txt
                        b = max(r, key=lambda s: sum(c.isdigit() for c in s))
                        return b if sum(c.isalnum() for c in b) >= 4 else txt
                    wd_final = _clean_run(wd)
                    # tight re-read from the NON-stripped image fixes prefix glyphs the line
                    # strip nicked ("0026002198"->"PO26002198"). Use it ONLY when it is at
                    # least as rich (alnum count) as the cleaned PSM-3 read, so it never
                    # DEGRADES an already-clean high-conf token (SH26M002307 read at conf 88
                    # must not collapse to a stray "7" from a misaligned crop).
                    if recrop_budget > 0:
                        recrop_budget -= 1
                        rx, ry = d2['left'][i], d2['top'][i]
                        rw, rh = d2['width'][i], d2['height'][i]
                        cp = max(2, int(rh * 0.15))
                        sub = ocr_image.crop((max(0, rx - cp), max(0, ry - cp),
                                              min(ocr_image.width, rx + rw + cp),
                                              min(ocr_image.height, ry + rh + cp)))
                        if sub.height < 40:
                            sub = sub.resize((sub.width * 2, sub.height * 2), Image.LANCZOS)
                        tight = pytesseract.image_to_string(
                            sub, lang=lang, config='--psm 7',
                            timeout=TESSERACT_TIMEOUT).strip().replace('\n', ' ').strip()
                        tb = _clean_run(tight) if tight else ''
                        if tb and sum(c.isalnum() for c in tb) >= sum(c.isalnum() for c in wd_final):
                            wd_final = tb
                    # replacing a primary token (a tiny under-read fragment): only when the
                    # recovered value spatially CONTAINS it and clearly dwarfs it. The gate is
                    # the RECROP's quality, not the line-stripped PSM-3 confidence — line
                    # removal tanks conf on exactly the cells that need recovery (dyavr-4's
                    # "PO26000613" read at conf 19). An equal-length re-read never swaps, so a
                    # legit short cell (a real "0" quantity) stays intact.
                    if covering:
                        if not (set(covering) <= set(inside)
                                and len(wd_final) > 2 * frag_len
                                and sum(c.isalnum() for c in wd_final) >= 4):
                            continue
                        drop_idx |= overlapped
                    text_annotations.append({
                        "description": wd_final,
                        "boundingPoly": {"vertices": _bbox_to_vertices(x, y, w_, h_)},
                    })
                    added_words.append(wd_final)
                if drop_idx:
                    text_annotations = [a for j, a in enumerate(text_annotations)
                                        if j == 0 or j not in drop_idx]
                if added_words:
                    # surface the recovered words to the full_text fallbacks too
                    full_text = (full_text or '') + '\n' + ' '.join(added_words)
                    text_annotations[0]["description"] = full_text
                    logger.info(f"bordered-cell recovery added {len(added_words)} token(s)")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"bordered-cell recovery skipped: {e}")

    # PSM-4 single-column recovery pass (PHOTOS only): the primary PSM-11 read drops
    # structured header fields on curled/tilted phone photos — a clearly legible date
    # or invoice number just isn't in the tokens. PSM 4 reads the page as one column
    # and catches them. Add-only: any token whose centre no primary box covers is added
    # (with the barcode-strip guard); the primary result is never overwritten.
    if OCR_PSM4_RECOVER and min(width, height) < 1400:
        try:
            d4 = pytesseract.image_to_data(
                ocr_image, lang=lang, config=(TESS_CONFIG.replace('--psm 11', '--psm 4')
                                              if '--psm' in TESS_CONFIG else TESS_CONFIG + ' --psm 4'),
                output_type=pytesseract.Output.DICT, timeout=TESSERACT_TIMEOUT)
            inv = 1.0 / scale if scale else 1.0

            def _box4(a):
                vs = a["boundingPoly"]["vertices"]
                xs = [v.get("x", 0) for v in vs]; ys = [v.get("y", 0) for v in vs]
                return min(xs), min(ys), max(xs), max(ys)

            pboxes = [_box4(a) for a in text_annotations[1:]]
            # date / id / amount shapes worth rescuing into the full text even when a
            # (garbage) primary token overlaps them — the field queries' fulltext
            # fallback can then resolve a header value the primary sparse pass mangled.
            hi_val = re.compile(r'^(?:\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|[A-Za-z]{0,3}\d{4,12}|\d[\d,]*\.\d{2})$')
            add4 = []
            for i in range(len(d4['text'])):
                wd = d4['text'][i].strip()
                if not wd or int(d4['conf'][i]) < MIN_CONFIDENCE or not any(c.isalnum() for c in wd):
                    continue
                x = int(round(d4['left'][i] * inv)); y = int(round(d4['top'][i] * inv))
                w_ = int(round(d4['width'][i] * inv)); h_ = int(round(d4['height'][i] * inv))
                if h_ > 0 and w_ / h_ > max(4.0, 1.3 * len(wd)):   # barcode-strip guard
                    continue
                cx, cy = x + w_ / 2.0, y + h_ / 2.0
                covered = any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in pboxes)
                # add uncovered tokens; also add a covered token IF it is a clean
                # date/id/amount shape (a header value the primary sparse pass mangled)
                # — overlapping the garbage token is fine, spatial + fulltext both see it.
                if covered and not hi_val.match(wd):
                    continue
                text_annotations.append({"description": wd,
                                         "boundingPoly": {"vertices": _bbox_to_vertices(x, y, w_, h_)}})
                pboxes.append((x, y, x + w_, y + h_))
                add4.append(wd)
            if add4:
                full_text = (full_text or '') + '\n' + ' '.join(add4)
                text_annotations[0]["description"] = full_text
                logger.info("PSM-4 recovery added %d token(s)", len(add4))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("PSM-4 recovery skipped: %s", e)

    # Shadow-cell zoom pass: a 1-2 char token alone in a WIDE same-row gap between
    # normal-length neighbors marks a table cell the layout analysis under-read
    # ("PO26002620" collapsed to "0"). Crop the cell band, upscale 3x, single-line
    # re-OCR; a confident 4+-char alnum read replaces the stray glyph. Narrow cells
    # (a legit lone "0" quantity) never trigger — the gap guard requires the cell
    # to be several times wider than the stray token.
    if OCR_ZOOM_SHADOW:
        try:
            def _b(a):
                vs = a["boundingPoly"]["vertices"]
                xs = [v.get("x", 0) for v in vs]; ys = [v.get("y", 0) for v in vs]
                return min(xs), min(ys), max(xs), max(ys)

            words = [(j, _b(a), (a["description"] or '').strip())
                     for j, a in enumerate(text_annotations) if j > 0]
            zoom_added = []
            zoom_drop = set()
            zoom_seen = set()
            budget = 8                       # a handful of cells per doc, tops
            for j, (x0, y0, x1, y1), txt in words:
                if budget <= 0:
                    break
                if not (1 <= len(txt) <= 2) or (y1 - y0) <= 0:
                    continue
                h = y1 - y0; cy = (y0 + y1) / 2.0; w = max(1, x1 - x0)
                row = [(bx, b, t2) for bx, b, t2 in
                       ((jj, bb, t2) for jj, bb, t2 in words if jj != j)
                       if abs((b[1] + b[3]) / 2.0 - cy) < max(h, b[3] - b[1]) * 0.8]
                lefts = [b for _, b, t2 in row if b[2] <= x0 and len(t2) >= 3]
                rights = [b for _, b, t2 in row if b[0] >= x1 and len(t2) >= 3]
                if not lefts or not rights:
                    continue
                span_l = max(b[2] for b in lefts)
                span_r = min(b[0] for b in rights)
                span_w = span_r - span_l
                if span_w < max(3 * w, 40):
                    continue                 # narrow cell — the glyph is the content
                # the span must be genuinely empty: a real token OVERLAPPING it means
                # this is normal text (an underlined title row), not an unread cell —
                # zooming there re-reads fragments of already-read words as junk
                overlap = any(min(b[2], span_r) - max(b[0], span_l) > 0.25 * span_w
                              for _, b, t2 in row if len(t2) >= 3)
                if overlap:
                    continue
                span_key = (int(span_l) // 8, int(span_r) // 8, int(cy) // 8)
                if span_key in zoom_seen:
                    continue                 # same cell already zoomed via another glyph
                zoom_seen.add(span_key)
                s = scale or 1.0
                pad = int(h * 0.3 * s) or 2
                box = (max(0, int(span_l * s) - pad), max(0, int((cy - h * 0.9) * s)),
                       min(ocr_image.width, int(span_r * s) + pad),
                       min(ocr_image.height, int((cy + h * 0.9) * s)))
                if box[2] - box[0] < 8 or box[3] - box[1] < 4:
                    continue
                budget -= 1
                cell = ocr_image.crop(box)
                cell = cell.resize((cell.width * 3, cell.height * 3), Image.LANCZOS)
                dz = pytesseract.image_to_data(
                    cell, lang='eng',
                    config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-',
                    output_type=pytesseract.Output.DICT, timeout=TESSERACT_TIMEOUT)
                cand = ''.join(dz['text'][i].strip() for i in range(len(dz['text']))
                               if dz['text'][i].strip())
                # accept only an id-shaped run and take exactly it — the crop edges
                # bleed stray glyphs from the neighbor cells ("1PO26002620S"), and
                # psm-7 whitelist reads report conf 0 even when correct, so the
                # gate is structural: 0-2 letters + 5-12 digits.
                m = max(re.finditer(r'[A-Z]{0,2}[0-9]{5,12}', cand), default=None,
                        key=lambda mm: len(mm.group()))
                if m is not None:
                    # Tight box from the actual glyph positions: dz word boxes are in
                    # resized-crop space (crop `box` in ocr_image space, then x3). Union
                    # the dz words that make up the matched id and map back to page space,
                    # so the DRAW overlay frames the recovered value itself — not the whole
                    # empty cell span (which read as a loose, misplaced box).
                    zinv = 1.0 / scale if scale else 1.0
                    off = 0; mb = None
                    for k in range(len(dz['text'])):
                        tk = dz['text'][k].strip()
                        if not tk:
                            continue
                        a, b = off, off + len(tk); off = b
                        if a < m.end() and b > m.start():
                            lx, ly = dz['left'][k], dz['top'][k]
                            rx, ry = lx + dz['width'][k], ly + dz['height'][k]
                            mb = [lx, ly, rx, ry] if mb is None else \
                                [min(mb[0], lx), min(mb[1], ly), max(mb[2], rx), max(mb[3], ry)]
                    if mb is not None:
                        ox0 = box[0] + mb[0] / 3.0; oy0 = box[1] + mb[1] / 3.0
                        ox1 = box[0] + mb[2] / 3.0; oy1 = box[1] + mb[3] / 3.0
                        verts = _bbox_to_vertices(int(round(ox0 * zinv)), int(round(oy0 * zinv)),
                                                  int(round((ox1 - ox0) * zinv)),
                                                  int(round((oy1 - oy0) * zinv)))
                    else:
                        verts = _bbox_to_vertices(int(span_l), int(y0), int(span_w), int(h))
                    cand = m.group()
                    zoom_drop.add(j)
                    text_annotations.append({"description": cand,
                                             "boundingPoly": {"vertices": verts}})
                    zoom_added.append(cand)
            if zoom_drop:
                text_annotations = [a for j, a in enumerate(text_annotations)
                                    if j == 0 or j not in zoom_drop]
            if zoom_added:
                full_text = (full_text or '') + '\n' + ' '.join(zoom_added)
                text_annotations[0]["description"] = full_text
                logger.info(f"shadow-cell zoom recovered {len(zoom_added)} cell(s)")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"shadow-cell zoom skipped: {e}")

    # Second pass: recover outlier-large numbers (hero amounts, grand-total bands) that
    # the primary layout analysis under-reads (e.g. it collapses "14,385.08 ₪" to "8").
    # For each recovered region we DROP the primary pass's shadow words inside it (that
    # bogus "8" would otherwise win a find-after lookup) and add the clean number.
    if OCR_RECOVER_NUMBERS:
        recovered = _recover_large_numbers(ocr_image, TESS_CONFIG)
        inv = 1.0 / scale if scale else 1.0

        def _center(vs):
            xs = [p["x"] for p in vs]; ys = [p["y"] for p in vs]
            return (sum(xs) / 4.0, sum(ys) / 4.0)

        added = 0
        recovered_labels = []
        # group recovered tokens by their source region box
        regions = {}
        for tok, x, y, w, h in recovered:
            regions.setdefault((x, y, w, h), []).append(tok)
        for (x, y, w, h), toks in regions.items():
            # map region to original-image space
            rx, ry, rw, rh = x * inv, y * inv, w * inv, h * inv
            # drop primary word annotations whose centre lies inside this region
            kept = [text_annotations[0]]
            for a in text_annotations[1:]:
                cx, cy = _center(a["boundingPoly"]["vertices"])
                if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
                    continue  # shadow word from the primary pass — drop it
                kept.append(a)
            text_annotations = kept
            for tok in toks:
                text_annotations.append({
                    "description": tok,
                    "boundingPoly": {"vertices": _bbox_to_vertices(
                        int(round(rx)), int(round(ry)), int(round(rw)), int(round(rh)))},
                })
                added += 1
            # Block-mode re-read of the region expanded UPWARD: sparse PSM 11 mis-groups a
            # stacked label+big-number (a chip) in page context, mangling the label word
            # (הזמנת רכש -> רכשו) so a find-below anchor never matches. PSM 4 reads the crop
            # cleanly; add its non-numeric label words with mapped boxes above the number.
            chip_label_boxes = []   # label boxes that sit ABOVE and x-overlap the number
            try:
                ex0 = max(0, int(x - w * 0.10)); ey0 = max(0, int(y - h * 1.6))
                ex1 = int(x + w * 1.10); ey1 = int(y + h * 0.2)
                sub = ocr_image.crop((ex0, ey0, ex1, ey1))
                bd = pytesseract.image_to_data(sub, lang=lang,
                                               config=TESS_CONFIG.replace('--psm 11', '--psm 4'),
                                               output_type=pytesseract.Output.DICT,
                                               timeout=TESSERACT_TIMEOUT)
                for j in range(len(bd['text'])):
                    wd = bd['text'][j].strip()
                    if len(wd) < 2 or int(bd['conf'][j]) < 40:
                        continue
                    if any(ch.isdigit() for ch in wd):
                        continue                       # numbers handled above
                    lx = (ex0 + bd['left'][j]) * inv; ly = (ey0 + bd['top'][j]) * inv
                    lw = bd['width'][j] * inv; lh = bd['height'][j] * inv
                    if ly + lh > ry:
                        continue    # only text fully ABOVE the number (skip number-row garbage)
                    text_annotations.append({
                        "description": wd,
                        "boundingPoly": {"vertices": _bbox_to_vertices(
                            int(round(lx)), int(round(ly)), int(round(lw)), int(round(lh)))},
                    })
                    recovered_labels.append(wd)
                    added += 1
                    if lx < rx + rw and lx + lw > rx:   # x-overlapping the number
                        chip_label_boxes.append((lx, lw))
            except Exception as _e:  # pragma: no cover - defensive
                logger.warning(f"chip label recovery failed: {_e}")
            # Stacked-chip grouping fix: a left-aligned chip has a SHORT label over a WIDER
            # number, so the number's centre drifts past the anchor's perpendicular band and
            # find-below rejects it (visible in the query drawing: lines reach down but nothing
            # aligns). When we confirmed a label directly above and x-overlapping the number
            # (true chip, NOT a hero amount whose label is beside it), add a copy of the number
            # centred under the label so the below-anchor aligns cleanly.
            if chip_label_boxes and toks:
                lg0 = min(b[0] for b in chip_label_boxes)
                lg1 = max(b[0] + b[1] for b in chip_label_boxes)
                lcx = (lg0 + lg1) / 2.0
                dw = max(rw * 0.5, 40)
                text_annotations.append({
                    "description": toks[0],
                    "boundingPoly": {"vertices": _bbox_to_vertices(
                        int(round(lcx - dw / 2)), int(round(ry)), int(round(dw)), int(round(rh)))},
                })
                added += 1
        if added:
            # also surface in full_text so the fulltext fallback can see them
            full_text = full_text + "\n" + " ".join(t for t, *_ in recovered) \
                + ("\n" + " ".join(recovered_labels) if recovered_labels else "")
            text_annotations[0]["description"] = full_text
            logger.info(f"Local OCR recovered {added} large-number annotation(s)")

    # Third pass: refine money tokens. A digit whitelist reads amounts more accurately
    # than the general LSTM (which makes occasional 9->0 style single-digit slips), so
    # re-OCR each money-shaped token in isolation and correct it. General: keyed on the
    # money shape, not on any label. Toggle with APITOOLS_OCR_REFINE_MONEY=0.
    if OCR_REFINE_MONEY:
        import re as _re
        money_sub = _re.compile(r'\d[\d,]*\.\d{2}')          # trigger: looks money-ish
        money_ok = _re.compile(r'^\d[\d,]*\.\d{2}$')         # accept: clean money value
        wl_cfg = TESS_CONFIG + ' --psm 8 -c tessedit_char_whitelist=0123456789.,'
        fixed = 0
        for a in text_annotations[1:]:
            desc = a["description"]
            if not money_sub.search(desc):
                continue
            neg = desc.strip().startswith('-') or desc.strip().endswith('-')  # signed amount
            vs = a["boundingPoly"]["vertices"]
            xs = [p["x"] for p in vs]; ys = [p["y"] for p in vs]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            pad = int((y1 - y0) * 0.35) + 2
            # crop from the image OCR actually ran on (annotation coords are original space)
            cb = (max(0, int(x0 * scale) - pad), max(0, int(y0 * scale) - pad),
                  int(x1 * scale) + pad, int(y1 * scale) + pad)
            try:
                token = pytesseract.image_to_string(ocr_image.crop(cb), lang='eng',
                                                     config=wl_cfg, timeout=TESSERACT_TIMEOUT).strip()
            except Exception:
                continue
            # accept only a digit-for-digit CORRECTION (same DIGIT count): this fixes 9->0
            # style slips but rejects a spurious extra digit (a ₪ in the crop reads as a
            # leading "1", turning 6,198.28 into 16,198.28 — that must never win). Compare
            # digit counts, not string length, so a trailing "-" on a negative doesn't block it.
            if (money_ok.match(token)
                    and sum(c.isdigit() for c in token) == sum(c.isdigit() for c in desc)):
                signed = ('-' + token) if neg else token   # preserve a negative sign
                if signed != desc:
                    full_text = full_text.replace(desc, signed, 1)
                    a["description"] = signed
                    fixed += 1
        if fixed:
            text_annotations[0]["description"] = full_text
            logger.info(f"Local OCR refined {fixed} money token(s)")

    # Split-id merge: a low-res cell can break ONE id across adjacent same-row tokens
    # ("PO26002620" -> "PO26002" + "2620"). The concatenation isn't clean (fragment
    # boundaries overlap), so re-OCR the UNION region: a letter-prefixed id-start
    # immediately followed by a digit run, aligned on the same line, is re-read and — if it
    # yields a clean LONGER id with the same prefix — replaces the two fragments. Adjacent
    # only: a real gap (two separate values) reads as two tokens on the union and is left.
    try:
        def _mb(a):
            vs = a["boundingPoly"]["vertices"]
            xs = [v.get("x", 0) for v in vs]; ys = [v.get("y", 0) for v in vs]
            return min(xs), min(ys), max(xs), max(ys)
        items = [(j, _mb(text_annotations[j]), text_annotations[j]["description"])
                 for j in range(1, len(text_annotations))]
        m_budget = 6; m_drop = set(); m_add = []
        s = scale or 1.0
        for ia in range(len(items)):
            if m_budget <= 0:
                break
            ja, ba, ta = items[ia]
            if ja in m_drop or not re.fullmatch(r'[A-Za-z]{1,2}\d{3,}', ta):
                continue
            ha = (ba[3] - ba[1]) or 8; cya = (ba[1] + ba[3]) / 2.0
            for ic in range(len(items)):
                jb, bb, tb = items[ic]
                if ic == ia or jb in m_drop or not re.fullmatch(r'\d{2,}', tb):
                    continue
                if abs((bb[1] + bb[3]) / 2.0 - cya) > 0.6 * ha:
                    continue                              # not the same row
                if max(ba[0] - bb[2], bb[0] - ba[2]) > 0.4 * ha:
                    continue                              # not adjacent (real gap)
                ux0, uy0 = min(ba[0], bb[0]), min(ba[1], bb[1])
                ux1, uy1 = max(ba[2], bb[2]), max(ba[3], bb[3])
                pad = max(2, int(ha * 0.2 * s))
                sub = ocr_image.crop((max(0, int(ux0 * s) - pad), max(0, int(uy0 * s) - pad),
                                      min(ocr_image.width, int(ux1 * s) + pad),
                                      min(ocr_image.height, int(uy1 * s) + pad)))
                if sub.height < 48:
                    zf = max(2, 48 // max(1, sub.height) + 1)
                    sub = sub.resize((sub.width * zf, sub.height * zf), Image.LANCZOS)
                mtxt = pytesseract.image_to_string(
                    sub, lang='eng', timeout=TESSERACT_TIMEOUT,
                    config='--psm 7 -c tessedit_char_whitelist='
                           'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').strip()
                runs = re.findall(r'[A-Za-z]{0,2}\d{6,}', mtxt)
                best = max(runs, key=len) if runs else ''
                if best and len(best) > len(ta) and best[:3] == ta[:3]:
                    m_drop.add(ja); m_drop.add(jb)
                    m_add.append({"description": best, "boundingPoly": {"vertices":
                                  _bbox_to_vertices(ux0, uy0, ux1 - ux0, uy1 - uy0)}})
                    m_budget -= 1
                    break
        if m_drop:
            text_annotations = [x for k, x in enumerate(text_annotations)
                                if k == 0 or k not in m_drop] + m_add
            full_text = (full_text or '') + '\n' + ' '.join(a["description"] for a in m_add)
            text_annotations[0]["description"] = full_text
            logger.info("split-id merge combined %d fragment pair(s)", len(m_add))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"split-id merge skipped: {e}")

    # Barcode injection: decode 1-D barcodes and add each as a word annotation at its
    # bbox (so a find-below/anchor query lands on it) plus into the full text. Tesseract
    # can't read a barcode's payload; a delivery note's shipment id lives only there.
    for txt, bx0, by0, bx1, by1 in _decode_barcodes(image):
        if txt in full_text:
            continue
        text_annotations.append({
            "description": txt,
            "boundingPoly": {"vertices": _bbox_to_vertices(int(bx0), int(by0), int(bx1), int(by1))},
        })
        full_text = full_text + "\n" + txt
        text_annotations[0]["description"] = full_text

    # Small-photo id recovery: append any 9-digit company/VAT ids found via a raw-gray
    # upscale+angle sweep, so a find-option company lookup can resolve a folded letterhead.
    # ALWAYS runs for small images (a folded photo's company id is only recoverable here —
    # skipping it when *any* 9-digit is already read wrongly drops the real id on garbled
    # photos). The sweep itself is now trimmed (fewer scale/angle passes) so it's affordable.
    if min(width, height) < 1100:
        extra_ids = _photo_recover_fulltext(image) - set(_re.findall(r'(?<!\d)\d{9}(?!\d)', full_text))
        if extra_ids:
            full_text = full_text + "\n" + " ".join(sorted(extra_ids))
            text_annotations[0]["description"] = full_text
            for _id in sorted(extra_ids):
                text_annotations.append({
                    "description": _id,
                    "boundingPoly": {"vertices": _bbox_to_vertices(0, 0, 60, 16)},
                })

    # Photo zoom-verify pass (PHOTOS only): fix the two blur signatures the full-page
    # read leaves behind — see OCR_ZOOM_VERIFY above. Replace-only-if-strictly-better,
    # bounded budget, same discipline as the recrop/shadow guards.
    if OCR_ZOOM_VERIFY and min(width, height) < 1400:
        try:
            def _bx(a):
                vs = a["boundingPoly"]["vertices"]
                xs = [v.get("x", 0) for v in vs]; ys = [v.get("y", 0) for v in vs]
                return min(xs), min(ys), max(xs), max(ys)

            def _dig(s):
                return sum(ch.isdigit() for ch in s)

            zoom_budget = 5
            fixed = []

            def _core(s):
                return s.strip().strip('.,;:|"\'')

            # (a) OVERLAPPING digit-bearing tokens with different reads = one value
            # shattered/truncated ("15/05/20" + "5/05/20,"). Zoom-vote the union crop;
            # accept ONLY a candidate that EXTENDS the longer fragment (startswith) —
            # blind majority picks a confident misread ('18/05/2025' outvotes the true
            # '15/05/2025' on yhzkal), but the fragment prefix was read in-context and
            # constrains it: the unique extension IS the true value.
            words = [(k, a) for k, a in enumerate(text_annotations) if k > 0]
            drop, add, add_fulltext = set(), [], []
            for ii in range(len(words)):
                if zoom_budget <= 0:
                    break
                k1, a1 = words[ii]
                if k1 in drop or _dig(a1["description"]) < 4:
                    continue
                x0, y0, x1, y1 = _bx(a1)
                for jj in range(ii + 1, len(words)):
                    k2, a2 = words[jj]
                    if k2 in drop or _dig(a2["description"]) < 4:
                        continue
                    if a2["description"] == a1["description"]:
                        continue
                    u0, v0, u1, v1 = _bx(a2)
                    ox = max(0, min(x1, u1) - max(x0, u0)); oy = max(0, min(y1, v1) - max(y0, v0))
                    amin = max(1, min((x1 - x0) * (y1 - y0), (u1 - u0) * (v1 - v0)))
                    if ox * oy / amin < 0.5:
                        continue
                    stem = max(_core(a1["description"]), _core(a2["description"]), key=len)
                    if len(stem) < 5:
                        continue
                    mx0, my0, mx1, my1 = min(x0, u0), min(y0, v0), max(x1, u1), max(y1, v1)
                    cand = [(w, v) for w, v in _zoom_votes(image, mx0, my0, mx1, my1, lang).items()
                            if w.startswith(stem) and len(w) > len(stem)]
                    if len({w for w, _ in cand}) == 1:
                        best = cand[0][0]
                        drop.update((k1, k2))
                        add.append({"description": best,
                                    "boundingPoly": {"vertices": _bbox_to_vertices(
                                        int(mx0), int(my0), int(mx1 - mx0), int(my1 - my0))}})
                        fixed.append(f"{a1['description']!r}+{a2['description']!r}->{best!r}")
                        zoom_budget -= 1
                        break

            # (b) suspect PURE-DIGIT runs (>=5 digits, low/unknown confidence — recovery
            # passes don't carry conf) = plausible-looking misreads ("669764" for 697512).
            # Zoom-vote the box; replace only on CONSENSUS: winner repeats (>=2 votes),
            # clearly beats the runner-up, is digit-only (dates go through (a) only, so a
            # zoomed misread date can never overwrite a fragment), and is at least as
            # digit-rich. Misreads scatter across variants; the true value repeats.
            # SAFE cost control (no correctness risk): the primary pass gives a per-token
            # confidence; a number read at high confidence is essentially never a misread,
            # so only LOW-confidence digit runs are worth the vote. This skips most correct
            # tokens for ZERO Tesseract cost (vs the earlier single-read peek, which could
            # reproduce a misread and skip a real fix). Recovery tokens carry no conf and
            # stay eligible. Budget bounds the rest.
            for k, a in words:
                if zoom_budget <= 0:
                    break
                if k in drop:
                    continue
                t = _core(a["description"])
                conf = a.get("_conf", 55)  # recovery-pass tokens: verify-eligible
                if conf >= 70 or _dig(t) < 5 or not _re.fullmatch(r'\d{5,}', t):
                    continue
                x0, y0, x1, y1 = _bx(a)
                if not (15 <= x1 - x0 <= 500 and 8 <= y1 - y0 <= 80):
                    continue    # degenerate/synthetic boxes (barcodes, injected ids)
                vs = sorted(_zoom_votes(image, x0, y0, x1, y1, lang).items(),
                            key=lambda z: (-z[1][0], -z[1][1]))
                vs = [(w, v) for w, v in vs if _re.fullmatch(r'\d{5,}', w)]
                if not vs:
                    continue
                best, (bv, bc) = vs[0]
                runner = vs[1][1][0] if len(vs) > 1 else 0
                if best != t and bv >= 2 and bv >= 2 * runner and _dig(best) >= _dig(t):
                    fixed.append(f"{t!r}(c{conf})->{best!r}(v{bv})")
                    a["description"] = best
                    add_fulltext.append(best)
                    zoom_budget -= 1

            # (c) MISSING WORD in a row gap (add-only): the full-page pass drops a small
            # blurry Hebrew LABEL between a keyword and its value ("מס" between "חשבונית"
            # and the invoice number), so a two-word anchor can't match. Detect a
            # word-sized EMPTY gap between two meaningful same-row tokens, zoom-read it,
            # and ADD the pure-Hebrew consensus word. Add-only + strict consensus: a
            # recovered label can only help an anchor find-after, never overwrite a value.
            from PIL import ImageEnhance as _IE

            def _heb(s):
                return sum('א' <= ch <= 'ת' for ch in s)

            if zoom_budget > 0:
                surv = []
                for k, a in words:
                    if k in drop:
                        continue
                    bx = _bx(a)
                    surv.append((a, bx[0], bx[1], bx[2], bx[3]))
                surv.sort(key=lambda z: (z[2] + z[4]) // 2)
                # cluster into text rows by VERTICAL-INTERVAL OVERLAP (robust: a short
                # word like "חשבונית" and a taller number on the same visual line have
                # overlapping y-spans even when their centres differ by >0.6x a glyph).
                rows = []
                for rec in surv:
                    ry0, ry1 = rec[2], rec[4]; cy = (ry0 + ry1) // 2
                    for row in rows:
                        if row[0] - 4 <= cy <= row[1] + 4:
                            row[2].append(rec); row[0] = min(row[0], ry0); row[1] = max(row[1], ry1)
                            break
                    else:
                        rows.append([ry0, ry1, [rec]])
                existing = {_core(a["description"]) for _, a in words}
                # collect ONLY the label<->value boundary gaps (a Hebrew word beside a
                # digit-value): that is where a dropped label ("מס" between "חשבונית" and
                # the number) hides. Rare per doc, so the zoom stays cheap.
                cands = []
                for _y0, _y1, row in rows:
                    row.sort(key=lambda z: z[1])
                    for L, R in zip(row, row[1:]):
                        gap = R[1] - L[3]
                        rh = max(L[4] - L[2], R[4] - R[2], 10)
                        lw, rw = L[0]["description"], R[0]["description"]
                        boundary = (_heb(lw) >= 3 and _dig(rw) >= 5) or (_dig(lw) >= 5 and _heb(rw) >= 3)
                        if boundary and 0.7 * rh <= gap <= 4 * rh:
                            cands.append((gap, L, R))
                cands.sort(key=lambda z: -z[0])
                for _g, L, R in cands[:2]:          # at most 2 gap-zooms per photo
                    if zoom_budget <= 0:
                        break
                    rh = max(L[4] - L[2], R[4] - R[2], 12)
                    # a tight gap crop reads nothing; extend ~1 char-height into each
                    # neighbour for context (Tesseract needs surrounding strokes).
                    pad = int(rh)
                    gx0, gx1 = L[3], R[1]
                    gy0, gy1 = min(L[2], R[2]), max(L[4], R[4])
                    c = image.crop((max(0, gx0 - pad), max(0, gy0 - 6),
                                    min(image.width, gx1 + pad), min(image.height, gy1 + 6)))
                    if c.width < 8 or c.height < 8 or c.width > 400 or c.height > 200:
                        continue
                    up = c.resize((c.width * 4, c.height * 4), Image.LANCZOS)
                    ctr = _IE.Contrast(up.convert('L')).enhance(2.0)
                    ldesc, rdesc = L[0]["description"], R[0]["description"]
                    gv: dict = {}
                    for im2 in (up, ctr):
                        try:
                            dd = pytesseract.image_to_data(im2, lang=lang, config='--psm 7',
                                                           output_type=pytesseract.Output.DICT, timeout=12)
                        except Exception:
                            continue
                        for i in range(len(dd['text'])):
                            w = _core(dd['text'][i]); cf = int(dd['conf'][i])
                            aln = sum(ch.isalnum() for ch in w)
                            if not (2 <= len(w) <= 8 and cf >= 45 and _heb(w) >= 2 and _heb(w) == aln):
                                continue
                            if w in ldesc or w in rdesc:   # bleed from a neighbour glyph
                                continue
                            gv[w] = gv.get(w, 0) + 1
                    if not gv:
                        continue
                    best = max(gv, key=lambda w: gv[w]); bv = gv[best]
                    if bv >= 2 and best not in existing:   # agreed by both recipes
                        add.append({"description": best,
                                    "boundingPoly": {"vertices": _bbox_to_vertices(
                                        int(gx0), int(gy0), int(gx1 - gx0), int(gy1 - gy0))}})
                        add_fulltext.append(best); existing.add(best)
                        fixed.append(f"gap+{best!r}(v{bv})")
                        zoom_budget -= 1

            if drop or fixed:
                text_annotations = [a for k, a in enumerate(text_annotations)
                                    if k == 0 or k not in drop] + add
                extra = ' '.join([x["description"] for x in add] + add_fulltext)
                if extra:
                    full_text = (full_text or '') + '\n' + extra
                    text_annotations[0]["description"] = full_text
                logger.info("photo zoom-verify fixed %d token(s): %s", len(fixed), '; '.join(fixed))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"photo zoom-verify skipped: {e}")

    # internal keys must not leak into the cached/returned OCR json
    for a in text_annotations:
        a.pop("_conf", None)

    result = {
        "textAnnotations": text_annotations,
        "fullTextAnnotation": {
            "text": full_text,
        },
    }

    logger.info(f"Local OCR produced {len(text_annotations)-1} word annotations")
    return result


def ocr_from_base64(image_content: str, lang: str = DEFAULT_LANG) -> dict:
    """Run local OCR on a base64-encoded image string."""
    image_bytes = base64.b64decode(image_content)
    image = Image.open(io.BytesIO(image_bytes))
    return ocr_from_image(image, lang=lang)
