"""Google Vision is never sent a page without a key (DGO-1792).

    python3 -m pytest apps/apitools/tests/test_vision_needs_key_unit.py      (or run it as a script)

With OCR_ENGINE=google named and GOOGLE_VISION_API_KEY empty, `_ocr_request_vision_api` posted the client's page to
Google anyway (Google refused it). Now it raises before any request is made; with a key it still sends.
"""
import unittest
from unittest import mock

from src.ocr_core import ocr_processor
from src.ocr_core.ocr_processor import OcrProcessor


class VisionNeedsKey(unittest.TestCase):
    def test_no_key_sends_nothing(self):
        for key in ("", "   ", None):
            proc = OcrProcessor(api_key=key, ocr_engine="google")
            with mock.patch.object(ocr_processor.requests, "post") as post:
                with self.assertRaises(Exception) as caught:
                    proc._ocr_request_vision_api("aGVsbG8=")
                post.assert_not_called()
            self.assertIn("GOOGLE_VISION_API_KEY is empty", str(caught.exception))

    def test_with_a_key_the_request_still_goes(self):
        proc = OcrProcessor(api_key="k-test", ocr_engine="google")
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"responses": [{}]}
        with mock.patch.object(ocr_processor.requests, "post", return_value=fake) as post:
            proc._ocr_request_vision_api("aGVsbG8=")
            post.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
