"""computers — the office's fleet of machines, as ONE platform service.

What this app is
----------------
The office runs on more than one machine: the host that runs the deployment itself (inside the
engine's network), and any number of servers the owner attaches over SSH. Until now each of those
was reachable only by whoever happened to hold the key and remember the address, which meant every
consumer — the console, another app, the office agent — had its own private idea of what a machine
is. This app makes the fleet a first-class noun.

Where the facts live (and where they deliberately do not)
---------------------------------------------------------
EVERY machine is a connection INSTANCE in the credential plane
(`platform-base/connections`, the vault), protocol `computer_ssh`, secret `{host, port, user, …}`.
That is the whole design, and it is the same one drive and mail use (ai/context/
platform-service-contract.md §1): the vault is the one copy of the fleet, the console renders its
instance switcher from the service contract, and an app never holds a machine's address in its own
config. Nothing about a machine lives in a table of ours; there is no database here at all.

The one thing this service DOES own is the key that opens them — `office_key`, an ed25519 keypair
minted once into the app's own volume (/data). It is not the owner's personal key and it is not
shared with any other app: it is the office's own credential, and the owner approves its PUBLIC
half on each machine, one machine at a time, with the ordinary SSH mechanism (`authorized_keys`).
The UI shows the public key and the exact command that approves it. That is the supported way to
add a machine — there is no password auth, no ssh-agent in the container, and no `sshpass`.

The local machine
-----------------
The host that runs the deployment is built in as the instance `computer_local-local` ("המחשב הזה"),
never deletable: it is how the office reaches the machine it is running on. Its address is the
GATEWAY of the `traefik-network` bridge, read from the engine at startup rather than hardcoded
(it is 172.18.0.1 here, and it is not that everywhere). Until its key is approved it reports
"ממתין לאישור" — a real state, not an error.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import requests
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("computers")

# ── the fourth channel: what ran on a computer, on `dgo:flow:computers` (flow.v1, DGO-1797) ─────────
# Through the office's ONE publisher, platform-base/redis/flowpub.py, mounted read-only at /opt/dgo
# (docker-compose.yml): «כל מקביל» draws every command as a bar on the row «מחשבים», and agents hear it
# (`./bbox computers flow`). What goes out is which computer, who asked, the command's FIRST WORD, its exit
# and its time — never the rest of the line (an argument may carry a secret), its stdin or its output. An
# image run without the mount publishes nothing and works the same.
sys.path.insert(0, "/opt/dgo")
try:
    import flowpub  # noqa: E402
except ImportError:
    flowpub = None

_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PROGRAM = re.compile(r"[A-Za-z0-9._+-]{1,40}")
_SPANS = re.compile(r"[$`(){}\\]")          # a value that can run on into the next words: $(…), `…`, ( … ), ${…}, \


def _first_word(command: str) -> str:
    r"""The program a command runs, for its bar — or «sh». Words are split as a shell splits them (a quoted
    `AUTH="Bearer <token>" curl` is ONE assignment, skipped), a path keeps its last part, and only a plain
    program name goes out. Anything else is said as «sh», never as its text: a word with a quote, `$`, `(`,
    `;` or `=` left in it (a subshell, a substitution, a second command), and every command whose leading
    assignment holds `$ \` ( ) { } \\` — such a value can span words a shell joins and shlex does not
    (`TOKEN=$(echo <secret> | base64) curl`), so the word after it may still be the value (DGO-1797, second
    and third readers). Only the first 8 KB is read: a long command must not hold the event loop."""
    try:
        words = shlex.split(command[:8192], comments=False, posix=True)
    except ValueError:                                  # an unbalanced quote: nothing of it is a name
        return "sh"
    for word in words:
        if _ASSIGN.match(word):
            if _SPANS.search(word):
                return "sh"
            continue
        name = word.rsplit("/", 1)[-1]
        return name if _PROGRAM.fullmatch(name) else "sh"
    return "sh"


def _flow(type_: str, title: str, data: dict) -> None:
    if flowpub is not None:
        flowpub.emit("computers", type_, title, data)


class _RedactDoorPath(logging.Filter):
    """Never print a door token — the whole promise of a share is that it is shown ONCE.

    The token IS a path segment (`/share/<token>`), and uvicorn logs every WebSocket path on its
    `uvicorn.error` logger ('%s - "WebSocket %s" [accepted]'), which `--no-access-log` does NOT
    silence — so this app's own container log carried a working door. The path is rewritten here
    before any handler formats the record: the door still opens, the log says only whose.
    """
    _RE = re.compile(r"/share/[A-Za-z0-9_\-]{8,}")

    def filter(self, record: logging.LogRecord) -> bool:      # True = let it through, redacted
        if isinstance(record.msg, str) and "/share/" in record.msg:
            record.msg = self._RE.sub("/share/<token>", record.msg)
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(self._RE.sub("/share/<token>", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


for _name in ("uvicorn.error", "uvicorn.access"):
    _lg = logging.getLogger(_name)
    if not any(isinstance(f, _RedactDoorPath) for f in _lg.filters):
        _lg.addFilter(_RedactDoorPath())

# ── configuration ───────────────────────────────────────────────────────────────
STATE_DIR = Path(os.environ.get("COMPUTERS_STATE_DIR", "/data"))
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "bina-deployment")
PROTOCOL = "computer_ssh"                 # this service owns this protocol and no other
LOCAL_INSTANCE = "computer_local-local"   # <protocol>-local, the synthetic private-engine id
LOCAL_LABEL = "המחשב הזה"
LOCAL_USER = os.environ.get("COMPUTERS_LOCAL_USER", "root")
LOCAL_PORT = int(os.environ.get("COMPUTERS_LOCAL_PORT", "22"))
NETWORK = os.environ.get("COMPUTERS_NETWORK", "traefik-network")
FALLBACK_GATEWAY = os.environ.get("COMPUTERS_LOCAL_HOST", "172.18.0.1")
MAX_TIMEOUT = 600
DEFAULT_TIMEOUT = 60
STDIN_MAX = 1024 * 1024      # a script or a secret, not a file transfer (that is `transfer`)
PROBE_TTL = float(os.environ.get("COMPUTERS_PROBE_TTL", "20"))
#: How many machines the fleet probes at once (DGO-1359): one machine out of reach no longer holds the others.
PROBE_WORKERS = max(1, int(os.environ.get("COMPUTERS_PROBE_WORKERS", "8") or 8))

KEY_DIR = STATE_DIR / "ssh"
KEY_PATH = KEY_DIR / "office_key"
PUB_PATH = KEY_DIR / "office_key.pub"
KNOWN_HOSTS = KEY_DIR / "known_hosts"

_STATIC = Path(__file__).parent / "static"

# ── the office key ──────────────────────────────────────────────────────────────
_key_lock = threading.Lock()


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def ensure_key() -> bool:
    """Mint the office keypair if it does not exist yet. Returns True when a PRIVATE key is on disk.

    Idempotent and cheap: called on startup and defensively before any SSH. ssh-keygen is used
    rather than a Python library because the artifact has to be a plain OpenSSH key — the owner
    will read the public half and paste it into a machine, and the operator will recognise the
    file. (python:3.12-slim has no ssh binary, so the image installs openssh-client for both.)
    """
    with _key_lock:
        if KEY_PATH.exists():
            return True
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        _chmod(KEY_DIR, 0o700)
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", f"office-key@{DEPLOYMENT_NAME}",
                 "-f", str(KEY_PATH)],
                check=True, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            log.error("office key could not be generated: %s: %s", type(e).__name__,
                      getattr(e, "stderr", b"") or e)
            return False
        _chmod(KEY_PATH, 0o600)
        _chmod(PUB_PATH, 0o644)
        log.info("office key minted at %s", KEY_PATH)
        return True


def _key_path_for(secret: dict) -> str | None:
    """The private key a machine's instance uses.

    A machine MAY carry its own key (`secret.private_key`), in which case it is written to its own
    file under the app's volume — a per-machine credential never overwrites the office key. With no
    key of its own, the machine uses the office key, which is the zero-config path and the one the
    UI explains.
    """
    cid = secret.get("_instance") or "instance"
    own = (secret.get("private_key") or "").strip()
    if own:
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        _chmod(KEY_DIR, 0o700)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", cid)
        p = KEY_DIR / f"{safe}.key"
        if not own.endswith("\n"):
            own += "\n"
        if not p.exists() or p.read_text(encoding="utf-8") != own:
            p.write_text(own, encoding="utf-8")
            _chmod(p, 0o600)
        return str(p)
    return str(KEY_PATH) if KEY_PATH.exists() else None


def public_key() -> str:
    try:
        return PUB_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def key_fingerprint() -> str:
    """ssh-keygen's own SHA256 fingerprint of the public half — what an operator can verify with."""
    if not PUB_PATH.exists():
        return ""
    try:
        r = subprocess.run(["ssh-keygen", "-lf", str(PUB_PATH)], capture_output=True,
                           text=True, timeout=10)
        if r.returncode == 0:
            parts = r.stdout.split()
            if len(parts) >= 2:
                return parts[1]
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


# ── the engine network's gateway: the address of the machine we run on ──────────
def gateway_from_route(text: str) -> str | None:
    """The default gateway out of /proc/net/route, or None.

    /proc/net/route is a fixed-width table of little-endian hex: the interface, the destination
    (00000000 = default), the gateway, then flags. It is the deployment's OWN answer and needs no
    tooling at all — which matters because python:3.12-slim has neither `ip` nor `hostname` nor
    `curl`, and this app deliberately does not mount the engine socket just to learn its own
    address.
    """
    for line in (text or "").splitlines()[1:]:
        f = line.split()
        if len(f) < 3 or f[1] != "00000000":
            continue
        try:
            raw = bytes.fromhex(f[2])
        except ValueError:
            continue
        if len(raw) != 4:
            continue
        return ".".join(str(b) for b in reversed(raw))     # little-endian
    return None


