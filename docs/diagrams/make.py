#!/usr/bin/env python3
"""make.py — the docs' eleven diagrams (DGO-1788) as SVG files in ../public/diagrams/. Each draws what its page's
placeholder `![…](TODO-shot: תרשים <name> …)` asks for, in the page's own words; the palette is the office's
«Olive Grove», light and dark by the reader's preference. The colours are READ from the office's one palette,
platform-base/bina-ui/theme-tokens.css (its light `:root` block and its `prefers-color-scheme:dark` block), at the
moment the files are made: no colour is written here (the owner's rule, G82's spirit, though docs/ is outside its scan).
Run: python3 make.py — writes the files and prints their names. No network, no dependencies."""
from __future__ import annotations

import os
import re
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "diagrams")
TOKENS = os.path.join(HERE, "..", "..", "platform-base", "bina-ui", "theme-tokens.css")

# class → (property, light token, dark token); `none` on the other property where the class draws a line
ROLES = {
    "bg": ("fill", "bg", "bg"), "surface": ("fill", "surface", "surface"), "soft": ("fill", "olive-soft", "olive-soft"),
    "olive": ("fill", "olive", "olive-d"), "oliveline": ("stroke", "olive", "olive-d"), "line": ("stroke", "muted", "muted"),
    "edge": ("stroke", "olive-line", "olive-line"), "ink": ("fill", "ink", "ink"), "muted": ("fill", "muted", "muted"),
    "onolive": ("fill", "olive-ink", "bg"), "block": ("stroke", "plum", "plum-d"), "blocktext": ("fill", "plum", "plum-d"),
    "plum": ("fill", "plum-soft", "plum-soft"), "head": ("fill", "olive", "olive-d"),
}
NO_FILL = {"oliveline", "line", "edge", "block"}


def palette() -> tuple[dict, dict]:
    css = open(TOKENS, encoding="utf-8").read()
    light = re.search(r':root,:root\[data-theme="light"\]\{(.*?)\}', css, re.S)
    dark = re.search(r'@media \(prefers-color-scheme:dark\)\{\s*:root\{(.*?)\}', css, re.S)
    if not (light and dark):
        raise SystemExit(f"{TOKENS}: the light :root block or the dark block was not found — the palette moved")
    read = lambda block: dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\b", block))
    lt = read(light.group(1))
    return lt, {**lt, **read(dark.group(1))}


def style() -> str:
    lt, dk = palette()
    rule = lambda cls, values, full: (f".{cls}{{" + ("fill:none;" if full and cls in NO_FILL else "")
                                      + f"{ROLES[cls][0]}:{values[ROLES[cls][1 if values is lt else 2]]}}}")
    light = "".join(rule(c, lt, True) for c in ROLES)
    dark = "".join(rule(c, dk, False) for c in ROLES)
    return ("<style>\n" + light + "\ntext{font-family:system-ui,\"Segoe UI\",\"Noto Sans Hebrew\",Arial,sans-serif}\n"
            ".mono{font-family:ui-monospace,Menlo,Consolas,monospace}\n"
            "@media (prefers-color-scheme:dark){" + dark + "}\n</style>\n")


STYLE = style() + """<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M0,0 L10,5 L0,10 z" class="muted"/></marker></defs>"""


def t(x, y, s, size=15, cls="ink", weight=400, mono=False, anchor="middle"):
    klass = f"{cls} mono" if mono else cls
    d = "ltr" if mono else "rtl"
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" class="{klass}" text-anchor="{anchor}" '
            f'direction="{d}">{escape(s)}</text>')


def lines(x, y, rows, size=14, cls="ink", gap=19):
    return "".join(t(x, y + i * gap, r, size, cls) for i, r in enumerate(rows))


def rect(x, y, w, h, cls="surface", r=10, stroke="edge"):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" class="{cls}"/>' + (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" class="{stroke}" stroke-width="1.5"/>' if stroke else "")


def arrow(x1, y1, x2, y2, cls="line", dash=False, width=1.8):
    d = ' stroke-dasharray="6 5"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}" stroke-width="{width}"{d} marker-end="url(#arr)"/>'


