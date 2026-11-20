// DGO-2036: where a conversation can run — the screen's /ui/providers door. Each cloud provider says whether its
// key is there and whether it comes from the office's secrets; each computer with a local model is named as its
// link named it; and the one write — a provider's key taken from the secrets — writes the vault POINTER for one of
// the three declared connections and nothing else. Run: node test_providers.mjs
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

process.env.DSH_TRUST_PROXY_AUTH_HEADER = "x-test-signed-in";
process.env.BINA_CLAUDE_API = "http://127.0.0.1:9";          // no Claude app here: it answers «not installed» at once
process.env.BINA_DS_UI_PEERS = "none.invalid";
const { createUi } = await import("./ui.mjs");

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};

// an office checkout with the registry the link wrote for the Dell
const office = mkdtempSync(path.join(tmpdir(), "office-"));
mkdirSync(path.join(office, ".generated", "registry"), { recursive: true });
writeFileSync(path.join(office, ".generated", "registry", "remote.portable-ubuntu.ollama.json"),
  JSON.stringify({ alias: "ollama", remote: { office: "portable-ubuntu", label: { he: "Dell", en: "Dell" } } }));
// our herd (the compiled registry): the Dell is ours under its alias; exampleu is not ours, and calls itself what we call us
writeFileSync(path.join(office, ".generated", "registry", "herd.offices.json"),
  JSON.stringify({ offices: { macbook: { aliases: [] }, dell: { aliases: ["portable-ubuntu", "portable"] } } }));
writeFileSync(path.join(office, ".generated", "registry", "remote.exampleu.ollama.json"),
  JSON.stringify({ alias: "ollama", remote: { office: "exampleu", label: { he: "המחשב של הלשכה", en: "This office" } } }));

const calls = [];
const catalog = {
  groups: [
    { id: "deepseek", name: "DeepSeek", models: [{ id: "deepseek-v4-pro" }, { id: "deepseek-v4-flash" }] },
    { id: "dgo-ollama-local", name: "Ollama", models: [{ id: "qwen3.5:4b" }] },
    { id: "dgo-ollama-portable-ubuntu", name: "Ollama", models: [{ id: "qwen3.5:4b" }, { id: "gemma4:12b" }] },
    { id: "dgo-ollama-exampleu", name: "Ollama", models: [{ id: "qwen3.5:4b" }] },
    { id: "dgo-ollama-../../etc", name: "x", models: [{ id: "m" }] },   // never a computer: not a route name
  ],
  default: { provider: "deepseek", model: "deepseek-v4-pro" },
  routableProviders: ["deepseek", "dgo-ollama-local"],
};
const rpc = async (method, args) => {
  calls.push([method, args]);
  if (method === "session/modelCatalog") return catalog;
  if (method === "credentials/describe") {
    const all = {
      DEEPSEEK_API_KEY: { configured: true, source: "office-vault:deepseek-key", writable: true },
      OPENAI_API_KEY: { configured: false, source: "env", writable: true },
      ANTHROPIC_API_KEY: { configured: true, source: "file", writable: true },   // a key typed into the full interface
    };
    return Object.fromEntries(args.refs.map((r) => [r, all[r]]));
  }
  if (method === "credentials/set") return undefined;
  throw new Error(`unexpected ${method}`);
};
const handle = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, rpc,
                          refreshList: () => {}, office });

// one request to the door, as the office's edge forwards it
async function call(method, p, { body, json = true, site = "same-origin" } = {}) {
  const chunks = body === undefined ? [] : [Buffer.from(typeof body === "string" ? body : JSON.stringify(body))];
  const req = {
    method, socket: { remoteAddress: "127.0.0.1" },
    headers: { "x-test-signed-in": "owner", "sec-fetch-site": site, ...(json && body !== undefined ? { "content-type": "application/json" } : {}) },
    async *[Symbol.asyncIterator]() { for (const c of chunks) yield c; },
    on() {},
  };
  const res = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = t ? String(t) : ""; }, write() {} };
  const u = new URL(p, "http://x");
  await handle(req, res, u.pathname, u.searchParams);
  let data = null;
  try { data = JSON.parse(res.text); } catch { /* not JSON */ }
  return { status: res.status, data };
}

const got = await call("GET", "/ui/providers");
check(got.status, 200, "GET /ui/providers answers");
check(got.data.cloud.map((c) => [c.id, c.configured, c.vault, c.routable, c.models]),
  [["deepseek", true, true, true, 2], ["openai", false, false, false, 0], ["anthropic", true, false, false, 0]],
  "cloud: the key's presence, whether it comes from the secrets, whether it can run, its models");
