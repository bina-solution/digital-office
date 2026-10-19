"""identity — WHO is calling the credential broker?

The broker's entire value rests on this file. `connections` holds every secret in the estate and
until now answered `GET /api/export-all?format=env` for anybody who could open a TCP socket to it
(security-plan-2026 B1, proven live from an unrelated container). Handing out secrets is only safe
if the caller can be named, so this module answers exactly one question:

    (source IP, claimed container id)  ->  which compose service is on the other end of this socket?

Two independent factors, and they must AGREE:

  1. **Network position** — the source IP of the TCP connection, mapped to a running container
     through the Docker Engine API. An attacker must occupy that IP.
  2. **Container-id proof** — the caller reads its OWN container id out of `/proc/self/mountinfo`
     (Docker bind-mounts `/var/lib/docker/containers/<64-hex>/{hostname,hosts,resolv.conf}` into
     every container, so the id is always legible from inside) and presents it as a header. The id
     is a 256-bit random value that a container cannot learn about ANOTHER container without
     already having the docker socket. An attacker must know that value.

Neither factor alone is sufficient, and we say so in the result (`method`), so the policy layer can
treat `container-id+ip` and bare `ip` differently. What this does NOT do — deliberately, because
claiming otherwise would be the dangerous part:

  ⚠ **A source IP on a shared docker bridge is not unforgeable.** Containers get `NET_RAW` by
    default, so a hostile container on the same bridge can ARP-poison its neighbour and complete a
    TCP handshake from a spoofed address. That is why factor 2 exists and why `ip`-only identity is
    reported as weaker rather than as proof. Real unforgeable identity needs mTLS with per-workload
    certs (SPIFFE); this is the strongest thing available without a PKI, and the honest name for it
    is "two factors an attacker must defeat together", not "authentication".

  ⚠ **The docker socket is read here, and reading it is a privilege.** We issue GET requests only —
    `/_ping`, `/containers/json` — and never a POST, so this module cannot create, exec into or
    start anything. But the bind mount itself grants the container the ability to; see the residual
    risks in README.md. Point `DOCKER_SOCK` at a read-only socket proxy where one is available.

No third-party dependency: the Docker Engine API is plain HTTP over a unix socket.
"""
import http.client
import json
import os
import socket
import threading
import time

DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
API_VERSION = os.environ.get("DOCKER_API_VERSION", "v1.41")
# The container table is cached for a moment because a grant burst at boot would otherwise hammer
# the daemon. The TTL is deliberately tiny: a cached row is a row that may already be WRONG, and the
# way it goes wrong is the dangerous direction — a container dies, docker later hands its address to
# a different service, and for the rest of the TTL an ip-only lookup would name the dead container's
# service. Two seconds is short enough that an attacker would have to win an address-recycling race
# it does not control; it is not zero, and that window is stated in README.md rather than rounded off.
CACHE_TTL = float(os.environ.get("CONN_IDENTITY_CACHE_TTL", "2"))
_SERVICE_LABEL = "com.docker.compose.service"
_PROJECT_LABEL = "com.docker.compose.project"
_APP_LABEL = "io.bina.app"          # optional, future: an explicit app id on the container


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection over an AF_UNIX socket — the Docker Engine API's transport."""

    def __init__(self, path, timeout=3.0):
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._unix_path)
        self.sock = s


