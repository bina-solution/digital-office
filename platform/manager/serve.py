"""platform.manager.serve — the REVERSE plane: apps of ANOTHER office, shown HERE.

Why this is not `placement` (peers.py) with the sign flipped
-----------------------------------------------------------
A **placement** puts an app of THIS office on a remote one and keeps its tile at home: the traffic
goes home → remote, and the home console proxies it through `dgo-extend`'s own `/peer/…` door, which
is an ordinary HTTP service inside this network.

**`remote:` is the other direction**, and it is the everyday model (owner, 2026-10-01): an app runs
where it runs, and a linked office SHOWS it. The owner's first use is exactly this — talking to the
MacBook's בינה from `console.staging.digital-office.co.il` — so it must work without the console's
own proxy in the path. It cannot: an agent UI holds a websocket on `/api`, and the shell's WSGI proxy
buffers. So the tile is an `external` module — the shell FRAMES the app on its own nested host
(`bina.macbook.console.<this office's domain>`) — and that host is routed here, by this module.

`remote:` generalizes the single-office `serve:` block that came first: same entries, same refusals,
plus what a link needs to name a PEER (its label, the link it arrived through, the commit it was
fetched at). **`serve:` is still read as an alias for one release** — a machine whose state predates
the projection keeps working, and the projection takes over the block on its next run.

Where the route is emitted, and why a FILE and not labels
--------------------------------------------------------
Traefik v3.3 **cannot** point a docker-label service at an address outside the engine:

    $ docker run --label traefik.http.services.x.loadbalancer.server.url=http://console:8080 …
    ERR service "x" error: port is missing

Measured on this deployment 2026-09-30, on the live edge, with the router label present and the
service label rejected — so the router is dropped and the host 404s with a healthy-looking stack.
That is the same class of trap as Docker 29's silent 0-routers, and it is why the route is emitted
into traefik's FILE provider, which does support an external `servers[].url` (measured live the same
day: a router in `platform-base/traefik/config/` forwarded to `http://console:8000` and answered 200
while no container of its own existed).

Where the service POINTS, and why it is a docker alias and not the tunnel address
---------------------------------------------------------------------------------
The backend URL is `http://<alias>.<office>:<port>` — a **network alias on the link proxy**. It is
not the peer's tunnel address, and that is a correction rather than a preference: the tunnel address
(`10.79.x.2`) exists only inside the tunnel container's namespace, and the edge lives on
`traefik-network` with no route to it — so a router written against it answers nothing while every
screen says the link is up. The link proxy is the half that LISTENS on this network and forwards into
the tunnel (`dgo-extend/linkproxy.py`, its `use` rules), and the alias is what makes one name reach
one peer. `render_aliases()` below is the other half of that pair: the alias has to exist on the
container that owns the network attachment, and the compiler is what emits it.

One writer, and the input is a projection
----------------------------------------
The input is a top-level `remote:` block in `platform.state.yaml` — the file a converged office
already derives from its declarations (`bbox`'s state step) and the only one this compiler may read:
office declarations live in `dgo-extend`'s volume, which layer 0 cannot and must not reach into. Who
writes the block is the projection (`dgo-extend`'s `/api/link/remote`): it pulls each linked peer's
catalog and translates it into this shape. The shape is validated here with a sentence per refusal,
in Hebrew — a bad entry produces either a route to nowhere or a route to the wrong office, and "the
tile opens another office" is not a symptom anyone debugs from the console.

`remote:` names only the SERVING side (office + its tunnel address + its apps). The tile, the nested
host and the identity mapping are derived here, so the remote's declaration stays what it is — a
description of the other office — and this office's presentation of it stays this office's business.
"""
from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

import yaml

#: The checkout this layer lives in — used only to read the LINK's own record on this machine
#: (`own_addresses`), which is where "which end of the pair am I" is answered by a fact.
REPO = Path(__file__).resolve().parents[2]

#: The block in platform.state.yaml that declares what other offices show to this one.
BLOCK = "remote"
#: The name that block had before the catalog existed. Read for one release, never written.
LEGACY_BLOCK = "serve"

#: Every rule below ends in `\Z`, never `$`: Python's `$` also matches just BEFORE a trailing newline,
#: so `^…$` accepted "alice\n" — a header value with a line break, the very injection HEADER_RE exists
#: to refuse (the identity's `to`/`from` are not stripped before the check). DGO-615.
#: An office id: the same rule `apps/dgo-extend/declaration.py` applies to `link.office`.
OFFICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")
#: A host label / tile alias: DNS-safe, and it becomes part of `bina.macbook.console.<domain>`.
LABEL_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}\Z")
#: What may be written into an HTTP header. A value with CR/LF in it is header injection, and a
#: value with a space is a header the reverse proxy would split — both are refusals, not sanitizing.
HEADER_RE = re.compile(r"^[A-Za-z0-9@._+\-]{1,128}\Z")
#: A host authority a served app may be told it is being reached under (`host`). A DNS name (or an
#: address) plus an optional port — never a path, never a space, never a second host.
AUTHORITY_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251})?(:\d{1,5})?\Z")
#: The link plane's own range (`apps/dgo-extend/net.py`): one /24 per pair, under 10.79.0.0/16.
TUNNEL_NET = ipaddress.ip_network("10.79.0.0/16")
#: On a remote app's own host, the one path THIS office answers itself and never forwards: "is this
#: browser signed in here?" — a redirect to the identity provider when it is not, a plain 200 when it
#: is, readable by this office's console and by nobody else. The shell asks it before framing such a
#: host (`ownHostState`, console/static/app.js) and learns the path from the tile.
SIGNED_IN_PATH = "/.dgo/signed-in"
#: …and the one that TAKES a browser through this office's sign-in on that host and hands it back to
#: the console, at the route that follows the path. A frame cannot show the sign-in, a top-level load
#: can — and one that is alive at the identity provider passes it without a keystroke — so the shell
#: sends the browser here instead of asking a person to open a tab (`enterOwnHost`, app.js).
ENTER_PATH = "/.dgo/enter"
#: What the tile of an app that keeps its own host names: the question and the way in.
OWN_HOST = (("signed_in", SIGNED_IN_PATH), ("enter", ENTER_PATH))
#: The sign-in in front of every form that reaches a linked office's app: its admins' (DGO-1755). A person the owner
#: invited opens this office's work apps, never another office's through the link, which arrives as its owner.
REMOTE_SIGN_IN = "authentik-admins@file"
#: The block that opens a linked office's DOOR to the internet on THIS office's edge (DGO-2050): a client
#: of the business opens `https://sign.<domain>/s/<token>` on the herd's public office, and the request
#: crosses the link to the office that holds the key and the documents. Read by `publish_plan`.
PUBLISH_BLOCK = "publish"
#: A door's path (`/s/`, `/webhook/meet-recordings`): absolute, plain URL characters — the serving office's
#: own rule for the paths it narrows a door to (apps/dgo-extend/catalog.py PATH_RE + plain_path), so a door
#: it publishes is never refused here; its link door checks the raw request line against them (link-proxy.py).
DOOR_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]*\Z")


def door_path(p) -> bool:
    """Is `p` a path a door may be narrowed to — absolute, no `.` or `..` segment, nothing escaped?"""
    return isinstance(p, str) and bool(DOOR_PATH_RE.match(p)) and "/../" not in f"{p}/" and "/./" not in f"{p}/"


#: What every published door wears on this edge, defined in the same file (traefik drops a router whose
#: middleware is missing):
#:   - HSTS (G21's invariant 7);
#:   - headers: framed only by its own pages (the signer page frames its PDF), no sniffing, and no Referer,
#:     because the token is in the URL;
#:   - a rate per client address;
#:   - an in-flight cap per client and one per host;
#:   - the https redirect of its `web` twin.
PUBLIC_HEADERS_MW = "dgo-public-headers"
PUBLIC_RATE_MW = "dgo-public-rate"
PUBLIC_INFLIGHT_IP_MW = "dgo-public-inflight-ip"
PUBLIC_INFLIGHT_MW = "dgo-public-inflight"
PUBLIC_HTTPS_MW = "dgo-public-https"


class ServeError(RuntimeError):
    """One refusal, with the field named. Collected by plan(); raised by render()."""


def own_addresses(repo: Path | None = None) -> set[str]:
    """This office's OWN tunnel address(es), from the LINK's record on this machine.

    The rule here used to be `x.1 היא הכתובת של הלשכה הזו בצמד — הצד השני הוא .2`: an ASSUMPTION about
    which end owns `.1`, and the first real pair falsified it. The MacBook dials, so `step_link`
    renders it as side 1 and it holds `10.79.2.1`; vps1 — the CONSUMING office — holds `10.79.2.2`
    (`ip route get 10.79.2.1` there answers `src 10.79.2.2`). The refusal therefore rejected the one
    correct address a remote app can have, `reconcile render` exited on it, and a converge would have
    left that machine with an unusable block.

    So the question the check asks is the fact it always meant: is this address THIS office's own? The
    answer is in the link's own record, not in a convention — `.dgo/addressing.json` (what the tunnel's
    applier reads) and `.dgo/wg0.conf` (`Address = 10.79.2.2/24`, the copy the link step ships for the
    machine that runs `wg-quick` there). Both are per-machine facts; an office that has neither gets an
    empty set and the check falls back to refusing only the network and broadcast addresses.
    """
    root = Path(repo) if repo else REPO
    out: set[str] = set()
    try:
        doc = json.loads((root / ".dgo/addressing.json").read_text(encoding="utf-8")) or {}
        if doc.get("self"):
            out.add(str(doc["self"]).strip())
        # ONE ADDRESS PER PAIR (2026-10-04): an office linked to several peers holds a different
        # address in each, and `net.render_multi` renders them all into `pairs[]`. Reading only the
        # legacy `self` would call the second pair's address "not ours" and refuse a correct block.
        for entry in doc.get("pairs") or []:
            if (entry or {}).get("self"):
                out.add(str(entry["self"]).strip())
    except (OSError, ValueError):
        pass
    # `pairs/wg<slot>.conf` is the layout since one-interface-per-pair; `.dgo/wg0.conf` is what a
    # machine whose tunnel runs on the HOST still receives (and what an older render wrote), so both
    # are read — the question is the address, not the file name.
    files = [root / ".dgo/wg0.conf"]
    pairs_dir = root / ".dgo/pairs"
    if pairs_dir.is_dir():
        files += sorted(pairs_dir.glob("*.conf"))
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            m = re.match(r"^\s*Address\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})", line)
            if m:
                out.add(m.group(1))
    return out


