"""doc_data.store — business-document management, Green-Invoice / morning.com style.

A document moves through a lifecycle, backed by Postgres (source of truth):

    draft ──issue──▶ issued ──send──▶ sent ──pay──▶ paid
      │                 │
   (editable)         cancel ──▶ cancelled   (+ a CREDIT_NOTE, when it is a tax invoice)

Legal invariants enforced here (see ../doc_models/COMPLIANCE.md):
  • a draft is freely editable; an ISSUED document is immutable (corrections = credit doc)
  • issuing allocates a gapless per (type, series, tax-year) sequence number
  • מקור served once (download marks original_served_at), then העתק; a draft prints טיוטה
  • every transition writes an audit event; rows are SHA-256 chained (tamper evidence)
  • nothing is ever deleted (7-year retention)

The rendered PDF is produced by doc_gen on issue and stored in the row (bytea); a draft
is rendered on the fly for preview. No OCR anywhere in this layer.
"""
from __future__ import annotations

import hashlib
import uuid

from .db import Cursor
from . import signing, allocation, pcn874
from ..doc_models import validate_compliance
from ..doc_models.models import Party, LineItem, BankDetails, BSLine, LEDGER_TYPES, HOUSE_TYPES, HouseDoc
from ..doc_gen.house import catalogue, printed_label, render_ledger as _render_ledger


def render(m, fmt='pdf', label='', brand=None, now=None):
    """A ledger document in the house style (DGO-2029), in the business's own brand (settings → brand).

    A caller that holds a Cursor passes `brand` in, read BEFORE it opened that cursor: reading it here
    opens a second one, and the ledger's lock is not reentrant — issue() hung on exactly that (caught by
    tests/test_ledger_house_unit.py before it shipped)."""
    if brand is None:
        from . import entities
        brand = entities.brand()
    return _render_ledger(m, fmt, label=label, brand=brand, now=now)

DRAFT, ISSUED, SENT, PAID, CANCELLED = 'draft', 'issued', 'sent', 'paid', 'cancelled'
_EDITABLE = {DRAFT}
_TERMINAL = {CANCELLED}

# each document TYPE gets its own numbering series (Israeli practice) — keeps numbers
# unique across types and human-meaningful (INV-2026-00001, IR-2026-00001, …)
TYPE_SERIES = {
    'INVOICE': 'INV', 'INVOICE_RECEIPT': 'IR', 'RECEIPT': 'RC', 'QUOTE': 'QT',
    'ORDER': 'OR', 'SHIPMENT': 'DN', 'BALANCE_SHEET': 'BS', 'CREDIT_NOTE': 'CN',
    # the house's own types (DGO-2029): each its own series, as the catalogue names it
    **{t: catalogue.TYPES[t]['series'] for t in HOUSE_TYPES},
}


# ── model (de)serialisation ────────────────────────────────────────────────
def _model_from_dict(d):
    doc_type = (d.get('doc_type') or '').upper()
    if doc_type in HOUSE_TYPES:
        return HouseDoc(doc_type, **{k: v for k, v in d.items() if k != 'doc_type'})
    cls = LEDGER_TYPES.get(doc_type)
    if cls is None:
        raise ValueError('unknown doc_type %r' % d.get('doc_type'))
    kw = _known(cls, d)
    for pk in ('supplier', 'customer'):
        if isinstance(kw.get(pk), dict):
            kw[pk] = Party(**_known(Party, kw[pk]))
    if isinstance(kw.get('bank'), dict):
        kw['bank'] = BankDetails(**_known(BankDetails, kw['bank']))
    line_cls = BSLine if cls.DOC_TYPE == 'BALANCE_SHEET' else LineItem
    if isinstance(kw.get('lines'), list):
        kw['lines'] = [line_cls(**_known(line_cls, l)) if isinstance(l, dict) else l for l in kw['lines']]
    return cls(**kw)


def _known(cls, d):
    """The keys a model class has. The stored model keeps every key it was given; one its class lacks — a field a
    newer screen sends, a line's `period` — is left out of the object instead of failing the save (DGO-2029: an
    order's `intro` made every save of an order a 400)."""
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


#: the types whose list row shows what their house page prints — a quote of a VAT-registered business prints its
#: VAT and the total with it (DGO-2029: the row said 1,000 where the page said 1,180.00)
_PRINTED_TOTALS = ('QUOTE', 'ORDER')


def _totals(m):
    if m.DOC_TYPE in _PRINTED_TOTALS:
        from ..doc_gen.house import context, from_model
        one = next((g for g in context(from_model(m)).get('groups') or [] if not g['period']), None)
        if one:
            t = one['totals']
            return {'subtotal': float(t['raw_sub']), 'discount': float(t['raw_disc']),
                    'vat': float(t['raw_vat']), 'total': float(t['raw_total'])}
    return {'subtotal': getattr(m, 'subtotal', None),
            'discount': getattr(m, 'discount', None),
            'vat': getattr(m, 'vat', None),
            'total': getattr(m, 'total_due', getattr(m, 'total',
                     getattr(m, 'amount', getattr(m, 'document_total', None))))}


def _chain(cur, core):
    prev = (cur.run('SELECT chain_hash FROM business_documents '
                    'WHERE chain_hash IS NOT NULL ORDER BY issued_at DESC NULLS LAST LIMIT 1'
                    if cur.pg else
                    'SELECT chain_hash FROM business_documents '
                    'WHERE chain_hash IS NOT NULL ORDER BY issued_at DESC LIMIT 1').one() or {})
    base = (prev.get('chain_hash') if prev else None) or 'GENESIS'
    return hashlib.sha256((base + core).encode('utf-8')).hexdigest()


def _event(cur, doc_id, action, detail='', actor='api'):
    cur.run('INSERT INTO business_document_events (doc_id, action, detail, actor) '
            'VALUES (%s,%s,%s,%s)', (doc_id, action, detail[:500], actor))


def _today(fmt='%d/%m/%Y'):
    """The office's day (Asia/Jerusalem). The container's clock is UTC: between midnight and 02:00–03:00 a document
    dated by it carried yesterday — on the 1st, last month; on 1 January, last year (DGO-2029, the third reader)."""
    from ..doc_gen.house import israel_now
    return israel_now().strftime(fmt)