def _docker_get(path, timeout=3.0):
    """GET one Docker API path. Returns parsed JSON, or None when the daemon is not reachable.

    GET ONLY. This module never mutates the daemon, and keeping that literally true (rather than
    "we only happen to call GETs") is what lets the README state the blast radius of the socket
    mount precisely."""
    conn = _UnixHTTPConnection(DOCKER_SOCK, timeout=timeout)
    try:
        conn.request("GET", f"/{API_VERSION}{path}")
        r = conn.getresponse()
        body = r.read()
        if r.status != 200:
            return None
        return json.loads(body.decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass


_lock = threading.Lock()
_cache = {"at": 0.0, "by_ip": {}, "by_id": {}, "available": False}


def _snapshot():
    """{ip -> [container]} and {id -> container} for every RUNNING container.

    One API call. A container can sit on several networks (drive is on traefik-network AND
    supabase-net), so every address it holds is indexed — matching on only the first network is how
    an identity check quietly starts failing for half the estate."""
    conts = _docker_get("/containers/json")
    if conts is None:
        return None
    by_ip, by_id = {}, {}
    for c in conts:
        labels = c.get("Labels") or {}
        nets = ((c.get("NetworkSettings") or {}).get("Networks") or {})
        ips = sorted({n.get("IPAddress") for n in nets.values() if n.get("IPAddress")})
        rec = {
            "container_id": c.get("Id", ""),
            "container_name": (c.get("Names") or ["/?"])[0].lstrip("/"),
            "service": labels.get(_SERVICE_LABEL) or "",
            "project": labels.get(_PROJECT_LABEL) or "",
            "app": labels.get(_APP_LABEL) or labels.get(_SERVICE_LABEL) or "",
            "ips": ips,
        }
        by_id[rec["container_id"]] = rec
        for ip in ips:
            by_ip.setdefault(ip, []).append(rec)
    return {"by_ip": by_ip, "by_id": by_id}


def _fresh(force=False):
    with _lock:
        if not force and (time.time() - _cache["at"]) < CACHE_TTL and _cache["available"]:
            return _cache
        snap = _snapshot()
        if snap is None:
            _cache.update({"at": time.time(), "available": False})
            return _cache
        _cache.update({"at": time.time(), "available": True, **snap})
        return _cache


def docker_available():
    return _fresh().get("available", False)


def _by_id(cache, claimed):
    """Look a claimed id up. Docker ids are 64 hex; callers may present the 12-char short form."""
    claimed = (claimed or "").strip().lower()
    if len(claimed) < 12 or not all(ch in "0123456789abcdef" for ch in claimed):
        return None
    hit = cache["by_id"].get(claimed)
    if hit:
        return hit
    for cid, rec in cache["by_id"].items():
        if cid.startswith(claimed):
            return rec
    return None


def identify(remote_addr, claimed_container_id=None):
    """Name the caller.

    Returns a dict that is always safe to log and to hand to a policy function:

        ok          bool   — an identity was established at all
        method      str    — container-id+ip | ip | none
        service     str    — the compose service name (the key the manifest uses)
        app         str    — app id if labelled, else the service name
        reason      str    — why identification failed, or a caveat when it succeeded

    `spoof-suspected` is its own outcome and is NEVER ok: it means the caller presented a real
    container id that does not own the address the packet came from. That is not a mis-configuration
    anyone hits by accident, so it is refused in every mode and logged loudly.
    """
    base = {"ok": False, "method": "none", "service": "", "app": "", "container_id": "",
            "container_name": "", "ip": remote_addr or "", "reason": ""}
    cache = _fresh()
    if not cache.get("available"):
        # try once more with a forced refresh: the daemon may have been restarting
        cache = _fresh(force=True)
    if not cache.get("available"):
        return {**base, "reason": f"docker socket unavailable at {DOCKER_SOCK}"}

    claimed_rec = _by_id(cache, claimed_container_id) if claimed_container_id else None
    if claimed_container_id and not claimed_rec:
        return {**base, "reason": "claimed container id is not a running container"}

    if claimed_rec:
        if remote_addr not in claimed_rec["ips"]:
            return {**base, "method": "spoof-suspected",
                    "container_id": claimed_rec["container_id"],
                    "container_name": claimed_rec["container_name"],
                    "service": claimed_rec["service"],
                    "reason": (f"claimed container {claimed_rec['container_name']} owns "
                               f"{','.join(claimed_rec['ips']) or '(no address)'}, "
                               f"but the request came from {remote_addr}")}
        return {"ok": True, "method": "container-id+ip", "ip": remote_addr,
                "container_id": claimed_rec["container_id"],
                "container_name": claimed_rec["container_name"],
                "service": claimed_rec["service"], "app": claimed_rec["app"],
                "reason": ""}

    hits = cache["by_ip"].get(remote_addr or "", [])
    if not hits:
        return {**base, "reason": f"no running container holds {remote_addr}"}
    if len(hits) > 1:
        names = ", ".join(sorted(h["container_name"] for h in hits))
        return {**base, "reason": f"address {remote_addr} maps to several containers ({names})"}
    rec = hits[0]
    return {"ok": True, "method": "ip", "ip": remote_addr,
            "container_id": rec["container_id"], "container_name": rec["container_name"],
            "service": rec["service"], "app": rec["app"],
            "reason": "no container-id proof presented — network position only"}


def self_container_id():
    """This process's own container id, read the way a client reads it (used by /healthz + tests).

    Docker mounts /var/lib/docker/containers/<id>/{hostname,hosts,resolv.conf}, so mountinfo names
    the id on every runtime and both cgroup versions; the cgroup path is a fallback for hosts where
    the mount source is masked."""
    for path, marker in (("/proc/self/mountinfo", "/containers/"), ("/proc/self/cgroup", "/docker/")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    i = line.find(marker)
                    while i != -1:
                        cand = line[i + len(marker):i + len(marker) + 64]
                        if len(cand) == 64 and all(c in "0123456789abcdef" for c in cand):
                            return cand
                        i = line.find(marker, i + 1)
        except OSError:
            continue
    return ""
