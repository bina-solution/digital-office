// DGO-1741: while the office's default model is a local route, new sessions default to the local preset —
// written only where the harness's `agent-presets` section is absent, and taken back only if this writer wrote
// it. Part 1 reads `presetPairing` out of llm-routes.mjs itself (the file runs a pass on import) and checks the
// decision. Part 2 runs `llm-routes.mjs --once` on throwaway settings documents, where the harness's YAML
// library can be loaded (the bina-ds image). Where it cannot, part 1 still runs, and the test then ends the
// way G72 reads as NOT RUN («No module named 'yaml'», exit 1) — never as a pass of a writer it did not run.
// Run: node test_preset_pairing.mjs   (exit 1 on a failed check; G72 runs it).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(HERE, "llm-routes.mjs");
const src = fs.readFileSync(SCRIPT, "utf8");
const fn = (name) => new RegExp(`function ${name}\\([\\s\\S]*?\\n}\\n`).exec(src)?.[0];
const konst = (name) => new RegExp(`^const ${name} = "([^"]+)";`, "m").exec(src)?.[1];
const PREFIX = konst("PREFIX"), LOCAL_PRESET = konst("LOCAL_PRESET");
if (!fn("presetPairing") || !fn("presetIsOurs") || !PREFIX || !LOCAL_PRESET) {
  console.error("FAIL could not find presetPairing / presetIsOurs / PREFIX / LOCAL_PRESET in llm-routes.mjs");
  process.exit(1);
}
// eslint-disable-next-line no-new-func
const presetPairing = new Function("PREFIX", "LOCAL_PRESET",
  `${fn("presetIsOurs")}\n${fn("presetPairing")}\nreturn presetPairing;`)(PREFIX, LOCAL_PRESET);
const OURS = { default: LOCAL_PRESET, modeSelectionEnabled: true };

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};

// ── part 1: the decision ─────────────────────────────────────────────────────────────────────────
check(LOCAL_PRESET, "azaria-local", "the local preset is the one apps/bina-ds/presets/ ships");
check(fs.existsSync(path.join(HERE, "..", "presets", LOCAL_PRESET, "agent.cordis.yml")), true, "…and it is there");
check(presetPairing("dgo-ollama-local", undefined, false, true), "set", "Exampleu: local default, no preset chosen → set");
check(presetPairing("dgo-ollama-dell", undefined, false, true), "set", "a linked office's Ollama is local too");
check(presetPairing("dgo-ollama-local", undefined, false, false), null, "the local preset not installed yet → nothing");
check(presetPairing("dgo-ollama-local", { default: "azaria", modeSelectionEnabled: true }, false, true), null,
  "a person chose the full Azaria → theirs, untouched");
check(presetPairing("dgo-ollama-local", OURS, true, true), null, "already paired → nothing (idempotent)");
check(presetPairing("deepseek", undefined, false, true), null, "DeepSeek and no section → nothing");
check(presetPairing("deepseek", OURS, true, true), "drop",
  "the default model is not local any more, and the pairing is ours → taken back");
check(presetPairing("deepseek", OURS, false, true), null, "…but a pairing a person wrote is theirs → kept");
check(presetPairing("deepseek", { default: "raphael", modeSelectionEnabled: true }, true, true), null,
  "ours, then a person changed it → theirs, kept");
check(presetPairing("deepseek", { ...OURS, pinned: ["azaria"] }, true, true), null,
  "ours, then a person added a key beside it → kept whole (dropping it would lose their key)");
check(presetPairing("deepseek", { default: LOCAL_PRESET, modeSelectionEnabled: false }, true, true), null,
  "ours, then a person switched the picker off → theirs, kept");
check(presetPairing("", OURS, true, true), "drop", "no default model named (the harness's own default) is not local");
check(presetPairing(undefined, null, true, true), null, "a null section is nobody's to drop");
check(presetPairing("deepseek", [LOCAL_PRESET], true, true), null, "a list where the section should be is not ours");

