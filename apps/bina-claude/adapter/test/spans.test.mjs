// node --test apps/bina-claude/adapter/test/spans.test.mjs — the bina-claude lane on כל מקביל (DGO-1684).
// Synthetic transcripts in Claude Code's own record shapes (no real session's content), in a temp HOME.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createSpanStore, liveSessions } from "../spans.mjs";

// any-concurrency's own vocabulary (apps/any-concurrency/app.py, _SPAN_STATUSES): a row outside it is drawn «unknown».
const STATUSES = new Set(["running", "success", "error", "canceled", "waiting", "crashed", "unknown"]);
const T0 = Date.parse("2026-11-09T10:00:00Z");
const at = (s) => new Date(T0 + s * 1000).toISOString();

const promptRec = (s, text) => ({ type: "user", timestamp: at(s), cwd: "/workspace/office", message: { role: "user", content: text } });
const toolUse = (s, id, name, input) => ({ type: "assistant", timestamp: at(s), message: { model: "claude-opus-5-5", stop_reason: "tool_use", content: [{ type: "tool_use", id, name, input }] } });
const toolResult = (s, id, isError = false) => ({ type: "user", timestamp: at(s), message: { role: "user", content: [{ type: "tool_result", tool_use_id: id, is_error: isError, content: "out" }] } });
const answer = (s, text, stop = "end_turn") => ({ type: "assistant", timestamp: at(s), message: { model: "claude-opus-5-5", stop_reason: stop, content: [{ type: "text", text }] } });
const stopHooks = (s) => ({ type: "system", subtype: "stop_hook_summary", timestamp: at(s) });

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "bina-claude-spans-"));
  fs.mkdirSync(path.join(h, ".claude", "projects", "-workspace-office"), { recursive: true });
  fs.mkdirSync(path.join(h, ".claude", "sessions"), { recursive: true });
  return h;
}
function write(h, id, recs, { append = false, mtimeS } = {}) {
  const f = path.join(h, ".claude", "projects", "-workspace-office", `${id}.jsonl`);
  const text = recs.map((r) => (typeof r === "string" ? r : JSON.stringify(r))).join("\n") + "\n";
  if (append) fs.appendFileSync(f, text); else fs.writeFileSync(f, text);
  if (mtimeS !== undefined) fs.utimesSync(f, new Date(T0 + mtimeS * 1000), new Date(T0 + mtimeS * 1000));
  return f;
}
function store(h, { live = new Map(), names = new Map(), nowS = 3600, chunk } = {}) {
  const clock = { s: nowS };
  const s = createSpanStore({ roots: [{ where: "desktop", home: h, live: () => live, names: () => names }],
                              now: () => T0 + clock.s * 1000, ...(chunk ? { chunk } : {}) });
  return { s, clock };
}
const byKind = (spans, kind) => spans.filter((r) => r.meta.kind === kind);

test("a finished turn: the session, the turn and its tool call, each with its real times and «success»", () => {
  const h = home();
  write(h, "aaaaaaaa-1111", [
    promptRec(0, "תבדוק את הדיסק בבקשה"),
    toolUse(2, "toolu_1", "Bash", { command: "df -h /", description: "Show disk usage" }),
    toolResult(5, "toolu_1"),
    answer(8, "הדיסק בסדר"),
    stopHooks(9),
  ], { mtimeS: 9 });
  const { spans } = store(h).s.read({ hours: 24 });
  for (const r of spans) {
    assert.ok(STATUSES.has(r.status), `${r.id} has status ${r.status}`);
    assert.equal(typeof r.s, "number");
    assert.equal(r.svc, "סשן aaaaaaaa");
  }
  const [session] = byKind(spans, "session");
  assert.equal(session.status, "success");
  assert.equal(session.s, T0);
  assert.equal(session.e, T0 + 9000);
  assert.equal(session.label, "תבדוק את הדיסק בבקשה");
  assert.equal(session.meta.turns, 1);
  const [turn] = byKind(spans, "turn");
  assert.deepEqual([turn.status, turn.s, turn.e], ["success", T0, T0 + 9000]);
  assert.equal(turn.label, "סבב 1 · תבדוק את הדיסק בבקשה");
  const [tool] = byKind(spans, "tool");
  assert.deepEqual([tool.status, tool.s, tool.e], ["success", T0 + 2000, T0 + 5000]);
  assert.equal(tool.label, "Bash · Show disk usage", "a Bash call is named by its description, not its command line");
});

