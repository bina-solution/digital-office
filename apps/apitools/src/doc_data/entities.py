"""Single-business entities: business settings (the issuer), customers, items.

This deployment serves ONE business. `business_settings` is a singleton row: the issuer used on every
document; `customers` and `items` are its address book and catalog. No tenancy — one deployment, one business.

WHO THE BUSINESS IS, IS NOT DEFINED HERE (DGO-2048). «זהות» (digital-assets, `GET /api/brand`, brand.v1) is the
one place an office defines its business: the name, the business number and its kind, the address, phone and
email, the site, the logo, the colour, who signs, the bank. With `BRAND_URL` set:
  * every field «זהות» holds is the document's; a field it held and no longer holds is cleared here too; a field
    it never held keeps the ledger's own (older) value and is named in `identity.missing`;
  * the row keeps a MIRROR of the last answer (and `identity_held`, which fields it held), written only right
    after a fresh answer and only to those columns — so a document is never drawn issuer-less while «זהות» is
    out of reach, and a save of the ledger's own settings in the same instant is never written over;
  * a change in «זהות» reaches the documents within BRAND_TTL_SECONDS (30); an issued document keeps the issuer
    it was issued with (its own snapshot);
  * a save through `/business` changes the ledger's own settings (VAT, numbering) and refuses to change a field
    «זהות» holds (IdentityHeld → 409, with the fields and where to change them).

WHO THE CUSTOMERS ARE, IS NOT DEFINED HERE EITHER (DGO-2101). «ישויות» (entities, entities.v1) keeps everyone the
business works with; once it runs in the office, `/customers` is its customers (see «the customers» below).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .db import Cursor

log = logging.getLogger(__name__)

SINGLETON = 'default'


# ── business settings (singleton issuer) ────────────────────────────────────
_DEFAULT_SETTINGS = {
    'id': SINGLETON, 'onboarded': False,
    'name': '', 'company_id': '', 'business_type': 'murshe',   # patur | murshe | company
    'street': '', 'city': '', 'zip': '', 'phone': '', 'fax': '', 'email': '',
    'logo_b64': '', 'vat_pct': 18.0, 'vat_registered': True,
    'default_series': 'A', 'doc_start': 0, 'bank_name': '', 'bank_branch': '', 'bank_account': '',
    # how the business's documents present it (DGO-2029): the name in Latin letters, the site, the mark
    # ('i0' = the office's own; '' = the logo above, else the initial), who signs and as what, the brand
    # (a JSON text of house-token overrides: {"colour": {"brand": "#…"}})
    'name_en': '', 'website': '', 'mark': '', 'signatory': '', 'signatory_title': '', 'brand': '',
    # the types whose numbers continue a series the business brought with it (DGO-2042), a JSON text
    # {"RECEIPT": 1001, "PAYMENT_REQUEST": 2001}: each such type numbers plainly (on from its last imported number) and does not
    # start again with the year. Written by the history import (store.import_issued), not typed.
    'series_start': '',
    # which identity fields «זהות» held at its last answer (a JSON list, DGO-2048): one it held and no longer holds
    # is cleared here too, and one it holds is never changed by a save, even while «זהות» is out of reach
    'identity_held': '',
    # 'entities' once this ledger's customers moved to «ישויות» (DGO-2101): from then on it is the list, and an
    # answer it does not give is said, never taken from this ledger's old table. Written by the move, not typed.
    'parties_from': '',
}


# ── the business's identity, read from «זהות» (DGO-2048) ─────────────────────
#: where «זהות» answers; empty = this office keeps its identity in the row alone (a ledger with no «זהות»)
BRAND_URL = (os.environ.get('BRAND_URL') or '').strip().rstrip('/')
#: where the owner edits it — what the screens link to (the console's address of the app)
IDENTITY_EDIT_URL = (os.environ.get('IDENTITY_EDIT_URL') or '/#/m/digital-assets').strip()
BRAND_TTL = float(os.environ.get('BRAND_TTL_SECONDS') or 30)
#: the row's columns that ARE the business's identity: a value «זהות» holds for one of them wins
IDENTITY_COLUMNS = ('name', 'name_en', 'company_id', 'business_type', 'street', 'city', 'zip', 'phone', 'email',
                    'website', 'logo_b64', 'signatory', 'signatory_title', 'bank_name', 'bank_branch', 'bank_account')
#: the house tones the business's colour gives (house.family) — cleared again when «זהות» stops holding a colour
COLOUR_KEYS = ('brand', 'brand_deep', 'brand_night', 'accent', 'accent_soft', 'wash', 'wash_line')
_BRAND = {'at': 0.0, 'fields': None, 'color': '', 'color2': '', 'error': '', 'unmapped': []}
_LOGO = {'url': '', 'b64': ''}


class IdentityHeld(ValueError):
    """A save tried to change what «זהות» defines (DGO-2048): the fields, and where they are changed."""

    def __init__(self, fields):
        self.fields = sorted(fields)
        super().__init__('פרטי העסק מוגדרים ב«זהות» — שם משנים אותם: ' + ', '.join(self.fields))


def _text(v):
    return v.strip() if isinstance(v, str) else ''


def _entity_type(text):
    """«זהות»'s kind of business → the ledger's, read the way a person types it: «עוסק פטור» with a non-breaking
    space, «חברה בעמ» without its gershayim, «פטור» alone. A VAT-free business must never fall through to the
    ledger's default «מורשה» at 18% because of how a space was typed (the second reader, DGO-2048). A kind the
    ledger has no type for (עמותה) is None: the ledger keeps its own, and says so (`identity.unmapped`)."""
    t = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text or '')).replace('״', '"').replace("''", '"').strip()
    if not t:
        return None
    if 'פטור' in t:
        return 'patur'
    if 'מורשה' in t or 'שותפות' in t:
        return 'murshe'
    if 'חברה' in t or re.search(r'בע"?מ|בערבון מוגבל', t):
        return 'company'
    return None


def _address(text):
    """«זהות»'s address (one free text) as the ledger's street, city and zip: «אסף שמחוני 19, פתח תקווה» →
    street «אסף שמחוני 19», city «פתח תקווה». A trailing country goes; a 5- or 7-digit part is the zip."""
    parts = [p.strip() for p in re.split(r'[,\n،]', text or '') if p.strip()]
    if len(parts) > 1 and parts[-1].lower() in ('ישראל', 'israel', 'il'):
        parts.pop()
    street, city, zipc = (parts[0] if parts else ''), [], ''
    for p in parts[1:]:
        if re.fullmatch(r'\d{5}(?:\d{2})?', p.replace(' ', '')):
            zipc = p.replace(' ', '')
        else:
            city.append(p)
    return street, ', '.join(city), zipc


def _il_phone(phone):
    """An Israeli number as a Hebrew document prints it: «זהות» may hold it in the international form the
    networks want (+972 50-000-0001), which broke across two lines in the page's right-to-left text (DGO-2048).
    050-000-0001 for a mobile, 03-000-0002 for a landline; any other number stays as written."""
    digits = re.sub(r'\D', '', phone or '')
    if not (phone or '').lstrip().startswith(('+972', '00972', '972')) or len(digits) < 11:
        return phone
    local = '0' + digits[digits.index('972') + 3:]
    if len(local) == 10:
        return f'{local[:3]}-{local[3:6]}-{local[6:]}'
    if len(local) == 9:
        return f'{local[:2]}-{local[2:5]}-{local[5:]}'
    return phone


def _logo_bytes(logo):
    """The active logo as base64 — its 512-px rendition (`png`), never the master, which can be megabytes in
    the row and in every document — fetched once per file (its address is its content hash) from where «זהות»
    answered: the address in the answer is «זהות»'s own name for itself, which another office cannot resolve.
    A logo that cannot be fetched is '' and keeps the last one: it never stops the rest of the identity."""
    url = ((logo or {}).get('png') or (logo or {}).get('url')) if isinstance(logo, dict) else ''
    m = re.search(r'/files/[0-9a-f]{64}\.[a-z0-9]{1,6}(?:\?px=\d{1,4})?$', url or '')
    if not m:
        return ''
    url = BRAND_URL + m.group(0)
    if _LOGO['url'] != url:
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                _LOGO.update(url=url, b64=base64.b64encode(r.read()).decode())
        except urllib.error.HTTPError as e:   # «זהות» answered and said why: its words go to the log (G66)
            log.warning('the logo was not fetched from «זהות» (%s): %s', e.code,
                        e.read()[:300].decode('utf-8', 'replace'))
            return ''
        except Exception as e:  # noqa: BLE001 — out of reach
            log.warning('the logo was not fetched from «זהות»: %s', type(e).__name__)
            return ''
    return _LOGO['b64']


def identity_from_brand(b):
    """The row's identity columns from a `brand.v1` answer: only the fields «זהות» holds (a missing one is absent),
    and the kinds of business it holds that the ledger has no type for."""
    out, unmapped = {}, []
    put = lambda k, v: out.__setitem__(k, v) if v else None  # noqa: E731
    put('name', _text(b.get('name')) or _text(b.get('legal_name')))
    put('name_en', _text(b.get('name_en')))
    number = _text(b.get('business_number'))
    put('company_id', re.sub(r'\D', '', number) or number)
    kind = _entity_type(_text(b.get('entity_type')))
    put('business_type', kind)
    if _text(b.get('entity_type')) and not kind:
        unmapped.append('business_type')
    if _text(b.get('address')):
        out['street'], out['city'], out['zip'] = _address(_text(b.get('address')))
    for k in ('email', 'signatory', 'signatory_title', 'bank_name', 'bank_branch', 'bank_account'):
        put(k, _text(b.get(k)))
    put('phone', _il_phone(_text(b.get('phone'))))
    put('website', re.sub(r'^https?://', '', _text(b.get('website'))).rstrip('/'))
    put('logo_b64', _logo_bytes(b.get('logo')))
    return out, unmapped


def _read_brand():
    """(columns, fresh): what «זהות» holds — fresh=True only from an answer this call received; the last answer
    while it is out of reach or inside the TTL; (None, False) when there has been none."""
    if not BRAND_URL:
        return None, False
    now = time.time()
    if _BRAND['at'] and now - _BRAND['at'] < BRAND_TTL:
        return _BRAND['fields'], False
    _BRAND['at'] = now                       # one try per TTL, answered or not: a down «זהות» is not hammered
    before = _BRAND['error']
    try:
        req = urllib.request.Request(BRAND_URL + '/api/brand', headers={'accept': 'application/json',
                                                                        'x-actor': 'apitools'})
        # 2 s: the health probe reads /business every 30 s, and one slow answer over a link must not make the
        # probe time out (a health flap re-lists the edge's routes); the rest of the TTL is served from memory
        with urllib.request.urlopen(req, timeout=2) as r:
            answer = json.loads(r.read().decode('utf-8'))
        b = answer.get('brand') if isinstance(answer, dict) else None
        b = b if isinstance(b, dict) else {}
        fields, unmapped = identity_from_brand(b)
        _BRAND.update(fields=fields, unmapped=unmapped, color=_text(b.get('color')),
                      color2=_text(b.get('color_secondary')), error='')
        if before:
            log.info('«זהות» answers again at %s', BRAND_URL)
        return fields, True
    except urllib.error.HTTPError as e:      # «זהות» answered and said why: its words go to the log (G66)
        _BRAND['error'] = 'HTTP %s' % e.code
        body = e.read()[:300].decode('utf-8', 'replace')
        if _BRAND['error'] != before:        # said once when it starts, not every 30 s in every worker
            log.warning('«זהות» at %s answered %s: %s — the last identity read is used', BRAND_URL, e.code, body)
    except Exception as e:  # noqa: BLE001 — out of reach: keep the last answer (or the mirror in the row)
        _BRAND['error'] = type(e).__name__
        if _BRAND['error'] != before:
            log.warning('«זהות» did not answer at %s (%s): the last identity read is used', BRAND_URL,
                        _BRAND['error'])
    return _BRAND['fields'], False


def _row():
    with Cursor() as cur:
        row = cur.run('SELECT * FROM business_settings WHERE id=%s', (SINGLETON,)).one()
    if not row:
        return dict(_DEFAULT_SETTINGS)
    row['onboarded'] = bool(row.get('onboarded'))
    row['vat_registered'] = bool(row.get('vat_registered'))
    return row


#: columns a save of the whole row never writes back — written alone (`_write_cols`), by what owns them: the move of
#: the customers to «ישויות» marks `parties_from`, and a settings save that read the row a moment before must not
#: unmark it (the second reader, DGO-2101)
_WRITTEN_ALONE = ('parties_from',)


def _write(m):
    cols = [k for k in _DEFAULT_SETTINGS if k != 'id' and k not in _WRITTEN_ALONE]
    with Cursor() as cur:
        exists = cur.run('SELECT 1 FROM business_settings WHERE id=%s', (SINGLETON,)).one()
        if exists:
            sets = ', '.join('%s=%%s' % c for c in cols)
            cur.run('UPDATE business_settings SET %s, updated_at=now() WHERE id=%%s' % sets,
                    tuple(m[c] for c in cols) + (SINGLETON,))
        else:
            ph = ', '.join(['%s'] * (len(cols) + 1))
            cur.run('INSERT INTO business_settings (id, %s) VALUES (%s)' % (', '.join(cols), ph),
                    (SINGLETON,) + tuple(m[c] for c in cols))


def _write_cols(vals):
    """Write only these columns (the identity mirror), never the row: a save of the ledger's own settings (its
    numbering, its series) made in the same instant stays as it was saved (the second reader, DGO-2048)."""
    cols = sorted(vals)
    with Cursor() as cur:
        if cur.run('SELECT 1 FROM business_settings WHERE id=%s', (SINGLETON,)).one():
            cur.run('UPDATE business_settings SET %s, updated_at=now() WHERE id=%%s'
                    % ', '.join('%s=%%s' % c for c in cols), tuple(vals[c] for c in cols) + (SINGLETON,))
            return
    _write({**_DEFAULT_SETTINGS, **vals})       # the first row: the defaults with these values (outside the cursor)
    alone = {c: vals[c] for c in vals if c in _WRITTEN_ALONE}
    if alone:                                   # …and what a row write leaves out, now that the row is there
        _write_cols(alone)


def _held(row):
    """The identity fields «זהות» held at its last answer, as the row remembers them."""
    try:
        v = json.loads(row.get('identity_held') or '[]')
    except (TypeError, ValueError):
        return set()
    return {x for x in v if isinstance(x, str)} if isinstance(v, list) else set()


def _brand_json(current, color, color2='', clear=False):
    """The row's house-token overrides with the brand tones of the colour «זהות» holds (house.family: the whole
    family, never `brand` alone — that drew a page half in the business's colour and half in emerald); `clear`
    takes those tones off again when «זהות» held a colour and no longer does."""
    from ..doc_gen.house import family
    try:
        v = json.loads(current or '{}')
        v = v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        v = {}
    colour = dict(v['colour']) if isinstance(v.get('colour'), dict) else {}
    tones = family(color, color2) if color else {}
    if tones:
        colour.update(tones)
    elif clear:
        colour = {k: c for k, c in colour.items() if k not in COLOUR_KEYS}
    else:
        return current or ''
    v = {**v, 'colour': colour} if colour else {k: x for k, x in v.items() if k != 'colour'}
    return json.dumps(v, ensure_ascii=False) if v else ''


def _overlay(row, fields):
    """The identity columns as «זהות» defines them now: a field it holds → its value; one it held at its last
    answer and holds no more → cleared here too (the kind of business stays: a document must have one); one it
    never held → the ledger's own, untouched. With what it holds now, to remember for its next answer."""
    before = _held(row)
    out = {c: fields[c] for c in IDENTITY_COLUMNS if c in fields}
    out.update({c: '' for c in IDENTITY_COLUMNS if c not in fields and c in before and c != 'business_type'})
    out['brand'] = _brand_json(row.get('brand'), _BRAND['color'], _BRAND['color2'], clear='_colour' in before)
    out['identity_held'] = json.dumps(sorted(set(fields) | ({'_colour'} if _BRAND['color'] else set())))
    return out


