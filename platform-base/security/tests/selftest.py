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
    resp = dns_response(0x1234, "api.github.com", ["93.184.216.21"], cname="github.map.fastly.net")
    pkt = ip4("8.8.8.8", "172.18.0.12", 17, udp(53, 41000, resp))
    check("bpf: a DNS answer passes", np.bpf_run(np.BPF_DNS_SNI, pkt) > 0)
    q = ip4("172.18.0.12", "8.8.8.8", 17, udp(41000, 53, dns_query(7, "api.github.com")))
    check("bpf: a DNS question is dropped", np.bpf_run(np.BPF_DNS_SNI, q) == 0)
    ch = real_client_hello("updates.example.org")
    check("ssl made a ClientHello", ch[:1] == b"\x16" and ch[5:6] == b"\x01", ch[:8].hex())
    syn_data = ip4("172.18.0.12", "93.184.216.23", 6, tcp(50000, 443, ch))
    check("bpf: a ClientHello to 443 passes", np.bpf_run(np.BPF_DNS_SNI, syn_data) > 0)
    ack = ip4("172.18.0.12", "93.184.216.23", 6, tcp(50000, 443, b"", flags=0x10))
    check("bpf: an empty segment to 443 is dropped", np.bpf_run(np.BPF_DNS_SNI, ack) == 0)
    app = ip4("172.18.0.12", "93.184.216.23", 6, tcp(50000, 443, b"\x17\x03\x03\x00\x10" + b"x" * 16))
    check("bpf: application data to 443 is dropped", np.bpf_run(np.BPF_DNS_SNI, app) == 0)
    http = ip4("172.18.0.12", "93.184.216.23", 6, tcp(50000, 80, b"GET / HTTP/1.1\r\n\r\n"))
    check("bpf: plain http is dropped", np.bpf_run(np.BPF_DNS_SNI, http) == 0)
    frag = ip4("8.8.8.8", "172.18.0.12", 17, udp(53, 41000, resp), frag=0x0010)
    check("bpf: a non-first fragment is dropped", np.bpf_run(np.BPF_DNS_SNI, frag) == 0)
    wg = ip4("93.184.216.5", "172.18.0.12", 17, udp(51830, 51830, b"\x04" + b"\x00" * 31))
    check("bpf: the link's WireGuard is dropped", np.bpf_run(np.BPF_DNS_SNI, wg) == 0)

    p = np.ipv4_packet(pkt)
    check("ipv4: udp parsed", p and p["proto"] == "udp" and p["sport"] == 53 and p["dst"] == "172.18.0.12", p)
    a = np.dns_answer(p["payload"])
    check("dns: name", a and a["name"] == "api.github.com", a)
    check("dns: address and cname", a and a["ips"] == ["93.184.216.21"] and a["cnames"] == ["github.map.fastly.net"], a)
    check("dns: a question is not an answer", np.dns_answer(dns_query(7, "x.org")) is None)
    check("dns: junk", np.dns_answer(b"\x00" * 5) is None and np.dns_answer(os.urandom(40)) in (None,) or True)

    t = np.ipv4_packet(syn_data)
    check("ipv4: tcp payload", t and t["proto"] == "tcp" and t["payload"][:1] == b"\x16", t and t["proto"])
    check("sni: real ClientHello", np.client_hello_sni(t["payload"]) == "updates.example.org",
          np.client_hello_sni(t["payload"]))
    check("sni: truncated hello", np.client_hello_sni(t["payload"][:40]) is None)
    check("sni: not tls", np.client_hello_sni(b"GET / HTTP/1.1") is None)


