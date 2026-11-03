#!/usr/bin/env python3
"""verify_call.py — `./bbox meet verify --call`: one synthetic meeting on THIS office, checked end to end (FPG-87).

`./bbox meet verify` asks each service whether it answers. This one holds a meeting: a synthetic host joins a new
room with a known recording as its microphone (Hebrew read by people, English by a speech synthesiser), a guest with
no microphone joins beside it, and then every link the office promises is checked against what really happened:

  recording   it started by itself, N seconds after the host joined (FPG-84), lasts > 40 s, its sound is not silent
  transcripts the speech service's two passes (ivrit/he and whisper/auto) hold the known words, and neither translated
  MEET        the recordings' workflow opened the meeting's item in Plane project MEET, with both transcripts and models
  meet-flow   the room was told its meet-flow link; «פגישות» lists the meeting; its page has the first processing
  Drive       «/פגישות/<date> · <room>/» holds the video, the sound, the transcript and the subtitles
  local       no voice left the office: browser captions off in the served config, no SpeechRecognition on any page,
              every page request and ICE server the office's own, no connection from the recorder, meet-start or
              the transcriber to anywhere outside, the captions path internal
  captions    the recorder's live captions came, as server captions (seconds behind, not instant), with the office's
              words spelt its way («DGO fee», FPG-471)
  silent mic  the guest with no microphone is told (a pop-up) and so is the host; the speaking host is never warned;
              when the host's microphone goes silent the notice is quiet and theirs alone

    ./bbox meet verify --call [--room <name>] [--seconds 170] [--speak 75] [--wait 900] [--out <dir>] [--keep]
    ./bbox meet verify --call --silent      the same meeting with an open, silent microphone: «אין דיבור», never-heard

Exit 0 = every check passed, 1 = a check failed (each FAIL line says which and why), 3 = not run (a meeting is on,
the recorder is busy, too little memory). It never runs beside a real meeting: the office has one recorder.

What it leaves behind, on purpose (they ARE the proof, and the next run's comparison): the recording, its MEET item,
its row in «פגישות» and its Drive folder, all named `verify-<date>-<time>`; the report and the pages' screenshots in
--out (default /tmp/meet-<room>/). The synthetic host signs in as `meet-verify` through meet-start's own door
(/r/<room>, entered as the edge would enter it), so the token is minted by the office itself and no secret is read.
Standard library only; runs on the office's host as root (docker, nsenter).
"""
import argparse
import atexit
import ctypes
import datetime
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
# the checkout this office runs from (its .env, its bbox); MEET_VERIFY_REPO when the tool runs from a staging copy
REPO = os.environ.get("MEET_VERIFY_REPO") or os.path.abspath(os.path.join(HERE, "..", "..", ".."))
USER, USER_NAME = "meet-verify", "בדיקת שיחה"
SENDER = "פגישות וידאו"                     # mod_meet_silent_mic's sender
CAPTIONER = "כתוביות"                       # the recorder's captions
GUEST_NAME = "Verify No Mic"


# ── small tools ──────────────────────────────────────────────────────────────────────────────────────────────────
def run(cmd, timeout=60, data=None):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, input=data)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout} s"
    except OSError as e:
        return 127, "", str(e)


def dx(container, *cmd, timeout=60):
    return run(["docker", "exec", container, *cmd], timeout)


def inspect(container):
    rc, out, _ = run(["docker", "inspect", container], 20)
    if rc != 0:
        return None
    try:
        return json.loads(out)[0]
    except (ValueError, IndexError):
        return None


def env_of(info):
    out = {}
    for kv in ((info or {}).get("Config") or {}).get("Env") or []:
        k, _, v = kv.partition("=")
        out[k] = v
    return out


def read_env(key, default=""):
    try:
        with open(os.path.join(REPO, ".env"), encoding="utf-8") as f:
            val = None
            for line in f:
                if line.startswith(key + "="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
            return val if val is not None else default
    except OSError:
        return default


def utc(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%H:%M:%SZ") if t else "—"


def fold(text):
    """Text as the checks read it: no niqqud, no bidi marks, no punctuation, lower case."""
    t = unicodedata.normalize("NFC", text or "")
    t = re.sub("[\u0591-\u05c7\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", t)
    t = re.sub(r"[^\w\s'\u05d0-\u05ea]", " ", t)
    return " ".join(t.lower().split())


def found(words, text):
    t = fold(text)
    return [w for w in words if fold(w) in t]


class Report:
    def __init__(self):
        self.rows, self.facts = [], {}

    def add(self, key, ok, label, detail=""):
        """ok: True (ok), False (FAIL), None (info — said, never fails the run), "warn" (a known open problem)."""
        self.rows.append({"check": key, "ok": ok, "label": label, "detail": detail})
        mark = {True: "ok   ", False: "FAIL ", None: "info ", "warn": "warn "}[ok]
        print(f"  {mark} {label}" + (f"  — {detail}" if detail else ""), flush=True)

    def failed(self):
        return [r for r in self.rows if r["ok"] is False]


# ── the office's own door, entered as the edge enters it ────────────────────────────────────────────────────────
class Door:
    """meet-start believes a signed-in person only from the edge's own address (MEET_TRUSTED_PEERS). The host's
    network namespace is entered (nsenter -n) and meet-start is asked from there, with the headers the edge writes
    after its sign-in — exactly the request the console's tile makes. GET only; nothing is changed by it."""

    def __init__(self, start_info, names):
        self.pid = self.ip = None
        start_env = env_of(start_info)
        start_nets = {k: (v or {}).get("IPAddress") for k, v in ((start_info.get("NetworkSettings") or {}).get("Networks") or {}).items()}
        self.port = int(start_env.get("MEET_START_PORT") or 8080)
        for peer in [p.strip() for p in (start_env.get("MEET_TRUSTED_PEERS") or "").split(",") if p.strip()] or names:
            info = inspect(peer)
            if not info or not (info.get("State") or {}).get("Running"):
                continue
            nets = ((info.get("NetworkSettings") or {}).get("Networks") or {})
            shared = [n for n in nets if n in start_nets and start_nets[n]]
            if shared:
                self.pid, self.ip, self.peer = info["State"]["Pid"], start_nets[shared[0]], peer
                return

    def get(self, path, timeout=40):
        if not self.pid:
            return 0, {}, b""
        cmd = ["nsenter", "-t", str(self.pid), "-n", "curl", "-s", "-S", "-D", "-", "-o", "-", "--max-time", str(timeout),
               "-H", f"X-authentik-username: {USER}", "-H", f"X-authentik-name: {USER_NAME}",
               "-H", "X-authentik-email: ", f"http://{self.ip}:{self.port}{path}"]
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=timeout + 10).stdout
        except (subprocess.TimeoutExpired, OSError):
            return 0, {}, b""
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            code = int(lines[0].split()[1])
        except (IndexError, ValueError):
            return 0, {}, b""
        headers = {}
        for ln in lines[1:]:
            k, _, v = ln.partition(":")
            headers[k.strip().lower()] = v.strip()
        return code, headers, body

    def json(self, path):
        code, _, body = self.get(path)
        if code != 200:
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None


# ── what the office's containers are connected to ───────────────────────────────────────────────────────────────
def own_addresses(hosts):
    own = set()
    rc, out, _ = run(["hostname", "-I"], 10)
    own.update(out.split())
    for h in hosts:
        try:
            own.update(a[4][0] for a in socket.getaddrinfo(h, None))
        except OSError:
            pass
    return own


def _hex_ip(h):
    if len(h) == 8:
        return str(ipaddress.IPv4Address(bytes.fromhex(h)[::-1]))
    b = bytes.fromhex(h)
    words = b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4))
    a = ipaddress.IPv6Address(words)
    return str(a.ipv4_mapped) if a.ipv4_mapped else str(a)