def local_gateway() -> str:
    """The host's address as seen from inside the deployment's network.

    This is the address of "the machine this deployment runs on", so it may not be a constant: the
    subnet is allocated per deployment and 172.18.0.1 is THIS machine's answer. The route table is
    the primary source; the engine is consulted only if there is no default route at all.
    """
    try:
        gw = gateway_from_route(Path("/proc/net/route").read_text(encoding="utf-8"))
        if gw:
            return gw
    except OSError:
        pass
    try:
        r = subprocess.run(["docker", "network", "inspect", NETWORK, "--format", "{{json .IPAM.Config}}"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            cfgs = json.loads(r.stdout.strip() or "[]")
            for c in cfgs if isinstance(cfgs, list) else []:
                gw = (c or {}).get("Gateway")
                if gw:
                    return gw
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log.warning("could not read the gateway of %s (%s)", NETWORK, type(e).__name__)
    return FALLBACK_GATEWAY


# ── the credential plane ────────────────────────────────────────────────────────
_VT = 10


def vault_list() -> tuple[list[dict], str | None]:
    """(instances, error) for computer_ssh. The ERROR is returned rather than swallowed: "the vault
    is down" and "there are no machines" both look like an empty list, and only one of them is a
    reason to tell the owner nothing is configured."""
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances",
                         params={"protocol": PROTOCOL}, timeout=_VT)
        r.raise_for_status()
        return list((r.json() or {}).get("instances", [])), None
    except (requests.RequestException, ValueError) as e:
        log.warning("vault_list: %r", e)
        return [], "שירות החיבורים אינו זמין"


def vault_secret(cid: str) -> dict | None:
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances/{cid}/secret", timeout=_VT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("vault secret for %s unavailable: %s", cid, type(e).__name__)
        return None


# The vault is one round trip per instance, and a fleet listing asks about every machine twice
# (once to identify it, once to build its row). This cache holds the LAST answer per instance for a
# few seconds — long enough to cover a page render, short enough that an edit made elsewhere is
# visible by the next poll. It is dropped for an instance on every write this service performs.
_secret_lock = threading.Lock()
_secret_cache: dict[str, tuple[float, dict | None]] = {}
_SECRET_TTL = 5.0


def secret_for(inst: dict) -> dict:
    """The `secret` body of an instance, cached briefly. {} when there is none or the vault is down."""
    cid = inst.get("id")
    if not cid:
        return {}
    now = time.time()
    with _secret_lock:
        hit = _secret_cache.get(cid)
    if hit and now - hit[0] < _SECRET_TTL:
        return hit[1] or {}
    body = vault_secret(cid)
    sec = (body or {}).get("secret") or {}
    with _secret_lock:
        _secret_cache[cid] = (now, sec)
    return sec


def forget_secret(cid: str | None = None) -> None:
    with _secret_lock:
        _secret_cache.pop(cid, None) if cid else _secret_cache.clear()


def vault_add(secret: dict, label: str, account_hint: str | None) -> tuple[dict, int]:
    body = {"protocol": PROTOCOL, "label": label, "secret": secret}
    if account_hint:
        body["account_hint"] = account_hint
    try:
        r = requests.post(f"{CONNECTIONS_URL}/api/instances", json=body, timeout=_VT)
        return (r.json() if r.content else {}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except requests.RequestException as e:
        return {"error": f"שירות החיבורים אינו זמין: {e}"}, 502


def vault_delete(cid: str) -> tuple[dict, int]:
    try:
        r = requests.delete(f"{CONNECTIONS_URL}/api/instances/{cid}", timeout=_VT)
        return (r.json() if r.content else {"ok": r.ok}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except requests.RequestException as e:
        return {"error": f"שירות החיבורים אינו זמין: {e}"}, 502


def is_local_instance(inst: dict, host: str) -> bool:
    """Is this vault row the machine we are running on?

    Asked of the ADDRESS, not of the id. The id is the platform's (`<protocol>-<8hex>`) and the vault
    mints it; only the built-in row is allowed to carry the synthetic `computer_local-local`, and
    matching on that alone meant a row registered before the local machine was promoted read as an
    ordinary computer — with a null address, a red row, and a "delete" button next to the machine the
    office runs on. The address is what the row IS.

    Two signals, cheapest first: `account_hint` (which the list endpoint always returns) and the
    secret (the authority). The hint is not decoration here — it is what keeps the guard working
    when the vault will not hand over a secret, which is precisely when a delete would be worst.
    """
    if inst.get("id") == LOCAL_INSTANCE:
        return True
    hint = (inst.get("account_hint") or "").strip()
    if hint and hint in (f"{LOCAL_USER}@{host}:{LOCAL_PORT}", f"{LOCAL_USER}@{host}"):
        return True
    sec = secret_for(inst)
    return (sec.get("host") == host and int(sec.get("port") or LOCAL_PORT) == LOCAL_PORT
            and (sec.get("user") or LOCAL_USER) == LOCAL_USER)


def vault_write(rec: dict) -> tuple[dict, int]:
    """Create the built-in instance AT ITS CANONICAL ID — `computer_local-local`.

    The instances API mints ids (`<protocol>-<8hex>`) unless the caller proposes one, and this is the
    one row whose id is the PLATFORM's spelling for "the machine this deployment runs on" (drive's
    history in connections_client.py). Addressed by a minted id instead, the row moved on every
    restart and every stale copy read as an ordinary, deletable machine.

    The id is a proposal, and the plane is entitled to refuse it — a taken id comes back 409 and is
    reported here, never silently replaced by a different one.
    """
    try:
        r = requests.post(f"{CONNECTIONS_URL}/api/instances",
                          json={**rec, "id": LOCAL_INSTANCE, "secret": {"auth": "office_key"}},
                          timeout=_VT)
        body = r.json() if r.content else {}
        if r.status_code >= 300:
            return body if isinstance(body, dict) else {}, r.status_code
        if body.get("id") != LOCAL_INSTANCE:
            # The plane accepted the call and minted its own name anyway. Say so loudly: silently
            # accepting it is what produced duplicate rows for one machine.
            log.warning("connections returned id %r for %r — the built-in machine will not be "
                        "addressable by its canonical id", body.get("id"), LOCAL_INSTANCE)
        return body, r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except requests.RequestException as e:
        return {"error": f"שירות החיבורים אינו זמין: {e}"}, 502


def vault_ensure_local(host: str, user: str, port: int) -> None:
    """The built-in instance for the machine we run on: create it once, at its canonical id, and
    remove any older row that described the same machine under a minted id.

    No secret to speak of on purpose: the local machine uses the office key, which lives in this
    app's own volume. An empty `secret` is rejected by the vault's API (it requires a non-empty
    dict), so the record carries an explicit marker instead of a lie.

    The cleanup is not cosmetic. A row created before this id was pinned is an ORDINARY computer to
    everything that matches on ids (the delete guard, the account bar's label, this function's own
    dedupe), so without it every restart registers the machine again and the local host accumulates
    duplicate, deletable rows for one machine.
    """
    insts, err = vault_list()
    if err:
        log.warning("cannot ensure the local computer: %s", err)
        return
    canonical = next((i for i in insts if i.get("id") == LOCAL_INSTANCE), None)
    stale = [i for i in insts if i.get("id") != LOCAL_INSTANCE and is_local_instance(i, host)]
    if not canonical:
        body, status = vault_write({"protocol": PROTOCOL, "label": LOCAL_LABEL,
                                    "account_hint": f"{user}@{host}:{port}", "status": "ok"})
        if status >= 300:
            log.warning("could not register the built-in machine: %s %s", status, body)
            return
        log.info("built-in machine registered as %s (%s@%s:%s)", LOCAL_INSTANCE, user, host, port)
    for i in stale:
        vault_delete(i["id"])
        log.info("removed the duplicate row for the built-in machine (%s)", i["id"])


def local_computer(host: str) -> dict:
    """The built-in machine as the API reports it — the instance id is the platform's, the fact
    "this is the machine you are running on" is ours."""
    return {"id": LOCAL_INSTANCE, "protocol": PROTOCOL, "label": LOCAL_LABEL,
            # what a person reads beside the name — not the engine network's gateway address
            "account_hint": "המכונה שמריצה את הלשכה", "status": "ok",
            "created_at": None, "host": host, "port": LOCAL_PORT, "user": LOCAL_USER,
            "builtin": True, "removable": False,
            "note": "המכונה שמריצה את הלשכה — אינה ניתנת למחיקה"}


def computer_record(inst: dict, host: str) -> dict:
    """A vault instance -> a computer. The address lives in the SECRET, which the list endpoint
    never returns; the single source of truth is the record, so it is read from the secret here
    rather than duplicated into `account_hint` (which is display-only)."""
    cid = inst.get("id")
    if is_local_instance(inst, host):
        return {**local_computer(host), "id": cid,
                "label": inst.get("label") or LOCAL_LABEL}
    sec = secret_for(inst)
    return {"id": cid, "protocol": inst.get("protocol"), "label": inst.get("label"),
            "account_hint": inst.get("account_hint"), "status": inst.get("status", "ok"),
            "created_at": inst.get("created_at"),
            "host": sec.get("host"), "port": int(sec.get("port") or 22),
            "user": sec.get("user") or "root",
            "has_own_key": bool(sec.get("private_key")),
            # lent by another office, reached through its door (the door's token is never shown)
            "shared": bool(sec.get("door")),
            "builtin": False, "removable": True}


# ── SSH ─────────────────────────────────────────────────────────────────────────
# Three things this deliberately is NOT:
#   · not paramiko — the platform's artifacts are plain OpenSSH keys and plain ssh semantics, and
#     the exit code of `ssh` is the exit code of the remote command, which /exec hands back as-is;
#   · not password auth — BatchMode=yes means "never prompt", so a machine that is not yet
#     authorised fails immediately with a real reason instead of hanging a worker;
#   · not a permissive host-key policy — unknown host keys are accepted ONCE and pinned into
#     /data/ssh/known_hosts, which is the ordinary first-contact model and is visible in the UI.
SSH_BASE = [
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=8",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2",
]


def _known_hosts_opt() -> list[str]:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    return ["-o", f"UserKnownHostsFile={KNOWN_HOSTS}"]


DOOR_RE = re.compile(r"^wss?://([A-Za-z0-9.-]+(?::\d+)?)/share/[A-Za-z0-9_-]{32,}\Z")


def _door_opts(cid: str, secret: dict) -> list[str]:
    """A computer another office SHARED with this one is reached through its door (share.py), with
    ssh's host key pinned under the instance id — the door's hostname is the lender's, not the
    machine's, and two machines lent by one office must not share a known_hosts line.

    The door is re-checked HERE, at the point of use, and not only where it was typed: ssh runs
    `ProxyCommand` through `/bin/sh`, and the value comes back from the credential plane, so a `;`
    or a space in that secret would otherwise be command execution inside this container — the one
    container that holds the engine socket.
    """
    door = (secret.get("door") or "").strip()
    if not door:
        return []
    if not DOOR_RE.match(door):
        raise ValueError("door is not a share address (wss://<host>/share/<token>)")
    return ["-o", f"ProxyCommand=python3 {shlex.quote(str(Path(__file__).parent / 'door_client.py'))} "
                  f"{shlex.quote(door)}",
            "-o", f"HostKeyAlias={cid}"]


# The remote probe: ONE round trip, and no dependency on anything but sh and /proc. The far side is
# very often NOT a full Linux userland — python:3.12-slim itself has no `free`, no `hostname`, no
# `nproc` and no `ip`, and a minimal Alpine has no `df` outside busybox — so every field has a
# fallback and every value is optional. A machine that answers with a hostname and nothing else is a
# machine that works: the JSON is ONE line, and that line is the probe's entire contract.
PROBE_SH = r"""
hn=$(hostname 2>/dev/null || cat /proc/sys/kernel/hostname 2>/dev/null)
osname=$( (. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-${NAME:-}}") )
[ -z "$osname" ] && osname=$(uname -s 2>/dev/null)
krn=$(uname -r 2>/dev/null)
arc=$(uname -m 2>/dev/null)
up=$(uptime -p 2>/dev/null)
[ -z "$up" ] && up=$(cut -d. -f1 /proc/uptime 2>/dev/null)
ld=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)
cpu=$(nproc 2>/dev/null)
[ -z "$cpu" ] && cpu=$(grep -c '^processor' /proc/cpuinfo 2>/dev/null)
mem=$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^MemFree:/{f=$2} END{if(t>0){u=t-a; if(a=="")a=f; printf "%d %d %d", int(t/1024), int(u/1024), int(a/1024)}}' /proc/meminfo 2>/dev/null)
dsk=$(df -Pm / 2>/dev/null | awk 'NR==2{print $2" "$3" "$4" "$5}')
printf '{"probe":"office.v1","hostname":"%s","os":"%s","kernel":"%s","arch":"%s","uptime":"%s","load":"%s","ncpu":"%s","memory":"%s","disk":"%s"}\n' \
  "$hn" "$osname" "$krn" "$arc" "$up" "$ld" "$cpu" "$mem" "$dsk"
"""
#: The marker inside that JSON: it is what makes the line identifiable among ssh's own chatter
#: ("Warning: Permanently added …"), and what tells a real answer from a machine that echoed
#: something else. Bump it and a machine whose shell mangled the format stops looking like a
#: machine that answered.
PROBE_MARK = '"probe":"office.v1"'


def classify_stderr(err: str, code: int) -> tuple[str, str, str]:
    """(state, Hebrew reason, what to do next) for a failed ssh.

    Matched on ssh's own words rather than on the exit code alone: ssh returns 255 for every
    connection-level failure, and a remote command's own non-zero code is indistinguishable from it
    by number. The distinctions matter to the owner — "the machine is off", "the key is not
    approved yet" and "the port is closed" have three different fixes.
    """
    e = (err or "").lower()
    if "permission denied" in e or "publickey" in e:
        return ("needs_action",
                "המפתח של הלשכה אינו מורשה במחשב הזה",
                "אשר את המפתח הציבורי במחשב (הכפתור „אישור המפתח” מציג את הפקודה המדויקת), "
                "או הוסף מפתח פרטי משלך לחיבור.")
    if "host key verification failed" in e or "remote host identification has changed" in e:
        return ("needs_action",
                "מפתח המחשב (host key) אינו תואם למה שנשמר",
                "המחשב הותקן מחדש או שזה מחשב אחר בכתובת הזו. הסר את הרשומה מ־"
                "known_hosts של הלשכה ואשר מחדש.")
    if "connection refused" in e:
        return ("error", "המחשב דוחה חיבורים בפורט הזה",
                "ודא ששירות SSH פועל במחשב ושהפורט נכון.")
    if "no route to host" in e or "network is unreachable" in e:
        return ("error", "אין מסלול למחשב",
                "בדוק את הכתובת ואת הרשת שבין הלשכה למחשב.")
    if "timed out" in e or "timeout" in e or "operation timed out" in e:
        return ("error", "המחשב לא הגיב בזמן", "בדוק שהמחשב דלוק ושה־SSH נגיש.")
    if "could not resolve hostname" in e or "name or service not known" in e:
        return ("error", "לא ניתן לזהות את שם המחשב", "בדוק את הכתובת — שם או IP.")
    if code == 255:
        return ("error", "החיבור למחשב נכשל", "פרטי השגיאה המלאים מופיעים למטה.")
    return ("ok", "", "")


class BadDestination(ValueError):
    """A computer's user or host that ssh would read as something else."""


#: what a user or a host may never be: led by «-» (ssh reads `-oProxyCommand=…@host` as an OPTION and runs it in this
#: container, which holds every machine's key — measured with `ssh -G`), or holding a control character. A space is
#: a user's right (a Windows account), so it is not refused: the `--` before the destination keeps it one argument.
_BAD_DEST = re.compile(r"^-|[\x00-\x1f\x7f]")


def check_destination(user: str, host: str) -> str:
    """`user@host`, or BadDestination with the sentence a screen shows."""
    if not user or _BAD_DEST.search(str(user)):
        raise BadDestination("שם המשתמש של המחשב אינו תקין: אסור שיתחיל ב-«-» או שיכיל תו בקרה")
    if not host or _BAD_DEST.search(str(host)) or re.search(r"[\s@]", str(host)):
        # «@» too: ssh splits the destination at its LAST «@», so a host `a@b` would reach `b` as another user
        raise BadDestination("כתובת המחשב אינה תקינה: אסור שתתחיל ב-«-» או שתכיל רווח, «@» או תו בקרה")
    return f"{user}@{host}"


def ssh_argv(cid: str, host: str, port: int, user: str, secret: dict,
             command: str, timeout: int = 60) -> list[str]:
    """The exact ssh command line for one machine — for ssh_run, transfer and the terminal alike, because a copy
    that used a looser connection would be a second answer to "how do we reach a machine", and the loose one is the
    one that drifts. `--` ends ssh's options before the destination: nothing a record holds can become one."""
    return ["ssh", *SSH_BASE, *_known_hosts_opt(), *_door_opts(cid, secret),
            "-i", _key_path_for({**secret, "_instance": cid}),
            "-p", str(int(port or 22)),
            "-o", f"ConnectTimeout={min(8, max(3, int(timeout or 8)))}",
            "--", check_destination(user, host), command]


def ssh_run(cid: str, host: str, port: int, user: str, secret: dict,
            command: str, timeout: int, stdin: bytes | None = None) -> dict:
    """Run a command on a machine. Always returns a dict — never raises into a route.

    {code, stdout, stderr, timed_out, reason, action, state}. `code` is the remote command's own
    exit code when the connection was made (including 255 if the far side's command exits 255), and
    255 when ssh itself failed — an ambiguity ssh itself has, which is why the reason is derived
    from stderr rather than from the number.

    `stdin` is handed to the remote command's standard input. It is how a SECRET reaches a machine:
    the command line travels as an argument — in this container's `ssh` argv and in the far side's
    `bash -c` argv, which any local user there can read in /proc/<pid>/cmdline — and stdin does not.
    """
    ensure_key()
    key = _key_path_for({**secret, "_instance": cid})
    if not key:
        return {"code": 255, "stdout": "", "stderr": "", "timed_out": False, "state": "needs_action",
                "reason": "לא נוצר עדיין מפתח SSH ללשכה",
                "action": "רענן את הדף — המפתח נוצר אוטומטית עם עליית השירות."}
    try:
        cmd = ssh_argv(cid, host, port, user, secret, command, timeout)   # ONE command line, not a second copy
    except BadDestination as e:        # a record saved before its user or host was checked
        return {"code": 255, "stdout": "", "stderr": "", "timed_out": False, "state": "error",
                "reason": str(e), "action": "תקן את פרטי המחשב במסך «מחשבים» (מחק והוסף אותו מחדש)."}
    except ValueError as e:            # a `door` in the vault that is not a share address
        return {"code": 255, "stdout": "", "stderr": "", "timed_out": False, "state": "error",
                "reason": "כתובת השיתוף של המחשב אינה תקינה", "action": str(e)}
    started = time.time()
    try:
        # BYTES, decoded with errors="replace" — never `text=True`.
        #
        # `text=True` decodes strictly, and a remote command that pipes through `head -c N` cuts its
        # output mid-character. One truncated Hebrew letter in the middle of a scan's sample output
        # then raised UnicodeDecodeError INSIDE subprocess, which escaped this function and made
        # /exec answer 500 "Internal Server Error" — a transport-level failure reported for a command
        # that ran perfectly. Found by apps/sites on 2026-09-23, on a `docker exec … wget … | head -c
        # 300` whose 300th byte landed inside a Hebrew character.
        p = subprocess.run(cmd, capture_output=True, timeout=max(1, int(timeout)),
                           input=stdin if stdin is not None else b"")
    except subprocess.TimeoutExpired as e:
        return {"code": None, "stdout": _text(e.stdout), "stderr": _text(e.stderr),
                "timed_out": True, "state": "error", "elapsed": round(time.time() - started, 2),
                "reason": f"הפקודה לא הסתיימה בתוך {timeout} שניות",
                "action": "הגדל את ה־timeout או בדוק את הפקודה."}
    except OSError as e:
        return {"code": 255, "stdout": "", "stderr": str(e), "timed_out": False, "state": "error",
                "reason": "לא ניתן להפעיל ssh", "action": "בדוק את הקונטיינר."}
    stdout, stderr = _text(p.stdout), _text(p.stderr)
    state, reason, action = classify_stderr(stderr, p.returncode)
    if state == "ok" and p.returncode != 0:
        # The command RAN and failed. That is not a broken connection, and calling it "ok" would be
        # the same class of lie as /readyz saying ready about an account that is gone: the caller is
        # handed the exit code and the error text, and `state` says what kind of answer this is.
        state = "error"
        reason = f"הפקודה הסתיימה בקוד {p.returncode}"
        action = "הפלט והשגיאות למטה."
    out = {"code": p.returncode, "stdout": stdout, "stderr": stderr, "timed_out": False,
           "elapsed": round(time.time() - started, 2), "state": state}
    if reason:
        out["reason"], out["action"] = reason, action
    return out


def _text(raw) -> str:
    """A subprocess stream as text, whatever bytes it actually contains.

    A remote command's output is not guaranteed to be valid UTF-8 — it is whatever the machine's
    shell produced, cut wherever a pipe buffer or a `head -c` happened to cut it. Replacing the
    undecodable byte keeps the REST of the answer readable, which is the whole value of /exec.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")


# ── /status: the probe, parsed, with the awaiting-approval state made first-class ──
def parse_probe(stdout: str) -> dict | None:
    """The probe's JSON out of ssh's output, or None.

    Found by the MARKER, not by "the last line": ssh writes its own chatter to stdout too
    ("Warning: Permanently added …"), and reading positionally is how a warning becomes a machine's
    status. A line without the marker is not an answer.
    """
    for line in (stdout or "").splitlines():
        if PROBE_MARK not in line:
            continue
        line = line[line.index("{"):] if "{" in line else line
        try:
            return json.loads(line)
        except ValueError:
            # A truncated line, or a shell that mangled the printf: read what is there rather than
            # declaring the machine broken. A hostname alone is a working machine.
            host = re.search(r'"hostname":"([^"]*)"', line)
            return {"hostname": host.group(1) if host else None} if host else None
    return None


def _text_int(text: str | None) -> int | None:
    """An int out of one probe field ("8", "8\n"). NOT `_num`, which reads a FACT out of the
    security-audit dict: two helpers shared the name until this one was renamed, and the later
    definition silently won — `probe()` called the dict version with one argument and every
    `/api/computers` and `/status` answer was a 500 (TypeError: missing 'key')."""
    try:
        return int(str(text).strip().split()[0])
    except (ValueError, IndexError, AttributeError):
        return None


def parse_memory(raw: str | None) -> dict | None:
    """free -m's `total used available` (MB) -> bytes."""
    parts = (raw or "").split()
    if len(parts) < 3:
        return None
    try:
        total, used, avail = (int(p) * 1024 * 1024 for p in parts[:3])
    except ValueError:
        return None
    return {"total": total, "used": used, "available": avail,
            "used_percent": round(used * 100 / total, 1) if total else None}


def parse_disk(raw: str | None) -> dict | None:
    """df -Pm's `total used avail capacity` for / (MB) -> bytes."""
    parts = (raw or "").split()
    if len(parts) < 3:
        return None
    try:
        total, used, avail = (int(p) * 1024 * 1024 for p in parts[:3])
    except ValueError:
        return None
    pct = parts[3].rstrip("%") if len(parts) > 3 else ""
    try:
        used_percent = float(pct)
    except ValueError:
        used_percent = round(used * 100 / total, 1) if total else None
    return {"total": total, "used": used, "available": avail, "used_percent": used_percent}


_probe_lock = threading.Lock()
_probe_cache: dict[str, tuple[float, dict]] = {}


def probe(cid: str, host: str, port: int, user: str, secret: dict,
          max_age: float = PROBE_TTL, builtin: bool = False) -> dict:
    now = time.time()
    with _probe_lock:
        hit = _probe_cache.get(cid)
    if hit and now - hit[0] < max_age:
        return {**hit[1], "cached": True}
    res = ssh_run(cid, host, port, user, secret, PROBE_SH, 25)
    out: dict = {"id": cid, "host": host, "port": port, "user": user,
                 "checked_at": int(now), "cached": False}
    data = parse_probe(res.get("stdout") or "")
    # SSH ITSELF failing takes precedence over the probe's own exit code. The remote command ends in
    # `printf` (whose exit code is always 0) unless the shell could not even run — so a non-zero code
    # with our sentinel absent, plus ssh's own words on stderr, IS a connection failure, and it must
    # be reported as one instead of as "the far side returned 127".
    ssh_failed = bool(res.get("stderr")) and data is None and (res.get("code") or 0) != 0
    if ssh_failed:
        state, reason, action = classify_stderr(res.get("stderr") or "", res.get("code") or 255)
        if builtin and "connection refused" in (res.get("stderr") or "").lower():
            # THE MACHINE THE OFFICE RUNS ON, AND NOTHING LISTENS FOR SSH ON IT. That is an office's
            # own choice — the owner's ruling for hp-laptop is that it runs no SSH server — and not
            # a fault: it was shown in red, with ssh's own words in a black box, on every visit,
            # for a state there is nothing to fix. It is said as what it is.
            out.update({"ok": False, "state": "no_ssh", "reason": "במחשב הזה אין שרת SSH",
                        "action": "כך הלשכה הזאת מוגדרת: היא אינה מקבלת חיבורי SSH, ולכן פקודות מכאן "
                                  "אינן רצות עליה. מדדי המחשב עצמו נמצאים במסך «מכונה»."})
        else:
            out.update({"ok": False, "state": state if state != "ok" else "error",
                        "reason": reason or "החיבור למחשב נכשל",
                        "action": action, "code": res.get("code"),
                        "stderr": (res.get("stderr") or "")[:2000]})
    elif res.get("code") == 0:
        if not data or not data.get("hostname"):
            out.update({"ok": False, "state": "error", "reason": "המחשב ענה בפורמט שאינו מוכר",
                        "action": "ודא ש־SSH מגיע ל־shell רגיל (לא ל־forced command).",
                        "stderr": (res.get("stderr") or "")[:2000]})
        else:
            out.update({"ok": True, "state": "ok", "hostname": data.get("hostname"),
                        "os": data.get("os"), "kernel": data.get("kernel"), "arch": data.get("arch"),
                        "uptime": data.get("uptime"), "load": data.get("load"),
                        "ncpu": _text_int(data.get("ncpu")),
                        "memory": parse_memory(data.get("memory")),
                        "disk": parse_disk(data.get("disk")),
                        "elapsed": res.get("elapsed")})
    else:
        # The connection was made and the command itself failed (a machine whose shell is not sh).
        out.update({"ok": False, "state": "error",
                    "reason": res.get("reason") or "המחשב לא החזיר את נתוני המצב",
                    "action": res.get("action"), "code": res.get("code"),
                    "stderr": (res.get("stderr") or "")[:2000]})
    with _probe_lock:
        _probe_cache[cid] = (now, out)
    return out


def invalidate(cid: str | None = None) -> None:
    with _probe_lock:
        if cid:
            _probe_cache.pop(cid, None)
        else:
            _probe_cache.clear()


# ── HTTP ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="computers", docs_url=None, redoc_url=None, openapi_url=None)


def _err(message: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


# ── who is asking: every write names its caller (DGO-1304) ──────────────────────────────────────
# One middleware, not a check per route: a route added later is covered by being a write, the way the
# door forwards every method and path. The decision is caller.identify (pure, tests/test_caller.py);
# what this section adds is the office's facts — the hops' addresses, what it shares, the token.
import caller as callermod  # noqa: E402
import link_identity as linkid  # noqa: E402
import remote  # noqa: E402 — the machines linked offices share with this one (DGO-553)

#: warn (the default): a write with no known caller is let through, logged and counted (GET /api/callers),
#: so the callers that still need a token are found before anything is refused. enforce: it is a 403.
AUTH_MODE = (os.environ.get("COMPUTERS_EXEC_AUTH") or "warn").strip().lower()
#: machines refused to an unknown caller whatever the mode — the HP's own host from day one: nothing
#: depends on it there (it never worked), and opening its door must not open it to every container.
ENFORCE_MACHINES = {m.strip() for m in (os.environ.get("COMPUTERS_ENFORCE_MACHINES") or "").split(",") if m.strip()}
#: the linked offices this office gives its computer to (per office, in .env; the HP: macbook)
SHARE_TO = {o.strip().lower() for o in (os.environ.get("COMPUTERS_SHARE_TO") or "").split(",") if o.strip()}
EXEC_TOKEN = os.environ.get("COMPUTERS_EXEC_TOKEN") or ""
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
#: the hops are CONTAINER names of this deployment (`console-hp`, `dgo-net-hp`): a network alias any other
#: compose file — or another deployment on the same engine — could declare is not a hop (the second reader)
DEPLOYMENT = os.environ.get("DEPLOYMENT_NAME") or "bina-deployment"
_HOPS: dict = {"at": 0.0, "door": set(), "sso": set()}
_HOPS_LOCK = threading.Lock()
_NAMES: dict[str, str] = {}
#: the count of unknown callers, bounded: a caller must not be able to grow it (one row per source, method
#: and route TEMPLATE; past the cap, rows go to one bucket)
_REFUSED: dict[tuple, dict] = {}
_REFUSED_CAP = 300
_REFUSED_SINCE = time.time()
#: the READS that came from another office (through the link's door) since this process started, by the office it
#: names and the route template — answered as before, only counted. The first stage of narrowing what a linked
#: office reads (issues/a-linked-office-reading-computers-through-the-door-gets-the-whole-fleet-…): before any read is
#: refused to anybody, the count says which offices read what (AGENTS.md rule 8). The office is the header's word
#: (not verified here: a count, not a decision); bounded like _REFUSED.
_DOOR_READS: dict[tuple, dict] = {}


def _count_door_read(office: str, path: str, herd: bool = False) -> None:
    """One read through the door, by office, route template and whether the door said the office is the herd's —
    the count the narrowing is decided by: a row with `herd: false` is what would be narrowed (DGO-1800)."""
    key = (str(office or "?").strip().lower()[:64], callermod.route_shape(path), bool(herd))
    if key not in _DOOR_READS and len(_DOOR_READS) >= _REFUSED_CAP:
        key = ("(many)", "(over the cap)", bool(herd))           # …still apart by herd: the total stays true
    row = _DOOR_READS.setdefault(key, {"office": key[0], "route": key[1], "herd": key[2], "count": 0})
    row.update(count=row["count"] + 1, last=int(time.time()))


#: the label a read gets when it names an office but did not come from the door: a container's claim, not a peer's read
NOT_THE_DOOR = "(not the door)"


def _door_read(request: Request) -> tuple[bool, bool]:
    """(from the door, the herd's) for a read that names an office (DGO-1800). Only the door's own address is the door
    (linkid.from_the_door) — any container can write the office header — and only the door's `x-dgo-herd: 1` says herd:
    the door removes a peer's own, by key it writes its own. A plain def — `_hops()` may look the door up — so it is run
    off the event loop."""
    door, _ = _hops()
    if not linkid.from_the_door((request.client.host if request.client else "") or "", door):
        return False, False
    return True, (request.headers.get(linkid.HERD_HEADER) or "").strip() == "1"


def _addrs(names) -> set:
    out: set = set()
    for name in names:
        try:
            for info in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP):
                out.add(str(info[4][0]))
        except OSError:
            continue
    return out


def _hops() -> tuple[set, set]:
    """The door's and the sign-in hops' addresses, re-read once a minute (15 s while the door is absent:
    an office linked a moment ago is noticed soon, and a cached miss is never a permission)."""
    now = time.time()
    with _HOPS_LOCK:
        if _HOPS["at"] and now - _HOPS["at"] < (60 if _HOPS["door"] else 15):
            return _HOPS["door"], _HOPS["sso"]
    door = _addrs(f"{n}-{DEPLOYMENT}" for n in callermod.DOOR_HOPS)
    sso = _addrs(f"{n}-{DEPLOYMENT}" for n in callermod.SSO_HOPS)
    with _HOPS_LOCK:
        _HOPS.update(at=now, door=door, sso=sso)
    return door, sso


def _link_secret(office: str) -> str:
    """This office's copy of the secret it shares with ONE linked office (`dgo_link` in the vault) — what
    the door signs with. Matched EXACTLY as the door matches it (apps/dgo-extend/link-proxy.py `names_office`,
    `link_secret`): `dgo_link-<office>`, or `<a>-><b>` in the hint, and never an agent credential a linked
    office handed over. Never a split on `-`: office ids carry hyphens (hp-laptop), hos-005.

    "" means the vault ANSWERED and holds no secret for that pair; a vault that did not answer is None —
    which the caller refuses. The two looked the same once, and for a minute after a vault hiccup an
    unsigned request from the door's address passed as "a pair without a secret" (the second reader)."""
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances", params={"protocol": "dgo_link"}, timeout=8)
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("instances") or []
        for row in rows:
            iid = str(row.get("id") or "").lower()
            if iid.startswith("dgo_link-serve-") and iid.endswith("-agent"):
                continue
            hint = str(row.get("account_hint") or "").lower().split(" ", 1)[0]
            if iid == f"dgo_link-{office}" or ("->" in hint and office in hint.split("->")):
                s = requests.get(f"{CONNECTIONS_URL}/api/instances/{row.get('id')}/secret", timeout=8)
                if s.status_code != 200:
                    return None
                tok = str(((s.json() or {}).get("secret") or {}).get("token") or "")
                if tok:
                    return tok
    except (requests.RequestException, ValueError):
        return None
    return ""


_SECRET_CACHE: dict[str, tuple[float, str]] = {}


def _secret_of(office: str) -> str | None:
    """`_link_secret`, remembered for a minute — an ANSWER only: a vault that did not answer is asked again
    next time, and is never remembered as "this pair has no secret"."""
    now = time.time()
    hit = _SECRET_CACHE.get(office)
    if hit and now - hit[0] < 60:
        return hit[1]
    got = _link_secret(office)
    if got is not None:
        _SECRET_CACHE[office] = (now, got)
    return got


def _name_of(addr: str) -> str:
    """The container behind an address (docker's DNS answers the reverse) — asked only when the count is READ
    (/api/callers, off the request path), never per write: a reverse lookup on the event loop stalled
    everything, /healthz included (the second reader)."""
    if addr not in _NAMES:
        if len(_NAMES) > _REFUSED_CAP:
            _NAMES.clear()
        try:
            _NAMES[addr] = socket.gethostbyaddr(addr)[0].split(".")[0]
        except (OSError, ValueError):
            _NAMES[addr] = ""
    return _NAMES[addr]


def identify_request(request: Request) -> callermod.Caller:
    door, sso = _hops()
    h = request.headers
    facts = callermod.Facts(
        client=(request.client.host if request.client else "") or "",
        office=h.get(linkid.OFFICE_HEADER) or "", claim=h.get(linkid.IDENTITY_HEADER) or "",
        user=h.get("x-authentik-username") or "", bearer=callermod.bearer_of(h.get("authorization")))
    return callermod.identify(facts, callermod.Policy(door_addrs=door, sso_addrs=sso, share_to=SHARE_TO,
                                                      token=EXEC_TOKEN, secret_of=_secret_of))


def _log_path(path: str) -> str:
    """The path as the log keeps it: a terminal session's id cut to its first four characters — it is what a
    caller presents to type into that shell, so the log never holds it whole."""
    return re.sub(r"(/shell/[0-9a-fA-F]{0,4})[^/]*", r"\1…", path) if "/shell/" in path else path


def _declares_office(request: Request) -> bool:
    """Does the request say it comes from another office (the door's two headers)?"""
    h = request.headers
    return bool((h.get(linkid.OFFICE_HEADER) or "").strip() or (h.get(linkid.IDENTITY_HEADER) or "").strip())


def _count(addr: str, method: str, path: str, why: str) -> bool:
    """Count one refusal; True when it is worth a log line (the first of its row, then every 100th — a caller
    must not be able to rotate this container's logs away)."""
    key = (addr, method, callermod.route_shape(path))
    if key not in _REFUSED and len(_REFUSED) >= _REFUSED_CAP:
        key = ("(many)", "*", "(over the cap)")
    row = _REFUSED.setdefault(key, {"source": key[0], "method": key[1], "route": key[2], "count": 0, "why": why})
    row.update(count=row["count"] + 1, last=int(time.time()), why=why)
    return row["count"] == 1 or row["count"] % 100 == 0


#: a machine another office shares, as this fleet addresses it: `<machine>.<office>` (remote.office_of), and the rest
_ITS_OFFICE = re.compile(r"^/api/computers/([^/]+\.[a-z0-9-]+)(/.*)?$")
#: how long a forwarded call may take: an exec runs up to its own timeout over there, and the link carries it
REMOTE_CALL_S = float(os.environ.get("COMPUTERS_REMOTE_CALL_S", "330"))


# DECLARED BEFORE _who_is_asking, ON PURPOSE: Starlette runs the middleware declared LAST first, so this one runs
# AFTER the caller check — a write to another office's machine is identified here before it leaves (DGO-553).
@app.middleware("http")
async def _to_its_office(request: Request, call_next):
    """A machine a linked office shares (`<machine>.<office>`): the request goes to THAT office through the link's
    door and its answer comes back as it is — that office runs it with its own key, on its own machine, under its own
    caller check (its door holds this office to the machine it gave). Nothing of the machine crosses but HTTP."""
    m = _ITS_OFFICE.match(request.url.path)
    if not m:
        return await call_next(request)
    office_app, machine = await run_in_threadpool(remote.office_of, m.group(1))
    if office_app is None:
        return await call_next(request)              # no linked office of that name: this app's own 404 says so
    if _declares_office(request):
        # a request that came through a door does not go on to a third office: as_rows does not re-share either
        return _err("בקשה שהגיעה מלשכה אחרת אינה ממשיכה ללשכה שלישית", 403)
    # what reaches another office's machine from here is what its door lets a linked office do there — running a
    # command, a terminal and its poll, on the one machine it gives — and nothing else (the second reader)
    local = f"/api/computers/{machine}{m.group(2) or ''}"
    poll = request.method == "GET" and re.fullmatch(rf"/api/computers/{re.escape(callermod.SHARED_MACHINE)}/shell/[0-9a-f]+",
                                                    local) is not None
    if not (callermod.door_allows(request.method, local) or poll):
        return _err("על מחשב של לשכה אחרת אפשר להריץ פקודה ולפתוח טרמינל, ולא יותר", 403,
                    action="את השאר מנהלים בלשכה שהמחשב שלה.")
    if request.method in WRITE_METHODS:
        # an IDENTIFIED caller only, in every mode: `warn` finds legacy callers, and nothing forwarded here is one —
        # an unknown container must not leave as this office's signed request (the second reader)
        who = getattr(request.state, "caller", None)
        if who is None or not who.ok:
            return _err("רק מתקשר מזוהה מריץ על מחשב של לשכה אחרת", 403,
                        action="מסך «מחשבים» דרך הקונסול, או טוקן של שירות.")
    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        return _err("גוף הבקשה חייב להיות JSON", 400)
    # EXACTLY the path that was checked above, encoded again — not the raw path, which a crafted `%2F` or an encoded
    # prefix could make differ from it (the second reader, round 2); an encoded `?` stays encoded
    path = (f"/api/computers/{machine}{urllib.parse.quote(m.group(2) or '', safe='/')}"
            + (f"?{request.url.query}" if request.url.query else ""))
    code, data = await run_in_threadpool(remote.fetch, office_app, request.method, path, payload, REMOTE_CALL_S)
    return JSONResponse(data, status_code=code)


@app.middleware("http")
async def _who_is_asking(request: Request, call_next):
    path = request.url.path
    if request.method not in WRITE_METHODS or path.startswith("/share/"):
        if path.startswith("/api/") and _declares_office(request):
            from_door, herd = await run_in_threadpool(_door_read, request)
            _count_door_read((request.headers.get(linkid.OFFICE_HEADER) or "") if from_door else NOT_THE_DOOR,
                             path, herd)                         # answered as before; counted
        return await call_next(request)               # reads stay open; a share's door has its own token
    who = await run_in_threadpool(identify_request, request)   # a signature may read the vault
    lp = _log_path(path)
    if who.ok and who.way == "door" and not callermod.door_allows(request.method, path):
        # A linked office was given THIS computer to run on — not the fleet, not its management. Refused in
        # EVERY mode: `warn` exists to find callers with no identity, and this one is identified; there is no
        # legacy caller to discover, only a door to keep shut (the second reader, round 2).
        why = (f"לשכה מקושרת מריצה פקודות על המחשב שהלשכה הזו נתנה לה ({callermod.SHARED_MACHINE}) ותו לא — "
               "לא מנהלת את הצי ולא מגיעה למחשב אחר")
        log.warning("REFUSED %s %s for %s: outside what a linked office is given", request.method, lp, who.who)
        return _err(why, 403, action="מכאן אפשר להריץ רק על המחשב המשותף; את השאר מנהלים בלשכה עצמה.")
    request.state.caller = who
    if who.note:
        log.info("caller note (%s %s): %s", request.method, lp, who.note)
    if not who.ok:
        addr = (request.client.host if request.client else "") or "?"
        say = _count(addr, request.method, path, who.why)
        if callermod.is_shell(path) and _declares_office(request):
            # A shell to this office's computer for a caller that SAID which office it is and failed the claim
            # (not from the door, not shared with, a bad signature): refused in every mode. `warn` is there to
            # find legacy callers with no identity; the shell routes have none, and a failed claim is not one
            # (the second reader). Exec and probe keep `warn` until their callers over the link are counted —
            # issues/a-failed-office-claim-on-exec-and-probe-passes-in-warn-until-their-callers-over-the-link-are-counted.yaml
            if say:
                log.warning("REFUSED %s %s from %s: %s", request.method, lp, addr, who.why)
            return _err(who.why, 403, action="טרמינל למחשב של לשכה אחרת נפתח דרך הקישור, למחשב שהיא משתפת.")
        if callermod.enforced(request.method, path, AUTH_MODE, ENFORCE_MACHINES):
            if say:
                log.warning("REFUSED %s %s from %s: %s", request.method, lp, addr, who.why)
            return _err(who.why, 403, action="מסך «מחשבים» דרך הקונסול, טוקן של שירות (Authorization: Bearer "
                                             "COMPUTERS_EXEC_TOKEN, לאפליקציה שמצהירה עליו ב-app.json), או "
                                             "לשכה מקושרת שהלשכה הזו משתפת איתה את המחשב.")
        if say:
            log.warning("WOULD REFUSE (warn) %s %s from %s: %s", request.method, lp, addr, who.why)
    else:
        log.info("write by %s (%s): %s %s", who.who, who.way, request.method, lp)
    return await call_next(request)


@app.get("/api/callers")
def api_callers():
    """The writes that had no known caller since this process started — what `enforce` would refuse. The
    gate counts these per office before `COMPUTERS_EXEC_AUTH=enforce` (`./bbox computers callers`). A plain
    def: FastAPI runs it in its threadpool, where the reverse lookups of the sources belong."""
    rows = sorted(({**r, "name": _name_of(r["source"]) if r["source"][:1].isdigit() else ""}
                   for r in list(_REFUSED.values())), key=lambda r: -r["count"])
    reads = sorted((dict(r) for r in list(_DOOR_READS.values())), key=lambda r: -r["count"])   # copies, as above
    return {"mode": AUTH_MODE, "enforce_machines": sorted(ENFORCE_MACHINES), "share_to": sorted(SHARE_TO),
            "token": bool(EXEC_TOKEN), "since": int(_REFUSED_SINCE), "unknown": rows,
            "count": sum(r["count"] for r in rows),
            # what other offices READ here through the link — counted, not refused (yet): each row says whether the door
            # called the office the herd's (by key); the reads of an office it did not are what narrowing would touch
            "door_reads": reads,
            "door_reads_not_herd": sum(r["count"] for r in reads if not r.get("herd") and r["office"] != NOT_THE_DOOR)}


# ── the herd: every office's computer (DGO-890) ─────────────────────────────────────────────────
# The resource view and the network view of a computer are what its own `machine` and `security`
# services say, read through `herd.Herd` — here, or through the door when it belongs to a linked
# office. Both are BASE services this app USES (app.json `use`), reached at their own addresses.
from herd import ALLOW as HERD_ALLOW, Herd  # noqa: E402 — the routes below are the only users

MACHINE_URL = os.environ.get("MACHINE_URL", "http://machine:8080").rstrip("/")
HERD = Herd(os.environ.get("COMPUTERS_REGISTRY", "/registry"),
            {"machine": MACHINE_URL, "security": os.environ.get("SECURITY_URL", "http://security:8995")},
            office=os.environ.get("DGO_OFFICE_ID", ""))
_CLEANUP_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def _lean_overview(ov: dict, brief: bool) -> dict:
    """machine's overview, without what no screen shows. Every container carries its compose LABELS
    (about 2 KB each: vps1's 74 containers made a 150 KB answer, through the link, every five seconds);
    the fleet list (`brief`) needs the figures and the last ten minutes of history, not the services."""
    out = dict(ov)
    out["containers"] = [] if brief else [{k: v for k, v in c.items() if k != "labels"}
                                          for c in (ov.get("containers") or []) if isinstance(c, dict)]
    if brief:
        out["history"] = (ov.get("history") or [])[-60:]
        st = dict(ov.get("storage") or {})
        st.pop("docker_df", None)
        st.pop("top_paths", None)
        out["storage"] = st
    return out


@app.get("/api/herd")
def api_herd():
    """This office's computer and every linked office's, with which of the two services each gives."""
    return {"office": HERD.office, "computers": HERD.computers(), "reads": {k: list(v) for k, v in HERD_ALLOW.items()}}


@app.get("/api/hosts/{where}/{svc}/{path:path}")
async def api_host_read(where: str, svc: str, path: str, request: Request):
    """ONE allowlisted read of `machine` or `security` on a computer of the herd (`where` = `local` or
    an office id). The answer is the service's own JSON, passed through; a refusal says why in Hebrew."""
    if where != "local" and not re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", where):
        return _err("מחשב לא מוכר", 404)
    status, body, why = await run_in_threadpool(HERD.get, where, svc, path, dict(request.query_params))
    if status == 200 and body is not None:
        if (svc, path.strip("/")) in (("machine", "api/overview"), ("security", "api/host/overview")) and isinstance(body, dict):
            body = _lean_overview(body, brief=request.query_params.get("brief") == "1")
        return JSONResponse(body, headers={"Cache-Control": "no-store"})
    return _err(why or "הקריאה נכשלה", status if status >= 400 else 502, where=where, service=svc)


@app.post("/api/hosts/local/machine/cleanup/{action_id}")
async def api_host_cleanup(action_id: str):
    """The ONE write of the merged screen, and only on THIS computer: one of machine's own cleanups,
    which machine itself allows or refuses (`MACHINE_CLEANUP_ALLOWED_ACTIONS`). A linked office's
    computer is cleaned from its own office — this door never reaches through the link."""
    if not _CLEANUP_ID.match(action_id or ""):
        return _err("פעולת ניקוי לא מוכרת", 400)
    try:
        r = await run_in_threadpool(lambda: requests.post(f"{MACHINE_URL}/api/cleanup/{action_id}", timeout=300))
    except requests.RequestException:
        return _err("שירות המכונה אינו זמין כרגע", 502)
    try:
        body = r.json()
    except ValueError:
        body = {"error": (r.text or "")[:300]}
    return JSONResponse(body, status_code=r.status_code)


def _resolve(cid: str, host: str) -> tuple[dict | None, JSONResponse | None]:
    """(computer, error_response). Everything that mutates or probes a machine goes through here,
    so no route invents its own idea of what a computer is."""
    insts, verr = vault_list()
    if verr:
        return None, _err(verr, 502)
    inst = next((i for i in insts if i.get("id") == cid), None)
    if not inst:
        return None, _err(f"לא נמצא מחשב בזהות {cid}", 404)
    rec = computer_record(inst, host)
    if not rec.get("host") and not secret_for(inst):
        # A row whose secret the vault will not hand over is not addressable: say so here rather
        # than ssh'ing to "None".
        return None, _err("לא ניתן לקרוא את פרטי החיבור של המחשב מהוולט", 502)
    return rec, None


@app.get("/healthz")
def healthz():
    return {"status": "ok", "office_key": bool(public_key())}


@app.get("/manifest")
def manifest():
    """The platform service contract (§2). `protocols` is what this service can connect, and the
    console's connect wizard is built from /providers — never from a map inside the console."""
    insts, err = vault_list()
    return {"service": "computers",
            "protocols": [PROTOCOL],
            "ops": ["list", "create", "delete", "status", "exec"],
            "connection": {"id": LOCAL_INSTANCE, "builtin": True, "protocol": PROTOCOL},
            "capabilities": {"multi_connection": True, "exec": True, "builtin_local": True,
                             "office_key": bool(public_key()),
                             "vault_available": err is None,
                             "vault_error": err,
                             "computers": len(insts) if err is None else None}}


@app.get("/readyz")
def readyz():
    """The built-in machine must RESOLVE — it is always registered — but it need not be approved:
    the fleet is usable the moment one machine answers. Ready = the vault is up and at least one
    machine's key is in place; the console shows the per-machine state."""
    insts, err = vault_list()
    if err:
        return JSONResponse({"ready": False, "reason": err}, status_code=503)
    if not any(i.get("id") == LOCAL_INSTANCE for i in insts):
        return JSONResponse({"ready": False,
                             "reason": "המחשב המובנה טרם נרשם בוולט — נסה שוב בעוד רגע"},
                            status_code=503)
    return {"ready": True, "connection_id": LOCAL_INSTANCE, "computers": len(insts)}


@app.get("/connections")
def connections(request: Request):
    """The platform service contract's instance list, in the console's own shape — the account bar
    renders machines from this, and never from a list of its own."""
    host = local_gateway()
    insts, err = vault_list()
    if err:
        return JSONResponse({"active": None, "connections": [], "reason": err}, status_code=200)
    # A row's status is what the last probe SAID — read from the cache, never by opening SSH from
    # the account bar. It was the literal "ok" of the record, so the bar showed a green dot for a
    # machine the page under it showed in error.
    def said(c: dict) -> dict:
        with _probe_lock:
            hit = _probe_cache.get(c.get("id"))
        return c if not hit or hit[1].get("state") in ("ok", "no_ssh") else {**c, "status": "error"}
    rows = [said(computer_record(i, host)) for i in insts]
    rows.sort(key=lambda c: (not c.get("builtin"), c.get("label") or ""))
    return {"active": LOCAL_INSTANCE, "connections": rows,
            "builtin": LOCAL_INSTANCE, "protocol": PROTOCOL}


@app.post("/connections/select")
async def connections_select(request: Request):
    """ONE binding today (this service addresses machines by id), so selecting is a check that the
    machine exists — accepted, and said plainly, rather than pretending to move a pointer."""
    body = await request.json() if await request.body() else {}
    cid = (body or {}).get("id")
    host = local_gateway()
    rec, bad = _resolve(cid or "", host)
    if bad:
        return bad
    invalidate(cid)
    return {"ok": True, "active": cid, "liveness": {k: rec.get(k) for k in ("id", "label", "host")}}


@app.post("/connections")
async def connections_add(request: Request):
    # the request itself, not its parsed body: api_computers_post reads the body (Starlette keeps it) — handed a dict,
    # it called `.body()` on the dict and every add through this route was a 500 (the second reader, 2026-11-10)
    return await api_computers_post(request)


@app.delete("/connections/{cid}")
async def connections_delete(cid: str):
    return await api_computers_delete(cid)


@app.get("/providers")
def providers():
    """This service's OWN provider catalogue (§4b: the user picks a provider, never a protocol).

    One provider, because there is one way to attach a machine — the office's key, approved by the
    owner on the machine itself. It is deliberately NOT `builtin` (that flag means "a private engine
    you already run, nothing to provide"), even though the local machine is built in: the METHOD
    still requires the owner to approve the key somewhere.
    """
    needs = ["host", "user"] if public_key() else ["host", "user", "private_key"]
    return {"providers": [{
        "id": "ssh_key",
        "name": "מחשב ב־SSH",
        "icon": "terminal",
        "description": "שרת או מחשב שמחובר ללשכה באמצעות מפתח SSH.",
        "auth_methods": [{
            "id": "office_key",
            "label": "מפתח הלשכה (מומלץ)",
            "protocol": PROTOCOL,
            "needs": needs,
            "recommended": True,
            "can": "הרצת פקודות וקריאת מצב (hostname, עומס, זיכרון, דיסק) במחשב.",
            "explain": "הלשכה מחזיקה מפתח אחד משלה. מאשרים את המפתח הציבורי במחשב — פעם אחת — "
                       "והמחשב מצטרף. הסיסמה שלך אינה נשמרת בשום מקום.",
        }],
    }]}


def _computer_ctx(rec: dict, host: str) -> tuple[dict, dict]:
    """(secret-for-ssh, machine-identity) for a resolved computer."""
    if rec.get("builtin"):
        sec = {"auth": "office_key"}
    else:
        sec = secret_for({"id": rec.get("id")})
    return sec, rec


@app.get("/api/computers")
def api_computers(request: Request = None, probe: int = 1, shared: int = 1):   # FastAPI injects it; a direct call may not
    """The fleet. `?probe=0` skips the SSH round trip (fast, for a background refresh). `?shared=0` leaves out the
    machines linked offices share — what one office asks of another, so two offices never ask each other in a loop.

    (DGO-553's rows are asked only for a person's screen: never when the request came through a door, whatever its
    `shared` says — an older peer does not send it — or each office would ask the other back, every 15 s, at once.)"""
    return _fleet(probe, bool(shared) and not (request is not None and _declares_office(request)))


def _last_said(rec: dict) -> dict:
    """A row of `?probe=0`: the record with what its last probe SAID, read from the cache — no SSH, whatever its age
    (`checked_at` says it). A machine never probed is the bare record, so its reader says «unknown».

    It was the bare record always: the terminal (and apps/terminal before it) read `ok`/`state` off this list and
    showed «לא ידוע» for every machine, and a linked office's shared row (DGO-553, asked with `probe=0`) carried no
    state at all — issues/the-fleet-without-a-probe-answered-no-state-so-the-terminal-showed-every-machine-unknown.yaml"""
    with _probe_lock:
        hit = _probe_cache.get(rec.get("id"))
    if not hit:
        return rec
    return {**rec, **{k: v for k, v in hit[1].items() if k != "id"}, "cached": True}


def _fleet(probe: int, with_shared: bool) -> dict:
    """The fleet. `?probe=0` skips the SSH round trip (fast, for a background refresh).

    The machines are probed AT ONCE, not in turn (DGO-1359): each probe waits up to ssh's 8 s for a machine
    that does not answer, so in turn the fleet took the sum — the MacBook away from home, its two LAN machines
    out of reach, answered in 17–20 s, and every reader with a shorter patience read «did not answer». At once
    it takes the slowest one. Each probe keeps its own cache and timeout (`probe`)."""
    host = local_gateway()
    insts, err = vault_list()
    if err:
        return _err(err, 502)
    recs = [computer_record(i, host) for i in insts]

    def probed(rec: dict) -> dict:
        sec, _ = _computer_ctx(rec, host)
        st = probe_computer(rec, sec, max_age=PROBE_TTL)
        return {**rec, **{k: v for k, v in st.items() if k != "id"}}

    if probe and recs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(recs)),
                                                   thread_name_prefix="probe") as pool:
            out = list(pool.map(probed, recs))
    else:
        out = [_last_said(rec) for rec in recs]
    out.sort(key=lambda c: (not c.get("builtin"), not c.get("ok"), c.get("label") or ""))
    shared, shared_from = _shared_machines() if with_shared else ([], [])
    return {"computers": out + shared, "count": len(out) + len(shared), "builtin": LOCAL_INSTANCE,
            "office_key": {"public_key": public_key(), "fingerprint": key_fingerprint(),
                           "user": LOCAL_USER, "local_host": host},
            # the linked offices asked, and the one that did not answer named — its machine absent, not stale
            "shared_from": shared_from}


#: how long one linked office may take to answer its list, and how long the answers are kept (the screen asks often)
REMOTE_LIST_S = float(os.environ.get("COMPUTERS_REMOTE_LIST_S", "4"))
_SHARED: dict = {"at": 0.0, "rows": [], "from": []}
_SHARED_LOCK = threading.Lock()


def _shared_machines() -> tuple[list[dict], list[dict]]:
    """(rows, shared_from): the machine each linked office gives this one, as rows of this fleet addressed
    `<machine>.<office>` (remote.as_rows; DGO-553) — asked of every office at once, each within REMOTE_LIST_S.

    ONE machine per office: its own (`caller.SHARED_MACHINE`), which is all a linked office's door may run on there
    (`door_allows`). A peer answers its whole list today (issues/a-linked-office-reading-computers-…): a row for a
    machine it would refuse is a button that fails, so only the one it gives is listed."""
    with _SHARED_LOCK:
        if time.time() - _SHARED["at"] < remote.REMOTE_TTL:
            return list(_SHARED["rows"]), list(_SHARED["from"])
    offices = remote.apps()
    if not offices:
        return [], []

    def ask(office_app: dict):
        return office_app, *remote.fetch(office_app, "GET", "/api/computers?probe=0&shared=0", timeout=REMOTE_LIST_S)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(offices)), thread_name_prefix="peer") as pool:
        answers = list(pool.map(ask, offices))
    rows, said = [], []
    for office_app, code, data in answers:
        head = {"office": office_app["office"], "label": office_app.get("label") or office_app["office"]}
        if code >= 300:
            said.append({**head, "ok": False, "why": (data or {}).get("error") or f"({code})"})
            continue
        if not isinstance(data.get("computers"), list):        # a page that is not the list (the door's wall) is not ok
            said.append({**head, "ok": False, "why": data.get("error") or "התשובה אינה רשימת מחשבים"})
            continue
        given = [c for c in data["computers"] if c.get("id") == callermod.SHARED_MACHINE]
        rows += remote.as_rows(office_app, {"computers": given})
        said.append({**head, "ok": True})
    with _SHARED_LOCK:
        _SHARED.update(at=time.time(), rows=rows, **{"from": said})
    return list(rows), list(said)


