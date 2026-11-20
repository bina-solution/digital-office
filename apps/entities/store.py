"""store — «ישויות»' records: one SQLite file in the app's volume (DGO-2101).

  entities   a person or an organization: its name and its own fields (patterns.ENTITY_FIELDS)
  roles      the patterns it holds (patterns.ROLES), each with that pattern's fields
  relations  a person who works at an organization (with a title); a salesperson who handles a customer
  sources    where an imported entity came from («ledger:cus_…»): an import runs again and keeps nothing twice
  events     every change: who made it, when, and what each changed field was before and after — the audit, and
             what an undone change is put back from (a role taken off keeps its fields there)

A field is a string; an empty one removes it. Nothing is deleted outright: an entity is archived (out of every
list, still answering by its id, because an issued document may name it), and comes back the same way.

Every write is one transaction, serialized with every other (`_tx`): committed whole, or rolled back whole — a write
that fails half-way (a full disk) leaves no open transaction holding the file's lock, and a change that reads a
record and writes it back reads it inside the same lock, so two at once never lose one of them.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from pathlib import Path

import patterns

DATA = Path(os.environ.get("ENTITIES_DATA", "/data"))
MAX_NAME = 200
MAX_VALUE = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, fields TEXT NOT NULL DEFAULT '{}',
  archived INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
  entity_id TEXT NOT NULL, role TEXT NOT NULL, fields TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY (entity_id, role)
);
CREATE TABLE IF NOT EXISTS relations (
  id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (source TEXT PRIMARY KEY, entity_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  at INTEGER NOT NULL, kind TEXT NOT NULL, entity_id TEXT, summary TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS roles_by_role ON roles(role);
CREATE INDEX IF NOT EXISTS rel_from ON relations(from_id);
CREATE INDEX IF NOT EXISTS rel_to ON relations(to_id);
CREATE INDEX IF NOT EXISTS events_by_entity ON events(entity_id);
"""


class Refused(ValueError):
    """A change the store does not take, in words a person can act on."""


_lock = threading.Lock()
_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DATA / "entities.db", timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


@contextlib.contextmanager
def _tx():
    """One write: alone (the lock), and whole — committed, or rolled back when anything in it fails."""
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise


#: columns a table gained after its first version: (table, column, its declaration) — `CREATE TABLE IF NOT EXISTS`
#: never adds one to a file that already has the table, so each is added here, once (the second reader)
COLUMNS_ADDED = [("events", "detail", "TEXT NOT NULL DEFAULT '{}'")]


def init() -> None:
    with _tx() as c:
        c.executescript(SCHEMA)
        for table, column, decl in COLUMNS_ADDED:
            if column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def now() -> int:
    return int(time.time())


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _norm(s: str) -> str:
    """A value as typed, read the way the closed lists are written: «חברה בע"מ» with a plain quote, with two
    apostrophes, with none at all or with a non-breaking space is «חברה בע״מ» (the ledger reads «זהות»' kind of
    business the same way). Only for matching: what is stored is the list's own spelling."""
    s = unicodedata.normalize("NFKC", s)
    for q in ("״", "''", "“", "”", '"'):
        s = s.replace(q, "")
    return " ".join(s.split())


def _clean(fields: dict | None, allowed: set[str], choices: dict | None = None) -> dict:
    """A patch of fields: known keys only, strings, an empty one meaning «remove»; a closed list's value is stored as
    the list writes it."""
    if fields is not None and not isinstance(fields, dict):
        raise Refused("השדות נשלחים כאובייקט: {\"שדה\": \"ערך\"}")
    out = {}
    for k, v in (fields or {}).items():
        if k not in allowed:
            raise Refused(f"שדה לא מוכר: {k} (השדות: {', '.join(sorted(allowed))})")
        v = "" if v is None else str(v).strip()
        if len(v) > MAX_VALUE:
            raise Refused(f"{k}: ארוך מדי (עד {MAX_VALUE} תווים)")
        if v and choices and k in choices:
            match = next((c for c in choices[k] if _norm(c) == _norm(v)), None)
            if match is None:
                raise Refused(f"{k}: אחד מ-{' / '.join(choices[k])}")
            v = match
        out[k] = v
    return out


