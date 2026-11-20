"""The house style draws every business document right — its numbers, its Hebrew, its law (DGO-2029).

Every type in the catalogue renders from its sample: the arithmetic a reader checks with a pencil
(subtotal, discount, VAT, total), the true minus of a credit, the Tax Authority's allocation number,
an עוסק פטור that charges no VAT and issues no tax invoice, text escaped, the payment facts kept in their
order in a right-to-left line. And in the app's image (WeasyPrint and PyMuPDF present): every type is
a PDF/A-3 with its own data inside, its Hebrew reads as written, and every page says which of how many.

    python3 -m unittest tests.test_house_documents_unit -v      # from apps/apitools, in its image
"""
import copy
import json
import re
import unittest

from src.doc_gen import house
from src.doc_gen.house import catalogue, samples, view

_HEB_WORD = re.compile("[א-ת]{3,}")


def _html(doc, **kw):
    return house.render_html(doc, **kw)


def _words(obj):
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, (list, tuple)):
        return {w for v in obj for w in _words(v)}
    return set(_HEB_WORD.findall(re.sub(r"\*\*", "", obj))) if isinstance(obj, str) else set()


class TestCatalogue(unittest.TestCase):
    def test_every_type_has_a_sample_and_renders(self):
        self.assertEqual(set(samples.ALL), set(catalogue.TYPES))
        for code in catalogue.TYPES:
            with self.subTest(code=code):
                html = _html(samples.sample(code))
                self.assertIn(catalogue.kind(code)['he'], html)
                self.assertIn('dir="rtl"', html)

    def test_an_exempt_dealer_issues_no_vat_document(self):
        self.assertFalse(catalogue.may_issue('INVOICE', 'patur'))
        self.assertFalse(catalogue.may_issue('CREDIT_NOTE', 'patur'))
        self.assertTrue(catalogue.may_issue('RECEIPT', 'patur'))
        self.assertTrue(catalogue.may_issue('PAYMENT_REQUEST', 'patur'))
        self.assertIn('INVOICE', catalogue.offered('company'))
        self.assertNotIn('INVOICE_RECEIPT', catalogue.offered('patur'))

    def test_the_ledgers_old_names_still_resolve(self):
        self.assertEqual(catalogue.kind('BALANCE_SHEET')['code'], 'STATEMENT')
        self.assertEqual(catalogue.kind('credit_invoice')['code'], 'CREDIT_NOTE')
        with self.assertRaises(KeyError):
            catalogue.kind('NO_SUCH_TYPE')


class TestNumbers(unittest.TestCase):
    def test_the_invoice_adds_up(self):
        ctx = house.context(samples.sample('INVOICE'))
        t = ctx['groups'][0]['totals']
        self.assertEqual(t['ladder'], [('סכום ביניים', '16,500.00'), ('הנחה 5%', '−825.00'),
                                       ('אחרי הנחה', '15,675.00'), ('מע״מ 18%', '2,821.50')])
        self.assertEqual(t['total'], '18,496.50')

    def test_vat_rounds_half_up_to_agorot(self):
        doc = samples.sample('INVOICE')
        doc['discount_pct'] = 0
        doc['lines'] = [{'description': 'שעה', 'qty': 1, 'unit_price': 0.25}]   # VAT 0.045 → 0.05
        t = house.context(doc)['groups'][0]['totals']
        self.assertEqual(t['ladder'][-1], ('מע״מ 18%', '0.05'))
        self.assertEqual(t['total'], '0.30')

    def test_a_credit_note_is_negative_and_names_the_invoice_it_credits(self):
        html = _html(samples.sample('CREDIT_NOTE'))
        self.assertIn('−2,578.30', html)                 # a true minus, never a hyphen
        self.assertIn('INV-2026-00031', html)
        self.assertIn('החזרת שני רישיונות', html)              # §9(ה): the reason
        self.assertNotIn('מספר הקצאה', html)                   # a credit note asks for none

    def test_an_exempt_dealer_charges_no_vat(self):
        html = _html(samples.sample('PAYMENT_REQUEST'))
        self.assertNotIn('מע״מ 18%', html)
        self.assertIn('עוסק פטור — לא נגבה מע״מ', html)
        self.assertIn('8,000.00', html)

    def test_a_setup_fee_and_a_monthly_retainer_are_two_totals(self):
        groups = house.context(samples.sample('PROPOSAL'))['groups']
        self.assertEqual([(g['title'], g['totals']['total']) for g in groups],
                         [('תשלום חד־פעמי', '16,000.00'), ('תשלום חודשי', '7,500.00')])

    def test_the_allocation_number_prints_its_nine_rightmost_digits_apart(self):
        a = view.allocation('202611191245678931')
        self.assertEqual((a['head'], a['tail']), ('202611191', '245678931'))
        self.assertIn('<b>245678931</b>', _html(samples.sample('INVOICE')))
        self.assertIsNone(view.allocation(''))

    def test_a_statement_carries_its_running_balance(self):
        st = house.context(samples.sample('STATEMENT'))['st']
        self.assertEqual([r['balance'] for r in st['rows']][-1], st['closing'])
        self.assertEqual(st['closing'], '3,360.00')

    def test_the_books_and_the_page_do_one_arithmetic(self):
        """1,234.75 × 18% = 222.255: float round() kept 222.25 in the books while the page printed 222.26
        (DGO-2029, the second reader). One arithmetic now — decimal, half up to the agora — in both."""
        from src.doc_models.models import InvoiceReceipt, LineItem, Party
        m = InvoiceReceipt(supplier=Party(name='מעבדת שקד בע״מ', company_id='515550001', tax_status='company'),
                           customer=Party(name='קבוצת אורן בע״מ'), doc_id='IR-2026-00001', doc_date='19/11/2026',
                           lines=[LineItem(description='רישיון', qty=1, unit_price=1234.75)])
        self.assertEqual((m.vat, m.total_due, m.amount_paid), (222.26, 1457.01, 1457.01))
        doc = house.from_model(m)
        t = house.context(doc)['groups'][0]['totals']
        self.assertEqual((t['raw_vat'], t['raw_total']), (view.r2('222.26'), view.r2('1457.01')))
        self.assertEqual([p['amount'] for p in doc['payments']], [1457.01])   # the payment under its total


