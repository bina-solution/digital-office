#!/usr/bin/env python3
"""call_inside.py — the meeting half of `./bbox meet verify --call` (apps/meet/qa/verify_call.py, FPG-87).

Runs INSIDE the throwaway container verify_call.py starts from the recorder's own image (Chrome, Xorg's dummy
driver, ffmpeg with flite, python3), as root. One synthetic meeting on the live office, its pages driven through
Chrome's DevTools protocol; everything the pages saw goes to <work>/out/timeline.json. Standard library only.

    python3 call_inside.py --work /w --meet https://meet.<domain> --room <room> [--seconds 170] [--speak 75]

<work> holds what verify_call.py put there: host.jwt (the host's token: read, never printed), xorg.conf (the live
recorder's own dummy-display config), known.json and he.ogg (the known speech). Two participants:
  host   the office's host token; its microphone is the known speech (Chrome's fake capture from a WAV: Hebrew,
         then English, repeated for --speak seconds, then digital silence); its page is 412 px wide — a phone's width,
         so the captions are seen as a phone shows them;
  guest  no token and NO microphone track at all (never unmuted): the silent-mic guard's case 1.
A headless Chrome makes no local tracks (measured 2026-10-26), so both are real windows on a dummy X display.
"""
import argparse
import base64
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HOST_PORT, GUEST_PORT = 9301, 9302
HOST_NAME, GUEST_NAME = "בדיקת שיחה", "Verify No Mic"

# Installed before any page script (Page.addScriptToEvaluateOnNewDocument): (1) counts every SpeechRecognition the
# page makes and starts — Chrome's Web Speech captions send the voice to Google, and the office's rule is that no
# voice leaves it (FPG-359); (2) every 500 ms: the ICE servers the bridge's connection was given (STUN/TURN: whose?),
# and from Jitsi's own store when the page joined, each chat line and each pop-up the first time it is there, the
# recording's states, the captions overlay's text.
HOOK = r"""
(function () {
  if (window.__verify) { return; }
  var V = window.__verify = {speech: {made: 0, started: 0}, ice: [], chat: {}, notes: {}, rec: {}, joined: 0, captions: {}, n: 0};
  ['SpeechRecognition', 'webkitSpeechRecognition'].forEach(function (k) {
    var C = window[k];
    if (!C) { return; }
    var W = function () {
      V.speech.made++;
      var r = new (Function.prototype.bind.apply(C, [null].concat([].slice.call(arguments))))();
      var s = r.start;
      r.start = function () { V.speech.started++; return s.apply(r, arguments); };
      return r;
    };
    W.prototype = C.prototype;
    try { Object.defineProperty(window, k, {value: W, configurable: true, writable: true}); } catch (e) { window[k] = W; }
  });
  setInterval(function () {
    try {
      if (!window.APP || !APP.store) { return; }
      var s = APP.store.getState(), now = Date.now();
      V.n++;
      if (!V.joined && APP.conference && APP.conference.isJoined()) { V.joined = now; }
      // the ICE servers the bridge's connection was given (standard getConfiguration(); nothing is wrapped)
      try {
        var pc = APP.conference._room.jvbJingleSession.peerconnection.peerconnection;
        ((pc.getConfiguration() || {}).iceServers || []).forEach(function (x) {
          [].concat(x.urls || x.url || []).forEach(function (u) { u = String(u).split('?')[0]; if (V.ice.indexOf(u) < 0) { V.ice.push(u); } });
        });
      } catch (e) {}
      (((s['features/chat'] || {}).messages) || []).forEach(function (m) {
        var k = m.messageId || m.id || ((m.displayName || '') + '|' + m.message);
        if (!V.chat[k]) { V.chat[k] = {t: now, from: String(m.displayName || ''), text: String(m.message || '').slice(0, 900), stamp: m.timestamp || null, priv: !!m.privateMessage}; }
      });
      (((s['features/notifications'] || {}).notifications) || []).forEach(function (x) {
        var p = x.props || {};
        var k = x.uid || (String(p.title || p.titleKey) + '|' + String(p.description || p.descriptionKey));
        if (!V.notes[k]) { V.notes[k] = {t: now, title: String(p.title || p.titleKey || ''), text: String(p.description || p.descriptionKey || '').slice(0, 900)}; }
      });
      (((s['features/recording'] || {}).sessionDatas) || []).forEach(function (d) {
        if (d.status && !V.rec[d.status]) { V.rec[d.status] = now; }
      });
      var c = document.getElementById('meet-captions');
      if (c && c.style.display !== 'none' && c.textContent) {
        var t = c.textContent.slice(0, 400);
        if (!V.captions[t]) { V.captions[t] = now; }
      }
    } catch (e) {}
  }, 500);
})();
"""

