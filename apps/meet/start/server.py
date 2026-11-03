#!/usr/bin/env python3
"""meet-start — the host's door to the office's video meetings (apps/meet). It draws no meeting
screen: every screen a person meets is Jitsi's own. It only says who is a host.

It sits behind the office sign-in: the console's proxy (the tile, /a/meet/) and traefik's authentik
forward-auth on its own host both hand it the signed-in person in X-authentik-username / -name /
-email, and it believes them only from those two (MEET_TRUSTED_PEERS). Guests never come here: they
open the room's link on the meeting host, and wait there until a host is in (ENABLE_GUESTS).

    GET /            the tile → Jitsi's own welcome page (its card links here for a new meeting)
    GET /new         a new room, with this person as its host → Jitsi's own pre-join page
    GET /r/<room>    Jitsi's tokenAuthUrl ("I am the host"): a JWT for this person and this room,
                     back into Jitsi's room page as its moderator
    GET /recordings  the office's recordings (the one page here: Jitsi has no list of its own)
    GET /recordings/<session>/<file>.mp4
                     one recording, from the recorder's volume (read-only here), with byte ranges
                     so a browser can play it and seek
    GET /flow        meet-flow (fireplace 2026-10-28): every meeting that has one - its whole life on
                     one time axis (the recording, the side recordings, who spoke, every word, the
                     screens, topics, decisions, tasks, its documents)
    GET /flow/<room>/          that meeting's page (start/flow/index.html), and under it its files:
                     data.js, frames/, media/ (byte ranges), docs/ - from the meeting's flow folder; a meeting
                     with no flow yet gets the live page (start/flow/live.html): its captions as they arrive
    GET /flow/<room>/live.json the meeting now, from prosody's captions door: captions, who is in, recording
    GET /flow/ and /flow/<room>/   with MEET_FLOW_UI=v2 (the default): «פגישות» v2, the meetings app's one page
                     (start/flow/app.html), for all of them and for one; v1 = the two pages above, as they were
    GET /flow/api/meetings · /flow/api/search?q=…[&room=…] · /flow/api/inbox[?all=1]
                     every meeting as data (kept 15 s), a search of all that was said and decided, the
                     decisions and tasks not approved yet (all=1: every one of them, with its state)
    GET /flow/<room>/meeting.json · edits · items · uploads · uploads/<name>
    POST /flow/<room>/edits · items · uploads/<name>/meta     PUT /flow/<room>/uploads/<name> (in pieces)
                     what people add to a meeting, kept in MEET_FLOW_DATA: corrections to its transcript, the
                     approval of its decisions and tasks (an approved task is ONE Plane work item in MEET), more
                     tracks and texts. A write needs a signed-in person and X-Meet-Flow: 1 («פגישות» v2 below)
    GET /healthz     200 once the signing secret is present, 503 naming what is missing

A second listener (MEET_MACHINE_PORT, 8001) is the office's machines' door to the same recordings,
for the workflow that transcribes them (blueprint/n8n, DGO-834). The edge routes nothing to it, and
it answers only the containers MEET_MACHINE_PEERS names (n8n's):

    GET /api/recordings                  every finished recording: its audio (written by
                                         jibri/finalize.sh), who started it, its console link
    GET /api/recordings/<session>/<file>.ogg|.mp4
                                         the audio or the video itself
    POST /api/recordings/<session>/<file>.ogg|.mp4/to-plane  {url, fields}
                                         that file into Plane's store, through the form Plane
                                         signed for the recording's work item (posted only to
                                         MEET_PLANE_API_URL's /uploads)

…and the recorder's own door, for the watchdog that runs inside meet-jibri (jibri/watch.py, fireplace
2026-10-26), answered only to that container (MEET_RECORDER_PEERS) with the secret both hold
(MEET_RECORDER_WATCH_SECRET): the two things it cannot reach from meet-net itself.

    POST /api/recorder/health            {state: degraded|ok, title, body, session, room} → one
                                         notification per recording in the office's notice centre
                                         (MEET_NOTIFY_URL, source meet-recorder), updated as it goes
    POST /api/recorder/captions?language=auto|he|en   a 30-s WAV → the office's transcriber
                                         (MEET_SPEECH_URL /transcribe, synchronous for short audio;
                                         `auto` = the whisper model, as spoken; `he` = ivrit) → {text}

…and two threads of its own (fireplace, 2026-10-27): every ended meeting's live captions (prosody's
/meet-captions door) go to Plane — a comment on the recording's item, or an item of their own for a
meeting with no recording — and a watch that tells the owner (the notice centre, source meet-health)
when a meeting is not being recorded, the bridge is overloaded, a meeting service does not answer, no
recorder is there, or the machine runs out of memory or disk.

Standard library only; its one state is what people add to a meeting («פגישות» v2, MEET_FLOW_DATA). The token is HS256 over MEET_JWT_SECRET, the secret
prosody verifies with (JWT_APP_ID dgo, audience jitsi). It names one room and lasts MEET_TOKEN_HOURS.
"""
import array
import base64
import calendar
import collections
import datetime
import hashlib
import hmac
import html
import json
import math
import os
import re
import secrets
import socket
import string
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = os.environ.get("MEET_JWT_SECRET", "")
MEET_HOST = os.environ.get("MEET_HOST", "meet.localhost").strip().rstrip("/")
try:
    # Short on purpose: the token rides in the XMPP websocket's query string, which the edge's access
    # log keeps. It is checked when a person joins; a longer meeting is not cut off by it.
    TOKEN_HOURS = max(0.25, min(24.0, float(os.environ.get("MEET_TOKEN_HOURS", "4"))))
except ValueError:
    TOKEN_HOURS = 4.0
# Who may hand this door a signed-in person. The X-authentik-* headers are the edge's word, and the
# edge strips any a browser sent; a request that did not come through it (another container on the
# shared network) could write them itself. So only the edge and the console (whose proxy carries the
# edge's headers to the tile) are believed; anyone else is not signed in.
TRUSTED = [h.strip() for h in os.environ.get("MEET_TRUSTED_PEERS", "traefik,console").split(",") if h.strip()]
_trusted_cache = {"at": 0.0, "ips": set()}
PORT = int(os.environ.get("MEET_START_PORT", "8080"))
RECORDINGS = os.path.realpath(os.environ.get("MEET_RECORDINGS", "/recordings/recordings"))
# The machines' door: which containers may read the recordings through it, and what it tells them.
MACHINE_PORT = int(os.environ.get("MEET_MACHINE_PORT", "8001"))
MACHINES = [h.strip() for h in os.environ.get("MEET_MACHINE_PEERS", "").split(",") if h.strip()]
_machine_cache = {"at": 0.0, "ips": set()}
# Of those, the link door (DGO-945): a request from it crossed a link, and the door wrote the office it
# came from (x-dgo-office, the peer's own claim removed). Only the office Meet's workflows run in is
# let in that way (hooks/prepare, from `workflows:`); with none named, no linked office is.
LINK_PEERS = [h.strip() for h in os.environ.get("MEET_LINK_PEERS", "").split(",") if h.strip()]
_link_cache = {"at": 0.0, "ips": set()}
WORKFLOWS_OFFICE = os.environ.get("MEET_WORKFLOWS_OFFICE", "").strip().lower()
# The people whose recordings are tests (DGO-959): the machines' door and the watcher never hand them
# to the workflow, so a test call on this office becomes no work item in the owner's Plane. Their
# recordings stay in the people's list until the test moves them out.
QUIET = {u.strip() for u in os.environ.get("MEET_QUIET_INITIATORS", "qa-host").split(",") if u.strip()}
CONSOLE_URL = os.environ.get("MEET_CONSOLE_URL", "").strip().rstrip("/")
PLANE_API = os.environ.get("MEET_PLANE_API_URL", "").strip().rstrip("/")
# An office whose Plane is its OWN (no link door to sign the call in) names the key here; empty =
# the link door signs it, as on vps1 (FPG, 2026-10-26).
PLANE_KEY = os.environ.get("MEET_PLANE_API_KEY", "").strip()
# The recorder's watchdog (jibri/watch.py): which container it is, the secret it shows, where the
# notice centre and the transcriber answer. Empty peers or secret: the door is shut.
RECORDER_PEERS = [h.strip() for h in os.environ.get("MEET_RECORDER_PEERS", "").split(",") if h.strip()]
_recorder_cache = {"at": 0.0, "ips": set()}
RECORDER_SECRET = os.environ.get("MEET_RECORDER_WATCH_SECRET", "").strip()
NOTIFY_URL = os.environ.get("MEET_NOTIFY_URL", "").strip().rstrip("/")
SPEECH_URL = os.environ.get("MEET_SPEECH_URL", "").strip().rstrip("/")


def _plane_headers(h: dict) -> dict:
    if PLANE_KEY:
        h["X-API-Key"] = PLANE_KEY
    return h
# DGO-907: the recordings' workflow is called the moment a recording ends (its webhook), and the
# recordings list links each recording to its Plane item. Empty: nothing is called.
WORKFLOW_HOOK = os.environ.get("MEET_WORKFLOW_HOOK", "").strip()
PLANE_WS = os.environ.get("MEET_PLANE_WORKSPACE", "bina").strip()
SOURCE = "meet-recording"            # the workflow's key for a recording's item (with session/file)
# meet-flow (fireplace 2026-10-28). The app is start/flow/ (one page for every meeting). A meeting's flow is a
# folder beside its recording, <session>/flow, or flows/<room> for a meeting recorded elsewhere, holding its
# flow.json ({room, title, started, session, ...}), data.js, frames/, media/ and docs/. The flow pipeline writes
# it; this door only reads it (the volume is read-only here) and only behind the office sign-in.
FLOW_APP = os.path.join(HERE, "flow")
# An open byte range (a player's «bytes=N-») is answered with at most this much: the console's proxy drops a response
# that streams for long (a 369 MB recording broke after ~10 s, fireplace 2026-10-28), and a player asks for the next
# piece by itself. 0 = the whole rest, as before.
try:
    MEDIA_CHUNK = max(0, int(os.environ.get("MEET_MEDIA_CHUNK", str(4 << 20))))
except ValueError:
    MEDIA_CHUNK = 4 << 20
FLOW_ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
FLOW_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json",
              ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
              ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
              ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
              ".mp4": "video/mp4", ".webm": "video/webm"}

# A room is what Jitsi's own room box accepts — Hebrew and spaces included; it refuses only these
# (and control characters). Jitsi lower-cases a name before it reaches the backend.
ROOM_REFUSED = re.compile(r"[/?&:\"'%#\x00-\x1f\x7f]")
# A name the backend spells exactly as the address does (Latin, digits, - _ .): the token can name
# that one room. Any other name is spelled differently inside XMPP, so its token names no room ("*")
# and stays the signed-in person's for its four hours.
ROOM_PLAIN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
# What Jibri writes: recordings/<session id>/<room>_<yyyy-mm-dd-hh-mm-ss>.mp4 (+ metadata.json).
# The room part is the room's name as XMPP spells it, so a Hebrew room arrives escaped (a name with
# %…): any character but a separator or a control one; recording_path still keeps every file inside
# the volume (realpath). Latin-only, which this was, left a Hebrew room's recording out of every list.
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
FILE_RE = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,220}\.mp4$")
# …and beside it, once jibri/finalize.sh is done: the same name in .ogg, the meeting's sound only.
AUDIO_RE = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,220}\.ogg$")
STAMP_RE = re.compile(r"^(?P<room>.+)_(?P<y>\d{4})-(?P<m>\d\d)-(?P<d>\d\d)-(?P<H>\d\d)-(?P<M>\d\d)-(?P<S>\d\d)\.mp4$")


def silences(folder, name):
    """The stretches of full silence jibri/finalize.sh measured in a recording's sound (DGO-959), as
    [[start, end], …] in seconds: [] when there are none, None when it has not measured them."""
    try:
        with open(os.path.join(folder, name[:-4] + ".silence.json"), encoding="utf-8") as f:
            got = json.load(f).get("stretches")
        return [[round(float(a), 1), round(float(b), 1)] for a, b in got][:50]
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def holes_of(folder, name):
    """The digital-zero holes jibri/finalize.sh measured in a recording's sound (the fpg103 damage):
    {runs, seconds, pct} or None when it has not measured them."""
    try:
        with open(os.path.join(folder, name[:-4] + ".holes.json"), encoding="utf-8") as f:
            got = json.load(f)
        return {"runs": int(got.get("runs") or 0), "seconds": float(got.get("seconds") or 0), "pct": float(got.get("pct") or 0),
                "long_runs": int(got.get("long_runs") or 0)}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def recordings(limit=50):
    """The recorder's files, newest first: what /recordings lists. Empty when the volume is."""
    found = []
    try:
        sessions = os.listdir(RECORDINGS)
    except OSError:
        return []
    for session in sessions:
        folder = os.path.join(RECORDINGS, session)
        if not SESSION_RE.fullmatch(session) or not os.path.isdir(folder):
            continue
        meta = {}
        try:
            with open(os.path.join(folder, "metadata.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        for name in os.listdir(folder):
            if not FILE_RE.fullmatch(name):
                continue
            try:
                st = os.stat(os.path.join(folder, name))
            except OSError:                                 # finalize.sh between its two mv's (a rebuilt mp4)
                continue
            m = STAMP_RE.match(name)
            people = [p.get("name") for p in (meta.get("participants") or []) if isinstance(p, dict) and p.get("name")]
            audio = name[:-4] + ".ogg"
            try:
                audio_bytes = os.path.getsize(os.path.join(folder, audio))
            except OSError:
                audio, audio_bytes = None, 0
            found.append({
                "session": session, "file": name, "bytes": st.st_size, "mtime": int(st.st_mtime),
                # the room as people wrote it (a Hebrew room's file name carries it escaped)
                "room": unquote(m.group("room") if m else name[:-4]),
                "started": (f"{m['y']}-{m['m']}-{m['d']} {m['H']}:{m['M']}" if m else
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))),
                "people": people[:12],
                # Jibri writes metadata.json when it finishes: no metadata yet = still recording
                "done": bool(meta),
                "audio": audio, "audio_bytes": audio_bytes,
                "initiator": ((meta.get("initiator") or {}).get("id") if isinstance(meta.get("initiator"), dict) else None),
                "silences": silences(folder, name),
                "holes": holes_of(folder, name),
            })
    found.sort(key=lambda r: r["mtime"], reverse=True)
    return found[:limit]


