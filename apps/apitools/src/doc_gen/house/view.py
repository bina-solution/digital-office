"""view — a document's data turned into what its page shows (DGO-2029).

The templates do no arithmetic and no formatting: everything they print is computed here, once,
from the document dict (the ledger's model as a dict, or a JSON document of the same shape).

Money is Decimal, rounded half-up to agorot, so a total is the sum the reader can check with a
pencil. Dates are read as DD/MM/YYYY or ISO and printed DD/MM/YYYY (a long form for letters and
covers). Every free text is escaped; a narrative text may use three marks: **bold**, a line that
starts with "- " (a bullet), and an empty line (a new paragraph).
"""
from __future__ import annotations

import base64
import datetime as _dt
import html
import re
from decimal import Decimal, ROUND_HALF_UP

from markupsafe import Markup

from . import catalogue

MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר',
          'אוקטובר', 'נובמבר', 'דצמבר']
TAX_LABEL = {catalogue.PATUR: 'עוסק פטור', catalogue.MURSHE: 'עוסק מורשה', catalogue.COMPANY: 'ח.פ.'}
PERIOD = {'month': 'לחודש', 'year': 'לשנה', 'hour': 'לשעה', 'week': 'לשבוע'}
PERIOD_GROUP = {'month': 'תשלום חודשי', 'year': 'תשלום שנתי', 'hour': 'לפי שעה', 'week': 'תשלום שבועי'}
Q = Decimal('0.01')


# ── numbers ─────────────────────────────────────────────────────────────────
def dec(v):
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v if v not in (None, '') else 0))
    except Exception:
        return Decimal(0)


def r2(v):
    return dec(v).quantize(Q, rounding=ROUND_HALF_UP)


def money(v, sign=True):
    """12,345.60 — a negative amount with a true minus (U+2212), never a hyphen."""
    d = r2(v)
    s = f'{abs(d):,.2f}'
    return ('−' + s) if (sign and d < 0) else s


def qty(v):
    d = dec(v)
    if d == d.to_integral_value():
        return f'{int(d):,}'
    return f'{d.normalize():f}'


def pct(v):
    d = dec(v)
    return f'{int(d)}' if d == d.to_integral_value() else f'{d.normalize():f}'


