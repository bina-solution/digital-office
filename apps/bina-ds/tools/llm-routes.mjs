#!/usr/bin/env node
// llm-routes.mjs — every Ollama this office can reach becomes a model route of the agent (DGO-825).
//
// The harness mounts its pi-ai adapter DORMANT: it has no routes until a `llm-pi-ai:` section in
// $DSH_HOME/settings.yaml declares them, and it re-reads that section once per operation. So a route
// written here is in the model picker on the next request, beside DeepSeek, with no restart, and it
// leaves again when its Ollama does. Choosing it stays a person's act: a route is offered, never used
// until a session selects it.
//
// WHERE THE OLLAMAS COME FROM — the compiled registry, never a list kept here:
//   · this office's own `ollama` app, when it is enabled (office.apps.json) → http://ollama:11434,
//     route `dgo-ollama-local`;
//   · every PAIRED office's `ollama` app (`remote.<office>.<alias>.json`, written from the peer's
//     catalog) → http://<alias>.<office>:<link_port>, the door of that app on the link (the app's own
//     port is not where the alias answers), route `dgo-ollama-<office>`. Named by the office id this
//     office paired with, never by a label the peer chose for itself.
// Each one is asked for its models (`/api/tags`), and a model is offered only when Ollama says it can
// call tools (`/api/show` → capabilities), because the agent cannot work without them.
//
// WHAT IT OWNS: routes whose name starts with `dgo-ollama-`. Every other route, and every other
// section of settings.yaml, is the owner's, and it is never read for anything but to be kept.
// And one credential reference, DGO_OLLAMA_KEY: pi-ai refuses a route with no key ("No API key for
// provider", measured on the Dell 2026-10-21) while Ollama ignores the one it is sent, so each route
// names `apiKeyEnv: DGO_OLLAMA_KEY` and the harness's own credentials document gets that one
// placeholder (`refs.DGO_OLLAMA_KEY: ollama`) when it is missing. Nothing else in that file is touched.
// The documents are written the way the harness writes them: under their `<file>.lock` sibling
// (O_EXCL, at most 2 s), as a comment-preserving YAML edit, renamed into place, mode 0600. settings.yaml
// is never CREATED here: until the harness has written it, there is nothing to add to.
// An Ollama that stops answering keeps its route for KEEP_S (its last models, in STATE), and a route
// that agent-default-model names is never removed, so a silent minute does not break the sessions
// that run on it.
//
//   node llm-routes.mjs --once [--dry-run]     one pass; --dry-run prints the section, writes nothing
//   node llm-routes.mjs --loop 60              a pass every 60 s (the bina-ds-llm-routes container)
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { pipeline, Transform } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";

const HOME = process.env.DSH_HOME || "/data/dsh";
const SETTINGS = path.join(HOME, "settings.yaml");
const CREDENTIALS = path.join(HOME, ".credentials.yaml");
const STATE = path.join(HOME, "llm-routes.json");
const OFFICE = process.env.OFFICE_ROOT || "/workspace/office";
const REGISTRY = path.join(OFFICE, ".generated", "registry");
const PREFIX = "dgo-ollama-";
const KEY_REF = "DGO_OLLAMA_KEY";
const KEEP_S = Number(process.env.LLM_ROUTES_KEEP_S || 1800);
// The most context a route declares. The ollama app runs with OLLAMA_CONTEXT_LENGTH=32768 unless its
// office sets less; less is read from the Ollama itself (see `served`), so no office has to repeat it.
const CONTEXT_CAP = Math.max(2048, Number(process.env.LLM_ROUTES_CONTEXT || 32768) || 32768);
// How long a route's stream may stay silent before pi-ai gives up (its default is 300 s). A CPU reads
// the whole prompt before it sends the first token: measured on the Dell (i7-5500U, 2026-10-21),
// qwen3.5:2b reads 15.7 tokens/s cold and qwen3.5:4b 6.2, so the full Azaria preset's first turn
// (some 15k tokens) is silent for 15–40 minutes. The owner's first local session ended on six 300-s
// timeouts in a row (01:16–01:47 UTC). 45 minutes covers a whole 32k context read on that machine.
// The same number is the route's whole-request timeout (`timeoutMs`, the client's own): unset, a
// request whose answer had not begun after 300 s ended "Request timed out." (the HP asking the Dell's
// Ollama over the link, a cold 3.5k-token prompt, 03:42 UTC).
const IDLE_MS = 45 * 60 * 1000;
const MAX_MODELS = 20;          // per Ollama, per pass
const PASS_S = 45;              // a whole pass, every Ollama together
const PROFILE = "/opt/bina/harness/profile/node_modules/.pnpm";
const args = process.argv.slice(2);
const DRY = args.includes("--dry-run");
const RELAYED = args.includes("--loop");      // only the service relays; --once writes direct URLs

// The YAML library the harness's own settings provider uses, from where pnpm put it.
function loadYaml() {
  for (const d of fs.existsSync(PROFILE) ? fs.readdirSync(PROFILE) : []) {
    if (!d.startsWith("@deepseek-ai+dsh-settings-file@")) continue;
    const pkg = path.join(PROFILE, d, "node_modules", "@deepseek-ai", "dsh-settings-file", "package.json");
    try { return createRequire(pkg)("yaml"); } catch { /* next */ }
  }
  return createRequire(import.meta.url)("yaml");
}
const YAML = loadYaml();

const log = (...a) => console.log(`[llm-routes] ${new Date().toISOString()}`, ...a);
const readJson = (f, dflt) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return dflt; } };

// ── the relay between the agent and an Ollama ───────────────────────────────────────────────────
// Every route's baseURL is this process (`http://bina-ds-llm-routes-<office>:11435/<route>/v1`), not
// the Ollama itself. Ollama sends its response headers with the first token, and a CPU reads the
// whole prompt first; the harness's fetch (Node's undici) gives up on headers after 300 s, whatever
// the route's own timeouts say: measured 2026-10-21 03:47 and 03:56 UTC, the HP asking the Dell's
// Ollama over the link, "Request timed out." at 300.7 s while the prompt was read in 288.8 s. So a
// response is passed through as Ollama gives it, status and headers included, unless a STREAMED
// request has had no answer for 20 s: then the relay answers it itself (200, text/event-stream), keeps
// it warm with an SSE comment every 15 s, and passes the model's stream through once it begins; an
// error Ollama gives after that point comes back as an SSE `error` event, which the client raises.
// An upstream that dies mid-answer ends the client's response at once (stream.pipeline), so a session
// fails and retries rather than waiting out its timeout. The client going away cancels the upstream
// request, so Ollama stops the work too. Only the `--loop` service relays (`--once` writes direct
// URLs); a relay that cannot listen ends the process, so the container restarts.
const RELAY_PORT = 11435;
const RELAY_HOST = `bina-ds-llm-routes-${process.env.DEPLOYMENT_NAME || "bina-deployment"}`;
const EARLY_MS = 20000;
const KEEPALIVE_MS = 15000;
const MAX_BODY = 16 * 1024 * 1024;
const TEMPERATURE = 0.3;             // for a chat request that names none (see the relay)
const LABELLED = new Set(["bash"]);  // tools whose required `description` is only a UI label (labeller)
// hop-by-hop headers, and compression: a relayed body is passed through byte for byte
const HOP = new Set(["connection", "keep-alive", "proxy-connection", "transfer-encoding", "te", "trailer",
                     "upgrade", "accept-encoding", "host", "content-length"]);
const upstream = new Map();          // route → its Ollama's base URL: from the saved state at start, then every pass

