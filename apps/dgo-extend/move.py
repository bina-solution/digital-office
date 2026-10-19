"""dgo-extend.move — move an app that runs HERE to another office, WITH its data.

Placement alone (see peers.py) moves an app's CONTAINERS: the app starts on the remote office and its
tile stays in the home rail, but its volumes stay behind, so an app with state arrives empty. This is
the missing half: stop it here, carry each declared volume across, start it there, and only then
publish it — with a restore point taken BEFORE anything stops, and a rollback that puts it back.

What it is careful about
------------------------
- **A backup first, and it must fit.** Each of the app's own volumes is tarred on THIS machine into
  `~/.digital-office/move-<app>-<ts>/` before the app is stopped, and the transfer is refused when
  the destination cannot hold it. A move that loses the only copy of a library is not a move.
- **The declaration is the switch, and it is written LAST.** The app is enabled on the target only
  after its data is there, so a crash midway leaves a stopped app HERE with its data intact — not an
  app that is running in two places with half a library each.
- **Rollback is a step, not an apology.** If anything fails from the transfer onwards, the
  declaration is reverted, the volumes are restored from the backup, and the app is started here
  again; the run ends `error` and says exactly what was undone.

Where the bytes go: `computers` owns the fleet and the key, so the copy is one op there
(`POST /api/computers/<src>/transfer`, see apps/computers/transfer.py) — this app never holds a
credential for either machine.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import traceback
import urllib.error
from pathlib import Path

import converge as cv

log = logging.getLogger("dgo-extend.move")

STEPS = ["preflight", "backup", "stop", "transfer", "enable", "verify"]
STEP_TITLES = {
    "preflight": "בדיקות מקדימות",
    "backup": "גיבוי כאן",
    "stop": "עצירה כאן",
    "transfer": "העברת הנתונים",
    "enable": "הפעלה בלשכה המרוחקת",
    "verify": "אימות",
}
LOCAL_MACHINE = "computer_local-local"
HOME_REPO = os.environ.get("DGO_HOME_REPO", "")
STATE_DIR = Path(os.environ.get("DGO_STATE_DIR", "/data"))
JOB_DIR = STATE_DIR / "moves"
VOL_ROOT = "/var/lib/docker/volumes"
#: Room for the copy plus the tar the destination unpacks while it streams.
DEST_HEADROOM = float(os.environ.get("OFFICES_MOVE_HEADROOM", "1.25"))
#: The remote needs this much RAM free before an app is put on it (measured, not assumed).
REMOTE_MIN_MB = int(os.environ.get("OFFICES_MOVE_MIN_MB", "500"))


class MoveFailed(Exception):
    def __init__(self, reason: str, action: str = "", detail: str = ""):
        super().__init__(reason)
        self.reason, self.action, self.detail = reason, action, detail


def _exec(machine: str, command: str, timeout: int = 120, what: str = "") -> str:
    return cv.must(machine, command, timeout, what)


def _facts(machine: str, command: str, timeout: int = 120) -> dict:
    return cv.parse_facts(_exec(machine, command, timeout))


def local(command: str, timeout: int = 120, what: str = "") -> str:
    if not HOME_REPO:
        raise MoveFailed("DGO_HOME_REPO אינו מוגדר", "bbox מגדיר אותו.")
    return _exec(LOCAL_MACHINE, f"cd {cv.q(HOME_REPO)} && {command}", timeout, what)


def _manifest_path(app: str) -> str:
    """Where an app's manifest is, as the checkout lays it out: layer-3 apps live under `apps/`, the
    substrate under `platform-base/` — and the office's IDENTITY and its VAULT are substrate apps, so
    a move that could only read `apps/` could not carry the two volumes a whole-office move exists
    for."""
    for base in ("apps", "platform-base"):
        rel = f"{base}/{app}/app.json"
        if local(f"test -f {cv.q(rel)} && echo yes || echo no", 30).strip().endswith("yes"):
            return rel
    raise MoveFailed(f"לא נמצא מניפסט ל-{app}",
                     "אפליקציה מצהירה app.json תחת apps/ או platform-base/.")


def _app_volumes(app: str, have: list[str] | None = None) -> list[str]:
    """The volumes the app DECLARES (`data.volumes`), as docker names on this machine.

    Declared, not discovered: a volume the app does not declare in its app.json is not the app's to
    carry, and a name that does not exist on this machine is reported instead of silently skipped.
    `have` is the machine's volume list, passed in by a caller that already asked for it — one
    `docker volume ls` per APP is the difference between a plan that takes seconds and one that takes
    minutes."""
    raw = json.loads(local(f"cat {cv.q(_manifest_path(app))}", 30, "לא ניתן לקרוא את המניפסט"))
    declared = list((raw.get("data") or {}).get("volumes") or [])
    if not declared:
        return []
    if have is None:
        have = _exec(LOCAL_MACHINE, "docker volume ls --format '{{.Name}}'", 60,
                     "לא ניתן לקרוא את ה-volumes").split()
    out = []
    for want in declared:
        name = want if isinstance(want, str) else (want or {}).get("name")
        match = next((h for h in have if h == name or h.endswith("_" + name)), None)
        if not match:
            raise MoveFailed(f"ה-volume „{name}” של {app} לא נמצא במכונה הזאת",
                             "ייתכן שהאפליקציה טרם רצה כאן, או שהיא מצהירה volume אחר.")
        out.append(match)
    return out


def _dest_project(machine: str, path: str) -> str:
    """The destination's compose project name — its volumes are named `<project>_<volume>`."""
    out = _exec(machine,
                "docker ps --format '{{.Label \"com.docker.compose.project\"}}' | "
                "grep -v '^$' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}'", 60).strip()
    if out:
        return out
    return re.sub(r"[^a-z0-9-]", "", os.path.basename(path).lower()) or "deployment-hacohen"


