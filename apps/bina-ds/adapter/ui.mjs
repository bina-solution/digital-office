// ui.mjs — the screen of עזריה (EXU-64): ONE list of every conversation, Azaria's and Claude's, one
// conversation view, one composer — the simulation the owner approved («Awesome go. Complete everything»),
// made real. The owner, 2026-11-14 00:49: «זה חייב להיות אחיד מקום אחד כמו הסימולציה שעשית לא עיצובים
// שונים לספקים שונים».
//
// Served by this adapter, on its own port (3081), behind the office's sign-in: `azaria.<domain>` and the
// console tile route here. The page is ../web/ (static); its data is the `/ui/…` door below, which speaks
// to the two engines through the ONE contract both already serve — agent.v1:
//   · Azaria — this adapter's own functions (the harness, DeepSeek or a local model);
//   · Claude — the office's OFFICIAL Claude app (apps/bina-claude, `http://bina-claude:3091`), signed in
//     once. Its messages run in that app, on that sign-in; this door holds bina-claude's action token
//     (taken from its container, as `bbox agent --app bina-claude` does) and never hands it to a browser.
//     Anthropic's terms keep a claude.ai sign-in in Anthropic's own flow
//     (code.claude.com/docs/en/legal-and-compliance), so no Claude sign-in is offered here.
//
// Who may call: a request that carries the identity header the office's edge adds after sign-in
// (DSH_TRUST_PROXY_AUTH_HEADER — the trust the harness itself places in it), from this page itself
// (Sec-Fetch-Site), and every write as JSON.
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { lookup } from "node:dns/promises";
import path from "node:path";

const WEB = process.env.BINA_DS_WEB_DIR || new URL("../web/", import.meta.url).pathname;
const EDGE = (process.env.DSH_TRUST_PROXY_AUTH_HEADER || "").toLowerCase();
const CLAUDE_API = (process.env.BINA_CLAUDE_API || "http://bina-claude:3091").replace(/\/+$/, "");
const CLAUDE_CONTAINER = process.env.BINA_CLAUDE_CONTAINER || `bina-claude-${process.env.DEPLOYMENT_NAME || "bina-deployment"}`;
const FILES = { "index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8",
                "vendor/markdown-it.min.js": "text/javascript; charset=utf-8" };
const ID = /^[A-Za-z0-9_.-]{1,96}$/;

class UiError extends Error { constructor(status, message, code = null) { super(message); this.status = status; this.code = code; } }

// ── who may reach the screen: the office's edge and its console, by address ────────────────────
// The identity header is added by the edge after the office's sign-in; on the office network any
// container could ALSO send it, so the screen answers only connections from the edge (traefik: the
// standalone host and the console's passthrough) and from the console (its /a/<alias>/ proxy), the
// same rule bina-claude's front door keeps (apps/bina-claude/adapter/gate.mjs). The names resolve at
// run time (below); BINA_DS_UI_PEERS overrides them.
const PEERS = (process.env.BINA_DS_UI_PEERS || `traefik-${process.env.DEPLOYMENT_NAME || "bina-deployment"},console-${process.env.DEPLOYMENT_NAME || "bina-deployment"}`)
  .split(",").map((s) => s.trim()).filter(Boolean);
// Re-asked every 10 s (a recreated edge's old address is admitted at most that long). ONE lookup at a
// time, shared by every request waiting on it, and a stranger can force a fresh one at most every 3 s —
// a flood from the network must not queue the real edge behind thousands of DNS questions (the same
// rule as bina-claude's gate, DGO-1074; second reader, EXU-64). A name whose lookup fails for a moment
// keeps its last good answer unless DNS says it no longer exists.
const PEER_TTL = 10000, PEER_MISS = 3000;
const peerKnown = new Map();                                                // name → [addresses]
let peerSet = new Set(["127.0.0.1", "::1"]), peerAt = 0, peerPending = null;
function peerRefresh() {
  if (!peerPending) {
    peerPending = (async () => {
      for (const name of PEERS) {
        try { peerKnown.set(name, (await lookup(name, { all: true })).map((a) => a.address)); }
        catch (e) { if (e && e.code === "ENOTFOUND") peerKnown.delete(name); }
      }
      peerSet = new Set(["127.0.0.1", "::1", ...[...peerKnown.values()].flat()]);
      peerAt = Date.now();
    })().finally(() => { peerPending = null; });
  }
  return peerPending;
}
async function peerAllowed(req) {
  const ip = String(req.socket.remoteAddress || "").replace(/^::ffff:/, "");
  if (Date.now() - peerAt > PEER_TTL) await peerRefresh();
  if (peerSet.has(ip)) return true;
  if (Date.now() - peerAt > PEER_MISS) await peerRefresh();                 // a recreated edge: ask once more
  return peerSet.has(ip);
}

