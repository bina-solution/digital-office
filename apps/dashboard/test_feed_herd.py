"""test_feed_herd.py — what the control centre says of an office whose link from HERE does not answer (DGO-1321).

    python3 apps/dashboard/test_feed_herd.py

The owner, 2026-11-03 21:19, on his phone through vps1's address: the MacBook's control centre read «vps1 לא ברשת»
while vps1 served the page — vps1 had dropped its side of the MacBook pair and the HP heard it 14 s before. Asked
here, with fakes and no network: an office another office reaches is `away` (on the network, the link from here
broken, with the measured reason and who reaches it), never `down`; one nobody reaches stays `down`; a down row's
"since" is the link history's own record of the fall, and with neither a record nor a handshake it is "unknown",
never the minute the page was read.
"""
import importlib.util
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(DASHBOARD_STATE=os.path.join(TMP, "state.json"), DASHBOARD_HERD=os.path.join(TMP, "none.yaml"))
SPEC = importlib.util.spec_from_file_location("dashboard_feed_herd", os.path.join(HERE, "feed.py"))
f = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f)

DOORS = {"hp-laptop": "http://computers.hp-laptop:9005", "examplef": "http://computers.examplef:9006"}


ASKED = []


SCALE = 0.1   # the fake's clock: a read's real timeout × SCALE is how long it may take here


def world(items, history=(), reach=(), mute=(), no_security=(), slow_security=(), delay=0.0, raising=(), delays=None,
          late=()):
    """The feed's reads, faked: this office's map and link history, every Computers app answering for its own
    machine but those in `mute`, and `reach` = the (office, target) pairs whose read of the target through that
    office answers. A target in `no_security` has its security app registered and not running: the far door's
    own 502 comes back (computers' Herd._fetch passes it through), its machine answers. A read of a target in
    `slow_security` times out (a dict maps it to the error said); one of a target in `raising` raises. Every
    read of a host takes `delay` seconds, or `delays[<service>]`."""
    ASKED.clear()

    def get(url, timeout=8):
        if url.endswith("/api/map"):
            return {"home": {"id": "macbook"}, "items": items}
        if "/api/link/history" in url:
            return {"items": list(history)}
        for office, door in DOORS.items():
            if url.startswith(f"{door}/api/computers/computer_local-local/status"):
                return {"_error": "timed out"} if office in mute else {"id": "computer_local-local", "state": "ok"}
            if url.startswith(f"{door}/api/computers?probe=1"):
                return {"_error": "timed out"} if office in mute else {"computers": [{"id": "computer_local-local", "state": "ok"}]}
            if url.startswith(f"{door}/api/hosts/"):
                target, service = url.split("/")[5:7]          # http: · · host · api · hosts · <target> · <service>
                ASKED.append((office, target, service))
                # a read honours its own timeout, as urllib's does: a service in `late` fails at the very end of it
                limit = timeout * SCALE
                wait = limit * 0.97 if service in late else (delays or {}).get(service, delay)
                time.sleep(min(wait, limit))
                if wait > limit:
                    return {"_error": "timed out"}
                if target in raising:
                    raise RuntimeError("a worker that raises")
                if target in slow_security and service == "security":
                    return {"_error": slow_security[target] if isinstance(slow_security, dict) else "timed out"}
                if target in no_security and service == "security":
                    return {"_error": "HTTP 502: security is not running"}
                return {"ok": True} if (office, target) in reach else {"_error": "HTTP 502: "}
        if "/api/computers/computer_local-local/status" in url:
            return {"id": "computer_local-local", "state": "ok"}
        if "/api/computers?probe=1" in url:
            return {"computers": [{"id": "computer_local-local", "state": "ok"}]}
        return {"_error": "not faked: " + url}
    f.get = get
    f.door = lambda office, alias="computers": DOORS.get(office, "")
    return {c["office"]: c for c in f.collect()["computers"]}


UP = {"office": "hp-laptop", "state": "up", "transport": "tcp", "handshake_age_s": 40, "state_error": ""}
VPS1 = {"office": "vps1", "state": "down", "transport": "udp", "handshake_age_s": None,
        "state_error": "הלשכה לא ענתה דרך הקישור (HTTP 502)"}


