"""dgo-extend.catalog — what an office SAYS about its own apps, and what a peer accepts it saying.

Why this exists (owner, 2026-10-01 16:20 — `ai/context/dgo-remote-apps.md`)
----------------------------------------------------------------------------
"Apps just run where they run." A linked office's apps must appear here — console, app manager, CLI
and API — without being installed, copied or enabled here. The ONE thing that has to cross the wire
for that is a description: which of my apps exist, what they are called, on which port the link
should reach them, and how a person opens them. That description is a **catalog**, and this module is
its whole vocabulary.

One source, and it is the compiler's
-----------------------------------
The catalog is a PROJECTION of `.generated/registry/office.apps.json` — the file layer 0 renders
from every enabled app's own `routing[]`/`capabilities[]` (`platform/manager/reconcile.py`). Nothing
here reads a manifest, a volume or another app: an app that is disabled disappears from the peer's
console in the same render that removes it from this one, and there is no second list of "our apps"
that can drift from the compiled one. The office's own name, label and commit come from the office
record; everything else comes from the registry.

Two directions, one file each
-----------------------------
* `build()` is the SERVING side: registry → the catalog this office publishes on the link.
* `parse()` is the CONSUMING side: a peer's catalog → what this office may show, with every refusal
  named. A catalog is written by another machine, so nothing in it is trusted: the office id, the
  aliases and the ports are validated here, and a bad one is refused with a sentence rather than
  rendered into a router.

The link's own control door
---------------------------
`dgo-extend` answers the catalog on the tunnel, and the consumer has to be able to read it BEFORE it
knows anything else about the peer. That makes the catalog a fact of the LINK and not of the office's
`serve:` list — an office that serves anything at all serves its own catalog. `with_control()` adds
that one entry, and the delivery plan, the firewall and the projection all agree about it because
they all call this function.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("dgo-extend.catalog")

#: The port a peer asks for this office's catalog on — the link's control door, on the tunnel. A
#: number on the wire (a peer dials it), which is why it stays what it was when it was also
#: dgo-extend's own port.
CATALOG_PORT = 8983
#: Where that door LEADS on the office network: dgo-extend's link listener, which serves the catalog
#: and nothing else. It used to lead to the app's own port, and a raw splice has no opinion about
#: paths — so a linked office reached this office's whole API through it, unauthenticated: declare
#: and converge offices, move apps, read the stored login of an installed office (found 2026-10-05,
#: reading the plan: `target: dgo-extend:8983`). What a peer may ask is now what this port serves.
LINK_PORT = 8984
#: The compiled registry artifact this module projects. Rendered by layer 0, read here.
REGISTRY_NAME = "office.apps.json"
#: The block in `platform.state.yaml` the projection writes, and the name it replaced (`serve:`,
#: still read as an alias for one release — see `platform/manager/serve.py`).
BLOCK = "remote"
LEGACY_BLOCK = "serve"
#: The office id rule, the same one `declaration.py` applies to `link.office`. Both rules end in `\Z`,
#: never `$`: Python's `$` also matches just BEFORE a trailing newline, so `^…$` accepted "macbook\n"
#: (DGO-615). Every reader here strips first; the rule must not depend on its caller doing so.
OFFICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")
#: A host label / tile alias: it becomes part of `<alias>.<office>.console.<domain>`.
ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}\Z")
#: An app id — the manifest schema's rule (`platform/schema/app.schema.json`). A published app's `app`
#: names a delivery target on the consuming side (`linkproxy._port`), so it is held to it (DGO-615).
APP_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")


def agent_service_ok(name) -> bool:
    """Who may answer an app's agent door (DGO-1018): a Docker service name (`linkproxy.SERVICE_RE`'s
    rule), and none of the link app's own. The door runs in the link's namespace with dgo-net and the
    carrier, so `localhost`, `dgo-net` or its container's `dgo-net-<deployment>` would deliver to the
    link itself, and `dgo-extend` (or `dgo-extend-<deployment>`) is the app that is never published to
    a peer (DGO-624). Nor the vault, `connections`: an agent door is a plain splice that writes no header, so
    it would hand a peer the vault's service-only routes past their relay gate (hos-001's second reader). One
    rule for the door (`linkproxy._serve_doors`), the catalog this office
    publishes (`build`) and the catalog a peer is refused for (`validate`): a name one of them took and
    another refused took the whole catalog down (the second reader of DGO-1018)."""
    return (isinstance(name, str) and bool(re.match(r"^[a-z][a-z0-9-]{1,62}\Z", name))
            and not re.match(r"^(localhost|dgo-net|dgo-extend|connections)(-.*)?\Z", name))
#: A user the link's door writes into a header — the rule `platform/manager/serve.py`'s HEADER_RE holds.
HEADER_RE = re.compile(r"^[A-Za-z0-9@._+\-]{1,128}\Z")
#: The authority an app answers under — `platform/manager/serve.py`'s AUTHORITY_RE. A re-shared app's
#: is written into `Host:` by the door in the middle (`catalog.reshare`, `link-proxy.Door._table`).
AUTHORITY_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251})?(:\d{1,5})?\Z")
#: This app. Its catalog door is part of every link (`with_control`); the app ITSELF — offices, links,
#: `serve:`, pairing, the stored logins of installed offices — is never published to a peer (DGO-624).
SELF = "dgo-extend"
#: A cache-control fact, not a policy: how long a fetched catalog is trusted for rendering.
FETCH_TTL = 300


class CatalogError(RuntimeError):
    """One refusal, with the field named. Raised on the consuming side; collected by parse()."""


def registry_path(base: str | Path) -> Path:
    return Path(base) / REGISTRY_NAME


def load_registry(base: str | Path) -> dict:
    """The compiled registry, or `{}` when the office has not rendered one yet.

    An unreadable/missing registry is an EMPTY catalog, never an exception: a peer asking a
    half-built office gets "no apps", which is exactly what that office has, and the screen can say
    so. A malformed one is reported the same way for the same reason.
    """
    try:
        doc = json.loads(registry_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _title(name: str, name_en: str = "") -> dict:
    out = {"he": name or ""}
    if name_en:
        out["en"] = name_en
    return out


def build(registry: dict, office: str, label=None, commit: str = "", exclude=(),
          now: int | None = None, link_port: int = 0, mark: dict | None = None,
          services: list | None = None, herd: str = "") -> dict:
    """The catalog this office publishes: registry rows → the contract's shape.

    `exclude` is the serving office's own `serve.exclude` — the owner's "not this app". It is applied
    HERE, on the serving side, because that is where the app exists and where the decision belongs:
    a peer cannot be trusted to hide what this office chose not to publish, and the consuming side
    would otherwise render a tile for something it is not allowed to reach.
    """
    skip = {str(x).strip().lower() for x in (exclude or []) if str(x).strip()}
    label = label or {}
    apps = []
    for row in (registry.get("apps") or []):
        if not isinstance(row, dict):
            continue
        alias = str(row.get("alias") or "").strip().lower()
        if not ALIAS_RE.match(alias):
            continue
        if alias in skip or str(row.get("app") or "").strip().lower() in skip:
            continue
        try:
            port = int(row.get("port"))
        except (TypeError, ValueError):
            continue
        if not 1 <= port <= 65535:
            continue
        entry = {
            "alias": alias,
            "app": str(row.get("app") or alias),
            "title": _title(str(row.get("name") or alias), str(row.get("name_en") or "")),
            "icon": str(row.get("icon") or "external"),
            "group": str(row.get("group") or "מרוחק"),
            "desc": str(row.get("desc") or ""),
            "order": row.get("order", 900),
            "port": port,
            "module": {"kind": str((row.get("module") or {}).get("kind") or "embedded"),
                       "path": str((row.get("module") or {}).get("path") or f"/a/{alias}/"),
                       # The MODULE ID crosses too: a link is written `#/m/<module id>/…`, and the
                       # consuming plan (serve.plan) falls back to the app id when it is missing —
                       # which differs for six apps (bina-ds is `bina`, indox is `incoming`, …), so a
                       # deep link to one of them landed on no tile (DGO-602).
                       **({"id": str(row["module"]["id"])}
                          if isinstance(row.get("module"), dict) and row["module"].get("id") else {})},
            "health": str(row.get("health") or "/healthz"),
        }
        # The authority the serving app EXPECTS to be reached under (its own SSO host). It crosses
        # the link because the consuming edge has to write it as the Host header: every harness here
        # refuses an authority it was never told about (DGO-32, measured), and the nested console
        # host is not its name.
        if row.get("host"):
            entry["host"] = str(row["host"])
        # The name to CONNECT to on the serving office's network (DGO-38): the compose service, which
        # is not the app id for every app (`indox` → `incoming-documents`, `mail` → `mailview`).
        # Additive on purpose — a peer that predates it falls back to the app id and keeps working.
        if row.get("service"):
            entry["service"] = str(row["service"])
        # A second door in the same container (`agent_api_port`, DGO-32): the adapter a CLI speaks to.
        try:
            api_port = int(row.get("agent_api_port"))
        except (TypeError, ValueError):
            api_port = 0
        if 1 <= api_port <= 65535 and api_port != port:
            entry["api"] = {"port": api_port,
                            "auth": str(row.get("auth") or f"bearer:vault:{entry['app']}")}
            # WHO answers it on the serving office's network (DGO-1018): not always the UI's service —
            # browser42's API is its task runner. Additive, like `service`: an office that renders the
            # serving half of a pair from this catalog (`converge._remote_delivery`) delivers there.
            # Only a name the door itself takes: for any other it delivers to the UI's service, and a
            # peer's `validate` would refuse the whole catalog for it — every tile of this office gone.
            if agent_service_ok(row.get("agent_api_service")):
                entry["api"]["service"] = row["agent_api_service"]
            elif row.get("agent_api_service"):
                log.warning("catalog: %s's agent door names %r, which is no service a door delivers to — "
                            "published without it, so its UI's service answers (DGO-1018)",
                            entry["app"], row.get("agent_api_service"))
        # The identity a request should BECOME when it arrives on the serving office. Only that
        # office knows its own user vocabulary, so the mapping is published here and applied by the
        # consuming office's edge.
        ident = row.get("identity") or {}
        if isinstance(ident, dict) and ident.get("to"):
            # DGO-622: a user stored before it was checked ("owner\n") is never published — the door writes it into a header.
            to = str(ident["to"])
            given = ident.get("from") or []
            names = [str(u) for u in (given if isinstance(given, list) else [given]) if u]
            if not HEADER_RE.match(to):
                log.warning("%s: the mapped user %r is not a header value — published with no identity; "
                            "declare it again (`serve`) to restore it", alias, to)
            else:
                entry["identity"] = {"to": to}
                kept = [u for u in names if HEADER_RE.match(u)]
                if len(kept) != len(names):
                    log.warning("%s: %d name(s) of identity.from are not header values — left out",
                                alias, len(names) - len(kept))
                if kept:
                    entry["identity"]["from"] = kept
        apps.append(entry)
    apps.sort(key=lambda a: (a.get("order", 900), a["alias"]))
    out = {
        "office": str(office or ""),
        "label": {"he": str(label.get("he") or office or ""),
                  "en": str(label.get("en") or label.get("he") or office or "")},
        "commit": str(commit or ""),
        "generated_at": int(now if now is not None else time.time()),
        "apps": apps,
    }
    # The DOORS WITH NO TILE this office gives (DGO-945, `publishable_services`): a key of their own,
    # so a consuming office on code from before it ignores them rather than drawing them as tiles.
    # A door on the alias of an app this catalog publishes is left out HERE: the consuming office
    # refuses a clash, and it refuses the whole catalog for it (`validate`), every tile with it.
    taken = {str(a.get("alias") or "").lower() for a in apps}
    doors = [dict(s) for s in (services or []) if str(s.get("alias") or "").lower() not in taken]
    if doors:
        out["services"] = doors
    # The LINK DOOR's port (DGO-32): one listener per link, with the Host header picking the app
    # behind it, because this office's own registry has four apps on 8080. It is published HERE and
    # not derived by the consumer: the end that owns the door is the end that names it. Zero when the
    # office is not part of a pair yet — a door with no tunnel has no port to answer on.
    if link_port:
        out["link"] = {"port": int(link_port)}
    # The HERD this office belongs to (DGO-1003, `DGO_HERD`): the office says it about itself, and the
    # consuming office groups its linked offices by it. Additive — none is published as none.
    if herd:
        out["herd"] = str(herd)
    # The office's MARK — a colour NAME and an animal NAME, never a hex (flt-004): the consuming
    # office draws a linked office's tile with its OWN palette entry for that name, so no value ever
    # crosses a machine boundary. `mark` is this office's choice (its identity, flt-001); absent, the
    # name it publishes itself under decides — an office is never published blank.
    import identity as _identity
    out["mark"] = _identity.clean_mark(mark) or _identity.mark_for(str(office or ""))
    return out


def validate(payload: dict, expect_office: str = "") -> list[str]:
    """Every way a PEER's catalog may be wrong, as sentences. Empty list = usable."""
    errs: list[str] = []
    if not isinstance(payload, dict):
        return ["הקטלוג שהתקבל אינו אובייקט JSON"]
    raw_office = str(payload.get("office") or "").strip()
    oid = raw_office.lower()
    if not OFFICE_RE.match(raw_office):
        errs.append(f"catalog.office {payload.get('office')!r} אינו מזהה לשכה תקין")
    elif expect_office and oid != expect_office.strip().lower():
        # A catalog that names a different office than the link does is a link to somewhere else —
        # rendering it would put another office's apps under this office's name.
        errs.append(f"catalog.office {oid!r} אינו הלשכה שאליה הקישור ({expect_office})")
    # The office's mark, when the peer publishes one: a colour and an animal from the closed
    # vocabularies a screen can draw (flt-004). Refused HERE, with the pair named, because a tile
    # rendered from an unknown name is a blank tile — a defect nobody traces back to the other
    # machine's typo. Absent is fine: an office older than marks publishes none and is drawn plainly.
    if payload.get("mark") is not None:
        import identity as _identity
        if not _identity.clean_mark(payload.get("mark")):
            errs.append(f"catalog.mark {payload.get('mark')!r} אינו זוג צבע/חיה מהמאגר "
                        f"(צבע: {', '.join(_identity.OFFICE_HUES)} · חיה: "
                        f"{', '.join(_identity.OFFICE_ANIMALS)})")
    apps = payload.get("apps")
    if not isinstance(apps, list):
        return errs + ["catalog.apps חייב להיות רשימה"]
    seen: dict[str, int] = {}
    for i, app in enumerate(apps):
        where = f"catalog.apps[{i}]"
        if not isinstance(app, dict):
            errs.append(f"{where} חייב להיות אובייקט")
            continue
        # Validated AS WRITTEN, then compared case-folded: a catalogue is another machine's
        # output, and a label that only becomes valid after we lowercase it is a name that will
        # reach a router differently than it left the peer.
        raw_alias = str(app.get("alias") or "").strip()
        if not ALIAS_RE.match(raw_alias):
            errs.append(f"{where}.alias {app.get('alias')!r} אינו תווית מארח תקינה")
            continue
        alias = raw_alias.lower()
        where = f"{where} ({alias})"
        if alias in seen:
            errs.append(f"{where}.alias '{alias}' מופיע פעמיים בקטלוג")
            continue
        try:
            port = int(app.get("port"))
        except (TypeError, ValueError):
            errs.append(f"{where}.port חייב להיות מספר — הפורט שהלשכה המרוחקת מאזינה עליו")
            continue
        if not 1 <= port <= 65535:
            errs.append(f"{where}.port {port} מחוץ לטווח")
            continue
        api = app.get("api") or {}
        if api and not isinstance(api, dict):
            errs.append(f"{where}.api חייב להיות אובייקט (port, auth)")
            continue
        if isinstance(api, dict) and api.get("port") not in (None, ""):
            try:
                api_port = int(api["port"])
            except (TypeError, ValueError):
                errs.append(f"{where}.api.port חייב להיות מספר")
                continue
            if not 1 <= api_port <= 65535 or api_port == port:
                errs.append(f"{where}.api.port חייב להיות פורט אחר, בטווח")
                continue
        # DGO-1018: `api.service` names a delivery target in the office that renders this one's serving
        # half (`converge._remote_delivery`), so it is checked as written, like the app id (DGO-615),
        # by the door's own rule (`agent_service_ok`).
        if isinstance(api, dict) and api.get("service") not in (None, ""):
            svc = api.get("service")
            if not agent_service_ok(svc):
                errs.append(f"{where}.api.service {svc!r} אינו שם שירות תקין")
                continue
        bad = _shape_error(app)
        if bad:
            errs.append(f"{where}.{bad}")
            continue
        # DGO-615: the APP id names a delivery target here (linkproxy._port), so it is checked as written, like the alias.
        if app.get("app") is not None and not APP_ID_RE.match(app["app"]):
            errs.append(f"{where}.app {app.get('app')!r} אינו מזהה אפליקציה תקין")
            continue
        seen[alias] = port
    # …and its doors with no tile (DGO-945), held to the same names and ports, and to their paths
    doors = payload.get("services")
    if doors is not None and not isinstance(doors, list):
        return errs + ["catalog.services חייב להיות רשימה"]
    for i, door in enumerate(doors or []):
        where = f"catalog.services[{i}]"
        if not isinstance(door, dict):
            errs.append(f"{where} חייב להיות אובייקט")
            continue
        raw_alias = str(door.get("alias") or "").strip()
        if not ALIAS_RE.match(raw_alias) or raw_alias.lower() in seen:
            errs.append(f"{where}.alias {door.get('alias')!r} אינו תווית תקינה, או שהוא שם של אפליקציה")
            continue
        if not APP_ID_RE.match(str(door.get("app") or "")):
            errs.append(f"{where}.app {door.get('app')!r} אינו מזהה אפליקציה תקין")
            continue
        try:
            port = int(door.get("port"))
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            errs.append(f"{where}.port {door.get('port')!r} אינו פורט בטווח")
            continue
        paths = door.get("paths")
        if paths is not None and (not isinstance(paths, list) or not paths or not all(plain_path(p) for p in paths)):
            errs.append(f"{where}.paths {paths!r}: רשימה של נתיבים מוחלטים בלבד")
            continue
        seen[raw_alias.lower()] = port
    return errs


