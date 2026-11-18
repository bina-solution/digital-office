"""dgo-cloud.billing — the plan, the checkout, the month, the wallet's top-ups (DGO-1893).

THE PLAN (the owner, 2026-11-14): «the basic dgo plan is 99 shekels a month you get a server and 24 shekels of tokens
in our llm router they can use on any model». Prices are what the buyer pays, VAT included (a consumer price in
Israel); the tax invoice Cardcom issues splits the VAT out by itself.

THE MONTH. A subscription's period is a calendar month from the day it was paid. The first month is charged on the
hosted page (which also saves the card as a token); every later month is charged on the token by `renew_due()`,
which the server's scheduler runs every few minutes. A charge is idempotent by `sub<id>-p<period>`.
  - paid       → the next period; the plan's unused credit of the period that ended expires, a fresh ₪24 arrives
  - declined   → past_due; tried again after 1 and 3 days; on the third decline the subscription is cancelled and
                 its server suspended (the data kept 14 days, `DGOCLOUD_KEEP_DAYS`)
  - «cancel»   → cancel_at_end: the server runs to the end of what was paid, then the subscription ends
Nothing here talks to a server: `on_paid(sub)` / `on_stopped(sub, why)` are the provisioner's, wired by server.py.
"""
import os

import cardcom
from store import Refused, NotFound, now, later, parse, add_month, shekels, dt

PLANS = {
    "basic": {
        "id": "basic", "name": "DGO Cloud בסיסי", "price": int(os.environ.get("DGOCLOUD_PRICE_BASIC", "9900")),
        "credit": int(os.environ.get("DGOCLOUD_CREDIT_BASIC", "2400")),
        "server": os.environ.get("DGOCLOUD_SERVER_LABEL", "שרת פרטי: 2 מעבדים · 8GB זיכרון · 100GB NVMe"),
        "features": ["לשכה דיגיטלית מלאה משלך, מאובטחת, בכתובת משלך", "שרת פרטי שרק שלך",
                     "₪24 בחודש לבינה מלאכותית — DeepSeek, Claude, OpenAI, כל מודל",
                     "עדכונים, גיבויים ואבטחה — אנחנו מנהלים", "ביטול בכל רגע, בלי התחייבות"],
    },
}
TOPUPS = (5000, 10000, 20000)          # ₪50 / ₪100 / ₪200 of AI credit, never expires
RETRY_DAYS = (1, 3)                    # after a decline: try again a day later, then three days later, then stop
KEEP_DAYS = int(os.environ.get("DGOCLOUD_KEEP_DAYS", "14"))


def _age(iso):
    """Seconds since an ISO time (a row with no time is old)."""
    t = parse(iso)
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() if t else 10 ** 9


def plan(pid):
    p = PLANS.get(pid)
    if not p:
        raise Refused("אין תוכנית כזאת.")
    return p


def public_plans():
    return [{"id": p["id"], "name": p["name"], "price": p["price"], "price_he": shekels(p["price"]),
             "credit": p["credit"], "credit_he": shekels(p["credit"]), "server": p["server"],
             "features": p["features"]} for p in PLANS.values()]


