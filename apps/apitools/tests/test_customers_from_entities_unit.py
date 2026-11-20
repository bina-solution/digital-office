"""The documents' customers are «ישויות»' (DGO-2101), and the ledger's own old list moves there once.

On the ledger's own SQLite fallback, against stand-ins of entities.v1 — the routes the ledger calls, answered as
apps/entities/app.py answers them (an app's test never reaches into another app's code), the token checked as its
door checks it, its limits (a name of 200, a value of 2000) held as its store holds them:

  * with no ENTITIES_URL, while «ישויות» does not resolve or does not answer, when something else answers in its
    place (a link's door with no such app: an empty 404; another service's /healthz), or when the hand-over fails
    (a wrong token) — the ledger's own table is the list, as before: nothing moves, nothing is marked, no 502;
  * the first time «ישויות» answers as itself, the table moves there — every row, none refused (a row with no name is
    named by its number; the address as street, city, zip, a city with no street kept as a city) — the row is
    marked with where it went, and a second hand-over brings what came in meanwhile; a restart moves nothing again;
  * from then on `/customers` is «ישויות»' customers in the table's shape: a customer added from a document is
    added there with the role customer, a change keeps what it did not name (the street when the city changes),
    an editor that sends `company_id: ''` adds no empty company record, notes come back as they were, a removal
    archives a customer that is only that and only takes the role off one that is also our supplier;
  * once moved, nothing answers from the old table — not a silent «ישויות», not a door's empty 404, not an emptied
    ENTITIES_URL, not an old `cus_` id — and a settings save cannot unmark the move;
  * pointed at another «ישויות», the old table is handed to it too and the mark follows.

    python3 -m unittest tests.test_customers_from_entities_unit -v      # from apps/apitools, in its image
"""
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

os.environ['no_proxy'] = os.environ['NO_PROXY'] = '127.0.0.1,localhost'

from src.doc_data import db, entities  # noqa: E402

NOWHERE = 'http://no-such-office.invalid:8999'
_resolve = socket.getaddrinfo


def _no_such_office(host, *a, **kw):
    """The name of an office that runs no «ישויות» does not resolve — at once, with or without a resolver here."""
    if host == 'no-such-office.invalid':
        raise socket.gaierror(socket.EAI_NONAME, 'Name or service not known')
    return _resolve(host, *a, **kw)


def _merge(cur, patch):
    out = dict(cur)
    for k, v in (patch or {}).items():
        if v:
            out[k] = str(v)
        else:
            out.pop(k, None)
    return out