def probe_computer(rec: dict, sec: dict, max_age: float = PROBE_TTL) -> dict:
    return probe(rec["id"], rec["host"], rec["port"], rec["user"], sec, max_age=max_age,
                 builtin=bool(rec.get("builtin")))


@app.post("/api/computers")
async def api_computers_post(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    host = (body.get("host") or "").strip()
    user = (body.get("user") or "root").strip() or "root"
    label = (body.get("label") or "").strip()
    door = (body.get("door") or "").strip()
    if door:
        # A computer another office shared with this one: its address IS the door the lender
        # printed (POST /api/computers/<id>/shares there). The host is the door's, for display.
        m = DOOR_RE.match(door)          # ONE definition of a door (see _door_opts), used twice
        if not m:
            return _err("הדלת אינה כתובת שיתוף תקינה (wss://<host>/share/<token>)", 400)
        host = host or m.group(1).split(":")[0]
    if not host:
        return _err("חסרה כתובת (host)", 400)
    if re.search(r"[\s;|&$`'\"]", host) or host.startswith("-"):
        return _err("הכתובת אינה תקינה", 400)
    try:
        check_destination(user, host)                # the user too: `-oProxyCommand=…` is an ssh option, not a name
    except BadDestination as e:
        return _err(str(e), 400)
    try:
        port = int(body.get("port") or 22)
    except (TypeError, ValueError):
        return _err("הפורט אינו מספר", 400)
    if not (1 <= port <= 65535):
        return _err("הפורט מחוץ לטווח", 400)
    secret = {"host": host, "port": port, "user": user}
    if door:
        secret["door"] = door
    if (body.get("private_key") or "").strip():
        secret["private_key"] = body["private_key"]
    if not door and host == local_gateway() and user == LOCAL_USER and port == LOCAL_PORT:
        # The machine we are running on is BUILT IN and already registered — adding it again would
        # create a second row for one machine, which is exactly the drift the local instance exists
        # to prevent.
        return _err("זו המכונה שהלשכה רצה עליה — היא מופיעה מובנית ואין צורך להוסיף אותה", 409,
                    id=LOCAL_INSTANCE)
    res, status = vault_add(secret, label or f"{user}@{host}", body.get("account_hint") or host)
    if status >= 300:
        return JSONResponse(res, status_code=status)
    cid = res.get("id")
    forget_secret(cid)
    log.info("computer added: %s (%s@%s:%s)", cid, user, host, port)
    # off the event loop, like /exec: a probe is an SSH round trip, and a shared computer's round
    # trip may come back through this very app's door
    st = await run_in_threadpool(probe, cid, host, port, user, secret, max_age=0)
    return {"id": cid, "label": label or f"{user}@{host}", "host": host, "port": port, "user": user,
            "status": "ok", "removable": True, "builtin": False, "shared": bool(door), "probe": st}


@app.delete("/api/computers/{cid}")
def api_computers_delete(cid: str):
    host = local_gateway()
    insts, err = vault_list()
    if err:
        return _err(err, 502)
    inst = next((i for i in insts if i.get("id") == cid), None)
    if not inst:
        return _err("לא נמצא מחשב כזה", 404)
    if is_local_instance(inst, host):
        # Guarded by ADDRESS, not by id: a row for the local machine that nobody promoted to the
        # canonical id is still the local machine, and deleting it removes the office's own hands.
        return _err("המחשב הזה הוא המכונה שהלשכה רצה עליה ואינו ניתן למחיקה", 409, id=cid)
    res, status = vault_delete(cid)
    invalidate(cid)
    forget_secret(cid)
    if status >= 300:
        return JSONResponse(res, status_code=status)
    log.info("computer removed: %s", cid)
    return {"ok": True, "id": cid}


@app.get("/api/computers/{cid}/status")
def api_computer_status(cid: str, fresh: int = 0):
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    sec, _ = _computer_ctx(rec, local_gateway())
    st = probe_computer(rec, sec, max_age=0 if fresh else PROBE_TTL)
    return {**rec, **st}


@app.post("/api/computers/{cid}/exec")
async def api_computer_exec(cid: str, request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    command = body.get("command")
    if not isinstance(command, str) or not command.strip():
        return _err("חסרה פקודה (command)", 400)
    try:
        timeout = int(body.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return _err("ה־timeout אינו מספר", 400)
    timeout = max(1, min(MAX_TIMEOUT, timeout))
    # the command's standard input — how a secret reaches the machine (ssh_run's docstring): never
    # logged, never echoed back; only its length is said
    stdin, raw = body.get("stdin"), None
    if stdin is not None:
        try:                                      # once: a lone surrogate is a 400, not a 500
            raw = stdin.encode() if isinstance(stdin, str) else None
        except UnicodeEncodeError:
            raw = None
        if raw is None or len(raw) > STDIN_MAX:
            return _err(f"stdin חייב להיות טקסט של עד {STDIN_MAX} בתים", 400)
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    sec, _ = _computer_ctx(rec, local_gateway())
    who = getattr(request.state, "caller", None)
    log.info("exec on %s by %s: %s%s", cid, f"{who.who} ({who.way})" if who and who.ok else "UNKNOWN",
             command.strip().splitlines()[0][:200], f" (stdin {len(raw)} bytes)" if raw is not None else "")
    # OFF THE EVENT LOOP, always. `ssh_run` blocks for as long as the command runs — up to
    # MAX_TIMEOUT — and this handler is `async`, so it ran INSIDE the single uvicorn worker's loop:
    # one long command made every other request wait, including `/healthz`. Measured 2026-10-04:
    # `/healthz` took 30 s and the container's own healthcheck failed 5 runs in a row (exit 1 on its
    # 8 s budget) while a long `exec` was in flight — an office whose door to its machines reports
    # unhealthy exactly when it is being used, and restarts itself under `autoheal`.
    # one bar in «כל מקביל»: `command.started`, then `.ended` (exit 0) or `.failed`, sharing `data.span`
    title = f"{cid}: {_first_word(command)}"
    bar = {"cid": cid, "caller": who.who if who and who.ok else "", "way": who.way if who and who.ok else "",
           "span": uuid.uuid4().hex[:12]}
    t0 = int(time.time() * 1000)
    _flow("command.started", title, bar)
    try:
        res = await run_in_threadpool(ssh_run, cid, rec["host"], rec["port"], rec["user"], sec,
                                      command, timeout, raw)
    except BaseException as e:
        _flow("command.failed", title, {**bar, "t0": t0, "ms": int(time.time() * 1000) - t0,
                                        "error": type(e).__name__})
        raise
    _flow("command.ended" if res.get("code") == 0 else "command.failed", title,
          {**bar, "t0": t0, "ms": int(time.time() * 1000) - t0, "exit": res.get("code")})
    return {"id": cid, "command": command, "timeout": timeout,
            **({"stdin_bytes": len(raw)} if raw is not None else {}), **res}


# ── an interactive shell: the terminal app's screen over shell.py ─────────────────────────────────────────────────
# The manifest promised `shell` (app.json required_ops) and the terminal app has called these five since it
# arrived (apps/terminal/app.py: open, input, poll, resize, close); shell.py, the session manager, waited with its
# test and no caller — no route joined them (issues/the-terminal-app-calls-shell-routes-the-computers-app-never-had).
# Ordinary HTTP, as shell.py says why. The same door as /exec: the same machine record, the same key, the same
# pinned host key — the session is ssh with a terminal (-tt) and no command, so the machine's login shell — and
# the same caller check (writes pass _who_is_asking; caller.RUN_RE counts the shell as running something on that
# machine). A session belongs to the caller that opened it: the poll, a read the middleware does not identify,
# identifies its caller here, and another caller's session answers as one that does not exist (shell.get).
import shell as shellmod  # noqa: E402


def shell_argv(cid: str, rec: dict, sec: dict) -> list[str]:
    """ssh_argv's own command line with a terminal (-tt), no escape character (-e none: `~C` cannot add a forward)
    and no command: the machine's login shell. The same checks as ssh_run, refused with a sentence."""
    ensure_key()
    if not _key_path_for({**sec, "_instance": cid}):
        raise shellmod.ShellError("לא נוצר עדיין מפתח SSH ללשכה", 409, "רענן את הדף — המפתח נוצר אוטומטית עם עליית השירות.")
    try:
        argv = ssh_argv(cid, rec["host"], rec["port"], rec["user"], sec, "", 8)[:-1]
    except BadDestination as e:                      # a record saved before its user or host was checked
        raise shellmod.ShellError(str(e), 409, "תקן את פרטי המחשב במסך «מחשבים» (מחק והוסף אותו מחדש).") from e
    except ValueError as e:                          # a `door` in the vault that is not a share address
        raise shellmod.ShellError("כתובת השיתוף של המחשב אינה תקינה", 409, str(e)) from e
    argv[1:1] = ["-tt", "-e", "none"]
    return argv


def _shell_owner(request: Request, who=None) -> str:
    who = who or getattr(request.state, "caller", None)
    return who.who if who is not None else ""


def _shell_size(body: dict) -> tuple[int, int]:
    def num(v, lo, hi, dflt):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError, OverflowError):        # JSON's Infinity is a float int() cannot take
            return dflt
    return num(body.get("cols"), 20, 400, 100), num(body.get("rows"), 5, 200, 30)


def _shell_state(s, cursor, wait: float = 0.0) -> dict:
    """What the screen draws: the bytes after `cursor`, the cursor to send next, whether bytes were lost before
    it, and whether the shell still runs (its reason when it ended)."""
    capped = s.drain(wait)
    try:
        cursor = max(0, int(cursor or 0))
    except (TypeError, ValueError, OverflowError):            # JSON's Infinity, after the keys were written
        cursor = 0
    data, nxt, lost = s.since(cursor)
    # the cursor stops on a whole character: a UTF-8 sequence cut between two reads is held back for the next one,
    # not drawn as two «�» (Hebrew is two bytes a letter)
    hold = _utf8_tail(data)
    if hold:
        data, nxt = data[:-hold], nxt - hold
    # a drain that stopped on its cap may have left the shell's last words in the pty: the reader is told to come
    # back for them, even when ssh has already ended
    alive = s.alive() or bool(capped)
    return {"session": s.key.rsplit(":", 1)[1], "cursor": nxt, "lost": lost, "alive": alive,
            "output": data.decode("utf-8", "replace"), **({"reason": s.error} if not alive and s.error else {})}


def _utf8_tail(b: bytes) -> int:
    """How many bytes at the end of `b` begin a UTF-8 character that is not complete yet (0–3)."""
    for back in range(1, min(4, len(b)) + 1):
        c = b[-back]
        if c & 0xC0 != 0x80:                           # the lead byte of the last character
            need = 2 if c & 0xE0 == 0xC0 else 3 if c & 0xF0 == 0xE0 else 4 if c & 0xF8 == 0xF0 else 1
            return back if back < need else 0
    return 0


def _shell_err(e: "shellmod.ShellError"):
    return _err(str(e), e.status, action=e.action)


async def _shell_body(request: Request):
    """The JSON object a shell route takes, or None (a list, a number or text that is not JSON is no body)."""
    try:
        body = (await request.json()) if await request.body() else {}
    except ValueError:                                        # not JSON, or not UTF-8
        return None
    return body if isinstance(body, dict) else None


def _shell_open(cid: str, cols: int, rows: int, owner: str):
    """(session, None) or (None, the refusal) — the vault's reads, the key check and the pty, all of it in the
    threadpool: each vault read may wait its full timeout, and none of that is the event loop's."""
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return None, bad
    sec, _ = _computer_ctx(rec, local_gateway())
    return shellmod.start(cid, shell_argv(cid, rec, sec), cols, rows, owner), None


@app.post("/api/computers/{cid}/shell")
async def api_shell_open(cid: str, request: Request):
    body = await _shell_body(request)
    if body is None:
        return _err("גוף הבקשה חייב להיות אובייקט JSON", 400)
    cols, rows = _shell_size(body)
    who = getattr(request.state, "caller", None)
    owner = _shell_owner(request)
    try:
        s, bad = await run_in_threadpool(_shell_open, cid, cols, rows, owner)
    except shellmod.ShellError as e:
        return _shell_err(e)
    if bad:
        return bad
    log.info("shell on %s by %s", cid, f"{who.who} ({who.way})" if who and who.ok else "UNKNOWN")
    return await run_in_threadpool(_shell_state, s, 0, 0.6)    # the login banner and the first prompt


@app.post("/api/computers/{cid}/shell/{sid}/input")
async def api_shell_input(cid: str, sid: str, request: Request):
    body = await _shell_body(request)
    if body is None:
        return _err("גוף הבקשה חייב להיות אובייקט JSON", 400)
    data = body.get("data") or ""
    if not isinstance(data, str) or len(data.encode("utf-8", "replace")) > 65536:
        return _err("הקלט לטרמינל חייב להיות טקסט של עד 64KB", 400)
    try:
        s = await run_in_threadpool(shellmod.get, cid, sid, _shell_owner(request))   # it may wait on an open's fork
        await run_in_threadpool(s.write, data)
    except shellmod.ShellError as e:
        return _shell_err(e)
    return await run_in_threadpool(_shell_state, s, body.get("cursor"), 0.12)   # give the shell a moment to echo


@app.get("/api/computers/{cid}/shell/{sid}")
async def api_shell_poll(cid: str, sid: str, request: Request, cursor: int = 0):
    who = await run_in_threadpool(identify_request, request)   # a read: the middleware did not ask who
    if not who.ok and _declares_office(request):
        # as the middleware refuses the writes of one — and counted and logged as they are
        addr = (request.client.host if request.client else "") or "?"
        if _count(addr, "GET", request.url.path, who.why):
            log.warning("REFUSED GET %s from %s: %s", _log_path(request.url.path), addr, who.why)
        return _err(who.why, 403)
    try:
        s = await run_in_threadpool(shellmod.get, cid, sid, _shell_owner(request, who))
    except shellmod.ShellError as e:
        return _shell_err(e)
    return await run_in_threadpool(_shell_state, s, cursor, 0.0)


@app.post("/api/computers/{cid}/shell/{sid}/resize")
async def api_shell_resize(cid: str, sid: str, request: Request):
    body = await _shell_body(request)
    if body is None:
        return _err("גוף הבקשה חייב להיות אובייקט JSON", 400)
    cols, rows = _shell_size(body)
    try:
        s = await run_in_threadpool(shellmod.get, cid, sid, _shell_owner(request))
        await run_in_threadpool(s.resize, cols, rows)          # it waits on the session's lock: never on the loop
    except shellmod.ShellError as e:
        return _shell_err(e)
    return {"session": sid, "cols": cols, "rows": rows}


@app.delete("/api/computers/{cid}/shell/{sid}")
async def api_shell_close(cid: str, sid: str, request: Request):
    try:
        s = await run_in_threadpool(shellmod.get, cid, sid, _shell_owner(request))
    except shellmod.ShellError as e:
        if e.status == 404:
            return {"session": sid, "closed": True}           # already gone: what was asked is so
        return _shell_err(e)
    await run_in_threadpool(s.close)
    return {"session": sid, "closed": True}


@app.post("/api/computers/{cid}/stream")
@app.post("/api/computers/{cid}/transfer")
async def api_transfer(cid: str, request: Request):
    """Stream a docker volume from this machine to another one — resumable, with progress.

    `/stream` is the op's name (computers.v1); `/transfer` is the name it shipped under and stays as
    the same door, so an older caller is not broken by a rename. See transfer.py for why the bytes
    pass through this app (no key ever travels) and how a dropped link resumes at the byte offset
    the destination already holds.

    Body: `to`, `volume`, optional `dest_volume`, `restart` (start over), `verify` (sha256 compare,
    default true), `measure` (measure the archive on the source, default true), `resume` (false =
    stream straight into the destination volume: no staging file, no resume)."""
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    to = (body.get("to") or "").strip()
    volume = (body.get("volume") or "").strip()
    if not to or not volume:
        return _err("חסרים to (מכונת היעד) ו-volume", 400)
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    dst, bad_dst = _resolve(to, local_gateway())
    if bad_dst:
        return bad_dst
    try:   # said here, not as a queued job that fails in its thread a moment later (the second reader)
        check_destination(rec["user"], rec["host"])
        check_destination(dst["user"], dst["host"])
    except BadDestination as e:
        return _err(str(e), 409, action="תקן את פרטי המחשב במסך «מחשבים» (מחק והוסף אותו מחדש).")

    def argv_for(machine_id: str, command: str) -> list[str]:
        if machine_id == cid:
            sec, _ = _computer_ctx(rec, local_gateway())
            return ssh_argv(cid, rec["host"], rec["port"], rec["user"], sec, command)
        sec, _ = _computer_ctx(dst, local_gateway())
        return ssh_argv(to, dst["host"], dst["port"], dst["user"], sec, command)

    import transfer                    # local import: this app must start even if the module is absent
    res = transfer.start(argv_for, frm=cid, to=to, volume=volume,
                         dest_volume=(body.get("dest_volume") or "").strip() or None,
                         restart=bool(body.get("restart")),
                         verify=body.get("verify", True) is not False,
                         measure=body.get("measure", True) is not False,
                         resume=body.get("resume", True) is not False)
    if res.get("error"):
        return _err(res["error"], 409, active=res.get("active_job"))
    return res


@app.get("/api/transfers")
def api_transfers():
    import transfer
    return {"transfers": transfer.jobs()}


@app.get("/api/transfers/{job}")
def api_transfer_status(job: str):
    import transfer
    row = transfer.status(job)
    if not row:
        return _err("אין העברה כזו", 404)
    return {"transfer": row}


@app.post("/api/transfers/{job}/cancel")
def api_transfer_cancel(job: str):
    """Stop an attempt and KEEP the staging file on the destination: a cancelled copy is a paused
    one, and the next run continues from the size of that file."""
    import transfer
    res = transfer.cancel(job)
    if res.get("error"):
        return _err(res["error"], 404)
    return res


@app.get("/api/office-key")
def api_office_key():
    host = local_gateway()
    pub = public_key()
    user, port = LOCAL_USER, LOCAL_PORT
    import share
    return {"public_key": pub, "fingerprint": key_fingerprint(),
            "authorize_command": (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && {share.END_LAST_LINE} && "
                                  f"echo '{pub}' >> ~/.ssh/authorized_keys && "
                                  f"chmod 600 ~/.ssh/authorized_keys") if pub else "",
            "local": {"id": LOCAL_INSTANCE, "label": LOCAL_LABEL, "host": host, "user": user,
                      "port": port},
            "hint": "הרץ את הפקודה במחשב שאליו מתחברים (בתור אותו משתמש), ואז רענן כאן."}


@app.post("/api/computers/{cid}/authorize-command")
async def api_authorize_command(cid: str):
    """The exact command that approves the office key ON the machine — as a copy-paste string.

    This is the whole onboarding: the owner runs it on the machine (as the user that instance names),
    and nothing is exchanged the other way. It is presented, not executed for them: the app has no
    business logging into a machine it has not been authorised on, and the owner should see the
    command that changes that machine before it runs.
    """
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    pub = public_key()
    if not pub:
        return _err("המפתח של הלשכה טרם נוצר", 503)
    import share
    return {"id": cid, "user": rec.get("user"), "host": rec.get("host"),
            "public_key": pub, "fingerprint": key_fingerprint(),
            "command": (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && {share.END_LAST_LINE} && "
                        f"echo '{pub}' >> ~/.ssh/authorized_keys && "
                        f"chmod 600 ~/.ssh/authorized_keys")}


# ── sharing a computer with another office (share.py) ─────────────────────────────

def _public_host() -> str:
    """The host the door is reached at from outside: this app's own public host."""
    v = os.environ.get("COMPUTERS_PUBLIC_HOST", "").strip()
    if not v:
        domain = os.environ.get("DEPLOYMENT_DOMAIN", "").strip()
        v = f"computers.{domain}" if domain else "computers.localhost"
    return re.sub(r"^https?://", "", v).rstrip("/")


@app.post("/api/computers/{cid}/shares")
async def api_share_create(cid: str, request: Request):
    """Lend this computer to another office: `{to, public_key}` → the door, shown ONCE.

    `public_key` is the BORROWING office's office key (its GET /api/office-key). It is put in the
    machine's authorized_keys through this office's own access — so a machine is shareable exactly
    when this office can already reach it, the built-in host included."""
    import share
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    to = (body.get("to") or "").strip()
    blob = share.key_blob(body.get("public_key") or "")
    if not share.TO_RE.match(to):
        return _err("חסר שם הלשכה שמקבלת את השיתוף (to): אותיות, ספרות, ._-", 400)
    if not blob:
        return _err("המפתח הציבורי אינו תקין (ssh-ed25519 …)", 400)
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    if rec.get("shared"):
        return _err("מחשב ששותף עם הלשכה הזאת אינו ניתן לשיתוף הלאה", 409)
    sec, _ = _computer_ctx(rec, local_gateway())
    sid = share.new_id()
    # The record FIRST, the key second, and the record is pulled back if the key does not land:
    # the one state this must never reach is a root key in authorized_keys that no row names,
    # because nothing could then list it or revoke it.
    row, token = await run_in_threadpool(share.create, STATE_DIR, sid, rec["id"], to, blob)
    res = await run_in_threadpool(ssh_run, rec["id"], rec["host"], rec["port"], rec["user"], sec,
                                  share.authorize_command(sid, to, blob), 30)
    if res.get("code") != 0:
        await run_in_threadpool(share.drop, STATE_DIR, sid)
        return _err("לא ניתן היה להוסיף את המפתח במחשב", 502, reason=res.get("reason"),
                    action=res.get("action"), stderr=(res.get("stderr") or "")[:1000])
    log.info("computer %s shared with %s as %s", rec["id"], to, sid)
    return {"share": row, "user": rec["user"], "door": f"wss://{_public_host()}/share/{token}",
            "note": "הדלת מוצגת פעם אחת בלבד. בלשכה המקבלת: POST /api/computers "
                    "{\"door\": …, \"user\": …, \"label\": …}"}


@app.get("/api/shares")
def api_shares(computer: str = ""):
    import share
    return {"shares": share.rows(STATE_DIR, computer or None)}


@app.delete("/api/shares/{sid}")
async def api_share_revoke(sid: str):
    """Revoke a share: the borrower's key leaves the machine, then the door closes.

    `key_removed` is the machine's own count of the lines left tagged with this share — NOT ssh's
    exit code, which the removal command used to make zero whatever happened. When the key could not
    be removed the row is KEPT: dropping it would leave a key with root login and nothing that names
    it. A live door already relaying is not cut here (OpenSSH keeps established sessions either way);
    what closes is every new one.
    """
    import share
    row = await run_in_threadpool(share.get, STATE_DIR, sid)
    if not row:
        return _err("אין שיתוף כזה", 404)
    computer = row.get("computer")
    if not computer:
        return _err("השיתוף חסר את המחשב שלו — הסר אותו ידנית מ־shares.json", 409, id=sid)
    rec, bad = _resolve(computer, local_gateway())
    removed = False
    if not bad:
        sec, _ = _computer_ctx(rec, local_gateway())
        res = await run_in_threadpool(ssh_run, rec["id"], rec["host"], rec["port"], rec["user"], sec,
                                      share.revoke_command(sid), 30)
        removed = (res.get("stdout") or "").strip() == "0" and res.get("code") == 0
    if removed:
        await run_in_threadpool(share.drop, STATE_DIR, sid)
    log.info("share %s revoked (key removed from the machine: %s)", sid, removed)
    return {"ok": True, "id": sid, "key_removed": removed, "still_listed": not removed,
            **({} if removed else {"warning": "הדלת נסגרה לחיבורים חדשים, אך המפתח לא הוסר מהמחשב — "
                                              f"הסר את השורה '{share.TAG}:{sid}:' מ־authorized_keys; "
                                              "השיתוף נשאר ברשימה כדי שלא ייעלם בלי עקבה"})}


@app.get("/share/{path:path}")
def share_http(path: str):
    """The door is a WEBSOCKET. A plain request — a browser tab, a curl — is refused with 403 and
    nothing else: not the app's SPA (this app serves its screens from a catch-all, which would answer
    200 here) and not a sign-in redirect. A 403 is the honest answer, and it says the door is routed.

    The whole `/share/` prefix, not one segment: `/share/` and `/share/<token>/x` reached the SPA
    through the catch-all on an unauthenticated public path until this route was widened.
    """
    return _err("הדלת נפתחת רק בחיבור WebSocket", 403)


@app.websocket("/share/{token}")
async def share_door(ws: WebSocket, token: str):
    """The door: one SSH connection, relayed byte for byte to the shared machine's sshd.

    Every socket this opens is closed on every path, including the ones that leave early: the sshd
    connection is opened BEFORE `accept()` (a door that cannot reach sshd must not look open), so the
    two live in one `try/finally` rather than in a sequence of early returns.
    """
    import share
    row = await run_in_threadpool(share.find, STATE_DIR, token)
    rec = None
    if row:
        rec, _ = await run_in_threadpool(_resolve, row.get("computer"), local_gateway())
    if not rec:
        await ws.close(code=1008)
        return
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(rec["host"], int(rec["port"] or 22)), 10)
    except (OSError, asyncio.TimeoutError) as e:
        log.warning("share %s: %s:%s unreachable: %s", row["id"], rec["host"], rec["port"], e)
        await ws.close(code=1011)
        return

    tasks: list[asyncio.Task] = []
    try:
        await ws.accept()
        log.info("share %s: open (%s → %s)", row["id"], row.get("to"), row.get("computer"))

        async def up():
            try:
                while True:
                    writer.write(await ws.receive_bytes())
                    await writer.drain()
            except (WebSocketDisconnect, RuntimeError, KeyError, ConnectionError):
                pass

        async def down():
            # a client that vanishes mid-relay raises HERE; unretrieved, it is a warning on every
            # dropped session and nothing else — the finally below is what actually cleans up
            try:
                while chunk := await reader.read(65536):
                    await ws.send_bytes(chunk)
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                pass

        tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, RuntimeError):
            pass
        try:
            await ws.close()
        except RuntimeError:
            pass
        log.info("share %s: closed", row.get("id"))


