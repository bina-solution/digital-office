"""public_route_live — G116's live edge (public-route-lint.py --live, DGO-1177 stage 2): every router traefik serves on
this office, and whether it is open. Every rule here leans to OPEN when it cannot prove otherwise.

    routers   every http, tcp and udp router of the running containers' labels (one `docker inspect` of `docker ps`;
              `traefik.enable` read as Go reads a bool, label keys as traefik reads them, case-insensitively), a router
              known by any key of it — one with no rule served under traefik's default rule, Host(`<name>`) — and of
              traefik's file provider (*.yaml, *.yml, *.toml in its config directory and below, any case; a templated
              file counted, not read; the FIRST definition of a middleware kept, as traefik keeps it).
    signed    an http router whose middlewares hold the sign-in, each name resolved as traefik resolves it (a bare name
              is the router's own provider's): authentik@file / authentik-admins@file — only while the edge's SSO is
              known to be on, and only while no file that was read defines them (their one definition is the templated
              authentik-forwardauth.yaml) — or the LAN door's lan-auth@docker / lan-auth-admins@docker, only while
              lan-signin is the one container that defines them.
    nothing   a router whose service is noop@internal and every middleware of which is of a kind that answers from the
              request alone (HARMLESS: a redirect, headers, an allowlist, a rate limit …): a redirect or a refusal.
    fenced    a router behind an IP allowlist (of its own protocol) every range of which parses and which TOGETHER do
              not admit every address of a family (a /0 in any spelling, halves that add up, an IPv4-mapped range) —
              a fence a file defines is believed only while no template was skipped (one could define it first).
    doors     the platform's own doors that authenticate by themselves — DOORS, by the exact compose service AND the
              router name, each with its reason. (The compose PROJECT is not checked: a second project on the same
              engine with a service named like a door would be believed — written here, the third reader's.)
    declared  a router the office names in platform.state.yaml `public:` — `router:<name>` for that router alone, or a
              host name for every router whose hosts are all PROVABLE and all named. A rule proves its hosts when each
              `||` branch (at every depth) has a top-level `&&` part that is a one-argument Host, or a bracketed part
              that proves them the same way, and nothing in it negates (`!`) or matches by pattern (HostRegexp,
              HostSNI, HostHeader).
    dropped   a router naming a docker middleware no running container defines: traefik drops it whole (its pages
              answer 404) — a fault, named apart; --strict fails on it too, since a label misread would hide here.
    open      every other router: named, so the office decides (G116's stages).

Reading nothing is no answer: the edge is read only when traefik's own container is among the containers inspected,
at least one router came from the labels, and the config directory exists. The SSO state must be known (read from
traefik's own environment — BBOX_SSO only, in memory, nothing else kept — or given with --sso); unknown counts OFF.
Nothing here writes.
"""
import ipaddress
import json
import pathlib
import re
import subprocess

SIGN_IN_FILE = {"authentik@file", "authentik-admins@file"}
SIGN_IN_LAN = {"lan-auth@docker", "lan-auth-admins@docker"}
LAN_SIGNIN_SERVICE = "lan-signin"
SERVES_NOTHING = "noop@internal"
GO_TRUE = {"1", "t", "true"}
#: middleware kinds that answer from the request alone, never with another service's content: the only ones a
#: noop@internal router may carry and still «serve nothing» (an unknown kind — a plugin, a forwardAuth, an errors,
#: one defined in a skipped template — is not one of them)
HARMLESS = {"redirectregex", "redirectscheme", "headers", "ipallowlist", "ipwhitelist", "ratelimit", "inflightreq",
            "stripprefix", "stripprefixregex", "addprefix", "replacepath", "replacepathregex", "compress",
            "buffering", "contenttype"}
#: (compose service, router name — a trailing «*» is a prefix) → why it is open: the platform's own doors (measured on
#: the MacBook's and vps1's edges, 2026-11-11)
DOORS = {
    ("dgo-net", "dgo-extend-link-door"): "the link's door — a linked office's every request carries the pair's token",
    ("lan-signin", "lan-console*"): "the LAN door's own console and sign-in pages (entrypoint lan) — its own sign-in",
    ("forward-auth", "forward-auth-*"): "the sign-in itself — its pages cannot ask for a sign-in first",
}


