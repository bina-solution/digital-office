"""esign — the PDF half of «מילוי וחתימה» (DGO-2139).

Three jobs, none of which calls an outside service:

  * a document's pages as pictures a phone shows at once (`render_page`, pypdfium2), cached on the volume;
  * the places a document asks to be filled and signed, read from the document itself (`detect`): the words a form
    prints under its lines («חתימה», «תאריך», «שם ותפקיד»…), the line above each, and the names printed over each block
    of lines, which say whose block it is;
  * the final copy (`fill`): every side's answers and signature drawn INTO the pages. Drawn, not put in form fields:
    a PDF viewer draws a form field's text itself, and none draws Hebrew right (research 03, DGO-2139).

A place on a page is four fractions of the page AS IT IS SHOWN (its CropBox, turned by its /Rotate), from its top-left
corner: x, y, width, height. The phone, the office's editor and this file read the same four numbers.
"""
from __future__ import annotations

import io
import os
import re
import threading
from typing import Iterable

import pikepdf

from pdfsign import _font, he

#: pdfium is not thread-safe, not even on two different documents (pypdfium2's own README), and the app serves each
#: request on a thread of its own: every call into it holds this lock (the second reader, DGO-2139)
PDFIUM = threading.Lock()
#: the widths a page picture is drawn at — any other asked for is the nearest of these (one file per width is kept)
WIDTHS = (600, 1100, 1600)

# ── a page as it is shown ──────────────────────────────────────────────────────────────────────────


def _inherited(obj, key: str):
    """A page attribute as a viewer reads it: on the page, else on the nearest /Pages node above it (PDF 93.184.216.16)."""
    seen = 0
    while obj is not None and seen < 32:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        seen += 1
    return None


def _boxes(page: pikepdf.Page) -> tuple[list[float], int]:
    """The visible box (the CropBox inside the MediaBox, either inherited) and the turn, as a viewer shows the page."""
    media = [float(v) for v in (_inherited(page.obj, "/MediaBox") or page.mediabox)]
    crop = [float(v) for v in (_inherited(page.obj, "/CropBox") or media)]
    box = [max(media[0], crop[0]), max(media[1], crop[1]), min(media[2], crop[2]), min(media[3], crop[3])]
    if box[2] <= box[0] or box[3] <= box[1]:
        box = media
    rot = int(_inherited(page.obj, "/Rotate") or 0) % 360
    return box, rot


def page_sizes(path: str) -> list[dict]:
    """Each page's shown width and height in points, and its turn — what a place's fractions are fractions of."""
    out = []
    with pikepdf.open(path) as pdf:
        for page in pdf.pages:
            box, rot = _boxes(page)
            w, h = box[2] - box[0], box[3] - box[1]
            if rot in (90, 270):
                w, h = h, w
            out.append({"w": round(w, 2), "h": round(h, 2), "rotate": rot})
    return out


#: the ink a hand is kept in, whatever the signer's screen drew it in (the palette's ink on paper: a phone in dark mode
#: inks in near-white, and its signature was invisible on the white page — the second reader)
PRINT_INK = (31, 42, 23)


def ink_png(raw: bytes, max_px: int = 4_000_000) -> bytes | None:
    """A signature as it is kept: the strokes' shape (their alpha) in PRINT_INK, so the page, the preview and the PDF
    agree. None for what is not a picture, or one too large to draw (a small file can decode to a huge one)."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        if im.width * im.height > max_px or max(im.width, im.height) > 4000:
            return None
        alpha = im.convert("RGBA").getchannel("A")
    except Exception:
        return None
    hand = Image.new("RGBA", alpha.size, PRINT_INK + (255,))
    hand.putalpha(alpha)
    out = io.BytesIO()
    hand.save(out, "PNG", optimize=True)
    return out.getvalue()


def picture_ok(raw: bytes, max_px: int = 12_000_000) -> bool:
    """A stamp's photo: a picture PIL reads, of a size a seal can draw."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        return im.width * im.height <= max_px and max(im.width, im.height) <= 6000
    except Exception:
        return False


def snap_width(width) -> int:
    try:
        w = int(width)
    except (TypeError, ValueError):
        w = 1100
    return min(WIDTHS, key=lambda v: abs(v - w))


