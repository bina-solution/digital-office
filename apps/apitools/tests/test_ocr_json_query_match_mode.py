"""Unit coverage for OcrJsonQuery's `find option` match_mode ("id" / "name_substring").

Added for the company-id-ocr-recognition Phase 0 wiring (see
issues/company-id-ocr-recognition-design.yaml). match_mode had ZERO test coverage
before this file — its only prior evidence was an inline code comment claiming
"81.4%/89.8% recall/precision over 97 ground-truth rows" (ocr_json_query.py, the
id-mode position-ordering block). These tests don't reproduce that ground-truth
measurement (no access to the 97-row corpus), but they pin down the two behaviours
that comment credits with the improvement, using synthetic OCR data so they run
without a live apitools server, network, or image corpus:

  1. position ordering: the FIRST-appearing candidate id wins, not the
     lexicographically largest one (the regression `max(hits)` had before).
  2. exclude_near: a candidate sitting next to a recipient marker (e.g. the
     client's own name) is vetoed rather than mistaken for the issuer's id.

Run: `cd apps/apitools && python -m unittest tests/test_ocr_json_query_match_mode.py`
(same convention as tests/test_ocr_query_limits.py — no server required).
"""

import unittest

from src.ocr_core.ocr_data import OcrData
from src.ocr_core.ocr_query import OcrQuery
from src.ocr_core.ocr_json_query import OcrJsonQuery


def _word(text: str, x0: int, y0: int, x1: int, y1: int) -> dict:
    return {
        "description": text,
        "boundingPoly": {
            "vertices": [
                {"x": x0, "y": y0},
                {"x": x1, "y": y0},
                {"x": x1, "y": y1},
                {"x": x0, "y": y1},
            ]
        },
    }


def _make_ocr_data(words, page_w: int = 1000, page_h: int = 1400) -> OcrData:
    """`words` is a list of (text, x0, y0, x1, y1) tuples IN READING ORDER — the
    `find option`/id-mode position-ordering logic scans textAnnotations in array
    order (mirroring how Google Vision/local OCR emit them), so list order here
    stands in for on-page reading order."""
    page = _word("", 0, 0, page_w, page_h)
    text_annotations = [page] + [_word(*w) for w in words]
    full_text = "\n".join(w[0] for w in words)
    return OcrData({
        "file_id": "synthetic-match-mode-test",
        "textAnnotations": text_annotations,
        "fullTextAnnotation": {"text": full_text},
    })


def _query(ocr_data: OcrData) -> OcrJsonQuery:
    return OcrJsonQuery(OcrQuery(ocr_data, ocr_drawer=None))


