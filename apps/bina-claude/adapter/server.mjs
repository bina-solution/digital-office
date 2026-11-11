// apps/bina-claude/adapter/server.mjs — agent.v1 (ai/context/agent-contract.md) over the official Claude
// desktop app (DGO-1298).
//
// The office's agents speak ONE contract. bina-ds serves it over the DeepSeek Harness; this serves the
// same routes over THE Claude of the office — the official desktop app in bina-claude-desktop, signed in
// to the owner's account — so `bbox agent --app bina-claude …`, Azaria, n8n and any other caller start,
// list, message and follow the very sessions the owner sees on its screen (owner, 2026-11-03: «כל מה
// שאני יכול לעשות מתצוגה אני … יכול לעשות מהשורת פקודה»).
//
// A session IS the app's: its id is the app's own (`local_…`, the id of its sidebar and session tools).
//   read   — the app's files, on the shared volume (/data/desktop is the app's HOME):
//            .config/Claude/claude-code-sessions/*/*/local_*.json   the app's record of each session
//            .claude/projects/*/<cliSessionId>.jsonl                its Claude Code transcript
//            .claude/sessions/<pid>.json                            live: busy|idle, per running session
//   write  — `desktop/drive` inside the app's container (docker exec): the app's own entry points
//            (claude://code/new, claude://code/continue) and the Return key — the owner's own gestures.
// Nothing here holds or reads a credential, and nothing here runs Claude itself.
//
// No dependencies: node's own http, child_process and fs.
import http from "node:http";
import { spawn } from "node:child_process";
import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { StringDecoder } from "node:string_decoder";
import { createSpanStore, liveSessions } from "./spans.mjs";
import { createWatch, desktopSignIn } from "./signin-watch.mjs";

const PORT = Number(process.env.BINA_CLAUDE_ADAPTER_PORT || 3091);
const STATE = process.env.BINA_CLAUDE_STATE || "/data/bina-claude";
const TOKEN_FILE = process.env.AGENT_TOKEN_FILE || `${STATE}/api-token`;
const OFFICE = process.env.BBOX_REPO_HOST || "/workspace/office";
// The app's HOME as this container sees it (docker-compose.yml: the volume's `desktop` folder).
const DESK = process.env.BINA_CLAUDE_DESKTOP_HOME || "/data/desktop";
const DESKTOP = process.env.BINA_CLAUDE_DESKTOP_CONTAINER || `bina-claude-desktop-${process.env.DEPLOYMENT_NAME || "bina-deployment"}`;
// The checkout is mounted at the same path in both containers, so the driver runs from it.
const DRIVE = path.join(OFFICE, "apps", "bina-claude", "desktop", "drive");
const VERSION = "0.5.0";
const startedAt = Date.now();

// Read by the entry point (main() below), never at import: test_signout.mjs imports this file for its one
// pure function, and a test has no office token to read.
let TOKEN = "";

class Fail extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
const now = () => new Date().toISOString();
const iso = (ms) => (ms ? new Date(ms).toISOString() : null);

// ── the app's sessions, read from its files ───────────────────────────────────────────────────────
function records() {
  const out = new Map();
  for (const f of fs.globSync(path.join(DESK, ".config/Claude/claude-code-sessions/*/*/local_*.json"))) {
    try { const r = JSON.parse(fs.readFileSync(f, "utf8")); if (r.sessionId) out.set(r.sessionId, r); } catch { /* mid-write */ }
  }
  return out;
}

// Live state, by the app's id: Claude Code keeps one file per running session and drops it on exit.
// Its status is busy (a turn runs), waiting (a question or an approval is open on the owner's screen —
// still inside the turn) or idle. A process killed with the app leaves its file behind, and this
// container cannot see the app's processes: a file older than the running app's own SingletonLock (made
// when it started) is from a life of the app that is over. Of two files for one session, the newer.
const MID_TURN = new Set(["busy", "waiting"]);
function live() {
  let since = 0;
  try { since = fs.lstatSync(path.join(DESK, ".config/Claude/SingletonLock")).mtimeMs - 5000; } catch { /* not running */ }
  const out = new Map();
  for (const f of fs.globSync(path.join(DESK, ".claude/sessions/*.json"))) {
    try {
      const j = JSON.parse(fs.readFileSync(f, "utf8"));
      if (!j.hostSessionId || (since && (j.startedAt || 0) < since)) continue;
      const had = out.get(j.hostSessionId);
      if (!had || (j.startedAt || 0) > (had.startedAt || 0)) out.set(j.hostSessionId, j);
    } catch { /* mid-write */ }
  }
  return out;
}

// ── the office timeline's lane: every Claude session here, as spans (spans.mjs; DGO-1684) ────────────
// The desktop app's own Claude Code sessions — the only Claude of this app. Their processes are in the app's
// container, so a live file is current when it is newer than the running app (its SingletonLock).
const spans = createSpanStore({ roots: [
  { where: "desktop", home: DESK,
    live: () => {
      let since = 0;
      try { since = fs.lstatSync(path.join(DESK, ".config/Claude/SingletonLock")).mtimeMs - 5000; } catch { return new Map(); }
      return liveSessions(DESK, (j) => (j.startedAt || 0) >= since);
    },
    names: () => new Map([...records().values()].filter((r) => r.cliSessionId)
      .map((r) => [r.cliSessionId, { id: r.sessionId, title: r.title || "" }])) },
] });

// A sign-in that is lost is never silent (signin-watch.mjs; DGO-1684): once a minute, the desktop app's ONE
// sign-in; a notice that rings the owner's phone, with the step, when it was signed in and is signed out.
if (process.env.BINA_CLAUDE_SIGNIN_WATCH !== "off") {
  createWatch({
    read: () => ({ desktop: login().logged_in }),
    stateFile: path.join(STATE, "signin-watch.json"),
    notifications: (process.env.NOTIFICATIONS_URL || "http://notifications:8977").replace(/\/+$/, ""),
    office: process.env.DEPLOYMENT_NAME || "",
  }).start();
}