def _services(machine: str, app: str, path: str) -> list[str]:
    out = _exec(machine, f"cd {cv.q(path)} && python3 platform/manager/reconcile.py "
                         f"compose-services --app {cv.q(app)}", 60)
    return [s.strip() for s in out.split() if s.strip()]


def _stop_services(machine: str, services: list[str], emit) -> list[str]:
    """Stop the containers of these compose services. Returns what was actually running."""
    stopped = []
    for svc in services:
        ids = _exec(machine, f"docker ps -q --filter label=com.docker.compose.service={cv.q(svc)}",
                    60).split()
        if not ids:
            continue
        _exec(machine, "docker stop " + " ".join(ids), 180)
        stopped.append(svc)
        emit(f"הופסק {svc}")
    return stopped


def _start_services(machine: str, services: list[str], emit) -> None:
    for svc in services:
        ids = _exec(machine, f"docker ps -aq --filter label=com.docker.compose.service={cv.q(svc)}",
                    60).split()
        if ids:
            _exec(machine, "docker start " + " ".join(ids), 180)
            emit(f"הוחזר לפעילות {svc}")


# ── the steps ───────────────────────────────────────────────────────────────────
def _same_commit(a: str, b: str) -> bool:
    """Are these two revisions the same commit? Compared as prefixes, because a declaration records
    the short sha (`719537ab`) while `git rev-parse HEAD` answers with the full one — and a six-char
    comparison would call two different commits equal, which is the whole thing being checked."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    n = min(len(a), len(b))
    return n >= 7 and a[:n] == b[:n]


def _dirty_app_files(app: str, dirty_paths: list[str] | None = None) -> list[str]:
    """Uncommitted changes to the app's OWN files at home. Empty when the app matches a commit.

    A move carries the app's DECLARATION (app.json) and its containers' code to a machine that checks
    out a COMMIT — so an app that is edited here and not committed there is a different app on the two
    sides. This is checked, not assumed: the same rule as everywhere else in this repo, a machine
    builds what git says, not what is in someone's working tree. `dirty_paths` is one whole working
    tree's status, passed in by a caller planning many apps."""
    if dirty_paths is None:
        dirty_paths = [ln.strip() for ln in
                       local("git status --porcelain | head -400", 60).splitlines() if ln.strip()]
    wants = (f"apps/{app}/", f"platform-base/{app}/")
    return [ln for ln in dirty_paths if ln.split(maxsplit=1)[-1].startswith(wants)]


def _app_dir(app: str) -> str:
    """The directory the app lives in (`apps/<id>` or `platform-base/<id>`)."""
    return _manifest_path(app).rsplit("/", 1)[0]


def _tree_at(commit: str, path: str) -> str:
    """The git tree hash of one directory at one commit, or "" when it cannot be read.

    THE precision that matters for a move: the far side builds the app from ITS commit, so what has to
    be equal on both sides is the app's own directory — not the whole checkout. Comparing whole commits
    refuses a move because an unrelated app changed, which is the normal state of this repository (it
    is being worked on from several lanes at once), and that refusal protects nothing."""
    if not commit or not path:
        return ""
    out = local(f"git rev-parse {cv.q(commit + ':' + path)} 2>/dev/null || true", 30)
    return (out or "").strip().splitlines()[-1].strip() if out.strip() else ""


def _enabled_apps() -> list[str]:
    """This office's ENABLED apps, from the compiler's own answer (`reconcile.py plan --json`).

    Read rather than assumed: an app that is disabled or archived here has nothing to move, and a move
    that silently enables it on the far side (and re-enables it here if it fails) is a change nobody
    asked for."""
    out = local("python3 platform/manager/reconcile.py plan --json 2>/dev/null", 180,
                "לא ניתן לקרוא את מצב הלשכה")
    try:
        return list(json.loads(out).get("enabled") or [])
    except ValueError:
        return []


