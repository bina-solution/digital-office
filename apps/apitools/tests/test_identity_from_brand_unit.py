"""The ledger takes the business from «זהות», and keeps no definition of its own (DGO-2048).

On the ledger's own SQLite fallback, against a local «זהות» (`GET /api/brand` + `/files/<sha>.<ext>?px=512`):

  * every field «זהות» holds wins over the ledger's row — name, number, kind, address (street / city / zip),
    phone (an Israeli number in its local form), email, site, who signs, the logo (its 512-px rendition, fetched
    from where «זהות» answered) and the colour (house.family: the whole family, legible);
  * an עוסק פטור charges no VAT, whatever the row said, and a kind typed with a non-breaking space or without
    gershayim is still read; a kind the ledger has no type for (עמותה) keeps the ledger's and is named;
  * a field «זהות» held and no longer holds is cleared here too; one it never held keeps the row's value;
  * the mirror is written only right after a fresh answer and only to its own columns: the ledger's numbering,
    saved in between, stays;
  * a save that would change a field «זהות» holds is refused (IdentityHeld), with «זהות» answering or not;
    the same values sent back pass, and the ledger's own settings are saved;
  * with «זהות» out of reach the mirror draws the same issuer; without BRAND_URL the row alone is the issuer.

    python3 -m unittest tests.test_identity_from_brand_unit -v      # from apps/apitools, in its image
"""
import base64
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ['no_proxy'] = os.environ['NO_PROXY'] = '127.0.0.1,localhost'

from src.doc_data import db, entities  # noqa: E402

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
SHA = 'c' * 64
BRAND = {}
BASE = {'name': 'בינה סולושנס', 'name_en': 'Bina Solutions', 'legal_name': 'ישראל ישראלי',
        'entity_type': 'עוסק פטור', 'business_number': '300000015',
        'address': 'אסף שמחוני 19, פתח תקווה', 'phone': '+972 50-000-0001', 'email': 'person7-x@example.com',
        'website': 'https://bina-solutions.co.il/', 'signatory': 'ישראל ישראלי', 'signatory_title': 'בעלים',
        'color': '#002e5f', 'color_secondary': '#00bfff',
        # the address «זהות» names itself by — unreachable from here, as from another office
        'logo': {'url': f'http://digital-assets:8985/files/{SHA}.png',
                 'png': f'http://digital-assets:8985/files/{SHA}.png?px=512', 'mime': 'image/png'}}
OLD = dict(name='שם ישן', company_id='999', business_type='murshe', street='רחוב ישן 1', city='עיר', phone='03-0',
           email='old@example.com', bank_name='בנק ישן', bank_branch='1', bank_account='2', vat_pct=18)
SEEN = []