#: The fields of a published app that the CONSUMING office copies into its own state (projection →
#: the `remote:` block → serve.plan → the edge), with the shape the contract gives each. A peer's
#: catalog is another machine's output: a block nested a few hundred levels deep in `order`, `module`
#: or `title` was copied verbatim until it crashed the state writer, and once written, every reader of
#: the state file (RecursionError) — so render could not run (DGO-619). Refused here, by field.
_STR_FIELDS = ("app", "icon", "group", "desc", "health", "host")
_MAX_TEXT = 512


def _short_text(v) -> bool:
    return isinstance(v, str) and len(v) <= _MAX_TEXT


def _shape_error(app: dict) -> str:
    """The first field of a peer's app entry that is not the contract's shape, as `field: why`."""
    for k in _STR_FIELDS:
        if app.get(k) is not None and not _short_text(app.get(k)):
            return f"{k} חייב להיות מחרוזת (עד {_MAX_TEXT} תווים)"
    title = app.get("title")
    if title is not None and (not isinstance(title, dict)
                              or not all(_short_text(t) for t in title.values())):
        return "title חייב להיות אובייקט של מחרוזות (he, en)"
    order = app.get("order")
    if order is not None and (isinstance(order, bool) or not isinstance(order, int)
                              or abs(order) > 10 ** 6):
        return "order חייב להיות מספר שלם"
    module = app.get("module")
    if module is not None:
        if not isinstance(module, dict):
            return "module חייב להיות אובייקט"
        for k, v in module.items():
            # one level of object is the most the contract has (`route: {mode: …}`, DGO-569)
            if not (_short_text(v) or (isinstance(v, dict) and all(_short_text(x) for x in v.values()))):
                return f"module.{k} חייב להיות מחרוזת (או אובייקט של מחרוזות)"
    ident = app.get("identity")
    if ident is not None:
        if not isinstance(ident, dict):
            return "identity חייב להיות אובייקט (to, from)"
        if ident.get("to") is not None and not _short_text(ident.get("to")):
            return "identity.to חייב להיות מחרוזת"
        frm = ident.get("from")
        if frm is not None and not (_short_text(frm) or (isinstance(frm, list)
                                                         and all(_short_text(u) for u in frm))):
            return "identity.from חייב להיות מחרוזת או רשימת מחרוזות"
    return ""


