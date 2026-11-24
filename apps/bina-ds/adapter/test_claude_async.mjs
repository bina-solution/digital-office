// DGO-2044: a message to Claude is taken in milliseconds. The door answers at once and hands it to the official
// app in the background: the app's own screen takes seconds (24 s measured on Exampleu), and the owner asked for
// «מילי שניות». A conversation opened here is the app's promise (`pending-…`) until its first message starts it;
// its read then names the id it goes on under (`resolved`). A message still on its way says so (`sending`); one the
// app did not take says why in Hebrew and gives its words back (`failed`); the next message of a conversation waits
// until the one before it is in (409); and the app is handed one message at a time. A message the app's line holds
// (its cap of running turns, DGO-2126) is on its way until the line sends it, and one the line gave up on says why.
// A fake agent.v1 app that keeps a promise as bina-claude does stands in for the real one. Run: node test_claude_async.mjs
import http from "node:http";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

process.env.DSH_TRUST_PROXY_AUTH_HEADER = "x-test-signed-in";
process.env.BINA_DS_UI_PEERS = "none.invalid";
let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(cond, ms = 5000) {
  const t = Date.now();
  while (Date.now() - t < ms) { if (await cond()) return true; await sleep(10); }
  return !!(await cond());
}

// A fake bina-claude: POST /v1/sessions {} is a promise of a session; its first message starts it (after `slow` ms)
// or is refused with a driver's code (`refuse`) — and a refused promise may be tried again, as bina-claude's UNSENT.
const APP_UNSENT = new Set(["no-text", "not-sent", "dropped", "locked", "busy", "waiting", "no-window", "no-app", "no-app-session", "not-focused", "no-session", "no-exec"]);
function fakeApp() {
  const state = { calls: [], started: [], promises: new Map(), n: 0, slow: 0, refuse: null, inflight: 0, most: 0,
                  starting: new Set(), failedStart: new Map(), failReads: false,
                  // its line (bina-claude's cap of running turns): a message to a started conversation waits in it,
                  // under the id the line gives it (qid)
                  lineMode: false, line: new Map(), lineFailed: new Map(), lastQid: null, linePlace: null, summary404: 0,
                  promiseLine: false, queuedPromises: new Set(), failPromiseReads: 0 };
  // where each waiting message stands in the whole line: the session's first at `linePlace`, the next behind it
  const placesOf = (line) => line.map((_, i) => (state.linePlace ?? 1) + i);
  const server = http.createServer(async (req, res) => {
    let body = "";
    for await (const c of req) body += c;
    state.calls.push([req.method, req.url]);
    const send = (code, j) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(j)); };
    if (req.url === "/v1/health") return send(200, { ok: true, login: { logged_in: true }, active: 0 });
    if (req.method === "GET" && req.url === "/v1/sessions") return send(200, { sessions: state.started });
    if (req.method === "POST" && req.url === "/v1/sessions") {
      const id = `pending-${randomUUID()}`;
      state.promises.set(id, null);
      return send(201, { id, preset: "claude-desktop" });
    }
    // a promise read before it started says whether its start is under way, or why a start that may have sent ended
    const one = /^\/v1\/sessions\/([^/?]+)$/.exec(req.url);
    if (one && req.method === "GET") {
      const pid = decodeURIComponent(one[1]);
      // a started conversation: its summary, with what waits in the line for it and what the line last gave up on
      if (state.started.some((s) => s.id === pid)) {
        if (state.summary404 > 0) { state.summary404 -= 1; return send(404, { error: "no such session", code: "no-session" }); }
        const line = state.line.get(pid) || [];
        return send(200, { id: pid, title: "started", queue: line.length, line, line_places: placesOf(line),
                           line_place: line.length ? (state.linePlace ?? 1) : 0, line_failed: state.lineFailed.get(pid) || [] });
      }
      if (!state.promises.has(pid)) return send(404, { error: "no such session", code: "no-session" });
      if (state.failPromiseReads > 0) { state.failPromiseReads -= 1; return send(500, { error: "the app is restarting" }); }
      if (state.promises.get(pid)) return send(200, { id: state.promises.get(pid), title: "started" });
      return send(200, { id: pid, blank: true, starting: state.starting.has(pid) || state.queuedPromises.has(pid),
                         ...(state.queuedPromises.has(pid) ? { queued: true, queue: 1 } : {}),
                         ...(state.failedStart.has(pid) ? { failed: state.failedStart.get(pid) } : {}) });
    }
    const m = /^\/v1\/sessions\/([^/?]+)\/(messages|cancel|events)/.exec(req.url);
    if (!m) return send(404, { error: "no" });
    const given = decodeURIComponent(m[1]);
    const real = state.promises.has(given) ? state.promises.get(given) : given;
    if (m[2] === "messages" && req.method === "POST") {
      state.inflight += 1; state.most = Math.max(state.most, state.inflight);
      const promise = state.promises.has(given) && !real;
      if (promise) state.starting.add(given);
      try {
        if (state.slow) await sleep(state.slow);
        if (state.refuse) {
          if (promise && !APP_UNSENT.has(state.refuse)) state.failedStart.set(given, state.refuse);   // as bina-claude keeps it
          return send(409, { error: "nothing was sent: the text is not in the composer", code: state.refuse });
        }
        if (state.promises.has(given) && !real && state.promiseLine) {   // at the cap: its first message waits in the line
          state.queuedPromises.add(given);
          return send(202, { accepted: true, queued: true, queue: 1, qid: randomUUID(), id: given, note: "#1 in line" });
        }
        if (state.promises.has(given) && !real) {
          const id = `local_started-${++state.n}`;
          state.promises.set(given, id);
          state.started.push({ id, title: JSON.parse(body).text, updated_at: new Date().toISOString() });
          return send(202, { accepted: true, queue: 0, id });
        }
        if (!state.started.some((s) => s.id === real)) return send(404, { error: "no such session", code: "no-session" });
        if (state.lineMode) {                            // at the cap: in the line, as bina-claude answers it
          const line = state.line.get(real) || [];
          state.lastQid = randomUUID(); line.push(state.lastQid); state.line.set(real, line);
          const at = state.linePlace ?? line.length;
          return send(202, { accepted: true, queued: true, queue: at, qid: state.lastQid, note: `#${at} in line` });
        }
        return send(202, { accepted: true, queue: 0 });
      } finally { state.inflight -= 1; state.starting.delete(given); }
    }
    if (state.promises.has(given) && !real) return send(409, { error: `${given} starts with its first message`, code: "not-started" });
    if (!state.started.some((s) => s.id === real)) return send(404, { error: "no such session", code: "no-session" });
    if (m[2] === "messages" && state.failReads) return send(500, { error: "the transcript could not be read" });
    if (m[2] === "messages") {
      const line = state.line.get(real) || [];
      return send(200, { events: [{ seq: 0, type: "user", text: "שלום", at: new Date().toISOString() }], has_more: false,
                         ...(line.length ? { line, line_places: placesOf(line) } : {}) });
    }
    if (m[2] === "cancel" && state.cancelRefuse) return send(409, { error: "the app is busy", code: state.cancelRefuse });
    if (m[2] === "cancel") return send(200, { id: real, cancelled: true });
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.end(`event: open\ndata: {"id":"${real}"}\n\n`);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r({ state, server, api: `http://127.0.0.1:${server.address().port}` })));
}

