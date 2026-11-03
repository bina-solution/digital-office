#!/usr/bin/env python3
"""lan-door.py — the engine's door on the Mac's LAN: the one guest port a peer office dials.

WHY. The engine forwards a guest port to the Mac's 127.0.0.1 and nowhere else (Lima's default), and
a forward to 0.0.0.0 is a rule of the VM's template, which takes effect only when the VM restarts —
which is never done without the owner at the machine. A peer office on the same LAN (the HP, beside
this MacBook) dials the Mac's OWN address. So this door takes the LAN's connections on 51443 and
hands each one to 127.0.0.1:51444, which the engine forwards to `dgo-net`, where the carrier
(apps/dgo-extend/carrier, `dgo-carry`) accepts it. That is the TCP path of a link that can never
carry a UDP packet (measured 2026-10-19: the guest receives no inbound UDP, and the HP's Windows
drops every inbound packet).

WHAT IT LETS IN. TCP from private (LAN) and link-local addresses only, at most PER_SOURCE at a time
from any one address, and only a connection that has said the carrier's whole first message (the
72-byte hello, `--first-bytes`) within `--first-timeout` seconds — so nothing that connects and stays
silent ever holds one of the carrier's few slots for unfinished handshakes. It reads nothing else: it
copies bytes, and the carrier still admits nobody who does not hold the pair's WireGuard key. When
either side ends, both are closed; a connection silent both ways for IDLE seconds is closed (the
carrier pings every 10 s, so a live one never is). It needs no admin, and macOS's application
firewall is off on this Mac (`socketfilterfw --getglobalstate`); where it is on, macOS asks once
whether python3 may accept incoming connections.

LIFETIME. Started by `bbox engine start` and by every `bbox` hand-off (packaging/macos/engine.sh),
one per Mac. It watches the engine's host-agent PID and exits when the engine stops, like the power
agent — also while it is still waiting for the port to be free.

THE CONSOLE'S DOOR (DGO-1125, the owner 2026-11-02: «expose the console in the local network on its ip
address … so I can access it from my phone»). The same door, a second instance, in HTTP's shape: no
hello (`--first-bytes 0`, a browser speaks first with its request), more connections per source (a
page opens several, `--per-source`), a cap on NEW connections per source per minute (`--rate`; the edge
behind Lima sees every client as one address, so this door is where a source can be told apart), and
it opens only while a policy file says so (`--policy`): {"on": true, "address": "<this Mac's LAN
address>", "port": 8080, "until": <epoch or 0>}. Written by the network screen, read every 5 s; off,
expired or absent closes the listener and every connection through it. The address is the LAN one, never
0.0.0.0: 127.0.0.1:8080 stays the engine's own forward (measured: both bind side by side).

WHEN THE MAC'S ADDRESS CHANGES (r030-002; measured 2026-11-03: after a reboot the router gave the Mac
192.168.16.104 instead of .100, and the door tried .100 every 5 s, "can't assign requested address").
The policy's address was never the owner's to choose — the screen writes the one this door reported — so
the door follows the Mac: when the address it should bind is no longer this Mac's, and the Mac is still
behind the SAME router it was opened behind (the default gateway's hardware address, kept in status.json),
it rewrites the policy's address to the one the Mac now leaves the LAN from. A Mac carried to another
network is never opened there by itself: the router differs, and the door stays shut until the owner
switches it on again. Once open, `.env`'s LAN_ADDRESS follows too (only when it is no longer one of this
Mac's addresses), and the LAN routes are re-made in the engine: lan-console's prepare (the derived name),
a render (the shared apps' LAN forms), and lan-signin recreated (its routes and sign-in URL).

Python 3.9 (the Command Line Tools' python3), standard library only.
"""
import argparse
import asyncio
import collections
import errno
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

MAX_CONNECTIONS = 64
PER_SOURCE = 4
CONNECT_TIMEOUT = 5.0
IDLE = 120.0
CHUNK = 65536


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + "[lan-door] " + msg, flush=True)


def allowed(peer):
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_link_local or ip.is_loopback


def host_port(text):
    host, _, port = text.rpartition(":")
    return host or "0.0.0.0", int(port)