class TheHerdsSecondEyes(unittest.TestCase):
    def test_an_office_another_one_reaches_is_away_not_down(self):
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")})
        v = rows["vps1"]
        self.assertEqual(v["state"], "away")
        self.assertEqual(v["heard_by"], "hp-laptop")
        self.assertIn("HTTP 502", v["why"])
        self.assertEqual(v["when"], "עכשיו")
        self.assertNotIn("when_ts", v)

    def test_an_office_nobody_reaches_stays_down_since_its_recorded_fall(self):
        rows = world([UP, VPS1], history=[{"kind": "change", "office": "vps1", "ok": False, "at": 1793722620}])
        v = rows["vps1"]
        self.assertEqual(v["state"], "down")
        self.assertEqual(v["since_ts"], 1793722620)

    def test_no_record_and_no_handshake_is_unknown_never_now(self):
        v = world([UP, VPS1])["vps1"]
        self.assertEqual(v["state"], "down")
        self.assertNotIn("since_ts", v)
        self.assertEqual(v["when"], "לא ידוע מתי")

    def test_a_fall_then_a_recovery_is_not_when_this_outage_began(self):
        # vps1 fell at 100 and came back at 200; it is down again now, with no record of the new fall yet
        hist = [{"kind": "change", "office": "vps1", "ok": False, "at": 100},
                {"kind": "change", "office": "vps1", "ok": True, "at": 200}]
        v = world([UP, VPS1], history=hist)["vps1"]
        self.assertNotEqual(v.get("since_ts"), 100)
        self.assertEqual(v["when"], "לא ידוע מתי")
        # …and `ok: None` is "not measured" (extend's _verdict: a restart), never a fall
        v = world([UP, VPS1], history=hist + [{"kind": "change", "office": "vps1", "ok": None, "at": 300}])["vps1"]
        self.assertNotIn("since_ts", v)

    def test_a_hop_change_while_down_is_not_a_new_fall(self):
        # extend writes a change row on every (ok, hop) change: fell at 100, its hop changed at 160, still down
        hist = [{"kind": "change", "office": "vps1", "ok": True, "at": 50},
                {"kind": "change", "office": "vps1", "ok": False, "hop": "door", "at": 100},
                {"kind": "change", "office": "vps1", "ok": None, "at": 130},
                {"kind": "change", "office": "vps1", "ok": False, "hop": "link", "at": 160}]
        self.assertEqual(world([UP, VPS1], history=hist)["vps1"]["since_ts"], 100)

    def test_an_office_whose_computers_app_did_not_answer_is_not_asked(self):
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")}, mute={"hp-laptop"})
        self.assertEqual(rows["vps1"]["state"], "down")
        self.assertEqual(ASKED, [])

    def test_the_machine_is_asked_when_security_fails_but_not_when_it_times_out(self):
        world([UP, VPS1], reach={("hp-laptop", "vps1")})
        self.assertEqual([a[2] for a in ASKED], ["security"])
        # vps1's security registered and not running: the far door's 502 comes back — the machine is asked
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")}, no_security={"vps1"})
        self.assertEqual([a[2] for a in ASKED], ["security", "machine"])
        self.assertEqual(rows["vps1"]["state"], "away")
        # a read that timed out is not asked again: the pass stays within one ask's time
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")}, slow_security={"vps1"})
        self.assertEqual([a[2] for a in ASKED], ["security"])
        self.assertEqual(rows["vps1"]["state"], "down")
        # …and the far Computers app's own timeout, said as HTTP 504, is a timeout too
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")}, slow_security={"vps1": "HTTP 504: המחשב לא ענה בזמן"})
        self.assertEqual([a[2] for a in ASKED], ["security"])
        self.assertEqual(rows["vps1"]["state"], "down")

    def test_a_worker_that_raises_is_not_heard_and_breaks_nothing(self):
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")}, raising={"vps1"})
        self.assertEqual(rows["vps1"]["state"], "down")
        self.assertEqual(rows["hp-laptop"]["state"], "up")

    def test_a_straggler_past_the_deadline_is_not_heard(self):
        t0 = time.monotonic()
        got = f.at_once(lambda x: (time.sleep(0.6), True)[1], [1, 2], False, 0.2, "test reads")
        took = time.monotonic() - t0
        self.assertEqual(got, [False, False])
        self.assertLess(took, 0.5, f"the round waited {took:.2f} s for stragglers past its 0.2 s deadline")

    def test_a_fallback_that_answers_inside_the_deadline_counts(self):
        # the two reads together fit ASK_DEADLINE: at a tenth of the real scale (16 s → 1.6 s), security failing at
        # 0.8 s and the machine answering 0.7 s later — 1.5 s, the real ~15 s — is heard; c0f35c84's 11 s first read
        # made the sum 19 s, past the deadline, and the row read «down»
        # the security read fails at the very END of its own timeout and the machine takes nearly all of its own:
        # a first read made longer than 8 s again (c0f35c84's 11) pushes the pair past the deadline and fails here
        was = f.ASK_DEADLINE
        f.ASK_DEADLINE = f.ASK_DEADLINE * SCALE
        try:
            rows = world([UP, VPS1], reach={("hp-laptop", "vps1")}, no_security={"vps1"},
                         late={"security"}, delays={"machine": 8 * SCALE * 0.95})
        finally:
            f.ASK_DEADLINE = was
        self.assertEqual([a[2] for a in ASKED], ["security", "machine"])
        self.assertEqual(rows["vps1"]["state"], "away")

    def test_the_asks_run_at_once_in_one_wave(self):
        # 10 offices down × 2 up = 20 asks, each a failed security read and a machine read of 0.3 s: in one wave
        # 0.6 s; a pool of 16 (the first version) took two waves, 1.2 s; one after another, 12 s
        fire = {"office": "examplef", "state": "up", "transport": "tcp", "handshake_age_s": 20, "state_error": ""}
        down = [dict(VPS1, office=f"far{i}") for i in range(10)]
        t0 = time.monotonic()
        world([UP, fire] + down, delay=0.3)
        took = time.monotonic() - t0
        self.assertEqual(len(ASKED), 40)
        self.assertLess(took, 1.0, f"20 asks of 2 × 0.3 s took {took:.2f} s: not one wave")

    def test_the_home_row_is_marked_and_never_asked_about(self):
        rows = world([UP, VPS1], reach={("hp-laptop", "vps1")})
        self.assertTrue(rows["macbook"]["home"])
        self.assertEqual(rows["hp-laptop"]["state"], "up")


