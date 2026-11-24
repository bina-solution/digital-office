// How many turns the office's Claude runs at once (turn-queue.mjs, DGO-2126): a turn asked for at the cap waits in a
// line kept on disk, under an id its sender is given; the line never lets a newcomer jump a turn that could start,
// starts the first waiting turn that can start when a slot frees, keeps — never drops — a turn whose start pressed
// nothing (backed off, so it holds nobody), drops and reports — never resends — one that may have been delivered,
// never starts again one a restart cut in the middle, and a retry of the same message keeps its place and its id.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { capOf, mayStart, createTurnQueue, DEFAULT_CAP, OWNER_TRIES, backoff } from "../turn-queue.mjs";

const tmpFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "turn-queue-")), "turn-queue.json");
const quiet = () => {};
const onDisk = (file) => JSON.parse(fs.readFileSync(file, "utf8")).items;
const refuse = (code) => { const e = new Error(code); e.code = code; throw e; };

test("capOf: the office's number 0–64, the default for nothing or anything else", () => {
  assert.equal(capOf(undefined), DEFAULT_CAP);
  assert.equal(capOf(""), DEFAULT_CAP);
  assert.equal(capOf("  "), DEFAULT_CAP);
  assert.equal(capOf("0"), 0);
  assert.equal(capOf("4"), 4);
  assert.equal(capOf(" 6 "), 6);
  assert.equal(capOf("64"), 64);
  const said = [];
  assert.equal(capOf("65", (m) => said.push(m)), DEFAULT_CAP);
  assert.equal(capOf("-1", (m) => said.push(m)), DEFAULT_CAP);
  assert.equal(capOf("four", (m) => said.push(m)), DEFAULT_CAP);
  assert.equal(capOf("2.5", (m) => said.push(m)), DEFAULT_CAP);
  assert.equal(said.length, 4, "every unreadable value is said");
});

test("mayStart: no cap starts always; under the cap with nobody waiting starts; a waiting line is never jumped", () => {
  assert.equal(mayStart({ cap: 0, active: 99, queued: 5 }), true);
  assert.equal(mayStart({ cap: 4, active: 3, queued: 0 }), true);
  assert.equal(mayStart({ cap: 4, active: 4, queued: 0 }), false);
  assert.equal(mayStart({ cap: 4, active: 9, queued: 0 }), false);
  assert.equal(mayStart({ cap: 4, active: 0, queued: 1 }), false);
});

test("the line: places and ids, a retry keeps both, kept on disk across a restart", () => {
  const file = tmpFile();
  let active = 4;
  const q = createTurnQueue({ file, cap: 4, active: () => active, start: async () => "x", log: quiet });
  assert.equal(q.allows(), false);
  const a = q.enqueue("new", "pending-a", "first");
  const b = q.enqueue("send", "local_b", "second");
  assert.deepEqual([a.place, b.place], [1, 2]);
  assert.match(a.qid, /^[0-9a-f-]{36}$/);
  assert.deepEqual(q.enqueue("new", "pending-a", "first"), a, "the same message asked again keeps its place and id");
  assert.equal(q.length(), 2);
  assert.equal(q.place("local_b"), 2);
  assert.equal(q.place("local_none"), 0);
  assert.deepEqual(q.qids("local_b"), [b.qid]);
  assert.equal(q.count("local_b"), 1);
  active = 0;
  assert.equal(q.allows(), false, "a free slot belongs to the waiting turn, not to a newcomer");
  const again = createTurnQueue({ file, cap: 4, active: () => 4, start: async () => "x", log: quiet });
  assert.equal(again.length(), 2, "an adapter restart keeps the line");
  assert.equal(again.place("pending-a"), 1);
  assert.deepEqual(again.qids("pending-a"), [a.qid]);
});

test("the same words for the same session while they still wait are one message, however late; once sent, a new one", async () => {
  const file = tmpFile();
  let clock = 1000, active = 1;
  const q = createTurnQueue({ file, cap: 1, active: () => active, start: async (it) => it.target, log: quiet, now: () => clock });
  const one = q.enqueue("send", "local_c", "continue");
  clock += 3 * 3600000;                            // hours later — a sender who could not see that it waits sends it again
  assert.deepEqual(q.enqueue("send", "local_c", "continue"), one, "the same message: never queued twice");
  assert.equal(q.enqueue("send", "local_other", "continue").place, 2, "another session's is another message");
  active = 0;
  await q.tick();
  const two = q.enqueue("send", "local_c", "continue");
  assert.notEqual(two.qid, one.qid, "sent: the same words now are a second message");
});

