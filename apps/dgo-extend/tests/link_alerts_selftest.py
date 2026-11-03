"""A link that falls is SAID (`app._alert_link_drops`) — once per outage, and its return too.

Run inside the app's image (it imports the app): `python3 tests/link_alerts_selftest.py` from
`apps/dgo-extend`. Exit code 0 = every check held. No notifications service is called: the sender is
handed in, so what would have been told is what the test reads.

Written 2026-10-19, after three links fell and were found by the owner days later while every pass
of this app had measured them.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
STATE = tempfile.mkdtemp(prefix="alert-state-")
os.environ["DGO_STATE_DIR"] = STATE
os.environ["DGO_TUNNEL_DIR"] = tempfile.mkdtemp(prefix="alert-tunnel-")

import app  # noqa: E402

app.STATE_DIR = Path(STATE)
sent = []


def told(sid, title, body, level):
    sent.append({"sid": sid, "title": title, "body": body, "level": level})
    return True


def refused(*_a):
    return False


def item(ok, office="hp-laptop", label="HP", why="הקישור הזה עובר בנתיב TCP"):
    return [{"office": office, "label": label, "verdict": {"ok": ok, "hop": "" if ok else "carry", "why": why}}]


T0, AFTER = 1_800_000_000, int(app.LINK_ALERT_AFTER)
problems = []

app._alert_link_drops(item(False), now=T0, notify=told)
if sent:
    problems.append("the first sighting of a fall starts the clock and tells nobody")
app._alert_link_drops(item(False), now=T0 + AFTER - 1, notify=told)
if sent:
    problems.append("a fall shorter than LINK_ALERT_AFTER is not news")
app._alert_link_drops(item(False), now=T0 + AFTER, notify=refused)
app._alert_link_drops(item(False), now=T0 + AFTER + 60, notify=told)
if len(sent) != 1 or sent[0]["level"] != "error" or "HP" not in sent[0]["title"]:
    problems.append(f"a fall that lasts is told once, as an error, by name — and a delivery that failed "
                    f"is tried again the next pass; got {sent}")
app._alert_link_drops(item(False), now=T0 + 5 * AFTER, notify=told)
if len(sent) != 1:
    problems.append("an outage is told ONCE, not on every pass")
app._alert_link_drops(item(None), now=T0 + 6 * AFTER, notify=told)
app._alert_link_drops(item(True), now=T0 + 6 * AFTER, notify=told)
if len(sent) != 2 or sent[1]["level"] != "info" or sent[1]["sid"] == sent[0]["sid"]:
    problems.append(f"the return of a told outage is told too, apart from it; got {sent}")
if f"{6 * AFTER // 60}" not in sent[1]["body"]:
    problems.append(f"the return says how long it lasted, got {sent[1]['body']!r}")
sent.clear()
app._alert_link_drops(item(False), now=T0 + 10 * AFTER, notify=told)
app._alert_link_drops(item(True), now=T0 + 10 * AFTER + 30, notify=told)
if sent:
    problems.append(f"a blip that never reached the threshold is not told on its return either; got {sent}")
app._alert_link_drops(item(False), now=T0 + 20 * AFTER, notify=told)
app._alert_link_drops(item(False), now=T0 + 21 * AFTER, notify=told)
if len(sent) != 1 or sent[0]["sid"].split("-")[-1] != str(T0 + 20 * AFTER):
    problems.append(f"a new outage is a new notification, named by when it began; got {sent}")

print("link_alerts selftest:", "PASS" if not problems else "FAIL")
for p in problems:
    print("  -", p)
sys.exit(1 if problems else 0)