def _merge(cur: dict, patch: dict) -> dict:
    m = dict(cur)
    for k, v in patch.items():
        if v:
            m[k] = v
        else:
            m.pop(k, None)
    return m


def _changes(before: dict, after: dict) -> dict:
    """{field: [before, after]} for every field that changed (an absent one is "")."""
    return {k: [before.get(k, ""), after.get(k, "")] for k in sorted(set(before) | set(after))
            if before.get(k, "") != after.get(k, "")}


def _event(c, kind: str, eid: str | None, summary: str, actor: str, detail: dict | None = None) -> None:
    c.execute("INSERT INTO events (at, kind, entity_id, summary, actor, detail) VALUES (?,?,?,?,?,?)",
              (now(), kind, eid, summary, actor or "", _j(detail or {})))


def _row(eid: str):
    return conn().execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()


def _roles(eid: str) -> dict:
    return {r["role"]: json.loads(r["fields"]) for r in
            conn().execute("SELECT role, fields FROM roles WHERE entity_id=? ORDER BY role", (eid,))}


def _relations(eid: str) -> list[dict]:
    out = []
    for r in conn().execute("SELECT * FROM relations WHERE from_id=? OR to_id=? ORDER BY created_at", (eid, eid)):
        other_id = r["to_id"] if r["from_id"] == eid else r["from_id"]
        o = _row(other_id)
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"],
                    "direction": "out" if r["from_id"] == eid else "in",
                    "other": {"id": other_id, "name": o["name"] if o else "", "kind": o["kind"] if o else ""}})
    return out


