// DGO-1731: a session's model set through the door is that session's own. The harness's selectModel also rewrites
// the office's default model (settings.yaml `agent-default-model`); the door puts it back unless `default: true`.
// The functions are read out of server.mjs itself (the server listens on import), so this tests the code that
// runs, not a copy. Run: node test_model_default.mjs   (exit 1 on a failed check; G72 runs it).
import { closeSync, existsSync, mkdirSync, mkdtempSync, openSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const src = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "server.mjs"), "utf8");
const fn = (name) => new RegExp(`(?:async )?function ${name}\\([\\s\\S]*?\\n}\\n`).exec(src)?.[0];
const line = (name) => new RegExp(`(?:const|let) ${name} = [^\\n]*\\n`).exec(src)?.[0];
const FNS = ["defaultEntry", "keepDefault", "keepOfficeDefault", "selectSessionModel", "selectOne"];
for (const n of FNS) if (!fn(n)) { console.error(`FAIL could not find ${n} in server.mjs`); process.exit(1); }
for (const n of ["SETTINGS_FILE", "readSettings", "modelTurn"]) if (!line(n)) { console.error(`FAIL could not find ${n} in server.mjs`); process.exit(1); }
// eslint-disable-next-line no-new-func
const { defaultEntry, keepDefault, keepOfficeDefault, selectSessionModel } = new Function(
  "readFileSync", "writeFileSync", "renameSync", "openSync", "closeSync", "rmSync", "process",
  `${line("SETTINGS_FILE")}${line("readSettings")}${line("modelTurn")}${FNS.map(fn).join("\n")}\n`
  + `return { ${FNS.join(", ")} };`)(readFileSync, writeFileSync, renameSync, openSync, closeSync, rmSync, process);

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};

// ── defaultEntry ──────────────────────────────────────────────────────────────────────────────────────
const head = "# the harness's settings\nagent-presets:\n  default: azaria-local\n  modeSelectionEnabled: true\n";
const tail = "llm-pi-ai:\n  providers:\n    dgo-ollama-portable-ubuntu:\n      model: qwen3:1.7b\n      provider: x\n";
const block = (p, m, e) => `agent-default-model:\n  provider: ${p}\n  model: ${m}\n${e ? `  reasoningEffort: ${e}\n` : ""}`;
const hp17 = head + block("dgo-ollama-portable-ubuntu", "qwen3:1.7b") + tail;
const hp4b = head + block("dgo-ollama-portable-ubuntu", "qwen3:4b-instruct-2507-q4_K_M", "off") + tail;
const sel4b = { provider: "dgo-ollama-portable-ubuntu", model: "qwen3:4b-instruct-2507-q4_K_M" };
check(defaultEntry(hp17), { from: 4, to: 7, provider: "dgo-ollama-portable-ubuntu", model: "qwen3:1.7b", effort: "" },
  "the HP's document: the entry's lines and what it names");
check(defaultEntry(hp4b).effort, "off", "the effort is read");
check(defaultEntry(tail), null, "no entry: a route's own `model:`/`provider:` keys elsewhere are not the default");
check(defaultEntry("x:\n  agent-default-model:\n    provider: a\n    model: b\n"), null, "a nested key of the same name is not the entry");
check(defaultEntry("agent-default-model: {provider: dgo-ollama-local, model: qwen3.5:4b}\nother: 1\n"),
  { from: 0, to: 1, provider: "dgo-ollama-local", model: "qwen3.5:4b", effort: "" }, "the flow form");
check(defaultEntry('agent-default-model:\n  model: "qwen3:4b"  # quoted, with a comment\n  provider: \'deepseek-official\'\n'),
  { from: 0, to: 3, provider: "deepseek-official", model: "qwen3:4b", effort: "" }, "quoted values, a comment, keys in another order");
check(defaultEntry("agent-default-model:\r\n  provider: a\r\n  model: b\r\nx: 1\r\n"),
  { from: 0, to: 3, provider: "a", model: "b", effort: "" }, "a CRLF document");
check(defaultEntry("agent-default-model:\n  provider: a\n\n  model: b\n\nnext: 1\n").to, 4,
  "a blank line INSIDE the block is part of it; the blank line after it is not");
check(defaultEntry("agent-default-model:\n  provider: a\n  model: b").to, 3, "the entry at the end with no final newline");
check(defaultEntry(""), null, "an empty document has no entry");

// ── keepDefault ───────────────────────────────────────────────────────────────────────────────────────
check(keepDefault(hp4b, hp17, sel4b), hp17, "THE HP's CASE: a session set to the 4B puts the 1.7B default back, every other line as it was");
check(keepDefault(hp4b, hp4b, sel4b), null, "the default already was the selection → nothing to write");
check(keepDefault(head + block("deepseek-official", "deepseek-v4-flash") + tail, hp17, sel4b), null,
  "the entry names something else (somebody chose since) → theirs stands");
