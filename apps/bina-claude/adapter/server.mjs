// apps/bina-claude/adapter/server.mjs — agent.v1 (ai/context/agent-contract.md) over Claude Code.
//
// The office's agents speak ONE contract. bina-ds serves it over the DeepSeek Harness; this serves the
// same routes over the official Claude Code CLI, so `bbox agent --app bina-claude …`, Azaria, n8n and any
// other caller drive Claude exactly as they drive Azaria — and nothing a caller holds names a harness.
//
// A session here is a record of ours plus the Claude Code session it resumes. A turn is ONE run of
//   claude -p <text> --output-format stream-json --verbose [--resume <claude session>] [--model <m>]
// whose JSON lines are translated into the contract's events (turn.start, user, assistant, reasoning,
// tool.call, tool.result, error, turn.end). The CLI is the same binary the web terminal runs, signed in
// with the same account (HOME on the volume), so a login made in the UI is the login the API uses.
//
// No dependencies: node's own http, child_process and fs. State is files on the volume —
//   <STATE>/sessions/<id>.json   the summary (rewritten after every turn)
//   <STATE>/sessions/<id>.jsonl  the events, appended as they happen
// — so a restart loses only the turn that was running, which is reported as such.
import http from "node:http";
import { spawn, execFile } from "node:child_process";
import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";

const PORT = Number(process.env.BINA_CLAUDE_ADAPTER_PORT || 3091);
const STATE = process.env.BINA_CLAUDE_STATE || "/data/bina-claude";
const TOKEN_FILE = process.env.AGENT_TOKEN_FILE || `${STATE}/api-token`;
const OFFICE = process.env.BBOX_REPO_HOST || "/workspace/office";
const CLAUDE = process.env.CLAUDE_BIN || "claude";
const HOME = process.env.HOME || "/data/home";
// The permission mode a turn runs in. The office agent operates the deployment (the same decision as
// bina-ds's danger-full-access, owner 2026-09-17), so nothing waits for an approval nobody can give
// from an API. As root, Claude Code allows it only with IS_SANDBOX=1 (docker-compose.yml).
const PERMISSION = process.env.BINA_CLAUDE_PERMISSION_MODE || "bypassPermissions";
const DEFAULT_MODEL = process.env.BINA_CLAUDE_MODEL || "";
// Turns at once, across every session. Each is a node process of ~250 MB; the Mac's engine has 5 GB
// for the whole office. A turn past the limit waits its turn, it is never refused.
const MAX_TURNS = Math.max(1, Number(process.env.BINA_CLAUDE_MAX_TURNS || 2));
const VERSION = "0.1.0";
const SESSIONS = path.join(STATE, "sessions");
const startedAt = Date.now();

fs.mkdirSync(SESSIONS, { recursive: true });
const TOKEN = fs.readFileSync(TOKEN_FILE, "utf8").trim();

let harness = "claude-code";
execFile(CLAUDE, ["--version"], { timeout: 30000 }, (err, out) => {
  if (!err && out) harness = `claude-code ${String(out).trim().split(/\s+/)[0]}`;
});

class Fail extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

// ── sessions ──────────────────────────────────────────────────────────────────────────────────────
const sessions = new Map();   // id → {meta, events|null, queue, proc, subs, waiting}
const now = () => new Date().toISOString();

