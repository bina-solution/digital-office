"""A cached document must never be refused by OCR admission control.

Admission control rations OCR *computation*. ~71 % of live /documentOcr traffic (1 164 of
1 633 successful responses in a measured 4.75 h window) returned in under 1 s because the OCR
was already cached — no computation at all. Once admission began shedding instead of queueing,
those requests started being refused on behalf of work they were not going to do, so
`get_document_ocr` probes the cache before contending. These tests pin that behaviour: a hit
bypasses the slot machinery entirely, a miss does not, and an explicit engine/cache override
(which forces a genuine re-OCR) is never allowed to take the fast path.
"""
import io
import unittest
from unittest.mock import patch

import flask
from flask.testing import EnvironBuilder
from flask import Request

from src.api import ocr_api


def _upload_request(query=""):
    app = flask.Flask(__name__)
    builder = EnvironBuilder(
        app=app,
        path="/documentOcr" + query,
        method="POST",
        data={"file": (io.BytesIO(b"pretend-jpeg-bytes"), "scan.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    return Request(builder.get_environ())


class TestOcrCacheFastPath(unittest.TestCase):
    def test_cache_hit_skips_admission_control(self):
        with patch.object(ocr_api.OcrObject, "from_file_id", return_value=object()), \
             patch.object(ocr_api, "_get_document_ocr", return_value={"ok": True}) as inner, \
             patch.object(ocr_api, "_expensive_request_slot") as slot:
            result = ocr_api.get_document_ocr(_upload_request())

        self.assertEqual(result, {"ok": True})
        inner.assert_called_once()
        slot.assert_not_called()

    def test_cache_miss_still_goes_through_admission_control(self):
        with patch.object(ocr_api.OcrObject, "from_file_id",
                          side_effect=FileNotFoundError("no cache")), \
             patch.object(ocr_api, "_get_document_ocr", return_value={"ok": True}), \
             patch.object(ocr_api, "_expensive_request_slot") as slot:
            ocr_api.get_document_ocr(_upload_request())

        slot.assert_called_once()

    def test_explicit_engine_never_takes_the_fast_path(self):
        # ?ocr_engine= forces a real re-OCR (cache is disabled for it), so it MUST be
        # rationed even if something is sitting in the cache under that hash.
        with patch.object(ocr_api.OcrObject, "from_file_id", return_value=object()) as probe, \
             patch.object(ocr_api, "_get_document_ocr", return_value={"ok": True}), \
             patch.object(ocr_api, "_expensive_request_slot") as slot:
            ocr_api.get_document_ocr(_upload_request("?ocr_engine=local"))

        probe.assert_not_called()
        slot.assert_called_once()

    def test_cache_false_never_takes_the_fast_path(self):
        with patch.object(ocr_api.OcrObject, "from_file_id", return_value=object()) as probe, \
             patch.object(ocr_api, "_get_document_ocr", return_value={"ok": True}), \
             patch.object(ocr_api, "_expensive_request_slot") as slot:
            ocr_api.get_document_ocr(_upload_request("?cache=false"))

        probe.assert_not_called()
        slot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