def superseded_addresses(block, repo: Path | None = None) -> set[str]:
    """The addresses the machine's link record (`.dgo/addressing.json`) claims for pairs the block has since MOVED.

    That record is the far end of a link another office once converged onto this machine (its host `wg-quick@wg0`).
    When such a link is retired and the pair made again by DGO Extend on another slot, nothing on this machine removes
    the record, and `own_addresses` kept calling its address this office's own. vps1, measured 2026-11-12: its pair
    with the MacBook of September (slot 2, `self` 10.79.2.2) had been replaced on 11-05 by a join on slot 7; the Dell's
    new join was given the free slot 2 (dgo-extend's pair allocator reads the LIVE tunnel), its end is 10.79.2.2, and
    the refusal «the address of this office on this link» kept every tile of the Dell off staging. Two readers, two
    truths for one fact.

    So an address the record claims for its pair with office X stops being this office's own once the block — the
    live link plane's picture of every peer — places X on another /24: the record's pair is no longer that pair. It is
    conservative: an address no pair of the record names (a `self` of its own, a `wg0.conf` alone) still counts, and so
    does one any claimant of which the block does not place elsewhere. Read only after `own_addresses` has read the same
    file, so a record that crashes that reader never reaches this one.
    """
    root = Path(repo) if repo else REPO
    try:
        doc = json.loads((root / ".dgo/addressing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    pairs = doc.get("pairs") if isinstance(doc, dict) else None
    if not isinstance(pairs, list):
        return set()
    def office_id(v) -> str:
        """An office id as plan() takes one, or "": only an id OFFICE_RE accepts is compared (ASCII, so the Go twin's
        lowering agrees with str.lower() on every one of them — a Greek final sigma does not)."""
        oid = v.strip().lower() if isinstance(v, str) else ""
        return oid if OFFICE_RE.match(oid) else ""

    placed: dict[str, str] = {}
    for entry in block if isinstance(block, list) else []:
        office = office_id(entry.get("office")) if isinstance(entry, dict) else ""
        addr = entry.get("address") if isinstance(entry, dict) else None
        if not office or not isinstance(addr, str):
            continue
        try:
            ip = ipaddress.ip_address(addr.strip())
        except ValueError:
            continue
        if ip.version == 4 and ip in TUNNEL_NET:
            placed.setdefault(office, str(ip))
    claims: dict[str, list[str]] = {}
    for pair in pairs:
        own = pair.get("self") if isinstance(pair, dict) else None
        if isinstance(own, str) and own.strip():
            claims.setdefault(own.strip(), []).append(office_id(pair.get("office")))
    net = lambda a: a.rsplit(".", 1)[0]                          # noqa: E731 — the /24 of a dotted address
    return {a for a, offices in claims.items()
            if all(o and o in placed and net(placed[o]) != net(a) for o in offices)}


def source(state: dict) -> tuple[str, object]:
    """The block this office's reverse plane is declared in: `remote:` if present, else `serve:`.

    One function, so "which name is the block" is answered once. The new block WINS when both exist
    rather than being merged: the projection writes the whole picture from the peers' catalogs, and
    merging a stale hand-written `serve:` into it would resurrect apps their owner has since
    disabled — the one thing a catalog exists to prevent.
    """
    if state.get(BLOCK) not in (None, [], {}):
        return BLOCK, state.get(BLOCK)
    return LEGACY_BLOCK, state.get(LEGACY_BLOCK)


def _host(default, field: str, errs: list[str]) -> str:
    v = str(default if default is not None else "").strip()
    if not LABEL_RE.match(v):
        errs.append(f"remote: {field} {default!r} אינו תווית מארח תקינה "
                    f"(אותיות לטיניות קטנות, ספרות ומקף)")
    return v


def _label(value, office: str, errs: list[str], where: str) -> dict:
    """The office's display name, in whatever languages it published. A missing one is the office's
    own id — never empty, because " · " with nothing after it is what the tile would show."""
    if value in (None, ""):
        return {"he": office, "en": office}
    if isinstance(value, str):
        return {"he": value, "en": value}
    if not isinstance(value, dict):
        errs.append(f"{where}.label חייב להיות מחרוזת או אובייקט (he, en)")
        return {"he": office, "en": office}
    he = str(value.get("he") or value.get("en") or office).strip()
    en = str(value.get("en") or value.get("he") or office).strip()
    return {"he": he, "en": en}


def _mark(value, office: str = "") -> dict | None:
    """The linked office's mark — a colour NAME and an animal NAME — or None (flt-004).

    Never a hex: the consuming office draws the mark with its OWN palette entry for that name, so
    the value is the whole of what crosses the link. A peer that publishes no mark (an office whose
    catalog predates the feature) is NOT drawn blank: the name it is known by decides, through the
    same deterministic derivation every office runs — so two offices that both lack a peer's
    declaration still draw that peer the same way, and the peer's own choice wins the moment it
    publishes one. The vocabularies are `dgo-extend`'s identity module's, imported lazily and
    tolerated as absent: serve.py must keep rendering for a checkout where that app is not installed.
    """
    try:
        import sys as _sys, pathlib as _pathlib
        _sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2] / "apps" / "dgo-extend"))
        import identity as _identity
        return _identity.clean_mark(value) or _identity.mark_for(office)
    except Exception:
        return None


def plan(state: dict, cat: dict) -> tuple[list[dict], list[str]]:
    """Validate the `remote:` block and return (entries, errors). Pure: no filesystem, no render.

    Every entry ends up as an edge route and a tile, so each refusal here is one fewer way for this
    office to show a door that opens onto nothing — or onto the wrong office.
    """
    errs: list[str] = []
    name, raw = source(state)
    if raw in (None, [], {}):
        return [], errs
    if not isinstance(raw, list):
        return [], [f"{name}: חייב להיות רשימה של לשכות מרוחקות (office/address/apps), "
                    f"לא {type(raw).__name__}"]

    out: list[dict] = []
    seen_office: set[str] = set()
    seen_label: dict[str, str] = {}
    for i, entry in enumerate(raw):
        where = f"{name}[{i}]"
        if not isinstance(entry, dict):
            errs.append(f"{where}: חייב להיות אובייקט עם office, address ו-apps")
            continue
        oid = str(entry.get("office") or "").strip().lower()
        if not OFFICE_RE.match(oid):
            errs.append(f"{where}.office {entry.get('office')!r} אינו מזהה לשכה תקין")
            continue
        where = f"{name}[{i}] ({oid})"
        if oid in seen_office:
            errs.append(f"{where}.office: אותה לשכה מוצהרת פעמיים")
            continue
        seen_office.add(oid)

        addr = str(entry.get("address") or "").strip()
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            errs.append(f"{where}.address {addr!r} אינה כתובת IPv4 — זו כתובת הלשכה המרוחקת "
                        f"במנהרה (למשל 10.79.3.2)")
            continue
        if ip not in TUNNEL_NET:
            errs.append(f"{where}.address {addr} מחוץ ל-{TUNNEL_NET} — כתובת שנגישה מהאינטרנט "
                        f"אינה קישור, ובקשה שתישלח אליה לא תעבור במנהרה")
            continue
        if int(str(ip).split(".")[-1]) in (0, 255):
            errs.append(f"{where}.address {addr}: x.0/x.255 הן כתובות רשת/שידור, לא כתובת של לשכה")
            continue
        mine = own_addresses() - superseded_addresses(raw)
        if str(ip) in mine:
            errs.append(f"{where}.address {addr} היא הכתובת של הלשכה הזו בקישור הזה "
                        f"(מ-.dgo) — הצד השני הוא הקצה האחר של אותו /24")
            continue

        doors = entry.get("services")
        if doors is not None and not isinstance(doors, list):
            errs.append(f"{where}.services חייב להיות רשימה של דלתות (app, alias, port)")
            continue
        apps = entry.get("apps")
        # …empty only beside a door with no tile (DGO-945): an office may give this one a capability
        # and no screen at all — vps1's recordings, to the office that runs their workflow.
        if not isinstance(apps, list) or (not apps and not doors):
            errs.append(f"{where}.apps חייב להיות רשימה של אפליקציות שהלשכה הזו מציגה")
            continue
        clean = []
        for j, app in enumerate(apps):
            if not isinstance(app, dict):
                errs.append(f"{where}.apps[{j}] חייב להיות אובייקט (app, port ועוד)")
                continue
            aid = str(app.get("app") or "").strip().lower()
            if not LABEL_RE.match(aid):
                errs.append(f"{where}.apps[{j}].app {app.get('app')!r} אינו מזהה אפליקציה תקין")
                continue
            label = str(app.get("alias") or aid).strip().lower()
            if not LABEL_RE.match(label):
                errs.append(f"{where}.apps[{j}].alias {app.get('alias')!r} אינו תווית מארח תקינה")
                continue
            # A remote alias is namespaced by its office (`<alias>.<office>`), so it may collide
            # with a LOCAL app of the same name: that is the owner's own rule — "an app installed in
            # both offices appears twice, once with the remote mark". Two entries of the SAME office
            # may not share one host, which is what this check is for.
            if f"{oid}.{label}" in seen_label:
                errs.append(f"{where}.apps[{j}].alias '{label}' כבר נתפס על ידי {seen_label[f'{oid}.{label}']} "
                            f"— שתי אפליקציות של אותה לשכה לא יכולות לחלוק מארח")
                continue
            try:
                port = int(app.get("port"))
            except (TypeError, ValueError):
                errs.append(f"{where}.apps[{j}].port חייב להיות מספר — הפורט שהאפליקציה מאזינה "
                            f"עליו בלשכה שמגישה אותה")
                continue
            if not 1 <= port <= 65535:
                errs.append(f"{where}.apps[{j}].port {port} מחוץ לטווח")
                continue
            api_port = app.get("agent_api_port")
            if api_port not in (None, ""):
                try:
                    api_port = int(api_port)
                except (TypeError, ValueError):
                    errs.append(f"{where}.apps[{j}].agent_api_port חייב להיות מספר")
                    continue
                if not 1 <= api_port <= 65535 or api_port == port:
                    errs.append(f"{where}.apps[{j}].agent_api_port חייב להיות פורט אחר, בטווח")
                    continue
            else:
                api_port = None
            ident = app.get("identity") or {}
            if not isinstance(ident, dict):
                errs.append(f"{where}.apps[{j}].identity חייב להיות אובייקט (to, from)")
                continue
            # `to` is ONE user name — the identity a request BECOMES here. `from` is the LIST of the
            # peer's own user names that map onto it, which is the shape the serving office's
            # `catalog.build` publishes and the shape every reader below wants (the delivery plan
            # writes the whole list into `X-DGO-From`). Read as a single header string, the pair's own
            # `from` did not merely fail validation: it reached `sorted({…})` further down with the
            # list intact and the compiler died on `unhashable type: 'list'`, so a peer publishing the
            # shape it declares could not be consumed at all (measured 2026-10-09, DGO-49).
            to_v = ident.get("to")
            if to_v not in (None, ""):
                if not HEADER_RE.match(str(to_v)):
                    errs.append(f"{where}.apps[{j}].identity.to: הערך נכתב לכותרת HTTP, ולכן "
                                f"מותר רק אותיות, ספרות ותווי @ . _ + - (בלי רווחים ובלי שורה חדשה)")
                    continue
                ident["to"] = str(to_v)
            from_v = ident.get("from")
            if from_v not in (None, ""):
                users = list(from_v) if isinstance(from_v, (list, tuple)) else [from_v]
                users = [u for u in users if u not in (None, "")]
                if any(not HEADER_RE.match(str(u)) for u in users):
                    errs.append(f"{where}.apps[{j}].identity.from: כל שם נכתב לכותרת HTTP, ולכן "
                                f"מותר רק אותיות, ספרות ותווי @ . _ + - (בלי רווחים ובלי שורה חדשה)")
                    continue
                ident["from"] = [str(u) for u in users]
            seen_label[f"{oid}.{label}"] = f"{oid}:{aid}"
            host = str(app.get("host") or "").strip().lower()
            if host and not AUTHORITY_RE.match(host):
                errs.append(f"{where}.apps[{j}].host {app.get('host')!r} אינו שם מארח תקין — זה "
                            f"השם שהאפליקציה של הלשכה האחרת מצפה לקבל בכותרת Host")
                continue
            title = app.get("title") or {}
            if not isinstance(title, dict):
                title = {}
            name_he = str(app.get("name") or title.get("he") or aid)
            # A number, or this place's default: the tiles and the app rows are SORTED by it, and a peer's
            # null (or a word) beside numbers was a TypeError after half the files were written — one
            # linked office stopped this office's render (DGO-627). Missing reads the same.
            order = app.get("order")
            if not isinstance(order, (int, float)):
                order = 900
            clean.append({
                "app": aid, "alias": label, "port": port,
                "agent_api_port": api_port,
                "name": name_he,
                "name_en": str(app.get("name_en") or title.get("en") or name_he),
                "icon": str(app.get("icon") or "external"),
                "group": str(app.get("group") or "מרוחק"),
                "desc": str(app.get("desc") or f"אפליקציה של הלשכה {oid}"),
                "order": order,
                "host": host,
                "health": str(app.get("health") or "/healthz"),
                "module_kind": str((app.get("module") or {}).get("kind") or "embedded"),
                "module_path": str((app.get("module") or {}).get("path") or f"/a/{label}/"),
                # The peer's own MODULE ID, so a link written on that office resolves here: the
                # office's task tool hands the owner `#/m/project-pln/<inner route>` while this
                # office's tile is `plane.<office>` — a shell that only knew the alias opened the
                # first tile instead (app.js/module-ref.js).
                "module_id": str((app.get("module") or {}).get("id") or aid),
                "identity": {k: ident[k] for k in ("to", "from") if ident.get(k)},
            })
        # …and its DOORS WITH NO TILE (DGO-945): the capabilities that office offers to this one, each
        # only an address on this office's network (`render_aliases`) and a place a workflow imported
        # here is pointed at (reconcile.link_endpoints). Never a tile, an edge route or a sign-in
        # entry: nothing below reads this list but those two.
        services = []
        for j, svc in enumerate(doors or []):
            if not isinstance(svc, dict):
                errs.append(f"{where}.services[{j}] חייב להיות אובייקט (app, alias, port)")
                continue
            sid = str(svc.get("app") or "").strip().lower()
            label = str(svc.get("alias") or "").strip().lower()
            if not LABEL_RE.match(sid) or not LABEL_RE.match(label):
                errs.append(f"{where}.services[{j}]: app/alias {svc.get('app')!r}/{svc.get('alias')!r} אינם תקינים")
                continue
            if f"{oid}.{label}" in seen_label:
                errs.append(f"{where}.services[{j}].alias '{label}' כבר נתפס על ידי {seen_label[f'{oid}.{label}']}")
                continue
            try:
                port = int(svc.get("port"))
            except (TypeError, ValueError):
                port = 0
            if not 1 <= port <= 65535:
                errs.append(f"{where}.services[{j}].port {svc.get('port')!r} אינו פורט בטווח")
                continue
            # The prefixes the serving office lets through this door (DGO-945's `paths`, DGO-2050): kept,
            # because a door this office may PUBLISH must be one the serving office narrowed itself.
            paths = svc.get("paths")
            if paths is not None and (not isinstance(paths, list) or not paths
                                      or not all(door_path(p) for p in paths)):
                errs.append(f"{where}.services[{j}].paths {paths!r}: רשימה של נתיבים מוחלטים, בלי . ו-.. "
                            f"(למשל /s/)")
                continue
            seen_label[f"{oid}.{label}"] = f"{oid}:{sid}"
            row = {"app": sid, "alias": label, "port": port}
            if paths is not None:
                row["paths"] = sorted(set(paths))
            # …and whether it OPENED the door to the internet (`public: true`, DGO-2050): its consent, without
            # which no office may publish it
            if svc.get("public") is True:
                row["public"] = True
            services.append(row)
        if clean or services:
            # ONE identity per link, not per app: two apps of the same office reachable under two
            # different identities is a second trust plane that nobody declared.
            to_users = sorted({a["identity"]["to"] for a in clean if a["identity"].get("to")})
            if len(to_users) > 1:
                errs.append(f"{where}: שני מיפויי זהות שונים ({', '.join(to_users)}) — "
                            f"קישור אחד, זהות אחת")
                continue
            # The peer's link DOOR, as it published it (DGO-32): every UI route of that office
            # targets this one port and the Host header picks the app. Optional on purpose — a peer
            # whose catalog predates the door publishes apps with their own ports, and then a route
            # per app is exactly what the link proxy still listens on.
            door = entry.get("link_port")
            if door not in (None, ""):
                try:
                    door = int(door)
                except (TypeError, ValueError):
                    door = 0
                if not 1 <= door <= 65535:
                    errs.append(f"{where}.link_port {entry.get('link_port')!r} אינו פורט בטווח")
                    continue
            else:
                door = 0
            out.append({"office": oid, "address": str(ip), "apps": clean, "link_port": door,
                        "label": _label(entry.get("label"), oid, errs, where),
                        "link": str(entry.get("link") or oid),
                        "commit": str(entry.get("commit") or ""),
                        # The office's mark, as its catalog published it (flt-004). A pair the
                        # vocabularies do not know is NAMED here and dropped: a tile invented from a
                        # typo is worse than a tile without a mark.
                        "mark": _mark(entry.get("mark"), oid),
                        "identity": {"to": to_users[0] if to_users else None,
                                     # The names, flattened out of the per-app lists and de-duplicated:
                                     # ONE identity per link, and this is the list the edge turns into
                                     # `X-DGO-From` — so it is a list of strings, never a list of lists.
                                     "from": sorted({u for a in clean
                                                     for u in (a["identity"].get("from") or [])})}})
            if services:
                out[-1]["services"] = services
    return out, errs