// The summary is saved at a turn's edges; the events are appended as they happen. So after a restart
// the EVENTS are the truth: seq and turn come from them (a stale seq would hand out numbers the log
// already has, and `since=` replay would answer with the wrong events), and a turn that started and
// never ended was cut by the restart — it gets its end now, said as such.
function load() {
  for (const f of fs.readdirSync(SESSIONS)) {
    if (!f.endsWith(".json")) continue;
    try {
      const meta = JSON.parse(fs.readFileSync(path.join(SESSIONS, f), "utf8"));
      const s = { meta, events: null, queue: [], proc: null, subs: new Set(), waiting: false };
      sessions.set(meta.id, s);
      const evs = eventsOf(s);
      if (!evs.length) continue;
      meta.seq = Math.max(meta.seq || 0, ...evs.map((e) => e.seq || 0));
      meta.turns = Math.max(meta.turns || 0, ...evs.map((e) => e.turn || 0));
      const lastStart = evs.findLastIndex((e) => e.type === "turn.start");
      if (lastStart >= 0 && !evs.slice(lastStart).some((e) => e.type === "turn.end")) {
        emit(s, "error", { code: "interrupted", message: "the adapter restarted while this turn ran; send the message again" });
        emit(s, "turn.end", { reason: "interrupted" });
      }
      save(s);
    } catch { /* a half-written summary: its events are still on disk, the next turn rewrites it */ }
  }
}

function save(s) {
  const f = path.join(SESSIONS, `${s.meta.id}.json`);
  fs.writeFileSync(`${f}.tmp`, JSON.stringify(s.meta));
  fs.renameSync(`${f}.tmp`, f);
}

function eventsOf(s) {
  if (s.events) return s.events;
  s.events = [];
  try {
    for (const line of fs.readFileSync(path.join(SESSIONS, `${s.meta.id}.jsonl`), "utf8").split("\n")) {
      if (line) try { s.events.push(JSON.parse(line)); } catch { /* a torn last line */ }
    }
  } catch { /* no events yet */ }
  return s.events;
}

function emit(s, type, data = {}) {
  const ev = { type, seq: ++s.meta.seq, at: now(), turn: s.meta.turns, ...data };
  eventsOf(s).push(ev);
  fs.appendFileSync(path.join(SESSIONS, `${s.meta.id}.jsonl`), JSON.stringify(ev) + "\n");
  s.meta.updated_at = ev.at;
  for (const send of s.subs) send(type, ev, ev.seq);
  return ev;
}

function summary(s) {
  const m = s.meta;
  return {
    id: m.id, title: m.title, running: !!s.proc || s.waiting, blank: m.turns === 0 && !s.queue.length,
    created_at: m.created_at, updated_at: m.updated_at, preset: "claude", permissions: PERMISSION,
    model: m.model || null, goal: null, todos: m.todos || [], turns: m.turns, tokens: m.tokens || {},
    queue: s.queue.length, cwd: m.cwd, claude_session: m.claude_session || null,
  };
}

function find(given) {
  if (sessions.has(given)) return sessions.get(given);
  const hits = [...sessions.keys()].filter((id) => id.startsWith(given));
  if (hits.length === 1) return sessions.get(hits[0]);
  if (hits.length > 1) throw new Fail(409, "ambiguous", `${hits.length} sessions start with ${given}`);
  throw new Fail(404, "no-session", `no session ${given}`);
}

function create({ title, cwd } = {}) {
  const id = crypto.randomUUID();
  const at = now();
  const meta = { id, title: title || "", created_at: at, updated_at: at, cwd: cwd || OFFICE, turns: 0, seq: 0,
                 claude_session: null, model: null, model_choice: DEFAULT_MODEL || null, tokens: {}, todos: [] };
  const s = { meta, events: [], queue: [], proc: null, subs: new Set(), waiting: false };
  sessions.set(id, s);
  save(s);
  return s;
}

// ── turns ─────────────────────────────────────────────────────────────────────────────────────────
let active = 0;
const pending = [];   // sessions whose next turn waits for a free slot

function enqueue(s, text, steer = false) {
  if (steer && s.proc) {
    s.queue.unshift(text);
    emit(s, "inbox", { text });
    cancel(s);
  } else if (steer) {
    s.queue.unshift(text);      // waiting for a slot: a steer still goes first
  } else {
    s.queue.push(text);
  }
  pump(s);
}

function pump(s) {
  if (s.proc || s.waiting || !s.queue.length) return;
  if (active >= MAX_TURNS) { s.waiting = true; pending.push(s); return; }
  run(s, s.queue.shift());
}