test("a turn without Stop hooks ends at the answer that ends it; a tool that failed is «error»", () => {
  const h = home();
  write(h, "bbbbbbbb", [promptRec(0, "go"), toolUse(1, "t1", "Read", { file_path: "/x" }), toolResult(2, "t1", true), answer(3, "done")], { mtimeS: 3 });
  const { spans } = store(h).s.read({ hours: 24 });
  assert.deepEqual(byKind(spans, "turn").map((r) => [r.status, r.e]), [["success", T0 + 3000]]);
  assert.deepEqual(byKind(spans, "tool").map((r) => [r.label, r.status]), [["Read · /x", "error"]]);
});

test("an open turn is what its session is NOW: running, waiting, error when idle, crashed when gone", () => {
  const open = [promptRec(0, "long job"), toolUse(1, "t1", "Bash", { command: "sleep 600" })];
  const cases = [
    [new Map([["cccccccc", { sessionId: "cccccccc", status: "busy" }]]), "running", null],
    [new Map([["cccccccc", { sessionId: "cccccccc", status: "waiting" }]]), "waiting", null],
    [new Map([["cccccccc", { sessionId: "cccccccc", status: "idle" }]]), "error", T0 + 1000],
    [new Map(), "crashed", T0 + 1000],
  ];
  for (const [live, status, e] of cases) {
    const h = home();
    write(h, "cccccccc", open, { mtimeS: 1 });
    const { spans } = store(h, { live, nowS: 3600 }).s.read({ hours: 24 });
    for (const kind of ["session", "turn", "tool"]) {
      const [r] = byKind(spans, kind);
      assert.equal(r.status, status, `${kind} with live ${JSON.stringify([...live.values()])}`);
      assert.equal(r.e, e, `${kind} ends`);
    }
  }
});

test("a transcript written in the last 30 s is running even before its live file appears", () => {
  const h = home();
  write(h, "dddddddd", [promptRec(0, "start")], { mtimeS: 3590 });
  const { spans } = store(h, { nowS: 3600 }).s.read({ hours: 24 });
  assert.equal(byKind(spans, "turn")[0].status, "running");
});

test("Esc ends the turn «canceled»; an API error is an instant, and a turn the API gave up on is «error»", () => {
  const h = home();
  write(h, "eeeeeeee", [
    promptRec(0, "one"), toolUse(1, "t1", "Bash", { command: "x" }),
    { type: "user", timestamp: at(2), message: { role: "user", content: [{ type: "text", text: "[Request interrupted by user for tool use]" }] } },
    promptRec(10, "two"),
    { type: "system", subtype: "api_error", timestamp: at(11), retryAttempt: 1, maxRetries: 10, uuid: "u-err" },
    { type: "assistant", timestamp: at(20), isApiErrorMessage: true, message: { model: "<synthetic>", content: [{ type: "text", text: "API Error: overloaded" }] } },
  ], { mtimeS: 20 });
  const { spans } = store(h).s.read({ hours: 24 });
  assert.deepEqual(byKind(spans, "turn").map((r) => [r.label, r.status]), [["סבב 1 · one", "canceled"], ["סבב 2 · two", "error"]]);
  assert.equal(byKind(spans, "tool")[0].status, "canceled");
  assert.deepEqual(byKind(spans, "api-error").map((r) => [r.status, r.s === r.e]), [["error", true], ["error", true]]);
});

