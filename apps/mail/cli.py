"""cli — «מייל» for agents and for the person at the server's shell. Reads, and two writes that change labels only.

The hooks pipe THIS file into the mailview container (`dcx exec -T mailview python - <verb> … <
apps/mail/cli.py`) — or, on an office that does not run the mail, into the credential plane's container
against the door of the office that does (MAIL_API) — so it runs from the checkout with no image rebuild
and talks to the screen's own API. Its answer goes through apps/mail/operatives/lines.py, the formatter the
mail operatives use, which flattens what a sender wrote so it cannot forge a line or a column.

    profile list                             every mailbox of the office, and the default (*)
    connections                              the same, as the service's JSON
    inbox [N]                                the newest N in the inbox (default 10)
    find "<gmail query>" [N]                 a search, in Gmail's grammar
    read <message id>                        one message
    thread <message id>                      the conversation it belongs to (headers only: one per message)
    labels                                   the mailbox's labels (DGO-1255: the reads first; send stays last)
    mark <message id>… starred|important|unread|archived [--off]
                                             set a mark on up to 50 messages, or take it off
    tag <message id> +<label>… -<label>…     add and remove labels by name
    …any of them:  -p <mailbox>  (its address, its name or its connection id; also --connection), once

Every call names its mailbox. Without -p a READ uses the office's default — a shared choice that may be a
client's real Gmail — and says so on stderr; a WRITE refuses, so a change never lands in a mailbox nobody
named. The writes are the screen's own (/api/mark, /api/tag) and touch labels only: a mark is a label
(archived = INBOX taken away), and `--off`, or the opposite sign, takes it back. A label added by name that
the mailbox did not have is created, and taking it off a message does not delete it. The office's own
mailboxes have one folder, so `archived` changes nothing there (mailapi/local_app.py). What a write prints
is what was ASKED: the service answers ok without saying which messages it found. Sending stays with the
`mail.send` operative and the screen: it reaches a person.
"""
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = (os.environ.get("MAIL_API") or "http://127.0.0.1:8976").rstrip("/")
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


def post(path, body):
    """A write through the screen's own API, the mailbox named in the body (mailview's gi carries it).
    Its answer is a JSON object or the call failed; a failure after the request left says the change may be
    partly made (mailview changes one message at a time), never that nothing happened."""
    req = urllib.request.Request(API + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    unknown = "the result is unknown: some messages may already have changed — check with `find`"
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            got = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"mail: {path} answered {e.code}: {e.read().decode('utf-8', 'replace')[:300]} ({unknown})")
    except ValueError:
        sys.exit(f"mail: {path} answered something that is not JSON ({unknown})")
    except urllib.error.URLError as e:                    # the request never reached the screen's API
        sys.exit(f"mail: the screen's API does not answer on {API} ({e.reason}); nothing was changed")
    except (http.client.HTTPException, TimeoutError, OSError) as e:
        sys.exit(f"mail: {path} gave no clear answer ({type(e).__name__}: {e}); {unknown}")
    if not isinstance(got, dict) or got.get("ok") is not True:
        sys.exit(f"mail: {path} did not answer ok: {json.dumps(got, ensure_ascii=False)[:300]} ({unknown})")
    return got


MARKS = ("starred", "important", "unread", "archived")     # mailview's MARK_LABELS
MAX_IDS = 50       # mailview changes one message at a time, and its worker has 120 s (mailview/Dockerfile)


def ids_of(words):
    for w in words:
        if not ID.fullmatch(w):
            sys.exit(f"mail: {w!r} is not a message id (hex, as `inbox` and `find` print it)")
    return list(words)


def named(flags, verb):
    """A write's mailbox: only the one -p names. The default may be a client's real Gmail."""
    if not flags.get("connection"):
        sys.exit(f"mail: `{verb}` changes a mailbox — name it with -p <mailbox> (`bbox mail profile list`)")
    return flags["connection"]


def mailbox(flags):
    """The connection to name: --connection, or the selected one — said, never silent."""
    if flags.get("connection"):
        return flags["connection"]
    try:
        active = json.loads(get("/api/connections")).get("active")
    except ValueError:
        active = None
    if not active:
        sys.exit("mail: no mailbox is selected — name one with -p <mailbox> (`bbox mail profile list`)")
    print(f"mailbox: {active} (the office's default; -p names another)", file=sys.stderr)
    return active


def split(args):
    """`-p <mailbox>` anywhere, ONCE and with a word after it: an empty word would match every mailbox
    (pick's prefix match), and a second -p would silently move a write to another mailbox."""
    flags, rest, it = {}, [], iter(args)
    for a in it:
        if a in ("--connection", "-p", "--profile", "--mailbox"):
            if "connection" in flags:
                sys.exit(f"mail: the mailbox is named twice ({a} again) — name it once")
            word = next(it, "")
            if not str(word).strip():
                sys.exit(f"mail: {a} needs a mailbox after it — its address, its name or its connection id")
            flags["connection"] = pick(word)
        else:
            rest.append(a)
    return flags, rest


def boxes():
    d = json.loads(get("/api/connections"))
    return d.get("connections") or [], d.get("active")


