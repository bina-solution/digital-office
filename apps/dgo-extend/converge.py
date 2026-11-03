"""dgo-extend.converge — make ONE remote office match its declaration.

A declaration (see app.py) says: this machine, this domain, this directory, this commit of this
repository, these apps. `converge(office)` walks the same ordered steps every time and each step
is idempotent, so a first install, an upgrade and a repair are the same operation:

    machine → dns → code → engine → env → state → run → health

Every command runs on the machine through `apps/computers` (POST /api/computers/<id>/exec). Nothing
here holds a key or opens a socket to a machine.

Long steps (an apt install, `./bbox run` building images for half an hour) must not live inside one
SSH round trip: `computers` caps a command at 600 s, and a dropped connection would kill the work
with it. So a long step is written to the machine as a script and started DETACHED (setsid), and
this module polls its exit-code file and log tail until it finishes. The work survives this
container restarting, the SSH connection dropping, or the home office going to sleep; the next
poll simply picks the log up again.
"""
from __future__ import annotations

import base64
import catalog
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import secrets
import shlex
import socket
import threading
import time
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import yaml

import peers

log = logging.getLogger("dgo-extend.converge")

COMPUTERS_URL = os.environ.get("COMPUTERS_URL", "http://computers:8977").rstrip("/")
#: The box that runs THIS office — the one whose console shows a placed app. Reached through
#: `computers` like every other machine (see app.py).
LOCAL_MACHINE = "computer_local-local"
HOME_REPO = os.environ.get("DGO_HOME_REPO", "")
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
DOMAINS_URL = os.environ.get("DOMAINS_URL", "http://domains:8980").rstrip("/")
q = shlex.quote

STEPS = ["machine", "dns", "backup", "code", "engine", "env", "login", "state", "run", "accounts",
         "link", "health", "publish"]
#: Steps a caller may ask for BY NAME that are never part of a default converge: `unlink` takes a link
#: away, and a default run that revoked a tunnel because someone forgot an argument would be the worst
#: kind of helpful.
EXTRA_STEPS = ["unlink", "offsite"]   # offsite: the daily backup off the server (FPG-26), asked by the watch
STEP_TITLES = {
    "offsite": "גיבוי מחוץ לשרת",
    "machine": "המחשב",
    "dns": "דומיין ו־DNS",
    "backup": "גיבוי לפני שדרוג",
    "code": "קוד הלשכה",
    "engine": "מנוע Docker",
    "env": "הגדרות (.env)",
    "login": "פרטי כניסה",
    "state": "האפליקציות",
    "run": "הפעלה (bbox run)",
    "accounts": "כתובות החשבונות",
    "link": "מנהרות וקישורים",
    "unlink": "ביטול קישור",
    "health": "בריאות",
    "publish": "פרסום האפליקציות",
}
DOCKER_MAJOR = "28"


class StepFailed(Exception):
    """A step that could not complete, with the sentence the owner reads and what to do about it."""

    def __init__(self, reason: str, action: str = "", detail: str = ""):
        super().__init__(reason)
        self.reason, self.action, self.detail = reason, action, detail


# ── the doors to other apps ─────────────────────────────────────────────────────
def _http(method: str, url: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}") | {"_status": e.code}
        except ValueError:
            return {"_status": e.code, "error": str(e)}


