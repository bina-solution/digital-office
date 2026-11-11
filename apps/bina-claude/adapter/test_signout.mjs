// apps/bina-claude/adapter/test_signout.mjs — the sign-out alarm's judgement and its turns, without a
// clock, a container or a network (DGO-1430).
//
//   node --test apps/bina-claude/adapter/test_signout.mjs
//
// Two layers, each tested on its own:
//   decideSignout   (state, observation, now) → (state, action): the decision, pure. A start-up flap, a
//                   real sign-out, a restart in the middle of one, the sign-in coming back, the store being
//                   unreadable (which is NOT a sign-out), `seen`: whether the alarm WATCHED the sign-in the
//                   sign-out follows (a «signed in» reading no more than two ticks before the beginning),
//                   and `attempted`: an episode whose red line may have landed is never forgotten.
//   alarmStep       the same turn with the board's calls and the pen handed in: the write marked on disk
//                   BEFORE the POST leaves, the retry that asks the board instead of posting blind, the red
//                   line that is still closed when its answer was lost, and the close that asks first.
import assert from "node:assert/strict";
import test from "node:test";

import { decideSignout, alarmStep, graceOf, salvageEpisode, when } from "./server.mjs";

const GRACE = 180000;                                     // BINA_CLAUDE_SIGNOUT_GRACE_S=180
const T0 = 1793964000000;                                 // a real epoch ms, the way an episode's start is
const at = (n) => T0 + n * 1000;                           // n seconds after the episode began
const sid = (n) => `signed-out-${Math.floor(at(n) / 1000)}`;
const OUT = { logged_in: false };
const IN = { logged_in: true };
const AWAY = { logged_in: null };
// a state in the shape ${STATE}/signout.json holds, with only what a case cares about given
const st = (over = {}) => ({ began: null, seen: false, posted: false, notice: null, attempted: null,
                            last_in: null, ...over });
const IDLE = st();

// one tick of the watcher exactly as the loop runs it
function tick(state, observation, now) {
  const d = decideSignout(state, observation, now, GRACE);
  return { state: d.state, action: d.action };
}

test("a 2-second start-up flap posts nothing", () => {
  const a = tick(IDLE, OUT, at(0));
  assert.equal(a.action, null);
  const b = tick(a.state, IN, at(2));
  assert.equal(b.action, null, "back in before the grace: no notice, and nothing to close");
  assert.deepEqual(b.state, st({ last_in: at(2) }), "no episode left behind — only «we were in at»");
});

test("180 s of «signed out» posts one notice — and the seconds inside the grace post none", () => {
  let s = IDLE;
  for (const t of [0, 60, 120, 179]) {
    const r = tick(s, OUT, at(t));
    assert.equal(r.action, null, `nothing at ${t} s`);
    assert.equal(r.state.began, at(0), "the episode began at the first observation and keeps that moment");
    s = r.state;
  }
  const r = tick(s, OUT, at(180));
  assert.equal(r.action?.kind, "post");
  assert.equal(r.action.since, at(0), "…announced as the episode it is, not as «now»");
  const announced = { ...r.state, posted: true, notice: 7 };
  for (const t of [240, 300, 3600, 86400]) {
    assert.equal(tick(announced, OUT, at(t)).action, null, `no second notice at ${t} s`);
  }
});

test("a restart in the middle of an announced episode does not post again", () => {
  // exactly what ${STATE}/signout.json holds while the app is out
  const reloaded = JSON.parse(JSON.stringify(st({ began: at(0), seen: true, posted: true, notice: 7 })));
  const r = tick(reloaded, OUT, at(1200));
  assert.equal(r.action, null);
  assert.deepEqual(r.state, st({ began: at(0), seen: true, posted: true, notice: 7 }),
                   "the open episode survives the restart");
});