// A tool whose schema REQUIRES `description` (the harness's bash: a 5–10 word label for the UI) is
// refused when a small model leaves it out, and gemma4:e2b did, in five of seven calls (2026-10-21
// 04:06–04:58 UTC), each time ending the errand. The label is not the command, so the relay supplies
// it from the call's own first string argument when the model did not. Ollama sends each tool call
// whole in one chunk; a call whose arguments do not parse as JSON is passed as it is.
//
// The same tool's command is killed at the harness's default of 60 s when the call names no
// `timeoutMs`, and a small model never names one: `bbox b42 shot` on a browser waking from its sleep
// took 65 s and was killed (2026-10-21 10:42 UTC), and one such turn costs the owner minutes. So a call
// to such a tool that names none gets TIMEOUT_MS (or the schema's own maximum, if lower), the same way.
const TIMEOUT_MS = 180000;
function labeller(requestJson) {
  // Only where `description` is a label: the harness's bash tool. Another tool's required
  // `description` may be real content (an item's text), and inventing it would hide the refusal.
  const label = new Set(), timed = new Map();
  for (const t of (requestJson && requestJson.tools) || []) {
    const f = t && t.function, p = f && f.parameters;
    if (!f || !LABELLED.has(f.name) || !p) continue;
    if (Array.isArray(p.required) && p.required.includes("description")) label.add(f.name);
    const most = p.properties && p.properties.timeoutMs && Number(p.properties.timeoutMs.maximum);
    if (p.properties && p.properties.timeoutMs) timed.set(f.name, most > 0 ? Math.min(TIMEOUT_MS, most) : TIMEOUT_MS);
  }
  if (!label.size && !timed.size) return null;
  const fix = (call) => {
    const f = call && call.function;
    if (!f || !(label.has(f.name) || timed.has(f.name)) || typeof f.arguments !== "string") return false;
    let a; try { a = JSON.parse(f.arguments); } catch { return false; }
    if (!a || typeof a !== "object" || Array.isArray(a)) return false;
    let changed = false;
    if (label.has(f.name) && !(typeof a.description === "string" && a.description.trim())) {
      const first = Object.values(a).find((v) => typeof v === "string" && v.trim()) || f.name;
      a.description = `Run: ${Array.from(first.replace(/\s+/g, " ").trim()).slice(0, 60).join("")}`;
      changed = true;
    }
    if (timed.has(f.name) && a.timeoutMs === undefined) { a.timeoutMs = timed.get(f.name); changed = true; }
    if (changed) f.arguments = JSON.stringify(a);
    return changed;
  };
  const fixDoc = (doc) => {
    let changed = false;
    for (const c of (doc && doc.choices) || []) {
      for (const call of ((c.delta && c.delta.tool_calls) || []).concat((c.message && c.message.tool_calls) || [])) changed = fix(call) || changed;
    }
    return changed;
  };
  return { fixDoc };
}

// ── a tool call written as text ─────────────────────────────────────────────────────────────────
// A small model sometimes writes its call as the answer instead of making it: asked «איזה כלים יש לך?»
// with the recipe `./bbox ops list` in hand, gemma4:e2b answered `{"command": "bbox ops list",
// "description": "List the office's operatives"}` — the bash tool's own arguments, as text — and the
// errand ended there (DGO-948, 2026-10-21 23:10 UTC). So an answer that is ONE JSON object and nothing
// else, and that is a call, goes back as that call: `{"name": <tool>, "arguments" | "parameters": {…}}`
// naming one of the request's tools, or the bare arguments of the bash tool (each key one of its
// parameters, every parameter it requires there: its UI label aside, which the labeller supplies). Bare
// arguments are read as bash's alone, the one case seen: a JSON document someone asked for (`{"path": …,
// "content": …}`) could otherwise fit a file tool. Anything more is text, as it was: a word around the
// object, a code fence, two objects, a key the tool does not have. So is a call this TURN already made
// and that worked, with every argument the same (the label aside): a small model that writes its last
// call again as its answer is reporting it, and running it again could send a second mail. An earlier
// turn's call is no such echo — the person may well ask for the same errand again — and a call that
// failed may be tried again. A call then runs through the harness like every call, so nothing runs
// that the model could not have called itself.
const CALL_TEXT_MOST = 8192;          // a longer answer is not held back: it is no call
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const isObject = (v) => Boolean(v) && typeof v === "object" && !Array.isArray(v);
function textCall(requestJson) {
  const tools = new Map();
  for (const t of (requestJson && requestJson.tools) || []) {
    const f = t && t.function;
    if (f && typeof f.name === "string") tools.set(f.name, isObject(f.parameters) ? f.parameters : {});
  }
  if (!tools.size) return null;
  const added = (name, k) => LABELLED.has(name) && (k === "description" || k === "timeoutMs");   // the labeller's
  // the calls this turn made that worked — since the person's last message (the harness's runtime note
  // is none), whose result does not end in a failed exit code: [tool, arguments]
  const msgs = Array.isArray(requestJson && requestJson.messages) ? requestJson.messages : [];
  let from = 0;
  msgs.forEach((m, i) => { if (m && m.role === "user" && !textOf(m).trim().startsWith("Current runtime context")) from = i + 1; });
  const failed = new Set(msgs.filter((m) => m && m.role === "tool" && /\[exit code: (?!0\])[^\]]*\]\s*$/.test(textOf(m)))
    .map((m) => m.tool_call_id));
  const made = [];
  for (const m of msgs.slice(from)) {
    for (const c of (m && m.role === "assistant" && Array.isArray(m.tool_calls) ? m.tool_calls : [])) {
      const f = c && c.function;
      let a = f && f.arguments;
      if (typeof a === "string") { try { a = JSON.parse(a); } catch { a = null; } }
      if (f && typeof f.name === "string" && isObject(a) && !failed.has(c.id)) made.push([f.name, a]);
    }
  }
  const again = (name, args) => made.some(([n, a]) => n === name && Object.keys(args).every((k) =>
    (k === "description" && LABELLED.has(name)) || (own(a, k) && JSON.stringify(a[k]) === JSON.stringify(args[k]))));
  // the arguments fit the tool: each is one of its parameters, and every one it requires is there
  const fits = (name, args) => {
    const p = tools.get(name);
    if (!p || !isObject(args)) return false;
    const known = isObject(p.properties) ? p.properties : {};
    if (Object.keys(args).some((k) => !own(known, k))) return false;
    return (Array.isArray(p.required) ? p.required : []).every((k) => own(args, k) || (k === "description" && LABELLED.has(name)));
  };
  const call = (name, args) => (fits(name, args) && !again(name, args) ? { name, arguments: args } : null);
  return (text) => {
    const t = String(text || "").trim();
    if (!t.startsWith("{") || !t.endsWith("}") || t.length > CALL_TEXT_MOST) return null;
    let o; try { o = JSON.parse(t); } catch { return null; }
    if (!isObject(o)) return null;
    const keys = Object.keys(o);
    if (typeof o.name === "string" && tools.has(o.name) && keys.length === 2) {
      const k = keys.find((x) => x !== "name");
      let a = k === "arguments" || k === "parameters" ? o[k] : null;
      if (typeof a === "string") { try { a = JSON.parse(a); } catch { return null; } }
      return call(o.name, a);
    }
    const bare = [...tools.keys()].filter((name) => LABELLED.has(name) && keys.some((k) => !added(name, k)));
    return bare.length === 1 ? call(bare[0], o) : null;
  };
}
// the call as Ollama sends one: its own id, the arguments as a JSON string
const callOf = (c) => ({ id: `call_${crypto.randomBytes(4).toString("hex")}`, index: 0, type: "function",
  function: { name: c.name, arguments: JSON.stringify(c.arguments) } });