function release() {
  active--;
  while (active < MAX_TURNS && pending.length) {
    const next = pending.shift();
    next.waiting = false;
    if (next.queue.length && !next.proc) run(next, next.queue.shift());
  }
}

function flat(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((c) => (typeof c === "string" ? c : c.text || (c.type ? `[${c.type}]` : ""))).join("\n");
  return content == null ? "" : JSON.stringify(content);
}

function translate(s, j, turn) {
  if (j.type === "system" && j.subtype === "init") {
    if (j.session_id) s.meta.claude_session = j.session_id;
    if (j.model) s.meta.model = { provider: "anthropic", model: j.model };
    save(s);                    // a restart mid-turn must still resume the right Claude session
    return;
  }
  if (j.type === "assistant") {
    emit(s, "step.start");
    for (const c of (j.message && j.message.content) || []) {
      if (c.type === "text" && c.text) emit(s, "assistant", { text: c.text });
      else if (c.type === "thinking" && c.thinking) emit(s, "reasoning", { text: c.thinking });
      else if (c.type === "tool_use") {
        emit(s, "tool.call", { id: c.id, name: c.name, args: c.input });
        if (c.name === "TodoWrite" && c.input && Array.isArray(c.input.todos)) s.meta.todos = c.input.todos;
      }
    }
    emit(s, "step.end");
    return;
  }
  if (j.type === "user" && j.message && Array.isArray(j.message.content)) {
    for (const c of j.message.content) {
      if (c.type === "tool_result") emit(s, "tool.result", { id: c.tool_use_id, ok: !c.is_error, text: flat(c.content).slice(0, 8000) });
    }
    return;
  }
  if (j.type === "result") {
    turn.result = j;
    if (j.session_id) s.meta.claude_session = j.session_id;
    const u = j.usage || {};
    const t = s.meta.tokens || {};
    s.meta.tokens = {
      uncachedInputTokens: (t.uncachedInputTokens || 0) + (u.input_tokens || 0),
      outputTokens: (t.outputTokens || 0) + (u.output_tokens || 0),
      cacheReadTokens: (t.cacheReadTokens || 0) + (u.cache_read_input_tokens || 0),
      costUsd: Math.round(((t.costUsd || 0) + (j.total_cost_usd || 0)) * 1e6) / 1e6,
    };
    // An error a turn ENDS with (not signed in, a refused request) comes as subtype "success" with
    // is_error: the subtype says how the run ended, not whether it worked.
    if (j.is_error) {
      const message = flat(j.result) || "Claude Code reported an error";
      const code = /run \/login|not logged in/i.test(message) ? "not-signed-in" : (j.subtype && j.subtype !== "success" ? j.subtype : "claude-error");
      emit(s, "error", { code, message });
    }
  }
}

