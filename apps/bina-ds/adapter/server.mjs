// bina-ds adapter — the `agent.v1` contract (ai/context/agent-contract.md) served over the DeepSeek
// Harness running in this same container, plus the office timeline's lane.
//
// The harness speaks its own RPC: POST /api/<namespace>/<method> with
//   {"type":"client-request","rpcId","method":"<namespace>/<method>","payload":{"args":{…}}}
// where args are named after the server method's parameters (session/create(request),
// session/list(_request), goals/get(agentId), commands/execute(agentId, line, submittedAttachments)),
// and live data flows over ONE WebSocket at /api/remote.mux ({type:"open"|"cancel"} in,
// {type:"item"|"end"|"error"} out). This process translates the platform's small, stable REST+SSE
// contract onto those calls, so nothing outside this container depends on the harness's wire
// protocol — a harness upgrade that renames a method is fixed here, once.
//
// Reach: the container publishes this port on the docker HOST's loopback only
// (127.0.0.1:${BINA_DS_AGENT_PORT} in docker-compose.yml). On the macOS engine Lima forwards a guest
// loopback port to the Mac's loopback, so `bbox agent` on any host talks to 127.0.0.1 directly: no
// edge, no DNS, no process spawned per call. Nothing else is reachable this way.
//
// Auth, both hops: callers present the office's action token (Bearer) to this server; this server
// presents the same token to the harness, which customize.sh taught to accept it. The token is
// minted by entrypoint.sh into the volume and never leaves the container except through the
// operator's own `bbox agent login` (which reads it via the engine — the same trust as docker).
import { createServer } from "node:http";
import { randomUUID, timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const PORT = Number(process.env.BINA_DS_ADAPTER_PORT || 3081);
const HARNESS = `http://127.0.0.1:${process.env.DSH_PORT || 3080}`;
const HARNESS_WS = HARNESS.replace(/^http/, "ws") + "/api/remote.mux";
const OFFICE = process.env.DSH_OFFICE_ROOT || "/workspace/office";
const PROFILE_DIR = process.env.DSH_PROFILE_DIR || "/opt/bina/harness/profile";
const TOKEN = (process.env.BINA_DS_API_TOKEN || readFileSync(`${process.env.DSH_HOME || "/data/dsh"}/api-token`, "utf8")).trim();
const VERSION = "agent.v1 / bina-ds 2";
const TZ = process.env.TZ || "Asia/Jerusalem";
const STARTED = Date.now();

class Fail extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

// The timeline lane's store — the same module the harness plugin (plugins/timeline-lanes) writes
// through, so the capture and this projection cannot drift apart. Loaded on FIRST USE rather than at
// startup on purpose: the lane is an addition to this process, and agent.v1 must keep answering even
// if the store is missing from an image, so a broken lane degrades to one failing route.
let ledgerModule = null;
/** The lane's store module, or a 503 that names the real reason. A failed load is not cached. */
function ledger() {
  if (!ledgerModule) {
    ledgerModule = import("../plugins/timeline-lanes/lib/ledger.js").catch((error) => {
      ledgerModule = null;
      throw new Fail(503, "timeline/store", `the timeline store module is unavailable (${error?.code ?? error?.message})`);
    });
  }
  return ledgerModule;
}

// ── the harness: unary RPC ──────────────────────────────────────────────────────
async function rpc(method, args = {}, timeoutMs = 120000) {
  let r;
  try {
    r = await fetch(`${HARNESS}/api/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify({ type: "client-request", rpcId: randomUUID(), method, payload: { args } }),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new Fail(502, "harness/unreachable", `the harness is not answering (${e.code || e.name})`);
  }
  const text = await r.text();
  if (!r.ok) throw new Fail(502, `harness/http-${r.status}`, text.slice(0, 300));
  const res = JSON.parse(text).result || {};
  if (res.ok === false) {
    const code = res.error?.code || "harness/error";
    throw new Fail(/not-found/.test(code) ? 404 : /bad-request|invalid/.test(code) ? 400 : 502, code,
      res.error?.message || code);
  }
  return res.value;
}

// ── the harness: streams over the one WebSocket mux ─────────────────────────────
// `ws` is the harness's own dependency; it accepts request headers, which the browser WebSocket
// cannot — and the mux needs the Bearer on the upgrade. Resolved from the profile's store.
let WS;
try {
  WS = createRequire(`${PROFILE_DIR}/package.json`)("ws");
} catch {
  try { WS = createRequire(`${PROFILE_DIR}/node_modules/.pnpm/node_modules/ws/package.json`)("ws"); } catch { WS = undefined; }
}

class Mux {
  constructor() { this.socket = null; this.opening = null; this.streams = new Map(); }
  async socketReady() {
    if (this.socket && this.socket.readyState === 1) return this.socket;
    if (this.opening) return this.opening;
    if (!WS) throw new Fail(501, "stream/unavailable", "no WebSocket client in this image");
    this.opening = new Promise((resolve, reject) => {
      const s = new WS(HARNESS_WS, { headers: { authorization: `Bearer ${TOKEN}` } });
      const fail = (e) => { this.opening = null; reject(new Fail(502, "stream/connect", `mux connect failed (${e?.message || e})`)); };
      s.once("error", fail);
      s.once("open", () => {
        s.off("error", fail);
        s.on("message", (data) => this.onMessage(String(data)));
        s.on("close", () => { this.socket = null; this.failAll("mux closed"); });
        s.on("error", () => {});
        this.socket = s; this.opening = null; resolve(s);
      });
    });
    return this.opening;
  }
  onMessage(text) {
    let m; try { m = JSON.parse(text); } catch { return; }
    const st = this.streams.get(m.streamId);
    if (!st) return;
    if (m.type === "item") st.onItem(m.value);
    else if (m.type === "end") { this.streams.delete(m.streamId); st.onEnd(); }
    else if (m.type === "error") { this.streams.delete(m.streamId); st.onError(new Fail(502, m.error?.code || "stream/error", m.error?.message || "stream error")); }
  }
  failAll(reason) {
    for (const [id, st] of this.streams) { this.streams.delete(id); st.onError(new Fail(502, "stream/closed", reason)); }
  }
  /** Open one stream; returns {cancel}. Items/end/error are delivered to the handlers. */
  async open(endpoint, args, handlers) {
    const s = await this.socketReady();
    const streamId = randomUUID();
    this.streams.set(streamId, handlers);
    s.send(JSON.stringify({ type: "open", streamId, endpoint, payload: { args } }));
    return {
      cancel: () => {
        if (this.streams.delete(streamId) && s.readyState === 1) s.send(JSON.stringify({ type: "cancel", streamId }));
      },
    };
  }
}
const mux = new Mux();

// ── sessions ────────────────────────────────────────────────────────────────────
const summary = (s) => {
  const v = s.projections?.values || {};
  const goal = v.goal?.goal;
  return {
    id: s.sessionId,
    title: v.title || null,
    running: !!s.running,
    blank: !!s.blank,
    cwd: s.cwd || null,
    updated_at: s.updatedAt ? new Date(s.updatedAt).toISOString() : null,
    preset: v.agentPreset || null,
    permissions: v.permissions?.currentValue || null,
    model: v.modelSelection?.lastUsed || v.modelSelection?.next || null,
    goal: goal ? { objective: goal.objective, phase: goal.phase, rounds: v.goal.roundsStarted, max_rounds: goal.maxGoalRounds } : null,
    todos: v.todos || null,
    turns: (v.turnOutline || []).length,
    tokens: v.tokenUsage || null,
    queue: s.queueItems ? s.queueItems.length : (v.inbox?.["next-turn"]?.length || 0) + (v.inbox?.["next-step"]?.length || 0),
    stale: !!s.stale,
  };
};

// ── the live session model ───────────────────────────────────────────────────────
// `session/list` is the harness's most expensive call — it rebuilds every session's projections per
// call — and under load it is the one thing that never answers (measured 2026-09-30: >120 s while
// GET / answered in under a second). The control stream carries the same projections once, as a
// baseline, and then only their deltas; so the model here is kept current by push and every read is
// a memory lookup. The list still runs — once at start, then in the background on a slow cadence —
// for the fields the stream does not carry (running, cwd, blank, updatedAt); until it has answered
// for a session, that session reads `stale: true`.
const LIST_REFRESH_MS = 20000;
class Live {
  constructor() { this.items = new Map(); this.ready = false; this.stream = null; this.opening = null; this.listAt = 0; this.listPending = null; }
  ensure() {
    if (this.stream) return Promise.resolve();
    if (!this.opening) {
      this.opening = mux.open("session/control", {}, {
        onItem: (item) => this.apply(item),
        onEnd: () => this.reset(),
        onError: () => this.reset(),
      }).then((st) => { this.stream = st; }, () => {}).finally(() => { this.opening = null; });
    }
    return this.opening;
  }
  reset() { this.stream = null; this.ready = false; }
  entry(id) {
    let cur = this.items.get(id);
    if (!cur) { cur = { sessionId: id, projections: { asOfSeq: -1, values: {} }, stale: true }; this.items.set(id, cur); }
    return cur;
  }
  apply(item) {
    if (item.type === "baseline") {
      const v = item.value || {};
      for (const [id, proj] of Object.entries(v.projections || {})) this.mergeProjections(this.entry(id), proj);
      for (const [id, items] of Object.entries(v.queues || {})) this.entry(id).queueItems = items;
      for (const [id, jobs] of Object.entries(v.jobs || {})) this.entry(id).jobs = jobs;
      this.ready = true;
      this.refreshList();
    } else if (item.type === "projection") {
      const cur = this.entry(item.sessionId);
      cur.projections = { asOfSeq: item.seq, values: { ...cur.projections.values, [item.key]: item.value } };
      cur.updatedAt = Date.now();
    } else if (item.type === "queue") { this.entry(item.sessionId).queueItems = item.items; }
    else if (item.type === "jobs") { this.entry(item.sessionId).jobs = item.jobs; }
  }
  mergeProjections(cur, proj) {
    if (!proj) return;
    if ((proj.asOfSeq ?? 0) >= (cur.projections.asOfSeq ?? -1)) cur.projections = { asOfSeq: proj.asOfSeq ?? 0, values: { ...cur.projections.values, ...(proj.values || {}) } };
  }
  refreshList(force = false) {
    if (this.listPending) return this.listPending;
    if (!force && Date.now() - this.listAt < LIST_REFRESH_MS) return Promise.resolve();
    this.listPending = rpc("session/list", { _request: {} }, 600000).then((v) => {
      for (const s of v?.items || []) {
        const cur = this.entry(s.sessionId);
        Object.assign(cur, { running: s.running, blank: s.blank, cwd: s.cwd, updatedAt: s.updatedAt, stale: false });
        this.mergeProjections(cur, s.projections);
      }
      this.listAt = Date.now();
    }, () => {}).finally(() => { this.listPending = null; });
    return this.listPending;
  }
  async sessions(fresh = false) {
    await this.ensure();
    // `fresh` means "ask the harness now" and waits for one list. Otherwise the answer is what the
    // model holds RIGHT NOW: after the baseline that is every attached session with its
    // projections; cold sessions arrive when the background list finishes (`partial` says so).
    // Measured 2026-09-30 under the spin: the list took 100-240 s, the baseline ~110 s — an instant
    // partial answer is worth more than a timeout, and on a healthy harness both are sub-second.
    if (fresh) await this.refreshList(true);
    else if (!this.ready && !this.listAt) await this.refreshList(true); // no stream at all: the list is the only source
    else this.refreshList();
    return [...this.items.values()];
  }
  get partial() { return !this.listAt; }
}
const live = new Live();
const rawSessions = (fresh = false) => live.sessions(fresh);
async function listSessions(fresh) { return (await live.sessions(fresh)).map(summary); }

const FULL_ID = /^session-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

async function resolveId(idOrPrefix) {
  // A complete id needs no lookup: the harness validates it on use. Only a PREFIX costs a list —
  // and the list is the harness's most expensive call, so a busy engine must not tax every verb.
  if (FULL_ID.test(idOrPrefix)) return idOrPrefix;
  const items = await rawSessions();
  const exact = items.find((x) => x.sessionId === idOrPrefix);
  if (exact) return exact.sessionId;
  const hits = items.filter((x) => x.sessionId.startsWith(idOrPrefix) || x.sessionId.startsWith("session-" + idOrPrefix));
  if (hits.length === 1) return hits[0].sessionId;
  if (hits.length > 1) throw new Fail(409, "session/ambiguous", `${hits.length} sessions match "${idOrPrefix}": ${hits.map((h) => h.sessionId.slice(0, 16)).join(", ")}`);
  throw new Fail(404, "session/not-found", `no session ${idOrPrefix}`);
}

const address = (sessionId) => ({ kind: "session", sessionId });

async function prompt(id, text, files, steer) {
  const content = [];
  if (text && String(text).trim()) content.push({ type: "text", text: String(text) });
  for (const f of files || []) content.push(f.attachment.mediaType ? { type: "image", attachment: f.attachment } : { type: "file", attachment: f.attachment });
  if (!content.length) throw new Fail(400, "text", "text or files required");
  await rpc("session/prompt", { request: {
    requestId: randomUUID(), sessionId: id, mode: steer ? "steer" : "queue", content, clientTimeZone: TZ,
  } });
}

// ── event normalization ─────────────────────────────────────────────────────────
// The harness log is rich (assistant/message content blocks, tool/call, tool/result, step/*,
// turn/*, llm/retry, agent/inbox/spliced, approval/*, goal/change…). The contract answers a compact
// vocabulary a terminal can render; ?raw=1 passes the originals through untouched.
const blocksText = (blocks) => (blocks || []).map((b) => (typeof b === "string" ? b : b?.type === "text" ? b.text : b?.type === "image" ? `[image ${b.attachment?.name || ""}]` : b?.type === "file" ? `[file ${b.attachment?.name || ""}]` : "")).join("");
const parseArgs = (s) => { if (typeof s !== "string") return s; try { return JSON.parse(s); } catch { return s; } };

function normalize(ev) {
  const d = ev.data || {};
  const base = { seq: ev.seq, at: ev.time ? new Date(ev.time).toISOString() : null, turn: d.turn, step: d.step };
  const out = [];
  switch (ev.type) {
    case "turn/start": out.push({ ...base, type: "turn.start" }); break;
    case "turn/end": out.push({ ...base, type: "turn.end", reason: d.reason || d.outcome || null }); break;
    case "step/start": out.push({ ...base, type: "step.start" }); break;
    case "step/end": out.push({ ...base, type: "step.end" }); break;
    case "user/message": {
      // the text sits at data.content; data.source.kind says who wrote it — "user" (a person),
      // "plugin" (a background-job notice, a steer's carrier), "agent" (a subagent's hand-back)
      const c = d.content || d.message?.content || [];
      out.push({ ...base, type: "user", text: blocksText(c), source: d.source?.kind || null });
      break;
    }
    case "assistant/message": {
      for (const b of d.message?.content || []) {
        if (b.type === "reasoning" && b.text) out.push({ ...base, type: "reasoning", text: b.text });
        else if (b.type === "text" && b.text) out.push({ ...base, type: "assistant", text: b.text });
        else if (b.type === "tool-call") out.push({ ...base, type: "tool.call", id: b.id, name: b.name, args: parseArgs(b.arguments) });
      }
      break;
    }
    case "tool/call":
      if (d.name) out.push({ ...base, type: "tool.call", id: d.callId || d.id, name: d.name, args: parseArgs(d.arguments) });
      break;
    case "tool/result": {
      const m = d.message || d;
      const blocks = (m.content || []).flatMap((b) => (b?.type === "tool-result" ? b.content || [] : [b]));
      const isErr = (m.content || []).some((b) => b?.type === "tool-result" && b.isError) || !!d.isError;
      out.push({ ...base, type: "tool.result", id: m.source?.callId || d.callId || null, ok: !isErr, text: blocksText(blocks) });
      break;
    }
    case "llm/retry": out.push({ ...base, type: "retry", provider: d.provider, reason: d.reason || d.failure?.message || null }); break;
    case "llm/retry-started": out.push({ ...base, type: "retry.start", attempt: d.retry }); break;
    case "agent/inbox/spliced": {
      // inserted = a steer or queued message reached the agent; an empty splice is the inbox being
      // consumed at a step boundary — bookkeeping, not something a reader needs to see
      const txt = blocksText((d.inserted || []).flatMap((i) => i.content || []));
      if (txt) out.push({ ...base, type: "inbox", target: d.target, text: txt });
      break;
    }
    case "approval/asked": out.push({ ...base, type: "approval.asked", request: d }); break;
    case "approval/decided": out.push({ ...base, type: "approval.decided", decision: d.decision || d }); break;
    case "goal/change": out.push({ ...base, type: "goal", goal: d.goal || d }); break;
    case "session/title": out.push({ ...base, type: "title", title: d.title || d.value || null }); break;
    case "system/message": break; // the prompt scaffold; never rendered
    case "session-log-deepseek/delivery-accepted": break;
    default: if (ev.type === "session/not-found") out.push({ ...base, type: "error", code: ev.type }); break;
  }
  return out;
}

function normalizeFrame(frame) {
  // assistant-stream frames: live tokens before the durable assistant/message lands
  if (frame.type === "start") return [{ type: "attempt.start", turn: frame.turn, step: frame.step, attempt: frame.attemptId }];
  if (frame.type === "end") return [{ type: "attempt.end", attempt: frame.attemptId }];
  if (frame.type !== "chunk") return [];
  const c = frame.chunk || {};
  const t = c.type || "";
  const text = c.delta ?? c.text ?? c.textDelta ?? null;
  if (/reasoning/.test(t) && typeof text === "string") return [{ type: "delta", kind: "reasoning", text }];
  if (/text/.test(t) && typeof text === "string") return [{ type: "delta", kind: "text", text }];
  if (/tool/.test(t)) return [{ type: "delta", kind: "tool", name: c.name || c.toolName || null, text: typeof text === "string" ? text : "" }];
  if (t === "finish") return [{ type: "attempt.finish", reason: c.reason?.kind || c.reason || null, message: c.reason?.failure?.message || null }];
  return [];
}

// ── HTTP plumbing ───────────────────────────────────────────────────────────────
function authorized(req) {
  const h = req.headers.authorization || "";
  if (!h.startsWith("Bearer ")) return false;
  const a = Buffer.from(h.slice(7)), b = Buffer.from(TOKEN);
  return a.length === b.length && timingSafeEqual(a, b);
}
async function readBody(req, limit = 64 << 20) {
  const chunks = []; let n = 0;
  for await (const c of req) { n += c.length; if (n > limit) throw new Fail(413, "too-large", "body too large"); chunks.push(c); }
  return Buffer.concat(chunks);
}
async function jsonBody(req) {
  const b = await readBody(req, 8 << 20);
  if (!b.length) return {};
  try { return JSON.parse(b.toString("utf8")); } catch { throw new Fail(400, "bad-json", "body is not JSON"); }
}
function sse(res) {
  res.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store", connection: "keep-alive", "x-accel-buffering": "no" });
  res.write(":ok\n\n");
  const send = (type, data, id) => { res.write(`${id !== undefined ? `id: ${id}\n` : ""}event: ${type}\ndata: ${JSON.stringify(data)}\n\n`); };
  const keep = setInterval(() => { try { res.write(":ping\n\n"); } catch {} }, 15000);
  return { send, close: () => { clearInterval(keep); try { res.end(); } catch {} } };
}

// ── routes ──────────────────────────────────────────────────────────────────────
async function health(deep) {
  const t0 = Date.now();
  let harness = "down", ms = null;
  try {
    const r = await fetch(`${HARNESS}/`, { redirect: "manual", signal: AbortSignal.timeout(4000) });
    harness = r.status ? "up" : "down"; ms = Date.now() - t0;
  } catch { /* down */ }
  // The timeline lane reports itself here rather than through a second probe: an office that
  // cannot see the agent on כל מקביל should be able to ask this container why, in one GET.
  const timeline = await ledger().then((m) => m.ledgerStatus())
    .catch((e) => ({ available: false, reason: String(e?.code ?? e?.message ?? e) }));
  const out = { ok: harness === "up", provider: "bina-ds", version: VERSION, harness, harness_ms: ms, uptime_s: Math.round((Date.now() - STARTED) / 1000), stream: !!WS, timeline };
  if (deep && harness === "up") {
    const t1 = Date.now();
    try { const items = await live.sessions(true); out.sessions = items.filter((x) => !x.stale).length; out.list_ms = Date.now() - t1; out.live_model = live.ready; } catch (e) { out.ok = false; out.list_error = e.message; }
  }
  return out;
}

async function route(req, res) {
  const url = new URL(req.url, "http://x");
  const p = url.pathname.replace(/\/+$/, "") || "/";
  const q = url.searchParams;
  if (req.method === "GET" && p === "/v1/health") { const h = await health(q.get("deep") === "1"); return [h.ok ? 200 : 502, h]; }
  // ── the office timeline's lane (SPAN_SOURCE_BINA, apps/bina-ds/app.json) ─────────────────────
  // Deliberately outside the token gate, and read-only on purpose: an any-concurrency span source
  // is a bare GET — it holds no credential for any app, which is exactly how INDOX's lane is
  // served too (`apps/any-concurrency/docs/custom-sources.md`). The rows are the agent's
  // own activity with every excerpt bounded, it is reachable only from the office network and the
  // docker host's loopback, and it answers `history_from` so a window it cannot cover reads as
  // "the store starts here" rather than as silence.
  if (req.method === "GET" && (p === "/timeline/spans" || p === "/v1/timeline/spans")) {
    const limit = Math.max(1, Math.min(50000, Number(q.get("limit") || 20000)));
    const since = Number(q.get("since") || 0);
    const hours = Number(q.get("hours") || 0);
    const store = await ledger();
    return [200, await store.readSpans({ dir: store.ledgerDir(), ...(since > 0 ? { since } : hours > 0 ? { hours } : {}), limit })];
  }
  if (!authorized(req)) throw new Fail(401, "auth", "missing or wrong Bearer token");

  // ── collections
  if (req.method === "GET" && p === "/v1/sessions") return [200, { sessions: await listSessions(q.get("fresh") === "1"), partial: live.partial }];
  if (req.method === "POST" && p === "/v1/sessions") {
    const b = await jsonBody(req);
    const created = await rpc("session/create", { request: { cwd: b.cwd || OFFICE, ...(b.preset ? { agentPreset: b.preset } : {}) } });
    const id = created.sessionId;
    if (b.title) await rpc("session/rename", { request: { sessionId: id, title: String(b.title) } }).catch(() => {});
    if (b.text || (b.files && b.files.length)) await prompt(id, b.text, b.files, false);
    live.refreshList(true);
    return [201, { id, preset: created.agentPreset || null }];
  }
  if (req.method === "GET" && p === "/v1/models") return [200, await rpc("session/modelCatalog", {})];
  if (req.method === "GET" && p === "/v1/presets") return [200, await rpc("agentPresets/list", {})];
  if (req.method === "GET" && p === "/v1/permissions") return [200, await rpc("permissionPresets/catalog", {})];
  if (req.method === "GET" && p === "/v1/search") {
    const query = q.get("q") || "";
    if (!query) throw new Fail(400, "query", "q is required");
    return [200, await rpc("session/search", { request: { query } })];
  }
  if (req.method === "GET" && p === "/v1/watch") { await watch(res, q); return null; }

  // ── one session
  const m = p.match(/^\/v1\/sessions\/([A-Za-z0-9_.-]+)(?:\/([a-z]+))?(?:\/([a-z]+))?$/);
  if (!m) throw new Fail(404, "route", `no route ${req.method} ${p}`);
  const id = await resolveId(m[1]);
  const sub = m[2] || "", act = m[3] || "";

  if (!sub && req.method === "GET") {
    const s = (await listSessions(q.get("fresh") === "1")).find((x) => x.id === id);
    if (!s) throw new Fail(404, "session", `no session ${id}`);
    return [200, s];
  }
  if (sub === "messages" && req.method === "POST") {
    const b = await jsonBody(req);
    await prompt(id, b.text, b.files, !!b.steer);
    return [202, { accepted: true, id }];
  }
  if (sub === "messages" && req.method === "GET") {
    const limit = Math.max(1, Math.min(500, Number(q.get("limit") || 20)));
    const events = await snapshotEvents(id, limit);
    return [200, { id, has_more: false, events }];
  }
  if (sub === "events" && req.method === "GET") { await follow(res, id, q); return null; }
  if (sub === "cancel" && req.method === "POST") { await rpc("session/cancel", { request: { sessionId: id } }); return [202, { accepted: true, id }]; }
  if (sub === "rename" && req.method === "POST") {
    const b = await jsonBody(req);
    if (!b.title) throw new Fail(400, "title", "title is required");
    await rpc("session/rename", { request: { sessionId: id, title: String(b.title) } }); live.refreshList(true);
    return [200, { id, title: String(b.title) }];
  }
  if (sub === "fork" && req.method === "POST") {
    const b = await jsonBody(req);
    const v = await rpc("session/fork", { request: { sessionId: id, ...(b.at_seq !== undefined ? { atSeq: Number(b.at_seq) } : {}) } });
    live.refreshList(true);
    return [201, { id: v?.sessionId || v, forked_from: id }];
  }
  if (sub === "upload" && req.method === "POST") {
    const name = q.get("name") || "upload.bin";
    const body = await readBody(req);
    let r;
    try {
      r = await fetch(`${HARNESS}/api/session/uploadFileBinary?${new URLSearchParams({ sessionId: id, name })}`, {
        method: "POST", headers: { "content-type": "application/octet-stream", authorization: `Bearer ${TOKEN}` }, body,
      });
    } catch (e) { throw new Fail(502, "harness/unreachable", `upload failed (${e.code || e.name})`); }
    const j = JSON.parse(await r.text());
    if (j.ok === false) throw new Fail(400, j.error?.code || "upload", j.error?.message || "upload rejected");
    return [201, { id, receipt: j.value?.receiptId, attachment: j.value?.file }];
  }
  if (sub === "command" && req.method === "POST") {
    const b = await jsonBody(req);
    if (!b.line || !String(b.line).startsWith("/")) throw new Fail(400, "line", "line must start with /");
    const v = await rpc("commands/execute", { agentId: id, line: String(b.line), submittedAttachments: (b.receipts || []).map((r) => ({ type: "file", receiptId: r })) });
    return [200, { id, result: v === undefined ? null : v }];
  }
  if (sub === "commands" && req.method === "GET") return [200, { id, commands: await rpc("commands/list", { agentId: id }) }];
  if (sub === "model" && req.method === "POST") {
    const b = await jsonBody(req);
    if (!b.provider || !b.model) throw new Fail(400, "model", "provider and model are required");
    await rpc("session/selectModel", { request: { sessionId: id, provider: b.provider, model: b.model, ...(b.effort ? { reasoningEffort: b.effort } : {}) } });
    live.refreshList(true);
    return [200, { id, provider: b.provider, model: b.model, effort: b.effort || null }];
  }
  if (sub === "preset" && req.method === "POST") {
    const b = await jsonBody(req);
    if (!b.preset) throw new Fail(400, "preset", "preset is required");
    await rpc("agentPresets/select", { agentId: id, agentPreset: String(b.preset) }); live.refreshList(true);
    return [200, { id, preset: b.preset }];
  }
  if (sub === "subagents" && req.method === "GET") return [200, { id, subagents: await rpc("subagents/list", { parentSessionId: id }) }];
  if (sub === "goal") {
    if (req.method === "GET") return [200, { id, goal: (await rpc("goals/get", { agentId: id })) ?? null }];
    if (req.method === "POST" && !act) {
      const b = await jsonBody(req);
      if (!b.objective) throw new Fail(400, "objective", "objective is required");
      return [201, { id, goal: await rpc("goals/create", { agentId: id, request: { objective: String(b.objective), ...(b.max_rounds ? { maxGoalRounds: Number(b.max_rounds) } : {}) } }) }];
    }
    if (req.method === "POST" && ["pause", "resume", "clear", "complete"].includes(act)) {
      const g = await rpc("goals/get", { agentId: id });
      if (!g) throw new Fail(404, "goal", "this session has no goal");
      return [200, { id, goal: await rpc(`goals/${act}`, { agentId: id, ref: { id: g.id, revision: g.revision } }) }];
    }
  }
  throw new Fail(404, "route", `no route ${req.method} ${p}`);
}

// live events of one session → SSE
async function follow(res, id, q) {
  const raw = q.get("raw") === "1";
  const since = Number(q.get("since") || -1);
  const history = Math.max(0, Math.min(500, Number(q.get("history") || 0)));
  const out = sse(res);
  let stream;
  const done = () => { stream?.cancel(); out.close(); };
  res.on("close", done);
  try {
    stream = await mux.open("session/follow", { request: { address: address(id), maxMessages: history, assistantStream: true } }, {
      onItem: (item) => {
        if (raw) { out.send("raw", item, item.event?.seq); return; }
        if (item.type === "event" && item.event) {
          if (item.event.seq <= since) return;
          for (const e of normalize(item.event)) out.send(e.type, e, item.event.seq);
        } else if (item.type === "snapshot") {
          // the history the follow request asked for: {header, cursor, records:[{type:"event", event}]}
          const evs = (item.records || []).flatMap((r) => (r.type === "event" && r.event && r.event.seq > since ? normalize(r.event) : []));
          out.send("snapshot", { id, header: item.header || null, cursor: item.cursor ?? null, events: evs });
        } else if (item.type === "assistant-stream" && item.frame) {
          for (const e of normalizeFrame(item.frame)) out.send(e.type, e);
        }
      },
      onEnd: () => { out.send("end", { id }); out.close(); },
      onError: (e) => { out.send("error", { code: e.code, message: e.message }); out.close(); },
    });
    out.send("open", { id, since, history, raw, stream: true });
  } catch (e) {
    out.send("error", { code: e.code || "stream", message: e.message }); out.close();
  }
}

// One page of history = the opening snapshot of a follow, cancelled the moment it arrives. The harness
// pages a log only against a cursor its follow frame hands out (SessionPageRequest.throughSeq is
// "obtained from the corresponding follow opening frame"; -1 is the empty cut — measured 2026-09-30:
// `session/page` with throughSeq -1 answers zero records, always), so the stream is the one source
// that is consistent by construction, and it costs the same one round trip.
function snapshotEvents(id, history) {
  return new Promise((resolve, reject) => {
    let stream = null, settled = false;
    const finish = (fn, v) => { if (settled) return; settled = true; clearTimeout(timer); try { stream?.cancel(); } catch {} fn(v); };
    const timer = setTimeout(() => finish(reject, new Fail(504, "snapshot/timeout", "the harness sent no history within 60s")), 60000);
    mux.open("session/follow", { request: { address: address(id), maxMessages: history, assistantStream: false } }, {
      onItem: (item) => {
        if (item.type !== "snapshot") return;
        finish(resolve, (item.records || []).flatMap((r) => (r.type === "event" && r.event ? normalize(r.event) : [])));
      },
      onEnd: () => finish(resolve, []),
      onError: (e) => finish(reject, new Fail(/not-found/.test(e.code || "") ? 404 : 502, e.code || "stream", e.message)),
    }).then((s) => { stream = s; if (settled) { try { s.cancel(); } catch {} } }, (e) => finish(reject, e));
  });
}

// every session, live → SSE (the harness's control stream: baseline, then queue/jobs/projection deltas)
async function watch(res, q) {
  const out = sse(res);
  let stream;
  const done = () => { stream?.cancel(); out.close(); };
  res.on("close", done);
  try {
    stream = await mux.open("session/control", {}, {
      onItem: async (item) => {
        if (item.type === "baseline") {
          let sessions = [];
          try { sessions = await listSessions(false); } catch {}
          out.send("baseline", { sessions, queues: item.value?.queues || {}, jobs: item.value?.jobs || {} });
        } else if (item.type === "projection") {
          out.send("update", { id: item.sessionId, key: item.key, value: item.value, seq: item.seq });
        } else if (item.type === "queue") {
          out.send("queue", { id: item.sessionId, items: item.items });
        } else if (item.type === "jobs") {
          out.send("jobs", { id: item.sessionId, jobs: item.jobs });
        }
      },
      onEnd: () => { out.send("end", {}); out.close(); },
      onError: (e) => { out.send("error", { code: e.code, message: e.message }); out.close(); },
    });
  } catch (e) { out.send("error", { code: e.code || "stream", message: e.message }); out.close(); }
}

createServer(async (req, res) => {
  let status, payload;
  try {
    const r = await route(req, res);
    if (r === null) return; // streaming route owns the response
    [status, payload] = r;
  } catch (e) {
    status = e instanceof Fail ? e.status : 500;
    payload = { error: e.message, code: e.code || "internal" };
    if (status === 500) console.error("adapter:", e);
  }
  if (res.headersSent) return;
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(payload));
}).listen(PORT, "0.0.0.0", () => console.log(`bina-ds adapter: ${VERSION} + the timeline lane on :${PORT} (stream: ${WS ? "ws" : "unavailable"})`));
