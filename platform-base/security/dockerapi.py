"""dockerapi — the security app's view of the engine, through GET requests only.

The app reads the edge's and the identity provider's logs, the containers' names and addresses, and
their resource use. It never creates, starts, stops or executes anything, so this client has exactly
one verb: there is no method here that could send a POST, PUT or DELETE, and a reviewer can confirm
that by reading one file. (The socket itself grants more; narrowing the socket to a filtering proxy is
plan item dsec-304, and this client already fits behind a GET-only one.)
"""
from __future__ import annotations

import http.client
import json
import socket
import urllib.parse


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float | None):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not None:
            s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


class DockerError(RuntimeError):
    pass


class Docker:
    def __init__(self, path: str = "/var/run/docker.sock"):
        self.path = path

    def _get(self, path: str, params: dict | None = None, timeout: float | None = 10):
        url = path + ("?" + urllib.parse.urlencode(params) if params else "")
        conn = _UnixConn(self.path, timeout)
        try:
            conn.request("GET", url, headers={"Host": "docker"})
            resp = conn.getresponse()
        except OSError as e:
            conn.close()
            raise DockerError(f"engine unreachable: {e}") from e
        return conn, resp

    def get_json(self, path: str, params: dict | None = None, timeout: float = 10):
        conn, resp = self._get(path, params, timeout)
        try:
            body = resp.read()
            if resp.status >= 400:
                raise DockerError(f"{path}: HTTP {resp.status} {body[:200]!r}")
            return json.loads(body or b"null")
        finally:
            conn.close()

    def containers(self, all_: bool = False) -> list:
        return self.get_json("/containers/json", {"all": "1" if all_ else "0"}) or []

    def inspect(self, name: str) -> dict:
        return self.get_json(f"/containers/{urllib.parse.quote(name)}/json") or {}

    def stats(self, cid: str) -> dict:
        return self.get_json(f"/containers/{cid}/stats", {"stream": "0", "one-shot": "1"}, timeout=15) or {}

    def system_df(self) -> dict:
        return self.get_json("/system/df", timeout=60) or {}

    def logs(self, name: str, since: float, follow: bool = True, tail: str = "all", tty: bool = False):
        """Yield (rfc3339_ts, line) from a container's stdout+stderr. Docker frames a non-TTY stream as
        [stream:1][0:3][size:4 BE][payload] (a TTY container's stream is raw); with timestamps=1 every
        line starts with an RFC 3339 nano timestamp and a space."""
        params = {"stdout": "1", "stderr": "1", "timestamps": "1", "follow": "1" if follow else "0",
                  "since": f"{since:.6f}" if since else "0", "tail": tail}
        conn, resp = self._get(f"/containers/{urllib.parse.quote(name)}/logs", params, timeout=None if follow else 30)
        if resp.status >= 400:
            body = resp.read()
            conn.close()
            raise DockerError(f"logs {name}: HTTP {resp.status} {body[:200]!r}")
        buf = b""
        try:
            while True:
                if tty:
                    chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(4096)
                    if not chunk:
                        return
                    buf += chunk
                else:
                    head = _read_exact(resp, 8)
                    if not head or len(head) < 8:
                        return
                    size = int.from_bytes(head[4:8], "big")
                    payload = _read_exact(resp, size)
                    if payload is None:
                        return
                    buf += payload
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", "replace")
                    ts, _, rest = text.partition(" ")
                    yield ts, rest
        finally:
            conn.close()


def _read_exact(resp, n: int):
    out = b""
    while len(out) < n:
        chunk = resp.read(n - len(out))
        if not chunk:
            return None if not out else out
        out += chunk
    return out


def container_addresses(containers: list) -> dict:
    """{ip: {"name": compose service or container name, "container": name}} for every network address."""
    out = {}
    for c in containers:
        labels = c.get("Labels") or {}
        cname = (c.get("Names") or ["?"])[0].lstrip("/")
        svc = labels.get("com.docker.compose.service") or cname
        for net in ((c.get("NetworkSettings") or {}).get("Networks") or {}).values():
            ip = net.get("IPAddress")
            if ip:
                out[ip] = {"name": svc, "container": cname}
    return out