def through_console(app: dict) -> bool:
    """May this remote app be framed through THIS console's own origin (`/a/<alias>.<office>/`)?

    Only when both hold, and each refusal is a measured failure rather than a preference:

      · it is EMBEDDED at home (`module.kind`). An app of its own host there addresses the ROOT of
        its origin — the serving office publishes `external` for it, whichever way the app says so
        (`reconcile._own_host_only`) — and on this console's origin the root belongs to THIS
        office's apps: the MacBook's בינה framed here made every call to hp-laptop's own agent, and
        its console listed hp-laptop's apps, so a tile of one office showed the other (measured
        2026-10-05).
      · it NAMES the authority it answers under (`host`). An app that names none is reached under
        the browser's own authority and checks it (`Origin` == `Host`); through a proxy the
        authority is the proxy's, and it refuses every call (measured the same day: 403).
    """
    return app.get("module_kind") != "external" and bool(app.get("host"))


def _tileless(cat: dict, app_id) -> bool:
    """True when the app's own manifest declares every routed module `tile: false`."""
    mods = [r.get("module") or {} for r in ((cat or {}).get(app_id) or {}).get("routing") or []]
    mods = [m for m in mods if m]
    return bool(mods) and all(m.get("tile") is False for m in mods)


#: The path an app lists its hand-offs at (`handoffs`, the manifest schema's own pattern).
HANDOFFS_PATH = re.compile(r"/[A-Za-z0-9/_.-]*")


def handoffs_path(cat: dict, app_id) -> str:
    """Where the app lists the people it is waiting for (`handoffs` in its manifest, DGO-1336), or "".

    Read from THIS office's copy of the manifest, as `_tileless` is: the declaration is the app's, in
    the one repository every office carries, so a linked office's app is asked at the path its own
    manifest names. The console reads the address the tile carries and never names the app (G9)."""
    path = ((cat or {}).get(app_id) or {}).get("handoffs")
    return path if isinstance(path, str) and HANDOFFS_PATH.fullmatch(path) else ""


def module_entries(entries: list[dict], cat: dict, taken=None) -> list[dict]:
    """The console tiles a `remote:` entry produces — ONE PER (OFFICE, ALIAS).

    Same shape the compiler emits for a LOCAL app's `routing[].module` (that is what the shell reads),
    with three differences that are the whole point: `external` — the shell frames the app on its own
    host instead of proxying it; no `service`, because there is no service in this network to probe;
    and a `remote` block, which is what the shell marks the tile with (`is-remote`, the office's
    label, `<office> לא זמינה כרגע` when the frame never renders).

    The tile id is `<alias>.<office>`, never the bare alias: a local app of the same name keeps its
    own tile, and both are listed side by side. The `host` is `<alias>.<office>` for the same reason
    — the shell appends its own hostname, so the framed destination is
    `<alias>.<office>.console.<domain>`, which is the name the router below matches.

    `taken` is accepted and IGNORED, for one release, so a caller written against the older signature
    (`taken=<ids of the local tiles>`) cannot crash a render mid-way. It used to suppress a remote tile
    when a local app owned the alias; the owner's rule is the opposite — an app installed in both
    offices appears TWICE — so the suppression is gone and the argument no longer means anything.
    """
    out = []
    for entry in entries:
        for app in entry["apps"]:
            # an app whose OWN manifest says `tile: false` (its screen lives in another app — machine's in
            # computers, DGO-890) gets no tile as a linked office's app either. Decided from THIS office's
            # copy of the manifest, so it holds for a peer that predates the flag; the link still carries
            # the app (computers reads machine.<office> through the door), only the launcher omits it.
            if _tileless(cat, app.get("app")):
                continue
            tile = f"{app['alias']}.{entry['office']}"
            # …and the people it is waiting for (DGO-1336): an app that declares `handoffs` is asked on
            # its agent door, which the link carries as `<alias>.<office>:<agent_api_port>` like every
            # agent door — the console SERVER's address, stripped from `/api/modules` with `door`.
            handoffs = handoffs_path(cat, app.get("app"))
            asked = ([("handoffs", f"http://{tile}:{app['agent_api_port']}{handoffs}")]
                     if handoffs and app.get("agent_api_port") else [])
            # THE SAME APP THROUGH THIS CONSOLE'S OWN ORIGIN. On a console whose identity provider
            # is another SITE — every `*.localhost` office: `auth.localhost` and `console.localhost`
            # are two sites — the nested host cannot authorize inside a frame (the provider's session
            # cookie is not sent to a cross-site frame, and its login page refuses framing), so the
            # tile opened onto a browser error page (measured 2026-10-05, hp-laptop). There the shell
            # frames `proxy`, and the console's own proxy reaches `door`: the same alias and port the
            # router below targets, with the same identity and Host. `door` is the console SERVER's
            # — `/api/modules` does not hand it out. Only an app that can live there gets one
            # (`through_console`); the others keep their own host on every console, and their tile
            # names the path where this office's edge says whether the browser is signed in there
            # (`SIGNED_IN_PATH`) — which is what the shell asks before framing a host that cannot
            # show its own sign-in — and the one that signs it in (`ENTER_PATH`).
            door = list(OWN_HOST) if not through_console(app) else [
                ("proxy", f"/a/{tile}/"),
                ("door", dict([
                    ("base", f"http://{tile}:{int(entry.get('link_port') or 0) or app['port']}"),
                    ("host", app["host"]),
                    ("user", (entry.get("identity") or {}).get("to") or ""),
                    ("from", list((entry.get("identity") or {}).get("from") or [])),
                ])),
            ]
            out.append(dict([
                ("id", tile),
                ("name", app["name"]),
                ("icon", app["icon"]),
                ("group", app["group"]),
                ("desc", f"{app['desc']} · {entry['label']['he']}".strip(" ·")),   # names the office
                ("order", app["order"]),
                ("external", True),
                ("host", tile),
                ("embed", f"/a/{app['alias']}/"),
                *door,
                ("office", entry["office"]),
                ("label", entry["label"]),
                # `commit`/`link` are optional in the block (a hand-written one may omit them):
                # absent, they are the empty string and the office id, never a KeyError in the
                # middle of a render.
                ("remote", {"office": entry["office"], "label": entry["label"],
                            "link": entry.get("link") or entry["office"],
                            "address": entry["address"], "commit": entry.get("commit") or "",
                            "mark": entry.get("mark"),
                            "port": app["port"], "api_port": app["agent_api_port"],
                            # …and how to resolve a link written on THAT office: by the app's own
                            # name there (`alias`, what both offices call it) or by its module id
                            # (`module_id`, what `#/m/…` carries). Either lands on this tile.
                            "alias": app["alias"], "module_id": app.get("module_id") or ""}),
                *asked,
            ]))
    return out


def own_origins(host: str, entry_points, port: str = "") -> list[str]:
    """Every `Origin` a browser sends from a page ON `host` — the scheme of each entry point it can
    arrive through, and the port it reached this edge on when that is not the scheme's own.

    Exact strings, never a pattern: a page on another port of the same name is another origin (the
    browser sends it the same cookies, which is exactly why it must not pass for this one).
    """
    # `lan` is plain HTTP like `web` (apps/lan-console: the office's console on its local network)
    schemes = [s for s, eps in (("http", ("web", "lan")), ("https", ("websecure",)))
               if any(ep in entry_points for ep in eps)]
    return [f"{s}://{host}{p}" for p in ([""] + ([f":{port}"] if port else [])) for s in schemes]


