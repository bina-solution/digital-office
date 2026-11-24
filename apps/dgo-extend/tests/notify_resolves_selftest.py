"""A link's return ENDS its outage on the board (`app._notify`, DGO-2111).

«link-up-<office>-<since>» names the «link-down-…» and «link-slow-…» rows of the same episode in `resolves` and says
`state: resolved`, so the notifications app marks them read. On vps1, 217 of 218 unread dgo-extend rows were outages
long over. Every other notice goes out as before, with no `resolves` and no `meta`.

Run inside the app's image (it imports the app): `python3 tests/notify_resolves_selftest.py` from `apps/dgo-extend`.
Exit code 0 = every check held. No notifications service is called: requests.post is replaced, and what it would
have sent is what the test reads.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ["DGO_STATE_DIR"] = tempfile.mkdtemp(prefix="notify-state-")
os.environ["DGO_TUNNEL_DIR"] = tempfile.mkdtemp(prefix="notify-tunnel-")

import app  # noqa: E402

sent, problems = [], []


class Answer:
    status_code = 201


def post(url, timeout=None, json=None):
    sent.append({"url": url, "json": json})
    return Answer()


app.requests.post = post

ok = app._notify("link-up-hp-laptop-1763600000", "הקישור ל-HP חזר", "אחרי 12 דקות שבהן לא ענתה.", "info")
body = sent[-1]["json"] if sent else {}
if not ok:
    problems.append("a 201 is a delivered notice")
if body.get("resolves") != ["link-down-hp-laptop-1763600000", "link-slow-hp-laptop-1763600000"]:
    problems.append(f"the return names the two rows of its own episode, got {body.get('resolves')!r}")
if body.get("meta") != {"state": "resolved"}:
    problems.append(f"the return says its episode is over, got {body.get('meta')!r}")
if (body.get("source"), body.get("source_id"), body.get("level")) != ("dgo-extend", "link-up-hp-laptop-1763600000",
                                                                       "info"):
    problems.append(f"the rest of the notice is as before, got {body!r}")

app._notify("link-down-hp-laptop-1763600000", "הקישור ל-HP נפל", "מאז 10:00.", "error")
body = sent[-1]["json"]
if "resolves" in body or "meta" in body:
    problems.append(f"an alarm ends nothing, got {body!r}")
app._notify("join-7", "בקשת הצטרפות", "", "info")
if "resolves" in sent[-1]["json"]:
    problems.append("a notice that is not a link's return ends nothing")

for p in problems:
    print("FAIL:", p)
print("notify_resolves_selftest:", "PASS" if not problems else f"{len(problems)} problem(s)")
sys.exit(1 if problems else 0)
