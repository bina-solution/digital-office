"""dgo-cloud.store — the one SQLite file: who bought what, what it cost, which server is whose (DGO-1893).

Money is kept in AGOROT (integers): ₪99 is 9900. Nothing here knows HTTP; server.py asks, this answers or raises
Refused (a sentence for a person) / NotFound.

  accounts      DGO net accounts (accounts.py owns them)
  subscriptions a plan an account pays for monthly: pending → active → past_due → cancelled/ended
  payments      every charge, first or renewal or top-up: its Cardcom LowProfile id, transaction, tax-invoice number
  wallet        the AI credit, as a ledger: + a plan's monthly credit, + a top-up, − usage, − credit that expired.
                Two buckets: `plan` (₪24 a paid month, expires at the period's end) and `topup` (never expires).
  nodes         the client servers: bought → installing → ready (in the pool) → claimed (someone's DGO) → suspended
                → destroyed. A node's DNS name is `<name>.<zone>`; its agent polls the front for what to do.
  keys          the LLM router's keys — one per node, born with it; it spends the wallet of the node's account
  usage         every metered model call
  acme          the TXT values a node's lego asked for (`_acme-challenge.<name>.<zone>`), served by dnsd.py
  jobs          what the front asked a node's agent to do (claim, suspend, resume, rotate), and what it answered
  audit         every write, who and when
"""
import datetime as dt
import json
import os
import sqlite3
import threading

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL DEFAULT '',
  phone TEXT DEFAULT '', company TEXT DEFAULT '', tax_id TEXT DEFAULT '', pw TEXT DEFAULT '', google_sub TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')), admin INTEGER DEFAULT 0,
  proven INTEGER DEFAULT 0, created_at TEXT, last_seen TEXT, last_ip TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS accounts_google ON accounts(google_sub) WHERE google_sub IS NOT NULL;
CREATE TABLE IF NOT EXISTS sessions (
  hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), created_at TEXT, expires_at TEXT,
  seen_at TEXT, ip TEXT DEFAULT '', ua TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account_id);
CREATE TABLE IF NOT EXISTS tokens (
  hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), purpose TEXT NOT NULL,
  created_at TEXT, expires_at TEXT, used_at TEXT);
CREATE TABLE IF NOT EXISTS viewing (actor INTEGER PRIMARY KEY, target INTEGER NOT NULL, since TEXT, until TEXT);
CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), plan TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','active','past_due','cancelled','ended')),
  price INTEGER NOT NULL, credit INTEGER NOT NULL DEFAULT 0, card_token TEXT DEFAULT '', card_exp TEXT DEFAULT '',
  card_last4 TEXT DEFAULT '', period INTEGER DEFAULT 0, period_start TEXT, period_end TEXT, next_charge_at TEXT,
  cancel_at_end INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, last_error TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS subs_account ON subscriptions(account_id);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), subscription_id INTEGER,
  kind TEXT NOT NULL CHECK (kind IN ('first','renewal','topup')), amount INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','failed','refunded','abandoned')),
  lp_id TEXT DEFAULT '', tran_id TEXT DEFAULT '', ext_id TEXT UNIQUE, doc_number TEXT DEFAULT '',
  doc_url TEXT DEFAULT '', card_last4 TEXT DEFAULT '', error TEXT DEFAULT '', period INTEGER DEFAULT 0,
  created_at TEXT, paid_at TEXT);
CREATE INDEX IF NOT EXISTS payments_account ON payments(account_id);
CREATE TABLE IF NOT EXISTS wallet (
  id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), bucket TEXT NOT NULL
    CHECK (bucket IN ('plan','topup')), delta INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('credit','usage','expire','adjust')), ref TEXT DEFAULT '', note TEXT DEFAULT '',
  created_at TEXT);
