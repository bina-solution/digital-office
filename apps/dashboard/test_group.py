"""test_group — the relay to the owner's group (group.py), its decisions proven with a clock and a list.

No redis, no Telegram: the RESP reader reads bytes a real redis sends, and the relay posts into a list. A pass
means the real group-events.json decides as its rules say: what posts, what stays on the board, a link drop
held for its return, how soon a notice may come again, the hourly cap and what it never holds back, a send
that fails tried again, an addressed notice kept off, and the line the owner reads — with no token in it.

    python3 -m unittest -v test_group          (from this directory; the standard library only)
"""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import group  # noqa: E402

RULES = group.load_rules()
BAN = [{"id": "block", "label": "חסום", "op": "security.ban", "args": {"ip": "203.0.113.9"}}]


def ev(type_="notice.new", **data):
    return {"type": type_, "title": data.pop("title", "t"), "app": "notifications",
            "data": json.dumps(data, ensure_ascii=False)}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.out, self.clock, self.saves, self.fail = [], Clock(), [], False
        self.relay = group.Relay(RULES, self.send, now=self.clock, save=lambda: self.saves.append(1))

    def send(self, text):
        if self.fail:
            return None
        self.out.append(text)
        return 1000 + len(self.out)

    def test_an_error_posts_a_warning_stays_on_the_board(self):
        self.relay.take(ev(title="הדופק: הסוכן של הלשכה לא עונה", source="raphael", source_id="pulse", level="error"))
        self.relay.take(ev(title="קונטיינר אחד לא בריא", source="raphael", source_id="c", level="warn"))
        self.relay.take(ev(title="n8n הופעל מחדש", source="autoheal", source_id="r", level="warning"))
        self.assertEqual(len(self.out), 1)
        self.assertIn("הדופק: הסוכן של הלשכה לא עונה", self.out[0])
        self.assertTrue(self.out[0].startswith("🔴 "))
        self.assertEqual(len(self.saves), 1)            # the state is written after the send

    def test_level_is_read_in_any_case(self):
        self.relay.take(ev(title="שגיאה", source="x", source_id="1", level="ERROR"))
        self.assertEqual(len(self.out), 1)

    def test_the_one_publishers_notice_level_types_are_notices(self):
        # the notice centre publishes through flowpub as `notice.<level>` (DGO-1402), its answers in data.actions
        # (DGO-1329): the relay reads it as it read `notice.new`, «חסום» and all (the release that took both, DGO-969)
        self.relay.take(ev("notice.error", title="הדופק: הסוכן של הלשכה לא עונה", source="raphael",
                           source_id="pulse", level="error", new=True))
        self.relay.take(ev("notice.warning", title="כתובת חדשה נכנסה", source="security", source_id="addr:1",
                           level="warning", new=True, actions=BAN))
        self.assertEqual(len(self.out), 2)
        self.assertTrue(self.out[0].startswith("🔴 "))
        self.assertIn("«חסום»", self.out[1])

    def test_only_notices_are_this_relays(self):
        self.relay.take({"type": "message.new", "title": "שלום", "app": "telegram",
                         "data": json.dumps({"chat_id": 1, "text": "שלום", "source": "x", "level": "error"})})
        self.relay.take({"type": "notice.new", "data": "not json"})
        self.assertEqual(self.out, [])

    def test_an_addressed_notice_never_goes_to_the_group(self):
        self.relay.take(ev(title="רק לך", source="x", source_id="p", level="error", to=["dana"]))
        self.relay.take(ev(title="ותשובה", source="security", source_id="q", level="warning", to=["dana"], actions=BAN))
        self.assertEqual(self.out, [])

    def test_app_exceptions_stay_on_the_board(self):
        for i in range(30):
            self.relay.take(ev(title=f"TypeError {i}", source="glitchtip-issue", source_id=str(i), level="error"))
        self.assertEqual(self.out, [])

    def test_a_deploy_always_posts(self):
        self.relay.take(ev(title="המשרד מעודכן שוב — hp-laptop", source="follow", source_id="follow:hp", level="info"))
        self.relay.take(ev("notice.recurred", title="המשרד מעודכן שוב — hp-laptop", source="follow",
                           source_id="follow:hp", level="info"))
        self.assertEqual(len(self.out), 2)

    def test_a_link_flicker_stays_off_a_real_drop_and_its_return_post(self):
        self.relay.take(ev(title="הקישור לMacBook נפל", source="dgo-extend", source_id="link-down-macbook-1", level="error"))
        self.clock.t += 60
        self.relay.take(ev(title="הקישור לMacBook חזר", source="dgo-extend", source_id="link-up-macbook-1", level="info"))
        self.relay.tick()
        self.assertEqual(self.out, [])
        self.assertEqual(self.relay.counts["flicker"], 1)
        self.relay.take(ev(title="הקישור ל-vps1 נפל", source="dgo-extend", source_id="link-down-vps1-2", level="error"))
        self.clock.t += 179
        self.relay.tick()
        self.assertEqual(self.out, [])
        self.clock.t += 2
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        self.assertIn("נפל", self.out[0])
        self.clock.t += 600
        self.relay.take(ev(title="הקישור ל-vps1 חזר", source="dgo-extend", source_id="link-up-vps1-2", level="info"))
        self.assertEqual(len(self.out), 2)
        self.assertTrue(self.out[1].startswith("🟢 "))

    def test_a_return_whose_drop_never_posted_stays_off(self):
        self.relay.take(ev(title="הקישור חזר", source="dgo-extend", source_id="link-up-mac-7", level="info"))
        self.assertEqual(self.out, [])
        self.assertEqual(self.relay.counts["up_without_down"], 1)

    def test_a_hold_runs_from_the_drop_not_from_when_it_was_read(self):
        # the relay was down: the drop happened 10 minutes before it read it — due at once, said with no age
        self.relay.take(ev(title="הקישור נפל", source="dgo-extend", source_id="link-down-mac-8", level="error"),
                        at=self.clock.t - 600)
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        # read two hours late: said with its age
        self.relay.take(ev(title="ישן", source="x", source_id="old", level="error"), at=self.clock.t - 3 * 3600)
        self.assertIn("(לפני 3 שע׳)", self.out[-1])

    def test_a_recurring_error_waits_its_repeat(self):
        self.relay.take(ev(title="ההפעלה מחדש נכשלה", source="autoheal", source_id="w2:failed", level="error"))
        self.clock.t += 60 * 60
        self.relay.take(ev("notice.recurred", title="ההפעלה מחדש נכשלה", source="autoheal",
                           source_id="w2:failed", level="error"))
        self.assertEqual(len(self.out), 1)
        self.assertEqual(self.relay.counts["repeat"], 1)
        self.clock.t += 181 * 60
        self.relay.take(ev("notice.recurred", title="ההפעלה מחדש נכשלה", source="autoheal",
                           source_id="w2:failed", level="error"))
        self.assertEqual(len(self.out), 2)

    def test_answers_are_written_and_kept_with_the_message(self):
        self.relay.take(ev(title="כתובת חדשה נכנסה לכניסה", source="security", source_id="addr:203.0.113.9",
                           level="warning", id=42, body="203.0.113.9 · vps1", actions=BAN))
        self.assertEqual(len(self.out), 1)
        self.assertIn("«חסום»", self.out[0])
        self.assertIn("203.0.113.9 · vps1", self.out[0])
        kept = self.relay.posted["1001"]
        self.assertEqual((kept["notice"], kept["actions"]), (42, BAN))

    def test_the_hour_is_capped_but_never_for_what_must_arrive(self):
        for i in range(25):
            self.relay.take(ev(title=f"שגיאה {i}", source="x", source_id=str(i), level="error"))
        self.assertEqual(len(self.out), RULES["per_hour"])
        self.assertEqual(self.relay.counts["capped"], 25 - RULES["per_hour"])
        self.relay.take(ev(title="פריסה", source="follow", source_id="f", level="info"))
        self.relay.take(ev(title="כתובת חדשה", source="security", source_id="a", level="warning", actions=BAN))
        self.assertEqual(len(self.out), RULES["per_hour"] + 2)
        self.clock.t += 3601
        self.relay.take(ev(title="שגיאה אחרי שעה", source="x", source_id="late", level="error"))
        self.assertIn("ועוד 5 עדכונים", self.out[-1])

    def test_the_claude_sign_out_and_its_close_both_reach_the_group(self):
        """DGO-1430: one episode is TWO lines — the red one and the one that closes it — and neither is
        held back by the hour. The close used to fall to `rest` (no post), so the red line stayed the
        group's last word about an office whose Claude had come back.

        The assertions are `assertTrue`, not `assertIn`/`assertEqual`: this class shadows `TestCase.fail`
        with the send-failure flag in setUp, and every assertion that reports through `self.fail` would come
        back as `TypeError: 'bool' object is not callable` instead of the reason it failed."""
        sid = "signed-out-1793964530"
        self.relay.take(ev(title="Claude נותק מהחשבון — הסשנים בו עצרו", source="bina-claude", source_id=sid,
                           level="error", body="נמצא מנותק ב-04.11 09:29. להתחבר: … → Continue with Google."))
        self.assertTrue(len(self.out) == 1, "the red line posts")
        self.assertTrue(self.out[0].startswith("🔴 "), "…with the error's own icon")
        self.assertTrue("Claude נותק מהחשבון" in self.out[0], "…and its title")
        self.assertTrue("04.11 09:29" in self.out[0], "…and its body, date and all")
        # the close: the SAME source and source_id at level info — its own rule, not `rest`
        self.clock.t += 600
        self.relay.take(ev("notice.recurred", title="Claude מחובר שוב", source="bina-claude", source_id=sid,
                           level="info", body="שוב מחובר. ההתראה מ-04.11 09:29 נסגרה."))
        self.assertTrue(len(self.out) == 2, "the close reaches the group too — it is not `rest`'s")
        self.assertTrue(self.out[1].startswith("🟢 "), "…as the info line it is")
        self.assertTrue("Claude מחובר שוב" in self.out[1], "…and it says the office is back")
        self.assertTrue(self.relay.counts["repeat"] == 0, "no window: the close shares the source_id")
        # …and the red line is not COUNTED. A burst of other errors fills the hour's cap WITHIN THE SAME
        # HOUR, and the sign-out line still posts. (The second reader, DGO-1430: this used to advance the
        # clock an hour before the burst, which emptied the cap by itself — the test then passed with
        # `uncapped` removed, so it proved nothing about the rule it is named for.)
        for i in range(RULES["per_hour"] + 2):
            self.relay.take(ev(title=f"שגיאה {i}", source="x", source_id=f"burst{i}", level="error"))
        self.relay.take(ev(title="Claude נותק מהחשבון — הסשנים בו עצרו", source="bina-claude",
                           source_id="signed-out-1793968130", level="error"))
        self.assertTrue("Claude נותק מהחשבון" in self.out[-1],
                        "uncapped: the office's agent stopped is never held back")
        self.assertTrue(self.relay.counts["capped"] == 2, "the cap held back the burst, and nothing else")

    def test_a_failed_send_is_tried_again_not_lost(self):
        self.fail = True
        self.relay.take(ev(title="פריסה נכשלה", source="follow", source_id="f1", level="error"))
        self.assertEqual((self.relay.counts["posted"], len(self.relay.pending)), (0, 1))
        self.clock.t += 31
        self.relay.tick()                       # still failing: waits longer
        self.assertEqual(len(self.relay.pending), 1)
        self.fail = False
        self.clock.t += 61
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        self.assertIn("פריסה נכשלה", self.out[0])
        self.assertEqual(self.relay.pending, [])

    def test_a_held_drop_whose_send_failed_still_pairs_with_its_return(self):
        self.fail = True
        self.relay.take(ev(title="נפל", source="dgo-extend", source_id="link-down-v-3", level="error"))
        self.clock.t += 181
        self.relay.tick()
        self.fail = False
        self.clock.t += 31
        self.relay.tick()
        self.relay.take(ev(title="חזר", source="dgo-extend", source_id="link-up-v-3", level="info"))
        self.assertEqual([o.split(": ")[-1] for o in self.out], ["נפל", "חזר"])

    def test_state_survives_a_restart(self):
        self.relay.take(ev(title="הקישור נפל", source="dgo-extend", source_id="link-down-mac-9", level="error"))
        st = json.loads(json.dumps(self.relay.state()))
        again = group.Relay(RULES, self.send, state=st, now=self.clock)
        self.clock.t += 200
        again.tick()
        self.assertEqual(len(self.out), 1)

    def test_a_relay_that_never_ran_says_once_that_it_is_on(self):
        self.assertTrue(self.relay.say_on())
        self.assertEqual(len(self.out), 1)
        self.assertIn("הממסר לקבוצה פעיל", self.out[0])
        st = json.loads(json.dumps(self.relay.state()))
        self.assertFalse(group.Relay(RULES, self.send, state=st, now=self.clock).say_on())
        self.assertEqual(len(self.out), 1)              # a restart is silent

    def test_a_hello_that_failed_is_sent_later_and_only_once(self):
        self.fail = True
        self.assertFalse(self.relay.say_on())
        self.fail = False
        self.assertFalse(self.relay.say_on())          # not twice: it waits in the retries
        self.clock.t += 31
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        self.assertIn("הממסר לקבוצה פעיל", self.out[0])

    def far_row(self, ts, title, **kw):
        return dict({"id": int(ts) % 1000, "source": "security", "source_id": title, "level": "warning", "title": title,
                     "body": "", "meta": {}, "last_seen": group.datetime.datetime.fromtimestamp(
                         ts, group.datetime.timezone.utc).isoformat()}, **kw)

    def test_a_linked_offices_notices_post_under_its_name_from_the_second_read_on(self):
        t = self.clock.t
        old = [self.far_row(t - 3600, "כניסה ממדינה חדשה: RU", source_id="country:RU")]
        self.assertEqual(self.relay.far("vps1", old), 0)            # the first read: the past is on its board
        self.assertEqual(self.out, [])
        new = old + [self.far_row(t + 5, "כניסה ממדינה חדשה: CN", source_id="country:CN",   # as security says it
                                  body="198.51.100.7 → mailview")]
        self.assertEqual(self.relay.far("vps1", new), 1)
        self.assertEqual(len(self.out), 1)
        self.assertTrue(self.out[0].startswith("🟡 🦅 vps1: כניסה ממדינה חדשה: CN"))
        self.assertEqual(self.relay.far("vps1", new), 0)            # read again: nothing new
        self.assertEqual(len(self.out), 1)

    def test_a_linked_offices_answers_are_kept_with_its_name(self):
        self.relay.far("vps1", [])
        self.relay.far("vps1", [self.far_row(self.clock.t + 1, "כתובת חדשה נכנסה", meta={"actions": BAN})])
        kept = self.relay.posted["1001"]
        self.assertEqual((kept["office"], kept["actions"]), ("vps1", BAN))
        self.assertIn("«חסום»", self.out[0])

    def test_a_linked_offices_link_drop_pairs_with_its_own_return_only(self):
        self.relay.far("vps1", [])
        t = self.clock.t
        down = self.far_row(t + 1, "הקישור ל-MacBook נפל", source="dgo-extend", source_id="link-down-macbook-5",
                            level="error")
        self.relay.far("vps1", [down])
        self.relay.take(ev(title="הקישור ל-MacBook חזר", source="dgo-extend", source_id="link-up-macbook-5",
                           level="info"))                         # THIS office's return, not vps1's
        self.clock.t += 200
        self.relay.tick()
        self.assertEqual(len(self.out), 1)                          # vps1's drop still posts after its hold
        self.assertIn("🦅 vps1", self.out[0])

    def drop(self, ts, observer, since, up=False, why="המנהרה פעילה, אבל הלשכה עצמה לא עונה."):
        kind = "up" if up else "down"
        return self.far_row(ts, f"הקישור לMacBook {'חזר' if up else 'נפל'}", source="dgo-extend",
                            source_id=f"link-{kind}-macbook-{since}", level="info" if up else "error",
                            body="אחרי 13 דקות שבהן לא ענתה." if up else f"מאז 12:16. {why}", id=hash((observer, kind)) % 997)

    def test_one_outage_seen_from_two_offices_is_one_line_and_one_return(self):
        from unittest import mock
        with mock.patch.object(group, "OFFICE", "hp-laptop"):         # the relay's own office, as on the HP
            self._one_outage_two_views()

    def _one_outage_two_views(self):
        t, since = self.clock.t, 1793880960
        self.relay.far("vps1", [])
        self.relay.take(ev(title="הקישור לMacBook נפל", source="dgo-extend", source_id=f"link-down-macbook-{since}",
                           level="error", body="מאז 12:16. המנהרה פעילה, אבל הלשכה עצמה לא עונה."), at=t)
        self.relay.far("vps1", [self.drop(t + 30, "vps1", since + 60, why="המנהרה לא מעבירה תנועה.")])
        self.clock.t += 181
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        line = self.out[0]
        self.assertIn("הקישור לMacBook נפל — 🐘 HP ו-🦅 vps1", line)
        self.assertIn("🐘 HP: מאז 14:16. המנהרה פעילה", line)               # each view, in the owner's clock
        self.assertIn("🦅 vps1: מאז 14:17. המנהרה לא מעבירה תנועה.", line)
        self.clock.t += 600
        self.relay.take(ev(title="הקישור לMacBook חזר", source="dgo-extend", source_id=f"link-up-macbook-{since}",
                           level="info", body="אחרי 13 דקות שבהן לא ענתה."))
        self.relay.far("vps1", [self.drop(self.clock.t + 5, "vps1", since + 60, up=True)])
        self.assertEqual(len(self.out), 2)                                    # one return, not two
        self.assertTrue(self.out[1].startswith("🟢 "))

    def test_a_second_view_after_the_drop_was_said_stays_quiet(self):
        t, since = self.clock.t, 1793880960
        self.relay.far("vps1", [])
        self.relay.take(ev(title="הקישור לMacBook נפל", source="dgo-extend", source_id=f"link-down-macbook-{since}",
                           level="error", body="מאז 12:16. x"), at=t)
        self.clock.t += 181
        self.relay.tick()
        self.clock.t += 600                                                    # vps1 tells its own view later
        self.relay.far("vps1", [self.drop(self.clock.t, "vps1", since + 300)])
        self.clock.t += 181
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        self.assertEqual(self.relay.counts["merged"], 1)

    def macbook_down(self, since, at=None):
        self.relay.take(ev(title="הקישור לMacBook נפל", source="dgo-extend", source_id=f"link-down-macbook-{since}",
                           level="error", body="מאז 12:16. המנהרה פעילה, אבל הלשכה עצמה לא עונה."), at=at or self.clock.t)

    def macbook_up(self, since):
        self.relay.take(ev(title="הקישור לMacBook חזר", source="dgo-extend", source_id=f"link-up-macbook-{since}",
                           level="info", body="אחרי 40 דקות שבהן לא ענתה."))

    def word(self, at, **kw):
        """A word as the power agent really writes it: any guard releases both (power-agent.py want_* and not guard)."""
        if kw.get("guards"):
            kw = dict({"lock": "sleep", "lid": "sleep"}, **kw)
        return dict({"at": at, "lock": "run", "lid": "run", "guards": [], "source": "battery", "percent": 60}, **kw)

    BATTERY = ["battery below 15%"]

    def one_drop(self, word, own=True):
        """A fresh relay, one MacBook drop judged by `word`: (its lines, how many sleeps it counted)."""
        out = []
        relay = group.Relay(RULES, lambda text: out.append(text) or len(out), now=self.clock)
        since = int(self.clock.t)
        relay.power["macbook"] = word(since) if callable(word) else word
        if own:
            relay.take(ev(title="הקישור לMacBook נפל", source="dgo-extend", source_id=f"link-down-macbook-{since}",
                          level="error", body="מאז 12:16. x"), at=self.clock.t)
        else:
            relay.far("vps1", [])
            relay.far("vps1", [self.drop(self.clock.t + 1, "vps1", since)])
        self.clock.t += 181
        relay.tick()
        return out, relay.counts.get("slept", 0)

    def test_a_laptop_its_battery_put_to_sleep_is_said_once_never_as_an_outage(self):
        since = int(self.clock.t)
        self.relay.power["macbook"] = self.word(since - 50, guards=self.BATTERY)
        self.relay.far("vps1", [])
        self.macbook_down(since)
        self.relay.far("vps1", [self.drop(self.clock.t + 30, "vps1", since + 60, why="המנהרה לא מעבירה תנועה.")])
        self.clock.t += 181
        self.relay.tick()
        self.assertEqual(len(self.out), 1, self.out)                         # one line for both offices' views
        self.assertTrue(self.out[0].startswith("💤 🦌 MacBook כבה או נרדם ב־"), self.out[0])
        self.assertIn(": הסוללה ירדה מתחת ל־15%. זו לא תקלה בקישור — כדי שיחזור צריך לחבר אותו לחשמל.", self.out[0])
        self.assertNotIn("נפל", self.out[0])
        self.clock.t += 2400                                                  # it wakes: no «חזר» for a drop never said
        self.macbook_up(since)
        self.relay.far("vps1", [self.drop(self.clock.t + 5, "vps1", since + 60, up=True)])
        self.assertEqual(len(self.out), 1, self.out)
        again = int(self.clock.t) + 600                                       # asleep again, on the same low battery
        self.relay.power["macbook"] = self.word(again - 40, guards=self.BATTERY)
        self.clock.t = again
        self.macbook_down(again)
        self.clock.t += 181
        self.relay.tick()
        self.assertEqual(len(self.out), 1, self.out)                         # one low battery is one line
        self.assertEqual(self.relay.counts["slept"], 2)

    def test_heat_is_said_as_a_sleep_and_the_battery_says_how_it_comes_back(self):
        out, _ = self.one_drop(lambda s: self.word(s - 50, guards=["thermal pressure: critical"]))
        self.assertIn("💤 🦌 MacBook כבה או נרדם ב־", out[0])            # held awake, heat shuts it down: no promise
        self.assertIn(": המחשב התחמם. זו לא תקלה בקישור — כדי שיחזור צריך להעיר או להדליק אותו כשיתקרר.", out[0])
        out, _ = self.one_drop(lambda s: self.word(s - 50, guards=["thermal pressure: serious", "battery below 9%"]))
        self.assertIn("כבה או נרדם", out[0])
        self.assertIn("המחשב התחמם והסוללה ירדה מתחת ל־9%", out[0])
        self.assertIn("כדי שיחזור צריך לחבר אותו לחשמל", out[0])

    def test_a_laptop_let_sleep_when_closed_goes_quietly(self):
        since = int(self.clock.t)
        self.relay.power["macbook"] = self.word(since - 50, lid="sleep")     # the owner's policy: closed means asleep
        self.macbook_down(since)
        self.clock.t += 181
        self.relay.tick()
        self.clock.t += 3600
        self.macbook_up(since)
        self.assertEqual(self.out, [])
        self.assertEqual(self.relay.counts["slept"], 1)

    def test_a_laptop_held_awake_that_drops_is_an_outage(self):
        for word in (lambda s: self.word(s - 50),                                          # held awake
                     lambda s: self.word(s - 3600, guards=self.BATTERY),                   # a word from before
                     lambda s: self.word(s - 50, guards=["the engine is not running"]),    # the office stopped
                     lambda s: self.word(s - 50, guards=self.BATTERY + ["the engine is not running"]),
                     lambda s: self.word(s - 50, guards=["battery below 15% for an hour"]),  # a guard not known
                     lambda s: None):                                                      # never read
            self.out.clear()
            since = int(self.clock.t)
            self.relay.power["macbook"] = word(since)
            self.macbook_down(since)
            self.clock.t += 181
            self.relay.tick()
            self.assertEqual(len(self.out), 1)
            self.assertTrue(self.out[0].startswith("🔴 "), self.out[0])
            self.clock.t += 600
            self.macbook_up(since)
            self.assertEqual(len(self.out), 2)                                # and its return, as ever
            self.clock.t += group.SAME_PEER

    def test_only_the_word_of_the_quarter_hour_before_the_drop_is_heard(self):
        for off, slept in ((-900, 1), (-901, 0), (120, 1), (121, 0)):
            out, n = self.one_drop(lambda s, off=off: self.word(s + off, lid="sleep"))       # another office's clock
            self.assertEqual((n, out[0][:1] if out else ""), (slept, "" if slept else "🔴"), off)
            out, n = self.one_drop(lambda s, off=off: group.power_word(self.word(s - 30, lid="sleep"), s + off))
            self.assertEqual((n, out[0][:1] if out else ""), (slept, "" if slept else "🔴"), off)   # this office's

    def test_this_offices_own_drop_is_timed_by_its_own_clock_another_offices_by_the_laptops(self):
        skewed = lambda s: dict(self.word(s + 400, guards=self.BATTERY), read_at=s - 30)   # the Mac 7 min ahead
        out, n = self.one_drop(skewed)
        self.assertEqual(n, 1)
        self.assertTrue(out[0].startswith("💤 "), out)
        out, n = self.one_drop(skewed, own=False)                             # vps1's notice: the laptop's clock
        self.assertEqual(n, 0)
        self.assertTrue(out[0].startswith("🔴 "), out)
        out, n = self.one_drop(lambda s: dict(self.word(s - 2000, guards=self.BATTERY), read_at=s - 30))
        self.assertEqual(n, 0)                                                # a word nobody rewrites is no word

    def test_a_word_in_any_other_shape_is_an_outage_never_a_crash(self):
        for word in ({"at": "x", "guards": []}, [1, 2], "x", lambda s: {"at": s - 50, "guards": 5},
                     lambda s: {"at": s - 50, "guards": [5]}, lambda s: {"at": s - 50, "guards": []},
                     lambda s: {"at": s - 50, "guards": None, "lock": "sleep"}):
            out, n = self.one_drop(word)
            self.assertEqual((n, out[0][:1]), (0, "🔴"), word)
        self.assertIsNone(group.power_word({"at": "x", "guards": []}, 5))
        self.assertIsNone(group.power_word({"at": 10 ** 400, "guards": []}, 5))
        self.assertIsNone(group.power_word({"at": 1, "guards": 5}, 5))
        self.assertIsNone(group.power_word([1], 5))
        self.assertEqual(group.power_word({"at": "7", "guards": ["a", 3], "lock": None, "percent": True}, 5),
                         {"at": 7.0, "read_at": 5, "lock": "", "lid": "", "guards": ["a", "3"], "percent": None})

    def test_a_sleep_line_is_never_capped_and_a_failed_one_is_tried_again_once(self):
        for full, fail in ((True, False), (False, True), (True, True)):
            self.out.clear()
            self.relay = group.Relay(RULES, self.send, now=self.clock)
            if full:
                self.relay.sent = [self.clock.t] * 20                         # the hour is full, two held back
                self.relay.held_back = 2
            self.fail = fail
            since = int(self.clock.t)
            self.relay.power["macbook"] = self.word(since - 50, guards=self.BATTERY)
            self.macbook_down(since)
            self.clock.t += 181
            self.relay.tick()
            if fail:
                self.assertEqual(self.out, [])
                self.fail = False
                for _ in range(2):
                    self.clock.t += 31
                    self.relay.tick()
            self.assertEqual(len(self.out), 1, self.out)
            self.assertTrue(self.out[0].startswith("💤 ") and "בלוח ההתראות" not in self.out[0], self.out)
            self.clock.t += group.SAME_PEER

    def test_a_later_view_of_the_same_sleep_keeps_its_verdict_after_a_brief_wake_and_a_restart(self):
        since = int(self.clock.t)
        self.relay.far("vps1", [])
        self.relay.power["macbook"] = self.word(since - 50, guards=self.BATTERY)
        self.macbook_down(since)
        self.clock.t += 181
        self.relay.tick()
        self.assertEqual(len(self.out), 1)
        self.clock.t += 220                                                   # a brief wake: back, and a newer word
        self.macbook_up(since)
        self.relay.power["macbook"] = self.word(self.clock.t)
        state = json.loads(json.dumps(self.relay.state()))                    # the relay restarts here
        self.relay = group.Relay(RULES, self.send, state, now=self.clock, save=lambda: None)
        self.assertEqual(self.relay.power["macbook"]["lock"], "run")
        self.relay.far("vps1", [self.drop(self.clock.t + 10, "vps1", since + 60)])   # vps1 tells the same drop late
        self.clock.t += 191
        self.relay.tick()
        self.assertEqual(len(self.out), 1, self.out)                         # not «נפל»: the same sleep
        self.relay.far("vps1", [self.drop(self.clock.t + 5, "vps1", since + 60, up=True)])
        self.assertEqual(len(self.out), 1, self.out)
        later = int(self.clock.t) + 300                                       # awake, and then a real drop
        self.relay.power["macbook"] = self.word(later - 40)
        self.clock.t = later
        self.macbook_down(later)
        self.clock.t += 181
        self.relay.tick()
        self.assertEqual(len(self.out), 2, self.out)
        self.assertTrue(self.out[1].startswith("🔴 "), self.out)

    def test_only_the_same_drop_inherits_a_sleep_a_drop_begun_before_or_after_it_is_judged_by_its_own_word(self):
        since = int(self.clock.t)
        self.relay.far("vps1", [])
        self.relay.power["macbook"] = self.word(since - 50, guards=self.BATTERY)
        self.macbook_down(since)
        # vps1's link fell ten minutes BEFORE the sleep, and its notice is read only now
        self.relay.far("vps1", [self.drop(self.clock.t + 20, "vps1", since - 600, why="המנהרה לא מעבירה תנועה.")])
        self.clock.t += 181
        self.relay.tick()                                                    # the HP's view: the sleep
        self.assertEqual([o[:2] for o in self.out], ["💤 "[:2]])
        self.clock.t += 30
        self.relay.tick()                                                    # vps1's: its own word, not the sleep
        self.assertEqual(len(self.out), 2, self.out)
        self.assertTrue(self.out[1].startswith("🔴 "), self.out)
        # no return was ever seen, and a new drop begins after the verdict: judged anew, by the word read since
        later = int(self.clock.t) + 60
        self.relay.power["macbook"] = self.word(later - 30)
        self.clock.t = later
        self.macbook_down(later + 7)
        self.clock.t += 188
        self.relay.tick()
        self.assertEqual(self.relay.counts["slept"], 1)                      # not the sleep's: an outage…
        self.assertEqual(self.relay.counts.get("merged"), 1)                 # …the one vps1 told minutes ago
        self.assertEqual(len(self.out), 2, self.out)

    def test_the_return_is_marked_at_the_notices_own_time(self):
        since = int(self.clock.t)
        self.relay.power["macbook"] = self.word(since - 50, guards=self.BATTERY)
        self.macbook_down(since)
        self.clock.t += 181
        self.relay.tick()
        self.clock.t += 3000                                                 # its return, read late
        self.relay.take(ev(title="הקישור לMacBook חזר", source="dgo-extend", source_id=f"link-up-macbook-{since}",
                           level="info", body="x"), at=since + 900)
        self.assertEqual(self.relay.slept["macbook"]["up"], since + 900)

    def test_the_power_word_is_read_from_our_herds_control_centres_and_kept_through_a_sleep(self):
        from unittest import mock
        doors = {"macbook": "http://dashboard.macbook:9007", "vps1": "http://dashboard.vps1:9031"}
        words = {"http://dashboard.macbook:9007/data/power.json": self.word(1793880000)}

        def get(url, timeout=15):
            if url not in words:
                raise OSError("404")
            return words[url]
        with mock.patch.object(group, "get_json", get):
            group.read_power(self.relay, doors, now=lambda: 1793880030)
            self.assertEqual(self.relay.power, {"macbook": group.power_word(self.word(1793880000), 1793880030)})
            words.clear()                                                     # asleep: the word before stays
            group.read_power(self.relay, doors, now=lambda: 1793880090)
            self.assertEqual(self.relay.power["macbook"]["read_at"], 1793880030)

    def test_the_control_centres_doors_are_keyed_by_the_links_own_names(self):
        import tempfile
        d = tempfile.mkdtemp()
        herd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "computers", "herd.yaml")
        for name, port in (("macbook", 9007), ("portable-ubuntu", 9033), ("exf", 9034)):
            with open(os.path.join(d, f"remote.{name}.dashboard.json"), "w", encoding="utf-8") as fh:
                json.dump({"link_port": port, "port": 80}, fh)
        self.assertEqual(group.far_doors(d, herd, alias="dashboard", by_link=True),
                         {"macbook": "http://dashboard.macbook:9007",
                          "portable-ubuntu": "http://dashboard.portable-ubuntu:9033"})

    def test_an_addressed_far_notice_stays_off(self):
        self.relay.far("vps1", [])
        self.relay.far("vps1", [self.far_row(self.clock.t + 1, "לך בלבד", level="error", meta={"to": "solomon"})])
        self.assertEqual(self.out, [])

    def test_only_the_office_that_runs_telegram_reads_the_linked_offices(self):
        herd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "computers", "herd.yaml")
        self.assertTrue(group.far_here("hp-laptop", herd, "auto"))
        self.assertFalse(group.far_here("macbook", herd, "auto"))
        self.assertFalse(group.far_here("hp-laptop", herd, "0"))

    def test_the_far_doors_are_our_herds_only_by_their_herd_names(self):
        import tempfile
        d = tempfile.mkdtemp()
        herd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "computers", "herd.yaml")
        for name, port in (("vps1", 9031), ("portable-ubuntu", 9033), ("exf", 9034)):
            with open(os.path.join(d, f"remote.{name}.alerts.json"), "w", encoding="utf-8") as fh:
                json.dump({"link_port": port, "port": 8977}, fh)
        with open(os.path.join(d, "remote.vps1.security.json"), "w", encoding="utf-8") as fh:
            json.dump({"link_port": 9032}, fh)
        with open(os.path.join(d, "remote.macbook.alerts.json"), "w", encoding="utf-8") as fh:
            fh.write("[1, 2]")                          # a record that is not an object is skipped, never a crash
        self.assertEqual(group.far_doors(d, herd), {"vps1": "http://alerts.vps1:9031",
                                                    "dell": "http://alerts.portable-ubuntu:9033"})

    def test_a_far_notice_that_fails_is_counted_and_the_ones_before_never_post_again(self):
        self.relay.far("vps1", [])
        t = self.clock.t
        good = self.far_row(t + 1, "פריסה", source="follow", source_id="follow:vps1", level="info")
        bad = self.far_row(t + 2, "שבור", level="error")
        real_take = self.relay.take

        def take(fields, at=None):
            if "שבור" in fields["title"]:
                raise ValueError("a malformed notice")
            return real_take(fields, at)
        self.relay.take = take
        self.relay.far("vps1", [good, bad])
        self.relay.far("vps1", [good, bad])
        self.assertEqual(len(self.out), 1)                          # the deploy line once, not once per read
        self.assertEqual(self.relay.counts["far_failed"], 1)

    def test_a_far_notice_repeats_only_itself(self):
        self.relay.take(ev(title="הסוכן עודכן", source="bina-ds", source_id="self-update", level="info"))
        self.relay.far("vps1", [])
        self.clock.t += 600
        self.relay.far("vps1", [self.far_row(self.clock.t, "הסוכן עודכן", source="bina-ds", source_id="self-update",
                                             level="info")])
        self.assertEqual(len(self.out), 2)                          # vps1's is not the HP's of ten minutes before

    def test_an_empty_first_read_begins_now_not_at_the_epoch(self):
        self.relay.far("vps1", [])
        old = [self.far_row(self.clock.t - 3 * 86400 + i, f"פריסה ישנה {i}", source="follow",
                            source_id=f"follow:{i}", level="info") for i in range(5)]
        self.assertEqual(self.relay.far("vps1", old), 0)
        self.assertEqual(self.out, [])

    def test_a_notice_committed_late_is_still_taken_once(self):
        self.relay.far("vps1", [])
        t = self.clock.t
        a = self.far_row(t + 10, "שגיאה א", level="error", id=1)
        b = self.far_row(t + 5, "שגיאה ב", level="error", id=2)      # stamped earlier, committed after a was read
        self.relay.far("vps1", [a])
        self.relay.far("vps1", [a, b])
        self.relay.far("vps1", [a, b])
        self.assertEqual([o.split(": ", 1)[-1] for o in self.out], ["שגיאה א", "שגיאה ב"])

    def test_a_link_line_says_the_owners_time_not_the_containers(self):
        since = 1793880960                               # 2026-11-05 12:16 UTC — 14:16 in Israel (winter, +2)
        n = {"source": "dgo-extend", "source_id": f"link-down-macbook-{since}", "level": "error",
             "title": "הקישור לMacBook נפל", "body": "מאז 12:16. המנהרה אליה פעילה, אבל הלשכה עצמה לא עונה."}
        line = group.line_of(n, RULES, office="hp-laptop")
        self.assertIn("מאז 14:16. המנהרה אליה פעילה", line)
        self.assertNotIn("12:16", line)
        other = dict(n, source="security")                 # only dgo-extend's link notices are rewritten
        self.assertIn("מאז 12:16", group.line_of(other, RULES, office="hp-laptop"))

    def test_the_line_names_the_office(self):
        n = {"title": "שורה\nאחת", "level": "info", "source": "follow"}
        self.assertTrue(group.line_of(n, RULES, office="hp-laptop").startswith("🟢 🐘 HP: שורה אחת"))
        self.assertTrue(group.line_of(n, RULES, office="elsewhere").startswith("🟢 elsewhere: "))

    def day(self, *lines):
        return [{"ts": self.clock.t + dt, "kind": k, "text": text, "ref": ref} for dt, k, text, ref in lines]

    def test_work_items_from_the_control_centres_day_one_message_a_pass(self):
        past = self.day((-3600, "done", "נסגר: ישן", "DGO-1"))
        self.relay.items(past)                          # the first reading is the past: it only sets the start
        self.assertEqual(self.out, [])
        self.clock.t += 30
        day = past + self.day((-5, "open", "נפתח: ניהול הלשכה מתוך הקבוצה", "DGO-1329"),
                              (-4, "done", "נסגר: הרשאות", "DGO-1306"),
                              (-3, "start", "התחיל: משהו", "DGO-7"),
                              (-2, "done", "הקישור חזר", ""),          # a link's line: no ref
                              (-1, "bad", "הקישור נפל", ""))
        self.relay.items(day)
        self.relay.items(day)                           # the feed rewrites its file every 30 s: posted once
        self.assertEqual(len(self.out), 1)
        head = RULES["offices"].get(group.OFFICE, group.OFFICE)
        self.assertEqual(self.out[0], f"🗂 {head}: \n📌 DGO-1329 · נפתח: ניהול הלשכה מתוך הקבוצה\n✅ DGO-1306 · נסגר: הרשאות")

    def test_a_close_saved_again_is_not_a_new_close_a_reopen_is(self):
        self.relay.items([])
        self.clock.t += 30
        self.relay.items(self.day((-5, "done", "נסגר: א", "DGO-3")))
        self.clock.t += 600                             # completed_at moved: Plane saved the closed item again
        self.relay.items(self.day((-1, "done", "נסגר: א", "DGO-3")))
        self.assertEqual(len(self.out), 1)
        self.clock.t += 60
        self.relay.items(self.day((-1, "open", "נפתח מחדש: א", "DGO-3"), (-2, "cancel", "בוטל: ב", "DGO-4")))
        self.assertEqual(len(self.out), 2)
        self.assertIn("✖️ DGO-4", self.out[1])
        self.assertIn("📌 DGO-3 · נפתח מחדש", self.out[1])
        self.clock.t += 60
        self.relay.items(self.day((-1, "done", "נסגר: א", "DGO-3")))       # closed again: news again
        self.assertEqual(len(self.out), 3)

    def test_a_day_of_closes_never_pushes_an_alarm_out(self):
        self.relay.items([])
        self.clock.t += 30
        self.relay.items(self.day(*[(-i, "done", f"נסגר: {i}", f"DGO-{100 + i}") for i in range(1, 26)]))
        self.assertEqual(len(self.out), 1)
        self.assertIn("(ועוד 10 בלוח הבקרה)", self.out[0])
        for i in range(RULES["per_hour"]):
            self.relay.take(ev(title=f"שגיאה {i}", source="x", source_id=str(i), level="error"))
        self.assertEqual(len(self.out), 1 + RULES["per_hour"])     # the alarms' whole budget, untouched

    def test_a_backlog_read_late_is_the_past(self):
        self.relay.items([])
        self.clock.t += 5 * 3600                        # the relay was down for hours
        self.relay.items(self.day((-4 * 3600, "done", "נסגר: מזמן", "DGO-9"), (-60, "done", "נסגר: עכשיו", "DGO-10")))
        self.assertEqual(len(self.out), 1)
        self.assertNotIn("DGO-9", self.out[0])

    def test_a_malformed_day_is_skipped(self):
        self.relay.items([])
        self.relay.items(["x", 3, None])                # not lines at all: nothing, and no exception
        self.assertEqual(self.out, [])

    def test_only_the_office_that_runs_plane_posts_items(self):
        herd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "computers", "herd.yaml")
        self.assertTrue(group.items_here("hp-laptop", herd, "auto"))
        self.assertFalse(group.items_here("macbook", herd, "auto"))
        self.assertFalse(group.items_here("", herd, "auto"))
        self.assertTrue(group.items_here("macbook", herd, "1"))
        self.assertFalse(group.items_here("hp-laptop", "/no/such/herd.yaml", "auto"))

    def test_no_line_says_an_address_of_the_offices_plumbing(self):
        self.relay.take(ev(title="המשרד התעדכן — test", source="follow", source_id="follow:test:took:abc1234",
                           level="info", body="took dgo-stable abc1234: the door at 10.20.0.7 and 192.168.1.23:9005, "
                                               "via 100.64.0.2 and 172.18.0.4, not 93.184.216.12 or 203.0.113.9"))
        line = self.out[-1]
        for gone in ("10.20.0.7", "192.168.1.23", "100.64.0.2", "172.18.0.4"):
            self.assertNotIn(gone, line)
        self.assertEqual(line.count("‹כתובת פנימית›"), 4, line)
        self.assertIn("93.184.216.12", line)                                   # public: said as it is
        self.assertIn("203.0.113.9", line)

    #: every form of an internal address a line may carry (the relay's say_group.INTERNAL refuses fewer of them today:
    #: it is the desk's list, and widening it is the desk's change)
    PLUMBING_SEEN = ("the door at 10.9.8.7.", "signin.localhost:8080/login", "http://notifications:8977/api",
                     "forge.console.localhost and macbook.console.localhost:8080/#/m/x",
                     "on localhost:3000", "git-accounts.macbook:9004", "fd12:3456::1", "fe80::1ff:fe23:4567:890a",
                     "::1 and 0.0.0.0", "169.254.1.2", "127.0.1.1")

    def test_every_kind_of_internal_address_and_a_bare_token_is_masked_in_any_line(self):
        token = "000000000:REDACTED"
        for seen in self.PLUMBING_SEEN + (f"token {token} here",):
            line = group.line_of({"source": "follow", "source_id": "x", "level": "info", "title": "t", "body": seen},
                                 RULES)
            self.assertTrue("‹כתובת פנימית›" in line or "<token>" in line, (seen, line))
            for part in ("10.9.8.7", "signin.localhost", "notifications:8977", "localhost:3000", "git-accounts.macbook",
                         "console.localhost", "forge.", "macbook.console",
                         "fd12:3456", "fe80::", "0.0.0.0", "169.254", "127.0.1.1", "AAHdqTcv"):
                self.assertNotIn(part, line, seen)
        line = group.line_of({"source": "x", "source_id": "x", "level": "info", "title": "v2.3 at 10:30, 1.5.2026, "
                              "DGO-1329:15, Chrome 130.0.6723.117"}, RULES)
        self.assertNotIn("‹כתובת פנימית›", line)                          # versions, times, dates: not addresses

    def test_an_address_is_masked_before_the_line_is_cut(self):
        line = group.line_of({"source": "x", "source_id": "x", "level": "info", "title": "t",
                              "body": "א" * 290 + " 192.168.100.200 " + "ב" * 50}, RULES)
        self.assertNotIn("192.168", line)
        self.assertNotIn("100.200", line)

    def test_one_open_problem_is_one_message_whatever_id_its_maker_gives_each_repeat(self):
        refusal = dict(title="הריפוי העצמי לא פועל — הפרויקט שלו לא ידוע", source="autoheal", level="error",
                       body="השירות אינו יודע איזו לשכה הוא משרת")
        for minute in range(3):                                  # autoheal: once a minute, `no-project:<epoch>`
            self.relay.take(ev(source_id=f"autoheal:no-project:{1793880000 + 60 * minute}", **refusal))
        self.assertEqual(len(self.out), 1, self.out)
        self.assertEqual(self.relay.counts["repeat"], 2)
        self.relay.take(ev(title="קונטיינר אחר נפל", source="autoheal", source_id="x:1", level="error"))
        self.assertEqual(len(self.out), 2)                       # another problem is another message
        self.clock.t += 241 * 60                                  # past the rule's window: said again, once
        self.relay.take(ev(source_id="autoheal:no-project:1793895000", **refusal))
        self.relay.take(ev(source_id="autoheal:no-project:1793895060", **refusal))
        self.assertEqual(len(self.out), 3, self.out)

    def test_a_token_never_reaches_the_log(self):
        msg = "InvalidURL: URL can't contain control characters. '/bot1234567:SECRETabc_-x\\n/sendMessage'"
        self.assertNotIn("SECRET", group.redact(msg))
        self.assertIn("bot<token>", group.redact(msg))


