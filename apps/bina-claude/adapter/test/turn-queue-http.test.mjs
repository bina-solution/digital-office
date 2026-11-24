// The turn cap at the adapter's own door (server.mjs + turn-queue.mjs, DGO-2126), with the real server, a fake app
// home and a fake `docker` that answers as the driver answers and logs every call. At the cap a message is QUEUED —
// 202, its place, its id (`qid`), a note — and nothing is driven until a slot frees. The line drains through the
// server: a promise becomes its session and a later message to it goes to that session, across an adapter restart
// too; messages to one session go in order; a retry while a drive runs is refused («locked»), never queued; a queued
// message the driver may have delivered is reported by its id in the session's summary and never sent again; one that
// pressed nothing stays and goes once it can; a live file whose process is gone holds no slot. Under the cap, and
// with no cap, a message goes to the driver at once.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = path.join(HERE, "..", "server.mjs");
const REPO = path.resolve(HERE, "..", "..", "..", "..");      // the adapter reads the driver's source from the checkout
const TOKEN = "t".repeat(40);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(cond, ms = 9000) {
  const t = Date.now();
  while (Date.now() - t < ms) { if (await cond()) return true; await sleep(50); }
  return !!(await cond());
}

// `docker exec … python3 -I -c <driver> <verb> [<id>]`, answered as the driver answers: `new` makes a session (its
// record, and its live file «busy»: its first turn runs); `send` puts a turn into a session that is not in one, and is
// refused «busy» otherwise; `live` names the dead files fake.json lists. fake.json: { refuse, slow, dead }.
const FAKE_DOCKER = `#!/usr/bin/env node
const fs = require("fs"), path = require("path");
const root = process.env.FAKE_ROOT, desk = process.env.BINA_CLAUDE_DESKTOP_HOME;
const args = process.argv.slice(2), c = args.indexOf("-c");
const verb = args[c + 2], sid = args[c + 3] || null;
const conf = (() => { try { return JSON.parse(fs.readFileSync(path.join(root, "fake.json"), "utf8")); } catch { return {}; } })();
const text = verb === "new" || verb === "send" ? fs.readFileSync(0, "utf8").trim() : "";
const say = (j) => {
  fs.appendFileSync(path.join(root, "calls.jsonl"), JSON.stringify({ verb, sid, text, ok: !!j.ok, code: j.code || null }) + "\\n");
  process.stdout.write(JSON.stringify(j) + "\\n");
  process.exit(j.ok ? 0 : 1);
};
const liveFile = (id) => path.join(desk, ".claude", "sessions", id + ".json");
const busy = (id) => fs.writeFileSync(liveFile(id), JSON.stringify({ hostSessionId: id, status: "busy", startedAt: Date.now() }));
setTimeout(() => {
  if (verb === "live") return say({ ok: true, dead: conf.dead || [] });
  if (conf.refuse) return say({ ok: false, code: conf.refuse, error: conf.error || "the fake driver refuses: " + conf.refuse, ...(conf.left ? { left: true } : {}) });
  if (verb === "new") {
    const dir = path.join(desk, ".config/Claude/claude-code-sessions/x/y");
    const id = "local_fake" + (fs.readdirSync(dir).filter((f) => f.startsWith("local_fake")).length + 1);
    fs.writeFileSync(path.join(dir, id + ".json"), JSON.stringify({ sessionId: id, title: text.slice(0, 30), createdAt: Date.now() }));
    busy(id);
    return say({ ok: true, id });
  }
  if (verb === "send") {
    let st = null;
    try { st = JSON.parse(fs.readFileSync(liveFile(sid), "utf8")).status; } catch { /* no process: idle */ }
    if (st === "busy") return say({ ok: false, code: "busy", error: "the session is in a turn" });
    busy(sid);
    return say({ ok: true });
  }
  say({ ok: false, code: "not-sent", error: "the fake knows no " + verb });
}, conf.slow || 0);
`;

// the driver's own words for a draft of the owner's in the box (drive fill()): his work, given up after two tries
const DRAFT = "nothing was sent: the composer is not empty (a draft of the owner's, or the click did not land in it)";