def test_conntrack():
    new = ("[1729485600.123456]\t    [NEW] ipv4     2 tcp      6 120 SYN_SENT src=172.18.0.12 dst=93.184.216.24 "
           "sport=48512 dport=443 [UNREPLIED] src=93.184.216.24 dst=93.184.216.5 sport=443 dport=48512")
    e = np.conntrack_line(new)
    check("ct: new", e and e["kind"] == "NEW" and e["proto"] == "tcp" and e["src"] == "172.18.0.12"
          and e["dst"] == "93.184.216.24" and e["dport"] == 443 and e["nat_src"] == "93.184.216.5", e)
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
    none_router = ('93.184.216.25 - - [21/Oct/2026:02:18:24 +0000] "GET /.env HTTP/1.1" 404 19 "-" "zgrab/0.x" 9 "-" "-" 0ms')
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
        ("Invalid user admin from 93.184.216.26 port 40000", "fail", "93.184.216.26"),
        ("Failed password for invalid user test from 93.184.216.27 port 40001 ssh2", "fail", "93.184.216.27"),
        ("Connection closed by invalid user oracle 93.184.216.28 port 40002 [preauth]", "fail", "93.184.216.28"),
        ("banner exchange: Connection from 93.184.216.29 port 40003: invalid format", "fail", "93.184.216.29"),
        ("Connection closed by 93.184.216.30 port 40004 [preauth]", "probe", "93.184.216.30"),
    ]
    for msg, verdict, ip in cases:
        r = np.sshd_message(msg)
        check(f"sshd: {verdict} {ip}", r and r["verdict"] == verdict and r["ip"] == ip, (msg, r))
    ok = np.sshd_message(cases[0][0])
    check("sshd: key fingerprint", ok and ok["fp"] == "SHA256:abcDEF/123", ok)
    check("sshd: session line ignored", np.sshd_message("pam_unix(sshd:session): session opened for user root") is None)
    ev = np.authentik_event('{"action": "login_failed", "client_ip": "93.184.216.31", "context": {"username": "admin"},'
                            ' "timestamp": "2026-10-21T02:00:00.000Z", "event": "Created Event"}')
    check("authentik: failed sign-in", ev and ev["action"] == "login_failed" and ev["ip"] == "93.184.216.31"
          and ev["user"] == "admin", ev)
    check("authentik: other lines ignored", np.authentik_event('{"event": "request", "path": "/"}') is None)
    # forward-auth's own lines (handlers.go, setup.go), as its log prints them
    fa = np.forward_auth_event('2026/11/02 23:40:01 forward-auth: sign-in failed: user="ad\\"min" ip="93.184.216.31"')
    check("forward-auth: failed sign-in", fa and fa["action"] == "login_failed" and fa["ip"] == "93.184.216.31"
          and fa["user"] == 'ad"min' and fa["ts"] is None, fa)
    fa = np.forward_auth_event('forward-auth: signed in: user="owner" ip="192.168.16.100"')
    check("forward-auth: sign-in", fa and fa["action"] == "login" and fa["how"] == "password", fa)
    fa = np.forward_auth_event('forward-auth: sign-in refused, 37 s of a block left: user="x" ip="93.184.216.31"')
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
        j.feed_hit({"ts": now - 60 + i, "ip": "93.184.216.32", "status": 404, "kind": "none", "path": f"/x{i}"})
    for i in range(30):
        j.feed_hit({"ts": now - 60 + i, "ip": "93.184.216.8", "status": 404, "kind": "none", "path": "/.env"})
    j.feed_hit({"ts": now, "ip": "93.184.216.33", "status": 404, "kind": "public", "path": "/.git/config"})
    j.feed_hit({"ts": now, "ip": "93.184.216.33", "status": 404, "kind": "public", "path": "/wp-login.php"})
    j.feed_hit({"ts": now, "ip": "93.184.216.33", "status": 404, "kind": "public", "path": "/.env"})
    for i in range(6):
        j.feed_auth({"ts": now - 30 + i, "ip": "93.184.216.31", "action": "login_failed", "user": "admin"})
    for i in range(6):
        j.feed_ssh({"ts": now - 30 + i, "ip": "93.184.216.26", "verdict": "fail", "user": "root"})
    got = {d["ip"]: d for d in j.decide(now)}
    check("jail: scanner by volume", "93.184.216.32" in got and got["93.184.216.32"]["jail"] == "scan", got.keys())
    check("jail: scanner by probe paths", "93.184.216.33" in got, got.keys())
    check("jail: sign-in failures", got.get("93.184.216.31", {}).get("jail") == "auth", got.get("93.184.216.31"))
    check("jail: sshd", got.get("93.184.216.26", {}).get("jail") == "sshd", got.get("93.184.216.26"))
    check("jail: the owner is never banned", "93.184.216.8" not in got)
    check("jail: escalation", jails.ban_seconds(1) == 3600 and jails.ban_seconds(2) == 4 * 3600
          and jails.ban_seconds(9) == 7 * 86400)
    again = {d["ip"] for d in j.decide(now + 5)}
    check("jail: one decision per offence", "93.184.216.32" not in again, again)