def _derive(m):
    """What follows from the business's kind: an עוסק פטור charges no VAT; onboarded = a name and a number."""
    if m.get('business_type') == 'patur':
        m['vat_pct'] = 0.0
        m['vat_registered'] = False
    m['onboarded'] = bool(m.get('name') and m.get('company_id'))
    return m


def get_business():
    """The ledger's settings, with the business as «זהות» defines it. `identity` says where each part came from:
    `source` brand (an answer), mirror («זהות» out of reach: the last answer kept in the row) or settings (no
    «זהות» for this ledger); `from_brand` the fields a save may not change; `missing`; `unmapped`."""
    fields, fresh = _read_brand()           # BEFORE the row: no network between reading the row and writing it
    row = _row()
    if fields is None:
        held = sorted(_held(row) - {'_colour'}) if BRAND_URL else []
        row['identity'] = {'source': 'mirror' if held else 'settings', 'url': IDENTITY_EDIT_URL if BRAND_URL else '',
                           'reachable': not BRAND_URL, 'from_brand': held, 'missing': [], 'unmapped': []}
        return row
    over = _overlay(row, fields)
    m = {**row, **over}
    if m.get('business_type') != row.get('business_type') and row.get('business_type') == 'patur':
        m['vat_pct'], m['vat_registered'] = 18.0, True     # no longer an עוסק פטור: VAT again (as save_business)
    m = _derive(m)
    keep = (*over, 'vat_pct', 'vat_registered', 'onboarded')
    if fresh and any(m.get(k) != row.get(k) for k in keep):
        try:
            _write_cols({k: m[k] for k in keep})  # the mirror, right after an answer: one write per change, not per read
        except Exception as e:  # noqa: BLE001 — a mirror that cannot be written is not a reason to fail a read
            log.warning('the identity mirror was not written: %s', type(e).__name__)
    m['identity'] = {'source': 'brand', 'url': IDENTITY_EDIT_URL, 'reachable': not _BRAND['error'],
                     'from_brand': sorted(fields),
                     'missing': [k for k in IDENTITY_COLUMNS if k not in fields and k not in ('city', 'zip')],
                     'unmapped': list(_BRAND['unmapped'])}
    return m


