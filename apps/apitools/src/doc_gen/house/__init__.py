"""house — every business document of the office, in one house style (DGO-2029).

    from src.doc_gen import house
    html = house.render_html(doc)                 # the page, as HTML (a live preview in a browser)
    pdf  = house.render_pdf(doc, label='מקור')    # the document, as PDF/A-3b with its data inside

`doc` is a dict: the ledger's model as a dict (`dataclasses.asdict` + `doc_type`) or a JSON document of
the same shape. Its `doc_type` is a catalogue type (catalogue.py), its `supplier` the business that
issues it (name, tax_status, company_id, address, contact, logo or mark, signatory), its `customer`
whom it is for. What else it carries depends on the type: `lines` (description, qty, unit,
unit_price, period), `payments`, `sections` and a `cover` (a proposal), `parties`/`recitals`/`clauses`/
`signatures` (an agreement), `statement` (a customer statement), `body` (a letter), `certificate` (an
e-signature). The renderer computes every number (view.py) and draws with house.css + templates/.

The look is the ledger's emerald style the owner chose (htmlgen.py, July 2026), raised: covers, a
running footer with «עמוד X מתוך Y», the totals under the amount column beside the terms and the bank,
the allocation number as the Tax Authority asks it printed, a true minus for credits, and the office's
mark. Its values are tokens.json; an office's brand (settings → brand) overrides any of them.
"""
from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import json
import os
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import catalogue, view

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), 'fonts')
TEMPLATES = os.path.join(HERE, 'templates')

_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(['j2', 'html']),
                   trim_blocks=True, lstrip_blocks=True)


def _read(name):
    with open(os.path.join(HERE, name), encoding='utf-8') as f:
        return f.read()


#: a brand value is written into the page's style and its mark's SVG, so each is held to its own shape — a hex
#: colour, a face the document embeds, a size in pt/px/mm — and anything else is not taken (DGO-2029, the second
#: reader: a «colour» that closed the style block could make the renderer read a file into the PDF)
_SHAPE = {
    'colour': re.compile(r'^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$').match,
    'face': lambda v: v in FACES,
    'size': re.compile(r'^\d{1,2}(?:\.\d{1,2})?(?:pt|px|mm)$').match,
}


def tokens(brand=None):
    """The house tokens with an office's brand laid over them (only known keys, each in its own shape)."""
    t = json.loads(_read('tokens.json'))
    for group in ('colour', 'face', 'size'):
        for k, v in ((brand or {}).get(group) or {}).items():
            if k in t[group] and isinstance(v, str) and _SHAPE[group](v.strip()):
                t[group][k] = v.strip()
    return t


def _rgb(hexcolour):
    h = hexcolour.strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    h = h[:6]                                    # an 8-digit colour's alpha is not a tone
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(round(max(0.0, min(1.0, x)) * 255) for x in rgb)