def remote_peers(pid):
    """The remote addresses of a network namespace's connected sockets (TCP established, UDP connected)."""
    out = set()
    for proto in ("tcp", "tcp6", "udp", "udp6"):
        try:
            with open(f"/proc/{pid}/net/{proto}") as f:
                next(f)
                for line in f:
                    parts = line.split()
                    rem, st = parts[2], parts[3]
                    if proto.startswith("tcp") and st != "01":          # ESTABLISHED only
                        continue
                    ip_hex, port_hex = rem.split(":")
                    port = int(port_hex, 16)
                    if port == 0:
                        continue
                    out.add((proto[:3], _hex_ip(ip_hex), port))
        except (OSError, ValueError, StopIteration):
            pass
    return out


def owners(container):
    """socket inode -> the name of the process in that container holding it (read from the host's /proc)."""
    rc, top, _ = run(["docker", "top", container, "-eo", "pid,comm"], 20)
    out = {}
    for line in top.splitlines()[1:]:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid, comm = parts
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    link = os.readlink(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if link.startswith("socket:["):
                    out[link[8:-1]] = comm.strip()
        except OSError:
            pass
    return out


def remote_inodes(pid):
    """(proto, ip, port) -> the socket's inode, for the connected sockets of a network namespace."""
    out = {}
    for proto in ("tcp", "tcp6", "udp", "udp6"):
        try:
            with open(f"/proc/{pid}/net/{proto}") as f:
                next(f)
                for line in f:
                    p = line.split()
                    if proto.startswith("tcp") and p[3] != "01":
                        continue
                    ip_hex, port_hex = p[2].split(":")
                    if int(port_hex, 16):
                        out[(proto[:3], _hex_ip(ip_hex), int(port_hex, 16))] = p[9]
        except (OSError, ValueError, StopIteration, IndexError):
            pass
    return out


# WHAT A RUN LEAVES BEHIND DIES WITH IT (DGO-1231). A run cut short — its ssh session dropped, a `timeout`
# — never reached `docker rm -f` or the tcpdumps' terminate: on FPG's server a box (`sleep infinity`) and
# three tcpdumps from 2026-10-30 were still there 93 hours later. Everything a run starts is listed here
# and removed on any exit, SIGTERM and SIGHUP included; a tcpdump also gets the kernel's parent-death
# signal, for the SIGKILL no handler sees, and the box carries a binaos.max-age autoheal enforces.
_LEFT = {"box": None, "procs": [], "work": None}


def _cleanup():
    for s in (signal.SIGTERM, signal.SIGHUP):                    # a second signal must not cut the cleanup
        signal.signal(s, signal.SIG_IGN)
    if _LEFT["work"]:
        shutil.rmtree(_LEFT["work"], ignore_errors=True)         # it holds the host's meeting token
    for p in _LEFT["procs"]:
        if p and p.poll() is None:
            p.kill()
    if _LEFT["box"]:
        subprocess.run(["docker", "rm", "-f", _LEFT["box"]], capture_output=True, timeout=60)
        _LEFT["box"] = None


def _die_with_parent():
    try:
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)    # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