test("a restart before the notice went out keeps the SAME episode — one notice, however many restarts", () => {
  // the adapter stopped 100 s into an episode and came back 400 s in: the grace is measured from the
  // episode's own start, so the notice arrives at once, under the id the first attempt would have used
  const persisted = st({ began: at(0), seen: true });
  const first = tick(persisted, OUT, at(400));
  assert.equal(first.action?.kind, "post");
  const again = tick(persisted, OUT, at(460));
  assert.equal(again.action?.kind, "post");
  assert.equal(first.action.since, again.action.since, "same source_id → the board upserts, it does not add");
});

test("back in: an announced episode is closed by asking the board, and one never said is forgotten", () => {
  const r = tick(st({ began: at(0), seen: true, posted: true, notice: 7 }), IN, at(600));
  assert.equal(r.action?.kind, "close");
  assert.equal(r.action.since, at(0), "the SAME source_id the error was posted under");
  assert.equal(r.action.notice, 7, "the id to mark read");
  // …and an episode whose WRITE WAS ATTEMPTED is asked about even though `posted` is false: the answer to
  // that POST may have been the one that came after the abort (the second reader, DGO-1430)
  const attempted = tick(st({ began: at(0), seen: true, attempted: sid(0) }), IN, at(600));
  assert.equal(attempted.action?.kind, "close", "a red line may be on the board: it is looked up, not assumed");
  // nothing was ever said about this one: nothing to look up, nothing to close
  const nothing = tick(st({ began: at(0), seen: true }), IN, at(600));
  assert.equal(nothing.action, null);
  assert.equal(nothing.state.began, null, "forgotten");
});

test("an episode that ended inside the grace says nothing and forgets itself", () => {
  const r = tick(st({ began: at(0), seen: true }), IN, at(90));
  assert.equal(r.action, null);
  assert.deepEqual(r.state, st({ last_in: at(90) }), "cleared — but «we were in at» stays");
});

test("null — the store is away — changes nothing; it is not a sign-out", () => {
  for (const s of [IDLE, st({ began: at(0), seen: true }),
                   st({ began: at(0), seen: true, posted: true, notice: 7 })]) {
    const r = tick(s, AWAY, at(3600));
    assert.equal(r.action, null);
    assert.deepEqual(r.state, s, "the same episode, untouched — an unreadable store is not an absence");
  }
});

test("an observation with no answer at all is not a sign-out either", () => {
  assert.equal(tick(IDLE, {}, at(0)).action, null);
  assert.equal(tick(IDLE, null, at(0)).action, null);
});

test("a broken state file reads as «no episode», not as a crash", () => {
  for (const junk of [undefined, null, {}, { began: "yesterday" }, []]) {
    const r = tick(junk, OUT, at(0));
    assert.equal(r.action, null, "a fresh episode is never announced on the tick it begins");
    assert.equal(r.state.began, at(0));
    assert.equal(r.state.seen, false, "and nothing claims to have watched a beginning it did not");
  }
});

// ── seen: the beginning this alarm watched, against the one it walked in on ──────────────────────

test("an adapter that STARTS on an app already signed out claims no beginning", () => {
  // the HP, 2026-11-06: the app had been out for 48 hours when the alarm was first brought up
  const r = tick(IDLE, OUT, at(0));
  assert.equal(r.state.seen, false, "the first reading was already «signed out» — nothing was watched");
  const p = tick(r.state, OUT, at(180));
  assert.equal(p.action?.kind, "post");
  assert.equal(p.action.seen, false, "…so the body says «נמצא מנותק ב-HH:MM», not «מאז HH:MM»");
});

test("a sign-in watched just BEFORE the sign-out makes the beginning a measurement", () => {
  const inSeen = tick(IDLE, IN, at(0));                    // the app was signed in, and this alarm saw it
  assert.deepEqual(inSeen.state, st({ last_in: at(0) }));
  const out1 = tick(inSeen.state, OUT, at(60));            // one tick later: the same minute
  assert.equal(out1.state.began, at(60));
  assert.equal(out1.state.seen, true);
  const p = tick(out1.state, OUT, at(60 + 180));
  assert.equal(p.action?.kind, "post");
  assert.equal(p.action.seen, true, "…so the body says «מאז HH:MM»");
});

