#!/usr/bin/env python3
"""meet-watch — apps/meet: the recorder's own health watchdog, and near-live captions (fireplace, 2026-10-26).

Runs INSIDE meet-jibri as an s6 longrun (jibri/s6/60-meet-watch), as the image's own user, beside
Jibri, Chrome, PulseAudio and ffmpeg. It reads only what the container already holds — no docker
socket, no host path — and speaks through two tiny doors on meet-net:

  * prosody's mod_meet_recorder_watch (HTTP on 5280, a bearer secret minted into .env by
    hooks/prepare): a room message to the room being recorded, as mod_meet_share_notice sends one;
  * meet-start's machines' door (/api/recorder/*, the same secret + the container's name): the
    office's notification centre, and the transcriber (apitools-asr), which this container cannot
    reach itself (it is on meet-net only).

WHY. On 2026-10-26 the recorder was throttled to 0.48 of a core; ffmpeg ran at 0.93-0.97x of real
time, ~40 % of every second of audio became zeros, and nobody in the room was told: the file looked
fine until the owner listened. So, every TICK seconds while Jibri says BUSY, this measures:
  - ffmpeg's own pace: Jibri logs every progress line (ffmpeg.0.txt, `time=` and `speed=`, with the
    time it was logged). The pace between two ticks is Δtime / Δwall — the instantaneous number;
    ffmpeg's `speed=` is an average since the start and lags behind by minutes;
  - how far the recording lags the clock (wall seconds since ffmpeg started minus `time=`);
  - the container's own cgroup (/sys/fs/cgroup/cpu.stat): the share of scheduling periods in which
    the kernel held it back (nr_throttled / nr_periods per tick);
  - ffmpeg and PulseAudio errors in that log, a stalled log (no progress line for 15 s), and Jibri's
    own health (its REST on 2222).
Three bad ticks in a row (15 s) → «⚠️ ההקלטה מאבדת קול/תמונה…» to the room and a warning
notification; three good ticks after that → «✅ …» and the notification is updated. Each recording
gets `<room>_<time>.capture.json` beside its video: wall time, recorded time, final and minimum
pace, throttled periods, and every event — the evidence the file itself does not carry.

CAPTIONS (near-live, 30-60 s behind). The meeting's mix is what Jibri records: PulseAudio's
`jibri-loop.monitor`. A second ffmpeg reads the same monitor into 30-s, 16 kHz mono WAV segments
(30 s is the transcriber's measured sweet spot: Whisper pads every window to 30 s). Each finished
segment goes to the transcriber through meet-start (`/transcribe`, synchronous for short audio;
`whisper` with language `auto` by default, so Hebrew and English are both taken as spoken; `he` →
the office's ivrit model) and the text comes back as a chat line from «כתוביות» — sent with a delay
stamp so the page shows it in the chat without a pop-up or a sound every 30 s — and goes into
`<room>_<time>.live.txt` beside the recording, for the work item. A segment with no sound is not
sent (Whisper invents «תודה רבה» on silence: issues/meet-whisper-hallucinates-thank-you-on-silence).
MEET_LIVE_CAPTIONS: `on`, `off`, or `auto` (default) = on only when the machine has at least
MEET_LIVE_CAPTIONS_MIN_CORES (4) cores AND the recorder is healthy — on a 2-core box the transcriber
and the recorder share the same two cores, and the recorder wins (its weight). A file
/run/meet-watch/captions holding on|off|auto overrides the setting at runtime (for a test).

MEMORY comes before either setting (MEET-48, fireplace 2026-11-01: with swap full, one 30-s segment
took 271 s, the whole machine stalled for 3.5 min and Jibri's killed ffmpeg left an mp4 with no
index). Captions start only with MEET_LIVE_CAPTIONS_MIN_FREE_MB (1536) of MemAvailable — the
transcriber's model is 1.6 GB — and pause while /proc/pressure/memory says every task stalled for
MEET_LIVE_CAPTIONS_PAUSE_PRESSURE (10) % of the last 10 s ("full avg10"); they resume once it is under
2 % with the memory free again, for a minute. The room is told once when they pause.
"""
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