const app = await fakeApp();
process.env.BINA_CLAUDE_API = app.api;
const { createUi } = await import("./ui.mjs");
const office = mkdtempSync(path.join(tmpdir(), "office-"));
const apps = [{ id: "bina-claude", key: "", title: null, api: app.api, container: "c1" }];
const handle = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {},
                          rpc: async () => ({ groups: [] }), refreshList: () => {}, office,
                          claudeApps: () => apps, claudeToken: async () => "tok" });
async function call(method, p, body) {
  const chunks = body === undefined ? [] : [Buffer.from(JSON.stringify(body))];
  const req = { method, socket: { remoteAddress: "127.0.0.1" }, on() {},
                headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin", ...(body !== undefined ? { "content-type": "application/json" } : {}) },
                async *[Symbol.asyncIterator]() { for (const c of chunks) yield c; } };
  const res = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = t ? String(t) : ""; }, write() {} };
  const u = new URL(p, "http://x");
  await handle(req, res, u.pathname, u.searchParams);
  let data = null;
  try { data = JSON.parse(res.text); } catch { /* not JSON */ }
  return { status: res.status, data };
}
const read = (id) => call("GET", `/ui/sessions/${encodeURIComponent(id)}/messages?limit=50`);
const posts = (u) => app.state.calls.filter(([m, x]) => m === "POST" && x === u).length;