test("a sign-in watched HOURS before is not the beginning of this sign-out", () => {
  // the second reader, DGO-1430: `was_in` was never cleared, so hours down (or a long stretch of
  // unreadable readings) came back as «מאז <the restart>» — a time this alarm never measured
  const earlier = tick(IDLE, IN, at(0));
  const out1 = tick(earlier.state, OUT, at(3600));
  assert.equal(out1.state.began, at(3600));
  assert.equal(out1.state.seen, false, "an hour of gap is not «the alarm watched it»");
  assert.equal(tick(out1.state, OUT, at(3600 + 180)).action.seen, false);
});

test("«we were in at» survives a restart — the corpus is the state, not the process", () => {
  // a restart between the sign-in and the sign-out: the state file is all that is left of that reading
  const reloaded = JSON.parse(JSON.stringify(st({ last_in: at(0) })));
  assert.equal(tick(reloaded, OUT, at(60)).state.seen, true, "one tick later is the same beginning");
  assert.equal(tick(reloaded, OUT, at(7200)).state.seen, false, "two hours later is not");
});

test("an old state file, written before these fields, reads as «not seen» — never as a claim", () => {
  // exactly what 5c3b92a8 wrote: {began, posted, notice}, no `seen`, no `last_in`
  const legacy = JSON.parse('{"began":1793964530632,"posted":true,"notice":12609}');
  const r = tick(legacy, OUT, at(7200));
  assert.equal(r.action, null, "an announced episode is not announced twice");
  assert.equal(r.state.seen, false, "and it does not start claiming a beginning it never recorded");
  assert.equal(r.state.began, 1793964530632, "the episode itself is kept as it was");
  const found = tick(legacy, IN, at(7200));
  assert.equal(found.action.kind, "close");
  assert.equal(found.action.notice, 12609);
});

// ── the turn: the write marked before the POST, and a retry that asks instead of posting blind ────

// A board whose every call is recorded and whose every answer is chosen by the case. `commit` is the pen:
// it records the state it is handed — what the volume would hold at that instant.
function board({ known = { ok: true, id: null, level: null }, readFails = false, postFails = false } = {}) {
  const seen = { existing: [], notify: [], markRead: [], commit: [], order: [] };
  return {
    seen,
    async existing(s) {
      seen.existing.push(s);
      seen.order.push("existing");
      if (readFails) return { ok: false, why: "AbortError: the operation was aborted" };
      return known;
    },
    async notify(body) {
      seen.notify.push(body);
      seen.order.push("notify");
      if (postFails) throw new Error("the operation was aborted");
      return 42;
    },
    async markRead(id) {
      seen.markRead.push(id);
      seen.order.push("markRead");
    },
    commit(s) {
      seen.commit.push(s);
      seen.order.push("commit");
    },
  };
}

test("the write is on disk BEFORE the POST leaves", async () => {
  // the second reader, DGO-1430: an answer that came after the abort, or a process that died right after
  // the POST, left a red line on the board and a state that said «nothing was said»
  const b = board();
  const r = await alarmStep(st({ began: at(0), seen: false }), OUT, at(180), b);
  assert.equal(r.step, "post");
  assert.deepEqual(b.seen.order.slice(0, 2), ["commit", "notify"], "the pen first, then the POST");
  assert.equal(b.seen.commit[0].attempted, sid(0), "and it names the source_id that is about to leave");
  assert.equal(r.state.posted, true);
  assert.equal(r.state.attempted, null, "confirmed: nothing is left «attempted»");
});