def parse(payload: dict, expect_office: str = "") -> dict:
    """The peer's catalog, validated, or a `CatalogError` naming the field."""
    errs = validate(payload, expect_office)
    if errs:
        raise CatalogError("; ".join(errs))
    return payload


# ── the serving office's own `serve:` map ─────────────────────────────────────────────────────────
#: The keys of a `serve:` map that are metadata of the declaration and never an app.
RESERVED = ("exclude", "only", "label", "identity", "shared", "services")


def app_specs(serve_map) -> dict:
    """The app entries of a `serve:` map, with the metadata keys dropped.

    `serve:` is `{app: {port}}` plus its reserved keys (`RESERVED`): `exclude`, the aliases this
    office publishes to nobody, and `only`, what ONE linked office is given when it is given less
    than the rest. Every consumer of the map (the firewall, the delivery plan, the tunnel) wants the
    apps; only the catalog wants the other two, so the split lives here and every reader calls it,
    instead of five loops each having to remember the reserved keys.
    """
    if not isinstance(serve_map, dict):
        return {}
    return {k: v for k, v in serve_map.items() if k not in RESERVED}


def withheld_by_only(serve_map, rows: list) -> dict:
    """{office: [app…]}: the apps `serve:` names that an office narrowed by `serve.only` is NOT given.

    `only` is an allow-list, so an app served after it was written reaches every linked office but
    those — silently: vps1 was given bina, plane and browser42 from the HP, and Bina Claude, enabled
    and served there later, opened on the owner's phone as «אין מסך בשם הזה» (DGO-1269). Widening a
    public server's list is the owner's decision, so it is SAID — in the answer of the call that
    serves the app — never done. An app counts as given when its id or any of its tiles' aliases
    (`rows`, the registry) is on the list.
    """
    only = (serve_map or {}).get("only") if isinstance(serve_map, dict) else None
    if not isinstance(only, dict):
        return {}
    aliases: dict = {}
    for r in rows or []:
        if isinstance(r, dict):
            aliases.setdefault(str(r.get("app")).strip().lower(), set()).add(str(r.get("alias")).strip().lower())
    out = {}
    for office in only:
        # read as the door reads it (`only_for`): one name or a list, lower-cased, keys as written
        try:
            given = only_for(serve_map, str(office))
        except TypeError:                      # a value that is neither a name nor a list
            continue
        if given is None:
            continue
        held = [app for app in app_specs(serve_map)
                if app != WILDCARD and app.strip().lower() not in given
                and not (aliases.get(app.strip().lower(), set()) & given)]
        if held:
            out[str(office).strip().lower()] = sorted(held)
    return out


def tile_spec(specs: dict, row: dict, rows: list) -> dict:
    """The `serve:` entry that applies to ONE published tile (`row`, of the registry `rows`).

    The app's entry first, the tile's own (its alias) after it — as every reader has asked. But an
    entry keyed by the APP names one port, and an app with two tiles listens on two (bina-claude: the
    desktop on 3000, its terminal on 7681): read whole, that one port went to every tile, and vps1 was
    offered claude-terminal on 3000, the desktop's (DGO-1269). So the app's PORT is a tile's only when
    the app has one tile or the tile carries the app's own name; another tile of it takes its own
    entry's port, or keeps the registry's — where its service listens. Its `host` likewise: the
    serving door keys its routes by host, so the app's authority on a second tile would route the
    first tile's host to the second tile's port.

    `rows` is the office's WHOLE registry, never a list `serve.only` already narrowed: vps1 given only
    `claude-terminal` sees one tile of bina-claude, and that one tile would take the desktop's port
    again (the second reader).
    """
    app, alias = str(row.get("app")), str(row.get("alias"))
    by_app = specs.get(app)
    spec = by_app or specs.get(alias) or {}
    if not isinstance(spec, dict):
        spec = {"port": spec}
    tiles = sum(1 for r in rows if isinstance(r, dict) and str(r.get("app")) == app)
    if by_app and tiles > 1 and alias != app:
        own = specs.get(alias) if isinstance(specs.get(alias), dict) else {}
        spec = {k: v for k, v in spec.items() if k not in ("port", "host")}
        for key in ("port", "host"):
            if key in own and (key == "host" or own.get(key)):
                spec[key] = own[key]
    return spec


def excluded(serve_map) -> list[str]:
    if not isinstance(serve_map, dict):
        return []
    value = serve_map.get("exclude")
    if isinstance(value, str):
        value = [value]
    return [str(x) for x in (value or [])]


def only_for(serve_map, office: str = "") -> set | None:
    """What ONE linked office is given, when it is given less than the rest: `serve.only`.

        serve: {"*": {}, "only": {"vps1": ["plane"]}}

    `None` — that office is not named there (or nobody asked on an office's behalf): it is given what
    `serve:` says. A set — exactly those apps, by alias or app id; an EMPTY set is a statement too:
    linked, and given nothing. The owner's own model of extending an office starts with choosing
    which apps to give, per office; one list for all meant that pairing with a public server either
    handed it the machine and the vault, or took the drive away from the office at home.
    """
    table = serve_map.get("only") if isinstance(serve_map, dict) else None
    key = str(office or "").strip().lower()
    if not isinstance(table, dict) or not key or key not in table:
        return None
    names = table[key]
    if isinstance(names, str):
        names = [names]
    return {str(x).strip().lower() for x in (names or []) if str(x).strip()}


# ── re-sharing: the apps OTHER offices gave this one (`serve.shared`, 2026-10-19) ──────────────────
# The owner's words: "option if ext shares also apps that shared with me or only dgos applications".
# A link is point-to-point and stays so — peer→peer packets are dropped by every tunnel's firewall —
# so an office two links away (claude-cloud → vps1 → hp-laptop) is reached at the APPLICATION layer:
# the office in the middle serves, on its own door, an app it USES, by handing the request to its own
# door for the office that runs it. Nothing about the tunnel, the firewall or the origin changes, and
# the origin still decides what it gives the office in the middle; that office decides whether to
# hand it on, and to whom.
#
# What crosses: a `shared` section per origin in the catalog this office publishes — additive, so an
# office that predates it reads its peer's own apps and nothing else. ONE HOP by construction: a
# section is built from what the origin published as ITS OWN apps (`apps`), never from what it
# re-shared, so no chain and no loop can form, whatever every office declares.
def shared_for(serve_map) -> set:
    """The origins whose apps this office re-shares — `{"*"}` for every origin; empty = nothing.

        serve: {"*": {}, "shared": "*"}                  # what every linked office gave this one
        serve: {"*": {}, "shared": ["hp-laptop"]}        # what those offices gave it

    Absent — the default — re-shares nothing: handing on what another office gave is a decision,
    never a side effect of `"*"`. Narrower than an origin is `serve.only[<office>]` by
    `<alias>.<origin>`, and this office's own "hide it here".

    Two forms, and only these two: an office that drives this one's far plan and predates `shared`
    reads it as an app (`linkproxy.ports_of`) — a string or a list has no second port and passes, a
    map has none at all and refuses the plan, which leaves the far end on a stale one (second reader,
    2026-10-19). Anything else re-shares nothing.
    """
    raw = serve_map.get("shared") if isinstance(serve_map, dict) else None
    if raw == WILDCARD:
        return {WILDCARD}
    if isinstance(raw, list):
        return {str(o).strip().lower() for o in raw if isinstance(o, str) and o.strip()}
    return set()


