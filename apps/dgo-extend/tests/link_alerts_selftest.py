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
os.environ.pop("DGO_LINK_ALERT_AFTER", None)
# a herd file of the test's own (DGO-922): vps1 declares five minutes, the HP nothing — so the checks below that use
# the HP keep the default, whatever herd file the image happens to carry
HERD = Path(tempfile.mkdtemp(prefix="alert-herd-")) / "herd.yaml"
HERD.write_text("offices:\n  hp-laptop: {label: HP}\n  vps1: {label: vps1, alert_after_s: 300}\n"
                "  dell: {aliases: [portable-ubuntu], alert_after_s: bad}\n  hub2: {alert_after_s: 300}\n"
                "  odd: just-a-string\n", encoding="utf-8")
os.environ["DGO_HERD_FILE"] = str(HERD)

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

# DGO-922: the herd file says how long each office may be silent — the always-on vps1 300 s, the HP the default
if (app._link_alert_after("vps1"), app._link_alert_after("hp-laptop")) != (300.0, float(AFTER)):
    problems.append(f"vps1 declares 300 s, the HP nothing; got {app._link_alert_after('vps1')}, "
                    f"{app._link_alert_after('hp-laptop')}")
if app._link_alert_after("portable-ubuntu") != float(AFTER):
    problems.append("a value that is not a number (the Dell's `bad`, found by its alias) is the default")
if app._link_alert_after("nobody") != float(AFTER):
    problems.append("an office the herd file does not name keeps the default")
if app._link_alert_after("odd") != float(AFTER):
    problems.append("an entry that is not a mapping keeps the default (and stops nothing)")
if app._link_alert_after("vps1", home="hub2") != 300.0:
    problems.append("two always-on ends: five minutes")
if app._link_alert_after("vps1", home="hp-laptop") != float(AFTER):
    problems.append("a pair with an end that declares nothing (a laptop) keeps ten minutes — the larger of the two")
sent.clear()
v = [{"office": "vps1", "label": "vps1", "verdict": {"ok": False, "hop": "tunnel", "why": "x"}}]
app._alert_link_drops(v, now=T0 + 30 * AFTER, notify=told)
app._alert_link_drops(v, now=T0 + 30 * AFTER + 299, notify=told)
if sent:
    problems.append("vps1 silent 299 s is not news yet")
app._alert_link_drops(v, now=T0 + 30 * AFTER + 300, notify=told)
if len(sent) != 1 or "vps1" not in sent[0]["title"]:
    problems.append(f"vps1 silent 300 s is told — its own five minutes, not the default ten; got {sent}")
app._LINK_ALERT_ENV, keep = True, app.LINK_ALERT_AFTER
app.LINK_ALERT_AFTER = 120.0
if app._link_alert_after("vps1") != 120.0:
    problems.append("an office's own DGO_LINK_ALERT_AFTER wins over the herd file")
app._LINK_ALERT_ENV, app.LINK_ALERT_AFTER = False, keep

# DGO-1782: a tunnel that answers while the office's catalog check does not (`hop: office`) is CONNECTED — told
# as a warning in those words, never «נפל»; and its return says the check answers again, not «הקישור חזר»
app._alert_link_drops(item(True), now=T0 + 39 * AFTER, notify=told)     # the earlier outage ends first
sent.clear()
slow = [{"office": "hp-laptop", "label": "HP", "verdict": {"ok": False, "hop": "office", "why": "x"}}]
app._alert_link_drops(slow, now=T0 + 40 * AFTER, notify=told)
app._alert_link_drops(slow, now=T0 + 41 * AFTER, notify=told)
if (len(sent) != 1 or sent[0]["level"] != "warning" or "נפל" in sent[0]["title"] or "מחוברת" not in sent[0]["title"]
        or not sent[0]["sid"].startswith("link-slow-")):
    problems.append(f"a live tunnel whose check did not answer is told as connected (a warning), never «נפל»; got {sent}")
app._alert_link_drops(item(True), now=T0 + 42 * AFTER, notify=told)
if len(sent) != 2 or "עונה שוב" not in sent[1]["title"] or "חזר" in sent[1]["title"]:
    problems.append(f"its return says the check answers again, not that the link came back; got {sent[1:]}")
sent.clear()
mixed = [{"office": "hp-laptop", "label": "HP", "verdict": {"ok": False, "hop": "tunnel", "why": "x"}}]
app._alert_link_drops(slow, now=T0 + 50 * AFTER, notify=told)
app._alert_link_drops(mixed, now=T0 + 51 * AFTER, notify=told)
if len(sent) != 1 or sent[0]["level"] != "error" or "נפל" not in sent[0]["title"]:
    problems.append(f"an outage whose tunnel is dead by the time it is told is a real fall (an error); got {sent}")

# …and one told as connected whose tunnel then dies IS told as a fall, once, and its return as the link coming back
app._alert_link_drops(item(True), now=T0 + 59 * AFTER, notify=told)
sent.clear()
app._alert_link_drops(slow, now=T0 + 60 * AFTER, notify=told)
app._alert_link_drops(slow, now=T0 + 61 * AFTER, notify=told)
app._alert_link_drops(mixed, now=T0 + 62 * AFTER, notify=told)
app._alert_link_drops(mixed, now=T0 + 63 * AFTER, notify=told)
app._alert_link_drops(item(True), now=T0 + 64 * AFTER, notify=told)
if ([s["level"] for s in sent] != ["warning", "error", "info"] or "נפל" not in sent[1]["title"]
        or "חזר" not in sent[2]["title"]):
    problems.append(f"connected-but-slow, then the tunnel dies: warning, then ONE «נפל», then «חזר»; got {sent}")

print("link_alerts selftest:", "PASS" if not problems else "FAIL")
for p in problems:
    print("  -", p)
sys.exit(1 if problems else 0)