// one live file per session (named by it): the newest status is the one the adapter reads
const setLive = (desk, id, status, extra = {}) =>
  fs.writeFileSync(path.join(desk, ".claude", "sessions", `${id}.json`), JSON.stringify({ hostSessionId: id, status, startedAt: Date.now(), ...extra }));

function freePort() {
  return new Promise((resolve) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
}

// An adapter on a fresh office (or, with `root`, the same office again: a restart)
async function adapter({ cap, busy = 0, idle = [], root = null }) {
  const fresh = !root;
  root = root || fs.mkdtempSync(path.join(os.tmpdir(), "turn-cap-"));
  const state = path.join(root, "state"), desk = path.join(root, "desk"), bin = path.join(root, "bin");
  if (fresh) {
    for (const d of [state, bin, path.join(desk, ".claude", "sessions"), path.join(desk, ".config/Claude/claude-code-sessions/x/y")]) {
      fs.mkdirSync(d, { recursive: true });
    }
    fs.writeFileSync(path.join(state, "api-token"), TOKEN);
    fs.writeFileSync(path.join(bin, "docker"), FAKE_DOCKER, { mode: 0o755 });
    for (let i = 0; i < busy; i++) setLive(desk, `local_busy${i}`, "busy");
    for (const id of idle) {                          // a session of the app with no process: idle
      fs.writeFileSync(path.join(desk, ".config/Claude/claude-code-sessions/x/y", `${id}.json`), JSON.stringify({ sessionId: id, title: id, createdAt: Date.now() }));
    }
  }
  const port = await freePort();
  const child = spawn(process.execPath, [SERVER], { stdio: ["ignore", "ignore", "pipe"], env: {
    ...process.env, PATH: `${bin}:${process.env.PATH}`, FAKE_ROOT: root, BBOX_REPO_HOST: REPO,
    BINA_CLAUDE_STATE: state, AGENT_TOKEN_FILE: path.join(state, "api-token"), BINA_CLAUDE_DESKTOP_HOME: desk,
    BINA_CLAUDE_ADAPTER_PORT: String(port), BINA_CLAUDE_MAX_TURNS: String(cap), BINA_CLAUDE_SIGNIN_WATCH: "off",
    BINA_CLAUDE_HOME_FOLDER: "off", BINA_CLAUDE_DESKTOP_CONTAINER: "fake-desktop", BINA_CLAUDE_LINE_EVERY_MS: "100" } });
  let err = "";
  child.stderr.on("data", (d) => { err += d; });
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    try { await fetch(`${base}/v1/health`); break; } catch { await sleep(50); }
  }
  const call = async (method, p, body) => {
    const r = await fetch(base + p, { method, headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
                                      body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, json: await r.json().catch(() => null) };
  };
  const calls = () => { try { return fs.readFileSync(path.join(root, "calls.jsonl"), "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; } };
  const line = () => { try { return JSON.parse(fs.readFileSync(path.join(state, "turn-queue.json"), "utf8")).items; } catch { return []; } };
  return {
    call, root, state, desk, calls, line, log: () => err, stop: () => child.kill("SIGKILL"),
    sent: () => calls().filter((c) => c.ok && (c.verb === "new" || c.verb === "send")),   // what reached the app
    fake: (conf) => fs.writeFileSync(path.join(root, "fake.json"), JSON.stringify(conf)),
    turnEnds: (id) => setLive(desk, id, "idle"),
  };
}

test("at the cap: a new session's message waits in the line; the sender is told; nothing is driven", async (t) => {
  const a = await adapter({ cap: 2, busy: 2 });
  t.after(a.stop);
  const r = await a.call("POST", "/v1/sessions", { text: "סקירה" });
  assert.equal(r.status, 202, a.log());
  assert.deepEqual([r.json.queued, r.json.queue], [true, 1]);
  assert.match(r.json.id, /^pending-/);
  assert.match(r.json.qid, /^[0-9a-f-]{36}$/);
  assert.match(r.json.note, /#1 in line/);
  const again = await a.call("POST", `/v1/sessions/${r.json.id}/messages`, { text: "סקירה" });
  assert.deepEqual([again.status, again.json.queue, again.json.qid], [202, 1, r.json.qid], "a retry keeps its place and id");
  const read = await a.call("GET", `/v1/sessions/${r.json.id}`);
  assert.deepEqual([read.status, read.json.starting, read.json.queued, read.json.failed], [200, true, true, undefined],
    "a promise in the line is starting, never «never sent»");
  assert.equal(a.line().length, 1, "the line is on disk");
  await sleep(600);                                 // six looks of the line
  assert.deepEqual(a.sent(), [], "nothing was driven");
  const h = await a.call("GET", "/v1/health");
  assert.deepEqual([h.json.max_turns, h.json.queued], [2, 1]);
});

test("the line drains through the server: a promise becomes its session, a later message goes to it — across a restart too", async (t) => {
  let a = await adapter({ cap: 1, busy: 1 });
  t.after(() => a.stop());
  const p = await a.call("POST", "/v1/sessions", { text: "first" });
  const later = await a.call("POST", `/v1/sessions/${p.json.id}/messages`, { text: "second" });
  assert.deepEqual([p.status, later.status, later.json.queue], [202, 202, 2]);
  a.turnEnds("local_busy0");                        // a slot frees
  const realOf = async () => (await a.call("GET", `/v1/sessions/${p.json.id}`)).json?.id;
  assert.ok(await until(async () => String(await realOf()).startsWith("local_fake")), a.log());
  const real = await realOf();
  assert.deepEqual(a.line().map((x) => [x.kind, x.target, x.text]), [["send", real, "second"]],
    "what waits for the promise now waits for its session — on disk");
  const s = (await a.call("GET", `/v1/sessions/${real}`)).json;
  assert.deepEqual([s.queue, s.line, s.from], [1, [later.json.qid], p.json.id]);
  a.stop();                                         // the adapter restarts while the session's first turn runs
  a = await adapter({ cap: 1, root: a.root });
  a.turnEnds(real);
  assert.ok(await until(() => a.sent().length === 2), a.log());
  assert.deepEqual(a.sent().map((c) => [c.verb, c.sid, c.text]), [["new", null, "first"], ["send", real, "second"]],
    "one session; both messages, in order, each once");
});

test("messages to one session go in order: a newcomer under the cap waits behind one already in line", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(a.stop);
  const b = await a.call("POST", "/v1/sessions/local_s/messages", { text: "B" });
  assert.deepEqual([b.status, b.json.queued], [202, true]);
  a.fake({ refuse: "locked" });                     // the line's first try meets another drive: B backs off (3 s)
  a.turnEnds("local_busy0");
  assert.ok(await until(() => a.calls().some((c) => c.verb === "send")), a.log());
  await sleep(300);                                 // that drive has ended (during one, a message is refused «locked»)
  const c = await a.call("POST", "/v1/sessions/local_s/messages", { text: "C" });
  assert.deepEqual([c.status, c.json.queued, c.json.queue], [202, true, 2], "C waits behind B, though the office is under its cap");
  a.fake({});
  assert.ok(await until(() => a.sent().length === 1), a.log());
  await sleep(300);                                 // the line sees B's turn run (a delivery it never sees running
  a.turnEnds("local_s");                            // holds its slot 20 s at most) — then B's turn ends
  assert.ok(await until(() => a.sent().length === 2), a.log());
  assert.deepEqual(a.sent().map((x) => x.text), ["B", "C"]);
});

test("a retry while a drive runs is refused («locked»), never queued — the drive may be that very message", async (t) => {
  const a = await adapter({ cap: 1, idle: ["local_s"] });
  t.after(a.stop);
  a.fake({ slow: 1500 });
  const first = a.call("POST", "/v1/sessions/local_s/messages", { text: "A" });   // under the cap: driven at once
  await sleep(400);
  setLive(a.desk, "local_other", "busy");           // meanwhile a turn starts on the app's screen: the office is at its cap
  const retry = await a.call("POST", "/v1/sessions/local_s/messages", { text: "A" });
  assert.deepEqual([retry.status, retry.json && retry.json.code], [409, "locked"], a.log());
  assert.equal((await first).status, 202);
  assert.deepEqual(a.line(), [], "nothing queued");
  await sleep(500);
  assert.deepEqual(a.sent().map((x) => x.text), ["A"], "A went once");
});

test("a queued message the driver may have delivered leaves the line, is never sent again, and its sender finds it by its id", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(a.stop);
  const q = await a.call("POST", "/v1/sessions/local_s/messages", { text: "X" });
  a.fake({ refuse: "not-confirmed" });
  a.turnEnds("local_busy0");
  const failedOf = async () => (await a.call("GET", "/v1/sessions/local_s")).json.line_failed;
  assert.ok(await until(async () => (await failedOf()).length === 1), a.log());
  const s = (await a.call("GET", "/v1/sessions/local_s")).json;
  const f = s.line_failed[0];
  assert.deepEqual([s.queue, s.line, f.qid, f.code, f.maybe], [0, [], q.json.qid, "not-confirmed", true]);
  await sleep(500);
  assert.equal(a.calls().filter((x) => x.verb === "send").length, 1, "tried once, never again");
});

test("a queued message that pressed nothing stays in line, backed off, and goes once it can", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(a.stop);
  const q = await a.call("POST", "/v1/sessions/local_s/messages", { text: "Y" });
  a.fake({ refuse: "locked" });                     // another drive: it clears by itself
  a.turnEnds("local_busy0");
  assert.ok(await until(() => a.calls().some((x) => x.verb === "send")), a.log());
  const s = (await a.call("GET", "/v1/sessions/local_s")).json;
  assert.deepEqual([s.line, s.line_failed], [[q.json.qid], []], "still waiting, nothing failed");
  a.fake({});
  assert.ok(await until(() => a.sent().length === 1), a.log());
  // the driver answered; the line lets it go a moment later
  assert.ok(await until(async () => (await a.call("GET", "/v1/sessions/local_s")).json.line.length === 0), a.log());
  assert.equal(a.sent().length, 1, "sent once");
});

test("after an adapter restart a sender still learns: what a promise became, and what the line gave up on", async (t) => {
  let a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(() => a.stop());
  const p = await a.call("POST", "/v1/sessions", { text: "first" });
  a.turnEnds("local_busy0");
  const keptOnDisk = () => { try { return (JSON.parse(fs.readFileSync(path.join(a.state, "turn-queue.json"), "utf8")).kept || {})[p.json.id]; } catch { return null; } };
  assert.ok(await until(() => !!keptOnDisk()), a.log());          // the line started it; nobody has asked yet
  const real = keptOnDisk().id;
  const q = await a.call("POST", "/v1/sessions/local_s/messages", { text: "X" });
  assert.equal(q.json && q.json.queued, true, "at the cap: the new session's first turn runs");
  a.fake({ refuse: "not-confirmed" });
  a.turnEnds(real);
  assert.ok(await until(() => a.calls().some((c) => c.verb === "send")), a.log());
  await sleep(300);
  a.stop();                                         // a deploy
  a = await adapter({ cap: 1, root: a.root });
  const promise = (await a.call("GET", `/v1/sessions/${p.json.id}`)).json;
  assert.equal(promise.id, real, "the promise reads as the session it became");
  assert.equal((await a.call("GET", `/v1/sessions/${real}`)).json.from, p.json.id);
  const s = (await a.call("GET", "/v1/sessions/local_s")).json;
  assert.deepEqual(s.line_failed.map((f) => [f.qid, f.code, f.maybe]), [[q.json.qid, "not-confirmed", true]],
    "what the line gave up on is still said, by its id");
});

test("a refusal after the text went into the app's composer leaves the line — «not known», never tried again", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(a.stop);
  const q = await a.call("POST", "/v1/sessions/local_s/messages", { text: "Z" });
  a.fake({ refuse: "busy", left: true });           // pasted, then the session took a turn: the text waits in its composer
  a.turnEnds("local_busy0");
  const failedOf = async () => (await a.call("GET", "/v1/sessions/local_s")).json.line_failed;
  assert.ok(await until(async () => (await failedOf()).length === 1), a.log());
  const f = (await failedOf())[0];
  assert.deepEqual([f.qid, f.code, f.maybe], [q.json.qid, "left-in-composer", true]);
  await sleep(4000);                                // past a back-off: nothing tries it again
  assert.equal(a.calls().filter((x) => x.verb === "send").length, 1, "tried once");
});

test("a queued message refused for the owner's own work in the app is given up after two tries, said «not sent»", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(a.stop);
  const q = await a.call("POST", "/v1/sessions/local_s/messages", { text: "W" });
  a.fake({ refuse: "not-sent", error: DRAFT });     // a draft of his in that session's box, in the driver's own words
  a.turnEnds("local_busy0");
  const failedOf = async () => (await a.call("GET", "/v1/sessions/local_s")).json.line_failed;
  assert.ok(await until(async () => (await failedOf()).length === 1), a.log());
  const f = (await failedOf())[0];
  assert.deepEqual([f.qid, f.code, f.maybe], [q.json.qid, "not-sent", false]);
  assert.equal(a.calls().filter((x) => x.verb === "send").length, 2, "two tries, no more: each one pulls his screen");
});

