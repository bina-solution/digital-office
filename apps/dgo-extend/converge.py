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
import ipaddress
import json
import logging
import os
import re
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

STEPS = ["machine", "dns", "backup", "code", "engine", "env", "login", "state", "run",
         "link", "health", "publish"]
#: Steps a caller may ask for BY NAME that are never part of a default converge: `unlink` takes a link
#: away, and a default run that revoked a tunnel because someone forgot an argument would be the worst
#: kind of helpful.
EXTRA_STEPS = ["unlink"]
STEP_TITLES = {
    "machine": "המחשב",
    "dns": "דומיין ו־DNS",
    "backup": "גיבוי לפני שדרוג",
    "code": "קוד הלשכה",
    "engine": "מנוע Docker",
    "env": "הגדרות (.env)",
    "login": "פרטי כניסה",
    "state": "האפליקציות",
    "run": "הפעלה (bbox run)",
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


def exec_on(machine: str, command: str, timeout: int = 120) -> dict:
    """Run a command ON the machine, through computers. Returns its dict verbatim."""
    try:
        return _http("POST", f"{COMPUTERS_URL}/api/computers/{machine}/exec",
                     {"command": command, "timeout": timeout}, timeout=timeout + 15)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"code": 255, "stdout": "", "stderr": str(e), "state": "error",
                "reason": "שירות המחשבים אינו זמין"}


def must(machine: str, command: str, timeout: int = 120, what: str = "") -> str:
    r = exec_on(machine, command, timeout)
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
    cmd = (f"set -e\numask 077\nmkdir -p {d}\nrm -f {d}/{name}.rc\n"
           f"echo {b64} | base64 -d > {d}/{name}.sh\n"
           f"nohup setsid bash -c 'umask 022; bash {d}/{name}.sh > {d}/{name}.log 2>&1; "
           f"echo $? > {d}/{name}.rc' </dev/null >/dev/null 2>&1 &\n")
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


def step_code(office: dict, ctx: dict, emit) -> dict:
    src = office.get("source") or {}
    repo, branch, commit = src.get("repo"), src.get("branch") or "", src.get("commit") or ""
    if not repo or not commit:
        raise StepFailed("להצהרה חסר מקור קוד (repo + commit)", "ערוך את הלשכה ובחר גרסה.")
    f = ctx.get("facts") or {}
    p = office["path"]
    auth = _auth_header(office)
    script = f"""
export GIT_TERMINAL_PROMPT=0
if ! command -v git >/dev/null; then apt-get update -q && apt-get install -y -q git; fi
# bbox's compiler (platform/manager/reconcile.py) needs python3 + PyYAML on the machine itself
python3 -c 'import yaml' 2>/dev/null || {{ apt-get update -q && apt-get install -y -q python3 python3-yaml; }}
P={q(p)}
if [ ! -d "$P/.git" ]; then
  mkdir -p "$(dirname "$P")"
  git {auth} clone --no-checkout {q(repo)} "$P"
fi
cd "$P"
git {auth} fetch --quiet origin {q(branch) if branch else ''} || git {auth} fetch --quiet origin
git cat-file -e {q(commit)}^{{commit}} 2>/dev/null || git {auth} fetch --quiet origin {q(commit)}
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
echo "HEAD=$(git rev-parse HEAD)"
"""
    start_detached(office, "code", script, secret=bool(auth))
    tail = wait_detached(office, "code", emit, limit=1800, every=5)
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