def _http_auth(method: str, url: str, token: str, timeout: float = 30) -> dict:
    """`_http` with a Bearer token, for a call over a link (`projection.pull_agents`). Never raises:
    a peer that did not answer is `{"_status": 0, "error": …}`, an HTTP refusal its body + `_status`."""
    req = urllib.request.Request(url, method=method, headers={"authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.loads(r.read() or b"{}")
            return doc if isinstance(doc, dict) else {"_status": 0, "error": "the answer is not an object"}
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        return {**(doc if isinstance(doc, dict) else {}), "_status": e.code}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return {"_status": 0, "error": f"{type(e).__name__}: {e}"}


def exec_on(machine: str, command: str, timeout: int = 120, stdin: str | None = None) -> dict:
    """Run a command ON the machine, through computers. Returns its dict verbatim. `stdin` goes to the
    command's standard input — the way a secret travels (never in the command, which is an argv)."""
    try:
        return _http("POST", f"{COMPUTERS_URL}/api/computers/{machine}/exec",
                     {"command": command, "timeout": timeout, **({"stdin": stdin} if stdin is not None else {})},
                     timeout=timeout + 15)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"code": 255, "stdout": "", "stderr": str(e), "state": "error",
                "reason": "שירות המחשבים אינו זמין"}


def must(machine: str, command: str, timeout: int = 120, what: str = "", stdin: str | None = None) -> str:
    r = exec_on(machine, command, timeout, stdin)
    if r.get("code") != 0:
        err = (r.get("stderr") or r.get("stdout") or "").strip()[-1500:]
        # `what` is the headline the owner reads ("the backup step could not be started"); the
        # machine's own reason and the app's HTTP status must survive underneath it. A masked
        # reason with an EMPTY detail is how a real failure was first seen here: an HTTP-level
        # answer from `computers` (no code, no stderr) reported as "nothing happened".
        why = r.get("reason") or (f"שירות המחשבים השיב {r['_status']}" if r.get("_status") else "")
        detail = "\n".join(x for x in (why, r.get("action") or "", err) if x)
        raise StepFailed(what or why or f"הפקודה נכשלה (קוד {r.get('code')})",
                         r.get("action") or "", detail)
    return r.get("stdout") or ""


def machine_record(machine: str) -> dict:
    r = _http("GET", f"{COMPUTERS_URL}/api/computers/{machine}/status?fresh=1", timeout=40)
    if r.get("_status"):
        raise StepFailed(r.get("error") or "המחשב אינו ברשימת המחשבים של הלשכה",
                         "הוסף אותו באפליקציית מחשבים.")
    return r


def machine_address(machine: str) -> str:
    """The address the fleet HOLDS for a machine — its record, with no SSH round trip.

    The link plane only needs where to dial. It asked `machine_record` (a FRESH probe: an SSH sign-in
    as root on the machine) every time the plane was built, and the plane is read every minute by the
    security app — one root sign-in on vps1 a minute, and for a peer with no machine declared a
    `GET /api/computers//status` that answered 404 (measured 2026-10-21, DGO-903). A step that must
    know the machine answers still calls `machine_record`."""
    if not machine:
        return ""
    r = _http("GET", f"{COMPUTERS_URL}/api/computers?probe=0", timeout=15)
    for c in (r or {}).get("computers") or []:
        if c.get("id") == machine:
            return (c.get("host") or "").strip()
    return ""


def vault_secret(cid: str) -> dict:
    r = _http("GET", f"{CONNECTIONS_URL}/api/instances/{cid}/secret", timeout=15)
    return (r or {}).get("secret") or {}


def domains_list() -> list[dict]:
    try:
        return list(_http("GET", f"{DOMAINS_URL}/api/domains", timeout=20).get("domains") or [])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []


# ── detached remote tasks ───────────────────────────────────────────────────────
def ctl_dir(office: dict) -> str:
    return f"$HOME/.digital-office/{office['id']}"


def start_detached(office: dict, name: str, script: str, secret: bool = False) -> None:
    """Write `script` to the machine and start it in its own session. Returns at once.

    "Started" is then VERIFIED, not assumed: an SSH command is done when its channel closes, and a
    detached child can be reported as a successful start while it in fact died on line one. So the
    script's own exit-code file is read once — a script that already failed is raised here, with the
    head of its log, instead of surfacing minutes later as "the step timed out"."""
    d = ctl_dir(office)
    body = "set -e\n" + ("rm -f \"$0\"\n" if secret else "") + script
    b64 = base64.b64encode(body.encode()).decode()
    # The detach is its OWN statement, on its own line, and that is the whole point.
    #
    # The command was one `a && b && c && setsid … &` chain. `&` has LOWER precedence than `&&`, so
    # it backgrounds the entire chain — which makes `setsid` a FOREGROUND child of that background
    # subshell, and the subshell's stdout is the SSH channel. sshd holds the channel open until every
    # writer closes it, so the call came back only when the STEP WAS OVER (or at the 60s ceiling,
    # whichever came first): the backup step measured `timed out after 60 seconds` while the backup
    # itself was running fine on the machine. Every long step was unusable — measured here on
    # 2026-09-29, on the first converge against a real server.
    #
    # `umask 022` INSIDE the payload, while the files this function creates keep 077. The strict umask
    # exists to protect the control script (it can carry a one-shot git token); inherited by the step
    # itself it made `git checkout` write every file it rewrote with mode 600, and a 600
    # worker-liveness.sh bind-mounted into a container running as `node` is a healthcheck that answers
    # `Permission denied` — which is how `bbox run` reported "n8n-worker-2 is unhealthy" on vps1 and
    # left the office half up (measured 2026-09-30).
    detach = (f"nohup setsid bash -c 'umask 022; bash {d}/{name}.sh > {d}/{name}.log 2>&1; "
              f"echo $? > {d}/{name}.rc' </dev/null >/dev/null 2>&1 &\n")
    if secret:
        # A SECRET script (a git token, the off-server key) travels on the command's STDIN: the command
        # is an argv — this office's ssh, the far side's login shell `-c`, readable in /proc/<pid>/cmdline
        # by any local user there. Its byte count is checked: a computers app that does not pass stdin yet
        # would hand `cat` nothing, and an EMPTY script runs to a perfect exit code 0.
        n = len(body.encode())
        cmd = (f"set -e\numask 077\nmkdir -p {d}\nrm -f {d}/{name}.rc\ncat > {d}/{name}.sh\n"
               f"[ \"$(wc -c < {d}/{name}.sh)\" -eq {n} ] || {{ rm -f {d}/{name}.sh; "
               f"echo 'the script did not arrive whole on stdin' >&2; exit 3; }}\n" + detach)
        must(office["machine"], cmd, 60, f"לא ניתן להפעיל את השלב {name} על המחשב", stdin=body)
    else:
        cmd = (f"set -e\numask 077\nmkdir -p {d}\nrm -f {d}/{name}.rc\n"
               f"echo {b64} | base64 -d > {d}/{name}.sh\n" + detach)
        must(office["machine"], cmd, 60, f"לא ניתן להפעיל את השלב {name} על המחשב")
    r = exec_on(office["machine"],
                f"{{ test -f {d}/{name}.sh || test -f {d}/{name}.log || test -f {d}/{name}.rc; }} "
                f"|| echo NOSCRIPT; "
                f"cat {d}/{name}.rc 2>/dev/null; echo '@@'; tail -c 800 {d}/{name}.log 2>/dev/null",
                30)
    out = r.get("stdout") or ""
    head, _, tail = out.partition("@@")
    if "NOSCRIPT" in head:
        # Not `test -f <name>.sh`: a SECRET script deletes itself on line one on purpose (it carries
        # a one-shot git token), so its absence is the expected state, not a failure to start.
        raise StepFailed(f"השלב {name} לא נכתב למחשב", "בדוק את הרשאת הכתיבה בתיקיית הבית של המשתמש.")
    rc = "".join(c for c in head if c.isdigit())
    if rc and rc != "0":
        raise StepFailed(f"השלב {name} נכשל מיד עם ההפעלה (קוד {rc})", "הפלט למטה.",
                         tail.strip()[-800:])


def wait_detached(office: dict, name: str, emit: Callable[[str], None], limit: int,
                  every: float = 8.0) -> str:
    """Poll a detached task until it writes its exit code. Streams new log lines to `emit`.
    Returns the full tail; raises StepFailed on a non-zero exit or on `limit` seconds."""
    d = ctl_dir(office)
    seen = 0
    started = time.time()
    tail = ""
    while True:
        r = exec_on(office["machine"],
                    f"cat {d}/{name}.rc 2>/dev/null || echo RUNNING; echo '@@'; "
                    f"wc -l < {d}/{name}.log 2>/dev/null || echo 0; echo '@@'; "
                    f"tail -n 400 {d}/{name}.log 2>/dev/null", 60)
        if r.get("code") == 0:
            parts = (r.get("stdout") or "").split("@@\n", 2) + ["", ""]
            rc, total, tail = parts[0].strip(), parts[1], parts[2]
            try:
                total_n = int(total.strip() or 0)
            except ValueError:
                total_n = 0
            lines = tail.splitlines()
            new = total_n - seen
            if new > 0:
                for ln in lines[-min(new, len(lines)):]:
                    emit(ln)
                seen = total_n
            if rc != "RUNNING":
                if rc != "0":
                    raise StepFailed(f"השלב {name} הסתיים בקוד {rc}", "הפלט למטה.",
                                     "\n".join(lines[-60:]))
                return tail
        if time.time() - started > limit:
            raise StepFailed(f"השלב {name} לא הסתיים בתוך {limit // 60} דקות",
                             "הוא ממשיך לרוץ על המחשב; הרץ שוב כדי להמשיך לעקוב.")
        time.sleep(every)


# ── the steps ───────────────────────────────────────────────────────────────────
FACTS = r"""
. /etc/os-release 2>/dev/null; echo "os=$ID"; echo "codename=$VERSION_CODENAME"
echo "arch=$(uname -m)"; echo "cpus=$(nproc)"; echo "uid=$(id -u)"
echo "mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)"
echo "avail_mb=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)"
echo "disk_free_gb=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
echo "docker=$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
echo "git=$(command -v git >/dev/null && echo yes || echo no)"
echo "python3=$(command -v python3 >/dev/null && echo yes || echo no)"
echo "sudo=$( [ "$(id -u)" = 0 ] && echo root || (sudo -n true 2>/dev/null && echo yes || echo no))"
echo "public_ip=$(curl -fsS -m 6 https://api.ipify.org 2>/dev/null || true)"
"""


def parse_facts(text: str) -> dict:
    out = {}
    for ln in text.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def step_machine(office: dict, ctx: dict, emit) -> dict:
    rec = machine_record(office["machine"])
    if rec.get("status") not in ("ok", None) and rec.get("state") != "ok":
        raise StepFailed(rec.get("reason") or "המחשב אינו זמין", rec.get("action") or "")
    f = parse_facts(must(office["machine"], FACTS, 60, "לא ניתן לקרוא את פרטי המחשב"))
    ctx["facts"] = f
    ctx["host"] = rec.get("host")
    if f.get("os") not in ("debian", "ubuntu"):
        raise StepFailed(f"מערכת ההפעלה {f.get('os')!r} אינה נתמכת", "Debian או Ubuntu.")
    if f.get("sudo") == "no":
        raise StepFailed("המשתמש במחשב אינו root ואין לו sudo ללא סיסמה",
                         "חבר את המחשב כ־root, או הגדר sudo ללא סיסמה למשתמש.")
    warn = []
    if int(f.get("mem_mb") or 0) < 3800:
        warn.append(f"זיכרון {f.get('mem_mb')}MB — לשכה מלאה צריכה לפחות 4GB")
    if int(f.get("disk_free_gb") or 0) < 15:
        warn.append(f"מקום פנוי {f.get('disk_free_gb')}GB — מומלץ 20GB לפחות")
    return {"summary": f"{f.get('os')} {f.get('codename')} · {f.get('arch')} · {f.get('cpus')} ליבות · "
                       f"{f.get('mem_mb')}MB · {f.get('disk_free_gb')}GB פנויים · Docker {f.get('docker') or 'אין'}",
            "facts": f, "warnings": warn}


def _machine_ip(ctx: dict) -> str | None:
    f = ctx.get("facts") or {}
    if f.get("public_ip"):
        return f["public_ip"]
    host = ctx.get("host") or ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        try:
            return socket.gethostbyname(host)
        except OSError:
            return None


def _resolve(name: str) -> str | None:
    try:
        return socket.gethostbyname(name)
    except OSError:
        return None


def step_dns(office: dict, ctx: dict, emit) -> dict:
    dom = office["domain"]
    ip = _machine_ip(ctx)
    names = [f"console.{dom}", f"auth.{dom}"]
    got = {n: _resolve(n) for n in names}
    wrong = {n: v for n, v in got.items() if v != ip}
    if not wrong:
        return {"summary": f"console/auth.{dom} → {ip}", "records": got}
    # Who can fix it: the domains app knows each domain's zone holder and whether it can write there.
    holder = None
    for d in domains_list():
        if dom == d.get("name") or dom.endswith("." + (d.get("name") or "")):
            holder = d.get("zone_holder") or {}
            break
    need = [f"{n}  A  {ip}" for n in wrong] + [f"*.{dom}  A  {ip}  (מומלץ — כל אפליקציה מקבלת כתובת)"]
    how = (holder or {}).get("how") or "הדומיין אינו מנוהל באפליקציית דומיינים"
    act = (holder or {}).get("action") or "הוסף את הרשומות אצל מי שמחזיק את ה־DNS של הדומיין."
    raise StepFailed(f"ה־DNS של {dom} אינו מצביע על המחשב ({ip})",
                     f"{how}. {act}",
                     "רשומות שחסרות:\n" + "\n".join(need) + "\n\nכרגע:\n" +
                     "\n".join(f"{n} → {v or 'לא קיים'}" for n, v in got.items()))


def _auth_header(office: dict) -> str:
    """git's -c option carrying the git app's token for the source repo, or '' for a public repo."""
    acct = (office.get("source") or {}).get("account")
    if not acct:
        return ""
    tok = vault_secret(acct).get("token")
    if not tok:
        raise StepFailed("לחשבון ה־git שנבחר אין טוקן בכספת", "בחר חשבון אחר באפליקציית git.")
    basic = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
    return f"-c http.extraHeader={q('Authorization: Basic ' + basic)}"


BACKUP = r"""
P=__PATH__

# A minimum free space, checked BEFORE anything is written. A pre-upgrade backup is ~the size of the
# machine's volumes and a converge can be run many times in an evening; filling the disk with backups
# turns "I have a restore point" into "the office cannot write", which is a strictly worse failure
# (measured 2026-09-30: the engine's disk hit 99% during a day of converges, and containers went
# unhealthy — the office's own health step reported them, not the disk).
vol_mb=$(du -sm /var/lib/docker/volumes 2>/dev/null | cut -f1 || echo 0)
vol_mb=${vol_mb:-0}
need_mb=$(( vol_mb * 125 / 100 ))                 # the tar itself plus the copy it is written into
min_mb=${DGO_BACKUP_MIN_FREE_MB:-3000}
free_mb=$(df -Pm /root | awk 'NR==2{print $4}')
if [ "${free_mb:-0}" -lt $(( need_mb + min_mb )) ]; then
  echo "BACKUP_SKIPPED=1"
  echo "SKIP_REASON=אין מקום לגיבוי: ${free_mb}MB פנויים, צריך ~$(( need_mb + min_mb ))MB (${vol_mb}MB volumes + ${min_mb}MB מרווח). הגיבוי דולג — אשמור על הקיים."
  echo "ENOUGH=0"
  exit 0
fi
echo "ROOM=ok free=${free_mb}MB need~$(( need_mb + min_mb ))MB"

STAMP=$(date +%Y%m%d-%H%M%S)
D=/root/backup-$STAMP-pre-upgrade
mkdir -p "$D/pg" "$D/vol" "$D/etc"
echo "BACKUP_DIR=$D"

# ── 1. logical dumps of every postgres the machine runs ─────────────────────────────────────────
# pg_dumpall over a hot data directory is the one backup that does not depend on the container
# being stopped, and it is what a restore actually replays. One file per server, named by the
# container, so a restore is `docker exec -i <c> psql -U <u> < <file>`.
# The image must BE postgres, not merely contain the word: `postgrest/postgrest` and
# `supabase/postgres-meta` are API servers that matched the old filter and produced two empty
# "failed" dumps on every run (measured 2026-09-29 on vps1).
for c in $(docker ps --format '{{.Names}}	{{.Image}}' | awk -F'\t' 'tolower($2) ~ /(^|\/)postgres(:|$)/ {print $1}'); do
  u=$(docker exec "$c" sh -c 'printf %s "${POSTGRES_USER:-postgres}"' 2>/dev/null) || u=""
  [ -n "$u" ] || u=postgres
  echo "-- pg_dumpall $c (user $u)"
  if docker exec "$c" pg_dumpall -U "$u" > "$D/pg/$c.sql" 2> "$D/pg/$c.err"; then
    echo "   ok $(du -h "$D/pg/$c.sql" | cut -f1)"
    rm -f "$D/pg/$c.err"
  else
    echo "   WARN: pg_dumpall failed for $c: $(head -c 300 "$D/pg/$c.err" | tr '\n' ' ')"
    rm -f "$D/pg/$c.sql"
  fi
done

# ── 2. every docker volume, tarred from the engine's own directory ──────────────────────────────
# The host path is what a restore extracts back into the volume, and it needs no helper image and
# no per-volume container start. A volume on a non-local driver has no such path and is reported
# (never silently skipped): "the backup finished" must not mean "the volumes were left out".
for v in $(docker volume ls -q); do
  # the off-server copies (FPG-26) — an archive that held yesterday's archive would double every day
  case "$v" in dgo-offsite*) echo "   vol $v — the off-server copy itself, left out"; continue ;; esac
  src=/var/lib/docker/volumes/$v/_data
  if [ ! -d "$src" ]; then echo "WARN: volume $v has no local path — NOT backed up"; continue; fi
  # tar exits 1 when a file changed while it was being read — the NORMAL outcome for a volume a
  # running postgres is writing to, and the archive is still usable. Treating 1 as failure dropped
  # the platform's own postgres volume from EVERY backup (measured 2026-09-29 on vps1:
  # "WARN: tar failed for volume deployment-hacohen_postgres_storage", 347 MB left out).
  # `|| rc=$?` and not a bare call: the script runs under `set -e`, so a tar that exits 1 (see
  # below) would abort the whole backup instead of being classified.
  rc=0
  tar czf "$D/vol/$v.tar.gz" -C "$src" . 2>"$D/vol/$v.err" || rc=$?
  if [ "$rc" = "0" ]; then
    echo "   vol $v $(du -h "$D/vol/$v.tar.gz" | cut -f1)"
    rm -f "$D/vol/$v.err"
  elif [ "$rc" = "1" ]; then
    echo "   vol $v $(du -h "$D/vol/$v.tar.gz" | cut -f1) (הקבצים השתנו תוך כדי קריאה)"
    rm -f "$D/vol/$v.err"
  else
    echo "WARN: tar failed for volume $v (קוד $rc): $(head -c 200 "$D/vol/$v.err" | tr '\n' ' ')"
    rm -f "$D/vol/$v.tar.gz"
  fi
done

# ── 3. the config that a git checkout does NOT carry: the office's own secrets ──────────────────
for f in .env platform.state.yaml; do [ -f "$P/$f" ] && cp -a "$P/$f" "$D/etc/"; done
find "$P" -maxdepth 3 -name acme.json -exec cp -a {} "$D/etc/" \; 2>/dev/null || true

{
  echo "office   = __OID__"
  echo "machine  = $(hostname)"
  echo "path     = $P"
  echo "commit   = $(cd "$P" && git rev-parse HEAD 2>/dev/null)"
  echo "date     = $(date -Is)"
  echo "docker   = $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
  echo
  echo "pg dumps:"; ls -1 "$D/pg" 2>/dev/null
  echo "volumes:"; ls -1 "$D/vol" 2>/dev/null
  echo "etc:"; ls -1 "$D/etc" 2>/dev/null
} > "$D/MANIFEST"

echo "PG=$(ls -1 "$D/pg" 2>/dev/null | wc -l)"
echo "VOL=$(ls -1 "$D/vol" 2>/dev/null | wc -l)"
echo "SIZE=$(du -sh "$D" | cut -f1)"
echo "BYTES=$(du -sb "$D" | cut -f1)"
echo "BACKUP_DONE=$D"

# Keep the disk bounded: a pre-upgrade backup is ~the size of the machine's volumes, and a converge
# can be re-run many times in one evening. The three newest are kept, older ones are removed and
# named in the log — never a silent delete.
KEEP=3
ls -1dt /root/backup-*-pre-upgrade 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  echo "PRUNED=$old ($(du -sh "$old" 2>/dev/null | cut -f1))"
  rm -rf "$old"
done
"""


def step_backup(office: dict, ctx: dict, emit) -> dict:
    """A restore point before `code` moves the machine to another version.

    Only for an office that ALREADY exists in the directory (a first install has nothing to lose):
    the step is a no-op on a fresh machine and a full snapshot on every upgrade — which is the case
    that bites, because `code` changes the checkout and `run` restarts the stack on top of live
    volumes. Idempotent in the sense that matters: running it twice makes two backups, never a
    half-one, and it never deletes or moves anything the office had.

    What it does NOT do: stop containers. A hot tar of a postgres data directory is not a consistent
    restore, which is exactly why every postgres also gets a logical `pg_dumpall` — the tar covers
    the volumes nobody dumps (mail, n8n, redis, authentik media), the dump covers the databases.
    """
    p = q(office["path"])
    have = exec_on(office["machine"],
                   f"test -d {p}/.git && test -s {p}/.env && echo present", 30)
    if have.get("code") != 0 or "present" not in (have.get("stdout") or ""):
        return {"summary": "אין לשכה קיימת בתיקייה — אין מה לגבות"}
    script = (BACKUP.replace("__PATH__", p).replace("__OID__", office["id"]))
    # an off-server snapshot still running beside this one: each checked the free space alone, and both
    # together could fill the machine's disk — it ends first (FPG-26)
    if _detached_running(office, "offsite"):
        emit("── הגיבוי היומי מחוץ לשרת עדיין רץ על המחשב — ממתין שיסתיים")
        try:
            wait_detached(office, "offsite", lambda ln: None, limit=5400, every=15)
        except StepFailed:
            pass                                   # its own failure is its own; the disk is free again either way
    start_detached(office, "backup", script)
    tail = wait_detached(office, "backup", emit, limit=5400, every=10)
    f = parse_facts(tail)
    if f.get("BACKUP_SKIPPED"):
        return {"summary": "הגיבוי דולג — אין מקום פנוי בדיסק של המכונה",
                "warnings": [f.get("SKIP_REASON") or "אין מקום פנוי לגיבוי"], "skipped": True}
    if not f.get("BACKUP_DONE"):
        raise StepFailed("הגיבוי לא הושלם", "ראה את הפלט.", tail[-1500:])
    warns = [ln.strip() for ln in tail.splitlines() if ln.startswith("WARN")]
    pg_n, vol_n = f.get("PG", "?"), f.get("VOL", "?")
    return {"summary": f"{f['BACKUP_DONE']} · {pg_n} בסיסי נתונים · {vol_n} volumes · {f.get('SIZE')}",
            "dir": f["BACKUP_DONE"], "pg": pg_n, "volumes": vol_n,
            "bytes": f.get("BYTES"), "warnings": warns}


# ── the backup that leaves the server (FPG-26) ─────────────────────────────────────────────────────
#: A client's office is copied off its own machine every day: the same snapshot as the backup step
#: (every postgres dumped, every volume, .env, the certificates), ENCRYPTED on the machine before it
#: leaves — the snapshot holds the client's secrets and their customers' data — with a key that lives
#: only in THIS office's vault (instance offsite_key-<office>; a restore needs it — the archive's .json
#: names it and its fingerprint). The key reaches the machine on the carrying command's STDIN (never an
#: argv: not this container's ssh, not the far side's `bash -c`, not openssl's), inside a detached script
#: that deletes itself, and only openssl's own environment holds it. The encrypted file goes into the
#: office's volume on the machine (the latest only), and the computers app's transfer copies that volume
#: to THIS office's own machine, one volume per day, where its sha256 is checked against the machine's
#: (openssl enc has no authenticated mode: the check at home is the integrity). OFFSITE_KEEP are kept.
OFFSITE_VOLUME = "dgo-offsite"
OFFSITE_KEEP = int(os.environ.get("DGO_OFFSITE_KEEP", "7"))
OFFSITE_CIPHER, OFFSITE_ITER = "aes-256-cbc", 200000
OFFSITE_ENCRYPT = r"""
# ── the snapshot above, encrypted, into the office's volume the transfer carries home ─────────────
[ -n "${D:-}" ] && [ -d "$D" ] || { echo "OFFSITE_SKIPPED=1"; exit 0; }
set -o pipefail                                   # a tar that fails must fail the pipeline, not openssl's 0
docker volume create __VOLUME__ >/dev/null
OUT=$(docker volume inspect -f '{{.Mountpoint}}' __VOLUME__)
F="__OID__-$STAMP.tar.enc"
trap 'rm -rf "$D" "$OUT/$F.part" "$OUT/$F.json.part"' EXIT   # neither the plaintext nor half an archive stays
# written whole under another name first: a run that fails leaves the last good archive in place
tar cf - -C "$D" . | DGO_OFFSITE_KEY="$K" openssl enc -__CIPHER__ -md sha256 -pbkdf2 -iter __ITER__ -salt \
  -pass env:DGO_OFFSITE_KEY -out "$OUT/$F.part"
SHA=$(sha256sum "$OUT/$F.part" | cut -d' ' -f1)
# how to open it, beside it: a restorer needs nothing but this and the key the vault names
printf '{"file": "%s", "cipher": "__CIPHER__", "md": "sha256", "pbkdf2_iter": __ITER__, "key": "__KEYID__", "key_fingerprint": "__FP__", "sha256": "%s", "stamp": "%s"}\n' \
  "$F" "$SHA" "$STAMP" > "$OUT/$F.json.part"
mv "$OUT/$F.part" "$OUT/$F"
mv "$OUT/$F.json.part" "$OUT/$F.json"
find "$OUT" -mindepth 1 -maxdepth 1 \( -name '*.tar.enc' -o -name '*.json' -o -name '*.part' \) \
  ! -name "$F" ! -name "$F.json" -delete
rm -rf "$D"
echo "OFFSITE_STAMP=$STAMP"
echo "OFFSITE_FILE=$F"
echo "OFFSITE_BYTES=$(stat -c %s "$OUT/$F")"
echo "OFFSITE_SHA=$SHA"
"""


def offsite_volume(oid: str) -> str:
    """The office's own volume on its machine — two offices on one machine never share one."""
    return f"{OFFSITE_VOLUME}-{oid}"


#: The snapshot's own directory: the office's id in it, so two offices on one machine never share one, and
#: the leftover cleanup matches exactly that shape — never a restore drill's /root/offsite-restore, never a
#: pre-upgrade backup, never another office's live snapshot.
OFFSITE_SNAP = "/root/offsite-__OID__-$STAMP"
OFFSITE_SNAP_GLOB = "offsite-__OID__-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]"


def cache_volumes() -> list[str]:
    """The volumes the apps declare rebuildable (`data.cache` in their app.json: a pinned model, cached audio — never
    anything the office cannot re-fetch or re-run), read from this office's checkout. The off-server copy leaves them
    out (FPG-92: fireplace's 3.7 GB speech model was half of a 7.6 GB copy). Never fatal: none read, none left out."""
    if not HOME_REPO:
        return []
    try:
        out = must(LOCAL_MACHINE, f"cd {q(HOME_REPO)} && grep -l '\"cache\"' apps/*/app.json", 60)
    except StepFailed:
        return []
    vols = []
    for path in out.split():
        app = path.split("/")[1] if path.count("/") == 2 else ""
        if not re.fullmatch(r"[a-z0-9-]+", app):
            continue
        for v in ((_app_manifest(app).get("data") or {}).get("cache") or []):
            if isinstance(v, str) and re.fullmatch(r"[a-z0-9_.-]+", v):
                vols.append(v)
    return sorted(set(vols))


def offsite_script(path_q: str, oid: str, key: str, fingerprint: str, cache: list[str] | tuple = ()) -> str:
    """The detached script: the backup step's snapshot under its own name, then encrypted into the volume. The
    volumes in `cache` (cache_volumes(): rebuildable) are left out of this copy, by name — the pre-upgrade backup
    still takes everything."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", key or ""):
        # never «delete it and run again»: the key in the vault is the one the existing archives need
        raise StepFailed("מפתח הגיבוי שבכספת אינו במבנה הצפוי",
                         "אל תמחק אותו — הוא פותח את הגיבויים הקיימים. בדוק את offsite_key בכספת.")
    snap = OFFSITE_SNAP.replace("__OID__", oid)
    # the pre-upgrade backups' pruning is the UPGRADE's: a daily copy must not delete a restore point
    body, cut, _ = BACKUP.partition("# Keep the disk bounded:")
    snapshot = (body.replace("__PATH__", path_q).replace("__OID__", oid)
                .replace("D=/root/backup-$STAMP-pre-upgrade", f"D={snap}")
                # the snapshot AND its ciphertext, and the last good archive until the new one is whole
                .replace("need_mb=$(( vol_mb * 125 / 100 ))", "need_mb=$(( vol_mb * 225 / 100 ))"))
    skip = '  case "$v" in dgo-offsite*) echo "   vol $v — the off-server copy itself, left out"; continue ;; esac\n'
    if not cut or f"D={snap}" not in snapshot or "vol_mb * 225 / 100" not in snapshot or skip not in snapshot:
        raise StepFailed("תבנית הגיבוי השתנתה — הגיבוי מחוץ לשרת לא ירוץ", "", "")
    names = [c for c in cache if re.fullmatch(r"[a-z0-9_.-]+", c)]
    if names:   # a compose project prefixes its volumes (fireplace_apitools_asr_data): the name, or *_name
        pat = "|".join(f"{c}|*_{c}" for c in names)
        snapshot = snapshot.replace(skip, skip + f'  case "$v" in {pat}) echo "   vol $v — rebuildable (data.cache), '
                                                 f'left out of the off-server copy"; continue ;; esac\n')
    head = ("umask 077\n"
            f"K='{key}'\n"                       # not exported: only openssl gets it, in its own environment
            # a run killed outright (OOM, a reboot) ran no trap: its plaintext goes now
            f"find /root -maxdepth 1 -name '{OFFSITE_SNAP_GLOB.replace('__OID__', oid)}' -mmin +180 "
            "-exec rm -rf {} + 2>/dev/null || true\n"
            f"trap 'rm -rf \"{snap.replace('$STAMP', '${STAMP:-none}')}\"' EXIT\n")
    return (head + snapshot + OFFSITE_ENCRYPT.replace("__VOLUME__", offsite_volume(oid)).replace("__OID__", oid)
            .replace("__CIPHER__", OFFSITE_CIPHER).replace("__ITER__", str(OFFSITE_ITER))
            .replace("__KEYID__", f"offsite_key-{oid}").replace("__FP__", fingerprint))


def _home_copies(oid: str) -> str:
    """The shell that lists this office's copies here, one per line (the anchored name, never a prefix) —
    and FAILS when docker does not answer: «no copies» read from a docker that failed would let a new key
    be made over copies that need the old one."""
    # grep's 1 is «none» (also under pipefail); its 2, and docker's failure, are failures
    return (f"V=$(docker volume ls -q) || exit 1; printf '%s\\n' \"$V\" | "
            f"{{ grep -E '^{OFFSITE_VOLUME}-{oid}-[0-9]{{8}}-[0-9]{{6}}$' || [ $? = 1 ]; }} | sort")


def offsite_home(office: dict) -> str:
    """Where an office's off-server copies are kept (FPG-92): the machine its declaration names (`offsite_to`, a
    computers-app id — the herd's backup store), else DGO_OFFSITE_TO, else this home as before. A client whose copy
    grew to gigabytes does not fit an 8 GB MacBook's engine; the herd puts the store on the HP/Dell."""
    return str(office.get("offsite_to") or os.environ.get("DGO_OFFSITE_TO") or LOCAL_MACHINE)


def _offsite_key(office: dict) -> tuple[str, str]:
    """The office's off-server key and its fingerprint: read from this office's vault, made there once —
    and NEVER made while copies encrypted with a key already exist here: a new key would leave every one
    of them unreadable, and nobody would know until the day of a restore."""
    iid = f"offsite_key-{office['id']}"
    try:
        got = _http("GET", f"{CONNECTIONS_URL}/api/instances/{iid}/secret", timeout=15)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        got = {"_status": 0, "error": str(e)}            # unreachable: an answer of its own, never «missing»
    if "_status" in got and got["_status"] != 404:
        # the vault did not answer — that is not «the key is gone», and nothing may be made on it
        raise StepFailed("הכספת לא ענתה — מפתח הגיבוי לא נקרא", "ודא שאפליקציית החיבורים רצה, והרץ שוב.",
                         f"connections {got.get('_status')}: {str(got.get('error') or '')[:200]}")
    key = (got.get("secret") or {}).get("key") or ""
    if not key:
        held = 0
        for where in dict.fromkeys((offsite_home(office), LOCAL_MACHINE)):   # the store, and the home's older copies
            have = must(where, _home_copies(office["id"]) + " | wc -l", 60, "לא ניתן לבדוק גיבויים קיימים")
            held += int((have.strip() or "0").splitlines()[-1])
        if held > 0:
            raise StepFailed("מפתח הגיבוי חסר בכספת — אבל יש כאן גיבויים שהוצפנו בו",
                             f"החזר את {iid} לכספת (מגיבוי של הכספת): בלעדיו אי אפשר לשחזר אותם. "
                             "מפתח חדש לא נוצר.")
        key = secrets.token_urlsafe(32)
        r = _http("POST", f"{CONNECTIONS_URL}/api/instances",
                  {"id": iid, "protocol": "offsite_key",
                   "label": f"מפתח הגיבוי מחוץ לשרת · {office.get('label') or office['id']}",
                   "account_hint": "a restore of this office's off-server backups needs it",
                   "secret": {"key": key}})
        if r.get("_status") and r["_status"] != 409:
            raise StepFailed("לא ניתן לשמור את מפתח הגיבוי בכספת", "ודא שאפליקציית החיבורים רצה.",
                             f"connections {r.get('_status')}")
        key = (vault_secret(iid) or {}).get("key") or ""   # read back: what is stored is what encrypts
        if not key:
            raise StepFailed("מפתח הגיבוי לא נקרא חזרה מהכספת", "הרץ שוב.")
    return key, hashlib.sha256(key.encode()).hexdigest()[:12]


def _transfer_volume(frm: str, to: str, volume: str, dest_volume: str, emit, limit: int = 7200) -> dict:
    """The computers app's verified volume copy, followed to its end. Raises on anything but `ok`. The
    app moves ONE volume at a time: while another office's copy runs, this one waits its turn — the wait
    and the copy each have `limit`, and a copy that runs out of it is CANCELLED, never left holding the
    app's one slot (or writing into a volume this step is about to remove)."""
    started, said = time.time(), None
    while True:
        r = _http("POST", f"{COMPUTERS_URL}/api/computers/{frm}/transfer",
                  {"to": to, "volume": volume, "dest_volume": dest_volume, "restart": True}, timeout=60)
        job = r.get("job") or {}
        if job.get("id"):
            break
        if r.get("active") and time.time() - started < limit:
            emit("   העברה אחרת רצה — ממתין לתורה")
            time.sleep(30)
            continue
        raise StepFailed("העברת הגיבוי לא התחילה", "", str(r.get("error") or r)[:500])
    started, misses = time.time(), 0
    while True:
        try:
            out = _http("GET", f"{COMPUTERS_URL}/api/transfers/{job['id']}", timeout=30)
            misses = 0
        except _HTTP_MISS as e:
            misses += 1                            # one lost answer is a blip; three are a copy nobody follows
            if misses < 3:
                time.sleep(10)
                continue
            raise _cancelled(job["id"], StepFailed("שירות המחשבים לא עונה באמצע העברת הגיבוי",
                                                   "הרץ שוב — ייווצר גיבוי חדש.", str(e)[:300]))
        if out.get("_status") == 404:              # the job lived in memory: the computers app restarted
            raise StepFailed("שירות המחשבים הופעל מחדש באמצע העברת הגיבוי", "הרץ שוב — ייווצר גיבוי חדש.")
        s = out.get("transfer") or {}
        state = s.get("state")
        if state == "ok":
            return s
        if state in ("error", "cancelled"):
            raise StepFailed("העברת הגיבוי נכשלה", "הרץ שוב — ייווצר גיבוי חדש.", str(s.get("error") or state)[:500])
        if time.time() - started > limit:
            raise _cancelled(job["id"], StepFailed("העברת הגיבוי לא הסתיימה בזמן", "הרץ שוב — ייווצר גיבוי חדש.",
                                                   f"{s.get('percent')}%"))
        if s.get("percent") is not None and s.get("percent") != said:
            said = s["percent"]
            emit(f"   {said}%")
        time.sleep(10)


#: what a lost answer from the computers app can look like: no connection, a cut-off reply, a body not JSON
_HTTP_MISS = (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError)


def _cancel_transfer(job_id: str, wait: int = 180) -> bool:
    """Cancel a copy and FOLLOW it to its end (bounded). Whether it ended: a job past its streaming (verify,
    extract) does not stop at once, and a cleanup beside it would have its extract recreate a volume
    directory docker does not know."""
    try:
        _http("POST", f"{COMPUTERS_URL}/api/transfers/{job_id}/cancel", {}, timeout=30)
    except _HTTP_MISS:
        pass
    until = time.time() + wait
    while time.time() < until:
        try:
            out = _http("GET", f"{COMPUTERS_URL}/api/transfers/{job_id}", timeout=30)
        except _HTTP_MISS:
            out = {}
        if out.get("_status") == 404 or (out.get("transfer") or {}).get("state") in ("ok", "error", "cancelled"):
            return True
        time.sleep(10)
    return False


def _cancelled(job_id: str, err: StepFailed) -> StepFailed:
    """The failure to raise once the copy is cancelled — marked when the copy is STILL running, so the step
    leaves its volume alone (retention removes it later, as a copy never verified)."""
    err.copy_running = not _cancel_transfer(job_id)
    return err


def _detached_running(office: dict, name: str) -> bool:
    """Whether the office's detached script `name` (offsite, backup) still runs on its machine — it can
    outlive its run's wait. `[.]`: the pattern must not match this very command's shell, whose argv carries
    its text."""
    d = ctl_dir(office)
    busy = exec_on(office["machine"], f"test -f {d}/{name}.log && ! test -f {d}/{name}.rc && "
                                      f"pgrep -f '[.]digital-office/{office['id']}/{name}[.]sh' >/dev/null && echo BUSY", 30)
    return "BUSY" in (busy.get("stdout") or "")


def step_offsite(office: dict, ctx: dict, emit) -> dict:
    p, oid = q(office["path"]), office["id"]
    have = exec_on(office["machine"], f"test -s {p}/.env && command -v openssl >/dev/null && echo ready", 30)
    if have.get("code") != 0 or "ready" not in (have.get("stdout") or ""):
        raise StepFailed("אין במכונה לשכה מותקנת או openssl", "הרץ converge מלא קודם.")
    # the snapshot is the WHOLE machine's (every postgres, every volume): with another office on it, this
    # office's archive would carry that office's customers under this office's key — refused, not mixed
    others = [d["id"] for d in _records(lambda d: str(d.get("kind") or "office") == "office"
                                         and d.get("machine") == office.get("machine") and d.get("id") != oid)]
    if others:
        raise StepFailed("על המחשב הזה יש לשכה נוספת — הגיבוי מחוץ לשרת לוקח את כל המחשב",
                         "גיבוי לפי לשכה על מחשב משותף עוד לא נבנה; העבר כל לשכה למחשב משלה.",
                         ", ".join(others))
    key, fp = _offsite_key(office)
    # a pre-upgrade backup that outlived its converge ends first: each checked the free space alone
    if _detached_running(office, "backup"):
        emit("── גיבוי לפני עדכון עדיין רץ על המחשב — ממתין שיסתיים")
        try:
            wait_detached(office, "backup", lambda ln: None, limit=5400, every=15)
        except StepFailed:
            pass
    # a backup an earlier run left running (it ran past that run's wait) is FOLLOWED, never doubled: a second
    # script beside it would delete its half archive, and its exit code would read as the new one's
    if _detached_running(office, "offsite"):
        emit("── גיבוי מהרצה קודמת עדיין רץ על המחשב — עוקב אחריו")
    else:
        start_detached(office, "offsite", offsite_script(p, oid, key, fp, cache_volumes()), secret=True)
    tail = wait_detached(office, "offsite", emit, limit=5400, every=10)
    f = parse_facts(tail)
    if f.get("BACKUP_SKIPPED") or f.get("OFFSITE_SKIPPED"):
        raise StepFailed("הגיבוי מחוץ לשרת דולג — אין מקום פנוי בדיסק של המכונה", "",
                         f.get("SKIP_REASON") or "")
    # every fact the machine reports is checked for its exact shape before any of it reaches a command HERE:
    # the log is written on the client's server, and its root must not be able to run a thing on this one
    stamp, fname, sha = f.get("OFFSITE_STAMP", ""), f.get("OFFSITE_FILE", ""), f.get("OFFSITE_SHA", "")
    nbytes = f.get("OFFSITE_BYTES", "") if re.fullmatch(r"[0-9]{1,15}", f.get("OFFSITE_BYTES", "")) else ""
    if not (re.fullmatch(r"[0-9]{8}-[0-9]{6}", stamp) and fname == f"{oid}-{stamp}.tar.enc"
            and re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise StepFailed("הגיבוי המוצפן לא נוצר", "ראה את הפלט.", tail[-1500:])
    # what the snapshot could not take (a database whose dump failed, a volume with no path) is SAID
    warns = [ln.strip() for ln in tail.splitlines() if ln.startswith("WARN")]
    dest = f"{OFFSITE_VOLUME}-{oid}-{stamp}"
    mount = f"$(docker volume inspect -f '{{{{.Mountpoint}}}}' {q(dest)})"
    home = offsite_home(office)
    # the store is asked for room BEFORE anything moves: the transfer stages the archive and then extracts it, so
    # it needs twice the archive, and a copy that does not fit is refused by name (10-30: a 7.6 GB copy met a
    # 14 GB-free engine that keeps five copies)
    room = exec_on(home, "df -PB1 \"$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)\" "
                         "| awk 'NR==2{print $4}'", 60)
    free = (room.get("stdout") or "").strip()
    if nbytes and re.fullmatch(r"[0-9]{1,15}", free) and int(free) < 2 * int(nbytes) + (1 << 30):
        raise StepFailed("אין מקום במחסן הגיבויים לעותק הזה", "פנה מקום שם, או הגדר offsite_to למחשב אחר.",
                         f"{home}: free {int(free) >> 20} MB, needs {(2 * int(nbytes) + (1 << 30)) >> 20} MB")
    emit(f"── {fname} ({nbytes} bytes) → {home}: {dest}")
    try:
        _transfer_volume(office["machine"], home, offsite_volume(oid), dest, emit)
        # what arrived was made by the client's machine: it holds EXACTLY the archive and its .json, as plain
        # files, before anything here reads it — a link or a pipe from there must not lead a root command
        # here anywhere (a .verified pointing at /etc/nologin, an archive that is /dev/zero)
        # the integrity: the file that arrived is the file the machine encrypted — and only then is the copy
        # marked as one (retention counts nothing else: a copy cut short by a crash HERE is no backup)
        got = must(home,
                   f"set -o pipefail; m={mount}; [ -n \"$m\" ] || exit 2; "
                   f"odd=$(find \"$m\" -mindepth 1 \\( ! -type f -o ! \\( -name {q(fname)} -o -name {q(fname + '.json')} \\) \\) "
                   f"-print -quit) || exit 2; [ -z \"$odd\" ] || {{ echo \"UNEXPECTED=$odd\"; exit 0; }}; "
                   f"sha256sum \"$m\"/{q(fname)} | cut -d' ' -f1", 300, "לא ניתן לבדוק את הגיבוי שהגיע")
        if "UNEXPECTED=" in got:
            raise StepFailed("בגיבוי שהגיע יש משהו מלבד הארכיון", "הגיבוי לא נשמר. בדוק את השרת של הלקוח.",
                             got.strip()[:300])
        if got.strip() != sha:
            raise StepFailed("הגיבוי שהגיע אינו זהה לגיבוי שהוצפן במכונה", "הרץ שוב — ייווצר גיבוי חדש.",
                             f"sha256 {got.strip()[:12]} ≠ {sha[:12]}")
        must(home, f"m={mount}; [ -n \"$m\" ] && rm -f \"$m\"/.verified && : > \"$m\"/.verified", 60,
             "לא ניתן לסמן את הגיבוי שנבדק")
    except Exception as e:
        # a copy that did not arrive whole is no copy: neither its volume nor the transfer's staging stays,
        # or empty volumes would count as backups and push real ones out — whatever cut it short (the
        # computers app restarting answers a refused connection, not a StepFailed). A copy STILL running is
        # left alone (removing its volume beside its extract leaves a directory docker does not know):
        # never verified, the next run's retention removes it.
        if getattr(e, "copy_running", False):
            emit("── ההעברה עדיין רצה אחרי הביטול — העותק שלה לא נבדק, והניקוי הבא יסיר אותו")
        else:
            exec_on(home, f"docker volume rm {q(dest)} >/dev/null 2>&1; "
                                   f"rm -f {q(f'/var/lib/bina-transfer/{offsite_volume(oid)}__{dest}.tar')}*", 60)
        if isinstance(e, StepFailed):
            raise
        raise StepFailed("העברת הגיבוי נקטעה", "הרץ שוב — ייווצר גיבוי חדש.", f"{type(e).__name__}: {e}"[:500]) from e
    # the copies here: OFFSITE_KEEP newest by name (the stamp sorts by time) among those VERIFIED; one that is
    # not (a copy an older version or a crash left) is removed first. Each removal is named.
    keep = must(home,
                f"set -o pipefail; L=$({_home_copies(oid)}) || exit 1; "
                f"for v in $L; do m=$(docker volume inspect -f '{{{{.Mountpoint}}}}' \"$v\"); "
                f"[ -f \"$m\"/.verified ] && [ ! -L \"$m\"/.verified ] && echo \"$v\" || {{ docker volume rm \"$v\" >/dev/null && "
                f"echo \"PRUNED=$v (unverified)\" >&2; }}; done | sort | head -n -{OFFSITE_KEEP} | while read -r v; do "
                f"docker volume rm \"$v\" >/dev/null && echo \"PRUNED=$v\"; done; "
                f"echo KEPT=$({_home_copies(oid)} | wc -l)", 180, "לא ניתן לנקות גיבויים ישנים")
    kf = parse_facts(keep)
    return {"summary": f"גיבוי מוצפן {nbytes} bytes → {dest} · נבדק · נשמרים {kf.get('KEPT', '?')}",
            "file": fname, "bytes": nbytes, "sha256": sha,
            "volume": dest, "store": home, "verified": True, "kept": kf.get("KEPT"), "warnings": warns,
            "key": f"offsite_key-{oid}", "key_fingerprint": fp}


def code_script(p: str, repo: str, branch: str, commit: str, auth: str = "",
                allow_rollback: bool = False) -> str:
    """The script the code step runs on the machine: clone or fetch, then put the checkout at `commit`.

    A CONVERGE NEVER STEPS AN OFFICE BACK (DGO-1016). On 2026-10-16 14:14 UTC a converge from the
    MacBook checked vps1 out at d24547e2, the commit its declaration had been saved with eight days
    earlier, and rebuilt every service from it. The 418 commits vps1 was running left without a
    word; among them the price of a conversation in Azaria's sessions (plugins/cost-meter), which
    the owner had asked for and then found gone. The stash below keeps only UNCOMMITTED work, so
    committed work was the one kind nothing protected.

    So a checkout that already exists must be CONTAINED in the declared commit. A machine whose
    HEAD is not an ancestor of it runs something the declaration would drop. The step then stops
    and names what would go (exit 3, `ROLLBACK:` and `DROP:` lines). The declaration moves forward
    to a commit that holds both, or says `source.allow_rollback: true` when going back is meant.
    A fresh clone has nothing to lose and is never asked.
    """
    return f"""
export GIT_TERMINAL_PROMPT=0
if ! command -v git >/dev/null; then apt-get update -q && apt-get install -y -q git; fi
# bbox's compiler (platform/manager/reconcile.py) needs python3 + PyYAML on the machine itself
python3 -c 'import yaml' 2>/dev/null || {{ apt-get update -q && apt-get install -y -q python3 python3-yaml; }}
P={q(p)}
fresh=0
if [ ! -d "$P/.git" ]; then
  mkdir -p "$(dirname "$P")"
  git {auth} clone --no-checkout {q(repo)} "$P"
  fresh=1
fi
cd "$P"
git {auth} fetch --quiet origin {q(branch) if branch else ''} || git {auth} fetch --quiet origin
git cat-file -e {q(commit)}^{{commit}} 2>/dev/null || git {auth} fetch --quiet origin {q(commit)}
# Never back (see code_script's docstring): what this machine runs must be inside the declared commit.
# A clone that was never checked out (a first converge that stopped after `clone --no-checkout`) has an
# empty index and runs nothing; its HEAD is only the remote's default branch.
[ -n "$(git ls-files | head -1)" ] || fresh=1
cur="$(git rev-parse -q --verify 'HEAD^{{commit}}' 2>/dev/null || true)"
if [ "$fresh" = 0 ] && [ -n "$cur" ] && [ {1 if allow_rollback else 0} != 1 ] \\
   && ! git merge-base --is-ancestor "$cur" {q(commit)}; then
  git log --date=short --format='DROP: %h %ad %<(70,trunc)%s' -n 8 {q(commit)}..$cur
  echo "ROLLBACK: $(git rev-list --count {q(commit)}..$cur) commits on this machine are not in {commit[:12]} (HEAD $(git rev-parse --short=12 "$cur"))"
  exit 3
fi
# platform.state.yaml is DERIVED from the declaration on every converge (step: state), so a local
# copy of it is never work to keep. Anything else changed by hand on the machine is kept in a stash.
# The fallback matters after the split: an office whose file is no longer tracked has nothing for
# `git checkout` to restore, and the product default is what the state step then derives from.
git checkout -- platform.state.yaml 2>/dev/null || cp -a platform.state.default.yaml platform.state.yaml 2>/dev/null || true
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "STASHED: $(git diff --name-only | tr '\\n' ' ')"
  git stash push -m "dgo-extend: local changes before {commit[:12]}"
fi
git -c advice.detachedHead=false checkout --quiet --detach {q(commit)}
# A release copy carries no platform.state.yaml (a new office starts from the product default), and
# on a fresh clone the fallback above ran before the commit put any file in the tree — the state step
# then found no file to write (fireplace, 2026-10-22). Now that the files are here, make it.
[ -f platform.state.yaml ] || cp -a platform.state.default.yaml platform.state.yaml 2>/dev/null || true
echo "HEAD=$(git rev-parse HEAD)"
"""


def step_code(office: dict, ctx: dict, emit) -> dict:
    src = office.get("source") or {}
    repo, branch, commit = src.get("repo"), src.get("branch") or "", src.get("commit") or ""
    if not repo or not commit:
        raise StepFailed("להצהרה חסר מקור קוד (repo + commit)", "ערוך את הלשכה ובחר גרסה.")
    p = office["path"]
    auth = _auth_header(office)
    script = code_script(p, repo, branch, commit, auth, bool(src.get("allow_rollback")))
    try:
        # Both can raise the refusal: a step that refuses at once is caught by start_detached's own
        # read of the exit code (with the log's last 800 bytes, where ROLLBACK: is printed last).
        start_detached(office, "code", script, secret=bool(auth))
        tail = wait_detached(office, "code", emit, limit=1800, every=5)
    except StepFailed as e:
        dropped = re.search(r"ROLLBACK: (\d+)", e.detail or "")
        if not dropped:
            raise
        raise StepFailed(f"הגרסה המוצהרת ({commit[:12]}) ישנה ממה שרץ על המחשב: {dropped.group(1)} שינויים "
                         "שהלשכה כבר מריצה היו נעלמים. הקוד לא הוחלף, ושום שירות לא נבנה מחדש.",
                         "בחר בהצהרה גרסה שמכילה את מה שרץ עכשיו (מיזוג), או סמן במפורש "
                         "'לחזור לגרסה ישנה' (source.allow_rollback) אם זו הכוונה.",
                         e.detail) from None
    head = re.search(r"HEAD=([0-9a-f]{40})", tail)
    stashed = re.search(r"STASHED: (.*)", tail)
    if not head or not head.group(1).startswith(commit[:7]):
        raise StepFailed("הקוד על המחשב אינו בגרסה המוצהרת", "", tail[-1500:])
    return {"summary": f"{head.group(1)[:10]} ב־{p}",
            "warnings": [f"שינויים מקומיים נשמרו ב־git stash: {stashed.group(1)}"] if stashed else []}


def step_engine(office: dict, ctx: dict, emit) -> dict:
    have = (ctx.get("facts") or {}).get("docker") or ""
    if have.split(".")[0] == DOCKER_MAJOR:
        return {"summary": f"Docker {have}"}
    replace = bool((office.get("engine") or {}).get("replace_docker"))
    if have and not replace:
        raise StepFailed(f"על המחשב מותקן Docker {have}; הלשכה צריכה Docker {DOCKER_MAJOR}.x",
                         "Docker 29 שובר את הניתוב בשקט. סמן 'להחליף את Docker' בהגדרות הלשכה — "
                         "הקונטיינרים יעצרו לרגע, ה־volumes נשמרים.")
    script = f"cd {q(office['path'])}\nBBOX_REPLACE_DOCKER={1 if replace else 0} bash debian-install.sh\n" \
             f"docker version --format 'DOCKER={{{{.Server.Version}}}}'\n"
    start_detached(office, "engine", script)
    tail = wait_detached(office, "engine", emit, limit=1800)
    m = re.search(r"DOCKER=(\S+)", tail)
    return {"summary": f"Docker {m.group(1) if m else '?'} הותקן"}


#: Is this `.env` the installer's copy of `.env.ex`? `debian-install.sh` (`setup_env_variables`, run by
#: the engine step, which comes BEFORE env) copies the template when there is no `.env`, so a fresh
#: machine always reached step_env with a file: `fresh` was never true, `ci-env.sh` never ran, and the
#: office came up on the template's published placeholder secrets and its home domain (fireplace,
#: 2026-10-22: DEPLOYMENT_DOMAIN=hacohen.…, every password the one in .env.ex). A copy is recognised by
#: its secrets — ALL of the template's literal ones still equal — because the URLs of a copy may
#: already have been normalised by an earlier ENV_MERGE. `ci-env.sh` changes every one of them, so a
#: generated `.env` can never read as a copy.
TEMPLATE_CHECK = r"""
import re
def parse(path):
    out = {}
    for ln in open(path, encoding='utf-8', errors='replace').read().splitlines():
        m = re.match(r'^([A-Z0-9_]+)=(.*)$', ln)
        if m:
            out[m.group(1)] = m.group(2).split(' #')[0].strip().strip("'\"")
    return out
env, ex = parse('.env'), parse('.env.ex')
keys = [k for k, v in ex.items() if re.search(r'(PASSWORD|SECRET|_KEY|TOKEN)$', k) and v and '${' not in v]
print('TEMPLATE=%d' % (1 if keys and all(env.get(k) == ex[k] for k in keys) else 0))
"""

ENV_MERGE = r"""
import os, re, sys, datetime, secrets, shutil
# THE RENAME (FPG-33): an installed office moves to another domain (the owner, DGO-1032: fireplace from
# thefireplaceguys.digital-office.co.il to fpg.digital-office.co.il). The declaration carries both names
# (the record keeps `renamed_from` when its domain changes), and the rename happens only while this
# .env still names exactly the previous one: any other domain is refused below, as before. ci-env.sh
# wrote every host out in full (63 keys on fireplace), so every value naming the old domain as a whole
# word (a host, a subdomain, a URL) gets the new one. An ADDRESS (`admin@<old>`) is not renamed: it is
# the sign-in of an account that n8n, Plane, GlitchTip and authentik already hold, and the platform logs
# in with it (connections → n8n, the vault's login): those keys are named in EMAILS_KEPT, and the
# accounts move as a step of their own (the second reader). The file is copied aside first, replaced
# whole, and only key names are printed.
renamed, kept = [], []
old_d, new_d = os.environ.get('DGO_RENAME_FROM', ''), os.environ.get('DGO_RENAME_TO', '')
if old_d and new_d and old_d != new_d and not (new_d.endswith('.' + old_d) or old_d.endswith('.' + new_d)):
    text = open('.env').read()
    flat = {}
    for ln in text.splitlines():
        m = re.match(r'^([A-Z0-9_]+)=(.*)$', ln)
        if m:
            v = m.group(2).split(' #')[0].strip().strip("'\"")
            flat[m.group(1)] = re.sub(r'\$\{([A-Z0-9_]+)\}', lambda x: flat.get(x.group(1), ''), v)
    if flat.get('DEPLOYMENT_DOMAIN') == old_d:
        # whole word: not inside a longer label, and not the start of a longer name (`old.example.net`)
        whole = re.compile(r'(?<![A-Za-z0-9-])' + re.escape(old_d) + r'(?![A-Za-z0-9-]|\.[A-Za-z0-9])')
        # …and `${DEPLOYMENT_DOMAIN}`, which follows the domain once it is renamed
        composed = re.compile(r'\$\{DEPLOYMENT_DOMAIN(?::-[^}]*)?\}')

        def is_address(v, start):
            # the word the name sits in, back to the last separator: `admin@`, `noreply@mail.`,
            # `mailto:admin@` are addresses; `https://u:CHANGE_ME@` is a URL's host
            i = start
            while i > 0 and v[i - 1] not in ' \t,;"\'<>()[]':
                i -= 1
            word = v[i:start]
            return '@' in word and '://' not in word

        out = []
        for ln in text.split('\n'):
            m = re.match(r'^([A-Z0-9_]+)=(.*)$', ln)
            if m and m.group(1) == 'DEPLOYMENT_DOMAIN':
                # written literally, whatever its form was: a composed `${COMPANY_SLUG}.…` names no
                # domain to replace, and every composed value below resolves through this one
                ln = 'DEPLOYMENT_DOMAIN=' + new_d
                renamed.append(m.group(1))
            elif m:
                v, parts, last, host, addr = m.group(2), [], 0, False, False
                for mm in sorted(list(whole.finditer(m.group(2))) + list(composed.finditer(m.group(2))),
                                 key=lambda x: x.start()):
                    if is_address(v, mm.start()):
                        addr = True
                        # an address written as `admin@${DEPLOYMENT_DOMAIN}` stays on the old name too
                        parts += [v[last:mm.start()], old_d if mm.re is composed else mm.group(0)]
                    elif mm.re is whole:
                        host = True
                        parts += [v[last:mm.start()], new_d]
                    else:
                        parts += [v[last:mm.start()], mm.group(0)]
                    last = mm.end()
                if host or addr:
                    ln = m.group(1) + '=' + ''.join(parts) + v[last:]
                if host:
                    renamed.append(m.group(1))
                if addr:
                    kept.append(m.group(1))
            out.append(ln)
        # the file itself, wherever .env points (a packaged office links it to /etc/binaos/binaos.env, and
        # replacing the link would leave the real file on the old domain for the next upgrade to restore)
        real = os.path.realpath('.env')
        tmp = real + '.rename-tmp'
        if os.path.lexists(tmp):
            os.remove(tmp)                 # a run cut short left it, with every secret in it
        shutil.copy2(real, '.env.before-rename-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
        # replaced whole: a write cut short (a full disk) must not leave half a .env behind; and 0600
        # from its first byte, not after
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
            f.write('\n'.join(out))
        shutil.copymode(real, tmp)
        os.replace(tmp, real)
print('RENAMED=' + ','.join(renamed))
print('EMAILS_KEPT=' + ','.join(kept))
env = open('.env').read()
have = {m.group(1) for m in re.finditer(r'^([A-Z0-9_]+)=', env, re.M)}
# Secrets no generator writes (S26: nothing minted the vault's root key, and compose falls back to
# its published default — `dev-root-key-not-for-production`, which the public export scrubs to
# CHANGE_ME). Only while the office has no vault yet (DGO_MINT=1): an existing vault is encrypted with
# the key it has, and a new one would lock it. A real value anywhere in the file is kept.
minted = []
if os.environ.get('DGO_MINT') == '1':
    for key in ('CONNECTIONS_ROOT_KEY',):
        found = [v.split(' #')[0].strip().strip("'\"") for v in re.findall(r'^%s=(.*)$' % key, env, re.M)]
        if all(v in ('', 'CHANGE_ME', 'dev-root-key-not-for-production') for v in found):
            env = re.sub(r'^%s=.*\n?' % key, '', env, flags=re.M)
            env = env.rstrip('\n') + '\n%s=%s\n' % (key, secrets.token_urlsafe(32))
            minted.append(key)
            have.add(key)
    # …and every own secret the template asks to be replaced. ci-env.sh randomises the keys it knows;
    # the rest arrived as .env.ex has them (fireplace, 2026-10-22: MCP_AUTH_TOKEN=CHANGE_ME — the header
    # n8n's MCP endpoints accept — and the SUPABASE_*_PASSWORD keygen keeps because they are not
    # missing). A key of an OUTSIDE provider (…_API_KEY, or `your-…-here`) is left as it is: a random
    # value there would read as configured.
    lines = env.split('\n')
    placeholder = re.compile(r'CHANGE_ME|change_me_to_(random|secure)\w*')
    value_of = lambda ln: ln.split('=', 1)[1].split(' #')[0].strip().strip("'\"")
    real = {ln.split('=', 1)[0] for ln in lines if re.match(r'^[A-Z0-9_]+=', ln)
            and not placeholder.fullmatch(value_of(ln))}   # a real value anywhere keeps the key whole
    fresh_values = {}                  # one value per key, written to EVERY line of it (compose reads the last)
    root_minted = set(minted)
    for i, ln in enumerate(lines):
        m = re.match(r'^([A-Z0-9_]+)=(.*)$', ln)
        if not m or m.group(1) in root_minted or m.group(1) in real or m.group(1).endswith('API_KEY') \
                or not re.search(r'(PASSWORD|SECRET|TOKEN|_KEY)$', m.group(1)):
            continue
        value = value_of(ln)
        if placeholder.fullmatch(value):
            key = m.group(1)
            if key not in fresh_values:
                fresh_values[key] = secrets.token_hex(16 if '32_hex' in value else 24)
                minted.append(key)
            lines[i] = '%s=%s' % (key, fresh_values[key])
    env = '\n'.join(lines)
    if minted:
        open('.env', 'w').write(env)
print('MINTED=' + ','.join(minted))
add = []
for ln in open('.env.ex').read().splitlines():
    m = re.match(r'^([A-Z0-9_]+)=', ln)
    # never the vault's key: with no line the vault runs under compose's default, and appending the
    # template's CHANGE_ME would switch its key and lock it (hos-002's second reader); minting it is above.
    # Nor DGO_IDENTITY: an office with no line asks authentik (traefik's compose default), and the
    # template's forward-auth (release 0.3.0) would point its edge at a sign-in it does not run.
    if m and m.group(1) not in have and m.group(1) not in ('CONNECTIONS_ROOT_KEY', 'DGO_IDENTITY'):
        add.append(ln); have.add(m.group(1))
if add:
    with open('.env', 'a') as f:
        f.write('\n# ── added by the dgo-extend app %s: keys this version needs that this .env lacked\n'
                % datetime.date.today().isoformat())
        f.write('\n'.join(add) + '\n')
print('ADDED=' + ','.join(a.split('=', 1)[0] for a in add))
vals = {}
for ln in open('.env').read().splitlines():
    m = re.match(r'^([A-Z0-9_]+)=(.*)$', ln)
    if m:
        v = m.group(2).split(' #')[0].strip().strip("'\"")
        vals[m.group(1)] = re.sub(r'\$\{([A-Z0-9_]+)\}', lambda x: vals.get(x.group(1), ''), v)
# A composed DEPLOYMENT_DOMAIN (`${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}` — what the staging machine
# carried) is not a domain as far as this platform is concerned: compose resolves it for the
# container labels, but the compilers read .env with a flat parser, so the SSO blueprint rendered
# `hello-bina.localhost` and `mail.localhost` while traefik routed `hello-bina.staging.<domain>` and
# `mail.staging.<domain>`. The result is a host that ROUTES and then 404s at the identity layer —
# measured on vps1 on 2026-09-30 (console and drive answered 302, mail/notifications/hello-bina 404,
# because their provider rows were registered for the wrong host). The office's domain is already
# declared, so writing it literally is both the fix and idempotent.
# EVERY composed value, resolved — not just the domain. Two different readers consume this file and
# only one of them expands variables: docker compose does, the compilers do not, and neither does a
# container's own label. mail's traefik rule is `Host(mail.${DEV_DOMAIN:-localhost})` and
# DEV_DOMAIN=${DEPLOYMENT_DOMAIN}, so on a machine that carried the nested form the rule became
# `Host(mail.${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN})` and the app had NO router at all: TLS fell back
# to traefik's default certificate and the host answered 000/404 (measured on vps1, 2026-09-30).
# A value that still contains '${' after one pass, or resolves empty, is left exactly as it was.
lines = open('.env').read().splitlines()
norm = []
for i, ln in enumerate(lines):
    m = re.match(r'^([A-Z0-9_]+)=(.*)$', ln)
    if not m or '${' not in m.group(2):
        continue
    key, raw = m.group(1), m.group(2)
    value = re.sub(r'\$\{([A-Z0-9_]+)(?::-([^}]*))?\}',
                   lambda x: vals.get(x.group(1)) or x.group(2) or '', raw)
    if value and '${' not in value and value != raw:
        lines[i] = f'{key}={value}'
        norm.append(key)
if norm:
    with open('.env', 'w') as f:
        f.write('\n'.join(lines) + '\n')
print('NORMALIZED=' + ','.join(norm))
print('DOMAIN=' + vals.get('DEPLOYMENT_DOMAIN', ''))
print('NAME=' + vals.get('DEPLOYMENT_NAME', ''))
"""


#: The volumes whose contents a secret of .env unlocks: the vault (CONNECTIONS_ROOT_KEY) and the
#: databases initialised with the passwords. Matched by SUFFIX, as hooks/migrate's find_volume does —
#: the compose project's name is chosen in scripts/lib.sh (pinned, symlink-resolved, or a fallback for a
#: folder name compose cannot use), and a guess at it here once read a live office as empty.
DATA_VOLUMES = ("connections_vault", "supabase_db_data", "authentik_postgres_data")


def _office_data(office: dict) -> int:
    """How many of DATA_VOLUMES exist on the office's machine — 0 = nothing a new secret could lock.

    Unknown is never 0: when docker cannot be asked (no answer, daemon down, no permission) the step
    stops, because the two decisions this answers — replace a template .env, mint a vault key — are
    exactly the ones that lock an office out of its own data when they are wrong."""
    pattern = "(^|_)(%s)$" % "|".join(DATA_VOLUMES)
    out = exec_on(office["machine"], f"n=$(docker volume ls --format '{{{{.Name}}}}') || exit 7; "
                                     f"printf '%s\\n' \"$n\" | grep -cE {q(pattern)} || true", 30)
    try:
        if out.get("code") != 0:
            raise ValueError(out.get("code"))
        return int((out.get("stdout") or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise StepFailed("לא ניתן לדעת אם ללשכה כבר יש נתונים — docker volume ls לא ענה במחשב",
                         "ודא ש-Docker רץ במחשב והרץ שוב. השלב לא יחליף סודות בלי לדעת.",
                         (out.get("stderr") or "")[-800:])


def step_env(office: dict, ctx: dict, emit) -> dict:
    p = q(office["path"])
    fresh = exec_on(office["machine"], f"test -s {p}/.env", 20).get("code") != 0
    volumes = _office_data(office)
    if not fresh:
        check = base64.b64encode(TEMPLATE_CHECK.encode()).decode()
        if parse_facts(must(office["machine"], f"cd {p} && echo {check} | base64 -d | python3 -", 60,
                            "בדיקת עותק התבנית ב־.env נכשלה")).get("TEMPLATE") == "1":
            if volumes:
                # It RAN on the template's secrets: the databases were initialised with them, and new
                # ones would lock every service out of its own data. That is a decision, not a step.
                raise StepFailed("ה־.env הוא עותק של .env.ex, וללשכה כבר יש נתונים "
                                 f"({volumes} volumes) — הסודות של התבנית כבר בשימוש",
                                 "צריך החלטה: לסובב כל סוד יחד עם השירות שלו, או למחוק את הנתונים "
                                 "ולהתקין מחדש. השלב לא ייצר סודות חדשים מעל נתונים קיימים.")
            # kept, not deleted: it is the template and nothing else, but a file is never thrown away here
            must(office["machine"], f"cd {p} && mv .env .env.installer-template.$(date +%Y%m%d%H%M%S)", 20,
                 "העברת עותק התבנית הצידה נכשלה")
            emit("ה־.env היה עותק של .env.ex שהמתקין העתיק — הועבר הצידה, ונוצר .env משל הלשכה")
            fresh = True
    if fresh and volumes:
        # no .env, but the databases and the vault are there (a deleted file on a machine that ran):
        # new passwords would be written over data initialised with the old ones
        raise StepFailed(f"אין ‎.env במחשב, אבל ללשכה כבר יש נתונים ({volumes} volumes)",
                         "שחזר את ה-.env מגיבוי. השלב לא ייצר סודות חדשים מעל נתונים קיימים.")
    if fresh:
        name = re.sub(r"[^a-z0-9]", "", office["id"].lower())[:20] or "office"
        must(office["machine"],
             f"cd {p} && OFFICE_DOMAIN={q(office['domain'])} CI_DEPLOYMENT_NAME={q(name)} "
             f"bash scripts/ci-env.sh", 300, "יצירת ה־.env נכשלה")
    b64 = base64.b64encode(ENV_MERGE.encode()).decode()
    # a vault key is minted only while there is no vault or database to lock — which also covers the
    # retry of a run that failed after ci-env.sh had written the file
    mint = 0 if volumes else 1
    # an office whose declared domain changed carries the one it had: the machine's .env is moved to the
    # new one only while it still names exactly that one (FPG-33)
    old = office.get("renamed_from") or ""
    rename = (f"DGO_RENAME_FROM={q(old)} DGO_RENAME_TO={q(office['domain'])} "
              if old and old != office["domain"] else "")
    out = must(office["machine"], f"cd {p} && echo {b64} | base64 -d | {rename}DGO_MINT={mint} python3 -", 60,
               "בדיקת ה־.env נכשלה")
    f = parse_facts(out)
    renamed = [k for k in (f.get("RENAMED") or "").split(",") if k]
    kept = [k for k in (f.get("EMAILS_KEPT") or "").split(",") if k]
    if renamed:
        emit(f"הדומיין הוחלף מ־{old} ל־{office['domain']} ב־{len(renamed)} מפתחות "
             f"(העותק הקודם נשמר במחשב כ־.env.before-rename-*)")
    if kept:
        emit("כתובות הכניסה של החשבונות נשארו על הדומיין הקודם (הן שמות המשתמש בתוך האפליקציות): " + ", ".join(kept))
    if f.get("DOMAIN") != office["domain"]:
        raise StepFailed(f"ה־.env על המחשב מוגדר לדומיין {f.get('DOMAIN')!r}, ההצהרה אומרת "
                         f"{office['domain']!r}" + (f" (והדומיין הקודם בהצהרה הוא {old!r})" if old else ""),
                         "תקן את הדומיין בהצהרה, או את DEPLOYMENT_DOMAIN ב־.env שעל המחשב.")
    if old:
        # the machine is on the declared domain: the previous one has nothing left to say, and a later
        # change starts from this one (the second reader)
        # …and the accounts' addresses are the `accounts` step's, after `run` (FPG-34) — recorded whenever
        # the machine is on the declared domain, not only when THIS run did the rename: a merge that
        # failed after its rename, or a converge cut short here, would otherwise strand them (the reader).
        # The verb is idempotent: with nothing left on the old domain it moves nothing.
        _forget_rename(office, addresses_from=old)
    added = [k for k in (f.get("ADDED") or "").split(",") if k]
    norm = [k for k in (f.get("NORMALIZED") or "").split(",") if k]
    minted = [k for k in (f.get("MINTED") or "").split(",") if k]
    if norm:
        emit("הומר לערך מפורש: " + ", ".join(norm) + f" = {office['domain']}")
    if minted:
        emit("סוד חדש נוצר במחשב (לא הודפס): " + ", ".join(minted))
    ctx["deployment_name"] = f.get("NAME")
    return {"summary": ("נוצר חדש · " if fresh else "קיים · ") +
                       (f"הדומיין הוחלף ב־{len(renamed)} מפתחות · " if renamed else "") +
                       (f"נוספו {len(added)} מפתחות חדשים" if added else "שלם"),
            "added": added, "minted": minted, "renamed": renamed, "emails_kept": kept}


def _forget_rename(office: dict, addresses_from: str = "") -> None:
    """The machine is on `office["domain"]` now: the record on disk says so. Read fresh, so an edit made
    while the converge ran is not written over. Its domain unchanged since: `renamed_from` goes. Changed
    meanwhile (o2 → o3 while the machine moved o1 → o2): the next rename starts from o2, where the machine
    is — not from o1, which would strand it (the third reader). Saved by the app's own writer.

    `addresses_from`: a domain the accounts' addresses may still be on, for the `accounts` step (FPG-34).
    A LIST: a second rename before the accounts moved leaves some on the first domain and, where an app
    moved meanwhile, some on the second — each is moved from (the reader)."""
    office.pop("renamed_from", None)
    import app as _app
    try:
        doc = _app.load(office["id"])
    except (OSError, yaml.YAMLError):
        return
    if not isinstance(doc, dict):
        return
    if "renamed_from" not in doc and doc.get("domain") == office["domain"] and not addresses_from:
        return
    if doc.get("domain") == office["domain"]:
        doc.pop("renamed_from", None)
    else:
        doc["renamed_from"] = office["domain"]
    if addresses_from and addresses_from != office["domain"]:
        have = _address_domains(doc)
        if addresses_from not in have:
            doc["addresses_from"] = have + [addresses_from]
    _app.save(doc)


def _address_domains(doc: dict) -> list[str]:
    """The record's `addresses_from` as a list (a record of the first FPG-34 build held one string)."""
    v = doc.get("addresses_from") or []
    return [v] if isinstance(v, str) else [d for d in v if isinstance(d, str) and d]


def rename_script(path_q: str, old: str, new: str) -> str:
    """The detached script the `accounts` step runs on the machine (start_detached puts `set -e` above it).

    `rc=0; … || rc=$?` and not `…; echo "RC=$?"`: under `set -e` the group exits at a failing bbox before
    its echo, the RC line was lost exactly when an app refused, and a refusal stopped the whole converge
    (the fifth reader). awk keeps the verdict pass (the first pass's «waiting» is expected and settled by
    the second) and the facts — RC, CHANGED — and the run holds a lock, so a run left going after a timeout
    and the next converge's never move addresses at once: the second says RC=busy and is tried again.
    The lock lives with the engine's other job locks (data/.locks/, gitignored), and bbox runs with fd 9
    CLOSED (`9>&-`): a dockerd it starts in the background would otherwise inherit the lock and hold it for
    as long as it runs — every later run «busy», with nothing saying why (the sixth reader). A lock this
    user cannot take (a data/.locks/ a root container made first; no `flock` on the machine) is skipped,
    never fatal — exactly as heavy_admit treats the same directory (the seventh reader)."""
    return (f"cd {path_q}\n"
            "L=data/.locks/rename-address.lock\n"
            "if command -v flock >/dev/null 2>&1 && mkdir -p data/.locks 2>/dev/null && touch \"$L\" 2>/dev/null; then\n"
            "  exec 9>>\"$L\"\n"
            "  if ! flock -n 9; then echo RC=busy; exit 0; fi\n"
            "fi\n"
            f"{{ rc=0; ./bbox rename-address {q(old)} {q(new)} 9>&- 2>&1 || rc=$?; echo \"RC=$rc\"; }} "
            "| awk '/rename-address: second pass/{p=1} p || /^RC=/ || /^CHANGED=/ || /rror/'\n")


def step_accounts(office: dict, ctx: dict, emit) -> dict:
    """The accounts follow the domain (FPG-34). The env step moved every HOST and left every ADDRESS
    (`admin@<old>`): it is the sign-in of an account n8n, Plane, GlitchTip and authentik already hold,
    and the platform signs in with it. Here, with the stack up, each app moves its own accounts and then
    its own keys — `bbox rename-address <old> <new>` on the machine, every enabled app that has the hook —
    and the vault's login is read again, so it names the address the account now has.

    Runs only while the record says addresses may still be behind (`addresses_from`, set by the env step),
    once per such domain, detached on the machine (two passes of every app's shell outlast one exec's
    limit). Then `run` again when something was really written (the verb's CHANGED=1) — the apps that moved
    took new keys even when another refused (connections signs in to n8n with N8N_OWNER_EMAIL, Plane's SSO map
    names its owner) — and a domain is forgotten only once its move was whole AND any such run succeeded. The
    vault's login is read again in every case.

    An app that REFUSED (the new address is someone else's) or was down is a warning, not a failure: the
    domain stays on the record and the next converge tries again, and `link`, `health` and `publish` still
    run — one conflict waiting for a person must not stop the office converging (the third reader). So is
    an office whose code has no such verb yet. The step fails only when the verb could not run at all, and
    the first such error is the one raised."""
    import app as _app
    pending = [d for d in _address_domains(_app.load(office["id"]) or {}) if d != office["domain"]]
    if not pending:
        return {"summary": "אין כתובות חשבונות להעביר"}
    p = q(office["path"])
    probe = exec_on(office["machine"], f"grep -q 'rename-address)' {p}/bbox", 20).get("code")
    if probe == 1:
        return {"summary": "הקוד של הלשכה עוד לא יודע להעביר את כתובות החשבונות — נשאר ברשומה",
                "warnings": ["הרץ את שלב code עם גרסה שיש בה את FPG-34; הכתובות יועברו בהרצה שאחריה"]}
    if probe != 0:
        raise StepFailed("לא ניתן לבדוק את קוד הלשכה במחשב", "ודא שהמחשב זמין ונסה את השלב שוב.")
    partial, done, changed, warnings, err = [], [], False, [], None
    try:
        for i, frm in enumerate(pending):
            name = f"accounts-{i}"
            start_detached(office, name, rename_script(p, frm, office["domain"]))
            facts = parse_facts(wait_detached(office, name, emit, limit=1800, every=10))
            changed = changed or facts.get("CHANGED") == "1"       # before the verdict: what was written stands
            if facts.get("RC") is None:
                raise StepFailed(f"הפקודה להעברת הכתובות לא סיימה במחשב (מ־@{frm})",
                                 "ודא שהמחשב זמין והלשכה שלמה, ונסה את השלב שוב.")
            (done if facts["RC"] == "0" else partial).append(frm)
    except StepFailed as e:
        err = e
    login = {"summary": "", "warnings": []}
    try:
        if changed:
            emit("── הפעלה מחדש, כדי שהאפליקציות יקבלו את הכתובות שעברו")
            step_run(office, ctx, emit)
        if done:
            # forgotten only once the containers took the moved keys (or nothing needed taking)
            doc = _app.load(office["id"]) or {}
            left = [d for d in _address_domains(doc) if d not in done]
            if left:
                doc["addresses_from"] = left
            else:
                doc.pop("addresses_from", None)
            _app.save(doc)
    except StepFailed as e:
        if err is None:
            err = e
        else:
            warnings.append(f"גם ההפעלה מחדש נכשלה: {e.reason}")
            emit(f"אזהרה: גם ההפעלה מחדש נכשלה: {e.reason}")
    finally:
        try:
            login = step_login(office, ctx, emit)
        except StepFailed as e:              # never hides the error this step is already raising
            login = {"summary": "", "warnings": [f"פרטי הכניסה לא רועננו: {e.reason}"]}
        for w in login.get("warnings") or []:
            emit(f"אזהרה: {w}")
        warnings += list(login.get("warnings") or [])
    if err is not None:
        raise err
    warnings += [f"לא כל הכתובות עברו מ־@{d} — נשאר ברשומה, וינוסה שוב בהרצה הבאה" for d in partial]
    return {"summary": (f"כתובות החשבונות עברו מ־@{', @'.join(done)} ל־@{office['domain']}" if done else
                        "כתובות החשבונות לא עברו במלואן") + (f" · נשאר לנסות: @{', @'.join(partial)}" if partial else ""),
            "login": login.get("summary"), "warnings": warnings}


STATE_SCRIPT = r"""
cd __PATH__
declare_state() { python3 platform/manager/reconcile.py set-state --app "$1" --state "$2" --by dgo-extend __CREATE__ >/dev/null 2>&1 || true; }
declared_sets() {
__SETS__
}
declared_sets
# The declaration is the WHOLE app set of this office, not "these and whatever the version enables".
# `code` checks out a commit whose platform.state.yaml is the HOME office's (that file is tracked, so
# it describes the home office). Without this pass a 2-core remote would inherit every app the home
# office runs — browser42, bina-ds, project-pln — which is a machine-size decision taken by a file
# nobody declared for it. Anything enabled on the machine and NOT named here is switched off.
undeclared_off() {
EXTRA=$(python3 - <<'PY'
import json, os, yaml
declared = set("__DECLARED__".split(","))
s = yaml.safe_load(open("platform.state.yaml")) or {}
apps = s.get("apps") or {}
on = [k for k, v in apps.items()
      if (v or {}).get("enabled") is True or (v or {}).get("state") == "enabled"]
def platform(app):
    # The platform itself is never "undeclared": `platform-base/` is layers 1-2, what every office gets
    # (AGENTS.md), and an app's manifest may also say `system: true` or layer 0/1. Such an app stays on
    # whatever a declaration leaves out; switching one off is a declaration's explicit `disabled`. A
    # declaration that named only the business apps switched off traefik, authentik, postgres, redis,
    # console and connections on fireplace (2026-10-22, "7 enabled · 15 switched off"), and the
    # compiler then refused to render.
    if os.path.isfile(os.path.join("platform-base", app, "app.json")):
        return True
    p = os.path.join("apps", app, "app.json")
    if not os.path.isfile(p):
        return False
    try:
        m = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return True                              # unreadable: keep it on, never guess it off
    return bool(m.get("system")) or m.get("layer") in (0, 1)
print(",".join(sorted(k for k in on if k not in declared and not platform(k))))
PY
)
# COMMA-separated on purpose (the OFF= line below is one fact, not a list of shell words), so the
# split here is explicit: a loop over `$EXTRA` as words would pass the whole list as ONE app id and
# append a junk entry (`a,b,c: {…}`) to platform.state.yaml — measured on the first run of this step
# on 2026-09-29, which left the machine's state file unparseable and every later step failing.
for a in $(printf '%s' "$EXTRA" | tr ',' ' '); do
  [ -n "$a" ] && declare_state "$a" disabled
done
}
undeclared_off
echo "OFF=$EXTRA"

# An app the declaration switches off has to actually STOP. Writing the disposition is not the same
# fact as the container being gone: chat stayed up on vps1 for an hour after being declared off,
# still holding memory on a 2-core box and still answering on its own host (measured 2026-09-30).
# Only the app's OWN services are touched — `reconcile services` returns the dependency CLOSURE, and
# stopping that would take postgres, redis and authentik down with the app.
#
# ...and only THIS OFFICE'S containers. A compose service name is not unique on an engine: a machine
# that already runs another stack (the WB Corp VPS carries the old layout of this same repo, whose
# services are also called n8n / ollama / portainer / redisinsight) would have had its production
# containers stopped by an office that merely declares those apps off. Found by reading this script
# before its first run there, 2026-10-05 — the working-directory label is what ties a container to
# the checkout this step is running in.
HERE="$(pwd)"; HERE_P="$(pwd -P)"
stop_app() {
  for s in $(python3 platform/manager/reconcile.py compose-services --app "$1" 2>/dev/null); do
    ids=$( { docker ps -q --filter "label=com.docker.compose.service=$s" --filter "label=com.docker.compose.project.working_dir=$HERE" 2>/dev/null;
             docker ps -q --filter "label=com.docker.compose.service=$s" --filter "label=com.docker.compose.project.working_dir=$HERE_P" 2>/dev/null; } | sort -u | tr '\n' ' ')
    if [ -n "$ids" ]; then docker stop $ids >/dev/null 2>&1 && echo "STOPPED=$1 $s"; fi
  done
}
for a in $(printf '%s' "__OFF_DECLARED__" | tr ',' ' '); do [ -n "$a" ] && stop_app "$a"; done
for a in $(printf '%s' "$EXTRA" | tr ',' ' '); do [ -n "$a" ] && stop_app "$a"; done
# The file this step writes is what every later step READS. A state file that does not parse is a
# machine that cannot converge again, so it is checked here and restored from the checkout if the
# write went wrong — then the declaration is re-applied on top of the restored copy.
if ! python3 -c "import yaml;yaml.safe_load(open('platform.state.yaml'))" 2>/dev/null; then
  echo "STATE_REPAIRED=1"
  cp -p platform.state.yaml "platform.state.yaml.bak-unreadable-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
  git checkout -- platform.state.yaml
  declared_sets
  # ...and the WHOLE declaration, not half of it: the restored copy is the tracked one, which enables
  # every app the home office runs. Re-applying only the named apps left the rest at those defaults —
  # measured 2026-10-02 on vps1: "31 apps enabled" after a repair, browser42 and project-pln among
  # them, on a machine whose declaration names 22.
  undeclared_off
  echo "OFF=$EXTRA"
  for a in $(printf '%s' "$EXTRA" | tr ',' ' '); do [ -n "$a" ] && stop_app "$a"; done
fi
python3 - <<'PY'
import yaml
s = yaml.safe_load(open("platform.state.yaml")) or {}
apps = s.get("apps") or {}
on = sorted(k for k, v in apps.items()
            if (v or {}).get("enabled") is True or (v or {}).get("state") == "enabled")
print("ON=" + ",".join(on))
PY
__SERVE__
"""


def _serve_b64(office: dict, emit) -> str:
    """The peer's `serve:` block, base64-encoded for the state step's script, and what it means.

    Empty is a legitimate answer and the common one: it is what a `use` link renders, and what
    removes a block a previous converge wrote.
    """
    try:
        home = home_office()
    except StepFailed as e:
        emit(f"אזהרה: לא ניתן לרנדר את רשימת המוגשות ({e})")
        return ""
    block = _serve_block(office, home)
    if block:
        shown = ", ".join(f"{a['alias']} ({e['address']}:{a['port']})"
                          for e in block for a in e["apps"])
        emit(f"מוגשות ללשכה {office['id']}: {shown}")
    return base64.b64encode(json.dumps(block, ensure_ascii=False).encode()).decode()


def step_state(office: dict, ctx: dict, emit) -> dict:
    """Write the DECLARED disposition of every app, and switch off whatever the version enabled
    behind the owner's back (see STATE_SCRIPT). Idempotent: the same declaration rewrites the same
    file.

    It also writes the `serve:` block this office's own `serve:` list means for that peer — the apps
    of THIS office the peer is allowed to show, which layer 0 there turns into a route, a tile and an
    identity provider. Written here because this is the step that owns that file, and removed here
    when the link or the `serve:` entry is gone: a door nobody declares must not outlive the
    declaration that opened it."""
    apps = office.get("apps") or {}
    if not apps:
        return {"summary": "ברירת המחדל של הגרסה"}
    declared = sorted(apps)
    declared_off = [a for a, d in sorted(apps.items()) if d not in (True, "enabled")]
    sets = "\n".join(
        f"declare_state {q(app_id)} {'enabled' if disp in (True, 'enabled') else 'disabled'}"
        for app_id, disp in sorted(apps.items()))
    # The writer is INSERTED, not merely pointed at: `__SERVE__` inside `SERVE_WRITER` is its own
    # placeholder for the block, and the first version of this shipped the base64 blob as a bare
    # line of the script — bash ran it as a command, printed `command not found` into a log nobody
    # reads, and the peer's `serve:` block was silently never written (measured 2026-10-01: the state
    # step reported nothing and vps1's file had no block, on a link whose every other half was live).
    script = (STATE_SCRIPT.replace("__PATH__", q(office["path"]))
              .replace("__SETS__", sets)
              .replace("__CREATE__", "--create")
              .replace("__DECLARED__", ",".join(declared))
              .replace("__OFF_DECLARED__", ",".join(declared_off))
              .replace("__SERVE__", SERVE_WRITER.replace("__SERVE__", _serve_b64(office, emit))))
    b64 = base64.b64encode(script.encode()).decode()
    out = must(office["machine"], f"echo {b64} | base64 -d | bash", 300,
               "כתיבת מצב האפליקציות נכשלה")
    f = parse_facts(out)
    on = [a for a in (f.get("ON") or "").split(",") if a]
    off = [a for a in (f.get("OFF") or "").split(",") if a]
    stopped = [ln.split("=", 1)[1].strip() for ln in out.splitlines() if ln.startswith("STOPPED=")]
    warn_repaired = ""
    if f.get("STATE_REPAIRED"):
        warn_repaired = "platform.state.yaml לא היה קריא — שוחזר מהמאגר והוצהר מחדש"
    ctx["enabled"] = on
    if off:
        emit("כובו (לא הוצהרו ללשכה הזו): " + ", ".join(off))
    # Only a DECLARED-ENABLED app that failed to appear is worth a warning. A declared-DISABLED app is
    # not "missing" — and reporting `chat` as unknown on a version that ships it was this step calling
    # its own declaration a mistake (measured on vps1 2026-09-30, where it kept the step at warn while
    # everything it did was correct).
    missing = [a for a in declared if apps.get(a) in (True, "enabled") and a not in on]
    warn = [warn_repaired] if warn_repaired else []
    if missing:
        warn.append("אפליקציות מוצהרות שאינן מוכרות בגרסה הזו: " + ", ".join(missing))
    if stopped:
        emit("הופסקו קונטיינרים: " + ", ".join(stopped))
    served = (f.get("SERVE") or "").strip()
    if served:
        emit(f"ב-state של הלשכה המרוחקת: serve = {served}")
    return {"summary": f"{len(on)} אפליקציות מופעלות" + (f" · {len(off)} כובו" if off else "")
                       + (f" · {len(stopped)} קונטיינרים הופסקו" if stopped else ""),
            "enabled": on, "disabled_undeclared": off, "stopped": stopped, "warnings": warn,
            "serve": served}


def step_run(office: dict, ctx: dict, emit) -> dict:
    # Headroom for a small remote machine, the same knob onboarding, baseline and CI already export
    # (`bbox`'s own comment). Measured 2026-10-01 on vps1 (2 cores): a recreated authentik bootstrap
    # needs ~6–8 minutes, so the 300 s default failed the step — and skipped `link` and `health` —
    # over a stack that came up whole two minutes later. The office's own value still wins.
    # A declaration that goes back ON PURPOSE (source.allow_rollback) says so to the machine's own
    # ledger too; otherwise dcx refuses every build of the older tree the code step just checked out
    # (DGO-1016, G90), and the office would be left with a checkout that is not what runs.
    back = "BBOX_ALLOW_ROLLBACK=1 " if (office.get("source") or {}).get("allow_rollback") else ""
    start_detached(office, "run",
                   f"cd {q(office['path'])}\n{back}BBOX_WAIT_TIMEOUT=${{BBOX_WAIT_TIMEOUT:-900}} ./bbox run\n")
    wait_detached(office, "run", emit, limit=3 * 3600, every=15)
    # `bbox run`'s exit code is not the answer. A failing `docker compose up` (an image it cannot
    # pull, a name conflict, a port already taken) is printed and the CLI still finishes 0, so this
    # step reported a green "bbox run הסתיים בהצלחה" over a stack that was only half brought up —
    # measured 2026-09-29, where an unpullable image left the office's console answering 502 while
    # this step said ok. Docker's own failures are greppable, and they are read from the WHOLE log
    # rather than from the last poll's tail.
    d = ctl_dir(office)
    bad = exec_on(office["machine"],
                  f"grep -aE 'Error response from daemon|docker: Error|failed to solve|"
                  f"ERROR: for |is already in use by container|deploy: REFUSED' {d}/run.log 2>/dev/null"
                  f" | head -8", 60)
    fails = [ln.strip() for ln in (bad.get("stdout") or "").splitlines() if ln.strip()]
    if any("deploy: REFUSED" in ln for ln in fails):
        raise StepFailed("הבנייה נדחתה: הקוד על המחשב לא מכיל את מה שהלשכה כבר מריצה, ושום שירות לא הוחלף",
                         "העבר את ההצהרה לגרסה שמכילה את שניהם, או סמן במפורש 'לחזור לגרסה ישנה' "
                         "(source.allow_rollback).", "\n".join(fails)[-1500:])
    if fails:
        raise StepFailed("ההרצה נעצרה על שגיאת Docker — הלשכה לא הורמה במלואה",
                         "השגיאות למטה. תקן את ההצהרה (למשל אפליקציה שאי אפשר להרים במכונה הזו) והרץ שוב.",
                         "\n".join(fails)[-1500:])
    return {"summary": "bbox run הסתיים בהצלחה"}


HEALTH = r"""
docker ps --format '{{.Names}}|{{.Status}}' > /tmp/.dgo-extend-ps 2>/dev/null || true
echo "total=$(wc -l < /tmp/.dgo-extend-ps)"
echo "healthy=$(grep -c '(healthy)' /tmp/.dgo-extend-ps)"
echo "unhealthy=$(grep -c 'unhealthy' /tmp/.dgo-extend-ps)"
echo "restarting=$(grep -c 'Restarting' /tmp/.dgo-extend-ps)"
echo "bad=$(grep -E 'unhealthy|Restarting' /tmp/.dgo-extend-ps | cut -d'|' -f1 | tr '\n' ' ')"
# the office's compose project as compose reads it: the containers above can all be healthy while every
# `dc` fails (rel10 on fireplace: one app's manifest named no compose file), and then nothing can be run,
# rebuilt or onboarded. Stderr is kept in memory (a fixed file in /tmp is another user's, or stale), and
# the line kept is compose's — or dc's own error — never compose's warnings or bbox's notices. It must
# never carry a value: an env file it cannot parse is named by file and line only, and any quoted text
# holding `=` is blanked (compose quotes a malformed `.env` line whole). A valid project with NO services
# is compose reading nothing at all (no compiled files) — said too.
if cerr="$(./scripts/dc config -q 2>&1 >/dev/null)"; then
  # empty only when compose ANSWERED with no services — a second call that failed (an .env being
  # rewritten between the two) is not "no compiled files"
  if svcs="$(./scripts/dc config --services 2>/dev/null)"; then
    if [ -n "$(printf '%s' "$svcs" | tr -d '[:space:]')" ]; then echo "compose=ok"; else echo "compose=empty"; fi
  else echo "compose=ok"; fi
else
  echo "compose=invalid"
  line="$(printf '%s\n' "$cerr" | awk '!/^time=/ && !(/^\[bbox\] / && !/^\[bbox\] error/) && NF { print; exit }')"
  case "$line" in   # a file compose could not parse — «failed to read|load X: line N: …» — by file and line only
    *": line "[0-9]*) line="$(printf '%s' "$line" | sed -E 's/^(.*): line ([0-9]+).*$/\1: line \2 — malformed/')" ;;
  esac
  echo "compose_error=$(printf '%s' "$line" | sed -E 's/(unterminated quoted value).*/\1 …/; s/"[^"]*=[^"]*"?/"…"/g' | cut -c1-200)"
fi
"""


def hosts_command() -> str:
    """The command that lists every host this machine publishes, from the labels the containers carry.

    Assembled HERE, with the python program base64-encoded, because the alternative is a string that
    is simultaneously a shell command, a python program and a regex — and hand-escaping that sandwich
    is what produced two broken versions of it (a literal backtick ended the remote shell's parsing,
    and an over-escaped backslash produced a regex that matched nothing, which reads exactly like
    "no hosts to check").

    The hosts come from `traefik.http.routers.*.rule` labels, i.e. the routers that EXIST, so this
    cannot drift from what the edge routes. `.localhost` names are excluded: the question is what the
    outside world can reach.
    """
    inner = "\n".join([
        "import json,sys,re",
        "hosts=set()",
        "for line in sys.stdin:",
        "    try: labels=json.loads(line)",
        "    except ValueError: continue",
        "    for k,v in (labels or {}).items():",
        "        if not k.startswith('traefik.http.routers') or not k.endswith('.rule'): continue",
        "        for h in re.findall(r'Host\\(([^()]+)\\)', v or ''):",
        "            h = h.strip().strip(chr(96))",
        "            if h and not h.endswith('.localhost'): hosts.add(h)",
        "print('HOSTS=' + ','.join(sorted(hosts)))",
    ])
    b64 = base64.b64encode(inner.encode()).decode()
    return ("docker inspect $(docker ps -q) --format '{{json .Config.Labels}}' 2>/dev/null | "
            f"python3 -c \"import base64;exec(base64.b64decode('{b64}').decode())\"")



def step_health(office: dict, ctx: dict, emit) -> dict:
    p = q(office["path"])
    f = parse_facts(must(office["machine"], f"cd {p} && echo head=$(git rev-parse HEAD)\n" + HEALTH,
                         60, "בדיקת הבריאות נכשלה"))
    ctx["health"] = f
    url = f"https://console.{office['domain']}/"
    code = None
    try:
        req = urllib.request.Request(url, method="GET")
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=20) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        code = f"{type(e).__name__}"
    ok_edge = code in (200, 301, 302, 303, 307, 308)
    commit = (office.get("source") or {}).get("commit") or ""
    warn = []

    # ── every host this office publishes ─────────────────────────────────────────────────────────
    # Measured for the owner's sake: a route that exists but answers 000/404 is an app nobody can
    # open, and "the office is healthy" must not be said while one of them is dark. The hosts come
    # from the containers' own labels (see HOSTS), so this cannot drift from what traefik routes.
    #
    # A 404 is not one fact. Three different things answer 404 on this estate (measured on vps1,
    # 2026-09-30, and each one was read out of the traefik access log or the response body):
    #   * the IDENTITY layer, for a host no provider knows (`alerts-svc`, `apitools` — routers
    #     `enabled`, containers healthy, permanently dark) — a REAL fault, and the reason this
    #     probe exists;
    #   * the APP itself, for a host whose root path simply has no page (supabase's kong answers a
    #     bare 404 for `/`) — reachable, not a fault;
    #   * the edge's own dashboard when the deployment declares it off (`TRAEFIK_API_DASHBOARD=false`
    #     is what `.env.ex` ships for production) — off BY DECLARATION.
    # Only the first is dead. The other two are named, so this line stays a measurement instead of
    # a green light that hides one of them.
    try:
        declared_hosts = [h for h in (parse_facts(must(office["machine"], hosts_command(), 90)).get("HOSTS") or "").split(",") if h]
    except StepFailed:
        declared_hosts = []
    dash_host, dash_on = _edge_dashboard(office)
    dead, http_only, app_answered, off_by_declaration = [], [], [], []
    for host in declared_hosts:
        if dash_host and host == dash_host and not dash_on:
            off_by_declaration.append(host)
            continue
        hcode, origin = _probe_host(host)
        if isinstance(hcode, int) and hcode < 400:
            continue
        if isinstance(hcode, int) and origin == "app":
            app_answered.append(f"{host} ({hcode})")     # the app's own answer, not a dark route
            continue
        hcode_http, horigin = _probe_http(host)
        if isinstance(hcode_http, int) and (hcode_http < 400 or horigin == "app"):
            http_only.append(f"{host} ({hcode_http} על http"
                             + ("" if hcode_http < 400 else ", מהאפליקציה") + ")")
            continue
        dead.append(f"{host} → {hcode}"
                    + (" (נדחה בשכבת הזהות)" if origin == "identity" else ""))
    if dead:
        warn.append("כתובות שאינן עונות: " + ", ".join(dead))
    # NOTES, not warnings: `warnings` is what makes this step `warn`, and a line that is true every
    # single converge ("the dashboard is off", "mail answers on http only") is a line whose reader
    # learns to ignore the step entirely — the same lesson as `login` warning about its own 409
    # (DGO-6, 2026-09-30). A warning here means something is WRONG; these say what was measured.
    notes = []
    if app_answered:
        notes.append("האפליקציה עצמה ענתה 4xx בשער שלה: " + ", ".join(app_answered))
    if http_only:
        notes.append("עונה רק ב-http (אין ראוטר TLS בתוויות האפליקציה): " + ", ".join(http_only))
    if off_by_declaration:
        notes.append("כבויה בהצהרה (TRAEFIK_API_DASHBOARD): " + ", ".join(off_by_declaration))
    ctx["hosts"] = {"declared": declared_hosts, "dead": dead, "http_only": http_only,
                    "app_answered": app_answered, "off_by_declaration": off_by_declaration}
    if f.get("unhealthy") not in ("0", None) or f.get("restarting") not in ("0", None):
        warn.append(f"קונטיינרים לא בריאים: {f.get('bad')}")
    cerr = f.get("compose_error") or ""
    if f.get("compose") == "invalid" and cerr.startswith(("dc:", "[bbox] error")):
        raise StepFailed("dc במכונה מסרב לרוץ — כל פקודת dc נכשלת",
                         "הקונטיינרים שרצים ממשיכים. השורה אומרת מה חסר במכונה (‎.env, ‏compose); "
                         "אם צעד אחר כותב את ‎.env ברגע זה — הרץ שוב בעוד דקה.", cerr)
    if f.get("compose") == "invalid":
        raise StepFailed("פרויקט ה־compose של הלשכה אינו תקין — כל פקודת dc במכונה נכשלת",
                         "הקונטיינרים שרצים ממשיכים, אבל אי אפשר להריץ, לבנות או להפעיל דבר עד שיתוקן. "
                         "תקן את ההצהרה שהשורה הזו מונה, ושחרר גרסה.", cerr)
    if f.get("compose") == "empty":
        raise StepFailed("פרויקט ה־compose של הלשכה ריק — dc אינו רואה אף שירות",
                         "הקבצים המהודרים חסרים (‎.generated); ‏`./bbox run` מהדר אותם מחדש.")
    if not f.get("head", "").startswith(commit[:7]):
        raise StepFailed("הגרסה שרצה אינה הגרסה המוצהרת", "הרץ שוב.")
    if not ok_edge:
        raise StepFailed(f"{url} אינו עונה ({code})",
                         "בדוק את ה־DNS ואת התעודה; traefik מנפיק תעודה בדקות הראשונות.")
    expected = len(declared_hosts) - len(off_by_declaration)
    answering = expected - len(dead)
    hosts_line = (f" · {answering}/{expected} כתובות עונות"
                  + (f" ({len(http_only)} רק ב-http · {len(app_answered)} 4xx מהאפליקציה"
                     + (f" · {len(off_by_declaration)} כבויה בהצהרה" if off_by_declaration else "")
                     + ")" if (http_only or app_answered or off_by_declaration) else "")
                  if declared_hosts else "")
    return {"summary": f"{f.get('healthy')}/{f.get('total')} בריאים · console עונה {code}" + hosts_line,
            "containers": f, "warnings": warn, "notes": notes, "edge": code,
            # the same facts as data, for a reader that is not this screen (the watch's weekly report
            # is written in the client's language from these — never from the Hebrew sentences above)
            "dead_hosts": [d.split(" → ")[0] for d in dead], "answering": answering if declared_hosts else None,
            "expected": expected if declared_hosts else None}


def _probe_http(host: str, timeout: int = 10):
    """(status, origin) for the plain-HTTP twin, for hosts whose app carries only a `web` router.

    Reported as a distinct state — "answers, but not over TLS" — because that is a real gap in that
    app's routing and calling it dark would be as wrong as calling it fine. A 4xx that the APP
    served counts as an answer here for the same reason it does over TLS: an API host (kong's
    `supabase.<domain>`) answers its own 404 at `/`, which says the address is served and has no
    root page — not that the office is broken. The code is printed either way.
    """
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://{host}/", method="GET"),
                                    timeout=timeout) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4096)
        except Exception:
            body = b""
        return e.code, _refusal_origin(body)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return _no_answer(e), ""


def _probe_host(host: str, timeout: int = 12):
    """(status, origin) for one HTTPS GET, following nothing. 2xx/3xx/401/403 mean "the route is
    alive and the app is behind it" (302 is the SSO gate, the normal answer for a gated app). A 4xx
    is returned with its ORIGIN, because a 404 here has three sources and they are three different
    facts — the identity layer refusing a host (dead), traefik matching no router at all (dead),
    and the app itself answering for a path it has no page for (alive). `origin` is "" for a
    non-error status."""
    ctx_ssl = ssl.create_default_context()
    ctx_ssl.check_hostname = False
    ctx_ssl.verify_mode = ssl.CERT_NONE          # the certificate is traefik's business, not this probe's
    try:
        req = urllib.request.Request(f"https://{host}/", method="GET")
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx_ssl), _NoRedirect)
        with opener.open(req, timeout=timeout) as r:
            return r.status, False
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4096)
        except Exception:
            body = b""
        return e.code, _refusal_origin(body)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return _no_answer(e), ""