// 1. a new conversation opens at once while the app takes its time to start it
app.state.slow = 1500;
let t = Date.now();
const made = await call("POST", "/ui/sessions", { engine: "claude", text: "שלום" });
const took = Date.now() - t;
const pid = made.data && made.data.id;
check([made.status, made.data.pending, /^pending-/.test(pid), took < 500], [201, true, true, true],
  `a new Claude conversation opens at once (${took} ms) while the app takes 1.5 s to start it`);
t = Date.now();
let r = await read(pid);
check([r.status, r.data.sending, r.data.events, Date.now() - t < 200], [200, true, [], true], "its read says its message is on its way, at once");
check(app.state.calls.some(([m, u]) => m === "GET" && u.startsWith(`/v1/sessions/${pid}`)), false, "…and the app is not asked to read what it has not started");
const listed = await call("GET", "/ui/sessions");
const row = listed.data.sessions.find((s) => s.id === pid);
check([row && row.sending, row && row.running, row && row.title, row && row.app], [true, true, "שלום", "bina-claude"],
  "the list has it at once: working, titled by its message, in its app");
const again = await call("POST", `/ui/sessions/${pid}/messages`, { text: "ועוד" });
check([again.status, posts(`/v1/sessions/${pid}/messages`)], [409, 1], "a second message while the first is handed over waits (409): nothing more is sent");
await until(async () => !(await read(pid)).data.sending);
r = await read(pid);
const real = r.data.resolved;
check([/^local_started-/.test(String(real)), r.data.sending, r.data.failed], [true, undefined, undefined], "once the app started it, its read names the id it goes on under");
check(posts(`/v1/sessions/${pid}/messages`), 1, "the message was handed to the app once");
const after = await call("GET", "/ui/sessions");
check([after.data.sessions.some((s) => s.id === pid), after.data.sessions.some((s) => s.id === real)], [false, true],
  "the list then names the started conversation, not its promise");
check([r.status, r.data.events.length], [200, 1], "read under the promise's id: the started conversation's events");

// everything under the promise's id reaches the started conversation
app.state.slow = 0;
const next = await call("POST", `/ui/sessions/${pid}/messages`, { text: "המשך" });
check([next.status, next.data.id, next.data.background], [202, real, true], "a message under the promise's id is taken at once and names the started id");
await until(() => posts(`/v1/sessions/${real}/messages`) === 1);
check([posts(`/v1/sessions/${real}/messages`), posts(`/v1/sessions/${pid}/messages`)], [1, 1], "…and is handed to the app under the started id");
const stop = await call("POST", `/ui/sessions/${pid}/cancel`, {});
check([stop.status, posts(`/v1/sessions/${real}/cancel`)], [202, 1], "stopping under the promise's id stops the started conversation");
const followed = await call("GET", `/ui/sessions/${pid}/stream?since=-1`);
check([followed.status, app.state.calls.some(([m, u]) => m === "GET" && u === `/v1/sessions/${real}/events?since=-1`)], [200, true],
  "following under the promise's id follows the started conversation");

