#!/usr/bin/env python3
"""line — the business's client documents in ONE house style, from data (DGO-1454).

    bbox my-docs line <data.json> [<out.pdf> | <folder>/] [--html] [--drive "/folder/"]

The owner, meeting exu102 (2026-11-08): «בכללי צריך לייצר קו של מסמכים שאנחנו שולחים ללקוחות». A document is
DATA — the customer, what is offered, the items and their sums, the clauses — and this file is its one design:
the look of the bs101 investment agreement (the dark olive cover with the i0 tile, Noto Serif Hebrew headings,
Noto Sans Hebrew text, the plum callout), written only in Olive Grove's own values
(platform-base/bina-ui/theme-tokens.css; G82 counts any other colour in a Python string). Which pages a document
has is what its data holds:

    cover        the cover page                           (optional)
    offer        what is offered: lead, scope, the price, the next steps, the sign-off  → a QUOTE
    agreement    the parties, the clauses, the signatures                               → a SERVICE AGREEMENT
    both         a quote and the agreement that makes it binding, as one document

SPEC below is the whole shape: every field, its kind, whether it is required. A field it does not name is refused
(a typo is not silently dropped). `example.json` beside this file is a whole document of a made-up customer. A real
customer's data is the business's own file: it lives in the drive beside the PDF it made, never in this repository.

The PDF is rendered by the first renderer that WORKS, in order: WeasyPrint (the ledger's own, in apitools), a
Chromium of this machine (DGO_CHROME, Playwright's chrome-headless-shell, Google Chrome, chromium on the PATH), the
Chromium of the office's browser42 image in a throwaway, named container (what `bbox` gets on the MacBook, whose
hooks run in the engine's guest). `--html` writes the HTML only; `--drive "/folder/"` then puts the PDF into the
office's drive (`bbox drive put`).

Text in the data is text: it is escaped. Three marks are read in it: **bold**, `{_}` a blank line to fill by hand,
`{__}` a wide one. The running header and the page title get the plain text (no marks), CSS-escaped.

Exit 0 written · 1 no renderer worked (the HTML is written; the sentence says why) · 2 refused (nothing written) ·
3 the PDF is written, but the drive did not take it.
"""
import datetime
import glob
import html
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

# The whole shape of a document: field → (kind, required). Kinds: "str", "num" (finite), "int" (above 0),
# "strs" (a text or a list of texts), ("list", kind) (one or more), ("obj", {fields}).
_PRICE = ("obj", {"columns": (("list", "str"), False),
                  "items": (("list", ("obj", {"text": ("str", True), "qty": ("num", True), "unit": ("num", True)})), True),
                  "advance": (("obj", {"text": ("str", True), "amount": ("num", True)}), False),
                  "balance_text": ("str", False), "total_text": ("str", False), "sum_text": ("str", False),
                  "note": ("str", False)})
SPEC = ("obj", {
    "title": ("str", True), "date": ("str", True), "valid_days": ("int", False),
    "seller": (("obj", {"name": ("str", True), "name_en": ("str", False), "site": ("str", False)}), True),
    "customer": (("obj", {"name": ("str", True), "short": ("str", False)}), True),
    "cover": (("obj", {"kicker": ("str", False), "title": ("strs", False), "subtitle": ("str", False)}), False),
    "offer": (("obj", {
        "kicker": ("str", False), "title": ("str", True), "lead": ("str", False), "scope_title": ("str", False),
        "scope": (("list", ("obj", {"title": ("str", False), "text": ("str", True)})), False),
        "price_title": ("str", False), "price": (_PRICE, False),
        "steps": (("obj", {"title": ("str", False), "items": (("list", "str"), True)}), False),
        "sign_off": (("obj", {"greeting": ("str", False), "name": ("str", True), "org": ("str", False)}), False)}), False),
    "agreement": (("obj", {
        "kicker": ("str", False), "title": ("str", True), "made": ("str", False),
        "parties": (("list", ("obj", {"label": ("str", False), "text": ("str", True)})), True),
        "clauses": (("list", ("obj", {"title": ("str", True), "text": ("str", True)})), True),
        "signatures": (("list", ("obj", {"who": ("str", True), "caption": ("str", False),
                                          "fields": (("list", "str"), False)})), False)}), False),
})