def render(entries: list[dict], cat: dict, domain: str = "localhost",
           console_port: str = "", framed=(), lan_domain: str = "", lan_port: str = "") -> str | None:
    """Traefik FILE-provider dynamic config for every remote app, or None when there is none.

    Two routers per app, the platform's own convention (`routing_labels()`):
      · `<alias>.<office>-console-local` — `Host(<alias>.<office>.console.localhost)`, plain web
      · `<alias>.<office>-console`       — `Host(<alias>.<office>.console.<domain>)`, web + TLS
        (omitted when this office's domain IS localhost — a second router with an identical rule is
        noise, and traefik would pick between two identical matchers)
      · `<alias>.<office>-console-http`  — the same nested host on `web` ALONE, answering a permanent
        redirect to https (`dgo-remote-https`, traefik's `redirectScheme`) and forwarding nothing
        (`noop@internal`). A router with a `tls` section handles TLS requests only, so the `-console`
        router above — `web` + `websecure` + `tls` — never matched on :80, and a link typed without
        `https://` was the edge's 404 (measured 2026-10-14 on vps1,
        `browser42.hp-laptop.console.staging.digital-office.co.il`; DGO-569). The base apps serve
        plain `web` behind SSO (`routing_labels`: `-http`), which a nested host must not — the sign-in
        and the console it hands back to are https — so the twin redirects. One twin per nested host
        covers every router of that host (`-own-origin`, `-signed-in`, `-enter` share it); the
        `.localhost` routers are `web`-only and plain, and get none.
    …for an app that names its authority, an `-own-origin` twin of each, and for an app that keeps
    its own host on every console, a `-signed-in` and an `-enter` one (explained where they are built). That
    is why `console_port` is asked for: the port a browser on the host reaches this edge on is part
    of every `Origin` it sends, exactly as it is part of the host `sso_hosts` registers.

    Both carry this office's own sign-in — its admins' since DGO-1755 (`REMOTE_SIGN_IN`; on the LAN entry
    `lan-auth-admins@docker`): the tile is under THIS office's SSO. That is the whole of the trust
    question on this side — what leaves for the serving office is this office's own authenticated
    user, rewritten to the mapped one by the identity middleware.

    The backend is the network alias on the link proxy (`http://bina.macbook:3080`), whose listener
    forwards into the tunnel. The alias itself is emitted by `render_aliases()` — a router to a name
    that does not resolve is a 502 with a healthy stack, which is exactly the failure this pair
    exists to make impossible.

    `framed` — {router name: host} of THIS office's apps the shell frames on a host of their own —
    is here for the routers such a host shares with a remote one: the shell's question and the way in.

    `lan_domain` — the NAME this office's console has on the local network (DGO-1126: the owner's phone
    on the office Wi-Fi, `console.<lan_domain>:<lan_port>`, apps/lan-console). An address cannot have a
    host nested under it, so a shared app that keeps its own host could not open there; under a name it
    can, exactly as on a real domain. Each app then gets one more form, `…-console-lan`, on the `lan`
    entry, signed in by that entry's own door — its admins' (`lan-auth-admins@docker`, the LAN outpost;
    DGO-1755) — instead of `REMOTE_SIGN_IN`, whose sign-in lives on a host the phone cannot reach. (Its
    shell's question and way in, `-signed-in` and `-enter`, keep `lan-auth@docker`.)
    """
    if not entries and not framed:
        return None
    console_routes = (cat.get("console") or {}).get("routing") or []
    console_host = (console_routes[0].get("host") if console_routes else "") or "console"
    domain = (domain or "localhost").strip()

    routers, services, middlewares = dict(), dict(), dict()
    asks_mw, answers, asked = "dgo-remote-console-asks", "dgo-remote-console-answers", False
    returns = "dgo-remote-console-returns"
    https_mw = "dgo-remote-https"

    lan_domain = (lan_domain or "").strip()
    lan_auth = "lan-auth@docker"

    def door_of(entry_points):
        """The sign-in in front of a form: the LAN entry's own outpost there, authentik's elsewhere."""
        return lan_auth if list(entry_points) == ["lan"] else "authentik@file"

    def remote_door_of(entry_points):
        """The sign-in in front of a form that REACHES a linked office's app — its admins' (DGO-1755): the door
        rewrites the caller to the far office's mapped user, so a linked office's app is the office's admins' alone,
        as the console's own /a/<alias>.<office>/ door holds it. The question and the way in (own_host) stay."""
        return "lan-auth-admins@docker" if list(entry_points) == ["lan"] else REMOTE_SIGN_IN

    def own_host(name, host, entry_points):
        """The two routers of a host whose sign-in a frame cannot show — answered HERE, both of them,
        and never forwarded to the office the app runs on."""
        nonlocal asked
        auth = door_of(entry_points)
        for tail, path, chain in (
                # THE SHELL'S QUESTION: `authentik@file` sends an unsigned browser to the identity
                # provider, and a signed one is answered by this office's own console, at its health
                # path — a plain 200, where traefik's built-in empty service says 418 and every
                # browser prints that as an error. `asks` stands in FRONT of the sign-in so that the
                # redirect, too, is readable by the console — a redirect without it is a network
                # error to the page that asked, i.e. "the office is down" where the truth is "sign
                # in" (measured on traefik v3.3: the headers middleware decorates the auth server's
                # own 302).
                ("signed-in", f"Path(`{SIGNED_IN_PATH}`)", [asks_mw, auth, answers]),
                # …AND THE WAY IN: the same sign-in, met by a browser that came to pass it, and
                # then the console again.
                ("enter", f"PathPrefix(`{ENTER_PATH}`)", [auth, returns])):
            routers[f"{name}-{tail}"] = dict([
                ("rule", f"Host(`{host}`) && {path}"), ("entryPoints", list(entry_points)),
                ("service", answers), ("middlewares", chain)])
            if "websecure" in entry_points:
                routers[f"{name}-{tail}"]["tls"] = dict([("certResolver", "myresolver")])
        asked = True
    for entry in entries:
        oid = entry["office"]
        # ── the identity the SERVING office's app will see (DGO-31) ───────────────────────────────
        # Rendered per office, not per app: it is one link, and two apps of the same office must not
        # be reachable under two identities. The header a CLIENT sends is not what makes this safe —
        # this office's own sign-in (`REMOTE_SIGN_IN`) runs first in the chain and replaces the identity
        # headers with the answer of THIS office's own outpost, so a forged `X-authentik-username` is already gone
        # before the mapped one is written. The mapping is therefore about the SERVING office's
        # vocabulary (`akadmin` here, the owner there), not about trust.
        ident_users = {entry["identity"].get("to")} if entry["identity"].get("to") else set()
        refused_users = set(entry["identity"].get("from") or [])
        mw_name = f"dgo-remote-{oid}-identity"
        if ident_users:
            to_user = sorted(ident_users)[0]
            mw = dict([("headers", dict([
                ("customRequestHeaders", dict([("X-authentik-username", to_user)])),
            ]))])
            if refused_users:
                mw["headers"]["customRequestHeaders"]["X-DGO-From"] = ",".join(sorted(refused_users))
            middlewares[mw_name] = mw

        # THE DOOR (DGO-32): one listener per link on the serving side, with the Host header picking
        # the app — because that office's registry holds four apps on 8080 and a listener per app
        # either collides or silently picks a winner. The port is published by the office that owns
        # the door (`catalog.build(link_port=…)`); an entry with none (a peer that predates the door,
        # or a catalog fetched before it existed) keeps the app's own port, which is what the link
        # proxy used to listen on.
        door = int(entry.get("link_port") or 0)
        for app in entry["apps"]:
            tile = f"{app['alias']}.{oid}"
            svc = f"dgo-remote-{oid}-{app['alias']}"
            services[svc] = dict([("loadBalancer", dict([
                # The alias, not the tunnel address: see the module docstring. It resolves, inside
                # this network, to the link proxy — the one process that listens here and forwards
                # into the tunnel.
                ("servers", [dict([("url", f"http://{tile}:{door or app['port']}")])]),
                # The remote end is a real application, so its Host header is the one it expects to
                # answer under — and it is what its own SSO/redirects are built from.
                ("passHostHeader", True),
            ]))])
            base_mw = [REMOTE_SIGN_IN] + ([mw_name] if ident_users else [])
            # ── and the name it expects to BE (DGO-32) ────────────────────────────────────────────
            # Passing the client's own Host is right up to the moment the app validates it: the
            # harness this office runs refuses every authority it was not told about (measured:
            # `Host: bina.console.staging…` answers nothing at all, `Host: bina.localhost` answers
            # 200), and the nested console host is not its name. The catalog carries the authority
            # the serving app answers under, and it is written here — after this office's sign-in, so the
            # identity this office establishes is what the app reads its user from.
            own_mw = ""
            if app.get("host"):
                host_mw = f"{svc}-host"
                middlewares[host_mw] = dict([("headers", dict([
                    ("customRequestHeaders", dict([("Host", app["host"])])),
                ]))])
                base_mw = base_mw + [host_mw]
                # ── …and the ORIGIN goes with it ──────────────────────────────────────────────────
                # An app that checks who is calling compares `Origin` with `Host` (the agent's
                # harness refuses every API call and its websocket when they differ — measured: 403
                # under a rewritten Host, 200 under `Host` and `Origin` of its own authority). So the
                # framed page calling its OWN server — an `Origin` that is exactly the host the
                # request was sent to — takes a twin router that writes the app's authority into
                # both. Every other `Origin` keeps the plain router and arrives untouched: that is
                # another site's page calling, and refusing it is the app's fence, which must hold.
                own_mw = f"{svc}-own-origin"
                middlewares[own_mw] = dict([("headers", dict([
                    ("customRequestHeaders", dict([("Origin", f"http://{app['host']}")])),
                ]))])
            forms = [(f"{svc}-console-local", f"{tile}.{console_host}.localhost", ["web"],
                      console_port if domain == "localhost" else "")]
            if domain != "localhost":
                forms.append((f"{svc}-console", f"{tile}.{console_host}.{domain}",
                              ["web", "websecure"], ""))
            if lan_domain:
                forms.append((f"{svc}-console-lan", f"{tile}.{console_host}.{lan_domain}",
                              ["lan"], lan_port))
            for name, host, entry_points, port in forms:
                chain = [remote_door_of(entry_points) if m == REMOTE_SIGN_IN else m for m in base_mw]
                # a served app's https host is a PUBLIC name of this office: it pins https like every
                # other certificate (DGO-1595). `hsts` is defined by the compiler in zz-https.yaml on
                # every office; adding it only where an https router exists keeps the other chains
                # byte-identical.
                if "websecure" in entry_points and "hsts@file" not in chain:
                    chain = ["hsts@file"] + chain    # FIRST: the sign-in's 302 ends the chain before a later pin

                def router(rule, chain):
                    r = dict([("rule", rule), ("entryPoints", list(entry_points)),
                              ("service", svc), ("middlewares", list(chain))])
                    if "websecure" in entry_points:
                        r["tls"] = dict([("certResolver", "myresolver")])
                    return r
                # The longer rules below outrank this one (traefik orders routers by rule length).
                routers[name] = router(f"Host(`{host}`)", chain)
                if "websecure" in entry_points:
                    # THE HTTP TWIN (DGO-569, see the docstring): `web` alone, no `tls`, so it is the
                    # one router of this host the non-TLS handler keeps. No sign-in in front of it —
                    # nothing is served here, so there is nothing to protect, and the sign-in itself
                    # runs where the redirect lands.
                    routers[f"{name}-http"] = dict([
                        ("rule", f"Host(`{host}`)"), ("entryPoints", ["web"]),
                        ("service", "noop@internal"), ("middlewares", [https_mw])])
                    middlewares[https_mw] = dict([("redirectScheme", dict([
                        ("scheme", "https"), ("permanent", True)]))])
                if own_mw:
                    own = " || ".join(f"Header(`Origin`, `{o}`)"
                                      for o in own_origins(host, entry_points, port))
                    routers[f"{name}-own-origin"] = router(f"Host(`{host}`) && ({own})",
                                                           chain + [own_mw])
                if not through_console(app):
                    own_host(name, host, entry_points)
    # …AND THE SAME TWO FOR AN APP OF THIS OFFICE that the shell frames on its own host. The
    # sign-in is this office's there too, and a frame cannot show it for the same reason (the
    # provider is another site on `.localhost`) — measured 2026-10-06 on hp-laptop: the Plane window
    # of an owner whose sign-in had run out was the browser's "refused to connect" page.
    for name, host in sorted(dict(framed).items()):
        own_host(name, host, ["web"])
    if asked:
        # Who may read the answer: a page of THIS office's console, on every address a browser
        # reaches it by — and it is sent the cookie of the host it asks about, or the answer would
        # always be "sign in".
        names = [f"{console_host}.localhost"] + ([] if domain == "localhost" else [f"{console_host}.{domain}"])
        consoles = own_origins(names[0], ["web"], console_port if domain == "localhost" else "")
        for wide in names[1:]:
            consoles += own_origins(wide, ["web", "websecure"])
        if lan_domain:
            names.append(f"{console_host}.{lan_domain}")
            consoles += own_origins(names[-1], ["lan"], lan_port)
        middlewares[asks_mw] = dict([("headers", dict([
            ("accessControlAllowOriginList", consoles),
            ("accessControlAllowCredentials", True),
        ]))])
        # …and where a browser that came to sign in goes next: the console the host is nested
        # under, on the scheme and port it arrived by, at the route that followed the path.
        middlewares[returns] = dict([("redirectRegex", dict([
            ("regex", "^(https?://)[^/]+\\.(%s)((?::[0-9]+)?)%s(.*)$"
                      % ("|".join(map(re.escape, names)), re.escape(ENTER_PATH))),
            ("replacement", "${1}${2}${3}/#${4}"),
        ]))])
        # …and who answers a signed-in browser: the console, by the name and port its own manifest
        # gives it on the office network — a URL in THIS file, so the route never depends on the
        # docker provider's snapshot of the console's container.
        console = console_routes[0] if console_routes else {}
        middlewares[answers] = dict([("replacePath", dict([("path", "/healthz")]))])
        services[answers] = dict([("loadBalancer", dict([("servers", [dict([
            ("url", f"http://{console.get('service') or 'console'}:{int(console.get('port') or 8000)}"),
        ])])]))])
    doc = dict([("http", dict())])
    if middlewares:
        doc["http"]["middlewares"] = middlewares
    doc["http"]["routers"] = routers
    doc["http"]["services"] = services
    header = (
        "# GENERATED by platform/manager/serve.py from platform.state.yaml `remote:` — DO NOT EDIT.\n"
        "# The apps of another office, shown HERE under this office's SSO: one router per app on\n"
        "# <alias>.<office>.<console host>.<domain>, forwarding to the link proxy's network alias.\n"
        "# A FILE and not labels because traefik refuses an external server URL in a docker label.\n")
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False, width=1000)


