#!/usr/bin/env python3
"""test_desk.py — desk.py reads the desktop's idle time from a session bus, and says «unknown» for anything else.

A fake session bus on a unix socket speaks the little D-Bus it needs, encoded HERE (not with desk.py's own
builder): AUTH, then a NameAcquired-like signal before any answer, Hello's answer, and GetIdletime's — a u64, or
an error when there is no idle monitor (a desktop that is not GNOME). desk.read_desk is pointed at a fake host
root with that socket at run/user/1000/bus.

    python3 platform-base/machine/test_desk.py      (stdlib only; no stack)
The proof against a real desk is a reading on the Dell, written on DGO-1797.
"""
from __future__ import annotations

import os
import socket
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def _align(b: bytearray, n: int) -> None:
    b += b"\0" * ((-len(b)) % n)


def reply(mtype: int, serial: int, reply_serial: int | None, sig: str = "", body: bytes = b"",
          error: str = "") -> bytes:
    """A message as a bus would send it: fields REPLY_SERIAL (5,u), ERROR_NAME (4,s), SIGNATURE (8,g)."""
    f = bytearray()
    if reply_serial is not None:
        _align(f, 8); f += bytes([5, 1]) + b"u\0"; _align(f, 4); f += struct.pack("<I", reply_serial)
    if error:
        _align(f, 8); f += bytes([4, 1]) + b"s\0"; _align(f, 4); f += struct.pack("<I", len(error)) + error.encode() + b"\0"
    if sig:
        _align(f, 8); f += bytes([8, 1]) + b"g\0" + bytes([len(sig)]) + sig.encode() + b"\0"
    head = bytearray(b"l" + bytes([mtype, 0, 1]) + struct.pack("<III", len(body), serial, len(f)) + bytes(f))
    _align(head, 8)
    return bytes(head) + body


def serve(path: str, mode: str, seen: dict) -> threading.Thread:
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        with conn:
            data = b""
            while b"\r\n" not in data:
                data += conn.recv(256)
            seen["auth"] = data
            if mode == "refuse":
                conn.sendall(b"REJECTED EXTERNAL\r\n")
                return
            if mode == "drip":                           # a peer that answers auth one byte at a time, forever
                for _ in range(40):
                    try:
                        conn.sendall(b"O")
                    except OSError:
                        return
                    time.sleep(0.2)
                return
            if mode == "endless":                        # a peer whose auth line never ends
                try:
                    conn.sendall(b"X" * 8000)
                    conn.recv(1)
                except OSError:
                    pass
                return
            conn.sendall(b"OK 0123456789abcdef0123456789abcdef\r\n")
            while b"BEGIN\r\n" not in data:
                data += conn.recv(4096)
            rest = data.split(b"BEGIN\r\n", 1)[1]
            msgs = []
            while len(msgs) < 2:                     # Hello and the call, as desk.method_call wrote them
                while len(rest) < 16:
                    rest += conn.recv(4096)
                body_len, serial, flen = struct.unpack("<III", rest[4:16])
                total = 16 + flen + ((-(16 + flen)) % 8) + body_len
                while len(rest) < total:
                    rest += conn.recv(4096)
                msgs.append((serial, rest[:total]))
                rest = rest[total:]
            seen["calls"] = msgs
            if mode == "silent":
                conn.recv(1)                             # never answers; the client times out
                return
            if mode == "huge":                           # a header that claims a 4 GB body, then a flood
                try:
                    conn.sendall(b"l" + bytes([2, 0, 1]) + struct.pack("<III", 0xFFFFFFF0, 3, 8) + b"\0" * 8)
                    conn.sendall(b"\0" * 200000)
                except OSError:
                    pass
                return
            if mode == "apparmor":                       # as the Dell's bus answered machine's container, 2026-11-10
                why = b"An AppArmor policy prevents this sender from sending this message to this recipient"
                conn.sendall(reply(3, 1, 1, "s", struct.pack("<I", len(why)) + why + b"\0",
                                   error="org.freedesktop.DBus.Error.AccessDenied"))
                conn.recv(1)                             # …and the call is never answered
                return
            out = reply(4, 1, None, "s", struct.pack("<I", 5) + b":1.42\0")        # a signal first: not ours
            out += reply(2, 2, 1, "s", struct.pack("<I", 5) + b":1.42\0")          # Hello's answer
            if mode == "gnome":
                out += reply(2, 3, 2, "t", struct.pack("<Q", 2221119))
            else:
                out += reply(3, 3, 2, error="org.freedesktop.DBus.Error.ServiceUnknown")
            conn.sendall(out)
        srv.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def host_with_bus(mode: str, seen: dict) -> Path:
    """A host root whose /run/user/<this uid>/bus is the fake bus — owned, as a real one is, by the uid its directory
    names (this test's own uid, so the reader asks in-process, as it does on its own bus)."""
    root = Path(tempfile.mkdtemp(prefix="desk-", dir="/tmp"))
    me = root / "run" / "user" / str(os.getuid())
    me.mkdir(parents=True)
    serve(str(me / "bus"), mode, seen)
    return root