def view(eid: str) -> dict | None:
    r = _row(eid)
    if not r:
        return None
    return {"id": r["id"], "kind": r["kind"], "name": r["name"], "fields": json.loads(r["fields"]),
            "roles": _roles(eid), "relations": _relations(eid), "archived": bool(r["archived"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _key(fields: dict, roles: dict) -> str:
    """What tells this entity apart in a list: its business number, else its email, else its phone."""
    return ((roles.get("company") or {}).get("business_number") or fields.get("email")
            or fields.get("phone") or fields.get("mobile") or "")


def listing(role: str = "", q: str = "", kind: str = "", archived: bool = False) -> list[dict]:
    rows = conn().execute("SELECT * FROM entities WHERE archived=? ORDER BY name COLLATE NOCASE",
                          (1 if archived else 0,)).fetchall()
    ql = (q or "").strip().lower()
    out = []
    for r in rows:
        roles = _roles(r["id"])
        if role and role not in roles:
            continue
        if kind and r["kind"] != kind:
            continue
        fields = json.loads(r["fields"])
        if ql and ql not in " ".join([r["name"], *fields.values(),
                                      *(v for f in roles.values() for v in f.values())]).lower():
            continue
        out.append({"id": r["id"], "kind": r["kind"], "name": r["name"], "roles": sorted(roles),
                    "key": _key(fields, roles), "phone": fields.get("phone") or fields.get("mobile") or "",
                    "email": fields.get("email") or "", "updated_at": r["updated_at"]})
    return out


def _known(value, table: dict) -> bool:
    """A name from a closed table — a string first: a list or an object sent as a kind is a refusal in words, not an
    unhashable 500 (the second reader of DGO-2101's kind fix)."""
    return isinstance(value, str) and value in table


def _check_role(kind: str, role: str) -> None:
    if role not in patterns.ROLES:
        raise Refused(f"תפקיד לא מוכר: {role} (התפקידים: {', '.join(patterns.ROLES)})")
    if kind not in patterns.ROLES[role]["kinds"]:
        raise Refused(f"התפקיד «{patterns.ROLES[role]['he']}» הוא של "
                      + " או ".join(patterns.KINDS[k]["he"] for k in patterns.ROLES[role]["kinds"]))


def _choices(role: str) -> dict:
    return {f[0]: f[3] for f in patterns.ROLES[role]["fields"] if len(f) > 3}


def _name(name) -> str:
    name = ("" if name is None else str(name)).strip()
    if not name:
        raise Refused("חסר שם")
    if len(name) > MAX_NAME:
        raise Refused(f"השם ארוך מדי (עד {MAX_NAME} תווים)")
    return name


def create(kind: str, name: str, fields: dict | None = None, roles: dict | None = None,
           actor: str = "", source: str = "") -> dict:
    if not _known(kind, patterns.KINDS):
        raise Refused("סוג לא מוכר: אדם (person) או ארגון (organization)")
    name = _name(name)
    f = {k: v for k, v in _clean(fields, patterns.entity_keys()).items() if v}
    if roles is not None and not isinstance(roles, dict):
        raise Refused("התפקידים נשלחים כאובייקט: {\"customer\": {…}}")
    rs = {}
    for role, rf in (roles or {}).items():
        _check_role(kind, role)
        rs[role] = {k: v for k, v in _clean(rf, patterns.field_keys(role), _choices(role)).items() if v}
    with _tx() as c:
        if source:
            had = c.execute("SELECT entity_id FROM sources WHERE source=?", (source,)).fetchone()
            if had:
                return view(had["entity_id"])
        eid = "ent_" + uuid.uuid4().hex[:12]
        t = now()
        c.execute("INSERT INTO entities (id, kind, name, fields, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                  (eid, kind, name, _j(f), t, t))
        for role, rf in rs.items():
            c.execute("INSERT INTO roles (entity_id, role, fields, created_at, updated_at) VALUES (?,?,?,?,?)",
                      (eid, role, _j(rf), t, t))
        if source:
            c.execute("INSERT INTO sources (source, entity_id) VALUES (?,?)", (source, eid))
        _event(c, "created", eid, f"{patterns.KINDS[kind]['he']} «{name}»"
               + (f" · {', '.join(patterns.ROLES[r]['he'] for r in rs)}" if rs else ""), actor,
               {"source": source} if source else None)
    return view(eid)


def _labels(keys, defs) -> str:
    he = {"name": "שם", "kind": "סוג", **{f[0]: f[1] for f in defs}}
    return ", ".join(he.get(k, k) for k in keys) or "שום שדה לא השתנה"


def _kind_fits(c, eid: str, kind: str) -> None:
    """A kind changes only to one that every role and every «works at» of the entity still fits — read inside the
    write's own transaction, so nothing added meanwhile slips past (issues/entities-kind-cannot-be-corrected-…)."""
    for (role,) in c.execute("SELECT role FROM roles WHERE entity_id=?", (eid,)):
        if role in patterns.ROLES and kind not in patterns.ROLES[role]["kinds"]:
            raise Refused(f"אי אפשר: לישות יש התפקיד «{patterns.ROLES[role]['he']}», שהוא של "
                          + " או ".join(patterns.KINDS[k]["he"] for k in patterns.ROLES[role]["kinds"]) + " בלבד")
    if kind != "person" and c.execute("SELECT 1 FROM relations WHERE from_id=? AND kind='works_at'", (eid,)).fetchone():
        raise Refused("אי אפשר: הישות «עובדת ב» ארגון, וזה קשר של אדם — הסירו את הקשר קודם")
    if kind != "organization" and c.execute("SELECT 1 FROM relations WHERE to_id=? AND kind='works_at'",
                                            (eid,)).fetchone():
        raise Refused("אי אפשר: אנשים «עובדים ב» ישות זו, וזה קשר לארגון — הסירו את הקשרים קודם")


def update(eid: str, name: str | None = None, fields: dict | None = None, actor: str = "",
           kind: str | None = None) -> dict:
    """The name, the fields and — to correct a guess (the ledger's hand-over calls a customer with no business
    number a person) — the kind. A kind that a role or a «works at» no longer fits is refused, saying which."""
    patch = _clean(fields, patterns.entity_keys())
    new_name = _name(name) if name is not None else None
    if kind is not None and not _known(kind, patterns.KINDS):
        raise Refused("סוג לא מוכר: אדם (person) או ארגון (organization)")
    with _tx() as c:
        r = c.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()     # read where it is written
        if not r:
            raise LookupError(eid)
        new_kind = kind or r["kind"]
        if new_kind != r["kind"]:
            _kind_fits(c, eid, new_kind)
        before = json.loads(r["fields"])
        merged = _merge(before, patch)
        changes = _changes({**before, "name": r["name"]}, {**merged, "name": new_name or r["name"]})
        if new_kind != r["kind"]:      # the values, as every field's are (what an undo puts back); the screen says them
            changes["kind"] = [r["kind"], new_kind]
        c.execute("UPDATE entities SET name=?, kind=?, fields=?, updated_at=? WHERE id=?",
                  (new_name or r["name"], new_kind, _j(merged), now(), eid))
        _event(c, "updated", eid, "עודכנו: " + _labels(changes, patterns.ENTITY_FIELDS), actor, changes)
    return view(eid)


def set_role(eid: str, role: str, fields: dict | None = None, actor: str = "") -> dict:
    r = _row(eid)
    if not r:
        raise LookupError(eid)
    _check_role(r["kind"], role)
    patch = _clean(fields, patterns.field_keys(role), _choices(role))
    with _tx() as c:
        k = c.execute("SELECT kind FROM entities WHERE id=?", (eid,)).fetchone()
        if not k:
            raise LookupError(eid)
        _check_role(k["kind"], role)        # again where it is written: a kind can change since (update)
        cur = c.execute("SELECT fields FROM roles WHERE entity_id=? AND role=?", (eid, role)).fetchone()
        before = json.loads(cur["fields"]) if cur else {}
        after = _merge(before, patch)
        t = now()
        if cur:
            c.execute("UPDATE roles SET fields=?, updated_at=? WHERE entity_id=? AND role=?", (_j(after), t, eid, role))
        else:
            c.execute("INSERT INTO roles (entity_id, role, fields, created_at, updated_at) VALUES (?,?,?,?,?)",
                      (eid, role, _j(after), t, t))
        c.execute("UPDATE entities SET updated_at=? WHERE id=?", (t, eid))
        changes = _changes(before, after)
        what = ("עודכן: " + _labels(changes, patterns.ROLES[role]["fields"])) if cur else "נוסף"
        _event(c, "role", eid, f"«{patterns.ROLES[role]['he']}» {what}", actor, {role: changes})
    return view(eid)


def remove_role(eid: str, role: str, actor: str = "") -> dict:
    """The role comes off; its fields stay in the history (`detail`), so taking it off by mistake is undone."""
    if not _row(eid):
        raise LookupError(eid)
    with _tx() as c:
        cur = c.execute("SELECT fields FROM roles WHERE entity_id=? AND role=?", (eid, role)).fetchone()
        if cur:
            c.execute("DELETE FROM roles WHERE entity_id=? AND role=?", (eid, role))
            c.execute("UPDATE entities SET updated_at=? WHERE id=?", (now(), eid))
            _event(c, "role", eid, f"«{patterns.ROLES.get(role, {}).get('he', role)}» הוסר", actor,
                   {"removed": {role: json.loads(cur["fields"])}})
    return view(eid)


def archive(eid: str, archived: bool = True, actor: str = "") -> dict:
    with _tx() as c:
        if not c.execute("SELECT 1 FROM entities WHERE id=?", (eid,)).fetchone():
            raise LookupError(eid)
        c.execute("UPDATE entities SET archived=?, updated_at=? WHERE id=?", (1 if archived else 0, now(), eid))
        _event(c, "archived" if archived else "restored", eid, "הועבר לארכיון" if archived else "הוחזר מהארכיון",
               actor)
    return view(eid)


def relate(from_id: str, to_id: str, kind: str, title: str = "", actor: str = "") -> dict:
    if not _known(kind, patterns.RELATIONS):
        raise Refused(f"קשר לא מוכר: {kind} (הקשרים: {', '.join(patterns.RELATIONS)})")
    a, b = _row(from_id), _row(to_id)
    if not a or not b:
        raise LookupError(from_id if not a else to_id)
    if from_id == to_id:
        raise Refused("ישות לא מתקשרת לעצמה")
    if kind == "works_at" and (a["kind"] != "person" or b["kind"] != "organization"):
        raise Refused("«עובד/ת ב» הוא קשר של אדם לארגון")
    with _tx() as c:
        ka = c.execute("SELECT kind FROM entities WHERE id=?", (from_id,)).fetchone()
        kb = c.execute("SELECT kind FROM entities WHERE id=?", (to_id,)).fetchone()
        if not ka or not kb:
            raise LookupError(from_id if not ka else to_id)
        if kind == "works_at" and (ka["kind"] != "person" or kb["kind"] != "organization"):
            raise Refused("«עובד/ת ב» הוא קשר של אדם לארגון")     # again where it is written (update changes kinds)
        rid = "rel_" + uuid.uuid4().hex[:12]
        c.execute("INSERT INTO relations (id, from_id, to_id, kind, title, created_at) VALUES (?,?,?,?,?,?)",
                  (rid, from_id, to_id, kind, (title or "").strip()[:MAX_NAME], now()))
        _event(c, "related", from_id, f"{patterns.RELATIONS[kind]['he']} «{b['name']}»", actor,
               {"relation": rid, "to": to_id, "title": (title or "").strip()[:MAX_NAME]})
    return view(from_id)


def unrelate(rid: str, actor: str = "") -> None:
    with _tx() as c:
        r = c.execute("SELECT * FROM relations WHERE id=?", (rid,)).fetchone()
        if not r:
            raise LookupError(rid)
        c.execute("DELETE FROM relations WHERE id=?", (rid,))
        _event(c, "unrelated", r["from_id"], "קשר הוסר", actor,
               {"relation": rid, "kind": r["kind"], "to": r["to_id"], "title": r["title"]})


def import_rows(rows: list, actor: str = "") -> dict:
    """Many entities at once, each naming its `source` («ledger:cus_…»). A source already here is kept as it is —
    what was changed here since is not overwritten — so a second run keeps nothing twice."""
    made, kept, refused = 0, 0, []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("source"):
            refused.append({"row": i, "detail": "each row names its source"})
            continue
        src = str(row["source"])
        if conn().execute("SELECT 1 FROM sources WHERE source=?", (src,)).fetchone():
            kept += 1
            continue
        try:
            create(row.get("kind", ""), row.get("name", ""), row.get("fields"), row.get("roles"), actor=actor,
                   source=src)
            made += 1
        except Refused as e:
            refused.append({"row": i, "source": src, "detail": str(e)})
    return {"created": made, "kept": kept, "refused": refused}


def events(eid: str = "", limit: int = 50) -> list[dict]:
    q, args = "SELECT * FROM events", []
    if eid:
        q, args = q + " WHERE entity_id=?", [eid]
    out = []
    # newest first; changes within one second in the order they were made (rowid)
    for r in conn().execute(q + " ORDER BY at DESC, rowid DESC LIMIT ?", (*args, max(1, min(500, limit)))):
        d = dict(r)
        d["detail"] = json.loads(d.get("detail") or "{}")
        out.append(d)
    return out


# ── what a document prints ───────────────────────────────────────────────────────────────────────────
#: the kind of business → the ledger's tax status (apitools entities._entity_type reads «זהות» the same way)
TAX_STATUS = {"עוסק פטור": "patur", "עוסק מורשה": "murshe", "חברה בע״מ": "company", "שותפות": "murshe"}


def party(eid: str) -> dict:
    """The entity as a document prints it — the ledger's Party fields (apps/apitools doc_models Party), plus its id
    and its notes (not printed; a reader that writes the block back keeps them). A document keeps this as its
    snapshot when it is issued; «ישויות» stays the definition."""
    e = view(eid)
    if not e:
        raise LookupError(eid)
    f, roles = e["fields"], e["roles"]
    company, customer, supplier = roles.get("company") or {}, roles.get("customer") or {}, roles.get("supplier") or {}
    contact = next((r for r in e["relations"] if r["kind"] == "works_at" and r["direction"] == "in"), None)
    number = company.get("business_number", "")
    return {"entity_id": eid, "name": company.get("legal_name") or e["name"],
            "company_id": re.sub(r"\D", "", number) or number,
            "tax_status": TAX_STATUS.get(company.get("entity_type", ""), ""),
            "vat_file_no": company.get("vat_file", ""),
            "street": f.get("street", ""), "city": f.get("city", ""), "zip": f.get("zip", ""),
            "phone": f.get("phone") or f.get("mobile") or "",
            "email": customer.get("billing_email") or f.get("email") or "",
            "website": f.get("website", ""),
            "customer_no": customer.get("customer_no", ""),
            "deduction_file_no": supplier.get("deduction_file", ""),
            "contact_person": contact["other"]["name"] if contact else "",
            "contact_title": contact["title"] if contact else "",
            "notes": f.get("notes", "")}


def parties(role: str = "", q: str = "") -> list[dict]:
    """Every entity the list would show, as a document prints it — the documents' picker in one call."""
    return [party(e["id"]) for e in listing(role, q)]