def render_aliases(entries: list[dict]) -> str | None:
    """The compose overlay that puts `<alias>.<office>` on the link proxy, or None.

    The edge routes to a NAME (`http://bina.macbook:3080`) and every agent inside the engine calls
    one (`http://bina.macbook:3081`), so the name has to resolve on the office network — and it
    resolves because it is a **network alias on the container that owns the attachment**, which is
    the tunnel container: the link proxy shares its namespace (`network_mode: service:dgo-net`), and
    a container with no network settings of its own cannot carry an alias.

    A docker alias can only be set at container creation, so this is a compose OVERLAY rather than
    something an app applies at runtime — and the compiler is the only party that may write it,
    because the alias list is a function of `remote:` and the app is forbidden from editing its own
    compose (that would be a second writer for one fact).

    Named `remote.override.yml` and included by `compose_files()` LAST among the aliases' peers: a
    later `-f` file wins, and this one only ever ADDS aliases under the service's own network stanza.
    """
    # every app's, and every door's with no tile (DGO-945): an alias is all a door is on this side
    aliases = sorted({f"{a['alias']}.{e['office']}" for e in entries
                      for a in list(e["apps"]) + list(e.get("services") or [])})
    if not aliases:
        return None
    doc = dict([("services", dict([("dgo-net", dict([
        ("networks", dict([("traefik-network", dict([("aliases", aliases)]))])),
    ]))]))])
    header = (
        "# GENERATED by platform/manager/serve.py from platform.state.yaml `remote:` — DO NOT EDIT.\n"
        "# One network alias per remote app on the link proxy's namespace (dgo-net): this is what\n"
        "# makes `http://<alias>.<office>:<port>` resolve inside the office network, for the edge\n"
        "# and for every agent. Applied by `dc up -d`, i.e. when the remote app set changes.\n")
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False, width=1000)


def publish_plan(state: dict, served: list[dict], domain: str = "",
                 cat: dict | None = None) -> tuple[list[dict], list[str], list[str]]:
    """Check `publish:` against the doors linked offices give this one: (published, errors, dropped).

    `publish:` opens ONE door of a linked office to the internet on THIS office's edge (DGO-2050). The example is
    the signer's page of the office that holds the documents and the signing key, reached through the herd's
    public office, which holds neither:

        publish:
          - host: sign.staging.digital-office.co.il
            door: esign-public.hp-laptop          # <the door's alias>.<the office that serves it>
            paths: [/s/]

    TWO KINDS OF NO, and only one stops the render:
    - `errors`: this office's own declaration is malformed. Not a list, not an object, a host that is no host,
      lies off this office's public domain or is a name one of its own apps is routed under, a host or a door
      twice, two doors whose routers would share a name, a path that is no path or is `/` (the whole app). The
      render stops, as for any malformed state, before the edge's files are written.
    - `dropped`: the SERVING office decides, and it decided otherwise. It no longer gives this door, did not
      narrow it to paths, did not open it to the internet (`public: true` in its serve.services, its consent to
      this), or narrowed it to paths that do not hold the ones asked for. The door is LEFT OUT with a line, and
      the render goes on: a change on the other office must never stop every render here, and leaving it out
      is closing it.

    Only an office with a real domain publishes; `localhost` has no internet to publish to.
    """
    raw = state.get(PUBLISH_BLOCK)
    if raw in (None, [], {}):
        return [], [], []
    if not isinstance(raw, list):
        return [], [f"{PUBLISH_BLOCK}: חייב להיות רשימה של דלתות מפורסמות (host, door, paths), "
                    f"לא {type(raw).__name__}"], []
    domain = (domain or "").strip().lower()
    doors = {f"{s['alias']}.{e['office']}": (e, s) for e in (served or []) for s in (e.get("services") or [])}
    # the names this office's own apps are routed under (`console`, `auth`, `esign`, …): a door published on one
    # would take its paths from that app, since traefik prefers the longer rule
    routed = {str(r.get("host")).strip().lower() for m in (cat or {}).values() if isinstance(m, dict)
              for r in (m.get("routing") or []) if isinstance(r, dict) and r.get("host")}
    out: list[dict] = []
    errs: list[str] = []
    dropped: list[str] = []
    hosts: set[str] = set()
    taken: set[str] = set()
    names: set[str] = set()
    for i, item in enumerate(raw):
        where = f"{PUBLISH_BLOCK}[{i}]"
        if not isinstance(item, dict):
            errs.append(f"{where}: חייב להיות אובייקט עם host, door ו-paths")
            continue
        host = str(item.get("host") or "").strip().lower()
        if not AUTHORITY_RE.match(host) or ":" in host or "." not in host:
            errs.append(f"{where}.host {item.get('host')!r} אינו שם מארח (בלי פורט ובלי נתיב)")
            continue
        if domain in ("", "localhost") or not host.endswith("." + domain):
            errs.append(f"{where}.host {host}: אינו תחת הדומיין של הלשכה הזו ({domain or 'אין לה דומיין'}) — "
                        f"רק לשכה עם דומיין ציבורי מפרסמת, ורק תחתיו")
            continue
        first = host[:-(len(domain) + 1)].split(".")[-1]
        if first in routed:
            errs.append(f"{where}.host {host}: {first}.{domain} כבר מנותב לאפליקציה של הלשכה הזו — "
                        f"שם אחר, למשל sign")
            continue
        if host in hosts:
            errs.append(f"{where}.host {host}: מפורסם פעמיים")
            continue
        door = str(item.get("door") or "").strip().lower()
        if "." not in door:
            errs.append(f"{where}.door {item.get('door')!r}: <כינוי הדלת>.<הלשכה שנותנת אותה>, למשל "
                        f"esign-public.hp-laptop")
            continue
        if door in taken:
            errs.append(f"{where}.door {door}: מפורסמת פעמיים — דלת אחת, שם מארח אחד")
            continue
        # the routers' names are built from the office and the alias, and a dash joins both: office `a-b` with
        # alias `c` and office `a` with alias `b-c` would be ONE router, and the later would replace the earlier
        alias, _, office = door.partition(".")
        name = f"dgo-public-{office}-{alias}"
        if name in names or f"{name}-http" in names:
            errs.append(f"{where}.door {door}: שם הנתב {name} מתנגש בנתב של דלת אחרת שמתפרסמת כאן — כינוי "
                        f"או לשכה אחרים")
            continue
        paths = item.get("paths")
        if not isinstance(paths, list) or not paths or not all(door_path(p) for p in paths) or "/" in paths:
            errs.append(f"{where}.paths {paths!r}: רשימה של נתיבים מוחלטים, בלי . ו-.., ולא / (האפליקציה כולה) "
                        f"— למשל /s/")
            continue
        hosts.add(host)
        taken.add(door)
        names.update((name, f"{name}-http"))
        # …and what the SERVING office decides: a door it gives, narrows and opens to the internet, or none
        if door not in doors:
            dropped.append(f"{where}: {door} — אין דלת כזו בין הדלתות שלשכות מקושרות נותנות ללשכה הזו כרגע; "
                           f"לא מתפרסם")
            continue
        entry, svc = doors[door]
        given = svc.get("paths") or []
        if not given:
            dropped.append(f"{where}: {door} — הלשכה {entry['office']} לא צמצמה את הדלת לנתיבים; לא מתפרסם")
            continue
        if svc.get("public") is not True:
            dropped.append(f"{where}: {door} — הלשכה {entry['office']} לא פתחה את הדלת לאינטרנט "
                           f"(public: true ב-serve.services שלה); לא מתפרסם")
            continue
        outside = sorted(p for p in set(paths)
                         if not any(p == g or (g.endswith("/") and p.startswith(g)) for g in given))
        if outside:
            dropped.append(f"{where}: {', '.join(outside)} — מחוץ לנתיבים שהלשכה {entry['office']} פתחה בדלת "
                           f"({', '.join(given)}); לא מתפרסם")
            continue
        port = int(entry.get("link_port") or 0) or int(svc["port"])
        out.append({"name": name, "host": host,
                    "office": entry["office"], "alias": svc["alias"], "app": svc["app"],
                    "url": f"http://{door}:{port}", "paths": sorted(set(paths))})
    return out, errs, dropped