check(got.data.cloud.map((c) => c.connection), ["deepseek-key", "openai-key", "anthropic-key"], "each provider's connection");
check(got.data.local.map((l) => [l.id, l.computer.name, l.computer.here, l.computer.ours, l.models.length, l.routable]),
  [["dgo-ollama-local", "המחשב של הלשכה", true, true, 1, true], ["dgo-ollama-portable-ubuntu", "Dell", false, true, 2, false],
   ["dgo-ollama-exampleu", "exampleu · מחוץ לעדר", false, false, 1, false]],
  "local: this office; the Dell (ours, by its alias) by its own label; an office outside the herd by its id, never by the name it gave itself; a route that is not a name is no computer");
check(got.data.claude.installed, false, "the Claude app's state rides along");
check(calls.find((c) => c[0] === "credentials/describe")[1], { refs: ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"] },
  "the three references are described in one call — no value is read");

const models = await call("GET", "/ui/models");
check(models.data.computers, { "dgo-ollama-local": "המחשב של הלשכה", "dgo-ollama-portable-ubuntu": "Dell", "dgo-ollama-exampleu": "exampleu · מחוץ לעדר" },
  "/ui/models names each computer");

calls.length = 0;
const bound = await call("POST", "/ui/providers/openai/vault", { body: {} });
check([bound.status, bound.data], [200, { id: "openai", connection: "openai-key" }], "bind: the key is taken from the secrets");
check(calls, [["credentials/describe", { refs: ["OPENAI_API_KEY"] }], ["credentials/set", { ref: "OPENAI_API_KEY", value: "vault:openai-key" }]],
  "…by reading where its key comes from, then writing the vault pointer — never a key");

// a harness that answers without saying whether the key is there (no view for it): unknown, nothing written
const shy = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, refreshList: () => {}, office,
                       rpc: async (method, args) => { calls.push([method, args]); if (method === "credentials/describe") return {}; throw new Error(`unexpected ${method}`); } });
calls.length = 0;
{
  const res = { status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = String(t || ""); }, write() {} };
  await shy({ method: "POST", socket: { remoteAddress: "127.0.0.1" }, on() {}, headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin", "content-type": "application/json" },
              async *[Symbol.asyncIterator]() { yield Buffer.from("{}"); } }, res, "/ui/providers/openai/vault", new URLSearchParams());
  check([res.status, calls.map((c) => c[0])], [503, ["credentials/describe"]], "no view for the key: unknown, never «no key» — nothing written");
}

calls.length = 0;
const kept = await call("POST", "/ui/providers/anthropic/vault", { body: {} });
check([kept.status, calls.map((c) => c[0])], [409, ["credentials/describe"]], "a key that works from elsewhere is never replaced by the pointer");

calls.length = 0;
const evil = await call("POST", "/ui/providers/evil/vault", { body: {} });
check([evil.status, calls.length], [404, 0], "an unknown provider is refused, nothing written");
const proto = await call("POST", "/ui/providers/__proto__/vault", { body: {} });
check([proto.status, calls.length], [404, 0], "…and so is a name from the object's prototype");
const form = await call("POST", "/ui/providers/openai/vault", { body: "x=1", json: false });
check([form.status, calls.length], [415, 0], "a write that is not JSON is refused, nothing written");
const cross = await call("POST", "/ui/providers/openai/vault", { body: {}, site: "cross-site" });
check([cross.status, calls.length], [403, 0], "a write from another site is refused, nothing written");

// a harness that cannot say where a key comes from: nothing is written, and the sheet is told «unknown», not «no»
const blind = createUi({ listSessions: async () => [], snapshotEvents: async () => [], prompt: async () => {}, refreshList: () => {}, office,
                         rpc: async (method) => { calls.push([method]); throw new Error("harness down"); } });
calls.length = 0;
{
  const req = (method, p, body) => ({ method, socket: { remoteAddress: "127.0.0.1" }, on() {},
    headers: { "x-test-signed-in": "owner", "sec-fetch-site": "same-origin", ...(body ? { "content-type": "application/json" } : {}) },
    async *[Symbol.asyncIterator]() { if (body) yield Buffer.from(body); } });
  const res = () => ({ status: 0, text: "", writeHead(s) { this.status = s; }, end(t) { this.text = String(t || ""); }, write() {} });
  const r1 = res();
  await blind(req("POST", "/ui/providers/openai/vault", "{}"), r1, "/ui/providers/openai/vault", new URLSearchParams());
  check([r1.status, calls.map((c) => c[0])], [503, ["credentials/describe"]], "unknown where the key comes from: refused, nothing written");
  const r2 = res();
  await blind(req("GET", "/ui/providers"), r2, "/ui/providers", new URLSearchParams());
  const p = JSON.parse(r2.text);
  check(p.cloud.map((c) => [c.configured, c.vault, c.routable]), [[null, null, null], [null, null, null], [null, null, null]],
    "a harness that does not answer: every provider «unknown», none «not connected»");
  check(p.keys_read, false, "…and the sheet is told the keys were not read");
}

rmSync(office, { recursive: true, force: true });
console.log(failed ? `FAILED ${failed}` : "PASS");
process.exit(failed ? 1 : 0);