def _no_answer(e: Exception) -> str:
    """WHY a published host gave no HTTP answer at all, as the health line prints it. A name with no
    DNS record, a port nothing listens on and a host that never replied are three different errands
    (a record to add, a router to fix, a machine to wake) — and all three used to be printed as the
    name of the exception class, `URLError`, which is none of them."""
    cause = getattr(e, "reason", e)
    if isinstance(cause, socket.gaierror):
        return "השם לא נפתר ב-DNS"
    if isinstance(cause, ConnectionRefusedError):
        return "החיבור נדחה"
    if isinstance(cause, TimeoutError):
        return "לא ענה בזמן"
    return type(cause).__name__


def _refusal_origin(body: bytes) -> str:
    """Who refused: "identity", "edge" or "app".

    Three 404s that look identical from the outside and mean three different things:
      * the outpost's refusal carries authentik's own page (`<title>authentik</title>` with
        `404 page not found`) — no application on this estate serves that, and the host is dark;
      * traefik matching no router answers the bare `404 page not found` (traefik's, in plain text);
      * anything else is the APP answering for a path it has no page for (kong's API root is a JSON
        `no Route matched`), which is a live host.

    Matched on the body, because the outpost sits behind traefik: by the time the response arrives
    the three carry the same headers.
    """
    low = body[:4096].strip().lower()
    if b"authentik" in low and b"404 page not found" in low:
        return "identity"
    if not low or low.startswith(b"404 page not found"):
        return "edge"
    return "app"