def pick(word):
    """The one mailbox a `-p` word names: its connection id, its address or its name — exactly, then as the
    start of one; two that answer the same word are named, never guessed between."""
    conns, _ = boxes()
    w = str(word or "").strip().lower()
    keys = lambda c: [str(c.get(k) or "").lower() for k in ("id", "account_hint", "label")]  # noqa: E731
    hits = [c for c in conns if w in keys(c)] or [c for c in conns if any(k.startswith(w) for k in keys(c) if k)]
    if len(hits) == 1:
        return hits[0]["id"]
    if not hits:
        sys.exit(f"mail: no mailbox is called {word!r} — `profile list` shows them")
    sys.exit(f"mail: {word!r} names {len(hits)} mailboxes — " + ", ".join(f"{c.get('account_hint') or c.get('label')} ({c['id']})" for c in hits))


def profile_list():
    conns, active = boxes()
    kind = {"mail_imap_local": "תיבה של הלשכה", "mail_gmail_oauth": "Gmail", "mail_imap_app_password": "Gmail · סיסמת אפליקציה"}
    for c in conns:
        print(("* " if c.get("id") == active else "  ") + f"{c.get('account_hint') or c.get('label')}\t"
              f"{kind.get(c.get('protocol'), c.get('protocol'))}\t{c.get('label') or ''}\t{c.get('id')}")
    if not conns:
        print("mail: no mailbox is connected", file=sys.stderr)


def count(rest, at, default=10):
    try:
        return max(1, min(100, int(rest[at]))) if len(rest) > at else default
    except ValueError:
        sys.exit(f"mail: a count is a number, not {rest[at]!r}")


def main(argv):
    flags, rest = split(argv)          # `-p <mailbox>` may stand before the verb too: `bbox mail -p x inbox`
    verb, rest = (rest[0], rest[1:]) if rest else ("", [])
    if verb in ("profile", "profiles", "mailboxes") and (not rest or rest[0] in ("list", "ls")):
        profile_list()
    elif verb == "connections":
        print(get("/api/connections"))
    elif verb == "inbox":
        print(get("/api/messages", {"limit": count(rest, 0), "connection_id": mailbox(flags)}))
    elif verb == "find" and rest:
        print(get("/api/messages", {"q": rest[0], "limit": count(rest, 1), "connection_id": mailbox(flags)}))
    elif verb == "read" and rest:
        if not ID.fullmatch(rest[0]):
            sys.exit(f"mail: {rest[0]!r} is not a message id (hex, as `inbox` and `find` print it)")
        print(get("/api/message/" + rest[0], {"connection_id": mailbox(flags)}))
    elif verb == "thread" and rest:
        if not ID.fullmatch(rest[0]):
            sys.exit(f"mail: {rest[0]!r} is not a message id (hex, as `inbox` and `find` print it)")
        # bodies=false: headers only — one BODY.PEEK[HEADER] per message, which marks nothing \\Seen
        print(get("/api/thread/" + rest[0], {"bodies": "false", "connection_id": mailbox(flags)}))
    elif verb == "labels":
        got = get("/api/labels", {"connection_id": mailbox(flags)})
        try:
            names = json.loads(got).get("labels")
        except (ValueError, AttributeError):
            names = None
        if not isinstance(names, list):
            sys.exit(f"mail: the labels did not answer: {got[:300]}")
        for n in names:                    # a label is a name someone typed: one line, whatever it holds
            print(" ".join(str(n).split()))
    elif verb == "mark" and len(rest) >= 2:
        off = "--off" in rest
        words = [w for w in rest if w != "--off"]
        what = words[-1].lower() if words else ""
        if what not in MARKS:
            sys.exit(f"mail: mark takes one of {', '.join(MARKS)} after the message ids, not {what!r}")
        ids = ids_of(words[:-1])
        if not ids:
            sys.exit("mail: mark needs at least one message id")
        if len(ids) > MAX_IDS:
            sys.exit(f"mail: mark takes at most {MAX_IDS} messages at a time, not {len(ids)}")
        cid = named(flags, "mark")
        post("/api/mark", {"ids": ids, "mark": what, "on": not off, "connection_id": cid})
        print(f"asked\t{what} {'off' if off else 'on'}\t{len(ids)} message(s)\t{cid}")
    elif verb == "tag" and len(rest) >= 2:
        mid = ids_of(rest[:1])[0]
        name = lambda w: " ".join(w[1:].split())          # noqa: E731 — the label as the screen would save it
        add = [name(w) for w in rest[1:] if w.startswith("+") and name(w)]
        rem = [name(w) for w in rest[1:] if w.startswith("-") and name(w)]
        bad = [w for w in rest[1:] if not (w.startswith(("+", "-")) and name(w))]
        if bad or not (add or rem):
            sys.exit(f"mail: tag takes +<label> to add and -<label> to remove, after one message id (not {bad!r})")
        both = sorted(set(add) & set(rem))
        if both:
            sys.exit(f"mail: {both!r} is both added and removed — say one")
        cid = named(flags, "tag")
        post("/api/tag", {"id": mid, "add": add, "remove": rem, "connection_id": cid})
        print(f"asked\t{mid}\t+{len(add)} -{len(rem)}\t{cid}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
