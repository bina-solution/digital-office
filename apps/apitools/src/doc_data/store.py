"""doc_data.store — business-document management, Green-Invoice / morning.com style.

A document moves through a lifecycle, backed by Postgres (source of truth):

    draft ──issue──▶ issued ──send──▶ sent ──pay──▶ paid
      │                 │
   (editable)         cancel ──▶ cancelled   (+ a CREDIT_INVOICE reversal is created)

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
import time
import uuid

from .db import Cursor
from . import signing, allocation, pcn874
from ..doc_models import DOC_TYPES, validate_compliance
from ..doc_models.models import Party, LineItem, BankDetails, BSLine
from ..doc_gen import render

DRAFT, ISSUED, SENT, PAID, CANCELLED = 'draft', 'issued', 'sent', 'paid', 'cancelled'
_EDITABLE = {DRAFT}
_TERMINAL = {CANCELLED}

# each document TYPE gets its own numbering series (Israeli practice) — keeps numbers
# unique across types and human-meaningful (INV-2026-00001, IR-2026-00001, …)
TYPE_SERIES = {
    'INVOICE': 'INV', 'INVOICE_RECEIPT': 'IR', 'RECEIPT': 'RC', 'QUOTE': 'QT',
    'ORDER': 'OR', 'SHIPMENT': 'DN', 'BALANCE_SHEET': 'BS',
}


# ── model (de)serialisation ────────────────────────────────────────────────
def _model_from_dict(d):
    cls = DOC_TYPES.get((d.get('doc_type') or '').upper())
    if cls is None:
        raise ValueError('unknown doc_type %r' % d.get('doc_type'))
    kw = {k: v for k, v in d.items() if k != 'doc_type'}
    for pk in ('supplier', 'customer'):
        if isinstance(kw.get(pk), dict):
            kw[pk] = Party(**kw[pk])
    if isinstance(kw.get('bank'), dict):
        kw['bank'] = BankDetails(**kw['bank'])
    line_cls = BSLine if cls.DOC_TYPE == 'BALANCE_SHEET' else LineItem
    if isinstance(kw.get('lines'), list):
        kw['lines'] = [line_cls(**l) if isinstance(l, dict) else l for l in kw['lines']]
    return cls(**kw)


def _totals(m):
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


# ── CRUD ───────────────────────────────────────────────────────────────────
def create(model_dict, actor='api'):
    """Create a DRAFT document from a model. No number yet — editable until issued.
    The issuer (supplier) and VAT default come from the business settings singleton
    unless the caller supplied them explicitly."""
    from . import entities
    model_dict = dict(model_dict or {})
    if not model_dict.get('supplier'):
        model_dict['supplier'] = entities.issuer_party()
    if 'vat_pct' not in model_dict and model_dict.get('doc_type') == 'INVOICE':
        model_dict['vat_pct'] = float(entities.get_business().get('vat_pct', 18) or 0)
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
    sql = ('SELECT id,doc_number,doc_type,status,customer_name,total,currency,'
           'allocation_number,issued_at,created_at, %s AS doc_date FROM business_documents WHERE 1=1' % dd)
    a = []
    for col, val in (('doc_type', doc_type), ('status', status),
                     ('customer_id', customer_id), ('issuer_id', issuer_id)):
        if val:
            sql += ' AND %s=%%s' % col; a.append(val)
    if date_from:
        sql += ' AND created_at>=%s'; a.append(date_from)
    if date_to:
        sql += ' AND created_at<=%s'; a.append(date_to)
    sql += ' ORDER BY created_at DESC LIMIT %s OFFSET %s'; a += [int(limit), int(offset)]
    with Cursor() as cur:
        return cur.run(sql, tuple(a)).all()


# ── numbering ──────────────────────────────────────────────────────────────
def _allocate(cur, doc_type, series, tax_year, start=1):
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
    tax_year = time.strftime('%Y')
    if series in (None, 'A'):                 # default: a per-type series
        series = TYPE_SERIES.get(rec['doc_type'], 'A')
    # a business may continue an existing numbering series (e.g. migrating in): when
    # doc_start is configured, numbers are plain sequential from it (80001, 80002, …),
    # gapless and system-assigned; otherwise the default SERIES-YEAR-00001 format.
    doc_start = int(entities.get_business().get('doc_start') or 0)
    with Cursor() as cur:
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
        pdf = render(m, 'pdf')
        sig = signing.sign(pdf)
        truth = m.extraction_truth()
        core = '%s|%s|%s|%s|%s' % (rec['doc_type'], series, seq, number,
                                   hashlib.md5(pdf).hexdigest())
        ch = _chain(cur, core)
        cur.run('UPDATE business_documents SET status=%s, doc_number=%s, series=%s, tax_year=%s, '
                'seq_number=%s, model=%s, truth=%s, pdf=%s, file_ext=%s, allocation_number=%s, '
                'allocation_status=%s, signature=%s, signer=%s, signed_at=%s, sig_certified=%s, '
                'chain_hash=%s, issued_at=now(), updated_at=now() WHERE id=%s',
                (ISSUED, number, series, tax_year, seq, model, truth, _blob(cur, pdf), 'pdf',
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
        served = rec.get('original_served_at')
        label = 'העתק' if served else 'מקור'
        if not served:
            cur.run('UPDATE business_documents SET original_served_at=now() WHERE id=%s', (doc_id,))
        _event(cur, doc_id, 'download', label, actor)
    ext = rec.get('file_ext', 'pdf')
    if fmt and fmt != ext:                       # re-render stored model in the asked format
        data = render(_model_from_dict(rec['model']), fmt, label=label)
        ext = fmt
    else:
        data = bytes(rec['pdf']) if rec.get('pdf') else render(_model_from_dict(rec['model']), ext, label=label)
    return data, '%s.%s' % (rec.get('doc_number') or doc_id, ext), label


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


def cancel(doc_id, reason, actor='api'):
    """Cancel an ISSUED document the compliant way: create a CREDIT_INVOICE that
    reverses it, then mark the original cancelled. Nothing is deleted."""
    rec = get(doc_id)
    if rec is None:
        raise KeyError(doc_id)
    if rec['status'] in _TERMINAL:
        raise PermissionError('document %s already %s' % (doc_id, rec['status']))
    credit = None
    if rec['status'] != DRAFT:
        cm = dict(rec['model'])
        cm['doc_type'] = 'INVOICE'          # credit note modelled as a reversing invoice
        cm['doc_id'] = ''                   # fresh CN-series number, not the original's
        cm['centralized'] = False
        cm['details_note'] = 'חשבונית זיכוי כנגד %s — %s' % (rec.get('doc_number'), reason)
        for l in cm.get('lines', []):
            for k in ('unit_price',):
                if k in l and isinstance(l[k], (int, float)):
                    l[k] = -abs(l[k])
        credit = create(cm, actor)
        credit = issue(credit['id'], series='CN', actor=actor, force=True)
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET status=%s, cancelled_by=%s, updated_at=now() '
                'WHERE id=%s', (CANCELLED, (credit or {}).get('id'), doc_id))
        _event(cur, doc_id, 'cancel', reason, actor)
        if credit:
            cur.run('UPDATE business_documents SET cancels=%s WHERE id=%s', (doc_id, credit['id']))
    out = get(doc_id)
    out['credit_document'] = credit
    return out


# which target types each source type may convert into (the sales-document graph)
CONVERSIONS = {
    'QUOTE':    ['ORDER', 'INVOICE', 'INVOICE_RECEIPT'],
    'ORDER':    ['SHIPMENT', 'INVOICE', 'INVOICE_RECEIPT'],
    'SHIPMENT': ['INVOICE', 'INVOICE_RECEIPT'],
    'INVOICE':  ['RECEIPT'],                       # collect payment -> issue receipt
}


def convert(doc_id, to_type, actor='api'):
    """Create a NEW DRAFT of `to_type` from a source document, carrying the customer +
    lines and linking back. The lifecycle spine is unchanged — the source stays as-is;
    the target is a fresh draft you then issue."""
    src = get(doc_id)
    if src is None:
        raise KeyError(doc_id)
    allowed = CONVERSIONS.get(src['doc_type'], [])
    if to_type not in allowed:
        raise ValueError('cannot convert %s -> %s (allowed: %s)'
                         % (src['doc_type'], to_type, allowed or 'none'))
    sm = src['model']
    # build a clean target model — carry only the fields the target type accepts;
    # source-type-specific fields (a quote's valid_until, or lines for a Receipt which
    # has none) would be rejected by the target model constructor
    if to_type == 'RECEIPT':                          # a receipt for the source's payment
        m = {'doc_type': to_type, 'doc_date': sm.get('doc_date'),
             'customer': sm.get('customer'),
             'amount': float(src.get('total') or 0),
             'nature': 'תשלום ע"ח %s' % (src.get('doc_number') or ''),
             'payment_method': sm.get('payment_method', 'מזומן')}
    else:                                             # line-carrying targets (invoice/order/shipment)
        m = {'doc_type': to_type, 'doc_date': sm.get('doc_date'),
             'customer': sm.get('customer'), 'lines': sm.get('lines', [])}
        if to_type in ('INVOICE', 'INVOICE_RECEIPT'):
            m['issued_at_shipping'] = True
            m['vat_pct'] = sm.get('vat_pct', 18)
    new = create(m, actor)
    with Cursor() as cur:
        cur.run('UPDATE business_documents SET converted_from=%s WHERE id=%s',
                (src.get('doc_number') or doc_id, new['id']))
        _event(cur, new['id'], 'convert', 'מ-%s (%s)' % (src.get('doc_number') or doc_id, src['doc_type']), actor)
        _event(cur, doc_id, 'converted', '→ %s' % to_type, actor)
    return get(new['id'])


def events(doc_id):
    with Cursor() as cur:
        return cur.run('SELECT ts, actor, action, detail FROM business_document_events '
                       'WHERE doc_id=%s ORDER BY id', (doc_id,)).all()


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
    with Cursor() as cur:
        rows = cur.run("SELECT doc_type, series, tax_year, seq_number FROM business_documents "
                       "WHERE seq_number IS NOT NULL ORDER BY doc_type, series, tax_year, seq_number").all()
    groups = {}
    for r in rows:
        groups.setdefault((r['doc_type'], r['series'], r['tax_year']), []).append(r['seq_number'])
    bad = {'/'.join(map(str, k)): v for k, v in groups.items()
           if v != list(range(1, len(v) + 1))}
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