test("incremental: an appended line is read alone, and the delta returns what it closed", () => {
  const h = home();
  const live = new Map([["ffffffff", { sessionId: "ffffffff", status: "busy" }]]);
  write(h, "ffffffff", [promptRec(0, "go"), toolUse(1, "t1", "Bash", { command: "make" })], { mtimeS: 1 });
  const { s, clock } = store(h, { live, nowS: 100 });
  const first = s.read({ hours: 24 });
  assert.equal(byKind(first.spans, "tool")[0].status, "running");
  const bytes = s.stats.bytes;
  clock.s = 200;
  write(h, "ffffffff", [toolResult(150, "t1"), answer(151, "ok")], { append: true, mtimeS: 151 });
  live.set("ffffffff", { sessionId: "ffffffff", status: "idle" });
  const delta = s.read({ since: T0 + 140 * 1000 });
  const appended = fs.statSync(path.join(h, ".claude/projects/-workspace-office/ffffffff.jsonl")).size;
  assert.equal(s.stats.bytes, appended, "only the appended bytes were read the second time");
  assert.ok(s.stats.bytes - bytes < appended, "the first part was not read again");
  assert.deepEqual(byKind(delta.spans, "tool").map((r) => [r.status, r.e]), [["success", T0 + 150000]]);
  assert.equal(byKind(delta.spans, "turn")[0].status, "success");
  // Nothing changed since: an empty delta.
  clock.s = 300;
  assert.equal(s.read({ since: T0 + 250 * 1000 }).spans.length, 0);
});

test("the delta carries a span that turned out to have CRASHED, though it began and ended long before", () => {
  const h = home();
  const live = new Map([["gggggggg", { sessionId: "gggggggg", status: "busy" }]]);
  write(h, "gggggggg", [promptRec(0, "go")], { mtimeS: 0 });
  const { s, clock } = store(h, { live, nowS: 600 });
  assert.equal(byKind(s.read({ hours: 24 }).spans, "turn")[0].status, "running");
  live.clear();                                   // the process is gone
  clock.s = 700;
  const delta = s.read({ since: T0 + 650 * 1000 });
  const [turn] = byKind(delta.spans, "turn");
  assert.deepEqual([turn.status, turn.e], ["crashed", T0]);
});

test("the first deltas after a seed do not send the window again", () => {
  const h = home();
  write(h, "jjjjjjjj", [promptRec(0, "go"), answer(5, "ok")], { mtimeS: 5 });
  const { s, clock } = store(h, { nowS: 3600 });
  assert.equal(s.read({ hours: 24 }).spans.length, 2);
  clock.s = 3605;
  assert.equal(s.read({ since: T0 + 3545 * 1000 }).spans.length, 0, "a finished session changed nothing since");
});

test("a store that starts after a session died (the adapter restarted) still sends the crash in its first delta", () => {
  const h = home();
  write(h, "kkkkkkkk", [promptRec(0, "go"), toolUse(1, "t1", "Bash", { command: "x" })], { mtimeS: 1 });
  const { s } = store(h, { nowS: 600 });                      // no live file: the process is gone
  const delta = s.read({ since: T0 + 540 * 1000 });
  assert.deepEqual(delta.spans.map((r) => [r.meta.kind, r.status]).sort(),
                   [["session", "crashed"], ["tool", "crashed"], ["turn", "crashed"]]);
});

test("the window: a transcript last written before it is never opened", () => {
  const h = home();
  write(h, "old00000", [promptRec(0, "old"), answer(1, "x")], { mtimeS: 1 });
  write(h, "new00000", [promptRec(90000, "new"), answer(90001, "y")], { mtimeS: 90001 });
  const { s } = store(h, { nowS: 90100 });
  const { spans } = s.read({ hours: 1 });
  assert.deepEqual([...new Set(spans.map((r) => r.svcid))], ["new00000"]);
  assert.equal(s.stats.opened, 1);
});

test("a desktop session is named by the app: its title, and the id `bbox agent` knows it by", () => {
  const h = home();
  write(h, "hhhhhhhh", [promptRec(0, "hi"), answer(1, "hello")], { mtimeS: 1 });
  const names = new Map([["hhhhhhhh", { id: "local_1234abcd", title: "בדיקת דיסק" }]]);
  const { spans } = store(h, { names }).s.read({ hours: 24 });
  const [session] = byKind(spans, "session");
  assert.equal(session.label, "בדיקת דיסק");
  assert.equal(session.meta.session, "local_1234abcd");
  assert.ok(spans.every((r) => r.meta.session === "local_1234abcd" && r.svcid === "hhhhhhhh"));
});