def _same(a, b):
    return str('' if a is None else a).strip() == str('' if b is None else b).strip()


def save_business(patch, actor='api'):
    cur_row = get_business()
    held = set((cur_row.pop('identity', None) or {}).get('from_brand') or [])
    patch = {k: v for k, v in (patch or {}).items() if k not in ('identity_held', 'parties_from')}
    # a field «זהות» holds is defined there, not here (DGO-2048): sent back as it is, it is left alone; sent with
    # another value, the save is refused and says where — never a «נשמר» over a value that comes back
    changed = [k for k, v in patch.items() if k in held and not _same(v, cur_row.get(k))]
    if changed:
        raise IdentityHeld(changed)
    patch = {k: v for k, v in patch.items() if k not in held}
    m = {**cur_row, **{k: v for k, v in patch.items() if k in _DEFAULT_SETTINGS}}
    try:
        m['doc_start'] = int(m.get('doc_start') or 0)   # numbering start comes from a text form
    except (TypeError, ValueError):
        m['doc_start'] = 0
    # a business_type of 'patur' (עוסק פטור) does not charge VAT
    if m.get('business_type') == 'patur':
        m['vat_pct'] = 0.0
        m['vat_registered'] = False
    # …and one that leaves it in THIS save (an עוסק פטור becomes מורשה or a company) charges it again: its 0% stayed
    # behind and its tax invoices came out with no VAT at all (DGO-2029). Only then: a מורשה or a company at 0%
    # on purpose (Eilat, zero-rated sales) keeps its 0% through every later save of its settings.
    elif (cur_row.get('business_type') == 'patur' and not float(m.get('vat_pct') or 0)
          and 'vat_pct' not in (patch or {})):
        m['vat_pct'] = 18.0
        m['vat_registered'] = True
    m['onboarded'] = bool(m.get('name') and m.get('company_id'))
    _write(m)
    return get_business()