TICK = 5
WINDOW = 3                                   # ticks that must agree before the room is told
JIBRI = "http://localhost:2222/jibri/api/v1.0/health"
LOGDIR = "/var/log/jitsi/jibri"
FFLOG = os.path.join(LOGDIR, "ffmpeg.0.txt")
JLOG = os.path.join(LOGDIR, "log.0.txt")
RECORDINGS = "/storage/recordings"
WORK = "/run/meet-watch"
OVERRIDE = os.path.join(WORK, "captions")
PROSODY = os.environ.get("MEET_PROSODY_HTTP", "http://meet-prosody:5280").rstrip("/")
PROSODY_HOST = os.environ.get("MEET_PROSODY_HTTP_HOST", "muc.meet.jitsi")
START = os.environ.get("MEET_START_MACHINES", "http://meet-start:8001").rstrip("/")
SECRET = os.environ.get("MEET_RECORDER_WATCH_SECRET", "").strip()
CAPTIONS = (os.environ.get("MEET_LIVE_CAPTIONS") or "auto").strip().lower()
LANGUAGE = (os.environ.get("MEET_LIVE_CAPTIONS_LANGUAGE") or "auto").strip().lower() or "auto"
SEGMENT = max(10, min(60, int(os.environ.get("MEET_LIVE_CAPTIONS_SEGMENT") or 30)))
MIN_CORES = int(os.environ.get("MEET_LIVE_CAPTIONS_MIN_CORES") or 4)
PULSE_SOURCE = os.environ.get("MEET_LIVE_CAPTIONS_SOURCE", "jibri-loop.monitor")
MIN_FREE_MB = int(os.environ.get("MEET_LIVE_CAPTIONS_MIN_FREE_MB") or 1536)
PAUSE_PRESSURE = float(os.environ.get("MEET_LIVE_CAPTIONS_PAUSE_PRESSURE") or 10)
CALM_PRESSURE = 2.0
CALM_SECONDS = 60
SLOW = 0.97          # pace below this is "losing time" (fpg103 ran at 0.968x and lost 23 s of 884)
FINE = 0.99
THROTTLED = 0.10     # a tenth of the periods held back is a starved recorder (fpg103: 41 %)
QUIET_PEAK = 300     # of 32767: a 30-s segment whose loudest sample is below this has no speech

PROGRESS = re.compile(r"^Jibri (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.(\d{3}) .*?(?:frame=|size=).*?time=(\d+):(\d\d):(\d\d(?:\.\d+)?).*?speed=\s*([\d.]+)x")
STARTING = re.compile(r"^Jibri (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.(\d{3}) .*?\[session_id=([0-9a-f-]+)\] JibriSubprocess\.launch#\d+: Starting ffmpeg with: \[(.*)\]")
TROUBLE = re.compile(r"(?i)\b(error|cannot|could not|failed|invalid|no such|broken pipe|connection refused|pa_|pulse)")
HARMLESS = re.compile(r"(?i)(^Jibri .*\[(libx264|aac|mp4|x11grab|pulse) @ 0x[0-9a-f]+\] (i8c|kb/s|Qavg|frame|mb |coded|ref|8x8|transform|direct|consecutive|final rate|i16|P16|B16|PSNR|SSIM|Weighted)|Exiting normally|deprecated|Guessed Channel Layout|Starting ffmpeg|Stream mapping|Press \[q\]|Input #\d+, (pulse|x11grab), from)")
# What Whisper writes into near-silence and crosstalk, measured on this office (2026-10-27, qacap2: three people,
# a shared screen): «פפפפפפפפפ», a run of «ב» with bidi marks then «תודה רבה.», «בבקשה» — a line like that on the
# room's screen is worse than none. So the bidi marks go, a character repeated five times or more ends the line
# there (the rest is noise), and a line that is only a courtesy word is dropped (HALLUCINATED below).
BIDI = re.compile("[‎‏‪-‮⁦-⁩]")
STUTTER = re.compile(r"(\S)\1{4,}")


def clean_caption(text):
    text = BIDI.sub("", text or "").strip()
    m = STUTTER.search(text)
    if m:
        text = text[:m.start()].strip()
    words = text.split()
    while words and len(words[-1].strip(".,!?")) <= 1:      # the stub a cut stutter leaves («ב ב ב»)
        words.pop()
    return " ".join(words)


HALLUCINATED = {"תודה רבה", "תודה רבה.", "תודה.", "תודה", "thank you.", "thank you", "thanks for watching.", "thanks for watching",
                "subtitles by the amara.org community", "you", "you.", "bye.", "bye", "כתוביות", "בבקשה", "בבקשה.",
                "תודה רבה לכם", "תודה רבה לכם.", "תודה רבה רבה", "שלום", "שלום."}