check(keepDefault(hp17, hp17, sel4b), null, "the harness did not write the selection → nothing to write");
check(keepDefault(head + block("dgo-ollama-portable-ubuntu", "qwen3:4b-instruct-2507-q4_K_M") + tail, hp4b, sel4b), hp4b,
  "only the effort moved → the effort is put back");
check(keepDefault("agent-default-model:\n  provider: p\n  model: m\n", "", { provider: "p", model: "m" }), "",
  "a document that had no default → the entry the selection added is taken out");
check(keepDefault(head + block("p", "m") + tail, head + tail, { provider: "p", model: "m" }), head + tail,
  "…the same in the middle of a document");
check(keepDefault(block("p", "m") + "x: 1\n", "agent-default-model: {provider: q, model: n}\nx: 1\n", { provider: "p", model: "m" }),
  "agent-default-model: {provider: q, model: n}\nx: 1\n", "a flow-form default comes back as it was written");
const crlfBefore = "a: 1\r\nagent-default-model:\r\n  provider: q\r\n  model: n\r\nb: 2\r\n";
const crlfAfter = "a: 1\r\nagent-default-model:\r\n  provider: p\r\n  model: m\r\nb: 2\r\n";
check(keepDefault(crlfAfter, crlfBefore, { provider: "p", model: "m" }), crlfBefore, "a CRLF document keeps its line ends");

