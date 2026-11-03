"""digital-assets.blueprints — ready-made sets of slots, as DATA (blueprints/*.yaml).

A blueprint answers "what digital assets does a business of THIS kind need?" once, from research,
so the owner does not start from an empty page:

  business-basic    every asset a business needs to exist properly online and on paper
  basic-restaurant  extends business-basic: menus, the kashrut certificate, signage, delivery listings
  startup-tail      the series a young product publishes to reveal itself and then its updates —
                    derived from umbrelOS, n8n, Notion and ten other companies (research/)

Applying a blueprint creates its slots (identity / content / media), its channels, and — for the
media timeline — one slot per media UNIT, dated from the launch day the owner gives (D0). Applying is
idempotent and additive: it refreshes the declaration of a slot and never touches the owner's
assets or active choices. `extends` is resolved parents-first.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from pathlib import Path

import yaml

import store

DIR = Path(os.environ.get("DIGITAL_ASSETS_BLUEPRINTS") or Path(__file__).with_name("blueprints"))
SECTIONS = ("identity", "content", "media")
KINDS = {"text", "richtext", "image", "video", "animation", "file", "document", "color", "palette",
         "link", "handle", "list", "price-list", "hours", "address", "phone", "email", "set"}
FIELDS = {"name", "bio", "avatar", "banner", "links", "handle"}
KIND_ALIASES = {"rich-text": "richtext"}
#: THE CONTENT LIBRARY (DGO-819, DGO-685): a blueprint's `library:` is its editorial plan — one entry
#: per item and language, each a richtext slot `content.<type>.<slug>.<lang>`. Its body, when it has
#: been written, is a markdown file beside the blueprints (`content/<type>/<slug>.<lang>.md`, front
#: matter + body) so the image carries it and a review reads it as a diff. The types and their shapes
#: are ai/context/seo/style-guide.md's.
CONTENT_TYPES = ("article", "tutorial", "post", "news", "report")
CONTENT_LANGS = ("he", "en")
CONTENT_DIR = DIR / "content"
SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
#: what a written body becomes, until somebody chooses otherwise in the app: a version, never the active one
CONTENT_AUTHOR = "בינה סולושנס"


class BlueprintError(Exception):
    pass


#: parsed files, keyed by path and invalidated by mtime — the blueprints are ~150KB of YAML, and
#: parsing them on every overview request held the GIL long enough to stall every other request.
_CACHE: dict[str, tuple[float, dict]] = {}
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _load_file(p: Path) -> dict:
    mtime = p.stat().st_mtime
    hit = _CACHE.get(str(p))
    if hit and hit[0] == mtime:
        return hit[1]
    data = yaml.load(p.read_text(encoding="utf-8"), Loader=_Loader) or {}
    _CACHE[str(p)] = (mtime, data)
    return data


def channel_catalog() -> list[dict]:
    return _load_file(DIR / "_channels.yaml").get("channels") or []


def all_blueprints() -> dict[str, dict]:
    found = []
    for p in sorted(DIR.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        b = _load_file(p)
        if b.get("id"):
            found.append(b)
    found.sort(key=lambda b: (b.get("order") or 99, b["id"]))     # the gallery's reading order
    return {b["id"]: b for b in found}


def validate(b: dict, known_channels: set[str]) -> list[str]:
    out = []
    keys = set()
    for s in b.get("slots") or []:
        k = s.get("key") or ""
        if not re.fullmatch(r"[a-z0-9]+(\.[a-z0-9-]+)+", k):
            out.append(f"{b.get('id')}: bad slot key {k!r}")
        if k in keys:
            out.append(f"{b.get('id')}: duplicate slot {k}")
        keys.add(k)
        if s.get("section") not in SECTIONS:
            out.append(f"{k}: section {s.get('section')!r} not in {SECTIONS}")
        kind = KIND_ALIASES.get(s.get("kind"), s.get("kind"))
        if kind not in KINDS:
            out.append(f"{k}: kind {s.get('kind')!r} unknown")
        for t in s.get("targets") or []:
            if t.get("channel") not in known_channels and t.get("channel") not in ("brand",):
                out.append(f"{k}: target channel {t.get('channel')!r} not in _channels.yaml")
            if t.get("field") and t["field"] not in FIELDS:
                out.append(f"{k}: target field {t['field']!r} not in {sorted(FIELDS)}")
    for ph in b.get("phases") or []:
        for u in ph.get("units") or []:
            if not u.get("id"):
                out.append(f"{b.get('id')}: phase {ph.get('id')} has a unit without id")
    for e in b.get("library") or []:
        where = f"{b.get('id')}: library {e.get('type')}/{e.get('slug')}.{e.get('lang') or 'he'}"
        if e.get("type") not in CONTENT_TYPES:
            out.append(f"{where}: type not in {CONTENT_TYPES}")
        if not SLUG_RE.fullmatch(str(e.get("slug") or "")):
            out.append(f"{where}: slug must be latin lowercase words joined by '-'")
        if (e.get("lang") or "he") not in CONTENT_LANGS:
            out.append(f"{where}: lang not in {CONTENT_LANGS}")
        if not e.get("title"):
            out.append(f"{where}: no title")
        k = _library_key(e)
        if k in keys:
            out.append(f"{where}: duplicate slot {k}")
        keys.add(k)
    return out


def resolve(bid: str, blueprints: dict[str, dict] | None = None, _seen=None) -> list[dict]:
    """[root, …, bid] — the chain to apply, parents first. A cycle is an error, not a loop."""
    blueprints = blueprints or all_blueprints()
    _seen = _seen or []
    if bid in _seen:
        raise BlueprintError("מעגל ב-extends: " + " → ".join(_seen + [bid]))
    b = blueprints.get(bid)
    if not b:
        raise BlueprintError(f"תבנית לא מוכרת: {bid}")
    chain = []
    for parent in b.get("extends") or []:
        for x in resolve(parent, blueprints, _seen + [bid]):
            if x["id"] not in [c["id"] for c in chain]:
                chain.append(x)
    chain.append(b)
    return chain


def _offset_days(timing: str) -> int | None:
    """The first `D±N` in a timing string ("D-180..D-60 (…)" → -180, "D0 at 00:01 PT" → 0)."""
    m = re.search(r"\bD\s*([+-])?\s*(\d+)", timing or "")
    if not m:
        return None
    return -int(m.group(2)) if m.group(1) == "-" else int(m.group(2))


def _due(timing: str, d0: str | None) -> str | None:
    off = _offset_days(timing)
    if off is None or not d0:
        return None
    try:
        return (dt.date.fromisoformat(d0) + dt.timedelta(days=off)).isoformat()
    except ValueError:
        return None


def _l(v, fallback: str = "") -> dict:
    """A label that may be written as a string or as {he, en}."""
    if isinstance(v, dict):
        return v
    return {"he": v or fallback, "en": v or fallback}


def media_slots(b: dict, params: dict) -> list[dict]:
    """The media TIMELINE as slots: one per unit (phases) and one per recurring moment (calendar)."""
    d0 = (params or {}).get("launch_date")
    out = []
    for ph in b.get("phases") or []:
        for i, u in enumerate(ph.get("units") or []):
            recurring = str(u.get("timing") or ph.get("window") or "").startswith("recurring")
            out.append({
                "key": f"media.{ph['id']}.{u['id']}", "section": "media", "grp": ph["id"],
                "label": _l(u.get("name")), "kind": "set", "required": False,
                "brief": {"he": u.get("purpose_he") or "", "en": u.get("purpose") or ""},
                "targets": [{"channel": c} for c in u.get("channels") or []],
                "ord": int(ph.get("order") or 0) * 100 + i,
                "plan": {"phase": ph["id"], "phase_name": _l(ph.get("name")),
                         "phase_order": ph.get("order"), "window": ph.get("window"),
                         "unit": u["id"], "timing": u.get("timing"), "trigger": u.get("trigger"),
                         "due": None if recurring else _due(u.get("timing") or ph.get("window"), d0),
                         "recurring": recurring, "channels": u.get("channels") or [],
                         "assets": u.get("assets") or [], "copy": u.get("copy"),
                         "examples": u.get("examples") or [], "from": b["id"]}})
    for i, c in enumerate(b.get("calendar") or []):
        out.append({
            "key": f"media.calendar.{c['id']}", "section": "media", "grp": "calendar",
            "label": _l(c.get("name") or c.get("name_he")), "kind": "set", "required": False,
            "brief": {"he": c.get("note_he") or "", "en": c.get("note") or ""},
            "targets": [{"channel": ch} for ch in c.get("channels") or []],
            "ord": 5000 + i,
            "plan": {"phase": "calendar", "phase_name": {"he": "לוח שנה", "en": "Calendar"},
                     "unit": c["id"], "timing": c.get("trigger"), "recurring": True,
                     "channels": c.get("channels") or [], "assets": c.get("assets") or [],
                     "copy": c.get("copy"), "from": b["id"]}})
    return out


def _library_key(e: dict) -> str:
    return f"content.{e.get('type')}.{e.get('slug')}.{e.get('lang') or 'he'}"


def _front(text: str) -> tuple[dict, str]:
    """A content file's front matter (YAML between two `---` lines) and its markdown body."""
    if text.startswith("---\n"):
        head, sep, body = text[4:].partition("\n---\n")
        if sep:
            front = yaml.load(head, Loader=_Loader) or {}
            return (front if isinstance(front, dict) else {}), body.lstrip("\n")
    return {}, text


