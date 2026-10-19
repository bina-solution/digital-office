"""Regression: OcrQuery match memos must be keyed by `region`.

Issue apitools-query-memo-ignores-region — a shared OcrQuery has its `region` re-assigned per
fallback step, but the match memos were keyed without it, so a region-scoped call could serve a
stale, whole-page list cached by an earlier unscoped step (and vice-versa). Asserted against a
FRESH-object control, not merely "two calls differ", so the key cannot silently regress when the
next parameter is added. Synthetic OCR data, so it runs with no cached files or network.
"""
import unittest

from src.ocr_core.ocr_data import OcrData
from src.ocr_core.ocr_query import OcrQuery


def _word(text, x0, y0, x1, y1):
    return {"description": text, "boundingPoly": {"vertices": [
        {"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]}}


def _make_ocr_data(words, page_w=1000, page_h=1200):
    page = _word("", 0, 0, page_w, page_h)
    return OcrData({"file_id": "synthetic-region-memo-test",
                    "textAnnotations": [page] + [_word(*w) for w in words],
                    "fullTextAnnotation": {"text": "\n".join(w[0] for w in words)}})


# A header word high on the page (kept by a top band), three identical anchor words below it
# (excluded by the band), and a bottom word that fixes the page's max center_y so the band fraction
# is deterministic. center_y = (y0 + y1) / 2.
WORDS = [
    ("H", 0, 10, 50, 30),            # center_y =   20  — kept by the band
    ("anchor", 100, 90, 200, 110),   # center_y =  100  — an anchor, excluded by the band
    ("anchor", 300, 90, 400, 110),
    ("anchor", 500, 90, 600, 110),
    ("B", 0, 1090, 50, 1110),        # center_y = 1100  — fixes ph; excluded by the band
]
TEXTS = ["anchor"]
BAND = {"y_max": 0.05}               # y1 = 0.05 * 1100 = 55: keeps H (20), excludes every anchor (100)


class TestRegionScopedMemo(unittest.TestCase):
    def _q(self):
        return OcrQuery(_make_ocr_data(WORDS), ocr_drawer=None)

    def test_band_is_load_bearing(self):
        # The band must keep >0 annotations (not the empty -> whole-page fallback) and exclude anchors,
        # or the test would pass by coincidence while the bug is present.
        q = self._q()
        q.region = BAND
        kept = [a.description for a in q.text_annotations]
        self.assertGreater(len(kept), 0, "band stranded the query -> it fell back to the whole page")
        self.assertNotIn("anchor", kept, "band must exclude the anchors")

    def test_scoped_after_unscoped_respects_region(self):
        unscoped_control = len(self._q().find_texts_matching_annotations(TEXTS))
        scoped_q = self._q()
        scoped_q.region = BAND
        scoped_control = len(scoped_q.find_texts_matching_annotations(TEXTS))
        self.assertGreaterEqual(unscoped_control, 1, "anchors must be matchable unscoped")
        self.assertLess(scoped_control, unscoped_control, "region must genuinely filter the anchors out")

        # The bug: a shared object, unscoped first then scoped, must not serve the stale unscoped list.
        shared = self._q()
        shared.find_texts_matching_annotations(TEXTS)          # populate the memo unscoped
        shared.region = BAND
        scoped_after = len(shared.find_texts_matching_annotations(TEXTS))
        self.assertEqual(scoped_after, scoped_control,
                         "a region-scoped call after an unscoped one must match the fresh scoped control")

    def test_unscoped_after_scoped_respects_region(self):
        unscoped_control = len(self._q().find_texts_matching_annotations(TEXTS))
        shared = self._q()
        shared.region = BAND
        shared.find_texts_matching_annotations(TEXTS)          # populate the memo scoped
        shared.region = None
        unscoped_after = len(shared.find_texts_matching_annotations(TEXTS))
        self.assertEqual(unscoped_after, unscoped_control,
                         "an unscoped call after a scoped one must match the fresh unscoped control")


if __name__ == "__main__":
    unittest.main()
