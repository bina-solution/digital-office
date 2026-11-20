"""dgo-cloud.provision — client servers: the warm pool, the claim, and the door a node's agent knocks on (DGO-1893).

WHY A POOL. A fresh DGO's first `bbox run` builds its images: 10–15 minutes on a small machine, and Hostinger needs
about 2 more to hand the server over. The owner asked for «a new secured dgo in seconds». So servers are bought and
installed AHEAD of the sale — `pool` of them stand ready (named, certified, running, the router key in place) — and
paying only CLAIMS one: the buyer becomes the office's admin, the key starts spending the buyer's wallet. Seconds.
The pool refills behind the sale.

A NODE'S LIFE (nodes.state):
  ordering    the front asked the provider for a server
  booting     the provider is setting it up (Hostinger: `initial` → `running`)
  installing  our install script runs on it (install.sh): Docker, the public release, one wildcard certificate,
              `bbox run`. It reports each step through /api/node/progress
  ready       in the pool: running, healthy, nobody's
  claiming    a buyer paid; the agent is making them the admin
  claimed     someone's DGO
  suspended   unpaid or ended: stopped, data kept `keep_days`
  destroying / destroyed   released at the provider
  failed      a step gave up (the admin sees why, and can retry or release)

THE AGENT (node/agent.py, a systemd service on the node) DIALS OUT: no inbound port, no SSH key on this side.
  POST /api/node/hello   the one-time BOOT token from the install script → the node's lasting secret + its router key
  POST /api/node/poll    health in, queued jobs out (every 3 s in the pool, 30 s once claimed)
  POST /api/node/job/<id>  a job's answer
  POST /api/node/progress  an install step
  POST /api/acme/present|cleanup   lego's httpreq DNS-01 (basic auth: node name + secret) — dnsd.py serves it
The verbs a node obeys are a closed list (agent.py VERBS): claim, password, suspend, resume, update, health. Nothing
here can ask a node to run an arbitrary command.
"""
import json
import os
import re
import secrets
import threading

from accounts import send_mail, sha
from store import Refused, NotFound, now, later, parse, dt

ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"         # no l/1/o/0: a name a person reads aloud
POLL_POOL = 3
POLL_CLAIMED = 30
INSTALL_TIMEOUT_MIN = int(os.environ.get("DGOCLOUD_INSTALL_TIMEOUT_MIN", "75"))
VERBS = ("claim", "password", "suspend", "resume", "update", "health")


def zone():
    return os.environ.get("DGOCLOUD_ZONE", "cloud.digital-office.co.il").strip(".").lower()


def node_domain(name, ip=""):
    """`<name>.<zone>` — or, for a laptop or a test (DGOCLOUD_ZONE=sslip.io), the address's own public name
    `<a-b-c-d>.sslip.io`, which resolves with no record of ours; traefik's HTTP-01 then certifies each host against a
    Let's Encrypt quota sslip.io shares with the world (it is not on the Public Suffix List): never for a sale."""
    if zone() == "sslip.io":
        return f"{(ip or '0.0.0.0').replace('.', '-')}.sslip.io"
    return f"{name}.{zone()}"


def console_url(node):
    return f"https://console.{node_domain(node['name'], node.get('ip', ''))}"


RELEASE = os.environ.get("DGOCLOUD_RELEASE", "https://github.com/bina-solution/digital-office")
RELEASE_BRANCH = os.environ.get("DGOCLOUD_RELEASE_BRANCH", "main")
# pinned by tag (G15); lego's httpreq provider is the DNS-01 path to the front
LEGO_IMAGE = os.environ.get("DGOCLOUD_LEGO_IMAGE", "goacme/lego:v4.20.4")