# Olive Grove, light — these are the palette's own values (theme-tokens.css), named once here.
P = {"ink": "#1f2a17", "muted": "#6a7068", "line": "#dcdfde", "bg": "#f3f5f7", "white": "#fff",
     "olive": "#56693f", "olive_d": "#475734", "olive_soft": "#e7eae4", "olive_line": "#bfc6b6",
     "lime": "#a9b84c", "lime_d": "#69732e", "lime_soft": "#f3f5e6", "lime_line": "#dee4bb",
     "plum": "#5b3349", "plum_soft": "#e8e2e6",
     # the logo's own three — --mark-tile/-glyph/-accent, and no other colour in a logo (the owner, DGO-1908)
     "mark_tile": "#1b5e4a", "mark_glyph": "#fbfcfc", "mark_accent": "#7ecfad"}

# The i0 mark (digital-office/brand/io/final/logo-1.svg's geometry) on a light tile, as on the bs101 cover.
MARK = (
    '<svg viewBox="53.57 53.57 892.86 892.86" role="img" aria-label="הלשכה הדיגיטלית">'
    '<rect fill="{mark_tile}" x="53.57" y="53.57" width="892.86" height="892.86" rx="196.43"/>'
    '<rect x="267.32" y="276.79" width="71.25" height="71.25" rx="19.24" fill="{mark_accent}"/>'
    '<rect x="267.32" y="419.29" width="71.25" height="285" rx="19.24" fill="{mark_glyph}"/>'
    '<path d="M429.06 276.79H675.59A19.24 19.24 0 0 1 694.82 296.02V685.05A19.24 19.24 0 0 1 675.59 704.29H429.06'
    'A19.24 19.24 0 0 1 409.82 685.05V296.02A19.24 19.24 0 0 1 429.06 276.79ZM500.31 348.04A19.24 19.24 0 0 0 481.07'
    ' 367.27V613.8A19.24 19.24 0 0 0 500.31 633.04H604.34A19.24 19.24 0 0 0 623.57 613.8V367.27A19.24 19.24 0 0 0'
    ' 604.34 348.04Z" fill="{mark_glyph}"/>'
    '<rect x="516.7" y="419.29" width="71.25" height="142.5" rx="19.24" fill="{mark_accent}"/></svg>')