@app.post("/api/computers/{cid}/probe")
def api_computer_probe(cid: str):
    # A plain def, like the status route it calls: FastAPI runs it in its threadpool, so the ssh round
    # trip never blocks the event loop. `await` on that plain function was a TypeError — every «בדוק
    # מחדש» answered 500 (measured on the MacBook 2026-10-30, DGO-1037).
    invalidate(cid)
    return api_computer_status(cid, fresh=1)


# ── /audit: is the MACHINE itself secure? ────────────────────────────────────────────────────────
# The site security check in `apps/sites` asks about a website's external posture. THIS asks about
# the box the websites run on — the other half of "is my business safe", and the half nobody looks
# at until something is already wrong: an SSH daemon accepting passwords, a firewall that was never
# enabled, a server six months behind on security updates, a container running with the engine socket
# mounted in it.
#
# The remote script only GATHERS facts (`key=value`, one per line) and every judgement is made here,
# in Python: a rule written in shell is a rule nobody can unit-test, and an audit whose findings
# cannot be reviewed in a diff is an audit people stop reading.
# What sshd ITSELF will do (DGO-415). The last matching line of sshd_config and its drop-ins concatenated was
# how this audit called Exampleu's keys-only server «accepts passwords» and «root may log in» (2026-11-10).
# * `sshd -T` prints the settings in force — only as root; as anyone else it prints nothing on stdout.
# * Without it, the files are read the way sshd reads them:
#   - `keyword value` and `keyword=value` alike, quotes off, a trailing comment off;
#   - an Include read where it stands (relative to /etc/ssh, globs expanded), the FIRST value of a keyword
#     wins;
#   - a Match line ends its file's OWN settings: what follows is conditional, and after an Include the
#     parent's state is the parent's again. Those lines come out as «@match …»;
#   - an unreadable file says «@unread …», because a value that might be in it is unknown, not absent;
#   - where the files say nothing, sshd's own defaults: PasswordAuthentication yes, PermitRootLogin
#     prohibit-password. `sshd -T` prints them itself, so the two paths agree.
# * A Match block that loosens a login (passwords, root, empty passwords) is counted either way: `sshd -T`
#   shows only the server's own settings.
# Kept apart from AUDIT_SH so its test runs this part alone (tests/test_audit_ssh.py).
AUDIT_SSH_SH = r"""
sshd_flat() {
  [ -r "$1" ] || { printf '@unread %s\n' "$1"; return 0; }
  m=
  while IFS= read -r l || [ -n "$l" ]; do
    l=$(printf '%s\n' "$l" | sed -e 's/^[[:space:]]*//' -e 's/^\([A-Za-z]*\)[[:space:]]*=[[:space:]]*/\1 /' -e 's/"//g')
    k=$(printf '%s\n' "$l" | awk '{print tolower($1)}')
    case "$k" in ''|'#'*) continue ;; match) m=1; continue ;; esac
    if [ -n "$m" ]; then printf '@match %s\n' "$l"; continue; fi
    if [ "$k" = include ]; then
      set -f
      for g in $(printf '%s\n' "$l" | sed -e 's/^[^[:space:]]*[[:space:]]*//' -e 's/[[:space:]]#.*$//'); do
        set +f
        case "$g" in /*|~*) ;; *) g="/etc/ssh/$g" ;; esac
        for f in $g; do [ -f "$f" ] && sshd_flat "$f"; done
        m=
        set -f
      done
      set +f
      continue
    fi
    printf '%s\n' "$l"
  done < "$1"
  return 0
}
sshd_files=$(sshd_flat /etc/ssh/sshd_config 2>/dev/null)
sshdc=$( (sshd -T || /usr/sbin/sshd -T) 2>/dev/null )
if [ -n "$sshdc" ]; then src=sshd
elif printf '%s\n' "$sshd_files" | grep -q '^@unread '; then src=files-partial
else src=files; fi
[ "$src" = sshd ] || sshdc=$(printf '%s\n' "$sshd_files" | grep -v '^@')
sshv() { printf '%s\n' "$sshdc" | grep -iE "^[[:space:]]*$1[[:space:]]+" | head -1 | awk '{print tolower($2)}'; }
pw=$(sshv PasswordAuthentication); rl=$(sshv PermitRootLogin)
if [ "$src" = files ]; then [ -n "$pw" ] || pw=yes; [ -n "$rl" ] || rl=prohibit-password; fi
echo "ssh_config_from=$src"
echo "ssh_password_auth=$pw"
echo "ssh_root_login=$rl"
echo "ssh_port=$(sshv Port)"
echo "ssh_max_auth=$(sshv MaxAuthTries)"
echo "ssh_empty_pw=$( [ "$(sshv PermitEmptyPasswords)" = yes ] && echo 1 || echo 0)"
echo "ssh_match_loosens=$(printf '%s\n' "$sshd_files" | grep -ciE '^@match[[:space:]]+(PasswordAuthentication[[:space:]]+yes|PermitRootLogin[[:space:]]+yes|PermitEmptyPasswords[[:space:]]+yes)([[:space:]]|$)')"
"""