class TestText(unittest.TestCase):
    def test_text_is_escaped(self):
        doc = samples.sample('QUOTE')
        doc['customer']['name'] = '<script>alert(1)</script>'
        doc['lines'][0]['description'] = 'a & b <i>'
        html = _html(doc)
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('a &amp; b &lt;i&gt;', html)

    def test_payment_facts_keep_their_order_in_a_right_to_left_line(self):
        html = _html(samples.sample('INVOICE_RECEIPT'))
        self.assertIn('<span class="iso">כרטיס המסתיים ב־4417</span>', html)
        self.assertIn('<span class="iso">3 תשלומים</span>', html)

    def test_a_brand_repaints_and_an_unknown_key_is_ignored(self):
        t = house.tokens({'colour': {'brand': '#123456', 'no_such_role': '#000000'}})
        self.assertEqual(t['colour']['brand'], '#123456')
        self.assertNotIn('no_such_role', t['colour'])
        doc = samples.sample('QUOTE')
        doc['brand'] = {'colour': {'brand': '#123456'}}
        self.assertIn('--brand: #123456;', _html(doc))

    def test_a_draft_says_so(self):
        html = _html(samples.sample('INVOICE'), label='טיוטה')
        self.assertIn('class="wm"', html)
        self.assertIn('טיוטה', html)
        self.assertNotIn('נחתם דיגיטלית', html)

    def test_a_brand_value_is_held_to_its_shape(self):
        """A brand value is written into the page's style: one that is not a colour, a face the document embeds
        or a size is not taken (it could close the style block — DGO-2029, the second reader)."""
        bad = 'x}</style><a rel="attachment" href="file:///proc/self/environ">.</a><style>'
        t = house.tokens({'colour': {'brand': bad, 'accent': 'red'}, 'face': {'text': 'Comic Sans'},
                          'size': {'base': '9pt; color: red'}})
        default = house.tokens()
        self.assertEqual((t['colour']['brand'], t['colour']['accent'], t['face']['text'], t['size']['base']),
                         (default['colour']['brand'], default['colour']['accent'], default['face']['text'],
                          default['size']['base']))
        self.assertEqual(house.tokens({'face': {'text': 'Rubik'}, 'size': {'base': '10pt'}})['face']['text'], 'Rubik')
        doc = samples.sample('QUOTE')
        doc['brand'] = {'colour': {'brand': bad}}
        self.assertNotIn('proc/self/environ', _html(doc))

    def test_a_logo_is_drawn_as_an_image_never_written_into_the_page(self):
        doc = samples.sample('QUOTE')
        doc['supplier']['logo'] = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        html = _html(doc)
        self.assertIn('<img src="data:image/svg+xml;base64,', html)
        self.assertNotIn('<script>alert', html)
        doc['supplier']['logo'] = 'data:image/png;base64,iVBOR" onerror="alert(1)'
        self.assertNotIn('onerror', _html(doc))                 # not a data URI of an image: not drawn at all

    def test_a_posted_document_of_the_books_is_drawn_as_a_draft_and_never_as_signed(self):
        from src.api.house_api import drawn_label
        for code in catalogue.TYPES:
            with self.subTest(code=code):
                k = catalogue.kind(code)
                got = drawn_label(k, 'מקור')
                self.assertEqual(got, 'טיוטה' if k['family'] in ('tax', 'book') else 'מקור')
        doc = samples.sample('INVOICE')                          # a type whose page ends in the sign-off
        self.assertIn('מסמך ממוחשב', _html(doc))                 # an issued ledger document
        doc['digital'] = False                                   # what /docGen/house sets on what it draws
        self.assertNotIn('מסמך ממוחשב', _html(doc))
        # no page claims a signature its file does not carry (the ledger's is kept beside the file)
        for code in catalogue.TYPES:
            if code != 'SIGN_CERTIFICATE':                       # esign's certificate: that file IS PAdES-signed
                self.assertNotIn('נחתם דיגיטלית', _html(samples.sample(code)), code)

    def test_an_agreement_without_its_sides_gets_them_from_its_parties(self):
        """An agreement converted from a proposal carries no «בין/לבין» or signature places of its own."""
        doc = samples.sample('SERVICE_AGREEMENT')
        for key in ('parties', 'signatures'):
            doc.pop(key, None)
        ctx = house.context(doc)
        self.assertEqual([p['label'] for p in ctx['parties']], ['בין:', 'לבין:'])
        self.assertIn(doc['supplier']['name'], ctx['parties'][0]['text'])
        self.assertIn(doc['customer']['name'], ctx['parties'][1]['text'])
        self.assertEqual([s['party'] for s in ctx['signatures']], ['הספק', 'הלקוח'])
        self.assertEqual(house.context(samples.sample('QUOTE'))['parties'], [])   # nothing for a non-agreement

    def test_the_signing_certificate_names_the_key_that_signs_not_the_business(self):
        """esign signs with its own key: the certificate names that key's subject, as esign passes it, and never
        claims the business signed (the third reader: on a client's office that named the wrong signer)."""
        doc = samples.sample('SIGN_CERTIFICATE')
        doc['certificate'].pop('fine', None)
        html = _html(doc)
        self.assertNotIn('(PAdES) של', html)
        doc['certificate']['key_subject'] = 'משרד בדיקה — office signing (self-signed)'
        self.assertIn('במפתח «משרד בדיקה', _html(doc))