// ── Claude: the official app's agent.v1, with its token — every Claude app of the office ──────────
// One office may run several Claude Desktops, each on its own account (DGO-1920 instances; the owner, 2026-11-17:
// «2-3 claude desktops on hp every one with diffrent account»). The first keeps the template's id, `bina-claude`;
// each further one is an instance the compiler writes as instances/<id>/app.json with `instance_of: bina-claude`,
// its names the template's with the prefix replaced (platform/manager/instances.py derive_name): its service
// `<id>` on 3091, its container `<id>-<office>`. Found from that declaration, never from a list kept here.
const CLAUDE_OF = "bina-claude";
// Read at most every 30 s, and a read that fails (a slow or EIO checkout: /mnt/c on the HP) keeps the last good
// list — an app must not vanish for one request and its conversations go to another (second reader). An instance
// that is turned off keeps its folder, so only the ones the compiler RESOLVED (its start order) are apps here.
const appsCache = new Map();                                         // office → { at, apps }
function claudeAppsIn(office) {
  const hit = appsCache.get(office);
  if (hit && Date.now() - hit.at < 30000) return hit.apps;
  const apps = [{ id: CLAUDE_OF, key: "", title: null, api: CLAUDE_API, container: CLAUDE_CONTAINER }];
  let names = [];
  try { names = readdirSync(path.join(office, "instances")); }
  catch (e) { if (!(e && e.code === "ENOENT")) return hit ? hit.apps : apps; }
  let on = null;
  try { const r = JSON.parse(readFileSync(path.join(office, ".generated", "resolved.json"), "utf8")); if (Array.isArray(r.order)) on = new Set(r.order); }
  catch { /* not compiled here: every declared one */ }
  let failed = false;
  for (const name of names.sort()) {
    if (!ID.test(name) || !name.startsWith(`${CLAUDE_OF}-`) || (on && !on.has(name))) continue;
    let m = null;
    try { m = JSON.parse(readFileSync(path.join(office, "instances", name, "app.json"), "utf8")); }
    catch (e) { if (!(e && e.code === "ENOENT")) failed = true; continue; }
    if (!m || m.instance_of !== CLAUDE_OF || m.id !== name) continue;
    apps.push({ id: name, key: String(m.instance_key || ""), title: m.title && typeof m.title === "object" ? m.title : null,
                api: `http://${name}:3091`, container: `${name}-${process.env.DEPLOYMENT_NAME || "bina-deployment"}` });
  }
  if (failed && hit) return hit.apps;
  appsCache.set(office, { at: Date.now(), apps });
  return apps;
}
// Each app's action token, read from its own container (as `bbox agent --app <id>` does), never handed to a browser.
const claudeTokens = new Map(), tokenFailedAt = new Map();
function readClaudeToken(app) {
  // (no token, no request: nothing left this door — a message is «not sent», never «not known», code no-exec)
  if (Date.now() - (tokenFailedAt.get(app.id) || 0) < 60000) return Promise.reject(new UiError(502, "אפליקציית Claude של הלשכה אינה זמינה", "no-exec"));
  return new Promise((resolve, reject) => {
    execFile("docker", ["exec", app.container, "sh", "-c", 'cat "$AGENT_TOKEN_FILE"'], { timeout: 10000 }, (err, out) => {
      const t = String(out || "").trim();
      if (err || !t) { tokenFailedAt.set(app.id, Date.now()); return reject(new UiError(502, err ? "אפליקציית Claude של הלשכה אינה זמינה" : "לאפליקציית Claude אין עדיין טוקן פעולה", "no-exec")); }
      resolve(t);
    });
  });
}
let tokenReader = readClaudeToken;                                   // a test hands its own (createUi's `claudeToken`)
async function tokenOf(app) {
  if (!claudeTokens.has(app.id)) claudeTokens.set(app.id, await tokenReader(app));
  return claudeTokens.get(app.id);
}
// What the Claude door's refusal MEANS, in the words the person reads (the codes are bina-claude's agent.v1
// and its desktop driver's; the English original goes to this container's log, never to the screen —
// «לא נשלח: nothing was sent: the text is not in the composer…» reached the owner's phone, EXU-64 07:41).
const SENT_NOTHING = "לא נשלח דבר — אפשר לשלוח שוב.";
const CLAUDE_SAYS = {
  "not-sent": `המסך של אפליקציית Claude לא היה מוכן לקבל את ההודעה. ${SENT_NOTHING}`,
  "no-window": `המסך של אפליקציית Claude לא פתוח. ${SENT_NOTHING}`,
  "dropped": `אפליקציית Claude לא פתחה שיחה חדשה בזמן. ${SENT_NOTHING}`,
  "not-focused": `אפליקציית Claude מציגה עכשיו שיחה אחרת. ${SENT_NOTHING}`,
  "no-app": `אפליקציית Claude לא ענתה. ${SENT_NOTHING}`,
  "no-app-session": `אפליקציית Claude של הלשכה לא זמינה כרגע. ${SENT_NOTHING}`,
  "no-exec": `אפליקציית Claude של הלשכה לא זמינה כרגע. ${SENT_NOTHING}`,
  "locked": "Claude מטפל ברגע זה בהודעה אחרת. לא נשלח דבר — שלחו שוב בעוד רגע.",
  "busy": "השיחה הזאת עובדת עכשיו. אפשר לשלוח כשהיא מסיימת, או לעצור אותה.",
  "waiting": "השיחה הזאת מחכה לאישור או לתשובה שלך באפליקציה הרשמית.",
  "no-session": "השיחה הזאת לא נמצאה באפליקציית Claude.",
  "not-confirmed": "ההודעה נמסרה ל-Claude אבל עוד לא מופיעה בשיחה. בדקו ברשימה לפני ששולחים שוב.",
  "unknown": "לא ידוע אם ההודעה נשלחה. בדקו ברשימה לפני ששולחים שוב.",
  "too-large": "ההודעה ארוכה מדי לאפליקציית Claude.",
  "no-text": "ההודעה ריקה.",
  "not-started": "השיחה עוד נפתחת באפליקציית Claude — אפשר לעצור אותה כשהיא מתחילה.",
};
// The refusals after which NOTHING reached the app (bina-claude's own UNSENT, and a text it would not take): the
// words may be sent again. Every other failure (unknown, not-confirmed, a timeout, a code not known here) may have
// delivered the message, so it is said as «not known», and the words are not offered again (DGO-2044, second reader).
const UNSENT = new Set(["no-text", "not-sent", "dropped", "locked", "busy", "waiting", "no-window", "no-app", "no-app-session",
                        "not-focused", "no-session", "no-exec", "too-large", "token"]);