test("a red line whose answer was lost is still closed when the app comes back", async () => {
  // 1. the POST lands, the answer arrives after the abort: alarmStep throws, the volume keeps `attempted`
  const lost = board({ postFails: true });
  await assert.rejects(() => alarmStep(st({ began: at(0), seen: true }), OUT, at(180), lost),
                        /aborted/, "the caller sees the failure…");
  const persisted = lost.seen.commit.at(-1);
  assert.equal(persisted.attempted, sid(0), "…and the volume knows a red line may exist");
  assert.equal(persisted.posted, false);
  // 2. the next reading is IN: the board is asked, and the red line it holds is closed — the group's last
  //    word is not left red for ever
  const back = board({ known: { ok: true, id: 42, level: "error" } });
  const r = await alarmStep(persisted, IN, at(600), back);
  assert.equal(r.step, "closed");
  assert.equal(back.seen.notify.length, 1, "the closing line went out");
  assert.equal(back.seen.notify[0].level, "info");
  assert.equal(back.seen.notify[0].source_id, sid(0));
  assert.deepEqual(back.seen.markRead, [42]);
  assert.equal(r.state.began, null, "and the episode is over");
});

test("a retry whose read fails skips the tick — it never posts blind", async () => {
  // 2. both calls timing out used to post again every tick, and every re-POST is a `notice.recurred`
  const b = board({ readFails: true });
  const r = await alarmStep(st({ began: at(0), seen: true, attempted: sid(0) }), OUT, at(300), b);
  assert.equal(r.step, "waiting");
  assert.deepEqual(b.seen.notify, [], "no red line was posted");
  assert.equal(r.state.attempted, sid(0), "the episode keeps what it knows, and tries again next tick");
  assert.equal(r.state.posted, false);
});

test("a retry the board answers «not there» for may post — the first one never landed", async () => {
  const b = board({ known: { ok: true, id: null, level: null } });
  const r = await alarmStep(st({ began: at(0), seen: true, attempted: sid(0) }), OUT, at(300), b);
  assert.equal(r.step, "post");
  assert.equal(b.seen.notify.length, 1, "posted once, now that the board has said it is not there");
});

test("a retry the board answers «already there» for adopts it — one red line, however many answers were lost", async () => {
  const b = board({ known: { ok: true, id: 42, level: "error" } });
  const r = await alarmStep(st({ began: at(0), seen: true, attempted: sid(0) }), OUT, at(300), b);
  assert.equal(r.step, "adopted");
  assert.deepEqual(b.seen.notify, [], "nothing was posted a second time");
  assert.equal(r.state.posted, true);
  assert.equal(r.state.notice, 42);
  assert.equal(r.state.attempted, null);
});

test("a close whose read fails waits, and posts nothing", async () => {
  const b = board({ readFails: true });
  const r = await alarmStep(st({ began: at(0), seen: true, posted: true, notice: 7 }), IN, at(600), b);
  assert.equal(r.step, "waiting");
  assert.deepEqual(b.seen.notify, [], "no second green line");
  assert.equal(r.state.posted, true, "the episode is kept for the next tick");
});

test("a close for an episode the board never got is forgotten, not posted", async () => {
  const b = board();                                    // ok, and nothing found
  const r = await alarmStep(st({ began: at(0), seen: true, attempted: sid(0) }), IN, at(600), b);
  assert.equal(r.step, "forgot");
  assert.deepEqual(b.seen.notify, [], "a green notice about nothing is not written");
  assert.equal(r.state.began, null);
});

test("a close whose answer was lost is not posted again", async () => {
  const b = board({ known: { ok: true, id: 42, level: "info" } });
  const r = await alarmStep(st({ began: at(0), seen: true, posted: true, notice: 42 }), IN, at(600), b);
  assert.equal(r.step, "closed");
  assert.deepEqual(b.seen.notify, [], "the board is already at «info»: the close happened");
  assert.deepEqual(b.seen.markRead, [42], "only the read is done again");
  assert.equal(r.state.began, null);
});

