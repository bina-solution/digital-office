"""cli — «פגישות וידאו» for agents and for the person at the server's shell.

Runs INSIDE the meet-start container (the hooks call `dcx exec -T meet-start python /app/cli.py …`)
and reuses server.py's own functions — importing it starts nothing: its doors and threads start only
under `__main__`. It reads the recordings volume and prints; it sends nothing and changes nothing.

    new                  a room nobody guesses, the host's link (signs the opener in as its host)
                         and the guests' link
    recordings [N]       the newest N recordings (default 10): when, room, who was there, done or not
    meetings [N]         the newest N meetings that have a meet-flow page (default 10)
"""
import re
import sys
from urllib.parse import quote

import server


def flat(v):
    """A guest's name, a room's name and a meeting's title are what people typed: one line each, with
    no direction marks (server.py's own `_BIDI`), so they forge no line and reorder none."""
    return re.sub(r"\s+", " ", server._BIDI.sub("", str(v or ""))).strip()[:120]


def new():
    room = server.new_room()
    guests = f"{server.meet_base()[0]}/{quote(room, safe='')}"
    host = f"{server.CONSOLE_URL}/a/meet/r/{quote(room, safe='')}" if server.CONSOLE_URL else None
    print(f"room:   {room}")
    # /r/<room> mints the opener's own host token (server.py's people's door): a link for a SIGNED-IN
    # person of this office, never for a guest — a guest waits in the room until a host is in.
    print(f"host:   {host or '(MEET_CONSOLE_URL is not set — open /r/' + room + ' on meet-start)'}")
    print(f"guests: {guests}")


def recordings(n):
    rows = server.recordings(limit=n)
    if not rows:
        print("no recordings")
    for r in rows:
        people = ", ".join(flat(p) for p in r["people"] if p) or "-"
        state = "done" if r["done"] else "recording"
        print(f"{r['started']}  {flat(r['room'])}  [{state}]  {people}  {r['session']}/{r['file']}")


def meetings(n):
    rows = server.flows()[:n]
    if not rows:
        print("no meetings with a meet-flow page")
    for m in rows:
        title = flat(m.get("title"))
        page = f"{server.CONSOLE_URL}/a/meet/flow/{quote(m['room'], safe='')}/" if server.CONSOLE_URL else ""
        print(f"{m.get('started') or '-'}  {flat(m['room'])}  {title}  {page}".rstrip())


def count(args, default=10):
    try:
        return max(1, int(args[0])) if args else default
    except ValueError:
        sys.exit(f"meet: a count is a number, not {args[0]!r}")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "new":
        new()
    elif verb == "recordings":
        recordings(count(args))
    elif verb == "meetings":
        meetings(count(args))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
