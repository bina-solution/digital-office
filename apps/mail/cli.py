"""cli — «מייל» for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the mailview container (`dcx exec -T mailview python - <verb> … <
apps/mail/cli.py`), so it runs from the checkout with no image rebuild and talks to the screen's own
API on 127.0.0.1. Its answer goes through apps/mail/operatives/lines.py, the formatter the mail
operatives use, which flattens what a sender wrote so it cannot forge a line or a column.

    connections                              the mailboxes, and which one is selected
    inbox [N] [--connection <id>]            the newest N in the inbox (default 10)
    find "<gmail query>" [N] [--connection <id>]   a search, in Gmail's grammar
    read <message id> [--connection <id>]    one message

Every call names its mailbox. Without --connection it uses the one selected in the account bar — a
shared choice that may be a client's real Gmail — and says so on stderr. Sending stays with the
`mail.send` operative and the screen: it reaches a person.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8976"
# A message id is hex: Gmail's message-id, or the local backend's uid (mailapi `_gmail_id`, local_app).
# Anything else is refused — mailview pastes the id into a query (`X&meta=false` forces the full fetch,
# which opens the folder read-write, so IMAP marks a client's message \Seen: a read would write).
ID = re.compile(r"[0-9A-Fa-f]{1,32}")


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace") or f'{{"error": "HTTP {e.code}"}}')
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"mail: the screen's API does not answer on {API} ({getattr(e, 'reason', e)})")


def mailbox(flags):
    """The connection to name: --connection, or the selected one — said, never silent."""
    if flags.get("connection"):
        return flags["connection"]
    try:
        active = json.loads(get("/api/connections")).get("active")
    except ValueError:
        active = None
    if not active:
        sys.exit("mail: no mailbox is selected — pass --connection <id> (`bbox mail connections`)")
    print(f"mailbox: {active} (selected in the account bar; pass --connection to name another)",
          file=sys.stderr)
    return active


def split(args):
    flags, rest, it = {}, [], iter(args)
    for a in it:
        if a == "--connection":
            flags["connection"] = next(it, "")
        else:
            rest.append(a)
    return flags, rest


def count(rest, at, default=10):
    try:
        return max(1, min(100, int(rest[at]))) if len(rest) > at else default
    except ValueError:
        sys.exit(f"mail: a count is a number, not {rest[at]!r}")


def main(argv):
    verb = argv[0] if argv else ""
    flags, rest = split(argv[1:])
    if verb == "connections":
        print(get("/api/connections"))
    elif verb == "inbox":
        print(get("/api/messages", {"limit": count(rest, 0), "connection_id": mailbox(flags)}))
    elif verb == "find" and rest:
        print(get("/api/messages", {"q": rest[0], "limit": count(rest, 1), "connection_id": mailbox(flags)}))
    elif verb == "read" and rest:
        if not ID.fullmatch(rest[0]):
            sys.exit(f"mail: {rest[0]!r} is not a message id (hex, as `inbox` and `find` print it)")
        print(get("/api/message/" + rest[0], {"connection_id": mailbox(flags)}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
