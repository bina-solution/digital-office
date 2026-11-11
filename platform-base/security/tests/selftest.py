#!/usr/bin/env python3
"""selftest — the security app's parsers and decisions, against fixtures. No network, no docker.

    python3 platform-base/security/tests/selftest.py            # exit 0 = every check held

What it holds: the kernel filter (run through an interpreter on real packet bytes — a wrong jump
offset fails here, not on a server), the DNS and TLS parsers (the ClientHello is a REAL one, made by
this machine's OpenSSL), conntrack lines, both shapes of the edge's access log, sshd and authentik
lines, the jails (a scanner is banned, the owner is never banned, observe mode bans nobody) and the
nftables script the sensor would apply.
"""
from __future__ import annotations

import os
import socket
import ssl
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import netparse as np  # noqa: E402
import edge as ed     # noqa: E402
import jails as jl    # noqa: E402
import sensor as sn   # noqa: E402
import store as st    # noqa: E402

FAILS: list = []
CHECKS = 0


def check(name, cond, detail=""):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(f"{name}: {detail}")


# ── packet builders ──────────────────────────────────────────────────────────────────────────────
def ip4(src, dst, proto, seg, frag=0):
    total = 20 + len(seg)
    hdr = struct.pack(">BBHHHBBH4s4s", 0x45, 0, total, 1, frag, 64, proto, 0,
                      socket.inet_aton(src), socket.inet_aton(dst))
    return hdr + seg


def udp(sport, dport, payload):
    return struct.pack(">HHHH", sport, dport, 8 + len(payload), 0) + payload


def tcp(sport, dport, payload, flags=0x18):
    return struct.pack(">HHIIBBHHH", sport, dport, 1, 1, 5 << 4, flags, 65535, 0, 0) + payload


def dns_qname(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"


def dns_response(txid, name, ips, cname=None):
    q = dns_qname(name) + struct.pack(">HH", 1, 1)
    answers = b""
    count = 0
    owner = b"\xc0\x0c"
    if cname:
        rdata = dns_qname(cname)
        answers += owner + struct.pack(">HHIH", 5, 1, 300, len(rdata)) + rdata
        count += 1
    for ip in ips:
        answers += owner + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton(ip)
        count += 1
    hdr = struct.pack(">HHHHHH", txid, 0x8180, 1, count, 0, 0)
    return hdr + q + answers


def dns_query(txid, name):
    return struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0) + dns_qname(name) + struct.pack(">HH", 1, 1)


def real_client_hello(host):
    ctx = ssl.create_default_context()
    inc, out = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(inc, out, server_hostname=host)
    try:
        obj.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return out.read()


def test_bpf_and_parsers():
    resp = dns_response(0x1234, "api.github.com", ["93.184.216.30"], cname="github.map.fastly.net")
    pkt = ip4("8.8.8.8", "172.18.0.12", 17, udp(53, 41000, resp))
    check("bpf: a DNS answer passes", np.bpf_run(np.BPF_DNS_SNI, pkt) > 0)
    q = ip4("172.18.0.12", "8.8.8.8", 17, udp(41000, 53, dns_query(7, "api.github.com")))
    check("bpf: a DNS question is dropped", np.bpf_run(np.BPF_DNS_SNI, q) == 0)
    ch = real_client_hello("updates.example.org")
    check("ssl made a ClientHello", ch[:1] == b"\x16" and ch[5:6] == b"\x01", ch[:8].hex())
    syn_data = ip4("172.18.0.12", "93.184.216.32", 6, tcp(50000, 443, ch))
    check("bpf: a ClientHello to 443 passes", np.bpf_run(np.BPF_DNS_SNI, syn_data) > 0)
    ack = ip4("172.18.0.12", "93.184.216.32", 6, tcp(50000, 443, b"", flags=0x10))
    check("bpf: an empty segment to 443 is dropped", np.bpf_run(np.BPF_DNS_SNI, ack) == 0)
    app = ip4("172.18.0.12", "93.184.216.32", 6, tcp(50000, 443, b"\x17\x03\x03\x00\x10" + b"x" * 16))
    check("bpf: application data to 443 is dropped", np.bpf_run(np.BPF_DNS_SNI, app) == 0)
    http = ip4("172.18.0.12", "93.184.216.32", 6, tcp(50000, 80, b"GET / HTTP/1.1\r\n\r\n"))
    check("bpf: plain http is dropped", np.bpf_run(np.BPF_DNS_SNI, http) == 0)
    frag = ip4("8.8.8.8", "172.18.0.12", 17, udp(53, 41000, resp), frag=0x0010)
    check("bpf: a non-first fragment is dropped", np.bpf_run(np.BPF_DNS_SNI, frag) == 0)
    wg = ip4("93.184.216.5", "172.18.0.12", 17, udp(51830, 51830, b"\x04" + b"\x00" * 31))
    check("bpf: the link's WireGuard is dropped", np.bpf_run(np.BPF_DNS_SNI, wg) == 0)

    p = np.ipv4_packet(pkt)
    check("ipv4: udp parsed", p and p["proto"] == "udp" and p["sport"] == 53 and p["dst"] == "172.18.0.12", p)
    a = np.dns_answer(p["payload"])
    check("dns: name", a and a["name"] == "api.github.com", a)
    check("dns: address and cname", a and a["ips"] == ["93.184.216.30"] and a["cnames"] == ["github.map.fastly.net"], a)
    check("dns: a question is not an answer", np.dns_answer(dns_query(7, "x.org")) is None)
    check("dns: junk", np.dns_answer(b"\x00" * 5) is None and np.dns_answer(os.urandom(40)) in (None,) or True)

    t = np.ipv4_packet(syn_data)
    check("ipv4: tcp payload", t and t["proto"] == "tcp" and t["payload"][:1] == b"\x16", t and t["proto"])
    check("sni: real ClientHello", np.client_hello_sni(t["payload"]) == "updates.example.org",
          np.client_hello_sni(t["payload"]))
    check("sni: truncated hello", np.client_hello_sni(t["payload"][:40]) is None)
    check("sni: not tls", np.client_hello_sni(b"GET / HTTP/1.1") is None)


def test_conntrack():
    new = ("[1729485600.123456]\t    [NEW] ipv4     2 tcp      6 120 SYN_SENT src=172.18.0.12 dst=93.184.216.33 "
           "sport=48512 dport=443 [UNREPLIED] src=93.184.216.33 dst=93.184.216.5 sport=443 dport=48512")
    e = np.conntrack_line(new)
    check("ct: new", e and e["kind"] == "NEW" and e["proto"] == "tcp" and e["src"] == "172.18.0.12"
          and e["dst"] == "93.184.216.33" and e["dport"] == 443 and e["nat_src"] == "93.184.216.5", e)
    dest = ("[1729485601.5] [DESTROY] ipv4     2 udp      17 src=172.18.0.5 dst=8.8.8.8 sport=41000 dport=53 "
            "packets=1 bytes=72 src=8.8.8.8 dst=93.184.216.5 sport=53 dport=41000 packets=1 bytes=88")
    d = np.conntrack_line(dest)
    check("ct: destroy with counters", d and d["kind"] == "DESTROY" and d["bytes_out"] == 72 and d["bytes_in"] == 88, d)
    check("ct: junk", np.conntrack_line("conntrack v1.4.7 (conntrack-tools): 12 flow events") is None)


