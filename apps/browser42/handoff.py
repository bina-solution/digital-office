#!/usr/bin/env python3
"""browser42 hand-off — the ONE address a person gets when the office browser needs a human.

Until 2026-10-14 (DGO-571) every hand-off was a generic string — "the owner at …/view/",
`live_view: "/a/browser42/"` — and the person landed on the WHOLE shared screen and hunted for the
window. Everything that identifies the window already existed: the group tag `b42g:<slug>`, its record
(/data/groups/<slug>/group.json or /data/tasks/<slug>/task.json, both with the tab id), the extension's
`session_<slug>` entry and its bring-to-front. Nothing connected them. This file is the connection,
and the only owner of it:

  GET /handoff/<slug>     Caddy's /handoff/* → this server (:8767, inside browser42-browser), with the
                          token Caddy adds (X-Browser42-Handoff) — the port is on the shared network too:
      1. an awake browser — /json/version IS the launch, the one wake path (hooks/sleep); ONE launch at
         a time (Waker), and a request that waited WAKE_WAIT_S answers a "waking…" page that reloads
         itself into the same launch instead of holding on;
      2. that group's tab to the front through the extension broker (`front`: the same window, never a
         new one) — after an idle sleep the extension finds it again by its last address and re-tags it;
      3. compact presentation (F11) left, so the tab strip — and the group's name on it — is visible;
      4. 302 to the live view: /view/ at this origin, the console mount behind the console; a tab that
         could not be brought to the front is SAID (`?lost=<slug>`, shown by the viewer), never pretended.
  handoff_link(slug)      the absolute address of that route as the OWNER's browser types it: a console
                          deep link (CONSOLE_BASE_URL + AUTH_PROTOCOL), the way apps/project-pln reports
                          a work item — framed inside the office, signed in by the office's own SSO.
  view_link()             the live view's address, for a notice that promises no tab (a released one).
  notify_human(...)       one notice per episode in the office's notice centre (platform-base/notifications).

The limit, stated once: noVNC shows a whole SCREEN, not a tab. The promise this route makes is "the
right tab in front, with its group's name on the strip" — never "only that page".

CLI (inside browser42-browser; `bbox b42 handoff <slug>` is the host-side hand):
    python3 /handoff.py link <slug>     → {"ok": true, "slug", "url", "tab_id", "group_id", "page"}
    python3 /handoff.py serve           → the route server (started by start-browser.sh §4f-bis)
"""