// ── selectSessionModel, against a fake harness that writes the selection into a real settings document ──────
// The fake does what the harness does: `session/selectModel` rewrites `agent-default-model` — at once, `lateMs`
// after it answers, or never — keeping every other line of the document.
const home = mkdtempSync(path.join(os.tmpdir(), "model-default-"));
const was = process.env.DSH_HOME;
process.env.DSH_HOME = home;
const file = path.join(home, "settings.yaml");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const harness = ({ lateMs = 0, never = false, calls = [] } = {}) => async (method, args) => {
  const r = args.request;
  calls.push(`${r.provider}/${r.model}`);
  if (never) return null;
  const write = () => {
    const t = readFileSync(file, "utf8"), e = defaultEntry(t);
    const blk = block(r.provider, r.model, r.reasoningEffort).replace(/\n$/, "").split("\n");
    const ls = t.split("\n");
    if (e) ls.splice(e.from, e.to - e.from, ...blk); else ls.unshift(...blk);
    writeFileSync(file, ls.join("\n"));
  };
  if (lateMs) setTimeout(write, lateMs); else write();
  return null;
};
const ask = (call, b) => selectSessionModel(call, "session-x", { provider: sel4b.provider, model: sel4b.model, ...b });
const D17 = { provider: "dgo-ollama-portable-ubuntu", model: "qwen3:1.7b", effort: null };
try {
  writeFileSync(file, hp17);
  let r = await ask(harness(), { effort: "off" });
  check([r.default, r.office_default], ["restored", D17], "THE HP's CASE: the harness moved the default to the 4B → restored, and the answer names the 1.7B");
  check(readFileSync(file, "utf8"), hp17, "…the document is the one from before, every line");
  check(statSync(file).mode & 0o777, 0o600, "…mode 0600, as the harness writes it");
  check(existsSync(`${file}.lock`), false, "…and the lock is given back");

  writeFileSync(file, hp17);
  r = await ask(harness(), { default: true });
  check([r.default, r.why, r.office_default.model], ["changed", "asked", sel4b.model], "`default: true` → the selection is the office's default, said as asked");

  writeFileSync(file, hp17);
  r = await ask(harness({ never: true }), {});
  check([r.default, readFileSync(file, "utf8") === hp17], ["kept", true], "the harness never wrote the default (1 s) → kept, nothing written");

  writeFileSync(file, hp17);
  r = await ask(harness({ lateMs: 350 }), {});
  check([r.default, readFileSync(file, "utf8") === hp17], ["restored", true], "the harness writes 350 ms after it answers → still restored");

  writeFileSync(file, head + block("dgo-ollama-portable-ubuntu", "qwen3:1.7b", "high") + tail);
  r = await ask(harness({ lateMs: 300 }), { model: "qwen3:1.7b", effort: "off" });
  check([r.default, r.office_default.effort], ["restored", "high"], "only the effort moved, late → put back to the effort from before");

  writeFileSync(file, hp17);
  const other = async (m, a) => { await harness()(m, a); writeFileSync(file, head + block("deepseek-official", "deepseek-v4-pro") + tail); return null; };
  r = await ask(other, {});
  check([r.default, /names deepseek-official\/deepseek-v4-pro, not this selection/.test(r.why), r.office_default.model],
    ["changed", true, "deepseek-v4-pro"], "somebody else chose meanwhile → changed, naming theirs, and theirs stands (never «kept»)");

  writeFileSync(file, hp17);
  writeFileSync(`${file}.lock`, "");
  const t0 = Date.now();
  r = await ask(harness(), {});
  check([r.default, /lock was not taken/.test(r.why)], ["changed", true], "the harness holds its lock → changed, saying why");
  check(Date.now() - t0 < 4500, true, "…within the lock's bound");
  check(defaultEntry(readFileSync(file, "utf8")).model, sel4b.model, "…and nothing written under somebody else's lock");
  rmSync(`${file}.lock`);

  // two overlapping selections (lanes setting two sessions at once) — the second reader's case: B starts after the
  // harness wrote A's model and before A put it back, so B would read A's model as «before» and put THAT back.
  // Each must see the office's own default as «before»: the office ends where it was and both answers are true.
  writeFileSync(file, hp17);
  const pa = ask(harness({ lateMs: 300 }), {});
  await sleep(350);
  const pb = ask(harness({ lateMs: 300 }), { provider: "deepseek-official", model: "deepseek-v4-flash" });
  const [a, b] = await Promise.all([pa, pb]);
  check([a.default, b.default, defaultEntry(readFileSync(file, "utf8")).model], ["restored", "restored", "qwen3:1.7b"],
    "two overlapping selections → both restored, the office's default is the one from before");

  // the put-back's own write fails AFTER the lock is taken: its temporary file's name is held by a read-only file
  // (the test runs as a user; root writes anyway, so the case is skipped there)
  const { chmodSync } = await import("node:fs");
  if (process.getuid && process.getuid() === 0) console.log("skip the failed-write case: root writes anyway");
  else {
    writeFileSync(file, hp17);
    const tmp = `${file}.adapter.${process.pid}`;
    writeFileSync(tmp, ""); chmodSync(tmp, 0o444);
    r = await ask(harness(), {});
    check([r.default, /could not be put back \(EACCES\)/.test(r.why)], ["changed", true], "the write fails after the lock → changed, saying why, no 500");
    check([existsSync(tmp), existsSync(`${file}.lock`)], [false, false], "…no temporary file and no lock left behind");
    check(defaultEntry(readFileSync(file, "utf8")).model, sel4b.model, "…and the answer is true: the default is the selection");
  }

  // a selection the harness refuses (a wrong session id) does not wedge the next one
  writeFileSync(file, hp17);
  let threw = "";
  try { await ask(async () => { throw new Error("404 no such session"); }, {}); } catch (e) { threw = e.message; }
  check(threw, "404 no such session", "a refused selection answers the harness's error, as before");
  r = await ask(harness(), {});
  check(r.default, "restored", "…and the next selection runs and is put back");

  // the harness writes the default and THEN fails (or the call times out): the default is put back all the same
  writeFileSync(file, hp17);
  threw = "";
  try { await ask(async (m, a2) => { await harness()(m, a2); throw new Error("selectModel timed out"); }, {}); } catch (e) { threw = e.message; }
  check([threw, readFileSync(file, "utf8") === hp17], ["selectModel timed out", true], "a selection that wrote the default and failed → the error, and the default put back");

  // `default: true` while somebody else chose: said as theirs, never «is now yours too»
  writeFileSync(file, hp17);
  r = await ask(other, { default: true });
  check([r.default, /names deepseek-official\/deepseek-v4-pro/.test(r.why)], ["changed", true], "`default: true` but the entry names somebody else's → said as theirs");

  // the selection IS the office's default: kept at once, no second's wait
  writeFileSync(file, hp17);
  const t1 = Date.now();
  r = await ask(harness(), { model: "qwen3:1.7b" });
  check([r.default, Date.now() - t1 < 500], ["kept", true], "selecting the default itself → kept, without the 1 s wait");

  // settings.yaml unreadable before (a directory in its place) → unknown, never «kept»
  rmSync(file); mkdirSync(file);
  r = await ask(async () => null, {});
  check([r.default, /could not be read before/.test(r.why)], ["unknown", true], "a document that cannot be read → unknown, saying why");
  rmSync(file, { recursive: true });

  r = await ask(async () => null, {});
  check([r.default, r.office_default], ["kept", null], "no document before or after → kept, no office default");
} finally {
  if (was === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = was;
  try { (await import("node:fs")).chmodSync(home, 0o755); } catch { /* gone */ }
  rmSync(home, { recursive: true, force: true });
}

// ── the route and the summary ─────────────────────────────────────────────────────────────────────────
const route = src.slice(src.indexOf('if (sub === "model" && req.method === "POST")'), src.indexOf('if (sub === "preset" && req.method === "POST")'));
check(/const r = await selectSessionModel\(rpc, id, b\);[^\n]*\n\s*live\.refreshList\(true\);\n\s*return \[200, r\];/.test(route), true,
  "the route selects through selectSessionModel and answers what it says");
check(/model: v\.modelSelection\?\.next \|\| v\.modelSelection\?\.lastUsed \|\| null,/.test(src), true,
  "the summary names the model the NEXT turn runs on");

if (failed) { console.error(`${failed} check(s) failed`); process.exit(1); }
console.log("all checks passed");
