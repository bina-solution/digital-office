import unittest
from unittest.mock import patch

from src.api import create_app


class FakeOcrData:
    original_filepath = ".storage/files/example.pdf"


class FakeOcrObject:
    ocr_data = FakeOcrData()


class TestDocExistsUnit(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_doc_exists_accepts_query_param(self):
        with patch("src.api.ocr_api.OcrObject.from_file_id", return_value=FakeOcrObject()):
            response = self.client.get("/docExists?file_id=abc123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["file_id"], "abc123")
        self.assertTrue(response.json["exists"])

    def test_doc_exists_accepts_post_json(self):
        with patch("src.api.ocr_api.OcrObject.from_file_id", return_value=FakeOcrObject()):
            response = self.client.post("/docExists", json={"file_id": "abc123"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["exists"])

    def test_doc_exists_missing_file_id_returns_400(self):
        response = self.client.get("/docExists")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "file_id is required")


if __name__ == "__main__":
    unittest.main()