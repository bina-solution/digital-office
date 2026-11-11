// DGO-954: a local session's file tools write only under /tmp/ (and LLM_ROUTES_WRITE_ROOTS). Measured 2026-10-21
// 13:06 UTC on the HP: asked to comment on DGO-908, qwen3:1.7b called `edit` with replace_all on
// apps/project-pln/plans/office.yaml. The relay (llm-routes.mjs `labeller`) turns such a call, before the
// harness sees it, into a bash call that fails and says why — or, with no bash tool, moves its path under /tmp.
// This test reads `labeller` and the constants it uses out of llm-routes.mjs itself (the file runs a pass on
// import, as test_preset_pairing.mjs says) and runs it on the answers a model gives.
// Run: node test_write_confine.mjs   (exit 1 on a failed check; G72 runs it).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "llm-routes.mjs"), "utf8");
const pick = (re, what) => {
  const m = re.exec(src);
  if (!m) { console.error(`FAIL could not find ${what} in llm-routes.mjs`); process.exit(1); }
  return m[0];
};
const parts = [
  pick(/^const LABELLED = .*$/m, "LABELLED"),
  pick(/^const TIMEOUT_MS = .*$/m, "TIMEOUT_MS"),
  pick(/^const WRITE_TOOLS = [\s\S]*?^const writable = [\s\S]*?;\n/m, "WRITE_TOOLS … writable"),
  pick(/^function labeller\([\s\S]*?\n}\n/m, "function labeller"),
];
// eslint-disable-next-line no-new-func
const load = (env = {}) => new Function("path", "process", `${parts.join("\n")}\nreturn labeller;`)(path.posix, { env });
const labeller = load();

let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"} ${what}`); if (!ok) failed += 1; };
const tool = (name, props = {}, required = []) => ({ type: "function", function: { name, parameters: { type: "object", properties: props, required } } });
const BASH = tool("bash", { command: {}, description: {}, timeoutMs: { maximum: 600000 } }, ["command", "description"]);
const FULL = { tools: [BASH, tool("write", { file_path: {}, content: {} }), tool("edit", { file_path: {} }), tool("read", { file_path: {} }),
                       tool("glob", { path: {} }), tool("upload", { path: {}, file_path: {} }), tool("ticket", { title: {} })] };
// one answer, as the harness gets it (non-streamed), with one call
const answer = (name, args) => ({ choices: [{ message: { tool_calls: [{ index: 0, function: { name, arguments: typeof args === "string" ? args : JSON.stringify(args) } }] } }] });
const callOf = (doc) => doc.choices[0].message.tool_calls[0].function;
const run = (req, name, args, lab = labeller) => { const doc = answer(name, args); lab(req).fixDoc(doc); return callOf(doc); };
const refused = (f) => f.name === "bash" && /Not written/.test(JSON.parse(f.arguments).command) && /exit 1/.test(JSON.parse(f.arguments).command);

// 1. the measured call: an edit of the office's plan file, relative to the session's cwd (the checkout)
check(refused(run(FULL, "edit", { file_path: "apps/project-pln/plans/office.yaml", old_string: "loc-908", new_string: "loc-908 azaria", replace_all: true })),
      "the measured call (edit, replace_all, plans/office.yaml relative) → a bash call that refuses it");