def flows():
    """Every meeting that has a meet-flow, newest first: its flow.json plus the folder it is in."""
    try:
        names = os.listdir(RECORDINGS)
    except OSError:
        return []
    folders = [os.path.join(RECORDINGS, s, "flow") for s in names if SESSION_RE.fullmatch(s) and s != "flows"]
    try:
        folders += [os.path.join(RECORDINGS, "flows", r) for r in os.listdir(os.path.join(RECORDINGS, "flows"))]
    except OSError:
        pass
    found = []
    for folder in folders:
        try:
            with open(os.path.join(folder, "flow.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        room = str(meta.get("room") or "").strip().lower() if isinstance(meta, dict) else ""
        if FLOW_ROOM_RE.fullmatch(room):
            found.append(dict(meta, room=room, folder=os.path.realpath(folder)))
    found.sort(key=lambda r: str(r.get("started") or ""), reverse=True)
    return found


def live_meeting(room: str):
    """The newest captions record of this room (one that is live first) and the room as it is now — or None."""
    rows = [m for m in (captions_door("/meetings") or []) if str(m.get("room") or "").strip().lower() == room]
    now = next((r for r in (captions_door("/rooms") or []) if str(r.get("room") or "").strip().lower() == room), None)
    doc = {}
    if rows:
        rows.sort(key=lambda m: (bool(m.get("live")), float(m.get("started") or 0)), reverse=True)
        doc = captions_door("/meetings/" + quote(str(rows[0]["id"]), safe="")) or {}
    if not doc.get("segments"):
        doc = with_server_captions(room, doc, now)         # no browser captions: the recorder's, and the recording
    if not doc and not now:
        return None
    keep = ("id", "started", "ended", "people", "attendees", "uncaptioned", "sessions", "segments", "words")
    out = {k: doc.get(k) for k in keep}
    out.update(room=room, live=bool(now) or bool(doc.get("live")), server_captions=bool(doc.get("server_captions")),
               now={k: now.get(k) for k in ("people", "hosts", "names", "recording", "failure", "since", "captioned_words")} if now else None)
    return out


def recording_start(name: str):
    """When a recording began (its file name's stamp, the office's local time), as epoch seconds; None if unnamed."""
    m = STAMP_RE.match(name)
    if not m:
        return None
    return time.mktime((int(m["y"]), int(m["m"]), int(m["d"]), int(m["H"]), int(m["M"]), int(m["S"]), 0, 0, -1))


# \u2500\u2500 the office's own words in the machine's text (fireplace, 2026-10-29, AUD-C5-002110) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Call 5 (fpg105): the live captions wrote \u00abDGO fee\u00bb as \u00abDGOP\u00bb, \u00ab\u05d3\u05d9 \u05d2'\u05d5\u05e4\u05d9\u00bb, \u00ab\u05d3\u05d9\u05d2'\u05d9 \u05d0\u05d5\u05e4\u05d9\u00bb, \u00ab\u05d3\u05d9\u05d2'\u05d9 \u05d0\u05d5 \u05e4\u05d9\u00bb, and \u00abOur share\u00bb
# as \u00ab\u05d0\u05d0\u05d5\u05d5\u05e8 \u05e9\u05d9\u05d9\u05e8\u00bb / \u00ab\u05d4\u05d5\u05d5\u05e8\u05e9\u05d9\u05d9\u05e8\u00bb; William asked why it says DGOP [0:19:32]. The office's speech service takes no word list
# (no prompt), so what it is known to mishear is put right after it: in the captions the recorder posts to the room
# (/api/recorder/captions answers the fixed text, which jibri/watch.py posts and writes to the .live.txt), in the server
# captions read back from a .live.txt, and in the first processing (the machine's own words kept beside it, \u00ab\u05de\u05e7\u05d5\u05e8\u00bb).
# A setting, not code: MEET_VOCAB_FILE (default start/vocab.json), {"terms": [{"say": "DGO fee", "heard": [...]}]};
# a Hebrew prefix stays and takes a hyphen (\u00ab\u05d1-DGO fee\u00bb), as the reviewed transcripts write it. Re-read when it changes.
# …and BEFORE the recogniser too (FPG-471, 2026-10-29): the same file's "prompt" — the office's English terms, as a
# list — goes with every live caption to the speech service as Whisper's initial prompt (apitools-asr `prompt`), so
# the model can spell them the office's way in the first place (measured: an English speaker's «Zelle», «chimney cap»);
# the rules above still put right what it misses (the owners' Hebrew «די ג'י אופי» is not changed by any prompt).
# A list, not a Hebrew sentence: that once made the model drop the first 8 s of a piece of call 5. Empty = none.
# A service from before the prompt ignores the field.
VOCAB_FILE = os.environ.get("MEET_VOCAB_FILE", "").strip() or os.path.join(HERE, "vocab.json")
_vocab = {"checked": 0.0, "stamp": None, "rules": [], "prompt": ""}
_vocab_lock = threading.Lock()


def _variant_re(heard: str) -> str:
    """A heard form as a pattern: the spaces, dots or hyphens between its parts may be there or not; an apostrophe may
    be ' \u05f3 or \u2019 (or missing); Latin letters in any case (the pattern is compiled IGNORECASE)."""
    out = []
    for part in re.split(r"[\s.\-]+", heard.strip()):
        if part:
            out.append("".join("['\u05f3\u2019]?" if c in "'\u05f3\u2019" else re.escape(c) for c in part))
    return r"[\s.\-]*".join(out)


def vocab_rules() -> list:
    """[(pattern, the office's spelling)], the longest heard form first; [] without a readable file. Checked every 30 s."""
    now = time.time()
    with _vocab_lock:
        if now - _vocab["checked"] < 30:
            return _vocab["rules"]
        _vocab["checked"] = now
        try:
            st = os.stat(VOCAB_FILE)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            _vocab.update(stamp=None, rules=[], prompt="")
            return []
        if stamp == _vocab["stamp"]:
            return _vocab["rules"]
        pairs, prompt = [], ""
        try:
            with open(VOCAB_FILE, encoding="utf-8") as f:
                doc = json.load(f)
            prompt = " ".join(str((doc.get("prompt") if isinstance(doc, dict) else "") or "").split())[:600]
            for term in (doc.get("terms") if isinstance(doc, dict) else None) or []:
                say = str((term or {}).get("say") or "").strip()
                for h in (term or {}).get("heard") or []:
                    if say and str(h).strip():
                        pairs.append((str(h).strip(), say))
            pairs.sort(key=lambda p: len(p[0]), reverse=True)
            # a Hebrew prefix (\u05d5 \u05d4 \u05d1 \u05dc \u05de \u05e9 \u05db, one or two of them) may be glued on, with or without a hyphen
            rules = [(re.compile(r"(?<![\w'\u05f3])(?P<pre>[\u05d5\u05d4\u05d1\u05dc\u05de\u05e9\u05db]{1,2}-?)?(?P<w>" + _variant_re(h) + r")(?![\w'\u05f3])",
                                 re.IGNORECASE), say) for h, say in pairs]
        except (OSError, ValueError, TypeError, AttributeError, re.error) as e:
            print(f"meet-start: the vocabulary {VOCAB_FILE} was not read: {e}", flush=True)
            rules = []
        _vocab.update(stamp=stamp, rules=rules, prompt=prompt)
        return rules


def vocab_prompt() -> str:
    """The vocabulary file's "prompt" (the office's terms for the recogniser, FPG-471); "" without one."""
    vocab_rules()
    return _vocab["prompt"]


def fix_terms(text):
    """The text with the office's words spelt the office's way (vocab_rules); the same text when nothing matched."""
    if not text or not isinstance(text, str):
        return text
    for rx, say in vocab_rules():
        text = rx.sub(lambda m, say=say: ((m.group("pre") or "").rstrip("-") + "-" + say) if m.group("pre") else say, text)
    return text


# \u2500\u2500 a meeting known by its recording alone (fireplace, 2026-10-29, CHAT-61 / CHAT-62) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Since 2026-10-27 no browser captions anyone (config.dgoCaptions.mode 'off': the voice stays in the office), so
# prosody's captions door opens no record of a meeting at all (it opens one at the first browser caption) \u2014 and a
# meeting it has no record of had no live captions on its page, no first processing and no row in \u00ab\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea\u00bb: fpg106
# (2026-10-28) was recorded twice and its page answered 404. The office's own captions are the recorder's
# (jibri/watch.py, MEET_LIVE_CAPTIONS=on): 30-s pieces of the meeting's sound, written beside the recording as
# <room>_<time>.live.txt, "[MM:SS] text" from the recording's start. So the recording is enough: while it records, its
# .live.txt is the meeting's live captions; once it is done, it is the meeting (its first processing: the video, the
# office's ivrit transcription of its sound, those captions). Nothing is written; QA's recordings stay out.
SERVER_CAPTIONS = "\u05db\u05ea\u05d5\u05d1\u05d9\u05d5\u05ea"            # a server caption's speaker: the meeting's mixed sound, nobody in particular
LIVE_LINE = re.compile(r"^\[(\d{1,4}):(\d\d)\]\s*(.*)$")


def recorded_seconds(rec: dict):
    """How long a recording is, as its watchdog measured it (<room>_<time>.capture.json), or None."""
    try:
        with open(os.path.join(RECORDINGS, rec["session"], rec["file"][:-4] + ".capture.json"), encoding="utf-8") as f:
            got = float(json.load(f).get("recorded_seconds") or 0)
        return got if got > 0 else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def live_txt_segments(rec: dict) -> list:
    """A recording's server captions (its .live.txt) as captions-door segments {t, name, text, final}, its words spelt
    the office's way (fix_terms: a .live.txt written before the vocabulary is read with it)."""
    t0 = recording_start(rec["file"])
    if t0 is None:
        return []
    out = []
    try:
        with open(os.path.join(RECORDINGS, rec["session"], rec["file"][:-4] + ".live.txt"), encoding="utf-8",
                  errors="replace") as f:
            raw = f.read(2 << 20)
    except OSError:
        return []
    for line in raw.splitlines():
        m = LIVE_LINE.match(line.strip())
        if m and m.group(3).strip():
            out.append({"t": round(t0 + int(m.group(1)) * 60 + int(m.group(2)), 1), "name": SERVER_CAPTIONS,
                        "text": fix_terms(m.group(3).strip()), "final": True})
    return out


def recorded_meeting(rec: dict, live: bool) -> dict:
    """A captions-door meeting made of one recording (the shape live_meeting reads): its start, its end once it is done,
    who was there (Jibri's metadata.json), and its server captions as the meeting's segments."""
    t0 = recording_start(rec["file"]) or float(rec.get("mtime") or 0)
    segs = live_txt_segments(rec)
    ended = None
    if not live:
        secs = recorded_seconds(rec)
        ended = t0 + secs if secs else float(rec.get("mtime") or t0)
    people = [str(p) for p in (rec.get("people") or []) if p]
    return {"id": "rec:" + rec["session"], "started": t0, "ended": ended, "live": live, "people": people,
            "attendees": [{"name": p, "captions": "server"} for p in people], "uncaptioned": [],
            "sessions": [rec["session"]], "segments": segs, "words": sum(len(s["text"].split()) for s in segs),
            "users": [], "server_captions": True}


def with_server_captions(room: str, doc: dict, now) -> dict:
    """The captions-door meeting `doc` of a room (or {} when the door has none), given the recorder's captions when the
    door has no words: the .live.txt of the recording it names; with no record at all, the room's recording itself \u2014
    the one being made while the room is live (written in the last ten minutes), else its newest finished one."""
    recs = {r["session"]: r for r in recordings(limit=300)}
    rec = next((recs[s] for s in (doc.get("sessions") or []) if s in recs), None)
    if rec is None and not doc:
        mine = sorted((r for r in recs.values() if str(r.get("room") or "").strip().lower() == room
                       and r.get("initiator") not in QUIET), key=lambda r: r["mtime"], reverse=True)
        if now:
            rec = next((r for r in mine if not r.get("done") and time.time() - float(r.get("mtime") or 0) < 600), None)
        else:
            rec = next((r for r in mine if r.get("done")), None)
        return recorded_meeting(rec, bool(now)) if rec else doc
    if rec is None:
        return doc
    segs = live_txt_segments(rec)
    if not segs:
        return doc
    return dict(doc, segments=segs, words=sum(len(s["text"].split()) for s in segs), server_captions=True)


_BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_first_cache = {}


def speech_job(audio_name: str, model: str = "ivrit"):
    """The speech service's finished job for this recording's audio (the recordings' workflow asks for it the moment a
    recording ends): its id, or None while there is none."""
    if not SPEECH_URL:
        return None
    try:
        with urllib.request.urlopen(f"{SPEECH_URL}/speechJobs?limit=100", timeout=8) as r:
            jobs = json.loads(r.read()).get("jobs") or []
    except (OSError, ValueError):
        return None
    for j in jobs:
        src, opt = j.get("source") or {}, j.get("options") or {}
        if j.get("status") == "completed" and src.get("name") == audio_name and (opt.get("model") or "") == model:
            return j.get("id")
    return None


# ── the office's second recogniser beside the first, and no translation in either (fireplace, 2026-10-29, MT-01) ──
# The recordings' workflow transcribes every recording twice (DGO-955): ivrit (Hebrew-tuned, language he) and whisper
# (multilingual, language auto) — never translated. The first processing showed ivrit only; whisper's words for the
# same moment now sit beside each line under «מקור» (it often writes the English words ivrit spells in Hebrew letters).
# Shlomo (S15 [09:38]): «לא צריך לתרגם פגישות». Whisper's known failure on a Hebrew stretch it took for English is to
# write it in English — a translation, not a transcript. Such a piece (English where ivrit heard Hebrew) is left out
# and said so in the line's notes; so are whisper's stock lines in a silent room (the workflow's own STOCK rule).
WHISPER_STOCK = {"תודה רבה", "תודה", "תודה רבה לכם", "thank you", "thanks", "you", "bye", "שלום", "תודה שצפיתם",
                 "כתוביות", "תרגום", "thank you for watching", "thanks for watching"}
_HEB = re.compile("[א-ת]")
_LAT = re.compile("[A-Za-z]")


def hebrew_share(text: str) -> float:
    """The share of Hebrew letters among a text's Hebrew and Latin letters (0 with neither)."""
    h, lat = len(_HEB.findall(text or "")), len(_LAT.findall(text or ""))
    return h / (h + lat) if h + lat else 0.0


def looks_translated(heard_he: str, heard_auto: str) -> bool:
    """True when the multilingual pass wrote English for a stretch the Hebrew pass heard as Hebrew: a translation."""
    return (len(_LAT.findall(heard_auto or "")) >= 8 and hebrew_share(heard_auto) <= 0.15
            and hebrew_share(heard_he) >= 0.6 and len(_HEB.findall(heard_he or "")) >= 6)


def second_pass(audio_name: str, offset: float):
    """(job id, [(start, end, text)]) of the whisper pass of a recording — ([], None) while there is none."""
    jid = speech_job(audio_name, "whisper")
    if not jid:
        return None, []
    try:
        with urllib.request.urlopen(f"{SPEECH_URL}/transcriptionResult?format=verbose_json&id={quote(jid)}", timeout=60) as r:
            doc = json.loads(r.read())
    except (OSError, ValueError):
        return None, []
    out = []
    for seg in doc.get("segments") or []:
        text = _BIDI.sub("", str(seg.get("text") or "")).strip()
        if not text or re.sub(r"[^\w\s֐-׿]", "", text).strip().lower() in WHISPER_STOCK:
            continue
        out.append((float(seg.get("start") or 0) + offset, float(seg.get("end") or 0) + offset, text))
    return jid, out


def with_second_pass(turns: list, segs: list) -> None:
    """Each turn of the Hebrew pass given what the multilingual pass heard over it (alts.whisper), unless that is a
    translation (looks_translated: left out, and said so)."""
    k = 0
    for t in turns:
        while k < len(segs) and segs[k][1] <= t["s"]:
            k += 1
        got = [txt for s, e, txt in segs[k:k + 12] if s < t["e"] and min(e, t["e"]) - max(s, t["s"]) >= min(1.0, 0.3 * (t["e"] - t["s"]))]
        if not got:
            continue
        auto = " ".join(got)
        mine = (t.get("alts") or {}).get("ivrit") or t["text"]
        if looks_translated(mine, auto):
            t["flags"].append("whisper wrote English for this Hebrew stretch — a translation, not a transcript: left out (MT-01)")
            continue
        if fix_terms(auto) != t["text"]:
            t.setdefault("alts", {})["whisper"] = auto


def first_pass(audio_name: str, offset: float):
    """The recording's transcription as meet-flow turns: one per segment, every word on the recording's clock (tenths
    of a second from the turn's start) and the words the recogniser was unsure of (confidence < 0.5); beside each, what
    the office's second recogniser heard (with_second_pass). Cached per pair of jobs."""
    jid = speech_job(audio_name)
    if not jid:
        return None, None
    wid = speech_job(audio_name, "whisper")
    if (jid, wid) in _first_cache:
        return jid, _first_cache[(jid, wid)]
    try:
        with urllib.request.urlopen(f"{SPEECH_URL}/transcriptionResult?format=verbose_json&id={quote(jid)}", timeout=60) as r:
            doc = json.loads(r.read())
    except (OSError, ValueError):
        return None, None
    turns = []
    for i, seg in enumerate(doc.get("segments") or []):
        words = [w for w in (seg.get("words") or []) if _BIDI.sub("", str(w.get("w") or "")).strip()]
        s0 = float(seg.get("start") or 0) + offset
        if words:
            toks = [_BIDI.sub("", str(w["w"])).strip() for w in words]
            text = " ".join(toks)
            wt = [max(0, round((float(w.get("start") or 0) + offset - s0) * 10)) for w in words]
            low = [k for k, w in enumerate(words) if float(w.get("confidence") if w.get("confidence") is not None else 1) < 0.5]
        else:
            text, wt, low = _BIDI.sub("", str(seg.get("text") or "")).strip(), None, []
        if not text:
            continue
        t = {"id": f"m{i:04d}", "s": round(s0, 2), "e": round(float(seg.get("end") or 0) + offset, 2), "who": "?", "text": text,
             "flags": ["ivrit turbo (the office's recogniser), not reviewed"]}
        fixed = fix_terms(text)
        if fixed != text:                      # the office's words (vocab.json); what the machine wrote stays one click away
            t.update(text=fixed, alts={"ivrit": text})
            t["flags"].append("office terms spelt by the vocabulary (start/vocab.json)")
            if wt and len(wt) != len(fixed.split()):
                wt, low = None, []             # the word times were the machine's words: they no longer line up
        if wt and len(wt) == len(t["text"].split()):
            t["w"] = wt
        if low:
            t["low"] = low
        turns.append(t)
    doc = None
    if wid:
        try:
            with_second_pass(turns, second_pass(audio_name, offset)[1])
        except (OSError, ValueError, TypeError, KeyError) as e:          # the second pass is a help, never a condition
            print(f"meet-start: the whisper pass of {audio_name} was not merged: {e!r}", flush=True)
    _first_cache.clear()                       # one meeting's text at a time: the box has 48 MB
    _first_cache[(jid, wid)] = turns
    return jid, turns


# ── the moments a screen was pointed at (fireplace, 2026-10-29, M5-T44) ───────────────────────────────────────────
# Shlomo, call 5 [1:41:39]: whenever someone says «here» («פה»), the shared screen's frame from that second belongs
# with the meeting; C1 [35:53]: every «צילום מסך» in a video call, automatically. The transcript knows the second each
# word was said (the recogniser's word times), so the moments are found in it: «צילום מסך» / «screenshot» (asked
# for: kind "shot") and «פה», «הנה», «כאן» (kind "here"), one moment per 15 s (call 5: 101 moments). The page draws
# each moment's frame from the recording and stores the ones people keep in the meeting's Drive folder; the list
# itself goes to Drive with the transcript (flow_to_drive), so whoever reads the meeting knows where to look.
HERE_WORDS = {"פה", "הנה", "כאן", "מפה", "לפה", "מכאן", "לכאן", "here"}
SHOT_PAIRS = {("צילום", "מסך"), ("צלם", "מסך"), ("תצלם", "מסך"), ("צילומי", "מסך"), ("צילום", "המסך")}
SHOT_WORDS = {"screenshot", "screenshots"}
MOMENT_MERGE = 15.0


def _word_key(w: str) -> str:
    return re.sub(r"[^\wא-ת]", "", fold(w)).lower()


def screen_moments(turns: list) -> list:
    """[{t, kind: shot|here, words, line, text}] of the turns, oldest first, one per MOMENT_MERGE seconds."""
    here, shot = {_word_key(w) for w in HERE_WORDS}, {_word_key(w) for w in SHOT_WORDS}
    pairs = {(_word_key(a), _word_key(b)) for a, b in SHOT_PAIRS}     # the words as fold() keeps them (final letters too)
    found = []
    for x in turns:
        text = str(x.get("text") or "")
        toks = text.split()
        if not toks:
            continue
        keys = [_word_key(w) for w in toks]
        wt = x.get("w") if isinstance(x.get("w"), list) and len(x["w"]) == len(toks) else None
        s = float(x.get("s") or 0)
        for k, key in enumerate(keys):
            kind = ("shot" if key in shot or (k + 1 < len(keys) and (key, keys[k + 1]) in pairs)
                    else "here" if key in here else None)
            if kind:
                found.append((round(s + (wt[k] / 10 if wt else 0), 1), kind, toks[k].strip(".,!?;:\"'״׳()"), x.get("id"), text))
    out = []
    for t, kind, word, line, text in sorted(found, key=lambda f: f[0]):
        if out and t - out[-1]["t"] < MOMENT_MERGE:
            last = out[-1]
            if kind == "shot":
                last["kind"] = "shot"
            if word not in last["words"]:
                last["words"].append(word)
            continue
        out.append({"t": t, "kind": kind, "words": [word], "line": line, "text": text[:160]})
    return out


def machine_flow(room: str):
    """The first processing of a meeting that ended and was recorded: the MEETING data of meet-flow's page, built from
    the recording (video, length) and its live captions (one paragraph per speaker, on the recording's clock). None
    while it is live, when it was not recorded, or when its recording is not finished."""
    doc = live_meeting(room)
    if not doc or doc.get("live"):
        return None
    recs = {r["session"]: r for r in recordings(limit=300)}
    rec = next((recs[x] for x in (doc.get("sessions") or []) if x in recs), None)
    if not rec or not rec.get("done"):
        return None
    t0 = recording_start(rec["file"]) or float(doc.get("started") or 0)
    dur = max(60.0, float(doc.get("ended") or 0) - t0)
    hues, colors, turns = ["sky", "lime", "olive", "plum"], {}, []
    rows = live_turns(doc)
    audio = re.sub(r"\.mp4$", ".ogg", rec["file"])
    jid, heard = first_pass(audio, 0.0)
    captions = []
    for i, x in enumerate(rows):
        start = max(0.0, float(x["t"]) - t0)
        nxt = max(start + 1.0, float(rows[i + 1]["t"]) - t0) if i + 1 < len(rows) else min(dur, start + 8.0)
        who = str(x.get("name") or "משתתף")
        colors.setdefault(who, hues[len(colors) % len(hues)])
        turns.append({"id": f"c{i:04d}", "s": round(start, 2), "e": round(nxt, 2), "who": who, "text": x["text"],
                      "flags": ["live caption, not reviewed" + ("" if x.get("final") else "; not final")]})
        captions.append({"s": round(start, 2), "e": round(nxt, 2), "text": f"{who}: {x['text']}"})
    if heard:
        # the recogniser's words are the transcript; a turn takes the name of the caption it overlaps most (the
        # captions are attributed by who was speaking), and the captions stay a lane of their own
        for t in heard:
            best, over = "?", 0.0
            for c in turns:
                if c["who"] == SERVER_CAPTIONS:          # the recorder's captions hear the whole room: nobody's name
                    continue
                o = min(t["e"], c["e"]) - max(t["s"], c["s"])
                if o > over:
                    best, over = c["who"], o
            t["who"] = best
            colors.setdefault(best, hues[len(colors) % len(hues)]) if best != "?" else None
        turns = heard
    else:
        captions = []
    people = [a.get("name") for a in (doc.get("attendees") or []) if isinstance(a, dict) and a.get("name")] or list(doc.get("people") or [])
    quiet = [n for n in (doc.get("uncaptioned") or []) if n]
    return {"meeting": {"id": room, "title": f"{room} · עיבוד ראשון", "duration": round(dur, 1),
                        "subtitle": f"{rec['started']} · {', '.join(people[:8])}",
                        "transcript_label": "תמלול מכונה (ivrit, לא נבדק)" if heard else "כתוביות חיות (מכונה)",
                        "facts": [["מה יש כאן", "ההקלטה והכתוביות החיות של הפגישה, מיד כשהסתיימה. העיבוד המלא (מזהה הדיבור הטוב ביותר, "
                                                "בדיקה, מסכים, נושאים, החלטות ומשימות) יחליף את זה בכתובת הזו."],
                                  ["הכתוביות", ("כתוביות השרת: הקול של כל הפגישה, בקטעים של 30 שניות, תומלל במשרד עצמו (שום קול לא "
                                               "יצא החוצה). הן לא יודעות מי דיבר, ומגיעות באיחור של דקה–שתיים"
                                               if doc.get("server_captions") else
                                               "כל משתתף מתמלל את עצמו בדפדפן; הן מגיעות באיחור של כדקה, אז שורה יכולה להופיע "
                                               "מעט אחרי הרגע שבו נאמרה" + (f". בלי כתוביות: {', '.join(quiet)}" if quiet else ""))]],
                        "docs": []},
            "colors": colors, "video": {"src": f"../../recordings/{rec['session']}/{rec['file']}", "offset": 0, "duration": round(dur, 1)},
            "audio": [{"id": "meet", "label": "הקלטת הפגישה", "src": None, "offset": 0, "duration": round(dur, 1)}],
            "frames": [], "screens": [], "floor": [], "presence": [], "turns": turns, "tail": [], "captions": captions,
            "topics": [], "decisions": [], "tasks": [], "questions": [], "likes": [], "insights": [],
            "moments": screen_moments(turns), "job": jid if heard else None, "people": people}


def flow_file(room: str, rest: str):
    """(the meeting's flow, one of its files) - the file only when it stays inside that flow's folder."""
    flow = next((f for f in flows() if f["room"] == room), None)
    if not flow:
        return None, None
    path = os.path.realpath(os.path.join(flow["folder"], rest))
    if not path.startswith(flow["folder"] + os.sep) or not os.path.isfile(path):
        return flow, None
    return flow, path


_items = {"at": 0.0, "ok": False, "map": {}, "project": ""}


def plane_items(max_age: float = 60.0) -> dict:
    """{"<session>/<file>": {"ref": "MEET-10", "path": "/#/m/<module>/…/issues/<id>"}} — the Plane
    item the workflow wrote for each recording (project MEET, external_source `meet-recording`),
    read through MEET_PLANE_API_URL (the link door signs the call in) at most once a minute. The
    path is the console's route to the item; the module is the Plane's host name there
    (`plane.hp-laptop`), as the workflow links it. `_items["ok"]` says the last read worked."""
    now = time.time()
    if not PLANE_API or now - _items["at"] < max_age:
        return _items["map"]
    _items["at"] = now
    base = f"{PLANE_API}/api/v1/workspaces/{PLANE_WS}"

    def get(path):
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=_plane_headers({})), timeout=10) as r:
            return json.load(r)

    def rows(x):
        return x if isinstance(x, list) else (x or {}).get("results") or []

    try:
        project = next((p for p in rows(get("/projects/?per_page=100")) if p.get("identifier") == "MEET"), None)
        found = {}
        # …and the one project the Plane relay writes in (MachineDoor.relay_plane)
        _items["project"] = str(project.get("id") or "") if project else ""
        if project:
            module = urlsplit(PLANE_API).hostname or "project-pln"
            cursor = ""
            for _ in range(20):                                      # 2,000 items at most
                page = get(f"/projects/{project['id']}/issues/?per_page=100"
                           + (f"&cursor={quote(cursor)}" if cursor else ""))
                for i in rows(page):
                    if i.get("external_source") == SOURCE and i.get("external_id"):
                        found[i["external_id"]] = {
                            "ref": f"MEET-{i.get('sequence_id')}",
                            "path": f"/#/m/{module}/{PLANE_WS}/projects/{project['id']}/issues/{i['id']}"}
                if not (isinstance(page, dict) and page.get("next_page_results") and page.get("next_cursor")):
                    break
                cursor = page["next_cursor"]
        _items.update(map=found, ok=True)
    except (OSError, ValueError) as e:
        _items["ok"] = False
        print(f"meet-start: Plane's items not read: {e}", flush=True)
    return _items["map"]


# `ok_at` starts at this door's start: a run this door began before a restart may still be going in
# n8n (its socket went, the run did not), so the workflow's clock waits as it does after a run.
_hook = {"want": None, "busy": False, "busy_since": 0.0, "ok_at": time.time()}
_hook_cv = threading.Condition()


def ask_workflow(reason: str, keys: list) -> None:
    """Ask for one run; asked while a run is going, it is ONE run more after that one."""
    with _hook_cv:
        if _hook["want"] is None:
            _hook["want"] = (reason, keys)
        _hook_cv.notify()


def call_workflow() -> None:
    """The one caller of the recordings' workflow (its webhook), so its runs come ONE AT A TIME:
    the webhook answers when the run ENDS, and this waits for it (a run that uploads a long meeting
    takes minutes) before it makes the next call. The machines' door says whether a
    call is going, since when, and when one last worked (`/api/recordings`): the workflow's own clock,
    the safety net, does nothing meanwhile, so two runs seldom write the same recording (a call that
    hangs is waited for twenty minutes, then the clock works). Nothing in the call is data the run
    depends on."""
    while True:
        with _hook_cv:
            while _hook["want"] is None:
                _hook_cv.wait()
            (reason, keys), _hook["want"] = _hook["want"], None
            _hook["busy"], _hook["busy_since"] = True, time.time()
        ok = False
        try:
            body = json.dumps({"reason": reason, "recordings": keys[:20]}).encode()
            req = urllib.request.Request(WORKFLOW_HOOK, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3600) as r:
                ok = 200 <= r.status < 300
                print(f"meet-start: the workflow ran ({reason}, {len(keys)}): {r.status}", flush=True)
        except Exception as e:                                       # noqa: BLE001 — the caller never dies
            print(f"meet-start: the workflow's hook did not answer ({reason}): {e}", flush=True)
        finally:
            with _hook_cv:
                _hook["busy"] = False
                if ok:
                    _hook["ok_at"] = time.time()
        if not ok:
            time.sleep(30)                                           # n8n down: not a call every second


def watch_recordings() -> None:
    """When the workflow runs (DGO-907, the owner: «triggred on new rec»):
      · a recording that ENDS (Jibri wrote its metadata, finalize.sh its sound) → now;
      · while a recording that ended in the last quarter hour has no item yet (its transcript is
        being made) → once a minute, so a short meeting's item lands a minute after its transcript.
        A longer one's transcript takes longer than that, and the five-minute run writes it: a
        recording that never gets an item (Plane refuses it) costs fifteen calls, not one a minute
        for hours;
      · otherwise every five minutes (the transcripts of long meetings, retries).
    The recordings seen when this starts are not «new» (they were there before): the second rule
    covers the recent ones among them. With Plane not answering, the second rule does not call. With
    no hook (MEET_WORKFLOW_HOOK empty) the workflow's clock runs it, and this only keeps the items'
    map fresh for the recordings list."""
    waiting_s, every_s, tick_s = 15 * 60, 60, 5 * 60
    seen, last, first = set(), 0.0, True
    while True:
        try:
            items = plane_items()
            now = time.time()
            ready = {r["session"] + "/" + r["file"]: r for r in recordings(limit=200)
                     if r["done"] and r["audio"] and r["initiator"] not in QUIET}
            fresh = [] if first else [k for k in ready if k not in seen]
            seen.update(ready)
            first = False
            waiting = [k for k, r in ready.items()
                       if _items["ok"] and k not in items and now - r["mtime"] < waiting_s]
            if WORKFLOW_HOOK and fresh:
                ask_workflow("ended", fresh)
                last = now
            elif WORKFLOW_HOOK and waiting and now - last >= every_s:
                ask_workflow("waiting", waiting)
                last = now
            elif WORKFLOW_HOOK and now - last >= tick_s:
                ask_workflow("tick", [])
                last = now
        except Exception as e:                                       # noqa: BLE001 — the watcher never dies
            print(f"meet-start: watching the recordings: {e}", flush=True)
        time.sleep(15)


def recording_path(session: str, name: str, audio: bool = False):
    """The file, only when both names are the recorder's shape and the path stays inside the volume.
    The audio beside a recording is served to the machines' door only (audio=True)."""
    if not (SESSION_RE.fullmatch(session) and (FILE_RE.fullmatch(name) or (audio and AUDIO_RE.fullmatch(name)))):
        return None
    path = os.path.realpath(os.path.join(RECORDINGS, session, name))
    if not path.startswith(RECORDINGS + os.sep) or not os.path.isfile(path):
        return None
    return path