// 2. a message the app did not take: why, in Hebrew, and its words back; sent again from the same conversation
app.state.refuse = "not-sent";
const m2 = await call("POST", "/ui/sessions", { engine: "claude", text: "בדיקה שנכשלת" });
const p2 = m2.data.id;
await until(async () => !(await read(p2)).data.sending);
r = await read(p2);
const f = r.data.failed || {};
check([f.text, /לא היה מוכן/.test(f.error || ""), /not in the composer/.test(f.error || ""), typeof f.at, r.data.resolved], ["בדיקה שנכשלת", true, false, "number", undefined],
  "a message the app did not take: its read says why in Hebrew (never the driver's English) and gives its words back");
const l2 = await call("GET", "/ui/sessions");
const row2 = l2.data.sessions.find((s) => s.id === p2);
check([row2 && row2.failed, row2 && row2.running, row2 && row2.title], [true, false, "בדיקה שנכשלת"], "the list keeps it, marked not sent");
app.state.refuse = null;
const retry = await call("POST", `/ui/sessions/${p2}/messages`, { text: "בדיקה שנכשלת" });
r = await read(p2);
check([retry.status, r.data.sending, r.data.failed], [202, true, undefined], "sent again from the same conversation: on its way, the failure no longer said");
await until(async () => !(await read(p2)).data.sending);
r = await read(p2);
check([/^local_started-/.test(String(r.data.resolved)), r.data.failed], [true, undefined], "…and the app starts it");

// 3. the app is handed one message at a time: two conversations opened together go one after the other
app.state.slow = 300; app.state.most = 0;
t = Date.now();
const a1 = await call("POST", "/ui/sessions", { engine: "claude", text: "ראשונה" });
const a2 = await call("POST", "/ui/sessions", { engine: "claude", text: "שנייה" });
check([a1.status, a2.status, Date.now() - t < 500], [201, 201, true], "two conversations open at once");
await until(async () => !(await read(a1.data.id)).data.sending && !(await read(a2.data.id)).data.sending);
const r1 = await read(a1.data.id), r2 = await read(a2.data.id);
check([app.state.most, typeof r1.data.resolved, typeof r2.data.resolved], [1, "string", "string"], "the app got them one at a time, and started both");

// 4. a message to a conversation the app cannot read: taken at once; its read then says it was not sent, and why,
// without events (the screen keeps what it shows). Nothing handed over and nobody has it: a 404.
const lost = await call("POST", "/ui/sessions/local_nobody/messages", { text: "x" });
await until(async () => !(await read("local_nobody")).data?.sending);
const lr = await read("local_nobody");
check([lost.status, lr.status, lr.data.failed && lr.data.failed.error, lr.data.failed && lr.data.failed.text, lr.data.events],
  [202, 200, "השיחה הזאת לא נמצאה באפליקציית Claude.", "x", undefined],
  "a message the app could not take, in a conversation it cannot read: said, with its words, and no events");
const never = await read("local_never");
check(never.status, 404, "a conversation nobody has and nothing was handed to: a 404");

// 5. a refusal after which the message MAY have gone is «not known», never «not sent» (the second reader: a resend
// would repeat it); an UNSENT one is «not sent»
app.state.slow = 0; app.state.refuse = "not-confirmed";
const mc = await call("POST", "/ui/sessions", { engine: "claude", text: "אולי נמסר" });
await until(async () => !(await read(mc.data.id)).data.sending);
let rf = (await read(mc.data.id)).data.failed || {};
check([rf.maybe, /עוד לא מופיעה בשיחה/.test(rf.error || ""), rf.text], [true, true, "אולי נמסר"], "not-confirmed: said as not known, in Hebrew, with its words");
app.state.refuse = "not-sent";
const ms = await call("POST", "/ui/sessions", { engine: "claude", text: "לא נמסר" });
await until(async () => !(await read(ms.data.id)).data.sending);
rf = (await read(ms.data.id)).data.failed || {};
check([rf.maybe, /לא נשלח דבר/.test(rf.error || "")], [undefined, true], "not-sent: said as not sent");
app.state.refuse = null;

