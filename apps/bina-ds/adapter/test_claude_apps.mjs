// DGO-2036: every Claude Desktop of the office in the one list — the first app (`bina-claude`) and each instance of
// it (DGO-1920: `bina-claude-2`, …, each its own account). The list merges them, a conversation runs in the app the
// person chose and goes on there, an app that is not this office's is refused, and the apps are found from the
// compiler's declaration (instances/<id>/app.json, instance_of: bina-claude) — nothing else. Two fake agent.v1
// apps stand in for the real ones. Run: node test_claude_apps.mjs
import http from "node:http";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
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

// a fake agent.v1 app: its sessions, its sign-in, and every call it was asked (with the token it was asked with)
function fakeApp(name, { signedIn = true, sessions = [] } = {}) {
  const state = { calls: [], sessions: [...sessions], n: 0 };
  const server = http.createServer(async (req, res) => {
    let body = "";
    for await (const c of req) body += c;
    state.calls.push([req.method, req.url, req.headers.authorization || ""]);
    const send = (code, j) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(j)); };
    if (req.url === "/v1/health") return send(200, { ok: true, login: { logged_in: signedIn }, active: 0 });
    if (req.method === "GET" && req.url === "/v1/sessions") return send(200, { sessions: state.sessions });
    if (req.method === "POST" && req.url === "/v1/sessions") {
      const id = `local_${name}-${++state.n}`;
      state.sessions.push({ id, title: JSON.parse(body).text, updated_at: new Date().toISOString() });
      return send(201, { id });
    }
    const m = /^\/v1\/sessions\/([^/]+)\/(messages|cancel)/.exec(req.url);
    if (m) {
      // as bina-claude does: a conversation that is not this app's is a 404, and nothing is driven
      if (!state.sessions.some((s) => s.id === decodeURIComponent(m[1]))) return send(404, { error: "no such session", code: "no-session" });
      return send(req.method === "POST" ? 202 : 200, req.method === "POST" ? { accepted: true } : { events: [] });
    }
    return send(404, { error: "no" });
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r({ ...state, state, server, api: `http://127.0.0.1:${server.address().port}` })));
}

const one = await fakeApp("one", { sessions: [{ id: "local_one-old", title: "בדיקת הגיבוי", updated_at: "2026-11-19T10:00:00Z" }] });
const two = await fakeApp("two", { sessions: [{ id: "local_two-old", title: "תקציב 2027", updated_at: "2026-11-19T11:00:00Z" }] });
const three = await fakeApp("three", { signedIn: false });
process.env.BINA_CLAUDE_API = one.api;                                  // the first app's address, read when the module loads
const { createUi } = await import("./ui.mjs");
const office = mkdtempSync(path.join(tmpdir(), "office-"));
const apps = [
  { id: "bina-claude", key: "", title: null, api: one.api, container: "c1" },
  { id: "bina-claude-2", key: "2", title: { he: "קלוד דסקטופ 2" }, api: two.api, container: "c2" },
  { id: "bina-claude-3", key: "3", title: null, api: three.api, container: "c3" },
];
const handle = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {},
                          rpc: async () => ({ groups: [] }), refreshList: () => {}, office,
                          claudeApps: () => apps, claudeToken: async (app) => `tok-${app.id}` });

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
const lastCall = (app) => app.state.calls[app.state.calls.length - 1];
// a message is handed to its app in the background (DGO-2044): the checks wait for the app to be asked
const posted = (app, u) => app.state.calls.some(([m, x]) => m === "POST" && x === u);
async function until(cond, ms = 4000) {
  const t = Date.now();
  while (Date.now() - t < ms) { if (await cond()) return true; await new Promise((r) => setTimeout(r, 10)); }
  return !!(await cond());
}
// …and for the door to be done with it (the next message of a conversation waits for the one before it)
const settled = (id) => until(async () => {
  const r = await call("GET", `/ui/sessions/${encodeURIComponent(id)}/messages?limit=5`);
  return r.status === 200 && !r.data.sending;                         // a read that answered, and says nothing is on its way
});

const list = await call("GET", "/ui/sessions");
check(list.data.sessions.map((s) => [s.id, s.app, s.app_key]), [["local_two-old", "bina-claude-2", "2"], ["local_one-old", "bina-claude", null]],
  "one list from every Claude app, each row naming its app");
check(Object.keys(list.data.engines.claudes), ["bina-claude", "bina-claude-2", "bina-claude-3"], "each app says whether it answered");
check(lastCall(two)[2], "Bearer tok-bina-claude-2", "each app is asked with its own token");

const models = await call("GET", "/ui/models");
check(models.data.claudes.map((c) => [c.id, c.key, c.signed_in]), [["bina-claude", "", true], ["bina-claude-2", "2", true], ["bina-claude-3", "3", false]],
  "/ui/models: every Claude app, its key and whether it is signed in");
check(models.data.claude.id, "bina-claude", "…and `claude` is still the first app");

const made = await call("POST", "/ui/sessions", { engine: "claude", app: "bina-claude-2", text: "שלום" });
check([made.status, made.data.app], [201, "bina-claude-2"], "a conversation starts in the app the person chose");
await settled(made.data.id);
check([posted(two, "/v1/sessions"), posted(two, `/v1/sessions/${made.data.id}/messages`), posted(one, "/v1/sessions")], [true, true, false],
  "…in that app, not the first: opened there, and its message handed to it");
