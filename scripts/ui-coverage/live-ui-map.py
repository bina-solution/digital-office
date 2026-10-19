#!/usr/bin/env python3
"""live-ui-map — render the LIVE platform through the SIMULATION's own panel list.

    python3 scripts/ui-coverage/live-ui-map.py                        # desktop, autodetect console
    python3 scripts/ui-coverage/live-ui-map.py --profile mobile
    python3 scripts/ui-coverage/live-ui-map.py --url http://127.0.0.1:8899/ --limit 5
    python3 scripts/ui-coverage/live-ui-map.py --list                 # what it would render, no browser
    python3 scripts/ui-coverage/live-ui-map.py --tiles --profile mobile   # every tile THIS office has

Out: ci-artifacts/ui-map/<profile>/NN.png — one per entry of PANELS in digital-office/sim/ui-map.py,
     numbered identically, plus render-log.json recording what each panel's action actually did —
     and any RAW VALUE the panel printed (`undefined`, `NaN`, `[object Object]`): `leaks`, also said
     beside the panel as it renders and listed at the end. So is a picture that is NOT of the app's
     own screen: a card in its place (`standin`), or an app the edge delivers while this map came in
     behind the edge (`edge`) — those panels are to be looked at through the edge, signed in.

Then, with no curation, no pair map and no way for the two sides to drift:

    python3 scripts/ui-coverage/pixel-diff.py --sim  digital-office/sim/ui-map/desktop \
                                              --live ci-artifacts/ui-map/desktop

WHY THIS EXISTS
---------------
The sim renders 43 panels to digital-office/sim/ui-map/<profile>/NN.png. `./bbox ui-map`
(scripts/ui-coverage/capture.py) renders a DIFFERENT, differently-named set of screens off
manifest.yaml — each app on its own host, its own recipe, its own name. Pairing the two therefore
needed the curated 29-entry map in pixel-diff.yaml, and 14 sim panels had no live counterpart at all.
A curated map is a judgement, and a judgement that is one row off produces a confident-looking number
about the wrong screen.

This removes the judgement. It walks the SAME list, in the SAME order, by the SAME recipe (load the
console shell, set location.hash, run the panel's action, shoot) and writes the SAME filenames. Panel
NN here and panel NN there are the same panel by construction.

NO PLAYWRIGHT — AND HOW THE PANEL LIST IS STILL THE SIM'S
----------------------------------------------------------
This repo is under a standing instruction not to drive Playwright. digital-office/sim/ui-map.py does
`from playwright.sync_api import sync_playwright` at top level, so importing it — the way
sim-live-parity.py does — would drag the banned dependency in through the back door and hard-fail on
any machine that hasn't got it.

So PANELS is read the way pixel-diff.py reads it: ast.parse over the file TEXT. That yields the label
and the module hash as literals, and the action as an AST expression — a name (`drive_grid`) or a
call (`mail_view("starred")`). Those expressions are matched against ACTIONS below, a hand-port of
the same helpers into CDP steps. The match is by NAME AND ARITY and it is CHECKED: a panel whose
action expression this file does not recognise is refused, loudly, rather than rendered without its
action — because a panel silently missing its action is not a failed panel, it is a WRONG panel that
will be diffed against the sim's correct one and produce a confident number about the wrong screen.
`--list` prints the resolution table for every panel without touching a browser, so drift in
ui-map.py shows up in one second.

HOW IT DRIVES A BROWSER: CDP OVER A RAW SOCKET
----------------------------------------------
A real Chrome, started with --remote-debugging-port, spoken to over the Chrome DevTools Protocol
through a ~90-line WebSocket client built from `socket` and `base64`. Nothing is installed; the whole
file imports only the standard library. That is the entire reason this approach was chosen over the
two alternatives:

  * `chrome --headless --screenshot=<file>` is one line and cannot run a panel's ACTION. 24 of the 43
    panels ARE an action (open the details pane, open the bulk bar, open the share dialog) — a
    screenshot-only renderer would produce the app's landing page 24 times and label them as 24
    different component surfaces. That is worse than not rendering them.
  * Playwright is banned, and would only have supplied the transport this file now has.

CDP covers exactly what PANELS needs and nothing more: Page.navigate, Runtime.evaluate (set the hash,
resolve a selector to a point), Input.dispatchMouseEvent (click it — for real, so hover, right-click
and shift-click behave), Emulation.setDeviceMetricsOverride (the view profile), Page.captureScreenshot.

Every panel gets a fresh INCOGNITO browser context, the same isolation `ui-map.py` gets from
`browser.new_context()` — otherwise an open modal, a switched INDOX instance or a theme toggle from
one panel leaks into the next shot.

WHICH CHROME, AND WHY IT MATTERS FOR THE NUMBER
-----------------------------------------------
--chrome picks the binary; the default is the first real Chrome/Chromium found. Be aware what this
does to the diff: the sim's PNGs were rendered by ONE engine, and every glyph edge of a differently
built one differs. If the sim map on disk was made by digital-office/sim/ui-map.py's CHROME
(/opt/pw-browsers/chromium-1194/chrome-linux/chrome), pointing --chrome at that same binary is what
makes "pixel-exact" mean pixel-exact; anything else puts a text-shaped floor under every panel that
no porting can remove. The launch flags below (--hide-scrollbars, --force-color-profile=srgb, …) are
the subset of Playwright's own launch arguments that visibly affect a screenshot, for the same
reason.

WHERE IT RUNS
-------------
Wherever the console is reachable. --url wins; otherwise the console container's IP is looked up with
`docker ps` exactly as sim-live-parity.py does it — deliberately the container IP and NOT
console.localhost, because the routed host is behind authentik and a capture harness must never need
an operator's password.

On this laptop Docker lives in WSL and the 172.x bridge is not routable from Windows, so the natural
place to run this is inside WSL, where the container IP resolves directly:

    wsl -d Ubuntu -- bash -lc 'cd /mnt/c/…/deployment-hacohen && python3 scripts/ui-coverage/live-ui-map.py'

From Windows instead, forward the port first (any loopback tunnel will do) and pass --url.
"""
from __future__ import annotations

import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import ast
import base64
import http.client
import json
import os
import pathlib
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SIM_UI_MAP = REPO / "digital-office" / "sim" / "ui-map.py"
PROFILES_YAML = HERE / "view-profiles.yaml"
OUT_ROOT = REPO / "ci-artifacts" / "ui-map"

