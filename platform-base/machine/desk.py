"""desk.py — is somebody sitting at this computer? (DGO-1797, package 1)

The owner, DGO-1797: on the Dell only the office and one browser run, and heavy work (a CI job, the emulator, a
big model) waits while somebody is at the desk unless it is small. This module answers the first half: how long
since the last keyboard, mouse or touch input, as the desktop itself counts it.

Measured 2026-11-10 on the Dell (Ubuntu 26.04, GNOME on Wayland), the signals that do NOT work there:
  * /proc/interrupts — the keyboard is on i8042, but the mouse and the touchscreen share the USB controller with
    the external SSD (+356 interrupts in 10 idle seconds) and the touchpad is on I2C: no counter is «a person»;
  * logind's IdleHint — always «no», because GNOME's idle-delay is 0 (the screen never blanks);
  * /dev/input/event* times — frozen at boot.
The one that does: GNOME's own idle monitor, `org.gnome.Mutter.IdleMonitor.GetIdletime` on the user's session bus
(2221119 ms = 37 min, true at that moment). machine already sees the host's root read-only, so the session bus
socket (/run/user/<uid>/bus) is in reach; the bus accepted this container's EXTERNAL auth.

The call is made here with the standard library only — AUTH EXTERNAL, Hello, one METHOD_CALL, its u64 reply — so
the image gains no dependency. It reads one number and changes nothing. No GNOME, no bus, an error: the reading
is «unknown» (`in_use: null`), which every reader treats as NOT in use, so a broken sampler never holds every job.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

DESK_IDLE_S = int(os.getenv("DESK_IDLE_S", "300"))   # input within this many seconds = somebody is there
CALL_TIMEOUT_S = 2.0
MAX_PART = 64 * 1024                                   # the most a header's fields or a body may claim
_CHILD_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}   # the child gets nothing of machine's own

_MUTTER = ("/org/gnome/Mutter/IdleMonitor/Core", "org.gnome.Mutter.IdleMonitor", "GetIdletime",
           "org.gnome.Mutter.IdleMonitor")
_HELLO = ("/org/freedesktop/DBus", "org.freedesktop.DBus", "Hello", "org.freedesktop.DBus")


def _pad(n: int, align: int) -> int:
    return (-n) % align


def method_call(path: str, interface: str, member: str, destination: str, serial: int) -> bytes:
    """A D-Bus METHOD_CALL with no arguments, little-endian. Header fields start at offset 16 (a multiple of 8), so
    alignment inside the field array is the same as alignment in the message."""
    fields = bytearray()
    for code, sig, value in ((1, "o", path), (2, "s", interface), (3, "s", member), (6, "s", destination)):
        fields += b"\0" * _pad(len(fields), 8)
        raw = value.encode()
        fields += bytes([code, 1]) + sig.encode() + b"\0"
        fields += b"\0" * _pad(len(fields), 4)
        fields += struct.pack("<I", len(raw)) + raw + b"\0"
    head = b"l" + bytes([1, 0, 1]) + struct.pack("<III", 0, serial, len(fields)) + bytes(fields)
    return head + b"\0" * _pad(len(head), 8)


def parse_message(buf: bytes) -> tuple[dict, int] | None:
    """(message, its total length) from the start of `buf`, or None while it is not all there. The message:
    type, serial, reply_serial, error name, signature and body."""
    if len(buf) < 16:
        return None
    e = "<" if buf[0:1] == b"l" else ">"
    mtype = buf[1]
    body_len, serial, fields_len = struct.unpack(e + "III", buf[4:16])
    if fields_len > MAX_PART or body_len > MAX_PART:
        # the answers this reader waits for are a few hundred bytes; a peer claiming more is not a desktop
        raise ValueError(f"a message of {fields_len}+{body_len} bytes: not an answer this reader takes")
    header_end = 16 + fields_len
    body_at = header_end + _pad(header_end, 8)
    total = body_at + body_len
    if len(buf) < total:
        return None
    out: dict = {"type": mtype, "serial": serial, "reply_serial": None, "error": None, "signature": "",
                 "body": bytes(buf[body_at:total])}
    i = 16
    while i < header_end:
        i += _pad(i, 8)
        if i >= header_end:
            break
        code, siglen = buf[i], buf[i + 1]
        sig = buf[i + 2:i + 2 + siglen].decode()
        i += 3 + siglen
        if sig in ("s", "o"):
            i += _pad(i, 4)
            (n,) = struct.unpack(e + "I", buf[i:i + 4])
            value: object = buf[i + 4:i + 4 + n].decode("utf-8", "replace")
            i += 5 + n
        elif sig == "g":
            n = buf[i]
            value = buf[i + 1:i + 1 + n].decode()
            i += 2 + n
        elif sig == "u":
            i += _pad(i, 4)
            (value,) = struct.unpack(e + "I", buf[i:i + 4])
            i += 4
        else:                                           # a field this reader does not need: stop reading fields
            break
        if code == 5:
            out["reply_serial"] = value
        elif code == 4:
            out["error"] = value
        elif code == 8:
            out["signature"] = value
    out["endian"] = e
    return out, total


def _text(msg: dict) -> str:
    """An error's own sentence: its body is one string."""
    body = msg.get("body") or b""
    if msg.get("signature", "").startswith("s") and len(body) >= 4:
        (n,) = struct.unpack(msg["endian"] + "I", body[:4])
        return body[4:4 + n].decode("utf-8", "replace")
    return ""