# ── CRUD ───────────────────────────────────────────────────────────────────
def create(model_dict, actor='api'):
    """Create a DRAFT document from a model. No number yet — editable until issued.
    The issuer (supplier) and VAT default come from the business settings singleton
    unless the caller supplied them explicitly."""
    from . import entities
    model_dict = dict(model_dict or {})
    if not model_dict.get('supplier'):
        model_dict['supplier'] = entities.issuer_party()
    doc_type = (model_dict.get('doc_type') or '').upper()
    # every type that prints VAT prints the business's rate — a quote, an order and a proposal too, not 18% by
    # default (DGO-2029: their page and their row now show the total with VAT)
    if 'vat_pct' not in model_dict and (doc_type in ('INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE') or
                                        (doc_type in catalogue.TYPES and catalogue.kind(doc_type).get('vat'))):
        model_dict['vat_pct'] = float(entities.get_business().get('vat_pct', 18) or 0)
    # an עוסק פטור issues no tax invoice, invoice-receipt or credit note — refused here, not discovered at the
    # tax authority (the catalogue says who may issue what)
    status = (model_dict.get('supplier') or {}).get('tax_status') or 'murshe'
    if doc_type in catalogue.TYPES and not catalogue.may_issue(doc_type, status):
        raise ValueError('%s: an %s business does not issue this document' % (doc_type, status))
    if doc_type == 'SHIPMENT' and not model_dict.get('sender_signature'):
        # a delivery note is signed by its sender (§8): the business, in its signatory's name — a converted one
        # carried none and could never be issued (DGO-2029, the third reader)
        sup = model_dict.get('supplier') or {}
        sup = sup if isinstance(sup, dict) else vars(sup)
        model_dict['sender_signature'] = sup.get('signatory') or sup.get('name') or ''
    if doc_type in catalogue.TYPES and catalogue.kind(doc_type)['bank'] and not model_dict.get('bank'):
        bank = entities.issuer_bank()           # a document that asks for payment carries the account
        if bank:
            model_dict['bank'] = bank
    m = _model_from_dict(model_dict)
    t = _totals(m)
    did = 'doc_' + uuid.uuid4().hex[:16]
    with Cursor() as cur:
        cur.run(
            'INSERT INTO business_documents (id, doc_type, status, issuer_id, customer_id, '
            'customer_name, subtotal, discount, vat, total, allocation_number, allocation_status, '
            'model) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (did, m.DOC_TYPE, DRAFT, m.supplier.company_id if m.supplier else None,
             m.customer.company_id if m.customer else None,
             m.customer.name if m.customer else None,
             t['subtotal'], t['discount'], t['vat'], t['total'],
             getattr(m, 'allocation_number', '') or None,
             getattr(m, 'allocation_status', 'none'), model_dict))
        _event(cur, did, 'create', m.DOC_TYPE, actor)
    return get(did)


def update(doc_id, patch, actor='api'):
    """Merge fields into a DRAFT's model and recompute totals. Rejected once issued."""
    rec = get(doc_id)
    if rec is None:
        raise KeyError(doc_id)
    if rec['status'] not in _EDITABLE:
        raise PermissionError('document %s is %s and immutable — issue a credit document to correct'
                              % (doc_id, rec['status']))
    merged = dict(rec['model']); merged.update(patch or {})
    m = _model_from_dict(merged); t = _totals(m)
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET model=%s, subtotal=%s, discount=%s, vat=%s, '
                'total=%s, customer_id=%s, customer_name=%s, updated_at=now() WHERE id=%s',
                (merged, t['subtotal'], t['discount'], t['vat'], t['total'],
                 m.customer.company_id if m.customer else None,
                 m.customer.name if m.customer else None, doc_id))
        _event(cur, doc_id, 'update', ','.join(sorted((patch or {}).keys()))[:200], actor)
    return get(doc_id)


def get(doc_id, with_pdf=False):
    cols = ('*' if with_pdf else
            'id,doc_number,doc_type,status,series,tax_year,seq_number,issuer_id,customer_id,'
            'customer_name,currency,subtotal,discount,vat,total,allocation_number,'
            'allocation_status,model,truth,file_ext,original_served_at,cancels,cancelled_by,'
            'converted_from,created_at,updated_at,issued_at')
    with Cursor() as cur:
        return cur.run('SELECT %s FROM business_documents WHERE id=%%s' % cols, (doc_id,)).one()


def query(doc_type=None, status=None, customer_id=None, issuer_id=None,
          date_from=None, date_to=None, limit=100, offset=0):
    from .db import is_postgres
    dd = "model->>'doc_date'" if is_postgres() else "json_extract(model,'$.doc_date')"
    sql = ('SELECT id,doc_number,doc_type,status,series,customer_name,total,vat,currency,'
           'allocation_number,cancelled_by,issued_at,created_at, %s AS doc_date FROM business_documents WHERE 1=1' % dd)
    a = []
    for col, val in (('doc_type', doc_type), ('status', status),
                     ('customer_id', customer_id), ('issuer_id', issuer_id)):
        if val:
            sql += ' AND %s=%%s' % col; a.append(val)
    if date_from:
        sql += ' AND created_at>=%s'; a.append(date_from)
    if date_to:
        sql += ' AND created_at<=%s'; a.append(date_to)
    # …then by id: one order across pages. An imported history gives a day's documents one `created_at` (its date at
    # midnight), and Postgres may order tied rows anew on every page — «מסמכים» reads the ledger page by page, and a
    # document came on two pages and another on none (DGO-2169, the second reader)
    sql += ' ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s'; a += [int(limit), int(offset)]
    with Cursor() as cur:
        return cur.run(sql, tuple(a)).all()


# ── numbering ──────────────────────────────────────────────────────────────
def _seq_type(doc_type, series):
    """The sequence a series counts in. Credit notes were INVOICE rows in series CN until they became a type of
    their own (DGO-2029): series CN goes on counting in that same sequence, so its numbers neither start again at
    CN-…-00001 nor repeat one already issued."""
    return 'INVOICE' if (doc_type, series) == ('CREDIT_NOTE', 'CN') else doc_type


#: the sequence key of a series that continues across years (business_sequences.tax_year)
CONTINUING = 'all'