def engine_alive(pid):
    if not pid:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Door:
    def __init__(self, to, first_bytes, first_timeout, per_source=PER_SOURCE, rate=0):
        self.to_host, self.to_port = to
        self.first_bytes, self.first_timeout = first_bytes, first_timeout
        self.per_source, self.rate = per_source, rate
        self.open = 0
        self.by_source = {}
        self.recent = collections.defaultdict(collections.deque)   # source -> its new connections' times
        self.writers = set()
        self.last_seen = {}                                          # source -> (epoch, admitted)
        self.gateway = ""          # the router this door last opened behind (its hardware address)
        self.routes_for = ""       # the address the LAN routes were last made for (sync_lan)
        self.render, self.render_for = None, ""     # the engine run re-making them, and for which address
        self.render_next, self.render_wait = 0.0, RERENDER_RETRY   # not before; the next wait after a failure
        self.refused = None        # (old, new) the door last declined to follow, said once

    def over_rate(self, peer):
        """More than `rate` new connections from one source in the last minute (0 = no cap)."""
        if not self.rate:
            return False
        now, seen = time.monotonic(), self.recent[peer]
        while seen and now - seen[0] > 60:
            seen.popleft()
        if len(seen) >= self.rate:
            return True
        seen.append(now)
        return False

    def prune(self):
        """Forget the sources that opened nothing in the last minute (over IPv6 the keys are unbounded)."""
        now = time.monotonic()
        for peer in [k for k, seen in self.recent.items() if not seen or now - seen[-1] > 60]:
            del self.recent[peer]

    def close_all(self):
        for w in list(self.writers):
            try:
                w.close()
            except OSError:
                pass

    async def pipe(self, reader, writer, touched):
        try:
            while True:
                data = await reader.read(CHUNK)
                if not data:
                    return
                touched[0] = time.monotonic()
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            return

    async def idle_watch(self, touched):
        while True:
            await asyncio.sleep(IDLE / 4)
            if time.monotonic() - touched[0] > IDLE:
                return

    async def handle(self, creader, cwriter):
        peer = (cwriter.get_extra_info("peername") or ("?", 0))[0]
        if (not allowed(peer) or self.open >= MAX_CONNECTIONS
                or self.by_source.get(peer, 0) >= self.per_source or self.over_rate(peer)):
            self.last_seen[peer] = (time.time(), False)
            cwriter.close()
            return
        self.last_seen[peer] = (time.time(), True)
        self.open += 1
        self.by_source[peer] = self.by_source.get(peer, 0) + 1
        self.writers.add(cwriter)
        uwriter = None
        try:
            # The carrier's first message, whole, before anything is opened toward the engine.
            try:
                first = await asyncio.wait_for(creader.readexactly(self.first_bytes), self.first_timeout)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError):
                return
            try:
                ureader, uwriter = await asyncio.wait_for(
                    asyncio.open_connection(self.to_host, self.to_port), CONNECT_TIMEOUT)
            except (OSError, asyncio.TimeoutError) as e:
                log("%s: the engine's %s:%d does not answer (%s) — is dgo-net publishing it?"
                    % (peer, self.to_host, self.to_port, e))
                return
            for w in (cwriter, uwriter):
                sock = w.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            uwriter.write(first)
            await uwriter.drain()
            touched = [time.monotonic()]
            started = time.monotonic()
            tasks = [asyncio.ensure_future(self.pipe(creader, uwriter, touched)),
                     asyncio.ensure_future(self.pipe(ureader, cwriter, touched)),
                     asyncio.ensure_future(self.idle_watch(touched))]
            # Either side ending ends the connection: the carrier's stream is one conversation, and a
            # half left open is only a slot held for nothing.
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
            lasted = time.monotonic() - started
            if lasted > 5:
                log("%s: a carrier session of %ds ended" % (peer, int(lasted)))
        finally:
            self.open -= 1
            self.writers.discard(cwriter)
            left = self.by_source.get(peer, 1) - 1
            if left > 0:
                self.by_source[peer] = left
            else:
                self.by_source.pop(peer, None)
            for w in (cwriter, uwriter):
                if w is not None:
                    try:
                        w.close()
                    except OSError:
                        pass


async def watch(pid):
    while True:
        await asyncio.sleep(10)
        if not engine_alive(pid):
            log("the engine stopped (pid %d) — closing the door" % pid)
            return