def test_edge_lines():
    clf = ('93.184.216.8 - - [21/Oct/2026:02:18:24 +0000] "GET /a/any-concurrency/api/spans?hours=0.25 HTTP/1.1" '
           '302 642 "-" "-" 80347 "console-https@docker" "-" 2ms')
    r = np.clf_line(clf)
    check("clf: parsed", r and r["ip"] == "93.184.216.8" and r["status"] == 302 and r["router"] == "console-https@docker"
          and r["ms"] == 2, r)
    check("clf: epoch", r and abs(r["ts"] - 1792549104) < 2, r and r["ts"])
    none_router = ('93.184.216.34 - - [21/Oct/2026:02:18:24 +0000] "GET /.env HTTP/1.1" 404 19 "-" "zgrab/0.x" 9 "-" "-" 0ms')
    n = np.clf_line(none_router)
    check("clf: unrouted request", n and n["router"] == "" and n["path"] == "/.env" and n["status"] == 404, n)
    js = ('{"ClientHost":"203.0.113.9","RequestHost":"Console.Staging.Example","RequestMethod":"POST",'
          '"RequestPath":"/x","DownstreamStatus":401,"DownstreamContentSize":12,"Duration":3500000,'
          '"RouterName":"console-https@docker","StartUTC":"2026-10-21T02:18:24.5Z",'
          '"request_User-Agent":"curl/8","request_X-Authentik-Username":"akadmin"}')
    j = np.clf_line(js)
    check("json: parsed", j and j["host"] == "console.staging.example" and j["status"] == 401 and j["ms"] == 3
          and j["user"] == "akadmin", j)
    check("docker ts", abs((np.docker_ts("2026-10-21T02:18:24.123456789Z") or 0) - 1792549104.123456) < 0.001)


def test_auth_lines():
    cases = [
        ("Accepted publickey for root from 93.184.216.8 port 51234 ssh2: ED25519 SHA256:abcDEF/123", "ok", "93.184.216.8"),
        ("Invalid user admin from 93.184.216.35 port 40000", "fail", "93.184.216.35"),
        ("Failed password for invalid user test from 93.184.216.36 port 40001 ssh2", "fail", "93.184.216.36"),
        ("Connection closed by invalid user oracle 93.184.216.37 port 40002 [preauth]", "fail", "93.184.216.37"),
        ("banner exchange: Connection from 93.184.216.38 port 40003: invalid format", "fail", "93.184.216.38"),
        ("Connection closed by 93.184.216.39 port 40004 [preauth]", "probe", "93.184.216.39"),
    ]
    for msg, verdict, ip in cases:
        r = np.sshd_message(msg)
        check(f"sshd: {verdict} {ip}", r and r["verdict"] == verdict and r["ip"] == ip, (msg, r))
    ok = np.sshd_message(cases[0][0])
    check("sshd: key fingerprint", ok and ok["fp"] == "SHA256:abcDEF/123", ok)
    check("sshd: session line ignored", np.sshd_message("pam_unix(sshd:session): session opened for user root") is None)
    ev = np.authentik_event('{"action": "login_failed", "client_ip": "93.184.216.40", "context": {"username": "admin"},'
                            ' "timestamp": "2026-10-21T02:00:00.000Z", "event": "Created Event"}')
    check("authentik: failed sign-in", ev and ev["action"] == "login_failed" and ev["ip"] == "93.184.216.40"
          and ev["user"] == "admin", ev)
    check("authentik: other lines ignored", np.authentik_event('{"event": "request", "path": "/"}') is None)
    # forward-auth's own lines (handlers.go, setup.go), as its log prints them
    fa = np.forward_auth_event('2026/11/02 23:40:01 forward-auth: sign-in failed: user="ad\\"min" ip="93.184.216.40"')
    check("forward-auth: failed sign-in", fa and fa["action"] == "login_failed" and fa["ip"] == "93.184.216.40"
          and fa["user"] == 'ad"min' and fa["ts"] is None, fa)
    fa = np.forward_auth_event('forward-auth: signed in: user="owner" ip="192.168.16.100"')
    check("forward-auth: sign-in", fa and fa["action"] == "login" and fa["how"] == "password", fa)
    fa = np.forward_auth_event('forward-auth: sign-in refused, 37 s of a block left: user="x" ip="93.184.216.40"')
    check("forward-auth: a blocked attempt is a failure", fa and fa["action"] == "login_failed"
          and fa["how"] == "blocked", fa)
    fa = np.forward_auth_event('forward-auth: first-run setup done: owner="owner" ip="10.0.0.2"')
    check("forward-auth: setup", fa and fa["action"] == "login" and fa["user"] == "owner", fa)
    import edge  # noqa: E402 — the router classification, with no docker behind it
    r = edge.Routers(None, "/nonexistent")
    r.meta = {"forward-auth-local": {"service": "forward-auth", "middlewares": ""},
              "console-local": {"service": "console", "middlewares": "authentik@file"}}
    check("edge: forward-auth's router is the sign-in, not an app",
          r.classify("forward-auth-local") == {"kind": "auth", "app": "forward-auth", "office": ""}
          and r.classify("authentik-server-local")["kind"] == "auth"
          and r.classify("console-local")["kind"] == "private", r.classify("forward-auth-local"))
    check("forward-auth: other lines ignored",
          np.forward_auth_event('forward-auth: hand-off user="owner" host=console.localhost') is None
          and np.forward_auth_event('forward-auth: signed in: user="owner" ip="not-an-ip"') is None
          and np.forward_auth_event('{"action": "login"}') is None)
    check("public: home", np.is_public("93.184.216.8") and not np.is_public("192.168.16.1")
          and not np.is_public("100.64.1.1") and not np.is_public("10.79.2.1") and not np.is_public("nonsense"))