def link(x1, y1, x2, y2, cls="oliveline", dash=False, width=3):
    d = ' stroke-dasharray="7 6"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}" stroke-width="{width}"{d} stroke-linecap="round"/>'


def tiles(x, y, cols, rows, size=22, gap=7, cls="olive", odd=None):
    out = []
    for r in range(rows):
        for c in range(cols):
            k = "plum" if odd and (r, c) in odd else cls
            out.append(f'<rect x="{x + c * (size + gap)}" y="{y + r * (size + gap)}" width="{size}" height="{size}" '
                       f'rx="5" class="{k}"/>')
    return "".join(out)


def computer(x, y, w, h, label=None):
    """A screen of w×h at (x, y) on a stand; the label goes under the stand."""
    cx = x + w / 2
    s = rect(x, y, w, h, "surface", 12) + rect(cx - 18, y + h, 36, 14, "soft", 2, None) + \
        rect(cx - 55, y + h + 14, 110, 8, "soft", 4, None)
    return s + (t(cx, y + h + 44, label, 15, "ink", 600) if label else "")


def person(cx, cy):
    return f'<circle cx="{cx}" cy="{cy - 26}" r="14" class="head"/>' + \
        f'<path d="M{cx - 26},{cy + 22} q0,-34 26,-34 q26,0 26,34 z" class="head"/>'


def cross(cx, cy, r=10):
    return (f'<line x1="{cx - r}" y1="{cy - r}" x2="{cx + r}" y2="{cy + r}" class="block" stroke-width="3"/>'
            f'<line x1="{cx - r}" y1="{cy + r}" x2="{cx + r}" y2="{cy - r}" class="block" stroke-width="3"/>')


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
            f'<title>{escape(title)}</title>{STYLE}<rect width="{w}" height="{h}" class="bg"/>{body}</svg>\n')


def stack_in_computer(rows, title):
    """The office on one computer: the console above, the computer below with its rows top to bottom."""
    w, h = 760, 540
    b = [t(380, 34, "המרכז", 16, "ink", 700), rect(230, 46, 300, 92, "surface", 12), tiles(262, 62, 8, 2, 24, 8)]
    b.append(arrow(380, 186, 380, 144, "line", True))
    b.append(computer(150, 190, 460, 270, "מחשב אחד"))
    top = 236
    for i, row in enumerate(rows):
        y = top + i * 52
        if isinstance(row, tuple):
            b.append(t(380, y - 8, "ההצהרות", 12, "muted"))
            b.append(rect(395, y, 190, 38, "soft", 8, None) + t(490, y + 25, row[0], 14, "ink", 600, mono=True))
            b.append(rect(175, y, 190, 38, "soft", 8, None) + t(270, y + 25, row[1], 14, "ink", 600, mono=True))
        elif row == "@tiles":
            b.append(tiles(268, y + 4, 8, 1, 24, 8, "olive") + t(380, y + 46, "האפליקציות", 12, "muted"))
        else:
            b.append(rect(255, y, 250, 38, "olive", 8, None) + t(380, y + 25, row, 15, "onolive", 700,
                                                                 mono=row.startswith(".")))
        if i < len(rows) - 1:
            b.append(arrow(380, y + 40, 380, y + 50))
    return svg(w, h, "".join(b), title)


