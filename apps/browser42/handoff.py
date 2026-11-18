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
  GET /handoff/           the hand-offs that are news (below), for a console in this office — the same door.
  GET /gate               Caddy's question before /view/*, /websockify and /handoff/* (the `gate` snippet):
                          the LINK is admitted by its address, everyone else is asked of the office's
                          identity provider with their own cookie (DGO-1336; see `gate_answer`).
  handoff_link(slug)      the absolute address of that route as the OWNER's browser types it: a console
                          deep link (CONSOLE_BASE_URL + AUTH_PROTOCOL), the way apps/project-pln reports
                          a work item — framed inside the office, signed in by the office's own SSO.
  view_link()             the live view's address, for a notice that promises no tab (a released one).
  notify_human(...)       one notice per episode in the office's notice centre (platform-base/notifications).

THE RECORD OF A HAND-OFF (DGO-1336). A link in a notice reaches a person who reads notices; an app's
«Continue with Google» is pressed by a person who is LOOKING AT THE APP, and nothing told the screen in
front of him that the office browser now needed him — the owner pressed it on his phone, Google's
account chooser opened in this browser's own display, and he kept seeing «Sign In» (2026-11-04: «זה
לא עובד לא פותח לי שום דפדפן»). So a hand-off is also a RECORD, /data/handoffs/<slug>.json: who asked
(`for`, the app), where it stands (`needed` → `done` | `failed`), one sentence for the person, and an
episode id. Never an address: a sign-in's query carries its state on the way out and its one-time code
on the way back. `bbox b42 open <app> <url>` writes `needed`; whoever finishes the errand writes the end
(`bbox b42 handoff <slug> --done | --failed <sentence>`); every console that shows this browser reads
the list (here, or the task runner's GET /v1/handoffs across a link) and brings the browser to the
person while it is `needed`, and the app back to him when it is `done`.

The limit, stated once: noVNC shows a whole SCREEN, not a tab. The promise this route makes is "the
right tab in front, with its group's name on the strip" — never "only that page".

CLI (inside browser42-browser; `bbox b42 handoff <slug>` is the host-side hand):
    python3 /handoff.py link <slug>     → {"ok": true, "slug", "url", "tab_id", "group_id", "page"}
    python3 /handoff.py record <slug> needed|done|failed [--for <app>] [--sentence <text>]
                                        → {"ok": true, "handoff": {slug, for, state, sentence, id, …}}
    python3 /handoff.py list            → {"ok": true, "handoffs": [the records that are news]}
    python3 /handoff.py serve           → the route server (started by start-browser.sh §4f-bis)
"""

import hmac
import http.client
import json
from contextlib import contextmanager
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
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
#: start-browser.sh §2b makes a new Chromium window compact within a 2 s cycle of it mapping: right after
#: a launch the window is briefly standard and about to turn compact. Looking before that would find
#: nothing to undo; so after a launch the look waits for it.
COMPACT_SETTLE_S = float(os.environ.get("BROWSER42_HANDOFF_SETTLE_SECONDS", "4"))
#: The windows the hand-off made standard, one X id a line: start-browser.sh §2b never makes one of them
#: compact again (it clears the file when no window is left).
STANDARD_MARK = Path("/tmp/.b42-standard")
#: Sets compact/standard as a STATE through Chrome's DevTools (start-browser.sh §2b uses it too); an
#: image built before it has none, and then a fullscreen window gets F11 once, as it always did.
WINDOW_TOOL = "/usr/local/bin/browser42-window.py"
#: Exactly what group-manager.py's slugify() produces: lowercase kebab, no edge or double hyphen.
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: Broker answers that mean "not yet" rather than "no": the extension is still reconnecting.
TRANSIENT = {"extension_unavailable", "broker_unreachable"}

#: The records (module docstring, DGO-1336): /data/handoffs/<slug>.json, one per slug.
HANDOFFS_DIR = "handoffs"
STATES = ("needed", "done", "failed")
#: A `needed` record older than this is nobody's errand any more: an app's sign-in lives 30 minutes
#: (claude.ai's hop_nonce), and a watcher that died with its container would leave the record standing,
#: so the list stops naming it rather than have every console send a person to a tab that waits for
#: nothing.
NEEDED_TTL_S = float(os.environ.get("BROWSER42_HANDOFF_NEEDED_SECONDS", "1800"))
#: An ended record is news for this long: a console asks every few seconds, so a console that sent a
#: person to the browser learns the end at its next look and takes him back (or says why not).
ENDED_TTL_S = float(os.environ.get("BROWSER42_HANDOFF_ENDED_SECONDS", "600"))
#: What a record may say — and all a list ever shows. No address is among them.
RECORD_KEYS = ("slug", "for", "state", "sentence", "id", "opened_at", "updated_at")
SENTENCE_MAX = 300
#: What an ended record says when its writer said nothing: a console shows `failed` as a card, and a card
#: with no sentence is the dead end this record exists to remove.
ENDED_SENTENCE = {"done": "הושלם — חוזרים לאפליקציה.",
                  "failed": "דפדפן הלשכה לא השלים את מה שהאפליקציה ביקשה — נסו שוב מתוך האפליקציה."}
#: A sentence is for a person; one that carries a sign-in's query is a leak, refused by name.
SECRET_SHAPED = re.compile(r"(?:^|[?&#\s])(?:code|state|hop_nonce|access_token|id_token)=", re.IGNORECASE)

#: THE LINK'S OWN ADDRESS (DGO-1336). A LINKED office's console reaches this app through the link proxy
#: (`dgo-net`, the namespace dgo-link runs in), after THAT office's edge signed the person in — the owner
#: opening the HP's office browser from vps1's console on his phone. Such a request carries the other
#: office's cookie, which this office's provider cannot read, so the gate refused it: 400 «refusing a
#: return-to outside this office», measured 2026-11-05 from vps1 with exactly the headers its edge sends,
#: for /view/vnc.html and /handoff/. The one browser every office of ours uses (the owner, EXF-29) was
#: visible from none of them. The link is admitted by ADDRESS, as bina-claude's door admits it
#: (apps/bina-claude/adapter/gate.mjs): a container on the network can write any header, but it cannot
#: answer from another container's address. Which offices reach this app over the link at all is the
#: serving office's own declaration (`serve.only.<office>`; browser42 is an admin app, given by name).
LINK_PEERS = tuple((os.environ.get("BROWSER42_LINK_PEERS") or "dgo-net").split())
#: Caddy writes the TCP peer here (`header_up X-Browser42-Peer {http.request.remote.host}`), replacing
#: whatever a client sent: the one value on a gate request that no caller chooses.
PEER_HEADER = "X-Browser42-Peer"
#: The peers' addresses are asked again every PEER_TTL_S, and a miss forces a fresh look at most every
#: PEER_MISS_S — a recreated link proxy gets a new address, and a flood of strangers must not turn
#: into a flood of DNS questions (the same two numbers as gate.mjs).
PEER_TTL_S, PEER_MISS_S = 10.0, 3.0
#: Everyone else is asked of the office's OWN identity provider, with the request's own cookie — the
#: question the edge's forwardAuth asks. WHICH provider is the platform's one switch, DGO_IDENTITY (the
#: value the edge's middleware reads); one this file does not know refuses the door, never opens it.
PROVIDERS = {
    "authentik": "http://authentik-server:9000/outpost.goauthentik.io/auth/traefik",
    # the office's browser is its admins' (app.json `people: admins`, DGO-1755): the admins' question, as the edge
    # asks it. A linked office's person arrives by the link proxy, already checked by THAT office's own form.
    "forward-auth": "http://forward-auth:9078/auth/traefik/admins",
}
#: …which Caddy also says on every gate request (`header_up X-Browser42-Identity {$DGO_IDENTITY:authentik}`, from
#: ITS environment): a browser container started from a config older than this file's has no
#: DGO_IDENTITY of its own, and would otherwise ask a provider the office does not run, refusing
#: everybody but the link. This container's own value wins; the header only names one of PROVIDERS,
#: each of which checks the cookie itself, so a header can choose a question, never an answer.
IDENTITY_HEADER = "X-Browser42-Identity"
PROVIDER_TIMEOUT_S = float(os.environ.get("BROWSER42_GATE_PROVIDER_SECONDS", "15"))
#: Never carried from one hop to the next: they describe a connection, not a request (RFC 9110 §7.6.1),
#: and Upgrade would turn the provider's GET into a websocket handshake.
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
              "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


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


def bare_url(url: str) -> str:
    """An address without what may carry a secret: scheme, host, port and path — no query, no fragment.

    A sign-in's query carries its state on the way out and its one-time code on the way back (DGO-1336),
    so this is what a record, a manifest or a log line is given in place of the address."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class RecordError(ValueError):
    """A record that cannot be written as asked; the message is the sentence the caller prints."""


def _record_path(slug: str, data: Path | None = None) -> Path:
    return (DATA if data is None else data) / HANDOFFS_DIR / f"{slug}.json"


def _read_record(slug: str, data: Path | None = None):
    try:
        record = json.loads(_record_path(slug, data).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


class Superseded(RecordError):
    """An end for an episode that is no longer the open one: a newer attempt owns the hand-off."""


def current_episode(slug: str, data: Path | None = None) -> str:
    """The id of the slug's current episode ("" when it has none) — how an attempt learns a newer one began."""
    return str((_read_record(slug, data) or {}).get("id") or "")


def write_record(slug: str, state: str, app: str | None = None, sentence: str | None = None,
                 data: Path | None = None, now: float | None = None, episode: str | None = None) -> dict:
    """Write a hand-off's record and return it as a list shows it.

    `needed` opens an EPISODE: `opened_at`, and `for` (the app) is required — a person is brought to the
    browser for SOMEBODY. Its id is the `episode` the caller minted when it gives one (so an opener knows
    its episode even when the open itself never answers), else a new one. `done` and `failed` end the
    episode that is open and keep its id and its app, so a console that switched a person for that
    episode knows this end is its end. An end that names its `episode` is refused (Superseded) when that
    episode is no longer the open one — a watcher that outlived its attempt must never end the new
    attempt with the old one's outcome. Read, checked and written under the slug's record lock, and
    written whole (a temporary file renamed over the old one): a console reading mid-write sees the old
    record or the new one, never half of either."""
    if not SLUG.match(slug or ""):
        raise RecordError(f"'{slug}' is not a slug — lowercase kebab-case, as `bbox b42 groups` lists them")
    if state not in STATES:
        raise RecordError(f"'{state}' is not a state; a hand-off is {', '.join(STATES)}")
    if app is not None and not SLUG.match(app):
        raise RecordError(f"'{app}' is not an app id — the app's id or alias, lowercase kebab-case")
    if episode is not None and not SLUG.match(episode):
        raise RecordError(f"'{episode}' is not an episode id — lowercase letters, digits and hyphens")
    sentence = " ".join(str(sentence or "").split())[:SENTENCE_MAX] or ENDED_SENTENCE.get(state, "")
    if SECRET_SHAPED.search(sentence):
        raise RecordError("the sentence carries what looks like a sign-in's query (code=, state=, …); a "
                          "record never holds an address — say what happened in words")
    if state == "needed" and not app:
        raise RecordError("a `needed` hand-off names the app it is for (--for <app>)")
    stamp = time.time() if now is None else now
    path = _record_path(slug, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _record_lock(path):
        previous = _read_record(slug, data) or {}
        if state == "needed":
            record = {"slug": slug, "for": app, "state": state, "sentence": sentence,
                      "id": episode or secrets.token_hex(6), "opened_at": int(stamp), "updated_at": int(stamp)}
        else:
            if episode is not None and str(previous.get("id") or "") != episode:
                raise Superseded(f"'{slug}' is no longer episode {episode} — a newer attempt owns the hand-off; "
                                 f"nothing was written")
            record = {"slug": slug, "for": app or str(previous.get("for") or ""), "state": state,
                      "sentence": sentence, "id": str(previous.get("id") or secrets.token_hex(6)),
                      "opened_at": int(previous.get("opened_at") or stamp), "updated_at": int(stamp)}
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    return {key: record[key] for key in RECORD_KEYS}


@contextmanager
def _record_lock(path: Path):
    """The record's own lock (`.<slug>.json.lock` beside it): the check of an end's episode and the write
    are one step, so an end can never overwrite a `needed` written a moment after it was checked."""
    try:
        import fcntl
    except ImportError:                                  # pragma: no cover — no flock on this platform
        yield
        return
    with path.with_name(f".{path.name}.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def waiting(slug: str, data: Path | None = None, now: float | None = None) -> bool:
    """Is a person waited for on this slug — a `needed` record that is still news (NEEDED_TTL_S)? A stale
    one, left by a watcher that died with its container, must not hold a bookmark in a reload loop."""
    record = _read_record(slug, data) or {}
    try:
        age = (time.time() if now is None else now) - float(record.get("updated_at") or 0)
    except (TypeError, ValueError):
        return False
    return record.get("state") == "needed" and age <= NEEDED_TTL_S


def read_records(data: Path | None = None, now: float | None = None) -> list:
    """The hand-offs that are news, newest first: a `needed` one younger than NEEDED_TTL_S, an ended one
    younger than ENDED_TTL_S. Only RECORD_KEYS leave this function — whatever else a file holds stays."""
    stamp = time.time() if now is None else now
    folder = (DATA if data is None else data) / HANDOFFS_DIR
    out = []
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return out
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("state") not in STATES or not SLUG.match(str(record.get("slug") or "")):
            continue
        try:
            age = stamp - float(record.get("updated_at") or 0)
        except (TypeError, ValueError):
            continue
        if age > (NEEDED_TTL_S if record["state"] == "needed" else ENDED_TTL_S):
            continue
        out.append({key: record.get(key) for key in RECORD_KEYS})
    return sorted(out, key=lambda r: (-(r.get("updated_at") or 0), r.get("slug") or ""))


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


def present_standard(run=_run, mark=STANDARD_MARK, tool=WINDOW_TOOL, sleep=time.sleep) -> int:
    """Leave compact presentation, so the tab strip — and the group's name on it — is visible. Every
    Chromium window's id goes into `mark` first, so the window loop never makes it compact again; then
    standard is SET (WINDOW_TOOL), twice a second apart, so a compact request of the loop's that was
    already in flight cannot be the last word. An image without the tool gets the old behaviour: F11 once
    on a FULLSCREEN window. The viewer's own toggle (browser-navigation.js) still wins afterwards.
    Returns how many windows were fullscreen."""
    windows = chromium_windows(run)
    try:
        mark.write_text("".join(window + "\n" for window in windows))
    except OSError:
        pass
    fullscreen = [window for window in windows if "FULLSCREEN" in run(["xprop", "-id", window, "_NET_WM_STATE"])]
    if windows and os.path.exists(tool):
        run(["python3", tool, "standard"])
        sleep(1)
        run(["python3", tool, "standard"])
    else:
        for window in fullscreen:
            run(["xdotool", "windowactivate", "--sync", window, "key", "--window", window, "F11"])
    return len(fullscreen)


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


#: The resolver's "this name does not exist" — an office with no link. Any other failure is "not known now".
_NO_SUCH_NAME = {getattr(socket, n) for n in ("EAI_NONAME", "EAI_NODATA") if hasattr(socket, n)}


def _resolve(name: str):
    """The name's addresses; an empty set when the name does not exist (no link here), and None when the
    answer is not known now (a transient failure: the last good answer stands, as in gate.mjs)."""
    try:
        return {info[4][0] for info in socket.getaddrinfo(name, None)}
    except socket.gaierror as error:
        return set() if error.errno in _NO_SUCH_NAME else None
    except (OSError, UnicodeError):
        return None


def _address(value: str) -> str:
    """`::ffff:10.0.0.5` (an IPv4 peer on a dual-stack socket) and `10.0.0.5` are one address."""
    value = str(value or "").strip()
    return value[7:] if value.lower().startswith("::ffff:") and "." in value else value


class Peers:
    """The link's addresses (LINK_PEERS), asked of Docker's resolver and asked again every PEER_TTL_S;
    an address not among them asks again at most every PEER_MISS_S (a link proxy recreated a moment
    ago). A name that does not exist — an office with no link — admits nobody; a failure that only means
    "not known now" keeps the last good answer. ONE look at a time, outside the lock, and only the very
    first is waited for (every request then waits for it, as gate.mjs awaits its refresh): after that a
    look runs beside the requests, because every file of the live view passes this gate and a slow
    resolver must hold none of them."""

    def __init__(self, names=LINK_PEERS, resolve=_resolve, clock=time.monotonic, spawn=None):
        self._names, self._resolve, self._clock = tuple(names), resolve, clock
        self._spawn = spawn or (lambda look: threading.Thread(target=look, name="browser42-peers", daemon=True).start())
        self._lock = threading.Lock()
        self._first = threading.Event()
        self._by_name, self._known, self._at, self._looking = {}, frozenset(), None, False

    def _look(self) -> None:
        try:
            found = {}
            for name in self._names:
                answer = self._resolve(name)
                found[name] = (self._by_name.get(name, frozenset()) if answer is None
                               else frozenset(_address(a) for a in answer))
            with self._lock:
                self._by_name, self._known, self._at = found, frozenset().union(*found.values()), self._clock()
        finally:
            with self._lock:
                self._looking = False
            self._first.set()

    def admits(self, address: str) -> bool:
        address = _address(address)
        if not address:
            return False
        with self._lock:
            first = self._at is None
            age = None if first else self._clock() - self._at
            look = not self._looking and (first or age > PEER_TTL_S
                                          or (address not in self._known and age > PEER_MISS_S))
            if look:
                self._looking = True
        if look and first:
            self._look()
        elif look:
            self._spawn(self._look)
        elif first:
            self._first.wait(PROVIDER_TIMEOUT_S)          # another request is making the first look
        with self._lock:
            return address in self._known


PEERS = Peers()


def provider_ask(endpoint: str, headers) -> tuple:
    """Ask the identity provider what Caddy would have asked it — the request's own headers (its cookie,
    its Host, the X-Forwarded-* the gate writes), minus the ones that describe a connection and the
    gate's own — and return its answer whole: (status, headers, body). A 302 to the sign-in, with the
    state cookie it sets, reaches the person exactly as it did when Caddy asked the provider itself
    (Caddy's forward_auth passed the request's own Host through, and so does this)."""
    parts = urlsplit(endpoint)
    sent = {name: value for name, value in headers.items()
            if (name.lower() == "host" or name.lower() not in HOP_BY_HOP)
            and not name.lower().startswith("x-browser42-")}
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=PROVIDER_TIMEOUT_S)
    try:
        connection.request("GET", parts.path + (f"?{parts.query}" if parts.query else ""), headers=sent)
        response = connection.getresponse()
        body = response.read()
        return response.status, [(k, v) for k, v in response.getheaders()
                                 if k.lower() not in HOP_BY_HOP and "\r" not in v and "\n" not in v], body
    except (OSError, http.client.HTTPException, ValueError) as error:
        # ValueError: a header http.client will not send (a CR or LF in it) — refused, and never quoted
        said = type(error).__name__ if isinstance(error, ValueError) else str(error)
        print(f"[handoff] gate: the identity provider at {parts.netloc} did not answer ({said})",
              file=sys.stderr, flush=True)
        return 502, [("Content-Type", "text/plain; charset=utf-8")], (
            f"browser42: the office's identity provider ({parts.netloc}) did not answer — this door "
            f"stays shut until it does\n").encode("utf-8")
    finally:
        connection.close()


def gate_answer(headers, peers=None, ask=provider_ask, env=None) -> tuple:
    """The gate's one decision: the link, by its address, is in (it was signed in at its own office's
    edge); anybody else is the provider's question, asked with their own cookie. (status, headers, body)."""
    if (PEERS if peers is None else peers).admits(headers.get(PEER_HEADER, "")):
        return 200, [("Cache-Control", "no-store")], b""
    identity = ((os.environ if env is None else env).get("DGO_IDENTITY")
                or headers.get(IDENTITY_HEADER, "") or "authentik").strip()
    endpoint = PROVIDERS.get(identity)
    if not endpoint:
        return 502, [("Content-Type", "text/plain; charset=utf-8")], (
            f"browser42: DGO_IDENTITY={identity!r} names no identity provider this door knows "
            f"({', '.join(sorted(PROVIDERS))}) — it stays shut rather than open\n").encode("utf-8")
    return ask(endpoint, headers)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        route = self.path.split("?", 1)[0]
        if route == "/healthz":
            self._json(200, {"ok": True, "service": "browser42-handoff"})
            return
        if not TOKEN or not hmac.compare_digest(self.headers.get(TOKEN_HEADER, ""), TOKEN):
            self._json(403, {"ok": False, "error": {
                "code": "forbidden",
                "message": "the hand-off is reached through the office's edge (Caddy /handoff/*), which carries its token"}})
            return
        if route == "/gate":
            status, headers, body = gate_answer(self.headers)
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route in ("/handoff", "/handoff/"):
            self._json(200, {"ok": True, "handoffs": read_records()})
            return
        slug = slug_from_path(self.path)
        if not slug:
            self._json(404, {"ok": False, "error": {"code": "not_found", "message": "GET /handoff/<slug>"}})
            return
        record = group_record(slug)
        if record is None and waiting(slug):
            # `bbox b42 open` records the hand-off BEFORE it wakes the browser and opens the tab, so the
            # person is brought here at once (a cold browser takes up to 69 s): until the tab is there,
            # the page says so and reloads itself into it — never a 404 in front of him (DGO-1336). It
            # does NOT wake the browser itself: the opener is waking it, and two get_or_launch calls at
            # once are two Chromes (Waker). The manifest appears once the browser is up and the tab open.
            self._html(200, waking_page(slug), refresh=5)
            return
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


def cmd_record(args: list) -> int:
    """`bbox b42 handoff <slug> --done | --failed <sentence> [--episode <id>]` (and `bbox b42 open`, which
    writes `needed`). Exit 3 = superseded: the episode named is no longer the open one."""
    slug, state = (args + ["", ""])[:2]
    given = {"--for": None, "--sentence": None, "--episode": None}
    rest = args[2:]
    while rest:
        flag = rest.pop(0)
        if flag in given and rest:
            given[flag] = rest.pop(0)
        else:
            print(json.dumps({"ok": False, "error": {"code": "usage", "message":
                  "record <slug> needed|done|failed [--for <app>] [--sentence <text>] [--episode <id>]"}}))
            return 2
    try:
        record = write_record(slug, state, app=given["--for"], sentence=given["--sentence"], episode=given["--episode"])
    except Superseded as error:
        print(json.dumps({"ok": False, "error": {"code": "superseded", "message": str(error)}}, ensure_ascii=False))
        return 3
    except RecordError as error:
        print(json.dumps({"ok": False, "error": {"code": "usage", "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "handoff": record}, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: list) -> int:
    verb = argv[1] if len(argv) > 1 else ""
    if verb == "link":
        return cmd_link(argv[2] if len(argv) > 2 else "")
    if verb == "record":
        return cmd_record(list(argv[2:]))
    if verb == "list":
        print(json.dumps({"ok": True, "handoffs": read_records()}, ensure_ascii=False, sort_keys=True))
        return 0
    if verb == "serve":
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        print(f"browser42 handoff listening on :{PORT} ({'token set' if TOKEN else 'NO TOKEN — every hand-off refused'})", flush=True)
        server.serve_forever()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