class Entities(BaseHTTPRequestHandler):
    """entities.v1 as the ledger calls it. `self.server.s` holds this «ישויות»' records and how it behaves:
    up (False: 503), door (True: every route an empty 404, as a link's door with no such app), service (what its
    /healthz calls itself)."""

    def _send(self, code, obj=None):
        body = b'' if obj is None else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _create(self, kind, name, fields=None, roles=None):
        s = self.server.s
        name = str(name or '').strip()
        if not name:
            raise ValueError('חסר שם')
        if len(name) > 200 or any(len(str(v)) > 2000 for v in (fields or {}).values()):
            raise ValueError('ארוך מדי')
        if kind not in ('person', 'organization'):
            raise ValueError('סוג לא מוכר')
        eid = 'ent_%04d%s' % (len(s['ents']) + 1, s['tag'])
        s['ents'][eid] = {'id': eid, 'kind': kind, 'name': name, 'fields': _merge({}, fields),
                          'roles': {r: _merge({}, f) for r, f in (roles or {}).items()}, 'archived': False}
        return s['ents'][eid]

    @staticmethod
    def _party(e):
        f, company, customer = e['fields'], e['roles'].get('company') or {}, e['roles'].get('customer') or {}
        number = company.get('business_number', '')
        return {'entity_id': e['id'], 'name': company.get('legal_name') or e['name'],
                'company_id': re.sub(r'\D', '', number) or number, 'tax_status': '',
                'street': f.get('street', ''), 'city': f.get('city', ''), 'zip': f.get('zip', ''),
                'phone': f.get('phone', ''), 'email': customer.get('billing_email') or f.get('email', ''),
                'customer_no': customer.get('customer_no', ''), 'contact_person': '', 'notes': f.get('notes', '')}

    def _route(self, method):
        s = self.server.s
        u = urllib.parse.urlsplit(self.path)
        s['calls'].append((method, u.path))
        if s['door']:
            return self._send(404)
        if not s['up']:
            return self._send(503, {'detail': 'starting'})
        if u.path == '/healthz':
            return self._send(200, {'ok': True, 'service': s['service']})
        if self.headers.get('Authorization') != 'Bearer tok-ledger':
            return self._send(401, {'detail': 'entities answers its own CLI and a caller with its token'})
        n = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(n) or b'{}') if n else {}
        q = dict(urllib.parse.parse_qsl(u.query))
        p = u.path.strip('/').split('/')
        try:
            if method == 'GET' and u.path == '/api/parties':
                words = (q.get('q') or '').lower()
                rows = [e for e in s['ents'].values() if not e['archived'] and (q.get('role') or '') in e['roles']
                        and words in ' '.join([e['name'], *e['fields'].values(),
                                               *(v for f in e['roles'].values() for v in f.values())]).lower()]
                return self._send(200, {'parties': [self._party(e) for e in sorted(rows, key=lambda e: e['name'])]})
            if method == 'POST' and u.path == '/api/import':
                s['imports'] = s.get('imports', 0) + 1
                if s.get('fail_second_import') and s['imports'] == 2:
                    return self._send(503, {'detail': 'restarting'})
                made, kept, refused = 0, 0, []
                for i, row in enumerate(body['rows']):
                    if row['source'] in s['sources']:
                        kept += 1
                        continue
                    try:
                        e = self._create(row['kind'], row['name'], row.get('fields'), row.get('roles'))
                    except ValueError as err:
                        refused.append({'row': i, 'source': row['source'], 'detail': str(err)})
                        continue
                    s['sources'][row['source']] = e['id']
                    made += 1
                return self._send(200, {'created': made, 'kept': kept, 'refused': refused})
            if method == 'POST' and u.path == '/api/entities':
                return self._send(200, self._create(body.get('kind', ''), body.get('name', ''), body.get('fields'),
                                                    body.get('roles')))
            if p[:2] == ['api', 'entities'] and len(p) >= 3:
                e, rest = s['ents'].get(p[2]), p[3:]
                if e is None:
                    return self._send(404, {'detail': 'no such entity: %s' % p[2]})
                if not rest and method == 'GET':
                    return self._send(200, e)
                if not rest and method == 'PATCH':
                    if 'name' in body:
                        e['name'] = body['name']
                    e['fields'] = _merge(e['fields'], body.get('fields'))
                    return self._send(200, e)
                if rest == ['party'] and method == 'GET':
                    return self._send(200, self._party(e))
                if rest[:1] == ['roles'] and len(rest) == 2 and method == 'PUT':
                    e['roles'][rest[1]] = _merge(e['roles'].get(rest[1]) or {}, body.get('fields'))
                    return self._send(200, e)
                if rest[:1] == ['roles'] and len(rest) == 2 and method == 'DELETE':
                    e['roles'].pop(rest[1], None)
                    return self._send(200, e)
                if rest == ['archive'] and method == 'POST':
                    e['archived'] = bool(body.get('archived', True))
                    return self._send(200, e)
            return self._send(404, {'detail': 'Not Found'})
        except ValueError as e:
            return self._send(400, {'detail': str(e)})

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def do_PATCH(self):
        self._route('PATCH')

    def do_PUT(self):
        self._route('PUT')

    def do_DELETE(self):
        self._route('DELETE')

    def log_message(self, *a):
        pass


def _serve(tag):
    srv = HTTPServer(('127.0.0.1', 0), Entities)
    srv.s = {'ents': {}, 'sources': {}, 'calls': [], 'up': True, 'door': False, 'service': 'entities', 'tag': tag}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