// 6. a door that restarted knows none of its promises: the app says what became of each
const fresh = () => createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, rpc: async () => ({ groups: [] }),
                               refreshList: () => {}, office, claudeApps: () => apps, claudeToken: async () => "tok" });
async function readOn(h, id) {
  const req = { method: "GET", socket: { remoteAddress: "127.0.0.1" }, on() {}, headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin" },
                async *[Symbol.asyncIterator]() {} };
  const res = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = t ? String(t) : ""; }, write() {} };
  const u = new URL(`/ui/sessions/${encodeURIComponent(id)}/messages?limit=50`, "http://x");
  await h(req, res, u.pathname, u.searchParams);
  return { status: res.status, data: JSON.parse(res.text || "null") };
}
app.state.slow = 1200;
const mr = await call("POST", "/ui/sessions", { engine: "claude", text: "אחרי הפעלה מחדש" });
await until(() => app.state.starting.has(mr.data.id));
let fr = await readOn(fresh(), mr.data.id);
check([fr.status, fr.data.sending], [200, true], "a restarted door reading a promise the app is starting: on its way");
await until(async () => typeof (await read(mr.data.id)).data.resolved === "string");
fr = await readOn(fresh(), mr.data.id);
check([fr.status, /^local_started-/.test(String(fr.data.resolved)), fr.data.events.length], [200, true, 1], "…once started: the restarted door names its id and reads it");
const idle = await (await fetch(`${app.api}/v1/sessions`, { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer tok" }, body: "{}" })).json();
fr = await readOn(fresh(), idle.id);
check([fr.data.failed && fr.data.failed.maybe, /לא הגיעה/.test((fr.data.failed || {}).error || ""), fr.data.events], [undefined, true, []],
  "a promise never asked to start: not sent (its words come from the screen that sent them)");
app.state.slow = 0; app.state.refuse = "unknown";
const mu = await call("POST", "/ui/sessions", { engine: "claude", text: "x" });
await until(async () => !(await read(mu.data.id)).data.sending);
fr = await readOn(fresh(), mu.data.id);
check([fr.data.failed && fr.data.failed.maybe, /לא ידוע/.test((fr.data.failed || {}).error || "")], [true, true], "a start that may have sent, read by a restarted door: not known");
app.state.refuse = null;

// 7. the conversation started but the app cannot be read now: its id is still said (the screen moves to it)
app.state.failReads = true;
const fail = await read(pid);
check([fail.status, fail.data.resolved, fail.data.events], [200, real, undefined], "the app unreadable after the start: the started id is still said, without events");
app.state.failReads = false;

// 8. a stop while the message is handed over is refused in plain words; the list names the promise a conversation
// started from
app.state.slow = 800;
const mh = await call("POST", "/ui/sessions", { engine: "claude", text: "עצירה מוקדמת" });
const early = await call("POST", `/ui/sessions/${mh.data.id}/cancel`, {});
check([early.status, /עוד נמסרת/.test((early.data && early.data.error) || "")], [409, true], "a stop while the message is handed over: 409, said plainly");
await until(async () => typeof (await read(mh.data.id)).data.resolved === "string");
const startedRow = (await call("GET", "/ui/sessions")).data.sessions.find((s) => s.from === mh.data.id);
check(!!(startedRow && /^local_started-/.test(startedRow.id)), true, "the list's row of a started promise says which promise it was (`from`)");
app.state.slow = 0;

// 9. the second reader's second round
// a token that cannot be read: no request left the door — «not sent», never «not known»
const noToken = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, rpc: async () => ({ groups: [] }),
                           refreshList: () => {}, office, claudeApps: () => apps,
                           claudeToken: async () => { const e = new Error("no exec"); e.code = "no-exec"; throw e; } });
async function on(h, method, p, body) {
  const chunks = body === undefined ? [] : [Buffer.from(JSON.stringify(body))];
  const req = { method, socket: { remoteAddress: "127.0.0.1" }, on() {},
                headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin", ...(body !== undefined ? { "content-type": "application/json" } : {}) },
                async *[Symbol.asyncIterator]() { for (const c of chunks) yield c; } };
  const res = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = t ? String(t) : ""; }, write() {} };
  const u = new URL(p, "http://x");
  await h(req, res, u.pathname, u.searchParams);
  let data = null;
  try { data = JSON.parse(res.text); } catch { /* not JSON */ }
  return { status: res.status, data };
}
const tk = await on(noToken, "POST", `/ui/sessions/${real}/messages`, { text: "בלי טוקן" });
await until(async () => !(await on(noToken, "GET", `/ui/sessions/${real}/messages?limit=5`)).data?.sending);
const tkr = (await on(noToken, "GET", `/ui/sessions/${real}/messages?limit=5`)).data || {};
check([tk.status, tkr.failed && tkr.failed.maybe, /לא זמינה/.test((tkr.failed || {}).error || "")], [202, undefined, true],
  "no token for the app: not sent (the words may go again), said in Hebrew");