# ── rules ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _scan(rule):
    """(index, char, depth) for every char outside a string — traefik's rules quote with ` or with " (\\" inside)."""
    depth, quote, i = 0, None, 0
    while i < len(rule):
        c = rule[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "`\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        yield i, c, depth
        i += 1


def split_top(rule, op):
    """The rule's parts at the top level of `op` (parentheses and both kinds of strings respected)."""
    out, last = [], 0
    for i, c, depth in _scan(rule):
        if depth == 0 and rule.startswith(op, i) and i >= last:
            out.append(rule[last:i])
            last = i + len(op)
    out.append(rule[last:])
    return [b.strip() for b in out]


def bracketed(part):
    """The inside of a part that is one bracketed sub-rule, else None."""
    if not (part.startswith("(") and part.endswith(")")):
        return None
    for i, c, depth in _scan(part):
        if c == ")" and depth == 0 and i != len(part) - 1:
            return None                          # `(a) && (b)`: not one bracket
    return part[1:-1]


def provable_hosts(rule):
    """Every host a request must name to reach this router, or None when the rule does not prove one."""
    if not rule.strip() or "!" in rule or re.search(r"(?i)HostRegexp|HostSNI|HostHeader", rule):
        return None
    if re.search(r"Host\(\s*[`\"][^`\"]*[`\"]\s*,", rule):  # traefik v2's several-argument Host
        return None
    return _prove(rule)


def _prove(rule):
    hosts = []
    for branch in split_top(rule, "||"):
        got = None
        for part in split_top(branch, "&&"):
            m = re.fullmatch(r"Host\(\s*(?:`([^`]+)`|\"([^\"\\]+)\")\s*\)", part)
            if m:
                got = [m.group(1) or m.group(2)]
                break
            inner = bracketed(part)
            if inner is not None:
                sub = _prove(inner)
                if sub:
                    got = sub
                    break
        if not got:
            return None
        hosts += got
    return hosts


def host_declared(host, declared):
    for d in declared:
        if d.startswith("router:"):
            continue
        if "." not in d and (host == d or host.startswith(d + ".")):
            return True
        if d.startswith("*.") and (host.endswith(d[1:]) or host == d[2:]):
            return True
        if "." in d and not d.startswith("*.") and host == d:
            return True
    return False


def door(service, name):
    return next((why for (svc, k), why in DOORS.items()
                 if service == svc and (name == k or (k.endswith("*") and name.startswith(k[:-1])))), None)


MAPPED = ipaddress.ip_network("::ffff:0:0/96")


def everyone(ranges):
    """None when a range does not parse or there is none (then it is no fence); True when the ranges TOGETHER admit
    every address of either family — `0.0.0.0/1` with `128.0.0.0/1` is everyone, and an IPv4-mapped IPv6 range is
    the IPv4 range it maps (as Go's IPNet.Contains lets an IPv4 address through it)."""
    v4, v6 = [], []
    for x in ranges:
        try:
            n = ipaddress.ip_network(str(x).strip(), strict=False)
        except ValueError:
            return None
        if n.version == 6 and n.prefixlen >= 96 and n.subnet_of(MAPPED):
            n = ipaddress.ip_network((int(n.network_address) & 0xFFFFFFFF, n.prefixlen - 96))
        elif n.version == 6 and n.supernet_of(MAPPED):
            v4.append(ipaddress.ip_network("0.0.0.0/0"))
        (v4 if n.version == 4 else v6).append(n)
    if not v4 and not v6:
        return None
    return any(c.prefixlen == 0 for c in list(ipaddress.collapse_addresses(v4)) + list(ipaddress.collapse_addresses(v6)))


# ── reading ─────────────────────────────────────────────────────────────────────────────────────────────────────────
class Edge:
    """What the routers, the middlewares and their definitions of one read are."""

    def __init__(self):
        self.routers = []
        self.definers = {}          # middleware@provider → {who defines it}
        self.kinds = {}             # middleware@provider (first definition) → its type, lower-case
        self.fences = {}            # (protocol, middleware@provider) (first definition) → [ranges]
        self.containers = []
        self.skipped = []

    def define(self, proto, name, kind, who, ranges=None):
        self.definers.setdefault(name, set()).add(who)
        self.kinds.setdefault(name, kind.lower())
        if ranges is not None and (proto, name) not in self.fences:
            self.fences[(proto, name)] = ranges


def from_labels(lines, edge=None):
    edge = edge or Edge()
    for line in lines:
        cname, _, js = line.strip().partition(" ")
        try:
            labels = json.loads(js)
        except ValueError:
            continue
        if not isinstance(labels, dict):
            continue
        cname = cname.lstrip("/")
        edge.containers.append(cname)
        low = {str(k).lower(): v for k, v in labels.items()}
        if str(low.get("traefik.enable", "")).strip().lower() not in GO_TRUE:
            continue
        svc_label = str(low.get("com.docker.compose.service", ""))
        found = {}
        for k, v in low.items():
            m = re.match(r"traefik\.(http|tcp|udp)\.routers\.([^.]+)\.(.+)$", k)
            if m:
                found.setdefault((m.group(1), m.group(2)), {})[m.group(3)] = str(v)
            m = re.match(r"traefik\.(http|tcp)\.middlewares\.([^.]+)\.([^.]+)(?:\.([^.]+))?", k)
            if m:
                proto, mname, kind, field = m.group(1), m.group(2) + "@docker", m.group(3), (m.group(4) or "").lower()
                ranges = ([x for x in re.split(r"[,\s]+", str(v)) if x]
                          if kind in ("ipallowlist", "ipwhitelist") and field == "sourcerange" else None)
                edge.define(proto, mname, kind, svc_label, ranges)
        if not any(kind == "http" for kind, _ in found) and (
                not found or any(k.startswith("traefik.http.") for k in low)):
            found[("http", cname)] = {}                      # traefik's default http router, under its default rule
        for (kind, name), d in sorted(found.items()):
            edge.routers.append({"kind": kind, "provider": "docker", "where": cname, "service_label": svc_label,
                                 "name": name, "rule": d.get("rule", ""),
                                 "mids": [x.strip() for x in d.get("middlewares", "").split(",") if x.strip()],
                                 "service": d.get("service", "")})
    return edge


def ci(d, key, default=None):
    """d[key] as traefik's file decoder reads it: the key in any case (the first one that matches)."""
    if not isinstance(d, dict):
        return default
    for k, v in d.items():
        if str(k).lower() == key.lower():
            return v
    return default


def from_files(config_dir, load_yaml, edge=None):
    edge = edge or Edge()
    paths = sorted(p for p in pathlib.Path(config_dir).rglob("*")
                   if p.is_file() and p.suffix.lower() in (".yaml", ".yml", ".toml"))
    for f in paths:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "{{" in text:
            edge.skipped.append(f.name)
            continue
        try:
            if f.suffix.lower() == ".toml":
                import tomllib
                doc = tomllib.loads(text)
            else:
                doc = load_yaml(text) or {}
        except Exception:                       # noqa: BLE001 — a file traefik cannot read either: counted
            edge.skipped.append(f.name)
            continue
        if not isinstance(doc, dict):
            continue
        for proto in ("http", "tcp", "udp"):
            sect = ci(doc, proto)
            if not isinstance(sect, dict):
                continue
            mws = ci(sect, "middlewares")
            for mname, d in (mws.items() if isinstance(mws, dict) else ()):
                if not isinstance(d, dict) or not d:
                    continue
                kind = next(iter(d))
                body = d.get(kind)
                ranges = None
                if str(kind).lower() in ("ipallowlist", "ipwhitelist") and isinstance(body, dict):
                    src = ci(body, "sourceRange", [])
                    ranges = [str(x) for x in src] if isinstance(src, list) else [str(src)]
                edge.define(proto, f"{mname}@file", str(kind), f.name, ranges)
            routers = ci(sect, "routers")
            for name, d in sorted(routers.items()) if isinstance(routers, dict) else ():
                d = d if isinstance(d, dict) else {}
                mids = ci(d, "middlewares") or []
                edge.routers.append({"kind": proto, "provider": "file", "where": f.name, "service_label": "",
                                     "name": str(name), "rule": str(ci(d, "rule", "")),
                                     "mids": [str(m) for m in mids] if isinstance(mids, list) else [str(mids)],
                                     "service": str(ci(d, "service", ""))})
    if edge.skipped:
        # a skipped template may define a fence first — traefik keeps the first: no file fence is believed then
        edge.fences = {k: v for k, v in edge.fences.items() if not k[1].endswith("@file")}
    return edge


# ── judging ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def resolved(mid, provider):
    return mid if "@" in mid else f"{mid}@{provider}"


def judge(edge, declared, sso_on=False):
    """{bucket: [router]}: signed, nothing, fenced, doors, declared, open, dropped."""
    out = {k: [] for k in ("signed", "nothing", "fenced", "doors", "declared", "open", "dropped")}
    file_sign_in = {m for m in SIGN_IN_FILE if m not in edge.definers} if sso_on else set()
    sign_in = file_sign_in | {m for m in SIGN_IN_LAN if edge.definers.get(m) == {LAN_SIGNIN_SERVICE}}
    by_router = {d[7:] for d in declared if d.startswith("router:")}
    for r in edge.routers:
        mids = [resolved(m, r["provider"]) for m in r["mids"]]
        fence = [edge.fences.get((r["kind"], m)) for m in mids]
        if any(m.endswith("@docker") and m not in edge.definers for m in mids):
            out["dropped"].append(r)
        elif r["kind"] == "http" and any(m in sign_in for m in mids):
            out["signed"].append(r)
        elif r["service"] == SERVES_NOTHING and all(edge.kinds.get(m) in HARMLESS for m in mids):
            out["nothing"].append(r)
        elif any(f is not None and everyone(f) is False for f in fence):
            out["fenced"].append(r)
        elif door(r["service_label"], r["name"]):
            out["doors"].append(r)
        elif r["name"] in by_router:
            out["declared"].append(r)
        else:
            hosts = provable_hosts(r["rule"]) if r["kind"] == "http" else None
            out["declared" if hosts and all(host_declared(h, declared) for h in hosts) else "open"].append(r)
    return out


def read_edge(labels_from=None, run=subprocess.run):
    """(label lines, sso_on — True/False, or None when unknown, traefik read)."""
    if labels_from:
        lines = pathlib.Path(labels_from).read_text(encoding="utf-8", errors="replace").splitlines()
        return lines, None, any(ln.lstrip("/").startswith("traefik-") for ln in lines)
    ids = run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=60)
    if ids.returncode != 0:
        raise RuntimeError(f"docker ps answered {ids.returncode}: {ids.stderr.strip()[:200]}")
    if not ids.stdout.split():
        return [], None, False
    got = run(["docker", "inspect", *ids.stdout.split(), "--format", "{{.Name}} {{json .Config.Labels}}"],
              capture_output=True, text=True, timeout=120)
    if got.returncode != 0:
        raise RuntimeError(f"docker inspect answered {got.returncode}: {got.stderr.strip()[:200]}")
    lines = got.stdout.splitlines()
    traefik = [ln.split(" ", 1)[0].lstrip("/") for ln in lines if ln.lstrip("/").startswith("traefik-")]
    sso_on = None
    if traefik:
        env = run(["docker", "inspect", traefik[0], "--format", "{{json .Config.Env}}"],
                  capture_output=True, text=True, timeout=60)
        if env.returncode == 0:
            try:
                values = json.loads(env.stdout or "[]")
            except ValueError:
                values = None
            if isinstance(values, list):
                sso_on = not any(v == "BBOX_SSO=off" for v in values if isinstance(v, str))
    return lines, sso_on, bool(traefik)


