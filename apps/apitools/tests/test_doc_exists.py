import unittest
import hashlib
import requests
from src.utils.storage import pdf_test_files_path

LOCAL_BASE = 'http://127.0.0.1:8080/'
BASE = LOCAL_BASE

class TestDocExists(unittest.TestCase):
    test_file_hash = None

    def test_0_doc_not_exists(self):
        # Use deterministic hash that likely not present
        fake_hash = '0'*32
        resp = requests.get(BASE + 'docExists', json={'file_id': fake_hash})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get('exists'))

    def test_1_upload_and_check(self):
        # Upload a pdf to create entry
        pdf_file = pdf_test_files_path() + '/a-kalkal.pdf'
        with open(pdf_file, 'rb') as f:
            content = f.read()
            file_hash = hashlib.md5(content).hexdigest()
            TestDocExists.test_file_hash = file_hash
            f.seek(0)
            resp = requests.post(BASE + 'documentOcr', files={'file': ('a-kalkal.pdf', f, 'application/pdf')})
        self.assertEqual(resp.status_code, 200)
        # Now check existence
        resp2 = requests.post(BASE + 'docExists', json={'file_id': TestDocExists.test_file_hash})
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2.get('exists'))
        self.assertIn('file_path', data2)

if __name__ == '__main__':
    unittest.main()