class Provisioner:
    def __init__(self, store, provider, public_url, llm_url, log=print):
        self.s = store
        self.p = provider
        self.url = public_url.rstrip("/")
        self.llm = llm_url.rstrip("/")
        self.log = log
        self.lock = threading.Lock()

    # ── the pool ─────────────────────────────────────────────────────────────────────────────────────
    def pool_target(self):
        return int(self.s.setting("pool", int(os.environ.get("DGOCLOUD_POOL", "1"))))

    def counts(self):
        rows = self.s.all("SELECT state, COUNT(*) n FROM nodes WHERE account_id IS NULL GROUP BY state")
        return {r["state"]: r["n"] for r in rows}

    def tick(self):
        """One pass of the scheduler: move every node forward one step, keep the pool full, hand waiting buyers a
        server. Never raises (one node's trouble is that node's `last_error`)."""
        if not self.lock.acquire(blocking=False):
            return
        try:
            for n in self.s.all("SELECT * FROM nodes WHERE state IN ('ordering','booting','installing')"):
                try:
                    self._advance(n)
                except Exception as e:
                    self.s.run("UPDATE nodes SET last_error=? WHERE id=?", f"{type(e).__name__}: {e}"[:500], n["id"])
            self._unstick_claims()
            self._serve_waiting()
            self._refill()
            self._expire_suspended()
        finally:
            self.lock.release()

    def _refill(self):
        if not self.p or not self.p.configured() or self.s.setting("pool_paused", False):
            return
        if self.p.name != "simulate" and not os.environ.get("DGOCLOUD_OPS_KEY"):
            return                  # order() says why when a person asks; the scheduler just does not buy
        c = self.counts()
        coming = sum(c.get(k, 0) for k in ("ordering", "booting", "installing", "ready"))
        # a buyer already waiting counts as a hole in the pool, too
        waiting = len(self.waiting())
        if coming < self.pool_target() + waiting and c.get("ordering", 0) + c.get("booting", 0) < 2:
            if self.s.one("SELECT COUNT(*) n FROM nodes WHERE state='failed' AND created_at > ?",
                          later(hours=-6))["n"] >= 3:
                return              # three failures in six hours: stop buying until a person looks
            self.order("pool")

    def order(self, actor):
        """Buy one server for the pool → the node row."""
        if not self.p or not self.p.configured():
            raise Refused("ספק השרתים לא מוגדר (HOSTINGER_API_TOKEN).")
        if self.p.name != "simulate" and not os.environ.get("DGOCLOUD_OPS_KEY"):
            # the host baseline (bbox onboarding) refuses to make SSH keys-only with no root key, and the office then
            # never starts: say it before a server is bought, not 15 minutes into its install
            raise Refused("חסר DGOCLOUD_OPS_KEY (המפתח הציבורי של צוות התפעול) — בלעדיו ההתקנה נעצרת.")
        name = "o-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
        boot = secrets.token_urlsafe(24)
        with self.s.tx() as c:
            nid = c.execute("INSERT INTO nodes(name,state,provider,secret_hash,created_at,progress) "
                            "VALUES (?,?,?,?,?,?)", (name, "ordering", self.p.name, "boot:" + sha(boot), now(),
                                                     "הוזמן")).lastrowid
            self.s.audit(actor, "node.order", f"n:{nid}", {"name": name}, "", c)
        script = install_script(self.url, name, boot)
        try:
            r = self.p.create(name, name if zone() == "sslip.io" else node_domain(name), script)
        except Exception as e:
            self.s.run("UPDATE nodes SET state='failed', last_error=? WHERE id=?", str(e)[:500], nid)
            self.s.audit(actor, "node.order.failed", f"n:{nid}", {"error": str(e)[:300]})
            if getattr(e, "unknown", False):
                # the provider may have sold us a server we do not track: buy nothing more until a person checked
                self.s.set_setting("pool_paused", True)
                self.s.audit("pool", "pool.paused", "pool", {"why": f"purchase unknown for {name}: look in hPanel"})
            raise
        self.s.run("UPDATE nodes SET state='booting', provider_id=?, datacenter=?, plan=?, meta=?, progress=? WHERE id=?",
                   r["ref"], r.get("datacenter", ""), r.get("plan", ""), json.dumps(
                       {"script_id": r.get("script_id"), "setup": r.get("setup")}), "השרת נקנה — מחכים לספק", nid)
        return self.s.one("SELECT * FROM nodes WHERE id=?", nid)

    def _advance(self, n):
        age = (dt.datetime.now(dt.timezone.utc) - (parse(n["created_at"]) or dt.datetime.now(dt.timezone.utc)))
        if n["state"] in ("booting", "installing") and age.total_seconds() > INSTALL_TIMEOUT_MIN * 60:
            self.s.run("UPDATE nodes SET state='failed', last_error=? WHERE id=?",
                       f"not ready after {INSTALL_TIMEOUT_MIN} min (last step: {n['progress'][:80]})", n["id"])
            self.s.audit("pool", "node.timeout", f"n:{n['id']}")
            return
        if n["state"] != "booting":
            return
        try:
            meta = json.loads(n["meta"] or "{}")
        except ValueError:
            meta = {}
        st = self.p.status(n["provider_id"], meta.get("setup"))
        if st["ref"] != n["provider_id"]:
            self.s.run("UPDATE nodes SET provider_id=? WHERE id=?", st["ref"], n["id"])
        if st["state"] == "error":
            self.s.run("UPDATE nodes SET state='failed', last_error='the provider reports error' WHERE id=?", n["id"])
            return
        if st["state"] == "running" and st["ip"]:
            # the address first (dnsd answers for the name from this row), then the fence, then the install runs
            self.s.run("UPDATE nodes SET ip=?, state='installing', progress='השרת עלה — ההתקנה מתחילה' WHERE id=?",
                       st["ip"], n["id"])
            try:
                self.p.fence(st["ref"])
            except Exception as e:
                self.s.run("UPDATE nodes SET last_error=? WHERE id=?", f"firewall: {e}"[:500], n["id"])
            if meta.get("script_id"):
                self.p.forget_script(meta["script_id"])      # it held the one-time boot token; it is spent soon

    # ── buyers ───────────────────────────────────────────────────────────────────────────────────────
    def waiting(self):
        """Paid subscriptions that have no server yet."""
        return self.s.all("SELECT s.* FROM subscriptions s WHERE s.status IN ('active','past_due') AND NOT EXISTS "
                          "(SELECT 1 FROM nodes n WHERE n.subscription_id=s.id AND n.state NOT IN "
                          "('destroying','destroyed','failed')) ORDER BY s.id")

    def on_paid(self, sub):
        """Billing: a subscription was paid (first month, back from past_due, or a returning buyer). Give it a server:
        its own, the buyer's suspended one (their data), or one from the pool — claim() decides, in one transaction."""
        return self.claim(sub)

    def claim(self, sub):
        """One transaction decides, so the payment's own call and the scheduler can never hand ONE subscription two
        servers (the second reader's #11): its live server if it has one; else the buyer's suspended server, woken
        (a returning buyer gets their data back, #14); else the oldest ready pool server that answered lately (#7)."""
        acc = self.s.one("SELECT * FROM accounts WHERE id=?", sub["account_id"])
        with self.s.tx() as c:
            mine = c.execute("SELECT * FROM nodes WHERE subscription_id=? AND state NOT IN "
                             "('destroying','destroyed','failed') ORDER BY id DESC LIMIT 1", (sub["id"],)).fetchone() \
                or c.execute("SELECT * FROM nodes WHERE account_id=? AND state='suspended' ORDER BY id DESC LIMIT 1",
                             (acc["id"],)).fetchone()
            if mine:
                if mine["state"] == "suspended":
                    c.execute("UPDATE nodes SET state='claimed', subscription_id=? WHERE id=?", (sub["id"], mine["id"]))
                    c.execute("INSERT INTO jobs(node_id,verb,args,created_at,by) VALUES (?,?,?,?,?)",
                              (mine["id"], "resume", "{}", now(), "billing"))
                    self.s.audit("billing", "node.resume", f"n:{mine['id']}", {"sub": sub["id"]}, "", c)
                return dict(mine)
            n = c.execute("SELECT * FROM nodes WHERE state='ready' AND account_id IS NULL AND last_seen > ? "
                          "ORDER BY ready_at LIMIT 1", (later(minutes=-2),)).fetchone()
            if not n:
                self.s.audit("pool", "claim.waiting", f"sub:{sub['id']}", {}, "", c)
                return None              # the pool is empty: tick() hands the next ready server to this buyer
            c.execute("UPDATE nodes SET state='claiming', account_id=?, subscription_id=?, claimed_at=? WHERE id=?",
                      (acc["id"], sub["id"], now(), n["id"]))
            c.execute("UPDATE keys SET account_id=? WHERE node_id=? AND revoked_at IS NULL", (acc["id"], n["id"]))
            c.execute("INSERT INTO jobs(node_id,verb,args,created_at,by) VALUES (?,?,?,?,?)",
                      (n["id"], "claim", json.dumps({"email": acc["email"], "name": acc["name"]}), now(), "billing"))
            self.s.audit("pool", "node.claim", f"n:{n['id']}", {"account": acc["id"], "sub": sub["id"]}, "", c)
        return self.s.one("SELECT * FROM nodes WHERE id=?", n["id"])

    def _serve_waiting(self):
        for sub in self.waiting():
            if not self.claim(sub):
                break

    def on_stopped(self, sub, why):
        """Billing: the subscription ended or went unpaid → the server stops; its data is kept `keep_days`."""
        n = self.s.one("SELECT * FROM nodes WHERE subscription_id=? AND state IN ('claimed','claiming')", sub["id"])
        if not n:
            return
        self.job(n["id"], "suspend", {"why": why}, "billing")
        with self.s.tx() as c:
            # the router key is NOT revoked: the router already refuses an account that is not paying, and the key in
            # the server's .env must work again the day the buyer comes back (a revoked key could not be re-sent)
            c.execute("UPDATE nodes SET state='suspended' WHERE id=?", (n["id"],))
            self.s.audit("billing", "node.suspend", f"n:{n['id']}", {"why": why}, "", c)

    def _unstick_claims(self):
        """A claim that failed, or a server that took the claim and fell silent: the server is set aside as failed (a
        person looks), its key unbound, and the buyer is served again by the next ready server (#7)."""
        for n in self.s.all("SELECT n.* FROM nodes n WHERE n.state='claiming' AND (n.claimed_at < ? OR EXISTS "
                            "(SELECT 1 FROM jobs j WHERE j.node_id=n.id AND j.verb='claim' AND j.state='failed'))",
                            later(minutes=-5)):
            with self.s.tx() as c:
                c.execute("UPDATE nodes SET state='failed', last_error=? WHERE id=? AND state='claiming'",
                          (f"claim did not finish (account {n['account_id']})", n["id"]))
                c.execute("UPDATE keys SET account_id=NULL WHERE node_id=?", (n["id"],))
                self.s.audit("pool", "node.claim.stuck", f"n:{n['id']}", {"account": n["account_id"]}, "", c)

    def _expire_suspended(self):
        keep = int(os.environ.get("DGOCLOUD_KEEP_DAYS", "14"))
        for n in self.s.all("SELECT n.* FROM nodes n JOIN subscriptions s ON s.id=n.subscription_id WHERE "
                            "n.state='suspended' AND s.status IN ('ended','cancelled') AND s.updated_at < ?",
                            later(days=-keep)):
            self.release(n["id"], "pool", f"suspended {keep} days")

    def release(self, nid, actor, why=""):
        n = self.s.one("SELECT * FROM nodes WHERE id=?", nid)
        if not n:
            raise NotFound("אין שרת כזה")
        self.s.run("UPDATE nodes SET state='destroying' WHERE id=?", nid)
        try:
            if self.p and n["provider_id"]:
                self.p.release(n["provider_id"])
            self.s.run("UPDATE nodes SET state='destroyed', ip='' WHERE id=?", nid)
        except Exception as e:
            self.s.run("UPDATE nodes SET last_error=? WHERE id=?", f"release: {e}"[:500], nid)
        # its secret opens no door any more (the node and ACME doors look nodes up by it)
        self.s.run("UPDATE nodes SET secret_hash=? WHERE id=?", "released:" + secrets.token_hex(16), nid)
        self.s.run("UPDATE keys SET revoked_at=? WHERE node_id=? AND revoked_at IS NULL", now(), nid)
        self.s.audit(actor, "node.release", f"n:{nid}", {"why": why})

    def job(self, nid, verb, args, actor):
        if verb not in VERBS:
            raise Refused("פעולה לא מוכרת.")
        jid = self.s.run("INSERT INTO jobs(node_id,verb,args,created_at,by) VALUES (?,?,?,?,?)", nid, verb,
                         json.dumps(args or {}), now(), actor)
        self.s.audit(actor, f"node.job.{verb}", f"n:{nid}", {"job": jid})
        return jid

    # ── the node's door ──────────────────────────────────────────────────────────────────────────────
    def node_by_secret(self, secret):
        if not secret:
            return None
        return self.s.one("SELECT * FROM nodes WHERE secret_hash=?", sha(secret))

    def hello(self, boot, facts):
        """The install script's first call: the boot token is spent; the node gets its lasting secret and its router
        key (both shown once, kept here as hashes)."""
        n = self.s.one("SELECT * FROM nodes WHERE secret_hash=?", "boot:" + sha(boot or ""))
        if not n:
            raise Refused("unknown or spent boot token")
        secret = secrets.token_urlsafe(32)
        key = "dk_" + secrets.token_urlsafe(30)
        ip = n["ip"] or re.sub(r"[^0-9.]", "", str(facts.get("ip", "")))[:15]
        with self.s.tx() as c:
            c.execute("UPDATE nodes SET secret_hash=?, last_seen=?, version=?, ip=? WHERE id=?",
                      (sha(secret), now(), str(facts.get("version", ""))[:80], ip, n["id"]))
            c.execute("INSERT INTO keys(prefix,hash,node_id,account_id,name,created_at) VALUES (?,?,?,?,?,?)",
                      (key[:10], sha(key), n["id"], n["account_id"], n["name"], now()))
            self.s.audit(f"n:{n['id']}", "node.hello", f"n:{n['id']}", {"ip": ip}, "", c)
        return {"name": n["name"], "secret": secret, "key": key, "domain": node_domain(n["name"], ip), "zone": zone(),
                "front": self.url, "llm": self.llm, "acme": self.url + "/api/acme",
                "acme_email": os.environ.get("DGOCLOUD_ACME_EMAIL", "person14@example.com"),
                "ops_key": os.environ.get("DGOCLOUD_OPS_KEY", ""), "release": RELEASE, "branch": RELEASE_BRANCH,
                "lego_image": LEGO_IMAGE}

    def progress(self, n, step, ok=True, detail=""):
        step = re.sub(r"[\r\n]+", " ", str(step or ""))[:200]
        if n["state"] not in ("ordering", "booting", "installing"):
            # an install reports only while it installs: a claimed or suspended server can never move itself to
            # failed or ready from here (the second reader's #6 — a buyer can read their own node.json)
            return
        if n["state"] in ("booting", "ordering"):
            self.s.run("UPDATE nodes SET state='installing' WHERE id=?", n["id"])
        if step == "ready" and ok:
            with self.s.tx() as c:
                c.execute("UPDATE nodes SET state='ready', ready_at=?, progress='מוכן', last_error='' WHERE id=? AND "
                          "state IN ('booting','installing')", (now(), n["id"]))
                self.s.audit(f"n:{n['id']}", "node.ready", f"n:{n['id']}", {}, "", c)
            return
        if not ok:
            self.s.run("UPDATE nodes SET last_error=?, progress=? WHERE id=?", f"{step}: {detail}"[:500], step, n["id"])
            if step == "fatal":
                self.s.run("UPDATE nodes SET state='failed' WHERE id=?", n["id"])
            return
        self.s.run("UPDATE nodes SET progress=?, last_seen=? WHERE id=?", step, now(), n["id"])

    def poll(self, n, health):
        h = json.dumps(health or {}, ensure_ascii=False)[:4000]
        self.s.run("UPDATE nodes SET last_seen=?, health=? WHERE id=?", now(), h, n["id"])
        with self.s.tx() as c:
            jobs = [dict(j) for j in c.execute("SELECT id, verb, args FROM jobs WHERE node_id=? AND state='queued' "
                                               "ORDER BY id LIMIT 5", (n["id"],)).fetchall()]
            for j in jobs:
                c.execute("UPDATE jobs SET state='sent', sent_at=? WHERE id=?", (now(), j["id"]))
        for j in jobs:
            j["args"] = json.loads(j["args"] or "{}")
        state = self.s.one("SELECT state FROM nodes WHERE id=?", n["id"])["state"]
        # re-send a job the node took and never answered (it restarted mid-job): every verb is idempotent
        stale = self.s.all("SELECT id, verb, args FROM jobs WHERE node_id=? AND state='sent' AND sent_at < ?",
                           n["id"], later(minutes=-10))
        for j in stale:
            j["args"] = json.loads(j["args"] or "{}")
            jobs.append(j)
            self.s.run("UPDATE jobs SET sent_at=? WHERE id=?", now(), j["id"])
        return {"jobs": jobs, "interval": POLL_POOL if state in ("ready", "claiming", "installing") else POLL_CLAIMED,
                "state": state}

    def job_done(self, n, jid, ok, result):
        j = self.s.one("SELECT * FROM jobs WHERE id=? AND node_id=?", jid, n["id"])
        if not j:
            raise NotFound("no such job")
        if j["state"] in ("done", "failed"):
            return
        result = result or {}
        secret_pw = result.pop("password", None)
        with self.s.tx() as c:
            c.execute("UPDATE jobs SET state=?, result=?, done_at=? WHERE id=?",
                      ("done" if ok else "failed", json.dumps(result, ensure_ascii=False)[:2000], now(), jid))
            if ok and j["verb"] in ("claim", "password") and secret_pw:
                # shown to the buyer once (their «my DGO» page), then wiped: see reveal_password()
                c.execute("UPDATE nodes SET admin_user=?, admin_pw=? WHERE id=?",
                          (str(result.get("user", ""))[:120], secret_pw, n["id"]))
            if ok and j["verb"] == "claim":
                c.execute("UPDATE nodes SET state='claimed' WHERE id=? AND state='claiming'", (n["id"],))
            if not ok:
                c.execute("UPDATE nodes SET last_error=? WHERE id=?", (f"{j['verb']}: {result.get('error', '')}"[:500],
                                                                       n["id"]))
            self.s.audit(f"n:{n['id']}", f"node.{j['verb']}.{'done' if ok else 'failed'}", f"n:{n['id']}",
                         {"job": jid}, "", c)
        if ok and j["verb"] == "claim" and n["account_id"]:
            # the buyer may have closed the tab while the pool was empty: the screen promised a mail
            acc = self.s.one("SELECT email, name FROM accounts WHERE id=?", n["account_id"])
            if acc:
                send_mail(acc["email"], "הלשכה הדיגיטלית שלך מוכנה",
                          f"שלום {acc['name']}, הלשכה שלך פועלת בכתובת console.{node_domain(n['name'], n['ip'])}. "
                          "פרטי הכניסה מחכים לך במסך שלך ב-DGO Cloud (הסיסמה מוצגת פעם אחת).",
                          self.url + "/#/app", "למסך שלי ב-DGO Cloud")

    def reveal_password(self, aid, nid):
        """The office password, once: read and wiped in one transaction."""
        with self.s.tx() as c:
            n = c.execute("SELECT * FROM nodes WHERE id=? AND account_id=?", (nid, aid)).fetchone()
            if not n:
                raise NotFound("אין שרת כזה")
            pw = n["admin_pw"]
            if not pw:
                raise Refused("הסיסמה כבר הוצגה פעם אחת. אפשר לבקש סיסמה חדשה.")
            c.execute("UPDATE nodes SET admin_pw='' WHERE id=?", (nid,))
            self.s.audit(f"a:{aid}", "node.password.shown", f"n:{nid}", {}, "", c)
        return {"user": n["admin_user"], "password": pw}

    # ── acme (lego httpreq) ──────────────────────────────────────────────────────────────────────────
    def acme_present(self, n, fqdn, value):
        fqdn = (fqdn or "").strip(".").lower()
        if fqdn != f"_acme-challenge.{node_domain(n['name'], n['ip'])}":
            raise Refused("this node may only answer for its own name")
        value = re.sub(r"[^A-Za-z0-9_-]", "", str(value))[:128]      # an ACME value is base64url: nothing else
        with self.s.tx() as c:
            # a wildcard order needs two values at once; four is room for a retry — never an amplifier's worth
            c.execute("DELETE FROM acme WHERE id IN (SELECT id FROM acme WHERE fqdn=? ORDER BY id DESC LIMIT -1 "
                      "OFFSET 3)", (fqdn,))
            c.execute("INSERT INTO acme(fqdn,value,node_id,created_at) VALUES (?,?,?,?)", (fqdn, value, n["id"], now()))

    def acme_cleanup(self, n, fqdn, value):
        self.s.run("DELETE FROM acme WHERE node_id=? AND fqdn=? AND value=?", n["id"], (fqdn or "").strip(".").lower(),
                   re.sub(r"[^A-Za-z0-9_-]", "", str(value))[:128])
        self.s.run("DELETE FROM acme WHERE created_at < ?", later(hours=-2))



def install_script(front, name, boot):
    """The node's whole first boot, ≤ 48 KB: fetch the real installer from the front (so it can be fixed in one
    place, between a sale and the next) and run it with the one-time token. Hostinger stores this text in its panel,
    so it carries only that token — spent on first use."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "node", "bootstrap.sh"), encoding="utf-8") as f:
        tpl = f.read()
    return tpl.replace("@@FRONT@@", front).replace("@@NAME@@", name).replace("@@BOOT@@", boot)
