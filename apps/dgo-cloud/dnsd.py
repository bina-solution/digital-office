"""dgo-cloud.dnsd — the authoritative name server of the zone the client servers live in (DGO-1893).

WHY OUR OWN. digital-office.co.il's DNS is at InterNIC (sitesdepot), which has no API, and every client server needs
two names the moment it is bought: `<name>.<zone>` and `*.<name>.<zone>` → its address, plus the TXT record its
certificate's DNS-01 challenge asks for. So the zone is DELEGATED here once (two records at InterNIC:
`ns-cloud A <vps1>`, `cloud NS ns-cloud.digital-office.co.il`) and this answers from the database, instantly.

It answers only for its zone, and only what it knows: SOA and NS at the apex, A for the apex (the front's address),
A for a node's name and anything under it, TXT for `_acme-challenge.<name>`. Everything else under the zone is
NXDOMAIN, and a name outside it is REFUSED (this is not a resolver). Standard library only: the wire format is RFC
1035, name compression on answers, no EDNS (a reply is small).
"""
import os
import socket
import socketserver
import struct
import threading

QTYPE = {1: "A", 2: "NS", 6: "SOA", 16: "TXT", 28: "AAAA", 257: "CAA", 255: "ANY"}
TTL = 60


def _name(labels):
    out = b""
    for l in labels:
        b = l.encode("idna") if not l.isascii() else l.encode()
        out += bytes([len(b)]) + b
    return out + b"\x00"


def parse_question(msg):
    """→ (id, flags, labels, qtype, qclass, end) or None."""
    if len(msg) < 12:
        return None
    qid, flags, qd = struct.unpack("!HHH", msg[:6])
    if qd != 1:
        return None
    i, labels = 12, []
    while True:
        if i >= len(msg):
            return None
        n = msg[i]
        if n == 0:
            i += 1
            break
        if n & 0xC0 or i + 1 + n > len(msg):
            return None
        labels.append(msg[i + 1:i + 1 + n].decode("ascii", "replace"))
        i += 1 + n
    if i + 4 > len(msg):
        return None
    qtype, qclass = struct.unpack("!HH", msg[i:i + 4])
    return qid, flags, labels, qtype, qclass, i + 4


