"""«חתימות» inside «מסמכים» through the BFF (DGO-2169, step 4) — run against the REAL app.py, with the ledger and esign
as the stand-ins of test_living_links (they record what they were asked):

- every link in one list, newest first: one-signer envelopes, view links and «מילוי וחתימה» events, each with its
  state in the screen's words, the document it belongs to named, and a fill event's sides counted;
- esign silent → `ok: false`, never an empty list that reads as «nothing was sent»;
- «חתימה על קובץ»: a PDF goes to esign as a signature envelope with the business as its sender; a file that is not
  a PDF, a missing signer and a bad term are refused in Hebrew, and esign is never asked.

    python3 -m unittest -v test_signatures          (stdlib + flask + requests: the my-docs image's own)
"""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_living_links import Esign, Ledger  # noqa: E402


class ListingLedger(Ledger):
    """The ledger, with its list of documents (`/documents?limit=…`), which names the documents links belong to, an
    issued quote to send to sign, and the trail's `send` that «שליחה לחתימה» writes."""

    def __init__(self):
        super().__init__()
        self.docs['doc_s'] = {'id': 'doc_s', 'doc_type': 'QUOTE', 'status': 'issued', 'doc_number': 'QT-5',
                              'customer_name': 'סטודיו גפן'}

    def get(self, h, q, b):
        if h.path.split('?')[0] == '/documents':
            return 200, list(self.docs.values()), {}
        return super().get(h, q, b)

    def post(self, h, q, b):
        d, act = self._doc(h.path.split('?')[0])
        if d is not None and act == 'send':
            return 200, {'ok': True}, {}
        return super().post(h, q, b)


class FillEsign(Esign):
    """esign, with its «מילוי וחתימה» events too, and a switch that silences it. (The stand-in's router holds the bound
    `self.get`, so overriding the method is what routes to it.)"""

    def __init__(self):
        self.down = False
        self.events = [
            {'id': 'fev1', 'status': 'open', 'ref': 'doc_q', 'doc_name': 'הצעה.pdf', 'title': 'הצעה',
             'created_at': '2026-11-21T09:00:00Z', 'expires': '2099-01-01',
             'parties': [{'label': 'הלקוח', 'signer': '', 'state': 'filling'}, {'label': 'הספק', 'signer': 'דנה', 'state': 'signed'}]},
            {'id': 'fev2', 'status': 'complete', 'ref': None, 'doc_name': 'טופס.pdf', 'title': 'טופס',
             'created_at': '2026-11-10T09:00:00Z', 'expires': '2099-01-01', 'completed_at': '2026-11-11T09:00:00Z',
             'parties': [{'label': 'הלקוח', 'signer': 'משה', 'state': 'signed'}]},
            # a draft the editor made and nobody sent: never a row
            {'id': 'fev3', 'status': 'draft', 'ref': 'doc_q', 'doc_name': 'הצעה.pdf', 'title': 'הצעה',
             'created_at': '2026-11-22T09:00:00Z', 'expires': '2099-01-01', 'parties': [{'label': 'הלקוח', 'state': 'waiting'}]},
        ]
        super().__init__()
        self.envs['env_sg'] = {'id': 'env_sg', 'kind': 'sign', 'status': 'signing', 'signer_name': 'דנה', 'ref': None,
                               'created_at': '2026-11-18T10:00:00Z', 'expires_at': '2099-01-01T00:00:00Z'}

    def get(self, h, q, b):
        if self.down:
            return 503, b'down', {'Content-Type': 'text/plain'}
        if h.path.split('?')[0] == '/api/events':
            return 200, {'ok': True, 'items': self.events}, {}
        return super().get(h, q, b)


class Signatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.esign = ListingLedger(), FillEsign()
        os.environ['APITOOLS_URL'] = cls.ledger.stub.url
        os.environ['ESIGN_URL'] = cls.esign.stub.url
        os.environ['DOCUMENTS_URL'] = 'http://127.0.0.1:9'
        import app as bff
        cls.bff, cls.cl = bff, bff.app.test_client()

    def share(self, doc='doc_q'):
        return self.cl.post('/api/share/' + doc, json={'to': 'דנה'}).get_json()

    def test_1_every_link_in_one_list_newest_first(self):
        view = self.share()['envelope']['id']
        r = self.cl.get('/api/signatures')
        self.assertEqual(r.status_code, 200, r.data)
        j = r.get_json()
        self.assertTrue(j['ok'], j)
        kinds = {(x['kind'], x['id']) for x in j['links']}
        self.assertIn(('view', view), kinds)
        self.assertIn(('sign', 'env_s1'), kinds)                  # the one-signer envelope
        self.assertIn(('fill', 'fev1'), kinds)                    # «מילוי וחתימה»
        stamps = [x['created_at'] or '' for x in j['links']]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_2_states_in_the_screens_words_and_a_fill_counted(self):
        j = self.cl.get('/api/signatures').get_json()
        by = {x['id']: x for x in j['links']}
        self.assertEqual((by['fev1']['state'], by['fev1']['signed'], by['fev1']['parties']), ('opened', 1, 2))
        self.assertEqual(by['fev2']['state'], 'signed')
        self.assertEqual(by['env_s1']['state'], 'sent')
        self.assertEqual(by['fev1']['doc'], 'הצעת מחיר — קבוצת אורן בע״מ')     # the document it belongs to, named
        self.assertIsNone(by['fev2']['doc'])                                   # a file of its own: no document

    def test_2b_a_document_sent_to_sign_is_listed_under_its_document(self):
        r = self.cl.post('/api/sign/doc_s', json={'signer': 'דנה'})
        self.assertEqual(r.status_code, 200, r.data)
        eid = r.get_json()['envelope']['id']
        self.assertEqual(self.esign.envs[eid]['ref'], 'doc_s')                 # «שליחה לחתימה» sends its document's id
        by = {x['id']: x for x in self.cl.get('/api/signatures').get_json()['links']}
        self.assertEqual((by[eid]['ref'], by[eid]['doc']), ('doc_s', 'הצעת מחיר QT-5 — סטודיו גפן'))

    def test_2c_a_draft_is_no_row_and_a_signature_in_flight_is_its_own_state(self):
        j = self.cl.get('/api/signatures').get_json()
        by = {x['id']: x for x in j['links']}
        self.assertNotIn('fev3', by)                                           # never sent: not «נשלח»
        self.assertEqual(by['env_sg']['state'], 'signing')

    def test_2d_a_reading_full_to_its_limit_says_so(self):
        self.assertFalse(self.cl.get('/api/signatures').get_json()['more'])
        was, self.bff._LIST_EVENTS = self.bff._LIST_EVENTS, 2
        try:
            self.assertTrue(self.cl.get('/api/signatures').get_json()['more'])
        finally:
            self.bff._LIST_EVENTS = was

    def test_3_esign_silent_is_not_an_empty_list(self):
        self.esign.down = True
        try:
            j = self.cl.get('/api/signatures').get_json()
        finally:
            self.esign.down = False
        self.assertFalse(j['ok'])
        self.assertRegex(j['message'], '[א-ת]')

    def test_4_a_file_goes_out_to_be_signed(self):
        n = len(self.esign.envs)
        r = self.cl.post('/api/signatures/file', data={'file': (io.BytesIO(b'%PDF-1.7 lease'), 'חוזה שכירות.pdf'),
                                                       'signer': 'משפחת לוי', 'days': '7', 'email': 'levi@example.com'},
                         content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200, r.data)
        j = r.get_json()
        self.assertTrue(j['link'].startswith('https://sign.test/s/'))
        env = self.esign.envs[j['envelope']['id']]
        self.assertEqual(len(self.esign.envs), n + 1)
        self.assertEqual((env['kind'], env['form']['signer'], env['form']['days'], env['form']['name']),
                         ('sign', 'משפחת לוי', '7', 'חוזה שכירות.pdf'))
        self.assertEqual(env['form']['sender'], 'בינה סולושנס')          # the business, never «הלשכה» when it has a name
        self.assertTrue(self.esign.files[env['id']].startswith(b'%PDF'))

    def test_5_refusals_are_hebrew_and_ask_esign_nothing(self):
        n = len(self.esign.stub.calls)
        cases = [({'file': (io.BytesIO(b'hello'), 'x.txt'), 'signer': 'דנה'}, 415),
                 ({'file': (io.BytesIO(b'%PDF-1.7'), 'a.pdf'), 'signer': ' '}, 400),
                 ({'file': (io.BytesIO(b'%PDF-1.7'), 'a.pdf'), 'signer': 'דנה', 'days': 'שבוע'}, 400),
                 ({'signer': 'דנה'}, 400)]
        for data, code in cases:
            r = self.cl.post('/api/signatures/file', data=data, content_type='multipart/form-data')
            self.assertEqual(r.status_code, code, (data.get('signer'), r.data))
            self.assertRegex(r.get_json()['message'], '[א-ת]')
        self.assertFalse([c for c in self.esign.stub.calls[n:] if c[0] == 'POST'])

    def test_5b_a_term_that_is_no_number_is_said_never_a_500(self):
        n, m = len(self.esign.stub.calls), len(self.ledger.stub.calls)
        # 1e400 is read as infinity, and int() of it raised OverflowError — a 500 (the second reader); and the term is
        # checked before the ledger is asked for anything (the document's PDF takes up to two minutes)
        for days in ('שבוע', 1e400, float('nan')):
            raw = json.dumps({'signer': 'דנה', 'days': days})                # 1e400 and NaN as JSON writes them
            r = self.cl.post('/api/sign/doc_s', data=raw, content_type='application/json')
            self.assertEqual(r.status_code, 400, (days, r.data))
            self.assertRegex(r.get_json()['message'], '[א-ת]')
            r = self.cl.post('/api/share/doc_s', data=raw.replace('signer', 'to'), content_type='application/json')
            self.assertEqual(r.status_code, 400, (days, r.data))
        self.assertFalse([c for c in self.esign.stub.calls[n:] if c[0] == 'POST'])
        self.assertFalse([c for c in self.ledger.stub.calls[m:] if 'download' in c[1]])

    def test_6_a_file_over_esigns_limit_is_said_before_it_is_sent(self):
        n = len(self.esign.stub.calls)
        was, self.bff._MAX_FILE = self.bff._MAX_FILE, 16
        try:
            r = self.cl.post('/api/signatures/file', data={'file': (io.BytesIO(b'%PDF-1.7 ' + b'x' * 64), 'big.pdf'),
                                                           'signer': 'דנה'}, content_type='multipart/form-data')
        finally:
            self.bff._MAX_FILE = was
        self.assertEqual(r.status_code, 413)
        self.assertIn('גדול מדי', r.get_json()['message'])
        self.assertFalse([c for c in self.esign.stub.calls[n:] if c[0] == 'POST'])


if __name__ == '__main__':
    unittest.main()