// a restarted door whose app cannot be asked: still on its way (asked again next read), not a frozen «not known»
const away = [{ id: "bina-claude", key: "", title: null, api: "http://127.0.0.1:1", container: "c1" }];
const doorAway = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, rpc: async () => ({ groups: [] }),
                            refreshList: () => {}, office, claudeApps: () => away, claudeToken: async () => "tok" });
const aw = (await on(doorAway, "GET", `/ui/sessions/${encodeURIComponent(idle.id)}/messages?limit=5`)).data || {};
check([aw.sending, aw.failed], [true, undefined], "a restarted door that cannot reach the app: on its way, nothing decided");
// a failure learned from the app is kept: the list carries the row, a second read says the same
const doorBack = fresh();
const once = (await readOn(doorBack, idle.id)).data.failed || {};
const twice = (await readOn(doorBack, idle.id)).data.failed || {};
const listedBack = (await on(doorBack, "GET", "/ui/sessions")).data.sessions.find((s) => s.id === idle.id);
check([once.error === twice.error && once.at === twice.at, !!(listedBack && listedBack.failed)], [true, true],
  "a failure learned from the app is kept: the same on every read, and the list carries the row");
// a promise no app keeps any more (bina-claude restarted, or a day went by): not «on its way» forever — not known,
// kept, and the list carries it (the second reader, round three)
const doorForgot = fresh();
const forgotten = "pending-00000000-0000-4000-8000-000000000000";
const fg1 = (await readOn(doorForgot, forgotten)).data || {};
const fg2 = (await readOn(doorForgot, forgotten)).data || {};
check([fg1.sending, fg1.failed && fg1.failed.maybe, fg1.failed && fg1.failed.code, /כבר לא מכירה/.test((fg1.failed || {}).error || ""), fg2.failed && fg2.failed.at === fg1.failed.at],
  [undefined, true, "no-session", true, true], "a promise the app forgot: not known (its start may have sent), said once and kept");
const fgRow = (await on(doorForgot, "GET", "/ui/sessions")).data.sessions.find((s) => s.id === forgotten);
check([!!(fgRow && fgRow.failed), !!(fgRow && fgRow.maybe), fgRow && fgRow.running], [true, true, false], "…and the list carries it, marked not known");
// a refused stop is said as a stop, not as a message
app.state.cancelRefuse = "busy";
const busyStop = await call("POST", `/ui/sessions/${real}/cancel`, {});
check([busyStop.status, /עסוקה כרגע בשיחה אחרת/.test((busyStop.data && busyStop.data.error) || "")], [409, true], "a stop the app refuses as busy: said as a stop");
app.state.cancelRefuse = null;