def render_published(published: list[dict]) -> str | None:
    """Traefik FILE-provider dynamic config for every published door (DGO-2050), or None when there is none.

    Per door, two routers and one service, nothing else:
      · `<name>`: on `websecure`, `Host(<host>) && (…)`, where each path is a `PathPrefix` when it ends in
        `/` and an exact `Path` when it does not, as the serving door itself matches it. The router carries:
          - its own Let's Encrypt certificate and HSTS;
          - headers: framed only by its own pages (SAMEORIGIN: the signer page frames its own PDF at
            /s/<token>/doc, which DENY would blank), no sniffing, and no Referer, because the token is in the URL;
          - a rate per client address (this edge is the only hop that sees it);
          - an in-flight cap per client and one per host.
        Every other path of the host matches nothing: traefik's 404.
      · `<name>-http`: the host on `web`, a permanent redirect to https, forwarding nothing.
      · the service: the door's network alias on the link proxy, with `passHostHeader: false`. The serving
        office's link door picks the door by the Host it is sent, and the client's Host never travels.
    No sign-in: the token in the path is the credential, and the serving app answers only it. The serving
    office's link door does mark the request as this office's (X-Dgo-Office, and X-Dgo-Herd on a herd pair). That
    grants nothing beyond the door's paths, which are all it answers. Nothing here adds an identity.
    Known limit: IPv6 clients reach vps1's edge as one docker address (DGO-1633), so they share one rate bucket.
    """
    if not published:
        return None
    middlewares = dict([
        (PUBLIC_HEADERS_MW, dict([("headers", dict([
            ("customFrameOptionsValue", "SAMEORIGIN"), ("contentTypeNosniff", True),
            ("referrerPolicy", "no-referrer")]))])),
        (PUBLIC_RATE_MW, dict([("rateLimit", dict([("average", 30), ("period", "1m"), ("burst", 20)]))])),
        (PUBLIC_INFLIGHT_IP_MW, dict([("inFlightReq", dict([
            ("amount", 5), ("sourceCriterion", dict([("ipStrategy", dict([("depth", 0)]))]))]))])),
        (PUBLIC_INFLIGHT_MW, dict([("inFlightReq", dict([
            ("amount", 20), ("sourceCriterion", dict([("requestHost", True)]))]))])),
        (PUBLIC_HTTPS_MW, dict([("redirectScheme", dict([("scheme", "https"), ("permanent", True)]))])),
    ])
    routers, services = dict(), dict()
    for p in published:
        rule = f"Host(`{p['host']}`) && (" + " || ".join(
            f"PathPrefix(`{x}`)" if x.endswith("/") else f"Path(`{x}`)" for x in p["paths"]) + ")"
        routers[p["name"]] = dict([
            ("rule", rule), ("entryPoints", ["websecure"]), ("service", p["name"]),
            ("middlewares", ["hsts@file", PUBLIC_HEADERS_MW, PUBLIC_RATE_MW, PUBLIC_INFLIGHT_IP_MW,
                             PUBLIC_INFLIGHT_MW]),
            ("tls", dict([("certResolver", "myresolver")]))])
        routers[f"{p['name']}-http"] = dict([
            ("rule", f"Host(`{p['host']}`)"), ("entryPoints", ["web"]),
            ("service", "noop@internal"), ("middlewares", [PUBLIC_HTTPS_MW])])
        services[p["name"]] = dict([("loadBalancer", dict([
            ("servers", [dict([("url", p["url"])])]), ("passHostHeader", False)]))])
    doc = dict([("http", dict([("middlewares", middlewares), ("routers", routers), ("services", services)]))])
    header = (
        "# GENERATED by platform/manager/serve.py from platform.state.yaml `publish:` — DO NOT EDIT.\n"
        "# A linked office's DOOR, opened to the internet on this office's edge (DGO-2050): only the paths\n"
        "# that office narrowed it to, no sign-in (the token in the path is the credential), a rate per client.\n")
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False, width=1000)


def sso_hosts(entries: list[dict], cat: dict, domain: str = "localhost",
              console_port: str = "") -> list[dict]:
    """The identity-layer host(s) each remote app needs — `<alias>.<office>.<console host>.<domain>`.

    A router is not a reachable host until the IDENTITY layer knows the name: measured on this
    deployment 2026-09-30, a served router matched and forwardAuth answered 404 with a 3.6 KB page
    ("the app is missing") while the edge looked healthy in the access log. So the compiler emits one
    authentik proxy provider per remote host, with the SAME string the router matches — derived here,
    once, so the two cannot drift.

    Two forms on `.localhost`, for the reason `framed_sso_entries` documents: the office browser
    reaches this edge PORT-LESS (`localhost-forward.py` serves loopback :80) while a browser on the
    host is on the console's own port, and `Host` carries the port it was reached on. On a real
    domain there is exactly one form — the nested name under this office's own.
    """
    console_routes = (cat.get("console") or {}).get("routing") or []
    console_host = (console_routes[0].get("host") if console_routes else "") or "console"
    out = []
    for entry in entries:
        for app in entry["apps"]:
            framed = f"{app['alias']}.{entry['office']}.{console_host}"
            out.append({
                "slug": f"dgo-remote-{entry['office']}-{app['alias']}",
                "name": f"{app['name']} · {entry['label']['he']}",
                "host": f"{framed}.localhost" if domain == "localhost" else f"{framed}.{domain}",
                "port_host": (f"{framed}.localhost:{console_port}"
                              if domain == "localhost" and console_port else ""),
            })
    return out


def describe(entries: list[dict], cat: dict) -> list[dict]:
    """A flat, printable view of what a `remote:` block produces — the `serve-plan` verb's output.

    Exists because the render is a template: "what will traefik actually route" must be answerable
    without reading Go-template syntax, by a human and by the phase-3 gate.
    """
    console_routes = (cat.get("console") or {}).get("routing") or []
    console_host = (console_routes[0].get("host") if console_routes else "") or "console"
    rows = []
    for entry in entries:
        for app in entry["apps"]:
            rows.append({
                "office": entry["office"], "address": entry["address"], "app": app["app"],
                "alias": app["alias"],
                "host": f"{app['alias']}.{entry['office']}.{console_host}.<DEPLOYMENT_DOMAIN>",
                "local_host": f"{app['alias']}.{entry['office']}.{console_host}.localhost",
                "target": f"http://{app['alias']}.{entry['office']}:{app['port']}",
                "tile": f"{app['alias']}.{entry['office']}",
                "identity_to": app["identity"].get("to"),
                "identity_from": app["identity"].get("from"),
            })
    return rows