def _logo(b64):
    """The uploaded logo as the document draws it: an SVG text, or a data: URI of the image."""
    b64 = (b64 or '').strip()
    if not b64 or b64.startswith('data:image/') or b64.startswith('<svg'):
        return b64
    try:
        head = base64.b64decode(b64[:64] + '=' * (-len(b64[:64]) % 4))
    except Exception:
        return ''
    kind = ('png' if head.startswith(b'\x89PNG') else 'jpeg' if head.startswith(b'\xff\xd8')
            else 'webp' if head[8:12] == b'WEBP' else 'gif' if head.startswith(b'GIF8') else 'svg+xml')
    return f'data:image/{kind};base64,{b64}'


def issuer_party():
    """The business as a doc_models Party dict, for use as document supplier."""
    b = get_business()
    return {'name': b['name'], 'company_id': b['company_id'], 'street': b['street'],
            'city': b['city'], 'zip': b['zip'], 'phone': b['phone'], 'fax': b['fax'],
            'email': b['email'], 'vat_file_no': b['company_id'],
            'tax_status': b.get('business_type', 'murshe'),
            'name_en': b.get('name_en') or '', 'website': b.get('website') or '', 'mark': b.get('mark') or '',
            'logo': _logo(b.get('logo_b64')), 'signatory': b.get('signatory') or '',
            'signatory_title': b.get('signatory_title') or ''}