class Brand(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append(self.path)
        if self.path == '/api/brand':
            body, kind = json.dumps({'brand': BRAND, 'missing': []}).encode(), 'application/json'
        elif self.path == f'/files/{SHA}.png?px=512':
            body, kind = PNG, 'image/png'
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class TestIdentityFromBrand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp(prefix='ledger-identity-'))
        for k in [k for k in os.environ if k.startswith(('DOC_DB_', 'SUPABASE_DB_'))]:
            os.environ.pop(k)
        db._STATE.update(conn=None, pg=None, schema_done=False)
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), Brand)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.srv.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        os.chdir(cls._cwd)

    def _use(self, url, brand=None):
        if brand is not None:
            BRAND.clear()
            BRAND.update(brand)
        entities.BRAND_URL = url
        entities._BRAND.update(at=0.0, fields=None, color='', color2='', error='', unmapped=[])
        entities._LOGO.update(url='', b64='')

    def _fresh(self):
        entities._BRAND['at'] = 0.0               # the TTL is over: the next read asks «זהות» again

    def test_1_without_brand_url_the_row_is_the_issuer(self):
        self._use('', BASE)
        entities.save_business(OLD)
        b = entities.get_business()
        self.assertEqual(b['name'], 'שם ישן')
        self.assertEqual(b['identity']['source'], 'settings')

    def test_2_identity_comes_from_zehut(self):
        self._use(self.url, BASE)
        b = entities.get_business()
        self.assertEqual(b['identity']['source'], 'brand')
        self.assertEqual((b['name'], b['name_en'], b['company_id'], b['business_type']),
                         ('בינה סולושנס', 'Bina Solutions', '300000015', 'patur'))
        self.assertEqual((b['street'], b['city'], b['zip']), ('אסף שמחוני 19', 'פתח תקווה', ''))
        self.assertEqual((b['phone'], b['email'], b['website']),
                         ('050-000-0001', 'person7-x@example.com', 'bina-solutions.co.il'))
        self.assertEqual((b['signatory'], b['signatory_title']), ('ישראל ישראלי', 'בעלים'))
        self.assertEqual(float(b['vat_pct']), 0.0)                      # an עוסק פטור charges no VAT
        self.assertTrue(b['onboarded'])
        p = entities.issuer_party()
        self.assertTrue(p['logo'].startswith('data:image/png;base64,'), p['logo'][:40])
        self.assertIn(f'/files/{SHA}.png?px=512', SEEN)                 # the rendition, never the master
        self.assertEqual(p['tax_status'], 'patur')
        colour = entities.brand().get('colour', {})                     # the whole family, never `brand` alone
        self.assertEqual(colour.get('brand'), '#002E5F')
        self.assertEqual(set(colour), set(entities.COLOUR_KEYS))
        self.assertEqual(colour['accent_soft'], '#00BFFF')               # the second colour reads on the cover
        self.assertEqual(b['bank_name'], 'בנק ישן')                      # never held by «זהות»: the row's own
        self.assertIn('bank_name', b['identity']['missing'])
        self.assertNotIn('name', b['identity']['missing'])

    def test_3_a_save_refuses_what_zehut_holds_and_keeps_the_ledgers_own(self):
        self._use(self.url, BASE)
        b = entities.get_business()
        with self.assertRaises(entities.IdentityHeld) as e:
            entities.save_business({'name': 'שם אחר', 'doc_start': '7'})
        self.assertEqual(e.exception.fields, ['name'])
        self.assertEqual(int(entities.get_business()['doc_start'] or 0), 0)   # refused whole: nothing half-saved
        same = {k: b[k] for k in ('name', 'company_id', 'business_type', 'street', 'city', 'zip', 'email', 'phone')}
        b = entities.save_business({**same, 'doc_start': '7', 'bank_account': '55'})     # the form sends them back
        self.assertEqual(b['name'], 'בינה סולושנס')
        self.assertEqual(int(b['doc_start']), 7)                        # the ledger's own setting is saved
        self.assertEqual(b['bank_account'], '55')                       # «זהות» holds no bank: still the row's

    def test_4_the_mirror_never_writes_over_the_ledgers_numbering(self):
        self._use(self.url, BASE)
        entities.get_business()
        entities.save_business({'doc_start': '500', 'series_start': '{"RECEIPT": 1017}'})
        writes = []
        real = entities._write_cols
        entities._write_cols = lambda vals: (writes.append(sorted(vals)), real(vals))
        try:
            BRAND['email'] = 'new@bina.example'                         # «זהות» changed: the mirror writes once
            self._fresh()
            for _ in range(4):                                          # …and reads inside the TTL write nothing
                b = entities.get_business()
        finally:
            entities._write_cols = real
        self.assertEqual(len(writes), 1, writes)
        self.assertNotIn('doc_start', writes[0])
        self.assertNotIn('series_start', writes[0])
        self.assertEqual(b['email'], 'new@bina.example')
        row = entities._row()
        self.assertEqual((int(row['doc_start']), row['series_start']), (500, '{"RECEIPT": 1017}'))

    def test_5_what_zehut_stops_holding_is_cleared_here_too(self):
        self._use(self.url, BASE)
        entities.get_business()
        gone = {k: v for k, v in BASE.items() if k not in ('email', 'logo', 'color', 'color_secondary')}
        self._use(self.url, gone)
        b = entities.get_business()
        self.assertEqual(b['email'], '')                                # held before, not now: cleared
        self.assertEqual(b['logo_b64'], '')
        self.assertEqual(entities.brand().get('colour', {}), {})        # the tones go with the colour
        self.assertEqual(b['bank_name'], 'בנק ישן')                      # never held: untouched
        self._use(self.url, BASE)
        self.assertEqual(entities.get_business()['email'], 'person7-x@example.com')

    def test_6_the_kind_of_business_is_read_as_a_person_types_it(self):
        for typed, kind in (('עוסק פטור', 'patur'), ('פטור', 'patur'), ('עוסק מורשה', 'murshe'),
                            ('חברה בעמ', 'company'), ('חברה בע״מ', 'company'), ('שותפות', 'murshe'),
                            ('עמותה', None), ('', None)):
            self.assertEqual(entities._entity_type(typed), kind, typed)
        self._use(self.url, {**BASE, 'entity_type': 'עמותה'})
        b = entities.get_business()
        self.assertEqual(b['business_type'], 'patur')                   # not mapped: the ledger's own stays
        self.assertEqual(b['identity']['unmapped'], ['business_type'])  # …and it says so

    def test_7_out_of_reach_the_mirror_draws_the_same_issuer_and_still_protects_it(self):
        self._use(self.url, BASE)
        entities.get_business()
        self._use('http://127.0.0.1:9')                                 # nothing listens there
        b = entities.get_business()
        self.assertEqual(b['identity']['source'], 'mirror')
        self.assertEqual((b['name'], b['company_id'], b['email']),
                         ('בינה סולושנס', '300000015', 'person7-x@example.com'))
        self.assertTrue(entities.issuer_party()['logo'].startswith('data:image/png;base64,'))
        with self.assertRaises(entities.IdentityHeld):
            entities.save_business({'company_id': '111'})

    def test_8_an_israeli_number_prints_in_its_local_form(self):
        for given, printed in (('+972 50-000-0001', '050-000-0001'), ('+972-3-000-0002', '03-000-0002'),
                               ('00972500000001', '050-000-0001'), ('050-000-0001', '050-000-0001'),
                               ('+1 415 555 0100', '+1 415 555 0100'), ('', '')):
            self.assertEqual(entities._il_phone(given), printed, given)

    def test_9_an_address_is_street_city_and_zip(self):
        for text, parts in (('אסף שמחוני 19, פתח תקווה', ('אסף שמחוני 19', 'פתח תקווה', '')),
                            ('Assaf Simhoni 19, Petah Tikva, Israel', ('Assaf Simhoni 19', 'Petah Tikva', '')),
                            ('הרצל 1, חיפה, 3100000', ('הרצל 1', 'חיפה', '3100000')),
                            ('הרצל 1', ('הרצל 1', '', ''))):
            self.assertEqual(entities._address(text), parts, text)

    def test_a_a_colour_gives_a_legible_family_in_its_own_hue(self):
        from src.doc_gen import house
        self.assertEqual(house.family('#0E5A48')['brand_night'], '#072B23')     # the house's own proportions
        for primary in ('#002e5f', '#0E5A48', '#ffcc00', '#87CEEB', '#FFFFFF', '#777', '#ff0000', '#AABBCC80'):
            for second in ('', '#ffff00', '#0b1a2a'):
                f = house.family(primary, second)
                self.assertGreaterEqual(house._contrast(f['brand'], '#FFFFFF'), 4.5, primary)
                self.assertGreaterEqual(house._contrast(f['accent'], '#FFFFFF'), 4.5, primary)
                self.assertGreaterEqual(house._contrast(f['accent_soft'], f['brand_night']), 4.5, primary)
                self.assertGreaterEqual(house._contrast(f['accent_soft'], f['brand']), 3.0, primary)
                self.assertEqual(house.tokens({'colour': f})['colour']['brand'], f['brand'])
        self.assertEqual(house.family('#002e5f')['brand'], '#002E5F')    # a dark colour stays itself
        self.assertEqual(house.family('not a colour'), {})


if __name__ == '__main__':
    unittest.main()
