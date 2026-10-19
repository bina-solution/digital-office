"""Render INDOX doc models into realistic Hebrew business documents (PDF/PNG).

Layout reproduces the demo-corpus conventions per type (see ../doc_models/SPEC.md,
studied visually 2026-07-08): RTL, logo + supplier header, customer/date bands with
the canonical KW anchors, row-numbered lines tables (zebra for the white invoice
family, per-line תעודה/הזמנה/הזמנתכם columns for the tan Priority family), a bordered
totals ladder, barcodes, the מקור/מסמך-ממוחשב chrome, legal text and signature boxes.

Values sit adjacent to their label anchors (label: value on one line, or value in a
right-aligned cell) so downstream keyword extraction still resolves them.
"""
from __future__ import annotations

import os

import fitz  # pymupdf

from src.utils.logging_config import get_logger

from . import elements as el

logger = get_logger('apitools.doc_gen')

FONT_DIRS = ['/usr/share/fonts/truetype/dejavu', r'C:\Windows\Fonts']
_FONT_DIR = next((d for d in FONT_DIRS if os.path.exists(os.path.join(d, 'DejaVuSans.ttf'))), None)
_FONT_FILE = 'DejaVuSans.ttf' if _FONT_DIR else 'arial.ttf'
if _FONT_DIR is None:
    _FONT_DIR = next((d for d in FONT_DIRS if os.path.exists(d)), '.')

CSS = (
    "@font-face {font-family: heb; src: url(%s);}"
    "* {font-family: heb; color: #111;}"
    "body {font-size: 11px;}"
    ".t {font-size: 15px; font-weight: bold;}"
    ".s {font-size: 9px; color: #333;}"
    ".b {font-weight: bold;}"
    ".u {text-decoration: underline;}"
    "table {width: 100%%; border-collapse: collapse;}"
    "th {border-bottom: 1.2px solid #333; padding: 3px 6px; font-weight: bold; text-align: right; font-size: 10px;}"
    "td {padding: 3px 6px; text-align: right; font-size: 10px;}"
    ".zebra tr:nth-child(even) td {background: #f0f0f0;}"
) % _FONT_FILE

A4 = (595, 842)
MARGIN = 36
TAN = (0.99, 0.96, 0.86)


def _money(v):
    return f'{v:,.2f}'


class _Page:
    """Vertical flow of html sections on A4 pages, plus the compliance chrome:
    a מקור/העתק/טיוטה stamp on every page and the Instruction-36 output footer."""

    def __init__(self, label='', footer_issuer='', footer_kind='', bg=None):
        self.doc = fitz.open()
        self.arch = fitz.Archive(_FONT_DIR)
        self.label = label
        self.footer_issuer = footer_issuer
        self.footer_kind = footer_kind
        self.bg = bg
        self._new_page()

    def _new_page(self):
        self.page = self.doc.new_page(width=A4[0], height=A4[1])
        if self.bg:
            self.page.draw_rect(fitz.Rect(0, 0, A4[0], A4[1]), color=self.bg, fill=self.bg)
        self.y = MARGIN
        if self.label:   # מקור exactly once / העתק / טיוטה — top-left stamp on EVERY page
            self.page.insert_htmlbox(fitz.Rect(MARGIN, 8, MARGIN + 160, 30),
                                     f"<div style='font-weight:bold;font-size:13px'>{self.label}</div>",
                                     css=CSS, archive=self.arch)

    def _footers(self):
        import time as _t
        n = len(self.doc)
        for i, page in enumerate(self.doc):
            foot = (f"{self.footer_issuer} | {self.footer_kind} | "
                    f"הופק: {_t.strftime('%d/%m/%Y %H:%M')} | עמוד {i + 1} מתוך {n}"
                    + (" | *** סוף פלט ***" if i == n - 1 else ""))
            page.insert_htmlbox(fitz.Rect(MARGIN, A4[1] - 26, A4[0] - MARGIN, A4[1] - 6),
                                f"<div dir='rtl' class='s' style='text-align:center'>{foot}</div>",
                                css=CSS, archive=self.arch)

    def block(self, html, height, css_extra=''):
        if self.y + height > A4[1] - MARGIN:
            self._new_page()
        rect = fitz.Rect(MARGIN, self.y, A4[0] - MARGIN, self.y + height)
        self.page.insert_htmlbox(rect, f"<div dir='rtl'>{html}</div>",
                                 css=CSS + css_extra, archive=self.arch)
        self.y += height

    def barcode(self, text, h=34):
        r = fitz.Rect(A4[0] / 2 - 150, self.y, A4[0] / 2 + 150, self.y + h)
        el.draw_barcode(self.page, r, text)
        self.y += h + 2

    def hrule(self):
        self.page.draw_line(fitz.Point(MARGIN, self.y), fitz.Point(A4[0] - MARGIN, self.y),
                            color=(0.2, 0.2, 0.2), width=0.8)
        self.y += 3

    def gap(self, h=8):
        self.y += h

    def pdf_bytes(self) -> bytes:
        self._footers()
        return self.doc.tobytes(garbage=4, deflate=True)

    def png_bytes(self, dpi=200) -> bytes:
        self._footers()
        pix = self.doc[0].get_pixmap(dpi=dpi)
        return pix.tobytes('png')


