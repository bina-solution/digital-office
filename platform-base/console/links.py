"""links.py — the ONE link a person is given: `https://<console>/go/<ref>` (DGO-1433).

THE PROBLEM. The office handed its owner about eleven forms of link, built in seven places, and none was opened
past the sign-in before it was sent: `/a/<alias>.<office>/` (a proxy mount that exists only for a tile with a
door — `{"error":"unknown_app"}` on his phone, twice), `#/m/<tile>/<two UUIDs>` (a fragment, which never reaches a
server and does not survive a typed sign-in), `http://console.localhost/…` (his own phone, by RFC 6761).

THE FORM. A PATH the console resolves server-side, then answers 302 to the shell's own route for it:

    /go/DGO-1433                      a work item, by its key   → #/m/<the Plane tile>/<ws>/browse/DGO-1433/
    /go/meet/exu101                   a meeting, by its room    → #/m/<the meet tile>/flow/exu101/
    /go/bina-claude.hp-laptop[/…]     an app on an office       → #/m/bina-claude.hp-laptop[/…]

A path survives every sign-in round trip (the edge's `rd` carries it; a fragment it cannot), names the THING and
not the mechanism (no `/a/`, no port, no UUID where a key exists, no `.localhost`), and is resolved at click time
against the console's own live registry — the one `/api/modules` serves — so the same link opens the same thing
on every console that has it, the owning office included (`<alias>.<own office>` is its own tile there).

What cannot be resolved is SAID: `resolve` returns the sentence — and, when several linked offices run what the
link asks for and this one does not, the CHOICES, each its own `/go/` link — and the console draws it as its card.
Never JSON, never another app, never a silent fall to the first tile.

`ref` arrives DECODED (werkzeug decodes the path once); each inner segment is encoded again for the shell's route.
Pure functions; app.py's `go()` is the route and the card.
"""
from __future__ import annotations

import re
from urllib.parse import quote

#: A work item's key, as Plane writes it: a project identifier, a dash, a number (DGO-1433, MEET-24).
KEY_RE = re.compile(r"[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}")
#: A tile's name in a link: an id (`bina-claude.hp-laptop`), an alias, or `<alias>.<office>`.
NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")
#: A meeting room — meet-start's own rule for a room in a URL (apps/meet/start/server.py FLOW_ROOM_RE).
ROOM_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")
#: What a segment of an inner route keeps unencoded (RFC 3986 pchar, less `%`: a decoded `%` is a character).
SAFE = "!$&'()*+,;=:@-._~"
#: The apps a reference KIND opens, by the names their tiles carry (app id or alias).
PLANE = ("project-pln", "plane")
MEET = ("meet",)


def names(m: dict) -> list:
    """The names a tile answers to, most specific first — static/module-ref.js `names`, the shell's own rule."""
    r = m.get("remote") if isinstance(m.get("remote"), dict) else {}
    return [x for x in (m.get("id"), m.get("alias"), r.get("module_id"), r.get("alias"))
            if isinstance(x, str) and x]


def linked(m: dict) -> bool:
    """A linked office's tile: compiled ones carry `office` and `remote`, a peers.d one `remote` alone."""
    return bool(m.get("office") or m.get("remote"))


def _tiles(tiles) -> list:
    return [m for m in (tiles or []) if isinstance(m, dict) and m.get("id")]


def find_all(tiles: list, ref: str, own_office: str = "") -> tuple:
    """(the tile `ref` names, or None; the linked tiles it could name when there is no one answer).

    module-ref.js `resolve`, kept in step (test_links.py runs its cases): the exact id; this office's own name;
    the name it has on its own office — and here, where the shell would take the first of several linked
    offices' tiles silently, the several are returned instead. And the one rule the shell lacks:
    `<alias>.<this office>` is this office's own tile, by its id or its own names only."""
    if not ref:
        return None, []
    tiles = _tiles(tiles)
    for m in tiles:
        if m["id"] == ref:
            return m, []
    local = [m for m in tiles if not linked(m)]
    for m in local:
        if ref in names(m):
            return m, []
    far = [m for m in tiles if linked(m) and ref in names(m)]
    if len(far) == 1:
        return far[0], []
    if far:
        return None, far
    alias, _, office = ref.rpartition(".")
    if alias and own_office and office == own_office.lower():
        hit = next((m for m in local if m["id"] == alias), None) or next((m for m in local if alias in names(m)), None)
        return hit, []
    return None, []


def find(tiles: list, ref: str, own_office: str = "") -> dict | None:
    return find_all(tiles, ref, own_office)[0]


def _of_app(tiles: list, wanted: tuple) -> list:
    """Every tile of an app, by the names it carries (a linked one is `<alias>.<office>`)."""
    out = []
    for m in _tiles(tiles):
        own = {m.get("id"), m.get("alias"), m.get("app")} | set(names(m))
        if own & set(wanted) or str(m["id"]).split(".", 1)[0] in wanted:
            out.append(m)
    return out