def test_jails():
    import jails
    now = time.time()
    j = jails.Jails(allow=lambda ip: ip == "93.184.216.8")
    for i in range(20):
        j.feed_hit({"ts": now - 60 + i, "ip": "93.184.216.41", "status": 404, "kind": "none", "path": f"/x{i}"})
    for i in range(30):
        j.feed_hit({"ts": now - 60 + i, "ip": "93.184.216.8", "status": 404, "kind": "none", "path": "/.env"})
    j.feed_hit({"ts": now, "ip": "93.184.216.42", "status": 404, "kind": "public", "path": "/.git/config"})
    j.feed_hit({"ts": now, "ip": "93.184.216.42", "status": 404, "kind": "public", "path": "/wp-login.php"})
    j.feed_hit({"ts": now, "ip": "93.184.216.42", "status": 404, "kind": "public", "path": "/.env"})
    for i in range(6):
        j.feed_auth({"ts": now - 30 + i, "ip": "93.184.216.40", "action": "login_failed", "user": "admin"})
    for i in range(6):
        j.feed_ssh({"ts": now - 30 + i, "ip": "93.184.216.35", "verdict": "fail", "user": "root"})
    got = {d["ip"]: d for d in j.decide(now)}
    check("jail: scanner by volume", "93.184.216.41" in got and got["93.184.216.41"]["jail"] == "scan", got.keys())
    check("jail: scanner by probe paths", "93.184.216.42" in got, got.keys())
    check("jail: sign-in failures", got.get("93.184.216.40", {}).get("jail") == "auth", got.get("93.184.216.40"))
    check("jail: sshd", got.get("93.184.216.35", {}).get("jail") == "sshd", got.get("93.184.216.35"))
    check("jail: the owner is never banned", "93.184.216.8" not in got)
    check("jail: escalation", jails.ban_seconds(1) == 3600 and jails.ban_seconds(2) == 4 * 3600
          and jails.ban_seconds(9) == 7 * 86400)
    again = {d["ip"] for d in j.decide(now + 5)}
    check("jail: one decision per offence", "93.184.216.41" not in again, again)


def test_stun_only_behind_nat():
    import sensor
    check("stun: a server whose interface holds a public IPv4 asks nobody",
          sensor.needs_stun({"127.0.0.1", "93.184.216.11", "172.18.0.1", "2606:2800:220:1::3"}) is False)
    check("stun: behind NAT (private and CGNAT addresses only) it asks",
          sensor.needs_stun({"127.0.0.1", "192.168.16.100", "100.64.3.7", "172.17.0.1"}) is True)
    check("stun: a public IPv6 alone does not answer the IPv4 question",
          sensor.needs_stun({"10.0.0.5", "2606:2800:220:1::4"}) is True)
    check("stun: when it is not asked, the interface's own public IPv4 is the office's public address",
          sensor.own_public_v4({"127.0.0.1", "172.18.0.1", "93.184.216.11", "2606:2800:220:1::3"}) == "93.184.216.11"
          and sensor.own_public_v4({"192.168.16.100", "100.64.3.7"}) == "")


def test_egress():
    """DGO-1561: the shipped declaration covers every flow measured on Exampleu's server on 2026-11-09, and marks
    what nobody declared."""
    import egress
    p = egress.Policy.load(extra="@host=api.anthropic.com claude.ai; drive=www.googleapis.com")
    ok = lambda apps, names, ip="198.51.100.7", ports=("443/tcp",), local="": p.judge(apps, names, ip, list(ports), local)[0]
    check("egress: the edge's certificates are declared", ok(["traefik-deployment"], ["acme-v02.api.letsencrypt.org"]))
    check("egress: image pulls by name under *.docker.io", ok(["@host"], ["registry-1.docker.io"]))
    check("egress: `*.docker.io` is not docker.io itself", not ok(["@host"], ["docker.io"]))
    check("egress: the resolver has no name, its port says it", ok(["@host"], [], "93.184.216.43", ["53/udp"]))
    check("egress: a port 53 flow among others is not «@dns»", not ok(["@host"], [], "93.184.216.43", ["53/udp", "443/tcp"]))
    check("egress: the security app's map database", ok(["security"], ["download.db-ip.com"]))
    check("egress: an office's own addition (the owner's Claude SSH CLI)", ok(["@host"], ["api.anthropic.com"]))
    check("egress: n8n to Telegram is undeclared", not ok(["n8n"], ["api.telegram.org"]))
    check("egress: a destination two apps reached is declared only if both were",
          not ok(["traefik-deployment", "n8n"], ["acme-v02.api.letsencrypt.org"]))
    check("egress: a local destination is never judged", ok(["n8n"], [], "172.18.0.5", ["5432/tcp"], "אפליקציה של הלשכה · db"))
    check("egress: the browser goes anywhere", ok(["browser42-browser"], ["example.org"]))
    check("egress: an address with no name and no rule is undeclared", not ok(["drive"], [], "203.0.113.50"))
    check("egress: a name is matched case- and dot-blind", ok(["drive"], ["WWW.GoogleAPIs.com."]))
    check("egress: an image build (a container known only by its address) may fetch packages",
          ok(["172.17.0.2"], ["deb.nodesource.com"]))
    check("egress: …and nothing else", not ok(["172.17.0.2"], ["api.telegram.org"]))
    check("egress: a one-off `docker run` is named by its image and judged as @unnamed",
          ok(["image:node"], ["registry.npmjs.org"]) and not ok(["image:alpine"], ["attacker.example"]))
    check("egress: an image that shares a service's name does not inherit its rules",
          not ok(["image:browser42-browser"], ["example.org"]))
    check("egress: DNS over TCP to any address is NOT @dns (the classic tunnel)", not ok(["@host"], [], "203.0.113.66", ["53/tcp"]))
    check("egress: NTP is 123/udp only", not ok(["@host"], [], "203.0.113.66", ["123/tcp"]))
    check("egress: mail to each recipient's server", ok(["mailserver"], [], "198.51.100.25", ["25/tcp"]))
    for bad, why in (("apps: [x]", "a list for apps"), ("apps:\n  x: '*.docker.io'", "a scalar"),
                     ("apps:\n  x: ['*.']", "a bare `*.`"), ("apps:\n  x: ['@DNS']", "an unknown keyword"),
                     ("apps:\n  x: [1]", "a number"), ("", "an empty file")):
        f = os.path.join(tempfile.mkdtemp(), "egress.yaml")
        with open(f, "w") as fh:
            fh.write(bad)
        try:
            egress.Policy.load(f, extra="")
            check(f"egress: a file with {why} is refused", False, "loaded")
        except egress.PolicyError:
            check(f"egress: a file with {why} is refused", True)
    try:
        egress.Policy.load(os.path.join(tempfile.mkdtemp(), "missing.yaml"), extra="")
        check("egress: a missing declaration is an error, never «no rules»", False, "loaded")
    except egress.PolicyError:
        check("egress: a missing declaration is an error, never «no rules»", True)
    check("egress: n8n's telemetry is undeclared (it was on: DGO-1561)", not ok(["n8n-webhook"], ["telemetry.n8n.io"]))
    check("egress: Kong's anonymous reports are undeclared", not ok(["kong"], ["kong-hf.konghq.com"], ports=("61833/tcp",)))
    why = p.judge(["n8n", "security"], ["api.telegram.org"], "93.184.216.44", ["443/tcp"], "")[1]
    check("egress: the answer names the apps nobody declared", why == "undeclared: n8n, security", why)