def main() -> int:
    seen: dict = {}
    r = desk.read_desk(host_with_bus("gnome", seen), idle_after_s=300, now=1000)
    check(r == {"at": 1000, "in_use": False, "idle_s": 2221, "how": "gnome"}, f"GNOME's idle time read: {r}")
    check(seen["auth"].startswith(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode()),
          "AUTH EXTERNAL with this process's own uid")
    calls = b"".join(m for _, m in seen.get("calls", []))
    check([s for s, _ in seen.get("calls", [])] == [1, 2], "Hello first, then the one call")
    check(all(w in calls for w in (b"Hello", b"/org/gnome/Mutter/IdleMonitor/Core", b"GetIdletime",
                                   b"org.gnome.Mutter.IdleMonitor")), "the call names Mutter's idle monitor")

    r = desk.read_desk(host_with_bus("gnome", {}), idle_after_s=3000, now=1000)
    check(r["in_use"] is True, "idle under DESK_IDLE_S = somebody is there")

    r = desk.read_desk(host_with_bus("other", {}), now=1000)
    check(r["in_use"] is None and r["how"] == "unknown" and "ServiceUnknown" in r["why"],
          f"a desktop that is not GNOME: unknown, with the bus's own words: {r}")
    r = desk.read_desk(host_with_bus("apparmor", {}), now=1000)
    check(r["in_use"] is None and "AccessDenied" in r["why"] and "AppArmor" in r["why"],
          f"a bus that refuses this container (AppArmor, the Dell): unknown, saying why at once: {r}")
    r = desk.read_desk(host_with_bus("refuse", {}), now=1000)
    check(r["in_use"] is None and "refused" in r["why"], f"auth refused: unknown: {r}")
    old = desk.CALL_TIMEOUT_S
    desk.CALL_TIMEOUT_S = 0.5
    try:
        r = desk.read_desk(host_with_bus("silent", {}), now=1000)
        check(r["in_use"] is None and r["how"] == "unknown", f"a bus that never answers: unknown, in bounded time: {r}")
        # what a host user could serve at their own /run/user/<uid>/bus (the second reader of package 1)
        t = time.monotonic()
        r = desk.read_desk(host_with_bus("drip", {}), now=1000)
        took = time.monotonic() - t
        check(r["in_use"] is None and took < 1.5, f"an auth answered a byte at a time: unknown in {took:.1f} s, not held: {r}")
        r = desk.read_desk(host_with_bus("endless", {}), now=1000)
        check(r["in_use"] is None and "auth" in r["why"], f"an auth line that never ends: refused, not read on: {r}")
        r = desk.read_desk(host_with_bus("huge", {}), now=1000)
        check(r["in_use"] is None and "not an answer" in r["why"], f"a 4 GB length: refused before reading it: {r}")
    finally:
        desk.CALL_TIMEOUT_S = old

    # only a real socket, owned by the uid its directory names, and never through a link
    root = Path(tempfile.mkdtemp(prefix="desk-ln-", dir="/tmp"))
    me = root / "run" / "user" / str(os.getuid())
    me.mkdir(parents=True)
    real = host_with_bus("gnome", {})
    (me / "bus").symlink_to(real / "run" / "user" / str(os.getuid()) / "bus")
    r = desk.read_desk(root, now=1000)
    check(r["in_use"] is None and "not a socket" in r["why"], f"a bus that is a link elsewhere: not followed: {r}")
    root = Path(tempfile.mkdtemp(prefix="desk-uid-", dir="/tmp"))
    other = root / "run" / "user" / str(os.getuid() + 4242)
    other.mkdir(parents=True)
    serve(str(other / "bus"), "gnome", {})
    r = desk.read_desk(root, now=1000)
    check(r["in_use"] is None and "not owned" in r["why"], f"a bus under another uid's name: refused: {r}")
    r = desk.read_desk(Path(tempfile.mkdtemp(prefix="desk-none-", dir="/tmp")), now=1000)
    check(r == {"at": 1000, "in_use": None, "idle_s": None, "how": "unknown", "why": "no desktop session bus"},
          f"no session bus at all (a server, WSL, a VM): {r}")

    pd = Path(tempfile.mkdtemp(prefix="desk-power-", dir="/tmp"))
    desk.write_desk(pd, {"at": 1, "in_use": False})
    check((pd / "desk.json").read_text().strip() == '{"at": 1, "in_use": false}' and not (pd / ".desk.json.tmp").exists(),
          "desk.json written whole, no temp left")

    # the heat beside the desk: the CPU package's zone, never another; no sensor or a failing read = None
    hr = Path(tempfile.mkdtemp(prefix="desk-sys-", dir="/tmp"))
    for i, (kind, temp) in enumerate((("acpitz", "99000"), ("x86_pkg_temp", "66000"), ("iwlwifi", "45000"))):
        z = hr / "sys" / "class" / "thermal" / f"thermal_zone{i}"
        z.mkdir(parents=True)
        (z / "type").write_text(kind + "\n")
        (z / "temp").write_text(temp + "\n")
    check(desk.pkg_temp_c(hr) == 66, f"the package's own zone is read, not the hottest: {desk.pkg_temp_c(hr)}")
    (hr / "sys" / "class" / "thermal" / "thermal_zone1" / "temp").write_text("")
    check(desk.pkg_temp_c(hr) is None, "a package zone that reads empty: no reading, no error")
    check(desk.pkg_temp_c(Path(tempfile.mkdtemp(dir="/tmp"))) is None, "no thermal zones (a VM, a Mac): no reading")

    # a battery on the machine itself (DGO-1801): a laptop's supply says `Battery`; a server's directory is there and
    # holds none (vps1, measured: empty); a host whose supplies cannot be read at all says nothing
    hb = Path(tempfile.mkdtemp(prefix="desk-bat-", dir="/tmp"))
    ps = hb / "sys" / "class" / "power_supply"
    ps.mkdir(parents=True)
    check(desk.has_battery(hb) is False, "an empty power_supply directory — a server: no battery")
    (ps / "AC").mkdir()
    (ps / "AC" / "type").write_text("Mains\n")
    check(desk.has_battery(hb) is False, "a mains supply alone is not a battery")
    (ps / "BAT0").mkdir()
    (ps / "BAT0" / "type").write_text("Battery\n")
    check(desk.has_battery(hb) is True, "a laptop's BAT0 is a battery")
    check(desk.has_battery(Path(tempfile.mkdtemp(dir="/tmp"))) is None, "no power_supply directory: not known, not «no»")
    hu = Path(tempfile.mkdtemp(prefix="desk-bat-", dir="/tmp"))
    (hu / "sys" / "class" / "power_supply" / "BAT9").mkdir(parents=True)        # a supply with no readable `type`
    check(desk.has_battery(hu) is None, "a supply that cannot be read might be the battery: not known, not «no»")

    # an engine's VM on a person's computer (DGO-1801: the card calls only "" a server)
    ev = Path(tempfile.mkdtemp(prefix="desk-vm-", dir="/tmp"))
    pv = ev / "version"
    pv.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@…)\n")
    check(desk.engine_vm(ev, pv) == "wsl", "WSL's kernel names it: the HP")
    pv.write_text("Linux version 6.1.0-25-amd64 (person181-x@example.com)\n")
    (ev / "etc").mkdir()
    check(desk.engine_vm(ev, pv) is None, "no /etc/hosts to read: not known")
    (ev / "etc" / "hosts").write_text("127.0.0.1 localhost\n")
    check(desk.engine_vm(ev, pv) == "", "a plain kernel and plain hosts: the machine itself (vps1, the Dell)")
    (ev / "etc" / "hosts").write_text("127.0.0.1 localhost\n192.168.5.2 host.lima.internal host.docker.internal\n")
    check(desk.engine_vm(ev, pv) == "engine", "Lima's own host.lima.internal: the MacBook's engine")
    (ev / "etc" / "hosts").write_text("127.0.0.1 localhost\n")
    (ev / "etc" / "sysctl.d").mkdir()
    (ev / "etc" / "sysctl.d" / "90-bbox-memory.conf").write_text("vm.min_free_kbytes = 131072\n")
    check(desk.engine_vm(ev, pv) == "engine", "…or what its provisioning writes (the Mac's engine, the phone's guest)")
    check(desk.engine_vm(ev, ev / "no-such-version") is None, "an unreadable kernel version: not known")

    # the heavy-work slot: held or not read off the host's lock table by the slot file's device and inode
    ld = Path(tempfile.mkdtemp(prefix="desk-locks-", dir="/tmp"))
    (ld / "heavy").write_text("")
    (ld / "heavy.holder").write_text("bbox run apitools | pid 4242 on dgo | since 2026-11-10 23:30:00 UTC\n")
    st = os.stat(ld / "heavy")
    me = "%02x:%02x:%d" % (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    other_dev = "%02x:%02x:%d" % (os.major(st.st_dev) + 1, os.minor(st.st_dev), st.st_ino)
    pl = ld / "locks"
    pathlib_proc_locks = Path("/proc/locks")

    def slot(table):
        pl.write_text(table)
        return desk.heavy_slot(ld, pl)
    r = slot(f"1: FLOCK  ADVISORY  WRITE 4242 {me} 0 EOF\n2: POSIX  ADVISORY  WRITE 99 00:1f:12 0 EOF\n")
    check(r["held"] is True and r["holder"].startswith("bbox run apitools"), f"held, and by whom: {r}")
    r = slot(f"1: POSIX  ADVISORY  WRITE 4242 {me} 0 EOF\n")
    check(r["held"] is True, f"a flock that the kernel records as POSIX (a 9p checkout: WSL, the HP) is held too: {r}")
    r = slot(f"1: OFDLCK ADVISORY  READ  -1 00:1f:9 0 EOF\n2: LEASE  ACTIVE    READ  77 00:1f:9 0 EOF\nshort line\n")
    check(r["held"] is False, f"other files' locks and odd lines are not the slot: {r}")
    r = slot(f"1: FLOCK  ADVISORY  WRITE 4242 {other_dev} 0 EOF\n")
    check(r["held"] is False, f"the same inode on another device is another file: free: {r}")
    if pathlib_proc_locks.exists():           # Linux: a REAL flock, read back from the real lock table
        import fcntl
        with open(ld / "heavy", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            r = desk.heavy_slot(ld, pathlib_proc_locks)
        check(r["held"] is True, f"a real flock on this filesystem is seen in /proc/locks: {r}")
        check(desk.heavy_slot(ld, pathlib_proc_locks)["held"] is False, "…and released, it is free")
    else:
        print("SKIP a real flock: no /proc/locks here (not Linux)")
    r = slot(f"1: -> FLOCK  ADVISORY  WRITE 4243 {me} 0 EOF\n")
    check(r["held"] is False, f"a waiter's line alone is not a holder: {r}")
    r = slot("")
    check(r["held"] is False and r["holder"].startswith("bbox run"), f"nothing locked: free, and the last holder said: {r}")
    r = desk.heavy_slot(ld, ld / "no-such-table")
    check(r["held"] is None and "not readable" in r["why"], f"an unreadable lock table: unknown, not «free»: {r}")
    r = desk.heavy_slot(Path(tempfile.mkdtemp(dir="/tmp")), pl)
    check(r["held"] is None and "no heavy-work slot" in r["why"], f"an office that never took the slot: unknown: {r}")

    print("PASS test_desk" if not FAIL else f"FAIL test_desk ({len(FAIL)} failed)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