test("a new conversation whose first message the line gave up on, having sent nothing, starts with the next one", async (t) => {
  const a = await adapter({ cap: 1, busy: 1 });
  t.after(a.stop);
  const p = await a.call("POST", "/v1/sessions", { text: "A" });
  a.fake({ refuse: "not-sent", error: DRAFT });     // his draft on the New page: two tries, then given up
  a.turnEnds("local_busy0");
  const readP = async () => (await a.call("GET", `/v1/sessions/${p.json.id}`)).json;
  assert.ok(await until(async () => (await readP()).failed === "not-sent"), a.log());
  const r = await readP();
  assert.deepEqual([r.starting, r.maybe], [false, false], "said as «not sent», nothing starting");
  a.fake({});
  const again = await a.call("POST", `/v1/sessions/${p.json.id}/messages`, { text: "A, again" });
  assert.equal(again.status, 202, `the next message is taken, not refused for a day: ${JSON.stringify(again.json)}`);
  assert.match(String(again.json.id), /^local_fake/, "…and starts the conversation");
  assert.deepEqual(a.sent().map((c) => [c.verb, c.text]), [["new", "A, again"]]);
});

test("after a deploy, a promise whose start may have been delivered never starts from a later message of it", async (t) => {
  let a = await adapter({ cap: 1 });                // a fresh office, then its line as a deploy left it:
  a.stop();                                         // A's start ended «not-confirmed»; B, a later message of it, waits
  const P = "pending-00000000-0000-4000-8000-0000000000aa";
  fs.writeFileSync(path.join(a.state, "turn-queue.json"), JSON.stringify({ v: 1,
    items: [{ qid: "qid-b", kind: "new", target: P, text: "B", at: Date.now() }], kept: {},
    failed: [{ target: P, qid: "qid-a", code: "not-confirmed", maybe: true, at: Date.now() }] }));
  a = await adapter({ cap: 1, root: a.root });
  t.after(() => a.stop());
  const read = (await a.call("GET", `/v1/sessions/${P}`)).json;
  assert.deepEqual([read.starting, read.failed], [false, "not-confirmed"], "its answer, though B still waits");
  assert.ok(await until(() => a.line().length === 0), a.log());
  assert.deepEqual(a.sent(), [], "B never started a second session");
  assert.ok(a.calls().every((c) => c.verb !== "new"));
});