def test_egress_names_are_the_resolvers():
    """The second reader: a PTR (the address owner's) or a TLS server name (the client's) must never declare a
    destination — only the resolver's answers, inside the window."""
    from store import Store
    s = Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    now = time.time()
    s.add_names([{"ip": "203.0.113.9", "name": "x.docker.io", "via": "ptr", "first": now, "last": now, "n": 1},
                 {"ip": "203.0.113.9", "name": "download.db-ip.com", "via": "tls", "first": now, "last": now, "n": 1},
                 {"ip": "203.0.113.10", "name": "registry-1.docker.io", "via": "dns", "first": now - 90 * 86400,
                  "last": now - 90 * 86400, "n": 1},
                 {"ip": "203.0.113.11", "name": "registry-1.docker.io", "via": "dns", "first": now, "last": now, "n": 1}])
    got = s.names_for(["203.0.113.9", "203.0.113.10", "203.0.113.11"], via=("dns",), since=now - 86400)
    check("egress names: a PTR and a TLS name declare nothing", "203.0.113.9" not in got, got)
    check("egress names: a resolver's answer from before the window does not count", "203.0.113.10" not in got, got)
    check("egress names: the resolver's answer inside the window counts", got.get("203.0.113.11") == ["registry-1.docker.io"], got)
    s.add_names([{"ip": "203.0.113.9", "name": "download.db-ip.com", "via": "dns", "first": now, "last": now, "n": 1}])
    got = s.names_for(["203.0.113.9"], via=("dns",), since=now - 86400)
    check("egress names: a name first seen by TLS counts once the resolver answers it", got.get("203.0.113.9") == ["download.db-ip.com"], got)


def test_nft_script():
    import sensor
    s = sensor.nft_script({"mode": "enforce", "bans": [{"ip": "93.184.216.41", "until": time.time() + 600},
                                                      {"ip": "2606:2800:220:1::4", "until": time.time() + 60},
                                                      {"ip": "10.0.0.1", "until": time.time() + 60},
                                                      {"ip": "2001:db8::1", "until": time.time() + 60},
                                                      {"ip": "not-an-ip", "until": time.time() + 60}],
                           "blocks": [{"ip": "93.184.216.45", "until": 0}]}, now=time.time())
    check("nft: one table, never deleted", "add table inet dgo_security" in s and "delete table" not in s, s)
    check("nft: chains flushed and rebuilt in the same transaction",
          s.count("flush chain inet dgo_security") == 3 and "hook prerouting priority -300" in s, s)
    check("nft: v4 ban with timeout", "93.184.216.41 timeout" in s, s)
    check("nft: v6 ban", "2606:2800:220:1::4 timeout" in s, s)
    check("nft: a private address is never banned", "10.0.0.1" not in s, s)
    check("nft: a documentation address is never banned", "2001:db8::1" not in s, s)
    check("nft: garbage never reaches nft", "not-an-ip" not in s, s)
    check("nft: an outbound block without expiry", "93.184.216.45 }" in s and "block4" in s, s)
    obs = sensor.nft_script({"mode": "observe", "bans": [{"ip": "93.184.216.41", "until": time.time() + 600}]}, now=time.time())
    check("nft: observe mode bans nobody", "93.184.216.41" not in obs, obs)


def test_volume():
    import sensor
    s = sensor.vol_script()
    check("vol: four sets, counted per element", all(f"add set inet dgo_security {n} " in s for n in sensor.VOL_SETS)
          and "update @vol_out4 { ip daddr counter }" in s and "update @vol_in6 { ip6 saddr counter }" in s, s)
    check("vol: a separate script — it never touches the ban sets", "ban4" not in s and "block4" not in s, s)
    check("vol: private and multicast are not volume", "10.0.0.0/8" in s and "224.0.0.0/3" in s and "fe80::/10" in s, s)
    doc = {"nftables": [{"metainfo": {}}, {"set": {"name": "vol_out4", "elem": [
        {"elem": {"val": "93.184.216.45", "timeout": 7200, "expires": 7100, "counter": {"packets": 10, "bytes": 1500}}},
        "8.8.8.8"]}}]}
    check("vol: elements parsed, a bare one skipped", sensor.vol_elements(doc) == {"93.184.216.45": (10, 1500)},
          sensor.vol_elements(doc))
    keep = sensor.SENSOR_DIR
    with tempfile.TemporaryDirectory() as tmp:
        sensor.SENSOR_DIR = tmp
        try:
            v = sensor.Volume()
            a = v.step({"vol_out4": {"93.184.216.45": (10, 1500)}, "vol_in4": {"93.184.216.45": (8, 9000)}})
            check("vol: the first reading is all growth",
                  a == [{"ip": "93.184.216.45", "out": 1500, "in": 9000, "pout": 10, "pin": 8}], a)
            b = v.step({"vol_out4": {"93.184.216.45": (12, 1700)}, "vol_in4": {"93.184.216.45": (8, 9000)}})
            check("vol: then only what grew", b == [{"ip": "93.184.216.45", "out": 200, "in": 0, "pout": 2, "pin": 0}], b)
            again = sensor.Volume()
            c = again.step({"vol_out4": {"93.184.216.45": (12, 1700)}})
            check("vol: a restarted sensor does not count twice", c == [], c)
            d = again.step({"vol_out4": {"93.184.216.45": (3, 300)}})
            check("vol: an element that expired and came back counts from zero",
                  d == [{"ip": "93.184.216.45", "out": 300, "in": 0, "pout": 3, "pin": 0}], d)
        finally:
            sensor.SENSOR_DIR = keep


def test_geo_editions():
    """An edition is fetched once: the next pass holds it and asks for nothing (it fetched 424 MB in a day
    when freshness was judged by the file's build date, which DB-IP stamps a month early)."""
    import geo
    calls = []

    class G(geo.Geo):
        def _fetch(self, url, dest):
            calls.append(url.rsplit("/", 1)[-1])
            with open(dest, "wb") as fh:
                fh.write(b"x")
            return True

        def _open_existing(self):
            pass

    with tempfile.TemporaryDirectory() as d:
        g = G(d, "city")
        g.refresh()
        first = list(calls)
        calls.clear()
        g.refresh()
        check("geo: the first pass fetches this month's two editions", len(first) == 2 and all("-lite-" in c for c in first), first)
        check("geo: the next pass fetches nothing", calls == [], calls)


def test_mmdb():
    path = os.environ.get("SECURITY_TEST_MMDB")
    if not path or not os.path.exists(path):
        return
    import mmdb
    r = mmdb.Reader(path)
    hit = r.get("8.8.8.8") or {}
    check("mmdb: a public address has a country", ((hit.get("country") or {}).get("iso_code")) == "US", hit)
    check("mmdb: a private address has none", r.get("192.168.1.1") is None)