def render_page(path: str, n: int, width: int, cache_dir: str = "", key: str = "") -> tuple[bytes, str]:
    """Page `n` (from 1) as a picture `width` pixels wide (one of WIDTHS): WebP, the lightest a phone opens (research
    04). The same page at the same width is drawn once and kept (`cache_dir`/`key`)."""
    width = snap_width(width)
    cached = os.path.join(cache_dir, "%s-%d-%d.webp" % (key, n, width)) if cache_dir and key else ""
    if cached and os.path.exists(cached):
        with open(cached, "rb") as fh:
            return fh.read(), "image/webp"
    import pypdfium2 as pdfium
    with PDFIUM:
        doc = pdfium.PdfDocument(path)
        try:
            if n < 1 or n > len(doc):
                raise IndexError("no such page")
            page = doc[n - 1]
            scale = width / float(page.get_width())
            bitmap = page.render(scale=scale, may_draw_forms=True)
            image = bitmap.to_pil().copy()                       # its own pixels: the bitmap is freed here, locked
            bitmap.close()
        finally:
            doc.close()
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "WEBP", quality=80, method=4)
    data = buf.getvalue()
    if cached:
        os.makedirs(cache_dir, exist_ok=True)
        tmp = cached + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, cached)
    return data, "image/webp"


# ── where a document asks to be filled ────────────────────────────────────────────────────────────
#: the words a form prints at a place, and what goes there. Read in order: the first that matches a label wins, so
#: «חתימה וחותמת» is a signature before «חתימה» is, and «שם ותפקיד» is two answers before «שם» is one.
LABELS = (
    (re.compile(r"שם\s*ו\s*תפקיד"), ("name", "text")),
    (re.compile(r"שם\s*ו\s*חתימה"), ("name", "signature")),      # a delivery note's receiver: who, and his hand
    # the word itself, not inside another: «נשלח קישור החתימה», «בתאריך» are a sentence's words (a certificate's row)
    # …and its construct form, the most common in a contract: «חתימת הלקוח», «חתימת המזמין» (round 5)
    (re.compile(r"(?<![א-ת])(?:חתימה\s*ו\s*חותמת|חתימה|חתימת)"), ("signature",)),
    (re.compile(r"ראשי\s*תיבות"), ("initials",)),
    (re.compile(r"(?<![א-ת])תאריך"), ("date_signed",)),
    # the short forms only as a word of their own: «עמ» is inside «עמוד», «חפ» inside a word
    (re.compile(r"(?:^|\s)(?:ת\.\s?ז\.?|ת[״\"]ז|תז)(?:$|\s)|תעודת\s*זהות|מספר\s*זהות"), ("id_number",)),
    (re.compile(r"(?:^|\s)(?:ח\.\s?פ\.?|ח[״\"]פ|ע\.\s?מ\.?|ע[״\"]מ)(?:$|\s)|מספר\s*(?:עוסק|חברה)"), ("company_number",)),
    (re.compile(r"טלפון|נייד"), ("phone",)),
    (re.compile(r"דוא\"?״?ל|אימייל|דואר\s*אלקטרוני"), ("email",)),
    (re.compile(r"כתובת"), ("text",)),
    (re.compile(r"תפקיד"), ("text",)),
    (re.compile(r"שם\s*מלא|^שם$"), ("name",)),
)
#: what each kind of place asks the person, by default (the office rewords it in «מסמכים»)
QUESTION = {"name": "שם מלא", "signature": "חתימה", "initials": "ראשי תיבות", "date_signed": "תאריך",
            "id_number": "מספר זהות", "company_number": "ח.פ. / ע.מ.", "phone": "טלפון", "email": "דוא״ל"}
#: how tall a place is, in points, when the page leaves room for it
HEIGHT = {"signature": 40.0, "initials": 24.0}
TEXT_HEIGHT = 17.0


