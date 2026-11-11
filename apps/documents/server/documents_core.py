"""documents — ONE list over the office's documents, issued and incoming (DGO-1630).

The owner (bina-261109-vjlwcr, 11:01): «כרגע יש לנו מסמכים נכנסים ומסמכים שלי … פשוט לאפליקציית מסמכים אחת». Today
the issued half lives in apitools' ledger (shown by «המסמכים שלי») and the incoming half in INDOX («מסמכים נכנסים»).
This module is the store of record's INDEX over both, per ai/context/research/DGO-1630-documents-app.md (hp-dgo,
e464d7f1): it moves no data and copies no book. Every row says which provider holds the document (`provider`, `ref`);
the index is derived and disposable — dropped, it is rebuilt from the providers with no loss and no duplicate.

Three rules hold here and nowhere else:
  - ONE choke point, `resolve(provider_id)`: an explicit provider, else the office's binding, else a refusal. No
    implicit fallback. `/readyz` asks the same function, so health and the ops cannot disagree.
  - The providers are READ: `ReadOnlyClient` sends GET, and a POST only to a path a provider names as a read (INDOX's
    `documents/query`). Anything else raises before a byte leaves. Issuing stays the ledger's (its own API, the
    owner's words), filing stays INDOX's.
  - A provider that does not answer — or answers a set that cannot be the whole truth — degrades ITS half of the
    list, by name and with its last good time, keeping its last good rows. Never an empty list that looks like "no
    documents", and never a half that flips.
A sync streams: a provider's pages go to a staging table one at a time, and the swap is computed in SQL, so memory
stays one page whatever the size of the book, and a second sync of the same set writes nothing.
Standard library only (it runs in python:3.12-alpine with no build, and its tests run on any Python ≥ 3.9).
"""
from __future__ import annotations

import datetime
import email.utils
import heapq
import http.client
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


class Refused(Exception):
    """A refusal the API answers as a 4xx/5xx with one Hebrew sentence."""

    def __init__(self, detail: str, code: int = 400):
        super().__init__(detail)
        self.detail, self.code = detail, code


class ReadOnlyViolation(Refused):
    """A write was about to reach a provider. This app never writes into another app."""

    def __init__(self, method: str, path: str):
        super().__init__(f"נחסם: {method} {path} — אפליקציית המסמכים קוראת מהספקים בלבד", 500)


class ProviderHTTPError(ConnectionError):
    """The provider answered with an HTTP error; `code` says which."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class NotAtProvider(ProviderHTTPError):
    """The provider answered, and it does not have this document (HTTP 404)."""


class Shrunk(ConnectionError):
    """The provider's set is far smaller than the index's: refused, so a short answer never empties a half."""


def load_types(path: str = "") -> list:
    with open(path or os.path.join(HERE, "types.json"), encoding="utf-8") as f:
        return json.load(f)["types"]


def type_name(code: str, types: list) -> str:
    for t in types:
        if t["code"] == code:
            return t["name_he"]
    return code or "לא מזוהה"


# ── dates: every provider writes its own way; the index holds YYYY-MM-DD so "newest" means newest ─────────────────
_YMD = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DMY = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?!\d)")
_ZONED = re.compile(r"^\s*\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?\s*(Z|[+-]\d{2}:\d{2})\s*$", re.I)


def iso_date(value) -> str:
    """'05/11/2026' (the ledger's doc_date), '2026-11-05T…Z' (INDOX's TIMESTAMP), 'Thu, 05 Nov 2026 08:00:00 GMT'
    (a timestamp through Flask's jsonify), '5.11.26' (INDOX's DOC_DATE, mixed) → '2026-11-05'; anything else → ''.
    A moment with a zone is the office's own day (TZ=Asia/Jerusalem in the container): 22:30Z is tomorrow here."""
    s = str(value or "").strip()
    if not s:
        return ""
    m = _YMD.match(s)
    if m and _ZONED.match(s):
        try:
            return datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00").replace("z", "+00:00")) \
                .astimezone().date().isoformat()
        except ValueError:
            pass                                           # an odd fraction: the written date below
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _DMY.match(s)
        if m:
            d, mo, y = (int(x) for x in m.groups())
            y += 2000 if y < 100 else 0
        else:
            try:
                dt = email.utils.parsedate_to_datetime(s)
            except (TypeError, ValueError, IndexError):
                return ""
            if dt is None:
                return ""
            if dt.tzinfo is not None:
                dt = dt.astimezone()                      # the office's own day (TZ=Asia/Jerusalem in the container)
            y, mo, d = dt.year, dt.month, dt.day
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return ""


