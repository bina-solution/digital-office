import json
import time
import unittest
from pathlib import Path

from src.ocr_core.ocr_data import OcrData
from src.ocr_core.ocr_query import OcrQuery


class TestOcrQueryLimits(unittest.TestCase):
    def test_problem_ocr_cache_alignment_search_is_bounded(self):
        cache_dir = Path("/tmp/apitools_problem_docs/ocr_cache")
        if not cache_dir.exists():
            self.skipTest("problem OCR cache bundle is not available")

        cache_files = sorted(cache_dir.glob("*.json"))[:3]
        if not cache_files:
            self.skipTest("problem OCR cache bundle is empty")

        for cache_file in cache_files:
            with self.subTest(cache_file=cache_file.name):
                with cache_file.open("r", encoding="utf-8") as handle:
                    ocr_dict = json.load(handle)

                query = OcrQuery(OcrData(ocr_dict), ocr_drawer=None)
                started = time.monotonic()
                result = query.find_texts_matching_annotations_via_alignment(
                    ["__this_text_should_not_exist__"],
                    fuzzy=False,
                    max_matches=1,
                    max_anchor_scan=200,
                )

                self.assertIsNone(result)
                self.assertLess(time.monotonic() - started, 5.0)


if __name__ == "__main__":
    unittest.main()