test("the close ends the episode even when marking it read fails", async () => {
  const b = board({ known: { ok: true, id: 42, level: "error" } });
  b.markRead = async (id) => { b.seen.markRead.push(id); throw new Error("the read route answered 500"); };
  const r = await alarmStep(st({ began: at(0), seen: true, posted: true, notice: 7 }), IN, at(600), b);
  assert.equal(r.step, "closed");
  assert.equal(r.state.began, null, "a failing read never keeps the episode open to swallow the next one");
});

// ── the grace, the clock and a state file the alarm cannot parse ─────────────────────────────────

test("a grace that is not a positive number is not a grace", () => {
  assert.equal(graceOf("180"), 180000);
  assert.equal(graceOf(" 90 "), 90000);
  assert.equal(graceOf(undefined), 180000, "unset = the default");
  assert.equal(graceOf(""), 180000, "empty = the default");
  for (const bad of ["3m", "0", "-5", "NaN", "1e", "three"]) {
    assert.equal(graceOf(bad), null, `${JSON.stringify(bad)} is not a count of seconds`);
  }
});

test("the date is said when it was not today, and only then", () => {
  const now = Date.UTC(2026, 10, 6, 12, 0);                 // 2026-11-06 12:00 UTC
  assert.equal(when(Date.UTC(2026, 10, 6, 9, 29), now, "UTC"), "09:29");
  assert.equal(when(Date.UTC(2026, 10, 4, 9, 29), now, "UTC"), "04.11 09:29", "three days out is not today");
  assert.equal(when(Date.UTC(2026, 9, 31, 23, 59), now, "UTC"), "31.10 23:59");
  assert.equal(when(Date.UTC(2026, 10, 6, 9, 29), now, "Asia/Jerusalem"), "11:29", "in the owner's clock");
});

test("a clock the runtime does not know is said once, and the hours go on in UTC", () => {
  const said = [];
  const real = console.error;
  console.error = (...a) => said.push(a.join(" "));
  try {
    const a = when(Date.UTC(2026, 10, 6, 9, 29), Date.UTC(2026, 10, 6, 12, 0), "Mars/Olympus");
    const b = when(Date.UTC(2026, 10, 4, 9, 29), Date.UTC(2026, 10, 6, 12, 0), "Mars/Olympus");
    assert.equal(a, "09:29", "UTC is what it can be");
    assert.equal(b, "04.11 09:29");
  } finally { console.error = real; }
  assert.equal(said.filter((l) => l.includes("not a time zone")).length, 1, "said once, not on every line");
});

test("a state file that is not JSON keeps the episode it still names", () => {
  // cut in half by a power loss: the notice's id is the only handle the close has
  const kept = salvageEpisode('{"began":1793964530632,"seen":true,"posted":true,"notice":12609}');
  assert.deepEqual(kept, { began: 1793964530632, seen: true, posted: true, notice: 12609, attempted: null,
                           last_in: null });
  assert.deepEqual(salvageEpisode(""), IDLE);
});

test("a number cut mid-write is not a number — 1970 is not a beginning", () => {
  // the second reader, DGO-1430: `"began":17939645` is a half-written epoch, and \d{6,} read it as
  // 1970-01-01 — an episode the grace has always already passed, posted at once
  assert.deepEqual(salvageEpisode('{"began":17939645,"posted":true,"notice":12609'), IDLE);
  // …and a whole number that is still before this code existed is refused too
  assert.deepEqual(salvageEpisode('{"began":946684800000,"posted":true,"notice":12609}'), IDLE,
                   "January 2000 is not a time this alarm could have been watching");
  // a number that ends where a number ends is read
  assert.equal(salvageEpisode('{"began":1793964530632}').began, 1793964530632);
});

test("a salvaged episode is never announced twice", async () => {
  const kept = salvageEpisode('{"began":1793964530632,"seen":true,"posted":true,"notice":12609}');
  const b = board();
  const r = await alarmStep(kept, OUT, at(7200), b);
  assert.equal(r.step, "none");
  assert.deepEqual(b.seen.notify, [], "the first notice is not orphaned by a second one");
});
