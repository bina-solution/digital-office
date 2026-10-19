"""Regression: /documentJsonQuery must signal request-level failures with a 4xx status, not a 200
whose body merely carries an error.

A 200 that means "I did nothing" is invisible to every status-code-based monitor and caller — it is
the "unread-failure" defect class (issues/unread-failure-defect-class.md; api-tools-id-never-persisted
part 2; bff-returns-200-carrying-an-upstream-404), called the single most expensive shape of bug in
this repo's own issue history. Request-shape errors (missing file_id / queries) are 400; a file whose
OCR does not exist is 404. Per-field errors inside a batch stay in the 200 body (partial success) and
are deliberately NOT changed here.

Offline: Flask test_client. Every path asserted validates the request BEFORE any OCR/DB/store access.
"""
import json
import sys
import types
import unittest

# The app's API layer imports `fcntl` (Unix-only, cross-worker slot locking) at module load. That
# locking is orthogonal to the request-shape validation these tests exercise, so on a platform
# without fcntl (Windows dev host) we stub it to no-ops. On Unix (CI / the apitools container) the
# real module imports and this block does nothing.
try:  # noqa: SIM105
    import fcntl  # noqa: F401
except ImportError:
    _f = types.ModuleType("fcntl")
    _f.flock = _f.lockf = lambda *a, **k: None
    _f.fcntl = lambda *a, **k: 0
    _f.LOCK_EX = _f.LOCK_SH = _f.LOCK_NB = _f.LOCK_UN = 0
    sys.modules["fcntl"] = _f

from src.api import create_app  # noqa: E402


class TestJsonQueryErrorStatus(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def _post(self, payload):
        return self.client.post("/documentJsonQuery", data=json.dumps(payload),
                                content_type="application/json")

    def test_empty_json_is_400(self):
        # An empty body is falsy, so it hits the missing_json_request guard (not missing_file_id).
        r = self._post({})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json().get("error"), "missing_json_request")

    def test_missing_file_id_is_400(self):
        # A non-empty body with no file_id reaches the missing_file_id guard.
        r = self._post({"ocr_json_query": {"action": "find", "action_value": ["x"]}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json().get("error"), "missing_file_id")

    def test_missing_ocr_json_queries_is_400(self):
        r = self._post({"file_id": "x", "ocr_json_queries": []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json().get("error"), "missing_ocr_json_queries")

    def test_missing_ocr_json_query_is_400(self):
        r = self._post({"file_id": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json().get("error"), "missing_ocr_json_query")

    def test_file_not_found_is_404(self):
        r = self._post({"file_id": "__nonexistent_test_file__",
                        "ocr_json_queries": [{"ocr_json_query": {"action": "find", "action_value": ["x"]}}]})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json().get("error"), "file_not_found")


if __name__ == "__main__":
    unittest.main()