def meet_base():
    """The meeting host as a browser reaches it: plain http on a .localhost office, https elsewhere."""
    host = MEET_HOST.split("://", 1)[-1]
    local = host == "localhost" or host.endswith(".localhost") or host.split(":")[0].endswith(".localhost")
    return ("http://" if local else "https://") + host, host, local


def b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def mint(person: dict, room: str, now: float | None = None) -> str:
    """One room, one person, moderator: what prosody's token_verification accepts."""
    now = int(now if now is not None else time.time())
    claims = {
        "iss": "dgo",
        "aud": "jitsi",
        "sub": "meet.jitsi",
        "room": room,
        "nbf": now - 60,
        "exp": now + int(TOKEN_HOURS * 3600),
        "context": {"user": {
            "id": person["username"],
            "name": person["name"] or person["username"],
            "email": person["email"],
            "moderator": True,
        }},
    }
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode())
    sig = b64(hmac.new(SECRET.encode(), head + b"." + body, hashlib.sha256).digest())
    return (head + b"." + body + b"." + sig).decode()


def new_room() -> str:
    """A name nobody guesses: the date, and six letters."""
    letters = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
    return time.strftime("bina-%y%m%d-") + letters


def page(name: str, values: dict) -> bytes:
    text = open(os.path.join(HERE, name), encoding="utf-8").read()
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text.encode("utf-8")


def peer_ips(names, cache) -> set:
    """The addresses these containers have now (re-read every 30 s: a recreate moves them)."""
    now = time.time()
    if now - cache["at"] > 30:
        ips = set()
        for name in names:
            try:
                ips.update(socket.gethostbyname_ex(name)[2])
            except OSError:
                pass
        cache.update(at=now, ips=ips)
    return cache["ips"]


def trusted_ips() -> set:
    """The addresses the edge and the console have now."""
    return peer_ips(TRUSTED, _trusted_cache)


