"""domains.dnsq — a tiny DNS client, because the office must be able to ask THE WORLD.

Two reasons this exists instead of a library, and the second is the important one:

  * the question "what does this domain actually resolve to" has to be answerable for a domain whose
    provider we cannot reach, have no API for, or have not connected — and a domain's delegation is
    public information;
  * a provider's API tells you what it BELIEVES. A record can be saved in Cloudflare and never reach
    a visitor, because the registrar still points its nameservers elsewhere. The only way to know is
    to ask a resolver that is not the provider's — so the app asks 1.1.1.1 and compares. That
    comparison ("the panel says X, the world says Y") is the single most useful thing a domains
    screen can show, and it needs its own resolver, not a client library pointed at the same API.

Deliberately small: A, AAAA, CNAME, MX, TXT, NS over UDP with a TCP retry on truncation. No DNSSEC
validation, no caching, no zones — those are a resolver's job and this is not one.
"""
from __future__ import annotations

import random
import socket
import struct

DEFAULT_RESOLVER = ("1.1.1.1", 53)
QTYPES = {"A": 1, "NS": 2, "CNAME": 5, "MX": 15, "TXT": 16, "AAAA": 28, "CAA": 257, "SOA": 6}


class DnsError(Exception):
    pass


def _encode_name(name: str) -> bytes:
    out = b""
    for label in name.strip(".").split("."):
        if not label:
            continue
        b = label.encode("idna") if any(ord(c) > 127 for c in label) else label.encode()
        out += bytes([len(b)]) + b
    return out + b"\x00"


def _decode_name(data: bytes, pos: int) -> tuple[str, int]:
    labels: list[str] = []
    jumps = 0
    while True:
        if pos >= len(data):
            raise DnsError("truncated name")
        length = data[pos]
        if length == 0:
            pos += 1
            break
        if length & 0xC0 == 0xC0:                        # a compression pointer
            if pos + 1 >= len(data):
                raise DnsError("truncated pointer")
            ptr = ((length & 0x3F) << 8) | data[pos + 1]
            jumps += 1
            if jumps > 10:
                raise DnsError("pointer loop")
            sub, _ = _decode_name(data, ptr)
            labels.append(sub)
            pos += 2
            break
        pos += 1
        labels.append(data[pos:pos + length].decode("utf-8", "replace"))
        pos += length
    return ".".join(labels), pos


def _rdata(data: bytes, rtype: int, rdlength: int, pos: int) -> tuple[str, int]:
    end = pos + rdlength
    if rtype == 1 and rdlength == 4:
        return ".".join(str(b) for b in data[pos:end]), end
    if rtype == 28 and rdlength == 16:
        groups = [data[pos + i:pos + i + 2].hex() for i in range(0, 16, 2)]
        return ":".join(groups), end
    if rtype in (2, 5):
        name, _ = _decode_name(data, pos)
        return name, end
    if rtype == 15:
        pref = struct.unpack("!H", data[pos:pos + 2])[0]
        name, _ = _decode_name(data, pos + 2)
        return f"{pref} {name}", end
    if rtype == 16:
        parts, p = [], pos
        while p < end:
            ln = data[p]
            parts.append(data[p + 1:p + 1 + ln].decode("utf-8", "replace"))
            p += 1 + ln
        return "".join(parts), end
    if rtype == 257:
        flags = data[pos]
        tag_len = data[pos + 1]
        tag = data[pos + 2:pos + 2 + tag_len].decode("ascii", "replace")
        value = data[pos + 2 + tag_len:end].decode("utf-8", "replace")
        return f"{flags} {tag} \"{value}\"", end
    return data[pos:end].hex(), end