def _contrast(a, b):
    """WCAG contrast ratio of two hex colours."""
    def lum(c):
        r, g, b_ = (x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in _rgb(c))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def family(primary, secondary=''):
    """The brand tones a business's own colour gives its documents (DGO-2048).

    «זהות» names one colour (and maybe a second); the house draws with seven: the brand, two depths of it
    (headings; the cover), an accent read as TEXT on paper, a soft accent read as text on the cover, and two
    washes. Laying only `brand` over the emerald house gave a page half in the business's colour and half in
    emerald. Each tone keeps the house's own proportion (tokens.json's emerald family: deep = 0.70 of the
    brand's lightness, night = 0.48, washes at 94% and 86%) in the business's hue. Every tone a page uses as
    TEXT reads (4.5:1): the brand itself (a title, a label) and the accent on paper — a light colour (a yellow,
    a sky blue) is darkened in its own hue until it does — and the soft accent on the cover, against both its
    ends (night 4.5:1, brand 3:1, as large text); the second colour is the soft accent only where it reads
    there, and white is the last resort. Not a colour → {} (the house stays as it is)."""
    import colorsys
    ok = lambda c: isinstance(c, str) and bool(_SHAPE['colour'](c.strip()))  # noqa: E731
    if not ok(primary):
        return {}
    h, l, s = colorsys.rgb_to_hls(*_rgb(primary))
    tone = lambda li, si: _hex(colorsys.hls_to_rgb(h, max(0.0, min(1.0, li)), max(0.0, min(1.0, si))))  # noqa: E731
    brand = _hex(_rgb(primary))
    while _contrast(brand, '#FFFFFF') < 4.5 and l > 0.05:      # the brand is text too: never illegible on paper
        l -= 0.02
        brand = tone(l, s)
    out = {'brand': brand, 'brand_deep': tone(l * 0.70, s), 'brand_night': tone(l * 0.48, s),
           'wash': tone(0.94, min(s, 0.28)), 'wash_line': tone(0.86, min(s, 0.33))}
    li = max(0.30, min(0.45, l * 2.1))
    accent = tone(li, s * 0.78)
    while _contrast(accent, '#FFFFFF') < 4.5 and li > 0.05:
        li -= 0.02
        accent = tone(li, s * 0.78)
    out['accent'] = accent
    night = out['brand_night']
    reads = lambda c: _contrast(c, night) >= 4.5 and _contrast(c, brand) >= 3.0  # noqa: E731
    if ok(secondary) and reads(_hex(_rgb(secondary))):
        out['accent_soft'] = _hex(_rgb(secondary))
    else:
        li = 0.65
        soft = tone(li, s * 0.45)
        while not reads(soft) and li < 0.97:
            li += 0.02
            soft = tone(li, s * 0.45)
        out['accent_soft'] = soft if reads(soft) else '#FFFFFF'
    return out


def _root_vars(t):
    out = [f'--{k.replace("_", "-")}: {v};' for k, v in t['colour'].items()]
    out += [f'--display: "{t["face"]["display"]}"; --text: "{t["face"]["text"]}";']
    out += [f'--base: {t["size"]["base"]}; --small: {t["size"]["small"]}; --tiny: {t["size"]["tiny"]};']
    return ' '.join(out)


#: the faces a document embeds — the only files /docGen/house/fonts/ serves
FONT_FILES = ('Heebo.ttf', 'Rubik.ttf')
FACES = tuple(n.rsplit('.', 1)[0] for n in FONT_FILES)
_FONT_BASE = re.compile(r'^[A-Za-z0-9/_.\-]*$')


def _fetcher():
    """What the renderer may read while it draws a document: its own two faces and data: URIs, nothing else — no
    file beside them, no address on the network, whatever a brand value or a logo says (DGO-2029)."""
    from urllib.parse import unquote, urlsplit

    fonts = os.path.realpath(FONTS)

    def check(url):
        if not url.startswith('data:'):
            parts = urlsplit(url)
            path = os.path.realpath(unquote(parts.path)) if parts.scheme == 'file' else ''
            if not path or os.path.dirname(path) != fonts or os.path.basename(path) not in FONT_FILES:
                raise ValueError('a document reads only its own faces: %s' % url[:120])

    try:
        from weasyprint.urls import URLFetcher             # WeasyPrint 68+ (requirements.txt asks 70)
    except ImportError:                                    # an older image: the fetcher is a function there
        from weasyprint import default_url_fetcher

        def fetch(url, *a, **kw):
            check(url)
            return default_url_fetcher(url, *a, **kw)
        return fetch

    class _House(URLFetcher):
        def fetch(self, url, headers=None):
            check(url)
            return super().fetch(url, headers)

    return _House(allowed_protocols=('data', 'file'), allow_redirects=False)