// ── the tool schemas, cut to what a local session can use ──────────────────────────────────────
// The harness describes its tools for a large hosted model: the bash tool alone is 3.3k characters,
// most of it on sandbox escalation (`sandbox_permissions` + `justification`) and background jobs. A
// small local model reads every token of that before it writes a word, and gemma4:e2b sent the unasked
// `justification` and was refused (2026-10-21). In a session with full file access the escalation can
// never apply, and with no `job_output` tool a background job can never be read back, so the relay
// drops those fields there; it also shortens each tool's description to its first sentences and each
// field's to about a line. The agent's fixed prompt fell from 1,406 to 715 tokens for qwen3:1.7b
// (DGO-908). The same request is always cut the same way, so a cached prompt prefix stays identical.
const TOOL_TEXT = 320, FIELD_TEXT = 120;
function firstSentences(text, limit) {
  if (typeof text !== "string" || text.length <= limit) return text;
  let out = "";
  for (const s of text.split(/(?<=[.!?])\s+/)) {
    if (out.length + s.length + 1 > limit) break;
    out = out ? `${out} ${s}` : s;
  }
  return out || text.slice(0, limit);
}
// The session's file policy, from the harness's own runtime-context message (a user message that starts
// with it; the latest one supersedes the earlier ones) — never from text that merely quotes it.
function filePolicy(messages) {
  let policy = "";
  for (const m of messages || []) {
    if (!m || m.role !== "user") continue;
    const text = typeof m.content === "string" ? m.content
      : Array.isArray(m.content) ? m.content.map((p) => (p && typeof p.text === "string" ? p.text : "")).join("") : "";
    if (!text.startsWith("Current runtime context")) continue;
    const got = /Current DSH file policy: ([\w-]+)/.exec(text);
    if (got) policy = got[1];
  }
  return policy;
}
function trimTools(j) {
  if (!j || !Array.isArray(j.tools) || !j.tools.length) return false;
  const names = new Set(j.tools.map((t) => t && t.function && t.function.name));
  const drop = new Set();
  if (filePolicy(j.messages) === "danger-full-access") drop.add("sandbox_permissions").add("justification");
  if (!names.has("job_output")) drop.add("run_in_background");
  let changed = false;
  for (const t of j.tools) {
    const f = t && t.function;
    if (!f) continue;
    const d = firstSentences(f.description, TOOL_TEXT);
    if (d !== f.description) { f.description = d; changed = true; }
    const p = f.parameters, props = p && p.properties;
    if (!props || typeof props !== "object") continue;
    const required = Array.isArray(p.required) ? p.required : [];
    for (const k of Object.keys(props)) {
      // a field the harness requires is never hidden from the model, or every call would be refused
      if (drop.has(k) && !required.includes(k)) { delete props[k]; changed = true; continue; }
      const v = props[k];
      const s = v && firstSentences(v.description, FIELD_TEXT);
      if (v && s !== v.description) { v.description = s; changed = true; }
    }
  }
  return changed;
}

// ── a tool's answer, cut to the window the model has ─────────────────────────────────────────────
// The harness passes a tool's answer on up to 50,000 characters (the rest goes to a spill file it names
// at the end). For a model whose whole window is 16k tokens that one answer is most of it: the owner's
// local Azaria listed the checkout with `ls -R`, and the next five answers came back empty and the turn
// ended in an error (2026-10-21 21:52 UTC). So each tool answer is cut to RESULT_SHARE of the window, in
// characters — the head, and the tail where the harness names the spill file. The window is read from
// the request itself: the relay gives a local route an answer limit of a quarter of its window. The same
// request is always cut the same way, so a cached prompt prefix stays identical.
// The answers of `read` are never cut here: they are what the model writes a file back from, and the
// harness counts a read as whole — a cut one would lose a file's middle on the next `write` (the
// relay's second reader, 2026-10-21). The harness pages a long file itself.
// (window × RESULT_SHARE characters: at about three characters a token, a quarter of the window)
const RESULT_SHARE = 0.75;
const UNCUT = new Set(["read"]);
function trimResults(j) {
  if (!j || !Array.isArray(j.messages)) return false;
  const asked = Number.isInteger(j.max_completion_tokens) ? j.max_completion_tokens : j.max_tokens;
  const window = Number.isInteger(asked) && asked > 0 ? asked * 4 : 16384;
  const most = Math.max(4000, Math.floor(window * RESULT_SHARE));
  const tool = new Map();                         // a call's id → the tool it called
  for (const m of j.messages) {
    for (const c of (m && m.role === "assistant" && Array.isArray(m.tool_calls) && m.tool_calls) || []) {
      if (c && c.id && c.function) tool.set(c.id, c.function.name);
    }
  }
  const long = (text) => typeof text === "string" && text.length > most;
  // (head + marker + tail stay within `most`, so a cut answer is never cut again)
  const cut = (text) => {
    const tail = Math.floor(most / 4), head = most - tail - 160;
    return `${text.slice(0, head)}\n[… ${text.length - head - tail} characters cut by the office's relay — the model's window is ${window} tokens …]\n${text.slice(-tail)}`;
  };
  let changed = false;
  for (const m of j.messages) {
    if (!m || m.role !== "tool" || UNCUT.has(tool.get(m.tool_call_id))) continue;
    if (long(m.content)) { m.content = cut(m.content); changed = true; continue; }
    for (const p of Array.isArray(m.content) ? m.content : []) {
      if (p && long(p.text)) { p.text = cut(p.text); changed = true; }
    }
  }
  return changed;
}

// ── the agent's persona, in the role every local model reads ─────────────────────────────────────
// The harness sends the agent's persona with role "developer" (the OpenAI name for it). Ollama hands
// the role to the model's own template, and the qwen templates render only "system": qwen3:1.7b and
// qwen3.5:4b read 1,396 and 1,712 tokens of the agent's prompt instead of 3,310 and 3,846 — the whole
// persona was dropped, in every local session on those models (measured 2026-10-21, DGO-908). Only the
// leading run is renamed: a template gathers every system message into the top block, so renaming one
// sent mid-session would rewrite the top of the prompt and cost a full re-read.
function asSystem(j) {
  let changed = false;
  for (const m of (j && Array.isArray(j.messages) && j.messages) || []) {
    if (!m || (m.role !== "developer" && m.role !== "system")) break;
    if (m.role === "developer") { m.role = "system"; changed = true; }
  }
  return changed;
}

// ── each request's own recipe (the Operative Collective, DGO-948/958) ────────────────────────────
// A small model does not hold "find the recipe, then do it": told to run `bbox ops find` first,
// gemma4:e2b read the recipe and reported the errand done without doing it, twice (2026-10-21 14:40
// UTC). So the relay finds the recipe and hands it over with the request: each of the person's messages
// gets its matching operative's steps appended (`ops.py find --show`; none when nothing matches or two
// tie). Every such message gets its own recipe on every request, so the conversation the model reads is
// the same from one turn to the next and the cached prompt holds.
const OPS = path.join(OFFICE, "apps", "operatives", "ops.py");
const RECIPE_MARK = "[מתכון מאוסף האופרטיבים לבקשה הזו — בצע את הצעדים שלו בדיוק, אחד אחרי השני, כל צעד בכלי שהוא אומר]";
const recipes = new Map();                   // a message's text → its recipe ("" when none), the last 500
let recipesFrom = "";                        // the operatives' files and times the cache was filled from