def _allocate(cur, doc_type, series, tax_year, start=1):
    doc_type = _seq_type(doc_type, series)
    row = cur.run('SELECT next_seq FROM business_sequences WHERE doc_type=%s AND series=%s '
                  'AND tax_year=%s', (doc_type, series, tax_year)).one()
    seq = row['next_seq'] if row else start
    if row:
        cur.run('UPDATE business_sequences SET next_seq=%s WHERE doc_type=%s AND series=%s '
                'AND tax_year=%s', (seq + 1, doc_type, series, tax_year))
    else:
        cur.run('INSERT INTO business_sequences (doc_type, series, tax_year, next_seq) '
                'VALUES (%s,%s,%s,%s)', (doc_type, series, tax_year, seq + 1))
    return seq


# ── lifecycle ──────────────────────────────────────────────────────────────
def issue(doc_id, series='A', actor='api', force=False):
    """DRAFT -> ISSUED. Validate, allocate a gapless legal number, render+store the PDF,
    snapshot the extraction truth, chain the row, and freeze it (immutable)."""
    rec = get(doc_id)
    if rec is None:
        raise KeyError(doc_id)
    if rec['status'] != DRAFT:
        raise PermissionError('document %s is already %s' % (doc_id, rec['status']))
    from . import entities
    model = dict(rec['model'])
    tax_year = _today('%Y')
    if series in (None, 'A'):                 # default: a per-type series
        series = TYPE_SERIES.get(rec['doc_type'], 'A')
    # a type that continues a series the business brought with it (DGO-2042: the receipts it imported) numbers
    # plainly from where that series stands and does not start again with the year. Otherwise the
    # legacy doc_start (every type from one start: issues/ledger-numbering-start-collides-across-types.yaml), or
    # the default SERIES-YEAR-00001.
    business = entities.get_business()
    start = entities.series_starts(business).get(rec['doc_type'])
    doc_start = int(business.get('doc_start') or 0)
    brand = entities.brand()                     # before the cursor: its lock is not reentrant
    with Cursor() as cur:
        if start:
            seq = _allocate(cur, rec['doc_type'], series, CONTINUING, start=start)
            number = model.get('doc_id') or str(seq)
        else:
            seq = _allocate(cur, rec['doc_type'], series, tax_year, start=doc_start or 1)
            if doc_start:
                number = model.get('doc_id') or str(seq)
            else:
                number = model.get('doc_id') or '%s-%s-%05d' % (series, tax_year, seq)
        model['doc_id'] = number
        m = _model_from_dict(model)
        issues = validate_compliance(m)
        if issues and not force:
            raise ValueError('not_compliant: ' + '; '.join(issues))
        # (a) allocation number (חשבוניות ישראל) — required for invoices >= threshold
        alloc_detail = None
        pre_vat = getattr(m, 'after_discount', getattr(m, 'total', None))
        if allocation.needs_allocation(rec['doc_type'], pre_vat, model.get('doc_date')):
            a = allocation.request_allocation(doc_id, m.supplier.company_id,
                                              m.customer.company_id if m.customer else '',
                                              pre_vat, model.get('doc_date'), number)
            alloc_detail = a
            if a.get('number'):
                model['allocation_number'] = a['number']
                model['allocation_status'] = 'granted'
                m = _model_from_dict(model)          # re-model so the number prints on the PDF
            elif a.get('status') == 'held' and not force:
                raise ValueError('allocation_held: ' + (a.get('message') or 'ITA held the invoice'))
            else:
                model['allocation_status'] = a.get('status', 'pending')
        # (b) render the final artifact, then (c) sign it (מסמך ממוחשב)
        # the stored artifact IS the original: it prints «מקור» (a document of the books; others print no label)
        from ..doc_gen.house import israel_now
        produced = israel_now()
        pdf = render(m, 'pdf', label=printed_label(rec['doc_type'], served=False), brand=brand, now=produced)
        # …and its copy, drawn now from the same model by the same renderer at the same minute: every later
        # download serves these bytes, the original's twin but for «העתק» — a copy never drifts with a later
        # template or rule (DGO-2029)
        copy_label = printed_label(rec['doc_type'], served=True)
        copy = render(m, 'pdf', label=copy_label, brand=brand, now=produced) if copy_label else None
        sig = signing.sign(pdf)
        truth = m.extraction_truth()
        core = '%s|%s|%s|%s|%s' % (rec['doc_type'], series, seq, number,
                                   hashlib.md5(pdf).hexdigest())
        ch = _chain(cur, core)
        cur.run('UPDATE business_documents SET status=%s, doc_number=%s, series=%s, tax_year=%s, '
                'seq_number=%s, model=%s, truth=%s, pdf=%s, copy_pdf=%s, file_ext=%s, allocation_number=%s, '
                'allocation_status=%s, signature=%s, signer=%s, signed_at=%s, sig_certified=%s, '
                'chain_hash=%s, issued_at=now(), updated_at=now() WHERE id=%s',
                (ISSUED, number, series, tax_year, seq, model, truth, _blob(cur, pdf),
                 _blob(cur, copy) if copy else None, 'pdf',
                 model.get('allocation_number'), model.get('allocation_status', 'none'),
                 _blob(cur, sig['cms']), sig['signer'], sig['signed_at'], sig['certified'],
                 ch, doc_id))
        _event(cur, doc_id, 'issue', number, actor)
        _event(cur, doc_id, 'sign', ('certified' if sig['certified'] else 'secured') + ' · ' + sig['signer'][:60], actor)
        if alloc_detail and alloc_detail.get('number'):
            _event(cur, doc_id, 'allocation', '%s (%s)' % (alloc_detail['number'], alloc_detail.get('backend')), actor)
    return get(doc_id)


def _blob(cur, data):
    if cur.pg:
        import psycopg2
        return psycopg2.Binary(data)
    return sqlite_blob(data)


def sqlite_blob(data):
    return memoryview(data)


