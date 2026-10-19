# -*- coding: utf-8 -*-
"""Resident Tesseract engine (libtesseract C API via ctypes).

WHY: pytesseract shells out to the `tesseract` binary for EVERY call. Measured on this
box, each invocation pays a fixed tax that has nothing to do with reading text:

    fork+exec .............   0.5 ms
    dynamic-link libtesseract   9.6 ms
    parse traineddata -> LSTM  88   ms   <- the killer
    PNG encode/write/read/decode  0.2-100 ms (by image size)
    ------------------------------------
    ~132 ms of pure ceremony per call

A photo runs ~251 calls => ~33 s of tax, and ~4.8 GB of redundant model loading, to
extract ~25 bytes. A 1-word crop measured 125 ms of which recognition was ~0 ms.

This module keeps ONE initialised API handle per (lang, tessdata, psm-independent)
process and feeds it raw grayscale bytes. Measured: 144.8 ms -> 20.8 ms per region
call (7.0x), 251-call workload 36.3 s -> 5.2 s.

EQUIVALENCE (critical): we deliberately use SetImage(CROP), never SetRectangle.
SetRectangle thresholds/segments over the WHOLE page and only restricts the ROI, which
changes results vs our crop-based reads (measured: differed on 3/5 probes). Feeding the
cropped image reproduces the current subprocess behaviour EXACTLY — verified 16/16
bit-identical across raw crops, 3x zoom, zoom+contrast and full page.

Fails soft: any error -> callers fall back to pytesseract.
"""
import ctypes
import os
import threading

from src.utils.logging_config import get_logger

logger = get_logger('apitools.tess_api')

# ON by default since 0.6.1 — opt out with APITOOLS_TESS_API=0.
#
# STATUS: proven at unit level (10/10 bit-identical; 7.3x/call) AND at integration
# level. The 176->31 collapse was _parse_cfg taking the FIRST --psm in a concatenated
# config while the CLI honors the LAST ('--psm 11 --psm 7' ran as 11: the number-
# recovery single-line probe read the whole page through a digits whitelist and
# flooded the merge). Fixed (last-flag-wins) and re-proven on yhzkal: 251 calls both
# paths, final token lists IDENTICAL (176), zoom fixes fire, 51.1s -> 29.9s (1.71x).
TESS_API_ENABLED = os.getenv('APITOOLS_TESS_API', '1') == '1'

_lib = None
_lock = threading.Lock()
_handles = {}          # (lang, datapath) -> api handle, per thread
_local = threading.local()
_sticky = {}          # (lang,datapath) -> variable names currently set on the handle


def _load():
    global _lib
    if _lib is not None:
        return _lib
    lib = ctypes.CDLL('libtesseract.so.5')
    lib.TessBaseAPICreate.restype = ctypes.c_void_p
    lib.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.TessBaseAPIInit3.restype = ctypes.c_int
    lib.TessBaseAPISetImage.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.TessBaseAPISetPageSegMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.TessBaseAPISetVariable.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.TessBaseAPISetVariable.restype = ctypes.c_int
    lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
    lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
    lib.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
    lib.TessDeleteText.argtypes = [ctypes.c_void_p]
    # --- ResultIterator: the image_to_data equivalent (text + conf + box per word) ---
    lib.TessBaseAPIRecognize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.TessBaseAPIRecognize.restype = ctypes.c_int
    lib.TessBaseAPIGetIterator.argtypes = [ctypes.c_void_p]
    lib.TessBaseAPIGetIterator.restype = ctypes.c_void_p
    lib.TessResultIteratorGetPageIterator.argtypes = [ctypes.c_void_p]
    lib.TessResultIteratorGetPageIterator.restype = ctypes.c_void_p
    lib.TessResultIteratorDelete.argtypes = [ctypes.c_void_p]
    lib.TessResultIteratorGetUTF8Text.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.TessResultIteratorGetUTF8Text.restype = ctypes.c_void_p
    lib.TessResultIteratorConfidence.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.TessResultIteratorConfidence.restype = ctypes.c_float
    lib.TessPageIteratorBegin.argtypes = [ctypes.c_void_p]
    lib.TessPageIteratorNext.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.TessPageIteratorNext.restype = ctypes.c_int
    lib.TessPageIteratorBoundingBox.argtypes = [ctypes.c_void_p, ctypes.c_int] + [ctypes.POINTER(ctypes.c_int)] * 4
    lib.TessPageIteratorBoundingBox.restype = ctypes.c_int
    _lib = lib
    return _lib


RIL_WORD = 3

# Tesseract's TSV renderer (what pytesseract parses) drops the LEADING bidi control mark
# the ResultIterator emits, but KEEPS a trailing one. Verified on a 131-word page:
#   raw            -> 18/131 words differ
#   lstrip(_BIDI)  ->  0/131  EXACT MATCH
#   strip(_BIDI)   ->  7/131 differ   (over-strips the trailing LRM)
# This matters: a leading RLM would break `re.fullmatch(r'\d{5,}', tok)` and silently
# disable the engine's digit-recovery rules.
_BIDI = '​‌‍‎‏‪‫‬‭‮⁦⁧⁨⁩'