function transcriptOf(rec) {
  if (!rec.cliSessionId) return null;
  return fs.globSync(path.join(DESK, ".claude/projects/*", `${rec.cliSessionId}.jsonl`))[0] || null;
}

function summary(rec, state) {
  return {
    id: rec.sessionId, title: rec.title || "", running: !!state && MID_TURN.has(state.status), blank: false,
    waiting_for: (state && state.status === "waiting" && (state.waitingFor || "the owner")) || null,
    created_at: iso(rec.createdAt), updated_at: iso(rec.lastActivityAt || rec.createdAt), preset: "claude-desktop",
    permissions: rec.permissionMode || null, model: rec.model ? { provider: "anthropic", model: rec.model } : null,
    goal: null, todos: [], turns: rec.completedTurns || 0, tokens: {}, queue: 0, cwd: rec.cwd || null,
    claude_session: rec.cliSessionId || null, archived: !!rec.isArchived,
  };
}

// A session a caller created before its first message (`bbox agent new` posts the session, then the
// text): the app has no blank session, so it is a promise of one until the text starts it.
const pending = new Map();   // pending id → {at, start: the in-flight start, id once started}
const delivered = new Map(); // app id → {at, seq}: when this adapter delivered, and the events it had then

setInterval(() => {            // a promise nobody kept: forgotten after a day
  for (const [k, v] of pending) if (Date.now() - v.at > 86400000) pending.delete(k);
}, 3600000).unref();

function find(given) {
  if (pending.has(given)) {
    const real = pending.get(given).id;
    if (!real) return { pendingId: given };
    given = real;
  }
  const recs = records();
  if (recs.has(given)) return { rec: recs.get(given) };
  const hits = [...recs.keys()].filter((id) => id.startsWith(given) || id.startsWith(`local_${given}`));
  if (hits.length === 1) return { rec: recs.get(hits[0]) };
  if (hits.length > 1) throw new Fail(409, "ambiguous", `${hits.length} sessions start with ${given}`);
  throw new Fail(404, "no-session", `the app has no session ${given}`);
}

// ── the transcript as the contract's events ───────────────────────────────────────────────────────
// One parser per session, fed only the bytes appended since its last read, so seq is stable across
// reads (since= replay works) and following a long session costs only its new lines. The transcripts
// run to tens of MB, so a parser keeps only its last KEEP events (seq goes on counting), reads its file
// in CHUNK pieces, and is forgotten once nobody has followed or read it for FORGET.
const parsers = new Map();   // app id → {file, offset, decoder, rest, events, seq, open, turn, idle, used, subs}
const KEEP = 3000;
const CHUNK = 4 << 20;
const FORGET = 600000;

function flat(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((c) => (typeof c === "string" ? c : c.text || (c.type ? `[${c.type}]` : ""))).join("\n");
  return content == null ? "" : JSON.stringify(content);
}

// What the owner (or a caller) said: the text parts, without the app's own <system-reminder> blocks.
function userText(content) {
  const parts = typeof content === "string" ? [content]
    : (content || []).filter((c) => c && c.type === "text").map((c) => c.text || "");
  return parts.join("\n").replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, "").trim();
}

function event(p, type, data = {}, at = now()) {
  const e = { type, seq: ++p.seq, at, turn: p.turn, ...data };
  p.events.push(e);
  if (p.events.length > KEEP + KEEP / 10) p.events.splice(0, p.events.length - KEEP);
  return e;
}

function parse(p, r) {
  const ev = (type, data) => event(p, type, data, r.timestamp || now());
  const out = [];
  if (r.isMeta || r.isSidechain) return out;
  if (r.type === "user" && r.message) {
    const c = r.message.content;
    if (Array.isArray(c) && c.some((x) => x && x.type === "tool_result")) {
      for (const x of c) if (x.type === "tool_result") out.push(ev("tool.result", { id: x.tool_use_id, ok: !x.is_error, text: flat(x.content).slice(0, 8000) }));
      return out;
    }
    const text = userText(c);
    // Esc on the screen: the app writes a marker, not a message — it ends the turn, it starts none.
    if (/^\[Request interrupted/.test(text)) {
      if (p.open) { p.open = false; out.push(ev("turn.end", { reason: "cancelled" })); }
      return out;
    }
    // A slash command typed on the screen and its local output are not a turn of Claude's.
    if (!text || /^<(command-name|command-message|local-command-std(out|err))>/.test(text)) return out;
    if (p.open) out.push(ev("turn.end", { reason: "interrupted" }));
    p.turn++;
    p.open = true;
    out.push(ev("turn.start"), ev("user", { text, source: "user" }));
    return out;
  }
  if (r.type === "assistant" && r.message) {
    out.push(ev("step.start"));
    for (const c of r.message.content || []) {
      if (c.type === "text" && c.text) out.push(ev("assistant", { text: c.text }));
      else if (c.type === "thinking" && c.thinking) out.push(ev("reasoning", { text: c.thinking }));
      else if (c.type === "tool_use") out.push(ev("tool.call", { id: c.id, name: c.name, args: c.input }));
    }
    out.push(ev("step.end"));
    return out;
  }
  // The app's Claude Code closes every turn with its Stop hooks' summary.
  if (r.type === "system" && r.subtype === "stop_hook_summary" && p.open) {
    p.open = false;
    out.push(ev("turn.end", { reason: "completed" }));
  }
  return out;
}

function refresh(rec) {
  let p = parsers.get(rec.sessionId);
  const file = transcriptOf(rec);
  if (!p || p.file !== file) {
    p = { file, offset: 0, decoder: new StringDecoder("utf8"), rest: "", events: [], seq: 0, open: false, turn: 0,
          idle: 0, used: 0, subs: p ? p.subs : new Set() };
    parsers.set(rec.sessionId, p);
  }
  p.used = Date.now();
  if (!file) return p;
  // A transcript can go between the stat and the read (the app deletes a session): what was read stands.
  let fd;
  try {
    const size = fs.statSync(file).size;
    if (size <= p.offset) return p;
    fd = fs.openSync(file, "r");
    while (p.offset < size) {
      const buf = Buffer.alloc(Math.min(CHUNK, size - p.offset));
      const n = fs.readSync(fd, buf, 0, buf.length, p.offset);
      if (!n) break;
      p.offset += n;
      // The decoder keeps a character the read cut in half for the next read (Hebrew is two bytes a letter).
      const lines = (p.rest + p.decoder.write(n < buf.length ? buf.subarray(0, n) : buf)).split("\n");
      p.rest = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let r;
        try { r = JSON.parse(line); } catch { continue; }
        for (const e of parse(p, r)) for (const send of p.subs) send(e.type, e, e.seq);
      }
    }
  } catch { /* gone, or unreadable now: the next read tries again from where this one stopped */ }
  finally { if (fd !== undefined) try { fs.closeSync(fd); } catch {} }
  return p;
}

