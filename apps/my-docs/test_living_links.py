"""The living document's links through the BFF (DGO-2047): a view link to send, the links a document went out in, a new
link and a closed one, and a draft whose open view links follow it when it is saved or issued — run against the REAL
app.py, with the ledger (apitools) and esign as small stand-ins on this machine that record what they were asked.

    python3 -m unittest -v test_living_links          (stdlib + flask + requests: the my-docs image's own)
"""
import json
import os
import sys
import threading
import unittest
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Stub:
    """One HTTP stand-in: `routes` maps (method, path) to a function(handler, query, body) -> (status, body, headers)."""

    def __init__(self, routes):
        self.calls, outer = [], self

        class H(BaseHTTPRequestHandler):
            def _go(self):
                u = urlparse(self.path)
                n = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(n) if n else b''
                outer.calls.append((self.command, u.path, parse_qs(u.query), body, dict(self.headers)))
                fn = routes.get((self.command, u.path)) or routes.get((self.command, '*'))
                status, out, headers = fn(self, parse_qs(u.query), body) if fn else (404, b'{"error":"nf"}', {})
                if isinstance(out, (dict, list)):
                    out = json.dumps(out, ensure_ascii=False).encode()
                    headers = dict({'Content-Type': 'application/json'}, **headers)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            do_GET = do_POST = do_PUT = do_PATCH = _go

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = 'http://127.0.0.1:%d' % self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def multipart(handler, body):
    """A multipart form as {name: str | bytes}: a file's bytes, a field's UTF-8 text (the email parser; no cgi)."""
    msg = BytesParser(policy=HTTP).parsebytes(
        b'Content-Type: ' + handler.headers['Content-Type'].encode() + b'\r\n\r\n' + body)
    out = {}
    for part in msg.iter_parts():
        name = part.get_param('name', header='content-disposition')
        data = part.get_payload(decode=True)
        out[name] = data if part.get_filename() else data.decode('utf-8')
    return out


class Ledger:
    """apitools' /documents, as far as these routes ask it."""

    def __init__(self):
        self.docs = {
            'doc_q': {'id': 'doc_q', 'doc_type': 'QUOTE', 'status': 'draft', 'doc_number': None,
                      'customer_name': 'קבוצת אורן בע״מ', 'model': {'customer': {'name': 'קבוצת אורן בע״מ'}}},
            'doc_x': {'id': 'doc_x', 'doc_type': 'QUOTE', 'status': 'cancelled', 'doc_number': 'QT-2026-00009',
                      'customer_name': 'סטודיו גפן'},
        }
        self.version = 1
        self.events = {'doc_q': [{'action': 'send', 'detail': 'חתימה · דנה לוי · env_s1'}]}
        r = {
            ('GET', '/business'): lambda h, q, b: (200, {'name': 'בינה סולושנס'}, {}),
            ('GET', '/docGen/house/types'): lambda h, q, b: (200, {'types': [{'code': 'QUOTE', 'he': 'הצעת מחיר'}]}, {}),
            ('GET', '*'): self.get, ('PATCH', '*'): self.patch, ('POST', '*'): self.post,
        }
        self.stub = Stub(r)

    def _doc(self, path):
        parts = path.strip('/').split('/')
        return (self.docs.get(parts[1]), parts[2] if len(parts) > 2 else '') if parts[0] == 'documents' and len(parts) > 1 else (None, '')

    def get(self, h, q, b):
        d, act = self._doc(h.path.split('?')[0])
        if d is None:
            return 404, {'error': 'not_found'}, {}
        if act == 'download':
            return 200, b'%PDF-1.7 ' + d['id'].encode() + b' v%d' % self.version, {'Content-Type': 'application/pdf'}
        if act == 'events':
            return 200, self.events.get(d['id'], []), {}
        return 200, d, {}

    def patch(self, h, q, b):
        d, _ = self._doc(h.path.split('?')[0])
        if d is None:
            return 404, {'error': 'not_found'}, {}
        if d['status'] != 'draft':
            return 409, {'error': 'PermissionError', 'message': 'immutable'}, {}
        d.setdefault('model', {}).update(json.loads(b or b'{}'))
        self.version += 1
        return 200, d, {}

    def post(self, h, q, b):
        d, act = self._doc(h.path.split('?')[0])
        if d is None:
            return 404, {'error': 'not_found'}, {}
        if act == 'issue':
            d['status'], d['doc_number'] = 'issued', 'QT-2026-00032'
            self.version += 1
            return 200, d, {}
        return 404, {'error': 'nf'}, {}