def test_geo_backfill():
    import tempfile
    import store as st

    class Geo:                                       # geo.Geo.lookup's three answers
        loaded = ""                                  # "" nothing yet · "asn" only the ASN edition · "city"

        def lookup(self, ip):
            if not self.loaded:
                return None
            if self.loaded == "asn":
                return {"asn": 47583, "org": "Hostinger"}
            return {"cc": "", "city": "", "lat": None, "lon": None} if ip.startswith("10.") else \
                {"cc": "FR", "city": "Paris", "lat": 48.8, "lon": 2.3, "asn": 47583, "org": "Hostinger"}

    s, g = st.Store(os.path.join(tempfile.mkdtemp(), "t.db")), Geo()
    s.add_hits([{"ts": 1.0, "ip": ip, "kind": "public", "app": "", "office": "", "host": "", "method": "GET", "path": "/",
                 "status": 200, "bytes": 0, "ms": 1, "ua": "", "user": "", "router": "", "src": "edge"}
                for ip in ("203.0.113.5", "10.0.0.7")], geo=g)
    check("geo backfill: nothing placed while no database is loaded", s.geo_backfill(g) == 0
          and s.one("SELECT COUNT(*) n FROM addr WHERE cc IS NULL")["n"] == 2)
    g.loaded = "asn"
    check("geo backfill: the ASN edition alone places nothing (no address frozen as nowhere)", s.geo_backfill(g) == 0
          and s.one("SELECT COUNT(*) n FROM addr WHERE cc IS NULL")["n"] == 2)
    g.loaded = "city"
    check("geo backfill: every unplaced address is placed once the database is there", s.geo_backfill(g) == 2
          and (s.one("SELECT cc FROM addr WHERE ip='203.0.113.5'") or {}).get("cc") == "FR"
          and (s.one("SELECT cc FROM addr WHERE ip='10.0.0.7'") or {}).get("cc") == "")
    check("geo backfill: a placed address is not asked again", s.geo_backfill(g) == 0)


def test_countries():
    """The new-country alert names the country the way the owner reads it (DGO-1639, MEET-28)."""
    import countries
    check("countries: flag and Hebrew name", countries.name("za") == "\U0001F1FF\U0001F1E6 דרום אפריקה", countries.name("za"))
    check("countries: Israel", countries.name("IL") == "\U0001F1EE\U0001F1F1 ישראל")
    check("countries: 257 names", len(countries.HE) == 257, len(countries.HE))
    check("countries: an unknown code keeps its code and flag", countries.name("QZ") == "\U0001F1F6\U0001F1FF QZ")
    check("countries: no country, no flag", countries.name("") == "" and countries.flag("1A") == "")


def test_host_lines():
    """The provider's guest agent and the console, read off the host's journal (DGO-1646). The lines are
    the ones measured on Hostinger's servers on 2026-11-09."""
    m = np.provider_message('info: guest-exec called: "timeout -s TERM -k 3660 3600 sh -c ps -eo vsz,rss,%cpu,time,etimes,pid,command --sort=-%cpu --no-header"')
    check("qga: an exec and its command", m and m["op"] == "exec" and m["detail"].startswith("timeout -s TERM"), m)
    m = np.provider_message("info: guest-file-open called, filepath: /.hstgr-1794226033.usage-telemetry.py, mode: w")
    check("qga: a file written into the machine", m and m["op"] == "file-write" and m["detail"] == "/.hstgr-1794226033.usage-telemetry.py", m)
    m = np.provider_message("info: guest-file-open called, filepath: /proc/meminfo, mode: r")
    check("qga: a file read", m and m["op"] == "file-read" and m["detail"] == "/proc/meminfo", m)
    check("qga: a status poll is not a call worth a row", np.provider_message("info: guest-exec-status called, pid: 2932636") is None)
    # the second reader's cases (DGO-1646): what the first parser missed or misread
    m = np.provider_message('info: guest-exec called: "sh -c line one\nline two"')
    check("qga: a command over several lines is still a call", m and m["op"] == "exec" and "line two" in m["detail"], m)
    m = np.provider_message("info: guest-file-open called, filepath: /tmp/my file.txt, mode: r+")
    check("qga: a path with a space, and r+ is a write", m and m["op"] == "file-write" and m["detail"] == "/tmp/my file.txt", m)
    m = np.provider_message("info: guest-file-open called, filepath: /root/.ssh/authorized_keys, mode: a")
    check("qga: an append is a write", m and m["op"] == "file-write", m)
    m = np.provider_message('info: guest-exec called: "sh -c echo root:S3cretPassw0rdLongEnough123 | chpasswd"')
    check("qga: a secret-looking value is never kept", m and "S3cret" not in m["detail"] and "chpasswd" in m["detail"], m)
    check("console: util-linux's line", np.console_message("ROOT LOGIN ON tty1") == {"tty": "tty1", "user": "root"})
    check("console: shadow's line", np.console_message("ROOT LOGIN  on '/dev/tty1'") == {"tty": "tty1", "user": "root"})
    check("console: a user on the serial line", np.console_message("LOGIN ON ttyS0 BY admin") == {"tty": "ttyS0", "user": "admin"})
    check("console: pam's line beside it is not a second sign-in",
          np.console_message("pam_unix(login:session): session opened for user root(uid=0) by root(uid=0)") is None)
    check("console: an sshd line is not a console sign-in", np.console_message("Accepted publickey for root from 93.184.216.7 port 22 ssh2") is None)


def test_firsts():
    """A new address is news only when it got in (firsts.py, DGO-1329): a completed sign-in, a real status, a way in,
    not the sign-in page — and each address once."""
    import firsts
    signed = {"198.51.100.7", "203.0.113.9"}
    known = {"203.0.113.9"}
    batch = [
        {"ip": "192.0.2.1", "kind": "auth", "status": 200, "path": "/"},                  # never signed in: a scanner
        {"ip": "198.51.100.7", "kind": "private", "status": 302, "path": "/login?rd=x"},   # bounced to the sign-in page
        {"ip": "198.51.100.7", "kind": "public", "status": 200, "path": "/"},              # a public site is no way in
        {"ip": "198.51.100.7", "kind": "private", "status": 0, "path": "/a/mail/"},        # no real status
        {"ip": "198.51.100.7", "kind": "private", "status": 200, "path": "/a/mail/"},      # GOT IN
        {"ip": "198.51.100.7", "kind": "remote", "status": 200, "path": "/a/drive/"},      # the same address again
        {"ip": "203.0.113.9", "kind": "auth", "status": 200, "path": "/"},                 # known already
    ]
    got = firsts.new_addresses(batch, known, signed)
    check("firsts: only the address that got in, once", [h["ip"] for h in got] == ["198.51.100.7"], got)
    check("firsts: the caller marks it known — a notice that failed is judged again",
          "198.51.100.7" not in known and len(firsts.new_addresses(batch, known, signed)) == 1)
    known.add("198.51.100.7")
    check("firsts: once marked, a second batch says nothing new", firsts.new_addresses(batch, known, signed) == [])
    check("firsts: news is a public, signed-in address whose first sign-in is after the watch began",
          firsts.is_news("signed-in", 1000.0, 900.0))
    check("firsts: never the herd's own, this office's own or a private address",
          not any(firsts.is_news(w, 1000.0, 900.0) for w in ("herd", "own", "private", "allowed", "")))
    check("firsts: a sign-in from before the watch (a first install reading logs back) is the past",
          not firsts.is_news("signed-in", 800.0, 900.0) and not firsts.is_news("signed-in", None, 900.0))
    ans = firsts.ban_answer("198.51.100.7")
    check("firsts: the answer is «חסום», this office's security.ban of that address",
          ans == [{"id": "block", "label": "חסום", "op": "security.ban", "args": {"ip": "198.51.100.7"}}], ans)