class Billing:
    def __init__(self, store, public_url, on_paid=None, on_stopped=None, log=print):
        self.s = store
        self.url = public_url.rstrip("/")
        self.on_paid = on_paid or (lambda sub: None)
        self.on_stopped = on_stopped or (lambda sub, why: None)
        self.log = log

    # ── reading ──────────────────────────────────────────────────────────────────────────────────────
    def subs(self, aid):
        return self.s.all("SELECT * FROM subscriptions WHERE account_id=? ORDER BY id DESC", aid)

    def current(self, aid):
        """The subscription that counts for an account: the newest that is not pending/ended, else the newest."""
        rows = self.subs(aid)
        for r in rows:
            if r["status"] in ("active", "past_due", "cancelled") and not self._over(r):
                return r
        return rows[0] if rows else None

    def _over(self, sub):
        end = parse(sub.get("period_end"))
        return sub["status"] in ("cancelled",) and end and end <= dt.datetime.now(dt.timezone.utc)

    def entitled(self, aid):
        """May this account use what it pays for (its server, the router)? active, or past_due inside the retries,
        or cancelled with paid time left."""
        sub = self.current(aid)
        if not sub:
            return False
        if sub["status"] in ("active", "past_due"):
            return True
        end = parse(sub.get("period_end"))
        return sub["status"] == "cancelled" and bool(end and end > dt.datetime.now(dt.timezone.utc))

    # ── buying ───────────────────────────────────────────────────────────────────────────────────────
    def checkout(self, acc, plan_id):
        """A pending subscription and its first payment, and the Cardcom page to pay it on → the page's URL."""
        if not cardcom.configured():
            raise Refused("התשלום עוד לא פתוח — נסו שוב בעוד מעט, או כתבו לנו: person11@example.com")
        p = plan(plan_id)
        live = [s for s in self.subs(acc["id"]) if s["status"] in ("active", "past_due")]
        if live:
            raise Refused("כבר יש לך מנוי פעיל. לשרת נוסף — כתבו לנו.")
        with self.s.tx() as c:
            # Another try reuses the pending subscription, and an earlier page is NEVER abandoned here: its buyer may
            # still pay it in another tab, and a page marked abandoned would then be money taken for nothing. If two
            # pages are paid, verify() keeps the first and flags the second for a refund (pay.double).
            row = c.execute("SELECT id FROM subscriptions WHERE account_id=? AND status='pending' ORDER BY id DESC "
                            "LIMIT 1", (acc["id"],)).fetchone()
            if row:
                sid = row["id"]
                c.execute("UPDATE subscriptions SET plan=?, price=?, credit=?, updated_at=? WHERE id=?",
                          (p["id"], p["price"], p["credit"], now(), sid))
            else:
                sid = c.execute("INSERT INTO subscriptions(account_id,plan,status,price,credit,created_at,updated_at) "
                                "VALUES (?,?,?,?,?,?,?)", (acc["id"], p["id"], "pending", p["price"], p["credit"],
                                                           now(), now())).lastrowid
            pid = c.execute("INSERT INTO payments(account_id,subscription_id,kind,amount,status,period,created_at)"
                            " VALUES (?,?,?,?,?,?,?)", (acc["id"], sid, "first", p["price"], "pending", 1,
                                                        now())).lastrowid
            c.execute("UPDATE payments SET ext_id=? WHERE id=?", (f"first{pid}", pid))
        return self._page(acc, pid, p["price"], [(f"{p['name']} — חודש ראשון", p["price"] / 100)], token=True)

    def topup(self, acc, amount):
        if not cardcom.configured():
            raise Refused("התשלום עוד לא פתוח — נסו שוב בעוד מעט.")
        amount = int(amount)
        if amount not in TOPUPS:
            raise Refused("אפשר לטעון ₪50, ₪100 או ₪200.")
        if not self.entitled(acc["id"]):
            raise Refused("טעינת קרדיט פתוחה למנויים פעילים.")
        pid = self.s.run("INSERT INTO payments(account_id,kind,amount,status,created_at) VALUES (?,?,?,?,?)",
                         acc["id"], "topup", amount, "pending", now())
        self.s.run("UPDATE payments SET ext_id=? WHERE id=?", f"top{pid}", pid)
        return self._page(acc, pid, amount, [(f"קרדיט בינה מלאכותית — ₪{shekels(amount)}", amount / 100)], token=False)

    def _page(self, acc, pid, amount, lines, token):
        doc = cardcom.document(acc.get("company") or acc["name"], acc["email"], acc.get("tax_id"), lines)
        try:
            lp, url = cardcom.create_page(amount, f"p{pid}", f"{self.url}/pay/return?p={pid}",
                                          f"{self.url}/pay/return?p={pid}&failed=1",
                                          f"{self.url}/api/cardcom/webhook", acc["email"], doc, token=token)
        except cardcom.PayError as e:
            self.s.run("UPDATE payments SET status='failed', error=? WHERE id=?", str(e)[:500], pid)
            self.log(f"checkout p{pid}: {e}")
            raise Refused("דף התשלום לא נפתח כרגע. נסו שוב בעוד דקה.")
        self.s.run("UPDATE payments SET lp_id=? WHERE id=?", lp, pid)
        self.s.audit(f"a:{acc['id']}", "pay.page", f"p:{pid}", {"amount": amount})
        return {"payment": pid, "url": url}

    def verify(self, pid, lp_id=None):
        """Ask Cardcom what became of a payment's page, and act on it ONCE. Safe to call any number of times, from
        the return page, the webhook and the scheduler alike → the payment row."""
        pay = self.s.one("SELECT * FROM payments WHERE id=?", pid)
        if not pay:
            raise NotFound("אין תשלום כזה")
        if lp_id and lp_id != pay["lp_id"]:
            raise Refused("הדף הזה לא שייך לתשלום הזה.")
        # A page counts until Cardcom says it is paid: a FAILED page may still be paid (the buyer retries with another
        # card on the same page) and an ABANDONED one too (a tab left open) — for two days, then they are final.
        if pay["status"] not in ("pending", "failed", "abandoned") or not pay["lp_id"]:
            return pay
        if pay["status"] != "pending" and _age(pay["created_at"]) > 2 * 86400:
            return pay
        try:
            r = cardcom.page_result(pay["lp_id"])
        except cardcom.PayError as e:
            self.log(f"verify p{pid}: {e}")
            return pay
        if r["paid"] is None:
            return pay
        if not r["paid"]:
            self.s.run("UPDATE payments SET status='failed', error=? WHERE id=? AND status='pending'",
                       (r.get("error") or "")[:500], pid)
            self.s.audit("cardcom", "pay.failed", f"p:{pid}", {"error": r.get("error")})
            return self.s.one("SELECT * FROM payments WHERE id=?", pid)
        if r.get("return") and r["return"] != f"p{pid}":
            self.log(f"verify p{pid}: ReturnValue {r['return']!r} is not ours")
            return pay
        if abs(float(r.get("amount") or 0) - pay["amount"] / 100) > 0.005:
            self.log(f"verify p{pid}: amount {r.get('amount')} != {pay['amount'] / 100}")
            self.s.run("UPDATE payments SET error=? WHERE id=?", f"amount mismatch {r.get('amount')}", pid)
            return pay
        sub = None
        with self.s.tx() as c:
            cur = c.execute("UPDATE payments SET status='paid', tran_id=?, doc_number=?, doc_url=?, card_last4=?, "
                            "paid_at=?, error='' WHERE id=? AND status IN ('pending','failed','abandoned')",
                            (r["tran_id"], r["doc_number"], r["doc_url"], r["last4"], now(), pid))
            if cur.rowcount != 1:                     # someone else took it a moment ago
                return self.s.one("SELECT * FROM payments WHERE id=?", pid)
            if pay["kind"] == "topup":
                self.s.credit(pay["account_id"], "topup", pay["amount"], f"p:{pid}", "טעינת קרדיט", c)
            elif pay["kind"] == "first":
                start = now()
                end = add_month(start)
                act = c.execute("UPDATE subscriptions SET status='active', card_token=?, card_exp=?, card_last4=?, "
                                "period=1, period_start=?, period_end=?, next_charge_at=?, failures=0, last_error='', "
                                "updated_at=? WHERE id=? AND status='pending'",
                                (r["token"], r["card_exp"], r["last4"], start, end, end, now(), pay["subscription_id"]))
                if act.rowcount == 1:
                    s = c.execute("SELECT * FROM subscriptions WHERE id=?", (pay["subscription_id"],)).fetchone()
                    self.s.credit(pay["account_id"], "plan", s["credit"], f"sub:{s['id']}:p1", "קרדיט החודש", c)
                    sub = dict(s)
                else:
                    # a second page of the same purchase was paid too (two tabs): the money is real, the month is
                    # already given — kept as paid, flagged for the admin to refund
                    c.execute("UPDATE payments SET error=? WHERE id=?", ("תשלום כפול — להחזיר ללקוח", pid))
                    self.s.audit("cardcom", "pay.double", f"p:{pid}", {"amount": pay["amount"]}, "", c)
            elif pay["kind"] == "renewal":
                # an overdue month paid on a page with a (new) card: the month advances, the new card is kept
                s = c.execute("SELECT * FROM subscriptions WHERE id=?", (pay["subscription_id"],)).fetchone()
                if s and s["status"] in ("past_due", "active") and pay["period"] == s["period"] + 1:
                    self._advance(c, dict(s), pid, r.get("token") or s["card_token"], r.get("card_exp") or s["card_exp"],
                                  r.get("last4") or s["card_last4"])
                    sub = dict(s, status="active") if s["status"] == "past_due" else None
                else:
                    c.execute("UPDATE payments SET error=? WHERE id=?", ("תשלום כפול — להחזיר ללקוח", pid))
                    self.s.audit("cardcom", "pay.double", f"p:{pid}", {"amount": pay["amount"]}, "", c)
            self.s.audit("cardcom", "pay.paid", f"p:{pid}", {"amount": pay["amount"], "tran": r["tran_id"]}, "", c)
        if sub:
            self._safe(self.on_paid, sub)
        return self.s.one("SELECT * FROM payments WHERE id=?", pid)

    def sweep_pending(self):
        """A page whose buyer closed the tab before coming back, and whose webhook never reached us: ask Cardcom
        about every page younger than a day, oldest first; older ones are abandoned."""
        for p in self.s.all("SELECT id, status, created_at FROM payments WHERE lp_id<>'' AND (status='pending' OR "
                            "(status='failed' AND created_at > ?)) ORDER BY id", later(days=-1)):
            if _age(p["created_at"]) < 60:
                continue
            p = self.verify(p["id"])              # Cardcom is asked BEFORE a page is called abandoned
            if p["status"] == "pending" and _age(p["created_at"]) > 86400:
                self.s.run("UPDATE payments SET status='abandoned' WHERE id=? AND status='pending'", p["id"])

    def pay_overdue(self, acc):
        """A past-due buyer pays the overdue month now, on a page, with any card — which becomes the card on file."""
        if not cardcom.configured():
            raise Refused("התשלום עוד לא פתוח — נסו שוב בעוד מעט.")
        sub = self.current(acc["id"])
        if not sub or sub["status"] != "past_due":
            raise Refused("אין חיוב פתוח לשלם.")
        period = sub["period"] + 1
        pid = self.s.run("INSERT INTO payments(account_id,subscription_id,kind,amount,status,period,created_at) "
                         "VALUES (?,?,?,?,?,?,?)", acc["id"], sub["id"], "renewal", sub["price"], "pending", period, now())
        self.s.run("UPDATE payments SET ext_id=? WHERE id=?", f"card{pid}", pid)
        p = PLANS.get(sub["plan"], {"name": sub["plan"]})
        return self._page(acc, pid, sub["price"], [(f"{p['name']} — חודש {period}", sub["price"] / 100)], token=True)

    def _advance(self, c, sub, pid, token, card_exp, last4):
        """A paid month (inside the caller's transaction): the next period, the plan credit renewed, the card kept."""
        period = sub["period"] + 1
        start = sub["period_end"]
        end = add_month(start)
        c.execute("UPDATE subscriptions SET status='active', period=?, period_start=?, period_end=?, next_charge_at=?, "
                  "failures=0, last_error='', card_token=?, card_exp=?, card_last4=?, updated_at=? WHERE id=?",
                  (period, start, end, end, token, card_exp, last4, now(), sub["id"]))
        # the scheduler's own attempt at this month (sub<id>-p<n>) is no longer owed
        c.execute("UPDATE payments SET status='abandoned' WHERE subscription_id=? AND period=? AND status='pending' "
                  "AND id<>?", (sub["id"], period, pid))
        self.s.expire_plan_credit(sub["account_id"], f"sub:{sub['id']}:p{sub['period']}", c)
        self.s.credit(sub["account_id"], "plan", sub["credit"], f"sub:{sub['id']}:p{period}", "קרדיט החודש", c)
        self.s.audit("billing", "sub.renewed", f"sub:{sub['id']}", {"period": period, "payment": pid}, "", c)

    # ── the month ────────────────────────────────────────────────────────────────────────────────────
    def renew_due(self):
        n = now()
        for sub in self.s.all("SELECT * FROM subscriptions WHERE status IN ('active','past_due','cancelled') "
                              "AND period_end IS NOT NULL AND (next_charge_at <= ? OR period_end <= ?)", n, n):
            try:
                self._renew_one(sub)
            except Exception as e:      # one bad row must never stop the others' month
                self.log(f"renew sub{sub['id']}: {e!r}")

    def _renew_one(self, sub):
        # read again: the list was read before the loop, and a cancel may have landed since (the second reader's #12)
        sub = self.s.one("SELECT * FROM subscriptions WHERE id=?", sub["id"])
        if not sub or sub["status"] not in ("active", "past_due", "cancelled"):
            return
        if sub["status"] == "cancelled" or sub["cancel_at_end"]:
            if (parse(sub["period_end"]) or dt.datetime.now(dt.timezone.utc)) <= dt.datetime.now(dt.timezone.utc):
                with self.s.tx() as c:
                    c.execute("UPDATE subscriptions SET status='ended', updated_at=? WHERE id=?", (now(), sub["id"]))
                    self.s.expire_plan_credit(sub["account_id"], f"sub:{sub['id']}:end", c)
                    self.s.audit("billing", "sub.ended", f"sub:{sub['id']}", {}, "", c)
                self._safe(self.on_stopped, sub, "ended")
            return
        if (parse(sub["next_charge_at"]) or dt.datetime.now(dt.timezone.utc)) > dt.datetime.now(dt.timezone.utc):
            return
        period = sub["period"] + 1
        ext = f"sub{sub['id']}-p{period}"
        pay = self.s.one("SELECT * FROM payments WHERE ext_id=?", ext)
        if not pay:
            pid = self.s.run("INSERT INTO payments(account_id,subscription_id,kind,amount,status,ext_id,period,"
                             "created_at) VALUES (?,?,?,?,?,?,?,?)", sub["account_id"], sub["id"], "renewal",
                             sub["price"], "pending", ext, period, now())
            pay = self.s.one("SELECT * FROM payments WHERE id=?", pid)
        elif pay["status"] == "paid":
            return
        acc = self.s.one("SELECT * FROM accounts WHERE id=?", sub["account_id"])
        p = PLANS.get(sub["plan"], {"name": sub["plan"]})
        month = dt.datetime.now(dt.timezone.utc).strftime("%m/%Y")
        doc = cardcom.document(acc.get("company") or acc["name"], acc["email"], acc.get("tax_id"),
                               [(f"{p['name']} — {month}", sub["price"] / 100)])
        r = cardcom.charge_token(sub["card_token"], sub["card_exp"], sub["price"], ext, doc) if sub["card_token"] \
            else {"paid": False, "error": "no card token"}
        if r["paid"] is None:
            # NOT a decline: no answer, or the key was already used (608). The idempotency key says what happened;
            # until it does, nothing is counted and the next cycle asks again (the second reader's #9)
            r = cardcom.lookup_ext(ext)
            if r["paid"] is None:
                self.s.run("UPDATE payments SET error=? WHERE id=?", f"unknown: {r.get('error', '')}"[:500], pay["id"])
                self.log(f"renew sub{sub['id']} p{period}: no answer yet ({r.get('error')})")
                return
        if r["paid"]:
            with self.s.tx() as c:
                c.execute("UPDATE payments SET status='paid', tran_id=?, doc_number=?, doc_url=?, card_last4=?, "
                          "paid_at=?, error='' WHERE id=?", (r["tran_id"], r["doc_number"], r["doc_url"],
                                                              sub["card_last4"], now(), pay["id"]))
                cur = c.execute("SELECT * FROM subscriptions WHERE id=?", (sub["id"],)).fetchone()
                if cur["status"] in ("active", "past_due") and cur["period"] == sub["period"]:
                    self._advance(c, dict(cur), pay["id"], cur["card_token"], cur["card_exp"], cur["card_last4"])
                else:       # cancelled while Cardcom was charging: the money is real — flagged, never lost
                    c.execute("UPDATE payments SET error=? WHERE id=?", ("חויב אחרי ביטול — להחזיר ללקוח", pay["id"]))
                    self.s.audit("billing", "pay.after_cancel", f"p:{pay['id']}", {}, "", c)
            if sub["status"] == "past_due":
                self._safe(self.on_paid, dict(sub, status="active"))
            return
        fails = sub["failures"] + 1
        with self.s.tx() as c:
            c.execute("UPDATE payments SET status=?, error=? WHERE id=?",
                      ("failed" if fails > len(RETRY_DAYS) else "pending", (r.get("error") or "")[:500], pay["id"]))
            if fails > len(RETRY_DAYS):
                c.execute("UPDATE subscriptions SET status='cancelled', failures=?, last_error=?, period_end=?, "
                          "updated_at=? WHERE id=? AND status IN ('active','past_due')",
                          (fails, (r.get("error") or "")[:300], now(), now(), sub["id"]))
                self.s.audit("billing", "sub.cancelled.unpaid", f"sub:{sub['id']}", {"error": r.get("error")}, "", c)
            else:
                c.execute("UPDATE subscriptions SET status='past_due', failures=?, last_error=?, next_charge_at=?, "
                          "updated_at=? WHERE id=? AND status IN ('active','past_due')",
                          (fails, (r.get("error") or "")[:300], later(days=RETRY_DAYS[fails - 1]), now(), sub["id"]))
                self.s.audit("billing", "sub.declined", f"sub:{sub['id']}", {"try": fails, "error": r.get("error")},
                             "", c)
        if fails > len(RETRY_DAYS):
            self._safe(self.on_stopped, sub, "unpaid")

    def cancel(self, aid, sid, actor):
        sub = self.s.one("SELECT * FROM subscriptions WHERE id=? AND account_id=?", sid, aid)
        if not sub or sub["status"] not in ("active", "past_due"):
            raise Refused("אין מנוי פעיל לבטל.")
        with self.s.tx() as c:
            c.execute("UPDATE subscriptions SET status='cancelled', cancel_at_end=1, updated_at=? WHERE id=?",
                      (now(), sid))
            self.s.audit(actor, "sub.cancel", f"sub:{sid}", {}, "", c)
        return self.s.one("SELECT * FROM subscriptions WHERE id=?", sid)

    def resume(self, aid, sid, actor):
        """Undo a cancel before the paid month ends."""
        sub = self.s.one("SELECT * FROM subscriptions WHERE id=? AND account_id=?", sid, aid)
        if not sub or sub["status"] != "cancelled" or not sub["cancel_at_end"] or self._over(sub):
            raise Refused("אפשר לחדש רק מנוי שבוטל ועדיין בתוקף.")
        with self.s.tx() as c:
            c.execute("UPDATE subscriptions SET status='active', cancel_at_end=0, updated_at=? WHERE id=?", (now(), sid))
            self.s.audit(actor, "sub.resume", f"sub:{sid}", {}, "", c)
        return self.s.one("SELECT * FROM subscriptions WHERE id=?", sid)

    def _safe(self, fn, *a):
        try:
            fn(*a)
        except Exception as e:
            self.log(f"billing hook {getattr(fn, '__name__', fn)}: {e!r}")