test("Hebrew cut in half by a read, a line that is not JSON and a line still being written cost nothing", () => {
  const h = home();
  const f = write(h, "iiiiiiii", [promptRec(0, "שלום עולם, מה שלומך היום?"), "{not json", answer(2, "טוב")], { mtimeS: 2 });
  fs.appendFileSync(f, JSON.stringify(promptRec(3, "half")).slice(0, 20));   // no newline yet
  fs.utimesSync(f, new Date(T0 + 2000), new Date(T0 + 2000));
  const { spans } = store(h, { chunk: 7 }).s.read({ hours: 24 });
  assert.deepEqual(byKind(spans, "turn").map((r) => [r.label, r.status]), [["סבב 1 · שלום עולם, מה שלומך היום?", "success"]]);
});

// ── the second reader's findings (DGO-1684) ────────────────────────────────────────────────────────────
test("a 7-day view polled every few seconds parses its week once, though the delta poll runs between", () => {
  const h = home();
  write(h, "week0000", [promptRec(0, "old"), answer(1, "x")], { mtimeS: 1 });                 // 3 days before now
  const { s, clock } = store(h, { nowS: 3 * 86400 });
  s.read({ hours: 168 });
  const opened = s.stats.opened;
  for (let i = 1; i <= 5; i++) {
    clock.s += 4;
    s.read({ since: T0 + (clock.s - 65) * 1000 });
    assert.equal(byKind(s.read({ hours: 168 }).spans, "session").length, 1);
  }
  assert.equal(s.stats.opened, opened, "never opened again");
});

test("a turn whose transcript got no line for 12 hours is crashed, though a live file still says busy", () => {
  const h = home();
  write(h, "stale000", [promptRec(0, "go"), toolUse(1, "t1", "Bash", { command: "x" })], { mtimeS: 1 });
  const live = new Map([["stale000", { sessionId: "stale000", status: "busy" }]]);
  const { spans } = store(h, { live, nowS: 13 * 3600 }).s.read({ hours: 24 });
  assert.equal(byKind(spans, "turn")[0].status, "crashed");
  assert.equal(byKind(spans, "tool")[0].status, "crashed");
});

test("a background task's notice is not the owner's prompt, and one that arrives mid-turn cancels nothing", () => {
  const h = home();
  const notice = (s) => ({ type: "user", timestamp: at(s), promptSource: "system", origin: { kind: "task-notification" },
                           message: { role: "user", content: "<task-notification>\n<task-id>b1</task-id>\n</task-notification>" } });
  write(h, "notice00", [
    promptRec(0, "the owner's prompt"), toolUse(1, "t1", "Bash", { description: "build" }),
    notice(2),                                     // mid-turn
    toolResult(3, "t1"), answer(4, "done"),
    notice(100),                                   // after the turn: Claude answers it — a turn, named by its kind
    answer(101, "noted"),
  ], { mtimeS: 101 });
  const { spans } = store(h).s.read({ hours: 24 });
  assert.deepEqual(byKind(spans, "turn").map((r) => [r.label, r.status]),
                   [["סבב 1 · the owner's prompt", "success"], ["סבב 2 · התראה · task-notification", "success"]]);
  assert.equal(byKind(spans, "tool")[0].status, "success", "the tool that succeeded is «success»");
  assert.equal(byKind(spans, "session")[0].label, "the owner's prompt");
  assert.equal(byKind(spans, "message")[0].label, "בתוך הסבב · התראה · task-notification");
});

test("a prompt after a long silence closes the turn that never wrote its end, as error at its last line", () => {
  const h = home();
  write(h, "silent00", [promptRec(0, "one"), toolUse(1, "t1", "Bash", { command: "x" }), promptRec(1000, "two"), answer(1001, "ok")],
        { mtimeS: 1001 });
  const { spans } = store(h).s.read({ hours: 24 });
  assert.deepEqual(byKind(spans, "turn").map((r) => [r.label, r.status, r.e]),
                   [["סבב 1 · one", "error", T0 + 1000], ["סבב 2 · two", "success", T0 + 1001000]]);
});

test("a `!` shell command is no turn, and a person's own words are a prompt whatever they start with", () => {
  const h = home();
  const human = (s, text) => ({ type: "user", timestamp: at(s), origin: { kind: "human" }, message: { role: "user", content: text } });
  write(h, "bang0000", [
    human(0, "<bash-input>git status</bash-input>"), human(1, "<bash-stdout>clean</bash-stdout><bash-stderr></bash-stderr>"),
    human(2, "<div> is the tag I mean"), answer(3, "ok"),
  ], { mtimeS: 3 });
  const { spans } = store(h).s.read({ hours: 24 });
  assert.deepEqual(byKind(spans, "turn").map((r) => r.label), ["סבב 1 · <div> is the tag I mean"]);
});