def log(msg):
    print(time.strftime("%H:%M:%S") + " meet-watch " + msg, flush=True)


def parse_stamp(day, ms):
    """A Jibri log stamp (local time, TZ of the container) → epoch seconds."""
    return time.mktime(time.strptime(day, "%Y-%m-%d %H:%M:%S")) + int(ms) / 1000.0


def http(url, body=None, headers=None, timeout=20, method=None):
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"))
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (OSError, ValueError) as e:
        return 0, str(e).encode()


def tail(path, size=65536):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - size))
            return f.read().decode("utf-8", "replace"), end
    except OSError:
        return "", 0


def cpu_stat():
    out = {}
    try:
        with open("/sys/fs/cgroup/cpu.stat") as f:
            for line in f:
                k, _, v = line.partition(" ")
                out[k] = int(v)
    except (OSError, ValueError):
        pass
    return out


def jibri():
    code, body = http(JIBRI, timeout=5)
    if code != 200:
        return None, None
    try:
        status = json.loads(body)["status"]
        return status.get("busyStatus"), (status.get("health") or {}).get("healthStatus")
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, None


# ── the room and the notice centre ───────────────────────────────────────────────────────────────

def tell_room(kind, text, room=None):
    """kind: recorder (a pop-up, from «הקלטה») or caption (a quiet chat line, from «כתוביות»)."""
    if not SECRET:
        return False
    body = json.dumps({"text": text, "room": room}, ensure_ascii=False).encode("utf-8")
    code, got = http(f"{PROSODY}/meet-recorder-watch/{kind}", body,
                     {"Host": PROSODY_HOST, "Authorization": "Bearer " + SECRET, "Content-Type": "application/json"}, timeout=10)
    if code != 200:
        log(f"prosody did not take the {kind} message: HTTP {code} {got[:160]!r}")
        return False
    return True


def notify(state, title, body, session, room):
    if not SECRET:
        return
    payload = json.dumps({"state": state, "title": title, "body": body, "session": session, "room": room}, ensure_ascii=False).encode("utf-8")
    code, got = http(f"{START}/api/recorder/health", payload,
                     {"Authorization": "Bearer " + SECRET, "Content-Type": "application/json"}, timeout=15)
    if code != 200:
        log(f"meet-start did not take the notification: HTTP {code} {got[:160]!r}")


# ── one recording, as the logs tell it ────────────────────────────────────────────────────────────

class Recording:
    def __init__(self):
        self.session = None
        self.started = None          # epoch: ffmpeg launched
        self.path = None             # the .mp4 Jibri writes
        self.room = None
        self.last_time = None        # (logged_at, ffmpeg time=) of the newest progress line
        self.prev_time = None        # …and the one from the previous tick
        self.first_time = None       # …and the first one: the lag is measured from it, not from the
                                     # launch (x11grab takes 2-3 s to open before the first frame)
        self.said_at = 0             # the last periodic status line
        self.speed = None            # ffmpeg's own cumulative speed
        self.min_pace = None
        self.offset = 0              # how far the ffmpeg log was read for errors
        self.errors = []             # recent trouble lines (text, at)
        self.events = []             # [{at, state, why}]
        self.state = "ok"
        self.bad = 0                 # consecutive bad / good ticks
        self.good = 0
        self.degraded_at = None
        self.throttled0 = None       # cpu.stat at the start
        self.throttle_window = []    # (Δthrottled, Δperiods) per tick, last WINDOW
        self.captions = 0
        self.caption_lag = []

    @property
    def stem(self):
        return self.path[:-4] if self.path and self.path.endswith(".mp4") else self.path

    def find(self):
        """The newest 'Starting ffmpeg' in Jibri's log that has no 'Stopping ffmpeg' after it is this
        recording (Jibri is BUSY while Chrome still joins: then the newest start is the LAST recording's,
        already stopped, and this waits). Its command names the file."""
        text, _ = tail(JLOG, 400000)
        found = None
        for line in text.splitlines():
            m = STARTING.match(line)
            if m:
                found = m
            elif found and "JibriSubprocess.stop" in line and f"[session_id={found.group(3)}]" in line:
                found = None
        if not found:
            return False
        args = [a.strip() for a in found.group(4).split(", ")]
        path = next((a for a in reversed(args) if a.endswith(".mp4")), None)
        if not path:
            return False
        self.session, self.started, self.path = found.group(3), parse_stamp(found.group(1), found.group(2)), path
        name = os.path.basename(path)[:-4]
        self.room = re.sub(r"_\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d$", "", name)
        return True

    def read_progress(self):
        """The newest progress line of ffmpeg.0.txt, and every trouble line logged since last time."""
        text, end = tail(FFLOG, 32768)
        if end < self.offset:              # rotated
            self.offset = 0
        for line in text.splitlines():
            m = PROGRESS.match(line)
            if m:
                at = parse_stamp(m.group(1), m.group(2))
                secs = int(m.group(3)) * 3600 + int(m.group(4)) * 60 + float(m.group(5))
                if at >= (self.started or 0) - 2:
                    self.last_time = (at, secs)
                    if self.first_time is None:
                        self.first_time = (at, secs)
                    try:
                        self.speed = float(m.group(6))
                    except ValueError:
                        pass
        # trouble: only the bytes appended since the last tick
        try:
            with open(FFLOG, "rb") as f:
                f.seek(self.offset)
                fresh = f.read().decode("utf-8", "replace")
                self.offset = f.tell()
        except OSError:
            fresh = ""
        now = time.time()
        for line in fresh.splitlines():
            if PROGRESS.match(line) or HARMLESS.search(line):
                continue
            if TROUBLE.search(line):
                self.errors.append((line[-200:], now))
        self.errors = [e for e in self.errors if now - e[1] <= TICK * WINDOW]