def idle_ms(bus_path: str, timeout: float | None = None) -> int:
    """GNOME's idle time on one session bus, in ms. Raises OSError / ValueError / TimeoutError on anything else."""
    timeout = CALL_TIMEOUT_S if timeout is None else timeout
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(bus_path)
        s.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        line = b""
        while not line.endswith(b"\r\n"):
            if time.monotonic() >= deadline or len(line) > 1024:   # a peer that drips, or never ends the line
                raise TimeoutError("the bus did not finish auth")
            chunk = s.recv(256)
            if not chunk:
                raise ValueError("the bus closed during auth")
            line += chunk
        if not line.startswith(b"OK "):
            raise ValueError(f"the bus refused auth: {line[:40]!r}")
        s.sendall(b"BEGIN\r\n" + method_call(*_HELLO, serial=1) + method_call(*_MUTTER, serial=2))
        buf = b""
        while time.monotonic() < deadline:
            parsed = parse_message(buf)
            if parsed is None:
                if len(buf) > 2 * MAX_PART + 64:
                    raise ValueError("the bus sent more than an answer")
                chunk = s.recv(4096)
                if not chunk:
                    raise ValueError("the bus closed before answering")
                buf += chunk
                continue
            msg, n = parsed
            buf = buf[n:]
            if msg["reply_serial"] == 1 and msg["type"] == 3:
                # the bus refused Hello itself — on Ubuntu 26.04 a container's AppArmor label may not speak on a
                # session bus at all (measured on the Dell: AccessDenied, «An AppArmor policy prevents …»)
                raise ValueError(f"{msg['error']}: {_text(msg)}"[:200])
            if msg["reply_serial"] != 2:
                continue                                # Hello's answer, NameAcquired: not ours
            if msg["type"] == 3:
                raise ValueError(f"no idle monitor here: {msg['error']}")
            if msg["type"] != 2 or msg["signature"] != "t" or len(msg["body"]) < 8:
                raise ValueError(f"an answer this reader does not know: type {msg['type']} sig {msg['signature']!r}")
            (ms,) = struct.unpack(msg["endian"] + "Q", msg["body"][:8])
            return int(ms)
    raise TimeoutError("the idle monitor did not answer in time")