// Followers are fed by one poll a second: the volume's files give no reliable change events.
// A turn the app's Stop hooks never closed — an API error, a usage limit, a process that died — is
// closed here once the session has been idle (or gone) for three polls in a row: a follower waiting for
// its turn.end must not wait forever. Waiting on the owner is not idle: the turn goes on once he answers.
setInterval(() => {
  try {
    for (const [id, p] of parsers) if (!p.subs.size && Date.now() - p.used > FORGET) parsers.delete(id);
    if (![...parsers.values()].some((p) => p.subs.size)) return;
    const recs = records();
    const st = live();
    for (const [id, p] of parsers) {
      if (!p.subs.size || !recs.has(id)) continue;
      refresh(recs.get(id));
      const s = st.get(id);
      p.idle = p.open && (!s || s.status === "idle") ? p.idle + 1 : 0;
      if (p.idle >= 3) {
        p.open = false;
        p.idle = 0;
        const e = event(p, "turn.end", { reason: "idle" });
        for (const send of p.subs) send(e.type, e, e.seq);
      }
    }
  } catch (e) { console.error(`[bina-claude] poll: ${e.message}`); }   // the next poll tries again
}, 1000).unref();

// ── the hand: desktop/drive inside the app's container ────────────────────────────────────────────
// One at a time: two hands on one keyboard interleave. A second call is refused, not queued: one that
// waited its turn behind a long drive would outlive its caller, who retries — and the message goes twice.
let driving = false;
// What the driver answers when it pressed nothing (a retry may go again); every other failure — not
// confirmed, no answer — may have been delivered.
const UNSENT = new Set(["no-text", "not-sent", "dropped", "locked", "busy", "waiting", "no-window", "no-app", "no-app-session", "not-focused", "no-session", "no-exec"]);

function drive(args, text) {
  if (driving) return Promise.reject(new Fail(409, "locked", "another call is driving the app right now; nothing was sent — send again when it ends"));
  driving = true;
  return new Promise((resolve, reject) => {
    // The driver's SOURCE goes in, not its path: the app's user cannot always reach the checkout. On Exampleu
    // it is mounted under /root, which is 0700 in the desktop's image, so `python3 <path>` was refused
    // (Errno 13) and no message could ever be sent there (DGO-1684). This container reads it as root.
    let source;
    try { source = fs.readFileSync(DRIVE, "utf8"); }
    catch (e) { throw new Fail(502, "no-exec", `the driver could not be read (${e.code || e.message}); nothing was sent`); }
    const p = spawn("docker", ["exec", "-i", "-u", "abc", "-e", "HOME=/config", "-e", "DISPLAY=:1", DESKTOP,
                               "python3", "-I", "-c", source, ...args], { stdio: ["pipe", "pipe", "pipe"] });
    let out = "", err = "", late = false;
    // The driver ends itself at 150 s with an answer; this is only for a driver that never answers. Killing
    // the docker client does not stop the driver inside, so the outcome is UNKNOWN, never "failed": a
    // caller that retried a failure could send the message twice.
    const kill = setTimeout(() => { late = true; p.kill("SIGKILL"); }, 200000);
    p.stdout.on("data", (d) => { out += d; });
    p.stderr.on("data", (d) => { err = (err + d).slice(-2000); });
    p.stdin.on("error", () => { /* the driver ended before reading: its answer (or 'close') says why */ });
    p.on("error", (e) => { clearTimeout(kill); reject(new Fail(502, "no-exec", `docker exec failed: ${e.message}`)); });
    p.on("close", (code) => {
      clearTimeout(kill);
      let j = null;
      try { j = JSON.parse(out.trim().split("\n").pop()); } catch { /* not the driver's answer */ }
      if (j && j.ok) resolve(j);
      else if (late) reject(new Fail(504, "unknown", "the driver did not answer in 200 s: the message may or may not have been delivered — look at the app before sending it again"));
      // docker exec's own failures: the driver never ran. 126/127 is the command; the engine and the
      // container answer 1 (measured, client 29.9) or 125 with their own words, the driver's never.
      else if (!j && !out.trim() && ([125, 126, 127].includes(code) ||
               /^(Error response from daemon|Cannot connect to the Docker daemon|Error: No such container)/m.test(err))) reject(new Fail(502, "no-exec", `the driver did not run (docker exec ${code}): ${err.trim() || "no reason given"} — nothing was sent`));
      else reject(new Fail(j && ["busy", "waiting", "locked", "not-focused"].includes(j.code) ? 409 : 502, (j && j.code) || "unknown",
                           (j && j.error) || err.trim() || `the driver said nothing (is ${DESKTOP} running?) — the message may or may not have been delivered`));
    });
    p.stdin.end(text);
  }).finally(() => { driving = false; });
}

async function startSession(text) {
  const j = await drive(["new"], text);
  delivered.set(j.id, { at: Date.now(), seq: 0 });
  return j.id;
}

async function sendTo(rec, text) {
  const seq = refresh(rec).seq;   // what was there before this message
  await drive(["send", rec.sessionId], text);
  delivered.set(rec.sessionId, { at: Date.now(), seq });
}