# the page's state; `track`: Jitsi's own store holds a local audio track (this build has no getLocalAudioTrack())
STATE = ("(function(){try{var c=window.APP&&APP.conference;var j=!!(c&&c.isJoined());"
         "var tr=((APP.store.getState()['features/base/tracks'])||[]).filter(function(t){return t.local&&t.mediaType==='audio'})[0];"
         "return JSON.stringify({joined:j,audioMuted:j?c.isLocalAudioMuted():null,"
         "track:!!tr,trackMuted:tr?!!tr.muted:null,members:j?c.membersCount:0,"
         "banner:(document.getElementById('meet-mic-banner')||{getAttribute:function(){return null}}).getAttribute('data-state'),"
         "now:Date.now()})}catch(e){return JSON.stringify({error:String(e),now:Date.now()})}})()")


def log(msg):
    print(time.strftime("%H:%M:%SZ", time.gmtime()) + " " + msg, flush=True)


# ── a small DevTools client: one websocket to one page, a reader thread, commands answered by id ─────────────────
class Page:
    def __init__(self, port, timeout=60):
        self.port, self.events, self.answers, self.next = port, [], {}, 0
        self.cv = threading.Condition()
        until = time.time() + timeout
        target = None
        while time.time() < until and not target:
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5))
                target = next((t for t in targets if t.get("type") == "page"), None)
            except (OSError, ValueError):
                pass
            if not target:
                time.sleep(1)
        if not target:
            raise RuntimeError(f"no Chrome page on :{port} in {timeout} s")
        u = urllib.parse.urlparse(target["webSocketDebuggerUrl"])
        self.sock = socket.create_connection((u.hostname, u.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("DevTools closed the handshake")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError("DevTools refused the websocket: " + buf[:120].decode("latin-1"))
        self.sock.settimeout(None)
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _rd(self, n):
        b = b""
        while len(b) < n:
            c = self.sock.recv(n - len(b))
            if not c:
                raise EOFError
            b += c
        return b

    def _reader(self):
        try:
            data = b""
            while True:
                h = self._rd(2)
                fin, op, n = h[0] & 0x80, h[0] & 0x0F, h[1] & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._rd(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._rd(8))[0]
                payload = self._rd(n)
                if op == 8:
                    break
                if op in (1, 2, 0):
                    data += payload
                    if not fin:
                        continue
                    try:
                        msg = json.loads(data)
                    except ValueError:
                        msg = {}
                    data = b""
                    with self.cv:
                        if "id" in msg:
                            self.answers[msg["id"]] = msg
                        elif msg.get("method"):
                            self.events.append(msg)
                            if len(self.events) > 20000:
                                del self.events[:5000]
                        self.cv.notify_all()
        except (OSError, EOFError):
            pass
        finally:
            self.alive = False
            with self.cv:
                self.cv.notify_all()

    def call(self, method, params=None, timeout=30):
        with self.cv:
            self.next += 1
            i = self.next
        data = json.dumps({"id": i, "method": method, "params": params or {}}).encode()
        mask, n = os.urandom(4), len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
                                if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(head + mask + bytes(b ^ mask[k % 4] for k, b in enumerate(data)))
        until = time.time() + timeout
        with self.cv:
            while i not in self.answers:
                left = until - time.time()
                if left <= 0 or not self.alive:
                    raise TimeoutError(f"{method}: no answer")
                self.cv.wait(left)
            return self.answers.pop(i)

    def eval(self, expr, timeout=20):
        m = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, timeout)
        r = (m.get("result") or {}).get("result") or {}
        return r.get("value")

    def json_eval(self, expr, timeout=20):
        try:
            v = self.eval(expr, timeout)
            return json.loads(v) if isinstance(v, str) else v
        except (TimeoutError, ValueError, OSError):
            return None

    def shot(self, path):
        try:
            m = self.call("Page.captureScreenshot", {"format": "png"}, 30)
            data = (m.get("result") or {}).get("data")
            if data:
                with open(path, "wb") as f:
                    f.write(base64.b64decode(data))
                return os.path.basename(path)
        except (TimeoutError, OSError, ValueError):
            pass
        return None

    def drain(self):
        with self.cv:
            ev, self.events = self.events, []
        return ev


# ── the known speech, as one WAV Chrome plays as its microphone ─────────────────────────────────────────────────
def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *args], check=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def make_speech(work, known, speak, total):
    a = os.path.join(work, "audio")
    os.makedirs(a, exist_ok=True)
    if speak <= 0:                       # --silent: an open microphone that gives nothing (the never-heard case)
        ff("-f", "lavfi", "-t", f"{total:.0f}", "-i", "anullsrc=r=48000:cl=mono", "-c:a", "pcm_s16le", os.path.join(a, "host.wav"))
        return os.path.join(a, "host.wav"), 0.0, 0.0, 0
    with open(os.path.join(a, "en.txt"), "w", encoding="utf-8") as f:
        f.write(known["english"]["text"] + "\n")
    ff("-i", os.path.join(work, known["hebrew"]["file"]), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", os.path.join(a, "he.wav"))
    ff("-f", "lavfi", "-i", f"flite=textfile={a}/en.txt:voice=slt", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", os.path.join(a, "en.wav"))
    for name, secs in (("s10", 1.0), ("s07", 0.7)):
        ff("-f", "lavfi", "-t", str(secs), "-i", "anullsrc=r=48000:cl=mono", "-c:a", "pcm_s16le", os.path.join(a, name + ".wav"))
    with open(os.path.join(a, "one.txt"), "w") as f:
        for name in ("s10", "he", "s07", "en", "s07"):
            f.write(f"file '{a}/{name}.wav'\n")
    ff("-f", "concat", "-safe", "0", "-i", os.path.join(a, "one.txt"), "-c:a", "pcm_s16le", os.path.join(a, "one.wav"))
    one = duration(os.path.join(a, "one.wav"))
    loops = max(1, int(speak // one + (1 if speak % one else 0)))
    ff("-stream_loop", str(loops - 1), "-i", os.path.join(a, "one.wav"), "-t", f"{speak:.2f}", "-c:a", "pcm_s16le", os.path.join(a, "speech.wav"))
    said = duration(os.path.join(a, "speech.wav"))
    # then digital silence for the rest of the call: Chrome plays the file once (measured 2026-10-26), and a file
    # that ends early must not leave the call to whatever Chrome does after its end
    ff("-i", os.path.join(a, "speech.wav"), "-af", f"apad=whole_dur={total:.0f}", "-ac", "1", "-ar", "48000",
       "-c:a", "pcm_s16le", os.path.join(a, "host.wav"))
    return os.path.join(a, "host.wav"), one, said, loops


# ── Chrome ───────────────────────────────────────────────────────────────────────────────────────────────────────
def chrome(name, port, out, wav, size, pos):
    prof = f"/tmp/prof-{name}"
    shutil.rmtree(prof, ignore_errors=True)
    cmd = ["google-chrome", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--disable-sync",
           "--mute-audio", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
           "--autoplay-policy=no-user-gesture-required", f"--window-size={size}", f"--window-position={pos}",
           f"--remote-debugging-port={port}", "--remote-allow-origins=*", f"--user-data-dir={prof}",
           "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]
    if wav:
        cmd.append(f"--use-file-for-fake-audio-capture={wav}")
    cmd.append("about:blank")
    logf = open(os.path.join(out, f"chrome-{name}.log"), "w")
    env = dict(os.environ, DISPLAY=":11")
    return subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)


def leave(page):
    """Leave the meeting the way the hang-up button does, so the room empties at once: a Chrome that is only killed
    stays in the room for prosody's stream-resumption time (60 s, measured on the first run) and the recorder with it."""
    if page:
        try:
            page.eval("(function(){try{APP.conference.hangup(false);return 'left'}catch(e){return String(e)}})()", 10)
        except (TimeoutError, OSError, ValueError):
            pass


def stop(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass


def room_url(meet, room, name, jwt=None, mute_video=True):
    q = ("?jwt=" + jwt) if jwt else ""
    cfg = ["config.prejoinConfig.enabled=false", "userInfo.displayName=" + urllib.parse.quote(json.dumps(name)),
           "config.resolution=180", "config.constraints.video.height.ideal=180", "config.constraints.video.height.max=180",
           "config.disableSimulcast=true", "config.channelLastN=1"]
    if mute_video:
        cfg.append("config.startWithVideoMuted=true")
    return f"{meet}/{urllib.parse.quote(room)}{q}#" + "&".join(cfg)


def open_page(port, url, metrics=None):
    p = Page(port)
    p.call("Page.enable")
    p.call("Network.enable")
    p.call("Page.addScriptToEvaluateOnNewDocument", {"source": HOOK})
    if metrics:
        p.call("Emulation.setDeviceMetricsOverride", metrics)
    p.call("Page.navigate", {"url": url})
    return p


def hosts_of(events, seen):
    for ev in events:
        m, prm = ev.get("method"), ev.get("params") or {}
        url = ""
        if m == "Network.requestWillBeSent":
            url = (prm.get("request") or {}).get("url") or ""
        elif m == "Network.webSocketCreated":
            url = prm.get("url") or ""
        if not url:
            continue
        sp = urllib.parse.urlsplit(url)
        key = f"{sp.scheme}://{sp.hostname or ''}" if sp.scheme in ("http", "https", "ws", "wss") else sp.scheme + ":"
        seen[key] = seen.get(key, 0) + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/w")
    ap.add_argument("--meet", required=True)
    ap.add_argument("--room", required=True)
    ap.add_argument("--seconds", type=float, default=170.0, help="how long the host stays, from its join")
    ap.add_argument("--speak", type=float, default=75.0, help="seconds of known speech, from the unmute")
    ap.add_argument("--guest-after", type=float, default=5.0)
    args = ap.parse_args()
    work, out = args.work, os.path.join(args.work, "out")
    os.makedirs(out, exist_ok=True)
    T = {"started": time.time()}
    result = {"room": args.room, "meet": args.meet, "t": T, "host": {}, "guest": {}, "shots": [], "errors": []}

    def save():
        with open(os.path.join(out, "timeline.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)

    with open(os.path.join(work, "known.json"), encoding="utf-8") as f:
        known = json.load(f)
    with open(os.path.join(work, "host.jwt")) as f:
        jwt = f.read().strip()
    wav, one, said, loops = make_speech(work, known, args.speak, args.seconds + 40)
    result["speech"] = {"rendition_seconds": round(one, 2), "speech_seconds": round(said, 2), "renditions": loops}
    log(f"the known speech: {loops} renditions of {one:.1f} s = {said:.1f} s, then digital silence" if loops else
        "the host's microphone gives digital silence for the whole call (--silent)")

    os.makedirs("/tmp/.X11-unix", exist_ok=True)
    os.chmod("/tmp/.X11-unix", 0o1777)
    xorg = subprocess.Popen(["Xorg", "-noreset", "-nolisten", "tcp", "+extension", "RANDR", "+extension", "RENDER",
                             "-logfile", "/tmp/xorg11.log", "-config", os.path.join(work, "xorg.conf"), ":11"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(3)
    host = guest = None
    hp = gp = None
    net = {"host": {}, "guest": {}}
    try:
        host = chrome("host", HOST_PORT, out, wav, "640,900", "0,0")
        hp = open_page(HOST_PORT, room_url(args.meet, args.room, HOST_NAME, jwt),
                       {"width": 412, "height": 860, "deviceScaleFactor": 1, "mobile": False})
        T["host_opened"] = time.time()
        log("host: the page is opening")
        deadline = time.time() + 120
        st = None
        while time.time() < deadline:
            st = hp.json_eval(STATE) or {}
            if st.get("joined"):
                break
            time.sleep(1)
        hosts_of(hp.drain(), net["host"])
        if not (st or {}).get("joined"):
            result["errors"].append(f"the host never joined in 120 s (last state {st})")
            result["host"]["shot"] = hp.shot(os.path.join(out, "host-not-joined.png"))
            save()
            return 2
        T["host_joined"] = st["now"] / 1000.0
        log(f"host: joined ({st})")
        unmuted = False
        guest_started = False
        shots = {}
        end = T["host_joined"] + args.seconds
        last_collect = last_unmute = 0.0
        while time.time() < end:
            st = hp.json_eval(STATE) or {}
            if st.get("joined") and not unmuted:
                if st.get("track") and not st.get("audioMuted") and not st.get("trackMuted"):
                    unmuted = True
                    T["host_unmuted"] = st["now"] / 1000.0
                    log(f"host: the microphone is on {T['host_unmuted'] - T['host_joined']:.1f} s after the join — the known speech plays from now")
                elif time.time() - last_unmute >= 3:
                    last_unmute = time.time()
                    hp.eval("APP.conference.muteAudio(false), 'unmuting'")
            if not guest_started and time.time() >= T["host_joined"] + args.guest_after and (unmuted or time.time() >= T["host_joined"] + 30):
                guest_started = True
                guest = chrome("guest", GUEST_PORT, out, None, "640,400", "660,0")
                gp = open_page(GUEST_PORT, room_url(args.meet, args.room, GUEST_NAME))
                T["guest_opened"] = time.time()
                log("guest (no microphone): the page is opening")
            if time.time() - last_collect >= 3:
                last_collect = time.time()
                hv = hp.json_eval("JSON.stringify(window.__verify||null)") or {}
                result["host"]["verify"] = hv
                hosts_of(hp.drain(), net["host"])
                if gp:
                    gv = gp.json_eval("JSON.stringify(window.__verify||null)") or {}
                    result["guest"]["verify"] = gv
                    gst = gp.json_eval(STATE) or {}
                    if gst.get("joined") and "guest_joined" not in T:
                        T["guest_joined"] = gst["now"] / 1000.0
                        log(f"guest: joined ({gst})")
                    result["guest"]["state"] = gst
                    hosts_of(gp.drain(), net["guest"])
                    # the guest's page when it is told it has no microphone (the pop-up and the banner)
                    if "guest-nomic" not in shots and any("מיקרופון" in (n.get("text") or "") for n in (gv.get("notes") or {}).values()):
                        shots["guest-nomic"] = gp.shot(os.path.join(out, "guest-no-mic.png"))
                if "host-rec" not in shots and (hv.get("rec") or {}).get("on"):
                    shots["host-rec"] = hp.shot(os.path.join(out, "host-recording.png"))
                caps = list((hv.get("captions") or {}).keys()) + [m.get("text") or "" for m in (hv.get("chat") or {}).values()
                                                                 if m.get("from") == "כתוביות"]
                for text in caps:
                    key = "host-caption-" + ("term" if "DGO" in text else "first")
                    if key not in shots:
                        shots[key] = hp.shot(os.path.join(out, key + ".png"))
                result["host"]["state"] = st
                result["shots"] = sorted(v for v in shots.values() if v)
                save()
            time.sleep(1)
        # the last look, and the pages as they are at the end
        result["host"]["verify"] = hp.json_eval("JSON.stringify(window.__verify||null)") or result["host"].get("verify")
        shots["host-end"] = hp.shot(os.path.join(out, "host-end.png"))
        if gp:
            result["guest"]["verify"] = gp.json_eval("JSON.stringify(window.__verify||null)") or result["guest"].get("verify")
            shots["guest-end"] = gp.shot(os.path.join(out, "guest-end.png"))
        hosts_of(hp.drain(), net["host"])
        if gp:
            hosts_of(gp.drain(), net["guest"])
        result["shots"] = sorted(v for v in shots.values() if v)
    except Exception as e:                                        # noqa: BLE001 — said in the timeline, then cleaned up
        result["errors"].append(f"{type(e).__name__}: {e}")
        log(f"error: {type(e).__name__}: {e}")
    finally:
        result["network"] = net
        T["guest_left"] = time.time()
        leave(gp)
        time.sleep(2)
        T["host_left"] = time.time()
        leave(hp)
        time.sleep(3)
        stop(guest)
        stop(host)
        log("both left: the room is empty, the recording ends")
        stop(xorg)
        save()
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