#: An office id that is also an authority: `<alias>.localhost` is an OWN app's name at every door (and
#: the door's one two-label fallback, link-proxy `route`), so an office called that is never handed on.
NOT_AN_ORIGIN = ("localhost",)


def shared_host(alias: str, origin: str) -> str:
    """The ONE name a re-shared app answers under at the door of the office in the middle — the same
    `<alias>.<office>` this office's own edge already resolves it by, which no app of its own can
    carry (an office id is never a domain), so it cannot shadow one."""
    return f"{alias}.{origin}"


def reshare(serve_map, office: str, home_id: str, fetched: dict, doors: dict,
            hidden: dict | None = None) -> list[dict]:
    """The `shared` sections this office publishes to `office`. Pure.

    `fetched` — `{origin: catalog}` as this office pulled them (what each origin GAVE it); `doors` —
    `{origin: port}`, this office's own door to that origin (`linkproxy.door_port` of the pair, read
    off the plan): an origin with no door here is not linked, and nothing of it is handed on; `hidden`
    — this office's own "hide it here" (`projection.load_exclude`): what it does not show itself, it
    does not hand on either.

    Never to the origin itself (an office is not handed its own apps back), never this app (its own
    door is the link's control door), never an origin's `api` (an agent door is a PORT, and only the
    origin's own pair carries one), never its `identity` (who the request becomes there is the
    ORIGIN's mapping of this office, written by the origin's door), and `serve.only[office]` narrows
    it by `<alias>.<origin>`.

    Only an app that names its AUTHORITY is handed on. `host: ""` says the app trusts the consuming
    office's own authority and wants the browser's Host passed through (`converge._serve_block`) —
    an authority the office in the middle cannot pass on, because the browser is not its own.
    """
    allow = shared_for(serve_map)
    if not allow:
        return []
    asking = str(office or "").strip().lower()
    only = only_for(serve_map, asking)
    hide = {str(o): {str(a) for a in (v or [])} for o, v in (hidden or {}).items()}
    out = []
    for origin in sorted(fetched or {}):
        doc = fetched[origin]
        oid = str(origin or "").strip().lower()
        if not isinstance(doc, dict) or not OFFICE_RE.match(oid) or oid in NOT_AN_ORIGIN:
            continue
        if oid in (asking, str(home_id or "").strip().lower()):
            continue
        if WILDCARD not in allow and oid not in allow:
            continue
        try:
            port = int((doors or {}).get(oid) or 0)
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            continue
        rows = []
        for app in doc.get("apps") or []:
            if not isinstance(app, dict):
                continue
            alias = str(app.get("alias") or "").strip().lower()
            aid = str(app.get("app") or alias).strip().lower()
            if not ALIAS_RE.match(alias) or SELF in (alias, aid):
                continue
            if alias in hide.get(oid, set()):
                continue
            origin_host = str(app.get("host") or "").strip().lower()
            if not AUTHORITY_RE.match(origin_host):
                continue
            host = shared_host(alias, oid)
            if only is not None and host not in only:
                continue
            row = {k: app[k] for k in ("app", "title", "icon", "group", "desc", "order", "module",
                                       "health") if k in app}
            row.update({"alias": alias, "port": port, "host": host,
                        # WHAT the door here connects to: its own name for that app — the alias this
                        # office's edge already routes by, on the link proxy that holds the door to
                        # the origin. The authority the ORIGIN expects travels beside it, and the
                        # door here writes it (`origin_host`): to the origin, the request is the one
                        # this office's own edge would have sent.
                        "service": host, "origin_host": origin_host})
            rows.append(row)
        if rows:
            out.append({"office": oid,
                        "label": doc.get("label") or {"he": oid, "en": oid},
                        "commit": str(doc.get("commit") or ""),
                        "generated_at": _stamp(doc.get("generated_at")),
                        **({"mark": doc["mark"]} if doc.get("mark") else {}),
                        "apps": rows})
    return out