// What a refused STOP means (a stop is not a message: «send again» would be wrong here); the screen says «לא נעצר: …»
const CANCEL_SAYS = {
  "locked": "Claude מטפל ברגע זה בהודעה אחרת — אפשר לעצור בעוד רגע.",
  "busy": "אפליקציית Claude עסוקה כרגע בשיחה אחרת — אפשר לעצור בעוד רגע.",
  "dropped": "אפליקציית Claude לא הציגה את השיחה בזמן — אפשר לנסות שוב.",
  "not-confirmed": "נלחץ Esc, אבל השיחה עדיין עובדת — אפשר לנסות שוב, או לעצור באפליקציה הרשמית.",
  "unknown": "אפליקציית Claude לא ענתה בזמן — ייתכן שהשיחה כבר נעצרה.",
  "not-started": "השיחה עוד נפתחת באפליקציית Claude — אפשר לעצור אותה כשהיא מתחילה.",
  "no-app": "אפליקציית Claude לא עונה כרגע — אפשר לנסות לעצור בעוד רגע.",
  "no-exec": "אפליקציית Claude של הלשכה לא זמינה כרגע — אפשר לנסות לעצור בעוד רגע.",
  "token": "אפליקציית Claude לא קיבלה את הבקשה — אפשר לנסות לעצור בעוד רגע.",
};
async function claude(app, method, p, body, timeoutMs) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const token = await tokenOf(app);
    let r;
    try {
      r = await fetch(app.api + p, {
        method,
        headers: { authorization: `Bearer ${token}`, ...(body ? { "content-type": "application/json" } : {}) },
        body: body ? JSON.stringify(body) : undefined,
        // a message is handed to the app by its driver, which may take 150 s and is given 200 s by the
        // door: waiting less here gave up on a call that could still send (and said so in English)
        signal: AbortSignal.timeout(timeoutMs || (method === "GET" ? 15000 : 210000)),
      });
    } catch (e) {
      console.error(`[bina-ds] ui: ${app.id} ${method} ${p}: ${e && e.message}`);
      // a connection that never opened sent nothing; a timeout may have (the app could be pressing keys)
      if (e && e.cause && ["ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN", "EHOSTUNREACH"].includes(e.cause.code)) {
        throw new UiError(502, method === "GET" ? "אפליקציית Claude לא עונה כרגע." : CLAUDE_SAYS["no-app"], "no-app");
      }
      throw new UiError(504, method === "GET" ? "אפליקציית Claude לא ענתה בזמן." : CLAUDE_SAYS.unknown, method === "GET" ? "no-answer" : "unknown");
    }
    if (r.status === 401 && attempt === 0) { claudeTokens.delete(app.id); continue; }   // a recreated app has a new token
    const text = await r.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
    if (!r.ok) {
      console.error(`[bina-ds] ui: ${app.id} ${method} ${p} → ${r.status} ${(json && json.code) || ""}: ${((json && json.error) || text).slice(0, 300)}`);
      const code = json && typeof json.code === "string" ? json.code : null;
      // a refusal this door does not know: for a read, the app did not answer as it should; for a message, it may
      // have gone, so it is not said to be unsent
      const said = CLAUDE_SAYS[code] || (method === "GET" ? "אפליקציית Claude לא ענתה כמו שצריך." : CLAUDE_SAYS.unknown);
      throw new UiError(r.status === 404 ? 404 : 502, said, code || (method === "GET" ? "no-answer" : "unknown"));
    }
    return json;
  }
}
// The whole of a Claude conversation. The door's /messages gives its last 500 events at most; its event
// stream opens with a `snapshot` of as many past events as asked, uncapped — that snapshot is read, and the
// stream closed (nothing is followed). A dead read says so in Hebrew.
const ALL = 100000;
async function claudeAll(app, id) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const token = await tokenOf(app);
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 30000);
    try {
      const r = await fetch(`${app.api}/v1/sessions/${encodeURIComponent(id)}/events?history=${ALL}`,
        { headers: { authorization: `Bearer ${token}` }, signal: ctl.signal });
      if (r.status === 401 && attempt === 0) { claudeTokens.delete(app.id); continue; }
      if (!r.ok) throw new UiError(r.status === 404 ? 404 : 502, CLAUDE_SAYS["no-session"]);
      const dec = new TextDecoder();
      let buf = "";
      for await (const chunk of r.body) {
        buf += dec.decode(chunk, { stream: true });
        for (let i = buf.indexOf("\n\n"); i >= 0; i = buf.indexOf("\n\n")) {
          const block = buf.slice(0, i);
          buf = buf.slice(i + 2);
          if (!/^event: snapshot$/m.test(block)) continue;
          const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
          return JSON.parse(data).events || [];
        }
      }
      return [];
    } catch (e) {
      if (e instanceof UiError) throw e;
      console.error(`[bina-ds] ui: Claude history of ${id}: ${e && e.message}`);
      throw new UiError(504, "ההיסטוריה המלאה של Claude לא נטענה בזמן. אפשר לנסות שוב.");
    } finally { clearTimeout(timer); ctl.abort(); }
  }
  throw new UiError(502, "אפליקציית Claude של הלשכה לא זמינה כרגע.");
}
async function claudeStatus(app) {
  try {
    const h = await (await fetch(app.api + "/v1/health", { signal: AbortSignal.timeout(5000) })).json();
    return { installed: true, signed_in: !!h?.login?.logged_in, active: h?.active ?? 0 };
  } catch { return { installed: false, signed_in: false, active: 0 }; }
}
// What the screen is told about each Claude app: its id (the console's tile is `#/m/<id>`), its key and title, its state.
const claudeFacts = async (apps) => (await Promise.all(apps.map((app) => claudeStatus(app))))
  .map((s, i) => ({ id: apps[i].id, key: apps[i].key || "", title: apps[i].title, ...s }));

// ── where Azaria may run (DGO-2036): the cloud providers, where each one's key comes from, and the
// office's computers that serve a local model ──────────────────────────────────────────────────────
// A key never crosses this screen. It is kept in the office's secrets (the `connections` app), and the
// harness reads it from there on every request once the provider's reference points at its connection:
// the vault-key plugin's `vault:<connection>` value (plugins/vault-key), written through the same
// `credentials/set` its card in the full interface uses. This table is that plugin's OFFERS — the three
// connections app.json declares; the broker grants this container nothing else.
const OFFERS = {
  deepseek: { ref: "DEEPSEEK_API_KEY", connection: "deepseek-key", name: "DeepSeek" },
  openai: { ref: "OPENAI_API_KEY", connection: "openai-key", name: "OpenAI" },
  anthropic: { ref: "ANTHROPIC_API_KEY", connection: "anthropic-key", name: "Anthropic" },
};
// A local model's route is `dgo-ollama-<office>` (tools/llm-routes.mjs): this office's own Ollama, or a
// linked office's. A label is what an office calls ITSELF, so it is shown only for an office of our own herd (the
// compiled herd registry: its ids and their aliases); any other office is named by the id this office paired
// with, as llm-routes names its route, and marked as outside the herd — a peer can never present itself as one of
// ours, nor as «המחשב של הלשכה» (second reader, DGO-2036).
const LOCAL = /^dgo-ollama-([a-z0-9][a-z0-9-]{0,62})$/;
function computerOf(office, route) {
  const id = (LOCAL.exec(route) || [])[1] || "";
  if (id === "local") return { id, name: "המחשב של הלשכה", here: true, ours: true };
  const reg = path.join(office, ".generated", "registry");
  let ours = false;
  try {
    const herd = JSON.parse(readFileSync(path.join(reg, "herd.offices.json"), "utf8"));
    for (const [oid, o] of Object.entries((herd && herd.offices) || {}))
      if (oid === id || (Array.isArray(o && o.aliases) && o.aliases.includes(id))) ours = true;
  } catch { /* no herd registry here: no office is known to be ours */ }
  if (!ours) return { id, name: `${id} · מחוץ לעדר`, here: false, ours: false };
  try {
    for (const f of readdirSync(reg).filter((n) => n.startsWith(`remote.${id}.`) && n.endsWith(".json")).sort()) {
      const r = JSON.parse(readFileSync(path.join(reg, f), "utf8"));
      const l = r && r.remote && r.remote.label;
      if (l && (l.he || l.en)) return { id, name: String(l.he || l.en), here: false, ours: true };
    }
  } catch { /* its registry is unreadable: its id */ }
  return { id, name: id, here: false, ours: true };
}

