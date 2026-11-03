"""bbox_agent.client — the agent.v1 client: where the provider is, how we authenticate, one call.

Nothing here knows any harness. The contract is ai/context/agent-contract.md; the provider is
whichever app declares capability `office-agent` with interface `agent.v1`.

Reach (the whole latency story): the provider publishes its port on the docker HOST's loopback, so
from a Linux docker host, from WSL, and from the macOS engine (Lima forwards a guest loopback port to
the Mac's loopback) the address is the same: http://127.0.0.1:3081. No process is spawned per call.
The token is obtained ONCE — read from the provider's container through the engine, the same trust
as `docker exec` — and cached at ~/.config/bbox/agent.json (0600). A 401 refreshes it once.

Python 3.9 (the Mac's system python) and the standard library only.
"""
from __future__ import annotations

import atexit
import base64
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Iterator, Optional

REPO = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:3081"
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "bbox" / "agent.json"
#: The protocol name of a link, and of the credentials it carries (`links.PROTOCOL`). The contract
#: (`ai/context/dgo-remote-apps.md`) names one instance per office, `dgo_link-<office>`; the serving
#: office's converge also writes one per served agent app. Both are tried, in that order.
PROTOCOL = "dgo_link"
#: The vault instance that holds a SERVED agent's action token (DGO-32). The office that serves an
#: agent app writes it under exactly this name (`apps/dgo-extend/converge.py:agent_instance`), from
#: facts both ends can see, so the handoff and this lookup cannot disagree about one secret's name.
AGENT_INSTANCE = "dgo_link-serve-{office}-{app}-agent"
#: An instance id is read back through a shell and a python one-liner: keep it inert.
INSTANCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")


class AgentError(Exception):
    """A failed call, carrying the exit code the CLI should end with."""

    def __init__(self, message: str, code: int = 1, http: Optional[int] = None, detail: Optional[str] = None):
        super().__init__(message)
        self.message, self.code, self.http, self.detail = message, code, http, detail