def idle_ms_as_owner(bus: Path) -> int:
    """idle_ms, asked AS THE BUS'S OWNER: a session bus admits only the uid it belongs to (measured on the Dell:
    root is authenticated and then dropped at BEGIN). Root (machine's container) asks through a short child with
    that uid, no other group and none of machine's environment; any other uid asks only its own bus.
    Only a real socket counts, owned by the uid its directory names, in a directory that uid owns — never followed
    through a link: a host user cannot point root at another socket or another user's bus."""
    st = os.lstat(bus)
    if not stat.S_ISSOCK(st.st_mode):
        raise ValueError(f"{bus.name} under /run/user/{bus.parent.name} is not a socket")
    owner = bus.parent.name
    if not owner.isdigit() or st.st_uid != int(owner) or os.lstat(bus.parent).st_uid != int(owner):
        raise ValueError(f"the bus under /run/user/{owner} is not owned by uid {owner}")
    if st.st_uid == os.getuid():
        return idle_ms(str(bus))
    if os.getuid() != 0:
        raise ValueError(f"the session bus belongs to uid {st.st_uid}, and this process is uid {os.getuid()}")
    p = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "idle-ms", str(bus)],
                       user=st.st_uid, group=st.st_gid, extra_groups=[], env=_CHILD_ENV, capture_output=True,
                       text=True, timeout=CALL_TIMEOUT_S + 3)
    if p.returncode != 0:
        raise ValueError((p.stderr.strip().splitlines() or ["the bus call failed"])[-1][:200])
    return int(p.stdout.strip())


def read_desk(host_root: Path, idle_after_s: int = DESK_IDLE_S, now: float | None = None) -> dict:
    """{"at", "in_use", "idle_s", "how", ["why"]} for this computer. Every session bus under /run/user is asked; the
    least idle one is the desk. `in_use` is None when no desktop answered («unknown» = not in use, for every
    reader)."""
    at = int(now if now is not None else time.time())
    best: int | None = None
    why = "no desktop session bus"
    for bus in sorted((host_root / "run" / "user").glob("*/bus")):
        try:
            ms = idle_ms_as_owner(bus)
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as e:
            why = f"{type(e).__name__}: {e}"[:160]
            continue
        best = ms if best is None else min(best, ms)
    if best is None:
        return {"at": at, "in_use": None, "idle_s": None, "how": "unknown", "why": why}
    idle_s = best // 1000
    return {"at": at, "in_use": idle_s < idle_after_s, "idle_s": idle_s, "how": "gnome"}