def _stamp(value) -> int:
    """A catalog's `generated_at` as a number — 0 when it is not one (`validate` does not hold it)."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):     # `Infinity` is valid JSON to json.loads
        return 0


def shared_sections(payload: dict, home_id: str = "") -> tuple[list[dict], list[str]]:
    """The `shared` sections of a PEER's catalog this office may use, and what was dropped and why.

    Per section, not all-or-nothing: a bad section is another office's mistake about a third one, and
    it must not take the peer's own apps off this console. A section is dropped when it names the
    peer itself or THIS office (an office is never handed its own apps back), when its apps do not
    validate as a catalog, when an app's host is not `<alias>.<origin>` — the only name the peer's
    door answers it under — or when a field the compiler would refuse for the WHOLE `remote:` block
    (`label`) or a stamp the projection reads as a number (`generated_at`) is not what it must be, or
    its `commit` is not text.

    What is kept is what `reshare` promises, enforced here and not believed: an app's `api` and
    `identity` are removed. An agent port is the origin's own pair's (through the peer it would be a
    port of the PEER's), and the identity is the origin's door's to write.
    """
    via = str((payload or {}).get("office") or "").strip().lower()
    raw = (payload or {}).get("shared")
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list):
        return [], [f"{via}: catalog.shared חייב להיות רשימה"]
    keep, errs, seen = [], [], set()
    me = str(home_id or "").strip().lower()
    for i, sec in enumerate(raw):
        where = f"{via}: catalog.shared[{i}]"
        if not isinstance(sec, dict):
            errs.append(f"{where} חייב להיות אובייקט")
            continue
        oid = str(sec.get("office") or "").strip()
        if not OFFICE_RE.match(oid):
            errs.append(f"{where}.office {sec.get('office')!r} אינו מזהה לשכה תקין")
            continue
        if oid in (via, me) or oid in seen or oid in NOT_AN_ORIGIN:
            errs.append(f"{where}.office {oid}: לשכה לא מקבלת דרך אחרת את עצמה, ולא פעמיים")
            continue
        label = sec.get("label")
        if not (label in (None, "") or isinstance(label, str) or (
                isinstance(label, dict) and all(isinstance(v, str) for v in label.values()))):
            errs.append(f"{where} ({oid}).label חייב להיות מחרוזת או אובייקט (he, en)")
            continue
        if not isinstance(sec.get("generated_at", 0), int) or isinstance(sec.get("generated_at"), bool) \
                or not isinstance(sec.get("commit", ""), str):
            errs.append(f"{where} ({oid}): generated_at חייב להיות מספר ו-commit מחרוזת")
            continue
        bad = validate({"office": oid, "apps": sec.get("apps"),
                        **({"mark": sec["mark"]} if sec.get("mark") is not None else {})}, oid)
        if bad:
            errs.append(f"{where} ({oid}): " + "; ".join(bad))
            continue
        wrong = [a.get("alias") for a in sec["apps"]
                 if str(a.get("host") or "").lower() != shared_host(str(a.get("alias") or "").lower(), oid)]
        if wrong:
            errs.append(f"{where} ({oid}): host של {wrong} אינו <alias>.{oid}")
            continue
        seen.add(oid)
        # …and never a door with no tile (DGO-945): `reshare` hands on apps alone, so a `services` list
        # here is not the origin's word — kept, it pointed this office's calls to the origin's
        # capability at the office in the middle, and one bad door refused the whole `remote:` block.
        keep.append({**{k: v for k, v in sec.items() if k != "services"},
                     "apps": [{k: v for k, v in a.items() if k not in ("api", "identity")}
                              for a in sec["apps"]]})
    return keep, errs


def with_control(serve_map, port: int = CATALOG_PORT) -> dict:
    """The `serve:` map plus the link's own control door — this app's catalog port.

    A peer that may arrive at ANY of this office's apps must be able to read the catalog first: that
    is how it learns which apps to render, and it can know nothing else about this office before
    that answer. So the catalog port is not something an office declares; it is part of what a link
    IS. Added here rather than in each of the three renderers (firewall, delivery plan, projection)
    so they cannot disagree — and idempotent, so an office that declared it anyway is unchanged.

    The WILDCARD is dropped, and that is the second half of the same rule: `{"*": {}}` is not an app
    with no port — it is "every app this office has" (`publishable`, which holds the registry and can
    enumerate them). A port map cannot enumerate them, so the key stays out of every map built here.
    Left in, it refused the whole delivery plan (`ל„*” אין פורט מספרי בהצהרת ה-serve`) and the far
    office kept a plan days old — measured 2026-10-06 on this MacBook, whose own `serve:` carries
    `"*": {}` beside `bina-ds`.
    """
    out = dict(app_specs(serve_map))
    # The wildcard is not an app (it cannot carry a port); "every app" still means "and the catalog,
    # always" — the door the peer reads first, before it knows which apps exist.
    wildcard_served = WILDCARD in out
    out.pop(WILDCARD, None)
    # …and an office that serves only DOORS (`serve.services`, DGO-945) serves something too: its
    # doors are behind the same link door, which needs the catalog to be read first
    doors = isinstance(serve_map, dict) and bool(serve_map.get("services"))
    if not out and not wildcard_served and not doors:
        return out
    out.setdefault("dgo-extend", {"port": int(port)})
    return out


#: The wildcard app of a `serve:` map: "every app this office has, minus `exclude`" (DGO-32). The
#: owner's own words for it were "all apps appear", and a list of twelve app ids maintained by hand
#: is a list that is wrong the day an app is installed — so the map may say ONE thing instead.
WILDCARD = "*"


def wildcard(serve_map) -> bool:
    """Does this `serve:` map mean "every app"? A key, not a value: `{"*": {}}`."""
    return bool(isinstance(serve_map, dict) and WILDCARD in serve_map)


def publishable(registry: dict, serve_map, office: str = "") -> dict:
    """The part of the compiled registry this office actually PUBLISHES on a link (DGO-32) — to
    `office` when one is named: `only_for` narrows it for that office alone.

    The catalog used to be every enabled app in the registry, while the delivery plan opened a door
    only for the served ones — so a linked office rendered tiles that could not open. Measured on vps1
    2026-10-02: its registry holds 21 apps, its `serve:` names none, and the MacBook projected eight
    tiles of apps no door reached.

    The rule is therefore one-directional and lives here, next to `exclude`, because both are the
    SERVING office's decision about what a peer may see:

    * `serve: {}` — publishes NOTHING (the link still carries the control door: a peer must be able to
      read the catalog to learn that the office serves nothing).
    * `serve: {"drive": {...}}` — publishes exactly `drive`, matched by app id OR by alias, because
      both are names a person writes and only one of them is the app's own id.
    * `serve: {"*": {}}` — publishes every app, minus `exclude`.

    Never THIS app (`SELF`), however `serve:` names it: through the door its API is this office's
    offices, links, `serve:` and pairing, and its catalog already reaches the peer on the link's own
    control door (`with_control`).

    A name in `serve:` that the registry does not hold is NOT invented here: it produces no row, and
    the office's own `serve:` validation/`link` step is where a name nobody runs is refused.
    """
    apps = app_specs(serve_map)
    if not apps:
        return {k: v for k, v in (registry or {}).items() if k != "apps"} | {"apps": []}
    skip = {str(x).strip().lower() for x in excluded(serve_map) if str(x).strip()}
    every = wildcard(serve_map)
    named = {str(k).strip().lower() for k in apps}
    only = only_for(serve_map, office)
    rows = []
    for row in ((registry or {}).get("apps") or []):
        if not isinstance(row, dict):
            continue
        app = str(row.get("app") or "").strip().lower()
        alias = str(row.get("alias") or "").strip().lower()
        if skip & {app, alias}:
            continue
        if SELF in (app, alias):
            continue                 # DGO-624: this app is never published — `*` and a named key alike; its catalog door is the link's
        if not every and not (named & {app, alias}):
            continue
        if only is not None and not (only & {app, alias}):
            continue                 # served by this office, and not to THIS one
        rows.append(dict(row))
    return {k: v for k, v in (registry or {}).items() if k != "apps"} | {"apps": rows}


#: A door's path allow-list (DGO-945): absolute, plain path segments only — no `.`/`..`, no escapes.
#: Each repeat ENDS at its slash, so no string can be split two ways: `(?:[…]+/?)*` nested a repeat in
#: a repeat and took 0.5 s on 24 characters, doubling with each one more (second reader, DGO-945).
PATH_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]*\Z")


def plain_path(p) -> bool:
    """Is `p` a path a door may be narrowed to — absolute, no dot segment, nothing escaped?"""
    return isinstance(p, str) and bool(PATH_RE.match(p)) and "/../" not in f"{p}/" and "/./" not in f"{p}/"


def clean_services(value) -> tuple[dict, str]:
    """`serve.services` as it is stored — alias → `{to, paths}` — or the reason it is not one.

    The one rule for both writers (the screen's `PUT /api/link/serve` and `converge.set_home_serve`):
    an alias, the offices it is given to, and the paths it answers. Anything else is refused rather
    than kept, because a key nobody reads is a declaration nobody enforces."""
    if not isinstance(value, dict):
        return {}, "serve.services חייב להיות מפה של כינוי → {to, paths}"
    out = {}
    for alias, spec in value.items():
        a = str(alias).strip().lower()
        if not ALIAS_RE.match(a):
            return {}, f"serve.services: {alias!r} אינו כינוי תקין"
        spec = {} if spec in (None, "") else spec
        if not isinstance(spec, dict) or set(spec) - {"to", "paths"}:
            return {}, f"serve.services.{a} הוא אובייקט עם to ו/או paths בלבד"
        entry = {}
        if "to" in spec:
            names = [spec["to"]] if isinstance(spec["to"], str) else spec["to"]
            if not isinstance(names, list) or not all(isinstance(o, str) and OFFICE_RE.match(o.strip().lower())
                                                      for o in names):
                return {}, f"serve.services.{a}.to: רשימה של מזהי לשכות"
            entry["to"] = [o.strip().lower() for o in names]
        if "paths" in spec:
            paths = [spec["paths"]] if isinstance(spec["paths"], str) else spec["paths"]
            if not isinstance(paths, list) or not paths or not all(plain_path(p) for p in paths):
                return {}, f"serve.services.{a}.paths: רשימה של נתיבים מוחלטים, בלי . ו-.. ובלי %"
            entry["paths"] = list(paths)
        out[a] = entry
    return out, ""


def publishable_services(registry: dict, serve_map, office: str = "") -> list[dict]:
    """The DOORS WITH NO TILE this office publishes on a link (`services` of the compiled registry,
    DGO-945) — to `office` when one is named.

    Stricter than `publishable`, on purpose: a door is a capability another office's machines use
    (the recordings, the transcriber, the webhook receiver), not a screen a person opens, so it is
    published only when `serve.services` NAMES it by its alias — never under `*`, never because its
    app is served. The entry says WHO gets it (`to: [vps1]`; without it, `serve.only` narrows it per
    office exactly as it narrows an app) and may name the PATHS the door answers (`serve: {"services":
    {"workflow-hooks": {"to": ["vps1"], "paths": ["/webhook/meet-recordings"]}}}`); the door then
    answers nothing else (link-proxy.py). A path list with a path that is not one is not narrowed to
    the rest: the door is not published at all, because a typo must never open more than was written.
    Under a reserved key of its own, so no reader of the apps (`app_specs`: the delivery plan, the
    firewall, the legacy serve block) ever takes a door for an app."""
    table = serve_map.get("services") if isinstance(serve_map, dict) else None
    specs = {str(k).strip().lower(): v for k, v in (table.items() if isinstance(table, dict) else [])}
    skip = {str(x).strip().lower() for x in excluded(serve_map) if str(x).strip()}
    only = only_for(serve_map, office)
    asker = str(office or "").strip().lower()
    out = []
    for row in ((registry or {}).get("services") or []):
        if not isinstance(row, dict):
            continue
        alias = str(row.get("alias") or "").strip().lower()
        if alias not in specs or alias in skip:
            continue
        spec = specs[alias] if isinstance(specs[alias], dict) else {}
        to = spec.get("to")
        if to is not None:
            if asker not in {str(x).strip().lower() for x in ([to] if isinstance(to, str) else to or [])}:
                continue
        elif only is not None and alias not in only:
            continue
        door = {k: row[k] for k in ("app", "alias", "port", "service", "health") if row.get(k) not in (None, "")}
        paths = spec.get("paths")
        if paths is not None:
            given = [str(p) for p in (paths if isinstance(paths, list) else [paths])]
            if not given or not all(plain_path(p) for p in given):
                continue
            door["paths"] = given
        out.append(door)
    return sorted(out, key=lambda d: d["alias"])


def published_agent(row: dict, door) -> dict:
    """The registry row as the catalog publishes it: its agent door's port and WHO answers it, both taken
    from the door this office opens (`serve_with_agents`), never from the registry row behind it.

    An agent API is published when this office OPENS it; the registry's own number used to travel
    regardless, and a peer built a listener for a port nothing answered on (DGO-32, hp-laptop's 3081,
    2026-10-05). The service follows the same rule (DGO-1018): behind the HP's hand tick `browser42:
    {port 80, agent_api_port 8931}` the row says browser42-task-runner, and publishing that beside 8931
    would name a pair nothing answers (the second reader of DGO-1018)."""
    out = {k: v for k, v in row.items() if k not in ("agent_api_port", "agent_api_service")}
    if isinstance(door, dict) and door.get("agent_api_port"):
        out["agent_api_port"] = int(door["agent_api_port"])
        if door.get("agent_api_service"):
            out["agent_api_service"] = str(door["agent_api_service"])
    return out


def serve_with_agents(registry: dict, serve_map, office: str = "") -> dict:
    """This office's `serve:` map, ENRICHED with the agent door every served app declares (DGO-570).

    The adapter's port is a fact of the APP, not of the link: `reconcile` compiles `agent_api_port`
    into the registry row of every app that answers one, so `serve:` no longer has to repeat it — and
    `{"*": {}}`, which names no app and therefore no port, gives its agent doors like an office that
    names its apps. Measured: a serving office that gave everything published its UI and hid its
    adapter (`linkproxy._serve_doors` had no port to open, `build_catalog` none to publish), and
    `bbox b42 task --office hp-laptop` died on `no_agent_door` (apps/browser42/remote-task.py).

    Up to three fields are added per served app, and none overrides the owner's own words:

    * `agent_api_port` — the row's own number; a row of a FETCHED catalog (`api.port`) counts the same,
      because the end that renders a far office's plan holds the peer's catalog and never its registry;
    * `service` — the name the door DELIVERS to (`mail` answers as `mailview`, DGO-38). It is the name
      this office publishes as `service`, so both ends of the link say one word;
    * `agent_api_service` — the name the AGENT door delivers to, when the app states it is not the UI's
      (browser42's task runner, DGO-1018; a fetched catalog's `api.service` counts the same). Only for
      the door the row describes: a hand entry that names another port or a service keeps its own.

    An explicit `serve:` field WINS, an app nobody serves is not added (`publishable` filters: the
    wildcard, `exclude` and `serve.only` all apply), a row declaring no agent API is not invented, and
    a port another entry already opens is skipped — one door, one port.
    """
    specs = {str(k): v for k, v in app_specs(serve_map).items()}
    out = dict(specs)
    opened: set[int] = set()
    for value in specs.values():
        for entry in (value if isinstance(value, list) else [value]):
            for key in ("port", "agent_api_port"):
                number = entry.get(key) if isinstance(entry, dict) else entry
                try:
                    opened.add(int(number))
                except (TypeError, ValueError):
                    continue
    for row in (publishable(registry, serve_map, office).get("apps") or []):
        if not isinstance(row, dict):
            continue
        app = str(row.get("app") or "").strip().lower()
        alias = str(row.get("alias") or "").strip().lower()
        api = row.get("api") if isinstance(row.get("api"), dict) else {}
        try:
            port = int(row.get("port"))
            api_port = int(row.get("agent_api_port") or api.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not app and not alias:
            continue
        if not 1 <= api_port <= 65535 or api_port == port:
            continue                     # exactly the rule `build` publishes a second port by
        # The KEY stays the app (its id, or the alias it was declared under): it is what `serve.only`
        # names and what a refusal reads out; `service` carries the name the door delivers to.
        key = app if app in specs else (alias if alias in specs else app)
        explicit = specs.get(key) if isinstance(specs.get(key), dict) else {}
        service = str(row.get("service") or app or alias)
        # …and the service that ANSWERS the agent port, which is not always the UI's (DGO-1018): the
        # registry names it (`agent_api_service`), a fetched catalog publishes it as `api.service`, and
        # a row from before either falls back to the UI's service, as every row did. The door delivers
        # the agent port there (`linkproxy._serve_doors`), so sharing an app shares its API and CLI
        # with nothing declared by hand — the owner: "it should just work … out of the box".
        agent = str(row.get("agent_api_service") or api.get("service") or service)
        # The registry's word on WHO answers holds for the door it describes and no other: a hand
        # entry that names another agent port, or names the service itself, is the owner's own word
        # and wins whole. The HP's stale tick `browser42: {port 80, agent_api_port 8931}` would else
        # have gone to the task runner's 8931, where nothing listens (the second reader of DGO-1018).
        own_word = ("service" in explicit or "agent_api_service" in explicit
                    or ("agent_api_port" in explicit and str(explicit.get("agent_api_port")) != str(api_port)))
        if api_port in opened:
            # The owner declared THIS door by hand (`browser42: {port: 80, agent_api_port: …}`): it
            # opens nothing new, but it still delivers to the row's service. Without it the door aimed
            # at the app id, a host nobody answers — the HP's 502 of 2026-10-22 ("browser42: nothing
            # answers at browser42:8931"), where `browser42` answers as `browser42-caddy`.
            if explicit and str(explicit.get("agent_api_port")) == str(api_port):
                carried = {} if "service" in explicit else {"service": service}
                if not own_word and agent != service:
                    carried["agent_api_service"] = agent
                if carried:
                    out[key] = {**carried, **explicit}
            continue
        door = {"service": service, "port": port, "agent_api_port": api_port}
        if agent != service and not own_word:
            door["agent_api_service"] = agent
        out[key] = {**door, **explicit}
        opened.add(api_port)
    # …and the doors with no tile (DGO-945) travel through under their reserved key: no reader takes
    # it for an app (`app_specs`), and `with_control` still opens the link's door for an office that
    # serves a door and nothing else — vps1's recordings, to an office that is given no tile.
    if isinstance(serve_map, dict) and serve_map.get("services"):
        out["services"] = serve_map["services"]
    return out


def served_by_peer(catalogs: dict) -> dict:
    """Fetched catalogs → the shape `linkproxy.build(served_by_peer=…)` expects.

    The delivery plan's `use` half needs exactly two facts per remote app: the port a person opens
    and the second port a CLI speaks to (DGO-32). Everything else in the catalog is presentation, and
    is not allowed to leak into a network plan.
    """
    out: dict[str, dict] = {}
    for office, doc in (catalogs or {}).items():
        if not isinstance(doc, dict):
            continue
        spec = {}
        for app in (doc.get("apps") or []):
            if not isinstance(app, dict):
                continue
            alias = str(app.get("alias") or "").strip().lower()
            try:
                port = int(app.get("port"))
            except (TypeError, ValueError):
                continue
            if not ALIAS_RE.match(alias) or not 1 <= port <= 65535:
                continue
            entry = {"port": port}
            api = app.get("api") or {}
            if isinstance(api, dict) and api.get("port"):
                try:
                    entry["agent_api_port"] = int(api["port"])
                except (TypeError, ValueError):
                    pass
            # Keyed by the REMOTE app id: it is what the plan's log line and its refusal messages
            # name, and it is the peer's own word for the door.
            name = str(app.get("app") or alias)
            if not APP_ID_RE.match(name):
                continue             # DGO-615: a catalog stored before `validate` asked `app` must not refuse every pair's plan
            spec[name] = entry
        out[str(office)] = spec
    return out


# ── the projection's own artifact ────────────────────────────────────────────────────────────────
def catalog_file(base: str | Path, office: str) -> Path:
    return Path(base) / "remote" / f"{office}.json"


def store(base: str | Path, payload: dict) -> Path:
    """Write a fetched catalog where the projection and the screens both find it."""
    dest = catalog_file(base, str(payload.get("office") or "").strip().lower())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def load_all(base: str | Path) -> dict:
    """Every catalog fetched so far, keyed by office. An unreadable file is skipped, not fatal."""
    out = {}
    directory = Path(base) / "remote"
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("office"):
            out[str(doc["office"]).strip().lower()] = doc
    return out


def selftest() -> list[str]:
    """The decisions this module makes, on one office's registry. No network, no peer, no machine —
    which is the point: the gate checks the shape before a second office exists."""
    problems: list[str] = []
    registry = {"apps": [
        {"app": "bina-ds", "alias": "bina", "name": "בינה ודעת", "name_en": "Bina", "icon": "bot",
         "group": "ראשי", "desc": "הסוכן של הלשכה", "order": 1, "port": 3080,
         "agent_api_port": 3081, "host": "bina.localhost",
         "module": {"kind": "embedded", "id": "bina", "path": "/a/bina/"}},
        {"app": "n8n", "alias": "n8n", "name": "n8n", "port": 5678, "order": 30},
        {"app": "broken", "alias": "Broken!", "port": 1},
        {"app": "portless", "alias": "portless"},
    ]}
    cat = build(registry, "macbook", {"he": "המק", "en": "MacBook"}, commit="deadbeef")
    if cat["office"] != "macbook" or cat["label"]["en"] != "MacBook" or cat["commit"] != "deadbeef":
        problems.append(f"the catalog must carry the office, its label and its commit, got {cat}")
    if [a["alias"] for a in cat["apps"]] != ["bina", "n8n"]:
        problems.append(f"an invalid alias and a portless row must not be published, got "
                        f"{[a['alias'] for a in cat['apps']]}")
    bina = cat["apps"][0]
    if bina["title"] != {"he": "בינה ודעת", "en": "Bina"}:
        problems.append(f"the title carries both languages, got {bina['title']}")
    if bina["api"] != {"port": 3081, "auth": "bearer:vault:bina-ds"}:
        problems.append(f"an agent app publishes its SECOND door too, got {bina['api']}")
    if bina.get("host") != "bina.localhost":
        problems.append(f"the authority the serving app expects must cross the link, got {bina}")
    if cat["apps"][1].get("api"):
        problems.append("an app with no agent API must publish no `api` block")
    if bina["module"].get("id") != "bina" or "id" in cat["apps"][1]["module"]:
        problems.append(f"the module id crosses the link when the row has one, and only then, got "
                        f"{bina['module']} / {cat['apps'][1]['module']}")

    filtered = build(registry, "macbook", {}, exclude=["n8n"])
    if [a["alias"] for a in filtered["apps"]] != ["bina"]:
        problems.append("`serve.exclude` must filter on the SERVING side")

    if validate(cat):
        problems.append(f"a catalog this module built must validate: {validate(cat)}")

    def _deep(n):
        v = "x"
        for _ in range(n):
            v = {"k": v}
        return v

    shaped = {"office": "macbook", "apps": [{
        "alias": "bina", "port": 80, "title": {"he": "בינה", "en": "Bina"}, "order": 1,
        "identity": {"to": "owner", "from": ["a", "b"]},
        "module": {"kind": "embedded", "id": "bina", "path": "/a/bina/", "route": {"mode": "standard"}}}]}
    if validate(shaped):
        problems.append(f"the contract's own shapes (module id + route, title, identity) must validate: "
                        f"{validate(shaped)}")
    for bad, needle in [
        ({"office": "MAC BOOK", "apps": []}, "office"),
        ({"office": "vps1", "apps": []}, "הקישור"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 0}]}, "טווח"),
        ({"office": "macbook", "apps": [{"alias": "Bina", "port": 1}]}, "תווית"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80},
                                        {"alias": "bina", "port": 81}]}, "פעמיים"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80, "api": {"port": 80}}]},
         "api.port"),
        ({"office": "macbook", "apps": "bina"}, "רשימה"),
        # the copied fields keep the contract's shape — a deep block is refused, not copied (DGO-619)
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80, "order": _deep(600)}]}, "order"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80, "order": True}]}, "order"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80,
                                         "module": {"kind": _deep(600)}}]}, "module.kind"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80, "title": "Bina"}]}, "title"),
        ({"office": "macbook", "apps": [{"alias": "bina", "port": 80,
                                         "identity": {"to": ["a", "b"]}}]}, "identity.to"),
        # DGO-615: the app id is a delivery target's name — a line break in it is refused like an alias's
        ({"office": "macbook", "apps": [{"alias": "notes", "app": "bina-ds\n", "port": 80}]},
         "אינו מזהה אפליקציה"),
    ]:
        errs = validate(bad, "macbook" if bad.get("office") == "vps1" else "")
        if not errs or not any(needle in e for e in errs):
            problems.append(f"expected a refusal mentioning {needle!r}, got {errs}")
    # A name that ENDS in a line break is not a name (DGO-615). Every reader in this module strips
    # before it asks, so the rules themselves are asked: `$` matched before the break and passed both.
    for rule, value in ((OFFICE_RE, "macbook"), (ALIAS_RE, "bina")):
        broken = value + "\n"
        if not rule.match(value) or rule.match(broken):
            problems.append(f"{value!r} is a name and {broken!r} is not: a line break is no part of one")

    serve = {"bina-ds": {"port": 3080, "agent_api_port": 3081}, "exclude": ["drive"]}
    if set(app_specs(serve)) != {"bina-ds"} or excluded(serve) != ["drive"]:
        problems.append("`serve.exclude` is metadata, not an app")
    # One app's port is not every tile's (DGO-1269): the HP served {"bina-claude": {"port": 3000}} and
    # vps1 was offered claude-terminal, which listens on 7681, on 3000.
    two = [{"app": "bina-claude", "alias": "bina-claude", "port": 3000},
           {"app": "bina-claude", "alias": "claude-terminal", "port": 7681}]
    by_app = {"bina-claude": {"port": 3000, "agent_api_port": 3091}}
    if tile_spec(by_app, two[0], two) != {"port": 3000, "agent_api_port": 3091}:
        problems.append("the tile carrying the app's own name takes the app's entry whole")
    if tile_spec(by_app, two[1], two) != {"agent_api_port": 3091}:
        problems.append(f"another tile of the app keeps its own port, got {tile_spec(by_app, two[1], two)}")
    if tile_spec({**by_app, "claude-terminal": {"port": 7682}}, two[1], two).get("port") != 7682:
        problems.append("a tile's own entry names its port")
    one = [{"app": "bina-ds", "alias": "bina", "port": 3080}]
    if tile_spec({"bina-ds": {"port": 3090}}, one[0], one).get("port") != 3090:
        problems.append("an app with ONE tile takes the app's port, whatever the tile's alias")
    # An office narrowed by `serve.only` is told nothing of an app served after its list (DGO-1269):
    # the answer that serves the app names the offices it does not reach.
    hp = {"bina-ds": {"port": 3080}, "bina-claude": {"port": 3000}, "plane": {"port": 80},
          "only": {"vps1": ["bina", "plane"], "fireplace": []}}
    rows = one + two + [{"app": "plane", "alias": "plane", "port": 80}]
    got = withheld_by_only(hp, rows)
    if got != {"vps1": ["bina-claude"], "fireplace": ["bina-claude", "bina-ds", "plane"]}:
        problems.append(f"withheld_by_only names, per narrowed office, each served app it is not given, got {got}")
    if withheld_by_only({"bina-claude": {"port": 3000}, "only": {"vps1": ["claude-terminal"]}}, rows):
        problems.append("an app is given when any of its tiles' aliases is on the list")
    if withheld_by_only({"bina-ds": {"port": 3080}}, rows):
        problems.append("no `only`, nothing withheld")
    if withheld_by_only({"bina-ds": {"port": 3080}, "only": {"VPS1": "bina"}}, rows):
        problems.append("`only` is read as the door reads it: one name for a list, case aside")
    if withheld_by_only({"bina-ds": {"port": 3080}, "only": {"vps1": 7}}, rows) != {}:
        problems.append("an `only` value that is no name and no list is skipped, not a crash")
    # the second tile takes neither the app's port nor its host: the door keys its routes by host
    hosted = {"bina-claude": {"port": 3000, "host": "claude.localhost"}}
    if "host" in tile_spec(hosted, two[1], two) or tile_spec(hosted, two[0], two).get("host") != "claude.localhost":
        problems.append("the app's host belongs to the tile of its own name only")
    if tile_spec({**hosted, "claude-terminal": {"host": ""}}, two[1], two).get("host") != "":
        problems.append("a tile's own entry names its host, empty included")
    control = with_control(serve)
    if control.get("dgo-extend") != {"port": CATALOG_PORT}:
        problems.append("the link's own control door must be served whenever anything is")
    if control.get("bina-ds") != {"port": 3080, "agent_api_port": 3081}:
        problems.append("the control door must not disturb the declared apps")
    if with_control({"dgo-extend": {"port": 1234}}).get("dgo-extend") != {"port": 1234}:
        problems.append("a declared catalog port must win over the default")
    if with_control({}):
        problems.append("an office that serves nothing serves no catalog either")

    by_peer = served_by_peer({"macbook": cat})
    if by_peer["macbook"]["bina-ds"] != {"port": 3080, "agent_api_port": 3081}:
        problems.append(f"the plan's `use` half needs the two ports, got {by_peer}")
    # DGO-615: a catalog STORED before `validate` asked the app id — its bad entry is left out of the
    # plan's `use` half, and the rest of that office (and every other pair) still renders.
    stale = {"apps": [{"alias": "notes", "app": "bina-ds\n", "port": 3090, "api": {"port": 3091}},
                      {"alias": "drive", "app": "drive", "port": 8975}]}
    if served_by_peer({"vps1": stale}) != {"vps1": {"drive": {"port": 8975}}}:
        problems.append(f"an entry whose app is no app id is skipped, got {served_by_peer({'vps1': stale})}")
    # DGO-622: a mapped user stored before it was checked is never published — and the log says so
    class _Heard(logging.Handler):
        def __init__(self):
            super().__init__()
            self.said = []

        def emit(self, record):
            self.said.append(record.getMessage())
    heard = _Heard()
    log.addHandler(heard)
    log.propagate = False

    def published_identity(ident):
        got = build({"apps": [{"app": "bina-ds", "alias": "bina", "port": 3080, "identity": ident}]}, "hp")
        return got["apps"][0].get("identity")
    try:
        if published_identity({"to": "owner\n", "from": ["guest"]}) is not None:
            problems.append("a mapped user with a line break must not be published (the door writes it into a header)")
        if not any("not a header value" in s for s in heard.said):
            problems.append(f"a mapped user that is not published is said in the log, heard {heard.said}")
        kept = published_identity({"to": "owner", "from": ["guest\n", "akadmin"]})
        if kept != {"to": "owner", "from": ["akadmin"]}:
            problems.append(f"only the `from` names that are header values are published, got {kept}")
        if published_identity({"to": "owner", "from": "alice"}) != {"to": "owner", "from": ["alice"]}:
            problems.append("a `from` written as one name is that name, not its letters")
    finally:
        log.removeHandler(heard)
        log.propagate = True

    # What this office PUBLISHES is what it SERVES (DGO-32). The registry holds `bina`/`bina-ds`,
    # `n8n`, `drive` and a running `dgo-extend`; the catalog must carry exactly the declared ones.
    wide = {"apps": registry["apps"] + [{"app": "dgo-extend", "alias": "dgo-extend", "port": 8983},
                                        {"app": "drive", "alias": "drive", "port": 8975}]}
    if [r["alias"] for r in publishable(wide, {})["apps"]]:
        problems.append("an office that serves nothing publishes nothing")
    one = publishable(wide, {"drive": {"port": 8975}})
    if [r["alias"] for r in one["apps"]] != ["drive"]:
        problems.append(f"`serve:` names the published apps, got {[r['alias'] for r in one['apps']]}")
    # Matched by ALIAS too: `bina` is the alias, `bina-ds` the app id, and either is what a person
    # writes in `serve:`.
    if [r["alias"] for r in publishable(wide, {"bina": {"port": 3080}})["apps"]] != ["bina"]:
        problems.append("a `serve:` key may be the alias as well as the app id")
    star = build(publishable(wide, {"*": {}, "exclude": ["n8n"]}), "macbook")
    if [r["alias"] for r in star["apps"]] != ["bina", "drive"]:
        problems.append(f"`serve: {{\"*\": {{}}}}` is every app minus `exclude` — and never this app "
                        f"(DGO-624), got {[r['alias'] for r in star['apps']]}")
    if publishable(wide, {"dgo-extend": {"port": 8983}})["apps"]:
        problems.append("this app is not published even when `serve:` names it: its catalog door is the link's (DGO-624)")
    if wildcard({"*": {}}) is not True or wildcard({"drive": {}}) is not False:
        problems.append("the wildcard is a key, and only the reserved one")
    # WHAT ONE LINKED OFFICE IS GIVEN (`serve.only`): narrower for the office it names, by alias or
    # app id; unchanged for every other office and for a question asked on nobody's behalf; and it
    # never widens — an app this office excludes stays out whatever `only` says.
    narrow = {"*": {}, "exclude": ["n8n"], "only": {"vps1": ["bina-ds", "n8n"], "tablet": []}}
    aliases = lambda office: [r["alias"] for r in build(publishable(wide, narrow, office), "hp")["apps"]]  # noqa: E731
    if aliases("vps1") != ["bina"]:
        problems.append(f"an office named in `only` is given exactly its list (minus `exclude`), got {aliases('vps1')}")
    if aliases("macbook") != ["bina", "drive"] or aliases("") != aliases("macbook"):
        problems.append(f"an office `only` does not name is given what `serve:` says, got {aliases('macbook')}")
    if aliases("tablet") or only_for(narrow, "tablet") != set() or only_for(narrow, "macbook") is not None:
        problems.append("an empty list is `linked, and given nothing`; an absent office is not narrowed")
    if "only" in app_specs(narrow) or "only" in with_control(narrow):
        problems.append("`serve.only` is metadata of the declaration, never an app with a port")

    # `serve.shared` (2026-10-19): what OTHER offices gave this one, handed on — vps1 in the middle,
    # hp-laptop the origin, claude-cloud asking.
    hp = build({"apps": [
        {"app": "project-pln", "alias": "plane", "name": "Plane", "port": 8080, "host": "plane.localhost",
         "agent_api_port": 8081, "identity": {"to": "owner"}},
        {"app": "browser42", "alias": "browser42", "name": "דפדפן", "port": 8090, "host": "browser42.localhost"},
        {"app": "bina-ds", "alias": "bina", "name": "בינה", "port": 3080},
        {"app": "dgo-extend", "alias": "dgo-extend", "name": "x", "port": 8983, "host": "dgo-extend.localhost"}]},
        "hp-laptop", {"he": "HP"})
    hp["shared"] = [{"office": "macbook", "apps": [{"alias": "drive", "app": "drive", "port": 9009,
                                                    "host": "drive.macbook"}]}]
    fetched, doors = {"hp-laptop": hp}, {"hp-laptop": 9003}
    every = {"*": {}, "shared": "*"}
    got = reshare(every, "claude-cloud", "vps1", fetched, doors)
    if [s["office"] for s in got] != ["hp-laptop"]:
        problems.append(f"`shared: *` hands on what the origin gave, and ONE HOP only — never what the "
                        f"origin itself re-shared, got {[s['office'] for s in got]}")
    rows = {a["alias"]: a for s in got for a in s["apps"]}
    if sorted(rows) != ["browser42", "plane"]:
        problems.append(f"every app of the origin that names its authority, except this app itself, "
                        f"got {sorted(rows)}")
    plane = rows.get("plane") or {}
    if (plane.get("port"), plane.get("host"), plane.get("service"), plane.get("origin_host")) != \
            (9003, "plane.hp-laptop", "plane.hp-laptop", "plane.localhost") or "api" in plane \
            or "identity" in plane:
        problems.append(f"a re-shared app answers under <alias>.<origin> on this office's own door to "
                        f"the origin, carries the origin's authority, and no agent port or identity, got {plane}")
    odd = {"hp-laptop": dict(hp, generated_at="soon", apps=[dict(hp["apps"][0], host="plane.localhost\r\nX: 1")])}
    if reshare(every, "claude-cloud", "vps1", odd, doors):
        problems.append("an authority that is not one is never handed on into a Host header")
    if [s["generated_at"] for s in reshare(every, "claude-cloud", "vps1", {"hp-laptop": dict(hp, generated_at=[1])}, doors)] != [0] \
            or _stamp(float("inf")) != 0:
        problems.append("a stored catalog's `generated_at` that is not a number is 0, never a raise")
    if reshare(every, "claude-cloud", "vps1", {"localhost": dict(hp, office="localhost")}, {"localhost": 9003}):
        problems.append("an office named `localhost` is never an origin: `<alias>.localhost` is an own app's name")
    if reshare({"*": {}}, "claude-cloud", "vps1", fetched, doors):
        problems.append("without `shared`, nothing another office gave is handed on")
    if reshare(every, "hp-laptop", "vps1", fetched, doors):
        problems.append("an office is never handed its own apps back")
    if reshare(every, "claude-cloud", "vps1", fetched, {}):
        problems.append("an origin with no door here is not linked here, and nothing of it is handed on")
    named = lambda serve, hidden=None: sorted(a["alias"] for s in reshare(serve, "claude-cloud", "vps1", fetched, doors, hidden)  # noqa: E731
                                             for a in s["apps"])
    if named({"*": {}, "shared": ["hp-laptop"]}) != ["browser42", "plane"] or named({"*": {}, "shared": ["macbook"]}):
        problems.append("`shared` names its origins")
    if named({"*": {}, "shared": {"hp-laptop": ["plane"]}}) or named({"*": {}, "shared": {"*": "*"}}):
        problems.append("a map is not a form of `shared` (an older driving office refuses the far plan "
                        "over it): it hands on nothing")
    if named(every, {"hp-laptop": ["browser42"]}) != ["plane"]:
        problems.append("what this office hides itself, it does not hand on")
    if named({**every, "only": {"claude-cloud": ["plane.hp-laptop"]}}) != ["plane"] or \
            named({**every, "only": {"claude-cloud": []}}):
        problems.append("`only` narrows a re-shared app by <alias>.<origin>, and an empty list gives nothing")
    if "shared" in app_specs(every) or "shared" in with_control(every):
        problems.append("`serve.shared` is metadata of the declaration, never an app with a port")
    # …and the consuming side: what of a peer's `shared` it may use, section by section.
    vps1 = build({"apps": [{"app": "drive", "alias": "drive", "name": "Drive", "port": 8975}]}, "vps1")
    vps1["shared"] = got + [{"office": "claude-cloud", "apps": [{"alias": "x", "port": 1, "host": "x.claude-cloud"}]},
                            {"office": "vps1", "apps": [{"alias": "y", "port": 1, "host": "y.vps1"}]},
                            {"office": "macbook", "apps": [{"alias": "drive", "port": 9002, "host": "drive.localhost"}]},
                            {"office": "tablet", "apps": [{"alias": "Bad!", "port": 1, "host": "bad.tablet"}]},
                            {"office": "phone", "label": ["x"], "apps": [{"alias": "a", "port": 1, "host": "a.phone"}]},
                            {"office": "watch", "generated_at": "soon", "apps": [{"alias": "a", "port": 1, "host": "a.watch"}]},
                            {"office": "ipad", "apps": [{"alias": "a", "port": 1, "host": "a.ipad",
                                                         "api": {"port": 3081}, "identity": {"to": "x y"}}]},
                            {"office": "localhost", "apps": [{"alias": "drive", "port": 1, "host": "drive.localhost"}]}]
    kept, dropped = shared_sections(vps1, "claude-cloud")
    if [s["office"] for s in kept] != ["hp-laptop", "ipad"] or len(dropped) != 7:
        problems.append(f"a section naming this office or the peer itself, a host the peer's door does not "
                        f"answer, an invalid app and a field the compiler refuses are dropped ONE BY ONE — "
                        f"got {[s['office'] for s in kept]}, {len(dropped)} dropped")
    if any(k in a for s in kept for a in s["apps"] for k in ("api", "identity")):
        problems.append("a handed-on app keeps no agent port and no identity, whatever the peer wrote")
    if validate(vps1):
        problems.append(f"`shared` is additive: the peer's own catalog still validates, got {validate(vps1)}")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("catalog.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