def judge(rec, healthy, stat, prev_stat):
    """One tick: is the recorder keeping up? Returns (bad: bool, why: str, numbers: dict)."""
    why, numbers = [], {}
    now = time.time()
    # the kernel's throttling of this container's cgroup, over the last WINDOW ticks
    if stat and prev_stat:
        d_thr, d_per = stat.get("nr_throttled", 0) - prev_stat.get("nr_throttled", 0), stat.get("nr_periods", 0) - prev_stat.get("nr_periods", 0)
        rec.throttle_window = (rec.throttle_window + [(d_thr, d_per)])[-WINDOW:]
    thr = sum(a for a, _ in rec.throttle_window)
    per = sum(b for _, b in rec.throttle_window)
    frac = thr / per if per else 0.0
    numbers["throttled_share"] = round(frac, 3)
    if per >= WINDOW * 10 and frac >= THROTTLED:
        why.append(f"CPU throttled {frac:.0%} of the time")
    # ffmpeg's pace between this tick's progress line and the previous tick's
    pace = None
    if rec.last_time and rec.prev_time and rec.last_time[0] > rec.prev_time[0] + 1:
        pace = (rec.last_time[1] - rec.prev_time[1]) / (rec.last_time[0] - rec.prev_time[0])
        numbers["pace"] = round(pace, 3)
        rec.min_pace = pace if rec.min_pace is None else min(rec.min_pace, pace)
        if now - rec.started > 20 and pace < SLOW:
            why.append(f"ffmpeg at {pace:.2f}x of real time")
    if rec.last_time:
        lag = (rec.last_time[0] - rec.first_time[0]) - (rec.last_time[1] - rec.first_time[1])
        numbers["lag_seconds"] = round(lag, 1)
        numbers["speed"] = rec.speed
        if now - rec.last_time[0] > 15:
            why.append(f"no progress from ffmpeg for {now - rec.last_time[0]:.0f} s")
    elif now - rec.started > 30:
        why.append("ffmpeg has logged no progress")
    if now - rec.said_at >= 60:                      # a status line a minute: the evidence trail
        rec.said_at = now
        log(f"recording {rec.session[:8]} {rec.state}: {numbers} bad={rec.bad} good={rec.good}")
    if len(rec.errors) >= 3 or any("pulse" in e[0].lower() or "pa_" in e[0].lower() for e in rec.errors):
        why.append("ffmpeg/pulse errors: " + rec.errors[-1][0][-90:].strip())
    if healthy and healthy != "HEALTHY":
        why.append(f"Jibri says {healthy}")
    rec.prev_time = rec.last_time
    return bool(why), "; ".join(why), numbers