AUDIT_SH = r"""
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT GLOB_SUBST NO_NOMATCH 2>/dev/null
echo "hostname=$(hostname 2>/dev/null)"
echo "os=$( (. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-}") )"
echo "kernel=$(uname -r 2>/dev/null)"
echo "uptime_days=$(( $(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0) / 86400 ))"
echo "reboot_required=$([ -f /var/run/reboot-required ] && echo yes || echo no)"
echo "sshd_running=$(ps -eo comm 2>/dev/null | grep -cx sshd)"
""" + AUDIT_SSH_SH + r"""
echo "users_empty_password=$(awk -F: '($2==""){print $1}' /etc/shadow 2>/dev/null | tr '\n' ',' )"
echo "users_uid0=$(awk -F: '($3==0){print $1}' /etc/passwd 2>/dev/null | tr '\n' ',')"
echo "users_sudo=$(getent group sudo 2>/dev/null | awk -F: '{print $4}')"
echo "ufw=$(command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 || echo 'not-installed')"
echo "nft_rules=$(command -v nft >/dev/null 2>&1 && nft list ruleset 2>/dev/null | grep -c 'rule' || echo 0)"
echo "iptables_rules=$(command -v iptables >/dev/null 2>&1 && iptables -S 2>/dev/null | grep -vc '^-P' || echo 0)"
echo "fail2ban=$(command -v fail2ban-client >/dev/null 2>&1 && fail2ban-client status 2>/dev/null | grep -c 'Jail list' || echo 0)"
echo "unattended_upgrades=$([ -f /etc/apt/apt.conf.d/20auto-upgrades ] && grep -c 'Unattended-Upgrade \"1\"' /etc/apt/apt.conf.d/20auto-upgrades || echo 0)"
echo "apparmor=$(command -v aa-status >/dev/null 2>&1 && aa-status --enabled 2>/dev/null && echo enabled || echo unknown)"
echo "pending_updates=$( (apt-get -s -o Debug::NoLocking=1 upgrade 2>/dev/null | grep -c '^Inst ') || echo 0)"
echo "pending_security=$( (apt-get -s -o Debug::NoLocking=1 upgrade 2>/dev/null | grep '^Inst' | grep -ci security) || echo 0)"
echo "docker_running=$(command -v docker >/dev/null 2>&1 && docker ps -q 2>/dev/null | wc -l || echo 0)"
echo "docker_socket_mounted=$(command -v docker >/dev/null 2>&1 && docker ps -q 2>/dev/null | xargs -r docker inspect --format '{{range .Mounts}}{{.Source}} {{end}}' 2>/dev/null | grep -c 'docker.sock' || echo 0)"
echo "docker_privileged=$(command -v docker >/dev/null 2>&1 && docker ps -q 2>/dev/null | xargs -r docker inspect --format '{{.HostConfig.Privileged}}' 2>/dev/null | grep -c true || echo 0)"
echo "docker_public_ports=$(command -v docker >/dev/null 2>&1 && docker ps --format '{{.Ports}}' 2>/dev/null | grep -c '0.0.0.0:' || echo 0)"
echo "listening=$( (ss -H -tuln 2>/dev/null || netstat -tuln 2>/dev/null) | awk '{print $5}' | sed 's/.*://' | sort -un | tr '\n' ',' )"
echo "disk_used_pct=$(df -P / 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')"
echo "AUDIT_END"
"""