def first_date(*values) -> str:
    for v in values:
        got = iso_date(v)
        if got:
            return got
    return ""


# ── the only door to a provider ───────────────────────────────────────────────────────────────────────────────────
class ReadOnlyClient:
    def __init__(self, base: str, reads_by_post: tuple = (), timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.reads_by_post = tuple(re.compile(p) for p in reads_by_post)
        self.timeout = timeout

    def _send(self, method: str, path: str, params: dict | None = None, body=None):
        if method != "GET" and not (method == "POST" and any(p.match(path) for p in self.reads_by_post)):
            raise ReadOnlyViolation(method, path)
        query = {k: v for k, v in (params or {}).items() if v is not None}
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            e.close()
            raise (NotAtProvider if e.code == 404 else ProviderHTTPError)(e.code, f"HTTP {e.code} {path}") from None
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            # HTTPException: a truncated or malformed answer (IncompleteRead, BadStatusLine) is "did not answer" too
            raise ConnectionError(f"{type(e).__name__}: {e}") from None

    def get(self, path: str, params: dict | None = None):
        return self._send("GET", path, params)

    def post_read(self, path: str, body: dict, params: dict | None = None):
        return self._send("POST", path, params, body)

    def request(self, method: str, path: str, params: dict | None = None, body=None):
        return self._send(method.upper(), path, params, body)


def _shaped(got, kind: type, what: str):
    if not isinstance(got, kind):
        raise ConnectionError(f"{what}: an answer of the wrong shape ({type(got).__name__})")
    return got


def _not_again(page: list, prev: set, what: str) -> set:
    """A page made only of the page before is a provider that ignored the offset: a fault, never "the end" — the end
    is an EMPTY page, and a list cut short there would delete the rest. Only one page of ids is held."""
    ids = {p["id"] for p in page}
    if ids <= prev:
        raise ConnectionError(f"{what} answered the same page twice — the list was kept")
    return ids


MAX_ROWS = 500_000                                         # a provider that never stops paging is a fault, not a book


# ── the providers ─────────────────────────────────────────────────────────────────────────────────────────────────
class LedgerProvider:
    """`local`: the business's own documents — apitools' ledger (`ledger` capability), what «המסמכים שלי» shows."""
    id, direction, title = "local", "out", "המסמכים שהעסק הנפיק (הפנקס)"
    PAGE = 200
    ANNOUNCED_STATES = ("issued", "sent", "paid")         # a draft is not a document yet (store.py: DRAFT … CANCELLED)

    def __init__(self, base: str):
        self.c = ReadOnlyClient(base)

    def ping(self):
        _shaped(self.c.get("/documents", {"limit": 1}), list, "the ledger")

    def pages(self):
        """Every page of the ledger, until an EMPTY page: a short page proves nothing about a clamp upstream."""
        offset, prev, total = 0, set(), 0
        while True:
            rows = _shaped(self.c.get("/documents", {"limit": self.PAGE, "offset": offset}) or [], list, "the ledger")
            if not rows:
                return
            page = [self._row(r) for r in rows]
            prev = _not_again(page, prev, "the ledger")
            total += len(page)
            if total > MAX_ROWS:
                raise ConnectionError(f"the ledger listed over {MAX_ROWS} documents — stopped")
            yield page
            offset += len(rows)

    @staticmethod
    def _row(r: dict) -> dict:
        return {"id": f"local:{r['id']}", "provider": "local", "direction": "out",
                "type": r.get("doc_type") or "", "number": str(r.get("doc_number") or ""),
                "date": first_date(r.get("doc_date"), r.get("issued_at"), r.get("created_at")),
                "party": r.get("customer_name") or "", "total": _num(r.get("total")),
                "currency": r.get("currency") or "ILS", "allocation_number": r.get("allocation_number") or "",
                "state": r.get("status") or "", "needs": "", "ref": {"id": str(r["id"])}}

    def event_kind(self, row: dict) -> str | None:
        return "document.issued" if row.get("state") in self.ANNOUNCED_STATES else None

    def document(self, ref: dict) -> dict:
        doc = _shaped(self.c.get(f"/documents/{urllib.parse.quote(ref['id'])}"), dict, "the ledger")
        try:
            doc["events"] = self.c.get(f"/documents/{urllib.parse.quote(ref['id'])}/events")
        except ConnectionError:
            doc["events"] = None
        return doc


class IndoxProvider:
    """`indox`: the documents that came IN — INDOX (`indox-api`), per instance (מופע), what «מסמכים נכנסים» shows."""
    id, direction, title = "indox", "in", "המסמכים שנכנסו (INDOX)"
    PAGE = 500                                             # INDOX caps a page at 500 (INCOMING_DOCS_QUERY_MAX_LIMIT)
    # only what the index maps — every one is a column of incoming_documents (apps/indox/blueprint/fixtures/schema.sql)
    COLUMNS = ["ID", "TYPE", "SHORT_DOC_ID", "DOC_DATE", "TIMESTAMP", "COMPANY_NAME", "NAME", "DOC_TOTAL_AMOUNT",
               "TOTAL_AMOUNT", "STATUS", "REQUIRED_ACTION"]
    # the primary key: a total order, so offset paging can neither skip nor repeat a row (INDOX's own default is
    # created_at, which a batch insert shares across many rows; the poller pages by the same key)
    ORDER = [{"col": "ID", "dir": "asc"}]
    NOT_THE_BUSINESS = ("test",)                           # the permanent test instance (apps/indox/AGENT.md)
    NO_REGISTRY = "no sql transport"                       # an INDOX with no instance registry: the main repo only
    # INDOX's row vocabulary (apps/indox/indox solution.md, B9): what is news, and what is not yet
    FILED = ("COMPLETED",)
    NEEDS_A_HAND = ("MISSING_COMPANY_ID", "UNKNOWN_COMPANY", "MISSING_TYPE", "MISSING_LINK", "API_TOOLS_FAILED",
                    "EXTRACTION_FAILED", "PRIORITY_SYNC_FAILED", "MAX_ITERATIONS", "NEEDS_REVIEW")
    NOT_NEWS = ("OLD", "GARBAGE", "DOUBLE", "MERGED")      # in flight: TO_EXTRACT, IN_PROGRESS, PAUSE, ACTION_RESTART

    def __init__(self, base: str, repo: str):
        self.repo = repo
        self.c = ReadOnlyClient(base, reads_by_post=(r"^/repos/[^/]+/documents/query$",))

    def ping(self):
        self.instances()

    def instances(self) -> list:
        got = _shaped(self.c.get("/instances") or {}, dict, "INDOX /instances")
        reason = str(got.get("reason") or "")
        if got.get("success") is False or ("reason" in got and reason != self.NO_REGISTRY):
            # INDOX answers 200 with an EMPTY list and a `reason` when its registry read fails — and the reason may be
            # "" (an exception with no message): that is "INDOX did not answer", never "no instances"
            raise ConnectionError(f"INDOX could not list its instances ({reason or 'no reason given'})")
        rows = [r for r in _shaped(got.get("instances") or [], list, "INDOX /instances")
                if isinstance(r, dict) and r.get("enabled", True) and str(r.get("id")) not in self.NOT_THE_BUSINESS]
        if not rows and reason == self.NO_REGISTRY:
            return [""]                                    # "" = the main repo
        return [str(r["id"]) for r in rows]

    def _query(self, inst: str, offset: int, wide: bool) -> dict:
        body = {"mode": "all", "limit": self.PAGE, "offset": offset, "order": self.ORDER}
        if not wide:
            body["select"] = self.COLUMNS
        return _shaped(self.c.post_read(f"/repos/{self.repo}/documents/query", body, {"instance": inst or None}) or {},
                       dict, "INDOX documents/query")

    def pages(self):
        for inst in self.instances():
            offset, prev, total, wide = 0, set(), 0, False
            while True:
                try:
                    got = self._query(inst, offset, wide)
                except ProviderHTTPError as e:
                    # INDOX refuses a `select` naming a column the instance's table lacks (supabase_transport `_ident`);
                    # then that instance is read whole — the same rows, more bytes — rather than not at all
                    if wide or e.code not in (400, 422):
                        raise
                    wide = True
                    continue
                rows = _shaped(got.get("rows") or [], list, "INDOX documents/query")
                if not rows:                               # until an EMPTY page: `truncated` is wrong under a clamp
                    break
                page = [self._row(inst, r) for r in rows]
                prev = _not_again(page, prev, f"INDOX («{inst or 'main'}»)")
                total += len(page)
                if total > MAX_ROWS:
                    raise ConnectionError(f"INDOX listed over {MAX_ROWS} documents in «{inst or 'main'}» — stopped")
                yield page
                offset += len(rows)

    def _row(self, inst: str, r: dict) -> dict:
        return {"id": f"indox:{inst or 'main'}:{r['ID']}", "provider": "indox", "direction": "in",
                "type": r.get("TYPE") or "UNKNOWN", "number": str(r.get("SHORT_DOC_ID") or ""),
                "date": first_date(r.get("DOC_DATE"), r.get("TIMESTAMP")),
                "party": r.get("COMPANY_NAME") or r.get("NAME") or "",
                "total": _num(r.get("DOC_TOTAL_AMOUNT") if r.get("DOC_TOTAL_AMOUNT") not in (None, "") else r.get("TOTAL_AMOUNT")),
                "currency": "ILS", "allocation_number": "", "state": r.get("STATUS") or "",
                "needs": r.get("REQUIRED_ACTION") or "",
                "ref": {"instance": inst, "repo": self.repo, "doc_id": str(r["ID"])}}

    def event_kind(self, row: dict) -> str | None:
        state = (row.get("state") or "").upper()
        if state in self.NOT_NEWS:
            return None
        if row.get("needs") or state in self.NEEDS_A_HAND:
            return "document.intake.needs_review"
        return "document.intake.filed" if state in self.FILED else None   # in flight: not yet

    def document(self, ref: dict) -> dict:
        return _shaped(self.c.get(f"/repos/{ref['repo']}/documents/{urllib.parse.quote(ref['doc_id'])}",
                                  {"instance": ref.get("instance") or None}), dict, "INDOX")


def _num(v):
    try:
        return round(float(v), 2) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


PROVIDERS = ("local", "indox")


def make(provider_id: str, env=os.environ):
    if provider_id == "local":
        return LedgerProvider(env.get("DOCUMENTS_LEDGER_URL", "http://apitools:8080"))
    if provider_id == "indox":
        return IndoxProvider(env.get("DOCUMENTS_INDOX_URL", "http://incoming-documents:8080/incomingDocuments"),
                             env.get("DOCUMENTS_INDOX_REPO", "incoming-documents-main"))
    raise Refused(f"אין ספק מסמכים בשם «{provider_id}» (יש: {', '.join(PROVIDERS)})", 404)


def binding(env=os.environ) -> list:
    """The office's binding: which providers this office reads (`DOCUMENTS_PROVIDERS`, comma-separated)."""
    return [p.strip() for p in (env.get("DOCUMENTS_PROVIDERS") or "").split(",") if p.strip()]


def resolve(provider_id: str | None = None, env=os.environ) -> list:
    """THE choke point: an explicit provider > the office's binding > a refusal. Never an implicit fallback."""
    if provider_id:
        return [make(provider_id, env)]
    bound = binding(env)
    if not bound:
        raise Refused("לא הוגדר אף ספק מסמכים בלשכה הזו (DOCUMENTS_PROVIDERS)", 503)
    return [make(p, env) for p in bound]


# ── the index ─────────────────────────────────────────────────────────────────────────────────────────────────────
CONTENT = ("direction", "type", "number", "date", "party", "total", "currency", "allocation_number", "state", "needs",
           "ref")
ROW = ("id", "provider") + CONTENT
COLS = ROW + ("synced_at",)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, provider TEXT NOT NULL, direction TEXT NOT NULL, type TEXT, number TEXT, date TEXT,
  party TEXT, total REAL, currency TEXT, allocation_number TEXT, state TEXT, needs TEXT, ref TEXT NOT NULL,
  synced_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS documents_by_date ON documents (direction, date);
CREATE INDEX IF NOT EXISTS documents_by_provider ON documents (provider);
CREATE TABLE IF NOT EXISTS syncs (
  provider TEXT PRIMARY KEY, last_ok REAL, last_try REAL, ok INTEGER, count INTEGER, error TEXT);
-- a provider's set while it is being read, one page at a time; `mark` is new / chg after the compare
CREATE TABLE IF NOT EXISTS stage (
  id TEXT PRIMARY KEY, provider TEXT NOT NULL, direction TEXT NOT NULL, type TEXT, number TEXT, date TEXT,
  party TEXT, total REAL, currency TEXT, allocation_number TEXT, state TEXT, needs TEXT, ref TEXT NOT NULL,
  mark TEXT);
CREATE INDEX IF NOT EXISTS stage_by_provider ON stage (provider, mark);
-- what was already told on the flow, once per document and kind: survives a row that drops out and comes back,
-- and a rebuild, so nothing is announced twice
CREATE TABLE IF NOT EXISTS announced (id TEXT NOT NULL, kind TEXT NOT NULL, at REAL, PRIMARY KEY (id, kind));
"""
SHRINK_FLOOR = 50                                          # below this many rows a half may empty freely
SHRINK_SHARE = 0.5                                         # a sync that would remove half or more is refused


class Index:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # the container's root is read-only and /app is a read-only mount: SQLite has no directory for a temp file,
        # so anything it would spill (a big sort, a big subquery) stays in memory — or fails as "disk I/O error"
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    # a sync, streamed: begin → add a page at a time (the network read happens outside the lock) → commit
    def stage_begin(self, provider_id: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM stage WHERE provider=?", (provider_id,))

    def stage_add(self, provider_id: str, rows: list):
        recs = [tuple(json.dumps(r["ref"], ensure_ascii=False, sort_keys=True) if k == "ref" else r[k] for k in ROW)
                for r in rows if r["provider"] == provider_id]
        with self.lock, self.db:
            self.db.executemany(f"INSERT OR REPLACE INTO stage ({','.join(ROW)}) VALUES ({','.join('?' * len(ROW))})",
                                recs)

    def stage_commit(self, provider_id: str, kind_of=None, accept_shrink: bool = False, budget: int = 0,
                     now: float | None = None) -> dict:
        """Swap the provider's half for the staged set in ONE transaction, writing only what differs. Returns the
        counts and up to `budget` events (document, kind) not told before — the newest first; none on the provider's
        first sync, nor on an accepted shrink (ids that flipped are not news). Past the budget, a burst is counted
        (`events_dropped`) and said in the sync's own event, not told one by one."""
        now = now or time.time()
        differs = " OR ".join(f"d.{c} IS NOT stage.{c}" for c in CONTENT)
        accept = f"(`./bbox documents sync {provider_id} --accept-shrink` מקבל את הרשימה הקטנה)"
        with self.lock, self.db:
            count = self.db.execute("SELECT count(*) FROM stage WHERE provider=?", (provider_id,)).fetchone()[0]
            # the half as a whole, and each instance (מופע — a whole client) in it: a short answer must not empty either
            groups = self.db.execute(
                "SELECT json_extract(d.ref, '$.instance') AS g, count(*) AS have, "
                "sum(CASE WHEN EXISTS (SELECT 1 FROM stage s WHERE s.id=d.id) THEN 0 ELSE 1 END) AS gone "
                "FROM documents d WHERE d.provider=? GROUP BY g", (provider_id,)).fetchall()
            have = sum(g["have"] for g in groups)
            removed = sum(g["gone"] or 0 for g in groups)
            if not accept_shrink:
                if have >= SHRINK_FLOOR and removed >= have * SHRINK_SHARE:
                    raise Shrunk(f"{provider_id} החזיר {have - removed} מתוך {have} המסמכים שברשימה — הרשימה נשמרה "
                                 f"כמו שהיא {accept}")
                for g in groups:
                    if g["g"] is not None and g["have"] >= SHRINK_FLOOR and (g["gone"] or 0) >= g["have"] * SHRINK_SHARE:
                        raise Shrunk(f"המופע «{g['g'] or 'main'}» של {provider_id} החזיר {g['have'] - g['gone']} מתוך "
                                     f"{g['have']} המסמכים שברשימה — הרשימה נשמרה כמו שהיא {accept}")
            first = self.db.execute("SELECT last_ok FROM syncs WHERE provider=?", (provider_id,)).fetchone()
            quiet = not (first and first["last_ok"]) or accept_shrink
            self.db.execute("UPDATE stage SET mark=NULL WHERE provider=?", (provider_id,))
            self.db.execute("UPDATE stage SET mark='new' WHERE provider=? AND NOT EXISTS "
                            "(SELECT 1 FROM documents d WHERE d.id=stage.id)", (provider_id,))
            self.db.execute(f"UPDATE stage SET mark='chg' WHERE provider=? AND mark IS NULL AND EXISTS "
                            f"(SELECT 1 FROM documents d WHERE d.id=stage.id AND ({differs}))", (provider_id,))
            added = self.db.execute("SELECT count(*) FROM stage WHERE provider=? AND mark='new'", (provider_id,)).fetchone()[0]
            changed = self.db.execute("SELECT count(*) FROM stage WHERE provider=? AND mark='chg'", (provider_id,)).fetchone()[0]
            self.db.execute(f"INSERT OR REPLACE INTO documents ({','.join(COLS)}) SELECT {','.join(ROW)}, ? FROM stage "
                            f"WHERE provider=? AND mark IS NOT NULL", (now, provider_id))
            self.db.execute("DELETE FROM documents WHERE provider=? AND NOT EXISTS "
                            "(SELECT 1 FROM stage s WHERE s.id=documents.id)", (provider_id,))
            newest, dropped = [], 0
            if kind_of:
                # no ORDER BY: sorting every new row of a first sync is what spills to a temp file; the newest `budget`
                # are kept in a heap instead, and what was told is written a thousand at a time
                told = []
                for r in self.db.execute(f"SELECT {','.join(ROW)} FROM stage WHERE provider=? AND mark IS NOT NULL",
                                         (provider_id,)):
                    rec = dict(r)
                    kind = kind_of(rec)
                    if not kind or self.db.execute("SELECT 1 FROM announced WHERE id=? AND kind=?",
                                                   (rec["id"], kind)).fetchone():
                        continue
                    told.append((rec["id"], kind, now))
                    if len(told) >= 1000:
                        self.db.executemany("INSERT OR IGNORE INTO announced VALUES (?,?,?)", told)
                        told = []
                    if quiet:
                        continue                           # the index learning the book is not news
                    item = (rec["date"] or "", rec["id"], kind, rec)
                    if len(newest) < budget:
                        heapq.heappush(newest, item)
                    else:
                        dropped += 1
                        if budget and item[:2] > newest[0][:2]:
                            heapq.heapreplace(newest, item)
                self.db.executemany("INSERT OR IGNORE INTO announced VALUES (?,?,?)", told)
            events = []
            for _date, _id, kind, rec in sorted(newest, key=lambda x: x[:2], reverse=True):
                rec["ref"] = json.loads(rec["ref"])
                events.append((rec, kind))
            self.db.execute("DELETE FROM stage WHERE provider=?", (provider_id,))
            self.db.execute("INSERT OR REPLACE INTO syncs VALUES (?,?,?,?,?,?)", (provider_id, now, now, 1, count, ""))
        return {"provider": provider_id, "count": count, "added": added, "changed": changed, "removed": removed,
                "events": events, "events_dropped": dropped}

    def replace_provider(self, provider_id: str, rows, accept_shrink: bool = True, now: float | None = None) -> dict:
        """One provider's whole set at once (a small set, or a test): the same swap as a streamed sync."""
        self.stage_begin(provider_id)
        self.stage_add(provider_id, list(rows))
        return self.stage_commit(provider_id, accept_shrink=accept_shrink, now=now)

    def failed(self, provider_id: str, error: str, now: float | None = None):
        now = now or time.time()
        with self.lock, self.db:
            self.db.execute("DELETE FROM stage WHERE provider=?", (provider_id,))
            row = self.db.execute("SELECT last_ok, count FROM syncs WHERE provider=?", (provider_id,)).fetchone()
            self.db.execute("INSERT OR REPLACE INTO syncs VALUES (?,?,?,?,?,?)",
                            (provider_id, row["last_ok"] if row else None, now, 0, row["count"] if row else 0, error[:300]))

    def status(self, now: float | None = None) -> list:
        now = now or time.time()
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT * FROM syncs ORDER BY provider")]
        for r in rows:
            r["said"] = (f"סונכרן {_ago(now - r['last_ok'])}" if r["ok"] else
                         (f"לא סונכרן מאז {_ago(now - r['last_ok'])} — {cause_he(r['error'])}" if r["last_ok"]
                          else f"עוד לא סונכרן — {cause_he(r['error'])}"))
        return rows

    def _rows(self, sql: str, args: tuple) -> list:
        with self.lock:
            out = [dict(r) for r in self.db.execute(sql, args)]
        for r in out:
            r["ref"] = json.loads(r["ref"])
        return out

    def list(self, direction=None, provider=None, type=None, q=None, limit=100, offset=0) -> list:
        sql, args = "SELECT * FROM documents WHERE 1=1", []
        for col, val in (("direction", direction), ("provider", provider), ("type", type)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        if q:
            # the words are the person's: % and _ are letters here, not wildcards
            like = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += " AND (" + " OR ".join(f"lower({c}) LIKE ? ESCAPE '\\'" for c in ("party", "number", "type", "state")) + ")"
            args += [like] * 4
        sql += " ORDER BY date DESC, id LIMIT ? OFFSET ?"
        args += [max(1, min(int(limit), 1000)), max(0, int(offset))]
        return self._rows(sql, tuple(args))

    def search(self, q: str, limit: int = 50) -> list:
        if len((q or "").strip()) < 2:
            raise Refused("חיפוש צריך לפחות שתי אותיות", 400)
        return self.list(q=q, limit=limit)

    def get(self, doc_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM documents WHERE id=?", (doc_id,))
        return rows[0] if rows else None

    def counts(self) -> dict:
        with self.lock:
            return {f"{r[0]}:{r[1]}": r[2] for r in
                    self.db.execute("SELECT provider, direction, count(*) FROM documents GROUP BY provider, direction")}

    def drop(self):
        """Forget the list (it is rebuilt from the providers). What was announced stays announced."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM documents")
            self.db.execute("DELETE FROM syncs")
            self.db.execute("DELETE FROM stage")


INTERNAL = "internal: "                                  # a fault of this app's own, not the provider's


def cause_he(error: str) -> str:
    """Why a half is stale, in words (G76): the raw error — a class name, an OS message — stays in the row's own
    `error` field and in the log, never inside the Hebrew sentence."""
    e = error or ""
    if re.search(r"[֐-׿]", e):                   # already a sentence (a shrink refusal names its own way out)
        return e
    if e.startswith(INTERNAL):
        return "תקלה באפליקציית המסמכים בזמן הקריאה מהספק (הפרטים ביומן)"
    if "could not list its instances" in e:
        return "INDOX לא הצליח לקרוא את רשימת המופעים שלו"
    if "same page twice" in e:
        return "הספק החזיר את אותו עמוד פעמיים"
    if "wrong shape" in e:
        return "הספק ענה בצורה לא צפויה"
    if "listed over" in e:
        return "הספק החזיר יותר מסמכים ממה שאפשר — הקריאה נעצרה"
    if e.startswith("HTTP "):
        return "הספק ענה בשגיאה"
    return "הספק לא עונה"


def _ago(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 90:
        return "עכשיו"
    if sec < 5400:
        return f"לפני {sec // 60} דק׳"
    if sec < 172800:
        return f"לפני {sec // 3600} שע׳"
    return f"לפני {sec // 86400} ימים"


def sync(index: Index, providers: list, on_event=None, accept_shrink: bool = False, budget: int = 20) -> list:
    """Read every provider whole, page by page, and swap its half of the index. A provider that fails — in any way —
    keeps its old rows, and its status says so by name; the others go on."""
    report = []
    for p in providers:
        try:
            index.stage_begin(p.id)
            for page in p.pages():
                index.stage_add(p.id, page)
            res = index.stage_commit(p.id, kind_of=p.event_kind, accept_shrink=accept_shrink, budget=budget)
            if on_event:
                for rec, kind in res["events"]:
                    on_event(rec, kind)
            report.append({"provider": p.id, "ok": True, "count": res["count"], "added": res["added"],
                           "changed": res["changed"], "removed": res["removed"],
                           "events": len(res["events"]), "events_dropped": res["events_dropped"]})
        except Exception as e:                            # noqa: BLE001 — one provider's fault is ITS half's, by name
            error = str(e) if isinstance(e, (ConnectionError, Refused)) else f"{INTERNAL}{type(e).__name__}: {e}"
            index.failed(p.id, error)
            report.append({"provider": p.id, "ok": False, "error": error, "said": cause_he(error)})
    return report
