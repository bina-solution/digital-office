"""cli — «אלמנט» from the shell: one call to the app's own adapter per verb (DGO-1264).

Runs INSIDE the element container (tools/verb does it: `docker exec … python3 -c <this file> <verb> …`), so it
needs no address and reads the app's bearer token from the volume, never from an argument. The standard
(ai/context/app-cli-api-standard.md): --json on every verb; exit 0 answered / 1 failed / 2 usage / 3 the app
did not answer. A secret arrives on stdin only.

    status                                   up, and which Matrix account this device is signed in as
    login <homeserver> <user> --password-stdin   sign this device in with a password (read from stdin)
    login <homeserver> --token-stdin             …or with an access token copied from Element (stdin)
    logout                                   this device signs out (the screen's own sign-in is untouched)
    rooms [N]                                the joined rooms, newest first (default 50)
    read <room id> [N]                       the room's last N messages (default 20)
    send <room id> <text…>                   a text message into a room that is not encrypted
    mark-read <room id> <event id>           the read receipt up to that message
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("ELEMENT_ADAPTER_URL", "http://127.0.0.1:3093").rstrip("/")
TOKEN_FILE = os.path.join(os.environ.get("ELEMENT_STATE", "/data/adapter"), "api-token")


def usage(msg=""):
    if msg:
        print("element: " + msg, file=sys.stderr)
    print(__doc__.split("\n\n", 2)[2].rstrip(), file=sys.stderr)
    return 2


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with open(TOKEN_FILE) as f:
            req.add_header("Authorization", "Bearer " + f.read().strip())
    except OSError:
        pass                                    # /v1/health needs none; anything else answers 401, said below
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": f"http-{e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"element: the adapter did not answer ({getattr(e, 'reason', e)})", file=sys.stderr)
        sys.exit(3)


def flat(v, n=200):
    """What a person typed: one line, so a message cannot forge another line or a column."""
    return " ".join(str(v if v is not None else "").split())[:n]


def secret_from_stdin(what):
    if sys.stdin.isatty():
        sys.exit(usage(f"the {what} is read from stdin, and stdin is a terminal"))
    v = sys.stdin.readline().rstrip("\r\n")         # only the line's end: a space can be part of a password
    if not v:
        sys.exit(usage(f"no {what} on stdin"))
    return v


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if not args or args[0] in ("-h", "--help", "help"):
        return usage()
    verb, rest = args[0], args[1:]
    room = lambda r: urllib.parse.quote(r, safe="")     # noqa: E731

    if verb == "status" and not rest:
        code, d = call("GET", "/v1/health")
    elif verb == "login" and rest and rest[-1] in ("--password-stdin", "--token-stdin"):
        if rest[-1] == "--token-stdin" and len(rest) == 2:
            code, d = call("POST", "/v1/login", {"homeserver": rest[0], "access_token": secret_from_stdin("access token")})
        elif rest[-1] == "--password-stdin" and len(rest) == 3:
            code, d = call("POST", "/v1/login", {"homeserver": rest[0], "user": rest[1], "password": secret_from_stdin("password")})
        else:
            return usage("login <homeserver> <user> --password-stdin, or login <homeserver> --token-stdin")
    elif verb == "logout" and not rest:
        code, d = call("POST", "/v1/logout")
    elif verb == "rooms" and len(rest) <= 1:
        if rest and not rest[0].isdigit():
            return usage(f"a count is a number, not {rest[0]!r}")
        code, d = call("GET", "/v1/conversations?limit=" + (rest[0] if rest else "50"))
    elif verb == "read" and 1 <= len(rest) <= 2:
        if len(rest) == 2 and not rest[1].isdigit():
            return usage(f"a count is a number, not {rest[1]!r}")
        code, d = call("GET", f"/v1/conversations/{room(rest[0])}?limit=" + (rest[1] if len(rest) == 2 else "20"))
    elif verb == "send" and len(rest) >= 2:
        code, d = call("POST", f"/v1/conversations/{room(rest[0])}/messages", {"text": " ".join(rest[1:])})
    elif verb == "mark-read" and len(rest) == 2:
        code, d = call("POST", f"/v1/conversations/{room(rest[0])}/read", {"event_id": rest[1]})
    else:
        return usage(f"unknown verb or arguments: {' '.join(args)}")

    if as_json:
        print(json.dumps(d, ensure_ascii=False))
    elif code >= 400:
        pass
    elif verb == "status":
        print(f"signed in as {d.get('user_id')} on {d.get('homeserver')} (device {d.get('device_id')})"
              if d.get("signed_in") else "not signed in — ./bbox element login <homeserver> <user> --password-stdin")
    elif verb == "rooms":
        for c in d.get("conversations") or []:
            print(f"{c['id']}\t{flat(c.get('name'), 80)}\t{'encrypted' if c.get('encrypted') else 'plain'}\t{c.get('unread', 0)}")
    elif verb == "read":
        for m in d.get("messages") or []:
            print(f"{m.get('ts')}\t{m.get('from')}\t{m.get('id')}\t" + ("[encrypted — read it on the screen]" if m.get("encrypted") else flat(m.get("text"))))
    elif verb == "login":
        print(f"signed in as {d.get('user_id')} (device {d.get('device_id')})")
    elif verb == "send":
        print(f"sent\t{d.get('id')}")
    else:
        print("ok")
    if code >= 400:
        print(f"element: {d.get('error')}: {d.get('detail') or ''}".rstrip(": "), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