class RespTest(unittest.TestCase):
    def test_xread_reply_as_redis_sends_it(self):
        raw = (b"*1\r\n*2\r\n$22\r\ndgo:flow:notifications\r\n*1\r\n*2\r\n$15\r\n1730000000000-0\r\n"
               b"*4\r\n$4\r\ntype\r\n$10\r\nnotice.new\r\n$5\r\ntitle\r\n$9\r\n\xd7\xa9\xd7\x9c\xd7\x95\xd7\x9d!\r\n")
        evs = group.events_of(group.read_reply(io.BytesIO(raw)))
        self.assertEqual(evs, [("dgo:flow:notifications", "1730000000000-0", {"type": "notice.new", "title": "שלום!"})])
        self.assertEqual(group.id_time("1730000000000-0"), 1730000000.0)

    def test_a_value_with_crlf_inside_nil_error_integer_and_a_cut(self):
        self.assertEqual(group.read_reply(io.BytesIO(b"$4\r\na\r\nb\r\n")), "a\r\nb")
        self.assertIsNone(group.read_reply(io.BytesIO(b"*-1\r\n")))
        self.assertIsNone(group.read_reply(io.BytesIO(b"$-1\r\n")))
        self.assertEqual(group.read_reply(io.BytesIO(b":7\r\n")), 7)
        with self.assertRaises(group.RedisError):
            group.read_reply(io.BytesIO(b"-WRONGPASS invalid\r\n"))
        with self.assertRaises(ConnectionError):
            group.read_reply(io.BytesIO(b"$10\r\nabc"))
        with self.assertRaises(ConnectionError):
            group.read_reply(io.BytesIO(b""))


if __name__ == "__main__":
    unittest.main()