test("every read of a session's messages carries what waits for it in the line", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s"] });
  t.after(a.stop);
  const q = await a.call("POST", "/v1/sessions/local_s/messages", { text: "V" });
  const m = (await a.call("GET", "/v1/sessions/local_s/messages?limit=5")).json;
  assert.deepEqual([m.line, m.line_places], [[q.json.qid], [1]]);
  const s = (await a.call("GET", "/v1/sessions/local_s")).json;
  assert.deepEqual([s.line, s.line_places, s.line_place], [[q.json.qid], [1], 1]);
});

test("a live file whose process is gone holds no slot: the desktop's /proc says so, and the line goes on", async (t) => {
  const a = await adapter({ cap: 1 });
  t.after(a.stop);
  fs.writeFileSync(path.join(a.desk, ".claude", "sessions", "4242.json"),
                   JSON.stringify({ hostSessionId: "local_ghost", status: "busy", startedAt: 77 }));
  a.fake({ dead: [{ file: "4242.json", startedAt: 77 }] });
  const r = await a.call("POST", "/v1/sessions", { text: "after the ghost" });
  assert.equal(r.json && r.json.queued, true, "until the desktop is asked, the ghost counts");
  assert.ok(await until(() => a.sent().length === 1), a.log());
  assert.ok(a.calls().some((x) => x.verb === "live"), "the line asked the desktop which files are dead");
});

