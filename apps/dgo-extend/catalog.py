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
import re
import time
from pathlib import Path

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
#: The office id rule, the same one `declaration.py` applies to `link.office`.
OFFICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
#: A host label / tile alias: it becomes part of `<alias>.<office>.console.<domain>`.
ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
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
          now: int | None = None, link_port: int = 0, mark: dict | None = None) -> dict:
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
                       "path": str((row.get("module") or {}).get("path") or f"/a/{alias}/")},
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
        # The identity a request should BECOME when it arrives on the serving office. Only that
        # office knows its own user vocabulary, so the mapping is published here and applied by the
        # consuming office's edge.
        ident = row.get("identity") or {}
        if isinstance(ident, dict) and ident.get("to"):
            entry["identity"] = {k: ident[k] for k in ("to",) if ident.get(k)}
            if ident.get("from"):
                entry["identity"]["from"] = [str(u) for u in ident["from"] if u]
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
    # The LINK DOOR's port (DGO-32): one listener per link, with the Host header picking the app
    # behind it, because this office's own registry has four apps on 8080. It is published HERE and
    # not derived by the consumer: the end that owns the door is the end that names it. Zero when the
    # office is not part of a pair yet — a door with no tunnel has no port to answer on.
    if link_port:
        out["link"] = {"port": int(link_port)}
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
        seen[alias] = port
    return errs


def parse(payload: dict, expect_office: str = "") -> dict:
    """The peer's catalog, validated, or a `CatalogError` naming the field."""
    errs = validate(payload, expect_office)
    if errs:
        raise CatalogError("; ".join(errs))
    return payload


# ── the serving office's own `serve:` map ─────────────────────────────────────────────────────────
#: The keys of a `serve:` map that are metadata of the declaration and never an app.
RESERVED = ("exclude", "only", "label", "identity")


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
    if not out and not wildcard_served:
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
        if not every and not (named & {app, alias}):
            continue
        if only is not None and not (only & {app, alias}):
            continue                 # served by this office, and not to THIS one
        rows.append(dict(row))
    return {k: v for k, v in (registry or {}).items() if k != "apps"} | {"apps": rows}


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
            spec[str(app.get("app") or alias)] = entry
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
         "module": {"kind": "embedded", "path": "/a/bina/"}},
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

    filtered = build(registry, "macbook", {}, exclude=["n8n"])
    if [a["alias"] for a in filtered["apps"]] != ["bina"]:
        problems.append("`serve.exclude` must filter on the SERVING side")

    if validate(cat):
        problems.append(f"a catalog this module built must validate: {validate(cat)}")
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
    ]:
        errs = validate(bad, "macbook" if bad.get("office") == "vps1" else "")
        if not errs or not any(needle in e for e in errs):
            problems.append(f"expected a refusal mentioning {needle!r}, got {errs}")

    serve = {"bina-ds": {"port": 3080, "agent_api_port": 3081}, "exclude": ["drive"]}
    if set(app_specs(serve)) != {"bina-ds"} or excluded(serve) != ["drive"]:
        problems.append("`serve.exclude` is metadata, not an app")
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
    if [r["alias"] for r in star["apps"]] != ["bina", "dgo-extend", "drive"]:
        problems.append(f"`serve: {{\"*\": {{}}}}` is every app minus `exclude`, got "
                        f"{[r['alias'] for r in star['apps']]}")
    if wildcard({"*": {}}) is not True or wildcard({"drive": {}}) is not False:
        problems.append("the wildcard is a key, and only the reserved one")
    # WHAT ONE LINKED OFFICE IS GIVEN (`serve.only`): narrower for the office it names, by alias or
    # app id; unchanged for every other office and for a question asked on nobody's behalf; and it
    # never widens — an app this office excludes stays out whatever `only` says.
    narrow = {"*": {}, "exclude": ["n8n"], "only": {"vps1": ["bina-ds", "n8n"], "tablet": []}}
    aliases = lambda office: [r["alias"] for r in build(publishable(wide, narrow, office), "hp")["apps"]]  # noqa: E731
    if aliases("vps1") != ["bina"]:
        problems.append(f"an office named in `only` is given exactly its list (minus `exclude`), got {aliases('vps1')}")
    if aliases("macbook") != ["bina", "dgo-extend", "drive"] or aliases("") != aliases("macbook"):
        problems.append(f"an office `only` does not name is given what `serve:` says, got {aliases('macbook')}")
    if aliases("tablet") or only_for(narrow, "tablet") != set() or only_for(narrow, "macbook") is not None:
        problems.append("an empty list is `linked, and given nothing`; an absent office is not narrowed")
    if "only" in app_specs(narrow) or "only" in with_control(narrow):
        problems.append("`serve.only` is metadata of the declaration, never an app with a port")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("catalog.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
