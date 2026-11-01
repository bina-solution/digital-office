# -*- coding: utf-8 -*-
"""htmlgen — beautiful, Hebrew-native business documents (HTML/CSS -> WeasyPrint PDF).

A 2026 design system: deep-emerald + warm neutrals, Rubik for display / Heebo for
text, tabular figures, generous whitespace, hairline dividers, a soft total band, and
a refined compliance footer (מסמך ממוחשב / מקור-העתק / 7-year retention). RTL throughout.

Public entry: build_html(model, label='') -> full HTML string. The render() in
render.py turns it into PDF (WeasyPrint) or PNG (PDF -> pixmap).
"""
from __future__ import annotations

import os

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')


def _u(name):
    return 'file://' + os.path.join(FONTS, name).replace('\\', '/')


def _money(v):
    try:
        return f'{float(v or 0):,.2f}'
    except (TypeError, ValueError):
        return '0.00'


def _nis(v):
    # amount kept LTR so digits/decimal don't reorder; the ₪ is a SEPARATE token after
    # a space so OCR never fuses it onto the digits (a fused ₪ mis-reads as a leading 1)
    return f'<span class="num">{_money(v)}</span> <span class="cur">₪</span>'


def _esc(s):
    return (str(s or '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _tax_line(sup):
    status = getattr(sup, 'tax_status', 'murshe')
    label = {'patur': 'עוסק פטור', 'company': 'ח.פ', 'murshe': 'עוסק מורשה'}.get(status, 'עוסק מורשה')
    return f'{label} {_esc(sup.company_id)}'


# ── design system ───────────────────────────────────────────────────────────
def _css():
    return f"""
@font-face {{ font-family: Heebo; src: url('{_u("Heebo.ttf")}'); font-weight: 100 900; }}
@font-face {{ font-family: Rubik; src: url('{_u("Rubik.ttf")}'); font-weight: 300 900; }}

:root {{
  --ink:#16211D; --brand:#0E5A48; --brand-deep:#0A3F33; --accent:#2FA98A;
  --wash:#EAF3EF; --wash-line:#CFE6DC; --muted:#7C8781; --line:#E9E5DB;
  --paper:#FFFFFF; --tint:#FBFAF6;
}}
@page {{ size: A4; margin: 15mm 14mm 20mm 14mm; }}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ font-family: Heebo, sans-serif; color: var(--ink); font-size: 10.5pt; line-height: 1.5; }}
body {{ direction: rtl; }}
/* normal document flow — a flex column with min-height + margin-top:auto on the
   signature bottom-anchors short docs but DROPS the totals/signature when content
   paginates to a 2nd page, so keep plain flow (short docs just get whitespace) */
main {{ }}
.num {{ direction: ltr; unicode-bidi: isolate; font-variant-numeric: tabular-nums;
       font-feature-settings: "tnum" 1; white-space: nowrap; }}
.rubik {{ font-family: Rubik, Heebo, sans-serif; }}
.muted {{ color: var(--muted); }}
.eyebrow {{ font-size: 8pt; letter-spacing: .12em; color: var(--muted); font-weight: 600; }}

/* ── header ── */
.head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }}
.brandbox {{ display: flex; gap: 12px; align-items: flex-start; }}
.mono {{ width: 46px; height: 46px; border-radius: 13px; background: var(--brand);
        color: #fff; font-family: Rubik; font-weight: 700; font-size: 24pt;
        display: flex; align-items: center; justify-content: center; flex: none; }}
.bizname {{ font-family: Rubik; font-weight: 700; font-size: 19pt; color: var(--brand-deep);
           letter-spacing: -.01em; line-height: 1.15; }}
.bizmeta {{ font-size: 9pt; color: var(--muted); margin-top: 3px; }}
.bizmeta b {{ color: var(--ink); font-weight: 600; }}

.docchip {{ border: 1px solid var(--line); border-radius: 14px; padding: 13px 18px 15px;
           min-width: 168px; background: var(--tint); text-align: left; }}
.docchip .kind {{ font-family: Rubik; font-weight: 600; font-size: 13pt; color: var(--brand); }}
.docchip .no {{ font-family: Heebo; font-weight: 800; font-size: 21pt; color: var(--ink);
               letter-spacing: .01em; margin-top: 1px; }}
.docchip .row {{ display: flex; justify-content: space-between; gap: 14px; font-size: 9pt;
                margin-top: 7px; color: var(--muted); }}
.docchip .row b {{ color: var(--ink); font-weight: 600; }}

.rule {{ height: 2px; background: linear-gradient(90deg, var(--brand) 0%, var(--accent) 55%, transparent 100%);
        border-radius: 2px; margin: 16px 0 4px; }}

/* ── customer band ── */
.band {{ display: flex; justify-content: space-between; gap: 20px; margin-top: 14px; }}
.to .who {{ font-size: 13pt; font-weight: 700; color: var(--ink); margin-top: 2px; }}
.to .det {{ font-size: 9.5pt; color: var(--muted); margin-top: 1px; }}

/* ── generic section ── */
.sec {{ margin-top: 20px; }}
.sec > .eyebrow {{ margin-bottom: 8px; }}

/* ── hero total (receipt) ── */
.hero {{ background: var(--wash); border: 1px solid var(--wash-line); border-radius: 16px;
        padding: 18px 22px; display: flex; justify-content: space-between; align-items: center;
        margin-top: 16px; }}
.hero .lbl {{ font-size: 11pt; color: var(--brand-deep); font-weight: 600;
             display: inline-flex; align-items: center; gap: 9px; white-space: nowrap; }}
.hero .tick {{ width: 24px; height: 24px; border-radius: 50%; background: var(--brand);
              color: #fff; display: inline-flex; align-items: center; justify-content: center;
              font-size: 12pt; font-weight: 700; }}
.hero .amt {{ font-family: Heebo; font-weight: 800; font-size: 26pt; color: var(--brand-deep); }}

/* ── detail grid ── */
.grid {{ display: flex; flex-wrap: wrap; gap: 10px 34px; margin-top: 16px; }}
.grid .cell {{ min-width: 150px; }}
.grid .k {{ font-size: 8.5pt; color: var(--muted); letter-spacing: .04em; }}
.grid .v {{ font-size: 11pt; color: var(--ink); font-weight: 600; margin-top: 1px; }}
.note {{ margin-top: 14px; font-size: 10pt; color: var(--ink); }}

/* ── line items ── */
table.lines {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
table.lines thead th {{ font-size: 8.5pt; color: var(--brand-deep); font-weight: 700;
                       text-align: right; padding: 0 8px 8px; border-bottom: 1.5px solid var(--brand); letter-spacing: .03em; }}
table.lines thead th.n {{ text-align: left; }}
table.lines tbody td {{ padding: 9px 8px; font-size: 10.5pt; border-bottom: 1px solid var(--line);
                       vertical-align: top; }}
table.lines td.n {{ text-align: left; white-space: nowrap; }}
table.lines td.desc {{ color: var(--ink); }}
table.lines td .sku {{ font-size: 8.5pt; color: var(--muted); }}

/* ── totals ── */
.totwrap {{ display: flex; justify-content: flex-start; margin-top: 16px; }}
.totals {{ width: 52%; }}
/* label + value kept ADJACENT (small gap, not spread) so OCR reads them as one
   group — "find after <label>" then reliably lands on the value */
.totals .tl {{ display: flex; justify-content: flex-start; gap: 12px; padding: 5px 2px; font-size: 10.5pt; }}
.totals .tl .k {{ color: var(--muted); }}
.totals .grand {{ margin-top: 8px; background: var(--wash); border: 1px solid var(--wash-line);
                 border-radius: 12px; padding: 12px 16px; }}
.totals .grand .k {{ color: var(--brand-deep); font-weight: 700; font-size: 11.5pt; }}
.totals .grand .num {{ font-family: Heebo; font-weight: 800; font-size: 15pt; color: var(--brand-deep); }}

/* ── status pill / draft watermark ── */
.pill {{ display: inline-block; font-size: 8.5pt; font-weight: 700; letter-spacing: .06em;
        padding: 3px 11px; border-radius: 999px; border: 1px solid var(--wash-line);
        color: var(--brand-deep); background: var(--wash); }}
.watermark {{ position: fixed; top: 40%; left: 0; right: 0; text-align: center;
             font-family: Rubik; font-weight: 800; font-size: 90pt; color: rgba(14,90,72,.06);
             letter-spacing: .1em; transform: rotate(-18deg); }}

/* ── signature + stamp ── */
.sign {{ display: flex; justify-content: space-between; align-items: flex-end;
        margin-top: 48px; padding-top: 34px; gap: 24px; }}
.seal {{ width: 104px; height: 104px; border-radius: 50%; border: 2px solid var(--brand);
        box-shadow: inset 0 0 0 3px #fff, inset 0 0 0 4.5px var(--accent);
        color: var(--brand-deep); display: flex; flex-direction: column; align-items: center;
        justify-content: center; text-align: center; padding: 14px; line-height: 1.2;
        opacity: .5; transform: rotate(-8deg); flex: none; margin-left: 6px; }}
.seal .nm {{ font-family: Rubik; font-weight: 700; font-size: 9pt; }}
.seal .sm {{ font-size: 6.5pt; font-weight: 600; letter-spacing: .05em; margin-top: 3px; }}
.seal .hr {{ width: 42px; height: 1px; background: var(--brand); opacity: .6; margin: 4px 0; }}
.sig {{ text-align: center; min-width: 210px; }}
.sig .line {{ border-bottom: 1.4px solid var(--ink); height: 30px; margin-bottom: 6px; }}
.sig .digital {{ font-size: 8pt; color: var(--accent); font-weight: 600; }}

/* ── footer (repeats every page) ── */
.foot {{ position: fixed; bottom: -14mm; left: 0; right: 0; padding-top: 7px;
        border-top: 1px solid var(--line); font-size: 8pt; color: var(--muted);
        display: flex; justify-content: space-between; gap: 12px; }}
.foot .l b {{ color: var(--brand-deep); font-weight: 600; }}
"""


# ── shared chrome ───────────────────────────────────────────────────────────
def _header(m, kind, meta_rows):
    sup = m.supplier
    contact = ' · '.join(x for x in [f'{_esc(sup.street)}, {_esc(sup.city)}'.strip(' ,'),
                                     f'טלפון {_esc(sup.phone)}' if sup.phone else '',
                                     _esc(sup.email) if sup.email else ''] if x.strip(' ,'))
    rows = ''.join(f'<div class="row"><span>{k}</span><b>{v}</b></div>' for k, v in meta_rows)
    initial = (sup.name or 'ב').strip()[0]
    return f"""
<div class="head">
  <div class="brandbox">
    <div class="mono">{_esc(initial)}</div>
    <div>
      <div class="bizname">{_esc(sup.name)}</div>
      <div class="bizmeta"><b>{_tax_line(sup)}</b></div>
      <div class="bizmeta">{contact}</div>
    </div>
  </div>
  <div class="docchip">
    <div class="kind">{kind}</div>
    <div class="no">{_esc(m.doc_id)}</div>
    {rows}
  </div>
</div>
<div class="rule"></div>"""


def _customer(m, extra=''):
    c = m.customer
    det = ' · '.join(x for x in [f'{_esc(c.street)} {_esc(c.city)}'.strip(),
                                 f'ח.פ {_esc(c.company_id)}' if c.company_id else '',
                                 f'טלפון {_esc(c.phone)}' if getattr(c, 'phone', '') else ''] if x.strip())
    return f"""
<div class="band">
  <div class="to">
    <div class="eyebrow">לכבוד</div>
    <div class="who">{_esc(c.name)}</div>
    {f'<div class="det">{det}</div>' if det else ''}
  </div>
  <div>{extra}</div>
</div>"""


def _signature(m):
    sup = m.supplier
    return f"""
<div class="sign">
  <div class="seal"><div class="nm">{_esc(sup.name)}</div><div class="hr"></div>
    <div class="sm">{_tax_line(sup)}</div></div>
  <div class="sig"><div class="line"></div>
    <div class="eyebrow">חתימה וחותמת</div>
    <div class="digital">✓ נחתם דיגיטלית — מסמך ממוחשב</div>
  </div>
</div>"""


def _footer(m, kind):
    label = getattr(m, '_label', '') or 'מקור'
    return f"""
<div class="foot">
  <div class="l"><b>{_esc(m.supplier.name)}</b> · {kind} {_esc(m.doc_id)} · {label}</div>
  <div>מסמך ממוחשב · נשמר 7 שנים · הופק ב־{{ts}}</div>
</div>"""


def _skeleton(body, foot, watermark=''):
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{_css()}</style></head><body>{watermark}{foot}<main>{body}</main></body></html>"""


# ── per-type documents ──────────────────────────────────────────────────────
def _receipt(m):
    head = _header(m, 'קבלה', [('תאריך', _esc(m.doc_date))])
    method = getattr(m, 'payment_method', 'מזומן')
    cells = [('אמצעי תשלום', _esc(method)), ('תאריך תשלום', _esc(m.doc_date))]
    if method == 'המחאה' and getattr(m, 'cheque_number', ''):
        cells.append(('המחאה', f'{_esc(m.cheque_number)} · {_esc(m.cheque_bank)}'))
    grid = ''.join(f'<div class="cell"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in cells)
    nature = _esc(getattr(m, 'nature', ''))
    body = f"""{head}{_customer(m, '<span class="pill">מסמך ממוחשב</span>')}
<div class="hero"><div class="lbl"><span class="tick">✓</span>סכום שהתקבל</div><div class="amt"><span class="num">{_money(m.amount)}</span> ₪</div></div>
<div class="grid">{grid}</div>
{f'<div class="note"><span class="muted">עבור:</span> {nature}</div>' if nature else ''}
{_signature(m)}"""
    return _skeleton(body, _footer(m, 'קבלה'))


def _payment_block(m):
    method = getattr(m, 'payment_method', 'מזומן')
    paid = getattr(m, 'amount_paid', getattr(m, 'total_due', 0))
    cells = [('אמצעי תשלום', _esc(method)), ('סכום ששולם', _nis(paid))]
    if method == 'המחאה' and getattr(m, 'cheque_number', ''):
        cells.append(('המחאה', f'{_esc(m.cheque_number)} · {_esc(m.cheque_bank)}'))
    grid = ''.join(f'<div class="cell"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in cells)
    return f'<div class="sec"><div class="eyebrow">פרטי תשלום (קבלה)</div><div class="grid">{grid}</div></div>'


def _lines_doc(m, kind, subtitle='', extra=''):
    meta = [('תאריך', _esc(m.doc_date))]
    if getattr(m, 'valid_until', ''):
        meta.append(('בתוקף עד', _esc(m.valid_until)))
    head = _header(m, kind, meta)
    rows = ''
    for l in getattr(m, 'lines', []) or []:
        sku = f'<div class="sku">{_esc(l.sku)}</div>' if getattr(l, 'sku', '') else ''
        # per-line cross-references (real invoices/delivery notes carry these; they
        # are the source of AI_ORDER_IDS / AI_SHIPMENT_IDS)
        rp = []
        if getattr(l, 'order_ref', ''):          rp.append(f'הזמנה {_esc(l.order_ref)}')
        if getattr(l, 'customer_order_ref', ''): rp.append(f'הזמנתכם {_esc(l.customer_order_ref)}')
        if getattr(l, 'shipment_ref', ''):       rp.append(f'תעודה {_esc(l.shipment_ref)}')
        refs = f'<div class="sku">{" · ".join(rp)}</div>' if rp else ''
        rows += (f'<tr><td class="desc">{_esc(l.description)}{sku}{refs}</td>'
                 f'<td class="n">{l.qty:g}</td>'
                 f'<td class="n">{_money(l.unit_price)}</td>'
                 f'<td class="n">{_money(l.total)}</td></tr>')
    table = f"""<table class="lines"><thead><tr>
      <th>תיאור</th><th class="n">כמות</th><th class="n">מחיר יחידה</th><th class="n">סכום</th>
    </tr></thead><tbody>{rows}</tbody></table>"""
    sub = getattr(m, 'subtotal', None)
    vat = getattr(m, 'vat', None)
    vat_pct = getattr(m, 'vat_pct', 0) or 0
    total = getattr(m, 'total_due', getattr(m, 'total', getattr(m, 'amount', 0)))
    tot_rows = f'<div class="tl"><span class="k">סכום ביניים</span>{_nis(sub if sub is not None else total)}</div>'
    disc = getattr(m, 'discount', 0) or 0
    if disc:
        tot_rows += f'<div class="tl"><span class="k">הנחה</span>{_nis(disc)}</div>'
    if vat_pct:
        tot_rows += f'<div class="tl"><span class="k">מע״מ {vat_pct:g}%</span>{_nis(vat)}</div>'
    totals = f"""<div class="totwrap"><div class="totals">{tot_rows}
      <div class="tl grand"><span class="k">{'סה״כ לתשלום' if kind!='הצעת מחיר' else 'סה״כ להצעה'}</span>{_nis(total)}</div>
    </div></div>"""
    intro = f'<div class="note">{_esc(getattr(m, "intro", ""))}</div>' if getattr(m, 'intro', '') else ''
    tail = '<div class="note muted">הצעת מחיר זו אינה מהווה מסמך חשבונאי.</div>' if kind == 'הצעת מחיר' else ''
    body = (f'{head}{_customer(m)}{intro}<div class="sec"><div class="eyebrow">{subtitle or "פירוט"}</div>'
            f'{table}{totals}</div>{extra}{tail}{_signature(m)}')
    return _skeleton(body, _footer(m, kind))


def _balance_sheet(m):
    head = _header(m, 'גיול חובות', [('תאריך', _esc(m.doc_date))])
    acct = (f'<div class="band"><div class="to"><div class="eyebrow">חשבון</div>'
            f'<div class="who">{_esc(m.customer.name)}</div>'
            f'<div class="det">מס׳ חשבון {_esc(m.account_no)}{(" · " + _esc(m.contact_line)) if getattr(m, "contact_line", "") else ""}</div>'
            f'</div><div></div></div>')
    rows = ''; bal = 0.0
    for l in m.lines:
        bal = round(bal + (l.debit or 0) - (l.credit or 0), 2)
        rows += (f'<tr><td class="desc">{_esc(l.ref_id)}{(" · " + _esc(l.ref2)) if l.ref2 else ""}</td>'
                 f'<td class="n">{_esc(l.doc_date)}</td><td class="n">{_esc(l.value_date)}</td>'
                 f'<td class="desc">{_esc(l.details)}</td>'
                 f'<td class="n">{_money(l.debit) if l.debit else ""}</td>'
                 f'<td class="n">{_money(l.credit) if l.credit else ""}</td>'
                 f'<td class="n">{_money(bal)}</td></tr>')
    table = f"""<table class="lines"><thead><tr>
      <th>אסמכתא</th><th class="n">ת. אסמכתא</th><th class="n">ת. ערך</th><th>פרטים</th>
      <th class="n">חובה</th><th class="n">זכות</th><th class="n">יתרה</th>
    </tr></thead><tbody>{rows}</tbody></table>"""
    tot = f"""<div class="totwrap"><div class="totals">
      <div class="tl grand"><span class="k">סה״כ יתרת חוב</span>{_nis(m.document_total)}</div></div></div>"""
    wpd = (f'<div class="note muted">תאריך תשלום משוקלל: {_esc(m.weighted_payment_date)}</div>'
           if getattr(m, 'weighted_payment_date', '') else '')
    body = f'{head}{acct}<div class="sec"><div class="eyebrow">גיול חובות פתוחים</div>{table}{tot}</div>{wpd}{_signature(m)}'
    return _skeleton(body, _footer(m, 'גיול חובות'))


_KIND = {'RECEIPT': 'קבלה', 'INVOICE': 'חשבונית מס', 'INVOICE_RECEIPT': 'חשבונית מס קבלה',
         'QUOTE': 'הצעת מחיר', 'ORDER': 'הזמנת רכש', 'SHIPMENT': 'תעודת משלוח'}


def build_html(model, label=''):
    setattr(model, '_label', label or 'מקור')
    dt = model.DOC_TYPE
    if dt == 'RECEIPT':
        html = _receipt(model)
    elif dt == 'BALANCE_SHEET':
        html = _balance_sheet(model)
    elif dt == 'INVOICE_RECEIPT':
        html = _lines_doc(model, _KIND[dt], extra=_payment_block(model))
    else:
        html = _lines_doc(model, _KIND.get(dt, dt))
    return html