def he_why(why):
    """The Hebrew half of the reason, from the English one: the numbers are the message."""
    out = []
    for part in why.split("; "):
        if part.startswith("CPU throttled"):
            out.append("המעבד חונק את המקליט " + part.split("throttled ", 1)[1].split(" of")[0] + " מהזמן")
        elif part.startswith("ffmpeg at"):
            out.append("ffmpeg מקליט ב-" + part.split("at ", 1)[1].split(" of")[0] + " מזמן אמת")
        elif part.startswith("no progress"):
            out.append("ffmpeg לא מתקדם")
        elif part.startswith("ffmpeg has logged"):
            out.append("ffmpeg לא התחיל להקליט")
        elif part.startswith("ffmpeg/pulse"):
            out.append("שגיאות ffmpeg/pulse")
        elif part.startswith("Jibri says"):
            out.append("Jibri מדווח " + part.split("says ", 1)[1])
        else:
            out.append(part)
    return ", ".join(out)


def capture_json(rec, stat):
    """<room>_<time>.capture.json beside the recording: what the file cannot say about itself."""
    if not rec.stem:
        return
    try:
        wall = (rec.last_time[0] if rec.last_time else time.time()) - rec.started
        thr0 = rec.throttled0 or {}
        lost = ((rec.last_time[0] - rec.first_time[0]) - (rec.last_time[1] - rec.first_time[1])) if rec.last_time else None
        doc = {
            "session": rec.session, "room": rec.room, "started": int(rec.started),
            "wall_seconds": round(wall, 1),
            "recorded_seconds": round(rec.last_time[1], 1) if rec.last_time else None,
            # the clock's seconds that never reached the file, between the first and the last frame
            # (ffmpeg's own 2-3 s of opening x11grab are not counted)
            "lost_seconds": round(lost, 1) if lost is not None else None,
            "final_speed": rec.speed, "min_pace": round(rec.min_pace, 3) if rec.min_pace is not None else None,
            "throttled_periods": (stat.get("nr_throttled", 0) - thr0.get("nr_throttled", 0)) if stat and thr0 else None,
            "periods": (stat.get("nr_periods", 0) - thr0.get("nr_periods", 0)) if stat and thr0 else None,
            "throttled_seconds": round((stat.get("throttled_usec", 0) - thr0.get("throttled_usec", 0)) / 1e6, 1) if stat and thr0 else None,
            "degraded_seconds": round(sum(e.get("for", 0) for e in rec.events if e["state"] == "ok"), 1),
            "events": rec.events,
            "captions": rec.captions,
            "caption_lag_seconds": {"n": len(rec.caption_lag), "median": sorted(rec.caption_lag)[len(rec.caption_lag) // 2] if rec.caption_lag else None,
                                    "max": max(rec.caption_lag) if rec.caption_lag else None},
        }
        tmp = rec.stem + ".capture.json.part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, rec.stem + ".capture.json")
    except OSError as e:
        log(f"could not write capture.json: {e}")


# ── captions ──────────────────────────────────────────────────────────────────────────────────────

class Captions:
    """One ffmpeg reading the recorder's monitor into SEGMENT-second WAVs; a thread that sends each
    finished one to the transcriber (through meet-start) and posts the text to the room."""

    def __init__(self, rec):
        self.rec = rec
        # one folder per start: a pump left behind by a pause (end(wait=False)) still unlinks its own
        # segment when its transcription comes back, and must never meet the resumed one's 00000.wav
        self.dir = os.path.join(WORK, f"seg-{(rec.session or 'x')[:8]}-{int(time.time())}")
        self.proc = None
        self.started = None
        self.sent = -1
        self.stop = threading.Event()
        self.abandon = threading.Event()
        self.thread = None
        self.warned_lag = False
        self.transcript = (rec.stem + ".live.txt") if rec.stem else None

    def start(self):
        os.makedirs(self.dir, exist_ok=True)
        for f in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, f))
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "pulse", "-i", PULSE_SOURCE,
               "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", str(SEGMENT),
               "-reset_timestamps", "1", os.path.join(self.dir, "%05d.wav")]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.started = time.time()
        self.thread = threading.Thread(target=self.pump, name="captions", daemon=True)
        self.thread.start()
        log(f"captions on: {PULSE_SOURCE} → {SEGMENT}-s segments, language {LANGUAGE}, transcript {self.transcript}")

    def end(self, wait=True):
        """wait=False (a pause under memory pressure): the segments not sent yet are dropped and the
        loop does not wait for a transcription in flight — the watchdog must keep its 5-s tick."""
        self.stop.set()
        if not wait:
            self.abandon.set()
            if self.proc and self.proc.poll() is None:
                self.proc.kill()                 # its segments are dropped anyway: no 10-s wait for a clean stop
                threading.Thread(target=self.proc.wait, daemon=True).start()
            return
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.thread and wait:
            self.thread.join(90)
        try:
            for f in os.listdir(self.dir):
                os.unlink(os.path.join(self.dir, f))
            os.rmdir(self.dir)
        except OSError:
            pass
        log(f"captions off: {self.rec.captions} lines, lag median "
            f"{sorted(self.rec.caption_lag)[len(self.rec.caption_lag) // 2] if self.rec.caption_lag else '-'} s")

    def pump(self):
        """Segment N is whole once N+1 exists (or ffmpeg has exited). One at a time, in order."""
        while True:
            if self.abandon.is_set():
                try:                                 # its own folder only (one per start)
                    for f in os.listdir(self.dir):
                        os.unlink(os.path.join(self.dir, f))
                    os.rmdir(self.dir)
                except OSError:
                    pass
                return
            try:
                files = sorted(f for f in os.listdir(self.dir) if f.endswith(".wav"))
            except OSError:
                files = []
            ended = self.proc is None or self.proc.poll() is not None
            ready = files[:-1] if not ended else files
            ready = [f for f in ready if int(f[:5]) > self.sent]
            if not ready:
                if ended and self.stop.is_set():
                    return
                time.sleep(1)
                continue
            # a backlog the transcriber cannot clear is dropped, oldest first, and said once
            if len(ready) > 3:
                dropped, ready = ready[:-2], ready[-2:]
                for f in dropped:
                    os.unlink(os.path.join(self.dir, f))
                log(f"captions lag: dropped {len(dropped)} segment(s) — the transcriber is slower than the meeting")
                if not self.warned_lag:
                    self.warned_lag = True
                    tell_room("caption", "⚠️ המתמלל לא עומד בקצב הפגישה — חלק מהכתוביות יחסרו. · The transcriber is slower than the meeting — some captions will be missing.", self.rec.room)
            f = ready[0]
            index = int(f[:5])
            self.sent = index
            path = os.path.join(self.dir, f)
            try:
                self.one(path, index)
            except Exception as e:                   # noqa: BLE001 — a bad segment never stops the next
                log(f"caption {index} failed: {type(e).__name__}: {e}")
            try:
                os.unlink(path)
            except OSError:
                pass

    def one(self, path, index):
        seg_start = self.started + index * SEGMENT
        seg_end = seg_start + SEGMENT
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            with wave.open(path, "rb") as w:
                frames, rate = w.getnframes(), w.getframerate()
                duration = frames / float(rate or 16000)
                w.setpos(0)
                raw = w.readframes(frames)
        except (wave.Error, EOFError):
            return
        if duration < 1.5:
            return
        seg_end = seg_start + duration
        peak = 0
        step = 8 * 2                                   # every 8th sample is enough for a peak
        for off in range(0, len(raw) - 1, step):
            v = struct.unpack_from("<h", raw, off)[0]
            if v < 0:
                v = -v
            if v > peak:
                peak = v
        if peak < QUIET_PEAK:
            log(f"caption {index}: {duration:.0f} s, no sound (peak {peak}) — not sent")
            return
        t0 = time.time()
        code, body = http(f"{START}/api/recorder/captions?language={LANGUAGE}", data,
                          {"Authorization": "Bearer " + SECRET, "Content-Type": "audio/wav"}, timeout=240)
        took = time.time() - t0
        if code != 200:
            log(f"caption {index}: transcriber answered HTTP {code} after {took:.0f} s: {body[:120]!r}")
            return
        try:
            text = clean_caption(json.loads(body).get("text") or "")
        except (ValueError, AttributeError):
            text = ""
        lag = time.time() - seg_end
        if self.abandon.is_set():
            # paused while this one was being transcribed: the room was told they stopped, and a pump
            # resumed since owns the room and the .live.txt — a late line would come out of order
            log(f"caption {index}: came back after the captions were paused — not posted")
            return
        if not text or text.lower().strip(" .!") in {h.strip(" .!") for h in HALLUCINATED} or len(text.strip(" .!?")) < 2:
            log(f"caption {index}: {duration:.0f} s, peak {peak}, {took:.0f} s of transcription, nothing to say ({text!r})")
            return
        self.rec.captions += 1
        self.rec.caption_lag.append(round(lag, 1))
        rel = max(0, seg_start - self.rec.started)
        mark = f"{int(rel // 60):02d}:{int(rel % 60):02d}"
        log(f"caption {index}: {duration:.0f} s, transcribed in {took:.0f} s, {lag:.0f} s behind the meeting: {text[:80]!r}")
        tell_room("caption", f"[{mark}] {text}", self.rec.room)
        if self.transcript:
            try:
                with open(self.transcript, "a", encoding="utf-8") as fh:
                    fh.write(f"[{mark}] {text}\n")
            except OSError as e:
                log(f"could not write the transcript: {e}")


