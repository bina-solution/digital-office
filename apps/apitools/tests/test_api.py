import requests
import unittest
import os

from src.utils.storage import ocr_drawings_path, ocr_test_files_path, pdf_test_files_path

TEXT_FILE = ocr_test_files_path() + "/file1.jpg"
JPEG_FILE = ocr_test_files_path() + "/file1.jpg"
PDF_FILE = pdf_test_files_path() + "/test.pdf"

OUTPUT_FILE = ocr_drawings_path() +"/rotate_test.jpg"

DEPLOYED_BASE = 'https://apitools-bupdvuqama-uc.a.run.app/'
LOCAL_BASE = 'http://127.0.0.1:8080/'

BASE = LOCAL_BASE  # Change to DEPLOYED_BASE to test deployed API


class TestAPI(unittest.TestCase):
    file_hash = None

    def setUp(self):  # Use setUp for consistent test prep
        print("Setting up")

    def test_0_base_route(self):
        response = requests.get(BASE)
        self.assertEqual(response.status_code, 200, "Base route failed")
        self.assertEqual(response.text, "Hello API!", "Unexpected base route response")

    def test_1_pdf_to_jpeg_conversion(self):
        url = BASE + 'pdfToJpeg'  # Corrected URL
        print(f"Testing PDF to JPEG conversion at {url}")
        print(f"Using PDF file: {PDF_FILE}")
        with open(PDF_FILE, 'rb') as f:
            files = {'file': ('test.pdf', f)}  # Correct file parameter
            response = requests.post(url, files=files)  # Use correct URL

        self.assertEqual(response.status_code, 200, "Failed to convert PDF")
        self.assertEqual(response.headers.get('Content-Type'), 'image/jpeg', "Invalid content type")

        with open(OUTPUT_FILE, 'wb') as f:
            f.write(response.content)
        self.assertTrue(os.path.isfile(OUTPUT_FILE), "Output file not created")
        print(f"Output file created: {OUTPUT_FILE}")

    def test_2_document_ocr(self):
        url = BASE + 'documentOcr'
        print(f"Testing document OCR at {url}")
        print(f"Using JPEG file: {JPEG_FILE}")
        with open(JPEG_FILE, 'rb') as f:
            files = {'file': ('file1.jpg', f, 'image/jpeg')}
            response = requests.post(url, files=files)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        TestAPI.file_hash = data['file_hash']
        print(f"File hash: {TestAPI.file_hash}")

    def test_3_document_json_query(self):
        if not TestAPI.file_hash:
            print("File hash not set, skipping test_document_json_query")
            self.skipTest("No file_hash from previous test.")
        url = BASE + 'documentJsonQuery'
        payload = {
            "file_id": TestAPI.file_hash,
            "ocr_json_query": {
                "action": "find after",
                "action_value": "חשבונית מס מס",
                "value_validations": [
                    {"validation_type": "length_greater_than", "validation_value": 2}
                ],
                "is_rtl": True
            }
        }
        response = requests.post(url, json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('result', data)
        print(f"Query result: {data['result']}")


if __name__ == '__main__':
    unittest.main()