def _edge_dashboard(office: dict):
    """(host, is_on) of the edge's OWN dashboard, read from the machine's .env.

    A dashboard the deployment declares off answers 404 BY DESIGN, and reporting that as a dark
    address is how a probe teaches its reader to ignore it. The value may still be composed
    (`traefik.${DEPLOYMENT_DOMAIN}`) when a machine's .env has not been through the env step, so
    `DEPLOYMENT_DOMAIN` is read beside it and substituted.
    """
    p = q(office["path"])
    try:
        out = must(office["machine"],
                   f"cd {p} && grep -E '^TRAEFIK_API_(BASE_URL|DASHBOARD)=|^DEPLOYMENT_DOMAIN=' .env",
                   30).strip()
    except StepFailed:
        return "", False
    raw = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        raw[k.strip()] = v.split("#")[0].strip()
    domain = raw.get("DEPLOYMENT_DOMAIN", "")
    host_val = raw.get("TRAEFIK_API_BASE_URL", "")
    host_val = re.sub(r"\$\{DEPLOYMENT_DOMAIN(?::-[^}]*)?\}", domain, host_val)
    on = raw.get("TRAEFIK_API_DASHBOARD", "").lower() in ("true", "1", "yes")
    return host_val.split(":")[0].strip(), on


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None



