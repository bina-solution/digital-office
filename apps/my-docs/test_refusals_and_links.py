"""The BFF after the second reader of DGO-2047 and the code audit of DGO-2169 — run against the REAL app.py, with
the ledger and esign as the stand-ins of test_living_links (they record what they were asked):

- a cancelled document closes its VIEW links too, not only its signature links;
- an issued document of the books is read once per open link, so one link holds its «מקור» and the rest «העתק»;
- a view link is not made — and the document not read — while esign does not answer;
- «esign did not answer» is a 502, never «the link is closed» (409);
- the ledger's refusals reach the screen in Hebrew, its own words kept as `detail`, and a refusal that is not JSON
  becomes one; a refused «הפק» keeps the draft it left in its body.

    python3 -m unittest -v test_refusals_and_links          (stdlib + flask + requests: the my-docs image's own)
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_living_links import Esign, Ledger  # noqa: E402


class BooksLedger(Ledger):
    """The ledger, with a document of the books whose download is «מקור» once and «העתק» after (Instruction 36), and
    refusals in the ledger's own English."""

    def __init__(self):
        super().__init__()
        self.served = {}
        self.docs['doc_inv'] = {'id': 'doc_inv', 'doc_type': 'INVOICE', 'status': 'draft', 'doc_number': None,
                                'customer_name': 'סטודיו גפן'}
        self.docs['doc_c'] = {'id': 'doc_c', 'doc_type': 'QUOTE', 'status': 'issued', 'doc_number': 'QT-7',
                              'customer_name': 'קבוצת אורן'}

    def get(self, h, q, b):
        d, act = self._doc(h.path.split('?')[0])
        if d is not None and act == 'download' and d['status'] != 'draft':
            n = self.served[d['id']] = self.served.get(d['id'], 0) + 1
            return 200, b'%PDF-1.7 ' + (b'ORIGINAL' if n == 1 else b'COPY'), {'Content-Type': 'application/pdf'}
        return super().get(h, q, b)

    def post(self, h, q, b):
        path = h.path.split('?')[0]
        d, act = self._doc(path)
        if path == '/documents' and q.get('issue') == ['1']:
            return 422, {'error': 'not_compliant', 'document': {'id': 'doc_left', 'status': 'draft'},
                         'message': 'not_compliant: customer address missing (§9(a)(4)); '
                                    'line 0: unit of measure missing (§9(a)(6))'}, {}
        if d is not None and act == 'cancel':
            d['status'] = 'cancelled'
            return 200, d, {}
        if d is not None and act == 'pay':
            return 409, {'error': 'PermissionError', 'message': 'cannot pay a cancelled document'}, {}
        if d is not None and act == 'send':
            return 502, b'<html><body>Bad Gateway</body></html>', {'Content-Type': 'text/html'}
        return super().post(h, q, b)

    def patch(self, h, q, b):
        d, _ = self._doc(h.path.split('?')[0])
        if d is not None and d['status'] != 'draft':
            return 409, {'error': 'PermissionError',
                         'message': 'document %s is issued and immutable — issue a credit document to correct' % d['id']}, {}
        return super().patch(h, q, b)


class Refusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.esign = BooksLedger(), Esign()
        os.environ['APITOOLS_URL'] = cls.ledger.stub.url
        os.environ['ESIGN_URL'] = cls.esign.stub.url
        os.environ['DOCUMENTS_URL'] = 'http://127.0.0.1:9'
        import app as bff
        cls.bff, cls.cl = bff, bff.app.test_client()

    def share(self, doc, **body):
        return self.cl.post('/api/share/' + doc, json=body)

    def test_1_a_cancelled_document_closes_its_view_links(self):
        vid = self.share('doc_c').get_json()['envelope']['id']
        r = self.cl.post('/api/documents/doc_c/cancel', json={'reason': 'טעות'})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.esign.envs[vid]['status'], 'cancelled')

    def test_2_an_issued_book_document_gives_one_link_its_original_and_the_rest_a_copy(self):
        older = self.share('doc_inv').get_json()['envelope']['id']
        newer = self.share('doc_inv').get_json()['envelope']['id']
        r = self.cl.post('/api/documents/doc_inv/issue')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.headers['X-Views-Followed'], '2/2')
        self.assertTrue(self.esign.files[older].endswith(b'ORIGINAL'))
        self.assertTrue(self.esign.files[newer].endswith(b'COPY'))

    def test_3_no_link_and_no_read_while_esign_does_not_answer(self):
        self.ledger.docs['doc_b'] = {'id': 'doc_b', 'doc_type': 'RECEIPT', 'status': 'issued', 'doc_number': '9',
                                     'customer_name': 'סטודיו גפן'}
        was, self.bff.ESIGN = self.bff.ESIGN, 'http://127.0.0.1:9'
        try:
            r = self.share('doc_b')
        finally:
            self.bff.ESIGN = was
        self.assertEqual(r.status_code, 502)
        self.assertNotIn('doc_b', self.ledger.served)              # its «מקור» was not spent on nobody
        self.assertRegex(r.get_json()['message'], '[א-ת]')

    def test_4_esign_down_is_502_not_a_closed_link(self):
        vid = self.share('doc_q').get_json()['envelope']['id']
        was, self.bff.ESIGN = self.bff.ESIGN, 'http://127.0.0.1:9'
        try:
            again = self.cl.post('/api/links/%s/again' % vid)
            revoke = self.cl.post('/api/links/%s/revoke' % vid)
        finally:
            self.bff.ESIGN = was
        self.assertEqual((again.status_code, revoke.status_code), (502, 502))

    def test_5_a_refused_issue_says_what_is_missing_in_hebrew_and_keeps_its_draft(self):
        r = self.cl.post('/api/documents?issue=1', json={'doc_type': 'INVOICE'}, headers={'Idempotency-Key': 'k-5'})
        self.assertEqual(r.status_code, 422)
        j = r.get_json()
        self.assertEqual(j['message'], 'המסמך לא הופק — חסר בו: כתובת הלקוח (רחוב או עיר) (§9(a)(4)); יחידת מידה בשורה 1 (§9(a)(6))')
        self.assertTrue(j['said'].startswith('not_compliant: customer address missing'))
        self.assertEqual(j['document']['id'], 'doc_left')          # the screen goes on writing THIS draft

    def test_6_every_refusal_of_the_ledger_is_hebrew(self):
        self.ledger.docs['doc_i2'] = {'id': 'doc_i2', 'doc_type': 'QUOTE', 'status': 'issued', 'doc_number': 'QT-2'}
        saved = self.cl.patch('/api/documents/doc_i2', json={'subject': 'x'})
        self.assertEqual(saved.status_code, 409)
        self.assertEqual(saved.get_json()['message'], 'המסמך כבר הופק ואינו נערך עוד — מתקנים אותו במסמך זיכוי או במסמך חדש')
        paid = self.cl.post('/api/documents/doc_i2/pay', json={})
        self.assertEqual(paid.get_json()['message'], 'אי אפשר לסמן כשולם מסמך שבוטל')
        gone = self.cl.get('/api/documents/doc_nope')
        self.assertEqual((gone.status_code, gone.get_json()['message']), (404, 'המסמך לא נמצא'))
        nobody = self.cl.get('/api/customers/c_nope')
        self.assertEqual(nobody.get_json()['message'], 'הלקוח לא נמצא')       # a 404 names what it did not find

    def test_6b_a_word_the_tables_do_not_know_never_lands_in_a_hebrew_sentence(self):
        import errors_he
        self.assertEqual(errors_he.he('document d1 already being processed', 409), errors_he._GENERAL[409])
        self.assertEqual(errors_he.he('cannot pay a draft document', 409), 'אי אפשר לסמן כשולם מסמך שעדיין טיוטה')
        self.assertEqual(errors_he.he('cannot frobnicate a draft document', 409), errors_he._GENERAL[409])
        kept = errors_he.body({'error': 'x', 'message': 'cannot pay a paid document', 'detail': 'its own'}, 409)
        self.assertEqual((kept['detail'], kept['said']), ('its own', 'cannot pay a paid document'))   # nothing overwritten
        for odd in (None, '', 'not_compliant:', 'not_compliant: (((', {'a': 1}, ['x']):
            self.assertIsInstance(errors_he.he(odd, 422), str)

    def test_7_a_refusal_that_is_not_json_becomes_one(self):
        r = self.cl.post('/api/documents/doc_q/send', json={'to': 'דנה'})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.headers['Content-Type'], 'application/json')
        self.assertEqual(r.get_json()['message'], 'מאגר המסמכים לא השלים את הפעולה')

    def test_7b_the_proxy_carries_the_screens_own_paths_only(self):
        """apitools has more than this screen's ledger (its OCR, its image tools): the BFF passes only the paths and
        methods the screen uses, and never asks the ledger for another (the code audit of DGO-2169, part B)."""
        n = len(self.ledger.stub.calls)
        # …and each path whole: requests collapses a dot segment before it sends (`documents/../documentOcr` went out
        # as apitools' OCR), and the ledger's allocation number and consent are not the screen's (the second reader)
        for method, path in (('POST', '/api/ocr/scan'), ('GET', '/api/images/resize'), ('DELETE', '/api/documents/doc_q'),
                             ('POST', '/api/business'), ('GET', '/api/documentsX'),
                             ('GET', '/api/documents/../documentOcr'), ('GET', '/api/documents/%2e%2e/documentOcr'),
                             ('POST', '/api/documents/./doc_q/../../documentOcr'),
                             ('POST', '/api/documents/doc_q/allocation'), ('POST', '/api/documents/consent')):
            r = self.cl.open(path, method=method)
            self.assertEqual(r.status_code, 404, (method, path))
            self.assertRegex(r.get_json()['message'], '[א-ת]')
        self.assertEqual(len(self.ledger.stub.calls), n)                     # the ledger was asked nothing
        self.assertEqual(self.cl.get('/api/documents/doc_q').status_code, 200)   # the screen's own still pass

    def test_8_a_ledger_that_does_not_answer_is_one_hebrew_sentence(self):
        was, self.bff.APITOOLS = self.bff.APITOOLS, 'http://127.0.0.1:9'
        try:
            r = self.cl.get('/api/documents/doc_q')
        finally:
            self.bff.APITOOLS = was
        self.assertEqual(r.status_code, 502)
        self.assertNotIn('Connection', r.get_json()['message'])   # never requests' English
        self.assertRegex(r.get_json()['message'], '^מאגר המסמכים לא ענה')


if __name__ == '__main__':
    unittest.main()
