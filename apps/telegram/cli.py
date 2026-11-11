"""cli — «טלגרם», the office's Telegram, for agents and for the person at the server's shell.

The hooks pipe THIS file into the telegram container (`dcx exec -T telegram python - <verb> … <
apps/telegram/cli.py`), so it runs from the checkout with no image rebuild, and talks to the service's own API
on 127.0.0.1.

    status                   the account: connected, as whom, which chats are listened to, the stream
    chats [query] [N]        the account's chats (default 50), each with whether the office listens to it
    history <chat_id> [N]    a listened-to chat's last N messages (default 200), oldest first
    media-save <chat_id> <message_id>    that message's file, any size, into the office's drive («טלגרם/<chat>/…»)
    chat <x> history [N|all]             the same, <x> a chat id or its title (all = the whole thread)
    chat <x> message <y> mark <emoji>    a reaction from the account on message <y> ("" takes it off)

The live events are `./bbox telegram flow` (the office's event stream, platform-base/redis/flow.py). Connecting
the account, choosing the chats and writing into one stay on the screen and the API (AGENT.md).
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8984"


def call(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"telegram: {doc.get('detail') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"telegram: the service does not answer on {API} ({getattr(e, 'reason', e)})")


def resolve_chats(x: str) -> list[int]:
    """The chats <x> names: an id is itself; a title is every LISTENED-TO chat of that name (a group that became
    a supergroup is two — its thread before and after), else the one chat of the account by that name. A title
    two unrelated chats of the account share is a refusal that names them — never a guess."""
    try:
        return [int(x)]
    except ValueError:
        pass
    want = x.strip().casefold()
    every = call("GET", "/api/status").get("watched") or []
    watched = [int(c["id"]) for c in every if str(c.get("title", "")).strip().casefold() == want]
    if watched:
        # …and the other half of a migration, whatever ITS title is now: a group and the supergroup it became are
        # one thread, and the owner renamed the supergroup after it migrated (DGO-1320)
        links = {int(c["id"]): {c.get("migrated_to"), c.get("migrated_from")} - {None} for c in every}
        grown = True
        while grown:
            more = {int(o) for i in watched for o in links.get(i, ()) if int(o) not in watched and int(o) in links}
            grown = bool(more)
            watched += sorted(more)
        return watched
    found = [int(c["id"]) for c in (call("GET", "/api/chats?" + urllib.parse.urlencode({"q": x, "limit": 50})).get("chats") or [])
             if str(c.get("title", "")).strip().casefold() == want]
    if len(found) == 1:
        return found
    if not found:
        sys.exit(f"telegram: no chat named {x!r}")
    sys.exit(f"telegram: more than one chat is named {x!r}: {', '.join(map(str, found))} — give the id")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "status":
        data = call("GET", "/api/status")
        data.get("login", {}).pop("qr_svg", None)
    elif verb == "chats":
        q = {"q": args[0] if args else "", "limit": 50}
        if len(args) > 1:
            try:
                q["limit"] = max(1, min(500, int(args[1])))
            except ValueError:
                sys.exit(f"telegram: a count is a number, not {args[1]!r}")
        data = call("GET", "/api/chats?" + urllib.parse.urlencode(q))
    elif verb == "history" and args:
        q = {"chat_id": args[0], "limit": 200}
        if len(args) > 1:
            try:
                q["limit"] = max(1, min(2000, int(args[1])))
            except ValueError:
                sys.exit(f"telegram: a count is a number, not {args[1]!r}")
        data = call("GET", "/api/history?" + urllib.parse.urlencode(q))
    elif verb == "media-save" and len(args) >= 2:
        try:
            body = {"chat_id": int(args[0]), "message_id": int(args[1])}
        except ValueError:
            sys.exit("telegram: chat_id and message_id are numbers")
        # the save runs in the app's background (a large file is minutes at Telegram's pace): started here, then its
        # state is read every few seconds until it is «saved» (with the path) or «failed» (with the reason)
        data = call("POST", "/api/media/save", body)
        q = urllib.parse.urlencode(body)
        while data.get("state") == "saving":
            time.sleep(3)
            data = call("GET", "/api/media/save?" + q)
        if data.get("state") == "failed":
            print(json.dumps(data, ensure_ascii=False, indent=1))
            sys.exit(f"telegram: not saved — {data.get('error') or 'no reason given'}")
    elif verb == "chat" and len(args) >= 2:
        cids = resolve_chats(args[0])
        if args[1] == "history":
            n = args[2] if len(args) > 2 else "200"
            try:
                limit = 10000 if n == "all" else max(1, min(10000, int(n)))
            except ValueError:
                sys.exit(f"telegram: a count is a number or `all`, not {n!r}")
            # a whole thread is minutes of reading at Telegram's pace, not one request's minute
            parts = [call("GET", "/api/history?" + urllib.parse.urlencode({"chat_id": c, "limit": limit}), timeout=300)
                     for c in cids]
            # one thread, oldest first, across a group and the supergroup it became; each message says its chat
            msgs = sorted(({**m, "chat_id": p["chat_id"]} for p in parts for m in p.get("messages") or []),
                          key=lambda m: m.get("at") or "")
            data = {"chat_ids": cids, "chat": parts[0].get("chat") if parts else "", "messages": msgs[-limit:]}
        elif args[1] == "message" and len(args) >= 4 and args[3] == "mark":
            if len(args) < 5:
                # a forgotten emoji must not take a mark off: clearing is said, as ""
                sys.exit('telegram: which mark? `… mark 👀` — or `… mark ""` to take it off')
            if len(cids) > 1:
                sys.exit(f"telegram: {args[0]!r} is {len(cids)} chats ({', '.join(map(str, cids))}: a group and the "
                         "supergroup it became) — a message id belongs to one of them; give its id")
            try:
                mid = int(args[2])
            except ValueError:
                sys.exit(f"telegram: a message id is a number, not {args[2]!r}")
            data = call("POST", "/api/mark", {"chat_id": cids[0], "message_id": mid,
                                               "emoji": args[4]})
        else:
            sys.exit(__doc__)
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