def report(buckets, edge, labelled, traefik_read, config_ok, sso_on, declared, strict, out=print):
    if declared is None:
        out("G116 FAIL (live) — platform.state.yaml `public:` is not a list of route names: it cannot be read.")
        return 1
    if not traefik_read or not labelled or not config_ok:
        out("G116 FAIL (live) — the edge was not read: traefik's own container is not among the containers inspected"
            " (another engine answered?), no router came from the labels, or the config directory is not there.")
        return 1
    for r in buckets["open"]:
        hosts = ",".join(provable_hosts(r["rule"]) or []) or (r["rule"][:60] or "(traefik's default rule)")
        out(f"  open, undeclared  {r['kind']} {r['name']:<34} {hosts:<44} ({r['where']}) — `router:{r['name']}` or "
            f"its host in platform.state.yaml `public:` if this office means it open, else the sign-in")
    if buckets["dropped"]:
        missing = sorted({m for r in buckets["dropped"] for m in (resolved(x, r["provider"]) for x in r["mids"])
                          if m.endswith("@docker") and m not in edge.definers})
        out(f"  FAULT  {len(buckets['dropped'])} router(s) name a middleware no running container defines "
            f"({', '.join(missing)}): traefik drops them, their pages answer 404 — a container older than its "
            f"compose? (`./scripts/dc up -d <service>` recreates it)")
    n = sum(len(v) for v in buckets.values())
    head = (f"{n} router(s) on the edge — {len(buckets['signed'])} behind the sign-in, {len(buckets['nothing'])} serving"
            f" nothing, {len(buckets['fenced'])} fenced to some addresses, {len(buckets['doors'])} the platform's own "
            f"doors, {len(buckets['declared'])} declared public, {len(buckets['dropped'])} dropped"
            + (" (SSO OFF or unknown: authentik@file is counted no sign-in)" if not sso_on else "")
            + (f"; not read: {', '.join(edge.skipped)}" if edge.skipped else ""))
    if strict and (buckets["open"] or buckets["dropped"]):
        out(f"G116 FAIL (live) — {head}; {len(buckets['open'])} open, undeclared.")
        return 1
    if buckets["open"] or buckets["dropped"]:
        out(f"G116 WARN (live) — {head}; {len(buckets['open'])} open, undeclared (stage 1: --strict fails on these).")
        return 0
    out(f"G116 PASS (live) — {head}.")
    return 0
