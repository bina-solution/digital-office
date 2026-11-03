// agent.mjs — the DGO benchmark's runner (DGO-949). Runs INSIDE a bina-ds container (its token, its harness
// on loopback), piped in on stdin by `bbox ops bench`, the cases in BENCH_CASES_JSON (the checkout is not
// mounted at the same path in every office):
//   node --input-type=module - <provider> <model> [<case-id>…]
// For each case: a new session with the «עזריה · מקומי» preset on <provider>/<model>, the request sent,
// the session's events read until its turn ends, then the case's checks on the commands it ran and its
// last answer. A turn still running at BENCH_TURN_S is cancelled and its end waited for, so the next case
// does not queue behind it on the same model. Selecting a session's model also rewrites the office's
// default model (agent-default-model in settings.yaml), so the default is read just before and put back
// just after. One JSON line per case, then a summary line.
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";

const HOME = process.env.DSH_HOME || "/data/dsh";
const TOKEN = fs.readFileSync(path.join(HOME, "api-token"), "utf8").trim();
const H = `http://127.0.0.1:${process.env.DSH_PORT || 3080}`;
const A = `http://127.0.0.1:${process.env.BINA_DS_ADAPTER_PORT || 3081}`;
const AUTH = { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" };
const PRESET = process.env.BENCH_PRESET || "azaria-local";
const TURN_S = Number(process.env.BENCH_TURN_S || 900);
const CANCEL_S = 120;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function rpc(method, args) {
  const r = await fetch(`${H}/api/${method}`, { method: "POST", headers: AUTH,
    body: JSON.stringify({ type: "client-request", rpcId: randomUUID(), method, payload: { args } }) });
  const t = await r.text();
  if (!r.ok) throw new Error(`${method} → ${r.status} ${t.slice(0, 200)}`);
  const j = JSON.parse(t);
  if (j.error) throw new Error(`${method} → ${JSON.stringify(j.error).slice(0, 200)}`);
  return j.result;
}
async function api(method, p, body) {
  const r = await fetch(`${A}${p}`, { method, headers: AUTH, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  if (!r.ok) throw new Error(`${method} ${p} → ${r.status} ${t.slice(0, 200)}`);
  return t ? JSON.parse(t) : {};
}

// ── the office's default model: read before, put back after (the harness's own yaml, its lock) ────────
const SETTINGS = path.join(HOME, "settings.yaml");
function yamlLib() {
  const P = "/opt/bina/harness/profile/node_modules/.pnpm";
  const d = fs.readdirSync(P).find((x) => x.startsWith("@deepseek-ai+dsh-settings-file@"));
  return createRequire(path.join(P, d, "node_modules/@deepseek-ai/dsh-settings-file/package.json"))("yaml");
}
const YAML = yamlLib();
const readDefault = () => (YAML.parse(fs.readFileSync(SETTINGS, "utf8")) || {})["agent-default-model"] || null;

// The lock this process holds, if any: a stop arriving inside the few milliseconds of an edit gives it
// back, rather than leaving the harness a lock nobody owns (the relay's edit() does the same).
let held = null;
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => { if (held) fs.rmSync(held, { force: true }); process.exit(130); });
}

// Put `before` back as the office's default (none → no key), the way the harness writes the file: under
// its `.lock` sibling, a comment-preserving edit, renamed into place, mode 0600. Only while the file still
// holds what this run selected: a default someone chose in the meantime is theirs. Answers what went
// wrong, or null.
function putBack(before, provider, model) {
  const lock = `${SETTINGS}.lock`;
  const deadline = Date.now() + 5000;
  let fd = null;
  for (let wait = 25; fd === null; wait = Math.min(wait * 2, 400)) {
    try { fd = fs.openSync(lock, "wx"); held = lock; } catch (e) {
      if (e.code !== "EEXIST" || Date.now() > deadline) return `the lock was not taken (${e.code})`;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, wait);
    }
  }
  try {
    const doc = YAML.parseDocument(fs.readFileSync(SETTINGS, "utf8"));
    if (doc.errors.length) return `settings.yaml does not parse (${doc.errors[0].code})`;
    const now = (doc.toJS() || {})["agent-default-model"] || {};
    if (now.provider !== provider || now.model !== model) return null;
    if (before) doc.setIn(["agent-default-model"], doc.createNode(before));
    else doc.deleteIn(["agent-default-model"]);
    const tmp = `${SETTINGS}.bench.${process.pid}`;
    fs.writeFileSync(tmp, String(doc), { mode: 0o600 });
    fs.renameSync(tmp, SETTINGS);
    return null;
  } finally {
    fs.closeSync(fd);
    fs.rmSync(lock, { force: true });
    held = null;
  }
}