AUDIT_TTL = float(os.environ.get("COMPUTERS_AUDIT_TTL", "300"))
_audit_lock = threading.Lock()
_audit_cache: dict[str, tuple[float, dict]] = {}

#: Ports that must never be reachable from the internet on a server that hosts websites. Matched
#: against what is actually LISTENING, because a firewall rule nobody verified is a firewall rule
#: that is not there.
RISKY_PORTS = {
    # port: (severity when merely listening, title, fix, escalate_when_reachable_from_outside)
    # SSH is the ONE port that is supposed to be reachable — it is how the owner and this office get
    # in — so its reachability is a note, not an alarm. Everything else here is a service that has no
    # business answering the internet, and for those reachability IS the finding.
    "22": ("info", "SSH פתוח", "ודא ש-SSH מקבל מפתחות בלבד ושיש fail2ban", False),
    "2375": ("error", "Docker API פתוח ללא TLS", "סגור את הפורט מיד — זה שליטה מלאה במכונה", True),
    "2376": ("warn", "Docker API פתוח", "הגבל לגישה מוכרת בלבד", True),
    "5432": ("warn", "PostgreSQL פתוח", "הגבל לרשת הפנימית", True),
    "3306": ("warn", "MySQL/MariaDB פתוח", "הגבל לרשת הפנימית", True),
    "6379": ("error", "Redis פתוח", "ל-Redis אין אימות כברירת מחדל — סגור אותו", True),
    "27017": ("warn", "MongoDB פתוח", "הגבל לרשת הפנימית", True),
    "9200": ("warn", "Elasticsearch פתוח", "הגבל לרשת הפנימית", True),
    "11211": ("warn", "memcached פתוח", "הגבל לרשת הפנימית", True),
}