try:
    import weasyprint  # noqa: F401
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    _PDF = True
except Exception:  # not the app's image: the PDF half is run there
    _PDF = False


@unittest.skipUnless(_PDF, 'WeasyPrint and PyMuPDF are the app image\'s; run there')
class TestPdf(unittest.TestCase):
    def test_every_type_is_an_archival_pdf_that_reads_right_to_left(self):
        for code in catalogue.TYPES:
            doc = samples.sample(code)
            with self.subTest(code=code):
                pdf = house.render_pdf(doc, label='מקור')
                d = fitz.open(stream=pdf, filetype='pdf')
                text = ''.join(p.get_text() for p in d)
                flat = re.sub(r'\s+', '', text)
                self.assertIn('WeasyPrint', d.metadata.get('producer') or '')
                self.assertIn(doc['doc_id'], flat)
                words = _words(doc)
                backwards = {w for w in words if w not in flat and w[::-1] in flat}
                self.assertEqual(backwards, set(), 'Hebrew reads backwards')
                self.assertGreaterEqual(len({w for w in words if w in flat}), 8, 'the words are not on the page')
                # every page says which of how many (Instruction 36: a page serial on every output)
                pages = len(d) - (1 if catalogue.kind(code)['template'] == 'proposal' or doc.get('cover') else 0)
                self.assertGreaterEqual(text.count('מתוך'), pages)
                # PDF/A-3 with the document's own data inside
                self.assertIn('dgo-document.json', d.embfile_names())
                self.assertEqual(json.loads(d.embfile_get('dgo-document.json'))['doc_id'], doc['doc_id'])
                self.assertIn('pdfaid', d.get_xml_metadata())
                d.close()


if __name__ == '__main__':
    unittest.main()