def _runs(textpage, n_chars: int) -> list[dict]:
    """The page's text as runs of characters on one line with no wide gap between them, each with its box (points,
    origin at the bottom-left of the page as pdfium gives it)."""
    runs, cur = [], None
    for i in range(n_chars):
        ch = textpage.get_text_range(i, 1)
        try:
            l, b, r, t = textpage.get_charbox(i)
        except Exception:                                         # a character with no box (a generated space)
            l = b = r = t = 0.0
        if not ch or ch in "\r\n" or (r - l) <= 0 and ch != " ":
            if cur:
                runs.append(cur)
            cur = None
            continue
        if ch == " ":
            if cur:
                cur["text"] += " "
            continue
        mid = (b + t) / 2
        if cur and abs(mid - cur["mid"]) < 3 and (l - cur["r"] < 9 and cur["l"] - r < 9):
            cur["text"] += ch
            cur["l"], cur["r"] = min(cur["l"], l), max(cur["r"], r)
            cur["b"], cur["t"] = min(cur["b"], b), max(cur["t"], t)
        else:
            if cur:
                runs.append(cur)
            cur = {"text": ch, "l": l, "r": r, "b": b, "t": t, "mid": mid}
    if cur:
        runs.append(cur)
    for r in runs:
        r["text"] = r["text"].strip()
        # a PDF may keep a Hebrew line in the order it is drawn (right to left as stored): read both ways
        r["rev"] = r["text"][::-1]
    return [r for r in runs if r["text"]]


def _lines(page) -> list[tuple]:
    """The page's horizontal lines (a thin path or a thin filled box, as a browser prints a border; or the edge a box
    with a box cut out of it paints, see _edges): (y, x0, x1, top) — `top` the top of the element whose bottom border
    the line is, None for a line of its own."""
    import pypdfium2.raw as raw
    out = []
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH], max_depth=4):
        bounds = getattr(obj, "get_bounds", None) or getattr(obj, "get_pos", None)   # pypdfium2 5 / 4
        try:
            l, b, r, t = bounds()[:4]
        except Exception:
            continue
        if (r - l) >= 40 and (t - b) <= 2.5:
            out.append(((b + t) / 2, l, r, None))
        elif (r - l) >= 40:
            out.extend(_edges(obj))
    out.sort(key=lambda ln: ln[:3])
    merged = []
    for y, l, r, top in out:                                      # one line drawn as several strokes is one line
        if merged and abs(merged[-1][0] - y) < 1 and l <= merged[-1][2] + 2 and r >= merged[-1][1] - 2:
            py, pl, pr, ptop = merged[-1]
            merged[-1] = (py, min(pl, l), max(pr, r), ptop if ptop is not None else top)
        else:
            merged.append((y, l, r, top))
    return merged


def _edges(obj) -> list[tuple[float, float, float]]:
    """The lines a path paints when it is one upright box with another cut out of it: that is how a browser prints an
    element's border-bottom (or border-top) — the path is the whole element (the office's own signing cells are
    18.7pt tall, an agreement's signing area 48pt), and its ink only the strip where the two boxes differ. The strips
    up to 2.5pt thick, as (y, x0, x1, top) in the frame pdfium gives the path's bounds in — `top` the element's top
    for a border at its bottom (None for one at its top); none when the boxes differ at their sides too (a frame),
    when the path is stroked, curved, or anything else, or when the whole box is filled."""
    import ctypes

    import pypdfium2.raw as raw
    try:
        h = obj.raw
        a, b, c, d, e, f = obj.get_matrix().get()
        n = raw.FPDFPath_CountSegments(h)
        fill, stroke = ctypes.c_int(), ctypes.c_int()
        if not raw.FPDFPath_GetDrawMode(h, ctypes.byref(fill), ctypes.byref(stroke)):
            return []
    except Exception:
        return []
    if not 8 <= n <= 12 or b or c or not a or not d or stroke.value:
        return []
    if fill.value not in (raw.FPDF_FILLMODE_ALTERNATE, raw.FPDF_FILLMODE_WINDING):
        return []
    subs, x, y = [], ctypes.c_float(), ctypes.c_float()
    for i in range(n):
        seg = raw.FPDFPath_GetPathSegment(h, i)
        kind = raw.FPDFPathSegment_GetType(seg)
        if kind == raw.FPDF_SEGMENT_BEZIERTO or not raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y)):
            return []                                         # a curve: a rounded frame, a mark — not a line
        if kind == raw.FPDF_SEGMENT_MOVETO or not subs:
            subs.append([])
        subs[-1].append((a * x.value + e, d * y.value + f))
    if len(subs) != 2:
        return []

    def turn(pts):                                            # which way a box is drawn: + one way, − the other
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if fill.value == raw.FPDF_FILLMODE_WINDING and turn(subs[0]) * turn(subs[1]) >= 0:
        return []                                             # both drawn one way, non-zero fill: the whole box is ink
    boxes = []
    for pts in subs:
        xs, ys = {round(p[0], 2) for p in pts}, {round(p[1], 2) for p in pts}
        if len(xs) != 2 or len(ys) != 2:
            return []                                         # two upright boxes and nothing else
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    (l1, b1, r1, t1), (l2, b2, r2, t2) = boxes
    if abs(l1 - l2) > 0.5 or abs(r1 - r2) > 0.5:
        return []                                             # it has sides too: a frame, not a line
    out = []
    lo, hi = sorted((b1, b2))
    if 0 < hi - lo <= 2.5:                                    # a border-bottom: the element stands above the line
        out.append(((lo + hi) / 2, min(l1, l2), max(r1, r2), max(t1, t2)))
    lo, hi = sorted((t1, t2))
    if 0 < hi - lo <= 2.5:                                    # a border-top: the element hangs under the line
        out.append(((lo + hi) / 2, min(l1, l2), max(r1, r2), None))
    return out