# ── publish: an app that runs THERE and is shown HERE ───────────────────────────
# See apps/dgo-extend/peers.py for the model. This step is the half that touches machines:
#
#   remote edge   one router per placed app on peer.<office domain>, requiring the office's token
#                 header, its backend read from the REMOTE office's own compiled registry (so the
#                 service URL is the one that office actually routes to, not a guess made here)
#   home office   the app is switched OFF in platform.state.yaml (the declaration owns the whole
#                 app set — see step_state), its local containers stopped, and one file written into
#                 the console's peer registry, which is what puts the tile back in the rail
#
# What it deliberately does NOT do: touch the app's own host or its SSO. A placed app is still a
# normal app of its own office, reachable there exactly as before; the peer host is an ADDITIONAL
# door, opened only for a caller that carries the token.
PEER_CONFIG = "platform-base/traefik/config/dgo-extend-peer.yaml"


def _peer_rules(office: dict, entries: list[dict], token: str) -> str:
    """The remote traefik file provider document, rendered from the placements."""
    host = f"{peers.PEER_HOST}.{office['domain']}"
    routers, services, middlewares = {}, {}, {}
    for e in entries:
        n = f"dgo-extend-peer-{e['alias']}"
        routers[n] = {
            # The token is part of the RULE: a request without the header matches no router at all,
            # so the host answers 404 and no new service has to exist to say no.
            "rule": f"Host(`{host}`) && Header(`X-Office-Peer`, `{token}`) && "
                    f"PathPrefix(`/{e['alias']}`)",
            "entryPoints": ["websecure"],
            "service": n,
            "middlewares": [f"{n}-strip"],
            "tls": {"certResolver": "myresolver"},
        }
        middlewares[f"{n}-strip"] = {"stripPrefix": {"prefixes": [f"/{e['alias']}"]}}
        services[n] = {"loadBalancer": {"servers": [{"url": e["url"]}]}}
    doc = {"http": {"routers": routers, "middlewares": middlewares, "services": services}}
    return ("# GENERATED by the dgo-extend app of the home office — DO NOT EDIT.\n"
            "# One router per app that runs on this office and is shown at home; each requires the\n"
            "# office's peer token, which only the home office holds. Deleting this file closes the\n"
            "# door; the next converge writes it again.\n"
            + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False))


def _remote_registry(office: dict) -> tuple[list, dict]:
    """The remote office's compiled console registry: its tiles and its backends."""
    p = q(office["path"])
    out = must(office["machine"],
               f"cat {p}/.generated/registry/console.modules.yaml 2>/dev/null; echo '@@BASES@@'; "
               f"cat {p}/.generated/registry/console.app_bases.json 2>/dev/null", 60,
               "לא ניתן לקרוא את רישום האפליקציות של הלשכה המרוחקת")
    mods_txt, _, bases_txt = out.partition("@@BASES@@")
    try:
        mods = yaml.safe_load(mods_txt) or []
        bases = json.loads(bases_txt or "{}")
    except (yaml.YAMLError, ValueError) as e:
        raise StepFailed("רישום האפליקציות של הלשכה המרוחקת אינו קריא",
                         "הרץ converge שוב — הוא נכתב בשלב ההרצה.", f"{type(e).__name__}: {e}")
    return mods, bases


def _local(command: str, timeout: int = 120, what: str = "") -> str:
    """Run a command on the machine that runs THIS office (a converge repairs the home side too)."""
    if not HOME_REPO:
        raise StepFailed("DGO_HOME_REPO אינו מוגדר", "bbox מגדיר אותו; הרץ מחדש בלשכה.")
    return must(LOCAL_MACHINE, f"cd {q(HOME_REPO)} && {command}", timeout, what)


LOGIN_KEYS = ("AUTHENTIK_BOOTSTRAP_EMAIL", "AUTHENTIK_BOOTSTRAP_PASSWORD",
              "N8N_OWNER_EMAIL", "N8N_OWNER_PASSWORD")


def step_login(office: dict, ctx: dict, emit) -> dict:
    """Capture the REMOTE office's own login facts, into THIS office's credential plane.

    The owner's acceptance for a deployed office is not "the containers are up" — it is "I can log in
    and use it". The account that opens `console.<domain>` is the one the deployment itself created,
    and it lives in that machine's `.env`, which is exactly where nobody looks a week later.

    So it is moved to the one place secrets belong here: an instance in the credential plane
    (`dgo_login-<office>`), revealed from the app's own screen like every other secret. What is NOT
    done: printing it into the run log or keeping it in the step's result — a converge log is read by
    anyone debugging, and a password in it is a password in every copy of that log.
    """
    p = q(office["path"])
    keys = " ".join(LOGIN_KEYS)
    out = must(office["machine"],
               f"cd {p} && for k in {keys}; do grep -m1 \"^$k=\" .env || true; done", 60,
               "לא ניתן לקרוא את פרטי הכניסה מהמכונה")
    vals = parse_facts(out)
    email = vals.get("N8N_OWNER_EMAIL") or vals.get("AUTHENTIK_BOOTSTRAP_EMAIL") or ""
    password = vals.get("N8N_OWNER_PASSWORD") or vals.get("AUTHENTIK_BOOTSTRAP_PASSWORD") or ""
    if not email or not password:
        return {"summary": "לא נמצאו פרטי כניסה ב-.env של הלשכה",
                "warnings": ["אין חשבון בעלים או מנהל authentik ב-.env של הלשכה המרוחקת"]}
    iid = f"dgo_login-{office['id']}"
    secret = {"url": f"https://console.{office['domain']}/", "email": email, "password": password,
              "admin_email": vals.get("AUTHENTIK_BOOTSTRAP_EMAIL") or "",
              "admin_password": vals.get("AUTHENTIK_BOOTSTRAP_PASSWORD") or ""}

    def _vault(method: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(f"{CONNECTIONS_URL}{path}", data=json.dumps(payload).encode(),
                                     method=method, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")

    create = {"id": iid, "protocol": "dgo_login",
              "label": f"כניסה ללשכה {office.get('label') or office['id']}",
              "account_hint": f"{email} @ console.{office['domain']}", "secret": secret}
    try:
        _vault("POST", "/api/instances", create)
    except urllib.error.HTTPError as e:
        if e.code != 409:
            return {"summary": "שמירת פרטי הכניסה נכשלה",
                    "warnings": [f"כספת האישורים השיבה {e.code}"]}
        # 409 = the instance is already there, which is the NORMAL state from the second converge
        # on. It used to be reported as "שמירת פרטי הכניסה נכשלה" on every single converge — a step
        # that always warns is a step whose reader learns to ignore it, and this is the value the
        # owner reads to get back IN. A re-deployed office can also have a new bootstrap password,
        # so the secret is UPDATED (the vault merges; protocol/label/created_at are not movable).
        try:
            _vault("PUT", f"/api/instances/{iid}/secret", {"secret": secret})
        except urllib.error.HTTPError as e2:
            return {"summary": "עדכון פרטי הכניסה נכשל",
                    "warnings": [f"כספת האישורים השיבה {e2.code} על עדכון"]}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e2:
            log.warning("vault secret update: %r", e2)
            return {"summary": "עדכון פרטי הכניסה נכשל",
                    "warnings": ["כספת האישורים לא ענתה, או ענתה תשובה שאינה קריאה"]}
        return {"summary": f"פרטי הכניסה עודכנו בכספת: {email} @ console.{office['domain']}",
                "instance": iid}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        log.warning("vault secret save: %r", e)
        return {"summary": "שמירת פרטי הכניסה נכשלה",
                "warnings": ["כספת האישורים לא ענתה, או ענתה תשובה שאינה קריאה"]}
    return {"summary": f"פרטי הכניסה נשמרו בכספת: {email} @ console.{office['domain']}",
            "instance": iid}


def step_publish(office: dict, ctx: dict, emit) -> dict:
    oid = office["id"]
    placement = [a for a in (office.get("placement") or []) if a]
    if not placement:
        gone = peers.clear_office(oid, set())
        cleared = exec_on(office["machine"],
                          f"rm -f {q(office['path'])}/{PEER_CONFIG} && echo removed", 30)
        return {"summary": "אין אפליקציות מוצהרות ללשכה הזו" +
                           (f" · הוסרו {len(gone)}" if gone else ""),
                "removed": gone, "remote": "removed" if cleared.get("code") == 0 else "absent"}

    modules, bases = _remote_registry(office)
    token = peers.token_for(oid)
    entries, published = [], []
    for app_id in placement:
        m = next((x for x in modules if (x or {}).get("id") == app_id), None)
        if not m:
            raise StepFailed(f"„{app_id}” אינה מוּפצת בלשכה המרוחקת",
                             "היא מוצהרת כ־placement אבל אינה מופעלת שם. הוסף אותה לרשימת "
                             "האפליקציות של הלשכה והרץ שוב.")
        alias = (m.get("embed") or "").strip("/").split("/")[-1]
        base = ((bases.get(alias) or {}).get("default") or "").strip()
        if not alias or not base:
            raise StepFailed(f"ל„{app_id}” אין כתובת פנימית בלשכה המרוחקת",
                             "האפליקציה צריכה להצהיר routing[].module.url כדי שאפשר יהיה לנתב אליה.")
        entries.append({"alias": alias, "url": base})
        published.append({"app": app_id, "alias": alias, "url": base,
                          "peer": peers.peer_url(office, alias)})

    # ── 1. the door on the remote edge ────────────────────────────────────────────
    doc = _peer_rules(office, entries, token)
    b64 = base64.b64encode(doc.encode()).decode()
    p = q(office["path"])
    must(office["machine"],
         f"set -e; echo {b64} | base64 -d > /tmp/dgo-extend-peer.yaml; "
         f"python3 -c \"import yaml;yaml.safe_load(open('/tmp/dgo-extend-peer.yaml'))\"; "
         f"mkdir -p {p}/platform-base/traefik/config; "
         f"mv /tmp/dgo-extend-peer.yaml {p}/{PEER_CONFIG}; echo written",
         90, "כתיבת ראוטר ה־peer בלשכה המרוחקת נכשלה")
    emit(f"נכתב {PEER_CONFIG} עם {len(entries)} ראוטרים")

    # ── 2. the app is switched off HERE (the declaration owns the app set) ────────
    for e in published:
        _local(f"python3 platform/manager/reconcile.py set-state --app {q(e['app'])} "
               f"--state disabled --by dgo-extend --create >/dev/null 2>&1 || true", 60)
        _local(f"./scripts/dc stop {q(e['app'])} >/dev/null 2>&1 || true", 120)
        ctx.setdefault("placed", []).append(e["app"])

    # ── 3. the tile, back in the home console's rail ─────────────────────────────
    tiles = {x.get("id"): x for x in modules}
    for e in published:
        peers.write(oid, e["alias"], tiles.get(e["app"]) or {"id": e["app"], "name": e["app"],
                                                             "icon": "box", "group": "עסק"},
                    f"http://dgo-extend:8983/peer/{oid}/{e['alias']}/")
    stale = peers.clear_office(oid, {e["alias"] for e in published})

    # ── 4. prove it: fetch the door from here, with the token ────────────────────
    wait = []
    for e in published:
        code, why = _probe_peer(office, e["alias"], token, tries=8)
        e["status"] = code
        if not (isinstance(code, int) and code < 400):
            wait.append(f"{e['alias']}: {code} {why}".strip())
    if wait:
        raise StepFailed("הדלת לאפליקציה המרוחקת אינה עונה",
                         "בדוק ש־peer." + office["domain"] + " פותר למחשב ושה־DNS wildcard קיים.",
                         "\n".join(wait))
    return {"summary": " · ".join(f"{e['app']} → {e['peer']}" for e in published),
            "placed": published, "stale": stale, "remote_router": PEER_CONFIG}


def _probe_peer(office: dict, alias: str, token: str, tries: int = 8) -> tuple:
    """GET the peer door from THIS container, with the token — the only real proof that the router
    landed and the certificate was issued. Returns (status_or_error, detail)."""
    url = peers.peer_url(office, alias)
    last = "no attempt"
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"X-Office-Peer": token})
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(req, timeout=15) as r:
                if r.status < 400:
                    return r.status, ""
                last = f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            if e.code < 400:
                return e.code, ""
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(6)
    return None, last



# ── the link plane: this office's own record, and the tunnel to a peer ──────────────────────────────
# A link is a one-way trust between two OFFICES, and the tunnel under it is one WireGuard interface
# per pair. Both ends are rendered HERE and the far end is handed its config through `computers`,
# because a pair shares ONE /24 (10.79.<slot>.0/24) and a side that rendered itself would number its
# own address .1 — the two ends would then disagree about who is who and the tunnel would handshake
# while passing nothing (net.render's `pair` argument exists for exactly this).
#
# The peer runs no dgo-extend of its own: everything it needs is shipped to `<office path>/.dgo/`.
# Its PRIVATE key never crosses that channel — `identity.py` is shipped and run THERE, and the config
# it receives carries `@PRIVATE@` for it to substitute locally.
DECL_DIR = Path(os.environ.get("DGO_STATE_DIR", "/data")) / "dgo"
HOME_FILE = "home.json"
TUNNEL_DIR = os.environ.get("DGO_TUNNEL_DIR", "/tunnel")

REMOTE_UP = """#!/bin/sh
# Apply the tunnel this side was handed. Shipped by dgo-extend/converge.step_link, run here.
set -eu
cd "$(dirname "$0")"
command -v wg-quick >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq wireguard-tools >/dev/null 2>&1; }
command -v nft >/dev/null 2>&1 || apt-get install -y -qq nftables >/dev/null 2>&1
sysctl -qw net.ipv4.ip_forward=1 2>/dev/null || true
# The tunnel's own UDP port, at the HOST's edge. `wg-quick` creates the interface on the host, so the
# host's INPUT policy decides whether the tunnel can be reached at all — vps1 runs ufw with
# `INPUT DROP` and only ssh allowed, which is a tunnel that comes up locally and never answers.
# WireGuard authenticates every packet by key, so the rule is the port, not a peer address (the
# dialing office is behind NAT and its address changes).
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 51820/udp >/dev/null 2>&1 || true
  # What ARRIVES through the tunnel is decided by the tunnel's own table (`inet dgo`, `from_tunnel`:
  # replies, ICMP and the served doors, nothing else). A host firewall with `INPUT DROP` decides it a
  # second time and says no to everything: measured 2026-10-02 on vps1, the door at 10.79.2.2:9002
  # answered locally and dropped every SYN from the peer. One gate — the one rendered from the link.
  ufw allow in on wg0 >/dev/null 2>&1 || true
fi
iptables -C INPUT -p udp --dport 51820 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT -p udp --dport 51820 -j ACCEPT 2>/dev/null || true
iptables -C INPUT -i wg0 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT -i wg0 -j ACCEPT 2>/dev/null || true
mkdir -p /etc/wireguard && chmod 700 /etc/wireguard
# The firewall rides on the interface's own lifecycle (PostUp/PreDown), so whatever brings wg0 up —
# this script, or systemd at boot — brings its rules with it. REPLACED, in one transaction: `nft -f`
# MERGES with whatever is loaded (a second converge appended a second copy of every rule, measured on
# vps1, 2026-10-01), and a delete in a command of its own left NO allow-list whenever nft refused the
# new rules. So the file carries its own prelude — create-if-missing, delete, then the table — and nft
# applies it all or nothing: a refused ruleset leaves the one in force (DGO-603, as tunnel-entrypoint.sh).
( printf 'table inet dgo {}\\ndelete table inet dgo\\n'; cat nftables.rules ) > dgo.nft
install -m 600 dgo.nft /etc/wireguard/dgo.nft
python3 - <<'PY' > /etc/wireguard/wg0.conf
import json, re
priv = json.load(open("identity.json", encoding="utf-8"))["wg"]["private"]
conf = open("wg0.conf", encoding="utf-8").read().replace("@PRIVATE@", priv)
hooks = ("PostUp = nft -f /etc/wireguard/dgo.nft\\n"
         "PreDown = nft delete table inet dgo 2>/dev/null || true")
conf = re.sub(r"^(PrivateKey\\s*=.*)$", lambda m: m.group(1) + "\\n" + hooks, conf, count=1, flags=re.M)
print(conf)
PY
chmod 600 /etc/wireguard/wg0.conf
# A SERVICE, not a one-off `wg-quick up`: measured on vps1 (2026-10-02), the tunnel was up while
# `wg-quick@wg0` was disabled and its nft table had been loaded by hand — one reboot of the VPS and the
# remote office would have stayed unreachable until somebody re-ran `link` from the other side. A host
# without systemd as init (a WSL distro can run without it) keeps the one-off form.
wg-quick down wg0 2>/dev/null || true
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
  systemctl enable wg-quick@wg0 >/dev/null 2>&1 || true
  systemctl restart wg-quick@wg0 || wg-quick up /etc/wireguard/wg0.conf
else
  wg-quick up /etc/wireguard/wg0.conf
fi
echo "UP"
"""

REMOTE_DOWN = """#!/bin/sh
# Take this side's tunnel down and forget it. Shipped by dgo-extend/converge.step_unlink.
set -eu
cd "$(dirname "$0")"
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now wg-quick@wg0 >/dev/null 2>&1 || true
fi
wg-quick down wg0 2>/dev/null || true
nft delete table inet dgo 2>/dev/null || true
rm -f /etc/wireguard/dgo.nft
# The port goes with the link: a revoked tunnel that leaves its UDP door open is a door nobody is
# watching. Both rules are the ones `up.sh` adds, and re-adding them is idempotent.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw delete allow 51820/udp >/dev/null 2>&1 || true
  ufw delete allow in on wg0 >/dev/null 2>&1 || true
fi
iptables -D INPUT -p udp --dport 51820 -j ACCEPT 2>/dev/null || true
iptables -D INPUT -i wg0 -j ACCEPT 2>/dev/null || true
rm -f wg0.conf nftables.rules
echo "DOWN"
"""


def declarations() -> list[dict]:
    """Every PEER this app has declared — both kinds, because both are peers.

    Two records answer "which peer is this": a DECLARATION (`kind` absent or `office`) describes a
    machine this office converges over SSH, and a PAIRED record (`kind: paired`,
    `ai/context/dgo-pairing-contract.md`) describes a peer that joined from the pairing screens and has
    no machine here at all. Both are peers of this office, so both are returned — and a caller that
    means "an office I can converge" asks for `machine_declarations()`, because a paired record has no
    machine, no path and no source, and `converge` must refuse it rather than fall over inside a step.

    This office itself is not among them: it is `home.json` (see home_office), because a file the owner
    could edit is the wrong home for the fact "which machine am I"."""
    return _records(lambda d: True)


def machine_declarations() -> list[dict]:
    """The peers that are MACHINES: what `converge`, `unlink` and the fleet-shaped screens mean."""
    return _records(lambda d: str(d.get("kind") or "office") != "paired")


def paired_records() -> list[dict]:
    """The peers that joined by pairing: no machine, no SSH, no converge step."""
    return _records(lambda d: str(d.get("kind") or "") == "paired")