class Esign:
    """esign's office half: envelopes by kind and ref, a file replaced, a link minted again, a link closed."""

    def __init__(self):
        self.envs, self.files, self.n = {}, {}, 0
        self.envs['env_s1'] = {'id': 'env_s1', 'kind': 'sign', 'status': 'sent', 'signer_name': 'דנה לוי',
                               'created_at': '2026-11-19T10:00:00Z', 'expires_at': '2099-01-01T00:00:00Z', 'ref': None}
        self.stub = Stub({('GET', '*'): self.get, ('POST', '*'): self.post, ('PUT', '*'): self.put})

    def get(self, h, q, b):
        p = urlparse(h.path).path
        if p == '/healthz':                      # esign's own (server.py): the BFF asks it before a document is read
            return 200, {'ok': True}, {}
        if p == '/api/envelopes':
            ref = (q.get('ref') or [''])[0]
            items = [e for e in self.envs.values() if not ref or e.get('ref') == ref]
            return 200, {'ok': True, 'data': {'items': items}}, {}
        eid = p.rsplit('/', 1)[-1]
        if eid in self.envs:
            return 200, {'ok': True, 'data': {'envelope': self.envs[eid]}}, {}
        return 404, {'ok': False}, {}

    def post(self, h, q, b):
        p = urlparse(h.path).path
        if p == '/api/envelopes':
            f = multipart(h, b)
            self.n += 1
            eid = 'env_v%d' % self.n
            self.envs[eid] = {'id': eid, 'kind': f.get('kind', 'sign'), 'ref': f.get('ref'), 'status': 'sent',
                              'signer_name': f.get('signer', ''), 'created_at': '2026-11-20T10:0%d:00Z' % self.n,
                              'expires_at': '2099-01-01T00:00:00Z', 'form': {k: v for k, v in f.items() if k != 'file'}}
            self.files[eid] = f['file']
            return 200, {'ok': True, 'data': {'envelope': self.envs[eid], 'link': 'https://sign.test/s/tok%d' % self.n}}, {}
        eid, act = p.split('/')[3], p.split('/')[4]
        e = self.envs.get(eid)
        if not e or e['status'] in ('cancelled', 'signed'):
            return 409, {'ok': False, 'detail': 'closed'}, {}
        if act == 'cancel':
            e['status'] = 'cancelled'
            return 200, {'ok': True, 'data': {'envelope': e}}, {}
        if act == 'link':
            return 200, {'ok': True, 'data': {'envelope': e, 'link': 'https://sign.test/s/new-' + eid}}, {}
        return 404, {'ok': False}, {}

    def put(self, h, q, b):
        eid = urlparse(h.path).path.split('/')[3]
        e = self.envs.get(eid)
        if not e or e['kind'] != 'view':
            return 409, {'ok': False}, {}
        self.files[eid] = multipart(h, b)['file']
        return 200, {'ok': True, 'data': {'envelope': e}}, {}


class LivingLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.esign = Ledger(), Esign()
        os.environ['APITOOLS_URL'] = cls.ledger.stub.url
        os.environ['ESIGN_URL'] = cls.esign.stub.url
        os.environ['DOCUMENTS_URL'] = 'http://127.0.0.1:9'
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import app as bff
        cls.cl = bff.app.test_client()

    def share(self, doc='doc_q', **body):
        return self.cl.post('/api/share/' + doc, json=body)

    def test_1_a_draft_is_shared_as_a_view_link_named_for_people(self):
        r = self.share(to='דנה לוי', days=7, password='אורן')
        self.assertEqual(r.status_code, 200, r.data)
        j = r.get_json()
        self.assertTrue(j['ok'])
        self.assertTrue(j['link'].startswith('https://sign.test/s/'))
        env = self.esign.envs[j['envelope']['id']]
        self.assertEqual((env['kind'], env['ref']), ('view', 'doc_q'))
        self.assertEqual(env['form']['name'], 'הצעת מחיר (טיוטה) — קבוצת אורן בע״מ.pdf')
        self.assertEqual((env['form']['days'], env['form']['password'], env['form']['sender']), ('7', 'אורן', 'בינה סולושנס'))
        self.assertTrue(self.esign.files[env['id']].startswith(b'%PDF'))

    def test_2_a_cancelled_document_and_a_bad_term_are_refused(self):
        self.assertEqual(self.share('doc_x').status_code, 409)
        self.assertEqual(self.share(days='שבוע').status_code, 400)
        self.assertEqual(self.share('doc_nope').status_code, 404)

    def test_3_the_links_list_says_every_link_with_its_state(self):
        self.share()
        j = self.cl.get('/api/links/doc_q').get_json()
        self.assertTrue(j['ok'])
        kinds = {(e['kind'], e['state']) for e in j['links']}
        self.assertIn(('view', 'sent'), kinds)
        self.assertIn(('sign', 'sent'), kinds)                 # the one-signer envelope, found by the ledger's trail

    def test_4_saving_a_draft_gives_its_open_view_links_the_new_document(self):
        vid = self.share().get_json()['envelope']['id']
        closed = self.share().get_json()['envelope']['id']
        self.cl.post('/api/links/%s/revoke' % closed)
        before = self.esign.files[closed]
        r = self.cl.patch('/api/documents/doc_q', json={'subject': 'סדנה'})
        self.assertEqual(r.status_code, 200, r.data)
        followed = r.headers['X-Views-Followed'].split('/')
        self.assertEqual(followed[0], followed[1])
        self.assertEqual(self.ledger.docs['doc_q']['model']['subject'], 'סדנה')       # the body reached the ledger
        self.assertTrue(self.esign.files[vid].endswith(b'v%d' % self.ledger.version))  # the new bytes
        self.assertEqual(self.esign.files[closed], before)                           # a closed link keeps what it had

    def test_5_a_refused_save_is_the_answer_and_moves_no_link(self):
        self.ledger.docs['doc_i'] = {'id': 'doc_i', 'doc_type': 'QUOTE', 'status': 'issued', 'doc_number': 'QT-1'}
        n = len(self.esign.stub.calls)
        r = self.cl.patch('/api/documents/doc_i', json={'subject': 'x'})
        self.assertEqual(r.status_code, 409)
        self.assertNotIn('X-Views-Followed', r.headers)
        self.assertFalse([c for c in self.esign.stub.calls[n:] if c[0] == 'PUT'])

    def test_6_a_read_of_a_document_still_goes_through_the_proxy(self):
        r = self.cl.get('/api/documents/doc_q')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['id'], 'doc_q')

    def test_7_a_new_link_and_a_closed_one(self):
        vid = self.share().get_json()['envelope']['id']
        r = self.cl.post('/api/links/%s/again' % vid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['link'], 'https://sign.test/s/new-' + vid)
        self.assertEqual(self.cl.post('/api/links/%s/revoke' % vid).status_code, 200)
        self.assertEqual(self.cl.post('/api/links/%s/again' % vid).status_code, 409)   # closed: no new link

    def test_8_issuing_through_the_screen_gives_the_view_link_the_issued_document(self):
        self.ledger.docs['doc_z'] = {'id': 'doc_z', 'doc_type': 'QUOTE', 'status': 'draft', 'doc_number': None,
                                     'customer_name': 'סטודיו גפן'}
        vid = self.share('doc_z').get_json()['envelope']['id']
        r = self.cl.post('/api/documents/doc_z/issue')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.headers['X-Views-Followed'], '1/1')
        self.assertEqual(self.ledger.docs['doc_z']['status'], 'issued')
        self.assertTrue(self.esign.files[vid].startswith(b'%PDF-1.7 doc_z'))


if __name__ == '__main__':
    unittest.main()