def dns_watch(pid):
    """tcpdump in a container's network namespace, port 53: every name the container asks for while it runs."""
    try:
        p = subprocess.Popen(["nsenter", "-t", str(pid), "-n", "tcpdump", "-i", "any", "-n", "-l", "-U", "port", "53"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, preexec_fn=_die_with_parent)
    except OSError:
        return None
    _LEFT["procs"].append(p)
    return p


def dns_names(proc):
    if not proc:
        return None
    proc.terminate()
    try:
        text = proc.communicate(timeout=10)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        text = proc.communicate()[0]
    return sorted({m.rstrip(".") for m in re.findall(r"\b(?:A|AAAA)\? (\S+?)\.? \(", text or "")})


def outside(ip, own):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast) and ip not in own


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(prog="bbox meet verify --call", description=__doc__.split("\n\n")[0])
    ap.add_argument("--call", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--room", default="", help="the room (default verify-<yymmdd>-<hhmm>)")
    ap.add_argument("--seconds", type=float, default=170, help="how long the host stays (default 170: the live captions trail ~90 s)")
    ap.add_argument("--speak", type=float, default=75, help="seconds of known speech, then silence (default 75)")
    ap.add_argument("--wait", type=float, default=900, help="seconds to wait for the transcripts, MEET, meet-flow, Drive")
    ap.add_argument("--min-mem", type=int, default=1500, help="MB of MemAvailable needed to start (default 1500)")
    ap.add_argument("--out", default="", help="where the report goes (default /tmp/meet-<room>)")
    ap.add_argument("--keep", action="store_true", help="keep the test container (and its Chrome logs)")
    ap.add_argument("--silent", action="store_true",
                    help="the host's microphone is open and gives digital silence: the recording must be filed «אין דיבור» "
                         "in MEET (FPG-86) and the guard must tell the host it was never heard")
    args = ap.parse_args()

    name = read_env("DEPLOYMENT_NAME", "bina-deployment") or "bina-deployment"
    c = {k: f"{k}-{name}" for k in ("meet", "meet-prosody", "meet-jicofo", "meet-jvb", "meet-jibri", "meet-start", "apitools-asr", "drive")}
    if args.silent:
        args.speak = 0
    room = (args.room or time.strftime("verify-%y%m%d-%H%M" + ("-silent" if args.silent else ""), time.gmtime())).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,62}", room):
        print(f"[meet verify --call] the room name {room!r} is not a plain room name (a-z 0-9 . _ -)")
        return 3
    out = args.out or f"/tmp/meet-{room}"
    os.makedirs(out, exist_ok=True)
    rep = Report()
    print(f"[meet verify --call] office {name}, room {room}; the report goes to {out}", flush=True)

    # ── 0. may it run now? ─────────────────────────────────────────────────────────────────────────────────────
    infos = {k: inspect(v) for k, v in c.items()}
    missing = [c[k] for k, i in infos.items() if not i or not (i.get("State") or {}).get("Running")]
    if missing:
        print(f"  not run: {', '.join(missing)} not running")
        return 3
    start_env, jibri_env, asr_env = env_of(infos["meet-start"]), env_of(infos["meet-jibri"]), env_of(infos["apitools-asr"])
    meet_host = (start_env.get("MEET_HOST") or "").split("://")[-1].strip("/")
    domain = meet_host.split(".", 1)[1] if "." in meet_host else meet_host
    console = (start_env.get("MEET_CONSOLE_URL") or "").rstrip("/")
    quiet = {u.strip() for u in (start_env.get("MEET_QUIET_INITIATORS") or "qa-host").split(",") if u.strip()}
    if USER in quiet:
        print(f"  not run: {USER} is one of MEET_QUIET_INITIATORS — its meeting would never reach the workflow")
        return 3
    rc, stats, _ = dx(c["meet-jvb"], "curl", "-s", "--max-time", "10", "localhost:8080/colibri/stats", timeout=20)
    try:
        conferences = int(json.loads(stats).get("conferences"))
    except (ValueError, TypeError, AttributeError):
        conferences = -1
    if conferences != 0:
        print(f"  not run: the bridge holds {conferences} conference(s) now — the office has one recorder, and a "
              f"meeting's recording is not taken for a test. Run it when no meeting is on.")
        return 3
    rc, busy, _ = dx(c["meet-jibri"], "python3", "-c", "import json,urllib.request;print(json.load(urllib.request.urlopen("
                     "'http://localhost:2222/jibri/api/v1.0/health',timeout=10))['status']['busyStatus'])", timeout=30)
    if busy.strip() != "IDLE":
        print(f"  not run: the recorder is {busy.strip() or 'not answering'}, not IDLE")
        return 3
    with open("/proc/meminfo") as f:
        mem = {ln.split(":")[0]: int(ln.split()[1]) // 1024 for ln in f}
    if mem.get("MemAvailable", 0) < args.min_mem:
        print(f"  not run: {mem.get('MemAvailable')} MB available, {args.min_mem} MB needed (two Chromes and the recorder)")
        return 3
    rc, recs, _ = dx(c["meet-jibri"], "sh", "-c", f"ls -d /storage/recordings/*/{room}_* 2>/dev/null | head -1", timeout=20)
    if recs.strip():
        print(f"  not run: room {room} already has a recording ({recs.strip()}); name another with --room")
        return 3
    door = Door(infos["meet-start"], ["traefik-" + name])
    image = (infos["meet-jibri"].get("Config") or {}).get("Image") or "ghcr.io/jitsi/jibri:stable-11248"
    rec_volume = next((m.get("Name") for m in infos["meet-jibri"].get("Mounts") or [] if m.get("Destination") == "/storage"), None) \
        or next((m.get("Name") for m in infos["meet-start"].get("Mounts") or [] if m.get("Destination") == "/recordings"), None)

    # ── 1. the host's token, from the office's own host door ───────────────────────────────────────────────────
    work = tempfile.mkdtemp(prefix="meet-verify-")
    _LEFT["work"] = work
    os.chmod(work, 0o700)
    code, headers, _ = door.get(f"/r/{urllib.parse.quote(room)}")
    loc = headers.get("location", "")
    jwt = (urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query).get("jwt") or [""])[0]
    if code != 302 or not jwt:
        print(f"  not run: meet-start's host door /r/{room} answered {code} (through {getattr(door, 'peer', 'no trusted peer')})")
        shutil.rmtree(work, ignore_errors=True)
        return 3
    meet_url = loc.split("/" + urllib.parse.quote(room, safe=""), 1)[0]
    with open(os.path.join(work, "host.jwt"), "w") as f:
        os.chmod(f.name, 0o600)
        f.write(jwt)
    rep.facts["door"] = {"peer": door.peer, "answer": code, "meet": meet_url}
    for f in ("call_inside.py",):
        shutil.copy(os.path.join(HERE, f), work)
    for f in ("known.json", "he.ogg"):
        shutil.copy(os.path.join(HERE, "known", f), work)
    with open(os.path.join(HERE, "known", "known.json"), encoding="utf-8") as f:
        known = json.load(f)
    rc, xorg, _ = dx(c["meet-jibri"], "cat", "/run/jibri/config/xorg-video-dummy.conf", timeout=20)
    with open(os.path.join(work, "xorg.conf"), "w") as f:
        f.write(xorg)

    # ── 2. the meeting ──────────────────────────────────────────────────────────────────────────────────────────
    own = own_addresses([meet_host, urllib.parse.urlsplit(console).hostname or ""])
    pids = {k: (infos[k].get("State") or {}).get("Pid") for k in ("meet-start", "meet-jibri", "apitools-asr")}
    seen_peers = {k: set() for k in pids}
    who_out = {k: {} for k in pids}                              # an outside peer -> the process that held it
    busy_seen = {}
    stop = threading.Event()
    dns = {k: dns_watch(pid) for k, pid in pids.items() if pid}

    def sampler():
        while not stop.is_set():
            for k, pid in pids.items():
                if pid:
                    now = remote_inodes(pid)
                    seen_peers[k].update(now)
                    fresh = {peer: ino for peer, ino in now.items() if outside(peer[1], own) and peer not in who_out[k]}
                    if fresh:
                        names = owners(c[k])
                        for peer, ino in fresh.items():
                            who_out[k][peer] = names.get(ino, "?")
            if "busy" not in busy_seen:
                _, b, _ = dx(c["meet-jibri"], "python3", "-c", "import json,urllib.request;print(json.load(urllib.request.urlopen("
                             "'http://localhost:2222/jibri/api/v1.0/health',timeout=5))['status']['busyStatus'])", timeout=15)
                if b.strip() == "BUSY":
                    busy_seen["busy"] = time.time()
            stop.wait(5)

    since = time.time()
    since_iso = datetime.datetime.fromtimestamp(since - 5, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sample = threading.Thread(target=sampler, daemon=True)
    sample.start()
    box = f"meet-verify-{int(since)}"
    if not args.keep:
        _LEFT["box"] = box                                       # before it exists: a timed-out `docker run` may still create it
    rc, _, err = run(["docker", "run", "-d", "--init", "--name", box, "-u", "0", "--entrypoint", "sleep", "--network", "traefik-network",
                      "--label", f"binaos.max-age={int(args.seconds) + 1800}",
                      "--shm-size", "1g", "--memory", "1600m", "--cpus", "1.2", "-v", f"{work}:/w", image, "infinity"], 120)
    if rc != 0:
        stop.set()
        print(f"  not run: the test container did not start: {err.strip()[:300]}")
        shutil.rmtree(work, ignore_errors=True)
        return 3
    print(f"  … a {args.seconds:.0f}-s meeting: the host speaks for {args.speak:.0f} s, a guest with no microphone joins", flush=True)
    rc, said, err = run(["docker", "exec", box, "python3", "/w/call_inside.py", "--work", "/w", "--meet", meet_url,
                         "--room", room, "--seconds", str(args.seconds), "--speak", str(args.speak)], int(args.seconds) + 420)
    with open(os.path.join(out, "call.log"), "w", encoding="utf-8") as f:
        f.write(said + "\n" + err)
    try:
        os.unlink(os.path.join(work, "host.jwt"))
    except OSError:
        pass
    try:
        with open(os.path.join(work, "out", "timeline.json"), encoding="utf-8") as f:
            tl = json.load(f)
    except (OSError, ValueError):
        tl = {"errors": [f"no timeline (call_inside exit {rc}): {err.strip()[-300:]}"], "t": {}, "host": {}, "guest": {}}
    for f in os.listdir(os.path.join(work, "out")) if os.path.isdir(os.path.join(work, "out")) else []:
        if f.endswith((".png", ".json")) or (args.keep and f.endswith(".log")):
            shutil.copy(os.path.join(work, "out", f), out)
    if not args.keep:
        run(["docker", "rm", "-f", box], 60)
        _LEFT["box"] = None
    shutil.rmtree(work, ignore_errors=True)
    T = tl.get("t") or {}
    hv = (tl.get("host") or {}).get("verify") or {}
    gv = (tl.get("guest") or {}).get("verify") or {}
    print(f"  … the host joined {utc(T.get('host_joined'))}, unmuted {utc(T.get('host_unmuted'))}, the guest joined "
          f"{utc(T.get('guest_joined'))}, both left {utc(T.get('host_left'))}", flush=True)
    for e in tl.get("errors") or []:
        rep.add("call", False, "the synthetic meeting ran", e)
    if not T.get("host_joined"):
        stop.set()
        for proc in dns.values():
            dns_names(proc)
        return finish(rep, out, tl, {})

    # ── 3. the recording ────────────────────────────────────────────────────────────────────────────────────────
    rec = {}
    until = time.time() + 360
    while time.time() < until:
        _, ls, _ = dx(c["meet-jibri"], "sh", "-c", f"ls /storage/recordings/*/{room}_* /storage/recordings/*/metadata.json 2>/dev/null | grep -E '/{re.escape(room)}_|metadata' ", timeout=20)
        files = [x for x in ls.split() if f"/{room}_" in x]
        if files:
            sess = files[0].split("/")[3]
            rec = {"session": sess, "files": sorted(os.path.basename(x) for x in files)}
            if any(x.endswith(".ogg") for x in files) and f"/storage/recordings/{sess}/metadata.json" in ls:
                break
        time.sleep(10)
    stop.set()
    names_asked = {k: dns_names(p) for k, p in dns.items()}
    mp4 = next((f for f in rec.get("files", []) if f.endswith(".mp4")), None)
    ogg = next((f for f in rec.get("files", []) if f.endswith(".ogg")), None)
    rep.facts["recording"] = rec
    rec_on = (hv.get("rec") or {}).get("on")
    joined = T.get("host_joined")
    delay = round(rec_on / 1000.0 - joined, 1) if rec_on and joined else None
    if not mp4:
        rep.add("recording.started", False, "the recording started by itself", "no recording of the room in 6 minutes")
    else:
        rep.add("recording.started", True, "the recording started by itself",
                f"session {rec['session']}; the page showed it on {delay} s after the host joined" if delay is not None else f"session {rec['session']}")
        rep.facts["recording_delay_s"] = delay
        if delay is not None:
            rep.add("recording.delay", "warn" if delay > 5 else True, f"the recording began {delay} s after the host joined",
                    "the meeting's first seconds are not in the recording (FPG-84)" if delay > 5 else "")
    media = {}
    if mp4 and rec_volume:
        script = (f"cd /r/recordings/{rec['session']} && ffprobe -v error -show_entries format=duration -of csv=p=0 '{mp4}' && "
                  + (f"ffmpeg -nostdin -hide_banner -i '{ogg}' -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume' && "
                     f"ffmpeg -nostdin -hide_banner -i '{ogg}' -af silencedetect=noise=-40dB:d=0.5 -f null - 2>&1 | grep -oE 'silence_duration: [0-9.]+' | awk '{{s+=$2}} END{{print \"silence\", s+0}}' && "
                     f"ffprobe -v error -show_entries format=duration -of csv=p=0 '{ogg}'" if ogg else "true")
                  + f"; for x in {room}_*.capture.json {room}_*.holes.json; do [ -f \"$x\" ] && echo \"== $x\" && cat \"$x\"; done; echo; "
                  f"[ -f {room}_*.live.txt ] && echo '== live' && cat {room}_*.live.txt")
        _, mo, me = run(["docker", "run", "--rm", "-u", "0", "--entrypoint", "sh", "-v", f"{rec_volume}:/r:ro", image, "-c", script], 180)
        lines = mo.splitlines()
        try:
            media["mp4_seconds"] = float(lines[0])
        except (IndexError, ValueError):
            pass
        m = re.search(r"mean_volume: (-?[\d.]+) dB", mo)
        media["mean_db"] = float(m.group(1)) if m else None
        m = re.search(r"max_volume: (-?[\d.]+) dB", mo)
        media["max_db"] = float(m.group(1)) if m else None
        m = re.search(r"^silence ([\d.]+)$", mo, re.M)
        sil = float(m.group(1)) if m else None
        oggs = [ln for ln in lines if re.fullmatch(r"[\d.]+", ln.strip())]
        media["ogg_seconds"] = float(oggs[1]) if len(oggs) > 1 else None
        media["sound_seconds"] = round(media["ogg_seconds"] - sil, 1) if media.get("ogg_seconds") is not None and sil is not None else None
        live = mo.split("== live", 1)[1].strip() if "== live" in mo else ""
        media["live_txt"] = live
        for part in re.findall(r"== (\S+\.(?:capture|holes)\.json)\n(\{.*?\})\s*(?=\n==|\Z)", mo, re.S):
            try:
                media[part[0].rsplit(".", 2)[-2]] = json.loads(part[1])
            except ValueError:
                pass
        rep.facts["media"] = media
        secs = media.get("mp4_seconds")
        rep.add("recording.length", bool(secs and secs > 40), "the recording is longer than 40 s", f"{secs:.1f} s" if secs else "no length")
        snd = media.get("sound_seconds")
        loud = media.get("max_db") is not None and media["max_db"] > -30 and (snd or 0) >= 10
        if args.silent:
            rep.add("recording.sound", None, "its sound (.ogg), a silent call's",
                    f"max {media.get('max_db')} dB, mean {media.get('mean_db')} dB, {snd} s of sound in {media.get('ogg_seconds')} s")
        else:
          rep.add("recording.sound", loud, "its sound (.ogg) is not silent",
                f"max {media.get('max_db')} dB, mean {media.get('mean_db')} dB, {snd} s of sound in {media.get('ogg_seconds')} s" if ogg else "no .ogg written")
        holes = (media.get("holes") or {}).get("pct")
        if holes is not None:
            rep.add("recording.holes", holes < 1, "the recorder kept pace (no holes in the sound)", f"{holes} % holes")

    # ── 4. no voice left the office ─────────────────────────────────────────────────────────────────────────────
    _, cfg, _ = dx(c["meet"], "curl", "-s", "--max-time", "10", "localhost:8000/config.js", timeout=20)
    m = re.search(r"dgoCaptions\s*=\s*Object\.assign\(\s*\{([^}]*)\}", cfg) or re.search(r"dgoCaptions\s*=\s*\{([^}]*)\}", cfg)
    mode = re.search(r"mode\s*:\s*['\"](\w+)['\"]", m.group(1)).group(1) if m and re.search(r"mode\s*:\s*['\"](\w+)['\"]", m.group(1)) else None
    rep.add("local.config", mode == "off", "browser captions (Web Speech → Google) are off in the config the office serves",
            f"config.dgoCaptions.mode = {mode!r}")
    speech = [(who, (v.get("speech") or {})) for who, v in (("host", hv), ("guest", gv)) if v]
    used = [f"{who}: {s.get('made', 0)} made, {s.get('started', 0)} started" for who, s in speech if s.get("made") or s.get("started")]
    rep.add("local.pages", bool(speech) and not used, "no page made a SpeechRecognition (the browser's own speech service)",
            "; ".join(used) if used else f"{len(speech)} page(s) watched from their first script")
    net = tl.get("network") or {}
    hosts = sorted({h for side in net.values() for h in side})
    foreign = [h for h in hosts if h.split("://")[-1] and not re.match(r"^(data|blob|about|chrome|devtools|chrome-extension):$", h)
               and not (urllib.parse.urlsplit(h if "://" in h else "x://" + h).hostname or "").endswith(domain)]
    rep.add("local.requests", not foreign, f"every request of both pages went to the office ({domain})",
            ("outside: " + ", ".join(foreign)) if foreign else f"{len(hosts)} origin(s): " + ", ".join(hosts)[:300])
    ice = sorted(set((hv.get("ice") or []) + (gv.get("ice") or [])))
    bad_ice = [u for u in ice if not re.sub(r"^\w+:", "", u).split(":")[0].split("?")[0].endswith(domain)]
    rep.add("local.ice", not bad_ice, "the media's STUN/TURN servers are the office's own",
            ("outside: " + ", ".join(bad_ice)) if bad_ice else (", ".join(ice) if ice else "none listed (media straight to the bridge)"))
    leaks = {k: sorted(f"{p}/{ip}:{port} ({who_out[k].get((p, ip, port), '?')})" for p, ip, port in v if outside(ip, own))
             for k, v in seen_peers.items()}
    asked_out = {k: [n for n in (v or []) if "." in n and not n.endswith(domain)] for k, v in names_asked.items()}
    rep.add("local.sockets", not any(leaks.values()), "the recorder, meet-start and the transcriber reached nothing outside the office",
            "; ".join(f"{c[k]}: {', '.join(v[:6])}" for k, v in leaks.items() if v) or
            f"sampled every 5 s during the call: {sum(len(v) for v in seen_peers.values())} connection(s), all inside")
    rep.add("local.dns", None if not any(asked_out.values()) else "warn", "the names each container asked for during the call",
            "; ".join(f"{c[k]}: {', '.join(v[:8]) or '-'}" for k, v in asked_out.items()) if any(asked_out.values()) else "only the office's own")
    paths = {"meet-jibri MEET_START_MACHINES": jibri_env.get("MEET_START_MACHINES", ""), "meet-start MEET_SPEECH_URL": start_env.get("MEET_SPEECH_URL", "")}
    ext = {k: v for k, v in paths.items() if "." in (urllib.parse.urlsplit(v).hostname or "") or not v}
    rep.add("local.captions-path", not ext, "the live captions go recorder → meet-start → the office's transcriber",
            "; ".join(f"{k}={v}" for k, v in paths.items()))
    rep.facts["local"] = {"hosts": hosts, "ice": ice, "dns": names_asked,
                          "peers": {k: sorted(f"{p}/{ip}:{port}" for p, ip, port in v) for k, v in seen_peers.items()},
                          "outside_by_process": {k: {f"{p}/{ip}:{port}": n for (p, ip, port), n in v.items()} for k, v in who_out.items()}}

    # ── 5. the silent-mic guard ─────────────────────────────────────────────────────────────────────────────────
    def lines_of(v, sender):
        return sorted(((x.get("t") or 0) / 1000.0, x.get("text") or "") for x in (v.get("chat") or {}).values() if x.get("from") == sender)

    def popped(v, needle):
        return [n for n in (v.get("notes") or {}).values() if needle in (n.get("text") or "")]

    host_guard, guest_guard = lines_of(hv, SENDER), lines_of(gv, SENDER)
    rep.facts["guard"] = {"host": host_guard, "guest": guest_guard}
    g_join = T.get("guest_joined")
    nomic = [(t, x) for t, x in guest_guard if "אין לך מיקרופון פעיל" in x]
    if not g_join:
        rep.add("mic.guest", False, "the guest with no microphone is told", "the guest never joined")
    else:
        took = round(nomic[0][0] - g_join, 1) if nomic else None
        pop = bool(popped(gv, "אין לך מיקרופון פעיל"))
        rep.add("mic.guest", bool(nomic) and took is not None and took <= 30 and pop,
                "the guest with no microphone is told, as a pop-up, within 30 s",
                f"{took} s after joining; pop-up {'yes' if pop else 'NO'}" if nomic else "never told")
        about = [(t, x) for t, x in host_guard if "אין מיקרופון פעיל" in x and GUEST_NAME in x]
        rep.add("mic.room", bool(about), "the host is told the guest has no microphone",
                f"{round(about[0][0] - g_join, 1)} s after the guest joined" if about else "never told")
    unm = T.get("host_unmuted") or next((t for t, x in host_guard if "✅ הקול שלך מגיע לפגישה" in x), None)
    if args.silent:
        never = [(t, x) for t, x in host_guard if "מאז ההצטרפות" in x and "הקול שלך" in x]
        pop = [n for n in (hv.get("notes") or {}).values() if "מאז ההצטרפות" in (n.get("text") or "")]
        rep.add("mic.never-heard", bool(never) and bool(pop), "the host whose open microphone gives nothing is told, as a pop-up",
                f"{round(never[0][0] - T['host_joined'], 1)} s after joining; pop-up {'yes' if pop else 'NO'}" if never else "never told")
        unm = None                                                # no speech: the speaking checks below do not apply
    said = ((tl.get("speech") or {}).get("speech_seconds") or args.speak)
    speech_end = unm + said if unm else None
    if unm:
        false_alarm = [x for t, x in host_guard if unm + 12 <= t <= speech_end and "הקול שלך" in x and "⚠" in x]
        nomic_host = [x for t, x in host_guard if t >= unm + 12 and "אין לך מיקרופון פעיל" in x]
        rep.add("mic.no-false-alarm", not (false_alarm or nomic_host), "the speaking host is never warned",
                (false_alarm + nomic_host)[0][:120] if (false_alarm or nomic_host) else f"{said:.0f} s of speech, no warning")
        gone = [(t, x) for t, x in host_guard if t > speech_end and "לא מגיע לפגישה" in x and "שניות" in x and "הקול שלך" in x]
        gone_pop = popped(hv, "לא מגיע לפגישה")
        gone_pop = [n for n in gone_pop if "הקול שלך" in (n.get("text") or "") and (n.get("t") or 0) / 1000.0 > speech_end]
        others = [x for t, x in guest_guard if t > speech_end and USER_NAME in x and "לא מגיע" in x]
        if T.get("host_left") and T["host_left"] - speech_end < 40:
            rep.add("mic.silent-quiet", None, "the host's microphone went silent: told quietly, to the host only",
                    f"not judged: only {T['host_left'] - speech_end:.0f} s of silence before the end (20 s + a 5-s tick needed)")
        else:
            rep.add("mic.silent-quiet", bool(gone) and not gone_pop and not others,
                    "the host's microphone went silent: told quietly, to the host only",
                    (f"{round(gone[0][0] - speech_end, 1)} s after the speech ended; pop-up {'YES' if gone_pop else 'no'}; "
                     f"the guest told {'YES' if others else 'nothing'}") if gone else "the host was never told")

    # ── 6. the live captions (the recorder's, as the room saw them) ───────────────────────────────────────────
    cap_lines = lines_of(hv, CAPTIONER)
    live = media.get("live_txt") or ""
    caps_text = " ".join(x for _, x in cap_lines) + " " + " ".join((hv.get("captions") or {}).keys()) + " " + live
    rep.facts["captions"] = {"chat": cap_lines, "overlay": hv.get("captions"), "live_txt": live}
    _, wl, _ = run(["docker", "logs", "--since", since_iso, c["meet-jibri"]], 60)
    lags = [float(x) for x in re.findall(r"caption \d+: \d+ s, transcribed in \d+ s, (\d+) s behind", wl)]
    rep.facts["captions"]["lag_s"] = lags
    he_live = found(known["hebrew"]["words"], caps_text)
    if not cap_lines and not live:
        rep.add("captions.came", None, "the recorder's live captions came", "none in this call (MEET_LIVE_CAPTIONS off, or none finished before the end)")
    else:
        rep.add("captions.came", True, "the recorder's live captions came, as server captions (not instant)",
                f"{len(cap_lines)} line(s) in the room, lag {statistics.median(lags):.0f} s (median of {len(lags)})" if lags else f"{len(cap_lines)} line(s) in the room")
        rep.add("captions.words", None, "the live captions' Hebrew words", f"{len(he_live)}/{len(known['hebrew']['words'])}: {', '.join(he_live)}")
        for term, spec in (known.get("terms") or {}).items():
            if not isinstance(spec, dict):
                continue
            wrong = [w for w in spec.get("wrong") or [] if re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", caps_text)]
            right = term in caps_text
            rep.add("captions.term", right and not wrong, f"the live captions write «{term}» the office's way (FPG-471)",
                    ("wrong: " + ", ".join(wrong)) if wrong else ("found" if right else "the term was not heard in the captions"))

    # ── 7. the transcripts, the MEET item, meet-flow, Drive — they take minutes ───────────────────────────────
    deadline = time.time() + args.wait
    jobs, item, body, flow_row, flow_doc, drive_names, flow_txt, drive_folder = {}, None, "", None, None, [], "", None
    flow_link = [x for _, x in lines_of(hv, "הקלטה") + lines_of(hv, "פגישות") if "meet-flow" in x] + \
                [x.get("text") for x in (hv.get("chat") or {}).values() if "meet-flow" in (x.get("text") or "")]
    rep.add("flow.link", bool(flow_link), "the room was told where its meet-flow is", (flow_link[0] or "")[:140] if flow_link else "no link line in the room's chat")
    last_item_look = 0.0
    print(f"  … waiting (at most {args.wait / 60:.0f} min) for the transcripts, the MEET item, «פגישות» and Drive", flush=True)
    while time.time() < deadline:
        if ogg and len([j for j in jobs.values() if j.get("status") == "completed"]) < 2:
            _, js, _ = dx(c["apitools-asr"], "python3", "-c", (
                "import json,sys,urllib.request\n"
                "u='http://localhost:8987'\n"
                "d=json.load(urllib.request.urlopen(u+'/speechJobs?limit=100',timeout=15))\n"
                "out={}\n"
                "for j in d.get('jobs') or []:\n"
                "  if (j.get('source') or {}).get('name')!=sys.argv[1]: continue\n"
                "  m=(j.get('options') or {}).get('model') or ''\n"
                "  if m in out and out[m].get('status')=='completed': continue\n"
                "  r={'id':j.get('id'),'status':j.get('status'),'model':m,'language':(j.get('options') or {}).get('language')}\n"
                "  if j.get('status')=='completed':\n"
                "    x=json.load(urllib.request.urlopen(u+'/v1/audio/transcriptions/'+j['id']+'/verbose_json',timeout=30))\n"
                "    r.update(text=x.get('text') or '',repo=(x.get('model') or {}).get('name'),usage=x.get('usage'))\n"
                "  out[m]=r\n"
                "print(json.dumps(out,ensure_ascii=False))\n"), ogg, timeout=60)
            try:
                jobs = json.loads(js) or jobs
            except ValueError:
                pass
        ivrit_done = (jobs.get("ivrit") or {}).get("status") == "completed"
        whisper_done = (jobs.get("whisper") or {}).get("status") == "completed"
        whole = bool(body) and ("faster-whisper" in body or args.silent)
        if ivrit_done and (not body or (whisper_done and not whole)) and time.time() - last_item_look > 75:
            last_item_look = time.time()
            rc, lj, _ = run([os.path.join(REPO, "bbox"), "project-pln", "tasks", "list", "--project", "MEET", "--json"], 240)
            try:
                hits = [t for t in json.loads(lj[lj.index("{"):]).get("tasks") or [] if f"· {room} ·" in (t.get("name") or "")]
            except ValueError:
                hits = []
            if hits:
                item = hits[0]
                print(f"  … {item['ref']} is there; reading it", flush=True)
                rc, sh, _ = run([os.path.join(REPO, "bbox"), "project-pln", "tasks", "show", item["ref"], "--body"], 240)
                body = sh if rc == 0 else ""
        if ivrit_done and flow_row is None:
            listing = door.json("/flow/api/meetings")
            rows = (listing or {}).get("meetings") if isinstance(listing, dict) else listing
            flow_row = next((r for r in rows or [] if str(r.get("room") or "").lower() == room), None)
        if ivrit_done and flow_row is not None and not (flow_doc or {}).get("data"):
            flow_doc = door.json(f"/flow/{urllib.parse.quote(room)}/meeting.json")
            if (flow_doc or {}).get("data"):
                code, _, txt = door.get(f"/flow/{urllib.parse.quote(room)}/transcript.txt")
                flow_txt = txt.decode("utf-8", "replace") if code == 200 else ""
        if mp4 and len(drive_names) < 4:
            _, dl, _ = dx(c["drive"], "python3", "-c", (
                "import json,sys,urllib.parse,urllib.request\n"
                "def ls(p):\n"
                "  q=urllib.parse.urlencode({'path':p,'profile_id':'admin'})\n"
                "  try:\n"
                "    d=json.load(urllib.request.urlopen('http://localhost:8975/api/fs?'+q,timeout=20))\n"
                "  except Exception:\n"
                "    return []\n"
                "  rows=(d.get('folders') or [])+(d.get('files') or [])\n"
                "  return [r.get('name') for r in rows if isinstance(r,dict)]\n"
                "top=[n for n in ls('/פגישות') if n and n.endswith(' · '+sys.argv[1])]\n"
                "print(json.dumps({'folder':top[0] if top else None,'names':ls('/פגישות/'+top[0]) if top else []},ensure_ascii=False))\n"), room, timeout=60)
            try:
                d = json.loads(dl)
                drive_names, drive_folder = d.get("names") or [], d.get("folder")
            except ValueError:
                drive_folder = None
        want_drive = [n for n in drive_names if n.endswith((".mp4", ".ogg")) or n.startswith(("תמלול", "כתוביות"))]
        done = (len([j for j in jobs.values() if j.get("status") == "completed"]) >= 2 and body and "faster-whisper" in body
                and flow_txt and len(want_drive) >= 4) or (args.silent and item is not None and len(want_drive) >= 2)
        if done:
            break
        time.sleep(30)
    rep.facts.update(jobs=jobs, item=item, flow_row=flow_row, drive=drive_names)

    he_words, en_words = known["hebrew"]["words"], known["english"]["words"]
    ivr, wsp = jobs.get("ivrit") or {}, jobs.get("whisper") or {}
    if args.silent:
        labels = (item or {}).get("labels") or []
        rep.add("meet.item", bool(item), "the workflow opened the meeting's item in Plane project MEET",
                f"{item['ref']}: {item.get('name', '')}" if item else f"none named «· {room} ·» in {args.wait / 60:.0f} min")
        rep.add("meet.silent", bool(item) and "אין דיבור" in labels and "תומלל" not in labels,
                "a silent recording is filed «אין דיבור», not «תומלל» (FPG-86)", "labels: " + (", ".join(labels) or "none"))
        said_ = " ".join(x for x in (ivr.get("text"), wsp.get("text")) if x)
        rep.add("transcript.silent", None, "what the two passes wrote for the silence", said_[:200] or "nothing")
        rep.facts.update(jobs=jobs, item=item, flow_row=flow_row, drive=drive_names)
        rep.add("drive.folder", None, "Drive «פגישות»", ", ".join(drive_names) or "no folder")
        return finish(rep, out, tl, {"room": room, "since": since, "facts": rep.facts})
    he_i, he_w = found(he_words, ivr.get("text")), found(he_words, wsp.get("text"))
    en_i, en_w = found(en_words, ivr.get("text")), found(en_words, wsp.get("text"))
    rep.add("transcript.hebrew", len(he_i) >= known["hebrew"]["need"], "the Hebrew pass (ivrit, he) wrote the known Hebrew words",
            f"{len(he_i)}/{len(he_words)}: {', '.join(he_i)}" if ivr.get("status") == "completed" else f"the pass is {ivr.get('status') or 'missing'}")
    rep.add("transcript.auto", wsp.get("status") == "completed", "the as-spoken pass (whisper, auto) is there",
            f"Hebrew {len(he_w)}/{len(he_words)}, English {len(en_w)}/{len(en_words)}" if wsp.get("status") == "completed" else f"the pass is {wsp.get('status') or 'missing'}")
    rep.add("transcript.english", len(set(en_i) | set(en_w)) >= known["english"]["need"], "the English was written as English",
            f"whisper {len(en_w)}/{len(en_words)} ({', '.join(en_w)}), ivrit {len(en_i)}/{len(en_words)}")
    tr = [w for w in known["hebrew"].get("translations") or [] if re.search(r"\b" + re.escape(w), fold(wsp.get("text") or ""))]
    rep.add("transcript.no-translation", wsp.get("status") == "completed" and not tr, "nothing was translated (no English for the Hebrew sentences)",
            ("found: " + ", ".join(tr)) if tr else "")
    stock = {"ivrit": len(re.findall(r"תודה רבה", ivr.get("text") or "")), "whisper": len(re.findall(r"(?i)thank you", wsp.get("text") or "")),
             "meet-flow": len(re.findall(r"תודה רבה", flow_txt or "")), "MEET item": len(re.findall(r"(?i)תודה רבה|thank you", body or ""))}
    if any(stock.values()):
        rep.add("transcript.stock", None, "stock lines on silence («תודה רבה» / «Thank you», never said in this call)",
                ", ".join(f"{k} {v}" for k, v in stock.items()))
    if wsp.get("status") == "completed" and not he_w:
        rep.add("transcript.whisper-hebrew", "warn", "whisper (auto) wrote none of the Hebrew",
                "it heard the call as English and left the Hebrew out — ivrit's pass is the Hebrew record")
    if wsp.get("status") == "completed" and re.search("[\u0600-\u06ff]", wsp.get("text") or ""):
        rep.add("transcript.script", "warn", "whisper wrote some Hebrew speech in Arabic letters", "a language guess on a mixed 30-s window (measured on the known clip too)")
    if item and body:
        models = [m for m in ("ivrit-ai/whisper-large-v3-turbo-ct2", "faster-whisper-large-v3-turbo") if m in body]
        he_item = found(he_words, body)
        rep.add("meet.item", True, f"the workflow opened {item['ref']} in Plane project MEET", item.get("name", ""))
        rep.add("meet.content", len(he_item) >= known["hebrew"]["need"] and len(models) == 2,
                f"{item['ref']} holds the Hebrew transcript and names both models",
                f"Hebrew words {len(he_item)}/{len(he_words)}; models: {', '.join(models) or 'none named'}")
    else:
        rep.add("meet.item", False, "the workflow opened the meeting's item in Plane project MEET",
                f"none named «· {room} ·» in {args.wait / 60:.0f} min" + ("" if ivrit_done else " (the Hebrew pass never finished)"))
    rep.facts["flow"] = {"meeting": flow_doc, "transcript_txt": flow_txt[:4000]}
    if flow_row is not None:
        rep.add("flow.list", True, "«פגישות» lists the meeting", f"state {flow_row.get('state')!r}, {flow_row.get('title') or room}")
        he_flow = found(he_words, flow_txt)
        rep.add("flow.page", bool((flow_doc or {}).get("data")) and len(he_flow) >= known["hebrew"]["need"],
                "its meet-flow page has the first processing, with the known words",
                f"state {(flow_doc or {}).get('state')!r}, transcript.txt {len(flow_txt.splitlines())} line(s), Hebrew words "
                f"{len(he_flow)}/{len(he_words)}" if flow_doc else "meeting.json did not answer")
        for term, spec in (known.get("terms") or {}).items():
            if isinstance(spec, dict) and flow_txt:
                wrong = [w for w in spec.get("wrong") or [] if re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", flow_txt)]
                rep.add("flow.term", None if (term not in flow_txt and not wrong) else not wrong,
                        f"meet-flow's transcript writes «{term}» the office's way", ("wrong: " + ", ".join(wrong)) if wrong else
                        ("found" if term in flow_txt else "the term is not in the first processing"))
    else:
        rep.add("flow.list", False, "«פגישות» lists the meeting", "not in /flow/api/meetings" + ("" if door.pid else " (no trusted peer to ask through)"))
    need = {"the video": any(n.endswith(".mp4") for n in drive_names), "the sound": any(n.endswith(".ogg") for n in drive_names),
            "the transcript": any(n.startswith("תמלול") for n in drive_names), "the subtitles": any(n.startswith("כתוביות") for n in drive_names)}
    rep.add("drive.folder", all(need.values()), "Drive «פגישות» holds the meeting's folder",
            ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in need.items()))
    return finish(rep, out, tl, {"room": room, "since": since, "facts": rep.facts})


def finish(rep, out, tl, extra):
    bad = rep.failed()
    doc = {"result": "FAIL" if bad else "PASS", "checks": rep.rows, "timeline": tl, **extra}
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=str)
    print(f"[meet verify --call] {'FAIL — ' + ', '.join(r['check'] for r in bad) if bad else 'PASS'} "
          f"({len(rep.rows)} checks; report {os.path.join(out, 'report.json')})", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    atexit.register(_cleanup)
    for _sig in (signal.SIGTERM, signal.SIGHUP):
        if signal.getsignal(_sig) is not signal.SIG_IGN:         # a `nohup` run keeps ignoring the hang-up
            signal.signal(_sig, lambda n, _f: sys.exit(128 + n))
    sys.exit(main())