test("a sender that cannot follow a line is never held by it: at the cap it goes to the app at once, as before the cap", async (t) => {
  const a = await adapter({ cap: 1, busy: 1, idle: ["local_s", "local_t"] });
  t.after(a.stop);
  const r = await a.call("POST", "/v1/sessions/local_s/messages", { text: "from the group", queue: false });
  assert.deepEqual([r.status, r.json && r.json.queued], [202, undefined], a.log());
  assert.deepEqual(a.sent().map((c) => [c.sid, c.text]), [["local_s", "from the group"]], "a wave in the line never starves a person");
  assert.deepEqual(a.line(), [], "nothing of it waits");
  const other = await a.call("POST", "/v1/sessions/local_t/messages", { text: "queued by another" });
  assert.equal(other.json.queued, true);
  const again = await a.call("POST", "/v1/sessions/local_t/messages", { text: "from the group", queue: false });
  assert.deepEqual([again.status, again.json && again.json.queued], [202, undefined], "not held behind another sender's message either");
  assert.deepEqual(a.sent().map((c) => c.text), ["from the group", "from the group"]);
  assert.deepEqual(a.line().map((x) => x.text), ["queued by another"], "the other sender's message still waits its turn");
  const busy = await a.call("POST", "/v1/sessions/local_t/messages", { text: "and more", queue: false });
  assert.deepEqual([busy.status, busy.json && busy.json.code], [409, "busy"], "a session in its turn refuses it, as it always did");
});