test("a start refused for the owner's own work in the app is given up after OWNER_TRIES, reported, never sent", async () => {
  const file = tmpFile();
  const failed = [];
  let clock = 0, tries = 0;
  const q = createTurnQueue({ file, cap: 2, active: () => 0, log: quiet, now: () => clock,
                              retryable: () => true, owners: (e) => e.code === "not-sent",
                              failed: (it, e) => failed.push([it.target, e.code]),
                              start: async () => { tries++; refuse("not-sent"); } });
  q.enqueue("send", "local_draft", "behind his draft");
  for (let i = 0; i < 5; i++) { await q.tick(); clock += 60001; }
  assert.equal(tries, OWNER_TRIES, "tried OWNER_TRIES times, each one pulling his screen — no more");
  assert.equal(q.length(), 0);
  assert.deepEqual(failed, [["local_draft", "not-sent"]]);
});

test("the owner's refusals are counted apart: another drive before them is not his work", async () => {
  const file = tmpFile();
  const codes = ["locked", "not-sent", "locked", "not-sent"];
  let clock = 0, tries = 0;
  const failed = [];
  const q = createTurnQueue({ file, cap: 2, active: () => 0, log: quiet, now: () => clock,
                              retryable: () => true, owners: (e) => e.code === "not-sent",
                              failed: (it, e) => failed.push(e.code),
                              start: async () => { refuse(codes[tries++]); } });
  q.enqueue("send", "local_s", "x");
  for (let i = 0; i < 3; i++) { await q.tick(); clock += 60001; }
  assert.equal(q.length(), 1, "locked, his draft, locked: one refusal of his so far — still waiting");
  await q.tick();
  assert.deepEqual([q.length(), failed], [0, ["not-sent"]], "his second: given up, reported");
});

test("blocked: told when nothing can start — all wait on their sessions (one may be a dead process's file)", async () => {
  const file = tmpFile();
  let told = 0;
  const q = createTurnQueue({ file, cap: 4, active: () => 1, log: quiet, ready: () => false, blocked: () => { told++; },
                              start: async () => "x" });
  q.enqueue("send", "local_busy", "after its turn");
  await q.tick();
  assert.equal(told, 1);
});

test("tick: nothing starts at the cap (the hook is told); one turn per tick when a slot frees, the oldest first", async () => {
  const file = tmpFile();
  let active = 4, told = 0;
  const started = [];
  const q = createTurnQueue({ file, cap: 4, active: () => active, log: quiet, blocked: () => { told++; },
                              start: async (it) => { started.push(it.target); active++; return it.target; } });
  q.enqueue("new", "pending-a", "one");
  q.enqueue("new", "pending-b", "two");
  assert.equal(await q.tick(), null);
  assert.deepEqual(started, []);
  assert.equal(told, 1, "turns wait at the cap: the hook is told (the adapter asks which live files are dead)");
  active = 3;
  assert.equal(await q.tick(), "pending-a");
  assert.equal(await q.tick(), null, "the start took the free slot");
  assert.deepEqual(started, ["pending-a"]);
  active = 2;
  await q.tick();
  assert.deepEqual(started, ["pending-a", "pending-b"]);
  assert.equal(q.length(), 0);
  assert.equal(onDisk(file).length, 0, "what started leaves the file too");
});

test("tick: a message to a session still in its own turn waits without holding the line behind it", async () => {
  const file = tmpFile();
  const started = [];
  const q = createTurnQueue({ file, cap: 4, active: () => 1, log: quiet,
                              ready: (it) => it.target !== "local_busy",
                              start: async (it) => { started.push(it.target); return it.target; } });
  q.enqueue("send", "local_busy", "later");
  q.enqueue("new", "pending-c", "now");
  await q.tick();
  assert.deepEqual(started, ["pending-c"]);
  assert.equal(q.place("local_busy"), 1, "it waits for its session, first in line");
});

test("allows: a waiting turn that cannot start now — its session in its own turn, or backed off — lets a newcomer start", async () => {
  const file = tmpFile();
  let clock = 1000, busy = true;
  const q = createTurnQueue({ file, cap: 4, active: () => 1, log: quiet, now: () => clock,
                              retryable: (e) => e.code === "locked",
                              ready: (it) => !(busy && it.target === "local_busy"),
                              start: async () => refuse("locked") });
  q.enqueue("send", "local_busy", "after its turn");
  assert.equal(q.allows(), true, "its session is in its own turn: a newcomer passes");
  busy = false;
  assert.equal(q.allows(), false, "its session is free: the free slot is its");
  await q.tick();                                  // refused, pressed nothing: backed off
  assert.equal(q.allows(), true, "backed off: a newcomer passes");
  clock += backoff(1);
  assert.equal(q.allows(), false, "its back-off is over: the slot is its again");
});