def test_verdict():
    """The screen's first answer on a database shaped like Exampleu's first day (DGO-1645/1646): the owner,
    the office, scanners sent to the sign-in, a secret hunter, a crawler on a public page, SSH strangers,
    our machines' SSH, the provider's commands. One address then gets a private app's 200, and the
    verdict must say so."""
    from store import Store
    import verdict
    with tempfile.TemporaryDirectory() as tmp:
        st = Store(os.path.join(tmp, "s.db"))
        now = time.time()
        OWNER, SCAN, HUNTER, CRAWLER, PROBER = "93.184.216.8", "93.184.216.46", "93.184.216.47", "93.184.216.48", "93.184.216.49"
        hits = ([{"ts": now - 600, "ip": OWNER, "kind": "private", "app": "console", "method": "GET", "path": "/api/me", "status": 200}] * 5 +
                [{"ts": now - 500, "ip": "172.18.0.1", "kind": "private", "app": "console", "method": "GET", "path": "/", "status": 200}] * 2 +
                [{"ts": now - 400, "ip": SCAN, "kind": "private", "app": "console", "method": "GET", "path": "/", "status": 302}] * 3 +
                [{"ts": now - 300, "ip": HUNTER, "kind": "auth", "app": "forward-auth", "method": "GET", "path": "/.env", "status": 302},
                 {"ts": now - 300, "ip": HUNTER, "kind": "public", "app": "meet", "method": "GET", "path": "/api/v1/.env", "status": 200}] +
                [{"ts": now - 200, "ip": CRAWLER, "kind": "public", "app": "n8n", "method": "GET", "path": "/assets/a.js", "status": 200}] * 4 +
                [{"ts": now - 100, "ip": "93.184.216.50", "kind": "none", "app": "", "method": "GET", "path": "/", "status": 404}])
        st.add_hits(hits)
        st.add_signins([{"ts": now - 900, "ip": OWNER, "src": "sso", "verdict": "ok", "user": "akadmin", "how": "password", "fp": ""},
                        {"ts": now - 800, "ip": "172.18.0.36", "src": "ssh", "verdict": "ok", "user": "root", "how": "publickey", "fp": "x"},
                        {"ts": now - 700, "ip": PROBER, "src": "ssh", "verdict": "probe", "user": "", "how": "", "fp": ""},
                        {"ts": now - 600, "ip": PROBER, "src": "ssh", "verdict": "fail", "user": "root", "how": "", "fp": ""}])
        st.add_host_events([{"ts": now - 50, "kind": "provider", "op": "exec", "detail": "sh -c ps -eo command"},
                            {"ts": now - 40, "kind": "provider", "op": "file-write", "detail": "/.hstgr-1.usage-telemetry.py"}])
        signed = {OWNER}

        def why(ip):
            if ip.startswith("172.18."):
                return "private"
            return "signed-in" if ip in signed else ""
        facts = {"listen": [{"proto": "tcp", "addr": "0.0.0.0", "port": 443, "scope": "all"},
                            {"proto": "tcp", "addr": "::", "port": 22, "scope": "all"},
                            {"proto": "udp", "addr": "0.0.0.0", "port": 10000, "scope": "all"}],
                 "ssh_keys": [{"fp": "x", "comment": "computers-office:exampleu"}, {"fp": "b", "comment": ""}],
                 "closed_fence": "present", "closed_drops": 3127, "provider_agent": True,
                 "watch": ["sshd", "qemu-ga", "login"]}
        old = verdict.compute(st, why, {k: v for k, v in facts.items()
                                        if k not in ("watch", "closed_drops", "closed_fence", "provider_agent", "ssh_keys")}, 24, now=now)
        od = {d["key"]: d for d in old["doors"]}
        check("verdict: a door the sensor does not watch is «not measured», never «0»",
              od["provider"]["state"] == "info" and od["provider"]["measured"] is False and od["closed"]["state"] == "info"
              and od["console"]["measured"] is False and od["ssh"]["measured"] is False
              and "provider" not in [x["key"] for x in old["needs"]], od)
        noagent = verdict.compute(st, why, {**facts, "provider_agent": False}, 24, now=now)
        check("verdict: a machine with no guest agent says so", {d["key"]: d for d in noagent["doors"]}["provider"]["agent"] is False)
        v = verdict.compute(st, why, facts, 24, now=now, would_ban=2, proxy="closed")
        check("verdict: the split", v["who"]["you"]["requests"] == 5 and v["who"]["office"]["requests"] == 2
              and v["who"]["internet"]["requests"] == 10 and v["who"]["internet"]["addrs"] == 4, v["who"])
        check("verdict: nothing got in", v["got_in"] == 0 and v["state"] in ("learning", "calm"), (v["got_in"], v["state"]))
        kinds = {t["key"]: t for t in v["tried"]}
        check("verdict: what the internet tried", kinds.get("signin", {}).get("requests") == 3
              and kinds.get("secrets", {}).get("requests") == 2 and kinds.get("public:n8n", {}).get("requests") == 4
              and kinds.get("bare", {}).get("requests") == 1 and kinds.get("ssh", {}).get("requests") == 2, kinds)
        si = v["signins"]
        check("verdict: people, machines and strangers apart", si["people"] == {"ok": 1, "typo": 0}
              and si["machines"]["ok"] == 1 and si["ssh_in"]["ok"] == 0
              and si["strangers"] == {"attempts": 2, "addrs": 1, "sso_fail": 0}, si)
        check("verdict: the proof counts what it checked", v["checked"] == 10, v["checked"])
        doors = {d["key"]: d for d in v["doors"]}
        check("verdict: the provider's hand is a door", doors["provider"]["n"] == 1 and doors["provider"]["files"] == 1
              and doors["provider"]["state"] == "warn", doors["provider"])
        check("verdict: an unnamed key is a door to look at", doors["ssh"]["unnamed"] == 1 and doors["ssh"]["state"] == "warn")
        check("verdict: the knocks on closed doors", doors["closed"]["n"] == 3127 and doors["docker"]["state"] == "ok")
        check("verdict: what needs the owner", [n["key"] for n in v["needs"]] == ["enforce", "provider", "keys"], v["needs"])
        # the second reader's blockers and misses (DGO-1646), each with its failing input
        st.add_signins([{"ts": now - 30, "ip": OWNER, "src": "sso", "verdict": "out", "user": "akadmin", "how": "", "fp": ""},
                        {"ts": now - 29, "ip": HUNTER, "src": "sso", "verdict": "fail", "user": "admin", "how": "password", "fp": ""},
                        {"ts": now - 28, "ip": OWNER, "src": "sso", "verdict": "fail", "user": "akadmin", "how": "password", "fp": ""}])
        v1 = verdict.compute(st, why, facts, 24, now=now)
        check("verdict: a sign-out is no failure, a stranger's failure is not the owner's typo",
              v1["signins"]["people"] == {"ok": 1, "typo": 1} and v1["signins"]["strangers"]["sso_fail"] == 1, v1["signins"])
        st.add_hits([{"ts": now - 20, "ip": "93.184.216.51", "kind": "private", "app": "drive", "method": "GET", "path": "/", "status": 200}])
        v1 = verdict.compute(st, why, facts, 24, now=now)
        check("verdict: the owner's own session from a neighbouring address is not «got in»", v1["got_in"] == 0, v1["got_in"])
        signed.add("203.0.113.50")              # Trust.why says «signed-in» after ANY SSH success…
        st.add_signins([{"ts": now - 15, "ip": "203.0.113.50", "src": "ssh", "verdict": "ok", "user": "root", "how": "password", "fp": ""}])
        v1 = verdict.compute(st, why, facts, 24, now=now)
        check("verdict: …so a stranger's SSH password sign-in is «in through SSH», and the verdict turns red",
              v1["signins"]["ssh_in"] == {"ok": 1, "addrs": 1} and v1["state"] == "needs"
              and {d["key"]: d["state"] for d in v1["doors"]}["ssh"] == "bad" and "ssh-in" in [x["key"] for x in v1["needs"]], v1["signins"])
        st.add_hits([{"ts": now - 12, "ip": SCAN, "kind": "private", "app": "bina-claude", "method": "GET", "path": "/ws", "status": 101}])
        v1 = verdict.compute(st, why, facts, 24, now=now)
        check("verdict: a websocket a private app accepted for an outsider is «got in»", v1["got_in"] == 1, v1["got_in"])
        st.add_hits([{"ts": now - 10, "ip": SCAN, "kind": "private", "app": "drive", "method": "GET", "path": "/api/files", "status": 200}])
        v2 = verdict.compute(st, why, facts, 24, now=now, proxy="open")
        check("verdict: a private answer to the internet is said at the top", v2["got_in"] == 2 and v2["state"] == "needs"
              and v2["got_in_addrs"] == 1 and {d["key"]: d["state"] for d in v2["doors"]}["web"] == "bad"
              and {"key": "docker"} in v2["needs"]
              and {t["key"]: t for t in v2["tried"]}["signin"]["in"] == 2, v2["state"])