CSS = """
@page {
  size: A4; margin: 22mm 19mm 20mm 19mm;
  @top-right { content: "%(head)s"; font: 8pt "Noto Sans Hebrew"; color: %(muted)s; }
  @top-left { content: "%(seller)s"; font: 600 8pt "Noto Sans Hebrew"; color: %(olive)s; }
  @bottom-right { content: "%(foot)s"; font: 7.5pt "Noto Sans Hebrew"; color: %(muted)s; }
  @bottom-left { content: counter(page); font: 700 8pt "Noto Sans Hebrew"; color: %(lime_d)s; }
}
@page cover {
  margin: 0;
  @top-right { content: none; } @top-left { content: none; }
  @bottom-right { content: none; } @bottom-left { content: none; }
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font-family: "Noto Sans Hebrew", sans-serif; font-size: 10.5pt; line-height: 1.6; color: %(ink)s; }
.cover { page: cover; break-after: page; width: 210mm; height: 297mm; position: relative; overflow: hidden;
  background: linear-gradient(170deg, %(ink)s 0%%, %(ink)s 30%%, %(olive_d)s 100%%); color: %(white)s; padding: 22mm 20mm 0 20mm; }
.brand { display: flex; align-items: center; gap: 4.5mm; }
.brand svg { width: 19mm; height: 19mm; flex: none; }
.brand .names { line-height: 1.35; }
.brand .he { font-weight: 700; font-size: 12.5pt; }
.brand .en { font-size: 9.5pt; color: %(olive_line)s; direction: ltr; text-align: right; }
.cover .kicker { margin-top: 62mm; color: %(lime)s; font-size: 9.5pt; letter-spacing: .14em; font-weight: 600; }
.cover h1 { margin: 4mm 0 0; font-weight: 700; font-size: 33pt; line-height: 1.18; }
.cover .bar { width: 26mm; height: 1.4mm; background: %(lime)s; margin: 12mm 0 7mm; border-radius: .7mm; }
.cover .sub { font-size: 11.5pt; line-height: 1.75; color: %(olive_soft)s; max-width: 150mm; }
.cover .sub b { color: %(white)s; }
.cover .foot { position: absolute; bottom: 14mm; right: 20mm; left: 20mm; border-top: .3mm solid %(olive)s;
  padding-top: 4mm; font-size: 8pt; color: %(olive_line)s; display: flex; justify-content: space-between; }
.cover .foot .site { direction: ltr; }
.section { break-before: page; }
.section.first { break-before: auto; }
.kick { color: %(lime_d)s; font-size: 8.5pt; font-weight: 700; letter-spacing: .3em; margin: 0 0 1mm; }
h2.title { font-family: "Noto Serif Hebrew", serif; color: %(olive_d)s; font-size: 23pt; line-height: 1.2; margin: 0 0 5mm; }
h3 { color: %(olive_d)s; font-size: 12pt; margin: 7mm 0 2.5mm; }
p { margin: 0 0 3mm; }
.lead { font-size: 11.5pt; line-height: 1.7; }
ol.scope { margin: 0; padding: 0 5mm 0 0; }
ol.scope li { margin: 0 0 2.4mm; padding-right: 1.5mm; }
ol.scope li::marker { color: %(lime_d)s; font-weight: 700; }
b { font-weight: 700; }
table.price { width: 100%%; border-collapse: collapse; margin: 1mm 0 2.5mm; font-size: 10pt; }
table.price th { background: %(olive_d)s; color: %(white)s; font-weight: 600; text-align: right; padding: 2.2mm 3mm; }
table.price th.n, table.price td.n { text-align: left; white-space: nowrap; }
table.price td { padding: 2.2mm 3mm; border-bottom: .3mm solid %(line)s; }
table.price tr.sum td { font-weight: 600; }
table.price tr.paid td { color: %(olive)s; }
table.price tr.total td { background: %(lime_soft)s; font-weight: 700; border-bottom: .5mm solid %(lime)s; }
.note { font-size: 9pt; color: %(muted)s; }
.callout { background: %(plum_soft)s; border-right: 1.4mm solid %(plum)s; padding: 4mm 5mm 3mm; margin: 6mm 0 5mm; break-inside: avoid; }
.callout .h { font-weight: 700; color: %(plum)s; margin-bottom: 1.5mm; }
.callout ul { margin: 0; padding: 0 4.5mm 0 0; }
.callout li { margin: 0 0 1.4mm; }
.sign-off { margin-top: 6mm; }
.sign-off .name { font-weight: 700; }
.blank { display: inline-block; min-width: 30mm; border-bottom: .3mm solid %(olive_line)s; height: 1em; vertical-align: -.15em; }
.blank.w { min-width: 46mm; }
.parties { width: 100%%; border-collapse: collapse; margin: 3mm 0 5mm; font-size: 10pt; }
.parties td { padding: 3mm; vertical-align: top; background: %(bg)s; border-bottom: 1.2mm solid %(white)s; line-height: 2.05; }
.parties td.k { width: 15mm; font-weight: 700; color: %(olive_d)s; }
ol.clauses { counter-reset: c; list-style: none; margin: 0; padding: 0; }
ol.clauses > li { counter-increment: c; position: relative; padding-right: 9mm; margin: 0 0 2.6mm; break-inside: avoid; }
ol.clauses > li::before { content: counter(c) "."; position: absolute; right: 0; top: 0; color: %(lime_d)s; font-weight: 700; }
ol.clauses > li > b:first-child { color: %(olive_d)s; }
.signs { display: flex; gap: 10mm; margin-top: 9mm; break-inside: avoid; }
.sign { flex: 1; border-top: .5mm solid %(olive_d)s; padding-top: 3mm; font-size: 9.5pt; line-height: 2.2; }
.sign .who { font-weight: 700; color: %(olive_d)s; font-size: 10.5pt; line-height: 1.6; margin-bottom: 1mm; }
.sign .line { margin-top: 9mm; border-bottom: .3mm solid %(olive_line)s; }
.sign .cap { color: %(muted)s; font-size: 8.5pt; line-height: 1.6; }
"""


class Refused(Exception):
    """The data cannot make a document; the sentence says which field and why."""