// The cache holds until an operative (or the matcher) changes: clearing it more often would ask again for
// every message of every open session — and a timed-out ask dropped an old message's recipe, which
// changed the prompt and cost a full re-read.
function refreshRecipes() {
  const seen = [];
  for (const root of ["apps", "platform-base"]) {
    let apps = [];
    try { apps = fs.readdirSync(path.join(OFFICE, root)); } catch { continue; }
    for (const app of apps) {
      const dir = path.join(OFFICE, root, app, "operatives");
      let files = [];
      try { files = fs.readdirSync(dir); } catch { continue; }
      for (const f of files) {
        try { seen.push(`${root}/${app}/${f}:${fs.statSync(path.join(dir, f)).mtimeMs}`); } catch { /* gone */ }
      }
    }
  }
  try { seen.push(`ops.py:${fs.statSync(OPS).mtimeMs}`); } catch { /* no matcher */ }
  const now = seen.sort().join("|");
  if (now !== recipesFrom) { recipes.clear(); recipesFrom = now; }
}

// texts → their recipes; the ones not known yet in ONE call of the matcher. A failed call is no recipe
// this time and is not kept.
function recipesFor(texts) {
  const missing = [...new Set(texts.filter((t) => !recipes.has(t)))];
  if (missing.length && fs.existsSync(OPS)) {
    const r = spawnSync("python3", [OPS, "match"], { input: JSON.stringify(missing), encoding: "utf8", timeout: 8000 });
    let got = null;
    try { got = r.status === 0 ? JSON.parse(r.stdout) : null; } catch { got = null; }
    if (Array.isArray(got) && got.length === missing.length) {
      missing.forEach((t, i) => {
        if (recipes.size >= 500) recipes.delete(recipes.keys().next().value);
        recipes.set(t, typeof got[i] === "string" ? got[i].trim() : "");
      });
    }
  }
  return texts.map((t) => recipes.get(t) || "");
}
function textOf(m) {
  return typeof m.content === "string" ? m.content
    : Array.isArray(m.content) ? m.content.map((p) => (p && typeof p.text === "string" ? p.text : "")).join("") : "";
}
function withRecipes(j, find = recipesFor) {
  if (!j || !Array.isArray(j.messages) || !Array.isArray(j.tools) || !j.tools.length) return false;
  // the person's messages; the harness's own runtime-context note is no request
  const asks = j.messages.filter((m) => m && m.role === "user").map((m) => [m, textOf(m).trim()])
    .filter(([, text]) => text && !text.startsWith("Current runtime context") && !text.includes(RECIPE_MARK));
  if (!asks.length) return false;
  const found = find(asks.map(([, text]) => text));
  let changed = false;
  asks.forEach(([m], i) => {
    if (!found[i]) return;
    const add = `\n\n${RECIPE_MARK}\n${found[i]}`;
    if (typeof m.content === "string") m.content += add;
    else m.content = [...m.content, { type: "text", text: add }];
    changed = true;
  });
  return changed;
}

// ── the agent's fixed prompt, read ahead ────────────────────────────────────────────────────────
// A laptop reads the agent's fixed prompt (preset + tools, ~3k tokens) for minutes, and Ollama keeps
// what it read: on 2026-10-21 10:07–10:13 UTC the owner's first local message waited 3 min 36 s and his
// second 4 s. What costs is the first message after the model was (re)loaded. So the relay keeps the
// fixed part of the last agent request per route and model (its system messages and tools: the persona
// names its model, so each model has its own), and when a model with a kept prefix is newly loaded — or
// nothing is loaded — and no request is in flight, it reads that part ahead: the same prefix and a
// one-character message, one token out. On an empty Ollama it picks the model used last. It never loads
// a model while ANOTHER is loaded (that would evict a model somebody chose).
const WARM_FILE = path.join(HOME, "llm-routes-warm.json");
const WARM_MAX_AGE_S = 3 * 86400;            // a prefix no session sent for three days is not read ahead
const WARM_TIMEOUT_MS = IDLE_MS;             // a CPU reads a cold prefix in minutes, silently; then it is given up
// route → model → { prefix: request body without the tail, at }; a file of the earlier shape (route →
// { model, prefix, at }: one model per route) is read as that one model
const warm = Object.fromEntries(Object.entries(readJson(WARM_FILE, {})).map(([route, v]) =>
  [route, v && typeof v.model === "string" && v.prefix ? { [v.model]: { prefix: v.prefix, at: v.at } } : (v || {})]));
const inFlight = new Map();                  // route → requests the relay is passing right now
const lastLoaded = new Map();                // route → the model names Ollama had loaded at the last look
const keptForever = new Map();               // route → whether its model was last seen with keep-alive forever
const warming = new Set();
let lastKept = 0;                            // the newest `at` written, see remember()