# ── dates ───────────────────────────────────────────────────────────────────
def parse_date(s):
    if isinstance(s, (_dt.date, _dt.datetime)):
        return s if isinstance(s, _dt.date) else s.date()
    s = (s or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y', '%d.%m.%Y', '%Y-%m-%dT%H:%M:%S'):
        try:
            return _dt.datetime.strptime(s[:19] if 'T' in s else s, fmt).date()
        except ValueError:
            continue
    return None


def date(s):
    d = parse_date(s)
    return d.strftime('%d/%m/%Y') if d else (s or '')


def long_date(s):
    d = parse_date(s)
    return f'{d.day} ב{MONTHS[d.month - 1]} {d.year}' if d else (s or '')


# ── text ────────────────────────────────────────────────────────────────────
def esc(s):
    return html.escape(str(s or ''), quote=True)


#: a document's number (PR-2026-00012) or a date inside free text: one unbroken left-to-right token
_TOKEN = re.compile(r'\b([A-Z]{2,4}-\d{4}-\d{3,6}|\d{1,2}/\d{1,2}/\d{4})\b')


def _inline(s):
    out = esc(s)
    out = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', out)
    out = _TOKEN.sub(r'<span class="num">\1</span>', out)
    return out.replace('\n', '<br>')


def plain(s):
    """The text without its marks: for a title in a running header or a file's metadata."""
    return re.sub(r'\s+', ' ', re.sub(r'\*\*(.+?)\*\*', r'\1', str(s or ''))).strip()


def parts(items):
    """Several short facts on one line, each in its own bidi isolate — so «כרטיס 4417 · 3 תשלומים» stays in that
    order and a number never jumps to the neighbouring fact."""
    items = [x for x in items if x]
    return Markup('<span class="sepdot"> · </span>'.join(f'<span class="iso">{esc(x)}</span>' for x in items))


def rich(text):
    """Paragraphs, bullets and **bold** from plain text — everything else is escaped."""
    if not text:
        return Markup('')
    if isinstance(text, (list, tuple)):
        text = '\n\n'.join(str(t) for t in text)
    out, bullets = [], []

    def flush():
        if bullets:
            out.append('<ul class="bul">' + ''.join(f'<li>{b}</li>' for b in bullets) + '</ul>')
            bullets.clear()

    for block in re.split(r'\n\s*\n', str(text).strip()):
        lines = [ln.rstrip() for ln in block.split('\n') if ln.strip()]
        para = []
        for ln in lines:
            if re.match(r'^\s*[-•]\s+', ln):
                if para:
                    out.append('<p>' + '<br>'.join(para) + '</p>'); para = []
                bullets.append(_inline(re.sub(r'^\s*[-•]\s+', '', ln)))
            else:
                flush()
                para.append(_inline(ln))
        if para:
            flush()
            out.append('<p>' + '<br>'.join(para) + '</p>')
        flush()
    return Markup(''.join(out))


def inline(text):
    return Markup(_inline(text))


# ── parties ─────────────────────────────────────────────────────────────────
def _addr(p):
    street = (p.get('street') or '').strip()
    city = (p.get('city') or '').strip()
    z = (p.get('zip') or '').strip()
    a = ', '.join(x for x in [street, ' '.join(x for x in [city, z] if x)] if x)
    return a


def party(p, *, issuer=False):
    p = dict(p or {})
    status = p.get('tax_status') or (catalogue.MURSHE if issuer else '')
    tax = ''
    if p.get('company_id'):
        if issuer:
            tax = f'{TAX_LABEL.get(status, "עוסק מורשה")} {p["company_id"]}'
        else:
            tax = f'ח.פ./ע.מ. {p["company_id"]}'
    contact = [x for x in [_addr(p),
                           f'טל׳ {p["phone"]}' if p.get('phone') else '',
                           p.get('email') or '',
                           p.get('website') or ''] if x]
    where = [x for x in [_addr(p), f'טל׳ {p["phone"]}' if p.get('phone') else ''] if x]
    online = [x for x in [p.get('email') or '', p.get('website') or ''] if x]
    return {
        'where': where, 'online': online,
        'name': p.get('name') or '',
        'name_en': p.get('name_en') or '',
        'tax_status': status,
        'tax': tax,
        'company_id': p.get('company_id') or '',
        'address': _addr(p),
        'phone': p.get('phone') or '',
        'email': p.get('email') or '',
        'website': p.get('website') or '',
        'contact': contact,
        'person': p.get('contact_person') or p.get('person') or '',
        'person_title': p.get('contact_title') or '',
        'vat_file': p.get('vat_file_no') or '',
        'deduction_file': p.get('deduction_file_no') or '',
        'customer_no': p.get('customer_no') or '',
        'signatory': p.get('signatory') or '',
        'signatory_title': p.get('signatory_title') or '',
        'initial': (p.get('name') or 'ב').strip()[:1],
        'logo': p.get('logo') or '',
        'mark': p.get('mark') or '',
    }


# ── the office's mark ───────────────────────────────────────────────────────
#: the office's mark (digital-office/brand/io, DGO-1908): a tile, the i, and the 0 — drawn in the
#: mark's own three colours, which the document passes in.
I0 = ('<svg class="mk" viewBox="53.57 53.57 892.86 892.86" xmlns="http://www.w3.org/2000/svg">'
      '<rect fill="{tile}" x="53.57" y="53.57" width="892.86" height="892.86" rx="196.43"/>'
      '<rect x="267.32" y="276.79" width="71.25" height="71.25" rx="19.24" fill="{accent}"/>'
      '<rect x="267.32" y="419.29" width="71.25" height="285" rx="19.24" fill="{glyph}"/>'
      '<path d="M429.06 276.79H675.59A19.24 19.24 0 0 1 694.82 296.02V685.05A19.24 19.24 0 0 1 675.59 '
      '704.29H429.06A19.24 19.24 0 0 1 409.82 685.05V296.02A19.24 19.24 0 0 1 429.06 276.79ZM500.31 '
      '348.04A19.24 19.24 0 0 0 481.07 367.27V613.8A19.24 19.24 0 0 0 500.31 633.04H604.34A19.24 19.24 '
      '0 0 0 623.57 613.8V367.27A19.24 19.24 0 0 0 604.34 348.04Z" fill="{glyph}"/>'
      '<rect x="516.7" y="419.29" width="71.25" height="142.5" rx="19.24" fill="{accent}"/></svg>')


#: a logo the page may draw: an image as a data: URI, nothing that names a file or an address
_DATA_IMAGE = re.compile(r'^data:image/(?:png|jpeg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$')


def mark(sup, colours):
    """The business's mark: its own logo (an SVG text or a data URI), the office's i0, or its initial.

    A logo is always drawn as an image, never written into the page: an SVG's text is whoever saved it, and
    inline it could carry a script or close the page's style (DGO-2029, the second reader)."""
    logo = (sup.get('logo') or '').strip()
    if logo.startswith('<svg'):
        logo = 'data:image/svg+xml;base64,' + base64.b64encode(logo.encode('utf-8')).decode('ascii')
    if _DATA_IMAGE.match(logo):
        return Markup(f'<span class="mark own"><img src="{esc(logo)}" alt=""/></span>')
    if (sup.get('mark') or '') == 'i0':
        return Markup('<span class="mark">' + I0.format(tile=colours['mark_tile'], glyph=colours['mark_glyph'],
                                                         accent=colours['mark_accent']) + '</span>')
    return Markup(f'<span class="mark mono"><span>{esc(sup.get("initial") or "ב")}</span></span>')


# ── lines and totals ────────────────────────────────────────────────────────
def lines(doc):
    out = []
    for i, ln in enumerate(doc.get('lines') or [], 1):
        ln = dict(ln or {})
        q = dec(ln.get('qty', 1) if ln.get('qty', '') != '' else 1)
        up = dec(ln.get('unit_price', 0))
        amount = r2(q * up) if ln.get('amount') in (None, '') else r2(ln.get('amount'))
        detail = [x for x in [ln.get('detail') or ln.get('notes') or '',
                              f'מק״ט {ln["sku"]}' if ln.get('sku') else ''] if x]
        refs = [x for x in [f'הזמנה {ln["order_ref"]}' if ln.get('order_ref') else '',
                            f'הזמנתכם {ln["customer_order_ref"]}' if ln.get('customer_order_ref') else '',
                            f'תעודה {ln["shipment_ref"]}' if ln.get('shipment_ref') else ''] if x]
        period = (ln.get('period') or '').strip()
        out.append({
            'n': i, 'description': ln.get('description') or '', 'detail': parts(detail + refs),
            'qty': qty(q), 'unit': ln.get('unit') or '', 'unit_price': money(up), 'amount': money(amount),
            'raw_amount': amount, 'period': period, 'period_label': PERIOD.get(period, period),
            'owner': ln.get('owner') or '', 'when': ln.get('when') or '', 'hours': ln.get('hours') or '',
        })
    return out


def _vat_on(k, sup, doc):
    """A VAT-registered business's document that carries VAT shows its VAT line — at 0% too (an export, a
    zero-rated sale): a tax invoice with no VAT line at all reads as a mistake, and once was one."""
    status = sup.get('tax_status') or catalogue.MURSHE
    return bool(k.get('vat')) and status in catalogue.VAT_ISSUERS


def totals(rows, doc, k, sup):
    """The ladder under a group of lines: subtotal, discount, VAT, the grand total."""
    sub = sum((r['raw_amount'] for r in rows), Decimal(0))
    disc_pct = dec(doc.get('discount_pct') or 0)
    disc = r2(doc.get('discount')) if doc.get('discount') not in (None, '', 0) else r2(sub * disc_pct / 100)
    after = r2(sub - disc)
    vat_on = _vat_on(k, sup, doc)
    vat_pct = dec(doc.get('vat_pct', 18)) if vat_on else Decimal(0)
    vat = r2(after * vat_pct / 100)
    total = r2(after + vat)
    # one line and nothing taken off or added: the grand total alone says it (no «סה״כ» above «סה״כ לתשלום»)
    ladder = [('סכום ביניים', money(sub))] if (disc or vat_on) else []
    if disc:
        ladder.append((f'הנחה {pct(disc_pct)}%' if disc_pct else 'הנחה', money(-disc)))
        ladder.append(('אחרי הנחה', money(after)))
    if vat_on:
        ladder.append((f'מע״מ {pct(vat_pct)}%', money(vat)))
    return {'ladder': ladder, 'total': money(total), 'raw_total': total, 'vat_on': vat_on,
            'patur': (sup.get('tax_status') == catalogue.PATUR) and bool(k.get('vat')),
            'raw_vat': vat, 'raw_after': after, 'raw_sub': r2(sub), 'raw_disc': disc}


def price_groups(doc, k, sup):
    """One-time lines in one group, each recurring period in its own (a setup fee and a monthly retainer)."""
    ls = lines(doc)
    groups, order = {}, []
    for ln in ls:
        key = ln['period'] or ''
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(ln)
    out = []
    for key in sorted(order, key=lambda x: (x != '', order.index(x))):
        g = groups[key]
        t = totals(g, doc if key == '' else {**doc, 'discount': 0, 'discount_pct': 0}, k, sup)
        out.append({'period': key, 'title': (PERIOD_GROUP.get(key, key) if key else 'תשלום חד־פעמי'),
                    'suffix': PERIOD.get(key, ''), 'lines': g, 'totals': t})
    return out


def payments(doc):
    out, total = [], Decimal(0)
    for p in doc.get('payments') or []:
        p = dict(p or {})
        amt = r2(p.get('amount'))
        total += amt
        method = p.get('method') or 'העברה בנקאית'
        detail = []
        if p.get('cheque_number'):
            detail.append(f'המחאה {p["cheque_number"]}')
        if p.get('bank'):
            detail.append(f'בנק {p["bank"]}')
        if p.get('branch'):
            detail.append(f'סניף {p["branch"]}')
        if p.get('account'):
            detail.append(f'חשבון {p["account"]}')
        if p.get('card_last4'):
            detail.append(f'כרטיס המסתיים ב־{p["card_last4"]}')
        if p.get('payments_count'):
            detail.append(f'{p["payments_count"]} תשלומים')
        if p.get('ref'):
            detail.append(f'אסמכתא {p["ref"]}')
        if p.get('due_date'):
            detail.append(f'לפירעון {date(p["due_date"])}')
        out.append({'method': method, 'detail': parts(detail), 'date': date(p.get('date') or doc.get('doc_date')),
                    'due': date(p.get('due_date')) if p.get('due_date') else '', 'amount': money(amt), 'raw': amt})
    return out, r2(total)


def allocation(number):
    """The allocation number as the Tax Authority asks it printed: the 9 rightmost digits stand out."""
    n = re.sub(r'\s', '', str(number or ''))
    if not n:
        return None
    return {'full': n, 'head': n[:-9], 'tail': n[-9:]}


def statement(doc):
    st = dict(doc.get('statement') or {})
    bal = r2(st.get('opening_balance'))
    rows, debit_sum, credit_sum = [], Decimal(0), Decimal(0)
    for r in st.get('rows') or []:
        d, c = r2(r.get('debit')), r2(r.get('credit'))
        debit_sum += d
        credit_sum += c
        bal = r2(bal + d - c)
        rows.append({'date': date(r.get('date')), 'ref': r.get('ref') or '', 'kind': r.get('kind') or '',
                     'details': r.get('details') or '', 'debit': money(d) if d else '',
                     'credit': money(c) if c else '', 'balance': money(bal), 'due': date(r.get('due'))})
    aging = [(k, money(v)) for k, v in (st.get('aging') or {}).items()]
    return {'period': f'{date(st.get("from"))} – {date(st.get("to"))}' if st.get('from') else '',
            'opening': money(st.get('opening_balance')), 'debits': money(debit_sum),
            'credits': money(credit_sum), 'closing': money(bal), 'raw_closing': bal,
            'rows': rows, 'aging': aging}