def selftest() -> list[str]:
    """Pure checks of the refusals this plane depends on. No filesystem, no traefik, no link — which
    is the point: the gate can exercise it before any remote office exists."""
    problems = []
    cat = {"console": {"routing": [{"host": "console"}]}}

    def run(state):
        return plan(state, cat)

    good = {"remote": [{"office": "macbook", "address": "10.79.3.2",
                        "label": {"he": "המקבוק", "en": "MacBook"}, "link": "macbook",
                        "apps": [{"app": "bina-ds", "port": 3080, "agent_api_port": 3081,
                                  "alias": "bina", "name": "עזריה",
                                  "identity": {"to": "owner@local"}}]}]}
    entries, errs = run(good)
    if errs or len(entries) != 1 or entries[0]["apps"][0]["port"] != 3080:
        problems.append(f"a valid remote block was refused or misread: {errs}")
    if not render(entries, cat):
        problems.append("a valid remote block rendered nothing")
    tiles = module_entries(entries, cat)
    if len(tiles) != 1 or tiles[0]["id"] != "bina.macbook" or tiles[0]["host"] != "bina.macbook":
        problems.append(f"one remote app must produce one namespaced tile, got {tiles}")
    if tiles[0]["remote"]["office"] != "macbook" or tiles[0]["external"] is not True:
        problems.append(f"the tile must carry the office and be external, got {tiles[0]}")
    if "proxy" in tiles[0] or "door" in tiles[0] or "own-origin" in render(entries, cat):
        problems.append(f"an app that names no authority is reached under the browser's own: it must "
                        f"get neither this console's proxy path nor a rewritten Origin, got {tiles[0]}")

    # WHICH apps take the console's own door: embedded at home AND naming their authority.
    doors = {"remote": [{"office": "macbook", "address": "10.79.3.2", "link_port": 9004,
                         "apps": [{"app": "drive", "port": 8975, "host": "drive.localhost",
                                   "identity": {"to": "owner@local"}},
                                  {"app": "bina-ds", "alias": "bina", "port": 3080,
                                   "host": "bina.localhost", "module": {"kind": "external"}},
                                  {"app": "notes", "port": 8000}]}]}
    dentries, derrs = run(doors)
    by_id = {t["id"]: t for t in module_entries(dentries, cat)} if not derrs else {}
    drive = by_id.get("drive.macbook") or {}
    if drive.get("proxy") != "/a/drive.macbook/" or drive.get("door") != {
            "base": "http://drive.macbook:9004", "host": "drive.localhost",
            "user": "owner@local", "from": []}:
        problems.append(f"an embedded app that names its authority must name its same-origin path "
                        f"and the door the console proxies to (the link's door, the app's Host, the "
                        f"identity): {derrs or drive}")
    plain = module_entries([dict(dentries[0], link_port=0)], cat) if dentries else [{}]
    if (plain[0].get("door") or {}).get("base") != "http://drive.macbook:8975":
        problems.append("a peer that publishes no link door is proxied on the app's own port")
    for tid, why in (("bina.macbook", "is an app of its own host at home (it addresses its origin's "
                                      "root, which on this console belongs to this office's apps)"),
                     ("notes.macbook", "names no authority")):
        t = by_id.get(tid) or {"proxy": "missing"}
        if "proxy" in t or "door" in t or t.get("external") is not True:
            problems.append(f"{tid} {why}: it must keep its own host on every console, got {t}")

    # THE ORIGIN GOES WITH THE HOST: a page calling its own server, and only that page.
    def routers(**kw):
        return (yaml.safe_load(render(dentries, cat, **kw)) or {}).get("http", {}) if dentries else {}
    local = routers(console_port="8080")
    own = (local.get("routers") or {}).get("dgo-remote-macbook-drive-console-local-own-origin") or {}
    here = "drive.macbook.console.localhost"
    if own.get("rule") != (f"Host(`{here}`) && (Header(`Origin`, `http://{here}`) || "
                           f"Header(`Origin`, `http://{here}:8080`))"):
        problems.append(f"the own-origin twin must match exactly the Origins of a page on that host "
                        f"(port-less and on the console's port), got {own.get('rule')!r}")
    if own.get("middlewares", [])[-2:] != ["dgo-remote-macbook-drive-host",
                                           "dgo-remote-macbook-drive-own-origin"]:
        problems.append(f"the twin must write the Host AND the Origin, after the identity: {own}")
    wrote = ((local.get("middlewares") or {}).get("dgo-remote-macbook-drive-own-origin") or {})
    if (wrote.get("headers") or {}).get("customRequestHeaders") != {"Origin": "http://drive.localhost"}:
        problems.append(f"the Origin written must be the app's own authority, got {wrote}")
    if "dgo-remote-macbook-drive-own-origin" in (
            (local.get("routers") or {}).get("dgo-remote-macbook-drive-console-local") or {}
    ).get("middlewares", []):
        problems.append("the plain router must leave a foreign Origin untouched — that is the app's "
                        "fence against another site's page")
    if any(k.startswith("dgo-remote-macbook-notes") and k.endswith("own-origin")
           for k in (local.get("routers") or {})):
        problems.append("an app whose Host is not rewritten must not have its Origin rewritten")
    there = "drive.macbook.console.example.co.il"
    wide = (routers(domain="example.co.il", console_port="8080").get("routers") or {})
    if (wide.get("dgo-remote-macbook-drive-console-own-origin") or {}).get("rule") != (
            f"Host(`{there}`) && (Header(`Origin`, `http://{there}`) || "
            f"Header(`Origin`, `https://{there}`))") or "tls" not in (
            wide.get("dgo-remote-macbook-drive-console-own-origin") or {}):
        problems.append(f"on a real domain the twin matches the http and https Origin of the nested "
                        f"host, no port, with TLS: {wide.get('dgo-remote-macbook-drive-console-own-origin')}")
    if "8080" in str((wide.get("dgo-remote-macbook-drive-console-local-own-origin") or {}).get("rule")):
        problems.append("the console's port belongs to a localhost office's Origin only")

    # THE HTTP TWIN (DGO-569): on a real domain every nested host answers :80 with a permanent
    # redirect to https, through a router on `web` ALONE that forwards nothing — and the existing
    # `-console` router is untouched. A `.localhost` office, plain web, gets no twin and no redirect.
    wide_doc = routers(domain="example.co.il", console_port="8080")
    twin = wide.get("dgo-remote-macbook-drive-console-http")
    if twin != {"rule": f"Host(`{there}`)", "entryPoints": ["web"], "service": "noop@internal",
                "middlewares": ["dgo-remote-https"]}:
        problems.append(f"a nested host on a real domain must have an http twin on `web` alone, no TLS, "
                        f"no sign-in, forwarding nothing and redirecting to https: {twin}")
    if (wide_doc.get("middlewares") or {}).get("dgo-remote-https") != {
            "redirectScheme": {"scheme": "https", "permanent": True}}:
        problems.append(f"the twin's middleware must be a permanent redirectScheme to https: "
                        f"{(wide_doc.get('middlewares') or {}).get('dgo-remote-https')}")
    twins = sorted(k for k, r in wide.items() if r.get("service") == "noop@internal")
    nested = sorted({r["rule"] for r in wide.values()
                     if r.get("entryPoints") == ["web", "websecure"] and "&&" not in r["rule"]})
    if len(twins) != len(dentries[0]["apps"]) or len(nested) != len(twins) \
            or not all(k.endswith("-console-http") for k in twins):
        problems.append(f"exactly ONE twin per nested host on the real domain, named `-console-http`: "
                        f"{twins} for {nested}")
    kept = wide.get("dgo-remote-macbook-drive-console") or {}
    if kept.get("entryPoints") != ["web", "websecure"] or "tls" not in kept \
            or [m for m in kept.get("middlewares", []) if m != "hsts@file"][:1] != [REMOTE_SIGN_IN]:
        # (the sign-in opens the chain after the pin, which comes first on an https router: DGO-1595)
        problems.append(f"the twin is an ADDITION: the `-console` router keeps its entry points, its TLS "
                        f"and its sign-in: {kept}")
    if any(r.get("service") == "noop@internal" for r in (local.get("routers") or {}).values()) \
            or "dgo-remote-https" in (local.get("middlewares") or {}) \
            or "dgo-remote-macbook-drive-console-local-http" in wide:
        problems.append("a `.localhost` router is plain web and gets neither a twin nor a redirect")

    # THE SHELL'S QUESTION: only a tile that keeps its own host names it, the edge answers it itself,
    # and only this office's console may read the answer.
    asks = (local.get("routers") or {}).get("dgo-remote-macbook-bina-console-local-signed-in") or {}
    if (by_id.get("bina.macbook") or {}).get("signed_in") != SIGNED_IN_PATH or "signed_in" in drive:
        problems.append(f"a tile names the sign-in question exactly when it keeps its own host: "
                        f"{by_id.get('bina.macbook')} / {drive}")
    if asks.get("rule") != f"Host(`bina.macbook.console.localhost`) && Path(`{SIGNED_IN_PATH}`)" \
            or asks.get("service") != "dgo-remote-console-answers" \
            or asks.get("middlewares") != ["dgo-remote-console-asks", "authentik@file",
                                           "dgo-remote-console-answers"]:
        problems.append(f"the question must be answered by this office (never forwarded to the "
                        f"other one), behind this office's sign-in, with the console's leave to "
                        f"read it written in FRONT of that sign-in: {asks}")
    answered = ((local.get("services") or {}).get("dgo-remote-console-answers") or {}).get("loadBalancer") or {}
    if answered.get("servers") != [{"url": "http://console:8000"}] or (
            (local.get("middlewares") or {}).get("dgo-remote-console-answers") != {"replacePath": {"path": "/healthz"}}):
        problems.append(f"a signed-in browser is answered by this office's console at its health "
                        f"path — a 200, not the edge's 418: {answered}")
    if any(k.startswith("dgo-remote-macbook-drive") and k.endswith("signed-in")
           for k in (local.get("routers") or {})):
        problems.append("an app framed through the console's own origin is never asked")
    readers = (((local.get("middlewares") or {}).get("dgo-remote-console-asks") or {})
               .get("headers") or {})
    if readers != {"accessControlAllowOriginList": ["http://console.localhost",
                                                    "http://console.localhost:8080"],
                   "accessControlAllowCredentials": True}:
        problems.append(f"only this office's console may read the answer, with the cookie of the "
                        f"host it asks about: {readers}")
    if "dgo-remote-console-asks" in str(yaml.safe_load(render(
            [dict(dentries[0], apps=[a for a in dentries[0]["apps"] if a["app"] == "drive"])], cat))):
        problems.append("no tile asks, so nobody is given leave to read an answer")
    # THE WAY IN: the same tile names it, the same sign-in stands in front of it, and what comes
    # after is the console the host is nested under — on the address the browser arrived by.
    enter = (local.get("routers") or {}).get("dgo-remote-macbook-bina-console-local-enter") or {}
    if (by_id.get("bina.macbook") or {}).get("enter") != ENTER_PATH or "enter" in drive \
            or enter.get("rule") != f"Host(`bina.macbook.console.localhost`) && PathPrefix(`{ENTER_PATH}`)" \
            or enter.get("middlewares") != ["authentik@file", "dgo-remote-console-returns"] \
            or enter.get("service") != "dgo-remote-console-answers":
        problems.append(f"a tile that keeps its own host names the way in, which is this office's "
                        f"sign-in and then a redirect — never the other office: {enter}")

    def back(doc, url):
        mw = ((doc.get("middlewares") or {}).get("dgo-remote-console-returns") or {}).get("redirectRegex") or {}
        return re.sub(mw.get("regex") or "$^", re.sub(r"\$\{(\d)\}", r"\\g<\1>", mw.get("replacement") or ""), url)
    for doc, url, want in (
            (local, "http://bina.macbook.console.localhost:8080/.dgo/enter/m/bina.macbook",
             "http://console.localhost:8080/#/m/bina.macbook"),
            (local, "http://bina.macbook.console.localhost/.dgo/enter", "http://console.localhost/#"),
            (routers(domain="example.co.il"), "https://bina.macbook.console.example.co.il/.dgo/enter/m/x?y=1",
             "https://console.example.co.il/#/m/x?y=1"),
            (routers(domain="example.co.il"), "http://bina.macbook.console.localhost/.dgo/enter",
             "http://console.localhost/#"),
            (local, "http://console.localhost.example.org/.dgo/enter", "http://console.localhost.example.org/.dgo/enter")):
        if back(doc, url) != want:
            problems.append(f"after the sign-in on {url} the browser must be at {want}, got {back(doc, url)}")
    home = (yaml.safe_load(render([], cat, framed={"plane-frame": "plane.console.localhost"}) or "{}")
            or {}).get("http", {})
    if (home.get("routers") or {}).get("plane-frame-signed-in") != {
            "rule": f"Host(`plane.console.localhost`) && Path(`{SIGNED_IN_PATH}`)", "entryPoints": ["web"],
            "service": "dgo-remote-console-answers",
            "middlewares": ["dgo-remote-console-asks", "authentik@file", "dgo-remote-console-answers"],
    } or "plane-frame-enter" not in (home.get("routers") or {}) \
            or not {"dgo-remote-console-asks", "dgo-remote-console-answers",
                    "dgo-remote-console-returns"} <= set(home.get("middlewares") or {}) \
            or render([], cat) is not None:
        problems.append(f"an app of THIS office framed on its own host is asked the same question and "
                        f"given the same way in, with no linked office at all — and an office with "
                        f"neither renders nothing: {home}")
    if "המקבוק" not in tiles[0]["desc"]:
        problems.append(f"the tile's description must name the office (the asleep-remote notice "
                        f"shows it), got {tiles[0]['desc']}")
    plain = [r for r in (yaml.safe_load(render(entries, cat))["http"]["routers"]).values()
             if r["rule"] == "Host(`bina.macbook.console.localhost`)"]
    if len(plain) != 1:
        problems.append("the local twin router must match the nested host exactly once")
    overlay = render_aliases(entries)
    if not overlay or "bina.macbook" not in overlay or "dgo-net" not in overlay:
        problems.append(f"the alias overlay must put <alias>.<office> on the link proxy: {overlay}")
    # The alias is what the router points at: a route to a name nobody resolves is a 502.
    if "http://bina.macbook:3080" not in render(entries, cat):
        problems.append("the backend must be the network alias, not the peer's tunnel address")
    if "10.79.3.2" in render(entries, cat):
        problems.append("the tunnel address must not appear as a backend — it is not routable from "
                        "the edge's network")

    # The legacy spelling keeps working: the projection replaces it, it is not a migration.
    legacy = {"serve": [{"office": "macbook", "address": "10.79.3.2",
                         "apps": [{"app": "bina-ds", "port": 3080, "alias": "bina"}]}]}
    lentries, lerrs = run(legacy)
    if lerrs or not lentries:
        problems.append(f"`serve:` must still be read as an alias of `remote:`: {lerrs}")
    if not render(lentries, cat):
        problems.append("a legacy `serve:` block must still render")

    bad = [
        ({"remote": [{"office": "MAC BOOK", "address": "10.79.3.2", "apps": []}]}, "office"),
        ({"remote": [{"office": "macbook", "address": "8.8.8.8",
                      "apps": [{"app": "bina-ds", "port": 3080}]}]}, "מנהרה"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.0",
                      "apps": [{"app": "bina-ds", "port": 3080}]}]}, "רשת"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds"}]}]}, "port"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 0}]}]}, "טווח"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080, "agent_api_port": 3080}]}]},
         "agent_api_port"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080, "alias": "bina"},
                               {"app": "drive", "port": 8975, "alias": "bina"}]}]}, "אותה לשכה"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080,
                                "identity": {"to": "owner\r\nX-Evil: 1"}}]}]}, "כותרת"),
        # a TRAILING newline alone — Python's `$` let it through (DGO-615)
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080,
                                "identity": {"to": "owner\n"}}]}]}, "כותרת"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080,
                                "identity": {"to": "owner", "from": ["guest\n"]}}]}]}, "כותרת"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080,
                                "identity": {"to": "a@b"}},
                               {"app": "drive", "port": 8975, "identity": {"to": "c@d"}}]}]},
         "זהות"),
        ({"remote": "macbook"}, "רשימה"),
        ({"remote": [{"office": "macbook", "address": "10.79.3.2",
                      "apps": [{"app": "bina-ds", "port": 3080, "host": "bina.localhost/x"}]}]},
         "Host"),
    ]
    for state, needle in bad:
        _e, errs = run(state)
        if not errs or not any(needle in e for e in errs):
            problems.append(f"expected a refusal mentioning {needle!r}, got {errs}")

    # The refusal that used to read "x.1 is this office" is now the FACT it always meant — a peer
    # address that is THIS office's own — and the pair's own record answers it (`own_addresses`).
    # Faked here so this check stays pure and machine-independent (a real `.dgo/` is a machine fact).
    real = globals().get("own_addresses")
    try:
        globals()["own_addresses"] = lambda repo=None: {"10.79.3.1"}
        _e, errs = run({"remote": [{"office": "macbook", "address": "10.79.3.1",
                                    "apps": [{"app": "bina-ds", "port": 3080}]}]})
        if not any("הלשכה הזו" in e for e in errs):
            problems.append(f"a peer address that is THIS office's own must be refused, got {errs}")
        # …and the SAME address is accepted when it is the peer's: this is the live pair's shape
        # (the MacBook holds .1, the consuming vps1 holds .2) and it was refused before the fix.
        globals()["own_addresses"] = lambda repo=None: {"10.79.3.2"}
        picked, perrs = run({"remote": [{"office": "macbook", "address": "10.79.3.1",
                                         "apps": [{"app": "bina-ds", "port": 3080}]}]})
        if perrs or not any(e["address"] == "10.79.3.1" for e in picked):
            problems.append(f"a peer that holds `.1` must be accepted, got {perrs or picked}")
    finally:
        globals()["own_addresses"] = real

    # A host record of a pair the block has MOVED claims its address no more (vps1, 2026-11-12: the September pair
    # with the MacBook on slot 2, re-made on slot 7, held the Dell's new end 10.79.2.2 as vps1's own) — and one whose
    # pair the block keeps on that /24, or does not place at all, still does.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".dgo").mkdir()
        (Path(tmp) / ".dgo/addressing.json").write_text(json.dumps({"self": "10.79.2.2", "pairs": [
            {"office": "macbook", "self": "10.79.2.2"}]}), encoding="utf-8")
        dell = {"office": "portable-ubuntu", "address": "10.79.2.2"}
        for block, want in (([{"office": "macbook", "address": "10.79.7.2"}, dell], {"10.79.2.2"}),
                            ([{"office": "MacBook", "address": " 10.79.7.2 "}, dell], {"10.79.2.2"}),
                            ([{"office": "macbook", "address": "10.79.2.1"}, dell], set()),
                            ([dell], set()),
                            ([{"office": "macbook", "address": "93.184.216.7"}, dell], set()),
                            ([{"office": "mac book", "address": "10.79.7.2"}, dell], set())):
            got = superseded_addresses(block, tmp)
            if got != want:
                problems.append(f"superseded_addresses({block}) is {got}, not {want}")

    # TWO OFFICES, one alias: the owner's own rule ("an app installed in both appears twice").
    two = {"remote": [
        {"office": "macbook", "address": "10.79.3.2", "label": "המקבוק",
         "apps": [{"app": "bina-ds", "port": 3080, "alias": "bina"}]},
        {"office": "vps1", "address": "10.79.4.2", "label": "vps1",
         "apps": [{"app": "bina-ds", "port": 3080, "alias": "bina"}]}]}
    tentries, terrs = run(two)
    if terrs:
        problems.append(f"two offices may both serve an app named `bina`: {terrs}")
    ttiles = module_entries(tentries, cat)
    if sorted(t["id"] for t in ttiles) != ["bina.macbook", "bina.vps1"]:
        problems.append(f"each office's tile must be namespaced by office, got {ttiles}")
    talias = render_aliases(tentries) or ""
    if "bina.macbook" not in talias or "bina.vps1" not in talias:
        problems.append(f"both offices' aliases must be emitted, got {talias}")
    # And the SAME office twice on one alias is still refused (checked above) — namespace, not luck.

    # A DOOR WITH NO TILE (DGO-945): the Dell's transcriber beside a tile of the same office. It gets
    # its address on this office's network and nothing else — no tile, no route on this office's edge.
    svc = {"remote": [{"office": "dell", "address": "10.79.5.2", "link_port": 9005, "label": "Dell",
                       "apps": [{"app": "ollama", "alias": "ollama", "port": 11434,
                                 "module": {"kind": "embedded"}}],
                       "services": [{"app": "apitools", "alias": "speech", "port": 8987}]}]}
    sentries, serrs = run(svc)
    if serrs or len(sentries) != 1 or sentries[0].get("services") != [
            {"app": "apitools", "alias": "speech", "port": 8987}]:
        problems.append(f"a service door beside a tile must be accepted as a door: {serrs} {sentries}")
    else:
        if [t["id"] for t in module_entries(sentries, cat)] != ["ollama.dell"]:
            problems.append(f"a service door must draw no tile, got {module_entries(sentries, cat)}")
        routed = render(sentries, cat) or ""
        if "speech.dell" in routed or "dgo-remote-dell-speech" in routed:
            problems.append("a service door must get no route on this office's edge")
        if "ollama.dell" not in routed:
            problems.append("the tile beside it must keep its route")
        if "speech.dell" not in (render_aliases(sentries) or ""):
            problems.append("a service door must get its network alias — that is the whole door")
        if "speech" in json.dumps(sso_hosts(sentries, cat), ensure_ascii=False):
            problems.append("a service door must get no sign-in entry")
    # …and a door that takes an app's own alias is refused like two apps on one host
    clash = {"remote": [dict(svc["remote"][0], services=[{"app": "apitools", "alias": "ollama", "port": 8987}])]}
    if not run(clash)[1]:
        problems.append("a door on the alias of an app of the same office must be refused")
    # …and an office that gives a door and no app at all is one entry with its alias and no tile
    only_door = {"remote": [dict(svc["remote"][0], apps=[])]}
    oentries, oerrs = run(only_door)
    if oerrs or len(oentries) != 1 or module_entries(oentries, cat) \
            or "speech.dell" not in (render_aliases(oentries) or ""):
        problems.append(f"a door with no app beside it must still be an alias, and nothing else: {oerrs}")
    if not run({"remote": [dict(svc["remote"][0], apps=[], services=[])]})[1]:
        problems.append("an office that gives neither an app nor a door must still be refused")

    # A DOOR OPENED TO THE INTERNET (DGO-2050): the HP's signer page, published on the public office.
    hp = {"office": "hp-laptop", "address": "10.79.6.2", "link_port": 9004, "label": "HP", "apps": [],
          "services": [{"app": "esign", "alias": "esign-public", "port": 8080, "paths": ["/s/"], "public": True}]}
    pentries, perrs = run({"remote": [hp]})
    if perrs or (pentries[0].get("services") or [{}])[0].get("paths") != ["/s/"] \
            or (pentries[0].get("services") or [{}])[0].get("public") is not True:
        problems.append(f"a door's paths and its office's consent must be kept: {perrs} {pentries}")
    if not run({"remote": [dict(hp, services=[dict(hp["services"][0], paths=["s"])])]})[1]:
        problems.append("a door path that is not a /prefix/ must be refused")
    if not run({"remote": [dict(hp, services=[dict(hp["services"][0], paths=["/s/../api/"])])]})[1]:
        problems.append("a door path with .. must be refused")
    hooks = {"remote": [dict(hp, services=[{"app": "n8n", "alias": "workflow-hooks", "port": 5678,
                                            "paths": ["/webhook/meet-recordings"]}])]}
    if run(hooks)[1]:
        problems.append("a door narrowed to a path with no trailing / (the serving office's own rule) must be "
                        "accepted, never stop the render")
    pub = {"host": "sign.staging.digital-office.co.il", "door": "esign-public.hp-laptop", "paths": ["/s/"]}
    dom = "staging.digital-office.co.il"
    published, puberrs, pubdrop = publish_plan({"publish": [pub]}, pentries, dom)
    if puberrs or pubdrop or len(published) != 1 or published[0]["url"] != "http://esign-public.hp-laptop:9004":
        problems.append(f"a narrowed, opened door under this office's domain must publish, at the door's alias "
                        f"and the link's port: {puberrs} {pubdrop} {published}")
    else:
        routed = render_published(published) or ""
        for must in ("Host(`sign.staging.digital-office.co.il`) && (PathPrefix(`/s/`))",
                     "certResolver: myresolver", "hsts@file", PUBLIC_HEADERS_MW,
                     "customFrameOptionsValue: SAMEORIGIN",
                     "referrerPolicy: no-referrer", PUBLIC_RATE_MW, PUBLIC_INFLIGHT_IP_MW, PUBLIC_INFLIGHT_MW,
                     "passHostHeader: false", "noop@internal", PUBLIC_HTTPS_MW):
            if must not in routed:
                problems.append(f"the published door's routes must carry {must!r}")
        for never in ("authentik", "X-authentik-username", "X-DGO-From"):
            if never in routed:
                problems.append(f"a published door must carry no sign-in and no identity, got {never!r}")
    # an exact path at the door is an exact path at the edge, and a narrower prefix inside the door's is allowed
    exact = run({"remote": [dict(hp, services=[dict(hp["services"][0], paths=["/s/", "/sign"])])]})[0]
    xs = publish_plan({"publish": [dict(pub, paths=["/sign", "/s/v/"])]}, exact, dom)[0]
    if len(xs) != 1 or "Path(`/sign`)" not in (render_published(xs) or "") \
            or "PathPrefix(`/s/v/`)" not in (render_published(xs) or ""):
        problems.append(f"an exact door path must be Path(), a narrower prefix PathPrefix(): {xs}")
    # THIS office's malformed declaration stops the render…
    for bad, why in (
            (dict(pub, host="sign.example.com"), "a host off this office's domain"),
            (dict(pub, host="sign.staging.digital-office.co.il:8443"), "a host with a port"),
            (dict(pub, door="esign-public"), "a door that names no office"),
            (dict(pub, paths=[]), "no paths at all"),
            (dict(pub, paths=["/"]), "the whole app"),
            (dict(pub, paths=["/s/../api/"]), "a path with ..")):
        if not publish_plan({"publish": [bad]}, pentries, dom)[1]:
            problems.append(f"publishing must refuse {why}")
    if not publish_plan({"publish": [pub, pub]}, pentries, dom)[1]:
        problems.append("publishing one host twice must be refused")
    if not publish_plan({"publish": [pub, dict(pub, host="sign2.staging.digital-office.co.il")]}, pentries, dom)[1]:
        problems.append("publishing one door on two hosts must be refused (one router name)")
    for one, two in (("c.a-b", "b-c.a"), ("x.o", "x-http.o"), ("x-http.o", "x.o")):
        pair = [dict(pub, door=one), dict(pub, door=two, host="sign2.staging.digital-office.co.il")]
        if not publish_plan({"publish": pair}, pentries, dom)[1]:
            problems.append(f"two doors whose routers share a name ({one}, {two}) must be refused")
    if not publish_plan({"publish": [pub]}, pentries, "localhost")[1]:
        problems.append("an office without a public domain must not publish")
    owned = {"console": {"routing": [{"host": "console"}]}, "esign": {"routing": [{"host": "esign", "port": 8080}]}}
    for taken_host in ("console.staging.digital-office.co.il", "esign.staging.digital-office.co.il",
                       "bina.macbook.console.staging.digital-office.co.il"):
        if not publish_plan({"publish": [dict(pub, host=taken_host)]}, pentries, dom, owned)[1]:
            problems.append(f"publishing on {taken_host}, a name this office already routes, must be refused")
    if publish_plan({"publish": [pub]}, pentries, dom, owned)[1]:
        problems.append("a free name (sign) must publish beside the office's own routed names")
    # …and what the SERVING office decided only leaves the door out, with a line, and never stops the render
    open_door = run({"remote": [dict(hp, services=[{"app": "esign", "alias": "esign-public", "port": 8080,
                                                    "public": True}])]})[0]
    unopened = run({"remote": [dict(hp, services=[dict(hp["services"][0], public=False)])]})[0]
    for served_now, why in ((open_door, "a door its office did not narrow"),
                            (unopened, "a door its office did not open to the internet"),
                            ([], "a door no office gives this one any more")):
        got = publish_plan({"publish": [pub]}, served_now, dom)
        if got[0] or got[1] or len(got[2]) != 1:
            problems.append(f"{why} must be left out with a line, never published and never a stop: {got}")
    got = publish_plan({"publish": [dict(pub, paths=["/api/"])]}, pentries, dom)
    if got[0] or got[1] or len(got[2]) != 1:
        problems.append(f"a path outside the door's own must be left out with a line: {got}")
    if publish_plan({}, pentries, dom) != ([], [], []) or render_published([]) is not None:
        problems.append("no publish: block must mean no file, no error and no line")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("serve.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
