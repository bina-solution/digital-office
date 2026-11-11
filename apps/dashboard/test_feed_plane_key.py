"""test_feed_plane_key.py — the office that runs Plane reads it with its own key (feed.py plane_base, DGO-1329).

    python3 apps/dashboard/test_feed_plane_key.py

On the office that runs Plane (the HP) no door signs the feed's requests: its Plane is the project-pln container,
asked with the vault's `plane_local_api_token-local`. What is asked: the local address and the key on every request
under it; another office's door is asked with no key at all; a vault that does not answer leaves no key and no crash.
No network: urlopen is a fake that records what it was asked.
"""
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(DASHBOARD_STATE=os.path.join(TMP, "state.json"), DASHBOARD_HERD=os.path.join(TMP, "herd.yaml"),
                  DASHBOARD_REGISTRY=TMP, DASHBOARD_PLANE_KEY_PACE="0")
SPEC = importlib.util.spec_from_file_location("dashboard_feed_key", os.path.join(HERE, "feed.py"))
f = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f)


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class PlaneKey(unittest.TestCase):
    def setUp(self):
        f.KEYS.clear()
        self.asked, self.vault = [], {"secret": {"token": "k-local"}}
        for p in (f.HERD, os.path.join(TMP, "remote.hp-laptop.plane.json")):
            if os.path.exists(p):
                os.remove(p)

    def urlopen(self, req, timeout=8):
        self.asked.append((req.full_url, req.get_header("X-api-key")))
        if req.full_url.endswith("/api/instances/plane_local_api_token-local/secret"):
            if self.vault is None:
                raise OSError("connection refused")
            return Answer(json.dumps(self.vault).encode())
        return Answer(b'{"results": []}')

    def read(self):
        with mock.patch.object(f.urllib.request, "urlopen", self.urlopen):
            base = f.plane_base()
            f.get(base + "/projects/")
        return base

    def test_the_local_plane_is_asked_with_the_office_key(self):
        base = self.read()
        self.assertEqual(base, "http://project-pln:80/api/v1/workspaces/bina")
        self.assertEqual(self.asked[0], ("http://connections:8990/api/instances/plane_local_api_token-local/secret", None))
        self.assertEqual(self.asked[-1], (base + "/projects/", "k-local"))

    def test_another_offices_door_is_asked_with_no_key(self):
        with open(f.HERD, "w", encoding="utf-8") as fh:
            fh.write("apps:\n  project-pln: hp-laptop\n")
        with open(os.path.join(TMP, "remote.hp-laptop.plane.json"), "w", encoding="utf-8") as fh:
            json.dump({"link_port": 9011}, fh)
        base = self.read()
        self.assertEqual(base, "http://plane.hp-laptop:9011/api/v1/workspaces/bina")
        self.assertEqual(self.asked, [(base + "/projects/", None)])     # the vault is never read for a door

    def test_a_vault_that_does_not_answer_leaves_no_key_and_no_crash(self):
        self.vault = None
        base = self.read()
        self.assertEqual(self.asked[-1], (base + "/projects/", None))

    def test_requests_with_the_key_are_paced_and_a_doors_are_not(self):
        f.KEY_PACE = 0.25
        try:
            with mock.patch.object(f.urllib.request, "urlopen", self.urlopen):
                base = f.plane_base()
                t0 = f.time.time()
                f.get(base + "/a/")
                f.get(base + "/b/")
                keyed = f.time.time() - t0
                t1 = f.time.time()
                f.get("http://plane.hp-laptop:9011/api/v1/workspaces/bina/c/")
                f.get("http://plane.hp-laptop:9011/api/v1/workspaces/bina/d/")
                door = f.time.time() - t1
        finally:
            f.KEY_PACE = 0.0
        self.assertGreaterEqual(keyed, 0.25)         # Plane's 60 a minute per key: two keyed asks never back to back
        self.assertLess(door, 0.2)

    def test_a_429_waits_for_the_keys_minute_and_asks_the_same_page_again(self):
        refusals = {"left": 2}

        def busy(req, timeout=8):
            if "/issues/" in req.full_url and refusals["left"]:
                refusals["left"] -= 1
                self.asked.append((req.full_url, "429"))
                raise f.urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {},
                                               io.BytesIO(b'{"error_code":5900,"error_message":"RATE_LIMIT_EXCEEDED"}'))
            return self.urlopen(req, timeout)
        saved, f.RATE_WAIT = f.RATE_WAIT, 0.0
        try:
            with mock.patch.object(f.urllib.request, "urlopen", busy):
                base = f.plane_base()
                self.assertEqual(f.get(base + "/issues/?page=7"), {"results": []})   # the third ask is answered
                refusals["left"] = 3
                self.assertTrue(f.get(base + "/issues/?page=8")["_error"].startswith("HTTP 429"))  # never forever
                refusals["left"] = 1                                                   # a door: no key, no retry
                self.assertTrue(f.get("http://plane.hp-laptop:9011/x/issues/")["_error"].startswith("HTTP 429"))
                self.assertEqual(f.get("http://plane.hp-laptop:9011/x/issues/"), {"results": []})
        finally:
            f.RATE_WAIT = saved
        self.assertEqual([a[1] for a in self.asked if a[0].endswith("page=7")], ["429", "429", "k-local"])
        self.assertEqual(f.rate_wait({"Retry-After": "7"}), 7.0)                       # Plane's own word, when said
        self.assertEqual(f.rate_wait({"Retry-After": "900"}), 60.0)                    # at most the key's minute
        self.assertEqual(f.rate_wait({}), f.RATE_WAIT)

    def test_a_restart_starts_from_the_last_full_reads_counts_and_day_while_that_read_is_fresh(self):
        now = f.time.time()
        totals, topics = {"all": 1423, "started": 75, "owner": 51}, [{"name": "דיווחים", "done": 3, "total": 8}]
        feed = [{"ts": now - 100, "kind": "open", "ref": "DGO-1", "text": "נפתח: א"},
                {"ts": now - 90, "kind": "done", "ref": "DGO-2", "text": "נסגר: ב", "by": "עזריה"},
                {"ts": now - 80, "kind": "start", "ref": "DGO-3", "text": "התחיל: ג", "live": 1},
                {"ts": now - 70, "kind": "bad", "ref": "", "text": "Dell נפל מהקישור"}]
        doc = {"at": now, "plane_at": now - 60, "totals": totals, "topics": topics + ["not a topic"], "feed": feed,
               "errors": {"plane": "HTTP 429: busy"}}
        got = f.saved_plane(doc)
        self.assertEqual((got["totals"], got["topics"], got["read_at"], got["error"]), (totals, topics, now - 60,
                                                                                         "HTTP 429: busy"))
        self.assertEqual([e["ref"] for e in got["events"]], ["DGO-1", "DGO-2"])      # opens and closes, not live, not links
        self.assertEqual([e["ref"] for e in f.saved_live_lines(doc)], ["DGO-3"])
        # the file is rewritten every pass: ITS age says nothing — the read that made the counts is an hour old
        self.assertEqual(f.saved_plane(dict(doc, plane_at=now - 7200)), {})
        self.assertEqual(f.saved_plane(dict(doc, plane_at=None)), {})
        for junk in ({}, {"plane_at": "x", "totals": {}}, {"plane_at": now, "totals": 5}, [1, 2], "x"):
            self.assertEqual(f.saved_plane(junk), {}, junk)
        path = os.path.join(TMP, "saved-state.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        self.assertEqual(f.saved_state(path), json.loads(json.dumps(doc, ensure_ascii=False)))
        for junk in ("{half", "[1, 2]"):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(f.saved_state(path), {})
        self.assertEqual(f.saved_state(os.path.join(TMP, "absent.json")), {})

    def test_a_key_read_once_stays_when_the_vault_is_away_later(self):
        self.read()
        self.vault = None
        base = self.read()
        self.assertEqual(self.asked[-1], (base + "/projects/", "k-local"))


if __name__ == "__main__":
    unittest.main()