def detect(path: str, hints: Iterable[str] = ()) -> dict:
    """The places a document asks to be filled and signed, as the office's editor first shows them.

    Every label of LABELS printed UNDER a line marks a place on that line. Labels under one line share it, each taking
    the part on its own side. Places whose lines stand close together are one side's block; a block's side is the
    name printed above it that matches one of `hints` (the parties the caller knows: the customer, the business),
    else the blocks are taken right to left, as the page reads. Answers: {parties, fields, found: {page}}."""
    hints = [h for h in (s.strip() for s in hints) if h]
    with PDFIUM:
        places = _read_places(path)
    return _sides(places, hints)


#: what a printed date looks like: a year, a day and a month («19.11», «19/11/2026»), a day and a month's name — each
#: a number of its own, never digits inside an ID or a phone number («ת.ז. 320134567», «050-0000023»; round 6)
DATE_SHAPE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)|(?<!\d)\d{1,2}[./-]\d{1,2}(?!\d)|(?<!\d)\d{1,2}\s*ב?(?:ינואר|"
                        r"פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר)")
#: the answers that say WHO a side is or that it signed: a block that already asks one is the next side's when it is
#: asked again (two «תפקיד», «כתובת», two phones are one side's — round 6)
SIDE_KINDS = {"name", "signature", "initials", "date_signed", "id_number", "company_number"}


def _label(run: dict) -> tuple:
    """(kinds, the label as read) when the run is a place's label — a few words of LABELS and nothing else («1 · חתימה»
    over a step, «תאריך 19.11.2026» are not) — else (None, "")."""
    for rx, kinds in LABELS:
        if rx.search(run["text"]) or rx.search(run["rev"]):
            said = run["text"] if rx.search(run["text"]) else run["rev"]
            if len(run["text"]) > 24 or re.search(r"[0-9·•:]", run["text"]) or len(said.split()) > 3:
                return None, ""
            return kinds, said
    return None, ""