def issuer_bank():
    """The business's bank account as a document prints it, or None when the settings hold none."""
    b = get_business()
    if not any(b.get(k) for k in ('bank_name', 'bank_branch', 'bank_account')):
        return None
    return {'bank': b.get('bank_name') or '', 'branch': b.get('bank_branch') or '', 'account': b.get('bank_account') or ''}


def brand():
    """The business's brand — house-token overrides — or {} (a broken JSON text is no brand, not an error)."""
    import json
    try:
        v = json.loads(get_business().get('brand') or '{}')
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def series_starts(business=None):
    """{doc_type: first number} of the series that continue across years (see _DEFAULT_SETTINGS); {} when none."""
    import json
    try:
        v = json.loads((business or get_business()).get('series_start') or '{}')
    except (TypeError, ValueError):
        return {}
    out = {}
    for t, n in (v.items() if isinstance(v, dict) else []):
        try:
            if int(n) >= 1:
                out[str(t).upper()] = int(n)
        except (TypeError, ValueError):
            continue
    return out


# ── generic CRUD for customers / items ──────────────────────────────────────
_TABLES = {
    'customers': ['name', 'company_id', 'street', 'city', 'zip', 'phone', 'email', 'notes'],
    'items': ['name', 'sku', 'description', 'unit', 'unit_price'],
}


def _list(table, q=None, limit=500):
    cols = _TABLES[table]
    sql = 'SELECT id, %s, created_at FROM %s' % (', '.join(cols), table)
    args = ()
    if q:
        sql += ' WHERE name ILIKE %s OR company_id ILIKE %s' if table == 'customers' \
               else ' WHERE name ILIKE %s OR sku ILIKE %s'
        args = ('%' + q + '%', '%' + q + '%')
    sql += ' ORDER BY name LIMIT %s'
    args += (int(limit),)
    with Cursor() as cur:
        return cur.run(sql, args).all()


def _create(table, body):
    cols = _TABLES[table]
    rid = table[:3] + '_' + uuid.uuid4().hex[:14]
    vals = [body.get(c) for c in cols]
    with Cursor() as cur:
        cur.run('INSERT INTO %s (id, %s) VALUES (%s)' % (table, ', '.join(cols),
                ', '.join(['%s'] * (len(cols) + 1))), (rid,) + tuple(vals))
    return _get(table, rid)