class TheOfficesOwnMachine(unittest.TestCase):
    """DGO-1353: the MacBook away from home read its own row «the computers app did not answer» — the fleet
    probe it asked for took 17–20 s (two LAN machines timing out in turn) against the read's 8 s."""

    def ask(self, answers):
        asked = []

        def get(url, timeout=8):
            asked.append(url.split("/api/", 1)[1])
            return answers.get(url.split("/api/", 1)[1], {"_error": "not faked: " + url})
        f.get = get
        return f.local_state("http://computers:8977"), asked

    def test_it_asks_for_its_own_machine_and_never_for_the_fleet(self):
        got, asked = self.ask({"computers/computer_local-local/status": {"state": "needs_action", "reason": "x"},
                               "computers?probe=1": {"_error": "timed out"}})
        self.assertEqual(got, ("needs_action", "x"))
        self.assertEqual(asked, ["computers/computer_local-local/status"])

    def test_an_ok_without_a_state_is_ok(self):
        got, _ = self.ask({"computers/computer_local-local/status": {"id": "computer_local-local", "ok": True}})
        self.assertEqual(got, ("ok", ""))

    def test_no_such_machine_is_unknown_and_the_fleet_is_not_asked(self):
        # the app's own 404 («לא נמצא מחשב בזהות …», _resolve) — the fleet said the same by leaving the row out
        got, asked = self.ask({"computers/computer_local-local/status":
                               {"_error": 'HTTP 404: {"error":"לא נמצא מחשב בזהות computer_local-local"}'}})
        self.assertEqual(got, ("unknown", ""))
        self.assertEqual(asked, ["computers/computer_local-local/status"])

    def test_an_app_that_does_not_answer_is_unreachable(self):
        got, asked = self.ask({"computers/computer_local-local/status": {"_error": "timed out"}})
        self.assertEqual(got[0], "unreachable")
        self.assertEqual(asked, ["computers/computer_local-local/status"])


class TheFleetIsStillWarmed(unittest.TestCase):
    """The console's account bar colours every machine from the Computers app's probe cache, which the fleet read
    kept warm on every pass: it still runs, beside the pass, never waited for and never two at once."""

    def test_the_fleet_is_probed_beside_the_pass_one_at_a_time(self):
        import threading as th
        for _ in range(250):                               # a pass of another test may still be warming
            if not f._warming.locked():
                break
            time.sleep(0.02)
        started, release, calls = th.Event(), th.Event(), []

        def get(url, timeout=8):
            calls.append((url, timeout))
            started.set()
            release.wait(5)
            return {"computers": []}
        f.get = get
        began = time.monotonic()
        f.warm_fleet("http://computers:8977")
        self.assertTrue(started.wait(2))
        f.warm_fleet("http://computers:8977")              # one is still running: not a second
        self.assertLess(time.monotonic() - began, 1.0)     # and nobody waited for it
        release.set()
        for _ in range(50):
            if not f._warming.locked():
                break
            time.sleep(0.02)
        self.assertEqual(calls, [("http://computers:8977/api/computers?probe=1", 60)])
        f.warm_fleet("http://computers:8977")              # done: the next pass warms again
        for _ in range(50):
            if len(calls) == 2:
                break
            time.sleep(0.02)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
