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

import base64
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    return out


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
        addr = str(sec.get("address") or "").strip()
        port = int(sec.get("port") or 0)
        appid = str(sec.get("app") or "")
        if not (addr and port):
            continue
        alias = str(sec.get("alias") or appid or "bina")
        return {"app": appid or "bina-ds", "alias": alias,
                "port": port, "service": f"dgo-serve-{sec.get('office')}-{appid}",
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
        for app in (entry.get("apps") or []):
            if not isinstance(app, dict):
                continue
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
            return {"app": aid, "alias": alias, "port": port,
                    "service": f"dgo-serve-{off}-{alias}", "url": f"http://{_link_host(alias, off, addr)}:{port}",
                    "served_by": off, "instances": cands, "instance": cands[0], "from": "state"}
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


def provider(office: str = "") -> dict:
    """Where an agent is: this office's own, or the one a linked office serves (DGO-32).

    `office` names the far office explicitly (`bbox agent --office macbook list`); without it the
    local provider wins when there is one, and a served agent is the fallback.
    """
    if office:
        remote = remote_provider(office)
        if remote:
            return remote
        raise AgentError(f"the office {office!r} is in neither this office's `remote:`/`serve:` block "
                         f"(platform.state.yaml) nor this office's vault (protocol `dgo_link`) — link "
                         f"it and converge, or read `GET /api/link` on dgo-extend for what is declared", 3)
    local = _local_provider()
    if local:
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
    lookup = ("import json,urllib.request,sys;"
              "print((json.load(urllib.request.urlopen("
              "'http://127.0.0.1:8990/api/instances/%s/secret' % sys.argv[1],timeout=20)"
              ").get('secret') or {}).get('token',''))")
    b64 = base64.b64encode(lookup.encode()).decode()
    tok = ""
    for name in names:
        if not INSTANCE_RE.match(name):
            continue
        script = (
            "c=$(docker ps -q --filter label=com.docker.compose.service=connections | head -1); "
            "[ -n \"$c\" ] || { echo 'the vault container is not running' >&2; exit 1; }; "
            f"docker exec \"$c\" python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\" "
            f"{name}"
        )
        try:
            got = _run(_engine_cmd(["sh", "-c", script]), timeout=240).splitlines()[-1].strip()
        except (AgentError, IndexError):
            continue
        if len(got) >= 32:
            return got
    raise AgentError(
        f"no credential for the agent of {served_by or 'the linked office'} in this office's vault — "
        f"tried {', '.join(names)}. The office that serves it hands it over on a converge with the "
        f"link (`bbox dgo converge <office>`), or the catalog names the instance the contract wants "
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


class Client:
    """One office agent provider, reached over agent.v1.

    `office` names a LINKED office whose agent is wanted (`bbox agent --office macbook list`): the
    provider is then resolved through this office's own `remote:`/`serve:` block, and the cached
    per-repo entry is deliberately NOT used — a URL cached for the local agent would answer for the
    wrong office, which is the one failure this flag exists to avoid.
    """

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None, timeout: float = 240.0,
                 office: str = ""):
        self.timeout = timeout
        self.office = (office or "").strip().lower()
        self.cfg_all = load_config()
        # A remote office's entry lives under its own key: one office's URL and token must never be
        # used for another's, and the plain repo key belongs to THIS office's own agent.
        entry = (self.cfg_all.get(f"{repo_key()}::{self.office}") or {}) if self.office \
            else (self.cfg_all.get(repo_key()) or {})
        self.url = (url or os.environ.get("BBOX_AGENT_URL") or entry.get("url") or DEFAULT_URL).rstrip("/")
        self.explicit_url = bool(url or os.environ.get("BBOX_AGENT_URL"))    # `--url` wins, at login too
        self.provider_cache: Optional[dict] = None
        if self.office:
            prov = provider(self.office)          # raises with the office named when nothing matches
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

    # ── auth
    def login(self, force: bool = False) -> dict:
        prov = self.provider_cache or provider(self.office)
        if prov.get("url") and not self.explicit_url:
            self.url = str(prov["url"]).rstrip("/")     # a served provider answers at its own address
        if force or not self.token:
            self.token = obtain_token(prov)
            self.token_source = "engine"
        entry = {"url": self.url, "token": self.token, "provider": prov["app"], "obtained_at": int(time.time())}
        if prov.get("served_by"):
            entry["served_by"] = prov["served_by"]
        if self.office:
            # A remote office's URL and token are cached under its own key: the plain repo key belongs
            # to the local agent, and one office's token must never be presented to another's.
            self.cfg_all[f"{repo_key()}::{self.office}"] = entry
        else:
            self.cfg_all[repo_key()] = entry
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
        if path != "/v1/health":
            self.ensure_token()
        try:
            with self._request(method, path, body, raw, content_type, timeout) as r:
                text = r.read()
                return json.loads(text or b"{}")
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
            except ValueError:
                err = {"error": str(e)}
            if e.code == 401 and _retry and not self.explicit_token:
                self.login(force=True)
                return self.call(method, path, body, raw, content_type, timeout, _retry=False)
            code = {404: 4, 401: 5, 409: 6}.get(e.code, 1)
            raise AgentError(f"{err.get('error') or e.reason}", code, http=e.code, detail=err.get("code"))
        except urllib.error.URLError as e:
            raise AgentError(f"provider unreachable at {self.url} ({e.reason}) — is the office up? try: bbox agent doctor", 3)
        except (socket.timeout, TimeoutError):
            raise AgentError(f"no answer from {self.url}{path} within {timeout or self.timeout:.0f}s — the engine is overloaded "
                             "or the harness is busy; retry, or raise --timeout", 3)
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            # a port that accepts and then drops (a forwarder whose far end is gone) shows up here
            raise AgentError(f"the connection to {self.url} dropped before an answer ({type(e).__name__}) — "
                             "the provider's port is not being served on this host; try: bbox agent doctor", 3)

    # ── server-sent events
    def events(self, path: str) -> Iterator[dict]:
        """Yield {'event','data','id'} per SSE message, until the server ends the stream."""
        self.ensure_token()
        try:
            resp = self._request("GET", path, timeout=None, stream=True)
        except urllib.error.HTTPError as e:
            if e.code == 401 and not self.explicit_token:
                self.login(force=True)
                resp = self._request("GET", path, timeout=None, stream=True)
            else:
                raise AgentError(f"{e.reason}", {404: 4}.get(e.code, 1), http=e.code)
        except urllib.error.URLError as e:
            raise AgentError(f"provider unreachable at {self.url} ({e.reason})", 3)
        except (http.client.HTTPException, ConnectionError, OSError) as e:
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
        try:
            return self.call("GET", "/v1/health" + ("?deep=1" if deep else ""), timeout=30)
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