def _get(table, rid):
    cols = _TABLES[table]
    with Cursor() as cur:
        return cur.run('SELECT id, %s, created_at FROM %s WHERE id=%%s' % (', '.join(cols), table),
                       (rid,)).one()


def _update(table, rid, patch):
    cols = [c for c in _TABLES[table] if c in (patch or {})]
    if not cols:
        return _get(table, rid)
    sets = ', '.join('%s=%%s' % c for c in cols)
    with Cursor() as cur:
        cur.run('UPDATE %s SET %s, updated_at=now() WHERE id=%%s' % (table, sets),
                tuple(patch[c] for c in cols) + (rid,))
    return _get(table, rid)


def _delete(table, rid):
    with Cursor() as cur:
        cur.run('DELETE FROM %s WHERE id=%s' % table if False else
                'DELETE FROM %s WHERE id=%%s' % table, (rid,))
    return {'deleted': rid}


# ── the customers: «ישויות» (DGO-2101) ──────────────────────────────────────
# «ישויות» (entities, entities.v1, ai/context/business-domains.md) is the one place an office keeps everyone the
# business works with, each with the roles it holds. Once it runs in the office, `/customers` IS its customers, in
# the table's shape below (the id is the entity's, `ent_…`): one added or changed from a document is added or
# changed there, and one removed is archived there (never deleted: a document may name it). A document keeps its
# customer as it was issued — its own snapshot, named by the business number — so nothing issued changes.
#
# THE MOVE, once. The first time this ledger finds «ישויות» answering AS ITSELF (its /healthz names the service), it
# hands it the customers of its own table — each named by its id, `ledger:cus_…`, so a second hand-over keeps nothing
# twice; a row with no name is named by its number, email or phone, a value too long is cut, so none is refused — and
# marks its row `parties_from = <where «ישויות» answered>`, then hands over once more what came in meanwhile. From
# then on «ישויות» is the list: when it does not answer, that is said (EntitiesUnreachable → 502), never answered
# from the old table, which would be a second list the moment «ישויות» came back — nor when ENTITIES_URL is emptied
# after the move. Until the move has worked — an office that runs no «ישויות», one whose «ישויות» has not answered
# yet, a move that failed half-way (a wrong token, a timeout) — the old table stays the list, as before; a probe
# that failed is not asked again for PROBE_TTL seconds. Pointed at another «ישויות» since (the herd's one, through a
# link), the old table is handed to it as well and the mark follows; the customers made in the first one are its
# own to export. A 404 is «no such entity» only in «ישויות»' own words (a JSON `detail` «no such …»): a link's door
# with no such app answers an empty 404, and that is not an answer.
ENTITIES_URL = (os.environ.get('ENTITIES_URL') or '').strip().rstrip('/')
ENTITIES_TOKEN = os.environ.get('ENTITIES_API_TOKEN') or ''
PROBE_TTL = 30.0
_MOVED = {'to': '', 'said': '', 'probe_at': -PROBE_TTL}
_MOVING = threading.Lock()
_NAME_MAX, _VALUE_MAX = 200, 2000               # «ישויות»' own limits (apps/entities/store.py)


class EntitiesRefused(ValueError):
    """«ישויות» refused the change, in its own words (a blank name, a kind of business off its list) → 400."""


class EntitiesUnreachable(RuntimeError):
    """«ישויות» holds this office's customers and did not answer → 502, said as it is."""


class CustomerNotFound(LookupError):
    """«ישויות» says it has no such entity → 404."""