# Same binary digital-office/sim/ui-map.py uses. Tried first when it exists, because a diff between
# two different Chromium builds is mostly a diff of font rasterisation.
SIM_CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CHROME_CANDIDATES = [
    SIM_CHROME,
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

# The sim's own settle times, copied rather than invented: two captures of the same screen taken at
# different points in its animation are a difference this tool would then report as a port gap.
WAIT_AFTER_LOAD = 400
WAIT_AFTER_HASH = 2600
WAIT_AFTER_ACTION = 1200
#: The raw values a screen prints when a field it reads is not what its data gives — read from the
#: page and every same-origin frame that is DRAWN, each with a little of the line around it (at most
#: five). A frame that is not drawn (another screen's, kept alive) answers `innerText` with its whole
#: `textContent`, inline scripts included, and every `!== undefined` in them would read as a value.
LEAKS_JS = r"""(() => {
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {
    if (!f.getClientRects().length) continue;
    try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) { /* another origin */ }
  }
  const seen = new Set();
  for (const d of docs) {
    const text = (d.body && d.body.innerText) || '';
    for (const m of text.matchAll(/[^\n]{0,24}(?:\bundefined\b|\bNaN\b|\[object Object\])[^\n]{0,24}/g)) seen.add(m[0].trim());
  }
  return [...seen].slice(0, 5);
})()"""
#: STILL DRAWING — placeholders a screen shows while its first answer is on the way (skeleton bars,
#: an element that says it is busy, a line that says «טוען…»). Network quiet does not mean drawn: the
#: data screen polls a seven-second sweep every 1.2 s, so there is a quiet half-second long before
#: there is a screen, and on 2026-10-07 its panel was a picture of grey bars at all three sizes.
#: The rule itself — what a placeholder is, how long a screen may take, when the camera gives up —
#: is drawn.py's, shared with the simulation's map and its flow suites: one rule, asked from the
#: moment a tile opens, and its answer (the time to drawn) written beside the picture.
sys.path.insert(0, str(HERE))
import drawn  # noqa: E402
#: A CARD STANDING WHERE THE APP'S SCREEN SHOULD BE — the shell's own notice (not shown from this
#: address, this office is not answering) or the console's card inside the frame (the app answered
#: with no screen). The picture is then of the card; this reads its line so the map can say so.
STANDIN_JS = r"""(() => {
  const line = el => ((el && el.innerText) || '').trim().split('\n')[0].slice(0, 70);
  const xn = [...document.querySelectorAll('.xn-card')].find(c => c.offsetParent);
  if (xn) return line(xn.querySelector('.xn-sub')) || line(xn);
  for (const f of document.querySelectorAll('iframe')) {
    try {
      const d = f.contentDocument;
      if (d && d.documentElement.hasAttribute('data-card')) return line(d.querySelector('p')) || d.title;
    } catch (e) { /* another origin */ }
  }
  return null;
})()"""
#: NOT THE SHELL — what the page at the console's address IS when it is not the console (its title),
#: or '' when it is. Every panel is opened IN the shell: the map sets `location.hash` there and
#: photographs what stands. On a page that is something else — a first-install wizard served at `/`,
#: a sign-in page, an error page — it set a hash nobody read and photographed that page once per
#: panel, each "drawn" in no time: 2026-10-09, a running office whose entry had become its install
#: wizard read as a healthy tile, and only the picture said otherwise. So the map looks before it
#: opens anything, and photographs nothing there.
NOT_THE_SHELL_JS = r"""(() => document.querySelector('#nav') && document.querySelector('#content') ? ''
  : (document.title.trim() || location.pathname || 'a page with no title'))()"""


class NotTheShell(Exception):
    pass


def edge_delivered():
    """{mount: [paths]} — what each app's manifest says the EDGE hands straight to the app
    (`routing[].module.passthrough`), keyed by the tile's mount (`/a/<alias>/`).

    This map reaches the console behind the edge (its container's own address, so that no sign-in
    stands in the way) and therefore never travels those paths: an app the edge delivers whole
    answers a caller it does not know, and one whose live channel is a passed-through websocket
    draws its frame and then fails to connect. Both are true pictures of the wrong road, and the
    map names them instead of filing them as that app's screen."""
    out = {}
    for f in sorted(REPO.glob("apps/*/app.json")) + sorted(REPO.glob("platform-base/*/app.json")):
        try:
            routes = json.loads(f.read_text(encoding="utf-8")).get("routing") or []
        except ValueError:
            continue
        for r in routes:
            m = r.get("module") or {}
            if m.get("alias") and m.get("passthrough"):
                out[f"/a/{m['alias']}/"] = [x.get("path") or "/" for x in m["passthrough"]]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PANELS — parsed out of the sim, never imported (see the header)
# ─────────────────────────────────────────────────────────────────────────────
def parse_panels():
    """[(label, module_hash, action_expr_or_None)] where action_expr is ('name', *literal_args).

    A lambda argument (panel 07's `drive_place("mydrive", lambda …)`) cannot be evaluated here, so it
    is surfaced as the marker '<lambda>' and ACTIONS has to name it explicitly. That is the point:
    an unported lambda must fail resolution rather than quietly degrade to `drive_place("mydrive")`,
    which is a DIFFERENT panel that already exists at index 06.
    """
    tree = ast.parse(SIM_UI_MAP.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "PANELS" for t in node.targets):
            continue
        out = []
        for el in getattr(node.value, "elts", []):
            parts = getattr(el, "elts", [])
            label = parts[0].value if parts and isinstance(parts[0], ast.Constant) else ""
            mod = parts[1].value if len(parts) > 1 and isinstance(parts[1], ast.Constant) else ""
            act = parts[2] if len(parts) > 2 else None
            out.append((str(label), str(mod), describe_action(act)))
        return out
    raise SystemExit(f"no PANELS list found in {SIM_UI_MAP}")


def describe_action(node):
    """AST -> ('func', *args) | None. Unknown shapes come back as ('?', <dump>) and fail resolution."""
    if node is None or (isinstance(node, ast.Constant) and node.value is None):
        return None
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = []
        for a in node.args:
            if isinstance(a, ast.Constant):
                args.append(a.value)
            elif isinstance(a, ast.Lambda):
                args.append("<lambda>")
            else:
                args.append("<expr>")
        return (node.func.id, *args)
    return ("?", ast.dump(node)[:80])


# ─────────────────────────────────────────────────────────────────────────────
# the ported actions
# ─────────────────────────────────────────────────────────────────────────────
# Each action is a list of STEPS run in order. A step is a dict; the runner understands:
#
#   sel        CSS selector to act on                scope   'frame' (default) | 'top'
#   text       element's text must contain this      nth     which match (default 0)
#   act        'click' (default) | 'hover' | 'fill' | 'open_side' | 'first_row' | 'noop'
#   button     'right' for a context click           mods    ['Shift'] etc.
#   value      for 'fill'
#   unless     skip this step if this selector already matches something visible
#   wait       ms to wait AFTER the step             optional  a miss is not a failure
#
# The vocabulary is small on purpose. Everything in ui-map.py's helpers is a selector click with a
# wait; anything that needed more than that would be a behaviour the sim panel is not describing.
def rail(sel, wait=0, **kw):
    """ui-map.py's rail_click: open the drawer first on the profiles that hide the rail behind one."""
    return [{"act": "open_side"}, {"sel": sel, "wait": wait, **kw}]


def drive_place(place, then=None):
    return rail(f'[data-place="{place}"]', wait=900) + (then or [])


def mail_view(view):
    steps = []
    if view in ("important", "all", "spam", "trash"):
        steps += rail("#sideNav .bnv-more", wait=400)
    return steps + rail(f'#sideNav [data-bnv-id="{view}"]', wait=1100)


def mail_gear(to, section=None):
    steps = rail('#sideNav [data-bnv-id="settings"]', wait=400) + [{"sel": f'#gearMenu [data-go="{to}"]', "wait": 1500}]
    return steps + ([{"sel": f'#setTabs [data-sec="{section}"]', "wait": 1500}] if section else [])


def indox_tab(name):
    # the shared side menu's row — the .tabstrip this used to click is not in the DOM any more
    return [{"sel": ".side.bnv .bnv-item", "text": name, "wait": 1800}]


# `_open_switcher` in the sim clicks `.dosw-top .dosw-btn` — the in-app account switcher from
# sim/overlay/switcher.js. That control was deliberately superseded live: C15 moved it into the
# CONSOLE's top bar (#acctChip), which is why sim-live-parity.py excludes every `dosw-*` token from
# the missing count. The selector is kept as the sim writes it and marked optional-scope 'top', so
# these panels render whatever live actually shows and are REPORTED as action-failed rather than
# silently passed off as the switcher screen.
SWITCHER = [{"sel": ".dosw-top .dosw-btn", "scope": "top", "wait": 700}]

ACTIONS = {
    ("open_first_row",): [{"act": "first_row"}],

    ("drive_grid",): rail('[data-place="mydrive"]', wait=800) + [{"sel": "#btnGrid", "wait": 700}],
    ("drive_details",): rail('[data-place="mydrive"]', wait=800) + [
        {"sel": "tr[data-id]", "wait": 400},
        # Open the pane only if selecting the row did not already open it — below 1120px it is a
        # fixed overlay, and opening it first would put it between the pointer and the row.
        {"sel": "#btnInfo", "unless": "#details:not(.hidden)", "wait": 500},
    ],
    ("drive_filter",): rail('[data-place="recent"]', wait=800) + [
        {"sel": '[data-chip="type"]', "wait": 500}],
    ("drive_preview",): rail('[data-place="recent"]', wait=900) + [
        {"sel": "tr[data-id] .name-open", "wait": 900}],
    # Through the row's MENU, the way every device has: the hover button this used to click is not
    # drawn where there is no hover (a finger), so the phone and tablet maps had no share dialog.
    ("drive_share",): rail('[data-place="recent"]', wait=900) + [
        {"sel": "tr[data-id]", "button": "right", "wait": 500},
        {"sel": 'button[data-c="share"]', "wait": 800}],
    ("drive_context",): rail('[data-place="recent"]', wait=900) + [
        {"sel": "tr[data-id]", "button": "right", "wait": 600}],
    ("drive_bulk",): rail('[data-place="recent"]', wait=900) + [
        {"sel": "tr[data-id]", "nth": 0, "wait": 200},
        {"sel": "tr[data-id]", "nth": 3, "mods": ["Shift"], "wait": 600}],

    ("mail_selmenu",): [{"sel": "#gmAllCaret", "wait": 500}],
    ("mail_bulk",): [{"sel": "#gmAllCaret", "wait": 300},
                     {"sel": '[data-sel="starred"]', "wait": 700}],
    ("mail_undo",): [{"sel": "#gmAllCaret", "wait": 300},
                     {"sel": '[data-sel="starred"]', "wait": 400},
                     {"sel": '[data-bulk="archive"]', "wait": 700}],
    ("mail_compose",): rail("#sideNav .bnv-primary", wait=700),

    ("indox_switcher",): SWITCHER,
    ("indox_details",): SWITCHER + [{"sel": ".dosw-menu .dosw-health", "scope": "top", "wait": 1200}],
    ("indox_new_instance",): SWITCHER + [
        {"sel": ".dosw-menu .dosw-add", "scope": "top", "wait": 900},
        {"sel": "#ni-label", "act": "fill", "value": "חברה חדשה"},
        {"sel": ".dosw-mod [data-go]", "wait": 700},
        {"sel": ".dosw-mod [data-go]", "wait": 900}],
    ("indox_sync_items",): indox_tab("סנכרון") + [
        {"sel": ".statelegend .li-btn", "wait": 1400}],
    ("indox_sync_editor",): indox_tab("סנכרון") + [
        {"sel": "button", "text": "+ מקור סנכרון חדש", "wait": 1100},
        {"sel": ".drawer-body input[type=radio]", "wait": 400},
        {"sel": ".drawer-foot button", "text": "המשך", "wait": 1400}],
}

# Parameterised helpers, resolved by (name, arity). Kept separate from the table above so that adding
# a `drive_place("archive")` panel to the sim needs no edit here at all.
PARAM_ACTIONS = {
    ("drive_place", 1): lambda place: drive_place(place),
    # The one lambda in PANELS: open my-drive, then open the first folder to show the breadcrumb.
    ("drive_place", 2): lambda place, lam: drive_place(
        place, [{"sel": "[data-folder]", "wait": 900}]),
    ("mail_view", 1): lambda v: mail_view(v),
    ("mail_gear", 1): lambda to: mail_gear(to),
    ("mail_gear", 2): lambda to, section: mail_gear(to, section),
    ("indox_tab", 1): lambda name: indox_tab(name),
}


def resolve(spec):
    """('drive_place','recent') -> [steps]. Raises on anything this file has not been taught."""
    if spec is None:
        return []
    if spec in ACTIONS:
        return ACTIONS[spec]
    key = (spec[0], len(spec) - 1)
    if key in PARAM_ACTIONS:
        return PARAM_ACTIONS[key](*spec[1:])
    raise KeyError(spec)


# ─────────────────────────────────────────────────────────────────────────────
# a WebSocket client, because CDP speaks one and nothing here may be installed
# ─────────────────────────────────────────────────────────────────────────────
class WS:
    """RFC6455 text-frame client: connect, send, recv. No extensions, no fragmentation on send.

    Server frames ARE fragmented and ARE large — a 1440x900 PNG comes back as a couple of megabytes
    of base64 in one message — so the read path handles 16- and 64-bit lengths and continuation
    frames, and answers pings. That is the whole protocol surface CDP uses.
    """

    def __init__(self, url, timeout=90):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        self.sock.settimeout(timeout)
        path = u.path + (("?" + u.query) if u.query else "")
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake: connection closed")
            buf += chunk
        head, rest = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise RuntimeError("websocket handshake failed: " + head[:200].decode("latin1"))
        self.buf = bytearray(rest)

    def ready(self, timeout):
        """Is a message waiting? Asked with select() BEFORE any byte of a frame is consumed.

        This is the only safe way to read with a short deadline: timing out half way through a frame
        would leave a header consumed and the stream permanently out of step, which shows up much
        later as a nonsense parse error in an unrelated command.
        """
        if self.buf:
            return True
        return bool(select.select([self.sock], [], [], timeout)[0])

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise RuntimeError("websocket closed by peer")
            self.buf += chunk
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    def send(self, text: str):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        n = len(payload)
        hdr = b"\x81" + (bytes([0x80 | n]) if n < 126 else
                         b"\xfe" + struct.pack(">H", n) if n < 65536 else
                         b"\xff" + struct.pack(">Q", n))
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def recv(self) -> str:
        data = b""
        while True:
            b0, b1 = self._read(2)
            fin, opcode, ln = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read(8))[0]
            if b1 & 0x80:                                   # server frames are never masked
                self._read(4)
            payload = self._read(ln) if ln else b""
            if opcode == 0x9:                               # ping -> pong, then keep reading
                self.sock.sendall(b"\x8a\x80" + os.urandom(4))
                continue
            if opcode == 0x8:
                raise RuntimeError("websocket closed by peer")
            if opcode == 0xA:
                continue
            data += payload
            if fin:
                return data.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.sendall(b"\x88\x80" + os.urandom(4))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    """One WebSocket, request/response by id. Events that arrive in between are kept, not dropped —
    Page.loadEventFired is an event and arrives interleaved with command replies."""

    def __init__(self, url, timeout=90):
        self.ws = WS(url, timeout)
        self.n = 0
        self.timeout = timeout
        self.events = []

    def drain(self):
        """Hand back the events that arrived while commands were being answered."""
        got, self.events = self.events, []
        return got

    def pump(self, seconds):
        """Read events for a while without sending anything. Used to watch the network go quiet."""
        end = time.time() + seconds
        got = []
        while time.time() < end:
            if not self.ws.ready(min(0.1, max(0.01, end - time.time()))):
                continue
            try:
                msg = json.loads(self.ws.recv())
            except (RuntimeError, OSError, ValueError):
                break
            if "method" in msg:
                got.append(msg)
        return got

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def wait_event(self, method, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            for i, e in enumerate(self.events):
                if e.get("method") == method:
                    return self.events.pop(i)
            self.ws.sock.settimeout(max(0.2, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except (socket.timeout, TimeoutError):
                break
            except RuntimeError:
                break
            finally:
                self.ws.sock.settimeout(self.timeout)
            if "method" in msg:
                if msg["method"] == method:
                    return msg
                self.events.append(msg)
        return None

    def close(self):
        self.ws.close()


# ─────────────────────────────────────────────────────────────────────────────
# the page-side helper
# ─────────────────────────────────────────────────────────────────────────────
# Injected into the CONSOLE document once per panel. It only ever RESOLVES elements to a point in
# top-page coordinates — the clicking itself is done by CDP's Input domain, so hover states,
# right-click menus and shift-range-selection behave exactly as they do under a hand.
#
# Reaching into the iframe from the top document is legitimate here and not a trick: the console
# proxies each app same-origin at /a/<name>/ precisely so the shell can embed it (see the comment at
# platform-base/console/static/app.js:345 — cross-origin embedding of an SSO-gated app is X-Frame
# blocked, so anything in the frame is same-origin by construction).
HELPER = r"""
window.__uimap = {
  doc(scope) {
    if (scope === 'top') return document;
    const f = document.getElementById('frame');
    if (!f) throw new Error('no #frame in the console shell');
    const d = f.contentDocument || (f.contentWindow && f.contentWindow.document);
    if (!d) throw new Error('#frame is not readable (cross-origin?)');
    return d;
  },
  off(scope) {
    if (scope === 'top') return {x: 0, y: 0};
    const r = document.getElementById('frame').getBoundingClientRect();
    return {x: r.left, y: r.top};
  },
  vis(el) { return !!(el && el.getClientRects && el.getClientRects().length); },
  all(scope, sel) { return Array.prototype.slice.call(this.doc(scope).querySelectorAll(sel)); },
  find(scope, sel, text, nth) {
    let els = this.all(scope, sel).filter(e => this.vis(e));
    if (text) els = els.filter(e => (e.textContent || '').indexOf(text) >= 0);
    return els[nth || 0] || null;
  },
  point(scope, el) {
    if (!el) return null;
    try { el.scrollIntoView({block: 'center', inline: 'center'}); } catch (e) {}
    const r = el.getBoundingClientRect(), o = this.off(scope);
    if (!r.width && !r.height) return null;
    return {x: o.x + r.left + r.width / 2, y: o.y + r.top + r.height / 2};
  },
  rect(scope, sel, text, nth) { return this.point(scope, this.find(scope, sel, text, nth)); },
  present(scope, sel) { try { return !!this.find(scope, sel, null, 0); } catch (e) { return false; } },

  // ui-map.py's open_side. is_visible() is NOT the test — an element inside a translated-off-screen
  // drawer still has a box; the only reliable signal is the drawer's own open state.
  side() {
    const d = this.doc('frame');
    const tog = this.find('frame', '#sideToggle');
    if (tog) return d.querySelector('aside.side.open') ? null : this.point('frame', tog);
    // the office's side menu (BinaNav — the mail's): its own button, `is-open` on the menu itself
    const nav = this.find('frame', '#navToggle');
    if (nav) return d.querySelector('#sideNav.is-open') ? null : this.point('frame', nav);
    return null;
  },

  // ui-map.py's open_first_row, same selector order and same heuristic: skip date-group separator
  // rows by requiring a HH:MM, a shekel sign, or simply enough text to be a real row.
  firstRow() {
    const sels = ['.gm-row[data-id]', 'table tbody tr', '.msg', '.row', '.card',
                  'li[role=option]', '.doc', '.item'];
    for (const sel of sels) {
      const rows = this.all('frame', sel).filter(e => this.vis(e));
      for (const r of rows.slice(0, 12)) {
        const t = r.innerText || '';
        if (/\d{1,2}:\d{2}/.test(t) || t.indexOf('\u20aa') >= 0 || t.length > 40) {
          const tgt = r.querySelector('.gm-sub, .name-open');
          return this.point('frame', tgt || r);
        }
      }
      if (rows.length) return this.point('frame', rows[0]);
    }
    return null;
  },

  fill(scope, sel, value) {
    const el = this.find(scope, sel, null, 0);
    if (!el) return false;
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
};
1
"""

MODIFIER_BITS = {"Alt": 1, "Control": 2, "Ctrl": 2, "Meta": 4, "Shift": 8}


# ─────────────────────────────────────────────────────────────────────────────
# browser lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def find_chrome(explicit):
    if explicit:
        if not pathlib.Path(explicit).exists() and not shutil.which(explicit):
            sys.exit(f"--chrome {explicit!r} not found")
        return explicit
    for c in CHROME_CANDIDATES:
        if pathlib.Path(c).exists():
            return c
    for c in ("google-chrome", "chromium", "chrome"):
        w = shutil.which(c)
        if w:
            return w
    sys.exit("no Chrome/Chromium found — pass --chrome /path/to/chrome")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def launch(chrome, port, profile, headed):
    """Start Chrome with the debugging port open and wait for it to answer.

    The flag list is small and every entry is here for a reason a screenshot can show:
    --hide-scrollbars and --force-color-profile=srgb are what Playwright itself passes (a visible
    scrollbar or a colour-managed profile changes real pixels), and the rest keep a first-run bubble,
    an update ping or a translate bar out of the frame.
    """
    tmp = tempfile.mkdtemp(prefix="live-ui-map-")
    args = [chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={tmp}",
            "--no-first-run", "--no-default-browser-check", "--no-sandbox",
            "--disable-background-networking", "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding", "--disable-extensions",
            "--disable-component-update", "--disable-default-apps", "--disable-sync",
            "--disable-translate", "--metrics-recording-only", "--mute-audio",
            "--hide-scrollbars", "--force-color-profile=srgb",
            f"--window-size={profile['width']},{profile['height']}",
            # A profile also says what the person POINTS with. A headless browser has no pointing
            # device, so `(hover: none)` matched on the desktop profile too: a page that gives a
            # hover-only column back to a finger gave it back to the desktop map, which then could
            # not find the button it clicks («no visible button[data-act="share"]», 2026-10-06).
            # Blink's own setting (the one Playwright passes); CDP cannot emulate these features.
            "--blink-settings=" + ("primaryHoverType=1,availableHoverTypes=1,primaryPointerType=2,availablePointerTypes=2"
                                    if profile.get("has_touch") else
                                    "primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4"),
            "about:blank"]
    if not headed:
        args.insert(1, "--headless=new")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 40
    while time.time() < end:
        if proc.poll() is not None:
            sys.exit(f"chrome exited immediately (code {proc.returncode}) — try --headed or --chrome")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return proc, tmp, json.loads(r.read().decode())["webSocketDebuggerUrl"]
        except (OSError, ValueError, KeyError, http.client.HTTPException):   # it is simply not up yet
            time.sleep(0.25)
    proc.kill()
    sys.exit(f"chrome never opened the debugging port {port}")


def console_url():
    """The console container's IP:8000 — console.localhost is behind authentik and a capture harness
    must not need a password. WHICH container is one rule for every tool that looks at a running
    office (scripts/refactor/office_browser.py: the compose service of THIS checkout)."""
    _sys.path.insert(0, str(REPO / "scripts" / "refactor"))
    import office_browser
    return office_browser.url("console", 8000, False)


# ─────────────────────────────────────────────────────────────────────────────
# one panel
# ─────────────────────────────────────────────────────────────────────────────
class Panel:
    """A fresh incognito context + tab, driven and then thrown away."""

    def __init__(self, browser, dbg_base, profile, timeout):
        self.browser, self.dbg, self.prof, self.timeout = browser, dbg_base, profile, timeout
        self.ctx = browser.call("Target.createBrowserContext")["browserContextId"]
        self.target = browser.call("Target.createTarget", url="about:blank",
                                   browserContextId=self.ctx)["targetId"]
        self.page = CDP(f"{dbg_base}/devtools/page/{self.target}", timeout)
        self.inflight = set()
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Network.enable")
        self.page.call("Emulation.setDeviceMetricsOverride",
                       width=profile["width"], height=profile["height"],
                       deviceScaleFactor=profile.get("dsf", 1),
                       mobile=bool(profile.get("is_mobile", False)))
        if profile.get("has_touch"):
            self.page.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

    def close(self):
        try:
            self.page.close()
        finally:
            try:
                self.browser.call("Target.closeTarget", targetId=self.target)
                self.browser.call("Target.disposeBrowserContext", browserContextId=self.ctx)
            except RuntimeError:
                pass

    # ── primitives ──────────────────────────────────────────────────────────
    def js(self, expr, silent=False):
        r = self.page.call("Runtime.evaluate", expression=expr, returnByValue=True,
                           awaitPromise=True)
        if r.get("exceptionDetails"):
            if silent:
                return None
            exc = r["exceptionDetails"]
            msg = (exc.get("exception") or {}).get("description") or exc.get("text") or "JS error"
            raise RuntimeError(str(msg).split("\n")[0][:160])
        return r.get("result", {}).get("value")

    def sleep(self, ms):
        if ms > 0:
            time.sleep(ms / 1000.0)

    def goto(self, url):
        self.page.call("Page.navigate", url=url)
        self.page.wait_event("Page.loadEventFired", timeout=self.timeout)

    def _net(self, events):
        for e in events:
            m, p = e.get("method"), e.get("params", {})
            if m == "Network.requestWillBeSent":
                self.inflight.add(p.get("requestId"))
            elif m in ("Network.loadingFinished", "Network.loadingFailed",
                       "Network.requestServedFromCache"):
                self.inflight.discard(p.get("requestId"))

    def wait_idle(self, quiet_ms=400, max_ms=6000):
        """Wait for the frame to stop fetching — up to a cap, then give up quietly.

        THE difference between rendering the sim and rendering live. The sim reads its fixtures out
        of one local file, so ui-map.py's fixed 2600ms is always enough. Live, the same screen is a
        console shell that fetches /api/modules, then an embedded app that fetches its own listing
        over the docker bridge, and on a laptop that is routinely slower than 2600ms — which does not
        fail, it silently screenshots a spinner and calls it the panel. (Measured: drive's details
        pane and the mail message panel both missed their row that way on the first run.)

        Deliberately CAPPED and deliberately not fatal: several surfaces here hold a connection open
        on purpose (the INDOX live sync state, any-concurrency's timeline), so "no request in flight"
        will never come true for them and waiting forever would hang the run. After the cap we carry
        on and the sim's own fixed wait still applies on top, so the settle point stays comparable.
        """
        self._net(self.page.drain())
        end = time.time() + max_ms / 1000.0
        quiet_since = time.time()
        while time.time() < end:
            self._net(self.page.pump(0.12))
            if self.inflight:
                quiet_since = time.time()
            elif time.time() - quiet_since >= quiet_ms / 1000.0:
                return True
        return False

    def settle(self, ms):
        """Let live finish fetching, THEN wait the sim's own animation time on top."""
        self.wait_idle()
        self.sleep(ms)

    def until_drawn(self, since=None, at_least_ms=0, cap_ms=drawn.CAP_MS):
        """Ask the shared rule until this screen is drawn, or the camera's patience ends (drawn.py).
        With `since` (when the tile was opened) the answer carries the screen's time to drawn; a
        screen that never finished within the cap is a finding the caller records, not a pass."""
        return drawn.wait(lambda js: self.js(js, silent=True), self.sleep, since=since,
                          at_least_ms=at_least_ms, cap_ms=cap_ms)

    def mouse(self, x, y, button="left", mods=(), clicks=1):
        bits = 0
        for m in mods:
            bits |= MODIFIER_BITS.get(m, 0)
        common = dict(x=x, y=y, button=button, modifiers=bits, clickCount=clicks,
                      buttons=1 if button == "left" else 2)
        self.page.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, modifiers=bits)
        self.page.call("Input.dispatchMouseEvent", type="mousePressed", **common)
        self.page.call("Input.dispatchMouseEvent", type="mouseReleased", **common)

    def hover(self, x, y):
        self.page.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, modifiers=0)

    # ── steps ───────────────────────────────────────────────────────────────
    def step(self, s):
        """Run one step. Returns a short string for the log; raises on a required miss."""
        scope = s.get("scope", "frame")
        act = s.get("act", "click")
        self.js(HELPER)                       # cheap, and the frame may have reloaded under us

        if act == "open_side":
            pt = self.js("JSON.stringify(window.__uimap.side()||null)", silent=True)
            pt = json.loads(pt) if pt else None
            if pt:
                self.mouse(pt["x"], pt["y"])
                self.settle(450)
                return "open_side"
            return "open_side(not needed)"

        if act == "first_row":
            pt = self.js("JSON.stringify(window.__uimap.firstRow()||null)")
            pt = json.loads(pt) if pt else None
            if not pt:
                raise RuntimeError("no first row found")
            self.mouse(pt["x"], pt["y"])
            self.settle(s.get("wait", 0))
            return "first_row"

        if s.get("unless") and self.js(
                f"window.__uimap.present({json.dumps(scope)},{json.dumps(s['unless'])})", silent=True):
            return f"skip {s['sel']} (already {s['unless']})"

        if act == "fill":
            ok = self.js(f"window.__uimap.fill({json.dumps(scope)},{json.dumps(s['sel'])},"
                         f"{json.dumps(s['value'])})")
            if not ok:
                raise RuntimeError(f"fill: no {s['sel']}")
            self.settle(s.get("wait", 0))
            return f"fill {s['sel']}"

        q = (f"JSON.stringify(window.__uimap.rect({json.dumps(scope)},{json.dumps(s['sel'])},"
             f"{json.dumps(s.get('text'))},{int(s.get('nth', 0))})||null)")
        pt = self.js(q)
        pt = json.loads(pt) if pt else None
        if not pt:
            # The index is part of the message on purpose: `tr[data-id]` nth=3 failing means live has
            # FEWER rows than the panel needs, which is a completely different finding from the
            # selector not existing at all, and the two are indistinguishable without it.
            raise RuntimeError(f"no visible {s['sel']}"
                               + (f"[{s['nth']}]" if s.get("nth") else "")
                               + (f" with text {s['text']!r}" if s.get("text") else ""))
        if act == "hover":
            self.hover(pt["x"], pt["y"])
        else:
            self.mouse(pt["x"], pt["y"], button=s.get("button", "left"), mods=s.get("mods", ()))
        self.settle(s.get("wait", 0))
        return f"{act} {s['sel']}" + (f"[{s['text']}]" if s.get("text") else "")

    def shot(self, path):
        data = self.page.call("Page.captureScreenshot", format="png",
                              captureBeyondViewport=False)["data"]
        path.write_bytes(base64.b64decode(data))


# ─────────────────────────────────────────────────────────────────────────────
def load_profiles():
    try:
        import yaml
        doc = yaml.safe_load(PROFILES_YAML.read_text(encoding="utf-8"))
        return doc["profiles"], doc.get("default", "desktop")
    except Exception as e:                                   # noqa: BLE001
        print(f"! could not read {PROFILES_YAML} ({e}); using the built-in desktop profile")
        return ({"desktop": {"label": "Desktop · 1440×900", "width": 1440, "height": 900,
                             "dsf": 1, "is_mobile": False, "has_touch": False}}, "desktop")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    profiles, default = load_profiles()
    ap.add_argument("--profile", choices=sorted(profiles), default=default)
    ap.add_argument("--url", help="live console base URL (default: the console container's IP:8000)")
    ap.add_argument("--out", type=pathlib.Path, help="default ci-artifacts/ui-map/<profile>")
    ap.add_argument("--chrome", help="browser binary (default: the first Chrome/Chromium found; "
                                     "point it at the sim's own build for a like-for-like diff)")
    ap.add_argument("--headed", action="store_true", help="show the window instead of --headless=new")
    ap.add_argument("--only", help="panel indices, e.g. 0,4,19-23")
    ap.add_argument("--limit", type=int, help="first N panels")
    ap.add_argument("--settle", type=float, default=1.0,
                    help="multiply every wait — live fetches real data and can need 1.5–2")
    ap.add_argument("--timeout", type=int, default=45, help="seconds for one navigation")
    ap.add_argument("--list", action="store_true",
                    help="print the panel/action resolution table and exit (no browser)")
    ap.add_argument("--skip-failed-actions", action="store_true",
                    help="write no PNG for a panel whose action failed, so pixel-diff reports it "
                         "UNPAIRED instead of diffing the screen it fell back to")
    ap.add_argument("--tiles", action="store_true",
                    help="render every tile of THIS office's own registry (what its console answers "
                         "at /api/modules) instead of the simulation's panels: the office as it is — "
                         "an office runs apps the simulation has no panel for, and lacks some it has. "
                         "Out: ci-artifacts/ui-map/<profile>-tiles")
    a = ap.parse_args()

    url = a.url or console_url()
    tiles = []
    if url:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/api/modules", timeout=30) as r:
                tiles = json.loads(r.read().decode("utf-8"))["modules"]
        except (OSError, ValueError, KeyError):
            tiles = []
    if a.tiles:
        if not tiles:
            sys.exit("--tiles asks the live console for its tiles, and none is reachable — pass --url.")
        panels = [(f"{m.get('name') or m['id']} ({m['id']})", "#/m/" + m["id"], None) for m in tiles]
    else:
        panels = parse_panels()
    # Behind the edge (no --url: the console's own address), what the edge delivers is not on this road.
    behind = {} if a.url else edge_delivered()
    edge_of = {"#/m/" + m["id"]: behind[m["embed"]] for m in tiles if m.get("embed") in behind}

    # Resolve EVERY action before opening a browser. A panel this file cannot drive must stop the run
    # here, where the message is 'teach me this action', not 40 panels later as a wrong picture.
    resolved, unknown = [], []
    for i, (label, mod, spec) in enumerate(panels):
        try:
            resolved.append(resolve(spec))
        except KeyError:
            resolved.append(None)
            unknown.append((i, label, spec))

    if a.list or unknown:
        print(f"{len(panels)} panels from {rel(SIM_UI_MAP)}\n")
        for i, ((label, mod, spec), steps) in enumerate(zip(panels, resolved)):
            how = "—" if spec is None else (
                "UNKNOWN ACTION" if steps is None else
                f"{spec[0]}(" + ", ".join(str(x) for x in spec[1:]) + ")")
            print(f"  {i:02d}  {mod:<16} {how:<34} {label[:44]}")
        if unknown:
            print(f"\n! {len(unknown)} panel(s) use an action this renderer has not been taught:")
            for i, label, spec in unknown:
                print(f"    {i:02d}  {spec}   {label[:50]}")
            print("  Add it to ACTIONS/PARAM_ACTIONS in this file. Refusing to render a panel "
                  "without its action:\n  it would be a different screen wearing the right number.")
            return 2
        return 0

    prof = profiles[a.profile]
    out = a.out or (OUT_ROOT / (a.profile + ("-tiles" if a.tiles else "")))
    out.mkdir(parents=True, exist_ok=True)

    if not url:
        sys.exit("no live console reachable (docker not visible from here?) — pass --url.\n"
                 "  From Windows the 172.x bridge is not routable: forward the port from WSL first, "
                 "then --url http://127.0.0.1:<port>/")

    want = set(range(len(panels)))
    if a.only:
        want = set()
        for part in a.only.split(","):
            if "-" in part:
                lo, hi = part.split("-")
                want |= set(range(int(lo), int(hi) + 1))
            elif part.strip():
                want.add(int(part))
    if a.limit:
        want = {i for i in want if i < a.limit}

    chrome = find_chrome(a.chrome)
    port = free_port()
    print(f"══ live-ui-map   profile {a.profile} ({prof['width']}x{prof['height']} @{prof.get('dsf',1)}x)")
    print(f"   console : {url}")
    print(f"   chrome  : {chrome}")
    print(f"   out     : {rel(out)}\n")
    proc, tmpdir, ws_url = launch(chrome, port, prof, a.headed)
    dbg_base = f"ws://127.0.0.1:{port}"
    browser = CDP(ws_url, timeout=a.timeout + 60)

    log, failed, ok, not_shell = [], [], 0, None
    try:
        for i, (label, mod, spec) in enumerate(panels):
            if i not in want:
                continue
            rec = {"index": i, "label": label, "module": mod,
                   "action": None if spec is None else list(spec),
                   "steps": [], "action_ok": True, "reason": None, "file": None}
            p = None
            try:
                p = Panel(browser, dbg_base, prof, a.timeout)
                p.goto(url)
                p.settle(WAIT_AFTER_LOAD * a.settle)
                other = p.js(NOT_THE_SHELL_JS, silent=True)
                if other:
                    raise NotTheShell(other)
                t0 = time.monotonic()
                p.js(f"location.hash = {json.dumps(mod)}")
                # The rule is asked from the moment the tile opens (the fixed time is the shell's
                # own animation, as in the sim) — then the wire, capped, as before.
                opened = p.until_drawn(since=t0, at_least_ms=WAIT_AFTER_HASH * a.settle)
                p.wait_idle()
                for s in resolved[i]:
                    st = dict(s)
                    st["wait"] = int(st.get("wait", 0) * a.settle)
                    try:
                        rec["steps"].append(p.step(st))
                    except RuntimeError as e:
                        # Exactly the sim's contract: an action that fails is a FINDING, not a crash.
                        # Live it means the surface this panel is named for is not reachable there.
                        rec["action_ok"] = False
                        rec["reason"] = str(e)[:160]
                        rec["steps"].append(f"FAILED: {str(e)[:80]}")
                        break
                if resolved[i]:
                    p.settle(WAIT_AFTER_ACTION * a.settle)
                # …and before the shutter: what the action opened has to be drawn too. `busy` is a
                # picture of a screen that never finished; `slow` is a screen that did, too late.
                # (A tile that never finished opening has had the camera's patience once already.)
                shown = p.until_drawn(cap_ms=drawn.CAP_MS if opened["drawn"] else 1000)
                rec["drawn_ms"] = opened["ms"] if opened["drawn"] else None
                rec["slow"] = drawn.said(opened) if opened["slow"] and opened["drawn"] else None
                rec["busy"] = 0 if shown["drawn"] else (shown["loading"] or 1)
                rec["busy_what"] = [] if shown["drawn"] else shown["what"]
                # A RAW VALUE ON THE SCREEN is read, not hoped to be noticed in a picture. On
                # 2026-10-06 the machine screen printed "undefined" three times for half a day — a
                # key renamed under it — and the map photographed it three times in three sizes.
                rec["leaks"] = p.js(LEAKS_JS, silent=True) or []
                # …and so is a picture that is not of the app: a card in its place, or an app whose
                # road is the edge's while this map came in behind it.
                rec["standin"] = p.js(STANDIN_JS, silent=True) or None
                rec["edge"] = edge_of.get(mod.split("?")[0]) or []
                fn = out / f"{i:02d}.png"
                if rec["action_ok"] or not a.skip_failed_actions:
                    p.shot(fn)
                    rec["file"] = fn.name
                ok += 1
            except NotTheShell as e:
                not_shell = str(e)
                break
            except Exception as e:                           # noqa: BLE001
                rec["action_ok"] = False
                rec["reason"] = f"{type(e).__name__}: {str(e)[:150]}"
            finally:
                if p:
                    p.close()
            if not rec["action_ok"]:
                failed.append(rec)
            mark = "ok  " if rec["action_ok"] else "ACT?"
            print(f"  {mark} {i:02d}  {label[:44]:<46}"
                  + ("" if rec["action_ok"] else f"  {rec['reason']}")
                  + (f"  RAW: {rec['leaks'][0]!r}" if rec.get("leaks") else "")
                  + (f"  CARD: {rec['standin']}" if rec.get("standin") else "")
                  + (f"  drawn in {rec['drawn_ms'] / 1000:.1f}s" if rec.get("drawn_ms") is not None and not rec.get("slow") else "")
                  + (f"  {rec['slow']}" if rec.get("slow") else "")
                  + (f"  BUSY: still drawing ({', '.join(rec.get('busy_what') or [])}) when the picture was taken" if rec.get("busy") else "")
                  + (f"  EDGE: {' '.join(rec['edge'])}" if rec.get("edge") else ""))
            log.append(rec)
    finally:
        try:
            browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:                                # noqa: BLE001
                proc.kill()
            shutil.rmtree(tmpdir, ignore_errors=True)

    if not_shell:
        print(f"! the page at {url} is not the console — it is «{not_shell}». Every panel is opened in the\n"
              "  console's shell, so NOTHING was photographed: a picture taken here would be that page under\n"
              "  each tile's name.")
        return 2

    # MERGED, not overwritten. The log's job is to describe the PNGs sitting in this directory, and a
    # `--only 15` re-render must not leave a log claiming the directory holds one panel — a reader
    # would then have no record of which of the other 42 reached the state they are named for.
    logfile = out / "render-log.json"
    keep = {}
    if logfile.exists():
        try:
            prev = json.loads(logfile.read_text(encoding="utf-8"))
            keep = {p["index"]: p for p in prev.get("panels", [])
                    if (out / f"{p['index']:02d}.png").exists()}
        except (ValueError, KeyError):
            keep = {}
    # …and only what is still THIS list's panel. An office's tiles change — one is withdrawn, the
    # order moves — and a picture numbered for a panel that is no longer at that number is a wrong
    # picture under a right name (two such sat here for a day: a tile its office had stopped giving,
    # and the last tile's old position). It goes, with its entry.
    for i in [i for i, p in keep.items() if i >= len(panels) or p.get("label") != panels[i][0]]:
        (out / f"{i:02d}.png").unlink(missing_ok=True)
        del keep[i]
    keep.update({r["index"]: r for r in log})
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for r in log:
        r["rendered_at"] = stamp
    logfile.write_text(
        json.dumps({"profile": a.profile, "console": url, "chrome": chrome, "last_run": stamp,
                    "last_run_panels": sorted(r["index"] for r in log),
                    "panels": [keep[i] for i in sorted(keep)]}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"\n   {ok}/{len(want)} panel(s) rendered -> {rel(out)}\\NN.png")
    if failed:
        # Loud on purpose. A panel whose action failed shows the screen it fell back to, so its diff
        # is a real number about the WRONG screen unless the reader knows.
        print(f"   ⚠ {len(failed)} panel(s) did not reach the state they are named for — their PNG "
              f"is the fallback screen, not the panel:")
        for r in failed:
            print(f"       {r['index']:02d}  {r['label'][:44]:<46} {r['reason']}")
    raw = [r for r in log if r.get("leaks")]
    if raw:
        print(f"   ⚠ {len(raw)} panel(s) print a raw value (undefined / NaN / [object Object]) — a field the "
              f"screen reads is not what its data gives:")
        for r in raw:
            print(f"       {r['index']:02d}  {r['label'][:44]:<46} {' | '.join(r['leaks'][:3])}")
    away = [r for r in log if r.get("standin") or r.get("edge")]
    if away:
        print(f"   ⚠ {len(away)} panel(s) are not the app's own screen — a card stands in its place, or the "
              f"edge delivers the app and this map came in behind it. Look at these through the edge:")
        for r in away:
            print(f"       {r['index']:02d}  {r['label'][:44]:<46} "
                  + " · ".join(x for x in (r.get("standin"), r.get("edge") and "edge: " + " ".join(r["edge"])) if x))
    late = [r for r in log if r.get("slow") or r.get("busy")]
    if late:
        # A finding of its own, whatever the picture shows: the screen made a person wait.
        print(f"   ⚠ {len(late)} panel(s) took longer than a screen may ({drawn.BUDGET_MS / 1000:g}s) to say what "
              f"they have to say, or never did — each is a bug to file with its time:")
        for r in late:
            print(f"       {r['index']:02d}  {r['label'][:44]:<46} "
                  + (r.get("slow") or f"NEVER DRAWN — still: {', '.join(r.get('busy_what') or [])}"))
    print(f"   log -> {rel(out / 'render-log.json')}")
    print("\n   next:\n     python3 scripts/ui-coverage/pixel-diff.py "
          f"--sim digital-office/sim/ui-map/{a.profile} --live {rel(out)}")
    return 1 if late else 0


def rel(p: pathlib.Path) -> str:
    try:
        return str(pathlib.Path(p).relative_to(REPO))
    except ValueError:
        return str(p)


if __name__ == "__main__":
    sys.exit(main())
