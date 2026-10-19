#!/usr/bin/env python3
"""The acceptance run for `dgo-extend.move` (DGO-37) — an app moves to another office WITH its data,
and a forced failure in the middle puts everything back.

What it proves, on real machines:

  1. **rollback first, on purpose.** The move is started with `fail_after: transfer`, which aborts the
     run right after the volumes arrived. The run must end `failed` with `rollback: done`, the
     declaration at the remote office must NOT name the app, and the app's containers must be RUNNING
     AGAIN at home. A rollback nobody has ever executed is a rollback nobody can trust.
  2. **the real move.** `POST /api/office/<oid>/move {app}` — the app stops here, its declared volumes
     go across (through `computers.stream`, resumable), the declaration switches it on there, and it
     is published.
  3. **the data really arrived.** The volume contents are hashed ON EACH MACHINE (not through the
     transfer's own report) BEFORE and AFTER, and the destination's hash must equal the source's.
  4. **it is on the far side.** The app's compose services run on the remote machine, and they no
     longer run here.

Usage (from the office checkout, stack up — this CHANGES the declaration, so it asks for `--yes`):

    python3 apps/dgo-extend/tests/move_acceptance.py --office vps1 --app any-concurrency --yes
    python3 apps/dgo-extend/tests/move_acceptance.py --office vps1 --app any-concurrency --yes --rollback-only

It does not move an app back: that is a second decision (`--app <id> --office <home>` in reverse), and
a test that quietly reverses a production change is worse than one that prints the command to do it.
"""
from __future__ import annotations

import argparse
import base64
import json
import shlex
import sys
import time
import urllib.error
import urllib.request

DGO = "http://dgo-extend:8983"
COMPUTERS = "http://computers:8977"
LOCAL = "computer_local-local"
STEPS = ["preflight", "backup", "stop", "transfer", "enable", "verify"]
#: Where the checkout is on the machine that runs THIS office. `reconcile.py compose-services` is
#: asked from inside that directory, so a wrong value here reports "the app does not run here".
HOME_REPO = "/Users/shlomobolotin/הלשכה הדיגיטלית שלי"


