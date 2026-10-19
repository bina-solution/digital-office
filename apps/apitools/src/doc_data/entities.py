"""Single-business entities: business settings (the issuer), customers, items.

This deployment serves ONE business. `business_settings` is a singleton row that IS the
issuer identity used on every document; `customers` and `items` are its address book and
catalog. No tenancy — one deployment, one business.
"""
from __future__ import annotations

import time
import uuid

from .db import Cursor

SINGLETON = 'default'


# ── business settings (singleton issuer) ────────────────────────────────────
_DEFAULT_SETTINGS = {
    'id': SINGLETON, 'onboarded': False,
    'name': '', 'company_id': '', 'business_type': 'murshe',   # patur | murshe | company
    'street': '', 'city': '', 'zip': '', 'phone': '', 'fax': '', 'email': '',
    'logo_b64': '', 'vat_pct': 18.0, 'vat_registered': True,
    'default_series': 'A', 'doc_start': 0, 'bank_name': '', 'bank_branch': '', 'bank_account': '',
}


def get_business():
    with Cursor() as cur:
        row = cur.run('SELECT * FROM business_settings WHERE id=%s', (SINGLETON,)).one()
    if not row:
        return dict(_DEFAULT_SETTINGS)
    row['onboarded'] = bool(row.get('onboarded'))
    row['vat_registered'] = bool(row.get('vat_registered'))
    return row


def save_business(patch, actor='api'):
    cur_row = get_business()
    m = {**cur_row, **{k: v for k, v in (patch or {}).items() if k in _DEFAULT_SETTINGS}}
    try:
        m['doc_start'] = int(m.get('doc_start') or 0)   # numbering start comes from a text form
    except (TypeError, ValueError):
        m['doc_start'] = 0
    # a business_type of 'patur' (עוסק פטור) does not charge VAT
    if m.get('business_type') == 'patur':
        m['vat_pct'] = 0.0
        m['vat_registered'] = False
    m['onboarded'] = bool(m.get('name') and m.get('company_id'))
    cols = [k for k in _DEFAULT_SETTINGS if k != 'id']
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
    return get_business()


def issuer_party():
    """The business as a doc_models Party dict, for use as document supplier."""
    b = get_business()
    return {'name': b['name'], 'company_id': b['company_id'], 'street': b['street'],
            'city': b['city'], 'zip': b['zip'], 'phone': b['phone'], 'fax': b['fax'],
            'email': b['email'], 'vat_file_no': b['company_id'],
            'tax_status': b.get('business_type', 'murshe')}


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


# public per-entity wrappers
def list_customers(q=None): return _list('customers', q)
def create_customer(b): return _create('customers', b)
def get_customer(i): return _get('customers', i)
def update_customer(i, b): return _update('customers', i, b)
def delete_customer(i): return _delete('customers', i)

def list_items(q=None): return _list('items', q)
def create_item(b): return _create('items', b)
def get_item(i): return _get('items', i)
def update_item(i, b): return _update('items', i, b)
def delete_item(i): return _delete('items', i)
