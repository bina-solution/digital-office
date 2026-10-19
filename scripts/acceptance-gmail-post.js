// Post a seed payload (/tmp/inject_payload.json: [{raw_base64,labels,folder}]) to gmail-imap /append.
// Usage (inside n8n container): node _gmail_post.js
const http = require("http"), fs = require("fs");
const items = JSON.parse(fs.readFileSync("/tmp/inject_payload.json", "utf8"));
function post(b) {
  return new Promise((res) => {
    const r = http.request({ host: "gmail-imap", port: 8970, path: "/append", method: "POST", headers: { "Content-Type": "application/json" } },
      x => { let d = ""; x.on("data", c => d += c); x.on("end", () => res({ code: x.statusCode, body: d })); });
    r.on("error", e => res({ code: 0, body: String(e) })); r.write(b); r.end();
  });
}
(async () => {
  let ok = 0, fail = 0;
  for (const it of items) {
    const r = await post(JSON.stringify({ raw_base64: it.raw_base64, labels: it.labels, folder: it.folder || "INBOX" }));
    if (r.code === 200) ok++; else { fail++; console.log("FAIL", r.code, r.body.slice(0, 60)); }
  }
  console.log(`append ok=${ok} fail=${fail}`);
})();