def query(name: str, rtype: str = "A", resolver: tuple[str, int] = DEFAULT_RESOLVER,
          timeout: float = 5.0) -> dict:
    """One question, one answer. Returns `{name, type, answers: [...], rcode, truncated}` — an empty
    answer list and `rcode: 3` (NXDOMAIN) is a legitimate, meaningful reply, not an error."""
    rtype = rtype.upper()
    if rtype not in QTYPES:
        raise DnsError(f"סוג רשומה לא נתמך: {rtype}")
    qid = random.randint(0, 0xFFFF)
    header = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = _encode_name(name) + struct.pack("!HH", QTYPES[rtype], 1)
    packet = header + question

    def ask(tcp: bool) -> bytes:
        if tcp:
            with socket.create_connection(resolver, timeout=timeout) as s:
                s.sendall(struct.pack("!H", len(packet)) + packet)
                head = s.recv(2)
                if len(head) < 2:
                    raise DnsError("תשובה קצרה מדי")
                (length,) = struct.unpack("!H", head)
                buf = b""
                while len(buf) < length:
                    chunk = s.recv(length - len(buf))
                    if not chunk:
                        break
                    buf += chunk
                return buf
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(packet, resolver)
            data, _ = s.recvfrom(4096)
            return data

    try:
        data = ask(False)
        flags = struct.unpack("!H", data[2:4])[0]
        if flags & 0x0200:                                # TC: truncated → ask again over TCP
            data = ask(True)
    except (OSError, struct.error) as e:
        raise DnsError("שאילתת DNS נכשלה") from e

    try:
        _, rflags, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
    except struct.error as e:
        raise DnsError("תשובת DNS פגומה") from e
    pos = 12
    for _ in range(qd):
        _, pos = _decode_name(data, pos)
        pos += 4
    answers = []
    for section in range(an + ns + ar):
        try:
            owner, pos = _decode_name(data, pos)
            rtype_n, _rclass, rttl, rdlength = struct.unpack("!HHIH", data[pos:pos + 10])
            pos += 10
            value, pos = _rdata(data, rtype_n, rdlength, pos)
        except (struct.error, DnsError):
            break
        if section < an:
            answers.append({"owner": owner, "type": _type_name(rtype_n), "value": value,
                            "ttl": rttl})
    return {"name": name, "type": rtype, "rcode": rflags & 0x000F, "answers": answers,
            "resolver": f"{resolver[0]}:{resolver[1]}"}


def _type_name(n: int) -> str:
    for k, v in QTYPES.items():
        if v == n:
            return k
    return str(n)


def snapshot(domain: str, resolver: tuple[str, int] = DEFAULT_RESOLVER) -> dict:
    """What the world currently answers for a domain: A/AAAA/CNAME/MX/TXT/NS, best-effort.

    Each type is asked separately and a failure of one does not lose the others: a domain whose MX is
    missing is exactly the domain an owner needs to see, and an NXDOMAIN on the A record must not
    blank the NS answer that explains why.
    """
    out: dict = {"domain": domain, "resolver": f"{resolver[0]}:{resolver[1]}", "records": {},
                 "errors": {}}
    for t in ("NS", "A", "AAAA", "CNAME", "MX", "TXT"):
        try:
            res = query(domain, t, resolver)
            out["records"][t] = [a["value"].rstrip(".") if t in ("CNAME", "NS", "MX") else a["value"]
                                 for a in res["answers"] if a["type"] == t]
            if t == "MX":
                out["records"][t] = [" ".join(a["value"].split()[:2]).rstrip(".")
                                     for a in res["answers"] if a["type"] == "MX"]
            out["rcode"] = res["rcode"]
        except DnsError as e:
            out["errors"][t] = str(e)
            out["records"][t] = []
    return out