CREATE INDEX IF NOT EXISTS wallet_account ON wallet(account_id);
CREATE TABLE IF NOT EXISTS nodes (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, state TEXT NOT NULL DEFAULT 'ordering'
    CHECK (state IN ('ordering','booting','installing','ready','claiming','claimed','suspended','failed',
                     'destroying','destroyed')),
  provider TEXT NOT NULL, provider_id TEXT DEFAULT '', ip TEXT DEFAULT '', plan TEXT DEFAULT '',
  datacenter TEXT DEFAULT '', account_id INTEGER REFERENCES accounts(id), subscription_id INTEGER,
  secret_hash TEXT NOT NULL, admin_user TEXT DEFAULT '', admin_pw TEXT DEFAULT '', progress TEXT DEFAULT '',
  version TEXT DEFAULT '', meta TEXT DEFAULT '', created_at TEXT, ready_at TEXT, claimed_at TEXT, last_seen TEXT, last_error TEXT DEFAULT '',
  health TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS nodes_account ON nodes(account_id);
CREATE TABLE IF NOT EXISTS keys (
  id INTEGER PRIMARY KEY, prefix TEXT NOT NULL, hash TEXT NOT NULL UNIQUE, node_id INTEGER REFERENCES nodes(id),
  account_id INTEGER REFERENCES accounts(id), name TEXT DEFAULT '', created_at TEXT, revoked_at TEXT, last_used TEXT);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY, key_id INTEGER, account_id INTEGER, model TEXT, provider TEXT, in_tokens INTEGER DEFAULT 0,
  out_tokens INTEGER DEFAULT 0, cached_tokens INTEGER DEFAULT 0, usd_micros INTEGER DEFAULT 0, cost INTEGER DEFAULT 0,
  status INTEGER DEFAULT 200, ms INTEGER DEFAULT 0, created_at TEXT);
CREATE INDEX IF NOT EXISTS usage_account ON usage(account_id, created_at);
CREATE TABLE IF NOT EXISTS acme (
  id INTEGER PRIMARY KEY, fqdn TEXT NOT NULL COLLATE NOCASE, value TEXT NOT NULL, node_id INTEGER, created_at TEXT);
CREATE INDEX IF NOT EXISTS acme_fqdn ON acme(fqdn);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL REFERENCES nodes(id), verb TEXT NOT NULL, args TEXT DEFAULT '{}',
  state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','sent','done','failed')), result TEXT DEFAULT '',
  created_at TEXT, sent_at TEXT, done_at TEXT, by TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS jobs_node ON jobs(node_id, state);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, target TEXT, detail TEXT, ip TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

#: what a person reads for a state (the client's screen and the admin's are in Hebrew, RTL)
NODE_HE = {"ordering": "בהזמנה", "booting": "עולה", "installing": "בהתקנה", "ready": "מוכן במאגר",
           "claiming": "נמסר ללקוח", "claimed": "פעיל", "suspended": "מושהה", "failed": "תקלה",
           "destroying": "נמחק", "destroyed": "נמחק"}
SUB_HE = {"pending": "ממתין לתשלום", "active": "פעיל", "past_due": "חיוב נכשל", "cancelled": "בוטל",
          "ended": "הסתיים"}
PAY_HE = {"pending": "ממתין", "paid": "שולם", "failed": "נכשל", "refunded": "הוחזר", "abandoned": "לא הושלם"}


class Refused(Exception):
    """A request the rules refuse — its text is shown to the person as is."""


class NotFound(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def later(**kw):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(**kw)).replace(microsecond=0).isoformat()