class Zone:
    def __init__(self, store, zone=None, apex_ip=None, ns=None):
        self.s = store
        self.zone = (zone or os.environ.get("DGOCLOUD_ZONE", "cloud.digital-office.co.il")).strip(".").lower()
        self.apex_ip = apex_ip or os.environ.get("DGOCLOUD_ZONE_IP", "")
        parent = self.zone.split(".", 1)[1] if "." in self.zone else self.zone
        self.ns = (ns or os.environ.get("DGOCLOUD_NS") or f"ns-cloud.{parent}").strip(".").lower()
        self.serial = 2026111501

    def lookup(self, qname, qtype):
        """→ (rcode, [(type, rdata-bytes)], authority-SOA?) for one question."""
        q = qname.strip(".").lower()
        if q != self.zone and not q.endswith("." + self.zone):
            return 5, [], False                                            # REFUSED: not ours
        rel = q[:-len(self.zone)].rstrip(".")
        recs = []
        if rel == "":
            if qtype in ("SOA", "ANY"):
                recs.append(("SOA", self._soa()))
            if qtype in ("NS", "ANY"):
                recs.append(("NS", _name(self.ns.split("."))))
            if qtype in ("A", "ANY") and self.apex_ip:
                recs.append(("A", socket.inet_aton(self.apex_ip)))
            return 0, recs, not recs
        parts = rel.split(".")
        if parts[0] == "_acme-challenge" and len(parts) == 2:
            vals = [r["value"] for r in self.s.all("SELECT value FROM acme WHERE fqdn=? ORDER BY id DESC LIMIT 4", q)]
            if not self._node(parts[1]):
                return 3, [], True
            if qtype in ("TXT", "ANY"):
                # the length byte counts BYTES (an ACME value is ASCII; anything else is measured, not assumed)
                recs = [("TXT", bytes([len(b)]) + b) for b in (v.encode() for v in vals) if len(b) < 256]
            return 0, recs, not recs
        if rel == "www" and self.apex_ip:
            return 0, ([("A", socket.inet_aton(self.apex_ip))] if qtype in ("A", "ANY") else []), qtype not in ("A", "ANY")
        node = self._node(parts[-1])           # <name> or anything.<name>
        if not node:
            return 3, [], True
        if qtype in ("A", "ANY") and node["ip"]:
            recs.append(("A", socket.inet_aton(node["ip"])))
        return 0, recs, not recs

    def _node(self, label):
        return self.s.one("SELECT name, ip FROM nodes WHERE name=? AND ip<>'' AND state NOT IN "
                          "('destroyed','destroying','ordering')", label)

    def _soa(self):
        return (_name(self.ns.split(".")) + _name(["hostmaster"] + self.zone.split(".")) +
                struct.pack("!IIIII", self.serial, 3600, 600, 1209600, TTL))

    def answer(self, msg, udp=False):
        q = parse_question(msg)
        if not q:
            return None
        qid, flags, labels, qtype_n, qclass, end = q
        if flags & 0x8000 or (flags >> 11) & 0xF:
            return None          # a response (QR=1) or not a plain QUERY: never answered, so two servers cannot ping-pong
        qtype = QTYPE.get(qtype_n, str(qtype_n))
        if qclass not in (1, 255):
            rcode, recs, soa = 5, [], False
        else:
            try:
                rcode, recs, soa = self.lookup(".".join(labels), qtype)
            except Exception:
                rcode, recs, soa = 2, [], False                              # SERVFAIL, never a crash
        rd = flags & 0x0100
        tcode = {v: k for k, v in QTYPE.items()}
        question = msg[12:end]
        answers = [b"\xc0\x0c" + struct.pack("!HHIH", tcode[typ], 1, TTL, len(rdata)) + rdata for typ, rdata in recs]
        auth = b""
        if soa:
            soa_r = self._soa()
            auth = _name(self.zone.split(".")) + struct.pack("!HHIH", 6, 1, TTL, len(soa_r)) + soa_r
        tc = 0
        if udp and 12 + len(question) + sum(map(len, answers)) + len(auth) > 512:
            # over UDP's 512 bytes: say so (TC) and send what fits; the resolver asks again over TCP
            tc, fit, size = 0x0200, [], 12 + len(question)
            for a in answers:
                if size + len(a) > 512:
                    break
                fit.append(a)
                size += len(a)
            answers, auth = fit, b""
        hdr = struct.pack("!HHHHHH", qid, 0x8000 | 0x0400 | tc | rd | rcode, 1, len(answers), 1 if auth else 0, 0)
        return hdr + question + b"".join(answers) + auth


def serve(zone, port, log=print):
    """UDP and TCP on `port`, in daemon threads. → the two servers."""
    class U(socketserver.BaseRequestHandler):
        def handle(self):
            data, sock = self.request
            r = zone.answer(data, udp=True)
            if r:
                sock.sendto(r, self.client_address)

    class T(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(10)
            try:
                ln = struct.unpack("!H", self.request.recv(2))[0]
                data = b""
                while len(data) < ln:
                    chunk = self.request.recv(ln - len(data))
                    if not chunk:
                        return
                    data += chunk
                r = zone.answer(data)
                if r:
                    self.request.sendall(struct.pack("!H", len(r)) + r)
            except (OSError, struct.error):
                pass

    class UServer(socketserver.UDPServer):
        # ONE thread for UDP: a flood on a public :53 queues, it never spawns a thread (and a connection) per packet
        allow_reuse_address = True

    class TServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    servers = []
    for cls, h in ((UServer, U), (TServer, T)):
        srv = cls(("0.0.0.0", port), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
    log(f"dns: authoritative for {zone.zone} on :{port} (udp+tcp), NS {zone.ns}")
    return servers
