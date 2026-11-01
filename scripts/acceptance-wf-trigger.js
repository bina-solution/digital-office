// Trigger an n8n workflow by id via the internal REST API (manual run from its trigger node).
// Usage (inside n8n container): node _wf_trigger.js <workflowId>
// Env: N8N_OWNER_EMAIL, N8N_OWNER_PASSWORD
const http = require("http");
const wfId = process.argv[2];
function req(o, b) {
  return new Promise((res) => {
    const r = http.request(o, x => { let d = ""; x.on("data", c => d += c); x.on("end", () => res({ code: x.statusCode, headers: x.headers, body: d })); });
    r.on("error", e => res({ code: 0, body: String(e) })); if (b) r.write(b); r.end();
  });
}
(async () => {
  const l = await req({ host: "localhost", port: 5678, path: "/rest/login", method: "POST", headers: { "Content-Type": "application/json" } },
    JSON.stringify({ emailOrLdapLoginId: process.env.N8N_OWNER_EMAIL, password: process.env.N8N_OWNER_PASSWORD }));
  const ck = (l.headers["set-cookie"] || []).map(c => c.split(";")[0]).join("; ");
  const g = await req({ host: "localhost", port: 5678, path: "/rest/workflows/" + wfId, method: "GET", headers: { Cookie: ck } });
  const wf = JSON.parse(g.body).data;
  const s = (wf.nodes.find(n => /Schedule|Trigger|When/.test(n.name)) || wf.nodes[0]).name;
  const run = await req({ host: "localhost", port: 5678, path: "/rest/workflows/" + wfId + "/run", method: "POST", headers: { "Content-Type": "application/json", Cookie: ck } },
    JSON.stringify({ workflowData: wf, startNodes: [{ name: s }], triggerToStartFrom: { name: s } }));
  console.log(wfId, "run", run.code, run.body.slice(0, 80));
})();
