#!/usr/bin/env python3
"""The RETURN leg of a move: bring an app that was moved to another office BACK to this machine.

The outbound move is the product (`POST /api/office/<oid>/move`): stop here, carry the volumes across,
switch it on there, publish it. This is its mirror, built from the same parts and verified the same
way — with one asymmetry that is deliberate:

  * the far side's switch is the office DECLARATION (this app's own `PUT /api/office/<oid>` writes it,
    and the far converge's `state` step is what acts on it);
  * this side's switch is the platform's single writer (`bbox apps enable`, which is what
    `reconcile.py set-state` is for) — a script that edited platform.state.yaml by hand would be a
    second writer of the one file that has one.

What it does, in order: read the far side's volumes and hash them THERE · stop the app there · tar this
machine's stale copies aside · stream each volume back through `computers.stream` · verify the returned
data hashes to what the far side had · enable and start the app HERE · disable it in the far
declaration and converge that office's `state` · confirm it runs here and is gone there.

Usage (stack up, the app ENABLED on that office):

    python3 apps/dgo-extend/tests/move_back.py --office vps1 --app domains --yes
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


def api(base: str, path: str, body: dict | None = None, method: str | None = None,
        timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"content-type": "application/json"},
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"✗ {path} → HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def sh(machine: str, command: str, timeout: int = 300) -> str:
    res = api(COMPUTERS, f"/api/computers/{machine}/exec",
              {"command": command, "timeout": timeout}, timeout=timeout + 60)
    if res.get("code") != 0:
        raise SystemExit(f"✗ {machine}: {command[:90]} → {(res.get('stderr') or res.get('reason') or '')[:300]}")
    return res.get("stdout") or ""


def script(machine: str, body: str, timeout: int = 600) -> str:
    enc = base64.b64encode(body.encode()).decode()
    return sh(machine, f"echo {enc} | base64 -d | bash", timeout)


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'✓' if condition else '✗'} {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        raise SystemExit(1)


def project_on(machine: str) -> str:
    return sh(machine, "docker ps --format '{{.Label \"com.docker.compose.project\"}}' | grep -v '^$' | "
                       "sort | uniq -c | sort -rn | head -1 | awk '{print $2}'").strip()


def volume_sha(machine: str, volume: str) -> str:
    return script(machine, f"cd /var/lib/docker/volumes/{volume}/_data && "
                           f"LC_ALL=C find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | "
                           f"sha256sum | cut -d' ' -f1", timeout=1800).strip().splitlines()[-1].strip()


def services_running(machine: str, path: str, app: str) -> list[str]:
    out = sh(machine, f"cd {shlex.quote(path)} && python3 platform/manager/reconcile.py "
                      f"compose-services --app {shlex.quote(app)}")
    running = []
    for svc in [s.strip() for s in out.split() if s.strip()]:
        if sh(machine, f"docker ps -q --filter label=com.docker.compose.service={svc}").split():
            running.append(svc)
    return running


def stop_services(machine: str, services: list[str]) -> list[str]:
    stopped = []
    for svc in services:
        ids = sh(machine, f"docker ps -q --filter label=com.docker.compose.service={svc}").split()
        if ids:
            sh(machine, "docker stop " + " ".join(ids), timeout=300)
            stopped.append(svc)
    return stopped


def declared_volumes(app: str, home_repo: str) -> list[str]:
    raw = ""
    for base in ("apps", "platform-base"):
        raw = sh(LOCAL, f"cd {shlex.quote(home_repo)} && test -f {base}/{shlex.quote(app)}/app.json && "
                        f"cat {base}/{shlex.quote(app)}/app.json")
        if raw.strip().startswith("{"):
            break
    if not raw.strip().startswith("{"):
        raise SystemExit(f"✗ אין מניפסט ל-{app}")
    return [v if isinstance(v, str) else (v or {}).get("name")
            for v in ((json.loads(raw).get("data") or {}).get("volumes") or [])]


def on(machine: str, docker_volumes: list[str], suffix: str) -> str:
    """The volume named `<suffix>` on that machine (its project prefixes the declared name)."""
    for v in docker_volumes:
        if v == suffix or v.endswith("_" + suffix):
            return v
    raise SystemExit(f"✗ לא נמצא volume בשם {suffix} על {machine}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--run-here", action="store_true",
                    help="הפעל את האפליקציה כאן בסוף (ברירת מחדל: לא — מצב ההפעלה של הבעלים לא משתנה)")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if not args.yes:
        raise SystemExit("✗ פעולה שמשנה הצהרה ומפעילה אפליקציה — הרץ עם --yes")

    ctx = api(DGO, "/api/context", timeout=180)
    home_repo = (ctx.get("home") or {}).get("path") or ""
    offices = {o["id"]: o for o in (api(DGO, "/api/office").get("items") or [])}
    office = offices.get(args.office)
    check("הלשכה מוצהרת", bool(office), str(sorted(offices)))
    far, far_path = office["machine"], office["path"]
    check("האפליקציה מוצהרת כמופעלת שם", (office.get("apps") or {}).get(args.app) == "enabled",
          str((office.get("apps") or {}).get(args.app)))
    far_services = services_running(far, far_path, args.app)
    check("האפליקציה רצה שם", bool(far_services), f"{far_services}")

    declared = [v for v in declared_volumes(args.app, home_repo) if v]
    far_vols = sh(far, "docker volume ls --format '{{.Name}}'").split()
    local_vols = sh(LOCAL, "docker volume ls --format '{{.Name}}'").split()
    pairs = []
    for name in declared:
        pairs.append((on(far, far_vols, name), on(LOCAL, local_vols, name)))
    print(f"── {args.app}: {len(pairs)} volumes")
    for f, l in pairs:
        print(f"   {f}  →  {l}")

    print("── עוצר שם ומודד את מה שיש")
    stop_services(far, far_services)
    far_sha = {f: volume_sha(far, f) for f, _ in pairs}
    for f, h in far_sha.items():
        print(f"   {f}: {h[:12]}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    print(f"── גיבוי העותקים הישנים כאן (~/.digital-office/back-move-{args.app}-{stamp})")
    lines = [f'D="$HOME/.digital-office/back-move-{args.app}-{stamp}"', 'mkdir -p "$D"']
    for _, l in pairs:
        lines.append(f'tar czf "$D/{l}.tgz" -C /var/lib/docker/volumes/{shlex.quote(l)}/_data . || [ $? = 1 ]')
    script(LOCAL, "\n".join(lines), timeout=3600)

    print("── מעביר את הנתונים בחזרה")
    for (fv, lv) in pairs:
        job = api(COMPUTERS, f"/api/computers/{far}/stream",
                  {"to": LOCAL, "volume": fv, "dest_volume": lv}).get("job") or {}
        jid = job.get("id")
        if not jid:
            raise SystemExit(f"✗ ההעברה של {fv} לא החלה: {json.dumps(job)[:200]}")
        t0 = time.time()
        while True:
            time.sleep(5)
            row = (api(COMPUTERS, f"/api/transfers/{jid}").get("transfer") or {})
            if row.get("state") in ("ok", "error", "cancelled"):
                break
            if time.time() - t0 > 6 * 3600:
                raise SystemExit("✗ ההעברה לא הסתיימה")
        check(f"{fv} הועבר", row.get("state") == "ok", str(row.get("error") or "")[:200])

    print("── מאמת שהתוכן שחזר זהה למה שהיה שם")
    for (fv, lv) in pairs:
        got = volume_sha(LOCAL, lv)
        check(f"{lv} זהה ל-{fv}", got == far_sha[fv], f"{got[:12]} מול {far_sha[fv][:12]}")

    # Whether the app RUNS here again is the owner's decision, not this script's: the business apps
    # were switched off on purpose on 2026-10-01, and bringing one back up "because we moved it" would
    # be exactly the kind of unasked-for change the move refuses elsewhere. The data comes home either
    # way; --run-here is the explicit request to also start it.
    if args.run_here:
        print("── מפעיל כאן (התבקש במפורש)")
        sh(LOCAL, f"cd {shlex.quote(home_repo)} && ./bbox apps enable {shlex.quote(args.app)}", timeout=600)
        services = sh(LOCAL, f"cd {shlex.quote(home_repo)} && python3 platform/manager/reconcile.py "
                             f"compose-services --app {shlex.quote(args.app)}").split()
        if services:
            sh(LOCAL, f"cd {shlex.quote(home_repo)} && ./scripts/dc up -d " +
               " ".join(shlex.quote(s) for s in services), timeout=1800)
        time.sleep(10)
        here = services_running(LOCAL, home_repo, args.app)
        check("האפליקציה רצה כאן שוב", bool(here), f"{here}")
    else:
        print("── מצב ההפעלה כאן לא משתנה (האפליקציה כבויה בהוראת הבעלים)")

    print("── מכבה בהצהרה של הלשכה המרוחקת ומריץ אצלה state")
    # The true inverse of "the move enabled it there": the row goes away, rather than becoming an
    # explicit "disabled" the declaration never had (the same mistake the rollback made, measured).
    office["apps"].pop(args.app, None)
    office["placement"] = [x for x in (office.get("placement") or []) if x != args.app]
    body = {k: office.get(k) for k in ("label", "machine", "domain", "path", "source", "apps",
                                       "placement", "engine", "serve")}
    api(DGO, f"/api/office/{args.office}", body, method="PUT")
    api(DGO, f"/api/office/{args.office}/converge", {"steps": ["state", "run"]}, timeout=1800)
    still = services_running(far, far_path, args.app)
    check("האפליקציה אינה רצה יותר שם", not still, f"{still}")

    print(f"\n✓ {args.app}: הנתונים חזרו ל-{LOCAL} זהים למה שהיה ב-{args.office}, "
          f"וההצהרה של {args.office} אינה מפעילה אותו יותר")
    return 0


if __name__ == "__main__":
    sys.exit(main())