def download(doc_id, fmt=None, actor='api'):
    """Return (bytes, filename, label). Issued docs serve the stored PDF and mark
    מקור-once / העתק; a draft renders a טיוטה preview (never a legal original)."""
    rec = get(doc_id, with_pdf=True)
    if rec is None:
        raise KeyError(doc_id)
    if rec['status'] == DRAFT:
        m = _model_from_dict(rec['model'])
        data = render(m, fmt or 'pdf', label='טיוטה')
        return data, 'DRAFT_%s.%s' % (doc_id, fmt or 'pdf'), 'טיוטה'
    with Cursor() as cur:
        # «מקור» once, decided by the row itself: two first downloads at once — two requests, two workers —
        # cannot both have it (DGO-2029, the second reader)
        first = cur.run('UPDATE business_documents SET original_served_at=now() '
                        'WHERE id=%s AND original_served_at IS NULL', (doc_id,)).cur.rowcount == 1
        label = 'מקור' if first else 'העתק'
        _event(cur, doc_id, 'download', label, actor)
    ext = rec.get('file_ext') or 'pdf'
    printed = printed_label(rec['doc_type'], served=not first)
    if (fmt and fmt != ext) or not rec.get('pdf'):
        # another format (an image of the page), or no stored file: drawn from the model, with its label
        data = render(_model_from_dict(rec['model']), fmt or ext, label=printed)
        ext = fmt or ext
    elif not first and rec.get('copy_pdf'):
        # the copy drawn when the original was (Instruction 36: the software never makes a second «מקור»)
        data = bytes(rec['copy_pdf'])
    else:
        # the original, signed as it was issued; a document that prints no label is the same every time; and one
        # issued before copies were kept is served as it was issued, as it always was — its copy is never drawn
        # again by a later renderer, with another look or another rule
        data = bytes(rec['pdf'])
    return data, '%s.%s' % (rec.get('doc_number') or doc_id, ext), label


def preview_html(doc_id, font_base=None):
    """The document as the screen shows it beside its record: the house HTML (the PDF's own source), drawn
    from the model. A preview is not a download — it uses up no «מקור»; a document of the books says «העתק» on it,
    so a preview that is printed is a marked copy (DGO-2029, the third reader), and a draft says «טיוטה»."""
    rec = get(doc_id)
    if rec is None:
        raise KeyError(doc_id)
    from . import entities
    from ..doc_gen.house import from_model, pages_html, render_html
    if (rec.get('model') or {}).get('imported'):
        # another system's document: its own stamped copy, page by page — never redrawn from its summary (DGO-2042)
        full = get(doc_id, with_pdf=True)
        data = full.get('copy_pdf') or full.get('pdf')
        if data:
            return pages_html(bytes(data), title=rec.get('doc_number') or '')
    doc = from_model(_model_from_dict(rec['model']))
    if rec.get('doc_number'):
        doc['doc_id'] = rec['doc_number']
    b = entities.brand()
    if b:
        doc['brand'] = b
    if rec['status'] == CANCELLED:
        doc['status'] = 'cancelled'
    label = 'טיוטה' if rec['status'] == DRAFT else printed_label(rec['doc_type'], served=True)
    return render_html(doc, label=label, font_base=font_base)


def _transition(doc_id, to_status, action, detail='', actor='api', from_ok=None):
    rec = get(doc_id)
    if rec is None:
        raise KeyError(doc_id)
    if from_ok and rec['status'] not in from_ok:
        raise PermissionError('cannot %s a %s document' % (action, rec['status']))
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET status=%s, updated_at=now() WHERE id=%s',
                (to_status, doc_id))
        _event(cur, doc_id, action, detail, actor)
    return get(doc_id)


def send(doc_id, to='', actor='api'):
    return _transition(doc_id, SENT, 'send', to, actor, from_ok={ISSUED, SENT})


def pay(doc_id, detail='', actor='api'):
    return _transition(doc_id, PAID, 'pay', detail, actor, from_ok={ISSUED, SENT, PAID})


#: the documents whose cancellation is itself a document of the books: a tax invoice is reversed by a credit note
_CREDITED = {'INVOICE', 'INVOICE_RECEIPT'}


def is_credit(rec):
    """A credit note — its own type, or one from before it had a type: an INVOICE row in series CN with a negative
    total (DGO-2029, the second reader: those were offered «ביטול», which issued a second credit and dropped the first
    from the report; the third: a positive invoice someone numbered in CN is a sale, and cancels like one). And any
    document that cancels another — an imported negative receipt (the fifth reader: cancelling it brought the receipt
    it cancelled back into the income)."""
    if rec.get('doc_type') == 'CREDIT_NOTE' or rec.get('cancels'):
        return True
    try:
        negative = float(rec.get('total') or 0) < 0
    except (TypeError, ValueError):
        negative = False
    return rec.get('doc_type') == 'INVOICE' and rec.get('series') == 'CN' and negative


def cancel(doc_id, reason, actor='api'):
    """Cancel a document; nothing is deleted. An ISSUED tax invoice (or invoice-receipt) is reversed the
    compliant way — a CREDIT_NOTE that names it, its date and the reason (§9(ה)), with the lines' prices
    negated — and is then marked cancelled. Any other document (a quote, an order, a receipt, a payment
    request, an agreement…) is only marked cancelled: it carries no VAT, so there is nothing to reverse,
    and a negative tax invoice for a quote would be a false entry in the VAT report (DGO-2029)."""
    rec = get(doc_id)
    if rec is None:
        raise KeyError(doc_id)
    if rec['status'] in _TERMINAL:
        raise PermissionError('document %s already %s' % (doc_id, rec['status']))
    if is_credit(rec) and rec['status'] != DRAFT:
        # a credit note is itself the correction: cancelling it would drop a tax document from the VAT report with
        # nothing in its place (DGO-2029, the second reader) — a sale credited by mistake is invoiced again
        raise PermissionError('a credit note is not cancelled — issue a new tax invoice instead')
    cm = None
    if rec['status'] != DRAFT and rec['doc_type'] in _CREDITED:
        src = dict(rec['model'])
        cm = {k: src[k] for k in ('supplier', 'customer', 'lines', 'discount_pct', 'vat_pct', 'bank')
              if k in src}
        cm.update({'doc_type': 'CREDIT_NOTE', 'doc_id': '', 'doc_date': _today(),
                   'issued_at_shipping': True, 'original_invoice': rec.get('doc_number') or doc_id,
                   'original_date': src.get('doc_date') or '', 'reason': reason})
        # each line's price negated as it is — a discount line (a negative price) comes back positive. -abs() made it
        # negative too, and the credit reversed more than was sold (DGO-2029, the third reader).
        cm['lines'] = [dict(l) for l in cm.get('lines', [])]
        for l in cm['lines']:
            l['unit_price'] = -float(l.get('unit_price') or 0)
        original = _model_from_dict(dict(src, doc_type=rec['doc_type']))
        # the credit at the invoice's own rate — an invoice kept before its rate was written carries the model's,
        # which create() would otherwise replace with the business's rate of today (the fourth reader)
        cm['vat_pct'] = original.vat_pct
        if _model_from_dict(cm).total_due != -original.total_due:
            raise ValueError('the credit note would not reverse %s exactly' % (rec.get('doc_number') or doc_id))
    # the document is claimed before its credit is made: two cancels at once must not issue two credit notes. The
    # event is written with the claim, so a cancel cut off between the two (a killed worker) is found, not lost.
    with Cursor() as cur:
        took = cur.run('UPDATE business_documents SET status=%s, updated_at=now() WHERE id=%s AND status=%s',
                       (CANCELLED, doc_id, rec['status'])).cur.rowcount == 1
        if took:
            _event(cur, doc_id, 'cancel', reason, actor)
    if not took:
        raise PermissionError('document %s changed while it was being cancelled' % doc_id)
    credit = None
    if cm is not None:
        try:
            credit = issue(create(cm, actor)['id'], actor=actor, force=True)
        except BaseException:                      # a timeout's SystemExit too: no credit, no cancel
            with Cursor() as cur:
                cur.run('UPDATE business_documents SET status=%s WHERE id=%s', (rec['status'], doc_id))
                # the trail is read in Hebrew, like every other detail it holds (it read «the credit note was not
                # made» beside a label the screen did not have, DGO-2029)
                _event(cur, doc_id, 'cancel-undone', 'חשבונית הזיכוי לא הופקה — המסמך חזר למצבו', actor)
            raise
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET cancelled_by=%s, updated_at=now() WHERE id=%s',
                ((credit or {}).get('id'), doc_id))
        if credit:
            cur.run('UPDATE business_documents SET cancels=%s WHERE id=%s', (doc_id, credit['id']))
    out = get(doc_id)
    out['credit_document'] = credit
    return out