def memory():
    """(MemAvailable in MB, /proc/pressure/memory full avg10 in %) — None for what cannot be read."""
    avail = pressure = None
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError):
        pass
    try:
        with open("/proc/pressure/memory", encoding="ascii") as f:
            for line in f:
                if line.startswith("full "):
                    pressure = float(line.split()[1].split("=")[1])
    except (OSError, ValueError, IndexError):
        pass
    return avail, pressure


class MemoryGuard:
    """Whether the machine has the memory for live captions now: pressure pauses them at once, and
    they come back only after CALM_SECONDS of low pressure with MIN_FREE_MB available."""

    def __init__(self):
        self.paused_at = None
        self.calm_since = None

    def allows(self, running):
        avail, pressure = memory()
        now = time.time()
        if pressure is not None and pressure >= PAUSE_PRESSURE:
            self.calm_since = None
            if self.paused_at is None:
                self.paused_at = now
            return False, f"memory pressure {pressure:.1f} % ≥ {PAUSE_PRESSURE:g} % (available {avail} MB)", True
        low = avail is not None and avail < MIN_FREE_MB
        if self.paused_at is not None:
            if low or (pressure is not None and pressure >= CALM_PRESSURE):
                self.calm_since = None
                return False, f"paused: memory available {avail} MB, pressure {pressure} %", False
            self.calm_since = self.calm_since or now
            if now - self.calm_since < CALM_SECONDS:
                return False, f"paused: memory calm for {now - self.calm_since:.0f} of {CALM_SECONDS} s", False
            self.paused_at = self.calm_since = None
        if low and not running:
            return False, f"memory available {avail} MB < {MIN_FREE_MB} MB (the transcriber's model is 1.6 GB)", False
        return True, f"memory available {avail} MB, pressure {pressure} %", False


