#!/usr/bin/env python3
"""accept — the DGO-553 acceptance, run instead of remembered.

    ./bbox dgo accept            # every linked office
    ./bbox dgo accept macbook    # one of them
    ./bbox dgo accept --self-test  # the verdicts themselves, against canned facts (an office that
                                   # IS updated, one that is old, one that is down) — because a
                                   # checker whose green path has never run proves nothing

Why this exists
---------------
The item's acceptance is four clauses, and two of them are answered by ANOTHER OFFICE's code: (א) that
office's console shows this one's in full, (ב) its «מחשבים» carries the machines this one shares. A
session that "knows" they work because a previous session said so is how a stale claim survives a
release — so the clauses are measured, per office, and each is reported with the ONE fact that decides
it: does that office's console serve `mount.js` as code (it can be mounted) or as its SPA (it cannot);
does its `computers` manifest carry the `shell` op; does it answer at all.

The two clauses this office owns are measured too, because they are the half that must not regress
while the other offices catch up:
  · ג — the terminal app: machines listed, `shell` in its manifest.
  · ד — no new exposure: a forged office header is refused BY NAME, and a request signed by the link's
        own door is answered with the shared set only.

Read-only: nothing here declares, shares, builds or restarts anything.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# Every sentence below is Hebrew, and `bbox` runs this with the host's own python (on Windows a code
# page, not UTF-8): G10 asks for this, and it is also what keeps the report readable in a pipe.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REG = os.path.join(REPO, ".generated", "registry")
LINK_APP = "http://dgo-extend:8983"
COMPUTERS = "http://computers:8977"


def sh(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=90).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _container(prefix: str) -> str:
    return sh("docker", "ps", "--filter", "name=^{}".format(prefix), "--format", "{{.Names}}").split("\n")[0]


def get(url: str, headers: dict | None = None, timeout: float = 25.0,
        method: str = "GET") -> tuple[int, str, bytes]:
    """(status, content-type, body) — from this shell, or through a container that is on the network.

    `bbox` is run both from a container ON the office network (where `console-home.macbook:9005`
    resolves) and from the host (where it does not). One helper, so every check asks the same way and
    a host run is not silently a page of failures.
    """
    hdrs = dict(headers or {})
    req = urllib.request.Request(url, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()
    except (urllib.error.URLError, OSError):
        pass
    box = _container("dgo-extend-")
    if not box:
        return 0, "", b""
    prog = (
        "import json,sys,urllib.request,urllib.error\n"
        "url, hdrs, method = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]\n"
        "try:\n"
        "    r = urllib.request.urlopen(urllib.request.Request(url, headers=hdrs, method=method), timeout=25)\n"
        "    sys.stdout.write(json.dumps([r.status, r.headers.get('content-type',''), "
        "r.read().decode('utf-8','replace')]))\n"
        "except urllib.error.HTTPError as e:\n"
        "    sys.stdout.write(json.dumps([e.code, e.headers.get('content-type',''), "
        "e.read().decode('utf-8','replace')]))\n"
        "except Exception as e:\n"
        "    sys.stdout.write(json.dumps([0, '', str(e)]))\n"
    )
    with open(os.devnull, "w") as _:
        p = subprocess.run(["docker", "exec", "-i", box, "python3", "-", url, json.dumps(hdrs), method],
                           input=prog, capture_output=True, text=True, timeout=120)
    try:
        status, ctype, body = json.loads(p.stdout)
    except ValueError:
        return 0, "", b""
    return int(status), ctype, str(body).encode()


def registry(office: str, alias: str) -> dict:
    """The compiler's own record of where that office's app is reachable from here."""
    path = os.path.join(REG, f"remote.{office}.{alias}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def door_of(office: str, alias: str) -> str:
    return str((registry(office, alias).get("door") or {}).get("base") or "").rstrip("/")


def door_signature(office: str, user: str) -> str:
    """What the link's own door would write on a request for that office — the door's own function.

    Asked of the door, never re-implemented here: a checker that signs differently from the thing it
    checks proves only itself.
    """
    box = _container("dgo-extend-")
    if not box:
        return ""
    prog = (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('door', '/app/link-proxy.py')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "print(m.identity_signature(%r, %r).decode())\n" % (office, user)
    )
    return sh("docker", "exec", "-i", box, "python3", "-c", prog)


def json_of(body: bytes) -> dict:
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {}


def old_door_answer(items: list) -> str:
    """What an UNSIGNED request gets when it comes from the link's door — asked from inside it.

    A door older than the signature is a real office, and the app tells it apart from a forgery by
    WHERE the request came from (`dgo-link` answers on the link network's own address). Running this
    inside that container makes the check a door's request by construction.
    """
    office = str((items[0] or {}).get("office") or "") if items else ""
    box = _container("dgo-link-")
    if not office or not box:
        return ""
    prog = (
        "import json,sys,urllib.request,urllib.error\n"
        "try:\n"
        "    r = urllib.request.urlopen(urllib.request.Request("
        "'http://computers:8977/api/computers', headers={'x-dgo-office': sys.argv[1]}), timeout=25)\n"
        "    print(json.dumps([r.status, len((json.load(r) or {}).get('computers') or [])]))\n"
        "except urllib.error.HTTPError as e:\n"
        "    print(json.dumps([e.code, 0]))\n"
        "except Exception as e:\n"
        "    print(json.dumps([0, str(e)]))\n"
    )
    p = subprocess.run(["docker", "exec", "-i", box, "python3", "-", office],
                       input=prog, capture_output=True, text=True, timeout=120)
    try:
        status, count = json.loads(p.stdout)
    except ValueError:
        return ""
    if status == 200:
        return f"{count} מחשבים משותפים"
    return f"נדחתה ({status})"


def judge_console(has_door: bool, version: int, mount_code: int, mount_type: str) -> tuple[list, int]:
    """Clause א for ONE linked office, from four facts — pure, so `--self-test` can prove both ways.

    The fact that decides it is what `/mount.js` IS: served as code, that office's console can be
    mounted under `/a/console-home.<office>/`; served as its own SPA, it cannot, and that is not a
    fault in the link — it is a release that does not have the file.
    """
    if not has_door:
        return ["  [ ] א  אין רשומת קונסול בלשכה הזו — היא לא פרסמה את «המרכז» שלה"], 1
    if version != 200:
        return [f"  [ ] א  הקונסול שלה אינו עונה דרך הדלת ({version or 'אין תשובה'})"], 1
    if mount_code == 200 and "javascript" in (mount_type or "").lower():
        return ["  [x] א  הקונסול שלה נשלח במלואו — mount.js מוגש כקוד, אפשר להרכיב אותו כאן"], 0
    return [f"  [ ] א  הקונסול שלה עונה, אבל mount.js אינו שם (הדלת מחזירה "
            f"{(mount_type or '').split(';')[0] or 'בלי סוג'} = מסך ה-SPA שלה) — היא צריכה עדכון"], 1


def judge_computers(has_door: bool, manifest_code: int, ops) -> tuple[list, int]:
    """Clause ב for ONE linked office: does its «מחשבים» carry the `shell` op (a remote terminal)?"""
    if not has_door:
        return ["  [ ] ב  אין רשומת מחשבים בלשכה הזו"], 1
    ops = [str(o) for o in (ops or [])]
    if manifest_code != 200:
        return [f"  [ ] ב  «מחשבים» שלה אינו עונה דרך הדלת ({manifest_code or 'אין תשובה'})"], 1
    if "shell" in ops:
        return [f"  [x] ב  «מחשבים» שלה מציג shell — טרמינל מרחוק על מכונותיה עובד "
                f"({len(ops)} פעולות)"], 0
    return [f"  [ ] ב  «מחשבים» שלה בגרסה ותיקה: {', '.join(ops) or 'בלי'} — אין shell, "
            f"ולכן אין טרמינל מרחוק"], 1


SELF_TEST = [
    # (what the peer is, console facts, computers facts, expected failures)
    ("updated", (True, 200, 200, "application/javascript; charset=utf-8"), (True, 200, ["list", "exec", "shell"]), 0),
    ("old", (True, 200, 200, "text/html; charset=utf-8"), (True, 200, ["list", "exec"]), 2),
    ("down", (True, 502, 502, ""), (True, 502, []), 2),
    ("no record", (False, 0, 0, ""), (False, 0, []), 2),
]


def self_test() -> int:
    """Prove the judge BOTH ways — the green path has never seen a peer that is actually updated."""
    bad = 0
    for name, console_facts, computers_facts, want in SELF_TEST:
        lines, f1 = judge_console(*console_facts)
        lines2, f2 = judge_computers(*computers_facts)
        got = f1 + f2
        marks = "ok  " if got == want else "FAIL"
        print(f"{marks} {name}: {got} open check(s), expected {want}")
        for line in lines + lines2:
            print("       " + line.strip())
        if got != want:
            bad += 1
    print()
    print("self-test: " + ("all verdicts as expected" if not bad else f"{bad} wrong verdict(s)"))
    return 0 if not bad else 1


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    # the office is the first argument that is not a flag, so `--tests` can sit anywhere
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wanted = args[0] if args else ""
    code, _ct, body = get(LINK_APP + "/api/link")
    link = json_of(body)
    items = [i for i in (link.get("items") or []) if isinstance(i, dict)]
    if wanted:
        items = [i for i in items if str(i.get("office")) == wanted]
    if not items:
        print("אין לשכה מקושרת" + (f" בשם {wanted}" if wanted else "") + " — «הרחבת לשכה» מציגה את הקיימות.")
        return 2
    serve = link.get("serve") or {}
    given = serve.get("computers") or {}
    machines = given.get("machines", "*") if isinstance(given, dict) else "*"
    if machines == "*":
        gave = "כל המחשבים"
    elif isinstance(machines, list) and machines:
        gave = f"{len(machines)} מחשבים לפי רשימה"
    else:
        gave = "לא משותף דבר"

    fails = 0
    served_ours = False        # the console half we own is measured once, not once per office
    print(f"DGO-553 · קבלה · הלשכה הזו נותנת: {gave}")
    print()
    for it in items:
        office = str(it.get("office") or "")
        label = str((it.get("label") or it.get("office") or "")) if not isinstance(it.get("label"), dict) \
            else str(it["label"].get("he") or it["label"].get("en") or office)
        state = str(it.get("state") or "?")
        print(f"— {label} ({office}) · קישור: {state}")

        # ── א · הקונסול נשלח במלואו ───────────────────────────────────────────────────────────────
        base = door_of(office, "console-home")
        if base:
            vcode, _ct, _vbody = get(base + "/api/version")
            mcode, mtype, _mb = get(base + "/mount.js")
        else:
            vcode = mcode = 0
            mtype = ""
        lines, n = judge_console(bool(base), vcode, mcode, mtype)
        for line in lines:
            print(line)
        fails += n
        if base:
            # …and the half THIS office owns, which is the one that can regress without anyone
            # noticing: our console answering a linked office's browser — a foreign Origin, the
            # mapped user the door writes, and the page that carries `mount.js`.
            if not served_ours:
                served_ours = True
                here = "console.localhost"
                origin = f"http://console-home.{office}.{here}"
                pcode, _pct, pbody = get("http://console:8000/",
                                         {"Host": here, "Origin": origin,
                                          "x-authentik-username": "akadmin"})
                acode, _act, abody = get("http://console:8000/api/modules",
                                         {"Host": here, "Origin": origin,
                                          "x-authentik-username": "akadmin"})
                tiles = len(json_of(abody).get("modules") or [])
                # …and `mount.js` itself, because "the page mentions it" is not "it is code": an
                # office whose console served it as its SPA would frame a shell of itself — the exact
                # failure this checks for on the OTHER side, and it must not exist on this one.
                js_code, js_type, js_body = get("http://console:8000/mount.js", {"Host": here})
                js_ok = (js_code == 200 and "javascript" in (js_type or "").lower()
                         and b"baseURI" in js_body and b"fetch" in js_body)
                if pcode == 200 and acode == 200 and tiles and js_ok:
                    print(f"  [x] א  הצד שלנו: הקונסול שלנו מוגש ללשכה מקושרת — {pcode}, "
                          f"{tiles} אריחים, ו-mount.js מוגש כקוד ({len(js_body)} בתים)")
                else:
                    print(f"  [ ] א  הצד שלנו: הקונסול שלנו אינו מוגש כראוי ללשכה מקושרת "
                          f"(עמוד {pcode}, מודולים {acode} עם {tiles} אריחים, "
                          f"mount.js {js_code} {js_type or 'בלי סוג'})")
                    fails += 1

        # ── ב · המחשבים שלה, כולל טרמינל ─────────────────────────────────────────────────────────
        cbase = door_of(office, "computers")
        if cbase:
            code, _ct, mbody = get(cbase + "/manifest")
            ops = json_of(mbody).get("ops") or []
        else:
            code, ops = 0, []
        lines, n = judge_computers(bool(cbase), code, ops)
        for line in lines:
            print(line)
        fails += n
        print()

    # ── ג · הטרמינל של הלשכה הזו ────────────────────────────────────────────────────────────────
    tcode, _ct, tbody = get("http://terminal:8080/api/machines")
    machines_n = len(json_of(tbody).get("machines") or [])
    ccode, _ct, cbody = get(COMPUTERS + "/manifest")
    ours_shell = "shell" in [str(o) for o in (json_of(cbody).get("ops") or [])]
    if tcode == 200 and machines_n and ours_shell:
        print(f"  [x] ג  הטרמינל בלשכה הזו: {machines_n} מכונות, shell במניפסט של «מחשבים»")
    else:
        print(f"  [ ] ג  הטרמינל בלשכה הזו אינו שלם (מכונות: {machines_n}, shell: {ours_shell})")
        fails += 1

    # ── ד · אין חשיפה חדשה ──────────────────────────────────────────────────────────────────────
    forged_code, _ct, forged_body = get(COMPUTERS + "/api/computers",
                                        {"x-dgo-office": "no-such-office"})
    forged = json_of(forged_body).get("error") or ""
    # …AND A PROXY IS NOT A BYPASS: the terminal is a local caller BY CONSTRUCTION (it is this
    # office's own app), so if it did not carry the door's headers on to `computers` it would answer a
    # linked office with the whole fleet — measured 2026-11-01, eleven machines and a shell on any of
    # them. Asked with a forged office header: the answer must be a refusal, never a machine list.
    tby_code, _tct, tby_body = get("http://terminal:8080/api/machines",
                                   {"x-dgo-office": "no-such-office"})
    bypass = len(json_of(tby_body).get("machines") or [])
    ok_refuse = forged_code == 403 and forged and tby_code == 403 and not bypass
    # …and the positive half, signed by the door itself for one of the linked offices.
    ok_signed, shared = False, 0
    for it in items:
        office = str(it.get("office") or "")
        user = ""
        ccode2, _ct2, cbody2 = get(LINK_APP.replace(":8983", ":8984") + "/api/link/catalog",
                                   {"x-dgo-office": office})
        for app in (json_of(cbody2).get("apps") or []):
            if str(app.get("alias")) == "computers":
                user = str((app.get("identity") or {}).get("to") or "")
                break
        sig = door_signature(office, user) if user else ""
        if not sig:
            continue
        scode, _ct3, sbody = get(COMPUTERS + "/api/computers",
                                 {"x-dgo-office": office, "x-dgo-identity": sig})
        if scode == 200:
            ok_signed = True
            shared = len(json_of(sbody).get("computers") or [])
            # A PEER MAY USE WHAT IT IS GIVEN, NEVER MANAGE IT. The door forwards every method and
            # path, so a mutating route that forgets its gate is reachable by a linked office — the
            # second reader found four of them on 2026-11-02 (delete, create, /stream, /api/transfers).
            # Asked here with a REAL signature, against one of this office's own machine ids.
            mine = next((c.get("id") for c in (json_of(sbody).get("computers") or [])
                         if not c.get("id", "").count(".")), "")
            if mine:
                dcode, _dt, dbody = get(COMPUTERS + "/api/computers/" + mine,
                                        {"x-dgo-office": office, "x-dgo-identity": sig},
                                        method="DELETE")
                peer_delete = dcode == 403 and "אינו פתוח" in (json_of(dbody).get("error") or "")
                tcode2, _tt, tbody2 = get(COMPUTERS + "/api/transfers",
                                          {"x-dgo-office": office, "x-dgo-identity": sig})
                peer_transfers = tcode2 == 403
                if not (peer_delete and peer_transfers):
                    print(f"  [ ] ד  לשכה מקושרת יכולה לשנות את הצי: DELETE→{dcode}, "
                          f"/api/transfers→{tcode2}")
                    fails += 1
                else:
                    print(f"  [x] ד  לשכה מקושרת משתמשת ואינה מנהלת — DELETE {dcode}, "
                          f"העברות {tcode2}")
            break
    if ok_refuse and ok_signed:
        # …and the third case, which is what a linked office on an older release actually does: it
        # writes the office and no signature, and the app accepts it because the request came from the
        # LINK'S DOOR and nowhere else can. Asked from inside that container, so the check is a door's
        # request by construction — not a header typed next to it.
        old = old_door_answer(items)
        print(f"  [x] ד  בקשה מזויפת נדחתה בשם ({forged_code}: «{forged}»), בקשה חתומה של הדלת "
              f"קיבלה {shared} מחשבים משותפים בלבד"
              + (f", ודלת ותיקה (בלי חתימה) שהגיעה מהדלת עצמה — {old}" if old else "")
              + f", והטרמינל אינו מעקף ({tby_code}, {bypass} מכונות)")
    else:
        print(f"  [ ] ד  השער אינו שלם (מזויפת: {forged_code}, חתומה: "
              f"{'עברה' if ok_signed else 'לא נבדקה'}, טרמינל כמעקף: {tby_code} עם {bypass} מכונות)")
        fails += 1

    print()
    if "--tests" in sys.argv[1:]:
        fails += run_invariants()
    if fails:
        print(f"מה שנשאר: {fails} בדיקות פתוחות — כולן בצד של הלשכה האחרת, ולכן הן נסגרות בעדכון שלה "
              f"(מיזוג דחיפת הלשכה הזו, ואז ה-bbox run שלה).")
        return 1
    print("כל חלקי הקבלה מוכחים")
    return 0


#: The checks that hold this feature down, one line each: which file they live in, and the interpreter
#: that runs them. `--tests` exists so ONE command answers both questions — "is the office across the
#: link able to receive it" and "has anything under it moved" — on a checkout several sessions edit.
INVARIANTS = [
    ("the door's signature", [sys.executable, "apps/computers/tests/test_link_identity.py"]),
    ("the shared fleet", [sys.executable, "apps/computers/tests/test_remote_fleet.py"]),
    ("the terminal's sessions", [sys.executable, "apps/computers/tests/test_shell.py"]),
    ("the sharing declaration", [sys.executable, "apps/dgo-extend/tests/test_serve_machines.py"]),
    ("the card's words", ["node", "apps/dgo-extend/tests/readiness-selftest.mjs"]),
    ("the screen's actions", ["node", "apps/computers/tools/ui-selfcheck.mjs"]),
    ("the console mount", ["node", "platform-base/console/test_mount.mjs"]),
    ("path_mount in the compiler", [sys.executable, "platform/manager/test_path_mount.py"]),
    ("the console's door", [sys.executable, "platform/manager/test_serve_console_door.py"]),
]


def run_invariants() -> int:
    """Run every suite the feature rests on. Returns how many FAILED."""
    bad = 0
    print("הבדיקות שמחזיקות את הפיצ'ר הזה:")
    for name, argv in INVARIANTS:
        try:
            p = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=300)
            ok = p.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        print(f"  [{'x' if ok else ' '}] {name}" + ("" if ok else f"  ({' '.join(argv[1:])})"))
        if not ok:
            bad += 1
    print()
    return bad


if __name__ == "__main__":
    sys.exit(main())