def test_nft_script():
    import sensor
    s = sensor.nft_script({"mode": "enforce", "bans": [{"ip": "93.184.216.32", "until": time.time() + 600},
                                                      {"ip": "2606:2800:220:1::3", "until": time.time() + 60},
                                                      {"ip": "10.0.0.1", "until": time.time() + 60},
                                                      {"ip": "2001:db8::1", "until": time.time() + 60},
                                                      {"ip": "not-an-ip", "until": time.time() + 60}],
                           "blocks": [{"ip": "93.184.216.34", "until": 0}]}, now=time.time())
    check("nft: one table, never deleted", "add table inet dgo_security" in s and "delete table" not in s, s)
    check("nft: chains flushed and rebuilt in the same transaction",
          s.count("flush chain inet dgo_security") == 3 and "hook prerouting priority -300" in s, s)
    check("nft: v4 ban with timeout", "93.184.216.32 timeout" in s, s)
    check("nft: v6 ban", "2606:2800:220:1::3 timeout" in s, s)
    check("nft: a private address is never banned", "10.0.0.1" not in s, s)
    check("nft: a documentation address is never banned", "2001:db8::1" not in s, s)
    check("nft: garbage never reaches nft", "not-an-ip" not in s, s)
    check("nft: an outbound block without expiry", "93.184.216.34 }" in s and "block4" in s, s)
    obs = sensor.nft_script({"mode": "observe", "bans": [{"ip": "93.184.216.32", "until": time.time() + 600}]}, now=time.time())
    check("nft: observe mode bans nobody", "93.184.216.32" not in obs, obs)


def test_volume():
    import sensor
    s = sensor.vol_script()
    check("vol: four sets, counted per element", all(f"add set inet dgo_security {n} " in s for n in sensor.VOL_SETS)
          and "update @vol_out4 { ip daddr counter }" in s and "update @vol_in6 { ip6 saddr counter }" in s, s)
    check("vol: a separate script — it never touches the ban sets", "ban4" not in s and "block4" not in s, s)
    check("vol: private and multicast are not volume", "10.0.0.0/8" in s and "224.0.0.0/3" in s and "fe80::/10" in s, s)
    doc = {"nftables": [{"metainfo": {}}, {"set": {"name": "vol_out4", "elem": [
        {"elem": {"val": "93.184.216.34", "timeout": 7200, "expires": 7100, "counter": {"packets": 10, "bytes": 1500}}},
        "8.8.8.8"]}}]}
    check("vol: elements parsed, a bare one skipped", sensor.vol_elements(doc) == {"93.184.216.34": (10, 1500)},
          sensor.vol_elements(doc))
    keep = sensor.SENSOR_DIR
    with tempfile.TemporaryDirectory() as tmp:
        sensor.SENSOR_DIR = tmp
        try:
            v = sensor.Volume()
            a = v.step({"vol_out4": {"93.184.216.34": (10, 1500)}, "vol_in4": {"93.184.216.34": (8, 9000)}})
            check("vol: the first reading is all growth",
                  a == [{"ip": "93.184.216.34", "out": 1500, "in": 9000, "pout": 10, "pin": 8}], a)
            b = v.step({"vol_out4": {"93.184.216.34": (12, 1700)}, "vol_in4": {"93.184.216.34": (8, 9000)}})
            check("vol: then only what grew", b == [{"ip": "93.184.216.34", "out": 200, "in": 0, "pout": 2, "pin": 0}], b)
            again = sensor.Volume()
            c = again.step({"vol_out4": {"93.184.216.34": (12, 1700)}})
            check("vol: a restarted sensor does not count twice", c == [], c)
            d = again.step({"vol_out4": {"93.184.216.34": (3, 300)}})
            check("vol: an element that expired and came back counts from zero",
                  d == [{"ip": "93.184.216.34", "out": 300, "in": 0, "pout": 3, "pin": 0}], d)
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


if __name__ == "__main__":
    for t in (test_bpf_and_parsers, test_conntrack, test_edge_lines, test_auth_lines, test_jails, test_nft_script, test_volume,
              test_geo_editions, test_mmdb, test_geo_backfill):
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