test("a start that pressed nothing stays in line however long it takes, backed off, and goes once it can", async () => {
  const file = tmpFile();
  const failed = [], sent = [];
  let clock = 0, code = "no-app";
  const q = createTurnQueue({ file, cap: 2, active: () => 0, log: quiet, now: () => clock,
                              retryable: (e) => e.code !== "unknown", owners: (e) => e.code === "not-sent",
                              failed: (it, e) => failed.push([it.target, e.code]),
                              start: async (it) => { if (code) refuse(code); sent.push(it.text); return it.target; } });
  q.enqueue("send", "local_s", "while the app is away");
  for (let i = 0; i < 40; i++) {                   // forty refusals, a minute apart at most: half an hour and more
    await q.tick();
    assert.equal(q.length(), 1, "never dropped");
    assert.equal(await q.tick(), null, "backed off: not tried again at once");
    clock += 60001;
  }
  assert.deepEqual(failed, []);
  assert.deepEqual([backoff(1), backoff(2), backoff(3), backoff(9)], [3000, 6000, 12000, 60000]);
  code = null;
  await q.tick();
  assert.deepEqual(sent, ["while the app is away"], "the app is back: sent, once");
  assert.equal(q.length(), 0);
});

test("a start that may have been delivered leaves the line at once, reported — never sent twice", async () => {
  const file = tmpFile();
  const failed = [];
  let tries = 0;
  const q = createTurnQueue({ file, cap: 2, active: () => 0, log: quiet,
                              retryable: (e) => e.code === "not-sent",
                              failed: (it, e) => failed.push([it.target, it.qid, e.code]),
                              start: async () => { tries++; refuse("not-confirmed"); } });
  const { qid } = q.enqueue("send", "local_d", "hello");
  await q.tick();
  await q.tick();
  assert.equal(tries, 1);
  assert.equal(q.length(), 0);
  assert.deepEqual(failed, [["local_d", qid, "not-confirmed"]], "its sender learns it by the id it was given");
});

test("back-off: an item that pressed nothing never holds the line behind it", async () => {
  const file = tmpFile();
  const started = [];
  const q = createTurnQueue({ file, cap: 3, active: () => 0, log: quiet, now: () => 5000000,
                              retryable: (e) => e.code === "not-sent",
                              start: async (it) => { if (it.target === "local_draft") refuse("not-sent"); started.push(it.target); return it.target; } });
  q.enqueue("send", "local_draft", "behind a draft");
  q.enqueue("new", "pending-g", "after it");
  await q.tick();                                  // the draft refuses, backed off
  await q.tick();                                  // the next one passes it
  assert.deepEqual(started, ["pending-g"]);
  assert.equal(q.place("local_draft"), 1);
});

test("one session's messages keep their order: a backed-off message holds the next one for its session, not others'", async () => {
  const file = tmpFile();
  const sent = [];
  let clock = 1000, refuseB = true;
  const q = createTurnQueue({ file, cap: 3, active: () => 0, log: quiet, now: () => clock,
                              retryable: (e) => e.code === "locked",
                              start: async (it) => { if (it.text === "B" && refuseB) refuse("locked"); sent.push(it.text); return it.target; } });
  q.enqueue("send", "local_s", "B");
  q.enqueue("send", "local_s", "C");
  q.enqueue("send", "local_t", "T");
  await q.tick();                                  // B meets another drive: backed off
  await q.tick();                                  // T (another session) passes it
  await q.tick();                                  // C does not: it waits for B
  assert.deepEqual(sent, ["T"], "C never passes B; T (another session) does");
  assert.equal(q.allows(), true, "B is backed off and C waits for B: neither holds a newcomer");
  refuseB = false;
  clock += backoff(1);
  assert.equal(q.allows(), false, "B can go now: the free slot is its");
  await q.tick();
  await q.tick();
  assert.deepEqual(sent, ["T", "B", "C"]);
});

test("a restart in the middle of a start never starts it again: reported as maybe delivered", async () => {
  const file = tmpFile();
  let release;
  const q = createTurnQueue({ file, cap: 2, active: () => 0, log: quiet,
                              start: () => new Promise((r) => { release = r; }) });
  const { qid } = q.enqueue("new", "pending-h", "long start");
  const going = q.tick();                          // the start is under way: marked on disk before it left
  assert.ok(onDisk(file)[0].sent, "marked sent before the start left");
  const failed = [];
  const again = createTurnQueue({ file, cap: 2, active: () => 0, log: quiet,   // the adapter restarted here
                                  start: async () => { throw new Error("must not start again"); },
                                  failed: (it, e) => failed.push([it.target, it.qid, e.code]) });
  assert.deepEqual(failed, [], "nothing is read before the first use");
  assert.equal(again.length(), 0, "not in the line any more");
  assert.deepEqual(failed, [["pending-h", qid, "unknown"]]);
  assert.equal(onDisk(file).length, 0);
  release("done"); await going;
});