def fragile():
    w, h = 760, 420
    b = [t(380, 36, "אותו מחשב", 16, "ink", 700), computer(250, 60, 260, 170, None), tiles(282, 90, 6, 3, 26, 10)]
    # lid: a laptop closing
    b.append(f'<path d="M80,250 l120,0 l-14,-90 l-92,0 z" class="soft"/><path d="M80,250 l120,0 l-14,-90 l-92,0 z" '
             f'class="edge" stroke-width="1.5"/><rect x="70" y="250" width="140" height="10" rx="4" class="soft"/>')
    b.append(t(140, 300, "שינה", 16, "ink", 700) + t(140, 322, "המכסה נסגר", 13, "muted"))
    # thermometer
    b.append('<rect x="372" y="282" width="16" height="70" rx="8" class="soft"/><circle cx="380" cy="360" r="16" '
             'class="plum"/><rect x="376" y="300" width="8" height="58" rx="4" class="plum"/>')
    b.append(t(380, 398, "חום", 16, "ink", 700))
    # memory bar, full
    b.append(rect(560, 150, 150, 26, "soft", 6, None) + rect(560, 150, 150, 26, "plum", 6, None))
    b.append(t(635, 205, "זיכרון מלא", 16, "ink", 700) + t(635, 227, "100%", 13, "muted", mono=True))
    b.append(arrow(215, 215, 262, 180, "line", True) + arrow(380, 280, 380, 262, "line", True) +
             arrow(555, 165, 515, 150, "line", True))
    return svg(w, h, "".join(b), "אותו מחשב עם שלושה סימנים: מכסה סגור, מדחום, פס זיכרון מלא")


def two_offices(extra, title, h=430, labels=("לשכה", "לשכה")):
    w = 760
    b = [computer(450, 70, 250, 160, labels[0]), tiles(478, 98, 6, 3, 26, 10, odd={(0, 5)}),
         computer(60, 70, 250, 160, labels[1]), tiles(88, 98, 6, 3, 26, 10)]
    b.append(extra)
    return svg(w, h, "".join(b), title)


def link_layer():
    e = link(310, 150, 450, 150) + t(380, 138, "קישור", 15, "ink", 700)
    e += arrow(260, 108, 640, 102, "line", True) + t(380, 60, "אריח מהלשכה השנייה, במרכז של הראשונה", 13, "muted")
    return two_offices(e, "שני מחשבים, לשכה בכל אחד, וקישור ביניהם; במרכז של הראשון אריח מהשני")


def sign_in():
    w, h = 760, 400
    b = [person(670, 190), t(670, 250, "אדם אחד", 15, "ink", 700), arrow(630, 190, 560, 190)]
    b.append(rect(410, 140, 145, 100, "surface", 14) + t(482, 182, "כניסה", 16, "ink", 700) + t(482, 204, "אחת", 16, "ink", 700))
    b.append(arrow(405, 190, 350, 190))
    b.append(rect(60, 70, 285, 120, "surface", 12) + tiles(84, 92, 7, 2, 26, 9) + t(202, 182, "הלשכה", 13, "muted"))
    b.append(rect(60, 210, 285, 120, "surface", 12) + tiles(84, 232, 7, 2, 26, 9, "plum") +
             t(202, 322, "לשכה מקושרת", 13, "muted"))
    return svg(w, h, "".join(b), "אדם אחד, כרטיס כניסה אחד, ומאחוריו כל האריחים של הלשכה, כולל אריחים של לשכה מקושרת")


def door_layer():
    e = link(310, 150, 352, 150) + link(408, 150, 450, 150)
    e += ('<rect x="356" y="112" width="48" height="76" rx="4" class="olive"/>'
          '<circle cx="394" cy="152" r="4" class="onolive"/>') + t(380, 100, "הדלת", 15, "ink", 700)
    e += arrow(380, 192, 380, 280, "line", True) + rect(290, 285, 180, 52, "soft", 10, None)
    e += t(380, 309, "יומן הדלת", 14, "ink", 700) + t(380, 327, "באפליקציית האבטחה", 12, "muted")
    for x in (180, 580):
        e += arrow(x, 400, x, 336, "block", False, 2) + cross(x, 352)
    e += t(380, 400, "מכל כיוון אחר — חסום", 13, "blocktext")
    return two_offices(e, "שתי לשכות ודלת אחת על הקישור ביניהן, עם יומן הדלת באפליקציית האבטחה", 420)


ROLES = [("שולחן העבודה", "המחשב הנייד"), ("בית המלאכה", "לעבודה כבדה"), ("החלון לציבור", "שרת בענן")]