import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATA = Path(os.environ.get("DATA", "/data"))
BROKER = os.environ.get("BROKER", "ws://127.0.0.1:8765")
#: cloakserve, inside the browser container: GET /json/version IS the launch (its get_or_launch).
CDP_VERSION_URL = os.environ.get("BROWSER42_CDP_VERSION_URL", "http://127.0.0.1:9222/json/version/")
PORT = int(os.environ.get("BROWSER42_HANDOFF_PORT", "8767"))
#: Where `serve` listens. The browser container sets loopback, and its forwarder carries the port to
#: browser42's own network only (start-browser.sh §4a, DGO-983).
HOST = os.environ.get("BROWSER42_HANDOFF_HOST", "0.0.0.0")
ALIAS = "browser42"          # app.json module.alias — the console mounts this app at /a/<alias>/
VIEW_PATH = "/view/"         # the live view at this app's own origin (caddy/Caddyfile)
CONSOLE_MOUNT = f"/a/{ALIAS}/"   # …and where the console mounts that same view (app.json module.url)
NOTIFICATIONS_URL = os.environ.get("NOTIFICATIONS_URL", "http://notifications:8977").rstrip("/")
#: Caddy is the only door: `handle /handoff/*` adds this header from its MCP_TOKEN (caddy/Caddyfile),
#: and this port is on the shared traefik network as well — a hand-off wakes the browser and moves
#: tabs, so a request without the token is refused. An empty token refuses everything but /healthz.
TOKEN = os.environ.get("BROWSER42_MCP_TOKEN", "")
TOKEN_HEADER = "X-Browser42-Handoff"
#: A cold Chromium with a real profile takes 15-60 s here (hooks/sleep allows 200): a short timeout
#: that gives up mid-launch and calls again is how the relaunch storms of 2026-09-30 started.
WAKE_TIMEOUT_S = float(os.environ.get("BROWSER42_HANDOFF_WAKE_SECONDS", "120"))
#: How long ONE request waits for that launch before answering a "waking…" page that reloads itself.
#: A held request invites a reload, and a reload that asked cloakserve again would be a second
#: get_or_launch — two Chromes (hooks/sleep, measured 2026-09-30 20:07). The launch goes on in the
#: background (Waker) and the reload joins it.
WAKE_WAIT_S = float(os.environ.get("BROWSER42_HANDOFF_WAIT_SECONDS", "20"))
#: A wake that took longer than this LAUNCHED Chrome; awake, /json/version answers in milliseconds.
COLD_LAUNCH_S = 3.0
#: After a wake the extension's offscreen page reconnects to the broker within ~1 s (offscreen.js);
#: `front` is retried that long while the broker says the extension is not there yet.
FRONT_RETRY_S = float(os.environ.get("BROWSER42_HANDOFF_FRONT_SECONDS", "20"))
#: start-browser.sh §2b presses F11 ONCE per new Chromium window, 1 s after it maps, on a 2 s poll:
#: right after a launch the window is briefly standard and about to turn compact. Looking before that
#: press would find nothing to undo; so after a launch the look waits for it.
COMPACT_SETTLE_S = float(os.environ.get("BROWSER42_HANDOFF_SETTLE_SECONDS", "4"))
#: Exactly what group-manager.py's slugify() produces: lowercase kebab, no edge or double hyphen.
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: Broker answers that mean "not yet" rather than "no": the extension is still reconnecting.
TRANSIENT = {"extension_unavailable", "broker_unreachable"}


def slug_from_path(path: str):
    """`/handoff/<slug>` → the slug; None for anything else (a traversal, a second segment, a typo)."""
    route = path.split("?", 1)[0]
    if not route.startswith("/handoff/"):
        return None
    slug = route[len("/handoff/"):].rstrip("/")
    return slug if SLUG.match(slug) else None