const twoPosts = () => two.state.calls.filter(([m, x]) => m === "POST" && x === `/v1/sessions/${made.data.id}/messages`).length;
const sent = await call("POST", `/ui/sessions/${made.data.id}/messages`, { text: "ועוד" });
await settled(made.data.id);
check([sent.status, twoPosts()], [202, 2], "its next message goes to the same app");
const old = await call("POST", "/ui/sessions/local_one-old/messages", { text: "המשך" });
await settled("local_one-old");
check([old.status, posted(one, "/v1/sessions/local_one-old/messages")], [202, true], "a listed conversation goes to the app that listed it");

const before = [one, two, three].map((a) => a.state.calls.length);
const stranger = await call("POST", "/ui/sessions", { engine: "claude", app: "bina-claude-9", text: "x" });
check([stranger.status, [one, two, three].map((a) => a.state.calls.length)], [404, before], "an app that is not this office's is refused, nobody asked");
const plain = await call("POST", "/ui/sessions", { engine: "claude", text: "בלי בחירה" });
check([plain.status, plain.data.app], [201, "bina-claude"], "no choice: the first app, as before instances");
await settled(plain.data.id);                                           // its message reached the first app

// a door that knows nothing yet (restarted; app 2's list slow): the screen's `app` decides, else each app is asked
const fresh = (h) => createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, rpc: async () => ({ groups: [] }),
                                refreshList: () => {}, office, claudeApps: () => apps, claudeToken: async (app) => `tok-${app.id}` });
async function callOn(h, method, p, body) {
  const chunks = body === undefined ? [] : [Buffer.from(JSON.stringify(body))];
  const req = { method, socket: { remoteAddress: "127.0.0.1" }, on() {},
                headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin", ...(body !== undefined ? { "content-type": "application/json" } : {}) },
                async *[Symbol.asyncIterator]() { for (const c of chunks) yield c; } };
  const res = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = t ? String(t) : ""; }, write() {} };
  const u = new URL(p, "http://x");
  await h(req, res, u.pathname, u.searchParams);
  return res.status;
}
const n1 = one.state.calls.length;
const hinted = await callOn(fresh(), "POST", "/ui/sessions/local_two-old/messages", { text: "המשך", app: "bina-claude-2" });
await until(() => posted(two, "/v1/sessions/local_two-old/messages"));
check([hinted, posted(two, "/v1/sessions/local_two-old/messages"), one.state.calls.length === n1], [202, true, true],
  "the screen's `app` goes first: the first app is not even asked");
const probed = await callOn(fresh(), "GET", "/ui/sessions/local_two-old/messages?limit=50");
check([probed, lastCall(one)[1], lastCall(two)[1]], [200, "/v1/sessions/local_two-old/messages?limit=50", "/v1/sessions/local_two-old/messages?limit=50"],
  "no `app`, nothing listed yet: the first app answers 404, the next one has it");
const lost = await callOn(fresh(), "GET", "/ui/sessions/local_nobody/messages?limit=50");
check(lost, 404, "a conversation no app has stays a 404");

// the apps come from the compiler's declaration, and only from it
mkdirSync(path.join(office, "instances", "bina-claude-2"), { recursive: true });
writeFileSync(path.join(office, "instances", "bina-claude-2", "app.json"), JSON.stringify({ id: "bina-claude-2", instance_of: "bina-claude", instance_key: "2", title: { he: "קלוד דסקטופ 2" } }));
mkdirSync(path.join(office, "instances", "bina-claude-x"), { recursive: true });
writeFileSync(path.join(office, "instances", "bina-claude-x", "app.json"), JSON.stringify({ id: "something-else", instance_of: "bina-claude" }));
mkdirSync(path.join(office, "instances", "bina-claude-y"), { recursive: true });
writeFileSync(path.join(office, "instances", "bina-claude-y", "app.json"), JSON.stringify({ id: "bina-claude-y", instance_of: "browser42" }));
mkdirSync(path.join(office, "instances", "notes-2"), { recursive: true });
writeFileSync(path.join(office, "instances", "notes-2", "app.json"), JSON.stringify({ id: "notes-2", instance_of: "notes" }));
// a declared instance that is turned off keeps its folder; the compiler's resolved order does not name it
mkdirSync(path.join(office, "instances", "bina-claude-4"), { recursive: true });
writeFileSync(path.join(office, "instances", "bina-claude-4", "app.json"), JSON.stringify({ id: "bina-claude-4", instance_of: "bina-claude", instance_key: "4" }));
mkdirSync(path.join(office, ".generated"), { recursive: true });
writeFileSync(path.join(office, ".generated", "resolved.json"), JSON.stringify({ order: ["console", "bina-claude", "bina-claude-2", "bina-ds"] }));
const found = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, rpc: async () => ({ groups: [] }),
                         refreshList: () => {}, office, claudeToken: async (app) => `tok-${app.id}` });
const r = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = String(t || ""); }, write() {} };
await found({ method: "GET", socket: { remoteAddress: "127.0.0.1" }, on() {}, headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin" },
              async *[Symbol.asyncIterator]() {} }, r, "/ui/models", new URLSearchParams());
check(JSON.parse(r.text).claudes.map((c) => [c.id, c.key]), [["bina-claude", ""], ["bina-claude-2", "2"]],
  "found from instances/: an instance of bina-claude whose id is its folder's and that runs — not a mismatched id, not another app's, not one turned off");

for (const a of [one, two, three]) a.server.close();
rmSync(office, { recursive: true, force: true });
console.log(failed ? `FAILED ${failed}` : "PASS");
process.exit(failed ? 1 : 0);