ENV_MERGE = r"""
import re, sys, datetime
env = open('.env').read()
have = {m.group(1) for m in re.finditer(r'^([A-Z0-9_]+)=', env, re.M)}
add = []
for ln in open('.env.ex').read().splitlines():
    m = re.match(r'^([A-Z0-9_]+)=', ln)
    if m and m.group(1) not in have:
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


def step_env(office: dict, ctx: dict, emit) -> dict:
    p = q(office["path"])
    fresh = exec_on(office["machine"], f"test -s {p}/.env", 20).get("code") != 0
    if fresh:
        name = re.sub(r"[^a-z0-9]", "", office["id"].lower())[:20] or "office"
        must(office["machine"],
             f"cd {p} && OFFICE_DOMAIN={q(office['domain'])} CI_DEPLOYMENT_NAME={q(name)} "
             f"bash scripts/ci-env.sh", 300, "יצירת ה־.env נכשלה")
    b64 = base64.b64encode(ENV_MERGE.encode()).decode()
    out = must(office["machine"], f"cd {p} && echo {b64} | base64 -d | python3 -", 60,
               "בדיקת ה־.env נכשלה")
    f = parse_facts(out)
    if f.get("DOMAIN") != office["domain"]:
        raise StepFailed(f"ה־.env על המחשב מוגדר לדומיין {f.get('DOMAIN')!r}, ההצהרה אומרת "
                         f"{office['domain']!r}",
                         "תקן את הדומיין בהצהרה, או את DEPLOYMENT_DOMAIN ב־.env שעל המחשב.")
    added = [k for k in (f.get("ADDED") or "").split(",") if k]
    norm = [k for k in (f.get("NORMALIZED") or "").split(",") if k]
    if norm:
        emit("הומר לערך מפורש: " + ", ".join(norm) + f" = {office['domain']}")
    ctx["deployment_name"] = f.get("NAME")
    return {"summary": ("נוצר חדש · " if fresh else "קיים · ") +
                       (f"נוספו {len(added)} מפתחות חדשים" if added else "שלם"),
            "added": added}


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
import yaml
declared = set("__DECLARED__".split(","))
s = yaml.safe_load(open("platform.state.yaml")) or {}
apps = s.get("apps") or {}
on = [k for k, v in apps.items()
      if (v or {}).get("enabled") is True or (v or {}).get("state") == "enabled"]
print(",".join(sorted(k for k in on if k not in declared)))
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
stop_app() {
  for s in $(python3 platform/manager/reconcile.py compose-services --app "$1" 2>/dev/null); do
    ids=$(docker ps -q --filter "label=com.docker.compose.service=$s" 2>/dev/null)
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
    start_detached(office, "run",
                   f"cd {q(office['path'])}\nBBOX_WAIT_TIMEOUT=${{BBOX_WAIT_TIMEOUT:-900}} ./bbox run\n")
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
                  f"ERROR: for |is already in use by container' {d}/run.log 2>/dev/null | head -8", 60)
    fails = [ln.strip() for ln in (bad.get("stdout") or "").splitlines() if ln.strip()]
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
            "containers": f, "warnings": warn, "notes": notes, "edge": code}


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
# this script, or systemd at boot — brings its rules with it. DELETE-THEN-APPLY and not `nft -f` alone:
# `nft -f` MERGES with whatever is loaded, so a second converge appended a second copy of every rule
# (measured on vps1, 2026-10-01) — the trap `tunnel-entrypoint.sh` answers the same way.
install -m 600 nftables.rules /etc/wireguard/dgo.nft
python3 - <<'PY' > /etc/wireguard/wg0.conf
import json, re
priv = json.load(open("identity.json", encoding="utf-8"))["wg"]["private"]
conf = open("wg0.conf", encoding="utf-8").read().replace("@PRIVATE@", priv)
hooks = ("PostUp = nft delete table inet dgo 2>/dev/null || true; nft -f /etc/wireguard/dgo.nft\\n"
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
    # `both` serves as well (see `_mirror`): testing for `serve` alone wrote an EMPTY block on a
    # bidirectional link, and the peer's compiler took its route, tile and alias away (measured
    # 2026-10-01 on vps1, the first converge after the link was made bidirectional).
    if _mirror((link or {}).get("direction") or "use") not in ("serve", "both"):
        return []
    served = home.get("serve") or {}
    if not served:
        return []
    slot = int((home.get("tunnel") or {}).get("slot") or 0)
    if not slot:
        return []
    domain = (home.get("domain") or "localhost").strip() or "localhost"
    default_to = _local_sso_user()
    entries = []
    for app, spec in sorted(served.items()):
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


def _served_ports_local(office: dict, slot: int | None = None) -> dict:
    """The ports a `serve` link opens HERE, from the apps this office's own record names.

    ONE door per link (DGO-32), plus the catalog and any app's agent API: an office whose registry
    holds four apps on 8080 cannot open a listener per app, so the door carries the UI doors and the
    Host header picks the app behind it (`linkproxy`). The catalog keeps its own port — it is how the
    peer learns which apps exist, and it cannot sit behind the door it describes — and an agent app's
    adapter keeps a port because a CLI addresses a port and not a name.

    An office that serves nothing returns an empty map: the firewall, the delivery plan and the peer's
    projection all read this one function, so "nothing served" cannot mean three different things.
    """
    served = catalog.with_control(office.get("serve"))
    if not served:
        return {}
    import linkproxy
    pair = int(slot or (office.get("tunnel") or {}).get("slot") or 0)
    if not pair:
        raise StepFailed(f"ללשכה {(office.get('id'))!r} אין slot מוצהר — אין פורט לדלת הקישור",
                         "הרץ קודם קישור (`bbox dgo link`) כדי שהזוג יקבל /24 משלו.")
    out = {linkproxy.DOOR_APP: linkproxy.door_port(pair),
           "dgo-extend": int(catalog.CATALOG_PORT)}
    for app, spec in served.items():
        if app == "dgo-extend":
            continue
        if isinstance(spec, dict) and spec.get("agent_api_port"):
            out[f"{app}:agent"] = int(spec["agent_api_port"])
    return out


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
    rendered = doc.get("rendered") if isinstance(doc, dict) else None
    if rendered is None or (isinstance(doc, dict) and doc.get("error")):
        raise StepFailed(str((doc or {}).get("error") or "רינדור המנהרה נכשל"),
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
    slot = int((home.get("tunnel") or {}).get("slot"))
    declared_endpoint = (office.get("tunnel") or {}).get("endpoint") or office.get("domain") or ""
    # The address to DIAL comes from the fleet first: `computers` already knows where that machine is
    # (`host: 31.97.196.82`), it is the same fact the SSH connection uses, and it does not depend on a
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
    for_home = {home["id"]: _served_ports_local({**office, "serve": far_serve}, slot)}
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
    # And the DELIVERY, measured from the far machine (DGO-24): the tunnel passing a ping says
    # nothing about whether a served port reaches the app behind it, and "the container is up" is not
    # a link. Retried like the ping because the proxy re-reads its plan on a timer; reported rather
    # than fatal, because the tunnel is up either way and the phase gate is where delivery must be
    # green.
    delivery = {}
    for app, port in sorted(_served_ports_local(home, slot).items()):
        probe = must(office["machine"],
                     f"for i in $(seq 1 8); do timeout 3 bash -c 'echo > /dev/tcp/{my_addr}/{port}' "
                     f"2>/dev/null && {{ echo OPEN; break; }}; sleep 4; done; echo END", 90)
        delivery[app] = {"port": port, "open": "OPEN" in probe}
    if delivery:
        got = sum(1 for d in delivery.values() if d["open"])
        emit(f"אספקה: {got}/{len(delivery)} פורטים פתוחים מן המכונה המרוחקת")
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


#: Where the far office's link proxy reads its plan: its own tunnel volume, mounted in its dgo-extend.
FAR_PLAN = "/tunnel/link-proxy.json"

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
    while True:
        try:
            client, _addr = srv.accept()
        except OSError:
            break
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
                      "socket": Path(bind[len("unix:"):]).stem})
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
    app_id = next((a for a in sorted(served) if a not in ("exclude", "dgo-extend", catalog.WILDCARD)), "")
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

    Written through the far office's OWN dgo-extend container, the one writer of its tunnel volume,
    atomically (a proxy polling the file never reads half a plan), and stamped `rendered_by` so that
    office's own renderer leaves a plan it did not make alone. Reported, never fatal: the tunnel is up
    either way, and the summary says which door answers.
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
    try:
        plan = linkproxy.build(far_home, [as_peer], {home["id"]: served}, side=2, halves=halves,
                               host_doors=serves)
    except linkproxy.LinkProxyError as e:
        emit(f"אזהרה: תוכנית האספקה של {office['id']} סורבה ({e})")
        return {"ok": False, "refused": str(e)}
    plan["rendered_by"] = home["id"]
    container = _remote_container(office, "dgo-extend-")
    if not container:
        emit(f"אזהרה: אין קונטיינר dgo-extend פעיל ב-{office['id']} — תוכנית האספקה לא נכתבה")
        return {"ok": False, "reason": "no dgo-extend container on the far machine"}
    b64 = base64.b64encode((json.dumps(plan, indent=2) + "\n").encode()).decode()
    must(office["machine"],
         f"echo {q(b64)} | base64 -d | docker exec -i {q(container)} sh -c "
         + q(f"cat > {FAR_PLAN}.new && mv {FAR_PLAN}.new {FAR_PLAN}"),
         60, f"כתיבת תוכנית האספקה ב-{office['id']} נכשלה")
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
    """
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
    slot = int((home.get("tunnel") or {}).get("slot") or 0)
    address = f"10.79.{slot}.1" if slot else ""
    out: dict = {}
    for app, spec in sorted((home.get("serve") or {}).items()):
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
           "link": step_link, "unlink": step_unlink,
           "health": step_health, "login": step_login, "publish": step_publish}