// ── one case ──────────────────────────────────────────────────────────────────────────────────────────
// ── nobody else on the agent ─────────────────────────────────────────────────────────────────────
// A case is a real session on the office's model. Beside a person's own session, it competes with him
// for that model and his answer waits: a run on 2026-10-21 21:32–21:50 UTC overlapped the owner's own
// testing. So before each case the agent's sessions are read. If one that is not the benchmark's is
// running, or was touched in the last BENCH_IDLE_S (600 s), the run waits, looking every 30 s, for at
// most BENCH_WAIT_S (1800 s); then it stops, naming the session it waited for.
// Not counted:
// - a session on another provider, which does not compete for this model (a DeepSeek goal session
//   runs almost always);
// - the session this runs in, when an agent runs the benchmark as a tool call (BENCH_IGNORE, by
//   default its DSH_SESSION_ID);
// - the sessions this run made itself, even untitled.
// A list the adapter has only partly read yet counts as in use.
const TITLE = "בנצ'מרק DGO — ";
const seconds = (v, d) => { const n = Number(v); return v !== undefined && v !== "" && Number.isFinite(n) && n >= 0 ? n : d; };
const IDLE_S = seconds(process.env.BENCH_IDLE_S, 600);
const WAIT_S = seconds(process.env.BENCH_WAIT_S, 1800);
const mine = new Set(String(process.env.BENCH_IGNORE || "").split(/[\s,]+/).filter(Boolean));
async function busy(provider) {
  const now = Date.now();
  const d = await api("GET", "/v1/sessions");
  if (d.partial) return [{ title: "(the agent's session list is still being read)", running: true }];
  return (d.sessions || []).filter((s) => s && !mine.has(s.id) && !String(s.title || "").startsWith(TITLE)
    && !(s.model && s.model.provider && s.model.provider !== provider)
    && (s.running || now - (Date.parse(s.updated_at || 0) || 0) < IDLE_S * 1000));
}
// → null when the agent is free, or why the run stops
async function quiet(provider) {
  for (const until = Date.now() + WAIT_S * 1000; ;) {
    let them;
    try { them = await busy(provider); } catch (e) { return `the agent's session list did not answer (${e.message})`; }
    if (!them.length) return null;
    const who = them.map((s) => `«${String(s.title || s.id).slice(0, 60)}»${s.running ? " (running)" : ""}`).join(", ");
    if (Date.now() >= until) return `the agent was still in use after ${WAIT_S} s: ${who}`;
    console.error(`[bench] waiting: the agent is in use — ${who}`);
    await sleep(30000);
  }
}