# which target types each source type may convert into (the sales-document graph)
CONVERSIONS = {
    # the deal: a proposal or a quote is signed into an agreement, then billed (DGO-2029)
    'PROPOSAL':          ['SERVICE_AGREEMENT', 'PAYMENT_REQUEST', 'WORK_ORDER', 'ORDER', 'INVOICE', 'INVOICE_RECEIPT'],
    'QUOTE':             ['SERVICE_AGREEMENT', 'ORDER', 'WORK_ORDER', 'PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT'],
    'SERVICE_AGREEMENT': ['PAYMENT_REQUEST', 'WORK_ORDER', 'INVOICE', 'INVOICE_RECEIPT'],
    'WORK_ORDER':        ['PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT'],
    'ORDER':             ['SHIPMENT', 'PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT'],
    'SHIPMENT':          ['INVOICE', 'INVOICE_RECEIPT'],
    'PAYMENT_REQUEST':   ['RECEIPT', 'INVOICE', 'INVOICE_RECEIPT'],
    'INVOICE':           ['RECEIPT'],                       # collect payment -> issue receipt
}


def convert(doc_id, to_type, actor='api'):
    """Create a NEW DRAFT of `to_type` from a source document, carrying the customer +
    lines and linking back. The lifecycle spine is unchanged — the source stays as-is;
    the target is a fresh draft you then issue."""
    src = get(doc_id)
    if src is None:
        raise KeyError(doc_id)
    allowed = [] if is_credit(src) else CONVERSIONS.get(src['doc_type'], [])   # a credit becomes no receipt
    if to_type not in allowed:
        raise ValueError('cannot convert %s -> %s (allowed: %s)'
                         % (src['doc_type'], to_type, allowed or 'none'))
    sm = src['model']
    src_kind = catalogue.kind(src['doc_type'])['he'] if src['doc_type'] in catalogue.TYPES else src['doc_type']
    number = src.get('doc_number') or ''
    # build a clean target model — carry only the fields the target type accepts;
    # source-type-specific fields (a quote's valid_until, or lines for a Receipt which
    # has none) would be rejected by the target model constructor
    if to_type == 'RECEIPT':                          # a receipt for the source's payment, dated the day it is made
        m = {'doc_type': to_type, 'doc_date': _today(),
             'customer': sm.get('customer'),
             'amount': float(src.get('total') or 0),
             'nature': '%s %s' % (src_kind, number) if number else 'תשלום',
             'payment_method': sm.get('payment_method', 'העברה בנקאית')}
    else:                                             # line-carrying targets
        # a recurring line (a monthly retainer) is billed each period on its own — it is not carried
        # into a one-time document; an agreement carries no lines, it points at its source
        lines = [dict(l) for l in sm.get('lines', []) if not (l or {}).get('period')]
        for l in lines:
            l.pop('period', None)
            if to_type in LEDGER_TYPES:               # a dataclass line knows its own fields only
                for k in list(l):
                    if k not in LineItem.__dataclass_fields__:
                        l.pop(k)
        m = {'doc_type': to_type, 'doc_date': _today(), 'customer': sm.get('customer')}
        if to_type not in ('SERVICE_AGREEMENT', 'NDA'):
            m['lines'] = lines
        else:
            # an agreement starts from the house's text, with its parties drawn from the business and the customer —
            # an agreement converted from a proposal used to be empty, and could be issued and sent to sign so
            # (DGO-2029, the second reader). The text is kept in the document: a later starter never changes it.
            from ..doc_gen.house import starters
            frame = starters.starter(to_type)
            m.update({k: frame[k] for k in ('title', 'recitals', 'clauses', 'cover') if frame.get(k)})
            if to_type == 'SERVICE_AGREEMENT':
                # its clauses put the services and the price «כמפורט בנספח א׳»: the appendix is the document it came
                # from, named — so that document must be issued, with a number (the third and fourth readers). It is
                # named, not attached: the signing link carries the agreement alone.
                if not number:
                    raise ValueError('an agreement is made from an issued %s: it is its appendix' % src_kind)
                m['appendix'] = (f'נספח א׳ — השירותים והתמורה: כמפורט ב{src_kind} מס׳ {number}'
                                 f'{" מיום " + sm["doc_date"] if sm.get("doc_date") else ""}, שנמסרה ללקוח; '
                                 f'היא נספח א׳ להסכם זה וחלק בלתי נפרד ממנו.')
        if to_type in HOUSE_TYPES and number:
            m['refs'] = {'source': {'kind': src_kind, 'number': number, 'date': sm.get('doc_date')}}
        if to_type in ('INVOICE', 'INVOICE_RECEIPT'):
            m['issued_at_shipping'] = True              # its VAT rate is the business's today (create())
    new = create(m, actor)
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET converted_from=%s WHERE id=%s',
                (src.get('doc_number') or doc_id, new['id']))
        _event(cur, new['id'], 'convert', 'מ-%s (%s)' % (src.get('doc_number') or doc_id, src['doc_type']), actor)
        _event(cur, doc_id, 'converted', '→ %s' % to_type, actor)
    return get(new['id'])