def to_plane_store(file: str, url: str, fields: dict) -> tuple:
    """Put one recording in Plane's store through the form Plane signed for it (DGO-834: the owner,
    «upload the file to Plain»), the three steps Plane's own screen takes; the workflow asks for the
    form and tells Plane the file arrived, this sends the file, which only this container holds.
    The form names Plane's PUBLIC origin, which this office may not reach; its path (/uploads, the
    store's bucket, routed by project-pln's own Caddyfile) is posted to MEET_PLANE_API_URL, the address
    this office does reach Plane at, so nothing goes anywhere but this office's Plane. Returns
    (HTTP status, what to say): 413 without sending when the form's size range does not take the file."""
    try:
        target = urlsplit(url or "")
    except ValueError:
        return 400, "the form's address is not one"
    # the bucket itself, exactly: nothing else of Plane's is reached from here
    if not PLANE_API or target.path.rstrip("/") != "/uploads" or not isinstance(fields, dict) \
            or not all(isinstance(k, str) and isinstance(v, str) and '"' not in k and "\r" not in k + v
                       and "\n" not in k + v for k, v in fields.items()):
        return 400, "the form must be Plane's own (/uploads) and this office must know its Plane"
    size = os.path.getsize(file)
    try:
        policy = json.loads(base64.b64decode(fields.get("policy") or fields.get("Policy") or ""))
        top = max([c[2] for c in (policy.get("conditions") or []) if isinstance(c, list) and len(c) == 3
                   and str(c[0]).lower() == "content-length-range"] or [size])
        top = int(top)
    except (ValueError, TypeError, AttributeError):
        top = size
    if size > top:
        return 413, f"the file is {size} bytes and this Plane takes at most {top}"
    kind = "audio/ogg" if file.endswith(".ogg") else "video/mp4"
    edge = "dgo" + secrets.token_hex(12)
    head = b"".join(f'--{edge}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    # the object's name is the form's `key`; the part's own file name is not read (tasks.py does the same)
    head += (f'--{edge}\r\nContent-Disposition: form-data; name="file"; filename="file"\r\n'
             f"Content-Type: {kind}\r\n\r\n").encode()
    tail = f"\r\n--{edge}--\r\n".encode()

    def body():                                                # the file streams: it can be large
        yield head
        with open(file, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                yield chunk
        yield tail

    dest = PLANE_API + target.path + (f"?{target.query}" if target.query else "")
    req = urllib.request.Request(dest, data=body(), method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={edge}",
        "Content-Length": str(len(head) + size + len(tail))})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, "stored"
    except urllib.error.HTTPError as e:
        return e.code, e.read(300).decode("utf-8", "replace")
    except (OSError, ValueError) as e:
        return 502, f"the store did not answer: {e}"


def header(value) -> str:
    """A header as the edge wrote it. http.server decodes header bytes as latin-1 and authentik sends
    UTF-8, so a Hebrew name would arrive as mojibake; this undoes that one step."""
    raw = (value or "").strip()
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


class Door(BaseHTTPRequestHandler):
    server_version = "meet-start"

    def person(self):
        if self.client_address[0] not in trusted_ips():
            return None
        user = header(self.headers.get("X-authentik-username"))
        if not user:
            return None
        return {
            "username": user,
            "name": header(self.headers.get("X-authentik-name")),
            "email": header(self.headers.get("X-authentik-email")),
        }

    def send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, url: str):
        self.send(302, b"", "text/plain; charset=utf-8", {"Location": url})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/healthz":
            if not SECRET:
                return self.send(503, b"MEET_JWT_SECRET is empty: apps/meet/hooks/prepare mints it into .env\n",
                                 "text/plain; charset=utf-8")
            return self.send(200, b"ok\n", "text/plain; charset=utf-8")
        base = meet_base()[0]
        if path in ("/", "/index.html"):
            # the tile (CHAT-67, «one meetings app»): «פגישות», the meetings centre, to a signed-in person — its «פגישה
            # חדשה» and «פתיחה לפי שם» open Jitsi. MEET_HOME=jitsi (or nobody signed in): Jitsi's own welcome page, as before.
            # Served here, not redirected: its root is read off this address (…/a/meet/ in the console), as for /flow/.
            if path == "/" and MEET_HOME == "flow" and flow_v2():
                who = self.person()
                if who is not None:
                    return self.send(200, flow_shell(base, None, who))
            return self.redirect(base + "/")
        who = self.person()
        if who is None:
            return self.send(401, page("signin.html", {}))
        room = new_room() if path == "/new" else None
        m = re.fullmatch(r"/r/([^/]+)", path)
        if m:
            room = unicodedata.normalize("NFKC", m.group(1)).strip().lower()
            if not room or len(room) > 200 or ROOM_REFUSED.search(room):
                return self.redirect(base + "/")       # a name Jitsi itself would refuse: its welcome page
        if room:
            if not SECRET:
                return self.send(503, b"MEET_JWT_SECRET is empty\n", "text/plain; charset=utf-8")
            # Jitsi reads the token from the room's query string (its own tokenAuthUrl contract) and
            # leaves it out of every link it hands on (the invite dialog builds a clean one).
            claim = room if ROOM_PLAIN.fullmatch(room) else "*"
            return self.redirect(f"{base}/{quote(room, safe='')}?jwt={mint(who, claim)}")
        if path == "/recordings":
            rows, items, now = recordings(), _items["map"], time.time()
            has_flow = {f.get("session"): f["room"] for f in flows() if f.get("session")}
            for r in rows:
                if r["session"] in has_flow:
                    r["flow"] = has_flow[r["session"]]      # its meet-flow: /flow/<room>/
                # the recording's Plane item (the watcher keeps the map a minute fresh), opened in the
                # console the page is framed in; or «בתמלול…» while a recent one has none yet
                item = items.get(r["session"] + "/" + r["file"])
                if item:
                    r["item"] = {"ref": item["ref"], "url": (CONSOLE_URL or "") + item["path"]}
                elif r["done"] and r["audio"] and _items["ok"] and now - r["mtime"] < 6 * 3600:
                    r["pending"] = True
            cfg = {"meet": base, "recordings": rows}
            return self.send(200, page("recordings.html", {
                "CONFIG": html.escape(json.dumps(cfg, ensure_ascii=False)),
            }))
        m = re.fullmatch(r"/recordings/([^/]+)/([^/]+)", path)
        if m:
            file = recording_path(m.group(1), m.group(2))
            if not file:
                return self.send(404, b"not found\n", "text/plain; charset=utf-8")
            return self.send_file(file)
        if path in ("/flow", "/flow/") and flow_v2():
            return self.send(200, flow_shell(base, None, who))                 # «פגישות» v2: the app's one page
        if path in ("/flow", "/flow/"):
            rows = [{k: v for k, v in f.items() if k != "folder"} for f in flows()]
            if RECORDER_SECRET:
                # the meetings whose first processing is ready: ended, recorded, no flow folder yet, not QA's
                try:
                    have, recs = {f["room"] for f in rows}, {r["session"]: r for r in recordings(limit=300)}
                    for m in captions_door("/meetings") or []:
                        room = str(m.get("room") or "").strip().lower()
                        if m.get("live") or room in have or not FLOW_ROOM_RE.fullmatch(room):
                            continue
                        rec = next((recs[x] for x in (m.get("sessions") or []) if x in recs), None)
                        if not rec or not rec.get("done") or rec.get("initiator") in QUIET or time.time() - float(m.get("ended") or 0) > 14 * 86400:
                            continue
                        have.add(room)
                        rows.append({"room": room, "title": f"{room} · עיבוד ראשון", "started": rec["started"], "who": ", ".join(rec.get("people") or []),
                                     "length": f"{round((float(m.get('ended') or 0) - float(m.get('started') or 0)) / 60)} דק׳",
                                     "tags": [["הקלטה + כתוביות חיות — לפני העיבוד המלא", "text"]], "docs": []})
                    rows.sort(key=lambda r: str(r.get("started") or ""), reverse=True)
                except (OSError, ValueError):
                    pass
            live = []
            if RECORDER_SECRET:
                try:
                    live = [{"room": str(r.get("room") or ""), "people": r.get("people"), "names": r.get("names") or [],
                             "recording": r.get("recording"), "since": r.get("since")}
                            for r in (captions_door("/rooms") or []) if FLOW_ROOM_RE.fullmatch(str(r.get("room") or "").strip().lower())]
                except (OSError, ValueError):
                    live = []
            return self.send(200, page("flow/list.html", {
                "CONFIG": html.escape(json.dumps({"meet": base, "flows": rows, "live": live}, ensure_ascii=False)),
            }))
        if path in ("/flow/api/meetings", "/flow/api/search", "/flow/api/inbox"):
            return self.flow_api(path)                                         # «פגישות» v2: the meetings as data
        m = re.fullmatch(r"/flow/app/([a-z0-9_-]+\.(?:js|css))", path)          # start/flow/: the app and live.js
        if m:
            file = os.path.join(FLOW_APP, m.group(1))
            if not os.path.isfile(file):
                return self.send(404, b"not found\n", "text/plain; charset=utf-8")
            with open(file, "rb") as f:
                return self.send(200, f.read(), FLOW_TYPES[os.path.splitext(file)[1]])
        m = re.fullmatch(r"/flow/([^/]+)(/.*)?", path)
        if m:
            room, rest = m.group(1).strip().lower(), (m.group(2) or "").lstrip("/")
            if not FLOW_ROOM_RE.fullmatch(room):
                return self.send(404, b"not found\n", "text/plain; charset=utf-8")
            if m.group(2) is None:                  # its links are relative to the folder: /flow/<room>/
                return self.redirect(quote(room) + "/")
            if rest in ("transcript.txt", "transcript.vtt", "transcript.srt"):
                return self.flow_export(room, rest.rsplit(".", 1)[1])          # CHAT-63: the transcript as a file
            if rest in ("meeting.json", "edits", "items", "uploads") or rest.startswith("uploads/"):
                return self.flow_get(room, rest, base)                         # «פגישות» v2: the meeting's own
            if rest == "live.json":
                flow, _ = flow_file(room, "flow.json")
                if flow:                                 # processed: the page reloads into the full timeline
                    return self.send(200, b'{"flow": true}', "application/json")
                if not RECORDER_SECRET:
                    return self.send(503, b'{"error": "no captions door"}', "application/json")
                try:
                    if machine_flow(room):               # ended and recorded: the first processing is ready
                        return self.send(200, b'{"flow": true}', "application/json")
                except (OSError, ValueError):
                    pass
                try:
                    doc = live_meeting(room)
                except (OSError, ValueError) as e:
                    return self.send(503, json.dumps({"error": str(e)}).encode(), "application/json")
                if doc is None:
                    return self.send(404, b'{"error": "no such meeting"}', "application/json")
                return self.send(200, json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json")
            if rest in ("", "index.html") and flow_v2():
                return self.send(200, flow_shell(base, room, who))             # any valid room: «לפני הפגישה» too
            if rest in ("", "index.html"):
                flow, _ = flow_file(room, "flow.json")
                if not flow:
                    # not processed yet: the first processing once it ended and was recorded (the full page, its data
                    # built on request), the live page while it runs
                    try:
                        if RECORDER_SECRET and machine_flow(room):
                            return self.send(200, page("flow/index.html", {"ROOM": room}))
                        known = RECORDER_SECRET and live_meeting(room) is not None
                    except (OSError, ValueError):
                        known = False
                    if known:
                        return self.send(200, page("flow/live.html", {"ROOM": room, "MEET": html.escape(base)}))
                    return self.send(404, b"no meet-flow for this meeting yet\n", "text/plain; charset=utf-8")
                # every path in it is written from the app's root (flow/<room>/…): the console sets the base
                return self.send(200, page("flow/index.html", {"ROOM": room}))
            flow, file = flow_file(room, rest)
            if not file and not flow and rest == "data.js" and RECORDER_SECRET:
                try:
                    data = machine_flow(room)
                except (OSError, ValueError):
                    data = None
                if data:
                    return self.send(200, ("window.MEETING = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n").encode("utf-8"),
                                     "text/javascript; charset=utf-8")
            if not file:
                return self.send(404, b"not found\n", "text/plain; charset=utf-8")
            ext = os.path.splitext(file)[1].lower()
            return self.send_file(file, FLOW_TYPES.get(ext, "application/octet-stream"),
                                  "private, no-store" if ext in (".js", ".json", ".html") else "private, max-age=3600")
        return self.send(404, b"not found\n", "text/plain; charset=utf-8")

    # ── «פגישות» v2: the reads under /flow/api/ and /flow/<room>/, and every write (POST, PUT) ───────────────────
    def flow_json(self, code: int, doc, since=None) -> None:
        """A JSON answer; one built from `since` on while the store did not answer says so ("store": "unavailable")."""
        if since is not None and isinstance(doc, dict) and _store_state["told_at"] >= since:
            doc = dict(doc, store="unavailable")
        self.send(code, json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def flow_api(self, path: str):
        """GET /flow/api/meetings | search?q=…[&room=…] | inbox[?all=1]."""
        query, since = parse_qs(self.path.partition("?")[2]), time.time()

        def arg(key: str) -> str:
            return (query.get(key) or [""])[0].strip()
        try:
            if path == "/flow/api/meetings":
                return self.flow_json(200, flow_meetings()[0])
            if path == "/flow/api/inbox":
                return self.flow_json(200, flow_inbox(arg("all").lower() in ("1", "true", "yes")), since)
            q, room = arg("q"), arg("room").lower()
            if len(q) < 2 or not query_words(q):
                return self.flow_json(400, {"error": "q", "detail": "q: at least 2 characters, and a word in them"})
            if room and not FLOW_ROOM_RE.fullmatch(room):
                return self.flow_json(404, {"error": "no such room"})
            return self.flow_json(200, flow_search(q, room or None), since)
        except (OSError, ValueError, TypeError, KeyError) as e:
            print(f"meet-start: {path}: {e!r}", flush=True)
            return self.flow_json(503, {"error": "unavailable", "detail": str(e)[:200]})

    def flow_export(self, room: str, ext: str):
        """GET /flow/<room>/transcript.txt | .vtt | .srt: the meeting's transcript with every correction (lines and
        speakers) applied — what people read, as a file (export_text). 404 while the meeting has none."""
        try:
            doc = meeting_doc(room)
            body = export_text(room, doc, ext) if doc else None
        except (OSError, ValueError, TypeError, KeyError) as e:
            print(f"meet-start: /flow/{room}/transcript.{ext}: {e!r}", flush=True)
            return self.flow_json(503, {"error": "unavailable", "detail": str(e)[:200]})
        if not body:
            return self.send(404, "לפגישה הזו עוד אין תמלול\n".encode("utf-8"), "text/plain; charset=utf-8")
        return self.send(200, body.encode("utf-8"), EXPORT_TYPES[ext],
                         {"Content-Disposition": f"attachment; filename=\"{room}.{ext}\"; filename*=UTF-8''{quote(room)}.{ext}"})

    def flow_get(self, room: str, rest: str, base: str):
        """GET /flow/<room>/meeting.json | edits | items | uploads | uploads/<name>: the meeting's state, and what
        people added to it (with no store: empty lists, and no upload)."""
        try:
            if rest == "meeting.json":
                since = time.time()
                return self.flow_json(200, flow_meeting(room, base), since)
            try:
                if rest == "edits":
                    return self.flow_json(200, {"edits": edits_of(room)})
                if rest == "items":
                    return self.flow_json(200, {"items": items_of(room, strict=True)})
                if rest == "uploads":
                    return self.flow_json(200, {"uploads": uploads_of(room)})
            except StoreDown:                                   # the store down: an empty answer that says so
                return self.flow_json(200, {rest: {} if rest == "items" else [], "store": "unavailable"})
        except (OSError, ValueError, TypeError, KeyError) as e:
            print(f"meet-start: /flow/{room}/{rest}: {e!r}", flush=True)
            return self.flow_json(503, {"error": "unavailable", "detail": str(e)[:200]})
        # uploads/<name>: the name as one segment of the address (an escaped / stays in it), the file as stored
        segs = self.path.split("?", 1)[0].split("/")
        name = upload_name(unquote(segs[4])) if len(segs) == 5 and unquote(segs[3]) == "uploads" else None
        if name and store_kind() == "drive":
            return self.send_drive_file(room, name)
        file = store_file(room, "uploads", name) if name else None
        if not file or not os.path.isfile(file):
            return self.send(404, b"not found\n", "text/plain; charset=utf-8")
        return self.send_file(file, UPLOAD_TYPES.get(os.path.splitext(file)[1].lower(), "application/octet-stream"),
                              "private, no-store", disposition=disposition_of(name),
                              extra={"X-Content-Type-Options": "nosniff"})

    def send_drive_file(self, room: str, name: str):
        """A file of the meeting's Drive folder, streamed from Drive as it comes (GET /api/fs/content), with byte
        ranges: an open range is asked for as one MEDIA_CHUNK, as send_file answers one."""
        try:
            folder = drive_folder(room)
        except StoreDown:
            return self.send(503, b"the store does not answer\n", "text/plain; charset=utf-8")
        if not folder:
            return self.send(404, b"not found\n", "text/plain; charset=utf-8")
        rng = (self.headers.get("Range") or "").strip()
        open_range = re.fullmatch(r"bytes=(\d+)-", rng)
        if open_range and MEDIA_CHUNK:
            rng = f"bytes={open_range.group(1)}-{int(open_range.group(1)) + MEDIA_CHUNK - 1}"
        try:
            r = _drive_open("GET", "/api/fs/content?path=" + quote(f"{folder}/{name}"),
                            headers={"Range": rng} if rng else None, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code == 416:
                self.send_response(416)
                self.send_header("Content-Range", e.headers.get("Content-Range") or "bytes */0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if e.code == 404:
                return self.send(404, b"not found\n", "text/plain; charset=utf-8")
            return self.send(503, f"Drive answered {e.code}\n".encode(), "text/plain; charset=utf-8")
        except (OSError, ValueError):
            return self.send(503, b"the store does not answer\n", "text/plain; charset=utf-8")
        with r:
            self.send_response(206 if r.status == 206 else 200)
            self.send_header("Content-Type", UPLOAD_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream"))
            self.send_header("Accept-Ranges", "bytes")
            for h in ("Content-Length", "Content-Range"):
                if r.headers.get(h):
                    self.send_header(h, r.headers[h])
            self.send_header("Content-Disposition", disposition_of(name))
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command == "HEAD":
                return None
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return None          # the player seeked elsewhere and closed this range
        return None

    def do_POST(self):
        return self.flow_write()

    def do_PUT(self):
        return self.flow_write()

    def flow_write(self):
        """POST /flow/<room>/edits | items | uploads/<name>/meta, PUT /flow/<room>/uploads/<name>: a signed-in person
        (else 401), the header X-Meet-Flow: 1 (else 403 — the CSRF guard: a browser sends a header of its own
        cross-site only after a CORS preflight, and this door answers none), a room FLOW_ROOM_RE takes (else 404) and
        a store this door may write (else 503 {"error": "no store"}). Every other POST and PUT is answered as it was
        before this door had any: 501."""
        segs = [unquote(x) for x in self.path.split("?", 1)[0].split("/")]
        put, what = self.command == "PUT", None
        if len(segs) >= 4 and not segs[0] and segs[1] == "flow":
            if len(segs) == 4 and not put and segs[3] in ("edits", "items"):
                what = segs[3]
            elif len(segs) == 5 and put and segs[3] == "uploads":
                what = "upload"
            elif len(segs) == 6 and not put and segs[3] == "uploads" and segs[5] == "meta":
                what = "meta"
        if what is None:
            return self.send_error(501, "Unsupported method (%r)" % self.command)
        room = segs[2].strip().lower()
        who = self.person()
        if who is None:
            return self.flow_json(401, {"error": "sign in"})
        if (self.headers.get("X-Meet-Flow") or "").strip() != "1":
            return self.flow_json(403, {"error": "X-Meet-Flow: 1"})
        if not FLOW_ROOM_RE.fullmatch(room):
            return self.flow_json(404, {"error": "no such room"})
        if not store_ok():
            return self.flow_json(503, {"error": "no store"})
        try:
            if what == "upload":
                return self.flow_upload(room, who, segs[4])
            doc, refused = self.flow_body()
            if refused:
                return self.flow_json(*refused)
            if what == "edits":
                code, answer = add_edit(room, who, doc)
            elif what == "items":
                code, answer = change_item(room, who, doc)
            else:
                code, answer = upload_meta(room, upload_name(segs[4]), doc)
        except (OSError, StoreDown) as e:
            print(f"meet-start: meet-flow v2 could not write {self.path}: {e}", flush=True)
            return self.flow_json(503, {"error": "no store", "detail": str(e)[:200]})
        return self.flow_json(code, answer)

    def flow_body(self):
        """The JSON object a write carries: (it, None), or (None, (code, answer)) — 413 over 64 KB (not read), 400
        for anything but a JSON object sent as application/json with its Content-Length."""
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            length = -1
        if length > BODY_MAX:
            return None, (413, {"error": "too big", "detail": f"a JSON body is at most {BODY_MAX} bytes"})
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if length <= 0 or ctype != "application/json":
            return None, (400, {"error": "bad body",
                                "detail": "a JSON object, Content-Type: application/json, with its Content-Length"})
        try:
            doc = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, OSError):
            doc = None
        if not isinstance(doc, dict):
            return None, (400, {"error": "bad body", "detail": "a JSON object"})
        return doc, None

    def flow_upload(self, room: str, who: dict, raw: str):
        """PUT /flow/<room>/uploads/<name>, one piece of a file: Content-Range: bytes <a>-<b>/<total>, its body that
        piece (8 MiB at most) and in order (upload_piece); a file is MEET_FLOW_UPLOAD_MAX at most."""
        name = upload_name(raw)
        if not name:
            return self.flow_json(400, {"error": "bad name",
                                        "detail": "a name ending in one of " + " ".join(sorted(UPLOAD_KINDS))})
        rng = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", (self.headers.get("Content-Range") or "").strip())
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            length = -1
        if not rng or length < 0:
            return self.flow_json(400, {"error": "bad piece",
                                        "detail": "Content-Range: bytes <a>-<b>/<total>, and its Content-Length"})
        a, b, total = (int(x) for x in rng.groups())
        if length > UPLOAD_PIECE or total > UPLOAD_MAX:
            return self.flow_json(413, {"error": "too big",
                                        "detail": f"a piece is at most {UPLOAD_PIECE} bytes, a file {UPLOAD_MAX}"})
        if not a <= b < total or b - a + 1 != length:
            return self.flow_json(400, {"error": "bad piece",
                                        "detail": "the range, the total and the body's length disagree"})
        try:
            self.connection.settimeout(120)          # a sender that stops does not hold a thread (and the file) for ever
            code, answer = upload_piece(room, who, name, a, total, length, self.rfile.read)
        finally:
            try:
                self.connection.settimeout(None)
            except OSError:
                pass
        return self.flow_json(code, answer)

    def send_file(self, file: str, ctype: str = "", cache: str = "private, no-store", disposition: str = "", extra=None):
        """The recording itself (or a file of a meeting's flow: ctype, cache; or an upload: its disposition and
        extra headers); one byte range when the browser asks for it (play and seek)."""
        size = os.path.getsize(file)
        start, end, code = 0, size - 1, 200
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        if rng and size and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                if not rng.group(2) and MEDIA_CHUNK:
                    end = min(end, start + MEDIA_CHUNK - 1)      # an open range in pieces (MEDIA_CHUNK)
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype or ("audio/ogg" if file.endswith(".ogg") else "video/mp4"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Disposition", disposition or f'inline; filename="{os.path.basename(file)}"')
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(file, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return    # the player seeked elsewhere and closed this range
                left -= len(chunk)

    def log_message(self, fmt, *args):
        # one line per request; a token goes out only in a redirect's Location, which is not logged
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


class MachineDoor(Door):
    """The machines' door (MEET_MACHINE_PORT): the recordings as data, for the containers that
    MEET_MACHINE_PEERS names, and for nobody else. Nothing here needs a person, and nothing here mints."""
    server_version = "meet-start-machines"
    timeout = 120      # a caller that stops sending mid-request does not hold a thread for ever

    def refused(self) -> bool:
        """Answer 403 and say True unless this caller may use the door: one of the office's workflow
        containers, or — through the link door — the office Meet's workflows run in, and no other.

        The link door is NOT one of the workflow containers (MEET_MACHINE_PEERS leaves it out): it is
        let in by the office check alone. The two names are cached apart (30 s each), so before an
        address is admitted as a workflow container the link door's name is resolved afresh — a
        recreated dgo-net on an address an n8n container held a minute ago is checked as the link.
        And the office is ONE header: two `x-dgo-office` lines mean someone wrote one beside the
        door's, and nothing is believed."""
        ip = self.client_address[0]
        link = peer_ips(LINK_PEERS, _link_cache)
        machine = ip in peer_ips(MACHINES, _machine_cache)
        if machine and LINK_PEERS and ip not in link:
            link = peer_ips(LINK_PEERS, {"at": 0.0, "ips": set()})
        if ip in link:
            said = [v.strip().lower() for v in (self.headers.get_all("X-Dgo-Office") or [])]
            office = said[0] if len(said) == 1 else ""
            if not WORKFLOWS_OFFICE or office != WORKFLOWS_OFFICE:
                self.send(403, (f"through the link this door answers the office Meet's workflows run in only "
                                f"(MEET_WORKFLOWS_OFFICE={WORKFLOWS_OFFICE or '-'}), not {office or 'an unnamed one'}\n")
                          .encode("utf-8"), "text/plain; charset=utf-8")
                return True
            return False
        if not machine:
            self.send(403, b"this door answers the office's workflow containers only (MEET_MACHINE_PEERS)\n",
                      "text/plain; charset=utf-8")
            return True
        return False

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/healthz":
            return self.send(200, b"ok\n", "text/plain; charset=utf-8")
        if path.startswith("/api/recorder/"):
            return self.recorder(path)
        if self.refused():
            return
        if path == "/api/recordings":
            # a test's recording (MEET_QUIET_INITIATORS) is no work item: the workflow never sees it
            rows = [r for r in recordings(limit=1000) if r["initiator"] not in QUIET]
            for row in rows:
                row["video_url"] = (f"{CONSOLE_URL}/a/meet/recordings/{quote(row['session'])}/{quote(row['file'])}"
                                    if CONSOLE_URL else None)
            # …and whether this door runs the workflow (call_workflow): a call going now and since
            # when, the last that worked. The workflow's clock does nothing while they say so.
            with _hook_cv:
                hook = ({"busy": _hook["busy"], "busy_since": int(_hook["busy_since"]), "ok_at": int(_hook["ok_at"])}
                        if WORKFLOW_HOOK else None)
            # plane_relay: this door relays Plane at /api/plane (relay_plane), so a workflow that runs
            # elsewhere asks it there; a meet-start from before the relay does not say so
            body = json.dumps({"recordings": rows, "console": CONSOLE_URL or None, "plane_api": PLANE_API or None,
                               "plane_relay": True, "hook": hook}, ensure_ascii=False).encode("utf-8")
            return self.send(200, body, "application/json; charset=utf-8")
        m = re.fullmatch(r"/api/recordings/([^/]+)/([^/]+)", path)
        if m:
            file = recording_path(m.group(1), m.group(2), audio=True)
            if not file:
                return self.send(404, b"not found\n", "text/plain; charset=utf-8")
            return self.send_file(file)
        if path.startswith("/api/plane/"):
            return self.relay_plane("GET")
        return self.send(404, b"not found\n", "text/plain; charset=utf-8")

    def relay_plane(self, method: str):
        """/api/plane/api/v1/workspaces/<the office's workspace>/… → the same request to Plane, at
        MEET_PLANE_API_URL (DGO-945).

        The workflow writes the recordings' items wherever it runs — this office's n8n, or the n8n of
        the office that runs the automations (the HP) — and Plane takes it only through a door that
        signs the call in: the link's (`MEET_PLANE_API_URL`, the address hooks/prepare derives),
        never a bare call from n8n, which holds no key (Code nodes can read neither credentials nor
        the environment). So its Plane calls come here, the one container that holds that address,
        and go on to Plane exactly as sent, answered exactly as Plane answers (the workflow reads 404,
        409 and 400). Nothing is kept.

        What is relayed is what the workflow writes and nothing more, because the call arrives in
        Plane signed as THIS office: the list of the workspace's projects (read, to find MEET) and
        everything under project MEET — its labels, its items, their attachments. Any other project,
        the workspace's own settings, an escape or a dot segment is refused before Plane is asked."""
        raw_path, _, query = self.path.partition("?")
        m = re.fullmatch(r"/api/plane(/api/v1/workspaces/([a-z0-9-]+)(/projects/(?:([0-9a-f-]{36})/[A-Za-z0-9._~/-]*)?))",
                         raw_path)
        dots = m and any(seg in (".", "..") for seg in m.group(1).split("/"))
        if not m or m.group(2) != PLANE_WS or dots:
            return self.send(404, b"only project MEET of this office's Plane workspace is relayed here\n",
                             "text/plain; charset=utf-8")
        if not PLANE_API:
            return self.send(503, b"no Plane address (MEET_PLANE_API_URL is empty)\n", "text/plain; charset=utf-8")
        if m.group(4) is None:
            if method != "GET":
                return self.send(404, b"the projects of this workspace are read here, never written\n",
                                 "text/plain; charset=utf-8")
        else:
            plane_items()                        # which project is MEET: read at most once a minute
            if not _items["project"] or m.group(4) != _items["project"]:
                return self.send(404, b"only project MEET is relayed here\n", "text/plain; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 4 * 1048576:
            return self.send(400, b"a Plane request body is a JSON object of 4 MB at most\n", "text/plain; charset=utf-8")
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(PLANE_API + m.group(1) + (f"?{query}" if query else ""), data=body, method=method,
                                     headers=_plane_headers({"Content-Type": self.headers.get("Content-Type") or "application/json",
                                              "Accept": "application/json"}))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return self.send(r.status, r.read(), r.headers.get("Content-Type") or "application/json")
        except urllib.error.HTTPError as e:
            return self.send(e.code, e.read(), e.headers.get("Content-Type") or "application/json")
        except (OSError, ValueError) as e:
            return self.send(502, f"Plane did not answer: {e}\n".encode(), "text/plain; charset=utf-8")

    def do_PATCH(self):
        if self.refused():
            return
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/plane/"):
            return self.send(404, b"not found\n", "text/plain; charset=utf-8")
        return self.relay_plane("PATCH")

    def do_PUT(self):
        # the people's door writes «פגישות» v2 (Door.flow_write); this door answers a PUT as it always did
        self.send_error(501, "Unsupported method (%r)" % self.command)

    def recorder(self, path: str):
        """The recorder's door (/api/recorder/*): meet-jibri's watchdog, and nobody else — the caller
        is the recorder's container (MEET_RECORDER_PEERS, by address, as the workflow's are) AND shows
        the secret prosody's door takes (MEET_RECORDER_WATCH_SECRET). Everything here is a relay to a
        service meet-jibri cannot reach from meet-net: nothing is kept."""
        ip = self.client_address[0]
        if not RECORDER_PEERS or not RECORDER_SECRET:
            return self.send(503, b"the recorder's door is shut (MEET_RECORDER_PEERS / MEET_RECORDER_WATCH_SECRET)\n",
                             "text/plain; charset=utf-8")
        if ip not in peer_ips(RECORDER_PEERS, _recorder_cache):
            peer_ips(RECORDER_PEERS, {"at": 0.0, "ips": set()})     # a recreated recorder: look again
            if ip not in peer_ips(RECORDER_PEERS, _recorder_cache):
                return self.send(403, b"this door answers the recorder's container only (MEET_RECORDER_PEERS)\n",
                                 "text/plain; charset=utf-8")
        if not hmac.compare_digest(self.headers.get("Authorization") or "", "Bearer " + RECORDER_SECRET):
            return self.send(401, b"unauthorized\n", "text/plain; charset=utf-8")
        if self.command != "POST":
            return self.send(405, b"POST\n", "text/plain; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if path == "/api/recorder/health":
            if not 0 < length <= 65536:
                return self.send(400, b"a small JSON object\n", "text/plain; charset=utf-8")
            try:
                doc = json.loads(self.rfile.read(length))
            except (ValueError, OSError):
                doc = None
            if not isinstance(doc, dict) or not doc.get("title"):
                return self.send(400, b"{state, title, body, session, room}\n", "text/plain; charset=utf-8")
            code, said = self.notify(doc)
            return self.send(200 if code in (200, 201) else 502, json.dumps({"notify": code, "said": said}).encode(),
                             "application/json; charset=utf-8")
        if path == "/api/recorder/captions":
            if not 0 < length <= 8 * 1048576:
                return self.send(400, b"a WAV of at most 8 MB\n", "text/plain; charset=utf-8")
            audio = self.rfile.read(length)
            query = parse_qs(self.path.partition("?")[2])
            language = (query.get("language") or ["auto"])[0].strip().lower() or "auto"
            model = (query.get("model") or [""])[0].strip() or ("ivrit" if language == "he" else "whisper")
            code, body, ctype = self.transcribe(audio, language, model)
            return self.send(code, body, ctype)
        return self.send(404, b"not found\n", "text/plain; charset=utf-8")

    def notify(self, doc: dict) -> tuple:
        """One notification per recording (source meet-recorder, source_id the session): a warning
        while the recorder loses sound or picture, turned into an info line when it recovers. The
        notice centre upserts by (source, source_id), so the owner sees one row that tells the story."""
        if not NOTIFY_URL:
            return 503, "MEET_NOTIFY_URL is empty"
        state = str(doc.get("state") or "degraded")
        payload = json.dumps({
            "source": "meet-recorder",
            "source_id": str(doc.get("session") or doc.get("room") or "recorder"),
            "title": str(doc.get("title"))[:200],
            "body": str(doc.get("body") or "")[:2000],
            "level": "info" if state == "ok" else "warning",
            "link": f"{CONSOLE_URL}/a/meet/recordings" if CONSOLE_URL else "",
            "meta": {"state": state, "room": doc.get("room"), "session": doc.get("session")},
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(NOTIFY_URL + "/api/notifications", data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(200).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(200).decode("utf-8", "replace")
        except (OSError, ValueError) as e:
            return 502, f"the notice centre did not answer: {e}"

    def transcribe(self, audio: bytes, language: str, model: str) -> tuple:
        """One short segment to the office's transcriber, synchronously (its /transcribe answers inline
        under SPEECH_SYNC_MAX_SECONDS, 120 s; the watchdog sends 30 s). Answered as the transcriber
        answers: {text}, or its 429 with Retry-After when its queue is full."""
        if not SPEECH_URL:
            return 503, b"MEET_SPEECH_URL is empty\n", "text/plain; charset=utf-8"
        boundary = "meet" + secrets.token_hex(12)
        parts = []
        fields = [("language", language), ("model", model), ("response_format", "json")]
        if vocab_prompt():
            fields.append(("prompt", vocab_prompt()))      # the office's terms, before the first words (FPG-471)
        for name, value in fields:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"segment.wav\"\r\n"
                     f"Content-Type: audio/wav\r\n\r\n".encode() + audio + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        # Silero VAD on: a 30-s stretch of a meeting is half silence, where Whisper writes words that were never
        # said (measured on a real recording, 2026-10-27: fewer invented words, the same recall).
        req = urllib.request.Request(SPEECH_URL + "/transcribe?vad=true", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=230) as r:
                status, raw, ctype = r.status, r.read(), r.headers.get("Content-Type") or "application/json"
            if status == 200:
                # the office's own words (fix_terms, AUD-C5-002110): the watchdog posts and keeps the text it is answered
                try:
                    doc = json.loads(raw)
                    if isinstance(doc, dict) and isinstance(doc.get("text"), str):
                        fixed = fix_terms(doc["text"])
                        if fixed != doc["text"]:
                            doc["text"] = fixed
                            for seg in doc.get("segments") or []:
                                if isinstance(seg, dict) and isinstance(seg.get("text"), str):
                                    seg["text"] = fix_terms(seg["text"])
                            raw, ctype = json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
                except ValueError:
                    pass
            return status, raw, ctype
        except urllib.error.HTTPError as e:
            return e.code, e.read(2000), e.headers.get("Content-Type") or "application/json"
        except (OSError, ValueError) as e:
            return 502, f"the transcriber did not answer: {e}\n".encode(), "text/plain; charset=utf-8"

    def do_POST(self):
        """POST /api/recordings/<session>/<file>/to-plane {url, fields}: this recording (its video or
        its sound) into Plane's store, through the form Plane signed (to_plane_store). And POST
        /api/plane/…: a Plane request, relayed (relay_plane)."""
        path = unquote(self.path.split("?", 1)[0])
        if path.startswith("/api/recorder/"):
            return self.recorder(path)
        if self.refused():
            return
        if path.startswith("/api/plane/"):
            return self.relay_plane("POST")
        m = re.fullmatch(r"/api/recordings/([^/]+)/([^/]+)/to-plane", path)
        file = recording_path(m.group(1), m.group(2), audio=True) if m else None
        if not file:
            return self.send(404, b"not found\n", "text/plain; charset=utf-8")
        # a bad request is 400, never 413: the workflow reads 413 as "this Plane does not take the file"
        try:
            length = int(self.headers.get("Content-Length") or 0)
            form = json.loads(self.rfile.read(length)) if 0 < length <= 65536 else None
        except (ValueError, OSError):
            form = None
        if not isinstance(form, dict):
            return self.send(400, b"the form is sent as a small JSON object: {url, fields}\n", "text/plain; charset=utf-8")
        code, said = to_plane_store(file, str(form.get("url") or ""), form.get("fields"))
        body = json.dumps({"store": code, "said": said, "file": os.path.basename(file)}, ensure_ascii=False).encode("utf-8")
        return self.send(200 if code in (200, 201, 204) else (413 if code == 413 else 502), body,
                         "application/json; charset=utf-8")



# ── LIVE TRANSCRIPTS AND THE MEETINGS' WATCH (fireplace, 2026-10-27) ───────────────────────────────
# The owner: «if critical things stop working I should get an alert in the office's notifications app»,
# and every meeting's words must survive a recording that broke or never happened. Two threads, both
# reading prosody's door (prosody/mod_meet_captions.lua: the live captions every browser sends, and
# the rooms now) with the secret the recorder's door uses.
CAPTIONS_URL = os.environ.get("MEET_CAPTIONS_URL", "http://meet-prosody:5280/meet-captions").strip().rstrip("/")
PROSODY_HOST = os.environ.get("MEET_PROSODY_HTTP_HOST", "muc.meet.jitsi").strip()
JVB_STATS = os.environ.get("MEET_JVB_STATS_URL", "http://meet-jvb:8080/colibri/stats").strip()
JICOFO_URL = os.environ.get("MEET_JICOFO_URL", "http://meet-jicofo:8888").strip().rstrip("/")
AUTO_RECORD = os.environ.get("MEET_AUTO_RECORD", "1").strip() != "0"
LIVE_SOURCE = "meet-live"            # an item of its own: a meeting with no recording (or no item for it)
try:
    LIVE_WAIT_HOURS = max(0.5, float(os.environ.get("MEET_LIVE_WAIT_HOURS", "6")))
except ValueError:
    LIVE_WAIT_HOURS = 6.0


def captions_door(path: str, body=None):
    """prosody's captions door: GET (or POST a JSON body). None for an empty list (cjson writes null)."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(CAPTIONS_URL + path, data=data, method="POST" if data else "GET",
                                 headers={"Host": PROSODY_HOST, "Authorization": "Bearer " + RECORDER_SECRET,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def plane(method: str, path: str, body=None):
    """One call to the office's Plane (MEET_PLANE_API_URL, the key or the link door signs it in)."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{PLANE_API}/api/v1/workspaces/{PLANE_WS}{path}", data=data, method=method,
                                 headers=_plane_headers({"Content-Type": "application/json", "Accept": "application/json"}))
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def plane_issue(project: str, source: str, key: str):
    """The item Plane keeps under (external_source, external_id): it answers the item itself, or 404."""
    try:
        got = plane("GET", f"/projects/{project}/issues/?external_source={quote(source)}&external_id={quote(key, safe='')}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if isinstance(got, dict) and got.get("id"):
        return got
    rows = got if isinstance(got, list) else (got or {}).get("results") or []
    return next((i for i in rows if i.get("external_source") == source and i.get("external_id") == key), None)


def say(level: str, key: str, title: str, body: str, link: str = "", meta=None) -> None:
    """One row in the notice centre per (meet-health, key), updated as the story goes on."""
    if not NOTIFY_URL:
        return
    payload = json.dumps({"source": "meet-health", "source_id": key, "title": title[:200], "body": body[:2000],
                          "level": level, "link": link or (f"{CONSOLE_URL}/a/meet/recordings" if CONSOLE_URL else ""),
                          "meta": meta or {}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(NOTIFY_URL + "/api/notifications", data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read(100)
    except (OSError, ValueError) as e:
        print(f"meet-start: the notice centre did not take «{title[:60]}»: {e}", flush=True)


def live_turns(doc: dict) -> list:
    """The meeting's captions as turns: in time order, a loudspeaker's echo dropped (the same words
    from another person within seconds), one paragraph per speaker until someone else speaks."""
    segs = sorted((s for s in (doc.get("segments") or []) if str(s.get("text") or "").strip()), key=lambda s: s.get("t") or 0)
    kept = []
    for s in segs:
        w = set(str(s["text"]).split())
        if len(w) >= 4 and any(k["name"] != s.get("name") and abs((k.get("t") or 0) - (s.get("t") or 0)) < 8
                               and len(w & set(str(k["text"]).split())) >= 0.7 * len(w) for k in kept[-6:]):
            continue
        kept.append(s)
    turns = []
    for s in kept:
        text = str(s["text"]).strip()
        if turns and turns[-1]["name"] == s.get("name"):
            turns[-1]["text"] += " " + text
            turns[-1]["final"] = turns[-1]["final"] and bool(s.get("final"))
        else:
            turns.append({"t": s.get("t") or 0, "name": s.get("name") or "משתתף", "text": text, "final": bool(s.get("final"))})
    return turns


def live_html(doc: dict, marker: str) -> str:
    e = html.escape
    start = float(doc.get("started") or 0)
    turns = live_turns(doc)
    words = sum(len(t["text"].split()) for t in turns)
    minutes = max(0, int((float(doc.get("ended") or start) - start) // 60))
    people = ", ".join(doc.get("people") or []) or "—"
    missing = ", ".join(doc.get("uncaptioned") or [])
    out = ["<h3>📝 תמלול חי מהפגישה</h3>",
           "<p>נלקח בזמן הפגישה מהכתוביות של כל משתתף — הדפדפן של כל אחד זיהה את הקול שלו, ולכן כל משפט "
           "רשום על שם מי שאמר אותו. התמלול של ההקלטה (ivrit, אחרי הפגישה) הוא המסמך הקובע; זה מה שנשמע בזמן אמת.</p>",
           f"<p><strong>בכתוביות:</strong> {e(people)} · <strong>מילים:</strong> {words} · <strong>משך:</strong> {minutes} דק׳</p>"]
    if missing:
        out.append(f"<p><strong>⚠️ היו בפגישה בלי כתוביות</strong> (אפליקציה בטלפון, דפדפן שלא מזהה דיבור, או מיקרופון כבוי) — "
                   f"הדברים שלהם רק בהקלטה: {e(missing)}</p>")
    for t in turns:
        rel = max(0, int(t["t"] - start))
        unsure = "" if t["final"] else " <em>(המשפט האחרון לא הושלם בזיהוי)</em>"
        out.append(f"<p><strong>[{rel // 60:02d}:{rel % 60:02d}] {e(t['name'])}:</strong> {e(t['text'])}{unsure}</p>")
    out.append(f"<p><small>🆔 {e(marker)}</small></p>")
    return "".join(out)


_live_done = set()


def post_live_transcripts() -> None:
    """Each ended meeting's live captions, once, into Plane:
      · it was recorded → a comment on the recording's MEET item, once the workflow has written that
        item (after the transcriber: minutes to hours); no item within MEET_LIVE_WAIT_HOURS → below;
      · it was not recorded (one recorder: a second meeting at the same time; a recorder that failed)
        → an item of its own (meet-live, keyed by the meeting) and a warning in the notice centre.
    Plane is the record: a comment or an item already there (its 🆔 line) is never posted again. QA's
    meetings (a QUIET user signed in) are not posted."""
    if not (PLANE_API and RECORDER_SECRET):
        return
    meetings = captions_door("/meetings") or []
    plane_items()
    project = _items.get("project")
    if not project:
        return
    recs = {r["session"]: r for r in recordings(limit=300)}
    now = time.time()
    for m in meetings:
        mid = str(m.get("id") or "")
        if not mid or m.get("live") or not m.get("ended") or mid in _live_done:
            continue
        if now - float(m["ended"]) > 14 * 86400 or int(m.get("words") or 0) < 3:
            _live_done.add(mid)
            continue
        doc = captions_door("/meetings/" + quote(mid, safe=""))
        # No `users` at all: written before prosody named the signed-in people (2026-10-27 10:38), so nobody can tell
        # a QA meeting from the owner's — left alone (MEET-34 was such a test meeting, filed as «not recorded»).
        if "users" not in doc or set(doc.get("users") or []) & QUIET:
            _live_done.add(mid)
            continue
        marker = "live:" + mid
        body = live_html(doc, marker)
        rec = next((recs[s] for s in (doc.get("sessions") or []) if s in recs), None)
        if not rec and doc.get("sessions"):
            # it WAS recorded — the recording is just not in the list any more (moved, deleted): never «not recorded»
            _live_done.add(mid)
            continue
        if rec and rec.get("initiator") in QUIET:
            _live_done.add(mid)
            continue
        if rec:
            issue = plane_issue(project, SOURCE, rec["session"] + "/" + rec["file"])
            if issue:
                comments = plane("GET", f"/projects/{project}/issues/{issue['id']}/comments/?per_page=100")
                rows = comments if isinstance(comments, list) else (comments or {}).get("results") or []
                if not any(marker in str(c.get("comment_html") or "") for c in rows):
                    plane("POST", f"/projects/{project}/issues/{issue['id']}/comments/", {"comment_html": body})
                    print(f"meet-start: the live transcript of {mid} went onto MEET-{issue.get('sequence_id')}", flush=True)
                _live_done.add(mid)
                continue
            if now - float(m["ended"]) < LIVE_WAIT_HOURS * 3600:
                continue                                            # the workflow has not written it yet
        issue = plane_issue(project, LIVE_SOURCE, mid)
        if not issue:
            started = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(doc.get("started") or now)))
            issue = plane("POST", f"/projects/{project}/issues/", {
                "name": f"פגישה · {doc.get('room') or '—'} · {started} · תמלול חי" + ("" if rec else " (לא הוקלטה)"),
                "description_html": body, "external_source": LIVE_SOURCE, "external_id": mid})
            module = urlsplit(PLANE_API).hostname or "project-pln"
            link = f"{CONSOLE_URL}/#/m/{module}/{PLANE_WS}/projects/{project}/issues/{issue.get('id')}" if CONSOLE_URL else ""
            why = ("לא הוקלטה" if not rec else f"ההקלטה לא קיבלה פריט תוך {LIVE_WAIT_HOURS:g} שעות")
            say("warning", "live:" + mid, f"פגישה «{doc.get('room')}» {why} — התמלול החי נשמר (MEET-{issue.get('sequence_id')})",
                f"הפגישה {why}. מה שנאמר בה נשמר מהכתוביות החיות של המשתתפים, לפי דובר, בפריט MEET-{issue.get('sequence_id')}. "
                + (f"היו בה בלי כתוביות (רק אם הוקלטה): {', '.join(doc.get('uncaptioned') or [])}." if doc.get("uncaptioned") else ""),
                link, {"meeting": mid, "room": doc.get("room")})
            print(f"meet-start: the live transcript of {mid} became MEET-{issue.get('sequence_id')} ({why})", flush=True)
        _live_done.add(mid)


def live_to_plane() -> None:
    while True:
        try:
            post_live_transcripts()
        except Exception as e:                                       # noqa: BLE001 — the thread never dies
            print(f"meet-start: live transcripts to Plane: {e}", flush=True)
        time.sleep(60)


def get_json(url: str, timeout: float = 5):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
        return json.load(r)


def machine_now() -> dict:
    """The machine as the kernel sees it (a container's /proc/meminfo and /proc/pressure are the host's)."""
    out = {}
    try:
        with open("/proc/meminfo") as f:
            mem = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in f)}
        out["mem_mb"] = mem.get("MemAvailable", 0) // 1024
        out["swap_used_mb"] = (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) // 1024
    except (OSError, ValueError):
        pass
    try:
        with open("/proc/pressure/memory") as f:
            out["mem_pressure"] = float(f.readline().split("avg10=")[1].split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        st = os.statvfs(RECORDINGS)
        out["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
        out["disk_free_pct"] = round(100.0 * st.f_bavail / max(st.f_blocks, 1), 1)
    except OSError:
        pass
    return out


_watch = {"since": {}, "open": {}, "rooms": {}}


def meeting_problems(now: float) -> dict:
    """What is wrong now, as {key: (level, title, body, room node or None)}."""
    problems = {}
    rooms = None
    try:
        rooms = captions_door("/rooms") or []
    except (OSError, ValueError) as e:
        problems["service:prosody"] = ("error", "⚠️ שירות הפגישות (prosody) לא עונה",
                                       f"פגישות לא נפתחות ולא נכנסים אליהן; הכתוביות לא נשמרות. ({e})", None)
    jibri = None
    try:
        det = (get_json(JICOFO_URL + "/stats") or {}).get("jibri_detector") or {}
        jibri = int(det.get("available", det.get("count", 0)) or 0), int(det.get("count", 0) or 0)
    except (OSError, ValueError):
        pass
    try:
        with urllib.request.urlopen(JICOFO_URL + "/about/health", timeout=5) as r:   # 200 with an empty body
            r.read(100)
    except urllib.error.HTTPError as e:
        problems["service:jicofo"] = ("error", "⚠️ שירות הפגישות (jicofo) לא תקין", f"פגישות חדשות לא ייפתחו (health {e.code}).", None)
    except (OSError, ValueError) as e:
        problems["service:jicofo"] = ("error", "⚠️ שירות הפגישות (jicofo) לא עונה", f"פגישות חדשות לא ייפתחו. ({e})", None)
    stats = None
    try:
        stats = get_json(JVB_STATS)
    except (OSError, ValueError) as e:
        problems["service:jvb"] = ("error", "⚠️ גשר הווידאו לא עונה", f"אין קול ותמונה בפגישות. ({e})", None)
    if stats:
        stress = float(stats.get("stress_level") or 0)
        if stress >= 0.9:
            problems["bridge"] = ("error" if stress >= 1.2 else "warning", f"⚠️ גשר הווידאו בעומס ({stress:.2f})",
                                  f"{stats.get('participants')} משתתפים, {stats.get('endpoints_sending_video')} שולחים וידאו: "
                                  "איכות הווידאו יורדת והקול עלול להיקטע. עוד משתתפים או מצלמות יחמירו את זה.", None)
    if AUTO_RECORD and jibri is not None and jibri[1] == 0:
        problems["service:jibri"] = ("error", "⚠️ אין מקליט — פגישות לא יוקלטו",
                                     "jicofo לא רואה אף מקליט (Jibri). פגישות נפתחות, אבל לא מוקלטות; הכתוביות החיות עדיין נשמרות.", None)
    recorded = [r.get("room") for r in rooms or [] if r.get("recording") in ("on", "pending")]
    for r in rooms or []:
        if not AUTO_RECORD or int(r.get("people") or 0) < 1 or int(r.get("hosts") or 0) < 1:
            continue
        if r.get("recording") in ("on", "pending") or now - float(r.get("since") or now) < 90:
            continue
        if recorded:
            why = f"המקליט מקליט עכשיו את «{', '.join(recorded)}»: יש מקליט אחד, והוא מקליט פגישה אחת בכל רגע"
        elif r.get("failure"):
            why = f"ההקלטה נכשלה ({r['failure']})"
        elif jibri is not None and jibri[0] == 0:
            why = "אין מקליט פנוי"
        else:
            why = "ההקלטה לא התחילה"
        key = f"unrecorded:{r.get('node')}:{int(float(r.get('since') or 0))}"
        problems[key] = ("warning", f"⚠️ הפגישה «{r.get('room')}» לא מוקלטת",
                         f"{why}. מה שנאמר נשמר מהכתוביות החיות (למי שהן פועלות אצלו: {', '.join(n for n, s in (r.get('captions') or {}).items() if s in ('on', 'muted')) or 'אף אחד עדיין'}), "
                         "ויגיע ל-Plane כשהפגישה תסתיים.", r.get("node"))
        _watch["rooms"][key] = r.get("room")
    m = machine_now()
    if m.get("mem_mb") is not None and m["mem_mb"] < 300:
        problems["server:memory"] = ("error", f"⚠️ לשרת נגמר הזיכרון ({m['mem_mb']} MB פנויים)",
                                     "המקליט והגשר עלולים להיחנק או להיסגר. פגישה פעילה בסכנה.", None)
    if m.get("mem_pressure") is not None and m["mem_pressure"] > 25:
        problems["server:swap"] = ("warning", f"⚠️ השרת נחנק מזיכרון (לחץ {m['mem_pressure']:.0f}%)",
                                   f"swap בשימוש {m.get('swap_used_mb')} MB: הכול מאט, הקלטות עלולות לאבד קול.", None)
    if m.get("disk_free_gb") is not None and (m["disk_free_gb"] < 5 or m.get("disk_free_pct", 100) < 8):
        problems["server:disk"] = ("error", f"⚠️ הדיסק כמעט מלא ({m['disk_free_gb']} GB פנויים)",
                                   "הקלטה חדשה עלולה להיחתך או לא להישמר.", None)
    return problems


_holes_told = set()


def tell_recording_holes(now: float) -> None:
    """A recording that came out with holes in its sound (finalize.sh's holes.json, pct ≥ 1): told once, as an
    error — the meeting's words in those holes are gone, and the live transcript is where they still are. The notice
    names its own room only (FPG-281: a body that also said «fpg103», the incident it was modelled on, read as if the
    damage were in another meeting)."""
    for r in recordings(limit=20):
        h = r.get("holes")
        key = "holes:" + r["session"]
        if not h or key in _holes_told or now - r["mtime"] > 6 * 3600 or r.get("initiator") in QUIET:
            continue
        _holes_told.add(key)
        if h["pct"] >= 1:
            say("error", key, f"⚠️ ההקלטה של «{r['room']}» ({r['started']}) נפגעה: {h['pct']:.1f}% מהשמע חסר",
                f"נמצאו {h['runs']} חורים של שקט דיגיטלי ({h['seconds']:.0f} שניות) בהקלטה של «{r['room']}»: המקליט לא עמד בקצב. "
                + (f"ועוד {h['long_runs']} קטעים ארוכים (מעל 2 שניות) של שקט מוחלט — השתקה, או נזק גדול יותר. " if h.get("long_runs") else "")
                + "המילים שנאמרו בחורים לא בהקלטה ולא בתמלול שלה; הן בתמלול החי של הפגישה (Plane), אם הכתוביות פעלו.",
                meta={"session": r["session"], "holes": h})
            print(f"meet-start: told the owner: recording {r['session']} has {h['pct']:.1f} % holes", flush=True)


def watch_meetings() -> None:
    """Every 15 s: a problem that lasts 30 s becomes a notification (level warning/error) and, for a
    meeting that is not being recorded, a line in that room; when it ends, the same row says so."""
    while True:
        try:
            now = time.time()
            problems = meeting_problems(now)
            for key, (level, title, body, node) in problems.items():
                first = _watch["since"].setdefault(key, now)
                if key not in _watch["open"] and now - first >= 30:
                    _watch["open"][key] = (level, title, body, node)
                    say(level, key, title, body, meta={"state": "open"})
                    print(f"meet-start: told the owner: {title}", flush=True)
                    if node and RECORDER_SECRET:
                        try:
                            captions_door("/tell", {"node": node, "text": "⚠️ הפגישה הזו לא מוקלטת — " + body.split(". ")[0]
                                                    + ". הכתוביות החיות נשמרות כתמלול. · This meeting is NOT being recorded; the live captions are kept as its transcript."})
                        except (OSError, ValueError) as e:
                            print(f"meet-start: could not tell the room: {e}", flush=True)
            for key in list(_watch["since"]):
                if key in problems:
                    continue
                _watch["since"].pop(key, None)
                if key in _watch["open"]:
                    level, title, body, node = _watch["open"].pop(key)
                    if key.startswith("unrecorded:"):
                        still = any(r for r in (captions_door("/rooms") or []) if r.get("node") == node) if RECORDER_SECRET else False
                        if still:
                            say("info", key, "✅ " + title.replace("⚠️ ", "").replace("לא מוקלטת", "מוקלטת עכשיו"),
                                "ההקלטה התחילה (באיחור). מה שנאמר לפני כן נמצא בתמלול החי.", meta={"state": "resolved"})
                        else:
                            say("warning", key, title.replace("לא מוקלטת", "הסתיימה בלי הקלטה"),
                                body.split(". ")[0] + ". התמלול החי שלה נשלח ל-Plane.", meta={"state": "ended"})
                    else:
                        say("info", key, "✅ " + title.replace("⚠️ ", ""), "חזר לתקין.", meta={"state": "resolved"})
            tell_recording_holes(now)
        except Exception as e:                                       # noqa: BLE001 — the watch never dies
            print(f"meet-start: watching the meetings: {e}", flush=True)
        time.sleep(15)


# ── the recordings into «קבצים» (the office's Files): /פגישות/<date> · <room>/ ─────────────────────────────
# The owner (2026-10-28): Meet's recordings belong in Drive, under «פגישות» — the office's one place for
# files, where every agent reads them. A finished recording (its video, and the sound finalize.sh writes)
# is copied there once. Drive is asked first whether a file is there already, so nothing is kept here and
# a restart copies nothing twice. Only what recordings() lists — never flow/ or flows/ — and only meetings
# that STARTED from MEET_DRIVE_SINCE on (the file's stamp): the older ones are tests and repair copies,
# and which of them belong in Drive is decided by whoever repaired them. Streamed from the volume in 4 MB
# pieces (this container has 48 MB and a tenth of a core), one file at a time. A Drive that is not
# installed or not answering is asked again ten minutes later; the meetings never wait for it.
DRIVE_URL = os.environ.get("MEET_DRIVE_URL", "http://drive:8975").strip().rstrip("/")
DRIVE_PROFILE = os.environ.get("MEET_DRIVE_PROFILE", "admin").strip()
DRIVE_SINCE = os.environ.get("MEET_DRIVE_SINCE", "2026-10-28 15:00").strip()
DRIVE_FOLDER = "פגישות"
DRIVE_PIECE = 4 * 1024 * 1024


def _drive(method: str, path: str, body=None, data=None, headers=None, timeout=120):
    url = f"{DRIVE_URL}{path}{'&' if '?' in path else '?'}profile_id={quote(DRIVE_PROFILE)}"
    h = dict(headers or {})
    if body is not None:
        data, h["Content-Type"] = json.dumps({**body, "profile_id": DRIVE_PROFILE}).encode(), "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})


def _in_drive(path: str) -> bool:
    try:
        _drive("GET", "/api/fs?path=" + quote(path))
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def _to_drive_one(src: str, folder: str, name: str, mime: str) -> None:
    size = os.path.getsize(src)
    _, s = _drive("POST", "/api/uploads", {"size": size, "name": name, "mime": mime, "path": folder})
    sid, off = s["id"], 0
    with open(src, "rb") as f:
        while off < size:
            piece = f.read(DRIVE_PIECE)
            if not piece:
                raise OSError(f"{src} ended at {off} of {size} bytes")
            _drive("PATCH", f"/api/uploads/{sid}", data=piece, timeout=300,
                   headers={"Upload-Offset": str(off), "Content-Type": "application/offset+octet-stream", "Tus-Resumable": "1.0.0"})
            off += len(piece)
    for _ in range(240):                                   # the drive hashes and stores it: seconds, a minute for hours
        _, st = _drive("GET", f"/api/uploads/{sid}")
        if st.get("state") == "done":
            return
        if st.get("state") == "failed":
            raise OSError(st.get("error") or "the drive could not store it")
        time.sleep(5)
    raise OSError("the drive did not finish storing it in 20 minutes")


def to_drive() -> None:
    marked, quiet_until = False, 0.0
    while True:
        try:
            if time.time() >= quiet_until:
                # the mp4 is final once finalize.sh wrote the .ogg (written after the rebuild): before, it may be the one
                # with no index, which rebuild_moov.py replaces — copied early, the rebuilt one would never follow
                # (_in_drive). A recording whose finalize never wrote one is copied as it is after six hours.
                todo = [r for r in recordings(limit=500)
                        if r["done"] and r["initiator"] not in QUIET and r["started"] >= DRIVE_SINCE
                        and (r["audio"] or time.time() - r["mtime"] > 6 * 3600)]
                if todo and not marked:                    # «פגישות» is Meet's own folder there (no rename / move / trash)
                    _drive("POST", "/api/fs/mkdir", {"path": "/" + DRIVE_FOLDER, "system": DRIVE_FOLDER})
                    marked = True
                for r in todo:
                    folder = f"/{DRIVE_FOLDER}/{r['started'][:10]} · {r['room']}"
                    for name, mime in ((r["file"], "video/mp4"), (r["audio"], "audio/ogg")):
                        if not name or _in_drive(f"{folder}/{name}"):
                            continue
                        _to_drive_one(os.path.join(RECORDINGS, r["session"], name), folder, name, mime)
                        print(f"meet-start: copied {r['session']}/{name} into «קבצים» {folder}", flush=True)
        except Exception as e:                                       # noqa: BLE001 — the copier never dies
            print(f"meet-start: copying the recordings into «קבצים»: {e}", flush=True)
            quiet_until = time.time() + 600
        time.sleep(60)


_told = set()


def tell_flow_links() -> None:
    """Every meeting that a host from the office opened is told, once, where its meet-flow is: one line in the
    room's chat (prosody's /tell, «הקלטה»). QA's meetings (a QUIET user signed in) are not."""
    while True:
        try:
            if CONSOLE_URL:
                rooms = captions_door("/rooms") or []
                docs = {}
                for r in rooms:
                    room, node = str(r.get("room") or "").strip().lower(), r.get("node")
                    if not node or int(r.get("hosts") or 0) < 1 or not FLOW_ROOM_RE.fullmatch(room):
                        continue
                    key = f"{node}@{r.get('since') or ''}"
                    if key in _told:
                        continue
                    if not docs:
                        docs = {str(m.get("room") or "").strip().lower(): m for m in (captions_door("/meetings") or []) if m.get("live")}
                    m = docs.get(room)
                    users = set((captions_door("/meetings/" + quote(str(m["id"]), safe="")) or {}).get("users") or []) if m else set()
                    if users & QUIET:
                        _told.add(key)
                        continue
                    captions_door("/tell", {"node": node, "text": f"📺 meet-flow של הפגישה הזו — הכתוביות מתעדכנות בזמן אמת, "
                                                                  f"וכל העיבוד מופיע שם אחריה: {CONSOLE_URL}/a/meet/flow/{quote(room)}/"})
                    _told.add(key)
        except Exception as e:                                       # noqa: BLE001 — the thread never dies
            print(f"meet-start: telling meet-flow links: {e}", flush=True)
        time.sleep(20)


# ── «פגישות» v2 — the meetings app's server half (fireplace, 2026-10-28) ──────────────────────────────────────────
# The owner (2026-10-28): every meeting on one time axis, live from its first minute, editable, on the phone and the
# desktop. Its one page is start/flow/app.html (MEET_FLOW_UI=v2, the default; v1 serves the pages before it exactly
# as they were). Under it: every meeting as data (/flow/api/meetings, search, inbox), one meeting's state
# (meeting.json), and what people add to a meeting — corrections to its transcript (edits), the approval of its
# decisions and tasks (items: an approved task is ONE Plane work item, in the project the recordings' items are in),
# more tracks and texts (uploads).
# Where that is kept: the office's Drive (the owner: «Drive is the office's ONE file layer»), through the client
# to_drive() uses (_drive, MEET_DRIVE_URL, MEET_DRIVE_PROFILE), in the meeting's own folder — the one to_drive() copies
# its recordings into, «/פגישות/<date> · <room>/»:
#     .meet-flow/edits.jsonl    one correction a line, oldest first (the newest per target wins)
#     .meet-flow/items.json     {"<kind>:<id>": {kind, id, state, by, at, fields, plane, added, edited}}
#     .meet-flow/uploads.json   {name: {name, size, kind, by, at, offset, label, tus}}
#     <name>                    an upload itself: a file people see in «קבצים», like the recordings beside it
# The three small files are read whole (kept META_TTL seconds) and written whole; an upload goes to ONE Drive upload
# session (tus) per file, each piece passed on as it arrives. With MEET_DRIVE_URL empty and MEET_FLOW_DATA set, a
# folder stands in for Drive (the tests): <MEET_FLOW_DATA>/<room>/{edits.jsonl, items.json, uploads.json, uploads/}.
# Drive not answering: reads answer empty and say "store": "unavailable"; writes 503 {"error": "no store"}.
# Every write is a signed-in person's (the edge's headers, believed only from MEET_TRUSTED_PEERS) and carries
# X-Meet-Flow: 1 (the CSRF guard: Door.flow_write). 0.1 CPU and 48 MB: nothing large is held in memory (an upload
# passes in 256 KB reads, files go out in byte ranges); a data.js is parsed once per change, one at a time, and only
# what search needs is kept — within SEARCH_CACHE bytes, the least recently used dropped first.
FLOW_UI = os.environ.get("MEET_FLOW_UI", "v2").strip().lower()
MEET_HOME = os.environ.get("MEET_HOME", "flow").strip().lower()   # the tile: flow = «פגישות» (CHAT-67), jitsi = its welcome page
FLOW_DATA = (os.path.realpath(os.environ["MEET_FLOW_DATA"]) if os.environ.get("MEET_FLOW_DATA", "").strip() else "")
try:
    UPLOAD_MAX = max(1, int(os.environ.get("MEET_FLOW_UPLOAD_MAX", str(2 << 30))))
except ValueError:
    UPLOAD_MAX = 2 << 30
SEARCH_CACHE = 12 * 10 ** 6             # the transcripts kept for search, in bytes (about 25 two-hour meetings)
META_TTL = 10.0                         # a room's small files, as Drive last answered them, kept this long
UPLOAD_PIECE = 8 << 20                  # one PUT's body at most
UPLOAD_READ = 256 << 10                 # …read from the socket this much at a time, straight to the file
BODY_MAX = 64 << 10                     # a JSON body at most
FLOW_SOURCE = "meet-flow"               # an approved task's Plane item: external_source, external_id "<room>:<id>"
FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
DUE_RE = re.compile(r"^\d{4}-\d\d-\d\d$")
SERIES_RE = re.compile(r"^(.*?)(\d+)$")
ITEM_KINDS = ("task", "decision", "question", "mark")
ITEM_ACTIONS = ("approve", "reject", "edit", "reopen", "add")
ITEM_FIELDS = ("text", "owner", "due", "t", "label", "context")
ITEM_STATES = ("proposed", "approved", "rejected", "edited")
STAGE_STATES = ("done", "running", "waiting", "off", "failed")
LABELS = ("decision", "task", "important", "question")
UPLOAD_KINDS = {ext: kind for kind, exts in (("audio", ".m4a .mp3 .ogg .opus .wav .webm .aac .flac"),
                                              ("video", ".mp4 .mov .mkv"), ("text", ".txt .md .vtt .srt .json"),
                                              ("doc", ".pdf .docx .xlsx .pptx .png .jpg"))
                for ext in exts.split()}
UPLOAD_TYPES = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
                ".webm": "audio/webm", ".aac": "audio/aac", ".flac": "audio/flac", ".mp4": "video/mp4",
                ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".txt": "text/plain; charset=utf-8",
                ".md": "text/plain; charset=utf-8", ".vtt": "text/vtt; charset=utf-8", ".srt": "text/plain; charset=utf-8",
                ".json": "application/json", ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                ".png": "image/png", ".jpg": "image/jpeg"}
NAME_REFUSED = '/\\:*?"<>|'
_store = threading.RLock()              # every read-modify-write of a room's files (and the uploads' bookkeeping)
_uploading = set()                      # (room, name) of the uploads a PUT is writing now
_plane_lock = threading.Lock()          # one approved task filed in Plane at a time: never two items for one task
_ids = {"last": 0}
_ids_lock = threading.Lock()


def flow_v2() -> bool:
    """«פגישות» v2's page (start/flow/app.html) — unless MEET_FLOW_UI=v1, or the page is not there yet: this door may
    ship before its page, and then the v1 pages answer as they always did."""
    return FLOW_UI != "v1" and os.path.isfile(os.path.join(FLOW_APP, "app.html"))


def flow_shell(base: str, room, who) -> bytes:
    """The app's one page, for all the meetings (room None) or for one: what it needs to start is in its body's
    data-config attribute (the console sets the page's base where it frames it; none is written here)."""
    me = {"username": who["username"], "name": who.get("name") or who["username"]} if who else None
    cfg = {"meet": base, "room": room, "me": me, "console": CONSOLE_URL, "ui": "v2"}
    return page("flow/app.html", {"CONFIG": html.escape(json.dumps(cfg, ensure_ascii=False))})


# ── the store: the meeting's folder in Drive (a local folder in the tests) ─────────────────────────────────────────
class StoreDown(Exception):
    """The store does not answer (Drive is down), or this door has none."""


# down_at: when the store last failed a call (for 10 s after it, Drive is not asked again: a list of fifty meetings
# does not wait fifty times for a Drive that is down); told_at: when a read last met it down (an answer says so)
_store_state = {"down_at": 0.0, "told_at": 0.0}
_meta_cache = {}                        # (room, name) → (when, text): Drive's last answer, or this door's last write
_folders = {"at": 0.0, "names": None}   # the folders in «פגישות», kept a minute
_room_folders = {}                      # room → (when, its folder's path)
_DATED = re.compile(r"^\d{4}-\d\d-\d\d · (.+)$")


def store_kind():
    """"drive": the office's Drive, the store of every office; "local": a folder standing in for it (MEET_FLOW_DATA
    with MEET_DRIVE_URL empty — the tests); None: no store."""
    if DRIVE_URL and DRIVE_PROFILE:
        return "drive"
    return "local" if FLOW_DATA else None


def store_ok() -> bool:
    """A write may be tried: Drive (whether it answers is found by asking it — StoreDown, 503), or a writable folder."""
    kind = store_kind()
    if kind == "drive":
        return True
    return kind == "local" and os.path.isdir(FLOW_DATA) and os.access(FLOW_DATA, os.W_OK | os.X_OK)


def store_down(e=None):
    _store_state["down_at"] = _store_state["told_at"] = time.time()
    return StoreDown(str(e or "the store does not answer"))


def _drive_guard() -> None:
    if time.time() - _store_state["down_at"] < 10:
        _store_state["told_at"] = time.time()
        raise StoreDown("Drive did not answer a moment ago")


def store_file(room: str, *parts: str, create: bool = False):
    """(local) A path under <MEET_FLOW_DATA>/<room>/: only for a room FLOW_ROOM_RE takes, and only while it stays
    inside that room's folder (realpath, as flow_file); with create its folder is made (never the store itself)."""
    if not FLOW_DATA or not FLOW_ROOM_RE.fullmatch(room or ""):
        return None
    folder = os.path.realpath(os.path.join(FLOW_DATA, room))
    if not folder.startswith(FLOW_DATA + os.sep):
        return None
    path = os.path.realpath(os.path.join(folder, *parts))
    if not path.startswith(folder + os.sep):
        return None
    if create:
        if not os.path.isdir(FLOW_DATA):
            raise OSError(f"no store at {FLOW_DATA}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def write_text(path: str, text: str) -> None:
    """(local) Atomically: a temp file beside it, flushed, then os.replace. The caller holds _store."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:            # Windows only (another handle on it, a test run); never on Linux
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _drive_open(method: str, path: str, data=None, headers=None, timeout=60):
    """One call to Drive exactly as _drive() makes it (MEET_DRIVE_URL, profile_id=MEET_DRIVE_PROFILE), its answer
    left open: a file's bytes are streamed, never read whole."""
    url = f"{DRIVE_URL}{path}{'&' if '?' in path else '?'}profile_id={quote(DRIVE_PROFILE)}"
    return urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=dict(headers or {})),
                                  timeout=timeout)


def _drive_json(method: str, path: str, body=None, missing=None, **kw):
    """_drive(), its answer's JSON — `missing` for a 404, StoreDown when Drive does not answer or refuses."""
    _drive_guard()
    try:
        return _drive(method, path, body, **kw)[1]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return missing
        raise store_down(f"Drive answered {e.code} to {method} {path.split('?')[0]}") from e
    except (OSError, ValueError) as e:
        raise store_down(f"Drive did not answer: {e}") from e


def drive_folders() -> list:
    """The names of the folders in «פגישות» (kept a minute)."""
    now = time.time()
    if _folders["names"] is None or now - _folders["at"] >= 60:
        doc = _drive_json("GET", "/api/fs?path=" + quote("/" + DRIVE_FOLDER), missing={}, timeout=20)
        _folders.update(at=now, names=[str(f.get("name") or "") for f in (doc.get("folders") or []) if isinstance(f, dict)])
    return _folders["names"]


def meeting_date(room: str) -> str:
    """The date in a meeting's Drive folder, by to_drive()'s rule: its recording's start (the office's time); for a
    meeting with no recording, its flow's start, else its captions' start, else today."""
    recs = {r["session"]: r for r in recordings(limit=300)}
    flow = next((f for f in flows() if f["room"] == room), None)
    rec = recs.get(flow["session"]) if flow and flow.get("session") else None
    doc = None
    if RECORDER_SECRET:
        try:
            doc = live_meeting(room)
        except (OSError, ValueError):
            doc = None
    if not rec and doc:
        rec = next((recs[x] for x in (doc.get("sessions") or []) if x in recs), None)
    if rec:
        return rec["started"][:10]
    if flow and local_ts(flow.get("started")):
        return str(flow["started"])[:10]
    if doc and num(doc.get("started")):
        return time.strftime("%Y-%m-%d", time.localtime(num(doc["started"])))
    return time.strftime("%Y-%m-%d")


def drive_folder(room: str, create: bool = False):
    """A meeting's folder in Drive, «/פגישות/<date> · <room>» — the folder to_drive() copies its recordings into: the
    one there is (the newest, when the room met on several days), or with create one made by meeting_date()'s rule.
    None when there is none and create is not asked."""
    hit = _room_folders.get(room)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    names = sorted(n for n in drive_folders() if (_DATED.fullmatch(n) or [None, None])[1] == room)
    if names:
        path = f"/{DRIVE_FOLDER}/{names[-1]}"
    elif create:
        path = f"/{DRIVE_FOLDER}/{meeting_date(room)} · {room}"
        _drive_json("POST", "/api/fs/mkdir", {"path": path}, timeout=20)
        _folders["at"] = 0.0
    else:
        return None
    _room_folders[room] = (time.time(), path)
    return path


def meta_text(room: str, name: str, fresh: bool = False):
    """A room's edits.jsonl, items.json or uploads.json as text; None when it has none. Drive's answer is kept
    META_TTL seconds (fresh: asked again, for a read-modify-write). StoreDown when the store does not answer."""
    kind = store_kind()
    if kind == "local":
        if not os.path.isdir(FLOW_DATA):
            raise store_down(f"no store at {FLOW_DATA}")
        path = store_file(room, name)
        if not path:
            return None
        with _store:
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                return None
            except OSError as e:
                raise store_down(e) from e
    if kind != "drive":
        raise store_down("this door has no store")
    hit = _meta_cache.get((room, name))
    if hit and not fresh and time.time() - hit[0] < META_TTL:
        return hit[1]
    folder, text = drive_folder(room), None
    if folder:
        _drive_guard()
        try:
            with _drive_open("GET", "/api/fs/content?path=" + quote(f"{folder}/.meet-flow/{name}"), timeout=20) as r:
                text = r.read(16 << 20).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise store_down(f"Drive answered {e.code}") from e
        except (OSError, ValueError) as e:
            raise store_down(f"Drive did not answer: {e}") from e
    _meta_cache[(room, name)] = (time.time(), text)
    return text


def meta_json(room: str, name: str, default, fresh: bool = False):
    text = meta_text(room, name, fresh)
    try:
        got = json.loads(text) if text else default
    except ValueError:
        got = default
    return got if isinstance(got, type(default)) else default


def meta_put(room: str, name: str, text: str) -> None:
    """Write a room's small file whole (the caller holds _store): in Drive into the meeting's folder (made on the
    first write), replacing the one before; StoreDown when the store does not take it."""
    kind = store_kind()
    if kind == "local":
        try:
            write_text(store_file(room, name, create=True), text)
        except (OSError, TypeError) as e:
            raise store_down(e) from e
    elif kind == "drive":
        path = f"{drive_folder(room, create=True)}/.meet-flow/{name}"
        ctype = "application/json" if name.endswith(".json") else "text/plain; charset=utf-8"
        _drive_json("PUT", f"/api/fs/content?path={quote(path)}&mode=replace", data=text.encode("utf-8"),
                    headers={"Content-Type": ctype}, timeout=60)
    else:
        raise store_down("this door has no store")
    _meta_cache[(room, name)] = (time.time(), text)


def meta_dump(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def store_rooms() -> list:
    """The rooms the store has a folder for (a meeting that has not happened yet may have items)."""
    try:
        if store_kind() == "local":
            return sorted(n for n in os.listdir(FLOW_DATA) if FLOW_ROOM_RE.fullmatch(n)
                          and os.path.isfile(os.path.join(FLOW_DATA, n, "items.json")))
        if store_kind() == "drive":
            return sorted({m.group(1) for m in map(_DATED.fullmatch, drive_folders()) if m and FLOW_ROOM_RE.fullmatch(m.group(1))})
    except (OSError, StoreDown):
        pass
    return []


def upload_files(room: str) -> dict:
    """{name: (bytes, when)} of the files beside a meeting: in Drive its folder's files (the recordings to_drive()
    copied, what people dropped there in «קבצים», the uploads); locally <room>/uploads/."""
    out = {}
    if store_kind() == "drive":
        folder = drive_folder(room)
        doc = _drive_json("GET", "/api/fs?path=" + quote(folder), missing={}, timeout=20) if folder else {}
        for f in doc.get("files") or []:
            if isinstance(f, dict) and f.get("name"):
                try:
                    when = float(calendar.timegm(time.strptime(str(f.get("created") or ""), "%Y-%m-%d %H:%M")))
                except ValueError:
                    when = None
                out.setdefault(str(f["name"]), (int(num(f.get("size")) or 0), when))
        return out
    folder = store_file(room, "uploads", "x")
    try:
        for name in os.listdir(os.path.dirname(folder)) if folder else []:
            st = os.stat(os.path.join(os.path.dirname(folder), name))
            if os.path.isfile(os.path.join(os.path.dirname(folder), name)) and not name.endswith(".tmp"):
                out[name] = (st.st_size, st.st_mtime)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise store_down(e) from e
    return out


def drive_session(sid: str):
    """(bytes Drive has, its state) of one Drive upload session; (None, None) when Drive keeps it no more (it drops
    them after 72 hours, and finished ones after an hour)."""
    s = _drive_json("GET", f"/api/uploads/{quote(str(sid), safe='')}", timeout=20)
    if not isinstance(s, dict):
        return None, None
    return int(num(s.get("offset")) or 0), str(s.get("state") or "")


def new_id(prefix: str) -> str:
    """e / m / u and the epoch in milliseconds, never the same twice from this door."""
    with _ids_lock:
        _ids["last"] = max(int(time.time() * 1000), _ids["last"] + 1)
        return f"{prefix}{_ids['last']}"


def by_of(who: dict) -> dict:
    return {"username": who["username"], "name": who.get("name") or who["username"]}


def num(v):
    """A finite number as a float, else None (a bool is not a number here)."""
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def blank(v):
    """A text, or None for nothing."""
    v = "" if v is None else str(v).strip()
    return v or None


def iso_ts(text):
    """An ISO time (data.js's start_iso, with its offset) as epoch seconds, or None."""
    try:
        return datetime.datetime.fromisoformat(str(text)).timestamp() if text else None
    except (ValueError, OverflowError, OSError):
        return None


def local_ts(text):
    """The office's local "YYYY-MM-DD HH:MM" (flow.json's started) as epoch seconds, or None."""
    try:
        return time.mktime(time.strptime(str(text), "%Y-%m-%d %H:%M")) if text else None
    except (ValueError, OverflowError):
        return None


def series_of(room: str):
    """fpg105 → ("fpg", 105), SERIES_RE; a room that does not end in digits is a series of its own (n None)."""
    m = SERIES_RE.fullmatch(room)
    return (m.group(1), int(m.group(2))) if m else (room, None)


def docs_of(docs) -> list:
    """A flow's documents as [title, href] pairs (flow.json writes {title, href})."""
    out = []
    for d in docs if isinstance(docs, list) else []:
        if isinstance(d, dict) and d.get("href"):
            out.append([str(d.get("title") or d["href"]), str(d["href"])])
        elif isinstance(d, (list, tuple)) and len(d) >= 2:
            out.append([str(d[0]), str(d[1])])
    return out


def clock(t) -> str:
    sec = max(0, int(t or 0))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def _list(v) -> list:
    return v if isinstance(v, list) else []


# search compares text folded: one case, no niqqud (nor other combining marks), the final letters as the others
_FOLD = {c: None for c in range(0x0591, 0x05C8) if unicodedata.category(chr(c)) == "Mn"}
_FOLD.update({c: None for c in range(0x0300, 0x0370)})
_FOLD.update({ord(a): b for a, b in zip("ךםןףץ", "כמנפצ")})


def fold(text) -> str:
    return unicodedata.normalize("NFKD", str(text)).casefold().translate(_FOLD)


def query_words(q: str) -> list:
    """A search's words, folded, without the punctuation around them: each must appear (AND)."""
    out = []
    for w in fold(q).split():
        while w and unicodedata.category(w[0]).startswith("P"):
            w = w[1:]
        while w and unicodedata.category(w[-1]).startswith("P"):
            w = w[:-1]
        if w and w not in out:
            out.append(w)
    return out


def upload_name(raw):
    """An upload's name as stored: Hebrew and spaces kept; / \\ : * ? " < > | and control characters out; spaces
    collapsed; at most 120 characters (and 240 bytes), its extension kept — one of UPLOAD_KINDS — else None."""
    name = unicodedata.normalize("NFC", str(raw or ""))
    name = "".join(c for c in name if c not in NAME_REFUSED and unicodedata.category(c) not in ("Cc", "Cf"))
    name = re.sub(r"\s+", " ", name).strip().lstrip(". ")
    stem, ext = os.path.splitext(name)
    if ext.lower() not in UPLOAD_KINDS:
        return None
    stem = stem[:120 - len(ext)].rstrip(" .")
    while stem and len((stem + ext).encode("utf-8")) > 240:
        stem = stem[:-1].rstrip(" .")
    return stem + ext if stem else None


def disposition_of(name: str) -> str:
    """inline, the name in ASCII for old clients and in UTF-8 (RFC 6266) for the rest: a header is latin-1."""
    plain = "".join(c if " " <= c <= "~" and c not in '"\\' else "_" for c in name)
    return f"inline; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


# ── the meetings' data, indexed: what lists, search, the inbox and an approval read ─────────────────────────────────
def meeting_index(doc: dict):
    """(meta, text, cost) of one meeting's MEETING data. meta: the small facts every list needs, kept for every
    meeting. text: each transcript line (turns, then the tail) as (id, start, who, text), the lines folded for search
    in one string, and the decisions, tasks and questions under the ids the UI gives them — their own "id", else
    D / T / Q and their 1-based place in that list in data order (T1…T65); kept within SEARCH_CACHE."""
    meet = doc.get("meeting") if isinstance(doc.get("meeting"), dict) else {}
    video = doc.get("video") if isinstance(doc.get("video"), dict) else {}
    names, lines = {}, []
    for x in _list(doc.get("turns")) + _list(doc.get("tail")):
        if isinstance(x, dict) and x.get("id") and str(x.get("text") or "").strip():
            who = str(x.get("who") or "")
            lines.append((str(x["id"]), num(x.get("s")) or 0.0, names.setdefault(who, who), str(x["text"])))
    items = []
    for kind, key, letter in (("decision", "decisions", "D"), ("task", "tasks", "T"), ("question", "questions", "Q")):
        for n, x in enumerate(_list(doc.get(key)), 1):
            if not isinstance(x, dict):
                continue
            if kind == "task":
                ctx = " · ".join(str(x[k]) for k in ("area", "where") if x.get(k))
            else:
                ctx = str(x.get("type") or "") if kind == "decision" else ""
            text = str(x.get("text") or "")
            items.append({"kind": kind, "id": str(x["id"]) if x.get("id") else f"{letter}{n}", "t": num(x.get("t")),
                          "text": text, "owner": blank(x.get("owner") or x.get("who")), "due": blank(x.get("due")),
                          "context": blank(ctx), "folded": fold(text)})
    colors = doc.get("colors")
    meta = {"title": str(meet.get("title") or ""), "start_ts": iso_ts(meet.get("start_iso")),
            "duration": num(meet.get("duration")) or num(video.get("duration")),
            "people": [str(k) for k in colors] if isinstance(colors, dict) and colors else [w for w in names if w],
            "lines": len(lines), "keys": tuple(f"{i['kind']}:{i['id']}" for i in items)}
    folded, offs, at = [], array.array("I"), 0
    for line in lines:
        f = fold(line[3]).replace("\n", " ")
        folded.append(f)
        offs.append(at)
        at += len(f) + 1
    offs.append(at)
    text = {"lines": lines, "blob": "\n".join(folded) + "\n", "offs": offs, "items": items}
    cost = 2 * at + sum(2 * len(line[3]) + 160 for line in lines) + sum(4 * len(i["text"]) + 600 for i in items)
    return meta, text, cost


_flow_meta = {}                          # source → (stamp, meta): every meeting's small facts, always kept
_flow_text = collections.OrderedDict()   # source → (stamp, cost, text), the least recently used first
_flow_cost = [0]
_cache_lock = threading.Lock()
_parse_lock = threading.Lock()           # one data.js parsed at a time: its peak (~6 MB for two hours) once


def _stamp(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _text_get(src, stamp):
    with _cache_lock:
        hit = _flow_text.get(src)
        if hit and hit[0] == stamp:
            _flow_text.move_to_end(src)
            return hit[2]
    return None


def _text_put(src, stamp, cost: int, text: dict) -> None:
    """Keep a meeting's text; then drop the least recently used beyond SEARCH_CACHE (never this one)."""
    with _cache_lock:
        old = _flow_text.pop(src, None)
        if old:
            _flow_cost[0] -= old[1]
        _flow_text[src] = (stamp, cost, text)
        _flow_cost[0] += cost
        while _flow_cost[0] > SEARCH_CACHE and len(_flow_text) > 1:
            _, dropped = _flow_text.popitem(last=False)
            _flow_cost[0] -= dropped[1]


def _cached(src, stamp, text: bool):
    hit = _flow_meta.get(src)
    if not hit or hit[0] != stamp:
        return None
    return _text_get(src, stamp) if text else hit[1]


def _read_meeting(path: str) -> dict:
    """data.js (window.MEETING = {…};) as its object; {} when it is not one."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        doc = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def folder_index(folder: str, text: bool = False):
    """A flow folder's data.js indexed (meeting_index), parsed once per change of the file: its meta, or with text
    its text. None when the folder has no data.js."""
    path = os.path.join(folder, "data.js")
    stamp = _stamp(path)
    if stamp is None:
        return None
    got = _cached(folder, stamp, text)
    if got is not None:
        return got
    with _parse_lock:
        got = _cached(folder, stamp, text)                  # another request parsed it meanwhile
        if got is not None:
            return got
        meta, txt, cost = meeting_index(_read_meeting(path))
        _flow_meta[folder] = (stamp, meta)
        _text_put(folder, stamp, cost, txt)
    return txt if text else meta


def first_index(room: str, mid, ended, text: bool = False):
    """The same for a first processing (machine_flow, from the captions door), built once per ended meeting."""
    src, stamp = "first:" + room, (str(mid), num(ended))
    got = _cached(src, stamp, text)
    if got is not None:
        return got
    data = machine_flow(room)
    if not data:
        return None
    meta, txt, cost = meeting_index(data)
    _flow_meta[src] = (stamp, meta)
    _text_put(src, stamp, cost, txt)
    return txt if text else meta


def source_index(src, text: bool = False):
    """A meeting's data as the meetings list found it: ("flow", folder) or ("first", room, id, ended); None without."""
    try:
        if src and src[0] == "flow":
            return folder_index(src[1], text)
        if src and src[0] == "first":
            return first_index(src[1], src[2], src[3], text)
    except (OSError, ValueError):
        return None
    return None


def counts_of(meta, items: dict) -> dict:
    """A meeting's counts: its data's decisions, tasks, questions and transcript lines, plus what people added;
    proposed / approved / rejected over its tasks and decisions by their stored state (proposed = no approve or
    reject stored); marks = its live marks not rejected."""
    keys = list((meta or {}).get("keys") or ())
    have = set(keys)
    keys += [k for k, e in items.items() if isinstance(e, dict) and e.get("added") and k not in have
             and k.split(":", 1)[0] in ("task", "decision", "question")]
    c = {"decisions": 0, "tasks": 0, "questions": 0, "proposed": 0, "approved": 0, "rejected": 0,
         "lines": int((meta or {}).get("lines") or 0),
         "marks": sum(1 for k, e in items.items() if k.startswith("mark:") and isinstance(e, dict)
                      and e.get("state") != "rejected")}
    for k in keys:
        kind = k.split(":", 1)[0]
        c[kind + "s"] += 1
        if kind != "question":
            e = items.get(k)
            state = e.get("state") if isinstance(e, dict) else None
            c[state if state in ("approved", "rejected") else "proposed"] += 1
    return c


def meeting_row(room, title, started, start, ended, length, people, state, meta, recording, docs, tags) -> dict:
    series, n = series_of(room)
    return {"room": room, "title": title, "series": series, "n": n, "started": started, "start_ts": start,
            "ended_ts": ended, "length_min": round(length / 60) if length else None, "people": people, "state": state,
            "counts": counts_of(meta, items_of(room)), "recording": bool(recording), "docs": docs, "tags": tags}


_meetings = {"at": 0.0, "doc": None, "src": {}}
_meetings_lock = threading.Lock()


def _list_meetings(now: float):
    """The meetings list and, for each room, where its data is: its flow folder (ready, or reviewed), its first
    processing (the v1 list's rule: ended, recorded and finished, no flow folder, not QA's, 14 days), or none (a
    room live now with neither). A room in captions_door("/rooms") is live, whatever else it has."""
    since = time.time()
    recs = {r["session"]: r for r in recordings(limit=300)}
    rooms, caps = [], []
    if RECORDER_SECRET:
        try:
            rooms = [r for r in (captions_door("/rooms") or []) if isinstance(r, dict)]
        except (OSError, ValueError):
            rooms = []
        try:
            caps = [m for m in (captions_door("/meetings") or []) if isinstance(m, dict)]
        except (OSError, ValueError):
            caps = []
    live = {}
    for r in rooms:
        room = str(r.get("room") or "").strip().lower()
        if FLOW_ROOM_RE.fullmatch(room):
            live.setdefault(room, r)
    rows, src = [], {}
    for f in flows():
        room = f["room"]
        if room in src:
            continue                                            # flow_file's choice: the newest folder of a room
        meta = folder_index(f["folder"]) or {}
        start = meta.get("start_ts") or local_ts(f.get("started"))
        dur = meta.get("duration")
        src[room] = ("flow", f["folder"])
        rows.append(meeting_row(room, str(f.get("title") or meta.get("title") or room), f.get("started"), start,
                                start + dur if start and dur else None, dur, meta.get("people") or [],
                                "live" if room in live else "reviewed" if f.get("reviewed") is True else "ready", meta,
                                f.get("session") in recs if f.get("session") else False, docs_of(f.get("docs")),
                                _list(f.get("tags"))))
    for m in caps:
        try:
            room = str(m.get("room") or "").strip().lower()
            if m.get("live") or room in src or not FLOW_ROOM_RE.fullmatch(room):
                continue
            rec = next((recs[x] for x in (m.get("sessions") or []) if x in recs), None)
            if not rec or not rec.get("done") or rec.get("initiator") in QUIET or now - float(m.get("ended") or 0) > 14 * 86400:
                continue
            started, ended = float(m.get("started") or 0), float(m.get("ended") or 0)
        except (ValueError, TypeError):
            continue
        try:
            meta = first_index(room, m.get("id"), m.get("ended")) or {}
        except (OSError, ValueError):
            meta = {}
        src[room] = ("first", room, m.get("id"), m.get("ended"))
        rows.append(meeting_row(room, f"{room} · עיבוד ראשון", rec["started"], recording_start(rec["file"]) or started or None,
                                ended or None, ended - started if ended and started else None,
                                list(rec.get("people") or []) or meta.get("people") or [], "first", meta, True, [],
                                [["הקלטה + כתוביות חיות — לפני העיבוד המלא", "text"]]))
    # a recorded meeting the captions door has no record of (no browser captions anyone): its recording is the meeting,
    # its newest finished one per room (with_server_captions' rule), 14 days back, not QA's
    newest = {}
    for r in sorted(recs.values(), key=lambda r: r["mtime"], reverse=True):
        room = str(r.get("room") or "").strip().lower()
        if room in newest or room in src or room in live or not FLOW_ROOM_RE.fullmatch(room):
            continue
        if r.get("done") and r.get("initiator") not in QUIET and now - float(r.get("mtime") or 0) <= 14 * 86400:
            newest[room] = r
    for room, r in newest.items():
        start = recording_start(r["file"])
        secs = recorded_seconds(r)
        ended = (start + secs) if start and secs else (float(r.get("mtime") or 0) or None)
        try:
            meta = first_index(room, "rec:" + r["session"], ended) or {}
        except (OSError, ValueError):
            meta = {}
        src[room] = ("first", room, "rec:" + r["session"], ended)
        rows.append(meeting_row(room, f"{room} · עיבוד ראשון", r["started"], start, ended,
                                (ended - start) if start and ended else None,
                                list(r.get("people") or []) or meta.get("people") or [], "first", meta, True, [],
                                [["הקלטה + כתוביות השרת — לפני העיבוד המלא", "text"]]))
    for room, r in live.items():
        if room in src:
            continue
        since = num(r.get("since"))
        src[room] = None
        rows.append(meeting_row(room, room, time.strftime("%Y-%m-%d %H:%M", time.localtime(since)) if since else None,
                                since, None, now - since if since else None, [str(x) for x in (r.get("names") or [])],
                                "live", None, r.get("recording") == "on", [], []))
    rows.sort(key=lambda r: r["start_ts"] or 0, reverse=True)
    now_live = [{"room": room, "people": r.get("people"), "names": r.get("names") or [], "recording": r.get("recording"),
                 "since": r.get("since")} for room, r in live.items()]
    doc = {"now": now, "meetings": rows, "live": now_live}
    if _store_state["told_at"] >= since:
        doc["store"] = "unavailable"                            # the counts are the data's alone
    return doc, src


def flow_meetings(max_age: float = 15.0):
    """(GET /flow/api/meetings, {room: its data's source}): every meeting of this office, newest first. The answer is
    kept 15 s; a change to a meeting's items drops it."""
    with _meetings_lock:
        now = time.time()
        if _meetings["doc"] is None or now - _meetings["at"] >= max_age:
            doc, src = _list_meetings(now)
            _meetings.update(at=now, doc=doc, src=src)
        return _meetings["doc"], _meetings["src"]


def flow_stages(state: str, flow, doc, rec, first: bool) -> list:
    """The meeting's way from its recording to its review, honestly: only what exists says done."""
    now_room = (doc or {}).get("now") or {}
    words = int(num((doc or {}).get("words")) or 0)
    said = flow.get("stages") if flow and isinstance(flow.get("stages"), dict) else {}
    out = []
    if rec and rec.get("done"):
        holes = rec.get("holes") or {}
        out.append(("record", "done", f"{rec['file']} · {rec['bytes'] / 1e6:.0f} MB"
                    + (f" · {holes['pct']:.1f}% מהשמע חסר" if (holes.get("pct") or 0) >= 1 else "")))
    elif rec or now_room.get("recording") == "on":
        out.append(("record", "running", "מקליט עכשיו" if now_room else "ההקלטה נסגרת"))
    elif now_room.get("failure"):
        out.append(("record", "failed", f"ההקלטה נכשלה: {now_room['failure']}"))
    elif now_room.get("recording") == "pending" or (state == "before" and doc is None and AUTO_RECORD):
        out.append(("record", "waiting", "תוקלט כשהפגישה תתחיל" if doc is None else "ההקלטה מתחילה"))
    else:
        out.append(("record", "off", "לא הוקלטה"))
    if words > 0:
        out.append(("captions", "running" if doc.get("live") else "done", f"{words} מילים בכתוביות החיות"))
    elif doc is not None and doc.get("live"):
        out.append(("captions", "waiting", "עוד אין כתוביות"))
    else:
        out.append(("captions", "off", "אין כתוביות חיות"))
    if flow or first:
        out.append(("first", "done", "העיבוד המלא קיים" if flow else "ההקלטה והכתוביות החיות על ציר אחד"))
    elif doc is None or doc.get("live") or (rec and not rec.get("done")):
        out.append(("first", "waiting", "כשהפגישה תסתיים וההקלטה תיסגר"))
    else:
        out.append(("first", "off", "הפגישה לא הוקלטה"))
    for key, name in (("best", "מזהה הדיבור הטוב ביותר"), ("speakers", "מי אמר מה"), ("summary", "נושאים, החלטות ומשימות")):
        v = said.get(key)
        if isinstance(v, dict) and v.get("state") in STAGE_STATES:
            out.append((key, v["state"], str(v.get("detail") or name)))
        elif v:
            out.append((key, "done", v if isinstance(v, str) else name))
        else:
            out.append((key, "waiting", name))
    out.append(("review", "done", "נבדק") if flow and flow.get("reviewed") is True else ("review", "waiting", "עוד לא נבדק"))
    return [{"key": k, "state": st, "detail": d} for k, st, d in out]


def flow_meeting(room: str, base: str) -> dict:
    """GET /flow/<room>/meeting.json: one meeting as it is now — before, live, first, ready or reviewed."""
    listed, _ = flow_meetings()
    flow = next((f for f in flows() if f["room"] == room), None)
    doc = None
    if RECORDER_SECRET:
        try:
            doc = live_meeting(room)
        except (OSError, ValueError):
            doc = None
    recs = {r["session"]: r for r in recordings(limit=300)}
    rec = recs.get(flow["session"]) if flow and flow.get("session") else None
    if not rec and doc:
        rec = next((recs[x] for x in (doc.get("sessions") or []) if x in recs), None)
    # data.js answers a first processing exactly when machine_flow() builds one: ended, recorded and finished
    first = bool(not flow and RECORDER_SECRET and doc and not doc.get("live") and rec and rec.get("done"))
    meta, title, start, ended, people = {}, room, None, None, []
    if flow:
        meta = folder_index(flow["folder"]) or {}
        title = str(flow.get("title") or meta.get("title") or room)
        start = meta.get("start_ts") or local_ts(flow.get("started"))
        ended = start + meta["duration"] if start and meta.get("duration") else None
        people = list(meta.get("people") or [])
    elif doc:
        if first:
            title = f"{room} · עיבוד ראשון"
            try:
                meta = first_index(room, doc.get("id"), doc.get("ended")) or {}
            except (OSError, ValueError):
                meta = {}
        start = (recording_start(rec["file"]) if first else None) or num(doc.get("started"))
        ended = None if doc.get("live") else num(doc.get("ended"))
        people = ([a.get("name") for a in (doc.get("attendees") or []) if isinstance(a, dict) and a.get("name")]
                  or [str(x) for x in (doc.get("people") or []) if x]
                  or [str(x) for x in ((doc.get("now") or {}).get("names") or []) if x])
    state = ("live" if (doc or {}).get("now") else "reviewed" if flow and flow.get("reviewed") is True
             else "ready" if flow else "first" if first else "before")
    series, n = series_of(room)
    prev = None
    if n is not None:
        older = [r for r in listed["meetings"] if r["room"] != room and r["series"] == series
                 and r["n"] is not None and r["n"] < n]
        if older:
            best = max(older, key=lambda r: (r["start_ts"] or 0, r["n"]))
            prev = {"room": best["room"], "title": best["title"]}
    has_data = bool(flow and os.path.isfile(os.path.join(flow["folder"], "data.js"))) or first
    return {"room": room, "title": title, "series": series, "n": n, "state": state, "prev": prev,
            "started_ts": start, "ended_ts": ended, "people": people,
            "uncaptioned": [str(x) for x in ((doc or {}).get("uncaptioned") or []) if x],
            "recording": {"session": rec["session"], "file": rec["file"], "done": bool(rec.get("done"))} if rec else None,
            "meet_url": f"{base}/{quote(room, safe='')}",
            "data": f"flow/{room}/data.js" if has_data else None,
            "live": f"flow/{room}/live.json" if doc is not None else None,
            "stages": flow_stages(state, flow, doc, rec, first),
            "counts": counts_of(meta, items_of(room))}


# ── edits: corrections over the transcript ─────────────────────────────────────────────────────────────────────────
def edits_of(room: str) -> list:
    """Every correction of a room, oldest first (the newest per target wins). StoreDown when the store is down."""
    out = []
    for line in (meta_text(room, "edits.jsonl") or "").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


_edit_maps = {}


def edit_maps(room: str):
    """({line id: its corrected text}, {line id: its corrected speaker}): what search applies ({} when the store is
    down: search still answers, uncorrected)."""
    try:
        now_text = meta_text(room, "edits.jsonl") or ""
    except StoreDown:
        return {}, {}
    hit = _edit_maps.get(room)
    if hit and hit[0] == now_text:
        return hit[1]
    text, who = {}, {}
    for e in edits_of(room):
        if e.get("kind") == "line":
            text[str(e.get("target"))] = str(e.get("after") or "")
        elif e.get("kind") == "speaker" and e.get("after"):
            who[str(e.get("target"))] = str(e["after"])
    _edit_maps[room] = (now_text, (text, who))
    return text, who


def add_edit(room: str, who: dict, body: dict):
    """POST /flow/<room>/edits {kind: line|speaker, target, before, after} → 201 {edit}."""
    extra = sorted(set(body) - {"kind", "target", "before", "after"})
    kind, target, after = body.get("kind"), body.get("target"), body.get("after")
    before = "" if body.get("before") is None else body.get("before")
    if extra:
        return 400, {"error": "bad body", "detail": f"unknown key: {extra[0]}"}
    if kind not in ("line", "speaker"):
        return 400, {"error": "bad body", "detail": "kind: line | speaker"}
    if not isinstance(target, str) or not FLOW_ID_RE.fullmatch(target):
        return 400, {"error": "bad body", "detail": "target: ^[A-Za-z0-9_.:-]{1,40}$"}
    if not isinstance(after, str) or len(after) > 4000 or (kind == "speaker" and not after.strip()):
        return 400, {"error": "bad body", "detail": "after: a string of at most 4000 characters (a name, for a speaker)"}
    if not isinstance(before, str) or len(before) > 4000:
        return 400, {"error": "bad body", "detail": "before: a string of at most 4000 characters"}
    edit = {"id": new_id("e"), "at": time.time(), "by": by_of(who), "kind": kind, "target": target,
            "before": before, "after": after}
    line = json.dumps(edit, ensure_ascii=False) + "\n"
    with _store:
        if store_kind() == "local":                 # append-only on a disk; Drive takes a file only whole
            try:
                with open(store_file(room, "edits.jsonl", create=True), "a", encoding="utf-8", newline="\n") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            except (OSError, TypeError) as e:
                raise store_down(e) from e
        else:
            meta_put(room, "edits.jsonl", (meta_text(room, "edits.jsonl", fresh=True) or "") + line)
    return 201, {"edit": edit}


# ── items: decisions, tasks, questions and live marks — approve, reject, edit, reopen, add ─────────────────────────
def items_of(room: str, strict: bool = False, fresh: bool = False) -> dict:
    """A room's stored items by "<kind>:<id>". The store down: {} (the lists still answer, and say so), or with
    strict, StoreDown."""
    try:
        got = meta_json(room, "items.json", {}, fresh)
    except StoreDown:
        if strict:
            raise
        got = {}
    return {k: v for k, v in got.items() if isinstance(v, dict)}


def fields_error(fields) -> str:
    """Why these fields are not an item's (empty when they are): text, owner, context strings of at most 2000
    characters (text not empty); due "" or YYYY-MM-DD; t seconds from the meeting's start or null; label one of
    decision | task | important | question, or ""."""
    if not isinstance(fields, dict):
        return "fields: an object"
    for k, v in fields.items():
        if k not in ITEM_FIELDS:
            return f"fields: unknown key {k}"
        if k == "t":
            if v is not None and (num(v) is None or not isinstance(v, (int, float)) or v < 0):
                return "fields.t: seconds from the meeting's start (a number, at least 0) or null"
        elif not isinstance(v, str) or len(v) > 2000:
            return f"fields.{k}: a string of at most 2000 characters"
        elif k == "text" and not v.strip():
            return "fields.text: not empty"
        elif k == "due" and v:
            try:
                ok = bool(DUE_RE.fullmatch(v)) and bool(datetime.date.fromisoformat(v))
            except ValueError:
                ok = False
            if not ok:
                return "fields.due: YYYY-MM-DD"
        elif k == "label" and v and v not in LABELS:
            return "fields.label: " + " | ".join(LABELS)
    return ""


def data_item(room: str, kind: str, iid: str):
    """The decision, task or question of the meeting's data (its flow folder's data.js) under this id, or None."""
    if kind == "mark":
        return None
    flow = next((f for f in flows() if f["room"] == room), None)
    txt = folder_index(flow["folder"], text=True) if flow else None
    return next((i for i in (txt or {}).get("items", []) if i["kind"] == kind and i["id"] == iid), None)


def item_after(entry, kind: str, iid: str, action: str, fields: dict, who: dict) -> dict:
    """The stored item after one action: approve → approved, reject → rejected, edit → edited (an approved or a
    rejected item stays so), reopen → proposed (edited, when its fields were changed), add → proposed."""
    e = dict(entry) if isinstance(entry, dict) else {"state": "proposed", "fields": {}}
    e["fields"] = dict(e["fields"] if isinstance(e.get("fields"), dict) else {},
                       **{k: (float(v) if k == "t" and v is not None else v) for k, v in fields.items()})
    if action == "add":
        e["added"] = True
    elif fields:
        e["edited"] = True
    if action == "approve":
        e["state"] = "approved"
    elif action == "reject":
        e["state"] = "rejected"
    elif action == "edit":
        e["state"] = e.get("state") if e.get("state") in ("approved", "rejected") else "edited"
    else:
        e["state"] = "edited" if e.get("edited") else "proposed"
    e.update(kind=kind, id=iid, by=by_of(who), at=time.time())
    return e


def change_item(room: str, who: dict, body: dict):
    """POST /flow/<room>/items {kind, id, action, fields} → {item}. An approved task is filed in Plane (approve_task)."""
    extra = sorted(set(body) - {"kind", "id", "action", "fields"})
    kind, iid, action = body.get("kind"), body.get("id"), body.get("action")
    fields = {} if body.get("fields") is None else body.get("fields")
    if extra:
        return 400, {"error": "bad body", "detail": f"unknown key: {extra[0]}"}
    if kind not in ITEM_KINDS:
        return 400, {"error": "bad body", "detail": "kind: " + " | ".join(ITEM_KINDS)}
    if action not in ITEM_ACTIONS:
        return 400, {"error": "bad body", "detail": "action: " + " | ".join(ITEM_ACTIONS)}
    why = fields_error(fields)
    if why:
        return 400, {"error": "bad body", "detail": why}
    if action == "add":
        if iid is not None:
            return 400, {"error": "bad body", "detail": "id: null for add (this door names it)"}
        if kind != "mark" and not str(fields.get("text") or "").strip():
            return 400, {"error": "bad body", "detail": "fields.text: what is added"}
        iid, data = new_id("m" if kind == "mark" else "u"), None
    else:
        if not isinstance(iid, str) or not FLOW_ID_RE.fullmatch(iid):
            return 400, {"error": "bad body", "detail": "id: ^[A-Za-z0-9_.:-]{1,40}$"}
        if action == "edit" and not fields:
            return 400, {"error": "bad body", "detail": "fields: what the edit changes"}
        data = data_item(room, kind, iid)
    key = f"{kind}:{iid}"
    if action != "add" and data is None and key not in items_of(room, strict=True, fresh=True):
        return 404, {"error": "no such item"}
    if action == "approve" and kind == "task":
        return approve_task(room, key, iid, data, fields, who)
    with _store:
        items = items_of(room, strict=True, fresh=True)
        old = items.get(key)
        if action == "approve" and old and old.get("state") == "approved" and not fields:
            return 200, {"item": old}                           # approved already: unchanged
        items[key] = item_after(old, kind, iid, action, fields, who)
        meta_put(room, "items.json", meta_dump(items))
    _meetings["at"] = 0.0                                       # the meetings' counts change
    return 200, {"item": items[key]}


def approve_task(room: str, key: str, iid: str, data, fields: dict, who: dict):
    """Approve a task: ONE Plane work item (file_task), its link stored with the approval. A second approve answers the
    stored link and asks Plane nothing; Plane failing → 502 {"error": "plane", "detail"} and nothing is stored."""
    with _plane_lock:
        entry = items_of(room, strict=True, fresh=True).get(key)
        if entry and entry.get("plane") and entry.get("state") == "approved" and not fields:
            return 200, {"item": entry}
        plane_link = (entry or {}).get("plane")
        if not plane_link:
            f = dict((entry or {}).get("fields") or {}, **fields)
            base = data or {}

            def eff(k):
                return blank(f[k]) if k in f else base.get(k)
            task = {"text": str(f.get("text") or base.get("text") or "").strip(), "owner": eff("owner"),
                    "due": eff("due"), "t": num(f["t"]) if "t" in f else base.get("t"), "context": eff("context")}
            plane_link, why = file_task(room, iid, task, who)
            if not plane_link:
                return 502, {"error": "plane", "detail": why}
        with _store:
            items = items_of(room, strict=True, fresh=True)
            e = item_after(items.get(key), "task", iid, "approve", fields, who)
            e["plane"] = plane_link
            items[key] = e
            meta_put(room, "items.json", meta_dump(items))
    _meetings["at"] = 0.0
    return 200, {"item": e}


def meet_project() -> str:
    """The Plane project the recordings' items are filed in: plane_items()'s (identifier MEET), else asked once."""
    if _items.get("project"):
        return _items["project"]
    got = plane("GET", "/projects/?per_page=100")
    rows = got if isinstance(got, list) else (got or {}).get("results") or []
    project = next((p for p in rows if isinstance(p, dict) and p.get("identifier") == "MEET"), None)
    return str(project.get("id") or "") if project else ""


def task_html(room: str, iid: str, task: dict, who: dict) -> str:
    """An approved task's Plane description: its context, the owner and the due date in Hebrew, and a link to the
    moment in the meeting ({CONSOLE_URL}/a/meet/flow/<room>/#t<seconds>)."""
    e = html.escape
    t = task.get("t")
    link = f"{CONSOLE_URL}/a/meet/flow/{quote(room)}/" + (f"#t{int(t)}" if t is not None else "")
    due = task.get("due") or ""
    if DUE_RE.fullmatch(due):
        due = f"{due[8:10]}.{due[5:7]}.{due[:4]}"
    out = ["<p>" + e(task["context"]).replace("\n", "<br>") + "</p>"] if task.get("context") else []
    out.append(f"<p><strong>אחראי:</strong> {e(task.get('owner') or 'לא נקבע')}<br>"
               f"<strong>תאריך יעד:</strong> {e(due or 'לא נקבע')}</p>")
    out.append(f'<p>🎬 <a href="{e(link)}">הרגע בפגישה «{e(room)}»' + (f" ({clock(t)})" if t is not None else "") + "</a></p>")
    out.append(f"<p><small>אושרה ב«פגישות» בידי {e(who.get('name') or who.get('username') or '')} · "
               f"🆔 {FLOW_SOURCE}:{e(room)}:{e(iid)}</small></p>")
    return "".join(out)


def file_task(room: str, iid: str, task: dict, who: dict):
    """ONE Plane work item for an approved task, in project MEET, keyed (meet-flow, <room>:<id>) — one Plane already
    has under that key is taken, never a second → ({id, key, url}, None), or (None, why)."""
    if not PLANE_API:
        return None, "MEET_PLANE_API_URL is empty: this office files nothing in Plane"
    if not task["text"]:
        return None, "the task has no text"
    key = f"{room}:{iid}"
    try:
        project = meet_project()
        if not project:
            return None, "Plane has no project MEET"
        issue = plane_issue(project, FLOW_SOURCE, key)
        if not issue:
            name = task["text"] if len(task["text"]) <= 255 else task["text"][:254] + "…"
            issue = plane("POST", f"/projects/{project}/issues/", {
                "name": name, "description_html": task_html(room, iid, task, who),
                "external_source": FLOW_SOURCE, "external_id": key})
    except urllib.error.HTTPError as e:
        try:
            said = e.read(200).decode("utf-8", "replace")
        except OSError:
            said = ""
        return None, f"Plane answered {e.code}: {said}".strip()[:300]
    except (OSError, ValueError) as e:
        return None, f"Plane did not answer: {e}"[:300]
    if not isinstance(issue, dict) or not issue.get("id"):
        return None, "Plane answered no work item"
    seq = issue.get("sequence_id")
    ident = (issue.get("project_detail") or {}).get("identifier") if isinstance(issue.get("project_detail"), dict) else None
    module = urlsplit(PLANE_API).hostname or "project-pln"
    return {"id": str(issue["id"]), "key": f"{ident or 'MEET'}-{seq}" if seq is not None else None,
            "url": f"{CONSOLE_URL or ''}/#/m/{module}/{PLANE_WS}/projects/{project}/issues/{issue['id']}"}, None


# ── uploads: more tracks and texts for a meeting ───────────────────────────────────────────────────────────────────
def upload_kind(name: str) -> str:
    return UPLOAD_KINDS.get(os.path.splitext(name)[1].lower(), "doc")


def upload_public(name: str, row: dict, received: int, done: bool) -> dict:
    return {"name": name, "size": int(num(row.get("size")) or 0), "received": received, "kind": row.get("kind") or upload_kind(name),
            "by": row.get("by"), "at": row.get("at"), "done": done, "offset": row.get("offset"), "label": row.get("label") or ""}


def uploads_of(room: str) -> list:
    """GET /flow/<room>/uploads: the files beside the meeting (in Drive: its folder, but .meet-flow — the recordings
    to_drive() copied there and what people dropped in it in «קבצים» too) with what uploads.json says of them (who,
    when, offset, label), and the uploads still arriving. received: what the store has now. StoreDown when down."""
    rows = meta_json(room, "uploads.json", {})
    files = upload_files(room)
    drive, out = store_kind() == "drive", []
    for name, row in rows.items():
        if not isinstance(row, dict):
            continue
        size = int(num(row.get("size")) or 0)
        if name in files and (not drive or files[name][0] == size):
            got = files[name][0]
        elif drive and row.get("tus"):
            got = drive_session(row["tus"])[0] or 0          # still arriving (or being stored)
        else:
            got = 0
        out.append(upload_public(name, row, got, got == size and name in files))
    for name, (size, when) in files.items():
        if name not in rows:
            out.append(upload_public(name, {"size": size, "at": when}, size, True))
    return out


def upload_piece(room: str, who: dict, name: str, a: int, total: int, length: int, read):
    """One piece of an upload (PUT /flow/<room>/uploads/<name>), read with read(n) in UPLOAD_READ pieces and passed on
    as it arrives: into ONE Drive upload session per file whose destination is the meeting's folder (so the file
    lands there as a file of «קבצים»), or locally straight to <room>/uploads/<name>. In order: `a` must be what the
    store has — else 409 with it (received), so the client resumes there. → (code, answer)."""
    key, drive = (room, name), store_kind() == "drive"
    with _store:
        rows = meta_json(room, "uploads.json", {}, fresh=True)
        row = rows.get(name) if isinstance(rows.get(name), dict) else None
        same = bool(row) and int(num(row.get("size")) or -1) == total
        if drive:
            folder = drive_folder(room, create=True)
            files = upload_files(room)
            have, sid = 0, (row or {}).get("tus") if same else None
            if sid:
                off, state = drive_session(sid)
                if off is None:                              # Drive dropped the session: its file, or from the start
                    have, sid = (total, None) if files.get(name, (None,))[0] == total else (0, None)
                else:
                    have = total if state in ("complete", "finishing", "done") else off
            taken = name in files and not same
        else:
            path = store_file(room, "uploads", name, create=True)
            have = os.path.getsize(path) if os.path.isfile(path) else 0
            taken = bool(have) and not same
        if key in _uploading:
            return 409, {"error": "busy", "detail": "another piece of this file is arriving now", "received": have, "total": total}
        if taken:
            return 409, {"error": "name taken", "detail": f"«{name}» is another file here", "received": have, "total": total}
        if a != have:
            return 409, {"error": "out of order", "detail": f"the next piece starts at byte {have}", "received": have,
                         "total": total}
        if not same or (drive and not sid):
            row = {"name": name, "size": total, "kind": upload_kind(name), "by": by_of(who), "at": time.time(),
                   "offset": (row or {}).get("offset") if same else None, "label": (row or {}).get("label", "") if same else ""}
            if drive:
                s = _drive_json("POST", "/api/uploads", {"size": total, "name": name, "path": folder,
                                                          "mime": UPLOAD_TYPES.get(os.path.splitext(name)[1].lower(), "")},
                                timeout=20)
                sid = row["tus"] = str((s or {}).get("id") or "")
                if not sid:
                    raise store_down("Drive opened no upload session")
            rows[name] = row
            meta_put(room, "uploads.json", meta_dump(rows))
        _uploading.add(key)
    early = []
    try:
        if drive:
            def body():                                      # the piece passes through: one read at a time
                left = length
                while left > 0:
                    try:
                        chunk = read(min(UPLOAD_READ, left))
                    except (TimeoutError, ConnectionError):
                        chunk = b""
                    if not chunk:
                        early.append(True)
                        raise ConnectionError("the piece ended early")
                    left -= len(chunk)
                    yield chunk
            try:
                _drive("PATCH", f"/api/uploads/{quote(sid, safe='')}", data=body(), timeout=300,
                       headers={"Upload-Offset": str(a), "Content-Length": str(length), "Tus-Resumable": "1.0.0",
                                "Content-Type": "application/offset+octet-stream"})
            except urllib.error.HTTPError as e:
                if e.code != 409:                            # 409: Drive has other bytes than we thought (below)
                    raise store_down(f"Drive answered {e.code} to a piece") from e
                early.append(False)
            except (OSError, ValueError) as e:
                if not early:
                    raise store_down(f"Drive did not answer: {e}") from e
            have, state = drive_session(sid)
            have = have or 0
            for _ in range(5 if early else 0):               # cut short: Drive may still be writing what came
                time.sleep(0.2)
                again = drive_session(sid)[0] or 0
                if again == have:
                    break
                have = again
            for _ in range(60):                            # the last piece: Drive stores the file (seconds)
                if have < total or state in ("done", "failed"):
                    break
                time.sleep(0.5)
                have, state = drive_session(sid)
                have = total if have is None else have
            if state == "failed":
                raise store_down("Drive could not store the file")
            done = have == total and (state == "done" or upload_files(room).get(name, (None,))[0] == total)
        else:
            got = 0
            try:
                with open(path, "ab") as f:
                    while got < length:
                        chunk = read(min(UPLOAD_READ, length - got))
                        if not chunk:
                            early.append(True)
                            break
                        f.write(chunk)
                        got += len(chunk)
            except (TimeoutError, ConnectionError):
                early.append(True)
            except OSError as e:
                raise store_down(e) from e
            have = os.path.getsize(path)
            done = have == total
    finally:
        with _store:
            _uploading.discard(key)
    if early == [False]:
        return 409, {"error": "out of order", "detail": f"the next piece starts at byte {have}", "received": have,
                     "total": total}
    if early:
        return 400, {"error": "the piece ended early", "received": have, "total": total}
    return 200, {"name": name, "received": have, "total": total, "done": done}


def upload_meta(room: str, name, body: dict):
    """POST /flow/<room>/uploads/<name>/meta {offset, label}: where the track sits on the meeting's axis (seconds,
    null = not placed) and what it is called → the stored row. A file beside the meeting that came another way (a
    recording, a file dropped in «קבצים») gets its row here."""
    extra = sorted(set(body) - {"offset", "label"})
    off = body.get("offset")
    if extra:
        return 400, {"error": "bad body", "detail": f"unknown key: {extra[0]}"}
    if "offset" in body and off is not None and (num(off) is None or not isinstance(off, (int, float)) or abs(off) > 86400):
        return 400, {"error": "bad body", "detail": "offset: seconds on the meeting's axis (within a day), or null"}
    if "label" in body and (not isinstance(body["label"], str) or len(body["label"]) > 200):
        return 400, {"error": "bad body", "detail": "label: a string of at most 200 characters"}
    if not name:
        return 404, {"error": "no such upload"}
    with _store:
        rows = meta_json(room, "uploads.json", {}, fresh=True)
        row = rows.get(name) if isinstance(rows.get(name), dict) else None
        if row is None:
            size, when = upload_files(room).get(name, (None, None))
            if size is None:
                return 404, {"error": "no such upload"}
            row = {"name": name, "size": size, "kind": upload_kind(name), "by": None, "at": when, "offset": None, "label": ""}
        if "offset" in body:
            row["offset"] = None if off is None else float(off)
        if "label" in body:
            row["label"] = body["label"].strip()
        rows[name] = row
        meta_put(room, "uploads.json", meta_dump(rows))
    return 200, next((u for u in uploads_of(room) if u["name"] == name), upload_public(name, row, 0, False))


# ── search and the inbox, across the meetings ──────────────────────────────────────────────────────────────────────
def search_targets(room=None) -> list:
    """(room, title, source) of what search and the inbox read, newest first: the rooms that have only what people
    added (a meeting still ahead), then the meetings list. With room: that one alone."""
    listed, src = flow_meetings()
    rows = [(r["room"], r["title"], src.get(r["room"])) for r in listed["meetings"]]
    if room:
        mine = [r for r in rows if r[0] == room]
        if mine:
            return mine
        flow = next((f for f in flows() if f["room"] == room), None)
        return [(room, str(flow.get("title") or room) if flow else room, ("flow", flow["folder"]) if flow else None)]
    known, ahead = {r[0] for r in rows}, []
    for name in store_rooms():
        if name not in known:
            ahead.append((max((num(e.get("at")) or 0 for e in items_of(name).values()), default=0), name))
    return [(name, name, None) for _, name in sorted(ahead, reverse=True)] + rows


def search_meeting(room: str, title: str, txt, words: list) -> list:
    """One meeting's hits: its lines (corrected text and speaker applied), its decisions, tasks and questions (their
    edited text applied), and what people added — every word in each."""
    line_ed, who_ed = edit_maps(room)
    items = items_of(room)
    out = []

    def hit(kind, iid, t, who, text):
        out.append({"room": room, "title": title, "kind": kind, "id": iid, "t": t, "who": who or None, "text": text})
    if txt:
        blob, offs = txt["blob"], txt["offs"]
        quick = all(w in blob for w in words)        # a meeting without every word is skipped at once
        if quick or line_ed:
            for i, (lid, s, who, text) in enumerate(txt["lines"]):
                if lid in line_ed:
                    text = line_ed[lid]
                    folded = fold(text)
                    found = bool(text.strip()) and all(w in folded for w in words)
                else:
                    found = quick and all(blob.find(w, offs[i], offs[i + 1] - 1) >= 0 for w in words)
                if found:
                    hit("line", lid, s, who_ed.get(lid, who), text)
        for it in txt["items"]:
            e = items.get(f"{it['kind']}:{it['id']}") or {}
            f = e.get("fields") if isinstance(e.get("fields"), dict) else {}
            text = f.get("text") or it["text"]
            folded = it["folded"] if text == it["text"] else fold(text)
            if text and all(w in folded for w in words):
                hit(it["kind"], it["id"], num(f["t"]) if "t" in f else it["t"],
                    blank(f["owner"]) if "owner" in f else it["owner"], text)
    for key, e in items.items():
        kind = key.split(":", 1)[0]
        f = e.get("fields") if isinstance(e.get("fields"), dict) else {}
        text = str(f.get("text") or "")
        if e.get("added") and kind in ("task", "decision", "question") and text and all(w in fold(text) for w in words):
            hit(kind, str(e.get("id") or key.split(":", 1)[1]), num(f.get("t")), blank(f.get("owner")), text)
    return out


def flow_search(q: str, room=None) -> dict:
    """GET /flow/api/search?q=…[&room=…]: at most 200 hits, the newest meeting first, then by time; total = all."""
    words, hits, total = query_words(q), [], 0
    for rm, title, src in search_targets(room):
        found = search_meeting(rm, title, source_index(src, text=True), words)
        total += len(found)
        if len(hits) < 200:
            found.sort(key=lambda h: (h["t"] is None, h["t"] or 0))
            hits.extend(found[:200 - len(hits)])
    return {"q": q, "total": total, "hits": hits}


def flow_inbox(every: bool) -> dict:
    """GET /flow/api/inbox: every task and decision with no approve or reject stored, newest meeting first, 300 at most
    (state "proposed"). all=1: every one of them, its stored state (proposed | approved | rejected | edited), its
    Plane link and its edited fields when it has them — 2000 at most. text, owner, due and t are as edited."""
    cap, rows = (2000 if every else 300), []
    for room, title, src in search_targets():
        if len(rows) >= cap:
            break
        items = items_of(room)
        meta = source_index(src) or {}
        txt = source_index(src, text=True) if meta.get("keys") else None
        cands = [i for i in (txt or {}).get("items", []) if i["kind"] in ("task", "decision")]
        have = {f"{i['kind']}:{i['id']}" for i in cands}
        for key, e in items.items():
            kind = key.split(":", 1)[0]
            if e.get("added") and key not in have and kind in ("task", "decision"):
                cands.append({"kind": kind, "id": str(e.get("id") or key.split(":", 1)[1]), "t": None, "text": "",
                              "owner": None, "due": None})
        per = []
        for it in cands:
            e = items.get(f"{it['kind']}:{it['id']}") or {}
            state = e.get("state") if e.get("state") in ITEM_STATES else "proposed"
            if not every and state in ("approved", "rejected"):
                continue
            f = e.get("fields") if isinstance(e.get("fields"), dict) else {}
            row = {"room": room, "title": title, "kind": it["kind"], "id": it["id"], "text": f.get("text") or it["text"],
                   "owner": blank(f["owner"]) if "owner" in f else it["owner"],
                   "due": blank(f["due"]) if "due" in f else it["due"],
                   "t": num(f["t"]) if "t" in f else it["t"], "state": state if every else "proposed"}
            if f:
                row["fields"] = f
            if e.get("plane"):
                row["plane"] = e["plane"]
            per.append(row)
        per.sort(key=lambda r: (r["t"] is None, r["t"] or 0))
        rows.extend(per[:cap - len(rows)])
    return {"items": rows}


import faulthandler, signal
if hasattr(signal, "SIGUSR1"):                            # (a test run on Windows has no SIGUSR1)
    faulthandler.register(signal.SIGUSR1, all_threads=True)   # docker kill -s USR1 <container>: every thread's stack into the log

# ── a meeting's transcript as a file, and every finished meeting's processing in Drive (fireplace, 2026-10-29) ──────
# CHAT-63: the transcript leaves the page as people corrected it — text (with a list of the screen moments), WebVTT
# (the speaker as a <v> voice) and SRT — at /flow/<room>/transcript.{txt,vtt,srt}. CHAT-62: the owner's rule that
# Drive is the office's one file layer — the moment a recorded meeting's first processing exists (the office's
# recognisers have finished), its transcript, its subtitles and its data (turns, speakers, screen moments) are written
# into the meeting's own Drive folder, «/פגישות/<date> · <room>/», beside its recording, with no request; written again
# when people correct it (its stamp is the recogniser's job and the corrections' hash), at most every FLOW_DRIVE_GAP s.
#     תמלול — <room>.txt          the transcript as people read it
#     כתוביות — <room>.vtt         WebVTT, for any player
#     .meet-flow/first.json       {stamp, room, job, made, duration, people, turns, moments} — for agents
# MEET_FLOW_TO_DRIVE=0 turns it off. QA's meetings and meetings from before MEET_DRIVE_SINCE are left alone (to_drive's
# rule); a processed flow (data.js) is not touched: its folder was written by whoever processed it.
EXPORT_TYPES = {"txt": "text/plain; charset=utf-8", "vtt": "text/vtt; charset=utf-8", "srt": "application/x-subrip; charset=utf-8"}
FLOW_TO_DRIVE = os.environ.get("MEET_FLOW_TO_DRIVE", "1").strip() != "0"
FLOW_DRIVE_EVERY = max(5.0, float(os.environ.get("MEET_FLOW_DRIVE_EVERY", "120") or 120))   # seconds between two looks
FLOW_DRIVE_GAP = max(0.0, float(os.environ.get("MEET_FLOW_DRIVE_GAP", "600") or 600))      # a meeting's files rewritten at most this often
_flow_drive = {}                         # room → (stamp, written at)


def meeting_doc(room: str):
    """The MEETING data people see for a room: its processed flow's data.js, else its first processing; None."""
    flow, path = flow_file(room, "data.js")
    if path:
        return _read_meeting(path) or None
    if not flow and RECORDER_SECRET:
        return machine_flow(room)
    return None


def export_turns(room: str, doc: dict) -> list:
    """The lines of a meeting as people read them: every correction applied (its text, its speaker), oldest first,
    the deleted ones left out; [{s, e, who, text}]."""
    texts, whos = edit_maps(room)
    out = []
    for x in list(doc.get("turns") or []) + [dict(t, tail=True) for t in (doc.get("tail") or [])]:
        if not isinstance(x, dict):
            continue
        tid = str(x.get("id") or "")
        text = str(texts.get(tid, x.get("text")) or "").strip()
        if not text:
            continue
        s = float(num(x.get("s")) or 0)
        e = float(num(x.get("e")) or 0)
        who = str(whos.get(tid) or x.get("who") or "").strip()
        out.append({"s": s, "e": e if e > s else s + 2.0, "who": "" if who in ("?", SERVER_CAPTIONS) else who,
                    "text": text, "tail": bool(x.get("tail"))})
    out.sort(key=lambda t: t["s"])
    return out


def _cue(t: float, sep: str) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def export_text(room: str, doc: dict, ext: str) -> str:
    """The transcript as text, WebVTT or SRT; "" with no lines."""
    lines = export_turns(room, doc)
    if not lines:
        return ""
    if ext == "vtt":
        out = ["WEBVTT", ""]
        for i, x in enumerate(lines, 1):
            who = x["who"].replace(">", "").replace("<", "")
            out += [str(i), f"{_cue(x['s'], '.')} --> {_cue(x['e'], '.')}", (f"<v {who}>" if who else "") + x["text"].replace("-->", "→"), ""]
        return "\n".join(out)
    if ext == "srt":
        out = []
        for i, x in enumerate(lines, 1):
            out += [str(i), f"{_cue(x['s'], ',')} --> {_cue(x['e'], ',')}", (f"{x['who']}: " if x["who"] else "") + x["text"], ""]
        return "\n".join(out)
    m = doc.get("meeting") or {}
    people = [str(p) for p in (doc.get("people") or []) if p]
    out = [str(m.get("title") or room), " · ".join(v for v in (str(m.get("subtitle") or ""), ", ".join(people[:12])) if v),
           f"{m.get('transcript_label') or 'תמלול'} · נכתב {time.strftime('%Y-%m-%d %H:%M')} · {len(lines)} שורות", ""]
    tail = False
    for x in lines:
        if x["tail"] and not tail:
            out += ["", "— אחרי שהשיחה בווידאו נגמרה —", ""]
            tail = True
        out.append(f"[{clock(x['s'])}] " + (f"{x['who']}: " if x["who"] else "") + x["text"])
    moments = doc.get("moments") if isinstance(doc.get("moments"), list) else screen_moments(doc.get("turns") or [])
    if moments:
        out += ["", "רגעי מסך — «פה» / «צילום מסך» (המסך המשותף באותה שנייה שייך לפגישה):"]
        out += [f"[{clock(x['t'])}] {'צילום מסך' if x['kind'] == 'shot' else '«' + '», «'.join(x['words']) + '»'} — {x['text']}" for x in moments]
    return "\n".join(out) + "\n"


def folder_put(room: str, name: str, text: str, ctype: str) -> None:
    """A file written whole into the meeting's own folder (Drive: «/פגישות/<date> · <room>/<name>», replacing the one
    before; the local store: <MEET_FLOW_DATA>/<room>/files/<name>). StoreDown when the store does not take it."""
    kind = store_kind()
    if kind == "local":
        with _store:
            try:
                write_text(store_file(room, "files", name, create=True), text)
            except (OSError, TypeError) as e:
                raise store_down(e) from e
    elif kind == "drive":
        path = f"{drive_folder(room, create=True)}/{name}"
        _drive_json("PUT", f"/api/fs/content?path={quote(path)}&mode=replace", data=text.encode("utf-8"),
                    headers={"Content-Type": ctype}, timeout=60)
    else:
        raise store_down("this door has no store")


def flow_to_drive_once(now: float) -> list:
    """One look: each finished, recorded meeting whose first processing has the office's transcript and whose files
    in Drive are missing or older than its corrections gets them (one meeting per look: 0.1 CPU). The rooms written."""
    listed, _ = flow_meetings()
    wrote = []
    for row in listed.get("meetings") or []:
        room = row.get("room")
        if row.get("state") != "first" or str(row.get("started") or "") < DRIVE_SINCE or not room:
            continue
        try:
            edits = meta_text(room, "edits.jsonl") or ""
        except StoreDown:
            return wrote
        known = _flow_drive.get(room)
        mark = hashlib.sha1(edits.encode("utf-8")).hexdigest()[:12]
        if known and known[0].endswith(":" + mark):
            continue                                            # written, and nobody corrected it since
        if known and now - known[1] < FLOW_DRIVE_GAP:
            continue
        doc = machine_flow(room)
        if not doc or not doc.get("job"):
            continue                                            # the recogniser has not finished: the next look
        stamp = f"{doc['job']}:{mark}"
        try:
            old = meta_json(room, "first.json", {}, fresh=True)
        except StoreDown:
            return wrote
        finally:
            _meta_cache.pop((room, "first.json"), None)         # read once a meeting: not kept in the 48 MB
        if old.get("stamp") != stamp:
            folder_put(room, f"תמלול — {room}.txt", export_text(room, doc, "txt"), EXPORT_TYPES["txt"])
            folder_put(room, f"כתוביות — {room}.vtt", export_text(room, doc, "vtt"), EXPORT_TYPES["vtt"])
            data = {"stamp": stamp, "room": room, "job": doc["job"], "made": now,
                    "duration": (doc.get("meeting") or {}).get("duration"), "people": doc.get("people") or [],
                    "video": (doc.get("video") or {}).get("src"), "moments": doc.get("moments") or [],
                    "turns": export_turns(room, doc)}
            with _store:
                meta_put(room, "first.json", meta_dump(data))
                _meta_cache.pop((room, "first.json"), None)
            print(f"meet-start: the first processing of {room} ({len(data['turns'])} lines, {len(data['moments'])} screen "
                  f"moments) is in its folder in «קבצים»", flush=True)
            wrote.append(room)
        _flow_drive[room] = (stamp, now)
        if wrote:
            break
    return wrote


def flow_to_drive() -> None:
    time.sleep(min(30.0, FLOW_DRIVE_EVERY))                     # the door first
    while True:
        try:
            flow_to_drive_once(time.time())
        except Exception as e:                                  # noqa: BLE001 — the writer never dies
            print(f"meet-start: writing the meetings' processing into «קבצים»: {e!r}", flush=True)
        time.sleep(FLOW_DRIVE_EVERY)


if __name__ == "__main__":
    if not SECRET:
        print("meet-start: MEET_JWT_SECRET is empty — /healthz answers 503 until apps/meet/hooks/prepare mints it", flush=True)
    # (ASCII only: this line is printed before anything else, whatever the log's encoding)
    kind = store_kind()
    print(f"meet-start: meet-flow {'v1' if FLOW_UI == 'v1' else 'v2'}; its store: "
          + (f"Drive {DRIVE_URL} (profile {DRIVE_PROFILE}), each meeting's folder in {DRIVE_FOLDER!a}" if kind == "drive"
             else f"the folder {FLOW_DATA!a} (" + ("writable" if store_ok() else "missing or read-only") + ")"
             if kind == "local" else "none (MEET_DRIVE_URL is empty): its reads answer empty, its writes 503"), flush=True)
    if MACHINES or LINK_PEERS:
        machines = ThreadingHTTPServer(("0.0.0.0", MACHINE_PORT), MachineDoor)
        threading.Thread(target=machines.serve_forever, name="machines", daemon=True).start()
    if WORKFLOW_HOOK or PLANE_API:
        threading.Thread(target=watch_recordings, name="recordings", daemon=True).start()
    if WORKFLOW_HOOK:
        threading.Thread(target=call_workflow, name="workflow", daemon=True).start()
    if RECORDER_SECRET:
        threading.Thread(target=watch_meetings, name="watch", daemon=True).start()
        threading.Thread(target=tell_flow_links, name="flow-links", daemon=True).start()
        if PLANE_API:
            threading.Thread(target=live_to_plane, name="live", daemon=True).start()
    if DRIVE_URL and DRIVE_PROFILE:
        threading.Thread(target=to_drive, name="drive", daemon=True).start()
    if FLOW_TO_DRIVE and RECORDER_SECRET and kind in ("drive", "local"):
        threading.Thread(target=flow_to_drive, name="flow-drive", daemon=True).start()
    print(f"meet-start: r4 - exports txt/vtt/srt; screen moments; whisper beside ivrit; first processing to the store "
          f"{'every %d s' % FLOW_DRIVE_EVERY if FLOW_TO_DRIVE and RECORDER_SECRET and kind in ('drive', 'local') else 'off'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Door).serve_forever()
