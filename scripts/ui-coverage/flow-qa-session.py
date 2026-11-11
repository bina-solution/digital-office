#!/usr/bin/env python3
"""flow-qa-session.py — mint the signed-in browser the flow suite needs (rel-2), in one command.

WHY THIS FILE EXISTS (rel-2). `digital-office/sim/flow-qa.py` aims every flow at a RUNNING office with
`--url <base>`, and on vps1 that base (`https://console.staging.digital-office.co.il`) answers 302 to
the office's sign-in: the browser lands on the login form, the rail is empty, and only the flows that
need no sign-in pass (3/62, measured). The suite had no way to be signed in — its only flags were
`--url`, `--tiles`, `--mobile`, `--accent`, `--ink`, `--surface` — so a live baseline was unreachable
by declaration and the only alternative was a hand-driven browser. This is the missing producer: it
turns an approval the office ALREADY HOLDS into a Playwright `storage_state` file, and the suite takes
it with `--auth <file>`. `bbox flow-qa-session` is the verb.

WHO SIGNS IN, AND WHERE. Not authentik: this office's identity service is `platform-base/forward-auth`
(the Go drop-in that replaced it in layers 1–2), and it publishes no `/api/v3/flows/executor/…` — that
path is a plain 404 here (measured 2026-11-04). What it does publish is the door every browser uses:
`GET /login?rd=<url>` renders a form carrying the `rd` and a one-time `st` token, `POST /login` takes
`user`, `password`, `rd`, `st` and answers with the `dgo_session` cookie for the office's domain. That
is a supported surface of the office's own sign-in, so this script drives exactly it — and then it
VERIFIES the result against the address the suite will be aimed at before it writes anything.

WHERE THE APPROVAL COMES FROM. `.env` — the same file `bbox` reads, which is also where the credential
plane's own entry for these secrets points (`GET http://connections:8990/api/connections` reports
`source: "env"` for them, so the vault and this file are one fact and not two). The names are
`AUTHENTIK_BOOTSTRAP_USER` / `AUTHENTIK_BOOTSTRAP_PASSWORD`, carried through the authentik → forward-auth
migration (forward-auth reads authentik's own password rows, README §"The two things that must survive
a swap"). Override with `--user` / `--password-stdin`, or `FLOW_QA_USER` / `FLOW_QA_PASSWORD`.

WHAT IT NEVER DOES. It never prints, stores under a name git tracks, or sends anywhere else a password,
a token or a cookie VALUE: the only lines it prints are the addresses, the cookie NAMES, their domains
and the path it wrote. The file it writes is `ci-artifacts/flow-qa/storage-state.json` — `ci-artifacts/`
is in `.gitignore` — and it is chmod 600. **And it writes to no other kind of place**: `--out` is
checked against git itself (`git check-ignore`), so a path git would commit is refused by name before
a password is ever posted — a live session in `git add -A` is the office's cookies in a commit. It
touches no check and no threshold: it supplies cookies and nothing else, and the suite's own verdict
is still the run's verdict.

EXIT CODES (the shell's `bbox flow-qa` prints them; 3 is deliberately not one of the suite's 0/1/2).
Each is the NUMBER below — the `EXIT_*` constants, with the human line on stderr and its `(exit N)`
hint kept in it — so a gate reading `$?` and a person reading the terminal are told the same thing.
Before 2026-11-10 every one of these left as `sys.exit("<text> … (exit 3)")`, and a string exit is **1**:
"no session" and "a flow failed" were one number to every caller. `digital-office/sim/flow-qa.py`
carries the same 3 and 4 for the same facts.
  0  signed in, verified against the target, storage_state written
  2  the office's sign-in refused the account (its page came back with the form again) — a real fact, not a bug here
  3  no session was minted: no sign-in service answered (DNS, TLS, HTTP), no sign-in form came back, or
     the target/account/sign-in host was never declared — the address or the office, named with what came back
  4  signed in but the TARGET is still not reachable signed-in (it answered 302 to /login, or a non-200)

USAGE
  bbox flow-qa-session                                   # target https://$CONSOLE_BASE_URL from .env
  bbox flow-qa-session --url https://console.example.com  # another address, same office sign-in
  bbox flow-qa-session --identity https://auth.example.com --out ci-artifacts/flow-qa/state.json
  ./bbox flow-qa console --live=https://console.staging.digital-office.co.il \
      --auth ci-artifacts/flow-qa/storage-state.json
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_OUT = 'ci-artifacts/flow-qa/storage-state.json'
# ── THE EXIT CONTRACT, IN ONE PLACE, AND IT IS A NUMBER ─────────────────────────────────────────
# The docstring above declares 0/2/3/4 and the shell prints them. Every path here used to leave with
# `sys.exit("<text> … (exit 3)")`, and `sys.exit` on a STRING exits **1** — so "no session was minted"
# arrived at every gate and CI job as "the suite went red", the one thing the codes exist to tell
# apart (measured 2026-11-10). The numbers are these, the text goes to stderr, and the `(exit N)` hint
# stays in it. The suite (`digital-office/sim/flow-qa.py`) carries the same pair, so a run of either
# answers 3 and 4 for the same facts.
EXIT_OK = 0              # signed in, verified against the target, storage_state written
EXIT_REFUSED = 2         # the office's sign-in refused the account — a real fact, not a bug here
EXIT_NO_SESSION = 3      # no session was minted: nothing answered, or nothing was declared to use
EXIT_TARGET_REFUSED = 4  # signed in, but the TARGET did not take the session (or set no cookie)
# The form fields the office's sign-in renders (platform-base/forward-auth/setup.go + handlers.go).
HIDDEN = re.compile(r'name="(rd|st)"\s+value="([^"]*)"')
# …and the password field, which is what proves the page in hand is a SIGN-IN FORM and not a refusal.
FORM_MARK = re.compile(r'name="password"', re.I)


def refuse(msg, code=EXIT_NO_SESSION):
    """Say it on stderr and leave with an EXIT CODE that means it — the one way out of this file that
    is not `return 0`. `msg` already carries its own `(exit N)` hint, so a human reading stderr and a
    script reading `$?` are told the same thing."""
    print(msg, file=sys.stderr)
    sys.exit(code)


def guarded_out(raw):
    """`--out` is where a LIVE SESSION is written (chmod 600), so it may not be a path git tracks:
    a session file in `git add -A` is the office's cookies in a commit. The one rule that decides it
    is git's own — `git check-ignore` — read from the repo root, so `.gitignore` (and any nested one)
    stays the single place that says what is ignored, and this file invents no second list."""
    out = pathlib.Path(raw)
    if not out.is_absolute():
        out = REPO_ROOT / out
    probe = out.resolve()
    try:
        r = subprocess.run(['git', 'check-ignore', '-q', str(probe)],
                           cwd=str(REPO_ROOT), capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        refuse(f'flow-qa-session: cannot ask git about {probe} ({type(e).__name__}: {e}) — refusing to '
               f'write a live session to a path nobody checked (exit {EXIT_NO_SESSION})')
    if r.returncode not in (0, 1):        # 128 is git's own fatal: not a repo, or git unhappy — not a verdict
        refuse(f'flow-qa-session: cannot ask git about {probe} (check-ignore exited {r.returncode}: '
               f'{(r.stderr or b"").decode("utf-8", "replace").strip()[:200] or "no word"}) — refusing to '
               f'write a live session to a path nobody checked (exit {EXIT_NO_SESSION})')
    if r.returncode == 1:
        refuse(f'flow-qa-session: refusing to write a live session to {probe} — git does NOT ignore that '
               f'path, so it would be committed. Name a path under a gitignored directory (the default '
               f'{DEFAULT_OUT} is ignored by `.gitignore`), or add the path to `.gitignore` first. '
               f'(exit {EXIT_NO_SESSION})')
    return out


def read_env(path=REPO_ROOT / '.env'):
    """The office's own `.env`, read the way bbox reads it: `KEY=value`, one per line."""
    env = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return env
    for line in lines:
        s = line.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        k, v = s.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class Jar:
    """One cookie jar and the opener that fills it. No redirect is hidden: the caller sees the final
    URL, because on this door the final URL is the proof (a signed-in browser lands on the office)."""

    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def get(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            r = self.op.open(req, timeout=45)
            return r.status, r.read().decode('utf-8', 'replace'), r.geturl()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace'), url
        except Exception as e:                        # DNS, TLS, refused: the address, not a verdict
            return None, f'{type(e).__name__}: {e}', url


def said(where, code, body):
    """What came back, short and without a secret: the code, and the first line of the body only when
    the body is not a page that could carry a token (a sign-in form's HTML is never echoed)."""
    if code is None:
        return f'{where}: {body}'
    head = ' '.join(body.strip().splitlines()[:1])[:120] if body else ''
    return f'{where}: HTTP {code}' + (f' — {head}' if head and '<' not in head else '')


def cookie_record(c):
    """One Playwright storage_state cookie, field for field."""
    return {
        'name': c.name,
        'value': c.value,
        'domain': c.domain,
        'path': c.path or '/',
        'expires': -1 if c.expires is None else float(c.expires),
        'httpOnly': bool(c.has_nonstandard_attr('HttpOnly')),
        'secure': bool(c.secure),
        'sameSite': 'Lax',            # the office's cookie is a session cookie sent on its own site
    }


def main():
    env = read_env()
    ap = argparse.ArgumentParser(add_help=True, description='mint a signed-in Playwright storage_state for the flow suite')
    ap.add_argument('--url', default='', help='the address flow-qa will be aimed at (default: https://$CONSOLE_BASE_URL)')
    ap.add_argument('--identity', default='', help='the office sign-in host (default: https://$FORWARD_AUTH_BASE_URL, else $AUTHENTIK_BASE_URL)')
    ap.add_argument('--user', default='', help='the account (default: $FLOW_QA_USER, else $AUTHENTIK_BOOTSTRAP_USER)')
    ap.add_argument('--password-stdin', action='store_true', help='read the password from stdin instead of .env')
    ap.add_argument('--out', default=DEFAULT_OUT, help=f'where to write it (default: {DEFAULT_OUT}, gitignored)')
    a = ap.parse_args()
    # WHERE THE SESSION GOES IS SETTLED BEFORE ANY NETWORK: a path git would commit is refused here,
    # not after a password has been used to mint a session for it (`guarded_out` asks git itself).
    out = guarded_out(a.out)

    target = (a.url or ('https://' + env['CONSOLE_BASE_URL'] if env.get('CONSOLE_BASE_URL') else '')).rstrip('/')
    ident = (a.identity or ('https://' + (env.get('FORWARD_AUTH_BASE_URL') or env.get('AUTHENTIK_BASE_URL', '')))).rstrip('/')
    if not target:
        refuse(f'flow-qa-session: no target — pass --url, or set CONSOLE_BASE_URL in .env '
               f'(exit {EXIT_NO_SESSION})')
    if ident in ('https:/', 'https:'):
        refuse(f'flow-qa-session: no sign-in host — pass --identity, or set FORWARD_AUTH_BASE_URL in '
               f'.env (exit {EXIT_NO_SESSION})')
    user = a.user or env.get('FLOW_QA_USER') or env.get('AUTHENTIK_BOOTSTRAP_USER', '')
    password = (sys.stdin.readline().rstrip('\n') if a.password_stdin
                else env.get('FLOW_QA_PASSWORD') or env.get('AUTHENTIK_BOOTSTRAP_PASSWORD', ''))
    if not user or not password:
        refuse(f'flow-qa-session: no account — set AUTHENTIK_BOOTSTRAP_USER/PASSWORD in .env, or pass '
               f'--user and --password-stdin (exit {EXIT_NO_SESSION})')
    print(f'flow-qa-session: {target}  via  {ident}  as  {user}')

    jar = Jar()
    landing = f'{ident}/login?rd=' + urllib.parse.quote(target + '/', safe='')
    code, body, _ = jar.get(landing)
    if not code:
        refuse(f'flow-qa-session: the sign-in host did not answer — {said(ident, code, body)} (exit {EXIT_NO_SESSION})')
    form = dict(HIDDEN.findall(body))
    if code != 200 or not FORM_MARK.search(body):
        refuse(f'flow-qa-session: {ident}/login is not a sign-in form — '
               f'{said(ident + "/login", code, body)} (exit {EXIT_NO_SESSION})')
    print(f'flow-qa-session: sign-in form at /login (rd + st taken from the page)')

    data = urllib.parse.urlencode({'user': user, 'password': password,
                                   'rd': form.get('rd', '') or target + '/',
                                   'st': form.get('st', '')}).encode()
    code, body, final = jar.get(f'{ident}/login', data=data,
                                headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if not code:
        refuse(f'flow-qa-session: the sign-in POST did not answer — {said(ident, code, body)} (exit {EXIT_NO_SESSION})')
    if FORM_MARK.search(body) and urllib.parse.urlsplit(final).path.startswith('/login'):
        # the form came back: the account was refused. Said plainly, and nothing is written.
        refuse(f'flow-qa-session: the office refused {user} — /login answered {said("", code, "")[2:] or code} '
               f'with the form again (exit {EXIT_REFUSED})', EXIT_REFUSED)

    # THE PROOF, BEFORE ANYTHING IS WRITTEN: the target must answer signed-in from this very jar.
    code2, body2, final2 = jar.get(target + '/')
    if not code2:
        refuse(f'flow-qa-session: signed in, but the target did not answer — {said(target, code2, body2)} '
               f'(exit {EXIT_TARGET_REFUSED})', EXIT_TARGET_REFUSED)
    if code2 != 200 or urllib.parse.urlsplit(final2).path.startswith('/login') or FORM_MARK.search(body2[:4000]):
        refuse(f'flow-qa-session: signed in, but the target still sends the browser to the sign-in — '
               f'{said(target, code2, body2)} (final {final2}) (exit {EXIT_TARGET_REFUSED})', EXIT_TARGET_REFUSED)
    print(f'flow-qa-session: signed in — {target}/ answers {code2}')

    cookies = [cookie_record(c) for c in jar.cj]
    if not cookies:
        refuse(f'flow-qa-session: the sign-in answered 200 but set no cookie — nothing to hand the '
               f'browser (exit {EXIT_TARGET_REFUSED})', EXIT_TARGET_REFUSED)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'cookies': cookies, 'origins': []}, indent=1), encoding='utf-8')
    out.chmod(0o600)                   # a live session: readable by the office that minted it, and by nobody else
    rel = out.relative_to(REPO_ROOT) if REPO_ROOT in out.parents else out
    print(f'flow-qa-session: wrote {len(cookies)} cookie(s) {[c["name"] for c in cookies]} '
          f'for {sorted({c["domain"] for c in cookies})} → {rel}')
    print(f'flow-qa-session: next — ./bbox flow-qa console --live={target} --auth {rel}')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