check(refused(run(FULL, "write", { file_path: "/workspace/office/apps/x/app.json", content: "{}" })), "a write to an absolute path in the checkout → refused");
check(refused(run(FULL, "write", { file_path: "/tmp/../workspace/office/.env", content: "X=1" })), "a write to /tmp/../ outside /tmp → refused (normalized)");
check(refused(run(FULL, "write", { file_path: "/tmpfoo/x", content: "" })), "a write to /tmpfoo (not under /tmp/) → refused");
// 2. what a local session needs still works
const mail = run(FULL, "write", { file_path: "/tmp/mail-1.json", content: "{\"to\":\"a\"}" });
check(mail.name === "write" && JSON.parse(mail.arguments).file_path === "/tmp/mail-1.json", "a write under /tmp/ (the mail's JSON) → untouched");
const rd = run(FULL, "read", { file_path: "/workspace/office/apps/project-pln/plans/office.yaml" });
check(rd.name === "read" && JSON.parse(rd.arguments).file_path.endsWith("office.yaml"), "a read of a checkout file → untouched");
const gl = run(FULL, "glob", { path: "/workspace/office" });
check(gl.name === "glob", "glob (a reading tool that names `path`) → untouched");
const bash = run(FULL, "bash", { command: "./bbox project-pln tasks comment DGO-908 --comment hi" });
check(bash.name === "bash" && JSON.parse(bash.arguments).command.startsWith("./bbox project-pln"), "bash (an errand is a command) → not confined");
const tk = run(FULL, "ticket", { title: "x" });
check(tk.name === "ticket", "a tool that names no file → not this guard's");
// 3. any other tool that names a file: every file it names must be under the roots
check(refused(run(FULL, "upload", { path: "/workspace/office/README.md" })), "another tool naming `path` outside /tmp/ → refused");
check(run(FULL, "upload", { path: "/tmp/a.png" }).name === "upload", "…and under /tmp/ → untouched");
check(refused(run(FULL, "upload", { file_path: "/tmp/decoy", path: "/workspace/office/x" })), "a decoy `file_path` under /tmp/ does not let a `path` elsewhere through");
// 4. it fails closed
check(refused(run(FULL, "write", "{not json")), "a write whose arguments are not JSON → refused");
check(refused(run(FULL, "edit", "[1,2]")), "a write whose arguments are not an object → refused");
// 5. a call sent in pieces: the later pieces of one turned away carry nothing
{
  const lab = labeller(FULL);
  const d1 = { choices: [{ delta: { tool_calls: [{ index: 0, function: { name: "write", arguments: "{\"file_path\": \"/workspace/office/x\"" } }] } }] };
  const d2 = { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: ", \"content\": \"rm\"}" } }] } }] };
  lab.fixDoc(d1); lab.fixDoc(d2);
  const f1 = d1.choices[0].delta.tool_calls[0].function, f2 = d2.choices[0].delta.tool_calls[0].function;
  check(f1.name === "bash" && f2.arguments === "", "a streamed write: its first piece refused, its later piece emptied");
  const d3 = { choices: [{ delta: { tool_calls: [{ index: 0, function: { name: "read", arguments: "{\"file_path\": " } }] } }] };
  const d4 = { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: "\"/x\"}" } }] } }] };
  lab.fixDoc(d3); lab.fixDoc(d4);
  check(d3.choices[0].delta.tool_calls[0].function.name === "read" && d4.choices[0].delta.tool_calls[0].function.arguments === "\"/x\"}",
        "…and a new call at that index is its own again: its later piece is kept (second reader)");
}
// 5b. another tool whose arguments do not parse but name a path: turned away (fails closed)
check(refused(run(FULL, "upload", "{\"path\": \"/workspace/office/x\"")), "a non-write tool with unparseable arguments naming a path → refused");
check(run(FULL, "ticket", "{\"title\": \"x\"").name === "ticket", "…and one naming no path → not this guard's");
check(JSON.parse(run(FULL, "write", { file_path: "/workspace/x", content: "" }).arguments).timeoutMs <= 10000,
      "the refusal's bash call asks no more time than the tool's schema allows");
// 6. with no bash tool to say it with, the path is moved to a copy under /tmp
{
  const req = { tools: [tool("write", { file_path: {}, content: {} })] };
  const f = run(req, "write", { file_path: "/workspace/office/apps/project-pln/plans/office.yaml", content: "x" });
  const a = JSON.parse(f.arguments);
  check(f.name === "write" && a.file_path.startsWith("/tmp/dgo-not-written/") && a.content === "x", "no bash tool: the write goes to a copy under /tmp/dgo-not-written/");
}
// 7. LLM_ROUTES_WRITE_ROOTS adds roots (absolute only)
{
  const lab = load({ LLM_ROUTES_WRITE_ROOTS: "/scratch, relative, /" });
  check(run(FULL, "write", { file_path: "/scratch/a.txt", content: "" }, lab).name === "write", "LLM_ROUTES_WRITE_ROOTS=/scratch → a write there is allowed");
  check(refused(run(FULL, "write", { file_path: "/workspace/office/a", content: "" }, lab)), "…a relative root and «/» are not taken: the checkout stays refused");
}
// 8. a request that names no tool is not touched at all
check(labeller({ messages: [] }) === null, "a request with no tools → no labeller");

console.log(failed ? `\nFAIL test_write_confine (${failed} failed)` : "\nPASS test_write_confine");
process.exit(failed ? 1 : 0);