def captions_wanted(rec_state):
    """on | off | auto, from the override file first, then the environment."""
    mode = CAPTIONS
    try:
        with open(OVERRIDE, encoding="utf-8") as f:
            got = f.read().strip().lower()
        if got in ("on", "off", "auto", "1", "0"):
            mode = got
    except OSError:
        pass
    if mode in ("on", "1", "true", "yes"):
        return True, "forced on"
    if mode in ("off", "0", "false", "no"):
        return False, "off"
    cores = os.cpu_count() or 1
    if cores < MIN_CORES:
        return False, f"auto: {cores} cores < {MIN_CORES}"
    if rec_state != "ok":
        return False, "auto: the recorder is not healthy"
    return True, f"auto: {cores} cores, recorder healthy"


# ── the loop ──────────────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(WORK, exist_ok=True)
    if not SECRET:
        log("MEET_RECORDER_WATCH_SECRET is empty — the room and the notice centre are not told (apps/meet/hooks/prepare mints it)")
    log(f"watching Jibri every {TICK} s; captions {CAPTIONS} (language {LANGUAGE}, {SEGMENT}-s segments, auto needs {MIN_CORES} cores; this machine has {os.cpu_count()})")
    rec, caps, prev_stat = None, None, None
    said_caps = None
    guard = MemoryGuard()
    told_paused = False
    while True:
        time.sleep(TICK)
        busy, healthy = jibri()
        stat = cpu_stat()
        if busy == "BUSY" and rec is None:
            rec = Recording()
            if not rec.find() or rec.started < time.time() - 3600:
                rec = None                         # Jibri is busy but ffmpeg has not started yet (Chrome joining)
                prev_stat = stat
                continue
            rec.throttled0 = stat
            rec.offset = tail(FFLOG, 1)[1]        # errors from here on
            log(f"recording {rec.session} of room {rec.room!r} → {rec.path}")
        if rec is None:
            prev_stat = stat
            continue
        if busy != "BUSY":
            # the recording ended: the last word on it, beside the file
            if caps:
                caps.end()
                caps = None
            rec.read_progress()
            if rec.state != "ok":
                rec.events.append({"at": int(time.time()), "state": "ended-degraded", "for": round(time.time() - rec.degraded_at, 1)})
                notify("ok", f"ההקלטה של {rec.room} הסתיימה בזמן תקלה", "The recording ended while degraded; see capture.json beside it.", rec.session, rec.room)
            capture_json(rec, stat)
            log(f"recording {rec.session} ended: wall {time.time() - rec.started:.0f} s, recorded {rec.last_time[1] if rec.last_time else '?'} s, "
                f"speed {rec.speed}, min pace {rec.min_pace}, state {rec.state}")
            rec, caps, prev_stat = None, None, stat
            told_paused = False
            continue
        rec.read_progress()
        bad, why, numbers = judge(rec, healthy, stat, prev_stat)
        prev_stat = stat
        if bad:
            rec.bad, rec.good = rec.bad + 1, 0
        else:
            rec.good, rec.bad = rec.good + 1, 0
        if rec.state == "ok" and rec.bad >= WINDOW:
            rec.state, rec.degraded_at = "degraded", time.time()
            rec.events.append({"at": int(time.time()), "state": "degraded", "why": why, **numbers})
            lag = numbers.get("lag_seconds")
            lag_he = f" ההקלטה כבר מפגרת ב-{lag:.0f} שניות אחרי השעון." if lag and lag >= 2 else ""
            lag_en = f" The recording is already {lag:.0f} s behind the clock." if lag and lag >= 2 else ""
            text = (f"⚠️ ההקלטה מאבדת קול/תמונה — המקליט לא עומד בקצב ({he_why(why)}).{lag_he} מה שנאמר עכשיו עלול לא להיכנס להקלטה — "
                    f"כדאי לחזור על הדברים החשובים כשתגיע ההודעה שההקלטה תקינה. · ⚠️ The recording is losing sound/video — the recorder "
                    f"is falling behind ({why}).{lag_en} What is said now may be missing from the recording; repeat what matters once it says it is back.")
            log(f"DEGRADED: {why} {numbers}")
            tell_room("recorder", text, rec.room)
            notify("degraded", f"⚠️ ההקלטה של {rec.room} מאבדת קול/תמונה", f"{why}. {json.dumps(numbers)}", rec.session, rec.room)
            capture_json(rec, stat)
        elif rec.state == "degraded" and rec.good >= WINDOW:
            for_s = time.time() - rec.degraded_at
            rec.state = "ok"
            rec.events.append({"at": int(time.time()), "state": "ok", "for": round(for_s, 1), **numbers})
            text = (f"✅ ההקלטה חזרה לקצב מלא (אחרי {for_s:.0f} שניות של תקלה). · ✅ The recording is back at full speed "
                    f"(after {for_s:.0f} s of trouble).")
            log(f"OK again after {for_s:.0f} s {numbers}")
            tell_room("recorder", text, rec.room)
            notify("ok", f"✅ ההקלטה של {rec.room} חזרה לתקינות", f"degraded for {for_s:.0f} s; {json.dumps(numbers)}", rec.session, rec.room)
            capture_json(rec, stat)
        # captions follow the switch and the recorder's health — and before both, the memory
        want, reason = captions_wanted(rec.state)
        pressed = False
        if want:
            want, reason, pressed = guard.allows(caps is not None)
        kind = re.sub(r"[\d.]+", "#", reason)       # said once per kind of reason, not per number
        if kind != said_caps:
            log(f"captions: {reason}")
            said_caps = kind
        if pressed and caps is not None:
            caps.end(wait=False)
            caps = None
            rec.events.append({"at": int(time.time()), "state": "captions-paused", "why": reason})
            if not told_paused:
                told_paused = True
                tell_room("caption", "⏸️ הכתוביות החיות הושהו — לשרת חסר זיכרון, וההקלטה קודמת. הן יחזרו לבד. · Live captions are paused — "
                          "the server is short of memory and the recording comes first. They will come back by themselves.", rec.room)
        elif want and caps is None and rec.stem:
            caps = Captions(rec)
            try:
                caps.start()
            except OSError as e:
                log(f"captions could not start: {e}")
                caps = None
        elif not want and caps is not None:
            # during a recording the tick goes on: a degraded recorder (the MEET-48 freeze degraded it
            # first) is exactly when a 100-s join would have left the room untold
            caps.end(wait=False)
            caps = None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