class TestMatchModeId(unittest.TestCase):
    def test_basic_match_ignores_absent_options(self):
        """A registered id printed on the page is found; an option that never
        appears is ignored (no false positive from an unrelated candidate)."""
        ocr_data = _make_ocr_data([
            ("עוסק", 100, 40, 160, 70),
            ("מורשה", 170, 40, 230, 70),
            ("514745819", 240, 40, 340, 70),
        ])
        result = _query(ocr_data).json_query({
            "action": "find option",
            "action_value": ["514745819", "000000000"],
            "match_mode": "id",
            "is_rtl": True,
        })
        matches = result["result"]["matches"]
        self.assertEqual([m["option"] for m in matches], ["514745819"])

    def test_position_ordering_not_lexicographic(self):
        """Two registered ids both appear on the page. The FIRST one in reading
        order must win even though it is lexicographically SMALLER than the
        second — this is the exact regression the ocr_json_query.py code comment
        documents: the old `max(hits)` picked the lexicographically largest id
        string, which is arbitrary the moment a document carries two ids (the
        comment cites 11/144 cached documents doing exactly that, the second
        usually being the recipient's own)."""
        ocr_data = _make_ocr_data([
            ("111111111", 100, 40, 200, 70),      # issuer id — appears first
            ("filler", 100, 400, 200, 430),
            ("999999999", 100, 900, 200, 930),    # recipient's own — appears later
        ])
        result = _query(ocr_data).json_query({
            "action": "find option",
            # deliberately listed out of on-page order
            "action_value": ["999999999", "111111111"],
            "match_mode": "id",
            "is_rtl": True,
        })
        matches = result["result"]["matches"]
        self.assertEqual([m["option"] for m in matches], ["111111111"])

    def test_exclude_near_vetoes_id_adjacent_to_recipient_marker(self):
        """An id sitting immediately next to a recipient marker (the client's own
        name, 'הכהנים' in production per q_v3_company's calibrated exclude_near
        list) must not be picked when that marker is passed in exclude_near —
        without it, the same id IS picked (false positive), proving exclude_near
        is actually doing the vetoing rather than the id simply never matching."""
        words = [
            ("לכבוד", 100, 900, 200, 930),
            ("מ.ש", 100, 940, 150, 970),
            ("הכהנים", 160, 940, 260, 970),
            ("מס'", 100, 980, 150, 1010),
            ("לקוח", 160, 980, 220, 1010),
            ("603603603", 230, 980, 330, 1010),
        ]

        result_no_exclude = _query(_make_ocr_data(words)).json_query({
            "action": "find option",
            "action_value": ["603603603"],
            "match_mode": "id",
            "is_rtl": True,
        })
        self.assertIsNotNone(result_no_exclude.get("result"))
        self.assertEqual(
            [m["option"] for m in result_no_exclude["result"]["matches"]],
            ["603603603"],
        )

        result_excluded = _query(_make_ocr_data(words)).json_query({
            "action": "find option",
            "action_value": ["603603603"],
            "match_mode": "id",
            "exclude_near": ["הכהנים"],
            "is_rtl": True,
        })
        self.assertIsNone(result_excluded.get("result"))
        self.assertEqual(result_excluded.get("error", {}).get("type"), "ActionOutputNone")


class TestMatchModeNameSubstring(unittest.TestCase):
    def test_ktiv_insensitive_match_with_option_map(self):
        """A letterhead name spelled with reduced ktiv ('הכל' vs the registry's
        'הכול') still matches, and option_map resolves the matched NAME back to
        the company's id — exactly the acronym-letterhead case the code comment
        for this branch describes ('א.י.ש. הכל ירוק' vs 'איש הכול ירוק')."""
        ocr_data = _make_ocr_data([
            ("א.י.ש.", 100, 40, 160, 70),
            ("הכל", 170, 40, 220, 70),   # ktiv-reduced spelling
            ("ירוק", 230, 40, 280, 70),
            ("בע\"מ", 290, 40, 340, 70),
        ])
        result = _query(ocr_data).json_query({
            "action": "find option",
            "action_value": ["איש הכול ירוק"],
            "option_map": {"איש הכול ירוק": "514194612"},
            "match_mode": "name_substring",
            "is_rtl": True,
        })
        matches = result["result"]["matches"]
        self.assertEqual([m["option"] for m in matches], ["514194612"])

    def test_exclude_near_vetoes_name_adjacent_to_recipient_marker(self):
        """A name fragment adjacent to the recipient marker must not be picked —
        with the control case (no exclude_near) proving the same setup DOES match
        absent the veto, so the second assertion is exercising exclude_near and
        not some unrelated reason the match failed."""
        words = [
            ("לכבוד", 100, 900, 200, 930),
            ("מ.ש", 100, 940, 150, 970),
            ("הכהנים", 160, 940, 260, 970),
        ]

        result_no_exclude = _query(_make_ocr_data(words)).json_query({
            "action": "find option",
            "action_value": ["הכהנים"],
            "option_map": {"הכהנים": "SHOULD_NOT_SURVIVE_EXCLUSION"},
            "match_mode": "name_substring",
            "is_rtl": True,
        })
        self.assertIsNotNone(result_no_exclude.get("result"))

        result_excluded = _query(_make_ocr_data(words)).json_query({
            "action": "find option",
            "action_value": ["הכהנים"],
            "option_map": {"הכהנים": "SHOULD_NOT_SURVIVE_EXCLUSION"},
            "match_mode": "name_substring",
            "exclude_near": ["הכהנים"],
            "is_rtl": True,
        })
        self.assertIsNone(result_excluded.get("result"))


if __name__ == "__main__":
    unittest.main()