// 10. the app's line (bina-claude's cap of running turns, DGO-2126): a message it holds is still on its way — the
// screen keeps it and the next one waits — until the line sends it; one the line gave up on is said with its words:
// «not sent» when nothing was pressed, «not known» when it may have gone. Another message's failure is not this one's.
const toLine = async (text) => {
  const n = posts(`/v1/sessions/${real}/messages`);
  const res = await call("POST", `/ui/sessions/${real}/messages`, { text });
  await until(() => posts(`/v1/sessions/${real}/messages`) === n + 1 && app.state.inflight === 0);
  await sleep(30);                                               // the door has read the app's answer
  return res;
};
app.state.lineMode = true;
app.state.linePlace = 2;                                          // one message of another conversation waits ahead
const queued = await toLine("בתור");
r = await read(real);
check([queued.status, r.data.sending, r.data.queued, r.data.failed], [202, true, 2, undefined],
  "a message the app's line holds: still on its way, and its place in the line said");
app.state.linePlace = 1;
r = await read(real);
check([r.data.sending, r.data.queued], [true, 1], "…the one ahead went: its place moves up");
app.state.linePlace = 2;
app.state.line.set(real, ["q-ahead-of-it", app.state.lastQid]);  // another sender's message to it waits ahead of it
r = await read(real);
check(r.data.queued, 3, "…its own place in the line, not the session's first message's");
app.state.linePlace = 1;
app.state.line.set(real, [app.state.lastQid]);
const sentSoFar = posts(`/v1/sessions/${real}/messages`);
const behind = await call("POST", `/ui/sessions/${real}/messages`, { text: "עוד אחת" });
check([behind.status, posts(`/v1/sessions/${real}/messages`)], [409, sentSoFar], "…and the next one waits for it (409): nothing more is sent");
app.state.summary404 = 1;                                         // the app's record caught mid-write: one 404
r = await read(real);
check([r.data.sending, r.data.failed], [true, undefined], "one 404 alone is not «gone»: still on its way");
app.state.line.set(real, ["another-senders-qid"]);               // the line sent it; another sender's message waits
r = await read(real);
check([r.data.sending, r.data.queued, r.data.failed, r.data.events.length], [undefined, undefined, undefined, 1],
  "the line sent it (another's still waiting): no longer on its way, nothing failed, the conversation read");
app.state.linePlace = null;
const gaveUp = (code, maybe) => { app.state.line.set(real, []); app.state.lineFailed.set(real, [{ qid: app.state.lastQid, code, maybe, at: Date.now() }]); };
await toLine("נדחה בתור");
gaveUp("no-session", false);                                      // the one «nothing pressed» end that leaves the line
r = await read(real);
let lf = r.data.failed || {};
check([r.data.sending, lf.text, lf.maybe, /לא נמצאה/.test(lf.error || "")], [undefined, "נדחה בתור", undefined, true],
  "the line gave it up having pressed nothing: not sent, said in Hebrew, its words back");
await toLine("אולי נשלח מהתור");
gaveUp("unknown", true);
r = await read(real);
lf = r.data.failed || {};
check([r.data.sending, lf.text, lf.maybe, /לא ידוע/.test(lf.error || "")], [undefined, "אולי נשלח מהתור", true, true],
  "…having maybe sent it: not known, with its words");
await toLine("נשאר בתיבה");
gaveUp("left-in-composer", true);
r = await read(real);
lf = r.data.failed || {};
check([lf.maybe, /נכנסה לתיבת הכתיבה/.test(lf.error || "")], [true, true],
  "…its text left in the app's composer: not known, never offered again, said where it waits");