def write_desk(power_dir: Path, reading: dict) -> None:
    """data/power/desk.json, atomically: the job door and the screen never read half a file."""
    power_dir.mkdir(parents=True, exist_ok=True)
    tmp = power_dir / ".desk.json.tmp"
    tmp.write_text(json.dumps(reading, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(power_dir / "desk.json")


# ── what the desk tile shows beside it: the CPU's heat and the heavy-work slot (DGO-1797) ──────────────────────

def pkg_temp_c(host_root: Path) -> int | None:
    """The CPU package's temperature, °C, as the readiness rule reads it (x86_pkg_temp); None with no such sensor (a
    VM, a Mac, an ARM board) or a read that fails."""
    for zone in sorted((host_root / "sys" / "class" / "thermal").glob("thermal_zone*")):
        try:
            if (zone / "type").read_text().strip() != "x86_pkg_temp":
                continue
            return int((zone / "temp").read_text().strip()) // 1000
        except (OSError, ValueError):
            continue
    return None


def has_battery(host_root: Path) -> bool | None:
    """Does the machine the office runs on have a battery — a laptop? Read off the host's power supplies (`type` is
    `Battery`). False when they are read and none is one — a server (vps1: the directory is there and empty), and
    also the VM of an engine (the Mac's guest, WSL), whose host's battery it cannot see; None when they cannot be
    read at all. The power card calls an office a server only with no power agent and no host OS besides (DGO-1801)."""
    root = host_root / "sys" / "class" / "power_supply"
    try:
        supplies = sorted(root.iterdir())
    except OSError:
        return None
    unread = False
    for s in supplies:
        try:
            if (s / "type").read_text().strip() == "Battery":
                return True
        except OSError:
            unread = True                  # a supply that could not be read might be the battery: not «no»
    return None if unread else False


def engine_vm(host_root: Path, proc_version: Path = Path("/proc/version")) -> str | None:
    """Which VM of an office's engine the office runs inside, on a person's own computer: "wsl" (the HP, under Windows),
    "engine" (the VM the office's own engine provisions — the MacBook's Lima engine, and the phone's guest, which keeps
    the same step), "" when it runs on the machine itself (a server, the Dell), None when that cannot be read.

    The power card calls an office a server only on "" (DGO-1801): inside such a VM there is no battery to see and, on
    the Mac, no host-side pass — a Mac whose agent never started would otherwise read «a server, nothing to set» and
    lose the card that tells it to start one (the second reader). WSL is named by its kernel (a container shares it:
    its version says Microsoft); the engine's VM by what its provisioning writes into it (packaging/macos/engine.yaml
    and packaging/android/engine/guest.sh: /etc/sysctl.d/90-bbox-memory.conf) or, as a fallback, by Lima's own
    `host.lima.internal` in the VM's /etc/hosts."""
    try:
        if "microsoft" in proc_version.read_text().lower():
            return "wsl"
    except OSError:
        return None
    etc = host_root / "etc"
    if (etc / "sysctl.d" / "90-bbox-memory.conf").exists():
        return "engine"
    try:
        hosts = (etc / "hosts").read_text()
    except OSError:
        return None
    return "engine" if "host.lima.internal" in hosts else ""


def heavy_slot(locks_dir: Path, proc_locks: Path) -> dict:
    """Who holds the office's heavy-work slot (scripts/lib.sh heavy_admit): {"held": bool|None, "holder": str}.
    «Held» is read off the HOST's /proc/locks (a container's own one shows only its own namespace's locks) by the
    slot file's device and inode — no lock is taken, so the reading never makes a job wait. The holder line is the
    last one written; with the slot free it names who held it last."""
    slot, holder_file = locks_dir / "heavy", locks_dir / "heavy.holder"
    try:
        holder = holder_file.read_text(encoding="utf-8", errors="replace").strip()[:300]
    except OSError:
        holder = ""
    try:
        st = os.stat(slot)
    except OSError:
        return {"held": None, "holder": holder, "why": "no heavy-work slot on this office yet"}
    want = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    try:
        lines = proc_locks.read_text().splitlines()
    except OSError:
        return {"held": None, "holder": holder, "why": "the host's lock table is not readable"}
    for line in lines:
        parts = line.split()
        # "1: FLOCK  ADVISORY  WRITE 1234 fd:01:5678 0 EOF" (a waiter's line starts "1: ->" and is one more field). ANY
        # kind counts: on a 9p checkout (WSL's drvfs — the HP) the kernel turns a flock into a POSIX lock, and nothing
        # but heavy_admit locks this one file (the second reader of package 1b)
        if "->" in parts or len(parts) < 6:
            continue
        try:
            major, minor, ino = parts[5].split(":")
            if (int(major, 16), int(minor, 16), int(ino)) == want:
                return {"held": True, "holder": holder}
        except ValueError:
            continue
    return {"held": False, "holder": holder}


if __name__ == "__main__":
    # `python3 desk.py idle-ms <bus>` — the child idle_ms_as_owner starts with the bus owner's uid
    if len(sys.argv) == 3 and sys.argv[1] == "idle-ms":
        try:
            print(idle_ms(sys.argv[2]))
        except (OSError, ValueError, TimeoutError) as e:
            print(str(e) or type(e).__name__, file=sys.stderr)
            sys.exit(1)
    else:
        print(json.dumps(read_desk(Path(os.getenv("HOST_ROOT", "/host/root")))))