# ── the history a business brings with it ─────────────────────────────────────
#: what another system's register calls a type (Morning's names)
TYPE_NAMES = {'חשבון עסקה': 'PAYMENT_REQUEST', 'דרישת תשלום': 'PAYMENT_REQUEST', 'קבלה': 'RECEIPT',
              'חשבונית מס': 'INVOICE', 'חשבונית מס קבלה': 'INVOICE_RECEIPT', 'חשבונית מס/קבלה': 'INVOICE_RECEIPT',
              'חשבונית מס זיכוי': 'CREDIT_NOTE', 'חשבונית זיכוי': 'CREDIT_NOTE', 'הצעת מחיר': 'QUOTE'}
#: the types an import keeps: a tax document only with its VAT said (subtotal + vat), never guessed from a total
_IMPORTABLE = ('PAYMENT_REQUEST', 'RECEIPT', 'QUOTE', 'INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE')
#: an imported type that is served as it was issued, with no «העתק» copy: the one a customer signs (DGO-2125)
_SIGNED_AS_ISSUED = ('QUOTE',)
_TAXED = ('INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE')


def _num(v):
    try:
        return float(str(v).replace(',', '').strip() or 0)
    except ValueError:
        raise ValueError('%r is not an amount' % (v,))


def _row_type(r):
    return TYPE_NAMES.get(str(r.get('type') or '').strip()) or str(r.get('doc_type') or '').strip().upper()


def _imported_row(t, number):
    """The ledger's row of an imported document of type t and this number, or None (a document issued here is
    never touched by an import)."""
    with Cursor() as cur:
        row = cur.run('SELECT id, status, total, model FROM business_documents WHERE doc_type=%s AND doc_number=%s',
                      (t, number)).one()
    return row if row and (row.get('model') or {}).get('imported') else None


def import_issued(rows, source='', actor='import'):
    """Documents another system issued, kept as they were issued (DGO-2042: A business's earlier documents).

    Each becomes a row of the ledger with its own number, date, customer and amount. Its original PDF is the stored
    original — counted as served, since it went out from that system — and its copy is that file with its «מקור»
    taken off and «העתק» drawn in its place (house.stamp_copy); the screen shows that copy, never a redraw. A quote
    keeps no copy: it is the document a customer signs, so it is served and shown as it was issued (DGO-2125). A
    cancelling document carries a negative amount, as its PDF does. Imported documents are not in the tamper chain:
    they were not issued here. This only keeps the rows: what they say of each other (a request paid, a document
    cancelled) and where each series goes on are settled once all are in (settle_imported), so an import sent in
    parts and in any order comes out the same (the fifth reader).

    Every row is checked before any is kept: a type the import keeps; a number of digits that no OTHER document
    holds (the ledger's numbers are one namespace); a type this ledger has not issued itself (two series would mix);
    a date; its PDF (without its original a document cannot be shown as it was); and, for a business that charges
    VAT, a subtotal and the VAT on every priced type. A number already held by the same import (type, date and total)
    is skipped, so an import can run again.

    A row: {type or doc_type, number, date DD/MM/YYYY, client or customer, amount, description, pays, cancels,
    payment_method, pdf_b64, file; subtotal and vat where VAT is charged}."""
    import base64
    from . import entities
    from ..doc_gen.house import stamp_copy
    supplier = entities.issuer_party()
    patur = (supplier.get('tax_status') if isinstance(supplier, dict) else '') == catalogue.PATUR
    plan, skipped, seen = [], [], set()
    for r in rows or []:
        t = _row_type(r)
        if t not in _IMPORTABLE:
            raise ValueError('%s: the import keeps %s' % (r.get('type') or t or '?', ', '.join(_IMPORTABLE)))
        number = str(r.get('number') or '').strip()
        if not number.isdigit():
            raise ValueError('%r: an imported document keeps its number, digits only' % number)
        if number in seen:
            raise ValueError('%s: twice in one import' % number)
        seen.add(number)
        date = str(r.get('date') or r.get('issued') or '').strip()
        parts = date.split('/')
        if len(parts) != 3 or len(parts[2]) != 4:
            raise ValueError('%s %s: the date is DD/MM/YYYY, got %r' % (t, number, date))
        amount = _num(r.get('amount'))
        if r.get('cancels'):
            amount = -abs(amount)                          # a cancelling document reverses: its PDF says −₪…
        taxed = t in _TAXED or (not patur and t != 'RECEIPT')
        if taxed:
            if r.get('subtotal') in (None, '') or r.get('vat') in (None, ''):
                raise ValueError('%s %s: a business that charges VAT imports it with its subtotal and VAT'
                                 % (t, number))
            sub, vat = _num(r['subtotal']), _num(r['vat'])
            if r.get('cancels'):
                sub, vat = -abs(sub), -abs(vat)
            totals = (sub, vat, round(sub + vat, 2))
        else:
            totals = (amount, 0.0, amount)
        with Cursor() as cur:
            have = cur.run('SELECT id, doc_type, total, model FROM business_documents WHERE doc_number=%s',
                           (number,)).one()
            native = cur.run('SELECT 1 FROM business_documents WHERE doc_type=%s AND doc_number IS NOT NULL AND ' +
                             ("NOT (model ? 'imported')" if cur.pg else "json_extract(model, '$.imported') IS NULL"),
                             (t,)).one()
        if have:
            hm = have.get('model') or {}
            if (have['doc_type'] == t and hm.get('imported') and hm.get('doc_date') == date
                    and abs(float(have.get('total') or 0) - totals[2]) < 0.005):
                skipped.append(number)                     # this same import, again
                continue
            raise ValueError('%s %s: the ledger already holds number %s (%s) — nothing was imported'
                             % (t, number, number, have['doc_type']))
        if native:
            raise ValueError('%s: this ledger already issues its own — an import would mix two series' % t)
        if not r.get('pdf_b64'):
            raise ValueError('%s %s: its PDF is missing — a document is kept with its original' % (t, number))
        plan.append((r, t, number, date, parts, amount, totals))

    imported = []
    for r, t, number, date, parts, amount, totals in plan:
        customer = r.get('customer') if isinstance(r.get('customer'), dict) else {'name': str(r.get('client') or '')}
        what = str(r.get('description') or '').strip()
        pays = str(r.get('pays') or '').strip()
        model = {'doc_type': t, 'doc_id': number, 'doc_date': date, 'supplier': supplier, 'customer': customer,
                 'imported': {'source': source, 'file': str(r.get('file') or ''), 'pays': pays,
                              'cancels': str(r.get('cancels') or '')}}
        if t == 'RECEIPT':
            model.update(amount=amount, nature=what or ('חשבון עסקה %s' % pays if pays else 'תקבול'),
                         payment_method=str(r.get('payment_method') or ''))
        else:
            sub, vat = totals[0], totals[1]
            model.update(lines=[{'description': what or catalogue.kind(t)['he'], 'qty': 1, 'unit': 'יח׳',
                                 'unit_price': sub}], vat_pct=round(vat / sub * 100, 2) if sub and vat else 0,
                         issued_at_shipping=True)
        if pays:
            model['refs'] = {'source': {'kind': 'חשבון עסקה', 'number': pays}}
        pdf = base64.b64decode(r['pdf_b64'])
        # a quote keeps no copy: it is the document a customer SIGNS, so it reaches its signer as the quote itself, not a
        # «העתק» from an archive, and the house prints no label on a quote of its own (printed_label) — DGO-2125. Every
        # other type keeps its «העתק» copy, a payment request too, whose face Morning printed «מקור» (DGO-2042)
        copy = None if t in _SIGNED_AS_ISSUED else stamp_copy(pdf, note='מארכיון %s' % source if source else '')
        when = '%s-%s-%s' % (parts[2], parts[1].zfill(2), parts[0].zfill(2))
        did = 'doc_' + uuid.uuid4().hex[:16]
        with Cursor() as cur:
            cur.run('INSERT INTO business_documents (id, doc_number, doc_type, status, series, tax_year, seq_number, '
                    'issuer_id, customer_name, subtotal, discount, vat, total, model, pdf, copy_pdf, file_ext, '
                    'original_served_at, issued_at, created_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)',
                    (did, number, t, ISSUED, TYPE_SERIES.get(t, 'A'), parts[2], int(number),
                     (supplier or {}).get('company_id'), customer.get('name'), totals[0], 0, totals[1], totals[2],
                     model, _blob(cur, pdf), _blob(cur, copy) if copy else None, 'pdf', when, when))
            _event(cur, did, 'import', ('%s · %s' % (source, r.get('file') or number))[:200], actor)
        imported.append(number)
    return {'imported': imported, 'skipped': skipped}