function remember(route, j) {
  if (!j || !Array.isArray(j.messages) || !Array.isArray(j.tools) || !j.tools.length || !j.model) return;
  const head = [];
  for (const m of j.messages) { if (m && (m.role === "system" || m.role === "developer")) head.push(m); else break; }
  if (!head.length) return;
  // the request's own length limits stay out: the read-ahead asks for one token (pi-ai sends
  // `max_completion_tokens`, 8192, which Ollama would honour over a `max_tokens` beside it)
  const { messages: _m, stream: _s, max_tokens: _x, max_completion_tokens: _y, stream_options: _o, ...rest } = j;
  const prefix = { ...rest, messages: head };
  const models = (warm[route] = warm[route] || {});
  const before = models[j.model];
  // strictly increasing, so two models used in the same millisecond are still ordered ("used last")
  const now = Math.max(Date.now() / 1000, lastKept + 1e-6);
  lastKept = now;
  // which model was used last is what an empty Ollama gets after a restart, so a switch is written at once
  const latest = Object.entries(models).reduce((a, b) => ((b[1].at || 0) > ((a && a[1].at) || 0) ? b : a), null);
  models[j.model] = { prefix, at: now };
  const changed = !before || JSON.stringify(before.prefix) !== JSON.stringify(prefix) || !latest || latest[0] !== j.model;
  if (changed || now - (before.at || 0) > 3600) {
    for (const [name, w] of Object.entries(models)) if (now - ((w && w.at) || 0) > WARM_MAX_AGE_S) delete models[name];
    try {
      const tmp = `${WARM_FILE}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(warm), { mode: 0o600 });
      fs.renameSync(tmp, WARM_FILE);
    } catch (e) { log(`warm: ${e.message}`); }
  }
}

function postWhole(url, doc) {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(JSON.stringify(doc));
    const u = new URL(url);
    const r = (u.protocol === "https:" ? https : http).request(u, { method: "POST",
      headers: { "content-type": "application/json", "content-length": String(body.length) } }, (res) => {
      const got = []; res.on("data", (c) => got.push(c));
      res.on("end", () => resolve({ status: res.statusCode, text: Buffer.concat(got).toString("utf8") }));
      res.on("close", () => { if (!res.complete) reject(new Error("the answer was cut")); });
    });
    r.setTimeout(WARM_TIMEOUT_MS, () => r.destroy(new Error(`no answer in ${WARM_TIMEOUT_MS / 60000} min`)));
    r.on("error", reject);
    r.end(body);
  });
}

async function warmUp() {
  for (const [route, models] of Object.entries(warm)) {
    const base = upstream.get(route);
    const now = Date.now() / 1000;
    const kept = Object.entries(models || {}).filter(([, w]) => w && w.prefix && now - (w.at || 0) <= WARM_MAX_AGE_S);
    if (!base || !kept.length) continue;
    let ps;
    try { ps = (await getJson(`${base}/api/ps`, null, AbortSignal.timeout(10000))).models || []; }
    catch { continue; }
    const loaded = ps.map((m) => m.name || m.model);
    const before = lastLoaded.get(route);
    lastLoaded.set(route, loaded);           // also while a read-ahead runs: the model it loads is not new after
    if (warming.has(route)) continue;
    // a model kept "forever" (OLLAMA_KEEP_ALIVE=-1: expires_at centuries ahead) that is gone again was
    // not unloaded by its keep-alive but by a restart of that Ollama, or of its machine
    for (const m of ps) {
      if (models[m.name || m.model]) keptForever.set(route, Date.parse(m.expires_at || 0) - Date.now() > 365 * 86400e3);
    }
    // a newly loaded model with a kept prefix; or, on an empty Ollama — the first look after this process
    // started, or its model was kept forever — the model used last (otherwise empty means its keep-alive
    // unloaded the model, and that is the office's choice). Only the office's OWN Ollama is loaded from
    // empty: another office's relay that did the same would load its own last model and evict this one
    // on a small GPU; a linked office's Ollama is read ahead only once its own office has loaded a model.
    let pick = kept.find(([model]) => loaded.includes(model) && !(before && before.includes(model)));
    if (!pick && route === PREFIX + "local" && loaded.length === 0 && (before === undefined || keptForever.get(route) === true)) {
      pick = kept.reduce((a, b) => ((b[1].at || 0) > (a[1].at || 0) ? b : a));
    }
    if (!pick || (inFlight.get(route) || 0) > 0) continue;
    const [model, w] = pick;
    warming.add(route);
    const t0 = Date.now();
    // a read-ahead that failed (the model gone, no memory for it) is not retried on every pass
    const failed = (why) => { keptForever.set(route, false); log(`warm ${route} ${model}: ${why}`); };
    postWhole(`${base}/v1/chat/completions`, { ...w.prefix, model, messages: [...w.prefix.messages, { role: "user", content: "." }],
      stream: false, max_tokens: 1, max_completion_tokens: 1 })
      .then((r) => (r.status === 200 ? log(`warm ${route} ${model}: ${r.status} in ${Math.round((Date.now() - t0) / 1000)} s`)
        : failed(`${r.status} ${r.text.slice(0, 200)}`)))
      .catch((e) => failed(e.message))
      .finally(() => {
        warming.delete(route);
        // the model this read-ahead loaded is not "newly loaded" at the next look
        const seen = lastLoaded.get(route) || [];
        if (!seen.includes(model)) lastLoaded.set(route, [...seen, model]);
      });
  }
}

// An SSE stream, event line by event line, with each `data:` document passed through `fixDoc` and shown
// to `watch` (its `see(doc)`, then `end()` when the stream ends). With `asCall` (textCall), an answer
// whose text begins with `{` is held back until it ends: then it goes out as the call it wrote, if it
// is one, and as it came if it is not (after the holding comment, which an SSE reader skips). An answer
// that begins with anything else passes as it comes.
// While an answer is held, a comment goes out at once and every KEEPALIVE_MS: Node sends the response's
// headers only with its first byte, and the harness gives up on headers, and on a silent body, at 300 s.
// A line this cannot read (a document of a shape Ollama does not send) passes as it came, and ends the
// holding: the relay process must never fall over on one answer.
function sseLabeller(fixDoc, watch = null, asCall = null) {
  let rest = "";
  const utf8 = new StringDecoder("utf8");     // a Hebrew character split between two chunks stays whole
  const HOLDING = ": the answer is read whole first";
  let deciding = Boolean(asCall), text = "", beat = null;
  const held = [];                            // { out, doc, carries: it holds some of the text } while deciding
  const still = () => { clearInterval(beat); beat = null; };
  const release = (...more) => { deciding = false; still(); return held.splice(0).map((h) => h.out).concat(more); };
  const take = (l) => {                       // → the lines to send now
    let doc = null;
    if (l.startsWith("data: ") && l !== "data: [DONE]") { try { doc = JSON.parse(l.slice(6)); } catch { doc = null; } }
    if (doc && watch) watch.see(doc);
    const out = doc && fixDoc(doc) ? `data: ${JSON.stringify(doc)}` : l;
    if (!deciding) return [out];
    const c = doc && Array.isArray(doc.choices) ? doc.choices[0] : null;
    const d = (c && c.delta) || {};
    if (d.tool_calls && d.tool_calls.length) return release(out);              // it called, itself
    const piece = typeof d.content === "string" ? d.content : "";
    text += piece;
    const start = text.trimStart();
    if (start && (start[0] !== "{" || text.length > CALL_TEXT_MOST)) return release(out);
    if (!piece && !held.length) {                                              // no text yet
      if (c && c.finish_reason) deciding = false;
      return [out];
    }
    if (!c || !c.finish_reason) {
      held.push({ out, doc, carries: Boolean(piece) });
      if (held.length > 1) return [];
      beat = setInterval(() => t.push(`${HOLDING}\n\n`), KEEPALIVE_MS);
      return [HOLDING, ""];
    }
    const call = start ? asCall(text) : null;                                 // the answer ended
    if (!call) return release(out);
    // the call in place of the text: what was held without text stays (a text event's blank line goes
    // with it; reasoning it carried stays, without the text), then the call, then this last event as a
    // call's end
    const kept = [];
    let after = false;
    for (const h of held) {
      const hd = h.carries && h.doc.choices[0].delta;
      if (hd && (hd.reasoning || hd.reasoning_content)) {
        const copy = JSON.parse(JSON.stringify(h.doc));
        copy.choices[0].delta.content = "";
        kept.push(`data: ${JSON.stringify(copy)}`);
        after = false;
      } else if (h.carries) after = true;
      else if (after && h.out === "") after = false;
      else { after = false; kept.push(h.out); }
    }
    const said = JSON.parse(JSON.stringify(doc));
    delete said.usage;
    said.choices = [{ index: 0, delta: { role: "assistant", content: "", tool_calls: [callOf(call)] }, finish_reason: null }];
    fixDoc(said);
    c.delta = { ...d, role: "assistant", content: "" };
    c.finish_reason = "tool_calls";
    held.length = 0;
    deciding = false;
    still();
    return kept.concat(`data: ${JSON.stringify(said)}`, "", `data: ${JSON.stringify(doc)}`);
  };
  const line = (l) => {
    try { return take(l); } catch { return deciding ? release(l) : [l]; }
  };
  const t = new Transform({
    transform(chunk, _enc, done) {
      const parts = (rest + utf8.write(chunk)).split("\n");
      rest = parts.pop();
      const out = parts.flatMap(line);
      done(null, out.length ? out.join("\n") + "\n" : "");
    },
    flush(done) {
      rest += utf8.end();
      let out = rest ? line(rest) : [];
      if (out[0] === HOLDING) out = [];                  // released at once below: nothing to keep alive
      const all = deciding ? release(...out) : out;       // a stream that ended before its answer did
      still();
      if (watch) watch.end();
      // the last piece had no newline after it, and gets none
      done(null, all.map((l, i) => (rest && i === all.length - 1 ? l : `${l}\n`)).join(""));
    },
  });
  t.on("close", still);
  return t;
}

// the same for a whole answer (not streamed), in place: true when its text was a call
function wholeCall(doc, asCall) {
  const c = doc && Array.isArray(doc.choices) ? doc.choices[0] : null;
  const m = c && c.message;
  if (!m || (m.tool_calls && m.tool_calls.length) || typeof m.content !== "string") return false;
  const call = asCall(m.content);
  if (!call) return false;
  m.content = "";
  m.tool_calls = [callOf(call)];
  c.finish_reason = "tool_calls";
  return true;
}

// A thinking model asked NOT to think, with tools, can come back empty: on Ollama 0.40.6 qwen3:1.7b
// generated 44 tokens and returned no content and no tool call, on /v1 and on the native API alike —
// every errand of local Azaria on it failed (DGO-960, 2026-10-21). Such an answer — at least
// DROPPED_TOKENS spent (the bug spent 44 and more; a model that stops at once spends one or two), nothing
// returned, not cut by its limit — counts against its route and model, and two in a row mark them: from
// then on their requests go with the model's thinking on, slower but working. One empty answer is never
// enough (a model that works with thinking off must not think for good after one silent turn), and an
// answer with something in it clears the count. The harness retries an empty answer five times, so the
// second retry is the first served with thinking.
const DROPPED_TOKENS = 8;
const thinkOffDrops = new Set();
const emptyRuns = new Map();
function noteAnswer(key, empty) {
  if (!empty) { emptyRuns.delete(key); return false; }
  const n = (emptyRuns.get(key) || 0) + 1;
  emptyRuns.set(key, n);
  if (n < 2 || thinkOffDrops.has(key)) return false;
  thinkOffDrops.add(key);
  return true;
}
function dropWatch(key, armed, report) {
  let saw = false, tokens = 0, finish = "";
  return {
    see(doc) {
      for (const c of (doc && doc.choices) || []) {
        const d = c.delta || c.message || {};
        if ((typeof d.content === "string" && d.content.trim()) || (d.tool_calls && d.tool_calls.length)
            || d.reasoning || d.reasoning_content) saw = true;
        if (c.finish_reason) finish = c.finish_reason;
      }
      if (doc && doc.usage && Number.isFinite(doc.usage.completion_tokens)) tokens = doc.usage.completion_tokens;
    },
    end() {
      if (!armed) return;
      const empty = !saw && tokens >= DROPPED_TOKENS && finish !== "length";
      if (saw || empty) report(key, empty, tokens);
    },
  };
}

function relay() {
  const server = http.createServer((req, res) => {
    const m = /^\/([a-z0-9][a-z0-9-]*)(\/.*)$/.exec(req.url || "");
    const base = m && upstream.get(m[1]);
    const fail = (code, message) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: { message } }));
    };
    if (!base) { fail(404, `no local model route ${m ? m[1] : req.url}`); return; }
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        // the answer goes out first; only then is the connection closed
        if (!res.headersSent) {
          res.writeHead(413, { "content-type": "application/json", connection: "close" });
          res.end(JSON.stringify({ error: { message: "request body over 16 MB" } }), () => req.destroy());
        }
        req.pause();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => {
      if (res.headersSent) return;
      let body = Buffer.concat(chunks);
      let streamed = false;
      let lab = null;
      let asked = null;                  // kept for the read-ahead once the model has answered it (200)
      let watch = null;                  // an answer that comes back empty with thinking off (dropWatch)
      let asCall = null;                 // an answer that is a tool call written as text (textCall)
      try {
        const j = req.method === "POST" ? JSON.parse(body.toString("utf8") || "{}") : {};
        streamed = j.stream === true;
        const persona = asSystem(j), trimmed = trimTools(j), routed = withRecipes(j), shortened = trimResults(j);
        lab = labeller(j);
        asCall = textCall(j);
        asked = j;
        // A request that names no temperature gets the model's own default, which for the small
        // local models is 1.0: gemma4:e2b then dropped the bash tool's required `description` and gave
        // up, three times in two sessions (2026-10-21 04:06–04:53 UTC). An agent wants it steady.
        const steady = Boolean(j.messages) && j.temperature === undefined;
        if (steady) j.temperature = TEMPERATURE;
        // pi-ai sends the answer's limit as `max_completion_tokens`, and Ollama's /v1 reads only `max_tokens`
        // (measured, Ollama 0.40.6: a limit of 12 in the first gave 692 tokens, in the second 12). With no
        // limit, a small model's looping answer ran to 6,397 tokens and on until it was cancelled (DGO-949,
        // 2026-10-21 16:57 UTC). The same number goes into the field Ollama reads.
        const capped = Number.isInteger(j.max_completion_tokens) && j.max_completion_tokens > 0 && j.max_tokens === undefined;
        if (capped) j.max_tokens = j.max_completion_tokens;
        // a model that drops its tool calls with thinking off (dropWatch) is sent with its thinking on
        const key = `${m[1]} ${j.model}`;
        const unthinking = j.reasoning_effort === "none" && Array.isArray(j.tools) && j.tools.length > 0;
        const thinking = unthinking && thinkOffDrops.has(key);
        if (thinking) delete j.reasoning_effort;
        else if (unthinking) {
          watch = dropWatch(key, true, (k, empty, n) => {
            if (noteAnswer(k, empty)) {
              log(`${k}: twice in a row with thinking off it spent tokens and returned nothing (the last ${n}; Ollama drops its tool calls, DGO-960) — sent with its thinking on from now`);
            }
          });
        }
        if (persona || trimmed || routed || shortened || steady || capped || thinking) body = Buffer.from(JSON.stringify(j));
      } catch { /* not JSON: passed as it is */ }
      const target = new URL(base + m[2]);
      const headers = {};
      for (const [k, v] of Object.entries(req.headers)) if (!HOP.has(k)) headers[k] = v;
      headers["content-length"] = String(body.length);
      const up = (target.protocol === "https:" ? https : http).request(target, { method: req.method, headers });
      inFlight.set(m[1], (inFlight.get(m[1]) || 0) + 1);
      let counted = true;
      const done = () => { if (counted) { counted = false; inFlight.set(m[1], Math.max(0, (inFlight.get(m[1]) || 1) - 1)); } };
      let early = null, warm = null;
      const cool = () => { clearTimeout(early); clearInterval(warm); early = warm = null; };
      const open = () => !res.writableEnded && !res.destroyed;
      const sseError = (message, code) => {
        if (open()) res.end(`data: ${JSON.stringify({ error: { message: String(message), code } })}\n\n`);
      };
      res.on("error", () => {});          // a client that went away mid-write is not this process's crash
      if (streamed) {
        early = setTimeout(() => {
          if (!open() || res.headersSent) return;
          res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
          res.write(": the model is reading the prompt\n\n");
          warm = setInterval(() => { if (open()) res.write(": the model is reading the prompt\n\n"); }, KEEPALIVE_MS);
        }, EARLY_MS);
      }
      up.on("response", (r) => {
        cool();
        const ok = r.statusCode === 200;
        if (ok && asked) remember(m[1], asked);   // a model name the Ollama refused is never kept
        // the answer, with a missing `description` supplied (labeller) and a call written as text made
        // a call (textCall): a stream event by event, a whole JSON answer at once
        // (watched as well: a request with tools but no labelled one is still watched for an empty answer)
        const fix = lab ? lab.fixDoc : () => false;
        const changes = ok && Boolean(lab || watch || asCall);
        const pass = () => {
          if (changes && streamed) { pipeline(r, sseLabeller(fix, watch, asCall), res, () => {}); return; }
          if (changes) {
            const got = [];
            r.on("data", (c) => got.push(c));
            r.on("close", () => { if (!r.complete) res.destroy(); });
            r.on("end", () => {
              let out = Buffer.concat(got);
              try {
                const doc = JSON.parse(out.toString("utf8"));
                if (watch) { watch.see(doc); watch.end(); }
                const wrote = asCall ? wholeCall(doc, asCall) : false;
                if (fix(doc) || wrote) out = Buffer.from(JSON.stringify(doc));
              } catch { /* as it is */ }
              if (open()) res.end(out);
            });
            return;
          }
          pipeline(r, res, () => {});
        };
        if (!res.headersSent) {
          const out = {};
          for (const [k, v] of Object.entries(r.headers)) if (!HOP.has(k) || (k === "content-length" && !changes)) out[k] = v;
          res.writeHead(r.statusCode || 502, out);
          pass();
          return;
        }
        if (ok) { pass(); return; }
        const err = [];
        r.on("data", (c) => err.push(c));
        r.on("close", () => { if (!r.complete) res.destroy(); });
        r.on("end", () => {
          let message = Buffer.concat(err).toString("utf8").slice(0, 2000);
          try { const j = JSON.parse(message); message = (j.error && (j.error.message || j.error)) || message; } catch { /* plain text */ }
          sseError(message, r.statusCode);
        });
      });
      up.on("error", (e) => {
        cool();
        if (res.headersSent) sseError(e.message, 502);
        else fail(502, e.message);
      });
      res.on("close", () => { cool(); done(); up.destroy(); });
      up.end(body);
    });
  });
  server.on("error", (e) => { log(`relay: ${e.message} — exiting`); process.exit(1); });
  server.listen(RELAY_PORT, "0.0.0.0", () => log(`relay on :${RELAY_PORT} (${RELAY_HOST})`));
}

// ── which Ollamas exist (the compiled registry) ─────────────────────────────────────────────────
function sources() {
  const out = new Map();
  const add = (s) => { if (out.has(s.route)) log(`${s.route}: a second source (${s.base}) — the first is kept`); else out.set(s.route, s); };
  const own = readJson(path.join(REGISTRY, "office.apps.json"), {});
  if ((own.apps || []).some((a) => a && a.app === "ollama")) {
    add({ route: PREFIX + "local", label: "המחשב הזה", base: "http://ollama:11434" });
  }
  for (const f of fs.existsSync(REGISTRY) ? fs.readdirSync(REGISTRY) : []) {
    const m = /^remote\.([a-z0-9][a-z0-9-]*)\.([a-z0-9][a-z0-9-]*)\.json$/.exec(f);
    if (!m) continue;
    const r = readJson(path.join(REGISTRY, f), null);
    if (!r || r.app !== "ollama" || !r.module || !r.module.host) continue;
    const port = Number(r.link_port || r.port || 11434);
    add({ route: PREFIX + m[1], label: m[1], base: `http://${m[2]}.${m[1]}:${port}` });
  }
  return [...out.values()];
}

async function getJson(url, body, signal) {
  const res = await fetch(url, {
    method: body ? "POST" : "GET", signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
    headers: body ? { "content-type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return res.json();
}

// The context an Ollama really runs its models with (its OLLAMA_CONTEXT_LENGTH) is what a loaded model
// reports in /api/ps. A route declares no more than that, or the harness would send prompts the model
// cuts. An office may set less than the 32k default to keep a small model whole on a small GPU: on the
// Dell's 4 GB Radeon, qwen3:1.7b at 32k ran 13 of its 29 layers on the CPU, because the 32k context
// alone takes 3.8 GB (2026-10-21, DGO-908). Only an agent model counts (an embedding model loaded
// beside it reports its own 2k). Kept per Ollama for the passes when nothing is loaded; after this
// process starts, until a model is seen loaded, the route's last declared context stands in.
const servedContext = new Map();             // Ollama base URL → the context its agent models were loaded with
async function served(base, names, signal) {
  try {
    const sizes = ((await getJson(`${base}/api/ps`, null, signal)).models || [])
      .filter((x) => names.has(x.name || x.model))
      .map((x) => Number(x.context_length) || 0).filter((n) => n > 0);
    if (sizes.length) servedContext.set(base, Math.min(...sizes));
  } catch { /* the last number heard stays */ }
  return servedContext.get(base) || 0;
}

// The models one Ollama can serve to an agent: those that declare tool calling. An answer is
// complete or it is no answer: a model whose /api/show failed or timed out fails the whole Ollama
// for this pass, so a half-heard list never replaces the last whole one.
async function models(src, signal, lastContext) {
  const tags = await getJson(`${src.base}/api/tags`, null, signal);
  const shown = [];
  for (const m of (tags.models || []).slice(0, MAX_MODELS)) {
    const show = await getJson(`${src.base}/api/show`, { model: m.name }, signal);
    if ((show.capabilities || []).includes("tools")) shown.push([m, show]);
  }
  const heard = await served(src.base, new Set(shown.map(([m]) => m.name)), signal);
  const cap = Math.min(CONTEXT_CAP, heard || lastContext || CONTEXT_CAP);
  const out = [];
  for (const [m, show] of shown) {
    const caps = show.capabilities || [];
    const info = show.model_info || {};
    const ctxKey = Object.keys(info).find((k) => k.endsWith(".context_length"));
    const ctx = Math.max(2048, Math.min(Number(ctxKey ? info[ctxKey] : cap) || cap, cap));
    const size = m.details && m.details.parameter_size ? ` · ${m.details.parameter_size}` : "";
    // A thinking model reasons before EVERY answer unless the request says not to, and on a CPU that is
    // minutes per step: measured on the Dell, qwen3.5:2b took 273.5 s and 190 tokens to answer
    // "17+25" by default and 1.5 s and 3 tokens with `reasoning_effort: "none"` (Ollama's /v1 ignores
    // `think: false`). It also ends the prompt cache: the next step's prompt drops the reasoning, so
    // the cached sequence is no prefix of it and Ollama reads the whole conversation again (measured,
    // `cached n_tokens = 0`). So thinking is off unless a session chooses a level; a level the route
    // does not offer (DeepSeek's `max`, carried over) resolves to off.
    const reasoningEfforts = caps.includes("thinking") ? { off: "none", low: "low", medium: "medium", high: "high" } : false;
    // a quarter of the window for the answer: at 16k, half of it reserved for output left the conversation
    // a few thousand tokens before the harness compacts it
    out.push({ id: m.name, name: `${m.name}${size}`, contextWindow: ctx, maxTokens: Math.min(8192, ctx >> 2),
               reasoningEfforts, input: ["text"] });
  }
  return out;
}

// ── one pass ────────────────────────────────────────────────────────────────────────────────────
async function pass() {
  if (!DRY && !fs.existsSync(SETTINGS)) { log("settings.yaml is not there yet — the harness writes it first"); return; }
  const state = readJson(STATE, {});
  const now = Math.floor(Date.now() / 1000);
  const srcs = sources();
  const stop = AbortSignal.timeout(PASS_S * 1000);
  // the context each route declared last (see `served`): the largest of its models' windows
  const lastContext = (route) => Math.max(0, ...(((state[route] || {}).models) || []).map((x) => Number(x.contextWindow) || 0));
  const answers = await Promise.allSettled(srcs.map((s) => models(s, stop, lastContext(s.route))));
  const routes = {};
  srcs.forEach((src, i) => {
    const a = answers[i];
    // a whole answer is the truth, even an empty one; the route last written stays beside it
    if (a.status === "fulfilled") state[src.route] = { ...state[src.route], at: now, models: a.value };
    else log(`${src.route}: ${a.reason && a.reason.message}`);
    if (state[src.route]) state[src.route].base = src.base;      // where the registry says it is now
    const known = state[src.route];
    if (!known || !Array.isArray(known.models) || !known.models.length || now - known.at > KEEP_S) return;
    routes[src.route] = { displayName: `מודל מקומי · ${src.label}`, api: "openai-completions",
                          baseURL: RELAYED ? `http://${RELAY_HOST}:${RELAY_PORT}/${src.route}/v1` : `${src.base}/v1`,
                          apiKeyEnv: KEY_REF,
                          streamIdleTimeoutMs: IDLE_MS, timeoutMs: IDLE_MS, models: known.models };
  });
  // The route the office's default names stays as it was last written, whatever this pass heard:
  // every new session (goals, the pulse) starts on it.
  const def = defaultRoute();
  if (def.provider.startsWith(PREFIX) && state[def.provider] && state[def.provider].route) {
    const last = state[def.provider].route;
    const r = routes[def.provider];
    if (!r) { routes[def.provider] = last; log(`${def.provider}: silent or gone, kept — agent-default-model names it`); }
    else if (!r.models.some((m) => m.id === def.model)) {
      const keep = (last.models || []).find((m) => m.id === def.model);
      if (keep) { r.models = [...r.models, keep]; log(`${def.provider}: ${def.model} kept — agent-default-model names it`); }
    }
  }
  // the relay serves every route declared here, a kept one at the Ollama it last answered from
  for (const k of Object.keys(routes)) if (state[k] && state[k].base) upstream.set(k, state[k].base);
  for (const [k, r] of Object.entries(routes)) state[k] = { ...state[k], route: r };
  for (const k of Object.keys(state)) if (!(k in routes) && now - state[k].at > KEEP_S) delete state[k];
  if (DRY) { console.log(YAML.stringify({ "llm-pi-ai": { providers: routes } })); return; }
  if (Object.keys(routes).length) {
    try {
      edit(CREDENTIALS, (doc) => {
        if (!mapAt(doc, ["refs"], true)) { log(".credentials.yaml: `refs` is not a map — left as it is"); return false; }
        if (doc.getIn(["refs", KEY_REF]) !== undefined) return false;
        if (doc.get("version") === undefined) doc.set("version", 1);
        doc.setIn(["refs", KEY_REF], "ollama");
        return true;
      });
    } catch (e) { log(`.credentials.yaml: ${e.message}`); }
    try { installPresets(); } catch (e) { log(`presets: ${e.code || e.message}`); }
  }
  const changed = write(routes);
  fs.writeFileSync(STATE, JSON.stringify(state));
  if (changed) log(`routes: ${Object.keys(routes).join(", ") || "none"}`);
}

function defaultRoute() {
  try {
    const d = (YAML.parse(fs.readFileSync(SETTINGS, "utf8")) || {})["agent-default-model"] || {};
    return { provider: String(d.provider || ""), model: String(d.model || "") };
  } catch { return { provider: "", model: "" }; }
}

// Whether the node at `keys` is a map, or absent (then `absentOk`). A null, a scalar or a list there
// is somebody's own content in a shape this writer will not guess at.
function mapAt(doc, keys, absentOk) {
  const n = doc.getIn(keys, true);
  if (n === undefined) return absentOk;
  return YAML.isMap(n);
}

// The presets made for a local model (apps/bina-ds/presets/<id>/, e.g. `azaria-local`) go into the
// harness's user preset root, $DSH_HOME/.agent-presets, which it scans on every listing: a file that
// differs from the repo's is rewritten, and nothing is ever removed (a session may be running on it).
function installPresets() {
  const src = path.join(OFFICE, "apps", "bina-ds", "presets");
  for (const id of fs.existsSync(src) ? fs.readdirSync(src) : []) {
    if (!/^[a-z0-9][a-z0-9-]*$/.test(id) || !fs.statSync(path.join(src, id)).isDirectory()) continue;
    const dst = path.join(HOME, ".agent-presets", id);
    for (const f of fs.readdirSync(path.join(src, id))) {
      const from = path.join(src, id, f);
      if (!fs.statSync(from).isFile()) continue;
      const body = fs.readFileSync(from);
      const to = path.join(dst, f);
      if (fs.existsSync(to) && fs.readFileSync(to).equals(body)) continue;
      fs.mkdirSync(dst, { recursive: true });
      fs.writeFileSync(to, body);
      log(`preset ${id}: ${f} installed`);
    }
  }
}

// The lock this process holds, if any: a stop (docker stop, a recreate) arriving inside the few
// milliseconds of an edit gives it back, rather than leaving the harness a lock nobody owns.
let held = null;
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => { if (held) fs.rmSync(held, { force: true }); process.exit(0); });
}

// Edit one of the harness's YAML documents the way the harness does: under its `<file>.lock` sibling,
// as a comment-preserving edit, renamed into place, mode 0600. `mutate` answers whether it changed it.
function edit(file, mutate) {
  const lock = file + ".lock";
  const deadline = Date.now() + 2000;
  let fd = null;
  for (let wait = 25; fd === null; wait = Math.min(wait * 2, 400)) {
    try { fd = fs.openSync(lock, "wx"); held = lock; } catch (e) {
      if (e.code !== "EEXIST" || Date.now() > deadline) { log(`${path.basename(file)}: lock not taken (${e.code}) — next pass`); return false; }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, wait);
    }
  }
  try {
    const doc = YAML.parseDocument(fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "");
    // the parser's message can quote a line of the file, and in the credentials file that is a secret
    if (doc.errors.length) { log(`${path.basename(file)} does not parse — left as it is (${doc.errors[0].code})`); return false; }
    if (!mutate(doc)) return false;
    const tmp = `${file}.llm-routes.${process.pid}`;
    fs.writeFileSync(tmp, String(doc), { mode: 0o600 });
    fs.renameSync(tmp, file);
    return true;
  } finally {
    fs.closeSync(fd);
    fs.rmSync(lock, { force: true });
    held = null;
  }
}

// settings.yaml: OUR routes only.
function write(routes) {
  return edit(SETTINGS, (doc) => {
    if (!mapAt(doc, ["llm-pi-ai"], true) || !mapAt(doc, ["llm-pi-ai", "providers"], true)) {
      log("settings.yaml: `llm-pi-ai` or its `providers` is not a map — left as it is");
      return false;
    }
    const before = JSON.stringify((doc.toJS() || {})["llm-pi-ai"] || {});
    const current = doc.getIn(["llm-pi-ai", "providers"]);
    const names = current && current.items ? current.items.map((p) => String(p.key && p.key.value !== undefined ? p.key.value : p.key)) : [];
    for (const n of names) if (n.startsWith(PREFIX) && !(n in routes)) doc.deleteIn(["llm-pi-ai", "providers", n]);
    for (const [n, r] of Object.entries(routes)) doc.setIn(["llm-pi-ai", "providers", n], doc.createNode(r));
    const prov = doc.getIn(["llm-pi-ai", "providers"]);
    if (prov && prov.items && !prov.items.length) doc.deleteIn(["llm-pi-ai", "providers"]);
    const sec = doc.get("llm-pi-ai");
    if (sec && sec.items && !sec.items.length) doc.delete("llm-pi-ai");
    return JSON.stringify((doc.toJS() || {})["llm-pi-ai"] || {}) !== before;
  });
}

const loop = args.indexOf("--loop");
if (loop >= 0) {
  const every = Math.max(10, Number(args[loop + 1]) || 60) * 1000;
  log(`every ${every / 1000} s; registry ${REGISTRY}; settings ${SETTINGS}`);
  // the routes settings.yaml already names are served from the first second, not after the first pass
  for (const [k, v] of Object.entries(readJson(STATE, {}))) if (v && v.base) upstream.set(k, v.base);
  relay();
  for (;;) {
    await pass().catch((e) => log(`pass failed: ${e.message}`));
    await warmUp().catch((e) => log(`warm: ${e.message}`));
    refreshRecipes();                        // an operative changed in the checkout is served within a pass
    await new Promise((r) => setTimeout(r, every));
  }
} else {
  await pass();
}