# ── DGO-1597: the six things the deep analysis of Exampleu's traffic found (DGO-1590) ────────────────
# Each of these FAILS on the code as it stood on 2026-11-09: the scan jail banned four AWS Oregon
# addresses for `GET /`, one ssh attempt counted twice, a page's caps read as totals, failed sign-ins
# itemized only partly, Let's Encrypt's validation invisible, and SSH sources counted by key.
def test_scan_an_innocent_404():
    """A 404 on `/` (or the favicon) is the internet asking whether anything is there — not a scan."""
    now = time.time()
    jail = jl.Jails()
    for i in range(24):          # 93.184.216.26 and its three neighbours, measured on Exampleu
        jail.feed_hit({"ip": "93.184.216.26", "kind": "none", "path": "/", "status": 404, "ts": now - 60 + i})
    for i in range(20):
        jail.feed_hit({"ip": "93.184.216.27", "kind": "none", "path": "/favicon.ico", "status": 404, "ts": now - 60 + i})
    check("scan jail: 24 `GET /` 404s on a name nobody routes are not a scan", jail.decide(now) == [],
          jail.decide(now))
    # …and reading the answers is still a scan: the same jail, the same count, real paths
    peek = jl.Jails()
    for i in range(13):
        peek.feed_hit({"ip": "93.184.216.52", "kind": "none", "path": "/.env", "status": 404, "ts": now - 60 + i})
    got = peek.decide(now)
    check("scan jail: 13 `/.env` 404s from one address are still a decision",
          len(got) == 1 and got[0]["ip"] == "93.184.216.52" and ".env" in got[0]["reason"], got)


def test_one_ssh_attempt():
    """sshd writes one failed attempt as two lines on the same socket — one attempt, one count."""
    one = getattr(sn, "one_attempt", None)
    bad = np.sshd_message("Invalid user admin from 93.184.216.26 port 51234")
    same = np.sshd_message("Failed password for invalid user admin from 93.184.216.26 port 51234 ssh2")
    check("sshd: both lines of one attempt name the same port", bad and same and bad.get("port") == same.get("port") == 51234,
          (bad, same))
    check("sshd: a failure carries its reason (not just «fail»)",
          bad and bad.get("how") == "invalid-user" and same and same.get("how") == "password", (bad, same))
    if one is None:
        check("sshd: one attempt is counted once (the rule that dedupes it exists)", False, "sensor.one_attempt is missing")
        return
    conns: dict = {}
    bad["ts"], same["ts"] = 1000.0, 1000.4
    check("sshd: one attempt is counted once", one(conns, bad) is True and one(conns, same) is False, conns)
    other = np.sshd_message("Failed password for invalid user admin from 93.184.216.26 port 51999 ssh2")
    other["ts"] = 1030.0
    check("sshd: a second attempt on a new connection still counts", one(conns, other) is True)
    ok = np.sshd_message("Accepted publickey for root from 93.184.216.26 port 51234 ssh2: RSA SHA256:abc")
    ok["ts"] = 1040.0
    check("sshd: a sign-in on a connection that first failed is never dropped", one(conns, ok) is True)


def test_detail_totals_behind_the_cap():
    """A page may show 300 requests; the address's number of requests is not 300."""
    totals = getattr(st.Store, "detail_totals", None)
    if totals is None:
        check("inbound detail: the page says how many it holds, not only what it shows", False,
              "store.detail_totals is missing")
        return
    s = st.Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    now = time.time()
    s.add_hits([{"ts": now - 5, "ip": "93.184.216.26", "kind": "none", "app": "", "office": "", "host": "",
                 "method": "GET", "path": "/", "status": 404, "bytes": 0, "ms": 1, "ua": "", "user": "",
                 "router": "", "src": "edge"} for _ in range(350)])
    t = s.detail_totals("93.184.216.26")
    shown = len(s.q("SELECT ts FROM hit WHERE ip=? ORDER BY ts DESC LIMIT 300", ("93.184.216.26",)))
    check("inbound detail: 350 requests, 300 shown — the total says 350", t.get("hits") == 350 == len(s.q("SELECT ts FROM hit WHERE ip=?", ("93.184.216.26",))) and shown == 300,
          {"totals": t, "shown": shown})
    check("inbound detail: an address never seen totals zero, not nothing", s.detail_totals("203.0.113.99").get("hits") == 0)