def _header(p, sup, logo=True):
    """Logo (top-left) + supplier block (top-right) — the corpus header layout."""
    top = p.y
    if logo:
        el.draw_logo(p.page, fitz.Rect(MARGIN, top, MARGIN + 46, top + 40), sup.name)
        p.page.insert_htmlbox(fitz.Rect(MARGIN, top + 42, MARGIN + 160, top + 56),
                              f"<div class='s'>{sup.email}</div>" if sup.email else "",
                              css=CSS, archive=p.arch)
    # tax designation per business type — an עוסק פטור must be labelled as such and
    # does not carry a VAT file (they are not registered for / do not charge VAT)
    _status = getattr(sup, 'tax_status', 'murshe')
    _tax_label = {'patur': 'עוסק פטור', 'company': 'ח.פ', 'murshe': 'עוסק מורשה'}.get(_status, 'עוסק מורשה')
    rows = [f"<div class='t'>{sup.name}</div>",
            f"<div class='s'>{sup.street}, {sup.city}</div>"]
    _contact = ', '.join(p for p in [f"טלפון: {sup.phone}" if sup.phone else '',
                                     f"פקס: {sup.fax}" if sup.fax else ''] if p)
    if _contact:
        rows.append(f"<div class='s'>{_contact}</div>")
    rows.append(f"<div class='s'>{_tax_label}: {sup.company_id}</div>")
    if _status != 'patur':
        rows.append(f"<div class='s'>מס' תיק במע\"מ: {sup.vat_file_no or sup.company_id}</div>")
    if sup.deduction_file_no:
        rows.append(f"<div class='s'>מס. תיק ניכויים: {sup.deduction_file_no}</div>")
    h = 14 * len(rows) + 6
    p.page.insert_htmlbox(fitz.Rect(A4[0] / 2, top, A4[0] - MARGIN, top + h),
                          "<div dir='rtl' style='text-align:right'>" + ''.join(rows) + "</div>",
                          css=CSS, archive=p.arch)
    p.y = top + max(h, 60)


def _customer_band(p, cust, date_lines, extra_right=''):
    """לכבוד block (right) + date block (left). date_lines = [(label,value), ...]."""
    left = ''.join(f"<div class='b'>{lbl}: {val}</div>" for lbl, val in date_lines)
    # only render fields that are actually filled — empty "טלפון:" / "מס' חברה:" labels
    # read as unfinished; morning omits them too
    rows = [f"<div class='b'>לכבוד:</div><div>{cust.name}</div>"]
    addr = ', '.join(x for x in [f"{cust.street} {cust.zip}".strip(), cust.city] if x and x.strip())
    if addr:
        rows.append(f"<div>{addr}</div>")
    if cust.phone:
        rows.append(f"<div>טלפון: {cust.phone}</div>")
    if cust.company_id:
        rows.append(f"<div>מס' חברה: {cust.company_id}</div>")
    right = ''.join(rows) + extra_right
    n = max(right.count('<div'), len(date_lines) + 1)
    p.block(f"<table><tr><td style='width:52%;vertical-align:top'>{right}</td>"
            f"<td style='width:48%;vertical-align:top'>{left}</td></tr></table>", 16 * n + 10)


def _lines_table(p, headers, rows, zebra=False, row_numbers=True):
    if row_numbers:
        headers = headers + ['#']
        rows = [r + [str(i + 1)] for i, r in enumerate(rows)]
    cls = " class='zebra'" if zebra else ""
    th = ''.join(f'<th>{h}</th>' for h in headers)
    trs = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    p.block(f"<table{cls}><tr>{th}</tr>{trs}</table>", 28 + 20 * len(rows))


