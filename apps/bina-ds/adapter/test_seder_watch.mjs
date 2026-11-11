// DGO-582: the seder's watch — what a cycle the clock opened is, until it ends with its balance. `sederFate`
// and `sederBalanced` are read out of server.mjs itself (the server listens on import), so this tests the
// code that runs, not a copy. Run: node test_seder_watch.mjs   (exit 1 on a failed check; G72 runs it).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const src = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "server.mjs"), "utf8");
const konst = (name) => /^const \w+ = "([^"]+)";/m.exec(src.slice(src.indexOf(`const ${name} = `)))?.[1];
const fn = (name) => new RegExp(`function ${name}\\([\\s\\S]*?\\n}\\n`).exec(src)?.[0];
const PENDING = konst("SEDER_PENDING"), BALANCE = konst("SEDER_BALANCE");
if (!PENDING || !BALANCE || !fn("sederFate") || !fn("sederBalanced")) {
  console.error("FAIL could not find the watch's functions/constants in server.mjs");
  process.exit(1);
}
// eslint-disable-next-line no-new-func
const { sederFate, sederBalanced } = new Function("SEDER_GRACE_MS", "SEDER_IDLE_MS", "SEDER_PENDING", "SEDER_BALANCE",
  `${fn("sederFate")}\n${fn("sederBalanced")}\nreturn { sederFate, sederBalanced };`)(180000, 1200000, PENDING, BALANCE);

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};
const M = 60000, t0 = 1_793_600_000_000;
const page = `# סדר מנחה\n\n- שיחה: x\n\n${BALANCE}\n\n${PENDING}\n`;
check(sederBalanced(page), false, "a page with the pending marker under «## מאזן הסדר» is not balanced");
check(sederBalanced(page.replace(PENDING, "נסגרו 3 פריטים · ₪0.41")), true, "a written balance is balanced");
check(sederBalanced(`${page}\n- 13:15 — נקטע בהפעלה מחדש של הלשכה\n`), false,
  "a note the watch appended after the marker does not count as a balance");
check(sederBalanced(""), false, "no page -> not balanced");

const base = { opened: t0, balanced: false, started: t0 - 60 * M, passFrom: t0 + 30 * M, listFrom: t0 + 30 * M + 1, now: t0 + 31 * M };
const idleSession = { running: false, stale: false, jobs: [], queueItems: [], updatedAt: new Date(t0 + 5 * M).toISOString() };
// 2026-10-14: opened 13:00, the container restarted in place at 13:10 — this process started after the cycle opened
check(sederFate({ ...base, started: t0 + 10 * M, now: t0 + 14 * M }), "killed",
  "מנחה 13:00, the door restarted at 13:10 (4 min later) -> killed, whatever the list says");
check(sederFate({ ...base, started: t0 + 10 * M, now: t0 + 11 * M }), "watching", "a minute after the restart -> the grace first");
check(sederFate({ ...base, started: t0 + 10 * M, resumed: t0 + 15 * M, now: t0 + 40 * M, session: idleSession }), "stopped",
  "pushed after the restart, then stopped with this process alive -> told (stopped), not killed again");
check(sederFate({ ...base, started: t0 + 50 * M, resumed: t0 + 15 * M, now: t0 + 55 * M }), "killed",
  "pushed, then the container restarted AGAIN -> killed (the second time: told, not pushed)");
check(sederFate({ ...base, balanced: true, started: t0 + 10 * M, now: t0 + 14 * M }), "balanced", "balanced beats everything");
check(sederFate({ ...base, session: idleSession }), "stopped", "alive process, idle 26 min, nothing running -> stopped");
check(sederFate({ ...base, session: { ...idleSession, running: true } }), "watching", "running -> watching");
check(sederFate({ ...base, session: { ...idleSession, jobs: [{ id: 1 }] } }), "watching", "a background job -> watching");
check(sederFate({ ...base, session: { ...idleSession, queueItems: [{ id: 1 }] } }), "watching", "a queued sub-agent hand-back -> watching");
check(sederFate({ ...base, session: { ...idleSession, stale: true } }), "watching", "a stale entry proves nothing -> watching");
check(sederFate({ ...base, session: undefined }), "watching", "a session the list does not hold -> watching, not dead");
check(sederFate({ ...base, listFrom: base.passFrom - 1, session: idleSession }), "watching",
  "a list asked for before this pass began -> watching (an old list proves nothing)");
check(sederFate({ ...base, session: { ...idleSession, updatedAt: new Date(t0 + 25 * M).toISOString() } }), "watching",
  "active 6 min ago -> watching (the idle limit is 20 min)");
// the watch's own guards, read from the code
check(/if \(sederWatching\) return;/.test(src), true, "one pass at a time");
const watch = src.slice(src.indexOf("async function sederWatch("), src.indexOf("BINA_DS_SEDER_WATCH !== \"0\""));
check(watch.length > 0 && !/\bprompt\(/.test(watch), true, "the watch sends no turn: no session continues itself (DGO-1292)");
check(/if \(!sederMark\(f\.session, \{ settled: killed/.test(watch), true, "a death is told once, its mark on record first");
check(/if \(!sederMark\(f\.session, \{ settled: "unknown"/.test(watch), true, "a cycle two days old with no end is told once, not dropped");
check(/renameSync\(part, file\)/.test(fn("sederWrite") || ""), true, "the record is written whole (a temporary file renamed)");
check(/BINA_DS_SEDER_WATCH !== "0"/.test(src), true, "the watch can be switched off where the data is a copy");
check(/source_id: `seder-door:\$\{id \|\| Date\.now\(\)\}`/.test(src), true, "each notice has its own source_id (no silent fold)");
process.exit(failed ? 1 : 0);
