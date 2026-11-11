// DGO-1741: the seder door opens no cycle while the office's default model is a local route. The functions
// are read out of server.mjs itself (the server listens on import), so this tests the code that runs, not a
// copy. Run: node test_seder_local.mjs   (exit 1 on a failed check; G72 runs it).
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const src = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "server.mjs"), "utf8");
const fn = (name) => new RegExp(`function ${name}\\([\\s\\S]*?\\n}\\n`).exec(src)?.[0];
if (!fn("defaultProvider") || !fn("sederLocalRefusal")) {
  console.error("FAIL could not find defaultProvider / sederLocalRefusal in server.mjs");
  process.exit(1);
}
// eslint-disable-next-line no-new-func
const { defaultProvider, sederLocalRefusal } = new Function("readFileSync",
  `${fn("defaultProvider")}\n${fn("sederLocalRefusal")}\nreturn { defaultProvider, sederLocalRefusal };`)(readFileSync);

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};

// Exampleu's settings.yaml as the harness wrote it on 2026-11-09 (the provider block, then the routes)
const exampleu = "agent-default-model:\n  provider: dgo-ollama-local\n  model: qwen3.5:4b\nllm-pi-ai:\n  providers:\n"
  + "    dgo-ollama-local:\n      displayName: מודל מקומי\n      api: openai-completions\n";
check(defaultProvider(exampleu), "dgo-ollama-local", "Exampleu's document names the local route");
check(defaultProvider(exampleu).startsWith("dgo-ollama-"), true, "…which is a local route");
check(defaultProvider("agent-default-model:\n  provider: deepseek\n  model: deepseek-chat\n"), "deepseek",
  "an office on DeepSeek names deepseek");
check(defaultProvider("agent-default-model:\n  model: x\n  provider: \"dgo-ollama-dell\"  # the Dell\n"), "dgo-ollama-dell",
  "a quoted value with a comment, after another key");
check(defaultProvider("agent-default-model: {provider: dgo-ollama-local, model: qwen3.5:4b}\n"), "dgo-ollama-local",
  "the flow form");
check(defaultProvider("llm-pi-ai:\n  providers:\n    dgo-ollama-local:\n      provider: dgo-ollama-local\n"), "",
  "no default model: a route's own `provider:` key elsewhere is not the default");
check(defaultProvider("agent-default-model:\n  model: x\nllm-pi-ai:\n  provider: dgo-ollama-local\n"), "",
  "the block ends at the next top-level key");
check(defaultProvider(""), "", "an empty document names nothing");
check(defaultProvider(undefined), "", "no document names nothing");
check(defaultProvider("ui-onboarding:\n  x: 1\n"), "", "a document without the key names nothing");

// the refusal itself, run on settings documents in a throwaway DSH_HOME
const home = mkdtempSync(path.join(os.tmpdir(), "seder-local-"));
const before = process.env.DSH_HOME;
process.env.DSH_HOME = home;
check(sederLocalRefusal(), null, "no settings document → no refusal (the door behaves as it always did)");
writeFileSync(path.join(home, "settings.yaml"), exampleu);
const said = sederLocalRefusal();
check(typeof said === "string" && said.includes("dgo-ollama-local"), true, "Exampleu's document → refused, naming the route");
writeFileSync(path.join(home, "settings.yaml"), "agent-default-model:\n  provider: deepseek\n  model: deepseek-chat\n");
check(sederLocalRefusal(), null, "an office on DeepSeek → no refusal");
writeFileSync(path.join(home, "settings.yaml"), "agent-default-model:\n  provider: dgo-ollama-dell\n  model: qwen3:8b\n");
check(typeof sederLocalRefusal() === "string", true, "a linked machine's Ollama is a local route too → refused");
writeFileSync(path.join(home, "settings.yaml"), "ui-onboarding:\n  x: 1\n");
check(sederLocalRefusal(), null, "a document without a default model → no refusal");
if (before === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = before;
rmSync(home, { recursive: true, force: true });

// the route: a stray caller is refused as before (403) BEFORE the model is judged; a refused cycle opens nothing
const route = src.slice(src.indexOf('p.startsWith("/v1/seder/")'), src.indexOf("if (!authorized(req))"));
const at = (s) => route.indexOf(s);
check(at("const refused = sederLocalRefusal();") > 0, true, "the door asks once per call");
check(at("String(b.by || \"\") !== SEDER_DRIVER") < at("if (refused) return"), true,
  "the caller check comes first: an unnamed caller still gets the 403 in words");
check(at("if (refused) return") < at("await startSeder("), true, "a refusal returns before any session is opened");
check(/if \(refused\) return \[200, \{ started: false, cycle, reason: refused \}\];/.test(route), true,
  "the refusal is `{started: false, reason}` — the shape the clock's workflow turns into a notice");
check(/dry_run: true, \.\.\.\(refused \? \{ would_refuse: refused \} : \{\}\)/.test(route), true,
  "the dry run says it as `would_refuse` — never `started`, which a dry run never carries");
const selfcheck = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "tools",
  "seder-door-selfcheck.py"), "utf8");
check(/body\.get\("started"\) is None/.test(selfcheck), true,
  "…which is what the door's own selfcheck asks of a dry run");
const wf = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "blueprint", "n8n",
  "binaSeder00001.workflow.ts"), "utf8");
check(/if \(out\.started === false\)/.test(wf) && /out\.reason/.test(wf), true,
  "the clock's workflow still reports a refusal with the door's reason");
// a cycle names its preset: the `seder` skill is the full Azaria's, whatever the office's default preset is
const start = fn("startSeder") || src.slice(src.indexOf("async function startSeder("), src.indexOf("// ── THE SEDER'S WATCH"));
check(/agentPreset: SEDER_PRESET/.test(start), true, "a cycle is opened on a named preset, not the default");
check(/^const SEDER_PRESET = "azaria";/m.test(src), true, "…the full Azaria");
const skill = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "harness", "profile", "agent-presets",
  "azaria", "skills", "seder");
let hasSkill = false;
try { hasSkill = readFileSync(path.join(skill, "SKILL.md"), "utf8").length > 0; } catch { /* checked below */ }
check(hasSkill, true, "…which is the preset that carries the `seder` skill");

if (failed) { console.error(`${failed} check(s) failed`); process.exit(1); }
console.log("all checks passed");