def _totals_ladder(p, m):
    """Bordered totals block, bottom-left (corpus convention): label:value rows."""
    rows = [('מחיר כולל', m.subtotal)]
    if m.discount_pct:
        rows += [(f'הנחה כללית ({m.discount_pct:.2f}%)', m.discount),
                 ('מחיר אחרי הנחה', m.after_discount)]
    rows += [(f'מע"מ ({m.vat_pct:.2f}%)', m.vat), ('סה"כ לתשלום', m.total_due)]
    # single-cell "label: value" per row (bordered) — keeps value adjacent to its
    # anchor in reading order so keyword extraction resolves (סה"כ לתשלום: <amount>)
    inner = ''.join(
        f"<tr><td style='border:0.5px solid #999'>"
        f"<span>{lbl}:</span> <span class='b'>{_money(val)}</span></td></tr>"
        for lbl, val in rows)
    p.block(f"<table style='width:52%'>{inner}</table>", 22 * len(rows) + 6)


def render_invoice(m, label='') -> _Page:
    bg = TAN if getattr(m, 'style', 'white') == 'tan' else None
    p = _Page(label=label, footer_issuer=m.supplier.name, footer_kind='חשבונית מס', bg=bg)
    _header(p, m.supplier, logo=getattr(m, 'has_logo', True))
    p.gap(4)
    dl = [('תאריך חשבונית', m.doc_date), ('מספר תעודה', m.doc_id)]
    if m.details_note:
        dl.append(('פרטים', m.details_note))
    _customer_band(p, m.customer, dl)
    p.gap(2)
    if getattr(m, 'has_seal', False):
        el.draw_computerized_seal(p.page, fitz.Point(MARGIN + 40, p.y + 8))
    kind = 'חשבונית מס מרכזת' if m.centralized else 'חשבונית מס'
    p.block(f"<div class='t u' style='text-align:center'>{kind} {m.doc_id} - מקור (מסמך ממוחשב)</div>", 26)
    if getattr(m, 'has_barcode', False):
        p.barcode(m.doc_id)
    p.gap(4)
    per_line = getattr(m, 'refs_mode', 'block') == 'per_line'
    if per_line:
        headers = ['תעודה', 'הזמנה', 'הזמנתכם', 'תאור מוצר', 'כמות', 'מחיר ליחידה', 'סכום']
        rows = [[l.shipment_ref, l.order_ref, l.customer_order_ref, l.description,
                 f'{l.qty:g}', _money(l.unit_price), _money(l.total)] for l in m.lines]
    else:
        headers = ['מק"ט', 'תאור מוצר', 'כמות', 'מחיר ליחידה', 'סכום']
        rows = [[l.sku, l.description, f'{l.qty:g}', _money(l.unit_price), _money(l.total)]
                for l in m.lines]
    _lines_table(p, headers, rows, zebra=(getattr(m, 'style', 'white') == 'white'))
    p.gap(6)
    # totals ladder (left) + doc-level refs / allocation (right) side by side
    y_before = p.y
    _totals_ladder(p, m)
    right = []
    if m.payment_due:
        right.append(f"לתשלום עד: {m.payment_due}")
    right.append(f"תנאי תשלום: {m.payment_terms}")
    if not per_line:
        if m.doc_shipment_ref: right.append(f"תעודה: {m.doc_shipment_ref}")
        if m.doc_order_ref: right.append(f"הזמנה: {m.doc_order_ref}")
        if m.doc_customer_order_ref: right.append(f"הזמנתכם: {m.doc_customer_order_ref}")
    right.append(f"מס. לקוח: {m.customer.customer_no or ''}")
    right.append(f"תיק מע\"מ לקוח: {m.customer.company_id}")
    if getattr(m, 'allocation_number', ''):
        d9 = ''.join(c for c in m.allocation_number if c.isdigit())[-9:]
        right.append(f"מספר הקצאה: <span class='b'>{d9}</span>")
    if m.agent:
        right.append(f"סוכן: {m.agent}")
    right_h = 16 * len(right) + 6
    p.page.insert_htmlbox(fitz.Rect(A4[0] / 2 + 10, y_before, A4[0] - MARGIN, y_before + right_h),
                          "<div dir='rtl' style='text-align:right;font-size:10px'>"
                          + '<br/>'.join(right) + "</div>", css=CSS, archive=p.arch)
    # advance past whichever column (totals ladder vs ref block) is taller
    p.y = max(p.y, y_before + right_h)
    p.gap(6)
    # full-width bold grand total on its own line (corpus 'סה"כ נותר לתשלום') — the
    # side-by-side ladder/refs blocks share a line in OCR order, so give the payable a
    # clean, unambiguous anchor of its own
    p.block(f"<div class='t'>סה\"כ נותר לתשלום: {_money(m.total_due)} ₪</div>", 24)
    p.gap(4)
    if m.bank:
        p.block(f"<div class='b'>פרטי חשבון בנק להעברה:</div>"
                f"<div>{m.bank.bank}, סניף - {m.bank.branch}, חשבון - {m.bank.account}</div>", 34)
    p.block("<div class='s'>הריני מאשר את קבלת הטובין לאחר בדיקה. הטובין נמצאו תקינים ולשביעות רצוני המלאה.<br/>"
            "הסחורה הינה רכוש הספק עד למועד פרעון מלא של ערך הטובין.</div>", 34)
    if m.printed_note:
        p.block(f"<div class='b' style='text-align:center'>{m.printed_note}</div>", 18)
    return p


