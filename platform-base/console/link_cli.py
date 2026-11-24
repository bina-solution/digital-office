"""bbox console link — the ONE builder of a link a person is given (DGO-1433).

    bbox console link <ref> [--for <who>] [--as <user>]
                                            resolve <ref> on the herd's hub console, open its frame past the sign-in
                                            as <user> (default: this office's own account), and print the link — or,
                                            when it does not open, the sentence why (exit 1)
    bbox console link check                 open every link in the ledger again; exit 1 when one no longer opens
    bbox console link list                  the ledger: what was given, to whom, when, when last opened

    <ref>:  DGO-1433 (a work item) · meet/exu101 (a meeting) · bina-claude.hp-laptop[/<route>] (an app on an office)

The link is `https://<the hub's console>/go/<ref>` (platform-base/console/links.py) and nothing else: a path the
console resolves at click time against its own live registry, which survives every sign-in round trip. It is
returned ONLY after the hub's console opened the frame the shell would load for it, as its edge sends it after
the sign-in (app.py `links_check`, run in the console's own process) and was answered with the page itself — a
redirect elsewhere, the door's refusal, the console's card, `unknown_app` or a sign-in page is a refusal with its
sentence. The host is never internal: a `.localhost`, an address, a port or a bare name refuses (RFC 6761 — on a
phone `localhost` is the phone).

Where: the herd's hub (apps/computers/herd.yaml `hub:`) is the console the owner works from away from home, so a
link is built THERE. Run anywhere else, the verb runs on the hub through `bbox via` (once: BBOX_VIA stops a second
hop). The ledger is the hub console's own (its store data/console/links, app.py `links_record`): one line per link given and per
check, never edited; the console opens every link given again every 15 minutes and writes a notice for a link that
stopped opening (`links_recheck`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INTERNAL = re.compile(r"(^|\.)localhost$|^\d+\.\d+\.\d+\.\d+$|^\[|:\d+$|^[^.]+$")


def env(key: str, default: str = "") -> str:
    """A value of this office's `.env` (the last assignment wins, quotes dropped), or the environment's."""
    if os.environ.get(key):
        return os.environ[key]
    val = default
    try:
        with open(os.path.join(REPO, ".env"), encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.match(r"^\s*(?:export\s+)?%s\s*=\s*(.*?)\s*$" % re.escape(key), line)
                if m:
                    val = m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return val


def hub(me: str = "") -> str:
    """The herd's hub (apps/computers/herd.yaml `hub:`) — only for an office that is one of the herd's own, by its
    name or an alias under `offices:`. A client's office runs this checkout: it builds its links on its own console,
    never on ours (as apps/project-pln/where.sh decides)."""
    try:
        with open(os.path.join(REPO, "apps", "computers", "herd.yaml"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    m = re.search(r"^hub:\s*([A-Za-z0-9_-]+)", text, re.M)
    block = re.search(r"^offices:\n((?:[ #].*\n|\n)*)", text, re.M)
    if not m or not block or not me:
        return ""
    names = set(re.findall(r"^  ([a-z0-9-]+):", block.group(1), re.M))
    for aliases in re.findall(r"^    aliases:\s*\[([^\]]*)\]", block.group(1), re.M):
        names |= {a.strip().lower() for a in aliases.split(",") if a.strip()}
    return m.group(1).lower() if me in names else ""


def public_base() -> tuple[str, str]:
    """(https://<console host>, "") — or ("", why) when this office's console has no address a person can open."""
    host = env("CONSOLE_BASE_URL").strip().strip("/").lower()
    host = re.sub(r"^https?://", "", host)
    proto = (env("AUTH_PROTOCOL") or "https").strip().lower()
    if not host:
        return "", "ללשכה הזאת אין כתובת קונסול (CONSOLE_BASE_URL ריק ב-.env)"
    if INTERNAL.search(host):
        return "", f"הכתובת של הקונסול כאן ({host}) פנימית — בטלפון או בלשכה אחרת היא מצביעה על המכשיר של הקורא עצמו"
    if proto != "https":
        return "", f"הקונסול כאן מוגש ב-{proto} ולא ב-https"
    return f"https://{host}", ""


def console_container() -> str:
    out = subprocess.run(["docker", "ps", "-q", "--filter", "label=com.docker.compose.service=console"],
                         capture_output=True, text=True, timeout=30)
    ids = [x for x in out.stdout.split() if x]
    return ids[0] if ids else ""


#: What runs IN the console's own process (`docker exec … python3 -c`): the check, and the ledger it keeps in its own
#: store (app.py `links_check`, `links_record`, `links_recheck`, `links_given`) — no route exposes any of it.
IN_CONSOLE = """
import json, sys
sys.path.insert(0, '/app')
import app
verb, ref, user, query, base, who = sys.argv[1:7]
if verb == 'build':
    out = app.links_check(ref, user, query)
    if out.get('ok'):
        said = '; '.join(c.get('said', '') for c in out.get('checks') or [])
        app.links_record({'path': out['path'], 'link': base + out['path'], 'opens': out.get('opens'), 'for': who,
                          'as': user, 'given_at': out['at'], 'checked_at': out['at'], 'ok': True, 'said': said})
elif verb == 'check':
    out = {'rows': app.links_recheck()}
else:
    out = {'rows': sorted(app.links_given().values(), key=lambda r: r.get('given_at') or 0)}
sys.stdout.write('\\nLINKS-CHECK ' + json.dumps(out, ensure_ascii=False) + '\\n')
"""


def in_console(verb: str, ref: str = "", user: str = "", base: str = "", who: str = "") -> dict:
    """Run `verb` in the hub console's own process: build (check + record), check (open every link again), list."""
    cid = console_container()
    if not cid:
        return {"ok": False, "why": "הקונסול של הלשכה הזאת לא רץ"}
    path, _, query = ref.partition("?")
    try:
        p = subprocess.run(["docker", "exec", "-i", "-w", "/app", cid, "python3", "-c", IN_CONSOLE,
                            verb, path, user, query, base, who], capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "הקונסול לא סיים את הבדיקה בתוך עשר דקות"}
    line = next((x for x in reversed(p.stdout.splitlines()) if x.startswith("LINKS-CHECK ")), "")
    try:
        return json.loads(line[len("LINKS-CHECK "):])
    except ValueError:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-1:] or [""]
        return {"ok": False, "why": "הקונסול לא ענה על הבדיקה (" + tail[0][:200] + ")"}