def library_file(e: dict) -> Path:
    return CONTENT_DIR / str(e.get("type")) / f"{e.get('slug')}.{e.get('lang') or 'he'}.md"


def library_slots(b: dict) -> list[dict]:
    """The editorial plan as slots: one richtext slot per `library:` entry, written or not yet."""
    out = []
    for i, e in enumerate(b.get("library") or []):
        lang = e.get("lang") or "he"
        out.append({
            "key": _library_key(e), "section": "content", "grp": e["type"], "kind": "richtext",
            "lang": lang, "label": _l(e.get("title")),
            "required": False, "brief": {"he": e.get("brief") or "", "en": ""},
            "constraints": {"words": e.get("words")} if e.get("words") else {},
            "targets": [{"channel": "website"}, {"channel": "blog"}],
            "ord": 9000 + i,
            "plan": {"type": e["type"], "slug": e["slug"], "lang": lang,
                     "category": e.get("category") or "", "refs": e.get("refs") or [],
                     "keywords": e.get("keywords") or [], "words": e.get("words"),
                     "file": str(library_file(e).relative_to(DIR)), "from": b["id"]}})
    return out


def seed_library(b: dict, by: str = "") -> int:
    """Each WRITTEN body becomes a draft version of its slot — once per content of the file.

    Additive like the rest of `apply`: a body whose exact text a version already carries
    (`meta.file_sha`) is not added again, an edited file is a NEW draft beside the old ones, and
    nothing here ever makes a version active — publishing is the owner's choice in the app."""
    added = 0
    for e in b.get("library") or []:
        f = library_file(e)
        if not f.is_file():
            continue
        raw = f.read_text(encoding="utf-8")
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        key = _library_key(e)
        if any((a.get("meta") or {}).get("file_sha") == sha
               for a in store.list_assets(key, include_archived=True)):
            continue
        front, body = _front(raw)
        if not body.strip():
            continue
        meta = {k: v for k, v in front.items() if k != "title"}
        meta.update({"format": "markdown", "file": str(f.relative_to(DIR)), "file_sha": sha,
                     "words": len(body.split()), "type": e["type"], "slug": e["slug"],
                     "lang": e.get("lang") or "he"})
        a = store.add_asset(key, "richtext", title=str(front.get("title") or e.get("title") or ""),
                            text=body, source="import", status="draft",
                            author=str(front.get("author") or CONTENT_AUTHOR), meta=meta)
        store.event("asset", f"טיוטה חדשה מהספרייה: {a['title']}", slot_key=key, actor=by,
                    data={"asset": a["id"], "file": meta["file"], "words": meta["words"]})
        added += 1
    return added


