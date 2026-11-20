"""DGO Cloud (DGO-1893) — the paths money and servers move along, end to end in one process.

    python3 -m unittest apps/dgo-cloud/tests/test_cloud.py      (no network: Cardcom simulated, the provider simulated)
"""
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["CARDCOM_SIMULATE"] = "1"
os.environ["DGOCLOUD_ZONE"] = "cloud.example.test"
os.environ["DGOCLOUD_SMTP_HOST"] = "off"

import billing as bill_mod  # noqa: E402
import cardcom  # noqa: E402
import dnsd  # noqa: E402
import hostinger  # noqa: E402
import router as router_mod  # noqa: E402
from accounts import Accounts  # noqa: E402
from billing import Billing  # noqa: E402
from provision import Provisioner  # noqa: E402
from store import Refused, Store, later  # noqa: E402


class World:
    def __init__(self):
        import accounts
        accounts._TRIES.clear()            # the throttle is per process: each test's buyer is a first try
        self.dir = tempfile.mkdtemp()
        self.s = Store(os.path.join(self.dir, "t.db"))
        self.acc = Accounts(self.s)
        self.p = Provisioner(self.s, hostinger.Simulated(), "https://front.test", "https://llm.test", log=lambda *a: None)
        self.b = Billing(self.s, "https://front.test", on_paid=self.p.on_paid, on_stopped=self.p.on_stopped,
                         log=lambda *a: None)

    def buyer(self, email="person15@example.com"):
        return self.acc.signup(email, "דנה", "olive-grove-77", "93.184.216.7")

    def pay_first(self, a, ok=True):
        r = self.b.checkout(a, "basic")
        lp = self.s.one("SELECT lp_id FROM payments WHERE id=?", r["payment"])["lp_id"]
        cardcom.sim_pay(lp, ok)
        return self.b.verify(r["payment"])

    def ready_node(self):
        """A server bought, said hello, installed, ready in the pool."""
        n = self.p.order("test")
        self.p.tick()                      # booting → installing (the simulated provider is «running» at once)
        boot = None
        # the boot token is only in the install script; take it from there, as the server would
        from provision import install_script  # noqa: F401
        row = self.s.one("SELECT * FROM nodes WHERE id=?", n["id"])
        return row