def one_of(tiles: list, wanted: tuple) -> tuple:
    """(the tile of `wanted` this console opens, or None; the linked tiles to choose from when several run it;
    the sentence when there is no one answer). This office's own first; else exactly one linked office's."""
    found = _of_app(tiles, wanted)
    local = [m for m in found if not linked(m)]
    if local:
        return local[0], [], ""
    if len(found) == 1:
        return found[0], [], ""
    if not found:
        return None, [], "האפליקציה שהקישור הזה פותח לא נמצאת בלשכה הזאת, ולא באף לשכה שמקושרת אליה."
    return None, sorted(found, key=lambda m: m["id"]), "כמה לשכות מקושרות מריצות את מה שהקישור הזה פותח — בחרו באיזו:"


def inner(segments: list, trailing: bool = False) -> tuple:
    """The inner route as the shell takes it (`/a/b`, each segment encoded once), or the sentence why not."""
    out = []
    for s in segments:
        if s == "":
            continue
        if s in (".", "..") or any(c in s for c in "\r\n\t\0\\"):
            return None, "בקישור יש חלק שאינו כתובת תקינה."
        out.append(quote(s, safe=SAFE))
    path = ("/" + "/".join(out)) if out else ""
    return (path + "/" if trailing and path else path), ""


def _choices(found: list, tail: str, q: str = "") -> list:
    return [{"tile": m["id"], "go": f"/go/{m['id']}{tail}{q}"} for m in found]


def resolve(ref: str, query: str, tiles: list, own_office: str = "", workspace: str = "bina") -> dict:
    """The shell route a `/go/<ref>` opens, or why it opens nothing.

    {"to": "/#/m/<tile>/<inner>[?q]", "kind": "item|meeting|app", "tile": <id>, "ref": <canonical ref>} or
    {"why": <sentence>, "kind": …, "ref": …, "choices"?: [{"tile", "go"}]}. `ref` is decoded; `query` is passed on
    to the app's inner route verbatim."""
    raw = (ref or "").strip("/")
    trailing = (ref or "").endswith("/")
    parts = raw.split("/") if raw else []
    if not parts:
        return {"why": "הקישור לא אומר מה לפתוח.", "kind": "", "ref": ""}
    head, rest = parts[0], parts[1:]
    q = ("?" + query) if query else ""
    if head.lower() == "meet" and rest:
        room = rest[0].lower()
        if not ROOM_RE.fullmatch(room):
            return {"why": "שם הפגישה בקישור אינו שם של חדר.", "kind": "meeting", "ref": raw}
        tile, found, why = one_of(tiles, MEET)
        if not tile:
            return {"why": why, "kind": "meeting", "ref": f"meet/{room}",
                    **({"choices": _choices(found, f"/flow/{room}/", q)} if found else {})}
        more, bad = inner(rest[1:], trailing)
        if more is None:
            return {"why": bad, "kind": "meeting", "ref": f"meet/{room}"}
        return {"to": f"/#/m/{tile['id']}/flow/{room}/{more.lstrip('/')}{q}",
                "kind": "meeting", "tile": tile["id"], "ref": f"meet/{room}"}
    key = head.upper()
    if KEY_RE.fullmatch(key) and not find(tiles, head.lower(), own_office):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", workspace or ""):
            return {"why": "סביבת העבודה של ניהול הפרויקטים לא מוגדרת בלשכה הזאת.", "kind": "item", "ref": key}
        tile, found, why = one_of(tiles, PLANE)
        if not tile:
            return {"why": why, "kind": "item", "ref": key,
                    **({"choices": _choices(found, f"/{workspace}/browse/{key}/", q)} if found else {})}
        return {"to": f"/#/m/{tile['id']}/{workspace}/browse/{key}/{q}", "kind": "item", "tile": tile["id"],
                "ref": key}
    name = head.lower()
    if not NAME_RE.fullmatch(name):
        return {"why": "הקישור לא נראה כמו שם של משימה, פגישה או אפליקציה.", "kind": "", "ref": raw}
    tile, found = find_all(tiles, name, own_office)
    more, bad = inner(rest, trailing)
    if more is None:
        return {"why": bad, "kind": "app", "ref": name}
    if not tile:
        if found:
            return {"why": f"כמה לשכות מקושרות נותנות כאן «{name}» — בחרו באיזו:", "kind": "app", "ref": name,
                    "choices": _choices(sorted(found, key=lambda m: m["id"]), more, q)}
        return {"why": f"אין בלשכה הזאת מסך בשם «{name}» — לא שלה, ולא של לשכה שמקושרת אליה.",
                "kind": "app", "ref": name}
    return {"to": f"/#/m/{tile['id']}{more}{q}", "kind": "app", "tile": tile["id"], "ref": tile["id"]}