def roles():
    w, h = 760, 470
    b = [computer(300, 170, 160, 100, None), tiles(320, 188, 4, 2, 24, 9), t(380, 314, "המשרד", 17, "ink", 700),
         t(380, 334, "תמיד דלוק — כל הנתונים", 12, "muted")]
    spots = [(600, 40), (600, 300), (60, 170)]
    for (name, sub), (x, y) in zip(ROLES, spots):
        b.append(computer(x, y, 120, 76, None) + t(x + 60, y + 118, name, 15, "ink", 700) + t(x + 60, y + 137, sub, 12, "muted"))
        b.append(link(x + (0 if x > 380 else 120), y + 40, 380 + (80 if x > 380 else -80), 220))
    b.append('<ellipse cx="120" cy="60" rx="64" ry="28" class="soft"/>' + t(120, 65, "האינטרנט", 14, "ink", 700))
    b.append(arrow(120, 90, 120, 164))
    b.append(arrow(182, 68, 300, 176, "block", False, 2) + cross(241, 122))
    b.append(t(380, 455, "האינטרנט נכנס רק דרך החלון לציבור", 13, "muted"))
    return svg(w, h, "".join(b), "ארבעה מחשבים עם שמות התפקיד; המשרד במרכז וקישור מכל מחשב אליו")


def herd():
    w, h = 760, 440
    names = [("מחשב נייד", 590, 40), ("מחשב לעבודה כבדה", 590, 290), ("שרת בענן", 60, 290), ("מחשב נוסף", 60, 40)]
    b = [computer(300, 160, 160, 100, None), tiles(320, 178, 4, 2, 24, 9), t(380, 304, "המשרד", 17, "ink", 700)]
    for name, x, y in names:
        b.append(computer(x, y, 110, 70, None) + t(x + 55, y + 110, name, 14, "ink", 700))
        b.append(link(x + (0 if x > 380 else 110), y + 36, 380 + (80 if x > 380 else -80), 210))
    b.append(link(172, 330, 588, 330, "block", True, 2) + cross(380, 330))
    b.append(t(380, 360, "בין השרת הציבורי לבית המלאכה אין קישור", 13, "blocktext"))
    return svg(w, h, "".join(b), "כמה מחשבים בתפקידים שלהם, מקושרים למשרד, בלי קישור בין השרת הציבורי לבית המלאכה")


def cards(items, title, h=300, icon=None):
    w = 860
    cw, gap = 195, 16
    x0 = w - 20 - cw
    b = []
    for i, (head, rows) in enumerate(items):
        x = x0 - i * (cw + gap)
        b.append(rect(x, 30, cw, h - 60, "surface", 14))
        y = 60
        if icon:
            b.append(icon(x + cw / 2, 52))
            y = 128
        b.append(t(x + cw / 2, y, head, 16, "ink", 700))
        for j, (row, mono) in enumerate(rows):
            b.append(t(x + cw / 2, y + 28 + j * 22, row, 11.5 if mono else 13.5, "muted" if not mono else "ink", 400, mono))
    return svg(w, h, "".join(b), title)


def doors():
    items = [("מה זה DGO", [("מה הלשכה מריצה", False), ("בשבילכם, ומה לא.", False)]),
             ("התחלה", [("איזה מחשב, איזו מיומנות,", False), ("ואיך מתקינים.", False)]),
             ("המושגים", [("המילים של הלשכה,", False), ("כל אחת פעם אחת.", False)]),
             ("כמה מחשבים — לשכה אחת", [("הרעיון,", False), ("שכבה אחרי שכבה.", False)])]
    door_icon = lambda cx, y: (f'<path d="M{cx - 22},{y + 54} l0,-46 q22,-22 44,0 l0,46 z" class="olive"/>'  # noqa: E731
                               f'<circle cx="{cx + 12}" cy="{y + 32}" r="3.5" class="onolive"/>')
    return cards(items, "ארבע דלתות מדף הבית: מה זה DGO, התחלה, המושגים, כמה מחשבים — לשכה אחת", 270, door_icon)