# ── the provider ────────────────────────────────────────────────────────────────
def _state() -> dict:
    try:
        import yaml  # noqa: PLC0415 — the Mac's system python has no yaml; only reached for `serve:`
    except ImportError:
        return {}
    try:
        return yaml.safe_load((REPO / "platform.state.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _manifest(app_id: str) -> dict:
    for base in ("apps", "platform-base"):
        p = REPO / base / app_id / "app.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def _agent_port(manifest: dict) -> int:
    for c in manifest.get("capabilities") or []:
        if c.get("name") == "office-agent" and c.get("interface") == "agent.v1":
            m = re.match(r"https?://[^:/]+:(\d+)", str(c.get("endpoint") or ""))
            if m:
                return int(m.group(1))
    return 0


def _local_provider() -> Optional[dict]:
    """The enabled app of THIS office providing office-agent/agent.v1: {app, service, port}."""
    state = (REPO / "platform.state.yaml").read_text(encoding="utf-8")
    for manifest in sorted(list(REPO.glob("apps/*/app.json")) + list(REPO.glob("platform-base/*/app.json"))):
        j = json.loads(manifest.read_text(encoding="utf-8"))
        for c in j.get("capabilities") or []:
            if c.get("name") == "office-agent" and c.get("interface") == "agent.v1" and c.get("endpoint"):
                if re.search(r"^\s+%s:\s*\{[^}]*(enabled:\s*true|state:\s*enabled)" % re.escape(j["id"]), state, re.M):
                    m = re.match(r"https?://([^:/]+):?(\d+)?", c["endpoint"])
                    return {"app": j["id"], "service": m.group(1) if m else j["id"], "port": int(m.group(2) or 80) if m else 80}
    return None


def _remote_blocks() -> list[dict]:
    """Every block of `platform.state.yaml` that names apps of ANOTHER office.

    Two keys, one meaning: `serve:` was the first shape (DGO-30) and `remote:` is its generalisation
    (`projection.py`, remote-core): the contract keeps `serve:` readable as an alias for one release,
    so discovery reads both and neither is a second source of truth — the file has one writer
    (`dgo-extend`), and this is a READER.
    """
    st = _state()
    out = []
    for key in ("remote", "serve"):
        block = st.get(key)
        if isinstance(block, dict):              # {office: {...}}
            for off, entry in block.items():
                if isinstance(entry, dict):
                    out.append({"office": str(entry.get("office") or off), **entry})
        elif isinstance(block, list):
            out.extend(e for e in block if isinstance(e, dict))
    return out or _registry_blocks()


def _registry_blocks() -> list[dict]:
    """The same blocks, read from what layer 0 compiled of them (`.generated/registry/remote.<office>.<alias>.json`),
    for a python with no yaml: the Mac's system python3 runs this CLI, and without PyYAML `_state()` is empty — so
    `bbox agent --office hp-laptop` found no HP at all (the Obsidian session, 2026-11-01). JSON needs nothing."""
    offices: dict = {}
    for f in sorted((REPO / ".generated" / "registry").glob("remote.*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        remote = d.get("remote") if isinstance(d, dict) else None
        if not isinstance(remote, dict) or not remote.get("office"):
            continue
        entry = offices.setdefault(str(remote["office"]), {
            "office": str(remote["office"]), "label": remote.get("label"), "address": remote.get("address"),
            "apps": []})
        entry["apps"].append({"app": d.get("app"), "alias": d.get("alias"),
                              "agent_api_port": d.get("agent_api_port"), "port": d.get("port"),
                              "link_port": d.get("link_port"), "host": d.get("host")})
    return list(offices.values())


def _vault_instances() -> list[dict]:
    """Every `dgo_link` instance this office's vault holds, secrets included.

    Through the engine, like every other vault read here: the CLI runs on the machine that runs the
    office, and `docker exec` into the vault's own container is the trust it already has. A vault
    that is down answers `[]` — the caller reports "not found", never "the link is gone".
    """
    inner = ("import json,urllib.request;"
             "print(json.dumps(json.load(urllib.request.urlopen("
             "'http://127.0.0.1:8990/api/instances?protocol=dgo_link',timeout=20))"
             ".get('instances') or []))")
    b64 = base64.b64encode(inner.encode()).decode()
    script = (
        "c=$(docker ps -q --filter label=com.docker.compose.service=connections | head -1); "
        "[ -n \"$c\" ] || { echo '[]'; exit 0; }; "
        f"docker exec \"$c\" python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\""
    )
    try:
        out = _run(_engine_cmd(["sh", "-c", script]), timeout=120).splitlines()[-1]
        rows = json.loads(out)
    except (AgentError, ValueError, IndexError):
        return []
    # the list endpoint does not carry secrets; the link's own facts (office, address, port) live in
    # them, so each row is read once — there are as many rows as there are links.
    detailed = []
    for row in rows if isinstance(rows, list) else []:
        iid = str((row or {}).get("id") or "")
        secret = _vault_secret(iid)
        if secret:
            detailed.append({**row, "secret": secret})
    return detailed


def _vault_secret(instance: str) -> dict:
    """One instance's secret dict from this office's vault ({} when it cannot be read)."""
    if not INSTANCE_RE.match(instance or ""):
        return {}
    inner = ("import json,urllib.request,sys;"
             "print(json.dumps((json.load(urllib.request.urlopen("
             "'http://127.0.0.1:8990/api/instances/%s/secret' % sys.argv[1],timeout=20)"
             ").get('secret') or {})))")
    b64 = base64.b64encode(inner.encode()).decode()
    script = (
        "c=$(docker ps -q --filter label=com.docker.compose.service=connections | head -1); "
        "[ -n \"$c\" ] || { echo '{}'; exit 0; }; "
        f"docker exec \"$c\" python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\" "
        f"{instance}"
    )
    try:
        return json.loads(_run(_engine_cmd(["sh", "-c", script]), timeout=120).splitlines()[-1])
    except (AgentError, ValueError, IndexError):
        return {}


def _link_host(alias: str, office: str, addr: str) -> str:
    """Where a linked office's app answers FROM HERE: the link's own name where it resolves, the
    peer's tunnel address elsewhere.

    `<alias>.<office>` is a network alias on the link proxy — it means something to every process on
    the office network (an agent in its container) and to nobody else; the tunnel address means
    something only where the tunnel's interface is (a host that carries it). Measured 2026-10-06 from
    hp-laptop's containers: the name answered in 0.13 s, the address timed out — its interface lives
    in the tunnel container's own namespace there, so `--office` reached nobody.
    """
    name = f"{alias}.{office}"
    try:
        socket.gethostbyname(name)
        return name
    except OSError:
        return addr


#: The other end of `_relay`, run inside a container on the office network: one TCP connection to the
#: link's name, carried over stdin/stdout. It sits in argv base64-encoded, because stdin is the stream.
_RELAY_PIPE = (
    "import os,socket,sys,threading\n"
    "s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=20)\n"
    "s.settimeout(None)\n"
    "def up():\n"
    "    while True:\n"
    "        d=os.read(0,65536)\n"
    "        if not d: break\n"
    "        s.sendall(d)\n"
    "    try: s.shutdown(socket.SHUT_WR)\n"
    "    except OSError: pass\n"
    "threading.Thread(target=up,daemon=True).start()\n"
    "while True:\n"
    "    d=s.recv(65536)\n"
    "    if not d: break\n"
    "    os.write(1,d)\n")
_LINK_NAME_RE = re.compile(r"[a-z0-9][a-z0-9.\-]{0,200}")      # fullmatch: no trailing newline
_DEPLOYMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
_relays: dict = {}


def _deployment_name() -> str:
    """This office's `DEPLOYMENT_NAME` — the suffix of every one of its containers (`<svc>-<name>`) —
    read from the checkout's `.env` by that one key, never printed. Absent, it is compose's own default
    (`container_name: dgo-extend-${DEPLOYMENT_NAME:-bina-deployment}`); "" only for a value a shell
    could misread."""
    try:
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DEPLOYMENT_NAME="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value if _DEPLOYMENT_RE.fullmatch(value) else ""
    except OSError:
        pass
    return "bina-deployment"


#: The relay processes alive in this run, so an interrupted `bbox agent` takes them with it: each one
#: runs in a session of its own (`killpg` reaches bash → limactl → ssh), and that same session is what
#: keeps a Ctrl-C in the terminal from reaching them.
_live: set = set()


def _kill_chain(p) -> None:
    try:
        os.killpg(p.pid, 9)
    except OSError:
        try:
            p.kill()
        except OSError:
            pass


@atexit.register
def _kill_relays() -> None:
    for p in list(_live):
        _kill_chain(p)


def _relay_cmd(name: str, port: int) -> list:
    """The process that carries one connection: `_RELAY_PIPE` in THIS office's dgo-extend, which is on the
    office network. By its container name (`dgo-extend-<DEPLOYMENT_NAME>`) where the checkout says it: a
    machine that runs two offices has two dgo-extends, and the other one's alias leads to the other
    office's link. `name` and `port` were checked by `_relay` and are inert in a shell."""
    b64 = base64.b64encode(_RELAY_PIPE.encode()).decode()
    dep = _deployment_name()
    pick = (f"--filter name=^dgo-extend-{dep}$" if dep else "") + " --filter label=com.docker.compose.service=dgo-extend"
    script = (f"c=$(docker ps -q {pick} | head -1); "
              "[ -n \"$c\" ] || { echo 'no dgo-extend of this office is running' >&2; exit 1; }; "
              f"exec docker exec -i \"$c\" python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\" "
              f"{name} {int(port)}")
    return _engine_cmd(["sh", "-c", script])


def _relay_one(client: socket.socket, name: str, port: int) -> None:
    try:
        p = subprocess.Popen(_relay_cmd(name, port), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
    except OSError:
        client.close()
        return
    _live.add(p)
    carried = [0]
    said = bytearray()

    def drain():
        # stderr is read while the connection lives: a pipe nobody reads blocks its writer at ~64 KB
        # (engine.sh says things on every hop), and only the last few lines are worth an answer
        try:
            while True:
                d = os.read(p.stderr.fileno(), 4096)
                if not d:
                    break
                said.extend(d)
                del said[:-2000]
        except OSError:
            pass
    drained = threading.Thread(target=drain, daemon=True)
    drained.start()

    def down():
        try:
            while True:
                d = os.read(p.stdout.fileno(), 65536)
                if not d:
                    break
                carried[0] += len(d)
                client.sendall(d)
        except OSError:
            pass
        if not carried[0]:
            # Nothing came back: the hop itself failed (no dgo-extend, no engine, a name the network does
            # not know). Said as an HTTP answer, so the caller reads why instead of "connection dropped".
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            drained.join(timeout=2)
            why = bytes(said) or b"the relay carried nothing"
            body = b"relay to " + name.encode() + b":" + str(port).encode() + b" failed: " + why.strip()
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\ncontent-type: text/plain\r\ncontent-length: "
                               + str(len(body)).encode() + b"\r\nconnection: close\r\n\r\n" + body)
            except OSError:
                pass
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    t = threading.Thread(target=down, daemon=True)
    t.start()
    try:
        while True:
            d = client.recv(65536)
            if not d:
                break
            p.stdin.write(d)
            p.stdin.flush()
    except OSError:
        pass
    try:
        p.stdin.close()
    except OSError:
        pass
    t.join(timeout=60)                   # the far side had its minute to finish what it was sending
    client.close()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_chain(p)                   # the whole chain, not only its first process
    _live.discard(p)


def _relay(name: str, port: int) -> str:
    """A loopback door to `<name>:<port>` as the office network sees it, for a process that is not on it.

    `<alias>.<office>` is a network alias on the link proxy: it resolves in a container on the office
    network and nowhere else. The Mac host is not there, and neither is a Linux host whose tunnel lives
    in a container (the HP, the Dell). So each connection is carried by one `docker exec -i` into this
    office's dgo-extend, which is on that network. Measured 2026-11-02 on the Mac: `bbox agent --office
    hp-laptop` dialled 10.79.5.1:10080, a tunnel address the host has no route to, on the port of the
    Mac's OWN listener (DGO-1127). "" when the name is not one this may pass to a shell."""
    if not _LINK_NAME_RE.fullmatch(name or "") or not 1 <= int(port) <= 65535:
        return ""
    key = (name, int(port))
    if key in _relays:
        return _relays[key]
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=_relay_one, args=(c, name, int(port)), daemon=True).start()
    threading.Thread(target=serve, daemon=True, name=f"relay-{name}").start()
    _relays[key] = f"http://127.0.0.1:{srv.getsockname()[1]}"
    return _relays[key]


def _link_url(alias: str, office: str, addr: str, port: int) -> str:
    """Where a linked office's app answers FROM HERE: by the link's name where it resolves, through
    `_relay` where it does not and the engine is at hand, and at the peer's tunnel address last (a
    machine whose tunnel is its own interface, with no engine to ask)."""
    name = f"{alias}.{office}"
    if _link_host(alias, office, addr) == name:
        return f"http://{name}:{port}"
    if not os.path.exists("/.dockerenv"):
        relayed = _relay(name, port)
        if relayed:
            return relayed
    return f"http://{addr}:{port}"


def _vault_provider(office: str = "") -> Optional[dict]:
    """A linked office's agent, resolved from THIS office's vault alone (DGO-32).

    The compiled `remote:`/`serve:` block is the primary answer, but it depends on a whole chain
    (catalog → projection → compiler) being present and accepted on this machine. The credential the
    serving office handed over is a direct fact and carries everything needed to reach it — the
    serving office's own end of the pair (`address`), the adapter's `port`, and its `label` — so
    `bbox agent --office <office>` works on a machine whose compiler has not caught up. An office may
    be named by its id, its label, or the account hint's half, all case-insensitively: a person says
    "macbook", the record may say "local with the label MacBook".
    """
    want = (office or "").strip().lower()
    for row in _vault_instances():
        sec = row.get("secret") or {}
        names = [str(row.get("id") or ""), str(sec.get("office") or ""),
                 str(sec.get("label") or ""), str(sec.get("peer") or "")]
        names += [n.split("-")[-1] for n in names]
        # An office is named the way a person names it — "macbook" — while the record may say `local`
        # with the label "הסוכן של MacBook — bina-ds". So a word match inside a name counts, and only
        # for names long enough that a substring cannot mean something else.
        def _named(n: str) -> bool:
            n = n.lower()
            return n == want or (len(want) >= 4 and re.search(r"(^|[^a-z0-9])" + re.escape(want) + r"([^a-z0-9]|$)", n) is not None)
        if want and not any(_named(n) for n in names if n):
            continue
        # …and an agent credential is the office its secret names, never the one its id seems to:
        # `hp` + `laptop-bina-ds` is `dgo_link-serve-hp-laptop-bina-ds-agent` too (DGO-1127).
        if want and str(row.get("id") or "").startswith("dgo_link-serve-") and sec.get("office") \
                and not (_named(str(sec["office"])) or _named(str(sec.get("label") or ""))):
            continue
        addr = str(sec.get("address") or "").strip()
        port = int(sec.get("port") or 0)
        appid = str(sec.get("app") or "")
        if not (addr and port):
            continue
        alias = str(sec.get("alias") or appid or "bina")
        return {"app": appid or "bina-ds", "alias": alias,
                "port": port, "service": f"dgo-serve-{sec.get('office')}-{appid}",
                # never through `_relay`: this port is the PEER's published one, and on this office's link
                # proxy that number may be another peer's listener (`apply_plan` moves ours) — only the
                # state block's port is ours to dial by the link's name
                "url": f"http://{_link_host(alias, want or str(sec.get('office') or ''), addr)}:{port}",
                "served_by": str(sec.get("office") or ""),
                "instances": [str(row.get("id") or "")], "instance": str(row.get("id") or ""),
                "from": "vault"}
    return None


def remote_provider(office: str = "") -> Optional[dict]:
    """The agent of a LINKED office, from this office's own state — and, failing that, its vault.

    The office that consumes renders the state block from the serving office's own catalog: the
    address is the peer's end of the pair (this office's view, derived — never something the peer
    publishes), and each app carries the second door of an agent (`agent_api_port`) and the authority
    it answers under.

    Reach is asked, not assumed (`_link_host`): the link's name where this process is on the office
    network, the peer's tunnel address where it is not.
    The vault instance is the contract's `dgo_link-<office>` when a catalog names one, the per-app
    instance the serving office's converge wrote otherwise; both are tried, and a miss says which
    names were looked for.
    """
    want = (office or "").strip().lower()
    for entry in _remote_blocks():
        off = str(entry.get("office") or "").strip()
        label = str(entry.get("label") or "")
        if isinstance(entry.get("label"), dict):
            label = str((entry["label"] or {}).get("en") or (entry["label"] or {}).get("he") or "")
        if want and want not in {off.lower(), label.lower()}:
            continue
        addr = str(entry.get("address") or "").strip()
        # THE office's agent first — the app declaring `office-agent` — and another agent.v1 app (bina-claude:
        # `claude-agent`) only where it is the one served. In file order `bina-claude` sorts before `bina`, so the HP's
        # update, which serves both, sent `--office hp-laptop` to bina-claude's door instead of Azaria (2026-11-03).
        apps = [a for a in (entry.get("apps") or []) if isinstance(a, dict)]
        apps.sort(key=lambda a: 0 if any(c.get("name") == "office-agent" and c.get("interface") == "agent.v1"
                                         for c in _manifest(str(a.get("app") or "")).get("capabilities") or []) else 1)
        for app in apps:
            aid = str(app.get("app") or "").strip()
            alias = str(app.get("alias") or aid).strip()
            port = int(app.get("agent_api_port") or 0)
            if not port:
                api = app.get("api") or {}
                port = int(api.get("port") or 0) if isinstance(api, dict) else 0
            port = port or _agent_port(_manifest(aid))
            if not (off and addr and aid and port):
                continue
            inst = str(app.get("instance") or entry.get("instance") or "").strip()
            cands = [i for i in (inst, AGENT_INSTANCE.format(office=off, app=aid),
                                 f"{PROTOCOL}-{off}", f"{PROTOCOL}-{off}-{aid}") if i]
            # The app's OWN door on the link (the screen's), for HarnessFallback: the office's link port and the
            # host the app answers under there. Kept as facts, dialled only if the agent door is not served.
            link_port = int(app.get("link_port") or entry.get("link_port") or 0)
            rpc = {"office": off, "alias": alias, "address": addr, "port": link_port,
                   "host": str(app.get("host") or f"{alias}.localhost")} if link_port else None
            return {"app": aid, "alias": alias, "port": port,
                    "service": f"dgo-serve-{off}-{alias}", "url": _link_url(alias, off, addr, port),
                    "served_by": off, "instances": cands, "instance": cands[0], "from": "state",
                    **({"rpc": rpc} if rpc else {})}
    # The state block is the primary answer; the credential plane is the fallback that works on a
    # machine whose compiler has not caught up (see _vault_provider).
    return _vault_provider(office)


def _served_provider() -> Optional[dict]:
    """The agent THIS office does not run itself, but SHOWS — with no office named (DGO-32).

    `serve:`/`remote:` in `platform.state.yaml` is the block layer 0 renders a route and a tile from —
    the office's own answer to "which apps of another office are reachable from here, and at which
    tunnel address". Discovery follows it for one reason: the owner's first use of a link is talking to
    the OTHER office's agent, and on that office nothing local provides `agent.v1` — so without this,
    `bbox agent` refuses on the very machine the feature exists for. `--office <id>` narrows it.
    """
    return remote_provider("")


def _peer_host(service: str) -> str:
    """How THIS process reaches an agent service: by its name from another container on the office
    network, by the host's loopback everywhere else — inside the provider itself, on the host, and in
    a container that cannot resolve the name (host networking, a CI runner, a devcontainer), where the
    loopback is what always worked."""
    if not os.path.exists("/.dockerenv") or socket.gethostname() == service:
        return "127.0.0.1"
    try:
        socket.gethostbyname(service)
        return service
    except OSError:
        return "127.0.0.1"


def _app_provider(app_id: str) -> Optional[dict]:
    """An agent.v1 provider named by its app id (`bbox agent --app bina-claude list`, DGO-1074).

    The office agent is the app whose capability is `office-agent`; another app may serve the same
    contract under a name of its own (bina-claude: `claude-agent`), so it never competes for the
    default. Addressed by id, any capability with `interface: agent.v1` is its door. From a container
    on the office network the door is the service itself; from the host it is the loopback port the
    compose file publishes, which every agent app publishes under the same number.
    """
    j = _manifest(app_id)
    for c in j.get("capabilities") or []:
        if c.get("interface") == "agent.v1" and c.get("endpoint"):
            m = re.match(r"https?://([^:/]+):?(\d+)?", str(c["endpoint"]))
            if not m:
                continue
            service, port = m.group(1), int(m.group(2) or 80)
            return {"app": j["id"], "service": service, "port": port, "url": f"http://{_peer_host(service)}:{port}"}
    return None


def provider(office: str = "", app: str = "") -> dict:
    """Where an agent is: this office's own, or the one a linked office serves (DGO-32).

    `office` names the far office explicitly (`bbox agent --office macbook list`); without it the
    local provider wins when there is one, and a served agent is the fallback. `app` names a local
    agent app by id (`--app bina-claude`), whatever its capability is called.
    """
    if app:
        if office:
            raise AgentError("--app names an agent app of THIS office; another office's agent is --office alone", 2)
        found = _app_provider(app)
        if found:
            return found
        raise AgentError(f"no app {app!r} here declares a capability with interface agent.v1 "
                         f"(apps/{app}/app.json)", 3)
    if office:
        remote = remote_provider(office)
        if remote:
            return remote
        raise AgentError(f"the office {office!r} is in neither this office's `remote:`/`serve:` block "
                         f"(platform.state.yaml) nor this office's vault (protocol `dgo_link`) — link "
                         f"it and converge, or read `GET /api/link` on dgo-extend for what is declared", 3)
    local = _local_provider()
    if local:
        # From ANOTHER container on the office network (bina-claude asking Azaria) the host's loopback
        # is that container's own: the door is the service, when its name resolves (_peer_host).
        host = _peer_host(local["service"])
        if host != "127.0.0.1":
            local["url"] = f"http://{host}:{local['port']}"
        return local
    served = _served_provider()
    if served:
        return served
    raise AgentError("no enabled app provides office-agent (agent.v1), and no `remote:`/`serve:` "
                     "entry names an office that serves one to this office", 3)


def _engine_cmd(args: list) -> list:
    """How to reach a docker CLI for the office's engine from THIS host."""
    if sys.platform == "darwin" and not os.environ.get("BBOX_IN_GUEST"):
        return ["bash", str(REPO / "packaging/macos/engine.sh"), "exec", "--", *args]
    return args


def _run(cmd: list, timeout: float = 120) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise AgentError(f"{' '.join(cmd[:3])}…: {p.stderr.strip()[-300:] or p.stdout.strip()[-300:]}", 3)
    return p.stdout.strip()


def obtain_token(prov: dict) -> str:
    """Read the action token out of the provider's container — once, through the engine.

    A provider that is SERVED to this office (DGO-32) has no container here: the app runs on the
    other side. Its token was handed to this office by the office that serves it, and it lives where
    every other credential of this office lives — the vault. Read through the engine for the same
    reason the local one is: the CLI runs on the machine that runs the office, and `docker exec` is
    the trust it already has.
    """
    if prov.get("instance"):
        return _vault_token(prov.get("instances") or [prov["instance"]], prov.get("served_by") or "")
    svc = prov["service"]
    # EVERY container carrying the app's compose label, not the first one: a self-update helper
    # (`bina-ds-self-update`, the previous image, kept for rollback) carries the same label and no
    # `AGENT_TOKEN_FILE`, so `docker ps -q … | head -1` reads the wrong container and the CLI reports
    # "the provider returned no action token" while the agent is running (measured 2026-10-01).
    script = (
        f"for c in $(docker ps -q --filter label=com.docker.compose.service={svc}); do "
        f"f=$(docker exec \"$c\" printenv AGENT_TOKEN_FILE 2>/dev/null || true); "
        f"if [ -n \"$f\" ]; then docker exec \"$c\" cat \"$f\" && exit 0; fi; done; "
        f"echo 'no running container of {svc} exposes AGENT_TOKEN_FILE' >&2; exit 1"
    )
    tok = _run(_engine_cmd(["sh", "-c", script]), timeout=240).splitlines()[-1].strip()
    if len(tok) < 32:
        raise AgentError("the provider returned no action token (is it running the agent.v1 adapter?)", 3)
    return tok


def _vault_token(instances, served_by: str = "") -> str:
    """One linked office's token from THIS office's vault, through the engine.

    Several candidate names, tried in order, because two conventions are live at once: the per-app
    instance the serving office's converge writes (`dgo_link-serve-<office>-<app>-agent`, DGO-32) and
    the per-office instance the remote-apps contract names (`dgo_link-<office>`). Which one exists is a
    fact of the deployment, not of this file — so it asks, and a miss names every name it tried
    instead of reporting "no token".
    """
    names = [str(i).strip() for i in (instances if isinstance(instances, (list, tuple)) else [instances]) if i]
    if not names:
        raise AgentError("the served provider names no vault instance", 3)
    # An agent credential names the office that gave it (`secret.office`): office and app ids are joined
    # with dashes, so `hp` + `laptop-bina-ds` names hp-laptop's row, and a row of another office is
    # never this office's token. sys.argv[2] is the office asked for ("" when not known).
    lookup = ("import json,urllib.request,sys;"
              "s=(json.load(urllib.request.urlopen("
              "'http://127.0.0.1:8990/api/instances/%s/secret' % sys.argv[1],timeout=20)"
              ").get('secret') or {});"
              "o=sys.argv[2] if len(sys.argv)>2 else '';"
              "print('' if (o and sys.argv[1].startswith('dgo_link-serve-') and s.get('office') "
              "and str(s.get('office'))!=o) else s.get('token',''))")
    b64 = base64.b64encode(lookup.encode()).decode()
    who = served_by if INSTANCE_RE.match(served_by or "") else ""     # read back through a shell: inert
    tok = ""
    for name in names:
        if not INSTANCE_RE.match(name):
            continue
        script = (
            "c=$(docker ps -q --filter label=com.docker.compose.service=connections | head -1); "
            "[ -n \"$c\" ] || { echo 'the vault container is not running' >&2; exit 1; }; "
            f"docker exec \"$c\" python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\" "
            f"{name} {who}"
        )
        try:
            got = _run(_engine_cmd(["sh", "-c", script]), timeout=240).splitlines()[-1].strip()
        except (AgentError, IndexError):
            continue
        if len(got) >= 32:
            return got
    raise AgentError(
        f"no credential for the agent of {served_by or 'the linked office'} in this office's vault — "
        f"tried {', '.join(names)}. This office's dgo-extend takes it over the link on its next "
        f"projection pass (DGO-1127) once both offices run it, the serving office's converge pushes it "
        f"(`bbox dgo converge <office>`), or the catalog names the instance the contract wants "
        f"(`dgo_link-<office>`)", 3)


# ── config ──────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)


def repo_key() -> str:
    return str(REPO)


# ── a linked office whose agent door is not served: its harness, through the link's app door ────────
#: Where a new session starts when none is named — the adapter's own default, a path every office's bina-ds keeps
#: (entrypoint.sh links it to the checkout).
HARNESS_OFFICE_ROOT = "/workspace/office"
HARNESS_FULL_ID = re.compile(r"^(session-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HARNESS_VERBS = "list, show, new, send, log, wait, rename, cancel and follow"


def _iso(ms) -> Optional[str]:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(float(ms) / 1000)) + ".000Z"
    except (TypeError, ValueError):
        return None


def harness_summary(s: dict) -> dict:
    """One harness session as agent.v1's row — the adapter's `summary()` (apps/bina-ds/adapter/server.mjs)."""
    v = ((s.get("projections") or {}).get("values")) or {}
    goal = (v.get("goal") or {}).get("goal")
    inbox = v.get("inbox") or {}
    return {
        "id": s.get("sessionId"), "title": v.get("title") or None, "running": bool(s.get("running")),
        "blank": bool(s.get("blank")), "cwd": s.get("cwd") or None, "updated_at": _iso(s.get("updatedAt")),
        "preset": v.get("agentPreset") or None, "permissions": (v.get("permissions") or {}).get("currentValue"),
        "model": (v.get("modelSelection") or {}).get("lastUsed") or (v.get("modelSelection") or {}).get("next"),
        "goal": {"objective": goal.get("objective"), "phase": goal.get("phase"), "rounds": (v.get("goal") or {}).get("roundsStarted"),
                 "max_rounds": goal.get("maxGoalRounds")} if goal else None,
        "todos": v.get("todos") or None, "turns": len(v.get("turnOutline") or []), "tokens": v.get("tokenUsage") or None,
        "queue": len(inbox.get("next-turn") or []) + len(inbox.get("next-step") or []), "stale": False,
    }


def _blocks_text(blocks) -> str:
    out = []
    for b in blocks or []:
        if isinstance(b, str):
            out.append(b)
        elif (b or {}).get("type") == "text":
            out.append(b.get("text") or "")
        elif (b or {}).get("type") in ("image", "file"):
            out.append(f"[{b['type']} {(b.get('attachment') or {}).get('name') or ''}]")
    return "".join(out)


def _args(s):
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except ValueError:
        return s


def harness_normalize(ev: dict) -> list:
    """One harness log event as agent.v1's compact events — the adapter's `normalize()`, type for type."""
    d = ev.get("data") or {}
    base = {"seq": ev.get("seq"), "at": _iso(ev["time"]) if isinstance(ev.get("time"), (int, float)) else ev.get("time"),
            "turn": d.get("turn"), "step": d.get("step")}
    t = ev.get("type")
    if t == "turn/start":
        return [{**base, "type": "turn.start"}]
    if t == "turn/end":
        return [{**base, "type": "turn.end", "reason": d.get("reason") or d.get("outcome")}]
    if t == "step/start":
        return [{**base, "type": "step.start"}]
    if t == "step/end":
        return [{**base, "type": "step.end"}]
    if t == "user/message":
        c = d.get("content") or (d.get("message") or {}).get("content") or []
        return [{**base, "type": "user", "text": _blocks_text(c), "source": (d.get("source") or {}).get("kind")}]
    if t == "assistant/message":
        out = []
        for b in (d.get("message") or {}).get("content") or []:
            if b.get("type") == "reasoning" and b.get("text"):
                out.append({**base, "type": "reasoning", "text": b["text"]})
            elif b.get("type") == "text" and b.get("text"):
                out.append({**base, "type": "assistant", "text": b["text"]})
            elif b.get("type") == "tool-call":
                out.append({**base, "type": "tool.call", "id": b.get("id"), "name": b.get("name"), "args": _args(b.get("arguments"))})
        return out
    if t == "tool/call":
        return [{**base, "type": "tool.call", "id": d.get("callId") or d.get("id"), "name": d["name"], "args": _args(d.get("arguments"))}] \
            if d.get("name") else []
    if t == "tool/result":
        m = d.get("message") or d
        content = m.get("content") or []
        blocks = [x for b in content for x in ((b.get("content") or []) if (b or {}).get("type") == "tool-result" else [b])]
        err = any((b or {}).get("type") == "tool-result" and b.get("isError") for b in content) or bool(d.get("isError"))
        return [{**base, "type": "tool.result", "id": (m.get("source") or {}).get("callId") or d.get("callId"),
                 "ok": not err, "text": _blocks_text(blocks)}]
    if t == "llm/retry":
        return [{**base, "type": "retry", "provider": d.get("provider"), "reason": d.get("reason") or (d.get("failure") or {}).get("message")}]
    if t == "llm/retry-started":
        return [{**base, "type": "retry.start", "attempt": d.get("retry")}]
    if t == "agent/inbox/spliced":
        txt = _blocks_text([c for i in d.get("inserted") or [] for c in (i.get("content") or [])])
        return [{**base, "type": "inbox", "target": d.get("target"), "text": txt}] if txt else []
    if t == "approval/asked":
        return [{**base, "type": "approval.asked", "request": d}]
    if t == "approval/decided":
        return [{**base, "type": "approval.decided", "decision": d.get("decision") or d}]
    if t == "goal/change":
        return [{**base, "type": "goal", "goal": d.get("goal") or d}]
    if t == "session/title":
        return [{**base, "type": "title", "title": d.get("title") or d.get("value")}]
    if t == "session/not-found":
        return [{**base, "type": "error", "code": t}]
    return []


class HarnessFallback:
    """agent.v1 answered from a linked office's HARNESS, through the link's app door (r030-204, DGO-1228).

    WHY. An office that fell behind serves no agent door — the door is newer code than it runs — so `bbox agent
    --office hp-laptop` met 502 (the HP, 761 commits behind, 2026-11-02), and the only way left to tell its agent
    «take dgo-stable» was the owner at the machine (rep-local-261102-201500). Its harness was there all along,
    behind the app the link already shares with this office: the screen speaks to it with `POST /api/<ns>/<method>`
    under the app's own Host and Origin, and so does this — the same door and the same trust as the screen, from
    this office's network (the relay the client already uses when this process is not on it).

    WHAT. The verbs that operate an office: list, show, new, send, log, wait, rename, cancel, and follow — each
    translated as the adapter translates it (apps/bina-ds/adapter/server.mjs), so the CLI renders the same thing.
    Reading the log is `session/page` against the newest sequence number, found by probing (the page refuses a
    sequence the log does not hold, and -1 is the empty cut); following is that read, repeated, because live tokens
    need the harness's websocket, which an HTTP door does not carry. Files, models, goals and the rest answer that
    they need the agent door, with the reason it is not served.
    """

    POLL = 3.0
    #: a follow gives up only after this many reads in a row failed (one slow relay hop is not the end of it)
    FAILS = 20

    def __init__(self, base: str, host: str, office: str, why: str, timeout: float = 240.0):
        self.base, self.host, self.office, self.why, self.timeout = base.rstrip("/"), host, office, why, timeout
        self._items: Optional[list] = None
        self._listed_at = 0.0
        #: per session, the newest sequence BEFORE this run prompted it: a follow that opens right after a send starts
        #: there, so the turn the send began is seen from its start (it may have started before the follow looked)
        self._marks: dict = {}

    # ── the wire
    def rpc_result(self, method: str, args: dict, timeout: Optional[float] = None) -> dict:
        """The harness's `result` ({ok, value | error}); raises only when its door did not answer."""
        body = json.dumps({"type": "client-request", "rpcId": str(uuid.uuid4()), "method": method,
                           "payload": {"args": args}}).encode()
        req = urllib.request.Request(f"{self.base}/api/{method}", data=body, method="POST",
                                     headers={"content-type": "application/json", "Host": self.host,
                                              "Origin": f"http://{self.host}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return (json.loads(r.read() or b"{}") or {}).get("result") or {}
        except urllib.error.HTTPError as e:
            raise AgentError(f"{self.office}'s harness answered HTTP {e.code} to {method} through its app door "
                             f"({e.headers.get('X-Dgo-Door') or e.reason})", 5 if e.code in (401, 403) else 3, http=e.code)
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            raise AgentError(f"{self.office}'s harness did not answer {method} through its app door ({e})", 3)

    def rpc(self, method: str, args: dict, timeout: Optional[float] = None):
        res = self.rpc_result(method, args, timeout)
        if res.get("ok") is not True:
            # an answer that does not SAY it worked did not work: "queued" must never be printed for a message
            # the harness never took
            err = res.get("error") or {"code": "harness/no-result", "message": f"{method} answered without a result"}
            code = str(err.get("code") or "harness/error")
            http_status = 404 if "not-found" in code else 400 if re.search(r"bad-request|invalid", code) else 502
            raise AgentError(str(err.get("message") or code), {404: 4, 400: 2}.get(http_status, 1),
                             http=http_status, detail=code)
        return res.get("value")

    # ── sessions
    def items(self, fresh: bool = False) -> list:
        """The harness's own list — its most expensive call (15 s for 271 sessions on the HP), so once per run, and a
        `fresh` read within seconds of the last one is that one."""
        if self._items is None or (fresh and time.time() - self._listed_at > 5):
            self._items = list((self.rpc("session/list", {"_request": {}}, max(self.timeout, 600)) or {}).get("items") or [])
            self._listed_at = time.time()
        return self._items

    def resolve(self, given: str) -> str:
        if HARNESS_FULL_ID.match(given):
            return given
        items = self.items()
        exact = [s for s in items if s.get("sessionId") == given]
        hits = exact or [s for s in items if str(s.get("sessionId") or "").startswith((given, "session-" + given))]
        if len(hits) == 1:
            return hits[0]["sessionId"]
        if hits:
            raise AgentError(f"{len(hits)} sessions match {given!r}", 6, http=409)
        raise AgentError(f"no session {given}", 4, http=404)

    def page(self, sid: str, through: int, max_messages: int, before: Optional[int] = None) -> dict:
        req = {"address": {"kind": "session", "sessionId": sid}, "throughSeq": int(through), "maxMessages": int(max_messages)}
        if before is not None:
            req["beforeSeq"] = int(before)
        return self.rpc("session/page", {"request": req}) or {}

    def _holds(self, sid: str, seq: int) -> bool:
        """Does the log hold `seq`? Only a page that CONTAINS it says yes — an answer without it is a no."""
        try:
            recs = self.page(sid, seq, 1).get("records") or []
        except AgentError as e:
            if e.detail and "bad-request" in e.detail:
                return False            # the log does not hold that sequence (yet)
            raise
        return any(((r or {}).get("event") or {}).get("seq") == seq for r in recs)

    def latest_seq(self, sid: str, hint: int = -1) -> int:
        """The newest sequence the session's log holds, -1 for an empty log.

        One call: a page asked far past the end is refused with the cursor in the refusal («past cursor N» — the same
        reading apps/project-pln/report.py does). Every RPC here is a hop through the engine when relayed, so that one
        call is the norm; doubling-then-halving from `hint` is the backup for a harness that words it otherwise."""
        res = self.rpc_result("session/page", {"request": {"address": {"kind": "session", "sessionId": sid},
                                                           "throughSeq": 10 ** 9, "maxMessages": 1}})
        if res.get("ok") is not True:
            err = res.get("error") or {}
            past = re.search(r"past cursor (-?\d+)", json.dumps(err))
            if past:
                return int(past.group(1))
            if "not-found" in str(err.get("code") or ""):
                raise AgentError(str(err.get("message") or f"no session {sid}"), 4, http=404, detail=str(err.get("code")))
        lo = hint if hint >= 0 and self._holds(sid, hint) else 0
        if lo == 0 and not self._holds(sid, 0):
            return -1
        step, hi = 1, lo + 1
        while hi < 10 ** 7 and self._holds(sid, hi):
            lo, step = hi, step * 2
            hi = lo + step
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if self._holds(sid, mid) else (lo, mid)
        return lo

    def events_after(self, sid: str, cursor: int, latest: int) -> list:
        """Every log event with cursor < seq <= latest, oldest first — pages sized to what is new."""
        got: dict = {}
        before = None
        while True:
            v = self.page(sid, latest, max(1, min(200, latest - cursor)), before)
            seqs = []
            for r in v.get("records") or []:
                ev = (r or {}).get("event")
                if (r or {}).get("type") == "event" and ev and isinstance(ev.get("seq"), int):
                    seqs.append(ev["seq"])
                    if ev["seq"] > cursor:
                        got[ev["seq"]] = ev
            if not seqs or min(seqs) <= cursor + 1 or not v.get("hasMore") \
                    or (before is not None and min(seqs) >= before):      # no progress: never loop on one page
                break
            before = min(seqs)
        return [got[k] for k in sorted(got)]

    def prompt(self, sid: str, text, files, steer: bool) -> None:
        if files:
            raise AgentError(f"files cannot reach {self.office} while its agent door is not served ({self.why}) — "
                             f"send the text alone", 2)
        if not str(text or "").strip():
            raise AgentError("text required", 2, http=400)
        if sid not in self._marks:
            self._marks[sid] = self.latest_seq(sid)
        self.rpc("session/prompt", {"request": {
            "requestId": str(uuid.uuid4()), "sessionId": sid, "mode": "steer" if steer else "queue",
            "content": [{"type": "text", "text": str(text)}],
            # the office's own zone — the adapter's TZ there — not whatever this machine says
            "clientTimeZone": "Asia/Jerusalem"}})

    def unsupported(self, what: str):
        raise AgentError(f"`{what}` needs {self.office}'s agent door, which is not served ({self.why}). Over its harness "
                         f"this CLI speaks {HARNESS_VERBS}; the rest comes back when the office takes dgo-stable", 3)

    # ── agent.v1, translated
    def call(self, method: str, path: str, body=None) -> dict:
        from urllib.parse import parse_qs, urlsplit
        u = urlsplit(path)
        p, q = (u.path.rstrip("/") or "/"), parse_qs(u.query)
        fresh = (q.get("fresh") or [""])[0] == "1"
        b = body or {}
        if method == "GET" and p == "/v1/sessions":
            return {"sessions": [harness_summary(s) for s in self.items(fresh)], "partial": False}
        if method == "POST" and p == "/v1/sessions":
            req = {"cwd": b.get("cwd") or HARNESS_OFFICE_ROOT, **({"agentPreset": b["preset"]} if b.get("preset") else {})}
            created = self.rpc("session/create", {"request": req}) or {}
            sid = created.get("sessionId")
            if not sid:
                raise AgentError(f"{self.office}'s harness created no session", 1)
            self._marks[sid] = -1           # new: everything in its log is this run's
            if b.get("title"):
                try:
                    self.rpc("session/rename", {"request": {"sessionId": sid, "title": str(b["title"])}})
                except AgentError:
                    pass                # the session is there; its name is cosmetic
            if b.get("text") or b.get("files"):
                self.prompt(sid, b.get("text"), b.get("files"), False)
            self._items = None
            return {"id": sid, "preset": created.get("agentPreset")}
        m = re.match(r"^/v1/sessions/([A-Za-z0-9_.\-]+)(?:/([a-z]+))?$", p)
        if not m:
            self.unsupported(f"{method} {p}")
        sid, sub = self.resolve(m.group(1)), m.group(2) or ""
        if not sub and method == "GET":
            s = next((x for x in self.items(fresh) if x.get("sessionId") == sid), None)
            if not s:
                raise AgentError(f"no session {sid}", 4, http=404)
            return harness_summary(s)
        if sub == "messages" and method == "POST":
            self.prompt(sid, b.get("text"), b.get("files"), bool(b.get("steer")))
            return {"accepted": True, "id": sid}
        if sub == "messages" and method == "GET":
            limit = max(1, min(500, int((q.get("limit") or ["20"])[0] or 20)))
            latest = self.latest_seq(sid)
            recs = (self.page(sid, latest, limit).get("records") or []) if latest >= 0 else []
            evs = [e for r in recs if (r or {}).get("type") == "event" and r.get("event") for e in harness_normalize(r["event"])]
            return {"id": sid, "has_more": False, "events": evs}
        if sub == "rename" and method == "POST":
            if not b.get("title"):
                raise AgentError("title is required", 2, http=400)
            self.rpc("session/rename", {"request": {"sessionId": sid, "title": str(b["title"])}})
            self._items = None
            return {"id": sid, "title": str(b["title"])}
        if sub == "cancel" and method == "POST":
            self.rpc("session/cancel", {"request": {"sessionId": sid}})
            return {"accepted": True, "id": sid}
        self.unsupported(f"{method} {p}")

    def events(self, path: str) -> Iterator[dict]:
        """The adapter's follow stream, rebuilt from the log: `open`, the `snapshot` asked for, then each new event as
        it lands (read every POLL seconds)."""
        from urllib.parse import parse_qs, urlsplit
        u = urlsplit(path)
        q = parse_qs(u.query)
        m = re.match(r"^/v1/sessions/([A-Za-z0-9_.\-]+)/events$", u.path.rstrip("/"))
        if not m or (q.get("raw") or [""])[0] == "1":
            self.unsupported(f"GET {u.path}" + (" (raw)" if m else ""))
        sid = self.resolve(m.group(1))
        history = max(0, min(500, int((q.get("history") or ["0"])[0] or 0)))
        since = int((q.get("since") or ["-1"])[0] or -1)
        latest = self.latest_seq(sid)
        yield {"event": "open", "data": {"id": sid, "since": since, "history": history, "raw": False, "stream": False}, "id": None}
        # the snapshot always comes, empty when no history was asked — as the harness's own follow opens
        recs = (self.page(sid, latest, history).get("records") or []) if history and latest >= 0 else []
        evs = [e for r in recs if (r or {}).get("type") == "event" and r.get("event") and r["event"].get("seq", -1) > since
               for e in harness_normalize(r["event"])]
        yield {"event": "snapshot", "data": {"id": sid, "header": None, "cursor": latest, "events": evs}, "id": None}
        cursor = max(latest, since)
        if since < 0 and not history and sid in self._marks:
            cursor = min(cursor, self._marks.pop(sid))   # right after a send: from where the send found the log
            yield from self._new_events(sid, cursor, latest)
            cursor = latest
        fails = 0
        while True:
            time.sleep(self.POLL)
            try:
                now = self.latest_seq(sid, cursor)
                batch = list(self._new_events(sid, cursor, now)) if now > cursor else []
            except AgentError as e:
                # reads only: retried, and given up after FAILS of them failed in a row, never at the first slow hop —
                # but a session that is gone (4) or a door that refuses this office (5) will not come back by waiting
                if e.code in (4, 5):
                    raise
                fails += 1
                if fails >= self.FAILS:
                    raise AgentError(f"following {sid} on {self.office}: {self.FAILS} reads in a row failed ({e.message})", 3)
                continue
            fails = 0
            yield from batch
            cursor = max(cursor, now)

    def _new_events(self, sid: str, cursor: int, latest: int) -> Iterator[dict]:
        if latest <= cursor:
            return
        for ev in self.events_after(sid, cursor, latest):
            for e in harness_normalize(ev):
                yield {"event": e["type"], "data": e, "id": str(ev.get("seq"))}


class Client:
    """One office agent provider, reached over agent.v1.

    `office` names a LINKED office whose agent is wanted (`bbox agent --office macbook list`): the
    provider is then resolved through this office's own `remote:`/`serve:` block, and the cached
    per-repo entry is deliberately NOT used — a URL cached for the local agent would answer for the
    wrong office, which is the one failure this flag exists to avoid.
    """

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None, timeout: float = 240.0,
                 office: str = "", app: str = ""):
        self.timeout = timeout
        self.office = (office or "").strip().lower()
        self.app = (app or "").strip().lower()
        self.cfg_all = load_config()
        # A remote office's entry lives under its own key: one office's URL and token must never be
        # used for another's, and the plain repo key belongs to THIS office's own agent. An agent app
        # named by `--app` has its own key for the same reason.
        self.cfg_key = f"{repo_key()}::{self.office}" if self.office \
            else (f"{repo_key()}::app:{self.app}" if self.app else repo_key())
        entry = self.cfg_all.get(self.cfg_key) or {}
        self.url = (url or os.environ.get("BBOX_AGENT_URL") or entry.get("url") or DEFAULT_URL).rstrip("/")
        self.explicit_url = bool(url or os.environ.get("BBOX_AGENT_URL"))    # `--url` wins, at login too
        self.provider_cache: Optional[dict] = None
        if self.office or self.app:
            prov = provider(self.office, self.app)  # raises with the office/app named when nothing matches
            self.provider_cache = prov
            if not url and not os.environ.get("BBOX_AGENT_URL"):
                # The DECLARED address always wins over a cache: it is what this office's own state
                # says the peer is at now, and a link whose address moved must not be addressed at
                # where it used to be.
                self.url = str(prov["url"]).rstrip("/")
        elif not (url or os.environ.get("BBOX_AGENT_URL") or entry.get("url")):
            # Discovery may know a URL the convention does not (DGO-32: an agent served by a linked
            # office answers on that office's tunnel address, not on this host's loopback). A
            # discovery failure is not fatal HERE — `login()` reports it with its own sentence, and
            # `bbox agent doctor` has to be able to say "there is no provider" at all.
            try:
                self.url = (provider().get("url") or DEFAULT_URL).rstrip("/")
            except AgentError:
                pass
        self.token = token or os.environ.get("BBOX_AGENT_TOKEN") or entry.get("token")
        self.explicit_token = bool(token or os.environ.get("BBOX_AGENT_TOKEN"))
        self.token_source = "flag/env" if self.explicit_token else ("cache" if entry.get("token") else "none")
        self.fallback: Optional[HarnessFallback] = None

    # ── a linked office whose agent door is not served (r030-204)
    def _fall_back(self, why: str) -> bool:
        """Answer the rest of this run from the linked office's harness, through the link's app door
        (HarnessFallback). Only for `--office`, only once, and only when the state names that door."""
        if self.fallback:
            return True
        rpc = (self.provider_cache or {}).get("rpc") if self.office else None
        if not rpc or os.environ.get("BBOX_AGENT_NO_FALLBACK"):
            return False
        base = _link_url(rpc["alias"], rpc["office"], rpc["address"], int(rpc["port"]))
        self.fallback = HarnessFallback(base, rpc["host"], rpc["office"], why, self.timeout)
        sys.stderr.write(f"agent: {rpc['office']}'s agent door is not served ({why}) — answering from its harness "
                         f"through the link's app door ({HARNESS_VERBS})\n")
        return True

    @staticmethod
    def _door_unserved(e: urllib.error.HTTPError) -> bool:
        """The LINK answered for the agent's door: the office is there, the door is not (`X-Dgo-Door: app-down`,
        apps/dgo-extend/link-proxy.py). An answer from the agent itself — whatever its status — never is: a
        message it took must not be sent twice."""
        return e.code == 502 and str((e.headers or {}).get("X-Dgo-Door") or "") == "app-down"

    def _via_fallback(self, method: str, path: str, body=None, raw: Optional[bytes] = None):
        if raw is not None:
            self.fallback.unsupported("upload")
        return self.fallback.call(method, path, body)

    # ── auth
    def login(self, force: bool = False) -> dict:
        prov = self.provider_cache or provider(self.office)
        if prov.get("url") and not self.explicit_url:
            self.url = str(prov["url"]).rstrip("/")     # a served provider answers at its own address
        if force or not self.token:
            self.token = obtain_token(prov)
            self.token_source = "engine"
        entry = {"url": self.url, "token": self.token, "provider": prov["app"], "obtained_at": int(time.time())}
        if self.url in _relays.values():
            # A relay lives as long as this process: a URL saved for the next run would be a dead port, or
            # one another program has taken by then, and that program would be handed the token.
            entry.pop("url")
        if prov.get("served_by"):
            entry["served_by"] = prov["served_by"]
        # A remote office's (or a named app's) URL and token are cached under its own key: the plain
        # repo key belongs to the local agent, and one office's token must never be presented to another's.
        self.cfg_all[self.cfg_key] = entry
        save_config(self.cfg_all)
        return {"url": self.url, "provider": prov["app"], "config": str(CONFIG_PATH),
                **({"office": self.office} if self.office else {}),
                **({"served_by": prov["served_by"]} if prov.get("served_by") else {})}

    def ensure_token(self) -> None:
        if not self.token:
            self.login()

    # ── one call
    def _request(self, method: str, path: str, body=None, raw: Optional[bytes] = None, content_type: Optional[str] = None,
                 timeout: Optional[float] = None, stream: bool = False):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"authorization": f"Bearer {self.token}"} if self.token else {}
        if data is not None:
            headers["content-type"] = content_type or "application/json"
        if stream:
            headers["accept"] = "text/event-stream"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        return urllib.request.urlopen(req, timeout=timeout or self.timeout)

    def call(self, method: str, path: str, body=None, raw: Optional[bytes] = None, content_type: Optional[str] = None,
             timeout: Optional[float] = None, _retry: bool = True):
        if self.fallback and path.split("?")[0] != "/v1/health":
            return self._via_fallback(method, path, body, raw)
        if path != "/v1/health":
            try:
                self.ensure_token()
            except AgentError as e:
                # no token for a linked office's agent: its door would refuse anyway — its harness need not
                if path.split("?")[0] != "/v1/health" and self._fall_back(f"no token for its agent here: {e.message[:160]}"):
                    return self._via_fallback(method, path, body, raw)
                raise
        try:
            with self._request(method, path, body, raw, content_type, timeout) as r:
                text = r.read()
                return json.loads(text or b"{}")
        except urllib.error.HTTPError as e:
            # `health` asks about the AGENT door itself: it is answered by that door (or its absence), never elsewhere
            usable = path.split("?")[0] != "/v1/health"
            if usable and self._door_unserved(e) and self._fall_back(f"the link answered {e.code} app-down for it"):
                return self._via_fallback(method, path, body, raw)
            try:
                err = json.loads(e.read())
            except ValueError:
                err = {"error": str(e)}
            if e.code == 401 and _retry and not self.explicit_token:
                try:
                    self.login(force=True)
                except AgentError:
                    pass                    # no fresh token to be had here: the 401 below decides
                else:
                    return self.call(method, path, body, raw, content_type, timeout, _retry=False)
            # the door refused this office's token even fresh from the vault (it changed there, and the link has not
            # handed the new one over): refused before anything ran, so its harness may answer instead
            if e.code == 401 and usable and self._fall_back("its agent door refused this office's token (401)"):
                return self._via_fallback(method, path, body, raw)
            code = {404: 4, 401: 5, 409: 6}.get(e.code, 1)
            raise AgentError(f"{err.get('error') or e.reason}", code, http=e.code, detail=err.get("code"))
        except urllib.error.URLError as e:
            # Never connected — nothing reached the agent. urllib also wraps an error raised while SENDING in URLError,
            # so a write goes the other way only on a connection that never opened (refused, or a name that did not resolve).
            never = isinstance(e.reason, (ConnectionRefusedError, socket.gaierror))
            if path.split("?")[0] != "/v1/health" and (method == "GET" or never) and self._fall_back(f"{self.url} unreachable ({e.reason})"):
                return self._via_fallback(method, path, body, raw)
            raise AgentError(f"provider unreachable at {self.url} ({e.reason}) — is the office up? try: bbox agent doctor", 3)
        except (socket.timeout, TimeoutError):
            raise AgentError(f"no answer from {self.url}{path} within {timeout or self.timeout:.0f}s — the engine is overloaded "
                             "or the harness is busy; retry, or raise --timeout", 3)
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            # a port that accepts and then drops (a forwarder whose far end is gone) shows up here. A READ may go to the
            # harness instead; a write may already have reached the agent, so it is not sent a second way.
            if method == "GET" and path.split("?")[0] != "/v1/health" and self._fall_back(f"{self.url} dropped the connection ({type(e).__name__})"):
                return self._via_fallback(method, path, body, raw)
            raise AgentError(f"the connection to {self.url} dropped before an answer ({type(e).__name__}) — "
                             "the provider's port is not being served on this host; try: bbox agent doctor", 3)

    # ── server-sent events
    def events(self, path: str) -> Iterator[dict]:
        """Yield {'event','data','id'} per SSE message, until the server ends the stream."""
        if self.fallback:
            yield from self.fallback.events(path)
            return
        try:
            self.ensure_token()
        except AgentError as e:
            if self._fall_back(f"no token for its agent here: {e.message[:160]}"):
                yield from self.fallback.events(path)
                return
            raise
        try:
            resp = self._request("GET", path, timeout=None, stream=True)
        except urllib.error.HTTPError as e:
            if self._door_unserved(e) and self._fall_back(f"the link answered {e.code} app-down for it"):
                yield from self.fallback.events(path)
                return
            resp = None
            if e.code == 401 and not self.explicit_token:
                try:
                    self.login(force=True)
                    resp = self._request("GET", path, timeout=None, stream=True)
                except AgentError:
                    pass                    # no fresh token to be had here
                except urllib.error.HTTPError as again:
                    e = again
                except (urllib.error.URLError, http.client.HTTPException, OSError) as gone:
                    raise AgentError(f"the connection to {self.url} failed after a fresh token ({type(gone).__name__})", 3)
            if resp is None:
                if ((e.code == 401 and self._fall_back("its agent door refused this office's token (401)"))
                        or (self._door_unserved(e) and self._fall_back(f"the link answered {e.code} app-down for it"))):
                    yield from self.fallback.events(path)
                    return
                raise AgentError(f"{e.reason}", {404: 4, 401: 5}.get(e.code, 1), http=e.code)
        except urllib.error.URLError as e:
            if self._fall_back(f"{self.url} unreachable ({e.reason})"):
                yield from self.fallback.events(path)
                return
            raise AgentError(f"provider unreachable at {self.url} ({e.reason})", 3)
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            if self._fall_back(f"{self.url} dropped the connection ({type(e).__name__})"):
                yield from self.fallback.events(path)
                return
            raise AgentError(f"the connection to {self.url} dropped before the stream opened ({type(e).__name__}); try: bbox agent doctor", 3)
        ev, data, eid = None, [], None
        with resp:
            for line in resp:
                line = line.decode("utf-8", "replace").rstrip("\r\n")
                if line == "":
                    if ev or data:
                        payload = "\n".join(data)
                        try:
                            parsed = json.loads(payload) if payload else None
                        except ValueError:
                            parsed = payload
                        yield {"event": ev or "message", "data": parsed, "id": eid}
                    ev, data, eid = None, [], None
                    continue
                if line.startswith(":"):
                    continue
                key, _, val = line.partition(":")
                val = val[1:] if val.startswith(" ") else val
                if key == "event":
                    ev = val
                elif key == "data":
                    data.append(val)
                elif key == "id":
                    eid = val

    # ── convenience
    def health(self, deep: bool = False) -> dict:
        # 30 s is the adapter's own budget; through `_relay` each connection first crosses the engine
        # (15–44 s on the MacBook, 2026-11-02), so that hop gets the run's own timeout on top
        budget = 30 + (self.timeout if self.url in _relays.values() else 0)
        try:
            return self.call("GET", "/v1/health" + ("?deep=1" if deep else ""), timeout=budget)
        except AgentError as e:
            if e.http == 502:
                # the adapter answered (502 = its harness is down): still a health answer
                return {"ok": False, "error": e.message}
            raise

    def sessions(self, fresh: bool = False) -> list:
        return self.call("GET", "/v1/sessions" + ("?fresh=1" if fresh else ""))["sessions"]

    def session(self, sid: str, fresh: bool = False) -> dict:
        return self.call("GET", f"/v1/sessions/{sid}" + ("?fresh=1" if fresh else ""))

    def upload(self, sid: str, path: Path) -> dict:
        data = path.read_bytes()
        from urllib.parse import quote
        return self.call("POST", f"/v1/sessions/{sid}/upload?name={quote(path.name)}", raw=data,
                         content_type="application/octet-stream", timeout=max(self.timeout, 600))