// ── part 2: the writer, end to end ───────────────────────────────────────────────────────────────
function yamlReachable() {
  const profile = "/opt/bina/harness/profile/node_modules/.pnpm";
  for (const d of fs.existsSync(profile) ? fs.readdirSync(profile) : []) {
    if (!d.startsWith("@deepseek-ai+dsh-settings-file@")) continue;
    try { createRequire(path.join(profile, d, "node_modules", "@deepseek-ai", "dsh-settings-file", "package.json"))("yaml"); return true; } catch { /* next */ }
  }
  try { createRequire(SCRIPT)("yaml"); return true; } catch { return false; }
}
const writerRuns = yamlReachable();
if (!writerRuns) {
  console.log("part 2 not run here: the harness's YAML library is not on this machine (the bina-ds image has it)");
} else {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "pairing-"));
  const office = fs.mkdtempSync(path.join(os.tmpdir(), "pairing-office-"));
  fs.mkdirSync(path.join(home, ".agent-presets", LOCAL_PRESET), { recursive: true });
  fs.writeFileSync(path.join(home, ".agent-presets", LOCAL_PRESET, "agent.cordis.yml"), "# installed\n");
  const settings = path.join(home, "settings.yaml");
  const run = () => spawnSync(process.execPath, [SCRIPT, "--once"],
    { env: { ...process.env, DSH_HOME: home, OFFICE_ROOT: office }, encoding: "utf8", timeout: 60000 });
  const read = () => fs.readFileSync(settings, "utf8");
  const mine = () => { try { return JSON.parse(fs.readFileSync(path.join(home, "llm-routes-preset.json"), "utf8")).written; } catch { return undefined; } };
  const local = "# the owner's own note\nagent-default-model:\n  provider: dgo-ollama-local\n  model: qwen3.5:4b\nui-onboarding:\n  welcomeNoticeVersion: 2026-08-13.1\n";

  fs.writeFileSync(settings, local);
  let r = run();
  check(r.status, 0, "--once exits 0 on a local default");
  check(/agent-presets:\n {2}default: azaria-local\n {2}modeSelectionEnabled: true/.test(read()), true, "the local preset is the default now");
  check(read().startsWith("# the owner's own note\nagent-default-model:"), true, "the owner's comment and order are kept");
  check(mine(), true, "the writer records that the pairing is its own");
  const once = read();
  run();
  check(read(), once, "a second pass changes nothing");

  fs.writeFileSync(settings, read().replace("provider: dgo-ollama-local", "provider: deepseek").replace("model: qwen3.5:4b", "model: deepseek-chat"));
  r = run();
  check(r.status, 0, "--once exits 0 after the switch to DeepSeek");
  check(/agent-presets/.test(read()), false, "the default model is not local: the pairing is taken back");
  check(mine(), false, "…and the record says so");

  fs.writeFileSync(settings, local + "agent-presets:\n  default: azaria\n  modeSelectionEnabled: true\n");
  run();
  check(/default: azaria\n/.test(read()) && !/azaria-local/.test(read()), true, "a person's own default is never replaced");

  fs.writeFileSync(settings, local);
  run();                                             // ours again
  fs.writeFileSync(settings, read().replace("default: azaria-local", "default: raphael"));
  run();
  check(mine(), false, "ours, then a person picked another: the record lets go");
  fs.writeFileSync(settings, read().replace("provider: dgo-ollama-local", "provider: deepseek"));
  run();
  check(/default: raphael/.test(read()), true, "…and the person's pick survives the switch away from local");

  fs.writeFileSync(settings, local);
  run();                                             // ours again
  fs.writeFileSync(settings, read().replace("modeSelectionEnabled: true", "modeSelectionEnabled: true\n  pinned: x"));
  fs.writeFileSync(settings, read().replace("provider: dgo-ollama-local", "provider: deepseek"));
  run();
  check(/default: azaria-local\n {2}modeSelectionEnabled: true\n {2}pinned: x/.test(read()), true,
    "ours, then a person added a key: the switch away keeps the section whole");
  check(mine(), false, "…and the record lets go of it");

  // a record left saying «ours» with no section (a write cut after the record) and a non-local model: it lets go,
  // so a person's later pick of the very same two keys is theirs and stays
  const deepseek = local.replace("provider: dgo-ollama-local", "provider: deepseek");
  fs.writeFileSync(settings, deepseek);
  fs.writeFileSync(path.join(home, "llm-routes-preset.json"), JSON.stringify({ written: true }));
  run();
  check(mine(), false, "a stale «ours» record with no section and a non-local model lets go");
  fs.writeFileSync(settings, deepseek + "agent-presets:\n  default: azaria-local\n  modeSelectionEnabled: true\n");
  run();
  check(/default: azaria-local/.test(read()), true, "…and a person's own pick of the same two keys is kept");

  fs.rmSync(home, { recursive: true, force: true });
  fs.rmSync(office, { recursive: true, force: true });
}

if (failed) { console.error(`${failed} check(s) failed`); process.exit(1); }
if (!writerRuns) {
  // G72's word for a test that needs what only its image has: NOT RUN, never a pass
  console.error("No module named 'yaml' — part 1 passed; part 2 (the writer) runs in the bina-ds image");
  process.exit(1);
}
console.log("all checks passed");