def _entities(method, path, body=None, timeout=5):
    """One call to «ישויות» with the office's token; None for its own «no such entity» (a 404 it words)."""
    req = urllib.request.Request(
        ENTITIES_URL + path, method=method,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'accept': 'application/json', 'content-type': 'application/json', 'x-actor': 'documents',
                 'authorization': 'Bearer ' + ENTITIES_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        text = e.read().decode('utf-8', 'replace')[:400]
        try:
            said = json.loads(text)
        except ValueError:
            said = None
        detail = said.get('detail') if isinstance(said, dict) and said.get('detail') else (text or '(an empty body)')
        if e.code == 404 and str(detail).startswith('no such'):
            return None
        if e.code == 400:
            raise EntitiesRefused(str(detail)) from None
        raise EntitiesUnreachable('«ישויות» answered %s at %s: %s' % (e.code, ENTITIES_URL, detail)) from None
    except urllib.error.URLError as e:
        where = 'does not run in this office' if isinstance(e.reason, socket.gaierror) else 'did not answer'
        raise EntitiesUnreachable('«ישויות» %s (%s: %s)' % (where, ENTITIES_URL, e.reason)) from None
    except (OSError, ValueError) as e:          # a reset connection, a timeout mid-read, a body that is not JSON
        raise EntitiesUnreachable('«ישויות» did not answer at %s: %s' % (ENTITIES_URL, e)) from None


def _cut(v, n):
    return str(v or '').strip()[:n]


def _from_ledger(c):
    """A row of the old table as «ישויות» takes it, never one it refuses: a business number makes it an organization
    with a company record; a row with no name is named by its number, email or phone; a value too long is cut."""
    number = _cut(c.get('company_id'), _VALUE_MAX)
    name = (_cut(c.get('name'), _NAME_MAX) or number[:_NAME_MAX] or _cut(c.get('email'), _NAME_MAX)
            or _cut(c.get('phone'), _NAME_MAX) or 'לקוח %s' % c.get('id'))
    fields = {k: _cut(c.get(k), _VALUE_MAX) for k in ('phone', 'email', 'street', 'city', 'zip', 'notes')
              if _cut(c.get(k), _VALUE_MAX)}
    return {'kind': 'organization' if number else 'person', 'name': name, 'fields': fields,
            'roles': {'customer': {}, **({'company': {'business_number': number}} if number else {})},
            'source': 'ledger:%s' % c.get('id')}


def _hand_over():
    """The old table, all of it, to «ישויות» (idempotent): {created, kept, refused}."""
    rows = [_from_ledger(c) for c in _list('customers', None, limit=100000)]
    if not rows:
        return {'created': 0, 'kept': 0, 'refused': []}
    got = _entities('POST', '/api/import', {'rows': rows}, timeout=120)
    if not isinstance(got, dict) or 'refused' not in got:
        raise EntitiesUnreachable('«ישויות» at %s did not take the hand-over' % ENTITIES_URL)
    return got


def _move(mark):
    """Hand the old table to «ישויות» and mark where it went. True once moved; False — the old table stays the
    list — while it has not worked (said in the log). An office already moved elsewhere (`mark`) is never answered
    from the old table: a failure there is raised."""
    if not _MOVING.acquire(blocking=False):     # another request of this process is moving them right now
        if mark:
            raise EntitiesUnreachable('the customers are being handed to «ישויות» at %s — a moment' % ENTITIES_URL)
        return False
    try:
        try:
            got = _hand_over()
            if got['refused']:
                raise EntitiesUnreachable('«ישויות» at %s refused customers of the old table: %s'
                                          % (ENTITIES_URL, got['refused'][:5]))
            _write_cols({'parties_from': ENTITIES_URL})
            _MOVED['to'] = ENTITIES_URL
        except EntitiesUnreachable as e:
            log.warning('the customers were not moved to «ישויות» yet: %s', e)
            _MOVED['probe_at'] = time.monotonic()
            if mark:
                raise
            return False
        # marked: «ישויות» is the list from here on, whatever happens next. What reached the old table while it was
        # being handed over goes too; a failure of that is only said — this request is still answered from «ישויות»
        # (the second reader: falling back here would write a customer into the old table after the mark)
        try:
            late = _hand_over()
            log.info('the customers moved to «ישויות» at %s: %s created, %s already there (then %s more)',
                     ENTITIES_URL, got.get('created'), got.get('kept'), late.get('created'))
        except EntitiesUnreachable as e:
            log.warning('the customers moved to «ישויות» at %s; the second hand-over failed (%s) — a customer '
                        'made in the old table in that moment is still there', ENTITIES_URL, e)
        return True
    finally:
        _MOVING.release()


def _probe():
    """Does «ישויות» answer here, as itself? A failure is held PROBE_TTL seconds (an office without it pays one
    lookup a while, not one per request)."""
    if time.monotonic() - _MOVED['probe_at'] < PROBE_TTL:
        return False
    try:
        h = _entities('GET', '/healthz', timeout=2)
        if not (isinstance(h, dict) and h.get('service') == 'entities'):
            raise EntitiesUnreachable('%s answered, but not as «ישויות»' % ENTITIES_URL)
        return True
    except EntitiesUnreachable as e:
        _MOVED['probe_at'] = time.monotonic()
        if _MOVED['said'] != str(e):
            log.info('the customers stay in the ledger: %s', e)
            _MOVED['said'] = str(e)
        return False


def _in_entities():
    """Are this office's customers in «ישויות»? The first time it answers, they move there."""
    if ENTITIES_URL and _MOVED['to'] == ENTITIES_URL:
        return True
    mark = _row().get('parties_from') or ''
    if mark and not ENTITIES_URL:
        raise EntitiesUnreachable('the customers moved to «ישויות» (%s), and ENTITIES_URL is empty here' % mark)
    if not ENTITIES_URL:
        return False
    if mark == ENTITIES_URL:
        _MOVED['to'] = mark
        return True
    if not _probe():
        if mark:
            raise EntitiesUnreachable('the customers moved to «ישויות» (%s), and %s does not answer as it'
                                      % (mark, ENTITIES_URL))
        return False
    return _move(mark)


def _customer(p):
    """A party of «ישויות» in the table's shape — what the documents' picker and form read — and the rest of it."""
    return {'id': p.get('entity_id') or '', 'name': p.get('name') or '', 'company_id': p.get('company_id') or '',
            'street': p.get('street') or '', 'city': p.get('city') or '', 'zip': p.get('zip') or '',
            'phone': p.get('phone') or '', 'email': p.get('email') or '', 'notes': p.get('notes') or '',
            'tax_status': p.get('tax_status') or '', 'customer_no': p.get('customer_no') or '',
            'contact_person': p.get('contact_person') or '', 'created_at': None, 'source': 'entities'}


def _entity_id(i):
    if not str(i).startswith('ent_'):
        raise EntitiesRefused('%s is a record of the ledger\'s old table: this office\'s customers are in «ישויות»'
                              % i)
    return urllib.parse.quote(str(i), safe='')


def list_customers(q=None):
    if not _in_entities():
        return _list('customers', q)
    got = _entities('GET', '/api/parties?' + urllib.parse.urlencode({'role': 'customer', 'q': q or ''}))
    if not isinstance(got, dict) or not isinstance(got.get('parties'), list):
        raise EntitiesUnreachable('«ישויות» at %s did not give its list' % ENTITIES_URL)
    return [_customer(p) for p in got['parties']]


def get_customer(i):
    if not _in_entities():
        return _get('customers', i)
    if not str(i).startswith('ent_'):
        return None                             # moved: an old id answers no more — its customer is in «ישויות»
    p = _entities('GET', '/api/entities/%s/party' % _entity_id(i))
    return _customer(p) if p else None


def create_customer(b):
    if not _in_entities():
        return _create('customers', b)
    b = b or {}
    number = str(b.get('company_id') or '').strip()
    fields = {k: str(b.get(k) or '').strip() for k in ('phone', 'email', 'street', 'city', 'zip', 'notes')
              if str(b.get(k) or '').strip()}
    kind = b.get('kind') if b.get('kind') in ('person', 'organization') else ('organization' if number else 'person')
    e = _entities('POST', '/api/entities', {
        'kind': kind, 'name': b.get('name') or '', 'fields': fields,
        'roles': {'customer': {}, **({'company': {'business_number': number}} if number else {})}})
    if not isinstance(e, dict) or not e.get('id'):
        raise EntitiesUnreachable('«ישויות» at %s did not say which entity it made' % ENTITIES_URL)
    return get_customer(e['id'])


def update_customer(i, patch):
    """The table's keys, said in «ישויות»' words: the name and the email a document prints (the legal name, the
    billing address, when the entity has them), the business number on its company record — only when there is a
    number to keep or a record to change (an editor that always sends `company_id: ''` adds no empty one)."""
    if not _in_entities():
        return _update('customers', i, patch)
    eid = _entity_id(i)
    e = _entities('GET', '/api/entities/' + eid)
    if e is None:
        raise CustomerNotFound(i)
    patch = patch or {}
    roles = e.get('roles') or {}
    company, customer = roles.get('company') or {}, roles.get('customer') or {}
    body, role = {'fields': {}}, {'company': {}, 'customer': {}}
    for k in ('phone', 'notes', 'street', 'city', 'zip'):
        if k in patch:
            body['fields'][k] = patch[k]
    if 'email' in patch:
        if customer.get('billing_email'):
            role['customer']['billing_email'] = patch['email']
        else:
            body['fields']['email'] = patch['email']
    if 'name' in patch:
        if company.get('legal_name'):
            role['company']['legal_name'] = patch['name']
        else:
            body['name'] = patch['name']
    if 'company_id' in patch and (str(patch['company_id'] or '').strip() or 'company' in roles):
        role['company']['business_number'] = patch['company_id']
    if body['fields'] or 'name' in body:
        _entities('PATCH', '/api/entities/' + eid, body)
    for r, f in role.items():
        if f:
            _entities('PUT', '/api/entities/%s/roles/%s' % (eid, r), {'fields': f})
    return get_customer(i)


def delete_customer(i):
    """Removed from the documents' customers: an entity that is more than our customer (a supplier, a contact)
    only stops being one; one that is only that is archived (never deleted: a document may name it)."""
    if not _in_entities():
        return _delete('customers', i)
    eid = _entity_id(i)
    e = _entities('GET', '/api/entities/' + eid)
    if e is None:
        raise CustomerNotFound(i)
    if set(e.get('roles') or {}) - {'customer', 'company'}:
        _entities('DELETE', '/api/entities/%s/roles/customer' % eid)
        return {'deleted': i, 'role_removed': 'customer'}
    _entities('POST', '/api/entities/%s/archive' % eid, {'archived': True})
    return {'deleted': i, 'archived': True}


def list_items(q=None): return _list('items', q)
def create_item(b): return _create('items', b)
def get_item(i): return _get('items', i)
def update_item(i, b): return _update('items', i, b)
def delete_item(i): return _delete('items', i)