function run(s, text) {
  active++;
  const m = s.meta;
  m.turns++;
  if (!m.title) m.title = text.replace(/\s+/g, " ").trim().slice(0, 60);
  emit(s, "turn.start");
  emit(s, "user", { text, source: "user" });
  const args = ["-p", text, "--output-format", "stream-json", "--verbose", "--permission-mode", PERMISSION];
  if (m.claude_session) args.push("--resume", m.claude_session);
  if (m.model_choice) args.push("--model", m.model_choice);
  const turn = { result: null, cancelled: false, stderr: "" };
  let proc;
  try {
    proc = spawn(CLAUDE, args, { cwd: fs.existsSync(m.cwd) ? m.cwd : OFFICE, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
  } catch (e) {
    emit(s, "error", { code: "spawn", message: String(e.message || e) });
    emit(s, "turn.end", { reason: "error" });
    save(s); release(); return;
  }
  s.proc = proc;
  s.turn = turn;
  let buf = "";
  proc.stdout.on("data", (d) => {
    buf += d;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      try { translate(s, JSON.parse(line), turn); } catch { /* a non-JSON line: Claude Code's own notice */ }
    }
  });
  proc.stderr.on("data", (d) => { turn.stderr = (turn.stderr + d).slice(-4000); });
  // A spawn that fails (ENOENT, EAGAIN/ENOMEM under the memory limit) is an 'error' EVENT, not a throw;
  // unheard, it kills the adapter. 'close' still follows, so the slot is released once, there.
  proc.on("error", (e) => { turn.stderr = `${turn.stderr}\n${e.message}`.slice(-4000); });
  proc.on("close", (code) => {
    if (!turn.result && !turn.cancelled) {
      emit(s, "error", { code: "claude-exit", message: turn.stderr.trim() || `claude exited ${code} with no result` });
    }
    const reason = turn.cancelled ? "cancelled" : turn.result ? (turn.result.is_error ? "error" : "completed") : "error";
    emit(s, "turn.end", { reason, ...(turn.result && turn.result.duration_ms ? { duration_ms: turn.result.duration_ms } : {}) });
    s.proc = null;
    s.turn = null;
    save(s);
    release();
    pump(s);
  });
}

function cancel(s) {
  if (!s.proc) return false;
  s.turn.cancelled = true;
  const p = s.proc;
  p.kill("SIGINT");
  setTimeout(() => { if (p.exitCode === null) p.kill("SIGKILL"); }, 5000).unref();
  return true;
}

// ── the account ───────────────────────────────────────────────────────────────────────────────────
// Which sign-in the CLI will use, in Claude Code's own order: an OAuth token in the environment, an
// API key, then the account signed in through /login (its credentials file on the volume).
function login() {
  if (process.env.CLAUDE_CODE_OAUTH_TOKEN) return { logged_in: true, method: "oauth-token" };
  if (process.env.ANTHROPIC_API_KEY) return { logged_in: true, method: "api-key" };
  const creds = path.join(HOME, ".claude", ".credentials.json");
  try {
    const j = JSON.parse(fs.readFileSync(creds, "utf8"));
    const o = j.claudeAiOauth || {};
    return { logged_in: !!(o.accessToken || o.refreshToken), method: "claude.ai", subscription: o.subscriptionType || null,
             expires_at: o.expiresAt ? new Date(o.expiresAt).toISOString() : null };
  } catch {
    return { logged_in: false, method: null, how: "open «בינה קלוד» in the console and type /login (or set BINA_CLAUDE_ANTHROPIC_API_KEY in .env)" };
  }
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

const MODELS = {
  default: { provider: "anthropic", model: DEFAULT_MODEL || "default" },
  groups: [{ id: "anthropic", name: "Claude (the signed-in account)", models: [
    { id: "opus", name: "Claude Opus — the latest" },
    { id: "sonnet", name: "Claude Sonnet — the latest" },
    { id: "haiku", name: "Claude Haiku — the latest" },
  ] }],
};

async function route(req, res, url) {
  const p = url.pathname;
  if (p === "/v1/health") {
    const out = { ok: true, provider: "bina-claude", version: VERSION, harness, harness_ms: 0,
                  uptime_s: Math.round((Date.now() - startedAt) / 1000), stream: true, login: login(), active, max_turns: MAX_TURNS };
    if (url.searchParams.get("deep")) { out.sessions = sessions.size; out.list_ms = 0; }
    return out;
  }
  if (!authorized(req)) throw new Fail(401, "token", "missing or wrong bearer token");
  if (p === "/v1/login") return login();
  if (p === "/v1/models") return MODELS;
  if (p === "/v1/presets") return { presets: [{ id: "claude", name: "Claude Code", isDefault: true, description: `permission mode ${PERMISSION}` }] };
  if (p === "/v1/permissions") return { permissions: [{ id: PERMISSION, isDefault: true }] };
  if (p === "/v1/sessions" && req.method === "GET") {
    return { sessions: [...sessions.values()].map(summary).sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || "")) };
  }
  if (p === "/v1/sessions" && req.method === "POST") {
    const b = await json(req);
    const s = create(b);
    if (typeof b.text === "string" && b.text.trim()) enqueue(s, b.text);
    return [201, { id: s.meta.id, preset: "claude" }];
  }
  if (p === "/v1/search") {
    const q = (url.searchParams.get("q") || "").toLowerCase();
    return { items: [...sessions.values()].filter((s) => (s.meta.title || "").toLowerCase().includes(q)).map(summary), hasMore: false };
  }
  const m = /^\/v1\/sessions\/([^/]+)(?:\/([a-z]+))?$/.exec(p);
  if (!m) throw new Fail(404, "no-route", `no route ${req.method} ${p}`);
  const s = find(decodeURIComponent(m[1]));
  const verb = m[2] || "";
  if (!verb && req.method === "GET") return summary(s);
  if (verb === "messages" && req.method === "POST") {
    const b = await json(req);
    const text = String(b.text || "").trim();
    if (!text) throw new Fail(400, "no-text", "a message needs text");
    enqueue(s, text, !!b.steer);
    return [202, { accepted: true, queue: s.queue.length }];
  }
  if (verb === "messages") {
    const limit = Math.max(1, Math.min(500, Number(url.searchParams.get("limit") || 50)));
    const evs = eventsOf(s);
    return { events: evs.slice(-limit), has_more: evs.length > limit };
  }
  if (verb === "events") {
    const history = Math.max(0, Number(url.searchParams.get("history") || 0));
    const since = Number(url.searchParams.get("since") ?? -1);
    const evs = eventsOf(s);
    const stream = sse(res);
    stream.send("open", { id: s.meta.id, history: history > 0 });
    const past = since >= 0 ? evs.filter((e) => e.seq > since) : (history ? evs.slice(-history) : []);
    stream.send("snapshot", { events: past, running: !!s.proc });
    // A follower that attaches while a turn runs gets that turn from its turn.start, live: the caller
    // that posts a message and then follows (`bbox agent new -F`) always attaches after the turn began,
    // and waits for a turn.start it would otherwise never see.
    // Not a turn being cancelled for a steer: replaying it would hand the follower its turn.end, and
    // the follower would leave before the steered turn it came for.
    if (s.proc && !(s.turn && s.turn.cancelled) && since < 0) {
      const last = past.length ? past[past.length - 1].seq : 0;
      for (const e of evs) if (e.turn === s.meta.turns && e.seq > last) stream.send(e.type, e, e.seq);
    }
    s.subs.add(stream.send);
    req.on("close", () => { s.subs.delete(stream.send); stream.close(); });
    return null;
  }
  if (verb === "cancel" && req.method === "POST") {
    s.queue.length = 0;
    if (s.waiting) { s.waiting = false; pending.splice(pending.indexOf(s), 1); }
    return [202, { cancelled: cancel(s) }];
  }
  if (["upload", "fork", "command", "preset"].includes(verb)) {
    throw new Fail(501, "not-implemented", `${verb} is not implemented by bina-claude (apps/bina-claude/README.md)`);
  }
  if (verb === "rename" && req.method === "POST") {
    const b = await json(req);
    s.meta.title = String(b.title || "").slice(0, 200);
    emit(s, "title", { title: s.meta.title });
    save(s);
    return { id: s.meta.id, title: s.meta.title };
  }
  if (verb === "model" && req.method === "POST") {
    const b = await json(req);
    s.meta.model_choice = String(b.model || "").trim() || null;
    save(s);
    return { provider: "anthropic", model: s.meta.model_choice || "default" };
  }
  if (verb === "commands") return { commands: [] };
  if (verb === "goal") return { goal: null };
  if (verb === "subagents") return { subagents: [] };
  throw new Fail(404, "no-route", `no route ${req.method} ${p}`);
}

load();
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
}).listen(PORT, "0.0.0.0", () => console.log(`[bina-claude] agent.v1 on :${PORT} · ${sessions.size} sessions · ${MAX_TURNS} turns at once`));