def check_user(who: str) -> str:
    """Who a link is opened as: `--as <user>`, else this office's own sign-in account (AUTHENTIK_BOOTSTRAP_USER) —
    the owner's — and said in the answer, so a verdict always names whose eyes it is."""
    return who or env("AUTHENTIK_BOOTSTRAP_USER") or "akadmin"



def build(ref: str, who: str, user: str) -> int:
    base, why = public_base()
    if not base:
        print(f"link: {why} — אין קישור", file=sys.stderr)
        return 1
    out = in_console("build", ref, user, base, who)
    if not out.get("ok"):
        picks = " · ".join(c.get("go", "") for c in out.get("choices") or [])
        print(f"link: {out.get('ref') or ref} לא נפתח — {out.get('why') or 'בלי סיבה'}"
              + (f" {picks}" if picks else "") + " — אין קישור", file=sys.stderr)
        return 1
    said = "; ".join(c.get("said", "") for c in out.get("checks") or [])
    # exactly what was proven: the frame's page answered past the gate, as `user` — that the screen DREW is a
    # browser's to prove (the item's proof does that). Recorded in the console's ledger, re-opened every 15 minutes.
    print(f"link: {out['path']} → {out.get('opens')} · נפתח מעבר לשער כ-{user}: {said}", file=sys.stderr)
    print(base + out["path"])
    return 0


def check() -> int:
    out = in_console("check")
    rows = out.get("rows")
    if rows is None:
        print(f"link: {out.get('why') or 'הבדיקה לא רצה'}", file=sys.stderr)
        return 1
    for r in rows:
        print(("✓ " if r.get("ok") else "✗ ") + str(r.get("link") or r.get("path"))
              + ("" if r.get("ok") else f" — {r.get('said')}"))
    if not rows:
        print("link: היומן ריק — לא ניתן עדיין אף קישור")
    return 0 if all(r.get("ok") for r in rows) else 1


def listing() -> int:
    out = in_console("list")
    for r in out.get("rows") or []:
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(r.get("checked_at") or r.get("given_at") or 0))
        print(f"{'✓' if r.get('ok') else '✗'} {r.get('link')}  ·  {r.get('for') or '—'}  ·  נבדק {when} UTC")
    if out.get("rows") is None:
        print(f"link: {out.get('why') or 'היומן לא נקרא'}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.split("\n\n")[0])
        return 0 if argv else 2
    me = (env("DGO_OFFICE_ID") or "").lower()
    h = hub(me)
    if h and me != h and not os.environ.get("BBOX_VIA"):
        # built where the owner opens it: the herd's hub — the verb runs there, once
        p = subprocess.run([os.path.join(REPO, "bbox"), "via", h, "console", "link", *argv],
                           capture_output=True, text=True)
        sys.stdout.write(p.stdout)
        if p.returncode and re.search(r"unknown: bbox console link|no such (verb|hook)", p.stdout + p.stderr):
            # the hub's checkout has no builder yet: its console does not answer /go/ either (measured 2026-11-08)
            print(f"link: בלשכת {h} עוד אין את הבונה — הקונסול שלה לא עונה /go/ (DGO-1433 עוד לא נלקח שם) — אין קישור",
                  file=sys.stderr)
        else:
            sys.stderr.write(p.stderr)
        return p.returncode
    opts = {}
    for flag in ("--for", "--as"):
        if flag in argv:
            i = argv.index(flag)
            opts[flag] = argv[i + 1] if i + 1 < len(argv) else ""
            argv = argv[:i] + argv[i + 2:]
    if not argv:
        print(__doc__.split("\n\n")[0])
        return 2
    verb = argv[0]
    if verb == "check":
        return check()
    if verb == "list":
        return listing()
    return build(verb, opts.get("--for") or "owner", check_user(opts.get("--as", "")))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