def installers():
    items = [("לינוקס", [("Debian או Ubuntu", False), ("מסוף ו-sudo", False), ("./bbox install debian", True), ("./bbox run", True)]),
             ("macOS", [("macOS 13 ומעלה", False), ("מסוף", False), ("./bbox run", True)]),
             ("Windows", [("Windows עם WSL2", False), ("CMD או PowerShell", False), ("bbox.cmd install windows", True),
                          ("bbox.cmd run", True)]),
             ("אנדרואיד", [("קובץ APK בטיוטה", False), ("לא בחנות", False), ("עלייה ראשונה איטית", False)])]
    screen = lambda cx, y: (f'<rect x="{cx - 34}" y="{y}" width="68" height="44" rx="6" class="soft"/>'  # noqa: E731
                            f'<rect x="{cx - 26}" y="{y + 7}" width="52" height="30" rx="3" class="olive"/>'
                            f'<rect x="{cx - 12}" y="{y + 46}" width="24" height="6" rx="3" class="soft"/>')
    return cards(items, "כרטיס לכל מערכת: לינוקס, macOS, Windows, אנדרואיד — המחשב, המיומנות והפקודה", 290, screen)


def words():
    w, h = 760, 470
    b = [link(140, 52, 620, 52, "oliveline", False, 2), link(140, 52, 140, 74, "oliveline", False, 2),
         link(620, 52, 620, 74, "oliveline", False, 2), t(380, 40, "עדר", 17, "ink", 700)]
    for x, label in ((420, "לשכה"), (40, "לשכה")):
        b.append(rect(x, 80, 300, 300, "surface", 14) + t(x + 150, 108, label, 16, "ink", 700))
        for k, (band, cls) in enumerate((("שכבה 3 — אפליקציות של העסק", "soft"), ("שכבות 1–2 — הבסיס", "soft"),
                                         ("שכבה 0 — המהדר", "olive"))):
            b.append(rect(x + 20, 124 + k * 46, 260, 38, cls, 8, None) +
                     t(x + 150, 148 + k * 46, band, 13, "onolive" if cls == "olive" else "ink", 600))
        b.append(rect(x + 20, 270, 120, 34, "plum", 8, None) + t(x + 80, 292, "app.json", 13, "ink", 600, mono=True))
        b.append(t(x + 80, 322, "ההצהרות", 12, "muted"))
        b.append(person(x + 220, 300) + t(x + 220, 352, "הסוכן", 12, "muted"))
    b.append(link(342, 230, 418, 230) + t(380, 220, "קישור", 14, "ink", 700))
    b.append('<ellipse cx="570" cy="430" rx="80" ry="26" class="soft"/>' + t(570, 435, "שירות חיצוני", 13, "ink", 700))
    b.append(arrow(570, 384, 570, 402) + t(650, 400, "חיבור", 12, "muted"))
    return svg(w, h, "".join(b), "המילים על תמונה אחת: שתי לשכות, אפליקציות בשכבות, הצהרות, סוכן, חיבור, קישור ועדר")


DIAGRAMS = {
    "office-on-one-computer": lambda: stack_in_computer(
        [("app.json לכל אפליקציה", "platform.state.yaml"), "המהדר", ".generated", "המנוע"],
        "מחשב אחד: ההצהרות, המהדר, התיקייה .generated והמנוע, ומעליהם המרכז עם האריחים"),
    "layer-1-one-computer": lambda: stack_in_computer(
        [("app.json", "platform.state.yaml"), "המהדר", "המנוע", "@tiles"],
        "מחשב אחד: ההצהרות, המהדר, המנוע והאפליקציות, ומעליו המרכז עם האריחים"),
    "layer-2-fragile": fragile,
    "layer-3-link": link_layer,
    "layer-4-sign-in": sign_in,
    "layer-5-door": door_layer,
    "layer-6-roles": roles,
    "layer-7-herd": herd,
    "four-doors": doors,
    "install-chooser-cards": installers,
    "words-on-one-picture": words,
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, make in DIAGRAMS.items():
        with open(os.path.join(OUT, f"{name}.svg"), "w", encoding="utf-8") as fh:
            fh.write(make())
        print(f"{name}.svg")