// ── HTTP ──────────────────────────────────────────────────────────────────────────────────────────
function readBody(req, limit = 4 << 20) {
  return new Promise((resolve, reject) => {
    const chunks = []; let n = 0;
    req.on("data", (c) => { n += c.length; if (n > limit) { reject(new Fail(413, "too-large", "body too large")); req.destroy(); } else chunks.push(c); });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}
async function json(req) {
  const b = await readBody(req);
  if (!b.length) return {};
  try { return JSON.parse(b.toString("utf8")); } catch { throw new Fail(400, "bad-json", "body is not JSON"); }
}
function authorized(req) {
  const m = /^Bearer\s+(.+)$/i.exec(req.headers.authorization || "");
  if (!m) return false;
  const a = Buffer.from(m[1].trim()), b = Buffer.from(TOKEN);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
function sse(res) {
  res.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store", connection: "keep-alive", "x-accel-buffering": "no" });
  res.write(":ok\n\n");
  const send = (type, data, id) => { res.write(`${id !== undefined ? `id: ${id}\n` : ""}event: ${type}\ndata: ${JSON.stringify(data)}\n\n`); };
  const keep = setInterval(() => { try { res.write(":ping\n\n"); } catch {} }, 15000);
  return { send, close: () => { clearInterval(keep); try { res.end(); } catch {} } };
}

// Is the app signed in? Its own config names the account it last opened, and that name OUTLIVES a sign-out —
// measured 2026-11-04 (DGO-1347): it answered «signed in» in the minute the owner's screen showed the sign-in
// page, and every reader of `bbox bina-claude status` believed it. What a sign-out DOES remove is the session
// cookie the app keeps for claude.ai, so the cookie is what is asked. Nothing secret is read — presence only,
// never a value. The cookie's ABSENCE, though, is a sign-out only when the app started without it: the running
// app takes it off the disk while it stays signed in (DGO-1684; signin-watch.mjs desktopSignIn says how).
function login() {
  const r = desktopSignIn(DESK);
  return r.state === true ? { logged_in: true, method: "claude-desktop (its claude.ai session cookie)" }
    : { logged_in: r.state, method: null, how: r.why };
}

// ── the sign-out alarm (DGO-1430) ─────────────────────────────────────────────────────────────────
// A Claude that has lost its account is not idle, it is STOPPED. On 2026-11-04 07:29 UTC the desktop app
// lost its claude.ai session and the manager and the group bot that run in it stood still for 48 hours
// while nothing in the office said a word. `login()` above (DGO-1347) is the measurement; this is the
// alarm: one notice when an episode of `logged_in === false` outlives the grace, one line when it ends,
// and the episode on the volume so a restart neither posts twice nor forgets an open one.
//
// The DECISION is one pure function — (state, observation, now) → (state, action) — so it is tested
// without a clock, a container or a network (test_signout.mjs, `node --test`). The caller only does what
// it says and records the outcome: a POST that failed leaves the episode unposted, and the next tick
// tries again — the notice is upserted by source+source_id, so a retry is never a second NOTICE. (It is
// not a second LINE in the group either: the retry asks the board first — `existingNotice()` below.)
const ALARM_EVERY = 60000;
const DEFAULT_GRACE_S = 180;

// A grace that is not a positive number is not a grace: `3m`, ``, `0`, `-5` all used to become NaN, and
// `now - began < NaN` is always false — an alarm that skipped the grace and fired on the app's 1–4 s
// start-up flap after every reboot (the second reader, DGO-1430). Number(raw) is NaN for anything but a
// plain count, so the parse and the rule are the same test. Milliseconds, or null for «that is not one».
export function graceOf(raw, fallbackS = DEFAULT_GRACE_S) {
  if (raw === undefined || raw === null || String(raw).trim() === "") return fallbackS * 1000;
  const s = Number(raw);
  return Number.isFinite(s) && s > 0 ? s * 1000 : null;
}
const ALARM_GRACE = (() => {
  const ms = graceOf(process.env.BINA_CLAUDE_SIGNOUT_GRACE_S);
  if (ms !== null) return ms;
  console.error(`[bina-claude] BINA_CLAUDE_SIGNOUT_GRACE_S=${JSON.stringify(process.env.BINA_CLAUDE_SIGNOUT_GRACE_S)}` +
                ` is not a positive number of seconds — using ${DEFAULT_GRACE_S}` +
                " (an unreadable grace would alarm on the start-up flap)");
  return DEFAULT_GRACE_S * 1000;
})();
const NOTIFY_URL = process.env.BINA_CLAUDE_NOTIFY_URL || "http://notifications:8977/api/notifications";
const SIGNIN_LINK = process.env.BINA_CLAUDE_SIGNIN_LINK || "";
const SIGNOUT_FILE = path.join(STATE, "signout.json");
const ALARM_SOURCE = "bina-claude";
const SIGNOUT_TITLE = "Claude נותק מהחשבון — הסשנים בו עצרו";
const SIGNIN_TITLE = "Claude מחובר שוב";
// What the body names when no address is configured: the tile the person already has.
const SIGNIN_TILE = "האריח «בינה קלוד» בקונסול";

// The hour the OWNER reads, not the container's. An office that sets TZ=Etc/UTC in its .env (the HP
// does) would say an hour he does not read, and DGO-1357 measured what that costs — «מאז 12:16» was
// 14:16 on his phone; the relay says its link notices in his clock for the same reason
// (apps/dashboard/group.py owner_time). BINA_CLAUDE_TZ names another clock explicitly.
const CLOCK = process.env.BINA_CLAUDE_TZ || "Asia/Jerusalem";

let clockWarned = false;
function parts(ms, clock = CLOCK) {
  try {
    const o = {};
    for (const p of new Intl.DateTimeFormat("en-GB", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hourCycle: "h23", timeZone: clock,
    }).formatToParts(new Date(ms))) o[p.type] = p.value;
    return o;
  } catch {                                   // an office that named a clock the runtime does not know
    // Said once, never silently: every hour in a notice would otherwise be UTC while the reader believes it
    // is his own clock — the DGO-1357 trap, this time a typo in BINA_CLAUDE_TZ.
    if (!clockWarned) {
      clockWarned = true;
      console.error(`[bina-claude] BINA_CLAUDE_TZ=${JSON.stringify(clock)} is not a time zone this runtime ` +
                    "knows — every hour is said in UTC");
    }
    const d = new Date(ms), p = (n) => String(n).padStart(2, "0");
    return { day: p(d.getUTCDate()), month: p(d.getUTCMonth() + 1), year: String(d.getUTCFullYear()),
             hour: p(d.getUTCHours()), minute: p(d.getUTCMinutes()) };
  }
}

// When it happened, in the owner's clock — with the DATE when it was not today. A sign-out that began
// three days ago must not read «מאז 09:29», which a person takes for this morning (DGO-1430: the app had
// been out since 2026-11-04 while the line named a time that read as today's).
export function when(ms, now = Date.now(), clock = CLOCK) {
  const t = parts(ms, clock), n = parts(now, clock);
  const hhmm = `${t.hour}:${t.minute}`;
  return t.year === n.year && t.month === n.month && t.day === n.day ? hhmm : `${t.day}.${t.month} ${hhmm}`;
}
const hhmm = (ms) => when(ms, ms);            // for a log line: always this time, never a date

// One episode, in the shape the volume keeps:
//   began      the first observation that said «signed out». It is the alarm's own moment — the app does not
//              write down when its cookie went — so it is only ever a fact about the ALARM.
//   seen       whether this alarm WATCHED the sign-in the episode follows: a «signed in» reading no more
//              than two ticks before `began`. It is what decides whether the notice may say «מאז HH:MM»;
//              an adapter that starts on an app already out, or that comes back after hours of unreadable
//              readings, did not see the beginning, and says «נמצא מנותק ב-HH:MM» instead (DGO-1430: the
//              first line said «מאז 13:28» — the adapter's own start — while the app had been out since
//              2026-11-04 07:29 UTC).
//   posted     the error notice's write went through;  notice  its id, the handle the close needs.
//   attempted  the source_id of an error POST that MAY have reached the board and was never confirmed
//              («the answer came after the abort», «the process died after the POST»). One rule comes of
//              it: a source_id that may exist is never posted blind — the board is asked first, and a
//              board that cannot answer means the tick is skipped, not a second red line.
//   last_in    when a «signed in» reading was last seen. A RESTART keeps it, which is what makes `seen` a
//              measurement of this alarm rather than a hope; it is also why a long gap cannot be dressed
//              up as «מאז <the restart>».
function episode(state) {
  const s = state && typeof state === "object" ? state : {};
  const began = Number(s.began), lastIn = Number(s.last_in);
  return { began: Number.isFinite(began) && began > 0 ? began : null,
           seen: !!s.seen,                 // a state file written before this field reads as «not seen»
           posted: !!s.posted,
           notice: s.notice == null ? null : s.notice,
           attempted: s.attempted == null ? null : String(s.attempted),
           last_in: Number.isFinite(lastIn) && lastIn > 0 ? lastIn : null };
}
// The notice's identity: one episode is ONE notice, whatever the adapter's restarts and retries.
const sourceId = (since) => `signed-out-${Math.floor(since / 1000)}`;
// «the alarm watched the beginning» — a «signed in» reading this close to the first «signed out» one.
const SEEN_WITHIN = 2 * ALARM_EVERY;
const IDLE = { began: null, seen: false, posted: false, notice: null, attempted: null, last_in: null };

export function decideSignout(state, observation, now, graceMs = ALARM_GRACE) {
  const s = episode(state);
  const li = observation ? observation.logged_in : null;
  // Neither a sign-out nor a sign-in: the store is away (the app's container is not up, or it is being
  // rebuilt). An alarm that fired on «I cannot see it» would cry wolf on every bring-up.
  if (li !== true && li !== false) return { state: s, action: null };
  if (li === true) {
    // «signed in» is remembered outside the episode: it is what makes the NEXT episode's beginning a thing
    // this alarm watched, rather than one it walked in on.
    s.last_in = now;
    if (s.began === null) return { state: s, action: null };
    // Nothing was ever said about this episode: it ended inside the grace and is forgotten here. An
    // episode whose write was ATTEMPTED is not forgotten — the board may hold a red line for it, and only
    // the board can say (the second reader, DGO-1430: that answer came after the abort, so the state still
    // said «not posted», and the red line stayed the group's last word for ever).
    if (!s.posted && !s.attempted) return { state: { ...s, began: null, seen: false }, action: null };
    return { state: s, action: { kind: "close", since: s.began, notice: s.notice } };
  }
  // Still out. The episode begins at the first observation that said so, and it is announced once it has
  // outlived the grace without a break — the app's start-up flap (1–4 s) and a sign-in in progress
  // (about a minute) are both inside it. `seen` is settled HERE, once, and never revised.
  if (s.began === null) {
    s.began = now;
    s.seen = s.last_in !== null && now - s.last_in <= SEEN_WITHIN;
  }
  if (s.posted || now - s.began < graceMs) return { state: s, action: null };
  return { state: s, action: { kind: "post", since: s.began, seen: s.seen } };
}

let signout = { ...IDLE };

// What the episode needs from a file that is there but is not JSON (a write cut in half by a power loss,
// a full disk): the numbers and flags themselves, read out of the text. Salvaged so the FIRST notice of an
// open episode is not orphaned by a second one — its id is the only handle the close has, and the close's
// source_id is derived from `began`, so a `began` that cannot be trusted leaves no episode to keep.
// A number must END where a number ends: `"began":17939645` is a write cut mid-number, and read as 17939645
// it is January 1970 — an episode the grace has always already passed, posted at once (the second reader,
// DGO-1430). The floor is the same idea: this alarm did not exist before 2026.
const SALVAGE_FLOOR = Date.UTC(2026, 0, 1);
export function salvageEpisode(raw) {
  const num = (key) => {
    const m = new RegExp(`"${key}"\\s*:\\s*(\\d{6,})(?=\\s*[,}])`).exec(raw);
    return m ? Number(m[1]) : null;
  };
  const flags = (key) => new RegExp(`"${key}"\\s*:\\s*true`).test(raw);
  const m = /"notice"\s*:\s*("([^"]*)"|(\d+))/.exec(raw);
  const notice = !m ? null : (m[3] !== undefined ? Number(m[3]) : m[2]);
  const began = num("began");
  const usable = began !== null && began >= SALVAGE_FLOOR;
  return episode({ began: usable ? began : null, seen: flags("seen"), posted: usable && flags("posted"),
                   notice: usable ? notice : null, last_in: num("last_in"),
                   attempted: /"attempted"\s*:\s*"([^"]*)"/.exec(raw)?.[1] ?? null });
}

function loadSignout() {
  let raw;
  try {
    raw = fs.readFileSync(SIGNOUT_FILE, "utf8");
  } catch (e) {
    signout = { ...IDLE };
    // No file is the first start of a fresh office — ordinary. Anything else is not, and one line says so
    // before the alarm goes on to open an episode it cannot know is a second one.
    if (e.code !== "ENOENT") {
      console.error(`[bina-claude] ${SIGNOUT_FILE} cannot be read (${e.code || e.message}) — ` +
                    `the alarm starts with no episode; if one was open, it will be posted again`);
    }
    return;
  }
  try {
    signout = episode(JSON.parse(raw));
    return;
  } catch { /* not JSON: salvaged below */ }
  const kept = salvageEpisode(raw);
  const recovered = kept.began !== null || kept.notice != null || kept.posted;
  signout = recovered ? kept : { ...IDLE };
  console.error(`[bina-claude] ${SIGNOUT_FILE} is not JSON (${raw.length} bytes) — ` +
                (recovered
                  ? `kept the episode it still names: notice ${kept.notice ?? "(no id)"}, posted ${kept.posted}` +
                    `${kept.began !== null ? `, began ${hhmm(kept.began)}` : ""}`
                  : "nothing in it was readable, so no episode was kept"));
}
function saveSignout() {
  try {
    fs.mkdirSync(STATE, { recursive: true });
    fs.writeFileSync(`${SIGNOUT_FILE}.tmp`, JSON.stringify(signout));
    fs.renameSync(`${SIGNOUT_FILE}.tmp`, SIGNOUT_FILE);
  } catch (e) { console.error(`[bina-claude] sign-out state not written: ${e.message}`); }
}

// One notice to the office's board. Returns its id; throws on anything else, so the caller retries.
async function notify(body) {
  const r = await fetch(NOTIFY_URL, { method: "POST", headers: { "content-type": "application/json" },
                                      body: JSON.stringify(body), signal: AbortSignal.timeout(10000) });
  if (!r.ok) throw new Error(`${NOTIFY_URL} answered ${r.status} for ${body.source_id}`);
  const j = await r.json().catch(() => null);
  return j && j.id != null ? j.id : null;
}
async function markRead(id) {
  const url = `${NOTIFY_URL.replace(/\/+$/, "")}/${encodeURIComponent(id)}/read`;
  const r = await fetch(url, { method: "POST", signal: AbortSignal.timeout(10000) });
  if (!r.ok) throw new Error(`${url} answered ${r.status}`);
}

// Is this episode's notice already on the board, and at which level? ONE read, and its answer has THREE
// states, because «not there» and «could not ask» are not the same fact: ok:false means the board said
// nothing — a red line is never posted on that (the second reader, DGO-1430: both calls timing out made the
// adapter post again every tick, and every re-POST is a `notice.recurred` on a stream the group reads).
async function existingNotice(sid) {
  try {
    const r = await fetch(`${NOTIFY_URL.replace(/\/+$/, "")}?source=${encodeURIComponent(ALARM_SOURCE)}&limit=50`,
                          { signal: AbortSignal.timeout(10000) });
    if (!r.ok) return { ok: false, why: `the board answered ${r.status}` };
    const j = await r.json();
    const hit = (j.notifications || j.items || []).find((n) => String(n.source_id) === sid);
    return { ok: true, id: hit ? hit.id : null, level: hit ? String(hit.level || "").toLowerCase() : null };
  } catch (e) { return { ok: false, why: e.message }; }
}

let alarmBusy = false;

// One turn of the alarm, with its effects named instead of reached for — the board's lookup, its POST, its
// mark-read and the pen that writes the episode to the volume. The pen is here for one reason: `attempted`
// must reach the disk BEFORE the POST leaves, or a process that dies between the two (or an answer that
// arrives after the abort) leaves a red line on the board and a state that says nothing was said.
export async function alarmStep(state, observation, now, io) {
  const d = decideSignout(state, observation, now);
  const next = d.state;
  const a = d.action;
  if (!a) return { state: next, step: "none" };
  const sid = sourceId(a.since);

  if (a.kind === "post") {
    // A source_id this adapter may already have sent: the board is asked, never posted at blind.
    if (next.attempted === sid) {
      const had = await io.existing(sid);
      if (!had.ok) return { state: next, step: "waiting", why: `the board did not answer (${had.why})` };
      if (had.id != null) {                                    // it landed: adopt it, do not say it twice
        return { state: { ...next, notice: had.id, posted: true, attempted: null },
                 step: "adopted", since: a.since, notice: had.id };
      }
    }
    io.commit({ ...next, attempted: sid });                     // ON DISK before it leaves
    next.attempted = sid;
    next.notice = await io.notify({
      source: ALARM_SOURCE, source_id: sid, level: "error", title: SIGNOUT_TITLE,
      // «מאז» only when this alarm watched the sign-in it follows; otherwise the moment it FOUND the app out,
      // said as the finding it is — with the date when that was not today. The relay writes the title and
      // the body (not the link field), so the address is in the body.
      body: `${a.seen ? `מאז ${when(a.since, now)}` : `נמצא מנותק ב-${when(a.since, now)}`}.` +
            ` להתחבר: ${SIGNIN_LINK || SIGNIN_TILE} → Continue with Google.`,
      link: SIGNIN_LINK,
    });
    next.posted = true;
    next.attempted = null;
    return { state: next, step: "post", since: a.since, seen: a.seen, notice: next.notice };
  }

  // The close. The board is asked FIRST, every time: an episode whose red line never landed has nothing to
  // close (posting the info would create a green notice about nothing), and an episode whose closing answer
  // was lost already reads «info» there (posting again would be a second green line). A board that cannot
  // answer keeps the episode for the next tick.
  const had = await io.existing(sid);
  if (!had.ok) return { state: next, step: "waiting", why: `the board did not answer (${had.why})` };
  if (had.id == null) {                                         // nothing was ever said: nothing to close
    return { state: { ...next, began: null, seen: false }, step: "forgot", since: a.since };
  }
  let id = had.id;
  if (had.level !== "info") {
    id = (await io.notify({
      source: ALARM_SOURCE, source_id: sid, level: "info", title: SIGNIN_TITLE,
      body: `שוב מחובר. ההתראה מ-${when(a.since, now)} נסגרה.`, link: SIGNIN_LINK,
    })) ?? id;
  }
  const closed = { ...IDLE, last_in: now };   // the episode ends with the closing LINE, not with the read
  try { await io.markRead(id); }              // the board's own red dot: best effort, never blocking
  catch (e) { console.error(`[bina-claude] the sign-out notice ${id} was closed but not marked read: ${e.message}`); }
  return { state: closed, step: "closed", since: a.since, notice: id, already: had.level === "info" };
}

async function alarmTick() {
  if (alarmBusy) return;             // the previous tick is still posting: one notice, never two in flight
  alarmBusy = true;
  try {
    const done = await alarmStep(signout, login(), Date.now(), {
      existing: existingNotice, notify, markRead,
      commit: (s) => { signout = s; saveSignout(); },
    });
    signout = done.state;
    if (done.step === "post") {
      console.log(`[bina-claude] ${done.seen ? "signed out since" : "found signed out at"} ${hhmm(done.since)}` +
                  ` — notice ${done.notice ?? "(no id)"}`);
    } else if (done.step === "adopted") {
      console.log(`[bina-claude] the sign-out notice from ${hhmm(done.since)} was already on the board` +
                  ` — notice ${done.notice}, nothing was said twice`);
    } else if (done.step === "closed") {
      console.log(`[bina-claude] signed in again — the sign-out notice from ${hhmm(done.since)} is closed` +
                  `${done.already ? " (it had already been said)" : ""}`);
    } else if (done.step === "forgot") {
      console.log(`[bina-claude] signed in again — nothing had been posted about the sign-out at ` +
                  `${hhmm(done.since)}, so there is nothing to close`);
    } else if (done.step === "waiting") {
      console.log(`[bina-claude] the sign-out alarm waits a tick: ${done.why}`);
    }
  } catch (e) {
    // A POST that failed says nothing about the sign-in: the episode stays as it was and the next tick
    // tries again. Nothing here may take the adapter down with it.
    console.error(`[bina-claude] sign-out alarm: ${e.message}`);
  } finally {
    alarmBusy = false;
    saveSignout();
  }
}

const notHere = (what) => new Fail(501, "not-implemented", `${what} is not offered over agent.v1 for the desktop app yet — do it on its screen (apps/bina-claude/README.md)`);

async function route(req, res, url) {
  const p = url.pathname;
  if (p === "/v1/health") {
    const out = { ok: true, provider: "bina-claude", version: VERSION, harness: "claude-desktop", harness_ms: 0,
                  uptime_s: Math.round((Date.now() - startedAt) / 1000), stream: true, desktop: DESKTOP, login: login(),
                  signout: { since_ms: signout.began, seen: signout.seen, posted: signout.posted,
                             notice: signout.notice, attempted: signout.attempted,
                             last_in_ms: signout.last_in, grace_s: ALARM_GRACE / 1000 },
                  active: [...live().values()].filter((s) => MID_TURN.has(s.status)).length };
    if (url.searchParams.get("deep")) { const t = Date.now(); out.sessions = records().size; out.list_ms = Date.now() - t; }
    return out;
  }
  // SPAN_SOURCE_BINA_CLAUDE (app.json) — outside the token gate and read-only, as bina-ds's lane is: an
  // any-concurrency span source is a bare GET that holds no credential. Reachable only from the office
  // network and the docker host's loopback; every label is bounded (spans.mjs).
  if (req.method === "GET" && (p === "/timeline/spans" || p === "/v1/timeline/spans")) {
    const since = Number(url.searchParams.get("since") || 0);
    const hours = Number(url.searchParams.get("hours") || 0);
    const limit = Math.max(1, Math.min(50000, Number(url.searchParams.get("limit")) || 20000));
    return spans.read(since > 0 ? { since, limit } : { hours, limit });
  }
  if (!authorized(req)) throw new Fail(401, "token", "missing or wrong bearer token");
  if (p === "/v1/login") return login();
  if (p === "/v1/models") return { default: { provider: "anthropic", model: "the app's choice" }, groups: [] };
  if (p === "/v1/presets") return { presets: [{ id: "claude-desktop", name: "the Claude desktop app", isDefault: true, description: "sessions of the official app, on its screen" }] };
  if (p === "/v1/permissions") return { permissions: [{ id: "the app's", isDefault: true }] };
  if (p === "/v1/sessions" && req.method === "GET") {
    const st = live();
    const all = url.searchParams.get("all");
    return { sessions: [...records().values()].filter((r) => all || !r.isArchived).map((r) => summary(r, st.get(r.sessionId)))
      .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || "")) };
  }
  if (p === "/v1/sessions" && req.method === "POST") {
    const b = await json(req);
    if (typeof b.text === "string" && b.text.trim()) return [201, { id: await startSession(b.text.trim()), preset: "claude-desktop" }];
    const id = `pending-${crypto.randomUUID()}`;
    pending.set(id, { at: Date.now(), start: null, id: null });
    return [201, { id, preset: "claude-desktop" }];
  }
  if (p === "/v1/search") {
    const q = (url.searchParams.get("q") || "").toLowerCase();
    const st = live();
    return { items: [...records().values()].filter((r) => (r.title || "").toLowerCase().includes(q)).map((r) => summary(r, st.get(r.sessionId))), hasMore: false };
  }
  const m = /^\/v1\/sessions\/([^/]+)(?:\/([a-z]+))?$/.exec(p);
  if (!m) throw new Fail(404, "no-route", `no route ${req.method} ${p}`);
  const given = decodeURIComponent(m[1]);
  const verb = m[2] || "";
  const hit = find(given);
  if (hit.pendingId) {
    // Before its first message only one thing can happen to it: that message starts it.
    if (verb === "messages" && req.method === "POST") {
      const text = String((await json(req)).text || "").trim();
      if (!text) throw new Fail(400, "no-text", "a message needs text");
      // One start per promise: a second POST while the first runs (a retry) waits for the same session.
      // A start that pressed nothing may be tried again; one that may have started a session keeps its
      // answer, so a retry never starts a second one.
      const pd = pending.get(given);
      if (!pd.start) pd.start = startSession(text).then((id) => { pd.id = id; return id; }, (e) => { if (UNSENT.has(e.code)) pd.start = null; throw e; });
      return [202, { accepted: true, queue: 0, id: await pd.start }];
    }
    if (!verb && req.method === "GET") return { id: given, title: "", running: false, blank: true, preset: "claude-desktop", turns: 0 };
    throw new Fail(409, "not-started", `${given} starts with its first message`);
  }
  const rec = hit.rec;
  const id = rec.sessionId;
  if (!verb && req.method === "GET") return summary(rec, live().get(id));
  if (verb === "messages" && req.method === "POST") {
    const b = await json(req);
    const text = String(b.text || "").trim();
    if (!text) throw new Fail(400, "no-text", "a message needs text");
    if (b.steer) throw notHere("steer");
    if (Array.isArray(b.files) && b.files.length) throw notHere("a file");
    await sendTo(rec, text);
    return [202, { accepted: true, queue: 0 }];
  }
  if (verb === "messages") {
    const limit = Math.max(1, Math.min(500, Number(url.searchParams.get("limit") || 50)));
    const evs = refresh(rec).events;
    return { events: evs.slice(-limit), has_more: evs.length > limit };
  }
  if (verb === "events") {
    const history = Math.max(0, Number(url.searchParams.get("history") || 0));
    const since = Number(url.searchParams.get("since") ?? -1);
    const pr = refresh(rec);
    const evs = pr.events;
    const running = summary(rec, live().get(id)).running || pr.open;
    const stream = sse(res);
    stream.send("open", { id, history: history > 0 });
    const past = since >= 0 ? evs.filter((e) => e.seq > since) : (history ? evs.slice(-history) : []);
    stream.send("snapshot", { events: past, running });
    // A follower that attaches after the turn it came for began — `bbox agent new|send -F` always does,
    // and the app may even have FINISHED a short turn by then — gets that turn from its turn.start: the
    // one this adapter delivered in the last two minutes (only a turn that began AFTER the delivery, never
    // the one before it), or else the one running.
    if (since < 0) {
      const d = delivered.get(id);
      const last = past.length ? past[past.length - 1].seq : 0;
      const start = d && Date.now() - d.at < 120000
        ? evs.find((e) => e.type === "turn.start" && e.seq > d.seq)
        : (running ? evs.findLast((e) => e.type === "turn.start") : null);
      if (start) for (const e of evs) if (e.seq >= start.seq && e.seq > last) stream.send(e.type, e, e.seq);
    }
    pr.subs.add(stream.send);
    req.on("close", () => { pr.subs.delete(stream.send); stream.close(); });
    return null;
  }
  // Esc on the session's running turn, as the owner stops one (desktop/drive cancel, DGO-1684). A session
  // waiting on the owner is refused: Esc there would answer his question.
  if (verb === "cancel" && req.method === "POST") {
    const j = await drive(["cancel", id], "");
    return { id, cancelled: !!j.cancelled, ...(j.note ? { note: j.note } : {}) };
  }
  if (verb === "commands") return { commands: [] };
  if (verb === "goal") return { goal: null };
  if (verb === "subagents") return { subagents: [] };
  throw notHere(verb || req.method);
}