app.state.summary404 = 2;                                         // the conversation is gone from the app
await toLine("לשיחה שנמחקה");
await read(real);
r = await read(real);
lf = r.data.failed || {};
check([r.data.sending, lf.text, lf.maybe], [undefined, "לשיחה שנמחקה", undefined], "a 404 twice running: gone — not sent, its words back");
app.state.summary404 = 0;
await toLine("שלי");
app.state.line.set(real, []);
app.state.lineFailed.set(real, [{ qid: "another-senders-qid", code: "not-sent", maybe: false, at: Date.now() }]);
r = await read(real);
check([r.data.sending, r.data.failed], [undefined, undefined], "another message's failure is not this one's: it was sent");
app.state.lineMode = false;

// 11. a new conversation at the app's cap: its first message waits in the app's line — the conversation is in the
// list at once and stays there, on its way, until the line starts it; then it is listed under the id it started as
app.state.promiseLine = true;
const qm = await call("POST", "/ui/sessions", { engine: "claude", text: "בתור לשיחה חדשה" });
const qp = qm.data.id;
await until(() => app.state.queuedPromises.has(qp) && app.state.inflight === 0);
await sleep(30);
const qRow = (await call("GET", "/ui/sessions")).data.sessions.find((s) => s.id === qp);
check([!!qRow, qRow && qRow.sending, qRow && qRow.running], [true, true, true],
  "a new conversation whose first message waits in the app's line: in the list, on its way");
r = await read(qp);
check([r.data.sending, r.data.queued, r.data.failed, r.data.resolved], [true, 1, undefined, undefined],
  "…and its read says it is on its way, first in the line");
const startedId = `local_started-${++app.state.n}`;                 // the line starts it
app.state.promises.set(qp, startedId); app.state.queuedPromises.delete(qp);
app.state.started.push({ id: startedId, title: "בתור לשיחה חדשה", updated_at: new Date().toISOString(), from: qp });
const afterStart = (await call("GET", "/ui/sessions")).data.sessions;
check([afterStart.some((s) => s.id === qp), (afterStart.find((s) => s.id === startedId) || {}).from], [false, qp],
  "once the line starts it, the list names the started conversation, and the promise it came from");
r = await read(qp);
check([r.data.resolved, r.data.sending], [startedId, undefined], "…and its read names the id it started as");

// 12. a long wait in the line, the app unreachable now and then: only five minutes of unbroken silence is «not known»
const um = await call("POST", "/ui/sessions", { engine: "claude", text: "ממתינה הרבה זמן" });
const up = um.data.id;
await until(() => app.state.queuedPromises.has(up) && app.state.inflight === 0);
await sleep(30);
app.state.failPromiseReads = 1;
r = await read(up);
check([r.data.sending, r.data.failed], [true, undefined], "the app did not answer once: still on its way");
r = await read(up);
check([r.data.sending, r.data.queued], [true, 1], "…it answers again: waiting in its line");
const realNow = Date.now;
Date.now = () => realNow() + 6 * 60000;          // six minutes on, still in the line, and one read fails again
try { app.state.failPromiseReads = 1; r = await read(up); } finally { Date.now = realNow; }
check([r.data.sending, r.data.failed], [true, undefined], "…a failed read after a long wait in which the app answered: never «not known»");
app.state.promiseLine = false;

// 13. a door that holds no record of the message (it restarted): the app's read says what waits, and where
app.state.line.set(real, ["q-from-before-the-restart"]);
app.state.linePlace = 3;
const nr = await readOn(fresh(), real);
check([nr.data.sending, nr.data.queued, nr.data.failed], [true, 3, undefined],
  "a door that restarted still says its conversation's message waits in the line, and its place");
app.state.line.set(real, []);
app.state.linePlace = null;

app.server.close();
rmSync(office, { recursive: true, force: true });
console.log(failed ? `FAILED ${failed}` : "PASS");
process.exit(failed ? 1 : 0);
