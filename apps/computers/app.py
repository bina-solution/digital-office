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

import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("computers")

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
PROBE_TTL = float(os.environ.get("COMPUTERS_PROBE_TTL", "20"))

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


def ssh_argv(cid: str, host: str, port: int, user: str, secret: dict,
             command: str, timeout: int = 60) -> list[str]:
    """The exact ssh command line for one machine.

    Extracted from ssh_run for `transfer`, which must open the SAME kind of connection — same key,
    same pinned host key, same BatchMode — because a copy that used a looser connection would be a
    second answer to "how do we reach a machine", and the loose one is the one that drifts.
    """
    return ["ssh", *SSH_BASE, *_known_hosts_opt(), "-i", _key_path_for({**secret, "_instance": cid}),
            "-p", str(int(port or 22)),
            "-o", f"ConnectTimeout={min(8, max(3, int(timeout or 8)))}",
            f"{user}@{host}", command]


def ssh_run(cid: str, host: str, port: int, user: str, secret: dict,
            command: str, timeout: int) -> dict:
    """Run a command on a machine. Always returns a dict — never raises into a route.

    {code, stdout, stderr, timed_out, reason, action, state}. `code` is the remote command's own
    exit code when the connection was made (including 255 if the far side's command exits 255), and
    255 when ssh itself failed — an ambiguity ssh itself has, which is why the reason is derived
    from stderr rather than from the number.
    """
    ensure_key()
    key = _key_path_for({**secret, "_instance": cid})
    if not key:
        return {"code": 255, "stdout": "", "stderr": "", "timed_out": False, "state": "needs_action",
                "reason": "לא נוצר עדיין מפתח SSH ללשכה",
                "action": "רענן את הדף — המפתח נוצר אוטומטית עם עליית השירות."}
    cmd = (["ssh", *SSH_BASE, *_known_hosts_opt(), "-i", key, "-p", str(int(port or 22)),
            "-o", f"ConnectTimeout={min(8, max(3, int(timeout or 8)))}",
            f"{user}@{host}", command])
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
        p = subprocess.run(cmd, capture_output=True, timeout=max(1, int(timeout)))
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
    body = await request.json() if await request.body() else {}
    return await api_computers_post(body or {})


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
def api_computers(probe: int = 1):
    """The fleet. `?probe=0` skips the SSH round trip (fast, for a background refresh)."""
    host = local_gateway()
    insts, err = vault_list()
    if err:
        return _err(err, 502)
    out = []
    for i in insts:
        rec = computer_record(i, host)
        if probe:
            sec, _ = _computer_ctx(rec, host)
            st = probe_computer(rec, sec, max_age=PROBE_TTL)
            rec = {**rec, **{k: v for k, v in st.items() if k != "id"}}
        out.append(rec)
    out.sort(key=lambda c: (not c.get("builtin"), not c.get("ok"), c.get("label") or ""))
    return {"computers": out, "count": len(out), "builtin": LOCAL_INSTANCE,
            "office_key": {"public_key": public_key(), "fingerprint": key_fingerprint(),
                           "user": LOCAL_USER, "local_host": host}}


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
    if not host:
        return _err("חסרה כתובת (host)", 400)
    if re.search(r"[\s;|&$`'\"]", host) or host.startswith("-"):
        return _err("הכתובת אינה תקינה", 400)
    try:
        port = int(body.get("port") or 22)
    except (TypeError, ValueError):
        return _err("הפורט אינו מספר", 400)
    if not (1 <= port <= 65535):
        return _err("הפורט מחוץ לטווח", 400)
    secret = {"host": host, "port": port, "user": user}
    if (body.get("private_key") or "").strip():
        secret["private_key"] = body["private_key"]
    if host == local_gateway() and user == LOCAL_USER and port == LOCAL_PORT:
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
    st = probe(cid, host, port, user, secret, max_age=0)
    return {"id": cid, "label": label or f"{user}@{host}", "host": host, "port": port, "user": user,
            "status": "ok", "removable": True, "builtin": False, "probe": st}


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
    rec, bad = _resolve(cid, local_gateway())
    if bad:
        return bad
    sec, _ = _computer_ctx(rec, local_gateway())
    log.info("exec on %s: %s", cid, command.strip().splitlines()[0][:200])
    # OFF THE EVENT LOOP, always. `ssh_run` blocks for as long as the command runs — up to
    # MAX_TIMEOUT — and this handler is `async`, so it ran INSIDE the single uvicorn worker's loop:
    # one long command made every other request wait, including `/healthz`. Measured 2026-10-04:
    # `/healthz` took 30 s and the container's own healthcheck failed 5 runs in a row (exit 1 on its
    # 8 s budget) while a long `exec` was in flight — an office whose door to its machines reports
    # unhealthy exactly when it is being used, and restarts itself under `autoheal`.
    res = await run_in_threadpool(ssh_run, cid, rec["host"], rec["port"], rec["user"], sec,
                                  command, timeout)
    return {"id": cid, "command": command, "timeout": timeout, **res}


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
    return {"public_key": pub, "fingerprint": key_fingerprint(),
            "authorize_command": (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
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
    return {"id": cid, "user": rec.get("user"), "host": rec.get("host"),
            "public_key": pub, "fingerprint": key_fingerprint(),
            "command": (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                        f"echo '{pub}' >> ~/.ssh/authorized_keys && "
                        f"chmod 600 ~/.ssh/authorized_keys")}


@app.post("/api/computers/{cid}/probe")
async def api_computer_probe(cid: str):
    invalidate(cid)
    return await api_computer_status(cid, fresh=1)


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
AUDIT_SH = r"""
echo "hostname=$(hostname 2>/dev/null)"
echo "os=$( (. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-}") )"
echo "kernel=$(uname -r 2>/dev/null)"
echo "uptime_days=$(( $(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0) / 86400 ))"
echo "reboot_required=$([ -f /var/run/reboot-required ] && echo yes || echo no)"
echo "sshd_running=$(ps -eo comm 2>/dev/null | grep -cx sshd)"
sshdc=$(cat /etc/ssh/sshd_config 2>/dev/null; cat /etc/ssh/sshd_config.d/*.conf 2>/dev/null)
echo "ssh_password_auth=$(printf '%s\n' "$sshdc" | grep -iE '^\s*PasswordAuthentication\s+' | tail -1 | awk '{print tolower($2)}')"
echo "ssh_root_login=$(printf '%s\n' "$sshdc" | grep -iE '^\s*PermitRootLogin\s+' | tail -1 | awk '{print tolower($2)}')"
echo "ssh_port=$(printf '%s\n' "$sshdc" | grep -iE '^\s*Port\s+' | tail -1 | awk '{print $2}')"
echo "ssh_max_auth=$(printf '%s\n' "$sshdc" | grep -iE '^\s*MaxAuthTries\s+' | tail -1 | awk '{print $2}')"
echo "ssh_empty_pw=$(printf '%s\n' "$sshdc" | grep -icE '^\s*PermitEmptyPasswords\s+yes')"
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
    elif root == "prohibit-password":
        add("ssh_root_login_key", "ok", "root רק עם מפתח", "PermitRootLogin prohibit-password")

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