def check(v, spec, where: str) -> None:
    """The data against SPEC: every kind, every required field, no field SPEC does not name."""
    if spec == "str":
        if not isinstance(v, str) or not v.strip():
            raise Refused(f"{where}: a text, not {v!r}"[:200])
    elif spec == "num":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise Refused(f"{where}: a number, not {v!r}"[:200])
    elif spec == "int":
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise Refused(f"{where}: a whole number above 0, not {v!r}"[:200])
    elif spec == "strs":
        if isinstance(v, str):
            check(v, "str", where)
        else:
            check(v, ("list", "str"), where)
    elif spec[0] == "list":
        if not isinstance(v, list) or not v:
            raise Refused(f"{where}: a list of one or more, not {type(v).__name__}")
        for i, x in enumerate(v):
            check(x, spec[1], f"{where}[{i}]")
    else:
        fields = spec[1]
        if not isinstance(v, dict):
            raise Refused(f"{where}: an object, not {type(v).__name__}")
        unknown = sorted(set(v) - set(fields))
        if unknown:
            raise Refused(f"{where}: unknown fields {unknown} — the fields are {sorted(fields)}")
        for key, (kind, required) in fields.items():
            if v.get(key) is None:
                if required:
                    raise Refused(f"{where}.{key}: missing")
                continue
            check(v[key], kind, f"{where}.{key}")


def plain(s) -> str:
    """The text without its marks — for the running header and the page's title, where no markup goes."""
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", str(s))
    return out.replace("{__}", "______").replace("{_}", "____")