test("keep: a promise the line kept sends what still waits for it to its session — on disk too", async () => {
  const file = tmpFile();
  const q = createTurnQueue({ file, cap: 1, active: () => 1, start: async () => "x", log: quiet });
  const first = q.enqueue("new", "pending-k", "start it");
  const later = q.enqueue("new", "pending-k", "and then this");
  q.enqueue("send", "local_other", "not this one");
  q.keep("pending-k", "local_kept");
  assert.deepEqual(q.qids("local_kept"), [first.qid, later.qid]);
  assert.equal(q.place("pending-k"), 0);
  const started = [];
  const restarted = createTurnQueue({ file, cap: 1, active: () => 0, log: quiet,
                                      start: async (it) => { started.push([it.kind, it.target, it.text]); return it.target; } });
  assert.deepEqual(onDisk(file).map((x) => [x.kind, x.target]), [["send", "local_kept"], ["send", "local_kept"], ["send", "local_other"]]);
  assert.deepEqual(restarted.qids("local_kept"), [first.qid, later.qid]);
  await restarted.tick();
  assert.deepEqual(started, [["send", "local_kept", "start it"]], "the restarted line sends to the session — never a second one");
});

test("outcomes are kept a day beside the line: after a restart, what a promise became and what the line gave up on", () => {
  const file = tmpFile();
  let clock = 1000;
  const q = createTurnQueue({ file, cap: 1, active: () => 1, start: async () => "x", log: quiet, now: () => clock });
  q.keep("pending-p", "local_p");
  q.noteFailed("local_s", "qid-1", "not-confirmed", true);
  q.noteFailed("pending-x", "qid-2", "unknown", true);
  const again = createTurnQueue({ file, cap: 1, active: () => 1, start: async () => "x", log: quiet, now: () => clock });
  assert.equal(again.keptOf("pending-p"), "local_p");
  assert.equal(again.promiseOf("local_p"), "pending-p");
  assert.deepEqual(again.failedFor("local_s"), [{ qid: "qid-1", code: "not-confirmed", maybe: true, at: 1000 }]);
  assert.deepEqual(again.failedFor("pending-x").map((x) => x.code), ["unknown"]);
  assert.deepEqual(again.failedFor("local_other"), []);
  clock += 86400001;                               // a day later: forgotten
  assert.equal(again.keptOf("pending-p"), null);
  assert.deepEqual(again.failedFor("local_s"), []);
});

test("enqueue: a line that cannot be written queues nothing", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "turn-queue-ro-"));
  const file = path.join(dir, "sub", "turn-queue.json");
  fs.writeFileSync(path.join(dir, "sub"), "a file where the folder should be");
  const q = createTurnQueue({ file, cap: 1, active: () => 1, start: async () => "x", log: quiet });
  assert.throws(() => q.enqueue("new", "pending-i", "x"));
  assert.equal(q.length(), 0, "not queued when not written");
});

test("no cap: the line still drains what an earlier cap left on disk", async () => {
  const file = tmpFile();
  const first = createTurnQueue({ file, cap: 1, active: () => 1, start: async () => "x", log: quiet });
  first.enqueue("new", "pending-e", "left over");
  const started = [];
  const q = createTurnQueue({ file, cap: 0, active: () => 50, log: quiet,
                              start: async (it) => { started.push(it.target); return it.target; } });
  assert.equal(q.allows(), true);
  await q.tick();
  assert.deepEqual(started, ["pending-e"]);
});

test("an unreadable line file is an empty line, never a crash", () => {
  const file = tmpFile();
  fs.writeFileSync(file, "{not json");
  const q = createTurnQueue({ file, cap: 4, active: () => 0, start: async () => "x", log: quiet });
  assert.equal(q.length(), 0);
  const aside = fs.readdirSync(path.dirname(file)).filter((f) => f.startsWith("turn-queue.json.unreadable-"));
  assert.equal(aside.length, 1, "what it held is kept beside it, never written over");
  assert.equal(fs.readFileSync(path.join(path.dirname(file), aside[0]), "utf8"), "{not json");
  fs.writeFileSync(file, JSON.stringify({ v: 1, items: [{ qid: "1", kind: "new", target: "pending-f", text: "ok" }, { bad: 1 }] }));
  assert.equal(createTurnQueue({ file, cap: 4, active: () => 0, start: async () => "x", log: quiet }).length(), 1);
});