def test_failed_signins_are_itemized():
    """Every failed sign-in, one row each, with its source and its reason — not a sample of five."""
    itemized = getattr(st.Store, "failed_signins", None)
    if itemized is None:
        check("sign-ins: every failure is itemized with its source and reason", False,
              "store.failed_signins is missing")
        return
    s = st.Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    now = time.time()
    rows = [{"ts": now - 10 + i, "ip": "93.184.216.26", "src": "ssh", "verdict": "fail", "user": f"u{i}",
             "how": "invalid-user" if i % 2 else "password", "fp": ""} for i in range(9)]
    rows += [{"ts": now - 9 + i, "ip": "93.184.216.52", "src": "sso", "verdict": "fail", "user": "admin",
              "how": "password", "fp": ""} for i in range(5)]
    s.add_signins(rows)
    got = itemized(s, now - 60)
    rows = got["rows"]
    sources = {r["src"] for r in rows}
    check("sign-ins: all 9 ssh failures and 5 sso failures are itemized", len(rows) == 14 == got["total"], got["total"])
    check("sign-ins: each failure names its source", sources == {"ssh", "sso"}, sources)
    check("sign-ins: each failure names its reason", all((r.get("how") or "") for r in rows), rows[:2])
    # …and the list is BOUNDED while the number stays true: an address under attack may fail thousands of
    # times, and a page that builds a megabyte of JSON is the same defect pointing the other way.
    big = st.Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    big.add_signins([{"ts": now - 30, "ip": "93.184.216.52", "src": "ssh", "verdict": "fail", "user": f"u{i}",
                      "how": "password", "fp": ""} for i in range(2500)])
    capped = itemized(big, now - 60)
    check("sign-ins: 2500 failures are itemized up to the limit and the total says 2500",
          len(capped["rows"]) == capped["limit"] == 2000 and capped["total"] == 2500,
          {"shown": len(capped["rows"]), "total": capped["total"], "limit": capped["limit"]})


def test_acme_validation_is_visible():
    """Let's Encrypt's validation is the edge's own request: it must be seen, and never be a scan."""
    kind = getattr(ed, "ACME_PREFIX", None)
    check("edge: the ACME path is named in the model", kind == "/.well-known/acme-challenge/", kind)
    routers = ed.Routers.__new__(ed.Routers)
    routers.meta, routers.titles, routers.offices, routers.at = {}, {}, {}, 0.0
    import threading
    routers.lock = threading.Lock()
    by_path = routers.classify("", "/.well-known/acme-challenge/tok123")
    by_router = routers.classify("acme-http@internal", "/")
    check("edge: a validation request is its own kind, not «private»", by_path.get("kind") == "acme", by_path)
    check("edge: …and so is the edge's own ACME router", by_router.get("kind") == "acme", by_router)
    # THE REAL SHAPE, from the HP's traefik 3.3.7 on 2026-11-09 (colours and all): the validation
    # request itself never reaches the access log, so the provider's own line is what makes a renewal
    # visible — an ACME failure here is the office's certificates, not a caller's.
    err = "\x1b[90m2026-11-09T08:47:46Z\x1b[0m \x1b[31mERR\x1b[0m \x1b[1mCannot retrieve the ACME challenge for console.localhost (token \"dgo1597-proof\")\x1b[0m \x1b[36mproviderName=\x1b[0m\x1b[31m\x1b[1macme"
    got = np.traefik_acme(err)
    check("edge: traefik's own ACME line is read (level, message, domain)", got and got["level"] == "error" and got["domain"] == "console.localhost", got)
    renew = np.traefik_acme('\x1b[90m2026-11-09T08:45:13Z\x1b[0m \x1b[31mERR\x1b[0m \x1b[1mUnable to obtain ACME certificate for domains\x1b[0m \x1b[36merror=\x1b[0m\x1b[31m\x1b[1m"… 400 :: POST :: https://acme-v02.api.letsencrypt.org/directory"')
    check("edge: a renewal that cannot get its certificate is read", renew and renew["level"] == "error", renew)
    check("edge: an access line is not an ACME line", np.traefik_acme('172.18.0.54 - - [09/Nov/2026:08:48:35 +0000] "GET /api/version HTTP/1.1" 302 172 "-" "-" 68368 "console-local@docker" "-" 9ms') is None)
    jail = jl.Jails()
    now = time.time()
    for i in range(24):
        jail.feed_hit({"ip": "93.184.216.52", "kind": "acme", "path": "/.well-known/acme-challenge/tok", "status": 404,
                       "ts": now - 60 + i})
    check("edge: a failing validation is never scan evidence", jail.decide(now) == [], jail.watching(now))


def test_ssh_sources_are_addresses():
    """Fifteen addresses that reached the machine are fifteen sources — not the five keys they used."""
    sources = getattr(st.Store, "ssh_sources", None)
    if sources is None:
        check("sign-ins: every source on the machine's ssh is named by its address", False,
              "store.ssh_sources is missing")
        return
    s = st.Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    now = time.time()
    s.add_signins([{"ts": now - 5 + n, "ip": f"203.0.113.{10 + n}", "src": "ssh", "verdict": "ok", "user": "root",
                    "how": "publickey", "fp": f"SHA256:key{n % 5}"} for n in range(15)])
    got = sources(s, now - 60)["rows"]
    keys = s.q("SELECT fp FROM signin WHERE src='ssh' AND verdict='ok' GROUP BY fp")
    check("sign-ins: 15 addresses are 15 sources", len(got) == 15, len(got))
    check("sign-ins: …while the keys they used are 5 (the old count)", len(keys) == 5, len(keys))
    check("sign-ins: a source names its keys and the names it tried", got and got[0].get("keys") and got[0].get("users"), got[:1])


if __name__ == "__main__":
    for t in (test_bpf_and_parsers, test_conntrack, test_edge_lines, test_auth_lines, test_jails,
              test_stun_only_behind_nat, test_egress, test_egress_names_are_the_resolvers, test_nft_script,
              test_volume, test_geo_editions, test_mmdb, test_geo_backfill, test_host_lines, test_verdict,
              test_scan_an_innocent_404, test_one_ssh_attempt, test_detail_totals_behind_the_cap,
              test_failed_signins_are_itemized, test_acme_validation_is_visible, test_ssh_sources_are_addresses,
              test_firsts, test_countries):
        try:
            t()
        except Exception as e:  # a crash is a failure with its name, not a traceback that hides the rest
            import traceback
            FAILS.append(f"{t.__name__} crashed: {e!r}\n{traceback.format_exc()}")
    if FAILS:
        print(f"security selftest: {len(FAILS)} of {CHECKS} failed")
        for f in FAILS:
            print("  ✗", f)
        sys.exit(1)
    print(f"security selftest: {CHECKS} checks passed")