def parse_audit(stdout: str) -> dict:
    """`key=value` lines → a dict. Found by the END MARKER, not by "the last line" — ssh writes its
    own chatter to stdout too, and reading positionally is how a warning becomes a fact."""
    facts: dict = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or "=" not in line or line == "AUDIT_END":
            continue
        k, _, v = line.partition("=")
        if re.fullmatch(r"[a-z0-9_]{2,32}", k):
            facts[k] = v.strip()[:500]
    return facts


def _num(facts: dict, key: str, default: int = 0) -> int:
    try:
        return int(str(facts.get(key, default)).strip() or default)
    except (TypeError, ValueError):
        return default


def audit_findings(facts: dict) -> list[dict]:
    """The rules. Every one names what to DO, because "SSH password auth is on" is not an action."""
    out: list[dict] = []

    def add(code, severity, title, detail="", fix=""):
        out.append({"code": code, "severity": severity, "title": title, "detail": detail,
                    "fix": fix})

    if facts.get("ssh_password_auth") == "yes":
        add("ssh_password_auth", "error", "SSH מקבל סיסמאות",
            "PasswordAuthentication yes — סיסמה אחת שנחשפה = כניסה לשרת.",
            "הגדר PasswordAuthentication no ב-/etc/ssh/sshd_config.d/ והפעל מחדש את sshd "
            "(המפתח של הלשכה כבר מורשה).")
    elif facts.get("ssh_password_auth") == "no":
        add("ssh_password_off", "ok", "SSH לא מקבל סיסמאות", "רק מפתחות.")

    root = (facts.get("ssh_root_login") or "").lower()
    if root in ("yes",):
        add("ssh_root_login", "warn", "התחברות root ב-SSH מותרת",
            "PermitRootLogin yes.", "הגדר prohibit-password או no.")
    elif root in ("prohibit-password", "without-password"):   # sshd -T says the older name for the same thing
        add("ssh_root_login_key", "ok", "root רק עם מפתח", "PermitRootLogin prohibit-password")
    if _num(facts, "ssh_match_loosens") > 0:
        # sshd -T shows the server's own settings; a Match block may still open a door for some logins
        add("ssh_match_loosens", "warn", "בלוק Match פותח סיסמאות או root לחלק מהכניסות",
            f"{_num(facts, 'ssh_match_loosens')} הגדרות בתוך בלוקי Match מתירות סיסמה, root או סיסמה ריקה.",
            "בדוק את בלוקי ה-Match ב-sshd_config ובקבצים שהוא כולל.")
    if facts.get("ssh_config_from") == "files-partial":
        add("ssh_config_partial", "info", "חלק מהגדרות ה-SSH לא נקראו",
            "המשתמש שהלשכה מתחברת איתו לא יכול לקרוא חלק מקובצי sshd_config, ולכן ערכי ה-SSH כאן חלקיים.",
            "חבר את המחשב כ-root, או תן למשתמש הרשאת קריאה ל-/etc/ssh.")

    if _num(facts, "ssh_empty_pw") > 0 or (facts.get("users_empty_password") or "").strip(","):
        add("empty_passwords", "error", "חשבונות בלי סיסמה",
            f"משתמשים: {facts.get('users_empty_password') or '—'}",
            "הגדר סיסמה או נעל את החשבון.")
    uid0 = [u for u in (facts.get("users_uid0") or "").split(",") if u and u != "root"]
    if uid0:
        add("extra_uid0", "error", "חשבונות עם הרשאות root מלאות (UID 0)",
            ", ".join(uid0), "הסר את ההרשאה או מחק את החשבון — זו דלת אחורית.")

    ufw = (facts.get("ufw") or "").lower()
    ipt = _num(facts, "iptables_rules")
    nft = _num(facts, "nft_rules")
    if "active" in ufw:
        add("firewall_ufw", "ok", "חומת אש פעילה (ufw)", facts.get("ufw", ""))
    elif ipt > 0 or nft > 0:
        add("firewall_rules", "ok", "קיימות חומות אש (iptables/nftables)",
            f"{ipt} כללי iptables, {nft} כללי nftables")
    else:
        add("no_firewall", "warn", "לא נמצאה חומת אש פעילה",
            "לא ufw, לא iptables ולא nftables — כל פורט מאזין חשוף לאינטרנט.",
            "הפעל ufw והרשה רק 22/80/443 (docker מפרסם פורטים בעקיפין, בדוק אחרי ההפעלה).")

    if _num(facts, "fail2ban") == 0:
        add("no_fail2ban", "info", "אין fail2ban",
            "ניסיונות התחברות כושלים אינם נחסמים.",
            "התקן fail2ban כדי לחסום ניסיונות SSH חוזרים.")
    else:
        add("fail2ban_ok", "ok", "fail2ban פעיל")

    if _num(facts, "unattended_upgrades") == 0:
        add("no_unattended", "warn", "עדכוני אבטחה אוטומטיים כבויים",
            "אין 20auto-upgrades עם Unattended-Upgrade \"1\".",
            "הפעל unattended-upgrades לעדכוני אבטחה.")

    sec = _num(facts, "pending_security")
    pend = _num(facts, "pending_updates")
    if sec >= 10:
        add("pending_security", "error", f"{sec} עדכוני אבטחה ממתינים",
            f"סה\"כ {pend} עדכונים זמינים.", "הרץ apt-get upgrade (או המתן לחלון התחזוקה).")
    elif sec > 0:
        add("pending_security_warn", "warn", f"{sec} עדכוני אבטחה ממתינים", "",
            "הרץ apt-get upgrade.")
    elif pend > 0:
        add("pending_updates", "info", f"{pend} עדכונים ממתינים (ללא אבטחה)", "")

    if (facts.get("reboot_required") or "") == "yes":
        add("reboot_required", "warn", "נדרשת הפעלה מחדש",
            "עדכוני ליבה או ספריות ממתינים לאתחול.",
            "הפעל מחדש בחלון תחזוקה — עד אז המכונה רצה עם ליבה ישנה.")

    if _num(facts, "docker_socket_mounted") > 0:
        add("docker_socket_in_container", "warn", "קונטיינר עם סוקט הדוקר",
            f"{facts.get('docker_socket_mounted')} קונטיינרים רואים את /var/run/docker.sock.",
            "הסוקט שווה ערך ל-root במכונה — ודא שזה מכוון ומוגבל.")
    if _num(facts, "docker_privileged") > 0:
        add("docker_privileged", "error", "קונטיינר בהרשאות privileged",
            f"{facts.get('docker_privileged')} קונטיינרים privileged.",
            "הסר privileged והשתמש ב-capabilities ספציפיות.")
    if _num(facts, "docker_public_ports") > 0:
        add("docker_public_ports", "info", "קונטיינרים מפרסמים פורטים על כל הכתובות",
            f"{facts.get('docker_public_ports')} מיפויים בפורמט 0.0.0.0.",
            "פרסום דרך 127.0.0.1 ואחריו reverse-proxy חוסך חשיפה מיותרת.")

    for port in [p.strip() for p in (facts.get("listening") or "").split(",") if p.strip()]:
        if port in RISKY_PORTS:
            sev, title, fix, _esc = RISKY_PORTS[port]
            add(f"port:{port}", sev, f"פורט {port} מאזין ({title})",
                "מאזין על המכונה — הבדיקה מאמתת מולו אם הוא נגיש מבחוץ.", fix)

    used = _num(facts, "disk_used_pct")
    if used >= 90:
        add("disk_full", "error", f"הדיסק מלא ב-{used}%", "",
            "פנה מקום — דיסק מלא מפיל את כל השירותים בבת אחת.")
    elif used >= 80:
        add("disk_high", "warn", f"הדיסק ב-{used}%", "", "פנה מקום לפני שיתמלא.")
    return out