def apply(bid: str, params: dict | None = None, by: str = "") -> dict:
    blueprints = all_blueprints()
    chain = resolve(bid, blueprints)
    known = {c["id"] for c in channel_catalog()}
    problems = [p for b in chain for p in validate(b, known)]
    if problems:
        raise BlueprintError("התבנית אינה תקינה: " + "; ".join(problems[:8]))
    ensure_channels()
    params = {**(store.applied().get(bid, {}).get("params") or {}), **(params or {})}
    created = refreshed = drafts = 0
    for depth, b in enumerate(chain):
        for i, s in enumerate(list(b.get("slots") or []) + media_slots(b, params) + library_slots(b)):
            s = dict(s)
            # the blueprint's own order IS the reading order (logo before colours, names before
            # contact); a parent's slots come before its child's
            if s.get("section") != "media" or not s.get("ord"):
                s["ord"] = depth * 10000 + i
            s["kind"] = KIND_ALIASES.get(s.get("kind"), s.get("kind"))
            s.setdefault("grp", s.get("group") or "")
            s["label"] = _l(s.get("label"), s["key"])
            existed = store.get_slot(s["key"]) is not None
            store.upsert_slot(s, source=b["id"])
            created += 0 if existed else 1
            refreshed += 1 if existed else 0
        # every channel a slot of this blueprint names becomes a channel row (from the catalogue),
        # so "where is this used" always has somewhere to point
        catalog = {c["id"]: c for c in channel_catalog()}
        named = {t.get("channel") for s in list(b.get("slots") or []) + media_slots(b, params) + library_slots(b)
                 for t in s.get("targets") or []}
        for cid in sorted(c for c in named if c in catalog):
            c = catalog[cid]
            if store.get_channel(cid):
                store.redefine_channel(cid, c.get("kind") or "listing", c.get("platform"))
                continue
            store.upsert_channel({"id": cid, "kind": c.get("kind") or "listing",
                                  "label": {"he": c.get("he"), "en": c.get("en")},
                                  "platform": c.get("platform"), "url": c.get("url"),
                                  "core": bool(c.get("core")), "ord": 100})
        drafts += seed_library(b, by)
        store.mark_applied(b["id"], b.get("version") or 1, params if b["id"] == bid else {}, by)
    store.event("blueprint", f"הוחלה התבנית {bid}: {created} משבצות חדשות, {refreshed} עודכנו"
                + (f", {drafts} טיוטות מהספרייה" if drafts else ""),
                actor=by, data={"blueprint": bid, "chain": [b["id"] for b in chain], "drafts": drafts})
    return {"blueprint": bid, "chain": [b["id"] for b in chain], "created": created,
            "refreshed": refreshed, "drafts": drafts}