function walk(o, key, out = []) {
  if (Array.isArray(o)) o.forEach((x) => walk(x, key, out));
  else if (o && typeof o === "object") for (const [k, v] of Object.entries(o)) (k === key ? out.push(v) : walk(v, key, out));
  return out;
}
async function runCase(provider, model, c, never = []) {
  const t0 = Date.now();
  const { id } = await api("POST", "/v1/sessions", { title: `${TITLE}${c.id} (${model})`, preset: PRESET });
  mine.add(id);
  const before = readDefault();
  let lost = null;
  try { await rpc("session/selectModel", { request: { sessionId: id, provider, model } }); }
  finally { lost = putBack(before, provider, model); }
  if (lost) {
    throw Object.assign(new Error(`the office's default model was NOT put back (${lost}): it is ${provider}/${model}, `
      + `it was ${JSON.stringify(before)}`), { fatal: true });
  }
  const tp = Date.now();
  await api("POST", `/v1/sessions/${id}/messages`, { text: c.request });
  const seen = new Set();
  const calls = new Map();
  let end = null, first = null, answer = "";
  async function read() {
    const ask = (n) => rpc("session/page", { request: { address: { kind: "session", sessionId: id }, throughSeq: n } });
    let page = await ask(1e9);
    const m = !page.ok && /past cursor (\d+)/.exec((page.error && page.error.message) || "");
    if (m) page = await ask(Number(m[1]));
    for (const rec of ((page.value || {}).records) || []) {
      const e = rec.event || {};
      const d = e.data || {};
      if (seen.has(e.seq)) continue;
      seen.add(e.seq);
      if (e.type === "tool/call") {
        if (first === null) first = (e.time - tp) / 1000;
        let a = d.arguments;
        try { a = typeof a === "string" ? JSON.parse(a) : a; } catch { a = null; }
        if (a && typeof a.command === "string") calls.set(d.callId, { command: a.command, ok: false });
      }
      // A command counts as run only when it worked: no tool error, no `[exit code: N]` (what the harness
      // appends to a command that failed), and something printed.
      if (e.type === "tool/result") {
        for (const p of (d.message || {}).content || []) {
          const call = calls.get(p.toolCallId);
          if (!call) continue;
          const text = walk(p.content || [], "text").join("\n").trim();
          call.ok = !p.isError && !/\[exit code: (?!0\])[^\]]*\]$/.test(text) && text !== "" && text !== "(no output)";
        }
      }
      if (e.type === "assistant/message") {
        // the answer is its `text` parts: a thinking model's `reasoning` part carries a text too
        const parts = ((d.message || {}).content || []).filter((p) => p && p.type === "text");
        const texts = walk(parts, "text").filter((x) => typeof x === "string" && x.trim());
        if (texts.length) answer = texts.join("\n");
        if (first === null) first = (e.time - tp) / 1000;
      }
      if (e.type === "turn/end") end = d.reason || { kind: "unknown" };
    }
  }
  while (!end && Date.now() - tp < TURN_S * 1000) {
    await sleep(3000);
    await read();
  }
  const total = Date.now() - tp;
  const timedOut = !end;
  if (timedOut) {
    await fetch(`${A}/v1/sessions/${id}/cancel`, { method: "POST", headers: { authorization: AUTH.authorization } })
      .catch(() => null);
    for (const until = Date.now() + CANCEL_S * 1000; !end && Date.now() < until;) {
      await sleep(3000);
      await read();
    }
  }
  const ran = [...calls.values()];
  const missing = (c.ran || []).filter((x) => !ran.some((k) => k.ok && k.command.includes(x)));
  // what no case may run (`never`, a mail sent, an item closed…) unless the case itself asks for it
  const banned = (c.not_ran || []).concat(never.filter((x) => !(c.ran || []).some((r) => r.includes(x))));
  const forbidden = banned.filter((x) => ran.some((k) => k.command.includes(x)));
  const noAnswer = c.answer_has && !answer.includes(c.answer_has);
  const kind = timedOut ? "TIMEOUT" : end.kind;
  const pass = kind === "completed" && !missing.length && !forbidden.length && !noAnswer && answer.trim().length > 0;
  return { case: c.id, pass, session: id, model, first_s: first === null ? null : Math.round(first * 10) / 10,
           total_s: Math.round(total / 100) / 10, setup_s: Math.round((tp - t0) / 100) / 10,
           end: kind, cancelled_end: timedOut ? (end ? end.kind : "still running") : undefined,
           commands: ran.map((k) => k.command), failed: ran.filter((k) => !k.ok).map((k) => k.command),
           missing, forbidden, answer: answer.slice(0, 400) };
}

const [provider, model, ...only] = process.argv.slice(2);
if (!provider || !model || !process.env.BENCH_CASES_JSON) {
  console.error("usage: BENCH_CASES_JSON='{\"cases\":[…]}' agent.mjs <provider> <model> [<case-id>…]");
  process.exit(2);
}
const doc = JSON.parse(process.env.BENCH_CASES_JSON);
const cases = doc.cases.filter((c) => !only.length || only.includes(c.id));
// BENCH_TIMES=k runs each case k times: τ²-bench's pass^k, a case that passes all k (MAPPING.md)
const TIMES = Math.max(1, Math.min(10, Math.floor(Number(process.env.BENCH_TIMES) || 1)));
const results = [];
const allPassed = [];                 // the cases every try of which passed
let finished = 0;                     // the cases all of whose tries ran (a stop can cut one short)
let stopped = null;
run: for (const c of cases) {
  let every = true;
  for (let i = 1; i <= TIMES; i++) {
    stopped = await quiet(provider);
    if (stopped) break run;
    let r;
    try { r = await runCase(provider, model, c, doc.never || []); }
    catch (e) { r = { case: c.id, pass: false, model, error: String(e.message || e).slice(0, 300), fatal: e.fatal || undefined }; }
    if (TIMES > 1) r.try = i;
    results.push(r);
    console.log(JSON.stringify(r));
    if (r.fatal) { console.error(`[bench] stopped: ${r.error}`); process.exit(1); }
    every = every && r.pass;
  }
  finished += 1;
  if (every) allPassed.push(c.id);
}
if (stopped) console.error(`[bench] stopped: ${stopped}`);
const passed = results.filter((r) => r.pass).length;
const firsts = results.map((r) => r.first_s).filter((x) => typeof x === "number").sort((a, b) => a - b);
const median = firsts.length ? firsts[Math.floor(firsts.length / 2)] : null;
console.log(JSON.stringify({ summary: true, provider, model, passed, of: results.length, median_first_s: median,
                             timeouts: results.filter((r) => r.end === "TIMEOUT").length,
                             total_s: Math.round(results.reduce((s, r) => s + (r.total_s || 0), 0)),
                             ...(TIMES > 1 ? { times: TIMES, cases: finished, pass_k: allPassed.length } : {}),
                             ...(stopped ? { stopped } : {}) }));
if (stopped) process.exit(3);