// ── one row of the list, whatever the engine ───────────────────────────────────────────────────
const label = (m) => (m && m.model ? String(m.model) : "");
function azariaRow(s) {
  const asks = (s.questions || []).filter((q) => q && q.questions && q.questions.length);
  return { id: s.id, engine: "azaria", title: s.title || null, running: !!s.running, waiting: asks.length ? "question" : null,
           updated_at: s.updated_at || null, turns: s.turns ?? null, model: s.model || null, model_label: label(s.model), preset: s.preset || null,
           todos: Array.isArray(s.todos) ? s.todos : null, questions: asks, can_retry: !!s.can_retry, queue: s.queue || 0 };
}
function claudeRow(s, app) {
  return { id: s.id, engine: "claude", app: app.id, app_key: app.key || null, title: s.title || null, running: !!s.running, waiting: s.waiting_for || null,
           updated_at: s.updated_at || s.created_at || null, turns: s.turns ?? null, model: s.model || null, model_label: label(s.model), preset: "claude-desktop" };
}
const engineOf = (id) => (id.startsWith("local_") || id.startsWith("pending-") ? "claude" : "azaria");

const MAX_UPLOAD = 25 << 20;
export function createUi({ listSessions, snapshotEvents, prompt, rpc, refreshList, office, archived = () => new Set(), setArchived = () => {},
                           follow = null, upload = null, claudeApps = null, claudeToken = null }) {
  tokenReader = claudeToken || readClaudeToken;                    // this door's own: nothing kept from another
  claudeTokens.clear(); tokenFailedAt.clear(); appsCache.clear();
  const appsNow = claudeApps || (() => claudeAppsIn(office));
  // Which Claude app holds a conversation: the one the screen names (`app`, from this door's own row), else the one
  // whose list showed it (or that opened it here), else the first — the only one an office had before instances.
  const owner = new Map();
  const appOf = (id, hint) => {
    const apps = appsNow(), by = (x) => (x ? apps.find((a) => a.id === x) : null);
    return by(hint) || by(owner.get(id)) || apps[0];
  };
  // ── a message to Claude goes in the BACKGROUND (DGO-2044; the owner: «זה ממש לא אמור לקחת דקה … זה אמור להיות
  // מילי שניות») ──────────────────────────────────────────────────────────────────────────────────────────────────
  // Handing a message to the official app drives the app's own screen, and that takes seconds (measured on Exampleu:
  // 24 s to start a conversation). The screen must not wait for it: the door answers at once, drives each app's
  // messages one after another (the app takes one at a time — two at once is its «locked»), and the conversation
  // says what happened when it is read: still going (`sending`), started under its real id (`resolved`), or not
  // sent and why (`failed`: the reason in Hebrew and the text, so the screen gives the text back).
  const lanes = new Map();                                          // app id → the tail of its queue
  const sending = new Map();                                        // conversation id → { at, text, app }
  const failedSend = new Map();                                     // conversation id → { at, text, error, maybe? }
  const resolvedTo = new Map();                                     // pending id → { id: the real id it started as, at }
  const unreached = new Map();                                      // pending id → when its app first could not be asked
  const realOf = (pid) => (resolvedTo.has(pid) ? resolvedTo.get(pid).id : undefined);
  function resolve(pid, real, appId) {
    resolvedTo.set(pid, { id: real, at: Date.now() });
    owner.set(real, appId);
  }
  // a failure is said for an hour, and a promise's real id is kept for a day (bina-claude forgets its promises then)
  function prune() {
    const now = Date.now();
    for (const [k, v] of failedSend) if (now - v.at > 3600000) failedSend.delete(k);
    for (const [k, v] of resolvedTo) if (now - v.at > 86400000) resolvedTo.delete(k);
    for (const [k, at] of unreached) if (now - at > 3600000) unreached.delete(k);
  }
  // What a failure means for the words: an UNSENT refusal reached nothing (they may go again); any other may have
  // delivered them — then it is «not known», and the screen does not offer them again (a second send would repeat)
  const failure = (e, text) => {
    const code = e && typeof e.code === "string" ? e.code : null;
    const error = e instanceof UiError ? e.message : (code && CLAUDE_SAYS[code]) || CLAUDE_SAYS.unknown;
    return { at: Date.now(), text, code, error, ...(UNSENT.has(code) ? {} : { maybe: true }) };
  };
  function inBackground(app, id, text, call) {
    prune();
    sending.set(id, { at: Date.now(), text, app: app.id });
    failedSend.delete(id);
    const run = (lanes.get(app.id) || Promise.resolve()).catch(() => {}).then(call);
    lanes.set(app.id, run.catch(() => {}));
    run.then((r) => {
      sending.delete(id);
      if (r && typeof r.id === "string" && r.id !== id && ID.test(r.id)) resolve(id, r.id, app.id);
      refreshList(true);
    }, (e) => {
      sending.delete(id);
      failedSend.set(id, failure(e, text));
    });
  }
  const pendingRow = (pid, s, failed) => {
    const app = appsNow().find((a) => a.id === s.app);
    return { id: pid, engine: "claude", app: s.app, app_key: (app && app.key) || null, title: String(s.text || "").slice(0, 60) || null,
             running: !failed, waiting: null, updated_at: new Date(s.at).toISOString(), turns: 0, model: null, model_label: "",
             preset: "claude-desktop", ...(failed ? { failed: true, ...(s.maybe ? { maybe: true } : {}) } : { sending: true }) };
  };
  // A conversation whose app is not known (the door restarted, and that app's list is slow): its app answers, and
  // the others answer 404 and press nothing — bina-claude finds a conversation by its full id before driving
  // anything — so each is asked in turn, and the one that answers is its owner from then on (second reader).
  async function viaApp(id, hint, call) {
    const apps = appsNow(), first = appOf(id, hint);
    const known = !!((hint && apps.some((a) => a.id === hint)) || owner.has(id));
    try { return await call(first); }
    catch (e) {
      if (known || !(e instanceof UiError) || e.status !== 404) throw e;
      for (const app of apps) {
        if (app.id === first.id) continue;
        try { const r = await call(app); owner.set(id, app.id); return r; }
        catch (e2) { if (!(e2 instanceof UiError) || e2.status !== 404) throw e2; }
      }
      throw e;
    }
  }
  // Each Claude app's list, never allowed to hold Azaria's back: a slow or absent app answers with the last list
  // it gave (and says it is not answering) after 4 s.
  const lastClaude = new Map();
  async function sessions() {
    prune();
    const apps = appsNow();
    const [a, ...cs] = await Promise.allSettled([listSessions(false), ...apps.map((app) => claude(app, "GET", "/v1/sessions", null, 4000))]);
    const rows = [];
    // a conversation that started from a promise of this door says which (`from`): the screen moves the promise's pin,
    // draft and place to it, even when it was not the open conversation
    const fromOf = new Map([...resolvedTo].map(([pid, v]) => [v.id, pid]));
    const shelved = archived();
    if (a.status === "fulfilled") for (const s of a.value) if (!s.stale && !(s.blank && !s.title)) rows.push({ ...azariaRow(s), archived: shelved.has(s.id) });
    const said = {};
    apps.forEach((app, i) => {
      const c = cs[i];
      if (c.status === "fulfilled") lastClaude.set(app.id, (c.value?.sessions || []).filter((s) => !s.archived && !(s.blank && !s.title)).map((s) => claudeRow(s, app)));
      said[app.id] = c.status === "fulfilled" ? { ok: true } : { ok: false, error: c.reason?.message || "unavailable" };
      for (const r of lastClaude.get(app.id) || []) { owner.set(r.id, app.id); rows.push(fromOf.has(r.id) ? { ...r, from: fromOf.get(r.id) } : r); }
    });
    // a conversation opened here whose first message is still being handed over (or was not): in the list at once
    for (const [pid, s] of sending) if (pid.startsWith("pending-") && !resolvedTo.has(pid)) rows.push(pendingRow(pid, s, false));
    for (const [pid, f] of failedSend) if (pid.startsWith("pending-") && !resolvedTo.has(pid) && !sending.has(pid)) rows.push(pendingRow(pid, { ...f, app: appOf(pid).id }, true));
    rows.sort((x, y) => String(y.updated_at || "").localeCompare(String(x.updated_at || "")));
    return {
      sessions: rows,
      engines: {
        azaria: a.status === "fulfilled" ? { ok: true } : { ok: false, error: a.reason?.message || "unavailable" },
        claude: said[apps[0].id],                                   // the first app, as before instances
        claudes: said,
      },
    };
  }

  async function models() {
    let catalog = null;
    try { catalog = await rpc("session/modelCatalog", {}); } catch { /* the harness answers later */ }
    // a local model's computer, by the name the link gave it: the screen says «Dell», not a route id
    const computers = {};
    for (const g of (Array.isArray(catalog?.groups) ? catalog.groups : [])) if (LOCAL.test(g.id)) computers[g.id] = computerOf(office, g.id).name;
    const claudes = await claudeFacts(appsNow());
    return { azaria: catalog, claude: claudes[0], claudes, computers };
  }

  // Every place a conversation can run, and what each one needs: a cloud provider (is its key there, and
  // does it come from the office's secrets), a computer of the office with a local model, the Claude app.
  async function providers() {
    const [catalog, creds, claudes] = await Promise.all([
      rpc("session/modelCatalog", {}).catch(() => null),
      rpc("credentials/describe", { refs: Object.values(OFFERS).map((o) => o.ref) }).catch(() => null),
      claudeFacts(appsNow()),
    ]);
    const views = (creds && (creds.views || creds)) || {};
    const groups = Array.isArray(catalog?.groups) ? catalog.groups : [];
    const routable = Array.isArray(catalog?.routableProviders) ? new Set(catalog.routableProviders) : null;
    // what is not known is said so (null), never «no»: a catalog that did not answer is not every provider down
    const can = (id) => (!catalog ? null : routable ? routable.has(id) : groups.some((g) => g.id === id));
    const cloud = Object.entries(OFFERS).map(([id, o]) => {
      const v = views[o.ref] || {};
      const g = groups.find((x) => x.id === id);
      const said = !!creds && typeof v.configured === "boolean";       // what the harness did not say is unknown
      return { id, name: o.name, connection: o.connection, configured: said ? v.configured : null,
               vault: said ? String(v.source || "").startsWith("office-vault:") : null, routable: can(id), models: g ? (g.models || []).length : 0 };
    });
    const local = groups.filter((g) => LOCAL.test(g.id)).map((g) => ({ id: g.id, computer: computerOf(office, g.id),
      models: (g.models || []).map((m) => m.id), routable: can(g.id) }));
    return { cloud, local, claude: claudes[0], claudes, keys_read: !!creds };
  }
  // A provider's key, taken from the office's secrets: its reference points at its connection from now on
  // (the value is the pointer, never a key). Refused for anything outside the table above, and never written over
  // a key that already works from elsewhere (typed into the full interface, the launch environment): the pointer
  // is the whole value, so it would replace that key with whatever the vault holds — maybe nothing (second reader).
  async function bindKey(id) {
    const o = Object.hasOwn(OFFERS, id) ? OFFERS[id] : null;
    if (!o) throw new UiError(404, "אין ספק כזה");
    let v = null;
    try { const d = await rpc("credentials/describe", { refs: [o.ref] }); v = ((d && (d.views || d)) || {})[o.ref] || null; }
    catch { v = null; }
    // an answer that does not SAY whether the key is there (no view, another shape) is not «no key» (second reader)
    if (!v || typeof v.configured !== "boolean") throw new UiError(503, "לא ידוע כרגע מאיפה המפתח של הספק, ולכן לא שונה דבר. אפשר לנסות שוב.");
    if (v.configured && !String(v.source || "").startsWith("office-vault:"))
      throw new UiError(409, `ל-${o.name} כבר יש מפתח שעובד, והוא נשאר כמו שהוא.`);
    await rpc("credentials/set", { ref: o.ref, value: `vault:${o.connection}` });
    return { id, connection: o.connection };
  }

  // A window of the last `limit` events (fast, what a poll needs), or the WHOLE conversation (`ALL`): the
  // owner must be able to read a conversation from its first message (EXU-64 07:48). `more` says whether
  // earlier events exist beyond the window.
  async function messages(id, limit, hint) {
    if (engineOf(id) === "claude") {
      // what is happening to a message handed over in the background, said with the conversation
      const s = sending.get(id);
      let f = failedSend.get(id), real = realOf(id), starting = false;
      // A promise this door does not know (the door restarted, a deploy): the app keeps its promises and says what
      // became of one — started (under its id), being started, refused (why), or never asked to start.
      if (id.startsWith("pending-") && !s && !f && !real) {
        let via = null, gone = false;
        const said = await viaApp(id, hint, (app) => { via = app; return claude(app, "GET", `/v1/sessions/${encodeURIComponent(id)}`); })
          .catch((e) => { if (e instanceof UiError && e.status === 404) gone = true; return null; });
        const waited = Date.now() - (unreached.get(id) || Date.now());
        if (said && typeof said.id === "string" && said.id !== id && ID.test(said.id)) { resolve(id, said.id, (via || appOf(id, hint)).id); real = said.id; }
        // no app keeps this promise any more (it restarted, or a day went by): its start may have sent before it forgot
        else if (gone) {
          f = { at: Date.now(), text: "", code: "no-session", maybe: true,
                error: "אפליקציית Claude כבר לא מכירה את השיחה הזאת — ייתכן שההודעה נשלחה לפני כן. בדקו ברשימה." };
          failedSend.set(id, f);
        }
        // the app cannot be asked right now (a deploy): still on its way, asked again next read — for five minutes
        else if ((!said && waited < 300000) || (said && said.starting)) { starting = true; if (!said && !unreached.has(id)) unreached.set(id, Date.now()); }
        else if (!said) { f = { at: Date.now(), text: "", code: "unknown", maybe: true, error: CLAUDE_SAYS.unknown }; failedSend.set(id, f); unreached.delete(id); }
        else {
          // what the app says is kept (the list then carries the row, and every later read says the same)
          const code = typeof said.failed === "string" ? said.failed : (said.blank ? "never-started" : "unknown");
          f = { at: Date.now(), text: "", code,
                error: code === "never-started" ? `ההודעה לא הגיעה לאפליקציית Claude. ${SENT_NOTHING}` : (CLAUDE_SAYS[code] || CLAUDE_SAYS.unknown),
                ...(code === "never-started" || UNSENT.has(code) ? {} : { maybe: true }) };
          failedSend.set(id, f);
        }
      }
      const told = { ...(s || starting ? { sending: true } : {}),
                     ...(f ? { failed: { error: f.error, text: f.text, at: f.at, ...(f.code ? { code: f.code } : {}), ...(f.maybe ? { maybe: true } : {}) } } : {}),
                     ...(real ? { resolved: real } : {}) };
      // a conversation not started yet has nothing to read in the app: what is happening to it is the answer
      if (id.startsWith("pending-") && !real) return { id, engine: "claude", app: (s && s.app) || appOf(id, hint).id, events: [], more: false, ...told };
      const read = real || id;
      let r;
      try {
        r = await viaApp(read, hint, async (app) => {
          if (limit >= ALL) {
            // the door's parser keeps a conversation's last 3,000 events (bina-claude's KEEP): say so when reached
            const events = await claudeAll(app, read);
            return { id, engine: "claude", app: app.id, events, more: false, capped: events.length >= 2990 };
          }
          const m = await claude(app, "GET", `/v1/sessions/${encodeURIComponent(read)}/messages?limit=${limit}`);
          return { id, engine: "claude", app: app.id, events: m?.events || [], more: !!m?.has_more };
        });
      } catch (e) {
        // the app could not be read, but what happened to the message handed over is known: that is the answer
        // (without `events`, so the screen keeps what it shows)
        if (s || f || real) return { id, engine: "claude", ...told };
        throw e;
      }
      return { ...r, ...told };
    }
    const events = await snapshotEvents(id, limit);
    return { id, engine: "azaria", events, more: limit < ALL && events.length >= limit };
  }

  // One message to Azaria: its text, the files attached to it (by the receipts their upload gave), and the
  // person's own time zone. rc.3's prompt parts: text · {file, receiptId} (an image's receipt enters as the image).
  async function promptAzaria(id, text, receipts, tz) {
    const content = [];
    if (text) content.push({ type: "text", text });
    for (const r of receipts) content.push({ type: "file", receiptId: r });
    if (!content.length) throw new UiError(400, "ההודעה ריקה");
    await rpc("session/prompt", { request: { requestId: randomUUID(), sessionId: id, mode: "queue", content, ...(tz ? { clientTimeZone: tz } : {}) } });
  }
  const receiptsOf = (b) => (Array.isArray(b.receipts) ? b.receipts.filter((r) => typeof r === "string" && r).slice(0, 20) : []);
  const tzOf = (b) => (typeof b.tz === "string" && /^[A-Za-z_]+(\/[A-Za-z0-9_+-]+)*$/.test(b.tz) ? b.tz : null);

  async function create(b) {
    const text = typeof b.text === "string" ? b.text.trim() : "";
    if (b.engine === "claude") {
      if (!text) throw new UiError(400, "ההודעה ריקה");
      // the Claude app it runs in: the one chosen (by its id, only one of this office's), else the first
      const apps = appsNow();
      const app = typeof b.app === "string" && b.app ? apps.find((a) => a.id === b.app) : apps[0];
      if (!app) throw new UiError(404, "אפליקציית Claude הזאת לא נמצאה בלשכה.");
      // the conversation opens AT ONCE: the app gives a promise of one (`pending-…`) in milliseconds, and its first
      // message — which drives the app's own screen — starts it in the background, under the same id
      // (asking for a promise sends nothing: if the app does not answer, it is «not answering», never «not known»)
      const r = await claude(app, "POST", "/v1/sessions", {}, 15000).catch(() => { throw new UiError(502, CLAUDE_SAYS["no-app"], "no-app"); });
      const pid = typeof r?.id === "string" ? r.id : "";
      if (!ID.test(pid)) throw new UiError(502, `אפליקציית Claude לא פתחה שיחה. ${SENT_NOTHING}`);
      owner.set(pid, app.id);
      inBackground(app, pid, text, () => claude(app, "POST", `/v1/sessions/${encodeURIComponent(pid)}/messages`, { text }));
      return { id: pid, engine: "claude", app: app.id, pending: true };
    }
    // `hold`: open the conversation without a message yet — its files are uploaded to it first
    if (!text && !b.hold) throw new UiError(400, "ההודעה ריקה");
    const created = await rpc("session/create", { request: { cwd: office, ...(b.preset ? { agentPreset: String(b.preset) } : {}) } });
    const id = created.sessionId;
    // A model chosen for this conversation (the picker's choice, or a fallback from a default without a key).
    if (b.model && b.model.provider && b.model.model) {
      await rpc("session/selectModel", { request: { sessionId: id, provider: String(b.model.provider), model: String(b.model.model), ...(b.model.effort ? { reasoningEffort: String(b.model.effort) } : {}) } });
    }
    if (text) await promptAzaria(id, text, [], tzOf(b));
    refreshList(true);
    return { id, engine: "azaria" };
  }

  async function send(id, b) {
    const text = typeof b.text === "string" ? b.text.trim() : "";
    const receipts = receiptsOf(b);
    if (engineOf(id) === "claude") {
      if (receipts.length) throw new UiError(501, "אי אפשר לצרף קבצים לשיחת Claude מכאן — צרפו אותם באפליקציה הרשמית.");
      if (!text) throw new UiError(400, "ההודעה ריקה");
      // accepted at once; handed to the app in the background (its read-back says how it went)
      const hint = typeof b.app === "string" ? b.app : null, target = realOf(id) || id;
      if (sending.has(id) || sending.has(target)) throw new UiError(409, "ההודעה הקודמת עוד נמסרת ל-Claude. אפשר לשלוח כשהיא נכנסת.");
      inBackground(appOf(target, hint), target, text,
        () => viaApp(target, hint, (app) => claude(app, "POST", `/v1/sessions/${encodeURIComponent(target)}/messages`, { text })));
      return { accepted: true, id: target, background: true };
    } else { await promptAzaria(id, text, receipts, tzOf(b)); refreshList(true); }
    return { accepted: true, id };
  }

  // A failed turn continued as it was (the harness's conversationContinuation): an empty prompt resumes it.
  async function retry(id) {
    if (engineOf(id) === "claude") throw new UiError(501, AZARIA_ONLY);
    await rpc("session/prompt", { request: { requestId: randomUUID(), sessionId: id, mode: "queue", content: [] } });
    refreshList(true);
    return { accepted: true, id };
  }

  // A sent message, edited: the conversation is forked just before it (the original stays as it was), and the
  // new words go to the fork — the Claude apps' edit-and-branch.
  async function edit(id, b) {
    if (engineOf(id) === "claude") throw new UiError(501, AZARIA_ONLY);
    const seq = Math.floor(Number(b.seq)), text = typeof b.text === "string" ? b.text.trim() : "";
    if (!(seq > 0) || !text) throw new UiError(400, "בקשה לא תקינה");
    const v = await rpc("session/fork", { request: { sessionId: id, atSeq: seq - 1 } });
    const fork = v?.sessionId || v;
    if (typeof fork !== "string") throw new UiError(502, "עזריה לא הצליח לפתוח את הגרסה החדשה של השיחה.");
    await promptAzaria(fork, text, [], tzOf(b));
    refreshList(true);
    return { id: fork, engine: "azaria", forked_from: id };
  }

  // The answer to what Azaria asked (ask_user_question): one item per question, by its id.
  async function answer(id, b) {
    if (engineOf(id) === "claude") throw new UiError(501, AZARIA_ONLY);
    const callId = typeof b.call_id === "string" ? b.call_id : "";
    const answers = Array.isArray(b.answers) ? b.answers.map((a) => ({ id: String(a.id), selected: Array.isArray(a.selected) ? a.selected.map(String) : [],
      ...(typeof a.custom === "string" && a.custom.trim() ? { custom: a.custom.trim() } : {}) })) : [];
    if (!callId || !answers.length) throw new UiError(400, "לא נבחרה תשובה");
    const ok = await rpc("userQuestions/answer", { agent: id, callId, answer: { answers } });
    if (ok === false) throw new UiError(409, "עזריה עוד מחכה לתשובה במסך אחר, או שהשאלה כבר נסגרה. נסו שוב בעוד רגע.");
    refreshList(true);
    return { accepted: true, id };
  }

  // A file the person attached, uploaded to Azaria's conversation before the message that carries it.
  async function uploadFile(req, id, q) {
    if (engineOf(id) === "claude") throw new UiError(501, "אי אפשר לצרף קבצים לשיחת Claude מכאן — צרפו אותם באפליקציה הרשמית.");
    const name = String(q.get("name") || "file").slice(0, 180).replace(/[\\/\0]/g, "_");
    const mediaType = /^[a-z]+\/[a-z0-9.+-]+$/i.test(q.get("type") || "") ? q.get("type") : "";
    const parts = [];
    let size = 0;
    for await (const chunk of req) { size += chunk.length; if (size > MAX_UPLOAD) throw new UiError(413, "הקובץ גדול מדי (עד 25MB)."); parts.push(chunk); }
    if (!size) throw new UiError(400, "הקובץ ריק");
    return upload(id, name, mediaType, Buffer.concat(parts));
  }

  // A conversation's own name, and putting it away (the harness archives; it has no delete) or back. These are
  // the harness's: a Claude conversation is renamed and archived in the official app itself.
  const AZARIA_ONLY = "את זה עושים לשיחת Claude באפליקציה הרשמית.";
  async function rename(id, b) {
    if (engineOf(id) === "claude") throw new UiError(501, AZARIA_ONLY);
    const title = typeof b.title === "string" ? b.title.trim().slice(0, 120) : "";
    if (!title) throw new UiError(400, "השם ריק");
    await rpc("session/rename", { request: { sessionId: id, title } });
    refreshList(true);
    return { id, title };
  }
  async function shelve(id, on) {
    if (engineOf(id) === "claude") throw new UiError(501, AZARIA_ONLY);
    const r = on
      ? await rpc("workspace/archiveSession", { request: { sessionId: id, stopActivity: true } })
      : await rpc("workspace/unarchiveSession", { request: { sessionId: id } });
    if (Array.isArray(r?.archivedSessionIds)) setArchived(r.archivedSessionIds);
    return { id, archived: on };
  }

  // The model of a conversation that already runs, switched as in the Claude apps: the next turn answers on it.
  async function switchModel(id, b) {
    if (engineOf(id) === "claude") throw new UiError(501, "החלפת מודל בשיחת Claude נעשית בבורר שבתיבת הכתיבה.");
    const provider = typeof b.provider === "string" ? b.provider : "", model = typeof b.model === "string" ? b.model : "";
    if (!provider || !model) throw new UiError(400, "לא נבחר מודל");
    await rpc("session/selectModel", { request: { sessionId: id, provider, model, ...(b.effort ? { reasoningEffort: String(b.effort) } : {}) } });
    refreshList(true);
    return { id, model: { provider, model } };
  }

  async function cancel(id, hint) {
    if (engineOf(id) === "claude") {
      const t = realOf(id) || id;
      // what a refused stop means is not what a refused message means («send again» would be wrong here)
      if (sending.has(id) || sending.has(t)) throw new UiError(409, "ההודעה עוד נמסרת ל-Claude — אפשר לעצור כשהיא נכנסת.", "handing");
      await viaApp(t, hint, (app) => claude(app, "POST", `/v1/sessions/${encodeURIComponent(t)}/cancel`, {})).catch((e) => {
        if (e instanceof UiError && CANCEL_SAYS[e.code]) throw new UiError(e.status === 504 ? 504 : 409, CANCEL_SAYS[e.code], e.code);
        throw e;
      });
    }
    else { await rpc("session/cancel", { request: { sessionId: id } }); refreshList(true); }
    return { accepted: true, id };
  }

  // The open conversation, live (Server-Sent Events, from `since`): Azaria's own follow — durable events and the
  // answer's text as it is written — or the Claude door's stream (it re-reads the transcript every second).
  async function stream(req, res, id, q) {
    const n = Math.floor(Number(q.get("since") ?? -1));
    const since = Number.isFinite(n) ? n : -1;
    if (engineOf(id) !== "claude") {
      if (!follow) { res.writeHead(501); res.end(); return; }
      await follow(res, id, new URLSearchParams({ since: String(since), history: "60" }));
      return;
    }
    const ctl = new AbortController();
    req.on("close", () => ctl.abort());
    try {
      const read = realOf(id) || id;                                 // a conversation opened here: its real id once it started
      const app = appOf(read, q.get("app"));
      const token = await tokenOf(app);
      const r = await fetch(`${app.api}/v1/sessions/${encodeURIComponent(read)}/events?since=${since}`,
        { headers: { authorization: `Bearer ${token}` }, signal: ctl.signal });
      if (r.status === 401) claudeTokens.delete(app.id);
      if (!r.ok || !r.body) { res.writeHead(502, { "content-type": "text/plain; charset=utf-8" }); res.end(); return; }
      res.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store", connection: "keep-alive", "x-accel-buffering": "no" });
      for await (const chunk of r.body) res.write(chunk);
    } catch { /* the reader went away, or the door did: the screen reopens from its last event */ }
    try { res.end(); } catch { /* closed */ }
  }

  async function readJson(req) {
    if (!/^application\/json\b/i.test(String(req.headers["content-type"] || ""))) throw new UiError(415, "בקשה לא תקינה");
    const parts = [];
    let size = 0;
    for await (const chunk of req) { size += chunk.length; if (size > 400000) throw new UiError(413, "ההודעה ארוכה מדי"); parts.push(chunk); }
    try { return size ? JSON.parse(Buffer.concat(parts).toString("utf8")) : {}; } catch { throw new UiError(400, "בקשה לא תקינה"); }
  }

  function serveFile(res, name) {
    const file = path.join(WEB, name);
    if (!existsSync(file)) { res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }); res.end("not found"); return; }
    res.writeHead(200, { "content-type": FILES[name], "cache-control": "no-cache", "x-content-type-options": "nosniff" });
    res.end(readFileSync(file));
  }

  /** The screen and its door. Answers null when the path is not the screen's (agent.v1 goes on). */
  return async function handle(req, res, p, q) {
    const isUi = p === "/" || p === "/index.html" || p.startsWith("/app/") || p === "/ui" || p.startsWith("/ui/");
    if (!isUi) return null;
    if (!(await peerAllowed(req))) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("this screen is reached through the office's edge");
      return true;
    }
    if (!EDGE || !String(req.headers[EDGE] || "").trim()) {
      res.writeHead(401, { "content-type": "text/plain; charset=utf-8" });
      res.end("sign in to the office first");
      return true;
    }
    const site = req.headers["sec-fetch-site"];
    if (p.startsWith("/ui") && site !== undefined && site !== "same-origin" && site !== "none") {
      res.writeHead(403, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: "not from this page" }));
      return true;
    }
    if (req.method === "GET" && (p === "/" || p === "/index.html")) { serveFile(res, "index.html"); return true; }
    if (req.method === "GET" && p.startsWith("/app/")) {
      const name = p.slice(5);
      if (!(name in FILES) || name === "index.html") { res.writeHead(404); res.end(); return true; }
      serveFile(res, name);
      return true;
    }
    const live = /^\/ui\/sessions\/([^/]+)\/stream$/.exec(p);
    if (live && req.method === "GET" && ID.test(live[1])) {
      try { await stream(req, res, live[1], q); } catch { try { res.end(); } catch { /* closed */ } }
      return true;
    }
    let status = 200, payload;
    try {
      const parts = p.split("/").filter(Boolean).slice(1);          // after "ui"
      if (req.method === "GET" && parts[0] === "sessions" && parts.length === 1) payload = await sessions();
      else if (req.method === "GET" && parts[0] === "models" && parts.length === 1) payload = await models();
      else if (req.method === "GET" && parts[0] === "providers" && parts.length === 1) payload = await providers();
      // a credential write is JSON or nothing (readJson refuses anything else, and it is not caught here)
      else if (req.method === "POST" && parts[0] === "providers" && parts.length === 3 && parts[2] === "vault" && ID.test(parts[1])) {
        await readJson(req);
        payload = await bindKey(parts[1]);
      }
      else if (req.method === "POST" && parts[0] === "sessions" && parts.length === 1) { payload = await create(await readJson(req)); status = 201; }
      else if (parts[0] === "sessions" && parts.length === 3 && ID.test(parts[1])) {
        const id = parts[1];
        if (req.method === "GET" && parts[2] === "messages") {
          const lim = q.get("limit") === "all" ? ALL : Math.max(1, Math.min(500, Math.floor(Number(q.get("limit"))) || 200));
          payload = await messages(id, lim, q.get("app"));
        }
        else if (req.method === "POST" && parts[2] === "messages") { payload = await send(id, await readJson(req)); status = 202; }
        else if (req.method === "POST" && parts[2] === "cancel") { const cb = await readJson(req).catch(() => ({})); payload = await cancel(id, typeof cb.app === "string" ? cb.app : null); status = 202; }
        else if (req.method === "POST" && parts[2] === "model") payload = await switchModel(id, await readJson(req));
        else if (req.method === "POST" && parts[2] === "rename") payload = await rename(id, await readJson(req));
        else if (req.method === "POST" && parts[2] === "answer") payload = await answer(id, await readJson(req));
        else if (req.method === "POST" && parts[2] === "retry") { await readJson(req).catch(() => ({})); payload = await retry(id); status = 202; }
        else if (req.method === "POST" && parts[2] === "edit") { payload = await edit(id, await readJson(req)); status = 201; }
        else if (req.method === "POST" && parts[2] === "upload") { payload = await uploadFile(req, id, q); status = 201; }
        else if (req.method === "POST" && (parts[2] === "archive" || parts[2] === "unarchive")) {
          await readJson(req).catch(() => ({}));
          payload = await shelve(id, parts[2] === "archive");
        }
        else throw new UiError(404, "אין כאן דבר כזה");
      } else throw new UiError(404, "אין כאן דבר כזה");
    } catch (e) {
      status = e instanceof UiError ? e.status : (e.status || 502);
      // the harness's own words (English, a code) go to the log; the person reads what it means
      if (!(e instanceof UiError)) console.error(`[bina-ds] ui: ${req.method} ${p}: ${e && (e.code || "")} ${e && e.message}`);
      payload = { error: e instanceof UiError ? e.message : "עזריה לא הצליח לבצע את זה כרגע. אפשר לנסות שוב." };
    }
    res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
    res.end(JSON.stringify(payload));
    return true;
  };
}