def ensure_channels() -> None:
    """The core channels exist from the first start, bound to nothing until the owner binds them."""
    for i, c in enumerate(channel_catalog()):
        if store.get_channel(c["id"]):
            store.redefine_channel(c["id"], c.get("kind") or "listing", c.get("platform"))
        elif c.get("core"):
            store.upsert_channel({"id": c["id"], "kind": c["kind"], "platform": c.get("platform"),
                                  "label": {"he": c.get("he"), "en": c.get("en")}, "core": True,
                                  "ord": i, "url": c.get("url")})


def summary(b: dict) -> dict:
    """What the blueprint gallery shows: the counts, never the whole file."""
    chain = resolve(b["id"])
    slots = [s for x in chain for s in x.get("slots") or []]
    units = [u for x in chain for ph in x.get("phases") or [] for u in ph.get("units") or []]
    cal = [c for x in chain for c in x.get("calendar") or []]
    by_section = {}
    for s in slots:
        by_section[s.get("section")] = by_section.get(s.get("section"), 0) + 1
    by_section["media"] = by_section.get("media", 0) + len(units) + len(cal)
    library = [e for x in chain for e in x.get("library") or []]
    by_section["content"] = by_section.get("content", 0) + len(library)
    return {"id": b["id"], "version": b.get("version") or 1, "name": _l(b.get("name")),
            "summary": _l(b.get("summary")), "extends": b.get("extends") or [],
            "sources": b.get("sources") or [], "params": b.get("params") or [],
            "counts": {"slots": len(slots), "units": len(units), "calendar": len(cal),
                       "phases": sum(len(x.get("phases") or []) for x in chain),
                       "library": len(library),
                       "written": sum(1 for e in library if library_file(e).is_file()),
                       "by_section": by_section},
            "applied": store.applied().get(b["id"])}
