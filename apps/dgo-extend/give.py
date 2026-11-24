"""dgo-extend.give — what the herd says an office ALWAYS gives another, by name (DGO-1433).

THE INCIDENT. `serve:` (home.json, this app's volume) is one list that every writer replaces whole: the screen,
pairing's `give`, pairing's automatic `*`, and anything inside the office that calls `POST /api/link/serve`. On
2026-11-06 at 12:56 UTC the HP's group answerer «declared» a list of seven apps, and bina, bina-claude and
browser42 left every office — vps1's console, where the owner works from his phone, and the MacBook's, whose
`bbox agent --office hp-laptop` reaches the HP through bina. Links he had been handed pointed at them. Nothing
outside the HP can write its list (no sshd, by its owner's ruling), so a list an agent got wrong stays wrong.

THE RULE. The herd file (`apps/computers/herd.yaml`, mounted read-only at /herd) is the herd's own declaration,
in git and reviewed. Its `give:` says which apps an office gives which office BY NAME, whatever its `serve:` says:

    give:
      hp-laptop:                      # the office that gives (a herd name or alias)
        vps1: [bina-ds, bina-claude]  # the office given, and the apps — by app id or by alias

It is read ON TOP of `serve:` and never written into it (`converge.home_office` returns the effective map; every
writer reads the file itself): taking a line out of the herd file withdraws the app again, in one reviewed commit,
and no writer of the volume can withdraw it before that. An office reaches every reader of the map at once — the
catalog a peer pulls, the door's route table, the agent doors, the firewall and the agent token's naming — because
the floor is expressed in the map's own words: each app NAMED with its registry port, and added to `only.<office>`
where that office is narrowed. A plain app named this way reaches every office the map does not narrow, exactly as
a name in `serve:` always has; an office that must not get it is narrowed by `only`. An ADMIN app (the herd file's
admin_apps) reaches only the office its line names wherever the withholding runs: toward the hub and a public or
foreign office from every office (DGO-1360), and toward the home offices too from an office in `admin_by_name`
(DGO-863, app.py `_admin_withheld`).

A DOOR, TOO (DGO-2125). A door with no tile — the HP's signer page, which vps1 opens to the internet — is given the
same way, as an item of the line: `vps1: [..., {door: esign-public, paths: [/s/], public: true}]`. Its paths and its
consent are the herd's (`doors`, `merge_doors`): a writer that sends a map without `services`, or with the door in
`exclude`, no longer closes every client's signing link, and no other office ever gets more of it than the map gave.

BY KEY, NOT BY NAME (as DGO-1355's relay): the floor applies only when THIS office's own WireGuard key is the one
the herd file gives the entry its name points at, and only toward a peer whose record here holds the herd file's
key for that peer's entry. A client's office runs this same checkout; a machine that happens to be called `vps1`
is not ours. Fails closed: no file, a file that cannot be read, a key that differs — no floor, `serve:` as it is.

Pure functions, except `load_herd` (the file, cached by its inode, both clocks and size, and never while it is young).
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import yaml

log = logging.getLogger("dgo-extend.give")

#: The herd's declaration, mounted read-only (apps/dgo-extend/docker-compose.yml: `../computers:/herd:ro`).
HERD_FILE = Path(os.environ.get("DGO_HERD_FILE", "/herd/herd.yaml"))
#: The herd file's key for it.
KEY = "give"
#: The keys of a `serve:` map that are not apps (catalog.RESERVED, repeated so this module stands alone).
_RESERVED = ("exclude", "only", "label", "identity", "shared", "services")
_WILDCARD = "*"
#: An app id or an alias, as `serve.only` takes one (app.py api_link_serve).
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}\Z")
#: A door in a `give:` line (DGO-2125): `{door: <alias>, paths: [...], public: true}` — the keys catalog.clean_services
#: takes for `serve.services`, and only those. catalog.ALIAS_RE and catalog.PATH_RE, repeated so this module stands alone.
DOOR_KEYS = ("door", "paths", "public")
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}\Z")
_DOOR_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]*\Z")

#: (key, doc), read and replaced as ONE value: a thread can never pair one call's key with another call's doc
_cache: dict = {"entry": (None, {})}
_said: set = set()
#: A herd file changed less than this long ago is read again on every call, and what is read then is never stored
#: under its key (load_herd: «racily clean»).
RACY_S = 1.0


def _once(what: str, *args) -> None:
    """A warning logged once per distinct text: this runs on every catalog answer."""
    text = what % args if args else what
    if text not in _said:
        _said.add(text)
        log.warning(text)


def load_herd(path: Path | None = None) -> dict:
    """The herd file, or {} — when there is none, and when it cannot be read for ANY reason (a date YAML refuses,
    bytes that are not UTF-8): one bad commit to it must cost the floor, never every catalog answer."""
    p = Path(path or HERD_FILE)
    try:
        st = p.stat()
    except OSError:
        return {}
    # The key is the file's identity and both of its clocks. Even so, a file written again within the kernel's file-clock
    # granularity, at the same size, keeps its mtime, ctime and size — git's «racily clean». Measured in test_clients:
    # one 19-character PIN for another, within one tick, and the joiner kept the old PIN (vps1, G72 at 8307508c5;
    # with the inode and ctime alone in the key, 1 of 20 runs still did). So what is read from a file younger than
    # RACY_S is stored WITHOUT its key: every call reads it again until a read finds it settled, and only that read is
    # trusted to the key (git's rule: an entry stored while racy is not trusted later). A settled file that changes gets
    # a new mtime, so its key changes. «Young» is by the LATER of mtime and ctime: a write that keeps the old mtime
    # (`cp -p`, copy2, `touch -r`) still moves ctime. The window is RACY_S either side, so a time in the future (a copied
    # file, a clock stepped back) is not «young» for as long as the clock takes to reach it. Its limits, said: a
    # filesystem whose timestamps are coarser than RACY_S (FAT's 2 s), and a writer whose clock is off the reader's by
    # more than RACY_S — a VM reading its host's checkout (the Mac's Lima guest, the HP's WSL over 9p) after a sleep;
    # there git's own takes still change the inode, so the key does.
    sig = (str(p), st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    racy = abs(time.time() - max(st.st_mtime, st.st_ctime)) < RACY_S
    cached_sig, cached_doc = _cache["entry"]
    if cached_sig == sig:
        return cached_doc
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:                              # noqa: BLE001 — see the docstring
        _once("the herd file %s cannot be read (%s: %s) — no app is given by it", p, type(e).__name__, str(e)[:200])
        doc = {}
    doc = doc if isinstance(doc, dict) and isinstance(doc.get("offices"), dict) else {}
    _cache["entry"] = (None if racy else sig, doc)
    return doc


def entry_of(doc: dict, oid: str) -> str:
    """The herd file's name for the office called `oid` — its key under `offices:` or one of that key's
    `aliases` (the Dell declares `portable-ubuntu`) — or ""."""
    who = str(oid or "").strip().lower()
    offices = doc.get("offices") if isinstance(doc.get("offices"), dict) else {}
    if not who:
        return ""
    for name, o in offices.items():
        aliases = o.get("aliases") if isinstance(o, dict) else None
        names = {str(name).strip().lower()} | ({str(a).strip().lower() for a in aliases}
                                               if isinstance(aliases, list) else set())
        if who in names:
            return str(name)
    return ""


def _herd_key(doc: dict, entry: str) -> str:
    o = (doc.get("offices") or {}).get(entry)
    return str((o if isinstance(o, dict) else {}).get("wg_public_key") or "").strip()


def _key(identity) -> str:
    """The WireGuard public key, from either shape an identity travels in (net._key)."""
    wg = (identity or {}).get("wg") if isinstance(identity, dict) else None
    if isinstance(wg, dict):
        return str(wg.get("public") or "").strip()
    return str(wg or "").strip()


def herd_peer(doc: dict, home: dict, rec: dict) -> bool:
    """Is the peer this office's record `rec` describes one of the HERD's — by KEY, as `floor` decides it?

    Both ends, or nothing: this office is the herd's only when its own key is the one the herd file writes for
    its name, and the peer only when this office's record of it holds the key the file writes for the peer's
    name. A name alone never counts (a client's machine may be called `portable`), and a herd file that cannot
    be read, an office it does not name, or a key missing on either side is «no» — the door then marks nothing
    (link-proxy's x-dgo-herd), and what reads that mark narrows (apps/computers, DGO-1800)."""
    if not doc or not isinstance(home, dict) or not isinstance(rec, dict):
        return False
    me = entry_of(doc, str(home.get("id") or ""))
    want = _herd_key(doc, me) if me else ""
    if not want or _key(home.get("identity")) != want:
        return False
    entry = entry_of(doc, str(rec.get("id") or ""))
    key = _herd_key(doc, entry) if entry and entry != me else ""
    return bool(key) and _key(rec.get("identity")) == key


def _names(value) -> set:
    """A list of app names (or one name), lower-cased; anything that is not a name is dropped, never guessed."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    out = set()
    for v in value:
        n = str(v).strip().lower() if isinstance(v, str) else ""
        if NAME_RE.match(n):
            out.add(n)
    return out


def _given(doc: dict, home: dict, records: list) -> dict:
    """{peer id as THIS office's record names it: [items as the herd file writes them]} — the `give:` lines toward each
    peer whose record here holds the herd file's key for it, when THIS office is the herd's by key. The checks `floor`
    always made, shared with `doors`; the items are names and doors as written, and each reader takes its own kind."""
    if not doc:
        return {}
    me = entry_of(doc, str((home or {}).get("id") or ""))
    table = doc.get(KEY) if isinstance(doc.get(KEY), dict) else {}
    mine: dict = {}
    for giver, given in table.items():                    # every key that names this office (its name, an alias)
        if me and entry_of(doc, str(giver)) == me and isinstance(given, dict):
            for peer_name, items in given.items():
                mine.setdefault(str(peer_name), []).extend(items if isinstance(items, list) else [items])
    if not mine:
        return {}
    want = _herd_key(doc, me)
    have = _key((home or {}).get("identity"))
    if not want or have != want:
        _once("this office is called %s, but its WireGuard key is not the one the herd file gives %s — the herd's "
              "`give:` is not applied here", (home or {}).get("id"), me)
        return {}
    out: dict = {}
    for peer_name, items in mine.items():
        entry = entry_of(doc, str(peer_name))
        if not entry or not items or entry == me:
            continue
        key = _herd_key(doc, entry)
        for rec in records or []:
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            rid = str(rec["id"]).strip().lower()
            if entry_of(doc, rid) != entry:
                continue
            if not key or _key(rec.get("identity")) != key:
                _once("the herd file gives %s apps or doors from this office, but this office's record of %s holds "
                      "another key — nothing is given to it by the herd file", entry, rid)
                continue
            out.setdefault(rid, []).extend(items)
    return out


def floor(doc: dict, home: dict, records: list) -> dict:
    """{peer id as THIS office's record names it: {app names}} — what the herd says this office always gives.

    `home` is this office's record (its `id` and `identity`), `records` its records of its peers (`id`,
    `identity`). Empty when the herd file names no `give:` for this office, when this office is not the herd's by
    key, or for a peer whose record here does not hold the herd file's key for it. A door in a line is `doors`'."""
    out: dict = {}
    for rid, items in _given(doc, home, records).items():
        names = _names(items)
        if names:
            out.setdefault(rid, set()).update(names)
    return out


def _plain(p) -> bool:
    """catalog.plain_path, repeated so this module stands alone: absolute, no dot segment, nothing escaped."""
    return isinstance(p, str) and bool(_DOOR_PATH_RE.match(p)) and "/../" not in f"{p}/" and "/./" not in f"{p}/"


def _door(item: dict):
    """(alias, paths, public) of a herd file's door item, or None when it is not one: an alias; paths, a list of
    plain absolute paths, never empty, never `/` when the door is opened to the internet; `public` true or false;
    nothing but those keys (catalog.clean_services' rule — and the herd's door is always narrowed to paths)."""
    if set(item) - set(DOOR_KEYS):
        return None
    alias = str(item.get("door") or "").strip().lower()
    paths = item.get("paths")
    paths = [paths] if isinstance(paths, str) else paths
    public = item.get("public", False)
    if not _ALIAS_RE.match(alias) or not isinstance(public, bool):
        return None
    if not isinstance(paths, list) or not paths or not all(_plain(p) for p in paths) or (public and "/" in paths):
        return None
    return alias, sorted(set(paths)), public


def doors(doc: dict, home: dict, records: list, registry=None) -> dict:
    """{alias: {"to": {peer ids}, "paths": [...], "public": bool}} — the doors with no tile the herd file says this
    office always gives (DGO-2125), by key as `floor`: an item `{door: esign-public, paths: [/s/], public: true}` in
    a `give:` line. A door that breaks the rule (`_door`) gives nothing, with a line: a typo must never open more
    than was written. One alias given with other paths or another consent to two offices gives nothing either: a
    door answers one set of paths, and a disagreement is not settled by a guess. And a door is given only when THIS
    office's registry lists it among its doors and no app goes by its name: a line that names an app would take the
    app's name out of `exclude` and re-open the whole app (the second reader). No registry, no door."""
    known = {_low(r.get("alias")) for r in ((registry or {}).get("services") or []) if isinstance(r, dict)}
    apps = {_low(r.get(k)) for r in _rows(registry) for k in ("app", "alias")}
    out: dict = {}
    bad: set = set()
    for rid, items in _given(doc, home, records).items():
        for it in items:
            if not isinstance(it, dict):
                continue
            spec = _door(it)
            if spec is None:
                _once("the herd file's door %r toward %s is not one (door, paths, public) — it gives nothing", it, rid)
                continue
            alias, paths, public = spec
            have = out.get(alias)
            if have and (have["paths"] != paths or have["public"] != public):
                bad.add(alias)
                continue
            out.setdefault(alias, {"to": set(), "paths": paths, "public": public})["to"].add(rid)
    for alias in sorted(bad):
        _once("the herd file gives the door %s with other paths or consent to two offices — it gives it to none", alias)
        out.pop(alias, None)
    for alias in sorted(out):
        if alias not in known or alias in apps:
            _once("the herd file's door %s is not a door of this office's registry, or an app goes by that name — it "
                  "gives nothing", alias)
            out.pop(alias)
    return out


def _within(paths, given) -> bool:
    """Do all `paths` lie inside `given` — a door's own narrowing, None being the whole door — as a door matches them
    (an exact path, or under a prefix that ends in `/`)?"""
    if given is None:
        return True
    given = [given] if isinstance(given, str) else given
    return isinstance(given, list) and all(
        any(p == str(g) or (str(g).endswith("/") and p.startswith(str(g))) for g in given) for p in paths)


def _map_door(old):
    """What a map's own entry for a door gives, read as catalog.publishable_services reads it: (offices, paths,
    consent) — paths None for the whole door, and consent only beside paths that are all plain and none `/` — or
    None when it names no offices (no `to`: wherever `only` allows) or gives nothing (a path that is no path closes
    the whole door). Its raw flags are never taken at their word (the second reader)."""
    if not isinstance(old, dict) or old.get("to") is None:
        return None
    paths = old.get("paths")
    if paths is not None:
        paths = [str(p) for p in (paths if isinstance(paths, list) else [paths])]
        if not paths or not all(_plain(p) for p in paths):
            return None
    to = old["to"]
    offices = {str(o).strip().lower() for o in ([to] if isinstance(to, str) else to if isinstance(to, list) else [])
               if str(o).strip()}
    return offices, paths, old.get("public") is True and bool(paths) and "/" not in paths


def merge_doors(serve_map, given_doors: dict) -> dict:
    """`serve_map` with the herd's doors in `services` — a NEW map; `serve_map` is not changed (DGO-2125).

    A door the herd gives carries the herd's paths and consent (`public`), whatever the map says, and leaves
    `exclude`, which gives it to nobody: no writer of the volume narrows or withdraws it. NEVER WIDER for anybody
    else. One alias holds one spec, so an office the map gave the door to keeps it only when the herd's spec is no
    wider for it, judged as the map's entry really gives (`_map_door`): paths inside the map's own (or the whole
    door) and no consent the map did not really give. Every other office loses it, with a line, because closing is
    the safe side. A union of offices would have handed the internet consent to an office nobody consented for (the
    second reader). A door `exclude` gave to nobody, or the map gives with no offices or nothing as written, goes to
    the herd's offices alone. `doors` gives no alias an app goes by, so `exclude` never re-opens an app here. No
    other key moves."""
    if not given_doors:
        return serve_map
    base = dict(serve_map) if isinstance(serve_map, dict) else {}
    table = dict(base.get("services")) if isinstance(base.get("services"), dict) else {}
    ex = base.get("exclude")
    ex = [ex] if isinstance(ex, str) else (list(ex) if isinstance(ex, list) else None)
    excluded = {_low(x) for x in ex or []}
    for alias, d in sorted(given_doors.items()):
        to = set(d["to"])
        old = table.get(alias)
        mine = _map_door(old)
        if alias in excluded:
            _once("the serve map's `exclude` gives the door %s to nobody: the herd file's offices alone get it", alias)
        elif mine is not None:
            offices, paths, consent = mine
            if _within(d["paths"], paths) and (not d["public"] or consent):
                to |= offices
            elif offices - to:
                _once("the serve map gives the door %s to %s too: the herd file's paths or consent would widen it for "
                      "them, so they lose it", alias, ", ".join(sorted(offices - to)))
        elif isinstance(old, dict):
            _once("the serve map's own entry for the door %s names no offices or gives nothing as written: the herd "
                  "file's line names who gets it", alias)
        table[alias] = {"to": sorted(to), "paths": list(d["paths"]), "public": bool(d["public"])}
    base["services"] = table
    if ex is not None:
        kept = [x for x in ex if _low(x) not in given_doors]
        if len(kept) != len(ex):
            base["exclude"] = kept
    return base


def _rows(registry) -> list:
    return [r for r in ((registry or {}).get("apps") or []) if isinstance(r, dict)]


def _low(v) -> str:
    return str(v or "").strip().lower()


def tile(name: str, registry) -> tuple | None:
    """(app id, the tile's alias, the app has one tile, the tile's port) — the ONE tile a name in `give:` designates,
    or None. An alias is that tile; an app id is the tile whose alias is the app's id, or the app's only tile. An
    app with several tiles and none named like it is not guessed at (bina-claude's terminal is `claude-terminal`,
    named by its own alias, never by the desktop's)."""
    rows = _rows(registry)
    hit = next((r for r in rows if _low(r.get("alias")) == name), None)
    if hit is not None:
        app_id = _low(hit.get("app")) or name
    else:
        app_id = name
        tiles = [r for r in rows if _low(r.get("app")) == app_id]
        hit = tiles[0] if len(tiles) == 1 else None
        if hit is None:
            if tiles:
                _once("the herd file names %s, an app with several tiles and none called %s — name the tile", name, name)
            return None
    single = sum(1 for r in rows if _low(r.get("app")) == app_id) == 1
    try:
        port = int(hit.get("port"))
    except (TypeError, ValueError):
        return None
    return (app_id, _low(hit.get("alias")) or app_id, single, port) if 1 <= port <= 65535 else None


def names_of(t: tuple) -> set:
    """What designates exactly that tile in a `serve:` map's own words: its alias — and its app id, when the app
    has that one tile (the delivery plan keys an agent door by the app id: linkproxy `k in only`)."""
    app_id, alias, single, _port = t
    return {alias} | ({app_id} if single else set())


def merge(serve_map, given: dict, registry) -> dict:
    """`serve_map` with the herd's floor (`given`, from `floor`) in it — a NEW map; `serve_map` is not changed.

    In the map's own words, so every reader of it agrees (the catalog, the door's routes, the agent doors, the
    firewall, the agent token's naming), and nothing else of the map moves:
      * a floor tile the map does not serve is NAMED — keyed by its app id when it is the app's own tile (or the
        app's only one), by its alias when it is a sibling (`claude-terminal`: keyed by the app's id it would put
        the desktop on the terminal's port, catalog.tile_spec) — with its registry port: a key with no port would
        refuse the whole delivery plan (linkproxy). Under `*` nothing is added: every app is served already;
      * its names join the `only` list of an office it is given to, when that office is narrowed there (an EMPTY
        list included — the herd's word wins over it); and an office narrowed there that the floor does NOT give
        that app loses any name of it its list held while the map did not serve it — never wider than before;
      * the tile leaves `exclude` (which publishes to nobody — the herd file says somebody); only that tile.
    WHAT IT REACHES: a NAMED app reaches every office `only` does not narrow, exactly as a name in `serve:` always
    has — the herd's home offices among themselves, as `*` did before 12:56; a public or foreign office still meets
    DGO-1360's withholding of admin surfaces (a name is not `only`) where that rule runs, and so does a home office
    from an office in the herd file's `admin_by_name` (DGO-863): an admin app reaches only the office named. `only` matches an app's id
    against every tile of it (catalog.publishable), so a list that names `bina-claude` passes its terminal too, as
    a hand-written list always has. No `only` list is written for an office that had none (second reader: one
    would override that withholding, and gate its doors and hand-ons). An agent's TOKEN is not office-wide: a key
    added here names it only for the office the floor gives it (app.py `_named_agents`)."""
    if not given:
        return serve_map
    base = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
            for k, v in (serve_map or {}).items()} if isinstance(serve_map, dict) else {}
    rows = _rows(registry)
    every = _WILDCARD in base
    low_named = {_low(k) for k in base if k not in _RESERVED and k != _WILDCARD}
    only = base.get("only") if isinstance(base.get("only"), dict) else None
    if only is not None:
        only = {str(o): (list(v) if isinstance(v, list) else ([v] if isinstance(v, str) else []))
                for o, v in only.items()}
    exclude = base.get("exclude")
    exclude = [exclude] if isinstance(exclude, str) else (list(exclude) if isinstance(exclude, list) else None)
    per_office: dict = {}                # office → the names its only: list gains (names_of each floor tile)
    gives: dict = {}                     # office → the app ids the floor gives it
    added: dict = {}                     # app id → every name of it (its id, every tile's alias): the floor served it
    for office in sorted(given):
        for name in sorted(given[office]):
            t = tile(name, registry)
            if t is None:
                continue
            app_id, alias, single, port = t
            names = names_of(t)
            per_office.setdefault(office, set()).update(names)
            gives.setdefault(office, set()).add(app_id)
            every_name = {app_id} | {_low(r.get("alias")) for r in rows if _low(r.get("app")) == app_id}
            # THIS tile served already? (catalog.publishable: a name of the map meets its app id or its alias) — a
            # sibling named alone does not serve the app's own tile (second reader)
            if not every and not ({app_id, alias} & low_named):
                if not (every_name & low_named) and app_id not in added:
                    added[app_id] = every_name     # no tile of it was served: names a list held for it were dormant
                key = app_id if (alias == app_id or single) else alias
                base[key] = {"port": port}
                low_named.add(key)
            if exclude:
                exclude = [x for x in exclude if _low(x) not in names]
    if only is not None:
        for key_office, lst in only.items():
            office = _low(key_office)
            # never wider: a name this list held for an app the map did not serve does not open it now that the
            # floor serves it for SOMEBODY ELSE
            drop = set()
            for app_id, every_name in added.items():
                if app_id not in gives.get(office, set()):
                    drop |= every_name
            kept = [x for x in lst if _low(x) not in drop]
            have = {_low(x) for x in kept}
            only[key_office] = kept + sorted(n for n in per_office.get(office, set()) if n not in have)
        base["only"] = only
    if exclude is not None:
        base["exclude"] = exclude
    return base


def names_for(given: dict, office: str, registry=None) -> set:
    """What the floor gives `office` (a peer id), in the map's own words — each name's tile (`names_of`) when the
    registry is given, the names as written otherwise; empty when it gives that office none."""
    raw = set((given or {}).get(_low(office)) or set())
    if registry is None:
        return raw
    out = set()
    for name in raw:
        t = tile(name, registry)
        if t is not None:
            out |= names_of(t)
    return out