test("a read parses at most its budget; the rest comes on the next reads, and the delta carries it", () => {
  const h = home();
  const recs = [];
  for (let i = 0; i < 40; i++) recs.push(promptRec(i * 10, `turn ${i} ${"x".repeat(200)}`), answer(i * 10 + 1, "ok"));
  write(h, "budget00", recs, { mtimeS: 400 });
  const clock = { s: 3600 };
  const s = createSpanStore({ roots: [{ where: "desktop", home: h }], now: () => T0 + clock.s * 1000, chunk: 1024, budget: 4096 });
  const first = s.read({ hours: 24 });
  assert.equal(first.behind, true);
  const seeded = byKind(first.spans, "turn").length;
  assert.ok(seeded > 0 && seeded < 40, `the first read stops at its budget (${seeded} turns)`);
  const got = new Map(byKind(first.spans, "turn").map((r) => [r.id, r.status]));
  for (let i = 0; i < 40; i++) {
    clock.s += 5;
    const d = s.read({ since: T0 + (clock.s - 65) * 1000 });
    for (const r of byKind(d.spans, "turn")) got.set(r.id, r.status);
    if (!d.behind && i > 0) break;
  }
  assert.equal(got.size, 40, "every turn reached the timeline, the late ones through the delta");
  assert.ok([...got.values()].every((st) => st === "success"), "and each one as it ended");
});

test("a 7-day view that ran out of budget never pushes days-old spans into the delta feed", () => {
  const h = home();
  const recs = [];
  for (let i = 0; i < 30; i++) recs.push(promptRec(i * 10, `old ${i} ${"x".repeat(200)}`), answer(i * 10 + 1, "ok"));
  write(h, "oldweek0", recs, { mtimeS: 300 });                                  // 3 days before now
  const clock = { s: 3 * 86400 };
  const s = createSpanStore({ roots: [{ where: "desktop", home: h }], now: () => T0 + clock.s * 1000, chunk: 1024, budget: 4096 });
  assert.equal(s.read({ hours: 168 }).behind, true);
  for (let i = 0; i < 20; i++) {
    clock.s += 5;
    const d = s.read({ since: T0 + (clock.s - 65) * 1000 });
    assert.equal(d.spans.length, 0, "nothing three days old is news to the live feed");
  }
});

test("a turn the feed holds waiting for over a day still reaches it as crashed when its process dies", () => {
  const h = home();
  write(h, "waitlong", [promptRec(0, "go"), toolUse(1, "t1", "Bash", { command: "x" })], { mtimeS: 1 });
  const live = new Map([["waitlong", { sessionId: "waitlong", status: "waiting" }]]);
  const { s, clock } = store(h, { live, nowS: 30 * 3600 });
  assert.equal(byKind(s.read({ hours: 48 }).spans, "turn")[0].status, "waiting");
  live.clear();
  clock.s += 10;
  const [turn] = byKind(s.read({ since: T0 + (clock.s - 65) * 1000 }).spans, "turn");
  assert.deepEqual([turn && turn.status, turn && turn.e], ["crashed", T0 + 1000]);
});

test("liveSessions reads Claude Code's live files and keeps the newer of two for one session", () => {
  const h = home();
  const dir = path.join(h, ".claude", "sessions");
  fs.writeFileSync(path.join(dir, "10.json"), JSON.stringify({ pid: 10, sessionId: "s1", startedAt: 1, status: "idle" }));
  fs.writeFileSync(path.join(dir, "11.json"), JSON.stringify({ pid: 11, sessionId: "s1", startedAt: 2, status: "busy" }));
  fs.writeFileSync(path.join(dir, "12.json"), JSON.stringify({ pid: 12, sessionId: "s2", startedAt: 3, status: "busy" }));
  fs.writeFileSync(path.join(dir, "13.json"), "{half");
  const live = liveSessions(h, (j) => j.pid !== 12);
  assert.deepEqual([...live.keys()], ["s1"]);
  assert.equal(live.get("s1").status, "busy");
});
