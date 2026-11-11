"""cli — «סלאק» from the shell: one call to the app's own adapter per verb (DGO-1264).

Runs INSIDE the slack container (tools/verb does it: `docker exec … python3 -c <this file> <verb> …`), so it
needs no address and reads the app's bearer token from the volume, never from an argument. The standard
(ai/context/app-cli-api-standard.md): --json on every verb; exit 0 answered / 1 failed / 2 usage / 3 the app
did not answer. A secret arrives on stdin only.

    status                                   up, and which workspace and user the token is (asked of Slack)
    login --token-stdin                      keep the owner's user token (xoxp-…), checked with auth.test first
    logout                                   forget the token (revoking it is the owner's, in his Slack app)
    rooms [N]                                channels, private channels and DMs, in Slack's order (default 100)
    read <channel id> [N]                    the last N messages (default 20)
    send <channel id> <text…>                a message, as the owner
    mark-read <channel id> <ts>              read up to that message
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("SLACK_ADAPTER_URL", "http://127.0.0.1:3094").rstrip("/")
TOKEN_FILE = os.path.join(os.environ.get("SLACK_STATE", "/data/adapter"), "api-token")


def usage(msg=""):
    if msg:
        print("slack: " + msg, file=sys.stderr)
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
        # longer than the adapter's worst case: `rooms 1000` is up to 5 pages at Slack's 30 s each
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": f"http-{e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"slack: the adapter did not answer ({getattr(e, 'reason', e)})", file=sys.stderr)
        sys.exit(3)


def flat(v, n=200):
    """What a person typed: one line, so a message cannot forge another line or a column."""
    return " ".join(str(v if v is not None else "").split())[:n]


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if not args or args[0] in ("-h", "--help", "help"):
        return usage()
    verb, rest = args[0], args[1:]
    q = lambda c: urllib.parse.quote(c, safe="")      # noqa: E731

    if verb == "status" and not rest:
        code, d = call("GET", "/v1/health?deep=1")         # asks Slack whether the token still works
    elif verb == "login" and rest == ["--token-stdin"]:
        token = sys.stdin.readline().strip()            # a token has no spaces: the line's ends are not part of it
        if not token:
            return usage("no token on stdin")
        code, d = call("POST", "/v1/login", {"token": token})
    elif verb == "logout" and not rest:
        code, d = call("POST", "/v1/logout")
    elif verb == "rooms" and len(rest) <= 1:
        if rest and not rest[0].isdigit():
            return usage(f"a count is a number, not {rest[0]!r}")
        code, d = call("GET", "/v1/conversations?limit=" + (rest[0] if rest else "100"))
    elif verb == "read" and 1 <= len(rest) <= 2:
        if len(rest) == 2 and not rest[1].isdigit():
            return usage(f"a count is a number, not {rest[1]!r}")
        code, d = call("GET", f"/v1/conversations/{q(rest[0])}?limit=" + (rest[1] if len(rest) == 2 else "20"))
    elif verb == "send" and len(rest) >= 2:
        code, d = call("POST", f"/v1/conversations/{q(rest[0])}/messages", {"text": " ".join(rest[1:])})
    elif verb == "mark-read" and len(rest) == 2:
        code, d = call("POST", f"/v1/conversations/{q(rest[0])}/read", {"ts": rest[1]})
    else:
        return usage(f"unknown verb or arguments: {' '.join(args)}")

    if as_json:
        print(json.dumps(d, ensure_ascii=False))
    elif code >= 400:
        pass
    elif verb == "status":
        print(f"signed in as {d.get('user')} in {d.get('team')} ({d.get('kind')} token)"
              if d.get("signed_in") else "no token yet — ./bbox slack login --token-stdin < token-file")
    elif verb == "rooms":
        for c in d.get("conversations") or []:
            print(f"{c['id']}\t{flat(c.get('name'), 80)}\t{c.get('kind')}")
        if d.get("more"):
            print(f"slack: {d.get('count')} shown, and there are more — rooms <N> shows up to 1000", file=sys.stderr)
    elif verb == "read":
        for m in d.get("messages") or []:
            print(f"{m.get('ts')}\t{m.get('from')}\t{flat(m.get('text'))}")
    elif verb == "login":
        print(f"signed in as {d.get('user')} in {d.get('team')}")
    elif verb == "send":
        print(f"sent\t{d.get('id')}")
    else:
        print("ok")
    if code >= 400:
        wait = f" (wait {d.get('retry_after')} s)" if d.get("retry_after") else ""
        print(f"slack: {d.get('error')}: {d.get('detail') or ''}".rstrip(": ") + wait, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