def port_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """Can the office OPEN a TCP connection to this port on that machine, right now?

    The difference between "something is listening" and "anyone on the internet can reach it" is the
    entire risk of an exposed database, and only a connection from outside can settle it — `ufw
    status` says "active" while docker's own iptables rules publish a port past the firewall, which
    is the single most common way a Redis ends up on the public internet. The office is an outside
    party (it is not on the machine's own loopback), so its answer is the honest one; it is reported
    as "reachable from the office" rather than pretending to be a third-party scanner.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


@app.get("/api/computers/{cid}/audit")
def api_computer_audit(cid: str, fresh: int = 0, reachable: int = 1):
    """Audit a machine: read-only, and cached — the script parses apt state, which is not free."""
    now = time.time()
    if not fresh:
        with _audit_lock:
            hit = _audit_cache.get(cid)
        if hit and now - hit[0] < AUDIT_TTL:
            return {**hit[1], "cached": True}
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    sec, _ = _computer_ctx(rec, local_gateway())
    res = ssh_run(cid, rec["host"], rec["port"], rec["user"], sec, AUDIT_SH, 120)
    facts = parse_audit(res.get("stdout") or "")
    if not facts:
        return _err(res.get("reason") or "המחשב לא החזיר נתוני ביקורת",
                   409 if res.get("state") == "needs_action" else 502,
                    stderr=(res.get("stderr") or "")[:800])
    findings = audit_findings(facts)
    if reachable and rec.get("host"):
        findings = _confirm_reachability(findings, rec["host"])
    counts = {s: sum(1 for f in findings if f["severity"] == s)
              for s in ("error", "warn", "info", "ok")}
    out = {"id": cid, "label": rec.get("label"), "host": rec.get("host"),
           "checked_at": int(now), "cached": False, "facts": facts, "findings": findings,
           "counts": counts,
           "state": "error" if counts["error"] else ("warn" if counts["warn"] else "ok")}
    with _audit_lock:
        _audit_cache[cid] = (now, out)
    log.info("audit %s: %s errors, %s warnings", cid, counts["error"], counts["warn"])
    return out


def _confirm_reachability(findings: list[dict], host: str) -> list[dict]:
    """Turn "listening" into "open to the world", or downgrade it to a note. One TCP attempt each."""
    out = []
    for f in findings:
        if not f["code"].startswith("port:"):
            out.append(f)
            continue
        port = int(f["code"].split(":", 1)[1])
        escalate = (RISKY_PORTS.get(str(port)) or (None, None, None, True))[3]
        if port_reachable(host, port):
            sev = "error" if escalate else "info"
            out.append({**f, "severity": sev,
                        "title": f"{f['title']} — נגיש מבחוץ",
                        "detail": (f"{f['detail']} התחברות TCP מהלשכה למכונה הצליחה: הפורט פתוח "
                                   f"לאינטרנט (docker מפרסם פורטים גם כשחומת אש פעילה).")})
        else:
            out.append({**f, "severity": "info",
                        "title": f"{f['title']} — אינו נגיש מבחוץ",
                        "detail": f"{f['detail']} ניסיון התחברות מהלשכה נכשל — כנראה חסום."})
    return out


@app.get("/")
def index():
    """The console embeds this at /a/computers/ and injects <base href>, so every path here and in
    the UI is RELATIVE — an absolute /api/... would address the console's origin, not the app."""
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/terminal")
def terminal_page():
    """«טרמינל» — a shell on the office's machines, served by the app that owns their key, their sessions and the
    caller check (DGO-1800): the person reaches it through the console and a linked office through the door, so
    computers sees who is asking with no relay between (issues/the-terminal-app-calls-computers-from-its-own-…).
    Its paths are relative to this app's root, like every screen here."""
    return FileResponse(_STATIC / "terminal" / "index.html")


@app.get("/{path:path}")
def page(path: str):
    """Every screen of this app is an address (the console's route contract, G83): the fleet `/`, a
    computer of the herd `/c/<where>/<tab>`, an SSH machine's dialog `/<id>`. Opened in a new tab or
    reloaded, such a path is the page, which reads it back. Declared last, so every API answers
    first; an unknown `api/…` stays a JSON 404, so a client never reads HTML as an answer."""
    if path.startswith(("api/", "static/")):
        return _err("לא נמצא", 404)
    return FileResponse(_STATIC / "index.html")


@app.on_event("startup")
def _startup() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    _chmod(KEY_DIR, 0o700)
    ensure_key()
    host = local_gateway()
    vault_ensure_local(host, LOCAL_USER, LOCAL_PORT)
    log.info("computers ready — built-in machine %s@%s:%s, office key %s",
             LOCAL_USER, host, LOCAL_PORT, key_fingerprint() or "(none)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8977")))