def text(s) -> str:
    """Data text → HTML: escaped first, then the three marks (**bold**, {_}, {__})."""
    out = html.escape(str(s if s is not None else ""), quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    return out.replace("{__}", '<span class="blank w"></span>').replace("{_}", '<span class="blank"></span>')


def css_string(s) -> str:
    """The plain text as the inside of a CSS `content: "…"` in a <style> element. A quote or a backslash would end
    the string, any line break (\\n \\r \\f) ends it too, and `<` could end the <style> element itself: each is a
    CSS escape (a line break, a space), so nothing in the data can leave the string."""
    out = []
    for ch in plain(s):
        if ch in "\r\n\f\t\v":
            out.append(" ")
        elif ch in '"\\<>&' or ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append("\\%x " % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def money(v: float) -> str:
    """10000 → «10,000 ₪»; a negative one keeps its sign beside its digits in a right-to-left line."""
    digits = f"{abs(v):,.0f}" if v == int(v) else f"{abs(v):,.2f}"
    return f'<bdi dir="ltr">−{digits}</bdi> ₪' if v < 0 else f"{digits} ₪"


def quantity(q: float) -> str:
    """40 → «40», 1500000 → «1,500,000», 2.5 → «2.5» — never an exponent."""
    return f"{int(q):,}" if q == int(q) else f"{q:,.2f}".rstrip("0").rstrip(".")


def day(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso)
    except ValueError:
        raise Refused(f"date: YYYY-MM-DD, not {iso!r}")
    return f"{d.day} ב{MONTHS[d.month - 1]} {d.year}"


def cover_page(doc: dict, when: str) -> str:
    c, s, cu = doc["cover"], doc["seller"], doc["customer"]
    lines = c.get("title") or doc["title"]
    title = "<br>".join(text(x) for x in (lines if isinstance(lines, list) else [lines]))
    valid = f" · בתוקף {doc['valid_days']} יום" if doc.get("valid_days") else ""
    site = f'<span class="site">{text(s["site"])}</span>' if s.get("site") else "<span></span>"
    en = f'<div class="en">{text(s["name_en"])}</div>' if s.get("name_en") else ""
    sub = f'<div class="sub">{text(c["subtitle"])}</div>' if c.get("subtitle") else ""
    return f"""
<section class="cover">
  <div class="brand">{MARK.format(**P)}
    <div class="names"><div class="he">{text(s["name"])}</div>{en}</div>
  </div>
  <div class="kicker">{text(c.get("kicker") or doc["title"])}</div>
  <h1>{title}</h1>
  <div class="bar"></div>
  {sub}
  <div class="foot"><span>הוכן עבור {text(cu.get("short") or cu["name"])} · {when}{valid}</span>{site}</div>
</section>"""


def price_table(pr: dict) -> str:
    cols = pr.get("columns") or ["פריט", "כמות", "מחיר", "סכום"]
    if len(cols) != 4:
        raise Refused("offer.price.columns: four names (item, quantity, unit price, sum)")
    rows, total = [], 0.0
    for i, it in enumerate(pr["items"]):
        qty, unit = float(it["qty"]), float(it["unit"])
        if qty <= 0 or unit < 0:
            raise Refused(f"offer.price.items[{i}]: a quantity above 0 and a price of 0 or more")
        total += qty * unit
        rows.append(f'<tr><td>{text(it["text"])}</td><td class="n">{quantity(qty)}</td><td class="n">{money(unit)}</td>'
                    f'<td class="n">{money(qty * unit)}</td></tr>')
    if not math.isfinite(total):
        raise Refused("offer.price.items: the sum is not a finite number")
    adv = pr.get("advance")
    if adv:
        paid = float(adv["amount"])
        if not 0 < paid <= total:
            raise Refused(f"offer.price.advance.amount: above 0 and at most the total ({quantity(total)})")
        if len(rows) > 1:   # one item IS its total; with more, the total is said before the advance comes off it
            rows.append(f'<tr class="sum"><td>{text(pr.get("sum_text") or "סה״כ")}</td><td class="n"></td>'
                        f'<td class="n"></td><td class="n">{money(total)}</td></tr>')
        rows.append(f'<tr class="paid"><td>{text(adv["text"])}</td><td class="n"></td>'
                    f'<td class="n"></td><td class="n">{money(-paid)}</td></tr>')
        rows.append(f'<tr class="total"><td>{text(pr.get("balance_text") or "יתרה לתשלום")}</td><td class="n"></td>'
                    f'<td class="n"></td><td class="n">{money(total - paid)}</td></tr>')
    else:
        rows.append(f'<tr class="total"><td>{text(pr.get("total_text") or "סה״כ")}</td><td class="n"></td>'
                    f'<td class="n"></td><td class="n">{money(total)}</td></tr>')
    head = "".join(('<th class="n">' if i else "<th>") + text(c) + "</th>" for i, c in enumerate(cols))
    note = f'<p class="note">{text(pr["note"])}</p>' if pr.get("note") else ""
    return f'<table class="price"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>{note}'


def offer_page(doc: dict, when: str, first: bool) -> str:
    o = doc["offer"]
    scope = ""
    if o.get("scope"):
        items = ""
        for x in o["scope"]:
            lead = "<b>" + text(x["title"]) + "</b> " if x.get("title") else ""
            items += "<li>" + lead + text(x["text"]) + "</li>"
        scope = f'<h3>{text(o.get("scope_title") or "מה כלול")}</h3><ol class="scope">{items}</ol>'
    price = f'<h3>{text(o.get("price_title") or "המחיר")}</h3>{price_table(o["price"])}' if o.get("price") else ""
    # Without a cover, the quote itself says how long it stands (the cover's foot says it otherwise).
    valid = (f'<p class="note">ההצעה בתוקף {doc["valid_days"]} יום מיום {when}.</p>'
             if doc.get("valid_days") and not doc.get("cover") else "")
    steps = ""
    if o.get("steps"):
        st = o["steps"]
        steps = (f'<div class="callout"><div class="h">{text(st.get("title") or "איך מתקדמים")}</div>'
                 f'<ul>{"".join("<li>" + text(x) + "</li>" for x in st["items"])}</ul></div>')
    so, sign = o.get("sign_off"), ""
    if so:
        org = "<br>" + text(so["org"]) if so.get("org") else ""
        sign = (f'<div class="sign-off">{text(so.get("greeting") or "בברכה,")}<br>'
                f'<span class="name">{text(so["name"])}</span>{org}</div>')
    lead = f'<p class="lead">{text(o["lead"])}</p>' if o.get("lead") else ""
    return f"""
<section class="section{' first' if first else ''}">
  <div class="kick">{text(o.get("kicker") or "ההצעה")}</div>
  <h2 class="title">{text(o["title"])}</h2>
  {lead}
  {scope}{price}{valid}{steps}{sign}
</section>"""


def agreement_page(doc: dict, first: bool) -> str:
    a = doc["agreement"]
    made = f'<p>{text(a["made"])}</p>' if a.get("made") else ""
    parties = "".join(f'<tr><td class="k">{text(p.get("label"))}</td><td>{text(p["text"])}</td></tr>'
                      for p in a["parties"])
    clauses = "".join(f'<li><b>{text(c["title"])}</b> {text(c["text"])}</li>' for c in a["clauses"])
    signs = ""
    for s in a.get("signatures") or []:
        fields = "<br>".join(text(f) + ': <span class="blank"></span>' for f in s.get("fields") or [])
        signs += (f'<div class="sign"><div class="who">{text(s["who"])}</div><div class="line"></div>'
                  f'<div class="cap">{text(s.get("caption") or "חתימה")}</div>{fields}</div>')
    signs = f'<div class="signs">{signs}</div>' if signs else ""
    return f"""
<section class="section{' first' if first else ''}">
  <div class="kick">{text(a.get("kicker") or "ההסכם")}</div>
  <h2 class="title">{text(a["title"])}</h2>
  {made}
  <table class="parties">{parties}</table>
  <ol class="clauses">{clauses}</ol>
  {signs}
</section>"""


def build(doc) -> str:
    """The data → the whole HTML page. Refused (nothing built) when the data cannot make a document."""
    check(doc, SPEC, "document")
    if not (doc.get("offer") or doc.get("agreement")):
        raise Refused("a document has an offer (a quote), an agreement, or both")
    when = day(doc["date"])
    cu, seller = doc["customer"], doc["seller"]["name"]
    vals = dict(P, head=css_string(f'{doc["title"]} · {cu.get("short") or cu["name"]}'),
                seller=css_string(seller), foot=css_string(f"{seller} · {when}"))
    body = cover_page(doc, when) if doc.get("cover") else ""
    first = not doc.get("cover")
    if doc.get("offer"):
        body += offer_page(doc, when, first)
        first = False
    if doc.get("agreement"):
        body += agreement_page(doc, first)
    title = html.escape(plain(f'{doc["title"]} · {cu["name"]} · {seller}'))
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Hebrew:wght@400;600;700&family=Noto+Serif+Hebrew:wght@700&display=block" rel="stylesheet">
<style>{CSS % vals}</style>
</head>
<body>{body}
</body>
</html>
"""


PRINT = ["--headless", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=20000",
         "--run-all-compositor-stages-before-draw"]


def chromes() -> list:
    """Every Chromium this machine has, in the order they are tried."""
    home, found = os.path.expanduser("~"), []
    if os.environ.get("DGO_CHROME"):
        found.append(os.environ["DGO_CHROME"])
    for pattern in (f"{home}/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell",
                    f"{home}/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell",
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        found += sorted(glob.glob(pattern), reverse=True)[:1]
    for name in ("chrome-headless-shell", "chromium", "chromium-browser", "google-chrome"):
        if shutil.which(name):
            found.append(shutil.which(name))
    out = []
    for exe in found:
        if os.path.exists(exe) and exe not in out:
            out.append(exe)
    return out


def browser_image() -> str:
    """The office's own browser image — browser42 ships Debian's chromium — when this machine has docker and it."""
    if not shutil.which("docker"):
        return ""
    try:
        refs = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                              capture_output=True, text=True, timeout=30).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return ""
    for ref in refs:
        repo, _, tag = ref.rpartition(":")
        if repo.endswith("browser42-browser") and tag == "latest":
            return ref
    return ""


def _printed(run, pdf: str, who: str) -> None:
    if run.returncode != 0 or not os.path.exists(pdf) or os.path.getsize(pdf) == 0:
        raise RuntimeError(f"{who} made no PDF (exit {run.returncode}): {run.stderr.strip()[-200:]}")


def print_local(exe: str, page: str, out: str) -> None:
    # beside the output, not in /tmp: a snap chromium cannot read /tmp, and the folder is this user's alone
    tmp = tempfile.mkdtemp(prefix=".line-", dir=os.path.dirname(out))
    try:
        src, pdf = os.path.join(tmp, "doc.html"), os.path.join(tmp, "doc.pdf")
        with open(src, "w", encoding="utf-8") as f:
            f.write(page)
        run = subprocess.run([exe] + PRINT + [f"--print-to-pdf={pdf}", pathlib.Path(src).as_uri()],
                             capture_output=True, text=True, timeout=180)
        _printed(run, pdf, os.path.basename(exe))
        shutil.copyfile(pdf, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def print_in_image(image: str, page: str, out: str) -> None:
    tmp = tempfile.mkdtemp(prefix="line-")
    name = f"line-{uuid.uuid4().hex[:12]}"   # named, so a timeout can remove it: killing the client leaves it running
    try:
        with open(os.path.join(tmp, "doc.html"), "w", encoding="utf-8") as f:
            f.write(page)
        cmd = (["docker", "run", "--rm", "--init", "--name", name, "-v", f"{tmp}:/work", "--entrypoint", "chromium",
                image, "--no-sandbox"] + PRINT + ["--print-to-pdf=/work/doc.pdf", "file:///work/doc.html"])
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
            raise RuntimeError(f"chromium in {image} did not finish in 300 s (container {name} removed)")
        _printed(run, os.path.join(tmp, "doc.pdf"), f"chromium in {image}")
        shutil.copyfile(os.path.join(tmp, "doc.pdf"), out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render(page: str, out: str):
    """The page → PDF at `out` by the first renderer that works: (who made it, '') or ('', why none did)."""
    tried = []
    try:
        import weasyprint  # the ledger's own renderer (apitools)
    except Exception as e:  # ImportError — or OSError, when it is installed and its libraries are not
        weasyprint = None
        if not isinstance(e, ImportError):
            tried.append(f"weasyprint: {e}"[:200])
    if weasyprint is not None:
        try:
            weasyprint.HTML(string=page, base_url=HERE).write_pdf(out)
            return "weasyprint", ""
        except Exception as e:
            tried.append(f"weasyprint: {e}"[:200])
    for exe in chromes():
        try:
            print_local(exe, page, out)
            return os.path.basename(exe), ""
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            tried.append(str(e))
    image = browser_image()
    if image:
        try:
            print_in_image(image, page, out)
            return f"chromium in {image}", ""
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            tried.append(str(e))
    return "", ("; ".join(tried) if tried else "no WeasyPrint, no Chromium, no browser42 image (DGO_CHROME names one)")


USAGE = 'line: bbox my-docs line <data.json> [<out.pdf> | <folder>/] [--html] [--drive "/folder/"]'


def main(argv) -> int:
    args, html_only, drive = [], False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--html":
            html_only = True
        elif a == "--drive" or a.startswith("--drive="):
            drive = a.split("=", 1)[1] if "=" in a else (argv[i + 1] if i + 1 < len(argv) else "")
            i += 0 if "=" in a else 1
            if not drive.strip():
                print(f"line: --drive needs a folder of the drive\n{USAGE}", file=sys.stderr)
                return 2
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a.startswith("-"):
            print(f"line: unknown option {a}\n{USAGE}", file=sys.stderr)
            return 2
        else:
            args.append(a)
        i += 1
    if not 1 <= len(args) <= 2:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as f:
            doc = json.load(f)
        page = build(doc)
    except (OSError, ValueError) as e:
        print(f"line: {args[0]}: {e}", file=sys.stderr)
        return 2
    except Refused as e:
        print(f"line: refused — {e}", file=sys.stderr)
        return 2
    stem = os.path.splitext(os.path.basename(args[0]))[0]
    out = args[1] if len(args) > 1 else os.path.join(REPO, "ci-artifacts", "my-docs-line", "")
    if out.endswith(os.sep) or os.path.isdir(out):
        out = os.path.join(out, stem + ".pdf")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    page_path = os.path.splitext(out)[0] + ".html"
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(page)
    if html_only:
        print(f"line: html {page_path}")
        return 0
    made, why = render(page, out)
    if not made:
        print(f"line: no renderer worked — {why} — the page is at {page_path}", file=sys.stderr)
        return 1
    print(f"line: pdf {out} ({os.path.getsize(out)} bytes, {made})")
    if drive:
        put = subprocess.run([os.path.join(REPO, "bbox"), "drive", "put", out, drive], capture_output=True, text=True)
        print((put.stdout + put.stderr).strip())
        if put.returncode != 0:
            print("line: the PDF is written, but the drive did not take it", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