def _read_places(path: str) -> list[dict]:
    """Every label under a line, on every unturned page, with the page's visible box (pdfium's: inherited boxes too)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    places = []
    try:
        for pno in range(len(doc)):
            page = doc[pno]
            if page.get_rotation() % 360:
                continue                                          # a turned page: the office places by hand
            # the visible box as a viewer has it — CropBox ∩ MediaBox, INHERITED from the page tree too (pdfium's
            # get_cropbox() does not inherit, and a box set only on /Pages fell back to US Letter — the second reader)
            cl, cb, cr, ct = [float(v) for v in page.get_bbox()]
            W, H = cr - cl, ct - cb
            tp = page.get_textpage()
            runs = _runs(tp, tp.count_chars())
            lines = _lines(page)
            for run in runs:
                kinds, said = _label(run)
                if not kinds:
                    continue
                # the line just above the label, over it
                over = [ln for ln in lines if 0 < ln[0] - run["t"] < 22 and ln[1] - 4 <= run["r"] and ln[2] + 4 >= run["l"]]
                if not over:
                    continue
                y, x0, x1, top = min(over, key=lambda ln: ln[0] - run["t"])
                # a label that does not CLEARLY hug the line above it — nearer the line below, or near both — is the
                # line below's, written over it: a form's «label, then its field», a ruled table's key centred in its
                # row (a tie the glyphs decide: 6.8 vs 7.3pt, round 8). Not this model's (a label under its line): no
                # place here, the office places it by hand — the answer went on the field above (round 7). A form's
                # labels under lines 20pt apart stand 0.4–0.66 of the way; a centred key 0.9–1.1; 0.8 parts them
                beneath = [run["b"] - ln[0] for ln in lines
                           if 0 <= run["b"] - ln[0] < 22 and ln[1] - 4 <= run["r"] and ln[2] + 4 >= run["l"]]
                if beneath and not y - run["t"] < 0.8 * min(beneath):
                    continue
                # the line is the bottom border of a field whose own label hugs its top from above (a printed web
                # form's tall input): that field is its label's, and a label under its border is the NEXT field's
                # (round 8: each answer went into the input above). A label's margin over its input is up to ~12pt
                # in print; only a LABEL counts — a party's name printed over the office's own cells does not (round 9)
                if top is not None and any(r is not run and 0 <= r["b"] - top < 12 and r["r"] > x0 and r["l"] < x1
                                           and _label(r)[0] for r in runs):
                    continue
                # the label is the first LABEL printed under its line: a second line under a label («ע.מ. 300000015»
                # under «חתימה») is that label's, not the line's. Other words between are no matter: a company's name
                # printed under the line, then «חתימה וחותמת» (round 6)
                if any(r is not run and r["t"] < y and r["b"] > run["t"] - 1 and _label(r)[0]
                       and min(r["r"], run["r"]) - max(r["l"], run["l"]) > 0 for r in runs):
                    continue
                # a date label with its date printed right under it is a fact, not a place: a cover's «תאריך» over
                # «19 בנובמבר 2026», a table's «תאריך» over its first row's date. The words under it are read
                # together — a PDF may keep «19 בנובמבר» and «2026» apart. (A party's number under «חתימה» is the
                # signing block's own line: still a place — the second reader, round 5.)
                below = [r for r in runs if r is not run and 0 < run["b"] - r["t"] < 14
                         and min(r["r"], run["r"] + 60) - max(r["l"], run["l"] - 60) > 0]
                said_below = " ".join(r["text"] for r in sorted(below, key=lambda r: -r["r"]))
                if kinds[0] == "date_signed" and below and (
                        DATE_SHAPE.search(said_below) or DATE_SHAPE.search(said_below[::-1])) and any(
                        min(r["r"], run["r"]) - max(r["l"], run["l"]) > 0.5 * (run["r"] - run["l"]) for r in below):
                    continue
                # a line already written on is no place to write: a ruled table's row rule with the row's own text
                # right above it, a cell «שם מלא» under it (round 5: _edges reads those rules as lines). The label of
                # the line above, standing alone on its row, is not writing — a stacked form's lines are 20pt apart
                # (round 6) — but a table's key with its value beside it is. On a written line a signature is still
                # signed there: «שם וחתימה» keeps its hand and drops the name
                def written(r):
                    if not _label(r)[0]:
                        return True
                    return any(q is not r and abs(q["mid"] - r["mid"]) < 3 and not _label(q)[0]
                               and q["r"] > x0 - 4 and q["l"] < x1 + 4 for q in runs)
                drop: set = set()
                if any(y + 0.5 < r["b"] < y + 12 and min(r["r"], run["r"] + 10) - max(r["l"], run["l"] - 10) > 2
                       and written(r) for r in runs if r is not run):
                    # the signing part stays where it was — «שם וחתימה»'s hand keeps its own side of the line, off
                    # the printed name (round 7)
                    drop = {k for k in kinds if k not in ("signature", "initials")}
                    if drop == set(kinds):
                        continue
                # what is printed on the line, anywhere along it: a hand is drawn beside it, never over it (round 8)
                ink = [r for r in runs if r is not run and y + 0.5 < r["b"] < y + 12 and r["r"] > x0 and r["l"] < x1
                       and written(r)]
                places.append({"page": pno + 1, "W": W, "H": H, "left": cl, "top": ct, "y": y, "x0": x0, "x1": x1,
                               "run": run, "kinds": kinds, "drop": drop, "text": said, "runs": runs,
                               "ink": sorted((r["l"], r["r"]) for r in ink)})
    finally:
        doc.close()
    return places


def _sides(places: list[dict], hints: list[str]) -> dict:
    """The labels found, made into sides and places (see detect)."""
    if not places:
        return {"parties": [{"id": "p1", "label": hints[0] if hints else "צד א׳", "note": ""}], "fields": [], "found": None}

    # each label owns the part of its line on its own side of the gap between the labels under that line
    by_line: dict = {}
    for p in places:
        by_line.setdefault((p["page"], round(p["y"], 1), round(p["x0"]), round(p["x1"])), []).append(p)
    for group in by_line.values():
        group.sort(key=lambda p: p["run"]["l"])
        for i, p in enumerate(group):
            left = p["x0"] if i == 0 else (group[i - 1]["run"]["r"] + p["run"]["l"]) / 2
            right = p["x1"] if i == len(group) - 1 else (p["run"]["r"] + group[i + 1]["run"]["l"]) / 2
            if p["kinds"][0] in ("date_signed", "initials"):
                # a date is short: it stands over its own label, at the end of the line the label is at
                wdt = min(right - left, max(72.0, p["run"]["r"] - p["run"]["l"] + 30))
                if (p["run"]["l"] + p["run"]["r"]) / 2 < (p["x0"] + p["x1"]) / 2:
                    right = left + wdt
                else:
                    left = right - wdt
            p["a"], p["b"] = left, right

    # blocks: the places of one side stand together — side by side in one row of cells a narrow gap apart (the
    # office's own «אישור הלקוח»: «שם מלא · תפקיד · תאריך · חתימה וחותמת», 17pt apart; two sides' boxes stand wider
    # apart, an agreement's 22.7pt), or one under another (overlapping across, near in height). A place joins its row
    # first, and a block never asks one thing twice: a second signature, side by side or under, is the next side
    # (the second reader, round 5: two parties' rows stacked in the same columns gave the second's signature to the
    # first)
    def asks(blk):
        return {k for o in blk for k in o["kinds"]} & SIDE_KINDS

    def beside(blk, p):
        q = blk[-1]
        if not (abs(q["y"] - p["y"]) < 2 and max(q["x0"] - p["x1"], p["x0"] - q["x1"]) < 20):
            return False
        # a cell joins the block that IS its row — never asking one thing twice there: «טלפון | טלפון» side by side
        # are two sides (round 9) — or one that already has a place over the cell's own column: two parties'
        # columns a narrow gutter apart stay two sides, row by row (round 8)
        if all(abs(o["y"] - p["y"]) < 2 for o in blk):
            return not set(p["kinds"]) & {k for o in blk for k in o["kinds"]}
        return any(o["y"] > p["y"] and min(o["x1"], p["x1"]) - max(o["x0"], p["x0"]) > 20 for o in blk)

    def under(blk, p):
        q = blk[-1]
        return min(q["x1"], p["x1"]) - max(q["x0"], p["x0"]) > 20 and abs(q["y"] - p["y"]) < 160

    blocks: list[list[dict]] = []
    for p in sorted(places, key=lambda p: (p["page"], -round(p["y"], 1), -p["x1"])):
        home = None
        for near in (beside, under):
            fits = [blk for blk in blocks if blk[-1]["page"] == p["page"] and near(blk, p)
                    and not set(p["kinds"]) & asks(blk)]
            if fits:
                # the NEAREST block that fits, the newest on a tie: the oldest one handed a lower party's phone to
                # the party above it, stacked in the same column (round 7)
                home = min(reversed(fits), key=lambda blk: abs(blk[-1]["y"] - p["y"]))
                break
        if home is not None:
            home.append(p)
        else:
            blocks.append([p])
    blocks.sort(key=lambda blk: (blk[0]["page"], -max(p["x1"] for p in blk)))     # right to left, as the page reads

    # a block's side: the name printed just above it that is one of the hints; the short line printed right under that
    # name («בשם הלקוח», «ישראל ישראלי») is the side's note, read the way the name was read (stored order or reversed)
    owner, notes = [], {}
    for blk in blocks:
        top = max(p["y"] for p in blk)
        x0, x1 = min(p["x0"] for p in blk), max(p["x1"] for p in blk)
        found, near = "", [r for r in blk[0]["runs"]
                           if r["b"] > top and r["b"] - top < 120 and r["r"] > x0 - 10 and r["l"] < x1 + 10]
        # the NEAREST name above is the block's (two parties' rows stacked: the upper party's name is above both)
        for run in sorted(near, key=lambda r: r["b"]):
            for h in hints:
                if h in run["text"] or h in run["rev"]:
                    found = h
                    under = [r for r in near if 0 < run["b"] - r["t"] < 14 and r is not run and len(r["text"]) <= 40]
                    if under and not re.search(r"[0-9]", under[0]["text"]):
                        notes[h] = under[0]["text"] if h in run["text"] else under[0]["rev"]
                    break
            if found:
                break
        owner.append(found)
    labels = []
    left = [h for h in hints if h not in owner]
    for found in owner:
        labels.append(found or (left.pop(0) if left else "צד %s" % "אבגדהוזחטי"[len(labels) % 10] + "׳"))
    parties, pid_of = [], {}
    for lab in labels:
        if lab not in pid_of:
            pid_of[lab] = "p%d" % (len(parties) + 1)
            parties.append({"id": pid_of[lab], "label": lab, "note": notes.get(lab, "")})

    fields, n = [], 0
    for blk, lab in zip(blocks, labels):
        pid = pid_of[lab]
        heights = sorted({round(p["y"], 1) for p in blk}, reverse=True)
        for p in sorted(blk, key=lambda p: -p["y"]):
            W, H, y = p["W"], p["H"], p["y"]
            # the room above a line: up to the block's line above it (with its label), else a signature's height
            above = [h for h in heights if h > y + 0.5]
            room = (min(above) - y - 6) if above else 60.0
            spans = [(p["a"], p["b"])]
            if len(p["kinds"]) == 2:
                # «שם ותפקיד»: the name on the right, the role beside it; «שם וחתימה»: the drawn hand gets the wider
                # part (the typed name shrinks to fit; a delivery note's hand was 45pt wide)
                cut = 0.58 if p["kinds"][1] in ("signature", "initials") else 0.42
                mid = p["a"] + (p["b"] - p["a"]) * cut
                spans = [(mid + 3, p["b"]), (p["a"], mid - 3)]
            for kind, (a, b) in zip(p["kinds"], spans):
                if kind in p.get("drop", ()):
                    continue                                      # already printed on the line (see _read_places)
                if kind in ("signature", "initials") and p.get("ink"):
                    # the hand takes the widest free stretch of its span between what is printed on the line — a
                    # name at one end, a date at the other (rounds 8–9)
                    gaps, cur = [], a
                    for lo, hi in p["ink"]:
                        gaps.append((cur, min(b, lo - 6)))
                        cur = max(cur, hi + 6)
                    gaps.append((cur, b))
                    free = max(gaps, key=lambda s: s[1] - s[0])
                    if free[1] - free[0] >= 30:
                        a, b = free
                n += 1
                hgt = min(HEIGHT.get(kind, TEXT_HEIGHT), max(room, 12.0))
                f = {"id": "f%d" % n, "party": pid, "type": kind, "label": QUESTION.get(kind, p["text"]),
                     "help": "", "required": True, "page": p["page"],
                     # fractions of the VISIBLE box, from its top-left: a page cropped off its origin counts from its
                     # own corner (the second reader: user space divided by the crop's size moved every place)
                     "box": [round(max(0.0, a - p["left"]) / W, 4), round(max(0.0, p["top"] - y - hgt - 1.5) / H, 4),
                             round((b - a) / W, 4), round(hgt / H, 4)]}
                if kind == "signature":
                    f["label"] = p["text"]                       # the document's own word: «חתימה וחותמת»
                if kind == "text":
                    f["label"] = "תפקיד" if "תפקיד" in p["text"] else p["text"]
                if kind in ("name",) or (kind == "text" and "תפקיד" in p["text"]):
                    f["group"] = "מי חותם בשם %s?" % lab
                elif kind not in ("signature", "initials", "date_signed"):
                    f["group"] = "הפרטים של %s" % lab
                fields.append(f)
    return {"parties": parties, "fields": fields, "found": {"page": fields[0]["page"]} if fields else None}


# ── the final copy ─────────────────────────────────────────────────────────────────────────────────


def _to_user(rot: int, box: list[float]) -> tuple:
    """The matrix that takes a point of the page AS SHOWN (origin bottom-left, x right, y up) to the page's own user
    space — the inverse of what a viewer does with /Rotate and the CropBox."""
    cx0, cy0, cx1, cy1 = box
    cw, ch = cx1 - cx0, cy1 - cy0
    if rot == 90:
        return (0, 1, -1, 0, cx0 + cw, cy0)
    if rot == 180:
        return (-1, 0, 0, -1, cx0 + cw, cy0 + ch)
    if rot == 270:
        return (0, -1, 1, 0, cx0, cy0 + ch)
    return (1, 0, 0, 1, cx0, cy0)


def _fit(text: str, font: str, size: float, width: float) -> float:
    from reportlab.pdfbase import pdfmetrics
    w = pdfmetrics.stringWidth(text, font, size)
    return size if w <= width or w <= 0 else max(5.0, size * width / w * 0.97)


def fill(src: str, places: list[dict]) -> bytes:
    """`src` with every place drawn in: {page, box, text | image (PNG/JPEG bytes) | stamp (bytes)}. Text is set from
    the place's right edge (a Hebrew document reads from there), sized to the place's height and shrunk to its width;
    a signature keeps its proportions, centred on the line; a stamp stands at the place's left, beside the hand."""
    from reportlab.lib.colors import Color
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    by_page: dict[int, list[dict]] = {}
    for p in places:
        if p.get("page") and p.get("box"):
            by_page.setdefault(int(p["page"]), []).append(p)
    ink = Color(0.12, 0.16, 0.09)
    kept = []                                                     # each overlay lives until the file is written
    with pikepdf.open(src) as pdf:
        for n, items in sorted(by_page.items()):
            if n < 1 or n > len(pdf.pages):
                continue
            page = pdf.pages[n - 1]
            media = [float(v) for v in page.mediabox]
            box, rot = _boxes(page)
            W, H = box[2] - box[0], box[3] - box[1]
            if rot in (90, 270):
                W, H = H, W
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(media[2] - media[0], media[3] - media[1]))
            c.translate(-media[0], -media[1])                    # the canvas speaks the page's own user space
            c.transform(*_to_user(rot, box))
            for it in items:
                fx, fy, fw, fh = [float(v) for v in it["box"]]
                x, w, h = fx * W, fw * W, fh * H
                y = H - (fy + fh) * H                             # the place's bottom, from the shown page's bottom
                if it.get("image"):
                    stamp = it.get("stamp")
                    hand_x, hand_w = (x + w * 0.38, w * 0.62) if stamp else (x, w)
                    c.drawImage(ImageReader(io.BytesIO(it["image"])), hand_x, y, hand_w, h, mask="auto",
                                preserveAspectRatio=True, anchor="c")
                    if stamp:
                        c.drawImage(ImageReader(io.BytesIO(stamp)), x, y - h * 0.15, w * 0.4, h * 1.3, mask="auto",
                                    preserveAspectRatio=True, anchor="c")
                    continue
                text = str(it.get("text") or "").strip()
                if not text:
                    continue
                font = _font()
                size = _fit(he(text), font, min(h * 0.7, 13.0), w - 3)
                c.setFont(font, size)
                c.setFillColor(ink)
                c.drawRightString(x + w - 1.5, y + max(1.5, (h - size) * 0.35), he(text))
            c.showPage()
            c.save()
            buf.seek(0)
            overlay = pikepdf.open(buf)
            kept.append(overlay)
            # laid exactly as drawn, in the page's own user space: the drawing already turned itself (_to_user), so the
            # page's /Rotate is NOT inverted again, and nothing is shrunk or grown (the second reader: add_overlay
            # inverts the turn by default — a /Rotate 90 page got its places turned twice and at 71% of their size)
            formx = pdf.copy_foreign(overlay.pages[0].as_form_xobject())
            name = page.add_resource(formx, pikepdf.Name.XObject, prefix="Fill")
            placed = page.calc_form_xobject_placement(formx, name, pikepdf.Rectangle(*media), invert_transformations=False,
                                                      allow_shrink=False, allow_expand=False)
            page.contents_add(b"q\n", prepend=True)               # the page's own drawing keeps its own state
            page.contents_add(b"\nQ\n" + bytes(placed), prepend=False)
        out = io.BytesIO()
        pdf.save(out)
    for o in kept:
        o.close()
    return out.getvalue()