def settle_imported(rows, source='', actor='import'):
    """What imported documents say of each other, once all are in, and where each series goes on (DGO-2042).

    First each imported type's numbers must run without a gap from its first: a register that skips a number — or a
    typo, 800010 for 80010 — is refused here, and nothing changes. Then, among imported documents only, each change
    written in their trail: a document that cancels another marks it cancelled, by it; a request is paid when a
    receipt that is not itself cancelled says it pays it. Last, each type continues from its highest number
    (settings.series_start): The last imported receipt is followed by the next number, issued here."""
    import json
    from . import entities
    types = sorted({_row_type(r) for r in rows or []} & set(_IMPORTABLE))
    spans, gaps = {}, {}
    for t in types:
        with Cursor() as cur:
            got = cur.run('SELECT doc_number, model FROM business_documents WHERE doc_type=%s AND doc_number IS NOT NULL',
                          (t,)).all()
        nums = sorted(int(x['doc_number']) for x in got
                      if (x.get('model') or {}).get('imported') and str(x['doc_number']).isdigit())
        if not nums:
            continue
        held = set(nums)
        missing = [n for n in range(nums[0], nums[-1] + 1) if n not in held]
        if missing:
            gaps[t] = missing[:12]
        spans[t] = (nums[0], nums[-1])
    if gaps:
        raise ValueError('the imported series have gaps, nothing was settled: ' +
                         '; '.join('%s %s' % (t, ', '.join(map(str, g))) for t, g in gaps.items()))

    cancelled, paid = [], []
    for r in rows or []:                                   # cancels first: a cancelled receipt pays nothing
        t, number = _row_type(r), str(r.get('number') or '').strip()
        target = ''.join(ch for ch in str(r.get('cancels') or '') if ch.isdigit())
        me = _imported_row(t, number) if target else None
        gone = _imported_row(t, target) if me else None
        if gone and gone['status'] != CANCELLED:
            with Cursor() as cur:
                cur.run('UPDATE business_documents SET status=%s, cancelled_by=%s WHERE id=%s',
                        (CANCELLED, me['id'], gone['id']))
                cur.run('UPDATE business_documents SET cancels=%s WHERE id=%s', (gone['id'], me['id']))
                _event(cur, gone['id'], 'cancel', ('בוטל במסמך %s (%s)' % (number, source))[:200], actor)
            cancelled.append(target)
    for r in rows or []:
        t, number = _row_type(r), str(r.get('number') or '').strip()
        pays = str(r.get('pays') or '').strip()
        me = _imported_row(t, number) if pays else None
        if not me or me['status'] == CANCELLED:
            continue
        pq = _imported_row('PAYMENT_REQUEST', pays)
        if pq and pq['status'] == ISSUED:
            with Cursor() as cur:
                cur.run('UPDATE business_documents SET status=%s WHERE id=%s', (PAID, pq['id']))
                _event(cur, pq['id'], 'pay', ('שולם — קבלה %s (%s)' % (number, source))[:200], actor)
            paid.append(pays)

    # each imported type's series continues from its highest number
    starts = entities.series_starts()
    nexts = {}
    for t, (first, top) in spans.items():
        series = TYPE_SERIES.get(t, 'A')
        with Cursor() as cur:
            key = (_seq_type(t, series), series, CONTINUING)
            row = cur.run('SELECT next_seq FROM business_sequences WHERE doc_type=%s AND series=%s AND tax_year=%s',
                          key).one()
            nexts[t] = max(row['next_seq'], top + 1) if row else top + 1
            if row:
                cur.run('UPDATE business_sequences SET next_seq=%s WHERE doc_type=%s AND series=%s AND tax_year=%s',
                        (nexts[t],) + key)
            else:
                cur.run('INSERT INTO business_sequences (doc_type, series, tax_year, next_seq) VALUES (%s,%s,%s,%s)',
                        key + (nexts[t],))
        starts[t] = min(starts.get(t, first), first)
    if nexts:
        entities.save_business({'series_start': json.dumps(starts)})
    return {'paid': paid, 'cancelled': cancelled, 'next': nexts}