def api(base: str, path: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"content-type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"✗ {path} → HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def repo(command: str) -> str:
    """A command run in the CHECKOUT on the office's own machine.

    `computers.exec` starts in the machine's login directory, not in the repository — so a bare
    `cat apps/x/app.json` reads nothing and looks like a missing manifest."""
    return f"cd {shlex.quote(HOME_REPO)} && " + command


def script(machine: str, body: str, timeout: int = 600) -> str:
    enc = base64.b64encode(body.encode()).decode()
    res = api(COMPUTERS, f"/api/computers/{machine}/exec",
              {"command": f"echo {enc} | base64 -d | bash", "timeout": timeout}, timeout + 60)
    if res.get("code") != 0:
        raise SystemExit(f"✗ {machine}: {(res.get('stderr') or res.get('reason') or '')[:400]}")
    return res.get("stdout") or ""


def sh(machine: str, command: str, timeout: int = 300) -> str:
    res = api(COMPUTERS, f"/api/computers/{machine}/exec",
              {"command": command, "timeout": timeout}, timeout + 60)
    return res.get("stdout") or ""


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'✓' if condition else '✗'} {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        raise SystemExit(1)


def services_running(machine: str, path: str, app: str) -> list[str]:
    """Which of this app's compose services have a RUNNING container on that machine.

    The path is QUOTED: the office's checkout is a Hebrew path with a space in it, and an unquoted
    `cd` there fails — which would report "the app does not run here" about an app that runs fine."""
    out = sh(machine, f"cd {shlex.quote(path)} && python3 platform/manager/reconcile.py "
                      f"compose-services --app {shlex.quote(app)}")
    running = []
    for svc in [s.strip() for s in out.split() if s.strip()]:
        ids = sh(machine, f"docker ps -q --filter label=com.docker.compose.service={svc}").split()
        if ids:
            running.append(svc)
    return running

def app_volumes(app: str) -> list[str]:
    """The app's DECLARED volumes, as docker names them on the machine that runs it.

    Both bases are searched: layer-3 apps live under apps/, the substrate under platform-base/."""
    raw = ""
    for base in ("apps", "platform-base"):
        raw = sh(LOCAL, repo(f"test -f {base}/{shlex.quote(app)}/app.json && "
                             f"cat {base}/{shlex.quote(app)}/app.json"))
        if raw.strip().startswith("{"):
            break
    if not raw.strip().startswith("{"):
        raise SystemExit(f"✗ אין מניפסט ל-{app} תחת apps/ או platform-base/")
    declared = [v if isinstance(v, str) else (v or {}).get("name")
                for v in ((json.loads(raw).get("data") or {}).get("volumes") or [])]
    have = sh(LOCAL, "docker volume ls --format '{{.Name}}'").split()
    out = []
    for want in declared:
        match = next((h for h in have if h == want or h.endswith("_" + want)), None)
        if match:
            out.append(match)
    return out


def vol_sha(machine: str, docker_volume: str) -> str:
    """The content identity of a volume, on the machine that holds it. `LC_ALL=C` on the find AND the
    sort: two machines with different collations sort the same list differently, and two identical
    volumes then hash differently — a false alarm indistinguishable from data corruption."""
    return script(machine, f"cd /var/lib/docker/volumes/{docker_volume}/_data && "
                           f"LC_ALL=C find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | "
                           f"sha256sum | cut -d' ' -f1",
                  timeout=1800).strip().splitlines()[-1].strip()


def wait_move(oid: str, timeout_s: int = 3 * 3600) -> dict:
    t0 = time.time()
    last = None
    while True:
        time.sleep(10)
        job = (api(DGO, f"/api/office/{oid}/move").get("move") or {})
        cur = job.get("current")
        if cur != last:
            print(f"   ── {cur or 'סיום'}")
            last = cur
        if job.get("status") in ("ok", "failed"):
            return job
        if time.time() - t0 > timeout_s:
            raise SystemExit("✗ ההעברה לא הסתיימה בזמן")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", required=True, help="target office id (from /api/office)")
    ap.add_argument("--app", required=True)
    ap.add_argument("--rollback-only", action="store_true")
    ap.add_argument("--fail-after", default="transfer",
                    help="השלב שאחריו נכשל בכוונה (transfer; stop = בלי לכתוב דבר ליעד)")
    ap.add_argument("--allow-stopped", action="store_true",
                    help="האפליקציה אינה רצה כרגע — הבדיקה היא שהמצב לא השתנה, לא שהיא חזרה לרוץ")
    ap.add_argument("--allow-disabled", action="store_true",
                    help="העבר אפליקציה שאינה מופעלת כאן (בודק את נתיב שחזור הנתונים בלי להעיר אפליקציה)")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="עקיפה מודעת של בדיקת אותו-קומיט/עץ-נקי (לבדיקת ה-rollback מול יעד בקומיט אחר)")
    ap.add_argument("--home-repo", default="",
                    help="נתיב ה-checkout במכונה שמריצה את הלשכה הזאת (ברירת מחדל: מהאפליקציה עצמה)")
    ap.add_argument("--yes", action="store_true", help="אשר שינוי הצהרה")
    args = ap.parse_args()
    if not args.yes:
        raise SystemExit("✗ זו פעולה שמשנה הצהרה — הרץ עם --yes")
    # The checkout path comes from dgo-extend itself (`/api/context` → home.path) unless it is given:
    # the office's path is a Hebrew name with a TRAILING SPACE, and any hardcoded copy of it is wrong
    # in a way that reads as "the app is missing".
    globals()["HOME_REPO"] = args.home_repo or ((api(DGO, "/api/context", timeout=120).get("home") or {})
                                                .get("path") or HOME_REPO)
    print(f"── checkout: {HOME_REPO}")

    offices = {o["id"]: o for o in (api(DGO, "/api/office").get("items") or [])}
    office = offices.get(args.office)
    check("הלשכה היעד מוצהרת", bool(office), f"יש: {sorted(offices)}")

    vols = app_volumes(args.app)
    print(f"── {args.app}: {len(vols)} volumes — {', '.join(vols) or 'אין'}")
    before = {v: vol_sha(LOCAL, v) for v in vols}
    for v, h in before.items():
        print(f"   {v}: {h[:12]}")
    services_home = services_running(LOCAL, HOME_REPO, args.app)
    if args.allow_stopped:
        print(f"   (האפליקציה אינה רצה כרגע: {services_home or 'אף שירות'})")
    else:
        check("האפליקציה רצה כאן", bool(services_home), f"שירותים: {services_home}")
    # The declaration BEFORE anything: the rollback must reproduce it EXACTLY, not approximate it. An
    # app the declaration already named (or did not) is a statement about that office, and the test
    # asserting "not present" would pass a rollback that quietly changed it.
    decl_before = json.dumps(office.get("apps") or {}, sort_keys=True)
    place_before = sorted(office.get("placement") or [])

    print(f"── שלב א׳: כישלון מאולץ אחרי „{args.fail_after}” (בודק את ה-rollback)")
    api(DGO, f"/api/office/{args.office}/move",
        {"app": args.app, "fail_after": args.fail_after, "allow_mismatch": args.allow_mismatch,
         "allow_disabled": args.allow_disabled})
    job = wait_move(args.office)
    check("ההעברה נכשלה כמתוכנן", job.get("status") == "failed", str(job.get("status")))
    check("ה-rollback רץ", job.get("rollback") == "done", str(job.get("rollback")))
    offices_now = {o["id"]: o for o in (api(DGO, "/api/office").get("items") or [])}
    after = offices_now[args.office]
    check("ההצהרה ביעד הוחזרה בדיוק למה שהיה",
          json.dumps(after.get("apps") or {}, sort_keys=True) == decl_before
          and sorted(after.get("placement") or []) == place_before,
          f"apps: {len(after.get('apps') or {})} מול {len(json.loads(decl_before))} · "
          f"placement: {sorted(after.get('placement') or [])}")
    after_rb = {v: vol_sha(LOCAL, v) for v in vols}
    check("הנתונים כאן לא נפגעו בגלגול", all(after_rb[v] == before[v] for v in vols),
          ", ".join(f"{v}:{after_rb[v][:8]}" for v in vols))
    home_again = services_running(LOCAL, HOME_REPO, args.app)
    check("מצב האפליקציה כאן לא השתנה" if args.allow_stopped else "האפליקציה חזרה לפעול כאן",
          sorted(home_again) == sorted(services_home), f"{home_again}")

    if args.rollback_only:
        print("\n✓ DGO-37 (rollback): כישלון באמצע → הכל חזר, הבית ממשיך לעבוד")
        return 0

    print("── שלב ב׳: ההעברה האמיתית")
    api(DGO, f"/api/office/{args.office}/move",
        {"app": args.app, "allow_mismatch": args.allow_mismatch,
         "allow_disabled": args.allow_disabled})
    job = wait_move(args.office)
    check("ההעברה הסתיימה בהצלחה", job.get("status") == "ok",
          json.dumps({k: (v.get("status") if isinstance(v, dict) else v)
                      for k, v in (job.get("steps") or {}).items()}, ensure_ascii=False))
    for step in STEPS:
        check(f"שלב {step} עבר", (job.get("steps") or {}).get(step, {}).get("status") == "ok")

    remote_services = services_running(office["machine"], office["path"], args.app)
    check("האפליקציה רצה בלשכה המרוחקת", bool(remote_services), f"{remote_services}")
    check("היא אינה רצה יותר כאן", not services_running(LOCAL, HOME_REPO, args.app))

    print("── אימות הנתונים ביעד (לא דרך דיווח ההעברה)")
    project = sh(office["machine"],
                 "docker ps --format '{{.Label \"com.docker.compose.project\"}}' | grep -v '^$' | "
                 "sort | uniq -c | sort -rn | head -1 | awk '{print $2}'").strip()
    for v in vols:
        suffix = v.split("_", 1)[1] if "_" in v else v
        dst = f"{project}_{suffix}"
        got = vol_sha(office["machine"], dst)
        check(f"התוכן של {v} זהה ביעד", got == before[v], f"{got[:12]} מול {before[v][:12]}")

    print(f"\n✓ DGO-37: {args.app} עבר ל-{args.office} עם הנתונים שלו, והבית שוחרר")
    print(f"  להחזיר: python3 apps/dgo-extend/tests/move_acceptance.py --office local "
          f"--app {args.app} --yes   (אותם שלבים, בכיוון ההפוך)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