def read_policy(path):
    """(address, port) while the policy file says on and its time has not passed; None otherwise.

    The address must be one of the LAN's: never loopback (127.0.0.1:8080 is the engine's own forward) and
    never 0.0.0.0 (every interface, a public one included, would be listening)."""
    try:
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
        until = float(p.get("until") or 0)
        port = int(p.get("port") or 8080)
        ip = ipaddress.ip_address(str(p.get("address") or ""))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if p.get("on") is not True or (until and time.time() >= until):    # "false" as a string is not on
        return None
    if not lan_ok(str(ip)):
        return None
    if not 1024 <= port <= 65535 or port == 51443:                       # 51443 is the link's own door
        return None
    return str(ip), port


def lan_ok(addr):
    """A LAN address: IPv4, private or link-local, never loopback (the engine's own forward) or 0.0.0.0."""
    try:
        ip = ipaddress.IPv4Address(addr)
    except ValueError:
        return False
    return not (ip.is_unspecified or ip.is_loopback) and (ip.is_private or ip.is_link_local)


def source_toward(ip):
    """The address this Mac sends from toward `ip` (a UDP socket's connect sends nothing)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ip, 9))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def lan_address():
    """This Mac's address on the LAN: the one it reaches its own router from. Not the address toward the
    internet: a full-tunnel VPN takes 0/1 and 128/1 and leaves `default` on the Wi-Fi, so "toward the
    internet" is the tunnel's address while the router is still the home's (the second reader)."""
    gw = gateway()[0]
    return (source_toward(gw) if gw else "") or source_toward("192.0.2.1")