def events(doc_id):
    with Cursor() as cur:
        rows = cur.run('SELECT ts, actor, action, detail FROM business_document_events '
                       'WHERE doc_id=%s ORDER BY id', (doc_id,)).all()
    # the time as ISO text on every database, as SQLite already keeps it: on Postgres the driver hands a datetime and
    # the API's JSON wrote it «Thu, 19 Nov 2026 20:23:22 GMT», which the screen (it reads ISO) drew as «hu, 19 Nov
    # 2026» in the Hebrew trail of every document on the HP (DGO-2042, the first night with the imported history)
    for r in rows:
        if hasattr(r.get('ts'), 'isoformat'):
            r['ts'] = r['ts'].isoformat(timespec='seconds')
    return rows


def signature(doc_id):
    """Signature metadata + verification for a document's stored artifact."""
    with Cursor() as cur:
        rec = cur.run('SELECT status, signer, signed_at, sig_certified, pdf, signature '
                      'FROM business_documents WHERE id=%s', (doc_id,)).one()
    if rec is None:
        raise KeyError(doc_id)
    if not rec.get('signature'):
        return {'signed': False, 'signer_status': signing.status()}
    v = signing.verify(bytes(rec['pdf']), bytes(rec['signature']))
    return {'signed': True, 'signer': rec['signer'], 'signed_at': rec['signed_at'],
            'certified': rec['sig_certified'],
            'mode': 'certified' if rec['sig_certified'] else 'secured',
            'verification': v}


def pcn874_report(business_id, date_from=None, date_to=None):
    """The unified-structure VAT report (מבנה אחיד 874) for a business's issued invoices."""
    sql = ("SELECT doc_type, doc_number, customer_id, total, vat, allocation_number, "
           "issued_at, status FROM business_documents WHERE issuer_id=%s AND status<>%s "
           "AND doc_number IS NOT NULL")
    a = [business_id, 'draft']
    if date_from:
        sql += ' AND issued_at>=%s'; a.append(date_from)
    if date_to:
        sql += ' AND issued_at<=%s'; a.append(date_to)
    sql += ' ORDER BY issued_at'
    with Cursor() as cur:
        rows = cur.run(sql, tuple(a)).all()
    return pcn874.build(rows, business_id)


# ── compliance self-checks & consent (unchanged obligations) ────────────────
def record_consent(customer_id, method='computerized', actor='api'):
    with Cursor() as cur:
        cur.run('INSERT INTO business_consents (customer_id, method) VALUES (%s,%s)',
                (customer_id, method))
        _event(cur, None, 'consent', '%s via %s' % (customer_id, method), actor)


def has_consent(customer_id):
    with Cursor() as cur:
        return cur.run('SELECT 1 FROM business_consents WHERE customer_id=%s AND '
                       'withdrawn_at IS NULL LIMIT 1', (customer_id,)).one() is not None


def attach_allocation(doc_id, allocation_number, status='granted', actor='api'):
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET allocation_number=%s, allocation_status=%s, '
                'updated_at=now() WHERE id=%s', (allocation_number, status, doc_id))
        _event(cur, doc_id, 'allocation', '%s:%s' % (status, allocation_number), actor)
    return get(doc_id)


def verify_sequence():
    """Every series gapless. A yearly series runs 1, 2, 3… within its year; a continuing one (a series the business
    brought with it, DGO-2042) runs on from its first number across the years — the imported numbers, then the next one issued."""
    from . import entities
    starts = entities.series_starts()
    with Cursor() as cur:
        rows = cur.run("SELECT doc_type, series, tax_year, seq_number FROM business_documents "
                       "WHERE seq_number IS NOT NULL ORDER BY doc_type, series, tax_year, seq_number").all()
    groups, first = {}, {}
    for r in rows:      # one group per sequence (credit notes count on in the old INVOICE/CN one: _seq_type)
        # a row is in its type's continuing series when its number is at or past that series' start — each row on
        # its own, by its own type (the fifth reader: a receipt issued here before an import stays in its year)
        start = starts.get(r['doc_type'])
        year = CONTINUING if start and r['seq_number'] >= start else r['tax_year']
        key = (_seq_type(r['doc_type'], r['series']), r['series'], year)
        groups.setdefault(key, []).append(r['seq_number'])
        if year == CONTINUING:
            first[key] = start
    for v in groups.values():
        v.sort()
    bad = {'/'.join(map(str, k)): v for k, v in groups.items()
           if v != list(range(first.get(k, 1), first.get(k, 1) + len(v)))}
    return {'ok': not bad, 'series_checked': len(groups), 'gaps': bad}


def verify_chain():
    with Cursor() as cur:
        rows = cur.run("SELECT doc_type, series, seq_number, doc_number, pdf, chain_hash "
                       "FROM business_documents WHERE chain_hash IS NOT NULL "
                       "ORDER BY issued_at", ()).all() if cur.pg else \
               cur.run("SELECT doc_type, series, seq_number, doc_number, chain_hash "
                       "FROM business_documents WHERE chain_hash IS NOT NULL "
                       "ORDER BY issued_at", ()).all()
    # chain verification needs the pdf md5 that fed the hash; recompute only when stored
    prev = 'GENESIS'
    for r in rows:
        if 'pdf' not in r or r.get('pdf') is None:
            return {'ok': None, 'note': 'pdf bytes not selected; run on the DB with artifacts'}
        core = '%s|%s|%s|%s|%s' % (r['doc_type'], r['series'], r['seq_number'],
                                   r['doc_number'], hashlib.md5(bytes(r['pdf'])).hexdigest())
        want = hashlib.sha256((prev + core).encode('utf-8')).hexdigest()
        if want != r['chain_hash']:
            return {'ok': False, 'first_bad': r['doc_number']}
        prev = r['chain_hash']
    return {'ok': True, 'checked': len(rows)}