test("a dead verdict is never taken against a live file written in the last two minutes", async (t) => {
  const a = await adapter({ cap: 1 });
  t.after(a.stop);
  const ghost = path.join(a.desk, ".claude", "sessions", "4343.json");
  fs.writeFileSync(ghost, JSON.stringify({ hostSessionId: "local_fresh", status: "busy", startedAt: 88, updatedAt: Date.now() }));
  a.fake({ dead: [{ file: "4343.json", startedAt: 88 }] });
  const r = await a.call("POST", "/v1/sessions", { text: "behind a fresh file" });
  assert.equal(r.json && r.json.queued, true);
  assert.ok(await until(() => a.calls().some((x) => x.verb === "live")), a.log());
  await sleep(600);
  assert.deepEqual(a.sent(), [], "written a moment ago: its process runs, whatever the verdict — it still counts");
  fs.writeFileSync(ghost, JSON.stringify({ hostSessionId: "local_fresh", status: "busy", startedAt: 88, updatedAt: Date.now() - 180000 }));
  assert.ok(await until(() => a.sent().length === 1), a.log());
});

test("under the cap, and with no cap, a message goes to the driver at once", async (t) => {
  const a = await adapter({ cap: 2, busy: 1 });
  t.after(a.stop);
  const r = await a.call("POST", "/v1/sessions", { text: "now" });
  assert.deepEqual([r.status, r.json.queued], [201, undefined], a.log());
  assert.match(r.json.id, /^local_fake/);
  assert.equal(fs.existsSync(path.join(a.state, "turn-queue.json")), false, "nothing queued");
  const b = await adapter({ cap: 0, busy: 9 });
  t.after(b.stop);
  const r2 = await b.call("POST", "/v1/sessions", { text: "now" });
  assert.equal(r2.status, 201, b.log());
});