def render_order(m, label='') -> _Page:
    p = _Page(label=label, footer_issuer=m.supplier.name, footer_kind='הזמנת רכש')
    p.block("<div class='t' style='text-align:center'>הזמנת רכש</div>", 28)
    p.hrule()
    p.block(f"<div class='b' style='text-align:center'>הזמנה מספר: {m.doc_id} | תאריך: {m.doc_date}</div>", 24)
    p.gap(6)
    sup, cust = m.supplier, m.customer
    p.block("<table><tr>"
            f"<td style='width:50%;vertical-align:top'><div class='b'>ספק:</div>"
            f"<div>{sup.name}</div><div>ח.פ: {sup.company_id}</div></td>"
            f"<td style='width:50%;vertical-align:top'><div class='b'>מזמין:</div>"
            f"<div>{cust.name}</div><div>ח.פ: {cust.company_id}</div>"
            f"<div>{cust.street} {cust.zip}</div></td>"
            "</tr></table>", 80)
    p.gap(4)
    _lines_table(p, ['מק"ט', 'תיאור פריט', 'כמות', "מחיר יח'", 'סכום'],
                 [[l.sku, l.description, f'{l.qty:g}', _money(l.unit_price), _money(l.total)]
                  for l in m.lines], row_numbers=False)
    p.gap(6)
    p.block(f"<div class='t'>סה\"כ מחיר: {_money(m.total)} ₪</div>", 26)
    return p