#: The resolvers a careful operator checks, and why more than one: "the world" is not one place.
#: A record that is correct at the authoritative nameservers can still be wrong for half the planet
#: while caches expire, and a single resolver's answer cannot tell you which of those two you are
#: looking at. Cloudflare's own guidance and every propagation checker do it this way.
PUBLIC_RESOLVERS = [("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53)]


def snapshot_multi(domain: str, resolvers: list[tuple[str, int]] | None = None,
                   types: tuple[str, ...] = ("A", "AAAA", "CNAME", "MX", "TXT", "NS")) -> dict:
    """What EVERY resolver answers, plus whether they agree.

    The disagreement is the finding: identical answers everywhere means the change has landed;
    one resolver still serving the old value is a cache waiting out its TTL, and the number that
    tells the owner how long to wait is the TTL we just read — not a guess.
    """
    resolvers = resolvers or PUBLIC_RESOLVERS
    per: dict[str, dict] = {}
    for host, port in resolvers:
        key = f"{host}"
        row: dict = {"resolver": key, "records": {}, "ttls": {}, "error": None, "ttl": None}
        for t in types:
            try:
                res = query(domain, t, (host, port), timeout=4)
                vals = [_clean(a["value"], t) for a in res["answers"] if a["type"] == t]
                row["records"][t] = sorted(vals)
                # TTL per answer, keyed by value — this is what turns "it has not propagated yet"
                # into "wait 300 more seconds", which is the only actionable version of that fact.
                row["ttls"][t] = {_clean(a["value"], t): a.get("ttl")
                                  for a in res["answers"] if a["type"] == t}
            except DnsError as e:
                row["records"][t] = []
                row["ttls"][t] = {}
                row["error"] = row["error"] or str(e)
        row["ttl"] = min([v for t in row["ttls"].values() for v in t.values() if v is not None],
                         default=None)
        per[key] = row
    agree: dict[str, dict] = {}
    for t in types:
        answers = {k: tuple(v["records"].get(t) or []) for k, v in per.items()}
        distinct = {a for a in answers.values() if a}
        agree[t] = {"values": sorted({v for a in answers.values() for v in a}),
                    "consistent": len(distinct) <= 1 and bool(distinct),
                    "by_resolver": {k: list(v) for k, v in answers.items()},
                    "ttls": {k: (v.get("ttls", {}).get(t) or {}) for k, v in per.items()}}
    return {"domain": domain, "resolvers": [r[0] for r in resolvers], "per_resolver": per,
            "agreement": agree,
            "consistent": all(a["consistent"] for a in agree.values() if a["values"]),
            "checked_at": int(__import__("time").time())}


def authoritative(domain: str, types: tuple[str, ...] = ("A", "AAAA", "CNAME", "MX", "TXT", "NS"),
                  resolver: tuple[str, int] = DEFAULT_RESOLVER, timeout: float = 4.0) -> dict:
    """What the zone's OWN nameservers answer — the source of truth, asked directly.

    This is the first half of every honest propagation view, and the half almost every panel skips:
    a public resolver's answer can be stale for as long as a TTL, so a change that HAS landed looks
    exactly like a change that has not, until you ask the authority. Only after the authority agrees
    does a resolver's disagreement mean "cache", and only then is "wait N seconds" a real number.

    `nameservers` comes from the delegation (asked of a public resolver), and each is then queried by
    IP, so a nameserver whose own A record is not resolvable is reported as such instead of silently
    returning nothing.
    """
    out: dict = {"domain": domain, "nameservers": [], "apex_ns": [], "per_ns": {}, "records": {},
                 "ttls": {}, "ip": {}, "errors": {}, "asked": f"{resolver[0]}:{resolver[1]}",
                 "checked_at": int(__import__("time").time())}
    try:
        ns_ans = query(domain, "NS", resolver, timeout=timeout)
        out["nameservers"] = sorted({_clean(a["value"], "NS") for a in ns_ans["answers"]
                                     if a["type"] == "NS"})
    except DnsError as e:
        out["errors"]["NS"] = str(e)
        return out
    for ns in out["nameservers"]:
        try:
            ip = query(ns, "A", resolver, timeout=timeout)
            addr = next((a["value"] for a in ip["answers"] if a["type"] == "A"), None)
        except DnsError:
            addr = None
        if not addr:
            out["errors"][ns] = "לא ניתן למצוא את כתובת ה-IP של שרת השמות"
            continue
        out["ip"][ns] = addr
        row: dict = {}
        ttls: dict = {}
        for t in types:
            try:
                res = query(domain, t, (addr, 53), timeout=timeout)
            except DnsError as e:
                row[t] = []
                out["errors"][f"{ns}/{t}"] = str(e)
                continue
            hits = [_clean(a["value"], t) for a in res["answers"] if a["type"] == t]
            row[t] = sorted(set(hits))
            ttls[t] = {_clean(a["value"], t): a.get("ttl")
                       for a in res["answers"] if a["type"] == t}
            for v in row[t]:
                out["records"].setdefault(t, [])
                if v not in out["records"][t]:
                    out["records"][t].append(v)
                out["ttls"].setdefault(t, {})[v] = ttls[t].get(v)
        # The APEX NS RRset, asked at the zone itself — a different thing from the delegation, and
        # the mismatch between the two is the most common real outage: the registrar points at
        # ns1/ns2 while the zone believes it lives somewhere else. The child answers its own name.
        try:
            res = query(domain, "NS", (addr, 53), timeout=timeout)
            for a in res["answers"]:
                if a["type"] == "NS":
                    v = _clean(a["value"], "NS")
                    if v not in out["apex_ns"]:
                        out["apex_ns"].append(v)
        except DnsError as e:
            out["errors"][f"{ns}/apex-ns"] = str(e)
        out["per_ns"][ns] = {"records": row, "ttls": ttls}
    for t in out["records"]:
        out["records"][t] = sorted(out["records"][t])
    out["apex_ns"] = sorted(out["apex_ns"])
    return out


def _clean(value: str, rtype: str) -> str:
    if rtype in ("CNAME", "NS", "MX"):
        return " ".join(str(value).split()[:2]).rstrip(".")
    return value