class TestCustomersFromEntities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp(prefix='ledger-customers-'))
        for k in [k for k in os.environ if k.startswith(('DOC_DB_', 'SUPABASE_DB_'))]:
            os.environ.pop(k)
        db._STATE.update(conn=None, pg=None, schema_done=False)
        cls.srv, cls.url = _serve('a')
        cls.srv2, cls.url2 = _serve('b')
        cls.s = cls.srv.s
        cls._was = (entities.ENTITIES_URL, entities.ENTITIES_TOKEN, entities.BRAND_URL)
        entities.ENTITIES_TOKEN = 'tok-ledger'
        entities.BRAND_URL = ''

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv2.shutdown()
        entities.ENTITIES_URL, entities.ENTITIES_TOKEN, entities.BRAND_URL = cls._was
        entities._MOVED.update(to='', said='', probe_at=-entities.PROBE_TTL)
        os.chdir(cls._cwd)

    def _use(self, url, up=True, door=False, service='entities'):
        entities.ENTITIES_URL = url
        entities.ENTITIES_TOKEN = 'tok-ledger'
        entities._MOVED.update(to='', said='', probe_at=-entities.PROBE_TTL)   # as after a restart: the row remembers
        self.s.update(up=up, door=door, service=service)

    def imports(self, s=None):
        return (s or self.s)['calls'].count(('POST', '/api/import'))

    def test_1_without_entities_the_table_is_the_list(self):
        self._use('')
        a = entities.create_customer({'name': 'קבוצת אורן בע״מ', 'company_id': '516123457', 'street': 'הרצל 1',
                                      'city': 'חיפה', 'zip': '3303101', 'phone': '04-0000009',
                                      'email': 'billing@oren.example', 'notes': 'משלמים בשוטף + 30'})
        entities.create_customer({'name': 'דנה לוי', 'phone': '050-1111111', 'city': 'עכו'})
        entities.create_customer({'name': '', 'company_id': '512345678'})           # a row with no name
        self.assertTrue(a['id'].startswith('cus_'))
        self.assertEqual(len(entities.list_customers()), 3)
        self.assertEqual(entities._row().get('parties_from') or '', '')

    @mock.patch('socket.getaddrinfo', _no_such_office)
    def test_2_nothing_moves_until_entities_itself_takes_them(self):
        self._use(NOWHERE)
        self.assertEqual(len(entities.list_customers()), 3)
        self._use(self.url, up=False)
        self.assertEqual(len(entities.list_customers()), 3)
        self._use(self.url, door=True)                  # a link's door with no such app: an empty 404
        self.assertEqual(len(entities.list_customers()), 3)
        self._use(self.url, service='documents')        # something answers, but not as «ישויות»
        self.assertEqual(len(entities.list_customers()), 3)
        self._use(self.url)
        entities.ENTITIES_TOKEN = 'wrong'               # the hand-over fails (401): still the old table, not a 502
        self.assertEqual(len(entities.list_customers()), 3)
        self.assertEqual(entities._row().get('parties_from') or '', '')
        self.assertEqual(self.s['ents'], {})
        held = self.s['calls'][:]                       # a probe that failed is held: no second ask for a while
        entities.list_customers()
        self.assertEqual(self.s['calls'], held)

    def test_3_the_first_answer_moves_them_once(self):
        self._use(self.url)
        before = self.imports()                         # test 2's refused hand-over (401) is counted there
        rows = entities.list_customers()
        self.assertEqual(entities._row().get('parties_from'), self.url)
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.imports() - before, 2)    # the hand-over, and what came in meanwhile
        self.assertTrue(all(c['id'].startswith('ent_') and c['source'] == 'entities' for c in rows), rows)
        oren = next(c for c in rows if c['company_id'] == '516123457')
        self.assertEqual((oren['name'], oren['street'], oren['city'], oren['zip'], oren['email'], oren['notes']),
                         ('קבוצת אורן בע״מ', 'הרצל 1', 'חיפה', '3303101', 'billing@oren.example', 'משלמים בשוטף + 30'))
        self.assertEqual(self.s['ents'][oren['id']]['kind'], 'organization')
        dana = next(c for c in rows if c['name'] == 'דנה לוי')
        self.assertEqual((dana['street'], dana['city']), ('', 'עכו'))      # a city with no street stays a city
        self.assertEqual(self.s['ents'][dana['id']]['kind'], 'person')
        self.assertIn('512345678', [c['name'] for c in rows])               # no name: named by its number
        self._use(self.url)                             # a restart: the row remembers, nothing is handed over again
        self.assertEqual(len(entities.list_customers()), 3)
        self.assertEqual(self.imports() - before, 2)
        self.assertEqual([c['name'] for c in entities.list_customers('אורן')], ['קבוצת אורן בע״מ'])

    def test_4_a_document_adds_changes_and_removes_there(self):
        self._use(self.url)
        c = entities.create_customer({'name': 'מעבדת שקד', 'company_id': '51-555555-1', 'street': 'האלה 3',
                                      'city': 'עכו'})
        self.assertEqual(sorted(self.s['ents'][c['id']]['roles']), ['company', 'customer'])
        self.assertEqual(c['company_id'], '515555551')
        c = entities.update_customer(c['id'], {'city': 'נהריה', 'phone': '04-0000010'})
        self.assertEqual((c['street'], c['city'], c['phone']), ('האלה 3', 'נהריה', '04-0000010'))
        c = entities.update_customer(c['id'], {'name': 'מעבדת שקד בע״מ'})
        self.assertEqual(entities.get_customer(c['id'])['name'], 'מעבדת שקד בע״מ')
        self.s['ents'][c['id']]['roles']['customer']['billing_email'] = 'ap@shaked.example'
        entities.update_customer(c['id'], {'email': 'invoices@shaked.example'})
        self.assertEqual(self.s['ents'][c['id']]['roles']['customer']['billing_email'], 'invoices@shaked.example')
        # an editor that always sends the whole form: no empty company record for a private customer
        dana = next(x for x in entities.list_customers() if x['name'] == 'דנה לוי')
        entities.update_customer(dana['id'], {**dana, 'phone': '050-2222222', 'company_id': ''})
        self.assertEqual(sorted(self.s['ents'][dana['id']]['roles']), ['customer'])
        # also our supplier: it stops being a customer, and stays a supplier
        self.s['ents'][c['id']]['roles']['supplier'] = {'bank_name': 'לאומי'}
        self.assertEqual(entities.delete_customer(c['id']), {'deleted': c['id'], 'role_removed': 'customer'})
        self.assertEqual(sorted(self.s['ents'][c['id']]['roles']), ['company', 'supplier'])
        self.assertFalse(self.s['ents'][c['id']]['archived'])
        # only a customer: archived
        self.assertEqual(entities.delete_customer(dana['id']), {'deleted': dana['id'], 'archived': True})
        self.assertTrue(self.s['ents'][dana['id']]['archived'])
        self.assertNotIn(dana['id'], [x['id'] for x in entities.list_customers()])
        self.assertIsNone(entities.get_customer('ent_nosuchthing'))
        with self.assertRaises(entities.CustomerNotFound):
            entities.update_customer('ent_nosuchthing', {'name': 'x'})
        self.assertEqual(len(entities._list('customers')), 3)   # the old table is not written to

    def test_5_refusals_and_old_ids(self):
        self._use(self.url)
        with self.assertRaises(entities.EntitiesRefused) as r:
            entities.create_customer({'name': ''})
        self.assertIn('חסר שם', str(r.exception))
        old = entities._list('customers')[0]['id']
        with self.assertRaises(entities.EntitiesRefused):
            entities.update_customer(old, {'name': 'x'})
        self.assertIsNone(entities.get_customer(old))           # moved: an old id answers no more
        entities.ENTITIES_TOKEN = 'wrong'
        with self.assertRaises(entities.EntitiesUnreachable) as r:
            entities.list_customers()
        self.assertIn('401', str(r.exception))

    @mock.patch('socket.getaddrinfo', _no_such_office)
    def test_6_once_moved_nothing_answers_from_the_old_table(self):
        self._use(self.url, up=False)                   # a restart, and «ישויות» is not up yet
        with self.assertRaises(entities.EntitiesUnreachable) as r:
            entities.list_customers()
        self.assertIn('503', str(r.exception))
        self._use(self.url, door=True)                  # a door's empty 404 is not «no such entity», nor an empty list
        with self.assertRaises(entities.EntitiesUnreachable):
            entities.list_customers()
        with self.assertRaises(entities.EntitiesUnreachable):
            entities.update_customer(next(iter(self.s['ents'])), {'name': 'x'})
        self._use('')                                   # ENTITIES_URL emptied after the move
        with self.assertRaises(entities.EntitiesUnreachable) as r:
            entities.list_customers()
        self.assertIn('ENTITIES_URL is empty', str(r.exception))
        self._use(NOWHERE)
        with self.assertRaises(entities.EntitiesUnreachable):
            entities.list_customers()

    def test_7_a_save_of_the_settings_does_not_unmark_the_move(self):
        self._use(self.url)
        stale = dict(entities._row(), parties_from='')  # a row read before the move, written back after it
        entities._write(stale)
        self.assertEqual(entities._row().get('parties_from'), self.url)
        entities.save_business({'parties_from': '', 'default_series': 'B'})
        self.assertEqual(entities._row().get('parties_from'), self.url)
        self.assertEqual(entities._row().get('default_series'), 'B')

    def test_8_pointed_at_another_entities_the_old_table_follows(self):
        self._use(self.url2)
        rows = entities.list_customers()
        self.assertEqual(entities._row().get('parties_from'), self.url2)
        self.assertEqual(sorted(c['name'] for c in rows), sorted(e['name'] for e in self.srv2.s['ents'].values()))
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.imports(self.srv2.s), 2)

    def test_9_marked_is_moved_even_when_the_second_hand_over_fails(self):
        srv3, url3 = _serve('c')
        try:
            srv3.s['fail_second_import'] = True
            entities._write_cols({'parties_from': ''})  # an office not moved yet, as before test 3
            self._use(url3)
            c = entities.create_customer({'name': 'לקוח חדש', 'phone': '03-1234567'})
            self.assertTrue(c['id'].startswith('ent_'), c)   # answered from «ישויות», never the old table
            self.assertEqual(entities._row().get('parties_from'), url3)
            self.assertEqual(self.imports(srv3.s), 2)        # the hand-over, and the second one that failed
            self.assertEqual(len(entities._list('customers')), 3)
        finally:
            srv3.shutdown()


if __name__ == '__main__':
    unittest.main()