def render_shipment(m, label='') -> _Page:
    p = _Page(label=label, footer_issuer=m.supplier.name, footer_kind='תעודת משלוח')
    _header(p, m.supplier, logo=True)
    p.gap(2)
    extra = ("<div class='b' style='margin-top:6px'>ממחסן:</div>"
             f"<div class='s'>{m.warehouse}</div>"
             + (f"<div class='s'>קוד קו חלוקה מהזמנה: {m.route}</div>" if m.route else ""))
    _customer_band(p, m.customer,
                   [('תאריך התעודה', m.doc_date),
                    ('תאריך הדפסה', m.print_date or m.doc_date),
                    ('שעת הדפסה', m.print_time),
                    ('לקוח', m.customer_line or 'A')],
                   extra_right=extra)
    p.block(f"<div class='b'>כתובת למשלוח: {m.delivery_address}</div>", 16)
    p.gap(2)
    if getattr(m, 'has_barcode', True):
        p.barcode(m.doc_id)
    copy = ' - העתק' if m.copy_marker else ''
    p.block(f"<div class='t u' style='text-align:center'>תעודת משלוח מספר {m.doc_id}{copy}</div>", 26)
    p.gap(4)
    _lines_table(p, ['הזמנה', 'הזמנתכם', 'מק"ט', 'תאור מוצר', 'כמות'],
                 [[l.order_ref, l.customer_order_ref, l.sku, l.description, f'{l.qty:g}']
                  for l in m.lines], zebra=False)
    p.gap(4)
    info = [f"ברקוד מספר תעודה: *{m.doc_id}*", f"תנאי תשלום: {m.payment_terms}"]
    if m.agent:
        info.append(f"סוכן: {m.agent}")
    info += [f"מס. לקוח: {m.customer.customer_no}",
             f"מספר חברה לקוח: {m.customer.company_id}",
             f"מספר מע\"מ לקוח: {m.customer.company_id}",
             f"משקל ברוטו מחושב: {_money(m.gross_weight)}"]
    p.block("<div style='text-align:right;font-size:10px'>" + '<br/>'.join(info) + "</div>", 16 * len(info) + 6)
    if m.legal_terms:
        p.block("<div class='s'>1. הסחורה הינה רכוש הספק עד לפירעון מלא של התשלום עבורה.<br/>"
                "2. חתימת הלקוח בתעודה מהווה אישור שהכמויות שהתקבלו מתאימות למופיע בגוף התעודה.<br/>"
                "3. באחריות הלקוח לבדוק התאמה בין המופיע בתעודה להזמנה שבוצעה בפועל.<br/>"
                "4. באחריות הלקוח לבדוק שהסחורה שקיבל תקינה ואיננה שבורה.</div>", 60)
    if m.signature_block:
        p.gap(8)
        box = fitz.Rect(A4[0] / 2, p.y, A4[0] - MARGIN, p.y + 66)
        el.draw_signature_box(p.page, box, p.arch, CSS,
                              'הרני החתום על התעודה, מאשר בזאת שהסחורה שסופקה על פי תעודה זו נספרה ונבדקה',
                              'חתימת המקבל', 'שם המקבל')
        p.y += 70
    if getattr(m, 'sender_signature', ''):
        p.block(f"<div>{m.sender_signature}<br/><span class='s'>{m.supplier.name}</span></div>", 30)
    return p


def render_receipt(m, label='') -> _Page:
    p = _Page(label=label, footer_issuer=m.supplier.name, footer_kind='קבלה')
    _header(p, m.supplier, logo=True)
    p.gap(2)
    _customer_band(p, m.customer, [('תאריך', m.doc_date)])
    p.gap(2)
    p.block(f"<div class='t u' style='text-align:center'>קבלה מספר {m.doc_id}</div>", 26)
    if m.computerized:
        p.block("<div class='b' style='text-align:center'>מסמך ממוחשב</div>", 16)
    p.gap(4)
    rows = [f"התקבל מ: {m.customer.name}",
            f"סכום שהתקבל: {_money(m.amount)} ש\"ח",
            f"עבור / החשבון שיזוכה: {m.nature}",
            f"אמצעי תשלום: {m.payment_method}"]
    if m.payment_method == 'המחאה':
        rows.append(f"המחאה מס' {m.cheque_number}, בנק {m.cheque_bank} סניף {m.cheque_branch}, ז.פ. {m.cheque_due_date}")
    if not m.computerized:
        rows.append(f"חתימת המקבל: {m.recipient_signature or '____________'}")
    p.block('<div style="font-size:11px">' + '<br/>'.join(rows) + '</div>', 18 * len(rows) + 10)
    return p


def render_balance_sheet(m, label='') -> _Page:
    p = _Page(label=label, footer_issuer=m.supplier.name, footer_kind='גיול חובות')
    top = p.y
    p.page.insert_htmlbox(fitz.Rect(MARGIN, top, MARGIN + 180, top + 20),
                          f"<div dir='rtl' class='s'>{m.print_time} {m.doc_date}</div>",
                          css=CSS, archive=p.arch)
    p.page.insert_htmlbox(fitz.Rect(A4[0] / 2, top, A4[0] - MARGIN, top + 40),
                          f"<div dir='rtl' style='text-align:right'><div class='t'>{m.supplier.name}</div>"
                          f"<div class='t'>גיול חובות פתוחים</div></div>", css=CSS, archive=p.arch)
    p.y = top + 44
    p.block(f"<div class='s'>תאריך אסמכתא: מ- {m.range_from} עד- {m.range_to} | "
            f"תאריך ערך: מ- {m.range_from} עד- {m.range_to}</div>", 16)
    p.block("<div class='s'>חובות שטרם שולמו</div>", 14)
    p.gap(4)
    p.block(f"<div class='b'>חשבון: {m.account_no} {m.customer.name}</div>"
            f"<div class='s'>{m.contact_line}</div>", 34)
    p.gap(4)
    bal = 0.0
    rows = []
    for l in m.lines:
        bal = round(bal + l.amount, 2)
        rows.append([l.ref_id, l.ref2, l.doc_date, l.value_date, l.details,
                     _money(l.debit) if l.debit else '', _money(l.credit) if l.credit else '',
                     _money(bal)])
    _lines_table(p, ['אסמ.', 'אסמ-2', 'ת.אסמ.', 'ת.ערך', 'פרטים', 'חובה', 'זכות', 'יתרת החוב'],
                 rows, row_numbers=False)
    p.gap(6)
    p.block(f"<div class='b'>סה\"כ יתרת חוב: {_money(m.document_total)}</div>"
            f"<div>תאריך תשלום משוקלל: {m.weighted_payment_date}</div>", 36)
    return p