// The entry point (entrypoint.sh runs `node /opt/bina-claude/adapter/server.mjs`, and restarts it if it
// ever stops): the token, the order on the volume, the alarm's clock, then the contract's door.
function main() {
  fs.mkdirSync(STATE, { recursive: true });
  TOKEN = fs.readFileSync(TOKEN_FILE, "utf8").trim();
  // DGO-1430's alarm (alarmTick) is NOT started: the sign-in watch above (signin-watch.mjs, DGO-1684) is the one
  // alarm. Both posted `source: bina-claude` at level error, so every sign-out rang the phone and the group twice,
  // and this one also spoke on a fresh office that was never signed in (the release that took both lines,
  // DGO-969). Its pure step (alarmStep) stays, tested by test_signout.mjs.

  http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://adapter");
    try {
      const out = await route(req, res, url);
      if (out === null) return;   // a stream owns the response
      const [status, body] = Array.isArray(out) ? out : [200, out];
      res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
      res.end(JSON.stringify(body));
    } catch (e) {
      const status = e instanceof Fail ? e.status : 500;
      if (!res.headersSent) res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: e.message || String(e), code: e.code || "internal" }));
    }
  }).listen(PORT, "0.0.0.0", () => console.log(`[bina-claude] agent.v1 over the Claude desktop app on :${PORT} · ${DESKTOP}`));
}

// Imported — by test_signout.mjs — this file offers only its pure decision and starts nothing.
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) main();
