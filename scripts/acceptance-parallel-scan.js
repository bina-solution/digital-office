// Gap-A parallel registration (orchestration-level, no workflow edits): fire ALL sync units
// CONCURRENTLY via REST /run + pinData on the unit's executeWorkflowTrigger. The 5 syncs are
// DISJOINT (different labels/folders) so concurrent claiming is safe. Each /run returns immediately
// (async execution) -> true parallel registration across workers, vs the scanner's serial mode=each.
// Usage (inside n8n container): REG=<sync_registry json> EM=.. PW=.. node _parallel_scan.js
const http = require("http");
function req(o, b) { return new Promise(r => { const x = http.request(o, s => { let d = ""; s.on("data", c => d += c); s.on("end", () => r({ code: s.statusCode, headers: s.headers, body: d })); }); x.on("error", e => r({ code: 0, body: String(e) })); if (b) x.write(b); x.end(); }); }

function buildUnits(reg) {
  const units = [];
  for (const s of reg) {
    if (!s.processor_wf || String(s.processor_wf).startsWith("TBD")) continue;
    const b = s.batch || {};
    if (s.source === "drive") {
      for (const p of (s.pairs || [])) units.push({ source: "drive", sync_name: s.name, type_hint: s.type_hint ?? null, processor_wf: s.processor_wf, take: b.take || 50, chunk: b.chunk || 25, to_sync: p.to_sync, in_progress: p.in_progress, synced: p.synced, failed: p.failed });
    } else if (s.source === "gmail") {
      units.push({ source: "gmail", sync_name: s.name, type_hint: s.type_hint ?? null, processor_wf: s.processor_wf, take: b.take || 50, chunk: b.chunk || 25, labels: s.labels, dest_folder: s.dest_folder, search_query: s.search_query, search_extra: s.search_extra, search_take: s.search_take || 10, claim_label: s.claim_label || (s.labels && s.labels.in_progress) || "Label_13" });
    }
  }
  return units;
}

(async () => {
  const reg = JSON.parse(process.env.REG);
  const units = buildUnits(reg);
  const l = await req({ host: "localhost", port: 5678, path: "/rest/login", method: "POST", headers: { "Content-Type": "application/json" } }, JSON.stringify({ emailOrLdapLoginId: process.env.EM, password: process.env.PW }));
  const ck = (l.headers["set-cookie"] || []).map(c => c.split(";")[0]).join("; ");
  const gw = await req({ host: "localhost", port: 5678, path: "/rest/workflows/SyncScanUnit0001", method: "GET", headers: { Cookie: ck } });
  const wf = JSON.parse(gw.body).data;
  const trg = "When Executed by Another Workflow";
  // fire all units concurrently (each /run returns an executionId immediately = async/parallel)
  const fires = units.map(u => req({ host: "localhost", port: 5678, path: "/rest/workflows/SyncScanUnit0001/run", method: "POST", headers: { "Content-Type": "application/json", Cookie: ck } },
    JSON.stringify({ workflowData: wf, startNodes: [{ name: trg }], triggerToStartFrom: { name: trg }, pinData: { [trg]: [{ json: u }] } })
  ).then(r => `${u.sync_name}:${r.code}`));
  console.log("parallel-fired:", (await Promise.all(fires)).join("  "));
})();