def render_invoice_receipt(m, label=''):
    p = render_invoice(m, label=label)
    method = getattr(m, 'payment_method', 'מזומן')
    paid = getattr(m, 'amount_paid', getattr(m, 'total_due', 0))
    rows = [f"אמצעי תשלום: {method}", f"סכום ששולם: {_money(paid)} ש\"ח"]
    if method == 'המחאה' and getattr(m, 'cheque_number', ''):
        rows.append(f"המחאה מס' {m.cheque_number}, {m.cheque_bank}, ז.פ. {m.cheque_due_date}")
    p.block("<div class='b'>קבלה — פרטי תשלום</div><div>" + '<br/>'.join(rows) + "</div>", 20 + 18 * len(rows))
    return p


def render_quote(m, label=''):
    p = _Page(label=label, footer_issuer=m.supplier.name, footer_kind='הצעת מחיר')
    _header(p, m.supplier, logo=True)
    p.gap(4)
    dl = [('תאריך', m.doc_date)]
    if getattr(m, 'valid_until', ''):
        dl.append(('בתוקף עד', m.valid_until))
    _customer_band(p, m.customer, dl)
    p.gap(2)
    p.block(f"<div class='t u' style='text-align:center'>הצעת מחיר {m.doc_id}</div>", 26)
    if getattr(m, 'intro', ''):
        p.block(f"<div class='s'>{m.intro}</div>", 20)
    p.gap(4)
    _lines_table(p, ['תאור', 'כמות', "מחיר יח'", 'סכום'],
                 [[l.description, f'{l.qty:g}', _money(l.unit_price), _money(l.total)] for l in m.lines],
                 row_numbers=False)
    p.gap(6)
    p.block(f"<div class='t'>סה\"כ: {_money(m.total)} ₪ (לפני מע\"מ)</div>", 24)
    p.block("<div class='s'>הצעת מחיר זו אינה מהווה מסמך חשבונאי.</div>", 16)
    return p


RENDERERS = {'INVOICE': render_invoice, 'INVOICE_RECEIPT': render_invoice_receipt,
             'ORDER': render_order, 'QUOTE': render_quote,
             'SHIPMENT': render_shipment, 'BALANCE_SHEET': render_balance_sheet,
             'RECEIPT': render_receipt}


def _render_legacy(model, fmt, dpi, label):
    page = RENDERERS[model.DOC_TYPE](model, label=label)
    return page.png_bytes(dpi) if fmt == 'png' else page.pdf_bytes()


def render(model, fmt='pdf', dpi=200, label='') -> bytes:
    """label: '' | 'מקור' | 'העתק' | 'נאמן למקור' | 'טיוטה' — stamped on every page.
    מקור-once semantics are enforced by doc_data.serve(), not here.

    Primary path: a modern Hebrew-native HTML template rendered by WeasyPrint.
    Falls back to the legacy fitz renderer if WeasyPrint is unavailable — and says so: the two
    templates do not look alike, and a document from the other one is not what was asked for."""
    try:
        from weasyprint import HTML
    except Exception as e:
        logger.warning(f"doc_gen: WeasyPrint is unavailable ({e}); rendering with the fitz template")
        return _render_legacy(model, fmt, dpi, label)
    import time as _t
    from . import htmlgen
    html = htmlgen.build_html(model, label=label)
    html = html.replace('{ts}', _t.strftime('%d/%m/%Y %H:%M'))
    pdf = HTML(string=html, base_url=htmlgen.FONTS).write_pdf()
    if fmt != 'png':
        return pdf
    doc = fitz.open(stream=pdf, filetype='pdf')
    png = doc[0].get_pixmap(dpi=dpi).tobytes('png')
    doc.close()
    return png