def parse(iso):
    try:
        return dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def add_month(iso):
    """The same day next month (the 31st becomes the month's last day) — a period is a calendar month."""
    d = parse(iso) or dt.datetime.now(dt.timezone.utc)
    y, m = (d.year + (d.month // 12), d.month % 12 + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=y, month=m, day=day).isoformat()
        except ValueError:
            continue


def shekels(agorot):
    """₪ for a person: 9900 → '99', 2450 → '24.50', -15 → '-0.15'."""
    a = int(agorot or 0)
    sign = "-" if a < 0 else ""
    a = abs(a)
    return f"{sign}{a // 100}" if a % 100 == 0 else f"{sign}{a // 100}.{a % 100:02d}"


class Store:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.path = path
        self._local = threading.local()
        self.lock = threading.RLock()       # one writer at a time: SQLite serialises anyway; this keeps a
        with self.lock:                     # read-modify-write (a wallet debit) whole
            self.db().executescript(SCHEMA)  # (executescript commits by itself: never inside tx())

    def db(self):
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.c = c
        return c

    class _Tx:
        def __init__(self, store):
            self.s = store

        def __enter__(self):
            self.s.lock.acquire()
            self.c = self.s.db()
            self.c.execute("BEGIN IMMEDIATE")
            return self.c

        def __exit__(self, et, ev, tb):
            try:
                self.c.execute("ROLLBACK" if et else "COMMIT")
            finally:
                self.s.lock.release()
            return False

    def tx(self):
        return Store._Tx(self)

    def one(self, sql, *a):
        r = self.db().execute(sql, a).fetchone()
        return dict(r) if r else None

    def all(self, sql, *a):
        return [dict(r) for r in self.db().execute(sql, a).fetchall()]

    def run(self, sql, *a):
        with self.tx() as c:
            cur = c.execute(sql, a)
            return cur.lastrowid

    # ── audit ────────────────────────────────────────────────────────────────────────────────────────
    def audit(self, actor, action, target="", detail=None, ip="", c=None):
        row = (now(), str(actor or ""), action, str(target or ""), json.dumps(detail or {}, ensure_ascii=False), ip)
        sql = "INSERT INTO audit(at,actor,action,target,detail,ip) VALUES (?,?,?,?,?,?)"
        if c is not None:
            c.execute(sql, row)
        else:
            self.run(sql, *row)

    # ── settings (what the admin changes at run time: the pool size, the price table's FX) ────────────
    def setting(self, key, default=None):
        r = self.one("SELECT value FROM settings WHERE key=?", key)
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except ValueError:
            return r["value"]

    def set_setting(self, key, value):
        self.run("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 key, json.dumps(value))

    # ── the wallet ───────────────────────────────────────────────────────────────────────────────────
    def balance(self, account_id, c=None):
        q = ("SELECT bucket, COALESCE(SUM(delta),0) AS b FROM wallet WHERE account_id=? GROUP BY bucket")
        rows = (c or self.db()).execute(q, (account_id,)).fetchall()
        out = {"plan": 0, "topup": 0}
        for r in rows:
            out[r["bucket"]] = int(r["b"])
        out["total"] = out["plan"] + out["topup"]
        return out

    def credit(self, account_id, bucket, amount, ref="", note="", c=None):
        sql = "INSERT INTO wallet(account_id,bucket,delta,kind,ref,note,created_at) VALUES (?,?,?,?,?,?,?)"
        row = (account_id, bucket, int(amount), "credit", ref, note, now())
        if c is not None:
            c.execute(sql, row)
        else:
            self.run(sql, *row)

    def debit(self, account_id, amount, ref="", note=""):
        """Usage: the plan's credit first, then the top-up. The last call may take the total below zero (a call
        cannot be priced before it ends); the router refuses the next one."""
        amount = int(amount)
        if amount <= 0:
            return self.balance(account_id)
        with self.tx() as c:
            b = self.balance(account_id, c)
            from_plan = min(amount, max(b["plan"], 0))
            rest = amount - from_plan
            ins = "INSERT INTO wallet(account_id,bucket,delta,kind,ref,note,created_at) VALUES (?,?,?,?,?,?,?)"
            if from_plan:
                c.execute(ins, (account_id, "plan", -from_plan, "usage", ref, note, now()))
            if rest:
                c.execute(ins, (account_id, "topup", -rest, "usage", ref, note, now()))
            return self.balance(account_id, c)

    def expire_plan_credit(self, account_id, ref, c):
        """A period ends: what is left of its plan credit goes (the plan gives ₪24 a month, not a savings
        account — Hugging Face's included credits work the same way). A top-up is never touched."""
        left = self.balance(account_id, c)["plan"]
        if left > 0:
            c.execute("INSERT INTO wallet(account_id,bucket,delta,kind,ref,note,created_at) VALUES (?,?,?,?,?,?,?)",
                      (account_id, "plan", -left, "expire", ref, "יתרת התקופה פגה", now()))
        return left