def _step_preflight(office: dict, app: str, ctx: dict, emit) -> dict:
    if office["machine"] == LOCAL_MACHINE:
        raise MoveFailed("המכונה של הלשכה היא המכונה הזאת", "")
    enabled = ctx.get("enabled_apps")
    if enabled is None:
        enabled = _enabled_apps()
    ctx["enabled_apps"] = enabled
    ctx["prior_enabled"] = app in enabled
    if not ctx["prior_enabled"] and not ctx.get("allow_disabled"):
        raise MoveFailed(
            f"{app} אינה מופעלת בלשכה הזאת — אין מה להעביר, וההעברה תפעיל אותה ביעד",
            f"הפעל אותה קודם (bbox apps enable {app}) או בחר אפליקציה אחרת. "
            f"לעקיפה מודעת: allow_disabled=true.")
    # ── decision 11: both offices on the SAME commit, or no move ────────────────
    # The app's containers on the far side are built from the commit that office has checked out. Two
    # different commits are two different app.jsons — so this is refused before anything stops, and
    # the refusal names the sha to converge to instead of leaving the operator to work it out.
    home_commit = ctx.get("home_commit")
    if not home_commit:
        home_commit = local("git rev-parse HEAD", 60, "לא ניתן לקרוא את הקומיט של הלשכה הזאת").strip()
        home_commit = home_commit.splitlines()[-1].strip() if home_commit else ""
    declared = ((office.get("source") or {}).get("commit") or "").strip()
    ctx["home_commit"], ctx["declared_commit"] = home_commit, declared
    app_dir = _app_dir(app)
    home_tree = _tree_at(home_commit or "HEAD", app_dir)
    remote_tree = _tree_at(declared, app_dir) if declared else ""
    ctx["app_tree"], ctx["remote_app_tree"] = home_tree, remote_tree
    if not declared:
        emit(f"⚠ ללשכה {office['id']} אין קומיט מוצהר — מדלגים על בדיקת הזהות בין הלשכות")
    elif _same_commit(home_commit, declared):
        emit(f"קומיט: בית {home_commit[:12]} · יעד {declared[:12]} — אותו קומיט")
    elif remote_tree and home_tree and remote_tree == home_tree:
        emit(f"קומיטים שונים ({declared[:12]} מול {home_commit[:12]}) אבל {app_dir} זהה בהם — ממשיך")
    elif not ctx.get("allow_mismatch"):
        differs = "שונה" if (remote_tree and home_tree) else "לא ניתן להשוות"
        raise MoveFailed(
            f"האפליקציה עצמה {differs} בין הלשכות: {app_dir} בקומיט {declared[:12]} מול "
            f"{home_commit[:12]} בבית — ההעברה תעביר נתונים לאפליקציה אחרת",
            f"הבא את {office['id']} לאותו קומיט (bbox dgo converge {office['id']} "
            f"source.commit={home_commit[:12]}) והרץ שוב. לעקיפה מודעת: allow_mismatch=true.")

    dirty = _dirty_app_files(app, ctx.get("dirty_paths"))
    if dirty and not ctx.get("allow_mismatch"):
        raise MoveFailed(
            f"ל-{app} יש שינויים שלא קומטו כאן ({len(dirty)} קבצים) — "
            f"ביעד היא תיבנה מהקומיט, כלומר תהיה אפליקציה אחרת",
            f"קומט ודחף את apps/{app}, הבא את הלשכה המרוחקת לאותו קומיט, והרץ שוב.",
            detail="\n".join(dirty[:10]))

    volumes = _app_volumes(app, ctx.get("have_volumes"))
    ctx["app_volumes"] = volumes
    # One `du` per volume, keyed by the volume that was asked for rather than by parsing the path out
    # of du's output: a path with a space in it parses wrong, and a wrong size is what a disk-space
    # preflight is made of.
    sizes = {}
    for vol in volumes:
        out = _exec(LOCAL_MACHINE, f"du -sb {VOL_ROOT}/{cv.q(vol)}/_data 2>/dev/null | cut -f1 || echo 0",
                    180).strip().splitlines()
        sizes[vol] = int(out[0]) if out and out[0].strip().isdigit() else 0
    total = sum(sizes.values()) or 0
    ctx["sizes"] = sizes
    ctx["total_bytes"] = total

    local_free = int(_facts(LOCAL_MACHINE, "df -BG --output=avail / | tail -1 | tr -dc 0-9").get("avail") or 0)
    if local_free and total and local_free < (total * DEST_HEADROOM) / (1024 ** 3):
        raise MoveFailed(
            f"אין מקום כאן לגיבוי לפני העברה ({total / 1024 ** 3:.1f}GB נדרשים, {local_free}GB פנויים)",
            "פנה מקום במכונת הלשכה, או העבר volume אחד בכל פעם.")
    rec = ctx.get("machine_record") or cv.machine_record(office["machine"])
    mem_free_mb = int((rec.get("memory") or {}).get("available", 0)) / (1024 ** 2)
    disk_free_gb = int((rec.get("disk") or {}).get("available", 0)) / (1024 ** 3)
    if mem_free_mb and mem_free_mb < REMOTE_MIN_MB:
        raise MoveFailed(
            f"בלשכה המרוחקת רק {int(mem_free_mb)}MB זיכרון פנוי (צריך {REMOTE_MIN_MB}MB)",
            "כבה שם אפליקציות שאינן בשימוש (למשל glitchtip) והרץ שוב.")
    if disk_free_gb and total and disk_free_gb < (total * DEST_HEADROOM) / (1024 ** 3):
        raise MoveFailed(
            f"אין מקום בלשכה המרוחקת ({total / 1024 ** 3:.1f}GB נדרשים, {disk_free_gb:.0f}GB פנויים)",
            "פנה מקום בשרת והרץ שוב.")
    project = ctx.get("dest_project") or _dest_project(office["machine"], office["path"])
    ctx["dest_project"] = project
    emit(f"{len(volumes)} volumes · {total / 1024 ** 2:.0f}MB · יעד {project} · "
         f"{int(mem_free_mb)}MB זיכרון ו-{disk_free_gb:.0f}GB דיסק פנויים שם")
    return {"summary": f"{len(volumes)} volumes, {total / 1024 ** 2:.0f}MB · יעד {project}",
            "volumes": volumes, "bytes": total, "dest_project": project,
            "remote_mem_mb": int(mem_free_mb), "remote_disk_gb": round(disk_free_gb, 1)}