def _records(want) -> list[dict]:
    out = []
    if not DECL_DIR.exists():
        return out
    for f in sorted(DECL_DIR.glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(d, dict) and d.get("id") and want(d):
            out.append(d)
    return out


def save_declaration(doc: dict) -> None:
    """The one writer of a peer's declaration file, for the fields a LINK decides (its tunnel slot,
    the endpoint it was reached at, the identity it answered with)."""
    DECL_DIR.mkdir(parents=True, exist_ok=True)
    (DECL_DIR / f"{doc['id']}.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


#: ONE writer at a time for the home record inside this process (the app's handlers, the projection
#: loop, the catalog's background refresh and every door fetch all reach it).
_HOME_LOCK = threading.RLock()


def _home_path() -> Path:
    return Path(os.environ.get("DGO_STATE_DIR", "/data")) / HOME_FILE


def _read_home() -> dict:
    """The home record as the FILE holds it — and a read that fails is retried, never taken as empty.

    Taking a failed parse for "no record" is how the MacBook lost its own: `home_office()` read the
    file while another writer was rewriting it, got `{}`, rebuilt it from defaults and wrote that back
    — the `serve:` list gone, the slot moved from 2 to 1, the name back to "הלשכה הזאת", and vps1's
    tile dead until somebody noticed (measured 2026-10-03 00:52). A file that is truly absent is the
    one legitimate empty answer; a file that will not parse is refused, so nothing overwrites it.
    """
    p = _home_path()
    for attempt in range(8):
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            time.sleep(0.05 * (attempt + 1))
    raise StepFailed("רשומת הלשכה (home.json) אינה קריאה — לא נכתבה מחדש",
                     "בדוק את /data/home.json בקונטיינר dgo-extend; היא לא נדרסה.")


def _write_home(doc: dict) -> None:
    """Atomic: a reader sees the old file or the new one, never half of either."""
    p = _home_path()
    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def home_office() -> dict:
    """THIS office, as the other end of every link: machine, path, domain, its slot, its public key.

    Its slot is allocated once and kept in `/data/home.json`, because a slot that moves silently
    renumbers a tunnel another office has already been told about. Only PUBLIC identity material is
    ever stored here — the private half stays in the `dgo_identity` volume.
    """
    with _HOME_LOCK:
        return _home_office()


#: Names an office must not take as its DEFAULT id: they are what every fresh machine of a kind is
#: called (a compose default, an engine's guest), so two fresh offices would both hold them.
_GENERIC_OFFICE_NAMES = ("local", "localhost", "office", "ubuntu", "debian", "bina-deployment",
                         "docker-desktop", "dgo-extend")


def default_office_id(public_identity: dict | None) -> str:
    """The id of an office nobody named: its machine's name, or a short form of its key fingerprint.

    Every fresh office used to be `local`. Two of them on one network — the owner's own first test of
    "two new offices pair from their screens" (2026-10-05) — refused each other: the host read the
    joiner's offer and answered "this is this office's own offer", because both were `local`. The id
    is what every link, tile and vault row of an office is named from, so it has to differ between
    two machines without anybody typing it.

    The machine's name is the identity's label (`hooks/identity mint` records the hostname). Where
    that name is one every machine of its kind has — the macOS engine's guest, a compose default —
    the key fingerprint answers instead: unique by construction, and stable for the life of the key.
    Pure: takes the PUBLIC identity, returns an id `declaration`/`pairing` accept, or `local` when
    the office has no identity yet (nothing can link to it then anyway).
    """
    pub = public_identity or {}
    name = re.sub(r"[^a-z0-9-]+", "-", str(pub.get("office") or "").strip().lower()).strip("-")[:31]
    if re.match(r"^[a-z][a-z0-9-]{1,30}$", name) and name not in _GENERIC_OFFICE_NAMES \
            and not name.startswith("lima"):
        return name
    fp = re.sub(r"[^0-9a-f]", "", str(pub.get("fingerprint") or "").lower())[:8]
    return f"office-{fp}" if len(fp) == 8 else "local"


def _home_office() -> dict:
    import identity as idmod
    doc = _read_home()
    before = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    # EVERY peer's slot counts, of both kinds, and only real ones: a record with no usable slot must
    # not occupy slot 0 (which the allocation below would then believe is taken) — an office that
    # hands a new pair a /24 another pair already holds is a pair whose packets arrive at the wrong
    # interface.
    used = set()
    for d in declarations():
        try:
            s_ = int((d.get("tunnel") or {}).get("slot") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= s_ <= 254:
            used.add(s_)
    slot = int((doc.get("tunnel") or {}).get("slot") or 0)
    if not slot:
        slot = next(s for s in range(1, 255) if s not in used)
    # The name this office is known by (`macbook`), from the declaration in its own compose; the
    # volume keeps it once written, so a container rebuild cannot rename a live link.
    # declared (DGO_OFFICE_ID) > what this office has been called so far (the volume keeps it, so a
    # rebuilt container cannot rename a live link) > a default that differs between two machines.
    # An office already called `local` STAYS `local`: only one that has no name at all gets the default.
    doc["id"] = (os.environ.get("DGO_OFFICE_ID") or "").strip() or doc.get("id") \
        or default_office_id(idmod.public())
    doc["label"] = doc.get("label") or "הלשכה הזאת"
    doc["machine"] = LOCAL_MACHINE
    doc["path"] = HOME_REPO
    doc["domain"] = os.environ.get("DEPLOYMENT_DOMAIN") or doc.get("domain") or "localhost"
    doc["tunnel"] = {"slot": slot, "dial": "home",
                     "endpoint": (doc.get("tunnel") or {}).get("endpoint") or ""}
    pub = idmod.public()
    if not pub.get("wg"):
        # A machine with no identity must not be written into a declaration: every peer would store
        # "no key" as this office's key and the tunnel would be refused on the other side instead of
        # here, where the sentence can say what to run.
        # `mint`, by name: the bare verb only PRINTS an identity, and there is none to print.
        raise StepFailed("אין זהות ללשכה הזאת — הקישור לא יכול להיווצר",
                         "הרץ `bbox dgo identity mint` על המכונה שמריצה את האפליקציה.")
    doc["identity"] = pub
    # Written only when something CHANGED: this runs on every catalog fetch and every projection pass,
    # and an unconditional rewrite was the open window the record was lost through.
    if json.dumps(doc, sort_keys=True, ensure_ascii=False) != before:
        try:
            _write_home(doc)
        except OSError:
            pass
    return doc


def set_home_serve(serve: dict) -> dict:
    """Declare which of THIS office's apps a peer may reach over a link (`serve:` in home.json).

    It is the same field a remote office declares on itself, and it is the only thing that opens an
    inbound port on this side: `net.render` opens `app_ports[peer]` only when the link's direction is
    `serve`, so an app nobody named here is a port nobody can reach — which is why it is a
    declaration and not a default.

    An app's entry carries its `port` (the UI a person opens), and — when it has one — the
    `agent_api_port` of its adapter and the `identity` the peer's traffic is presented under. All
    three are declarations: the second port is a second door, and the identity of a served request is
    a mapping this office chose, never a string a caller sent.
    """
    with _HOME_LOCK:
        return _set_home_serve(serve)


def _set_home_serve(serve: dict) -> dict:
    doc = _read_home()
    clean: dict = {}
    for k, v in (serve or {}).items():
        if k == "exclude":
            # The reserved key of the same declaration (DGO-37): the apps this office does NOT
            # publish to a linked office. It is not an app and has no port, so a loop that only
            # keeps `{port}` would DROP the owner's own exclusion on the next `link` — silently
            # un-hiding an app on every peer. Kept as written, validated at the API that writes it.
            if isinstance(v, list):
                clean["exclude"] = [str(x).strip().lower() for x in v if str(x).strip()]
            continue
        if k == "only":
            # The other reserved key: what ONE linked office is given when it is given less than the
            # rest (`catalog.only_for`). Kept as written, validated at the API that writes it; an
            # office whose list is EMPTY stays in — "linked, and given nothing" is a statement.
            if isinstance(v, dict):
                narrowed = {str(o).strip().lower(): [str(x).strip().lower() for x in names if str(x).strip()]
                            for o, names in v.items() if str(o).strip() and isinstance(names, list)}
                if narrowed:
                    clean["only"] = narrowed
            continue
        if k == "shared":
            # The third reserved key: what OTHER offices gave this one, handed on (`catalog.shared_for`).
            # Kept as written — "*" or a list of origins, the two forms an older office reads without
            # refusing the far plan — validated at the API that writes it. Empty clears it.
            if v == catalog.WILDCARD:
                clean["shared"] = v
            elif isinstance(v, list) and v:
                clean["shared"] = [str(o).strip().lower() for o in v if isinstance(o, str) and o.strip()]
            continue
        if k == "services":
            # The fourth: the doors with no tile this office gives (DGO-945) — alias → {to, paths},
            # held to `catalog.clean_services`, the rule the API that writes it refuses by. A map that
            # is not one gives no door at all rather than a door wider than was written. Empty clears it.
            doors, _why = catalog.clean_services(v)
            if doors:
                clean["services"] = doors
            continue
        if k == catalog.WILDCARD:
            # "Every app" (`catalog.publishable`) — kept as the bare key it is: it has no port, and
            # `int(None)` here would have refused the one declaration the owner asked for.
            clean[k] = {}
            continue
        spec = v if isinstance(v, dict) else {"port": v}
        entry = {"port": int(spec.get("port"))}
        if spec.get("agent_api_port"):
            entry["agent_api_port"] = int(spec["agent_api_port"])
        ident = spec.get("identity") or {}
        if ident.get("to") or ident.get("from"):
            entry["identity"] = {"to": str(ident.get("to") or ""),
                                 "from": [str(u) for u in (ident.get("from") or []) if u]}
        if "host" in spec:
            # Declared, so kept even when EMPTY: "" is the statement that this app trusts the
            # consuming office's own authority, and the far edge passes the browser's Host through
            # (`_serve_block`, `catalog.build`). Absent means the manifest's `sso.default_host`.
            entry["host"] = str(spec.get("host") or "").strip().lower()
        # A caller that names an app's PORTS is not un-declaring its identity or its host: those are
        # separate declarations, and only an explicit key changes them. Measured 2026-10-02: an agent
        # re-declared `bina-ds` with its two ports while adding `*`, the identity mapping and the
        # host pass-through vanished, and vps1's Bina tile answered 401 through the door.
        before = ((doc.get("serve") or {}).get(str(k)) or {}) if isinstance(doc.get("serve"), dict) else {}
        if isinstance(before, dict):
            if "identity" not in spec and before.get("identity"):
                entry["identity"] = before["identity"]
            if "host" not in spec and "host" in before:
                entry["host"] = before["host"]
        clean[str(k)] = entry
    # …and a caller that re-declares what the office gives is not un-narrowing an office either: the
    # screen's "give everything" names no `only`, and dropping it there would hand a narrowed office
    # the whole list. Only an explicit `only` changes it (`{}` clears it).
    kept = (doc.get("serve") or {}).get("only") if isinstance(doc.get("serve"), dict) else None
    if "only" not in (serve or {}) and isinstance(kept, dict) and kept:
        clean["only"] = kept
    # …nor un-sharing: handing on what other offices gave is changed only by an explicit `shared`.
    kept = (doc.get("serve") or {}).get("shared") if isinstance(doc.get("serve"), dict) else None
    if "shared" not in (serve or {}) and kept:
        clean["shared"] = kept
    # …nor closing a door: the screen's "give everything" names no `services` either. An EMPTY
    # declaration is the other thing — "give nothing" (`pair_api.give("none")`) — and closes them too:
    # the screen must never say "nothing" over a door that is open (second reader, DGO-945).
    kept = (doc.get("serve") or {}).get("services") if isinstance(doc.get("serve"), dict) else None
    if serve and "services" not in serve and kept:
        clean["services"] = kept
    doc["serve"] = clean
    doc.setdefault("id", "local")
    _write_home(doc)
    return doc["serve"]


def set_home_label(label: str) -> str:
    """How THIS office names itself to the offices it is linked to.

    It reaches the far console (the tile a served app produces says which office it belongs to, and
    that sentence is the only "the remote is asleep" signal the owner gets), so it has to be a name a
    person recognizes — "MacBook", not "local".
    """
    with _HOME_LOCK:
        doc = _read_home()
        doc["label"] = str(label).strip()
        doc.setdefault("id", "local")
        _write_home(doc)
        return doc["label"]


# ── the `serve:` block the PEER's state file carries (DGO-30, DGO-32) ───────────────────────────#: The instance id of the credential a SERVING office hands to the office that consumes its agent.
#: Deterministic and derived from facts both ends can see (the serving office's id and the app's),
#: so the handoff and `bbox agent`'s lookup cannot disagree about the name of the same secret.
def agent_instance(office: str, app: str) -> str:
    return f"dgo_link-serve-{office}-{app}-agent"


def _app_manifest(app_id: str) -> dict:
    """One app's manifest, read from THIS office's checkout through `computers`.

    The presentation of a served tile (its alias, name, icon) and the port a person opens are the
    APP's own facts, declared in its `app.json` — not something a link may invent. Read through the
    one door to machines (`computers`), from the office's own checkout, and never fatal: a manifest
    that cannot be read leaves the declaration's own values in place.
    """
    if not HOME_REPO:
        return {}
    try:
        out = must(LOCAL_MACHINE, f"cat {q(HOME_REPO.rstrip('/') + '/apps/' + app_id + '/app.json')}",
                   60)
        return json.loads(out or "{}")
    except (StepFailed, ValueError):
        return {}


def _agent_port(manifest: dict) -> int | None:
    """The adapter port an app declares for `agent.v1` — the second door of an agent app."""
    for cap in (manifest.get("capabilities") or []):
        if cap.get("name") == "office-agent" and cap.get("interface") == "agent.v1":
            m = re.search(r":(\d{1,5})\b", str(cap.get("endpoint") or ""))
            if m:
                return int(m.group(1))
    return None


def _local_sso_user() -> str:
    """The user THIS office's own edge authenticates — i.e. who a served app of this office knows.

    Read from the office's own `.env` through `computers`, not from this container's environment: the
    app is deliberately not handed the identity of the office it runs in, and `AUTHENTIK_BOOTSTRAP_USER`
    is the account `bbox run` creates. A failure is not fatal — the declaration may name the user
    itself — so an unreadable `.env` leaves the answer empty rather than failing a converge.
    """
    if not HOME_REPO:
        return ""
    try:
        out = must(LOCAL_MACHINE,
                   f"grep -m1 '^AUTHENTIK_BOOTSTRAP_USER=' {q(HOME_REPO.rstrip('/') + '/.env')} "
                   f"| cut -d= -f2- | tr -d '\"'", 60)
    except StepFailed:
        return ""
    return (out or "").strip().splitlines()[0].strip() if (out or "").strip() else ""


def _serve_block(office: dict, home: dict) -> list[dict]:
    """The layer-0 `serve:` list that belongs in the PEER's `platform.state.yaml`.

    Direction first: only an office whose link says the peer may arrive serves anything, so a `use`
    link renders NO block at all. What follows is one entry per served app, and every field is a fact
    that already exists somewhere else — the alias/name/icon/port come from the app's own manifest,
    the address is this office's end of the pair (`net.py`: `.1` is the office that owns the slot),
    and the identity is the mapping the serving office declared (defaulting to its own SSO user,
    because the request that arrives left the peer's edge as a user of the peer's office and has to
    become a user of THIS one).

    The `host` field is the app's own authority (`sso.default_host` in its `routing[]`). It is sent
    as the Host header by the peer's edge, because an app that validates its Host — every harness in
    this platform does — refuses a name it was never told about, and the nested console host is not
    its name.
    """
    link = _link_of(office, home.get("id") or "local")
    if not link:
        # No link declared between the two offices: nothing is served. The `use` default below is for
        # a link that names no direction — read for NO link, it mirrored to `serve`, and a new office
        # that links to nobody (fireplace, 2026-10-22) was handed this office's apps: a bina tile, at
        # an address of a pair it is not in, in the console of a client who must not see us.
        return []
    # `both` serves as well (see `_mirror`): testing for `serve` alone wrote an EMPTY block on a
    # bidirectional link, and the peer's compiler took its route, tile and alias away (measured
    # 2026-10-01 on vps1, the first converge after the link was made bidirectional).
    if _mirror((link or {}).get("direction") or "use") not in ("serve", "both"):
        return []
    served = home.get("serve") or {}
    if not served:
        return []
    try:
        slot = _pair_slot(office, home)              # this pair's /24, where this office is `.1`
    except (TypeError, ValueError):
        slot = 0
    if not slot:
        return []
    domain = (home.get("domain") or "localhost").strip() or "localhost"
    default_to = _local_sso_user()
    entries = []
    # The apps, never the declaration's reserved keys (`catalog.app_specs`): `exclude` is a list and
    # `shared` may be "*", and either read as a port is an `int()` that takes the converge down.
    for app, spec in sorted(catalog.app_specs(served).items()):
        spec = spec if isinstance(spec, dict) else {"port": spec}
        man = _app_manifest(app)
        routes = man.get("routing") or []
        route = next((r for r in routes if (r.get("module") or {}).get("alias")), routes[0] if routes else {})
        module = route.get("module") or {}
        port = int(spec.get("port") or route.get("port") or 0)
        if not port:
            continue
        alias = str(module.get("alias") or route.get("host") or app).lower()
        host = ""
        authority = ((route.get("sso") or {}).get("default_host") or "").strip()
        if "host" in spec:
            # The serving office's own declaration wins. EMPTY says the app trusts the consuming
            # office's authority (it is in the app's trust list), so the far edge must pass the
            # browser's Host through: a harness whose Origin fence requires `Origin == Host` refuses
            # every API call and websocket of a framed page whose Host was rewritten (measured
            # 2026-10-01 on bina-ds: `isTrustedApiRequest` → 403 while `GET /` answered 200).
            host = str(spec.get("host") or "").strip().lower()
        elif authority:
            host = authority
        elif route.get("host"):
            host = f"{route['host']}.{'localhost' if domain == 'localhost' else domain}"
        ident = spec.get("identity") or {}
        to_user = str(ident.get("to") or default_to or "").strip()
        entry = {"app": app, "alias": alias, "port": port,
                 "name": str(module.get("name") or man.get("title", {}).get("he") or app),
                 "icon": str(module.get("icon") or "external"),
                 "group": str(module.get("group") or "מרוחק"),
                 "desc": str(module.get("desc") or man.get("title", {}).get("he") or app)
                         + f" · הלשכה {(home.get('label') or home.get('id') or '')}".rstrip(),
                 "order": int(module.get("order") or 900)}
        agent_port = int(spec.get("agent_api_port") or _agent_port(man) or 0)
        if agent_port:
            entry["agent_api_port"] = agent_port
        if host:
            entry["host"] = host
        if to_user:
            entry["identity"] = {"to": to_user}
            if ident.get("from"):
                entry["identity"]["from"] = [str(u) for u in ident["from"] if u]
        entries.append(entry)
    if not entries:
        return []
    # The link's ONE door (DGO-32): this office answers the peer's UI requests on `door_port(slot)` and
    # picks the app by Host, so the peer's route has to target the door and not the app's own port —
    # which this office no longer opens on the tunnel. Without it the peer's compiler falls back to the
    # app's port (the "predates the door" case) and the tile 502s the moment this office runs the door.
    import linkproxy
    return [{"office": str(home.get("id") or "local"), "address": f"10.79.{slot}.1", "apps": entries,
             "link_port": linkproxy.door_port(slot)}]


#: The served block, handed to THE writer of `platform.state.yaml` on the peer's machine
#: (`reconcile.py remote-set`, beside the reader — gate G33). This was a second text surgery on that
#: file, shipped from here: it wrote the legacy `serve:` key, unvalidated, and twice left the file
#: unparseable (2026-10-02 on vps1). The writer it asks now validates the block against the peer's
#: own catalog before a byte changes, writes it as `remote:` — the general form `serve:` was an
#: alias of — and takes a legacy `serve:` block away with it.
#:
#: THE PROJECTION WINS, and this step stands aside where it has written: `projection.py` builds the
#: same block on the consuming side from the serving office's own catalog, and marks each entry with
#: when that catalog was read (`fetched`). Two writers of one meaning is exactly the drift the
#: remote-apps contract (`ai/context/dgo-remote-apps.md`) exists to end — so the declared block is
#: written only where no entry carries that mark. An empty block is a declaration too: it removes
#: what an earlier converge wrote.
SERVE_WRITER = r'''
DGO_SERVE_B64='__SERVE__' python3 - <<'PY'
import base64, json, os, subprocess, sys
raw = os.environ.get("DGO_SERVE_B64") or ""
block = json.loads(base64.b64decode(raw).decode("utf-8")) if raw else []
writer = [sys.executable, "platform/manager/reconcile.py"]
got = subprocess.run(writer + ["remote-get"], capture_output=True, text=True)
if got.returncode:
    sys.exit("the version checked out here has no `remote-get` (the state file's one writer) — "
             "declare a newer version for this office: " + (got.stderr or got.stdout).strip()[-300:])
if any("fetched" in e for e in json.loads(got.stdout or "[]")):
    print("SERVE=skipped (remote: is written by the projection)")
    raise SystemExit(0)
put = subprocess.run(writer + ["remote-set"], input=json.dumps(block), capture_output=True, text=True)
if put.returncode:
    sys.exit("the served block was refused, nothing written: " + (put.stderr or put.stdout).strip()[-600:])
print("SERVE=" + ",".join(f"{e['office']}:{a['alias']}" for e in block for a in e["apps"]))
PY
'''


def _ship(office: dict, files: dict) -> None:
    """Write files under `<office path>/.dgo/` on the machine — base64 through `computers`, so no
    rendered config has to survive a shell, a heredoc and a JSON body at the same time."""
    parts = []
    for name, text in files.items():
        b = base64.b64encode(text.encode()).decode()
        parts.append(f"echo {q(b)} | base64 -d > {q(office['path'] + '/.dgo/' + name)}")
    must(office["machine"],
         f"mkdir -p {q(office['path'] + '/.dgo')} && chmod 700 {q(office['path'] + '/.dgo')} && "
         + " && ".join(parts), 120, "כתיבת קבצי המנהרה על המכונה נכשלה")


def _remote_identity(office: dict, oid: str) -> dict:
    """The peer's PUBLIC identity, minting it on its own machine when it has none.

    `identity.py` is shipped and run THERE, so the private half never crosses the channel this app has
    to that machine; the module prints `public()` and nothing else.
    """
    src = base64.b64encode(Path(__file__).with_name("identity.py").read_bytes()).decode()
    d = office["path"] + "/.dgo"
    out = must(office["machine"],
               f"mkdir -p {q(d)} && echo {q(src)} | base64 -d > {q(d + '/identity.py')} && "
               f"cd {q(d)} && DGO_IDENTITY_DIR={q(d)} python3 identity.py --label {q(oid)} mint",
               120, "מינוי הזהות של המכונה המרוחקת נכשל")
    i = out.find("{")
    try:
        return json.loads(out[i:])
    except (ValueError, json.JSONDecodeError):
        raise StepFailed("המכונה המרוחקת לא החזירה זהות קריאה",
                         "בדוק ש-python3 ו-openssl זמינים על המכונה.")


def _remote_identity_seed(office: dict, oid: str, emit) -> dict:
    """Make the far office's OWN dgo-extend hold the identity minted for it here (DGO-32).

    `_remote_identity` mints the far end's keys on its own machine, into `<path>/.dgo/identity.json` —
    because the WireGuard interface that runs on its HOST has to be given a private key there. But the
    APP on that machine reads its identity from its own `dgo_identity` volume (mounted at
    `/identity`), and nothing had ever put a file in it. Measured on vps1 2026-10-02: the volume was
    empty, `home_office()` there answered `local` with no key, and `GET /api/link/catalog` — the door
    the OTHER office pulls to learn which apps exist — could not answer at all. So the office that
    dials seeds the office it dialed: same machine, the same identity, one fact in one place.

    The copy is by VOLUME NAME read off the far container (never constructed: the far office's compose
    project name is its own), through a one-shot container of the image that container already runs,
    and mode 0600. The private half never leaves that machine, and never passes through this process.
    """
    container = _remote_container(office, "dgo-extend-")
    if not container:
        emit(f"אזהרה: אין קונטיינר dgo-extend פעיל ב-{office['id']} — הזהות לא הועתקה")
        return {"ok": False, "reason": "no dgo-extend container on the far machine"}
    out = must(office["machine"],
               "docker inspect " + q(container) + " --format '{{json .Mounts}}'", 60,
               f"קריאת ה-volumes של dgo-extend ב-{office['id']} נכשלה")
    try:
        mounts = json.loads(out[out.find("["):out.rfind("]") + 1])
    except ValueError:
        mounts = []
    volume = next((str(m.get("Name") or "") for m in mounts
                   if isinstance(m, dict) and m.get("Destination") == "/identity"), "")
    if not volume:
        emit(f"אזהרה: לקונטיינר dgo-extend ב-{office['id']} אין volume של זהות")
        return {"ok": False, "reason": "the far office has no identity volume"}
    image = must(office["machine"],
                 "docker inspect " + q(container) + " --format '{{.Config.Image}}'", 60,
                 f"קריאת התמונה של dgo-extend ב-{office['id']} נכשלה").strip()
    src = office["path"] + "/.dgo/identity.json"
    script = "umask 077; cat > /identity/identity.json && chmod 600 /identity/identity.json"
    must(office["machine"],
         f"cat {q(src)} | docker run --rm -i --entrypoint sh -v {q(volume + ':/identity')} "
         f"{q(image)} -c {q(script)}", 120,
         f"העתקת הזהות ל-volume של {office['id']} נכשלה")
    # Verified by ASKING the app, not by the exit code of a copy: the file has to parse there, and it
    # has to name this office — the whole point is that the far app can now answer who it is.
    check = must(office["machine"],
                 f"docker exec {q(container)} python3 -c "
                 + q("import json;d=json.load(open('/identity/identity.json'));print('SEED='+str(d.get('office') or ''))"),
                 60, f"אימות הזהות ב-{office['id']} נכשל")
    name = _fact_line(check, "SEED")
    if not name:
        emit(f"אזהרה: הזהות הועתקה ל-{office['id']} אך האפליקציה אינה קוראת אותה")
        return {"ok": False, "reason": "the far app cannot read the seeded identity", "volume": volume}
    return {"ok": name == oid, "volume": volume, "office": name}


#: The one writer of a key in the far office's `.env`. `step_env` only EXTENDS a `.env` with keys the
#: checkout's `.env.ex` declares (and deliberately never regenerates secrets), so a value that belongs
#: to the DECLARATION — this office's own id — is written here, from the declaration.
ENV_SET = r'''
import re, sys
key, value = sys.argv[1], sys.argv[2]
try:
    text = open(".env", encoding="utf-8").read()
except OSError:
    text = ""
line = f"{key}={value}"
if re.search(rf"^{re.escape(key)}=.*$", text, re.M):
    text = re.sub(rf"^{re.escape(key)}=.*$", line, text, count=1, flags=re.M)
else:
    text = text.rstrip("\n") + "\n" + line + "\n"
open(".env", "w", encoding="utf-8", newline="\n").write(text)
print("ENV=" + line)
'''


def _remote_office_id(office: dict, emit) -> dict:
    """Tell the far office WHICH office it is (`DGO_OFFICE_ID`), and only when it changed.

    Without it `home_office()` there falls back to `local`: the catalog it publishes names the wrong
    office, every tile the peer renders is namespaced under `local`, and the link's own control door
    answers for a name no declaration holds. The id is a fact of the DECLARATION here, so it is written
    from here — the same reason its tunnel and its identity are.

    Recreating its `dgo-extend` container is how an environment variable takes effect, so it is done
    only when the file actually changes: a converge that restarts an app every time is a converge that
    drops whatever that app was doing.
    """
    path = office["path"]
    key = "DGO_OFFICE_ID"
    current = must(office["machine"], f"grep -s '^{key}=' {q(path + '/.env')} || true", 60).strip()
    if current == f"{key}={office['id']}":
        return {"ok": True, "changed": False, "value": office["id"]}
    out = must(office["machine"],
               f"cd {q(path)} && python3 -c {q(ENV_SET)} {q(key)} {q(office['id'])}", 60,
               f"כתיבת {key} ב-.env של {office['id']} נכשלה")
    if "ENV=" not in out:
        return {"ok": False, "reason": f"{key} was not written"}
    must(office["machine"], f"cd {q(path)} && ./scripts/dc up -d dgo-extend", 300,
         f"הפעלה מחדש של dgo-extend ב-{office['id']} עם {key} נכשלה")
    emit(f"{office['id']}: {key}={office['id']} נכתב ו-dgo-extend הופעל מחדש")
    return {"ok": True, "changed": True, "value": office["id"]}


def _remote_label(office: dict, emit) -> dict:
    """Tell the far office its NAME (the declaration's `label`), and only when it differs.

    The label travels in its catalog, and the peer's console prints it on every tile it shows of that
    office ("<office> לא זמינה כרגע", the corner mark's tooltip). A far end that was never told keeps
    the default — "הלשכה הזאת", "this office" — so the MacBook listed vps1's fourteen apps as its own
    (measured 2026-10-02). No restart: the label is read from the home record per request.
    """
    label = str(office.get("label") or "").strip()
    container = _remote_container(office, "dgo-extend-")
    if not label or not container:
        return {"ok": False, "reason": "no label declared or no dgo-extend container"}
    code = ("import json,sys,converge as cv;p='/data/home.json';"
            "cur=(json.load(open(p)) if __import__('os').path.exists(p) else {}).get('label');"
            "want=sys.argv[1];"
            "print('LABEL=same' if cur==want else 'LABEL=set:'+cv.set_home_label(want))")
    out = must(office["machine"], f"docker exec {q(container)} python3 -c {q(code)} {q(label)}", 60,
               f"כתיבת השם של {office['id']} נכשלה")
    changed = "LABEL=set:" in out
    if changed:
        emit(f"{office['id']}: השם בלשכה המרוחקת עודכן ל-„{label}”")
    return {"ok": True, "changed": changed, "value": label}


def _remote_config(office: dict, doc: dict) -> None:
    """Ship the far end's rendered config and bring it up."""
    # `addressing.json` is shipped too: it is the far office's own record of which address it holds in
    # THIS pair, which is what it derives its link door's port from (`app._pair_slot`) — a fact the end
    # that rendered the pair knows and the far end cannot compute for itself.
    _ship(office, {"wg0.conf": doc["wg"], "nftables.rules": doc["nftables"], "up.sh": REMOTE_UP,
                   "addressing.json": json.dumps(doc["addressing"], indent=2) + "\n"})
    out = must(office["machine"], f"sh {q(office['path'] + '/.dgo/up.sh')}", 240,
               "העלאת המנהרה על המכונה המרוחקת נכשלה")
    if "UP" not in out:
        raise StepFailed("המנהרה לא עלתה על המכונה המרוחקת", "ראה את פלט up.sh בצעד.")


def _remote_down(office: dict) -> None:
    _ship(office, {"down.sh": REMOTE_DOWN})
    must(office["machine"], f"sh {q(office['path'] + '/.dgo/down.sh')}", 120,
         "הורדת המנהרה על המכונה המרוחקת נכשלה")



def _dial_address(host: str) -> str:
    """The address WireGuard DIALS, resolved where DNS actually answers.

    `wg-quick` resolves the Endpoint itself, on the machine that runs it — and this platform's
    containers get a docker-internal resolver that does not answer for public names (measured
    2026-10-01: both `dgo-extend` and `dgo-net` answer `gaierror` for the office's own domain while the
    host resolves it). Writing the address we resolved keeps a tunnel from depending on which resolver
    the applier happens to have.
    """
    h = (host or "").split(":")[0].strip()
    if not h or re.match(r"^\d+\.\d+\.\d+\.\d+$", h):
        return h
    try:
        return socket.gethostbyname(h)
    except OSError:
        pass
    out = must(LOCAL_MACHINE, f"getent hosts {q(h)} 2>/dev/null | head -1 | awk '{{print $1}}'", 30)
    ip = (out or "").strip().splitlines()[0].strip() if (out or "").strip() else ""
    if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
        raise StepFailed(f"לא ניתן לפתור את {h} לכתובת",
                         "בדוק את ה-DNS, או כתוב כתובת IP ב-tunnel.endpoint של ההצהרה.")
    return ip


def _link_of(office: dict, home_id: str) -> dict:
    for l in (office.get("links") or []):
        if (l or {}).get("office") == home_id or (l or {}).get("id") == home_id:
            return l or {}
    return {}


def _mirror(direction: str) -> str:
    """The SAME link seen from the other end: what one office serves, the other uses.

    `both` is its own mirror: a link the owner declared bidirectional is bidirectional from either
    side, and flipping it to `use` would silently close half of what he asked for.
    """
    d = direction or "use"
    if d == "both":
        return "both"
    return "use" if d == "serve" else "serve"


def _served_ports_local(office: dict, slot: int | None = None, registry: dict | None = None,
                        peer: str = "") -> dict:
    """The ports a `serve` link opens HERE, from the apps this office's own record names.

    ONE door per link (DGO-32), plus the catalog and any app's agent API: an office whose registry
    holds four apps on 8080 cannot open a listener per app, so the door carries the UI doors and the
    Host header picks the app behind it (`linkproxy`). The catalog keeps its own port — it is how the
    peer learns which apps exist, and it cannot sit behind the door it describes — and an agent app's
    adapter keeps a port because a CLI addresses a port and not a name.

    An office that serves nothing returns an empty map: the firewall, the delivery plan and the peer's
    projection all read this one function, so "nothing served" cannot mean three different things.

    `registry` — the registry of the office whose doors these are (this office's compiled one, or a
    peer's FETCHED catalog): the served map is then ENRICHED with the agent door each served app declares
    (`catalog.serve_with_agents`, DGO-570) — the very map the link proxy listens by. Without it the
    firewall opened only an agent port written into `serve:` by hand, while the proxy listened on the
    registry's: browser42's 8931 on hp-laptop listened behind a firewall that dropped it, and no linked
    office could drive the HP's browser (measured 2026-10-22, DGO-1002).
    """
    served = catalog.with_control(catalog.serve_with_agents(registry, office.get("serve"))
                                  if registry is not None else office.get("serve"))
    if not served:
        return {}
    import linkproxy
    pair = int(slot or (office.get("tunnel") or {}).get("slot") or 0)
    if not pair:
        raise StepFailed(f"ללשכה {(office.get('id'))!r} אין slot מוצהר — אין פורט לדלת הקישור",
                         "הרץ קודם קישור (`bbox dgo link`) כדי שהזוג יקבל /24 משלו.")
    out = {linkproxy.DOOR_APP: linkproxy.door_port(pair),
           "dgo-extend": int(catalog.CATALOG_PORT)}
    # WHAT THAT PEER IS GIVEN, the way the proxy narrows it (`linkproxy.build_multi`'s `given`): an office
    # named in `serve.only` gets an agent door only for an app on its list — the door and the catalog
    # stay. The firewall's accept has no destination, so a port opened here for a peer the proxy does not
    # serve would reach another pair's listener through this peer's own tunnel.
    only = catalog.only_for(office.get("serve"), peer)
    for app, spec in served.items():
        if app == "dgo-extend" or (only is not None and app not in only):
            continue
        if isinstance(spec, dict) and spec.get("agent_api_port"):
            out[f"{app}:agent"] = int(spec["agent_api_port"])
    return out


def _pair_slot(office: dict, home: dict) -> int:
    """The /24 of THIS pair: the office record's own `tunnel.slot`, or the home's for a record that
    declares none (the first converged link, vps1, predates per-pair slots and shares the home's).

    With one interface per pair (`pairs/wg<slot>.conf`) every pair needs its own /24. Taking the home's
    slot for every converged office gave the second one vps1's (fireplace, 2026-10-22: declared 6,
    saved as 2, and the renderer refused "two pairs on the same slot (2)")."""
    own = (office.get("tunnel") or {}).get("slot")
    return int(own or (home.get("tunnel") or {}).get("slot"))


def _render_local_tunnel(emit) -> dict:
    """Write THIS office's local tunnel through the ONE renderer that owns that layout.

    `step_link` used to write `/tunnel/wg0.conf` itself. With one interface per PAIR the layout is
    `pairs/wg<slot>.conf` plus the shared artifacts, and a second writer of the same directory is how
    a pair's file goes missing — and a missing file is an interface the applier retires. The renderer
    refuses as a whole when any pair cannot be rendered (and then writes nothing, so what is running
    stays running); that refusal is this step's failure, with its own sentence.
    """
    import app as _app
    doc = _app.render_tunnel()
    if not isinstance(doc, dict):
        # the renderer answers its refusals as the HTTP route does (a JSONResponse): read the sentence
        # out of it, or the step crashed on `.get` and the refusal itself was never shown (fireplace,
        # 2026-10-22: "'JSONResponse' object has no attribute 'get'")
        try:
            doc = json.loads(bytes(getattr(doc, "body", b"") or b"{}").decode("utf-8", "replace")) or {}
        except ValueError:
            doc = {}
        doc.setdefault("error", "רינדור המנהרה נכשל")
    rendered = doc.get("rendered")
    if rendered is None or doc.get("error"):
        raise StepFailed(str(doc.get("error") or "רינדור המנהרה נכשל"),
                         "בדוק את רשומות הלשכות המקושרות ואת הזהויות שלהן.")
    emit("המנהרה של הלשכה הזאת רונדרה (%d זוגות)" % len(doc.get("pairs") or []))
    return doc


def _pair_addresses(office_id: str, slot: int) -> tuple[str, str]:
    """This office's address and the peer's, IN ONE PAIR, from the plan that was just written.

    A question about a pair, not about "the tunnel": with several pairs there is no single `self`, and
    the step's ping and delivery probes are measurements of THIS pair.
    """
    try:
        doc = json.loads((Path(TUNNEL_DIR) / "addressing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StepFailed("תוכנית המנהרה לא נקראה אחרי הרינדור",
                         "בדוק את יומן dgo-extend ואת הרשאות התיקייה.", f"{type(e).__name__}: {e}")
    for entry in (doc.get("pairs") or []):
        if entry.get("office") == office_id or int(entry.get("slot") or 0) == int(slot or 0):
            return str(entry.get("self") or ""), str(entry.get("peer") or "")
    # A plan written before pairs existed (or a single-pair fallback): the legacy shape.
    peers = doc.get("peers") or []
    return str(doc.get("self") or ""), (str(peers[0].get("address")) if peers else "")


def _await_pong(office: dict, my_addr: str, tries: int = 15) -> str:
    """Wait for the far machine to answer a ping through the tunnel, retried.

    Asked repeatedly and not once: this end's interface is brought up by the `dgo-net` sidecar, which
    re-applies a changed rendered plan within ~15 seconds, so a single ping measures that timer rather
    than the tunnel. `PONG` in the output is the answer; anything else is a tunnel that carries
    nothing, which the caller repairs and re-measures before it is reported.
    """
    return must(office["machine"],
                f"for i in $(seq 1 {int(tries)}); do ping -c1 -W3 {my_addr} >/dev/null 2>&1 && "
                f"{{ echo PONG; break; }}; sleep 4; done; echo END", 120)


def step_link(office: dict, ctx: dict, emit) -> dict:
    """Bring up the tunnel between this office's machine and the HOME office — both ends, one step.

    The declaration that decides it is the one this converge is running for: `links: [{office: local,
    direction: use|serve}]` on the peer, where `serve` means "the home may reach the apps I serve".
    Rendered here, applied on both machines, and then MEASURED: `wg show` on the far end and a ping
    through the tunnel. "The container is up" is not a link.
    """
    import identity as idmod
    import net as netmod
    home = home_office()
    link = _link_of(office, home["id"])
    if not link:
        return {"summary": "אין קישור מוצהר ללשכה הזאת — אין מנהרה להעלות", "links": []}
    direction = netmod.link_direction(link)
    slot = _pair_slot(office, home)
    # Refused BEFORE anything is written: this step saves the slot into the record, and a colliding
    # slot saved once is read as the record's own from then on (fireplace, 2026-10-22).
    import app as _app
    holder = next((o["id"] for o in _app.all_declarations() if o.get("id") != office["id"]
                   and int((o.get("tunnel") or {}).get("slot") or 0) == slot), None)
    if holder:
        raise StepFailed(f"ה-slot {slot} כבר של הזוג עם {holder} — לכל זוג /24 משלו",
                         "הצהר על tunnel.slot פנוי ללשכה הזאת (1–254) והרץ שוב.")
    declared_endpoint = (office.get("tunnel") or {}).get("endpoint") or office.get("domain") or ""
    # The address to DIAL comes from the fleet first: `computers` already knows where that machine is
    # (`host: 93.184.216.5`), it is the same fact the SSH connection uses, and it does not depend on a
    # resolver inside a container (the platform's containers cannot resolve public names — measured).
    try:
        peer_endpoint = (machine_record(office["machine"]).get("host") or "").strip()
    except StepFailed:
        peer_endpoint = ""
    peer_endpoint = peer_endpoint or _dial_address(declared_endpoint)
    peer = {**office,
            "tunnel": {**(office.get("tunnel") or {}), "slot": slot, "endpoint": peer_endpoint,
                       "dial": "remote"}}
    home_side = {**home, "links": [{"office": office["id"], "direction": _mirror(direction)}]}
    peer_ident = _remote_identity(office, office["id"])
    # The far office has to know WHO it is and hold its own identity file before anything it publishes
    # can be read (DGO-32): its catalog is the door the other office pulls to learn which apps exist,
    # and it cannot answer for an office with no name.
    seeded = _remote_identity_seed(office, office["id"], emit)
    office_id = _remote_office_id(office, emit)
    _remote_label(office, emit)
    ids = {home["id"]: home["identity"], office["id"]: peer_ident}
    # The port map this end opens for the peer is no longer built here: the local render
    # (`app.render_tunnel`) derives it from the same records, one pair at a time
    # (`app._link_pairs`), which is where the direction rule lives now.
    # What the far office SERVES is its own declaration (`_remote_serve_map`, the same answer its
    # catalog and its delivery plan use), not a field of this office's record of it. Reading the
    # record opened nothing: measured 2026-10-02, vps1 declared `serve: {"*": {}}`, its door and its
    # socket bridge were up, and its tunnel firewall still dropped every SYN from 10.79.2.1.
    far_serve = (_remote_serve_map(office, emit) if direction in ("serve", "both") else {}) \
        or (office.get("serve") or {})
    import app as _app
    for_home = {home["id"]: _served_ports_local({**office, "serve": far_serve}, slot,
                                                catalog.load_all(_app.STATE_DIR).get(office.get("id")) or {},
                                                peer=home["id"])}
    # The FAR side is rendered here because only this end holds both identities; OUR side is rendered
    # by `app.render_tunnel` below, through the one renderer that owns the per-pair layout (and that
    # renders every pair, not just this one).
    try:
        peer_doc = netmod.render(peer, [home_side], ids, for_home,
                                 pair={"slot": slot, "side": 2, "dial": "remote"},
                                 host_forward=True)
    except netmod.NetError as e:
        raise StepFailed(str(e), "בדוק את הצהרת הקישור ואת הזהויות של שני הצדדים.")
    _remote_config(office, peer_doc)
    base = Path(TUNNEL_DIR)
    base.mkdir(parents=True, exist_ok=True)
    # The LOCAL side is written by the ONE renderer that owns this layout (`app.render_tunnel`), not a
    # second copy of it here: this step used to write `/tunnel/wg0.conf` itself, and with one interface
    # PER PAIR (`pairs/wg<slot>.conf`) two writers of the same directory is how a pair's file goes
    # missing — and a missing file is an interface the applier retires.
    #
    # The declaration is saved FIRST for the same reason: the renderer reads the records, and a pair it
    # cannot see is a pair it does not render.
    office.setdefault("identity", {}).update(peer_ident)
    office.setdefault("tunnel", {})["slot"] = slot
    office["tunnel"]["endpoint"] = declared_endpoint      # the readable host stays in the declaration
    save_declaration(office)
    home_doc = _render_local_tunnel(emit)
    ident = idmod.load() or {}
    secret = base / "wg-private.key"
    secret.write_text((ident.get("wg") or {}).get("private", ""), encoding="utf-8")
    secret.chmod(0o600)
    # The DELIVERY half of the same plan (DGO-24): which of this office's own ports the peer can
    # actually reach, from the same two facts the firewall was rendered from. Without it an `accept`
    # in the tunnel's firewall is a permission nobody delivers on — measured from vps1 on 2026-10-01:
    # the SYN to 10.79.2.1:3081 was DROPPED (the timeout expired, rc=124), not refused.
    try:
        # The app's OWN renderer, not a second one: it knows every declared peer, the catalogs the
        # projection pulled, and the proxy's own address for the `use` doors. Rendering here from
        # `[office]` alone bound the catalog door to 0.0.0.0, which collides with the serve door on a
        # bidirectional link (refused on every converge, 2026-10-01) — and without the collision it
        # would have replaced the app's plan with a poorer one.
        import app as _app
        proxy_plan = _app.render_link_proxy()
        if proxy_plan.get("refused"):
            emit(f"אזהרה: תוכנית האספקה לא רונדרה ({proxy_plan['refused']})")
    except Exception as e:                      # noqa: BLE001 — a link is not only its delivery
        proxy_plan = {"rules": []}
        emit(f"אזהרה: תוכנית האספקה לא רונדרה ({e})")
    # ...and the FAR end's delivery, the consuming half. Without it the far office's edge has a route,
    # a tile and an alias (`bina.macbook`) that resolve to its link proxy, and nothing listening
    # there: the SSO gate answers 302 and the page behind it is a 502 (measured on vps1, 2026-10-01).
    far_delivery = _remote_delivery(office, home, direction, slot, emit)

    # The addresses this step MEASURES come from the pair the renderer just wrote, not from a document
    # rendered here: one pair per interface means "self"/"peers[0]" is a question about a pair.
    my_addr, peer_addr = _pair_addresses(office["id"], slot)
    remote_wg = must(office["machine"], "wg show wg0 2>/dev/null | head -3 || echo 'no wg0'", 60)
    # RETRIED, not asked once: this end's interface is brought up by the dgo-net sidecar, which
    # re-applies the rendered plan within ~15 seconds (it polls the file's mtime), so a single ping
    # right after the write measures the sidecar's timer rather than the tunnel. The far end is
    # already up — it was brought up by this step, synchronously.
    pong = _await_pong(office, my_addr)
    emit(f"tunnel {slot}: {my_addr} ↔ {peer_addr}")
    if "PONG" not in pong:
        # REPAIR BEFORE REPORTING. A flow this office's own NAT/router/engine-guest network blackholed
        # looks, from here, exactly like an office that is switched off — and it is repaired on the one
        # hop this office owns: the source port of its own tunnel. Measured 2026-10-06 on this Mac:
        # `wg show wg2` counted ~7 KiB of handshake initiations as sent, `tcpdump` on the machine showed
        # each 148-byte initiation leaving, the server's `tcpdump` captured NONE of them while control
        # packets on other source ports arrived, and `wg set wg2 listen-port 51900` handshook within
        # seconds. Asking the human to notice this is how the same outage ran twice in three days.
        try:
            import app as _app
            healed = _app.rotate_listen_port(office["id"], why="the tunnel did not pass a ping")
        except Exception as e:                          # noqa: BLE001 — a repair is not the tunnel
            healed = {"ok": False, "reason": f"{type(e).__name__}: {e}"}
        if healed.get("ok"):
            emit(f"{office['id']}: פורט המנהרה של הלשכה הזאת הוזז ל-{healed['port']} — בודק שוב")
            pong = _await_pong(office, my_addr)
        else:
            emit(f"{office['id']}: לא הוזז פורט ({healed.get('reason')})")
    if "PONG" not in pong:
        raise StepFailed(f"המנהרה לא מעבירה תנועה: {my_addr} לא ענה לפינג מן המכונה המרוחקת",
                         "בדוק UDP 51820 בכניסה למכונה המרוחקת ואת ה-Endpoint בהצהרה.",
                         remote_wg.strip())
    delivery = _home_delivery(office, home, direction, slot, my_addr, emit)   # the far record's own, never mirrored
    # And what the far office needs to USE a served agent API (DGO-32). The port is only half the
    # door: `agent.v1` authenticates every call with the app's own action token, and the office that
    # consumes it has no way to read a container that runs here. So the SERVING office hands the
    # credential over — into the peer's vault, through the two doors that already exist (`computers`
    # to the machine, and that machine's own connections container) — and never into a file of ours,
    # a screenshot, or a command line.
    credentials = _handoff_agents(office, home, direction, emit)
    return {"summary": f"מנהרה מול {office['id']} ({direction}): {my_addr} ↔ {peer_addr} · פינג חזר",
            "delivery": delivery, "far_delivery": far_delivery, "credentials": credentials,
            "identity": seeded, "office_id": office_id,
            "links": [{"office": office["id"], "direction": direction, "self": my_addr,
                       "peer": peer_addr, "wg": remote_wg.strip()}]}


def _home_delivery(office: dict, home: dict, direction: str, slot: int, my_addr: str, emit) -> dict:
    """The DELIVERY of the home's served ports, measured from the far machine (DGO-24): the tunnel
    passing a ping says nothing about whether a served port reaches the app behind it, and "the container
    is up" is not a link. Retried like the ping because the proxy re-reads its plan on a timer; reported
    rather than fatal, because the tunnel is up either way and the phase gate is where delivery must be
    green. Only for a far office that USES the home (`use`/`both`): on a `serve` link nothing of the
    home's is opened to it by design, and «0/3 open» stood beside DGO-1018's 502 as if it were broken."""
    if direction not in ("use", "both"):
        return {}
    delivery = {}
    import app as _app
    for app, port in sorted(_served_ports_local(home, slot, catalog.load_registry(_app.REGISTRY_DIR),
                                                peer=office["id"]).items()):
        probe = must(office["machine"],
                     f"for i in $(seq 1 8); do timeout 3 bash -c 'echo > /dev/tcp/{my_addr}/{port}' "
                     f"2>/dev/null && {{ echo OPEN; break; }}; sleep 4; done; echo END", 90)
        delivery[app] = {"port": port, "open": "OPEN" in probe}
    if delivery:
        got = sum(1 for d in delivery.values() if d["open"])
        emit(f"אספקה: {got}/{len(delivery)} פורטים פתוחים מן המכונה המרוחקת")
    return delivery


#: Where the far office's link proxy reads its plan: its own tunnel volume, mounted in its dgo-extend.
#: Written here only for a far office too old to have `SHIPPED_DIR` (see `_remote_delivery`).
FAR_PLAN = "/tunnel/link-proxy.json"

#: Run in the far office's dgo-extend: does it take shipped plans as inputs, and then render its one
#: plan now (its own pairs + every shipped plan) instead of at its next projection pass.
FAR_SHIPPED = ("import linkproxy;"
               "print('SHIPPED=' + str(getattr(linkproxy, 'SHIPPED_DIR', '')))")
FAR_RENDER = ("import app;"
              "p = app.render_link_proxy();"
              "print('RULES=%d' % len(p.get('rules') or []));"
              "print('REFUSED=' + str(p.get('refused') or p.get('shipped_refused') or ''))")

#: Run on the far machine, in its dgo-extend container: one request per rendered `use` rule, through
#: the link proxy BY NAME (`dgo-net`, the service whose namespace the proxy shares) — the same door the
#: far office's edge and CLI use. Any HTTP status is a delivery (a 401 is the peer's app answering);
#: only a refused or silent connection is not.
FAR_PROBE = r'''
import json, sys, time, urllib.request, urllib.error
want = json.loads(sys.argv[1]); got = {}
for _ in range(8):
    for port, path in want:
        if got.get(str(port), {}).get("code"):
            continue
        try:
            with urllib.request.urlopen(f"http://dgo-net:{port}{path}", timeout=6) as r:
                got[str(port)] = {"code": r.status}
        except urllib.error.HTTPError as e:
            got[str(port)] = {"code": e.code}
        except Exception as e:
            got[str(port)] = {"code": 0, "error": type(e).__name__}
    if all(v.get("code") for v in got.values()):
        break
    time.sleep(4)
print("FAR=" + json.dumps(got))
'''


def _remote_serve_map(office: dict, emit) -> dict:
    """What the FAR office declares it serves, read from its own app — never guessed here.

    The far end of a pair cannot render its own delivery plan (it holds no declaration of this office),
    so this side renders it: the tunnel, and now the door. But WHICH apps it serves is a declaration in
    that office's own volume, and a plan rendered from a guess is a door onto a name nobody promised.
    Read through the app's own module, so the answer is the same one its catalog publishes.
    """
    container = _remote_container(office, "dgo-extend-")
    if not container:
        return {}
    code = ("import json;import app as a;"
            "print('SERVE=' + json.dumps(a.cv.home_office().get('serve') or {}))")
    try:
        out = must(office["machine"], f"docker exec {q(container)} python3 -c {q(code)}", 90,
                   f"קריאת ה-`serve:` של {office['id']} נכשלה")
    except StepFailed as e:
        emit(f"אזהרה: לא ניתן לקרוא את ה-`serve:` של {office['id']} ({e.reason})")
        return {}
    raw = _fact_line(out, "SERVE")
    try:
        doc = json.loads(raw or "{}")
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


#: The door's other half on a machine whose tunnel is NOT in a container (DGO-32): a tiny TCP→unix
#: forwarder. It has no opinion about anything — it copies bytes between the tunnel address the peer
#: dials and the socket `dgo-link` listens on — and it is a systemd unit for the same reason the tunnel
#: is (`wg-quick@wg0`): a door that only exists while someone watches is not a door.
REMOTE_DOOR = r'''#!/usr/bin/env python3
"""The link door on the MACHINE (DGO-32). Rendered by apps/dgo-extend/converge.py — do not edit here.

Why this exists at all: on this machine the WireGuard interface belongs to the HOST (`wg-quick@wg0`),
so a packet addressed to this office's tunnel address terminates at the host's own stack. The office's
containers share a different namespace and cannot bind that address; this process can. It listens on
the address the peer dials and forwards every connection into a unix socket that `dgo-link` — which
DID share the tunnel container's namespace — listens on, and the office's own network is reached from
there by name. Delivery therefore stays by NAME on both sides of the bridge, and this file never
learns an app's address.

It has no opinion about the bytes: HTTP, a websocket or an upload all take the same path.
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DOORS = BASE / "doors.json"
SOCKETS = BASE / "doors"


def log(message):
    print("[dgo-door] " + message, flush=True)


def pump(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(client, path):
    try:
        up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        up.settimeout(10)
        up.connect(str(path))
        up.settimeout(None)
    except OSError as e:
        log("%s: nothing is listening (%s)" % (path.name, e))
        client.close()
        return
    a = threading.Thread(target=pump, args=(client, up), daemon=True)
    b = threading.Thread(target=pump, args=(up, client), daemon=True)
    a.start()
    b.start()
    a.join()
    b.join()
    for s in (client, up):
        try:
            s.close()
        except OSError:
            pass


def serve(door):
    path = SOCKETS / (door["socket"] + ".sock")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    while True:
        try:
            srv.bind((door["bind"], int(door["port"])))
            break
        except OSError as e:
            # The tunnel address may not be up yet (this unit is ordered after wg-quick@wg0, and the
            # interface can still be re-applying a plan). Retrying forever is right: the door is a
            # permanent thing, and systemd is not a watchdog for it.
            log("cannot listen on %s:%s (%s) — retrying" % (door["bind"], door["port"], e))
            time.sleep(10)
    srv.listen(64)
    log("listening %s:%s → %s" % (door["bind"], door["port"], path))
    clients = set(door.get("clients") or [])
    while True:
        try:
            client, addr = srv.accept()
        except OSError:
            break
        # Only the PEER dials this address through the tunnel, from its own end of the pair (the
        # rule's `clients`). A container on this machine reaches it over the docker bridge too, and
        # the door behind writes the peer's office on whatever it carries (DGO-1127). Staged: said
        # here first, refused once the log shows the peer never arrives from anywhere else.
        if clients and addr and addr[0] not in clients:
            log("%s:%s: a caller at %s is not this door's peer (%s) — would be refused"
                % (door["bind"], door["port"], addr[0], ", ".join(sorted(clients))))
        threading.Thread(target=handle, args=(client, path), daemon=True).start()


def main():
    try:
        doors = json.loads(DOORS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log("no readable doors.json (%s)" % e)
        return 1
    if not doors:
        log("no doors declared")
        return 0
    for door in doors:
        threading.Thread(target=serve, args=(door,), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
'''

#: The unit that runs it. Ordered after the tunnel it exists for, and restarted by systemd rather than
#: by a converge: a machine that reboots brings its door back without anybody converging it.
DOOR_UNIT = """[Unit]
Description=BINA digital office — the link door on the tunnel address
After=network-online.target wg-quick@wg0.service
Wants=wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 {path}/.dgo/link-door.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def _remote_doors(office: dict, plan: dict, emit) -> dict:
    """Install (or remove) the far MACHINE's door service, from the plan that was just rendered.

    Every rule whose bind is a unix socket is a door the machine has to carry: the plan names the
    socket and the address, this writes `doors.json` and the forwarder, and systemd runs it. When the
    plan has no socket rule the service is stopped and disabled — a door nobody declared must not keep
    listening, and "removed from the declaration" has to mean removed.
    """
    doors = []
    for rule in plan.get("rules") or []:
        bind = str(rule.get("bind") or "")
        if not bind.startswith("unix:"):
            continue
        doors.append({"bind": str(rule.get("host_bind") or ""),
                      "port": int(rule["port"]),
                      "socket": Path(bind[len("unix:"):]).stem,
                      "clients": [str(c) for c in (rule.get("clients") or [])]})
    files = {"link-door.py": REMOTE_DOOR,
             "doors.json": json.dumps(doors, indent=2) + "\n",
             "dgo-link-door.service": DOOR_UNIT.format(path=office["path"])}
    _ship(office, files)
    unit = "dgo-link-door.service"
    if not doors:
        must(office["machine"],
             f"mkdir -p {q(office['path'] + '/.dgo/doors')} && systemctl disable --now {unit} "
             f"2>/dev/null || true", 120, "עצירת שירות דלת הקישור נכשלה")
        return {"ok": True, "doors": 0, "stopped": True}
    must(office["machine"],
         f"mkdir -p {q(office['path'] + '/.dgo/doors')} && "
         f"install -m 644 {q(office['path'] + '/.dgo/dgo-link-door.service')} "
         f"/etc/systemd/system/{unit} && systemctl daemon-reload && "
         # The sidecar has to be running BEFORE the unit: it is the process that creates the sockets
         # the unit connects to. `up -d` is a no-op when nothing about it changed, and this is the one
         # place that brings it in line after the compose gained the socket directory.
         f"cd {q(office['path'])} && ./scripts/dc up -d dgo-link >/dev/null 2>&1 || true; "
         f"systemctl enable {unit} >/dev/null 2>&1; systemctl restart {unit}", 300,
         "התקנת שירות דלת הקישור על המכונה המרוחקת נכשלה")
    state = must(office["machine"], f"systemctl is-active {unit} || true", 60).strip()
    if state != "active":
        detail = must(office["machine"],
                      f"journalctl -u {unit} -n 8 --no-pager 2>/dev/null | tail -8 || true", 60)
        emit(f"אזהרה: שירות דלת הקישור ב-{office['id']} אינו פעיל ({state})")
        return {"ok": False, "doors": len(doors), "state": state, "log": detail.strip()}
    # MEASURED, not assumed: the door answers on the far machine's OWN tunnel address, with the Host an
    # app of that office is reached under. Any HTTP answer is delivery — the app's own SSO/redirect is
    # the app answering; a refused or silent connection is not delivery at all.
    probe = {"ok": False, "code": ""}
    host = _far_probe_host(office, emit)
    if host:
        out = must(office["machine"],
                   f"curl -s -o /dev/null -w '%{{http_code}}' -m 20 "
                   f"-H {q('Host: ' + host)} http://{q(doors[0]['bind'])}:{int(doors[0]['port'])}/ "
                   f"|| true", 90)
        probe = {"ok": bool(out.strip() and out.strip() != "000"), "code": out.strip()[:8], "host": host}
        emit(f"דלת הקישור ב-{office['id']}: {doors[0]['bind']}:{doors[0]['port']} → "
             f"{probe['code'] or 'אין תשובה'} (Host: {host})")
    return {"ok": True, "doors": len(doors), "state": state, "probe": probe}


def _far_probe_host(office: dict, emit) -> str:
    """One authority the far office serves, to aim the door's own measurement at.

    The door's proof has to be an HTTP request under a name that office answers to, and the name has to
    come from THAT office: its own `serve:` entry when it declared one, otherwise the authority its app
    manifest declares (`sso.default_host`) — the same fact its catalog publishes.
    """
    served = _remote_serve_map(office, emit)
    # The apps, never the declaration's reserved keys (`catalog.app_specs`): `shared: "*"` read as an
    # app id skipped the probe without a word (second reader, 2026-10-19).
    app_id = next((a for a in sorted(catalog.app_specs(served)) if a not in ("dgo-extend", catalog.WILDCARD)), "")
    if not app_id:
        # `serve: {"*": {}}` names no app of its own — and the wildcard KEY was taken for one, so the
        # probe asked for a host nobody declared and reported every working door as down (measured
        # 2026-10-02 on vps1). The catalog's own app is behind every door (the door routes by the
        # Host's first label), so the measurement asks for it.
        return "dgo-extend.localhost" if served else ""
    spec = served.get(app_id) or {}
    if isinstance(spec, dict) and str(spec.get("host") or "").strip():
        return str(spec["host"]).strip().lower()
    container = _remote_container(office, "dgo-extend-")
    if not container:
        return ""
    code = ("import json;import app as a;"
            f"m = a._app_manifest({app_id!r}) or {{}};"
            "print('HOST=' + json.dumps([str((r.get('sso') or {}).get('default_host') or '')"
            " for r in (m.get('routing') or [])]))")
    try:
        out = must(office["machine"], f"docker exec {q(container)} python3 -c {q(code)}", 60)
        hosts = json.loads(_fact_line(out, "HOST") or "[]")
    except (StepFailed, ValueError):
        return ""
    return next((str(h).strip().lower() for h in hosts if str(h).strip()), "")


def _remote_delivery(office: dict, home: dict, direction: str, slot: int, emit) -> dict:
    """Render the FAR end's delivery plan, ship it into its tunnel volume, install its door, probe it.

    The far end of a pair is rendered by the end that dials, exactly like its tunnel
    (`net.render(pair={side: 2}, host_forward=True)`): that office holds no declaration of this one,
    and the facts it needs are this one's — which end of the pair it holds, and (read from its own app)
    which apps it serves.

    Two shapes, because the far end's tunnel runs on its MACHINE:
      · the `use` half binds an address of its own OFFICE network and reaches `.1` through the host's
        routing — that half is a normal rule;
      · the `serve` half cannot bind its tunnel address (it is not in its container's namespace), so it
        is a UNIX SOCKET plus the address it stands for, and a small service on the machine carries it
        (`REMOTE_DOOR`).

    Written through the far office's OWN dgo-extend container, atomically, stamped `rendered_by`, into
    that office's INPUT directory (`linkproxy.SHIPPED_DIR/<this office>.json`) — never into the plan it
    renders: the far office writes that one itself, from its own pairs AND this file, and is asked to
    do it now. It used to be written over the rendered plan, which held only while the far office
    declared no pair of its own (vps1 paired with hp-laptop on 2026-10-12, and from then on its own
    render erased this plan within a minute of every converge). Reported, never fatal: the tunnel is
    up either way, and the summary says which door answers.
    """
    import catalog
    import linkproxy
    consumes = direction in ("use", "both")
    serves = direction in ("serve", "both")
    halves = tuple([h for h, on in (("serve", serves), ("use", consumes)) if on]) or ("use",)
    served = catalog.with_control(home.get("serve")) if consumes else {}
    far_serve = _remote_serve_map(office, emit) if serves else {}
    far_home = {"id": office["id"], "tunnel": {"slot": slot}, "serve": far_serve}
    as_peer = {"id": home["id"], "links": [{"office": office["id"], "direction": _mirror(direction)}]}
    # The far office's agent doors come from the catalog it PUBLISHES, the same facts its firewall
    # half is rendered from (`step_link`, DGO-1009): without them a far office that serves `*` got a
    # firewall that opened its agent ports and, here, no door behind them (DGO-1018).
    far_registry = None
    if serves:
        import app as _app
        far_registry = catalog.load_all(_app.STATE_DIR).get(office.get("id")) or None
    try:
        plan = linkproxy.build(far_home, [as_peer], {home["id"]: served}, side=2, halves=halves,
                               host_doors=serves, registry=far_registry)
    except linkproxy.LinkProxyError as e:
        emit(f"אזהרה: תוכנית האספקה של {office['id']} סורבה ({e})")
        return {"ok": False, "refused": str(e)}
    plan["rendered_by"] = home["id"]
    container = _remote_container(office, "dgo-extend-")
    if not container:
        emit(f"אזהרה: אין קונטיינר dgo-extend פעיל ב-{office['id']} — תוכנית האספקה לא נכתבה")
        return {"ok": False, "reason": "no dgo-extend container on the far machine"}
    b64 = base64.b64encode((json.dumps(plan, indent=2) + "\n").encode()).decode()
    inputs = _fact_line(must(office["machine"], f"docker exec {q(container)} python3 -c {q(FAR_SHIPPED)}",
                             60, f"קריאת גרסת dgo-extend ב-{office['id']} נכשלה"), "SHIPPED")
    target = f"/tunnel/{inputs}/{home['id']}.json" if inputs else FAR_PLAN
    must(office["machine"],
         f"echo {q(b64)} | base64 -d | docker exec -i {q(container)} sh -c "
         + q(f"mkdir -p {os.path.dirname(target)} && cat > {target}.new && mv {target}.new {target}"),
         60, f"כתיבת תוכנית האספקה ב-{office['id']} נכשלה")
    if inputs:
        out = must(office["machine"], f"docker exec {q(container)} python3 -c {q(FAR_RENDER)}", 120,
                   f"רינדור תוכנית האספקה ב-{office['id']} נכשל")
        refused = _fact_line(out, "REFUSED")
        emit(f"אספקה ב-{office['id']}: {_fact_line(out, 'RULES') or 0} כללים בתוכנית שלה"
             + (f" — סירוב: {refused}" if refused else ""))
    doors = _remote_doors(office, plan, emit)
    rules = plan.get("rules") or []
    if not rules:
        emit(f"אספקה ב-{office['id']}: אין אפליקציות לצרוך — תוכנית ריקה נכתבה")
        return {"ok": True, "rules": 0, "doors": {}, "machine_doors": doors}
    want = [[int(r["port"]), "/healthz" if r["app"] == "dgo-extend" else "/"]
            for r in rules if not str(r.get("bind") or "").startswith("unix:")]
    if not want:
        return {"ok": bool(doors.get("ok")), "rules": len(rules), "doors": {},
                "machine_doors": doors}
    out = must(office["machine"],
               f"docker exec {q(container)} python3 -c {q(FAR_PROBE)} {q(json.dumps(want))}", 90)
    doors_report = {}
    try:
        doors_report = json.loads(_fact_line(out, "FAR") or "{}")
    except ValueError:
        doors_report = {}
    by_port = {int(r["port"]): r["app"] for r in rules}
    answered = {p: d for p, d in doors_report.items() if (d or {}).get("code")}
    emit(f"אספקה ב-{office['id']}: {len(answered)}/{len(want)} דלתות עונות דרך ה-link proxy ("
         + ", ".join(f"{by_port.get(int(p), '?')}:{p}={(d or {}).get('code') or (d or {}).get('error')}"
                     for p, d in sorted(doors_report.items())) + ")")
    return {"ok": len(answered) == len(want), "rules": len(rules), "doors": doors_report,
            "machine_doors": doors}


def _fact_line(text: str, name: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(name + "="):
            return line[len(name) + 1:].strip()
    return ""


def _remote_container(office: dict, prefix: str) -> str:
    """The name of a running container on the REMOTE machine, by service prefix (`connections-`).

    By PREFIX and not by a composed name: the deployment's suffix is the remote office's own
    (`-staging` on vps1, `-local` here), and a name this office computes is a name that goes stale
    the day the far office is renamed. The machine answers, and an empty answer is a state the caller
    reports rather than a crash.
    """
    out = must(office["machine"],
               f"docker ps --format '{{{{.Names}}}}' | grep -m1 '^{prefix}' || true", 60)
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def own_container_id() -> str:
    """This container's id, as the vault's caller check reads it (platform-base/connections/identity.py):
    Docker mounts /var/lib/docker/containers/<id>/… into every container, so mountinfo names it."""
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


def vault_agent_token(app: str) -> str:
    """One app's agent token, read by THIS office's vault (`links.agent_token`). Raises `links.LinkError`."""
    import links as linkmod
    return linkmod.agent_token(app, own_container_id())


def _local_agent_token(app: str) -> str:
    """One app's own action token, read from its container HERE — the same trust as `docker exec`.

    A general name on purpose: `agent.v1` says where the token lives (`AGENT_TOKEN_FILE`) rather than
    which app serves it, and this asks the app's own container instead of a path on the host.

    It asks EVERY container carrying the app's compose label and takes the first that answers with a
    token file, because the label alone is not unique: a self-update helper (`bina-ds-self-update`,
    the PREVIOUS image, kept around for rollback) carries the same `com.docker.compose.service`
    label and no `AGENT_TOKEN_FILE` — and `docker ps -q … | head -1` picked it, so the handoff
    reported "reading the action token failed" while the app was running and healthy (measured
    2026-10-01 19:2x on this office, right after a self-update).

    The vault first (`links.agent_token`, DGO-1127): it reads the same file with the docker socket it
    already holds, and ssh to this office's own machine does not exist where there is no sshd (the
    HP). ssh stays as the second way, for a vault that predates the route.
    """
    import links as linkmod
    try:
        tok = vault_agent_token(app)
        if len(tok) >= 32:
            return tok
    except linkmod.LinkError as e:
        log.info("the vault did not read %s's agent token (%s) — asking the machine", app, e)
    script = (f"for c in $(docker ps -q --filter label=com.docker.compose.service={q(app)}); do "
              f"f=$(docker exec \"$c\" printenv AGENT_TOKEN_FILE 2>/dev/null || true); "
              f"if [ -n \"$f\" ]; then docker exec \"$c\" cat \"$f\" && exit 0; fi; done; "
              f"echo 'no running container of {app} exposes AGENT_TOKEN_FILE' >&2; exit 1")
    out = must(LOCAL_MACHINE, f"sh -c {q(script)}", 240, f"קריאת אסימון הפעולה של {app} נכשלה")
    return (out or "").strip().splitlines()[-1].strip() if (out or "").strip() else ""


def _remote_vault_put(office: dict, instance: dict) -> str:
    """Put one secret into the REMOTE office's vault — idempotently.

    The vault is the one place a credential of that office may live: reads are logged, a revoke is a
    deletion, and nothing is written into another office's files or into this app's own state. The
    transport is the fleet's door (`computers`) plus the peer's own connections container, which is
    the only process that may write its vault.
    """
    container = _remote_container(office, "connections-")
    if not container:
        raise StepFailed("לא נמצא קונטיינר כספת בלשכה המרוחקת",
                         "הרץ converge מלא — הלשכה המרוחקת צריכה קונטיינר connections פעיל.")
    payload = base64.b64encode(json.dumps(instance, ensure_ascii=False).encode()).decode()
    # The base carries NO trailing slash, and the paths do: `POST /api/instances/` is a 404 in this
    # app's own router (`/api/instances` is the route), and Flask answers that for a POST rather than
    # redirecting — so the handoff failed with "writing the key failed" while the GET beside it worked
    # (measured 2026-10-01 19:3x against vps1's live vault).
    inner = (
        "import base64,json,urllib.request,urllib.error\n"
        f"d=json.loads(base64.b64decode('{payload}').decode())\n"
        "base='http://127.0.0.1:8990/api/instances'\n"
        "def call(method,path,body=None):\n"
        "    req=urllib.request.Request(base+path,data=(json.dumps(body).encode() if body else None),\n"
        "        headers={'content-type':'application/json'},method=method)\n"
        "    with urllib.request.urlopen(req,timeout=25) as r: return json.loads(r.read() or b'{}')\n"
        "try:\n"
        "    call('GET', '/'+d['id']+'/secret')\n"
        "    have=True\n"
        "except urllib.error.HTTPError:\n"
        "    have=False\n"
        "out = call('PUT', '/'+d['id']+'/secret', {'secret': d['secret'], 'replace': True}) if have \\\n"
        "      else call('POST','', d)\n"
        "print(json.dumps({'id': d['id'], 'updated': have, 'ok': True}))"
    )
    return must(office["machine"], f"docker exec {container} python3 -c {q(inner)}", 180,
                "כתיבת המפתח לכספת הלשכה המרוחקת נכשלה")


def _handoff_agents(office: dict, home: dict, direction: str, emit) -> dict:
    """Hand the peer what it needs to reach the SERVED agent APIs, and say so either way.

    Only the office that serves has anything to hand over, and only for apps whose manifest declares
    an `agent.v1` capability. Reported rather than fatal: a link whose tunnel is up is a working
    link, and a credential that could not be written is a sentence the owner must read (`bbox agent`
    on the far side will refuse with the same name), not a converge that rolls back a tunnel.

    The instance carries the ADDRESS as well as the token (`10.79.<slot>.<this side>`, this office's
    own end of the pair), and its label — so the consuming office can resolve the agent from the
    credential plane alone. That is the door `bbox agent --office <office>` uses when the compiled
    `remote:`/`serve:` block is not on the machine yet, and it is a fact this side owns: the office
    that answers knows where it answers from.
    """
    if _mirror(direction) not in ("serve", "both"):
        return {}
    try:
        slot = _pair_slot(office, home)              # this pair's /24 — not the home's first one
    except (TypeError, ValueError):
        slot = 0
    address = f"10.79.{slot}.1" if slot else ""
    out: dict = {}
    for app, spec in sorted(catalog.app_specs(home.get("serve") or {}).items()):
        agent_port = spec.get("agent_api_port") if isinstance(spec, dict) else None
        if not agent_port:
            agent_port = _agent_port(_app_manifest(app))
        if not agent_port:
            continue
        iid = agent_instance(str(home.get("id") or "local"), app)
        try:
            token = _local_agent_token(app)
            if not token:
                raise StepFailed("האסימון ריק")
            _remote_vault_put(office, {
                "id": iid, "protocol": "dgo_link",
                "label": f"הסוכן של {home.get('label') or home.get('id')} — {app}",
                "account_hint": f"{office['id']}->{home['id']} agent:{app}",
                "secret": {"token": token, "office": home.get("id") or "local",
                           "label": home.get("label") or "", "peer": office["id"],
                           "app": app, "alias": app, "address": address,
                           "port": int(agent_port), "direction": "use",
                           "created_at": int(time.time())}})
            out[app] = {"instance": iid, "port": int(agent_port), "ok": True, "address": address}
            emit(f"מפתח הסוכן של {app} נמסר לכספת {office['id']} ({iid}"
                 + (f", {address}:{int(agent_port)}" if address else "") + ")")
        except StepFailed as e:
            out[app] = {"instance": iid, "port": int(agent_port), "ok": False, "reason": str(e)}
            emit(f"אזהרה: מפתח הסוכן של {app} לא נמסר ({e})")
    return out


def step_unlink(office: dict, ctx: dict, emit) -> dict:
    """Revoke — on BOTH ends, in one converge.

    A revoked link must not leave a reachable interface behind: the far end is told to take its tunnel
    down, this end's rendered files are removed (so dgo-net re-applies an empty plan), the link entry
    is dropped from the peer's declaration, and the link TOKENS in the vault are revoked with it.
    """
    home = home_office()
    link = _link_of(office, home["id"])
    _remote_down(office)
    # ONLY this pair's interface goes: `nftables.rules`, `addressing.json` and `edge-guard.json` are
    # rendered from EVERY pair, so deleting them would take a second link down with the one being
    # revoked — they are re-rendered below instead, without this peer in the list.
    removed = []
    slot = int((office.get("tunnel") or {}).get("slot") or 0)
    candidates = []
    if slot:
        candidates.append(Path(TUNNEL_DIR) / "pairs" / f"wg{slot}.conf")
    candidates.append(Path(TUNNEL_DIR) / "wg0.conf")   # the compatibility copy of the first pair
    for f in candidates:
        try:
            f.unlink()
            removed.append(str(f.relative_to(TUNNEL_DIR)))
        except OSError:
            pass
    try:
        import app as _app
        _app.render_tunnel()
        removed.append("re-rendered the remaining pairs")
    except Exception as e:                      # noqa: BLE001 — a revoke is not undone by a render
        log.warning("step_unlink: %r", e)
        emit("אזהרה: המנהרה לא רונדרה מחדש אחרי הביטול")
    if link:
        office["links"] = [l for l in (office.get("links") or [])
                           if (l or {}).get("office") != home["id"]]
        save_declaration(office)
    revoked = 0
    try:
        import links as linkmod
        for inst in (linkmod.find(home["id"], office["id"]) + linkmod.find(office["id"], home["id"])):
            if linkmod.revoke(inst.get("id")):
                revoked += 1
    except Exception as e:                      # noqa: BLE001 — the vault is a neighbour, not a step
        log.warning("step_unlink: %r", e)
        emit("אזהרה: לא ניתן לבטל את אסימוני הקישור")
    return {"summary": f"הקישור ל-{office['id']} בוטל משני הצדדים ({revoked} אסימונים בוטלו)",
            "removed": removed, "revoked": revoked}


# Every runner, in one place, AFTER the definitions: the registry used to sit above them and
# naming a runner defined later is a NameError at import — which is how a container that only
# advertises the step came up crash-looping instead of converging.
RUNNERS = {"machine": step_machine, "dns": step_dns, "backup": step_backup, "code": step_code,
           "engine": step_engine, "env": step_env, "state": step_state, "run": step_run,
           "accounts": step_accounts,
           "link": step_link, "unlink": step_unlink, "offsite": step_offsite,
           "health": step_health, "login": step_login, "publish": step_publish}