def group_record(slug: str, data: Path | None = None):
    """What names the window: a session group's manifest (groups/<slug>/group.json — `bbox b42 group`)
    or a task's record (tasks/<slug>/task.json — `bbox b42 task start`); both carry the tab id. None
    when no such slug was ever opened here: a closed session group leaves no manifest, a task's record
    stays (finished or not)."""
    root = DATA if data is None else data
    for path in (root / "groups" / slug / "group.json", root / "tasks" / slug / "task.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            return record
    return None


def group_id_of(record: dict):
    """A session manifest says `group_id`; a task record says `native_group.id`."""
    return record.get("group_id") if record.get("group_id") is not None else (record.get("native_group") or {}).get("id")


def group_color_of(record: dict):
    """A session manifest says `color`; a task record says `native_group.color`."""
    return record.get("color") or (record.get("native_group") or {}).get("color")


def _console(env=None) -> str:
    """The console's own public address, as the OWNER's browser types it.

    Derived from what the office declares (`CONSOLE_BASE_URL` + `AUTH_PROTOCOL`), the way
    apps/project-pln/hooks/tasks derives a work item's link: the owner's browser, the console's SSO,
    the app framed inside the office. A CONSOLE_BASE_URL that already carries a scheme, or a port
    (an edge that landed on :8080), is used as it is; unset, the local office's default.
    """
    env = os.environ if env is None else env
    host = (env.get("CONSOLE_BASE_URL") or "").strip().rstrip("/")
    if not host:
        return "http://console.localhost:8080"
    if "://" not in host:
        return f"{(env.get('AUTH_PROTOCOL') or '').strip() or 'http'}://{host}"
    return host


def handoff_link(slug: str, env=None) -> str:
    """The absolute address the OWNER opens — a console deep link, never a bare app origin."""
    return f"{_console(env)}{CONSOLE_MOUNT}handoff/{slug}"


def view_link(env=None) -> str:
    """The live view inside the console — for a notice that can promise no tab (it was released)."""
    return f"{_console(env)}{CONSOLE_MOUNT}"


def redirect_target(behind_console: bool, lost: str | None = None) -> str:
    """Where the 302 lands. At this app's own origin the view is /view/. Behind the console the request
    came through the /a/<alias>/handoff passthrough (X-Forwarded-Prefix is present), and the console
    mounts /view/ AT the alias root (app.json module.url) — so there, the view is the mount itself. The
    mount is this app's own constant, never the header's value: a header is a hint, not an address.
    `lost` names a group whose tab could not be brought to the front; the viewer says so."""
    target = CONSOLE_MOUNT if behind_console else VIEW_PATH
    return f"{target}?lost={lost}" if lost else target


def touch_activity(name: str = "handoff") -> None:
    """A person coming to look is use: the sleeper (start-browser.sh §4k, reaper.py) counts idle from
    these. Touched only once the browser ANSWERED — a marker written while it sleeps is what made the
    sleeper launch a second Chrome (hooks/sleep `wake`, measured 2026-09-30 20:07:33)."""
    try:
        activity = DATA / ".activity"
        activity.mkdir(parents=True, exist_ok=True)
        (activity / name).touch()
    except OSError:
        pass


def wake(timeout: float | None = None) -> bool:
    """Wake the browser the ONE way (hooks/sleep `wake`): /json/version is cloakserve's get_or_launch.
    Awake, it answers at once; asleep, it answers when Chrome is up."""
    try:
        with urlopen(CDP_VERSION_URL, timeout=WAKE_TIMEOUT_S if timeout is None else timeout):
            return True
    except HTTPError as e:
        # cloakserve answered and REFUSED — its body says why (G66: the error is read, never discarded)
        print(f"[handoff] wake refused: HTTP {e.code} {e.read(300).decode('utf-8', 'replace').strip()}",
              file=sys.stderr, flush=True)
        return False
    except (URLError, OSError, TimeoutError) as e:      # not up yet: a slow launch is not an error here
        print(f"[handoff] wake: no answer yet ({e})", file=sys.stderr, flush=True)
        return False


class Waker:
    """ONE launch at a time. Every request asks for an awake browser; the first to find it asleep
    starts the launch, and the others WAIT for that launch instead of asking cloakserve again — two
    concurrent get_or_launch calls are two Chromes (the double launch hooks/sleep records)."""

    def __init__(self, wake=wake):
        self._wake = wake
        self._lock = threading.Lock()
        self._thread = None
        self._done = threading.Event()
        self._result = {"awake": False, "took": 0.0}

    def ensure(self, timeout: float):
        """{"awake", "took"} once the launch finished within `timeout`; None = still waking."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._done.clear()
                self._thread = threading.Thread(target=self._run, name="browser42-wake", daemon=True)
                self._thread.start()
        if not self._done.wait(timeout):
            return None
        return dict(self._result)

    def _run(self) -> None:
        started = time.monotonic()
        awake = self._wake()
        self._result = {"awake": bool(awake), "took": time.monotonic() - started}
        self._done.set()


WAKER = Waker()


def broker_command(command: dict, timeout: float = 5) -> dict:
    from websockets.sync.client import connect as websocket_connect   # in the image; the tests inject
    with websocket_connect(BROKER, open_timeout=timeout, close_timeout=1) as socket:
        socket.send(json.dumps({"role": "client", "command": {"protocolVersion": 1, **command}}))
        return json.loads(socket.recv(timeout=timeout + 2))


def front(slug: str, record: dict | None = None, budget: float | None = None, send=None,
          clock=time.monotonic, sleep=time.sleep) -> dict:
    """Bring the group's tab to the front through the broker (extension action `front`).

    The command carries what the extension needs to find the tab AGAIN after an idle sleep — Chrome's
    --restore-last-session reopens tabs with new ids and no window.name, so the stored session points
    at nothing; the record's address, label and colour let it recover the tab by URL and re-tag it.
    Retried while the answer is "not yet" (the extension reconnecting after a wake) and returned as it
    is otherwise, `ok` or not — a tab that is not there comes back as `tab_lost`, a fact the route says.
    """
    send = broker_command if send is None else send
    record = record or {}
    command = {"action": "front", "slug": slug, "url": record.get("url") or "", "label": slug}
    if group_color_of(record):
        command["color"] = group_color_of(record)
    deadline = clock() + (FRONT_RETRY_S if budget is None else budget)
    while True:
        try:
            answer = send(command)
        except Exception as error:                      # noqa: BLE001 — the broker may be mid-restart
            answer = {"ok": False, "error": {"code": "broker_unreachable", "message": str(error)}}
        error = answer.get("error")
        code = error.get("code", "") if isinstance(error, dict) else ""
        if answer.get("ok") or code not in TRANSIENT or clock() >= deadline:
            return answer
        sleep(1)


def _run(argv: list) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def chromium_windows(run=_run) -> list:
    """The browser's X window ids — the same filter as start-browser.sh `chromium_window_ids`
    (`wmctrl -lx`, a class containing "chrom"); DISPLAY/XAUTHORITY are inherited from the entrypoint."""
    ids = []
    for line in run(["wmctrl", "-lx"]).splitlines():
        parts = line.split()
        if len(parts) > 2 and "chrom" in parts[2].lower():
            ids.append(parts[0])
    return ids


def present_standard(run=_run) -> int:
    """Leave compact presentation: a FULLSCREEN (F11) Chromium window gets F11 once, so the tab strip —
    and the group's name on it — is visible. A standard window is left alone, and the viewer's own
    toggle (browser-navigation.js) still wins afterwards. Returns how many windows were switched."""
    switched = 0
    for window in chromium_windows(run):
        if "FULLSCREEN" in run(["xprop", "-id", window, "_NET_WM_STATE"]):
            run(["xdotool", "windowactivate", "--sync", window, "key", "--window", window, "F11"])
            switched += 1
    return switched


def perform(slug: str, record: dict, *, waker=None, front=front, present=present_standard,
            touch=touch_activity, sleep=time.sleep) -> dict:
    """The hand-off, in order: awake → use → the tab in front → the strip visible.

    The order is load-bearing: the activity marker is touched only AFTER the browser answered (see
    touch_activity). A launch still running after WAKE_WAIT_S is reported as `waking` and nothing
    else happens — the person's page reloads and joins the same launch. Every later step is
    best-effort and REPORTED: a tab that is not there is `lost`, never pretended."""
    woke = (WAKER if waker is None else waker).ensure(WAKE_WAIT_S)
    if woke is None:
        return {"slug": slug, "waking": True}
    touch()
    answer = front(slug, record)
    cold = bool(woke["awake"]) and woke["took"] > COLD_LAUNCH_S
    if cold:
        sleep(COMPACT_SETTLE_S)                         # the compact press lands first (COMPACT_SETTLE_S)
    switched = present()
    return {"slug": slug, "waking": False, "awake": bool(woke["awake"]), "cold": cold,
            "front": bool(answer.get("ok")), "lost": not answer.get("ok"), "front_answer": answer,
            "presentation_switched": switched, "state": record.get("state"),
            "tab_id": record.get("tab_id"), "group_id": group_id_of(record)}


def waking_page(slug: str) -> str:
    """What the person sees while Chrome launches (a cold start is 15-60 s): one sentence in the
    office's words, and the page reloads itself into the same launch. It names no colour of its own —
    the office's palette is theme-tokens.css's, and this is a sentence, not a screen."""
    name = escape(slug)
    return ('<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="5"><title>דפדפן הלשכה מתעורר</title></head>'
            f"<body><p>דפדפן הלשכה מתעורר… הדף ייטען שוב בעוד 5 שניות ויעלה את הכרטיסייה «{name}» קדימה.</p>"
            "</body></html>\n")


def notify_human(slug: str, body: str, link: str, url: str | None = None, title: str | None = None,
                 since=None) -> bool:
    """One notice in the office's notice centre (platform-base/notifications, POST /api/notifications):
    source `browser42`, one row per slug (`source_id`), level warning, the link both as `link` and in
    the text (the centre renders an address in the text as a link).

    One notice per EPISODE: `since` (epoch seconds — the task's start, the stall's moment) becomes
    `meta.lastSeen`, the field the centre compares in create_notification's `recurred` rule. A second
    post with the same value refreshes the text and leaves the read-state alone; a later episode
    re-surfaces the notice as unread. Without it the centre stamps "now", and a looping refusal would
    make the same notice new again at every turn.

    Best-effort — a notice must never break the escape path that raised it. An empty address means
    "no notice" (the unit tests)."""
    url = NOTIFICATIONS_URL if url is None else url
    if not url:
        return False
    meta = {"app": ALIAS, "slug": slug}
    if since:
        meta["lastSeen"] = datetime.fromtimestamp(float(since), timezone.utc).isoformat()
    payload = {
        "source": ALIAS, "source_id": f"handoff:{slug}", "level": "warning",
        "title": title or f"דפדפן הלשכה — נדרש אדם: {slug}",
        "body": f"{body}\n{link}", "link": link, "meta": meta,
    }
    try:
        request = Request(f"{url.rstrip('/')}/api/notifications",
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5):
            return True
    except HTTPError as e:
        # the centre refused the notice — say what it said (G66), the hand-off itself still stands
        print(f"[handoff] notification centre refused: HTTP {e.code} "
              f"{e.read(300).decode('utf-8', 'replace').strip()}", file=sys.stderr, flush=True)
        return False
    except (URLError, OSError, TimeoutError) as e:
        print(f"[handoff] notification centre unreachable ({e})", file=sys.stderr, flush=True)
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        if self.path.split("?", 1)[0] == "/healthz":
            self._json(200, {"ok": True, "service": "browser42-handoff"})
            return
        if not TOKEN or not hmac.compare_digest(self.headers.get(TOKEN_HEADER, ""), TOKEN):
            self._json(403, {"ok": False, "error": {
                "code": "forbidden",
                "message": "the hand-off is reached through the office's edge (Caddy /handoff/*), which carries its token"}})
            return
        slug = slug_from_path(self.path)
        if not slug:
            self._json(404, {"ok": False, "error": {"code": "not_found", "message": "GET /handoff/<slug>"}})
            return
        record = group_record(slug)
        if record is None:
            self._json(404, {"ok": False, "error": {
                "code": "no_such_group",
                "message": f"no group or task '{slug}' was ever opened here — a closed session group leaves no "
                           f"manifest, while a task's record stays even when it is finished (bbox b42 groups)"}})
            return
        result = perform(slug, record)
        print(json.dumps({"handoff": result}, ensure_ascii=False, sort_keys=True), flush=True)
        if result.get("waking"):
            self._html(200, waking_page(slug), refresh=5)
            return
        behind_console = bool(self.headers.get("X-Forwarded-Prefix"))
        self.send_response(302)
        self.send_header("Location", redirect_target(behind_console, slug if result.get("lost") else None))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, status: int, payload: dict) -> None:
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self._send(status, body, "application/json")

    def _html(self, status: int, html: str, refresh: int | None = None) -> None:
        if refresh:
            self.send_response(status)
            self.send_header("Refresh", str(refresh))
            self._finish(html.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self._finish(body, content_type)

    def _finish(self, body: bytes, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def cmd_link(slug: str) -> int:
    """`bbox b42 handoff <slug>` — the address for the person, and what it will bring to the front."""
    if not SLUG.match(slug or ""):
        print(json.dumps({"ok": False, "error": {"code": "usage", "message": "handoff <slug> — a lowercase kebab-case group or task slug"}}))
        return 2
    record = group_record(slug)
    if record is None:
        print(json.dumps({"ok": False, "error": {"code": "no_such_group", "message": f"no group or task '{slug}' was ever opened here (bbox b42 groups)"}}))
        return 2
    print(json.dumps({"ok": True, "slug": slug, "url": handoff_link(slug), "tab_id": record.get("tab_id"),
                      "group_id": group_id_of(record), "page": record.get("url"), "state": record.get("state")},
                     ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: list) -> int:
    verb = argv[1] if len(argv) > 1 else ""
    if verb == "link":
        return cmd_link(argv[2] if len(argv) > 2 else "")
    if verb == "serve":
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        print(f"browser42 handoff listening on :{PORT} ({'token set' if TOKEN else 'NO TOKEN — every hand-off refused'})", flush=True)
        server.serve_forever()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