class TestMoney(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def test_first_month_activates_credits_and_is_idempotent(self):
        a = self.w.buyer()
        pay = self.w.pay_first(a)
        self.assertEqual(pay["status"], "paid")
        sub = self.w.b.current(a["id"])
        self.assertEqual((sub["status"], sub["period"], sub["price"]), ("active", 1, 9900))
        self.assertTrue(sub["card_token"].startswith("simtok-"))
        self.assertEqual(self.w.s.balance(a["id"])["plan"], 2400)
        # the webhook and the return page both verify: the second does nothing
        self.w.b.verify(pay["id"])
        self.assertEqual(self.w.s.balance(a["id"])["plan"], 2400)
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM wallet")["n"], 1)

    def test_a_declined_page_activates_nothing(self):
        a = self.w.buyer()
        pay = self.w.pay_first(a, ok=False)
        self.assertEqual(pay["status"], "failed")
        self.assertEqual(self.w.b.current(a["id"])["status"], "pending")
        self.assertEqual(self.w.s.balance(a["id"])["total"], 0)

    def test_an_amount_that_is_not_ours_is_not_taken(self):
        a = self.w.buyer()
        r = self.w.b.checkout(a, "basic")
        lp = self.w.s.one("SELECT lp_id FROM payments WHERE id=?", r["payment"])["lp_id"]
        cardcom.sim_pay(lp, True)
        with cardcom._SIM_LOCK:
            cardcom._SIM[lp]["amount"] = 1.0
        self.assertEqual(self.w.b.verify(r["payment"])["status"], "pending")

    def test_two_tabs_both_paid_give_one_month_and_flag_the_second(self):
        a = self.w.buyer()
        r1 = self.w.b.checkout(a, "basic")
        r2 = self.w.b.checkout(a, "basic")                                   # a second tab, before paying the first
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM subscriptions")["n"], 1)
        for r in (r1, r2):
            lp = self.w.s.one("SELECT lp_id FROM payments WHERE id=?", r["payment"])["lp_id"]
            cardcom.sim_pay(lp, True)
            self.w.b.verify(r["payment"])
        pays = self.w.s.all("SELECT status, error FROM payments ORDER BY id")
        self.assertEqual([p["status"] for p in pays], ["paid", "paid"])     # the first tab's money is never lost
        self.assertIn("כפול", pays[1]["error"])
        self.assertEqual(self.w.s.balance(a["id"])["plan"], 2400)            # one month, one credit
        self.assertTrue(self.w.s.one("SELECT 1 x FROM audit WHERE action='pay.double'"))

    def test_a_second_live_subscription_is_refused(self):
        a = self.w.buyer()
        self.w.pay_first(a)
        with self.assertRaises(Refused):
            self.w.b.checkout(a, "basic")

    def test_renewal_charges_the_token_once_and_renews_the_credit(self):
        a = self.w.buyer()
        self.w.pay_first(a)
        self.w.s.debit(a["id"], 900, "u:1", "deepseek-chat")             # ₪9 used of the ₪24
        self.w.s.credit(a["id"], "topup", 5000, "p:x", "topup")
        self.w.s.run("UPDATE subscriptions SET next_charge_at=?, period_end=?", later(minutes=-1), later(minutes=-1))
        self.w.b.renew_due()
        self.w.b.renew_due()                                                # twice: still one charge
        sub = self.w.b.current(a["id"])
        self.assertEqual((sub["status"], sub["period"]), ("active", 2))
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM payments WHERE kind='renewal' AND status='paid'")["n"], 1)
        bal = self.w.s.balance(a["id"])
        self.assertEqual(bal["plan"], 2400)                                 # the ₪15 left expired, a fresh ₪24
        self.assertEqual(bal["topup"], 5000)                                # a top-up never expires

    def test_three_declines_cancel_and_stop_the_server(self):
        a = self.w.buyer()
        self.w.pay_first(a)
        self.w.s.run("UPDATE subscriptions SET card_token='simtok-decline'")
        for _ in range(3):
            self.w.s.run("UPDATE subscriptions SET next_charge_at=?, period_end=?", later(minutes=-1), later(minutes=-1))
            self.w.b.renew_due()
        sub = self.w.s.one("SELECT * FROM subscriptions")
        self.assertEqual(sub["status"], "cancelled")
        self.assertFalse(self.w.b.entitled(a["id"]))

    def test_cancel_runs_to_the_end_then_ends(self):
        a = self.w.buyer()
        self.w.pay_first(a)
        sub = self.w.b.current(a["id"])
        self.w.b.cancel(a["id"], sub["id"], "a:1")
        self.assertTrue(self.w.b.entitled(a["id"]))                         # paid time left
        self.w.s.run("UPDATE subscriptions SET period_end=?, next_charge_at=?", later(minutes=-1), later(minutes=-1))
        self.w.b.renew_due()
        self.assertEqual(self.w.s.one("SELECT status FROM subscriptions")["status"], "ended")
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM payments WHERE kind='renewal'")["n"], 0)
        self.assertEqual(self.w.s.balance(a["id"])["plan"], 0)

    def test_no_answer_is_not_a_decline_and_past_due_pays_with_a_new_card(self):
        a = self.w.buyer()
        self.w.pay_first(a)
        self.w.s.run("UPDATE subscriptions SET card_token='simtok-noanswer', next_charge_at=?, period_end=?",
                     later(minutes=-1), later(minutes=-1))
        self.w.b.renew_due()
        sub = self.w.b.current(a["id"])
        self.assertEqual((sub["status"], sub["failures"]), ("active", 0))   # not counted as a decline (#9)
        self.w.s.run("UPDATE subscriptions SET card_token='simtok-decline'")
        self.w.b.renew_due()
        self.assertEqual(self.w.b.current(a["id"])["status"], "past_due")
        r = self.w.b.pay_overdue(a)                                         # «לשלם עכשיו בכרטיס אחר»
        lp = self.w.s.one("SELECT lp_id FROM payments WHERE id=?", r["payment"])["lp_id"]
        cardcom.sim_pay(lp, True)
        self.w.b.verify(r["payment"])
        sub = self.w.b.current(a["id"])
        self.assertEqual((sub["status"], sub["period"], sub["failures"]), ("active", 2, 0))
        self.assertTrue(sub["card_token"].startswith("simtok-sim-"))        # the new card is the card on file
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM payments WHERE kind='renewal' AND status='paid'")["n"], 1)
        self.assertEqual(self.w.s.balance(a["id"])["plan"], 2400)

    def test_a_page_declined_then_paid_on_a_second_card_counts(self):
        a = self.w.buyer()
        r = self.w.b.checkout(a, "basic")
        lp = self.w.s.one("SELECT lp_id FROM payments WHERE id=?", r["payment"])["lp_id"]
        cardcom.sim_pay(lp, False)
        self.assertEqual(self.w.b.verify(r["payment"])["status"], "failed")
        cardcom.sim_pay(lp, True)                                           # the same page, another card (#10)
        self.assertEqual(self.w.b.verify(r["payment"])["status"], "paid")
        self.assertEqual(self.w.b.current(a["id"])["status"], "active")

    def test_debit_takes_plan_credit_first(self):
        a = self.w.buyer()
        self.w.s.credit(a["id"], "plan", 1000)
        self.w.s.credit(a["id"], "topup", 1000)
        b = self.w.s.debit(a["id"], 1500)
        self.assertEqual((b["plan"], b["topup"]), (0, 500))


class TestServers(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def _hello(self, node):
        boot = "boot-" + node["name"]
        from accounts import sha
        self.w.s.run("UPDATE nodes SET secret_hash=? WHERE id=?", "boot:" + sha(boot), node["id"])
        return self.w.p.hello(boot, {"ip": "10.0.0.9"})

    def test_pool_claim_and_the_one_time_password(self):
        self.w.p.tick()                                                     # the pool orders its first server
        node = self.w.s.one("SELECT * FROM nodes")
        self.assertEqual(node["state"], "booting")
        self.w.p.tick()
        self.assertEqual(self.w.s.one("SELECT state FROM nodes")["state"], "installing")
        h = self._hello(node)
        self.assertTrue(h["key"].startswith("dk_"))
        self.assertEqual(h["domain"], f"{node['name']}.cloud.example.test")
        with self.assertRaises(Refused):                                    # the boot token is spent
            self._hello_again = self.w.p.hello("boot-" + node["name"], {})
        n = self.w.p.node_by_secret(h["secret"])
        self.w.p.progress(n, "ready")
        self.assertEqual(self.w.s.one("SELECT state FROM nodes")["state"], "ready")
        # a buyer pays → the ready server is claimed in the same breath
        a = self.w.buyer()
        self.w.pay_first(a)
        n = self.w.s.one("SELECT * FROM nodes WHERE id=?", node["id"])
        self.assertEqual((n["state"], n["account_id"]), ("claiming", a["id"]))
        self.assertEqual(self.w.s.one("SELECT account_id FROM keys")["account_id"], a["id"])
        r = self.w.p.poll(n, {"containers": 40})
        self.assertEqual([j["verb"] for j in r["jobs"]], ["claim"])
        self.assertEqual(r["jobs"][0]["args"]["email"], a["email"])
        self.w.p.job_done(n, r["jobs"][0]["id"], True, {"user": a["email"], "password": "abcd-efgh-jkmn-pqrs"})
        self.assertEqual(self.w.s.one("SELECT state FROM nodes")["state"], "claimed")
        self.assertEqual(self.w.p.reveal_password(a["id"], n["id"])["password"], "abcd-efgh-jkmn-pqrs")
        with self.assertRaises(Refused):
            self.w.p.reveal_password(a["id"], n["id"])                      # once
        # the pool refills behind the sale
        self.w.p.tick()
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM nodes WHERE account_id IS NULL")["n"], 1)

    def test_a_buyer_with_an_empty_pool_gets_the_next_ready_server(self):
        a = self.w.buyer()
        self.w.s.set_setting("pool", 0)
        self.w.pay_first(a)
        self.assertEqual(len(self.w.p.waiting()), 1)
        self.w.p.tick()                                                     # a waiting buyer counts as a hole
        node = self.w.s.one("SELECT * FROM nodes")
        self.w.p.tick()
        h = self._hello(node)
        self.w.p.progress(self.w.p.node_by_secret(h["secret"]), "ready")
        self.w.p.tick()
        self.assertEqual(self.w.s.one("SELECT account_id FROM nodes")["account_id"], a["id"])

    def test_a_node_answers_acme_only_for_its_own_name(self):
        self.w.p.tick()
        node = self.w.s.one("SELECT * FROM nodes")
        h = self._hello(node)
        n = self.w.p.node_by_secret(h["secret"])
        self.w.p.acme_present(n, f"_acme-challenge.{node['name']}.cloud.example.test.", "tok1")
        with self.assertRaises(Refused):
            self.w.p.acme_present(n, "_acme-challenge.other.cloud.example.test.", "x")

    def test_unpaid_suspends_and_a_returning_buyer_gets_their_own_server_back(self):
        self.test_pool_claim_and_the_one_time_password()
        sub = self.w.s.one("SELECT * FROM subscriptions")
        mine = self.w.s.one("SELECT * FROM nodes WHERE account_id IS NOT NULL")
        self.w.s.run("UPDATE subscriptions SET status='ended'")
        self.w.p.on_stopped(sub, "unpaid")
        self.assertEqual(self.w.s.one("SELECT state FROM nodes WHERE id=?", mine["id"])["state"], "suspended")
        self.assertIsNone(self.w.s.one("SELECT revoked_at FROM keys WHERE node_id=?", mine["id"])["revoked_at"])
        self.assertFalse(self.w.b.entitled(sub["account_id"]))                 # the router refuses it meanwhile
        self.assertEqual(self.w.s.one("SELECT verb FROM jobs ORDER BY id DESC LIMIT 1")["verb"], "suspend")
        # a suspended server cannot fail itself from its own door (#6)
        self.w.p.progress(self.w.s.one("SELECT * FROM nodes WHERE id=?", mine["id"]), "fatal", False, "x")
        self.assertEqual(self.w.s.one("SELECT state FROM nodes WHERE id=?", mine["id"])["state"], "suspended")
        # the buyer comes back: a new subscription, the SAME server (their data), woken (#14)
        a = self.w.acc.get(sub["account_id"])
        self.w.pay_first(a)
        n = self.w.s.one("SELECT * FROM nodes WHERE id=?", mine["id"])
        new_sub = self.w.b.current(a["id"])
        self.assertEqual((n["state"], n["subscription_id"]), ("claimed", new_sub["id"]))
        self.assertEqual(self.w.s.one("SELECT verb FROM jobs ORDER BY id DESC LIMIT 1")["verb"], "resume")
        self.assertEqual(self.w.s.one("SELECT COUNT(*) n FROM nodes WHERE account_id=?", a["id"])["n"], 1)

    def test_a_silent_ready_server_is_not_handed_out_and_a_stuck_claim_is_set_aside(self):
        self.w.p.tick()
        node = self.w.s.one("SELECT * FROM nodes")
        self.w.p.tick()
        h = self._hello(node)
        self.w.p.progress(self.w.p.node_by_secret(h["secret"]), "ready")
        self.w.s.run("UPDATE nodes SET last_seen=?", later(minutes=-10))     # it stopped answering
        self.w.s.set_setting("pool", 0)
        a = self.w.buyer()
        self.w.pay_first(a)
        self.assertIsNone(self.w.s.one("SELECT account_id FROM nodes WHERE id=?", node["id"])["account_id"])
        # it answers again → claimed; its claim job then fails → set aside, the buyer waits for the next one (#7)
        self.w.s.run("UPDATE nodes SET last_seen=?", later(minutes=0))
        self.w.p.tick()
        n = self.w.s.one("SELECT * FROM nodes WHERE id=?", node["id"])
        self.assertEqual(n["state"], "claiming")
        r = self.w.p.poll(n, {})
        self.w.p.job_done(n, r["jobs"][0]["id"], False, {"error": "authentik refused"})
        self.w.p.tick()
        self.assertEqual(self.w.s.one("SELECT state FROM nodes WHERE id=?", node["id"])["state"], "failed")
        self.assertEqual(len(self.w.p.waiting()), 1)


class TestDNS(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.w.s.run("INSERT INTO nodes(name,state,provider,secret_hash,ip,created_at) VALUES "
                     "('o-abc234','claimed','simulate','x','203.0.113.7','2026-11-15')")
        self.w.s.run("INSERT INTO acme(fqdn,value,node_id,created_at) VALUES "
                     "('_acme-challenge.o-abc234.cloud.example.test','v1',1,'2026-11-15')")
        self.z = dnsd.Zone(self.w.s, "cloud.example.test", "198.51.100.1", "ns-cloud.example.test")

    def ask(self, name, qtype=1):
        q = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + dnsd._name(name.split(".")) + struct.pack("!HH", qtype, 1)
        r = self.z.answer(q)
        return struct.unpack("!HHHHHH", r[:12]), r

    def test_names(self):
        (qid, flags, _, an, ns, _), r = self.ask("console.o-abc234.cloud.example.test")
        self.assertEqual((qid, flags & 0xF, an), (0x1234, 0, 1))
        self.assertIn(socket.inet_aton("203.0.113.7"), r)
        (_, flags, _, an, ns, _), _ = self.ask("nobody.cloud.example.test")
        self.assertEqual((flags & 0xF, an, ns), (3, 0, 1))                  # NXDOMAIN with the SOA
        (_, flags, _, an, _, _), _ = self.ask("example.com")
        self.assertEqual(flags & 0xF, 5)                                    # REFUSED: not ours
        (_, flags, _, an, _, _), r = self.ask("_acme-challenge.o-abc234.cloud.example.test", 16)
        self.assertEqual(an, 1)
        self.assertIn(b"\x02v1", r)
        (_, flags, _, an, _, _), r = self.ask("cloud.example.test", 2)
        self.assertEqual(an, 1)
        (_, flags, _, an, _, _), r = self.ask("cloud.example.test", 1)
        self.assertIn(socket.inet_aton("198.51.100.1"), r)
        # a RESPONSE (QR=1) is never answered: no ping-pong between two servers (#15)
        q = struct.pack("!HHHHHH", 1, 0x8100, 1, 0, 0, 0) + dnsd._name("cloud.example.test".split(".")) + \
            struct.pack("!HH", 1, 1)
        self.assertIsNone(self.z.answer(q, udp=True))

    def test_udp_answers_over_512_bytes_are_truncated(self):
        for i in range(4):
            self.w.s.run("INSERT INTO acme(fqdn,value,node_id,created_at) VALUES (?,?,1,'t')",
                         "_acme-challenge.o-abc234.cloud.example.test", "x" * 200)
        q = struct.pack("!HHHHHH", 9, 0x0100, 1, 0, 0, 0) + \
            dnsd._name("_acme-challenge.o-abc234.cloud.example.test".split(".")) + struct.pack("!HH", 16, 1)
        r = self.z.answer(q, udp=True)
        self.assertLessEqual(len(r), 512)
        self.assertTrue(struct.unpack("!H", r[2:4])[0] & 0x0200)            # TC: ask again over TCP
        self.assertGreater(len(self.z.answer(q, udp=False)), 512)


class TestRouter(unittest.TestCase):
    def test_translation_both_ways(self):
        req = {"model": "claude-sonnet-5-5", "temperature": 0.2, "stream": True, "max_tokens": 100,
               "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"},
                            {"role": "assistant", "content": None, "tool_calls": [
                                {"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{\"a\":1}"}}]},
                            {"role": "tool", "tool_call_id": "t1", "content": "42"},
                            {"role": "user", "content": [{"type": "text", "text": "and?"},
                                                         {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]}],
               "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
               "tool_choice": "required"}
        out = router_mod.openai_to_anthropic(req)
        self.assertNotIn("temperature", out)
        self.assertEqual(out["system"], "be brief")
        self.assertEqual([m["role"] for m in out["messages"]], ["user", "assistant", "user"])
        self.assertEqual(out["messages"][1]["content"][0]["type"], "tool_use")
        self.assertEqual(out["messages"][2]["content"][0]["type"], "tool_result")       # merged into one user turn
        self.assertEqual(out["messages"][2]["content"][2]["source"]["media_type"], "image/png")
        self.assertEqual(out["tool_choice"], {"type": "auto"})
        back = router_mod.anthropic_to_openai({"id": "m1", "content": [{"type": "text", "text": "ok"},
                                                                       {"type": "tool_use", "id": "t2", "name": "g",
                                                                        "input": {"x": 2}}],
                                               "stop_reason": "tool_use", "usage": {"input_tokens": 10,
                                                                                    "output_tokens": 5}}, "claude-x")
        self.assertEqual(back["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(back["usage"]["total_tokens"], 15)

    def test_cost(self):
        p = {"in": 2.0, "cached": 0.2, "out": 10.0}
        agorot, micros = router_mod.cost_agorot(p, 3.75, 0.10, inp=1_000_000, out=100_000)
        self.assertEqual(micros, 3_000_000)                                 # $2 + $1
        self.assertEqual(agorot, 1238)                                      # 3 × 3.75 × 1.1 = ₪12.375 → 1238

    def test_refuses_without_credit_and_meters_a_call(self):
        w = World()
        a = w.buyer()
        w.pay_first(a)
        key = "dk_" + "x" * 40
        from accounts import sha
        w.s.run("INSERT INTO keys(prefix,hash,account_id,created_at) VALUES (?,?,?,?)", key[:10], sha(key), a["id"], "t")
        r = router_mod.Router(w.s, w.b)

        class Up:
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self):
                return json.dumps({"id": "x", "choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 500,
                                                                       "prompt_cache_hit_tokens": 200}}).encode()

        class Out:
            def __init__(self):
                self.body = b""

            def start(self, s, hh):
                self.status = s

            def write(self, b):
                self.body += b

            def done(self):
                pass

        with mock.patch.dict(os.environ, {"ROUTER_DEEPSEEK_KEY": "sk-test", "ROUTER_ANTHROPIC_KEY": "sk-test"}), \
                mock.patch.object(r, "_open",
                                                                                               return_value=Up()):
            o = Out()
            body = json.dumps({"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]}).encode()
            r.handle("/chat/completions", {"Authorization": "Bearer " + key}, lambda: body, o)
            self.assertEqual(o.status, 200)
            u = w.s.one("SELECT * FROM usage")
            self.assertEqual((u["in_tokens"], u["out_tokens"], u["cached_tokens"]), (1000, 500, 200))
            self.assertGreater(u["cost"], 0)
            self.assertEqual(w.s.balance(a["id"])["plan"], 2400 - u["cost"])
            # a call that MAY cost more than is left is refused before it is sent (#13): 128k tokens of Fable's output
            # are 128,000 × $50/M = $6.40 → ₪26.40 at 3.75 + 10%, above the ₪23.97 left
            big = json.dumps({"model": "claude-fable-5-1", "max_tokens": 128000, "messages": []}).encode()
            with self.assertRaises(router_mod.RouterError) as e:
                r.handle("/chat/completions", {"Authorization": "Bearer " + key}, lambda: big, Out())
            self.assertEqual(e.exception.status, 402)
            # server-side tools are billed outside the price table: refused
            web = json.dumps({"model": "claude-opus-5-5", "tools": [{"type": "web_search_20260209", "name": "w"}],
                              "messages": []}).encode()
            with self.assertRaises(router_mod.RouterError) as e:
                r.handle("/v1/messages", {"Authorization": "Bearer " + key}, lambda: web, Out())
            self.assertEqual(e.exception.status, 400)
            w.s.debit(a["id"], 100000)
            with self.assertRaises(router_mod.RouterError) as e:
                r.handle("/chat/completions", {"Authorization": "Bearer " + key}, lambda: b"{}", Out())
            self.assertEqual(e.exception.status, 402)
            with self.assertRaises(router_mod.RouterError) as e:
                r.handle("/chat/completions", {"Authorization": "Bearer dk_nope"},
                         lambda: self.fail("the body is read before the key is checked"), Out())
            self.assertEqual(e.exception.status, 401)
            w.s.run("UPDATE accounts SET status='disabled'")
            with self.assertRaises(router_mod.RouterError) as e:
                r.handle("/chat/completions", {"Authorization": "Bearer " + key}, lambda: b"{}", Out())
            self.assertEqual(e.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