def _step_backup(office: dict, app: str, ctx: dict, emit) -> dict:
    """A restore point on THIS machine, taken while the app still runs."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    d = f"$HOME/.digital-office/move-{app}-{stamp}"
    script = [f"set -e", f'D={d}', 'mkdir -p "$D"']
    for vol in ctx["app_volumes"]:
        script.append(f'echo "── tar {vol}"; tar czf "$D/{vol}.tgz" -C {VOL_ROOT}/{vol}/_data . '
                      f'|| [ $? = 1 ]')
    script.append('du -sh "$D" | cut -f1')
    out = _exec(LOCAL_MACHINE, "\n".join(script), 3600, "הגיבוי לפני ההעברה נכשל")
    ctx["backup_dir"] = d.replace("$HOME", "/root")
    emit(f"גיבוי: {ctx['backup_dir']} ({out.strip().splitlines()[-1] if out.strip() else '?'})")
    return {"summary": f"{ctx['backup_dir']} ({out.strip().splitlines()[-1] if out.strip() else '?'})",
            "backup_dir": ctx["backup_dir"]}


def _step_stop(office: dict, app: str, ctx: dict, emit) -> dict:
    services = _services(LOCAL_MACHINE, app, HOME_REPO)
    ctx["services"] = services
    ctx["stopped"] = _stop_services(LOCAL_MACHINE, services, emit)
    if not ctx["stopped"]:
        emit("לא נמצאו קונטיינרים רצים כאן — ממשיך")
    return {"summary": f"הופסקו {len(ctx['stopped'])} שירותים" if ctx["stopped"] else "לא היו רצים",
            "stopped": ctx["stopped"]}


def _transfer_one(ctx: dict, machine: str, src_vol: str, dest_vol: str, emit) -> int:
    """One volume, through computers' streaming op, polled to completion.

    `/stream` (apps/computers/transfer.py) resumes at the byte offset the destination already holds,
    so a link that drops — or this office restarting mid-move — costs the bytes that were in flight
    and not the whole volume. That is what makes a 12GB move a thing we can attempt at all."""
    import urllib.request
    body = json.dumps({"to": machine, "volume": src_vol, "dest_volume": dest_vol,
                       "restart": bool(ctx.get("re_transfer"))}).encode()
    req = urllib.request.Request(cv.COMPUTERS_URL + f"/api/computers/{LOCAL_MACHINE}/stream",
                                 data=body, headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:        # `computers` answered — what it said is the report
        raise MoveFailed(f"לא ניתן להתחיל העברה של {src_vol}",
                         e.read().decode("utf-8", "replace")[:300] or f"HTTP {e.code}")
    except Exception as e:                     # noqa: BLE001 — the reason is the report
        raise MoveFailed(f"לא ניתן להתחיל העברה של {src_vol}", str(e)[:200])
    job = (res or {}).get("job") or {}
    jid = job.get("id")
    if not jid:
        raise MoveFailed(f"ההעברה של {src_vol} לא החלה", json.dumps(res, ensure_ascii=False)[:200])
    resume_from = int(job.get("resumed_from") or 0)
    if resume_from:
        emit(f"   {src_vol}: ממשיך מ-{resume_from / 1024 ** 2:.0f}MB שכבר ביעד")
    last, started, last_line, done = 0, time.time(), "", 0
    while True:
        time.sleep(5)
        # The deadline comes FIRST. It used to sit under the poll, whose failure `continue`d past
        # it — so a poll that failed every time (a job `computers` no longer knows answers 404
        # for ever) was a move that never ended and never said why.
        if time.time() - started > 6 * 3600:
            raise MoveFailed(f"ההעברה של {src_vol} לא הסתיימה בשש שעות",
                             f"הרץ שוב — ההמשך מאותה נקודה ({done} בתים כבר ביעד).")
        try:
            with urllib.request.urlopen(cv.COMPUTERS_URL + f"/api/transfers/{jid}", timeout=30) as r:
                row = (json.loads(r.read() or b"{}") or {}).get("transfer") or {}
        except urllib.error.HTTPError as e:
            if e.code == 404:                  # `computers` answered: it has no such job any more
                raise MoveFailed(f"ההעברה של {src_vol} נעלמה מרשימת ההעברות של המחשבים",
                                 e.read().decode("utf-8", "replace")[:300])
            continue
        except Exception:                      # noqa: BLE001 — a poll that fails is not a failure
            continue
        done = int(row.get("done_bytes") or row.get("bytes") or 0)
        if done - last > 50 * 1024 * 1024:
            last = done
            pct = row.get("percent")
            eta = row.get("eta_s")
            line = (f"   {src_vol}: {done / 1024 ** 2:.0f}MB"
                    + (f" ({pct:.0f}%)" if pct else "")
                    + (f" · נותרו ~{int(eta) // 60}ד׳{int(eta) % 60:02d}שנ׳" if eta else ""))
            if line != last_line:
                last_line = line
                emit(line)
        if row.get("state") == "ok":
            emit(f"   {src_vol}: הועבר ({done / 1024 ** 2:.0f}MB ב-{int(time.time() - started)}s)")
            return done
        if row.get("state") in ("error", "cancelled"):
            if row.get("error_code") == "source_changed" and not ctx.get("re_transfer"):
                # The volume moved under a half-finished copy (the app ran again after a rolled-back
                # attempt). For a move, "the volume as it is now" is the only thing worth carrying,
                # so start that volume over — once.
                emit(f"   {src_vol}: התוכן השתנה מאז הניסיון הקודם — מתחיל את ההעברה מהתחלה")
                ctx["re_transfer"] = True
                return _transfer_one(ctx, machine, src_vol, dest_vol, emit)
            raise MoveFailed(f"ההעברה של {src_vol} נכשלה",
                             (row.get("error") or row.get("state") or "")[:300])


def _step_transfer(office: dict, app: str, ctx: dict, emit) -> dict:
    done = {}
    for vol in ctx["app_volumes"]:
        dest = f"{ctx['dest_project']}_{vol.split('_', 1)[1] if '_' in vol else vol}"
        emit(f"── {vol} → {dest}")
        done[vol] = _transfer_one(ctx, office["machine"], vol, dest, emit)
    ctx["transferred"] = done
    return {"summary": f"{len(done)} volumes הועברו ({sum(done.values()) / 1024 ** 2:.0f}MB)",
            "volumes": done}


def _step_enable(office: dict, app: str, ctx: dict, emit) -> dict:
    """Write the declaration — enable on the target and place it — then converge that office.

    The declaration is written HERE, last, so a failure before this point leaves the app stopped at
    home with everything intact."""
    import app as A                              # the office store lives in the app module
    o = A.load(office["id"])
    # What the declaration said BEFORE we touch it, so the rollback can put it back EXACTLY — an app
    # the declaration did not mention must not be left behind as an explicit "disabled" row, which is
    # a different statement about that office than silence.
    ctx.setdefault("prior_decl", {"apps": dict(o.get("apps") or {}),
                                  "placement": list(o.get("placement") or [])})
    o.setdefault("apps", {})[app] = "enabled"
    o["placement"] = sorted(set(o.get("placement") or []) | {app})
    A.save(o)
    emit("ההצהרה עודכנה — מפעיל בלשכה המרוחקת")
    ctx.setdefault("declaration_written", True)
    for name in ("state", "run", "health", "publish"):
        emit(f"── {cv.STEP_TITLES[name]}")
        res = cv.RUNNERS[name](o, ctx, emit)
        emit(f"✓ {res.get('summary', '')}")
    return {"summary": "ההצהרה עודכנה והלשכה converged"}


def _step_verify(office: dict, app: str, ctx: dict, emit) -> dict:
    services = _services(office["machine"], app, office["path"])
    running = []
    for svc in services:
        ids = _exec(office["machine"],
                    f"docker ps -q --filter label=com.docker.compose.service={cv.q(svc)}", 60).split()
        if ids:
            running.append(svc)
    if not running:
        raise MoveFailed(f"{app} לא עלה בלשכה המרוחקת",
                         "בדוק את שלב ההרצה בלוג של ה-converge.")
    return {"summary": f"{len(running)}/{len(services)} שירותים רצים שם: {', '.join(running)}",
            "running": running}


def _rollback(office: dict, app: str, ctx: dict, emit) -> None:
    """Put it back: the declaration, the volumes, and the app itself."""
    prior = ctx.get("prior_decl")
    if prior is None:
        # `enable` never ran, so the declaration was never touched — and a rollback that writes to it
        # anyway is not an undo, it is a NEW change: it added a row for an app the declaration did not
        # name (measured: 22 apps became 23). Nothing to put back, so nothing is written.
        emit("ההצהרה ביעד לא נגעה בהעברה הזאת — אין מה להחזיר")
    try:
        import app as A
        o = A.load(office["id"])
        apps = dict(o.get("apps") or {})
        if prior is not None:
            was = (prior.get("apps") or {}).get(app, "") if app in (prior.get("apps") or {}) else None
            if was is None:
                apps.pop(app, None)
            else:
                apps[app] = was
            o["apps"] = apps
            o["placement"] = list(prior.get("placement") or [])
        else:
            apps[app] = "disabled"
            o["apps"] = apps
            o["placement"] = [x for x in (o.get("placement") or []) if x != app]
        if prior is not None:
            A.save(o)
            emit("ההצהרה הוחזרה למה שהיה — האפליקציה אינה מוצהרת ללשכה המרוחקת")
    except Exception as e:                       # noqa: BLE001
        emit(f"⚠ החזרת ההצהרה נכשלה: {e}")
    d, volumes = ctx.get("backup_dir"), ctx.get("app_volumes") or []
    if d and volumes:
        script = ["set -e"]
        for vol in volumes:
            script.append(f'echo "── restore {vol}"; '
                          f'rm -rf {VOL_ROOT}/{vol}/_data/* 2>/dev/null || true; '
                          f'tar xzf {d}/{vol}.tgz -C {VOL_ROOT}/{vol}/_data')
        try:
            _exec(LOCAL_MACHINE, "\n".join(script), 3600)
            emit("ה-volumes שוחזרו מהגיבוי")
        except Exception as e:                   # noqa: BLE001
            emit(f"⚠ שחזור ה-volumes נכשל: {e}. הגיבוי נמצא ב-{d}")
    # The destination's half-finished archive belongs to a source state that no longer exists (the
    # volumes above were just restored from the backup), so it is discarded — keeping it would make
    # the next attempt refuse on a fingerprint mismatch, or splice two archives into one.
    project = ctx.get("dest_project")
    for vol in volumes:
        dest = f"{project}_{vol.split('_', 1)[1] if '_' in vol else vol}" if project else None
        if not dest:
            continue
        try:
            _exec(office["machine"], f"rm -f /var/lib/bina-transfer/{cv.q(vol)}__{cv.q(dest)}.tar*", 60)
        except Exception as e:                   # noqa: BLE001
            emit(f"⚠ לא ניתן לפנות את קובץ הביניים ביעד: {e}")
    if volumes:
        emit("קובצי הביניים ביעד נמחקו")
    try:
        # The disposition is RESTORED, not assumed: an app the owner had turned off must not come
        # back on because it was the subject of a failed move. `prior_enabled` is read in preflight.
        if ctx.get("prior_enabled") is False:
            # Written only if it actually differs: the move never touched this office's disposition
            # when the app was already off, and a `set-state` that rewrites an identical row still
            # overwrites WHO set it (measured: the owner's `by: user` became `by: dgo-extend`).
            now = _enabled_apps()
            if app in now:
                local(f"python3 platform/manager/reconcile.py set-state --app {cv.q(app)} "
                      f"--state disabled --by dgo-extend >/dev/null 2>&1 || true", 60)
                emit("האפליקציה הוחזרה למצב שהיה לה כאן: לא מופעלת")
            else:
                emit("מצב ההפעלה כאן לא נגענו בו — נשאר כפי שהיה (כבוי)")
        else:
            local(f"python3 platform/manager/reconcile.py set-state --app {cv.q(app)} "
                  f"--state enabled --by dgo-extend --create >/dev/null 2>&1 || true", 60)
            _start_services(LOCAL_MACHINE, ctx.get("stopped") or [], emit)
            emit("האפליקציה הוחזרה לפעילות כאן")
    except Exception as e:                       # noqa: BLE001
        emit(f"⚠ החזרת האפליקציה לפעילות נכשלה: {e}")
    # The far side's platform.state.yaml is derived from the DECLARATION, which was just reverted —
    # so it has to be re-derived, or the office there keeps an app its own declaration no longer
    # names (measured: a failed move left `domains: enabled` in vps1's state while its declaration
    # had no such row). Skipped when the declaration was never written: nothing to re-derive.
    if ctx.get("declaration_written"):
        try:
            emit("מריץ state בלשכה המרוחקת כדי שתתאים להצהרה שהוחזרה")
            cv.RUNNERS["state"](office, ctx, emit)
        except Exception as e:                   # noqa: BLE001 — the undo is already done
            log.warning("re-run of the remote state after an undo: %r", e)
            emit(f"⚠ ה-state בלשכה המרוחקת לא הורץ מחדש: {e}")


# ── one command that answers "what would moving the whole office cost?" ─────────
def _apps_with_data() -> list[str]:
    """The apps that HAVE data here: every app whose declared volumes exist on this machine.

    Derived from the manifests on disk plus `docker volume ls`, not from a list anybody maintains:
    a hand-written list of "the apps with data" is stale the day an app is added, and an app left out
    of it is an app whose data silently stays behind."""
    names = [ln.strip() for ln in
             local("ls -d apps/*/app.json platform-base/*/app.json 2>/dev/null", 60).splitlines()
             if ln.strip()]
    have = _exec(LOCAL_MACHINE, "docker volume ls --format '{{.Name}}'", 60).split()
    out = []
    for path in names:
        app = path.split("/")[1]
        try:
            declared = ((json.loads(local(f"cat {cv.q(path)}", 30)).get("data") or {})
                        .get("volumes") or [])
        except Exception:                            # noqa: BLE001 — a manifest we cannot read is skipped
            continue
        for want in declared:
            name = want if isinstance(want, str) else (want or {}).get("name")
            if name and any(h == name or h.endswith("_" + name) for h in have):
                out.append(app)
                break
    return sorted(out)


def plan(office: dict, apps: list[str] | None = None) -> dict:
    """A READ-ONLY plan for moving this office to that one.

    It runs the move's own `preflight` for every app and reports the result per app — the volumes, the
    bytes, and above all the refusals (a different commit, an uncommitted working tree, no room on the
    destination). Nothing is stopped, nothing is written, no declaration changes: this is the call that
    answers "can we do this, and what will it cost" BEFORE anything is at stake. A start that would be
    refused later is refused here, by the same code that would refuse it then."""
    if office["machine"] == LOCAL_MACHINE:
        return {"error": "המכונה של הלשכה היא המכונה הזאת"}
    selected = apps or _apps_with_data()
    # The facts that are the same for every app are gathered ONCE: one git status, one volume list,
    # one probe of the destination. Asking per app is what turned this read-only plan into minutes of
    # SSH round trips (measured: ~30 apps took 4m11s before this).
    shared = {
        "allow_mismatch": False,
        "enabled_apps": _enabled_apps(),
        "have_volumes": _exec(LOCAL_MACHINE, "docker volume ls --format '{{.Name}}'", 60,
                              "לא ניתן לקרוא את ה-volumes").split(),
        "dirty_paths": [ln.strip() for ln in
                        local("git status --porcelain | head -400", 120).splitlines() if ln.strip()],
    }
    try:
        shared["home_commit"] = local("git rev-parse HEAD", 60).strip().splitlines()[-1].strip()
    except Exception:                                # noqa: BLE001 — reported per app below
        shared["home_commit"] = ""
    try:
        shared["machine_record"] = cv.machine_record(office["machine"])
    except Exception:                                # noqa: BLE001
        shared["machine_record"] = {}
    try:
        shared["dest_project"] = _dest_project(office["machine"], office["path"])
    except Exception:                                # noqa: BLE001
        shared["dest_project"] = None
    rows, total = [], 0
    for app in selected:
        ctx: dict = {"app": app, **shared}
        lines: list[str] = []
        try:
            res = _step_preflight(office, app, ctx, lines.append)
            total += int(res.get("bytes") or 0)
            rows.append({"app": app, "ok": True, "volumes": res["volumes"], "bytes": res["bytes"],
                         "dest_project": res["dest_project"], "detail": res["summary"],
                         "log": lines})
        except MoveFailed as e:
            rows.append({"app": app, "ok": False, "reason": e.reason, "action": e.action,
                         "detail": e.detail, "volumes": ctx.get("app_volumes") or [], "log": lines})
        except Exception as e:                       # noqa: BLE001 — a plan reports, it never raises
            rows.append({"app": app, "ok": False, "reason": f"{type(e).__name__}: {e}",
                         "action": "", "detail": "", "volumes": [], "log": lines})
    movable = [r for r in rows if r["ok"]]
    return {"office": office["id"], "machine": office["machine"], "apps": rows,
            "count": len(rows), "movable": len(movable),
            "total_bytes": total,
            # the destination needs the archive in flight AND the copy it is extracted into
            "dest_need_bytes": int(total * 2.04),
            "not_included": ["dgo_identity (dgo-extend)", "הכספת (connections)",
                             "הזיהוי וה-SSO (authentik)", "מסדי הנתונים של אפליקציות בלי volume מוצהר"],
            "note": "זהו תכנון בלבד. הרצה: POST /api/office/<oid>/move לכל אפליקציה; "
                    "פקודה אחת לכל הלשכה טרם ממומשת (ראה ai/context/moving-an-office.md)."}


# ── the job ─────────────────────────────────────────────────────────────────────
def _job_file(oid: str) -> Path:
    return JOB_DIR / f"{oid}.json"


def last(oid: str) -> dict | None:
    p = _job_file(oid)
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _persist(job: dict) -> None:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _job_file(job["office"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False))
    tmp.replace(_job_file(job["office"]))


_running: dict[str, dict] = {}


def running(oid: str) -> dict | None:
    return _running.get(oid)


def start(office: dict, app: str, fail_after: str | None = None,
          allow_mismatch: bool = False, allow_disabled: bool = False) -> dict:
    """Begin the move.

    `fail_after` is a TEST HOOK: it aborts the run right after that step succeeds, which is the only
    way to prove the rollback path without breaking a real link by hand. `allow_mismatch` is the
    deliberate override of the same-commit / clean-worktree refusals (decision 11) — an operator who
    knows the two sides differ, never a default."""
    oid = office["id"]
    if oid in _running:
        return {"error": "העברה כבר רצה ללשכה הזאת", "job": _running[oid]}
    job = {"office": oid, "app": app, "status": "running", "started": int(time.time()),
           "ended": None, "current": None, "rollback": None, "fail_after": fail_after or None,
           "allow_mismatch": bool(allow_mismatch), "allow_disabled": bool(allow_disabled),
           "steps": {s: {"status": "pending", "title": STEP_TITLES[s]} for s in STEPS}, "log": []}
    _running[oid] = job
    import threading
    threading.Thread(target=_execute, args=(office, app, job), daemon=True,
                     name=f"move-{oid}").start()
    return {"job": job}


def _make_emit(job: dict):
    def emit(line: str, step: str | None = None) -> None:
        job["log"].append({"t": int(time.time()), "step": step or job.get("current"), "line": line[:2000]})
        del job["log"][:-1500]
    return emit


def _run_app(office: dict, app: str, job: dict, emit, steps_slot: dict | None = None,
             status_slot: dict | None = None) -> bool:
    """ONE app through the whole step list, with its own rollback. True when it finished ok.

    Shared by the single-app move and by the office-wide one so the two cannot drift: an office move is
    this function, per app, in order — not a second implementation of moving an app."""
    slot = steps_slot if steps_slot is not None else job["steps"]
    ctx: dict = {"app": app, "allow_mismatch": bool(job.get("allow_mismatch")),
                 "allow_disabled": bool(job.get("allow_disabled")), "office": office}
    try:
        for name in STEPS:
            job["current"] = name
            slot[name].update(status="running", started=int(time.time()))
            emit(f"── {STEP_TITLES[name]}", name)
            try:
                res = globals()["_step_" + name](office, app, ctx, emit)
                slot[name].update(status="ok", result=res, ended=int(time.time()))
                emit(f"✓ {res.get('summary', '')}", name)
            except MoveFailed as e:
                slot[name].update(status="failed", ended=int(time.time()),
                                  error={"reason": e.reason, "action": e.action, "detail": e.detail})
                raise
            except Exception as e:               # noqa: BLE001
                log.error("move %s crashed: %s", app, traceback.format_exc())
                slot[name].update(status="failed", ended=int(time.time()),
                                  error={"reason": "שגיאה פנימית",
                                         "action": "", "detail": str(e)[:400]})
                raise
            _persist(job)
            if job.get("fail_after") == name:
                raise MoveFailed(
                    f"כשל מאולץ אחרי „{STEP_TITLES[name]}” (fail_after) — זו הבדיקה של ה-rollback",
                    "הרץ שוב בלי fail_after.")
        return True
    except Exception as e:                       # noqa: BLE001
        # `failed` means FINISHED failing — including the rollback. Marking it before the rollback
        # runs makes a caller that polls see "failed, rollback: none" while the undo is still in
        # flight, which reads as "nothing was put back" about a run that is putting everything back.
        where = status_slot if status_slot is not None else job
        if ctx.get("stopped") or ctx.get("backup_dir"):
            where["rollback"] = "running"
            _persist(job)
            emit("מחזיר למצב הקודם…")
            try:
                _rollback(office, app, ctx, emit)
                where["rollback"] = "done"
            except Exception as undo:            # noqa: BLE001 — the failure that matters most
                where["rollback"] = "failed"
                emit(f"✗ הגלגול לאחור נכשל: {undo}")
                log.error("move %s rollback failed: %s", app, traceback.format_exc())
        where["error"] = {"reason": str(e)[:400]}
        return False


def _execute(office: dict, app: str, job: dict) -> None:
    emit = _make_emit(job)
    try:
        job["status"] = "ok" if _run_app(office, app, job, emit) else "failed"
    finally:
        job["ended"] = int(time.time())
        job["current"] = None
        _persist(job)
        _running.pop(job["office"], None)


def _execute_office(office: dict, apps: list[str], job: dict) -> None:
    """The whole office: the same per-app move, in order, stopping at the first failure.

    Stopping (rather than carrying on) is the decision: what is already on the far side is a real,
    verified move, and continuing past a failure would spread a broken assumption over more apps. Each
    app keeps its own rollback, so a failure leaves THAT app as it was here."""
    emit = _make_emit(job)
    try:
        for app in apps:
            job["current"] = app
            entry = {"app": app, "status": "running", "rollback": None,
                     "steps": {s: {"status": "pending", "title": STEP_TITLES[s]} for s in STEPS}}
            job["apps"].append(entry)
            emit(f"══ {app}", app)
            if _run_app(office, app, job, emit, steps_slot=entry["steps"], status_slot=entry):
                entry["status"] = "ok"
                _persist(job)
                continue
            entry["status"] = "failed"
            job["status"] = "failed"
            emit(f"✗ {app} נכשל — העברת הלשכה נעצרת כאן. "
                 f"מה שכבר הועבר נשאר ביעד; {app} הוחזר למצבו כאן.")
            return
        job["status"] = "ok"
    finally:
        job["ended"] = int(time.time())
        job["current"] = None
        _persist(job)
        _running.pop(job["office"], None)


def start_office(office: dict, apps: list[str] | None = None, allow_mismatch: bool = False,
                 allow_disabled: bool = True, fail_after: str | None = None) -> dict:
    """Move the WHOLE office: every app that holds data here, one at a time, each with its own undo.

    `allow_disabled` defaults to TRUE here and to false for a single app, and that difference is the
    point: moving one app out of a running office is a decision about that app, while moving the office
    is a decision about all of it — an office whose app set is currently switched off here (which is
    what a machine being handed over looks like) is exactly the case this command exists for."""
    oid = office["id"]
    if oid in _running:
        return {"error": "העברה כבר רצה ללשכה הזאת", "job": _running[oid]}
    apps = apps or _apps_with_data()
    if not apps:
        return {"error": "לא נמצאו אפליקציות עם נתונים להעביר"}
    job = {"office": oid, "kind": "office", "apps_wanted": list(apps), "current": None,
           "status": "running", "started": int(time.time()), "ended": None, "rollback": None,
           "fail_after": fail_after or None, "allow_mismatch": bool(allow_mismatch),
           "allow_disabled": bool(allow_disabled), "apps": [], "log": []}
    _running[oid] = job
    import threading
    threading.Thread(target=_execute_office, args=(office, list(apps), job), daemon=True,
                     name=f"move-office-{oid}").start()
    return {"job": job}