def _fonts_css(font_base=None):
    """WeasyPrint reads the faces from this directory; a browser preview asks them of `font_base` (a relative
    path the page serves them under — validated: it is written into CSS)."""
    if font_base and _FONT_BASE.match(font_base):
        u = lambda n: font_base.rstrip('/') + '/' + n
    else:
        u = lambda n: 'file://' + os.path.join(FONTS, n).replace('\\', '/')
    return (f'@font-face {{ font-family: "Heebo"; src: url("{u("Heebo.ttf")}"); font-weight: 100 900; }}\n'
            f'@font-face {{ font-family: "Rubik"; src: url("{u("Rubik.ttf")}"); font-weight: 300 900; }}')


def israel_now():
    """The minute a document is produced, on Israel's clock (a container's clock is UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo('Asia/Jerusalem'))
    except Exception:  # no tz database in the image: the clock as it is
        return _dt.datetime.now()


def _footer_line(k, now, sup, issued=True):
    """The footer's last line. «מסמך ממוחשב» only on an issued document of the books — not on a draft, and not on a
    page /docGen/house drew (see `digital` in context())."""
    when = f'הופק ב־{now.strftime("%d/%m/%Y %H:%M")}'
    if k['family'] in ('tax', 'book') and issued:
        return f'מסמך ממוחשב · {when}'
    return ' · '.join(x for x in [when, sup.get('website') or sup.get('email') or ''] if x)


def _bank(doc, sup_raw):
    b = dict(doc.get('bank') or sup_raw.get('bank') or {})
    if not any(b.get(k) for k in ('bank', 'branch', 'account', 'iban')):
        return None
    b.setdefault('beneficiary', sup_raw.get('name') or '')
    return b


_TAX_WORD = {catalogue.PATUR: 'עוסק פטור', 'murshe': 'עוסק מורשה', 'company': 'ח.פ.'}


def _sides(doc, k):
    """An agreement's two sides as the screen writes them (my-docs buildModel), for one that came without them — an
    agreement converted from a proposal (DGO-2029, the second reader): «בין:» the business, «לבין:» the customer, and
    a place for each to sign. Nothing for any other type."""
    if k['family'] != 'legal':
        return [], []
    sup, cust = dict(doc.get('supplier') or {}), dict(doc.get('customer') or {})
    nda = doc.get('doc_type') == 'NDA'
    a1, a2 = ('הצד הראשון', 'הצד השני') if nda else ('הספק', 'הלקוח')

    def where(p):
        at = ', '.join(x for x in (p.get('street'), p.get('city')) if x)
        return ', ' + at if at else ''

    tax = _TAX_WORD.get(sup.get('tax_status') or '', 'ע.מ.')
    cid = ', ח.פ. ' + cust['company_id'] if cust.get('company_id') else ''
    parties = [{'label': 'בין:', 'text': f"{sup.get('name') or ''}, {tax} {sup.get('company_id') or ''}{where(sup)} "
                                        f"(להלן: **«{a1}»**)"},
               {'label': 'לבין:', 'text': f"{cust.get('name') or '…'}{cid}{where(cust)} (להלן: **«{a2}»**)"}]
    sigs = [{'party': (sup.get('name') or a1) if nda else a1, 'name': sup.get('signatory') or sup.get('name') or '',
             'title': sup.get('signatory_title') or ''},
            {'party': (cust.get('name') or a2) if nda else a2, 'name': cust.get('contact_person') or cust.get('name') or '',
             'title': (cust.get('name') or '') if cust.get('contact_person') else '', 'stamp': True}]
    return parties, sigs


def context(doc, *, label='', now=None, font_base=None):
    """Everything a template prints, computed once."""
    doc = copy.deepcopy(dict(doc or {}))
    k = catalogue.kind(doc.get('doc_type'))
    t = tokens(doc.get('brand') or (doc.get('supplier') or {}).get('brand'))
    sup_raw = dict(doc.get('supplier') or {})
    sup = view.party(sup_raw, issuer=True)
    cust = view.party(doc.get('customer'))
    status = (doc.get('status') or '').lower()
    label = label or doc.get('label') or ''
    # an issued document of the ledger: not a draft, not a page /docGen/house drew for a caller (digital False)
    issued = bool(doc.get('digital', True)) and not (label == 'טיוטה' or status == 'draft')
    now = now or israel_now()
    doc_id = doc.get('doc_id') or ''
    doc_date = view.date(doc.get('doc_date')) or now.strftime('%d/%m/%Y')

    chip = [('תאריך', doc_date)]
    if doc.get('valid_until'):
        chip.append(('בתוקף עד', view.date(doc['valid_until'])))
    if doc.get('payment_due'):
        chip.append(('לתשלום עד', view.date(doc['payment_due'])))
    if doc.get('delivery_date'):
        chip.append(('מועד אספקה', view.date(doc['delivery_date'])))

    facts = []
    for key, word in (('customer_order_ref', 'הזמנתכם'), ('delivery_note_ref', 'תעודת משלוח'),
                      ('payment_terms', 'תנאי תשלום'), ('project', 'פרויקט'), ('reference', 'אסמכתא')):
        if doc.get(key):
            facts.append((word, doc[key]))
    cust_no = (doc.get('customer') or {}).get('customer_no')
    if cust_no:
        facts.insert(0, ('מס׳ לקוח', cust_no))

    groups = view.price_groups(doc, k, sup) if doc.get('lines') else []
    pays, received = view.payments(doc)
    withholding = sum((view.r2(p.get('amount')) for p in (doc.get('payments') or [])
                       if (p.get('method') or '') == 'ניכוי במקור'), view.Decimal(0))

    refbox = ''
    ref = doc.get('refs') or {}
    if k.get('credit') and (ref.get('invoice') or doc.get('original_invoice')):
        inv = ref.get('invoice') or {'number': doc.get('original_invoice'), 'date': doc.get('original_date')}
        refbox = Markup(f'זיכוי לחשבונית מס <b class="num">{view.esc(inv.get("number"))}</b>'
                        + (f' מיום <span class="num">{view.esc(view.date(inv.get("date")))}</span>' if inv.get('date') else '')
                        + (f' · {view.esc(doc.get("reason"))}' if doc.get('reason') else ''))
    elif ref.get('source'):
        src = ref['source']
        refbox = Markup(f'בהמשך ל{view.esc(src.get("kind") or "מסמך")} <b class="num">{view.esc(src.get("number"))}</b>'
                        + (f' מיום <span class="num">{view.esc(view.date(src.get("date")))}</span>' if src.get('date') else ''))

    watermark = ''
    if label == 'טיוטה' or status == 'draft':
        watermark = 'טיוטה'
    if status == 'cancelled':
        watermark = 'מבוטל'

    cov = dict(doc.get('cover') or {})
    title = doc.get('title') or cov.get('title') or k['he']
    cover_title = view.inline(cov.get('title') or title)
    cover_facts = [('מוגש ל־' if k['family'] != 'legal' else 'בין הצדדים', cust['name'] or '—'),
                   ('תאריך', view.long_date(doc.get('doc_date')) or doc_date)]
    if doc_id:
        cover_facts.append(('מספר', Markup(f'<span class="num">{view.esc(doc_id)}</span>')))

    sections = []
    for s in doc.get('sections') or []:
        s = dict(s)
        sections.append({
            'kicker': s.get('kicker') or '',
            'title': s.get('title') or '', 'lead': view.inline(s.get('lead')) if s.get('lead') else '',
            'body': view.rich(s.get('body')) if s.get('body') else '',
            'modules': [{'n': i, 'title': m.get('title') or '', 'body': view.rich(m.get('body'))}
                        for i, m in enumerate(s.get('modules') or [], 1)],
            'plan': [{'when': r.get('when') or '', 'what': view.inline(r.get('what')), 'who': r.get('who') or ''}
                     for r in s.get('plan') or []],
            'pricing': bool(s.get('pricing')), 'price_note': view.rich(s.get('price_note')) if s.get('price_note') else '',
            'terms': [view.inline(x) for x in s.get('terms') or []],
            'callout': view.inline(s.get('callout')) if s.get('callout') else '',
        })

    default_parties, default_sigs = _sides(doc, k)
    parties = []
    for ptx in doc.get('parties') or default_parties:
        parties.append({'label': ptx.get('label') or '', 'text': view.inline(ptx.get('text'))})
    clauses = [{'title': c.get('title') or '', 'text': view.rich(c.get('text')) if c.get('text') else '',
                'points': [view.inline(x) for x in c.get('items') or []]} for c in doc.get('clauses') or []]
    sigs = []
    for s in doc.get('signatures') or default_sigs:
        sg = dict(s.get('signed') or {}) or None
        if sg:
            when = view.parse_date(sg.get('at')) if sg.get('at') else None
            sg = {'when': sg.get('when') or sg.get('at') or '', 'date': view.date(sg.get('at')) if when else '',
                  'image': sg.get('image') or ''}
        sigs.append({'party': s.get('party') or '', 'name': s.get('name') or '', 'title': s.get('title') or '',
                     'stamp': bool(s.get('stamp')), 'signed': sg})

    cert = None
    if doc.get('certificate'):
        c = dict(doc['certificate'])
        cert = {
            'envelope': c.get('envelope') or '', 'title': c.get('title') or '', 'number': c.get('number') or '',
            'pages': c.get('pages') or '', 'sender': c.get('sender') or sup['name'],
            'sha_before': c.get('sha_before') or '', 'sha_after': c.get('sha_after') or '',
            'signers': [dict(s) for s in c.get('signers') or []],
            'events': [dict(e) for e in c.get('events') or []],
            'verdict': c.get('verdict') or 'שרשרת האירועים שלמה, והמסמך לא השתנה מאז נחתם.',
            # whose signature it is, as the signing key itself says (esign passes its subject): on another office the
            # business's own name here named the wrong signer (DGO-2029, the third reader)
            'fine': c.get('fine') or ('המסמך החתום נושא חתימה דיגיטלית (PAdES)' +
                                      (' במפתח «' + c['key_subject'] + '»' if c.get('key_subject') else '') +
                                      '. כל שינוי בבית אחד שלו מבטל אותה, וכל קורא PDF מראה זאת. '
                                      'התעודה הזאת היא חלק מהמסמך החתום ונחתמה יחד איתו.'),
        }

    signed = None
    if doc.get('signed'):
        sgd = dict(doc['signed'])
        signed = {'name': sgd.get('name') or '', 'when': sgd.get('when') or sgd.get('at') or '', 'image': sgd.get('image') or ''}

    ctx = {
        'k': k, 'sup': sup, 'cust': cust, 'doc_id': doc_id, 'doc_date': doc_date, 'status': status,
        'label': label, 'watermark': watermark, 'chip_rows': chip, 'facts': facts,
        'to_word': doc.get('to_word') or ('לכבוד' if k['family'] != 'report' else 'חשבון'),
        'subject': doc.get('subject') or '', 'intro': view.rich(doc.get('intro')) if doc.get('intro') else '',
        'refbox': refbox, 'groups': groups, 'lines_title': doc.get('lines_title') or ('פירוט' if k['prices'] else 'הפריטים'),
        'terms': [view.inline(x) for x in doc.get('terms') or []],
        'notes': view.rich(doc.get('notes')) if doc.get('notes') else '',
        'bank': _bank(doc, sup_raw), 'alloc': view.allocation(doc.get('allocation_number')),
        'pays': pays, 'received': view.money(received), 'withholding': view.money(withholding) if withholding else '',
        'nature': doc.get('nature') or '', 'patur': sup['tax_status'] == catalogue.PATUR,
        'computerised': doc.get('computerised', k['family'] in ('tax', 'book')),
        'is_draft': label == 'טיוטה' or status == 'draft', 'valid_until': view.date(doc.get('valid_until')),
        # «מסמך ממוחשב» only on an issued document of the ledger — never a draft, never a page /docGen/house drew for
        # a caller (house_api sets digital False). Not «נחתם דיגיטלית»: the ledger's CMS signature is kept beside
        # the file, not in it (issues/ledger-issued-pdf-carries-no-embedded-signature.yaml)
        'digital': issued,
        'cover_kick': cov.get('kicker') or f'{k["he"]} · {k["en"].upper()}', 'cover_title': cover_title,
        'cover_sub': view.inline(cov.get('subtitle')) if cov.get('subtitle') else '', 'cover_facts': cover_facts,
        'confidential': bool(cov.get('confidential', k['family'] in ('narrative', 'legal'))),
        'has_cover': bool(doc.get('cover')) if k['template'] == 'agreement' else True,
        'sections': sections, 'sign_off': doc.get('sign_off') or None, 'signed': signed,
        # the price, once more, where the customer signs: one cell per total (a setup fee, a monthly retainer)
        'recap': [(g['title'], g['totals']['total'], 'לחודש' if g['period'] == 'month' else
                   ('לשנה' if g['period'] == 'year' else '')) for g in groups] if k.get('acceptance') else [],
        'title': title, 'made': doc.get('made') or (f'שנערך ונחתם ביום {view.long_date(doc.get("doc_date"))}' if doc.get('doc_date') else ''),
        'parties': parties, 'recitals': [view.inline(r) for r in doc.get('recitals') or []], 'clauses': clauses,
        'signatures': sigs, 'appendix': view.rich(doc.get('appendix')) if doc.get('appendix') else '',
        'st': view.statement(doc) if k['code'] == 'STATEMENT' else None,
        'long_date': view.long_date(doc.get('doc_date')) or doc_date, 'body': view.rich(doc.get('body')),
        'closing': doc.get('closing') or '', 'cc': doc.get('cc') or '', 'cert': cert,
        'footer_line': doc.get('footer_line') or _footer_line(k, now, sup, issued),
        'run_title': ' · '.join(x for x in [view.plain(title) if k['family'] in ('narrative', 'legal') else k['he'],
                                            doc_id] if x),
        'style_name': t['name'],
    }
    ctx['mark_html'] = view.mark(sup, t['colour'])
    ctx['root_vars'] = Markup(_root_vars(t))
    ctx['fonts_css'] = Markup(_fonts_css(font_base))
    ctx['css'] = Markup(_read('house.css'))
    return ctx


def render_html(doc, *, label='', now=None, font_base=None):
    """The document as HTML. For a browser (a preview), `font_base` says where the page serves the faces
    (house.css's @media screen then lays the document out as sheets of paper)."""
    ctx = context(doc, label=label, now=now, font_base=font_base)
    tpl = _env.get_template(ctx['k']['template'] + '.html.j2')
    return tpl.render(**ctx)


_OLD_CREDIT = re.compile(r'^חשבונית זיכוי כנגד (\S+)\s*[—-]\s*(.*)$')


def _payment(d, amount):
    return {'method': d.get('payment_method') or 'מזומן', 'amount': amount, 'date': d.get('doc_date'),
            'cheque_number': d.get('cheque_number') or '', 'bank': d.get('cheque_bank') or '',
            'branch': d.get('cheque_branch') or '', 'due_date': d.get('cheque_due_date') or ''}


def from_model(m):
    """A ledger model (a doc_models dataclass, or a HouseDoc) as the house's document dict.

    The corpus models were drawn for INDOX's synthetic documents; here they become the business's own:
    a receipt's or an invoice-receipt's one payment becomes a payment row, a balance sheet a statement,
    a delivery address a note. A credit the ledger issued before DGO-2029 — an INVOICE with negative
    prices and «חשבונית זיכוי כנגד <n> — <reason>» — is drawn as what it is, a credit note naming its invoice."""
    if not dataclasses.is_dataclass(m):
        return dict(m.to_dict())
    d = dataclasses.asdict(m)
    t = d['doc_type'] = m.DOC_TYPE
    if t == 'RECEIPT':
        d['payments'] = [_payment(d, d.get('amount'))]
    elif t == 'INVOICE_RECEIPT':
        d['payments'] = [_payment(d, m.amount_paid)]
    elif t == 'BALANCE_SHEET':
        d['doc_type'] = 'STATEMENT'
        d['statement'] = {'opening_balance': 0, 'rows': [
            {'date': l.get('doc_date'), 'kind': '', 'ref': ' · '.join(x for x in [l.get('ref_id'), l.get('ref2')] if x),
             'details': l.get('details'), 'debit': l.get('debit'), 'credit': l.get('credit')} for l in d.pop('lines', [])]}
    elif t == 'SHIPMENT' and d.get('delivery_address'):
        d['notes'] = 'כתובת למשלוח: ' + d['delivery_address']
    note = (d.get('details_note') or '').strip()
    old = _OLD_CREDIT.match(note) if t == 'INVOICE' else None
    if t == 'CREDIT_NOTE':
        d['refs'] = {'invoice': {'number': d.get('original_invoice'), 'date': d.get('original_date')}}
    elif old and (getattr(m, 'total_due', 0) or 0) < 0:
        d['doc_type'] = 'CREDIT_NOTE'
        d['refs'] = {'invoice': {'number': old.group(1)}}
        d['reason'] = old.group(2)
    elif note:
        d['notes'] = note
    if d.get('printed_note'):
        d['notes'] = '\n\n'.join(x for x in [d.get('notes'), d['printed_note']] if x)
    if isinstance(d.get('bank'), dict) and not any(d['bank'].values()):
        d.pop('bank')
    return d


def render_ledger(model, fmt='pdf', dpi=200, label='', brand=None, now=None):
    """What the ledger issues and serves: the model drawn in the house style (in `brand`, the business's
    token overrides, when it has one); `png` is the first page. `now` is the minute the footer says it was
    produced — one minute for an original and the copy drawn with it."""
    doc = from_model(model)
    if brand:
        doc['brand'] = brand
    pdf = render_pdf(doc, label=label, now=now)
    if fmt != 'png':
        return pdf
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    d = fitz.open(stream=pdf, filetype='pdf')
    png = d[0].get_pixmap(dpi=dpi).tobytes('png')
    d.close()
    return png


def printed_label(doc_type, served):
    """The label a document prints: «מקור» on the first copy of a document of the books, «העתק» on every
    other; a commercial document (a quote, a payment request, an agreement…) prints none (DGO-2029)."""
    try:
        family = catalogue.kind(doc_type)['family']
    except KeyError:
        family = 'tax'
    if family not in ('tax', 'book'):
        return ''
    return 'העתק' if served else 'מקור'


def render_pdf(doc, *, label='', now=None, archive=True):
    """The PDF. `archive` makes it PDF/A-3b and embeds the document's own data (dgo-document.json), so
    the file still says what it is, in data, years from now."""
    from weasyprint import HTML, Attachment
    html = render_html(doc, label=label, now=now)
    kw = {}
    if archive:
        data = json.dumps(doc, ensure_ascii=False, indent=1, default=str).encode('utf-8')
        kw['attachments'] = [Attachment(string=data, name='dgo-document.json',
                                        description='The document as data (DGO documents)')]
        kw['pdf_variant'] = 'pdf/a-3b'
    return HTML(string=html, base_url=FONTS, url_fetcher=_fetcher()).write_pdf(**kw)


#: how another system's face says «original» (a PDF may keep a Hebrew word in reading or in visual order)
_ORIGINAL_WORDS = ('מקור', 'רוקמ', 'מקור:', ':רוקמ')


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:                                    # older PyMuPDF
        import fitz
    return fitz


def stamp_copy(pdf, label='העתק', note=''):
    """A copy of a document another system issued (DGO-2042: A business's earlier documents): its own bytes, with every
    «מקור» its face prints taken off and «העתק» drawn where it stood — a copy that still reads «מקור» is a second
    original (Instruction 36; the fifth reader) — and a mark in the top corner naming where it came from. Nothing else
    of the page changes. The marks are drawn by the house renderer (Hebrew shaped right, one of the two faces) and
    laid over the page as vector (PyMuPDF show_pdf_page); the word is removed by a redaction of its text only."""
    from weasyprint import HTML
    fitz = _fitz()
    ink = tokens()['colour']['credit']

    def drawn(page_css, box_css, inner):
        html = ('<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><style>' + _fonts_css() +
                f'@page {{ {page_css}; margin: 0 }} html, body {{ margin: 0; background: transparent }}'
                f'.s {{ font-family: "Heebo"; direction: rtl; color: {ink}; border: 0.5mm solid {ink};'
                ' border-radius: 1.6mm; font-weight: 800; background: rgba(255, 255, 255, .92); text-align: center;'
                f' box-sizing: border-box; {box_css} }}'
                '.s small { display: block; font-size: 6.8pt; font-weight: 500 }'
                f'</style></head><body><div class="s">{inner}</div></body></html>')
        return fitz.open(stream=HTML(string=html, base_url=FONTS, url_fetcher=_fetcher()).write_pdf(), filetype='pdf')

    small = f'<small>{view.esc(note)}</small>' if note else ''
    corner = drawn('size: A4', 'position: absolute; top: 7mm; left: 7mm; padding: 1.2mm 3.2mm; font-size: 11pt',
                   view.esc(label) + small)
    cover = drawn('size: 30mm 11mm', 'width: 30mm; height: 11mm; padding-top: 1.6mm; font-size: 14pt',
                  view.esc(label))
    doc = fitz.open(stream=pdf, filetype='pdf')
    try:
        for page in doc:
            hits = [fitz.Rect(w[:4]) for w in page.get_text('words') if w[4] in _ORIGINAL_WORDS]
            for r in hits:
                page.add_redact_annot(r)
            if hits:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
                for r in hits:
                    page.show_pdf_page(fitz.Rect(r.x0 - 6, r.y0 - 3, r.x1 + 6, r.y1 + 3), cover, 0,
                                       overlay=True, keep_proportion=False)
            page.show_pdf_page(page.rect, corner, 0, overlay=True, keep_proportion=False)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
        corner.close()
        cover.close()


def pages_html(pdf, title=''):
    """A stored PDF as the screen shows a document beside its record — each page an image on a sheet — for a document
    the house did not draw (an imported one): redrawing it from its summary would show what was never issued."""
    import base64
    fitz = _fitz()
    doc = fitz.open(stream=pdf, filetype='pdf')
    try:
        pages = [base64.b64encode(p.get_pixmap(dpi=110).tobytes('png')).decode('ascii') for p in doc]
    finally:
        doc.close()
    t = tokens()['colour']
    imgs = ''.join(f'<img alt="עמוד {i}" src="data:image/png;base64,{b}">' for i, b in enumerate(pages, 1))
    return ('<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f'<title>{view.esc(title)}</title><style>html, body {{ margin: 0; background: {t["wash"]} }}'
            'body { width: 210mm; margin: 0 auto; padding: 6mm 0 }'
            f'img {{ display: block; width: 210mm; margin: 0 auto 6mm; background: {t["paper"]};'
            ' box-shadow: 0 1mm 4mm rgba(0, 0, 0, .18) }</style></head>'
            f'<body>{imgs}</body></html>')