def _api(lang: str, datapath: str):
    """One initialised handle per (lang, datapath) PER THREAD — a TessBaseAPI is not
    thread-safe, and the zoom-verify votes run in a ThreadPoolExecutor."""
    cache = getattr(_local, 'handles', None)
    if cache is None:
        cache = _local.handles = {}
    key = (lang, datapath or '')
    h = cache.get(key)
    if h is not None:
        return h
    lib = _load()
    api = ctypes.c_void_p(lib.TessBaseAPICreate())
    # datapath None => Tesseract's own default (TESSDATA_PREFIX). Several engine call
    # sites pass no --tessdata-dir and therefore use the SYSTEM (fast) models; that
    # behaviour must be preserved exactly, not silently upgraded to the bundled 'best'.
    rc = lib.TessBaseAPIInit3(api, (datapath.encode() if datapath else None), lang.encode())
    if rc != 0:
        lib.TessBaseAPIDelete(api)
        raise RuntimeError('TessBaseAPIInit3 failed rc=%s lang=%s datapath=%s' % (rc, lang, datapath))
    cache[key] = api
    logger.info('tess_api: initialised resident engine lang=%s (thread=%s)', lang,
                threading.current_thread().name)
    return api


def _apply_vars(lib, api, key, variables):
    """Apply per-call variables AND reset any left over from a previous call.

    CRITICAL: a subprocess gets a virgin Tesseract every call, so pytesseract's
    per-call `-c tessedit_char_whitelist=...` dies with the process. A RESIDENT handle
    keeps it — once _recover_large_numbers set a digits-only whitelist, every later call
    on that handle silently became digits-only (measured: 176 word annotations -> 31,
    all numeric). Any resident-engine port MUST reset sticky variables per call.
    """
    variables = variables or {}
    prev = _sticky.setdefault(key, set())
    for name in prev - set(variables):
        lib.TessBaseAPISetVariable(api, str(name).encode(), b'')   # reset to default
    for k, v in variables.items():
        lib.TessBaseAPISetVariable(api, str(k).encode(), str(v).encode())
    _sticky[key] = set(variables)


def available() -> bool:
    if not TESS_API_ENABLED:
        return False
    try:
        _load()
        return True
    except Exception as e:
        logger.warning('tess_api unavailable, falling back to subprocess: %s', e)
        return False


def image_to_text(image, lang: str, datapath: str, psm: int, variables: dict = None) -> str:
    """Recognise ONE image (already cropped/preprocessed by the caller) — the exact
    semantics of pytesseract.image_to_string on that same image, minus the ceremony."""
    lib = _load()
    api = _api(lang, datapath)
    im = image if image.mode == 'L' else image.convert('L')
    buf = im.tobytes()
    lib.TessBaseAPISetPageSegMode(api, int(psm))
    _apply_vars(lib, api, (lang, datapath or ''), variables)
    # bytes_per_pixel=1 (gray), bytes_per_line=width
    lib.TessBaseAPISetImage(api, buf, im.width, im.height, 1, im.width)
    p = lib.TessBaseAPIGetUTF8Text(api)
    if not p:
        return ''
    try:
        return ctypes.string_at(p).decode('utf-8', 'replace')
    finally:
        lib.TessDeleteText(p)


def image_to_words(image, lang: str, datapath: str, psm: int, variables: dict = None):
    """image_to_data(Output.DICT) equivalent via the ResultIterator.

    Returns a dict with the same keys the engine consumes from pytesseract:
    text / conf / left / top / width / height  (word level, RIL_WORD).
    Same crop-in semantics as image_to_text — no SetRectangle.
    """
    lib = _load()
    api = _api(lang, datapath)
    im = image if image.mode == 'L' else image.convert('L')
    buf = im.tobytes()
    lib.TessBaseAPISetPageSegMode(api, int(psm))
    _apply_vars(lib, api, (lang, datapath or ''), variables)
    lib.TessBaseAPISetImage(api, buf, im.width, im.height, 1, im.width)
    out = {'text': [], 'conf': [], 'left': [], 'top': [], 'width': [], 'height': []}
    if lib.TessBaseAPIRecognize(api, None) != 0:
        return out
    it = lib.TessBaseAPIGetIterator(api)
    if not it:
        return out
    it = ctypes.c_void_p(it)
    try:
        pit = ctypes.c_void_p(lib.TessResultIteratorGetPageIterator(it))
        l, t, r, b = (ctypes.c_int() for _ in range(4))
        while True:
            tp = lib.TessResultIteratorGetUTF8Text(it, RIL_WORD)
            if tp:
                try:
                    w = ctypes.string_at(tp).decode('utf-8', 'replace')
                finally:
                    lib.TessDeleteText(tp)
                cf = lib.TessResultIteratorConfidence(it, RIL_WORD)
                if lib.TessPageIteratorBoundingBox(pit, RIL_WORD,
                                                   ctypes.byref(l), ctypes.byref(t),
                                                   ctypes.byref(r), ctypes.byref(b)):
                    # pytesseract reads Tesseract's TSV, which TRUNCATES the float
                    # confidence (52.85 -> 52). round() would give 53 and silently shift
                    # every conf-gated decision in the engine. Verified against TSV.
                    out['text'].append(w.strip().lstrip(_BIDI))
                    out['conf'].append(int(cf))
                    out['left'].append(l.value); out['top'].append(t.value)
                    out['width'].append(r.value - l.value); out['height'].append(b.value - t.value)
            if not lib.TessPageIteratorNext(pit, RIL_WORD):
                break
    finally:
        lib.TessResultIteratorDelete(it)
    return out
