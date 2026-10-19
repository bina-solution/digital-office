"""Visual document elements drawn directly on the PDF page (fitz primitives).

These are the graphical fixtures that make a document look like a real Israeli
business document — logo mark, the Priority-style "מסמך ממוחשב" seal, a Code128-
looking barcode, and bordered signature boxes. None need to be machine-scannable;
they reproduce the *appearance* of the corpus (see doc_models/SPEC.md).

Colours are deterministic from the supplier name so a given business always looks
the same across its documents.
"""
from __future__ import annotations

import hashlib

import fitz

# a small brand palette (RGB 0..1) — picked to read on white and on tan
_PALETTE = [
    (0.72, 0.11, 0.13), (0.11, 0.35, 0.63), (0.13, 0.52, 0.42),
    (0.55, 0.32, 0.66), (0.85, 0.45, 0.10), (0.20, 0.44, 0.55),
    (0.63, 0.16, 0.38), (0.30, 0.40, 0.20),
]


def brand_color(name: str):
    h = int(hashlib.md5((name or 'x').encode('utf-8')).hexdigest(), 16)
    return _PALETTE[h % len(_PALETTE)]


def draw_logo(page, rect: fitz.Rect, name: str):
    """A simple, believable logo: a rounded brand-coloured tile with a bold glyph,
    over the first Latin/Hebrew initials of the business."""
    col = brand_color(name)
    r = fitz.Rect(rect.x0, rect.y0, rect.x0 + 46, rect.y0 + 40)
    page.draw_rect(r, color=col, fill=col, radius=0.18)
    # a white geometric mark (two chevrons) — abstract, brand-like
    page.draw_line(fitz.Point(r.x0 + 10, r.y1 - 12), fitz.Point(r.x0 + 23, r.y0 + 12),
                   color=(1, 1, 1), width=2.4)
    page.draw_line(fitz.Point(r.x0 + 23, r.y0 + 12), fitz.Point(r.x0 + 36, r.y1 - 12),
                   color=(1, 1, 1), width=2.4)


def draw_computerized_seal(page, center: fitz.Point):
    """The round 'חתימה שומרת מסמך ממוחשב' style seal seen on Priority-issued docs —
    two concentric circles, a check-mark, brand blue."""
    col = (0.11, 0.42, 0.66)
    page.draw_circle(center, 22, color=col, width=1.6)
    page.draw_circle(center, 17, color=col, width=0.8)
    # check mark
    page.draw_line(fitz.Point(center.x - 8, center.y), fitz.Point(center.x - 2, center.y + 7),
                   color=col, width=2.2)
    page.draw_line(fitz.Point(center.x - 2, center.y + 7), fitz.Point(center.x + 9, center.y - 8),
                   color=col, width=2.2)


def draw_barcode(page, rect: fitz.Rect, text: str):
    """A Code128-looking barcode: variable-width black bars derived from a hash of
    the text (purely visual). Fills rect horizontally."""
    seed = hashlib.sha256((text or '0').encode('utf-8')).digest()
    x = rect.x0
    i = 0
    y0, y1 = rect.y0, rect.y1
    # quiet zone
    x += 6
    while x < rect.x1 - 6 and i < len(seed) * 2:
        byte = seed[i // 2]
        nibble = (byte >> 4) if (i % 2 == 0) else (byte & 0xF)
        w = 0.9 + (nibble % 4) * 0.9          # bar width 0.9..3.6pt
        bar = (i % 2 == 0)                     # alternate bar / space
        if bar:
            page.draw_rect(fitz.Rect(x, y0, min(x + w, rect.x1 - 6), y1),
                           color=(0, 0, 0), fill=(0, 0, 0))
        x += w
        i += 1


def draw_signature_box(page, rect: fitz.Rect, arch, css, heading: str,
                       left_label: str, right_label: str):
    """Bordered receiver-signature box (delivery notes / detailed invoices)."""
    page.draw_rect(rect, color=(0.3, 0.3, 0.3), width=0.7)
    page.insert_htmlbox(fitz.Rect(rect.x0 + 6, rect.y0 + 4, rect.x1 - 6, rect.y0 + 22),
                        f"<div dir='rtl' style='font-size:9px'>{heading}</div>",
                        css=css, archive=arch)
    yl = rect.y1 - 20
    page.draw_line(fitz.Point(rect.x0 + 20, yl), fitz.Point(rect.x0 + 150, yl),
                   color=(0.3, 0.3, 0.3), width=0.6)
    page.draw_line(fitz.Point(rect.x1 - 150, yl), fitz.Point(rect.x1 - 20, yl),
                   color=(0.3, 0.3, 0.3), width=0.6)
    page.insert_htmlbox(fitz.Rect(rect.x0 + 20, yl, rect.x0 + 150, yl + 16),
                        f"<div dir='rtl' style='text-align:center;font-size:9px'>{left_label}</div>",
                        css=css, archive=arch)
    page.insert_htmlbox(fitz.Rect(rect.x1 - 150, yl, rect.x1 - 20, yl + 16),
                        f"<div dir='rtl' style='text-align:center;font-size:9px'>{right_label}</div>",
                        css=css, archive=arch)