def own(ip):
    """Is `ip` one of this Mac's own addresses? (Only an own address can be bound.)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((ip, 0))
        return True
    except (OSError, ValueError, TypeError):
        return False
    finally:
        s.close()


_GATEWAY = {"at": 0.0, "value": ("", "")}
GATEWAY_TTL = 60.0


def gateway(fresh=False):
    """(the default router's address, its hardware address) — which network the Mac is on, whatever
    address it was given; ("", "") when not known (no route, or ARP not resolved yet). Asked of `route` and
    `arp` at most once a minute (the status is written every 5 s), unless `fresh`."""
    if not fresh and time.time() - _GATEWAY["at"] < GATEWAY_TTL:
        return _GATEWAY["value"]
    value = ("", "")
    try:
        out = subprocess.run(["/sbin/route", "-n", "get", "default"], capture_output=True, text=True,
                             timeout=5).stdout
        gw = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", out)
        if gw:
            arp = subprocess.run(["/usr/sbin/arp", "-n", gw.group(1)], capture_output=True, text=True,
                                 timeout=5).stdout
            m = re.search(r" at ([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5}) ", arp)
            value = (gw.group(1), m.group(1) if m else "")
    except (OSError, subprocess.SubprocessError):
        pass
    _GATEWAY.update(at=time.time(), value=value)
    return value


def write_json_text(path, text):
    """Written whole, then moved into place: a reader never sees half a file. The file keeps its mode
    and, where it is a link, stays one (the target is replaced) — a policy written 0600 stays 0600."""
    real = os.path.realpath(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if os.path.exists(real):
            shutil.copymode(real, tmp)
        os.replace(tmp, real)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json(path, obj):
    write_json_text(path, json.dumps(obj))


def follow(policy, door, want):
    """The policy's address is no longer this Mac's: follow the Mac — only behind the same router."""
    gw = gateway(fresh=True)[1]
    if not gw:
        return                              # not known yet (ARP still resolving): ask again in 5 s
    now = lan_address()
    if not now or now == want[0] or not lan_ok(now):
        return
    if door.gateway and gw == door.gateway:
        if follow_address(policy, want[0], now):
            log("the Mac's address moved on the same network: %s → %s; the policy follows" % (want[0], now))
    elif door.refused != (want[0], now):
        door.refused = (want[0], now)
        log("the Mac is now %s behind %s: the door stays shut there until the console is switched on again"
            % (now, "another router" if door.gateway else "a router it has no record of"))


def follow_address(policy, old, new):
    """Rewrite the policy's address (old → new), the rest of it as the owner switched it."""
    try:
        with open(policy, encoding="utf-8") as f:
            p = json.load(f)
        if str(p.get("address") or "") != old:
            return False                     # the screen wrote something else meanwhile: that wins
        p.update(address=new, moved_from=old, moved_at=int(time.time()))
        write_json(policy, p)
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


RERENDER_RETRY = 60.0          # the first wait after a failed run; it doubles, up to RERENDER_MAX
RERENDER_MAX = 3600.0


def sync_lan(policy, door, addr):
    """The LAN routes made for the address the door is open on. `door.routes_for` (kept in status.json, so
    a restart remembers it) is the address they were last made for; when it differs, the engine re-makes
    them in the background — the door keeps serving meanwhile — and a failed run is tried again a minute
    later, then two, four… up to an hour, said once (a state that keeps it failing — forward-auth down or
    without its owner — must not become an engine call a minute on an 8 GB Mac: the second reader).
    In the engine, behind the office's heavy-job slot (no second render beside a `bbox run`):
    `.env`'s LAN_ADDRESS by lib.sh's env_set (its mode and link kept), only when the one there is no longer
    this Mac's; lan-console's prepare (the derived name); a render (the shared apps' LAN forms); lan-signin
    (its routes and sign-in URL) and dashboard-feed (the name the screen shows) recreated."""
    if door.render is not None:
        rc = door.render.poll()
        if rc is None:
            return                           # still running
        door.render = None
        if rc == 0:
            door.routes_for, door.render_wait = door.render_for, RERENDER_RETRY
            log("the LAN routes are made for %s" % door.render_for)
        else:
            if door.render_wait == RERENDER_RETRY:
                log("re-making the LAN routes for %s failed (exit %d); trying again from %d s, doubling up to an hour"
                    % (door.render_for, rc, RERENDER_RETRY))
            door.render_next = time.time() + door.render_wait
            door.render_wait = min(door.render_wait * 2, RERENDER_MAX)
    if door.routes_for == addr or time.time() < door.render_next or not lan_ok(addr):
        return
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(policy))))   # <repo>/data/lan/x
    try:
        with open(os.path.join(root, ".env"), encoding="utf-8") as f:
            cur = next((l.split("=", 1)[1].strip() for l in f.read().splitlines() if l.startswith("LAN_ADDRESS=")), "")
    except OSError:
        return
    if not cur:
        return                               # not set: this office keeps no LAN console of its own
    env = "" if (cur == addr or own(cur)) else "env_set LAN_ADDRESS %s && " % shlex.quote(addr)
    cmd = (". scripts/lib.sh && heavy_admit lan-follow 400 && " + env +
           "./bbox lan-console prepare && python3 platform/manager/reconcile.py render >/dev/null && "
           "./scripts/dc up -d --no-deps lan-signin dashboard-feed")
    log("re-making the LAN routes for %s in the engine%s" % (addr, " (LAN_ADDRESS %s → %s)" % (cur, addr) if env else ""))
    door.render_for = addr
    try:
        door.render = subprocess.Popen(
            ["/bin/bash", os.path.join(root, "packaging/macos/engine.sh"), "exec", "--", "bash", "-c", cmd],
            cwd=root, stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        log("could not start the re-render (%s)" % e)


def write_status(policy, door, bound, failed):
    """status.json beside the policy, for the screen: open or not, where, why not, and who came in the last
    hour (an address and whether it was admitted). Written whole, then moved into place."""
    now = time.time()
    for peer in [k for k, (t, _) in door.last_seen.items() if now - t > 3600]:
        del door.last_seen[peer]
    for peer, _ in sorted(door.last_seen.items(), key=lambda kv: -kv[1][0])[32:]:   # the newest 32 only
        del door.last_seen[peer]
    status = {"at": int(now), "open": "%s:%d" % bound if bound else None,
              "error": ("cannot take %s:%d" % failed) if failed else "", "address": lan_address(),
              "gateway": door.gateway, "routes_for": door.routes_for,
              "sources": [{"ip": k, "last": int(t), "admitted": ok, "connections": door.by_source.get(k, 0)}
                          for k, (t, ok) in sorted(door.last_seen.items(), key=lambda kv: -kv[1][0])]}
    path = os.path.join(os.path.dirname(policy) or ".", "status.json")
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(status, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


async def serve_policy(policy, to, watch_pid, door):
    """Open the door while the policy says on, close it (and every connection through it) when it stops."""
    server, bound, failed = None, None, None
    try:              # the router it was last open behind, and what the routes were made for, survive a restart
        with open(os.path.join(os.path.dirname(policy) or ".", "status.json"), encoding="utf-8") as f:
            last = json.load(f)
        door.gateway, door.routes_for = str(last.get("gateway") or ""), str(last.get("routes_for") or "")
    except (OSError, ValueError, AttributeError):
        pass
    while engine_alive(watch_pid):
        write_status(policy, door, bound, failed)
        want = read_policy(policy)
        door.prune()
        if server is not None and not own(bound[0]):
            # the address went away under an open listener (sleep and wake, a new lease on reconnect): let it
            # go, so the bind below fails as EADDRNOTAVAIL and the address can be followed
            server.close()
            door.close_all()
            await server.wait_closed()
            log("closed: %s:%d is no longer this Mac's address" % bound)
            server, bound = None, None
        if want != bound:
            if server is not None:
                server.close()
                door.close_all()             # first: from 3.12 wait_closed() waits for open connections
                await server.wait_closed()
                log("closed: %s:%d (the policy is off, expired or moved)" % bound)
                server, bound = None, None
            if want is not None:
                try:
                    server = await asyncio.start_server(door.handle, want[0], want[1], reuse_address=True)
                    bound, failed = want, None
                    door.gateway = gateway(fresh=True)[1] or door.gateway
                    log("open: %s:%d → %s:%d (private sources only, %d at a time and %s new a minute each)"
                        % (want[0], want[1], to[0], to[1], door.per_source, door.rate or "any"))
                except OSError as e:
                    if failed != want:
                        log("cannot take %s:%d (%s) — trying again every 5 s" % (want[0], want[1], e))
                        failed = want
                    if e.errno == errno.EADDRNOTAVAIL:
                        follow(policy, door, want)
        if bound is not None:
            sync_lan(policy, door, bound[0])
        await asyncio.sleep(5)
    log("the engine stopped (pid %d) — closing the door" % watch_pid)
    if server is not None:
        server.close()
        door.close_all()


async def serve(listen, to, watch_pid, first_bytes, first_timeout, per_source=PER_SOURCE, rate=0):
    door = Door(to, first_bytes, first_timeout, per_source, rate)
    host, port = listen
    server = None
    said = False
    while server is None:
        if not engine_alive(watch_pid):
            log("the engine stopped (pid %d) before the door could open" % watch_pid)
            return
        try:
            server = await asyncio.start_server(door.handle, host, port, reuse_address=True)
        except OSError as e:
            if not said:
                log("cannot take %s:%d (%s) — trying again every 10 s" % (host, port, e))
                said = True
            await asyncio.sleep(10)
    log("open: %s:%d → %s:%d (private sources only, %d at a time each)" % (host, port, to[0], to[1], per_source))
    async with server:
        if watch_pid:
            await watch(watch_pid)
        else:
            await server.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", default="0.0.0.0:51443")
    ap.add_argument("--to", default="127.0.0.1:51444")
    ap.add_argument("--watch-pid", type=int, default=0, help="exit when this process (the engine) ends")
    ap.add_argument("--first-bytes", type=int, default=72, help="the carrier's hello: forwarded only once whole")
    ap.add_argument("--first-timeout", type=float, default=3.0)
    ap.add_argument("--per-source", type=int, default=PER_SOURCE, help="connections at a time from one address")
    ap.add_argument("--rate", type=int, default=0, help="new connections a minute from one address (0 = no cap)")
    ap.add_argument("--policy", default="", help="open only while this JSON says on (the console's door)")
    a = ap.parse_args()
    try:
        if a.policy:
            door = Door(host_port(a.to), a.first_bytes, a.first_timeout, a.per_source, a.rate)
            asyncio.run(serve_policy(a.policy, host_port(a.to), a.watch_pid, door))
        else:
            asyncio.run(serve(host_port(a.listen), host_port(a.to), a.watch_pid, a.first_bytes, a.first_timeout,
                              a.per_source, a.rate))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
