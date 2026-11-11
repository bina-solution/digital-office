// The follow request never asks the harness for maxMessages 0, and «no history» still sends none.
// Measured on Exampleu's office, 2026-11-10: the harness refuses `maxMessages: 0` («maxMessages must be a positive
// safe integer»), and the adapter sent exactly that for every `bbox agent new -F` / `follow` without --history.
// The functions are read out of server.mjs itself (the server listens on import), so this tests the code that
// runs, not a copy. Run: node test_follow_history.mjs   (exit 1 on a failed check; G72 runs it).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const src = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "server.mjs"), "utf8");
const fn = (name) => new RegExp(`function ${name}\\([\\s\\S]*?\\n}\\n`).exec(src)?.[0];
if (!fn("followRequest") || !fn("snapshotRecords")) {
  console.error("FAIL could not find followRequest / snapshotRecords in server.mjs");
  process.exit(1);
}
// eslint-disable-next-line no-new-func
const { followRequest, snapshotRecords } = new Function(
  `${fn("followRequest")}\n${fn("snapshotRecords")}\nreturn { followRequest, snapshotRecords };`)();

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};
const addr = { kind: "session", sessionId: "s1" };
const max = (h) => followRequest(addr, h, true).request.maxMessages;

check(max(0), 1, "history 0 asks the harness for 1, never 0");
check(max(undefined), 1, "no history given asks for 1");
check(max("abc"), 1, "a history that is not a number asks for 1");
check(max(-5), 1, "a negative history asks for 1");
check(max(20), 20, "history 20 asks for 20");
check(max(9999), 500, "history is capped at 500");
check(max(2.7), 2, "a fraction is a whole count");
check(followRequest(addr, 0, false).request, { address: addr, maxMessages: 1, assistantStream: false },
  "the whole request, without the assistant stream");
check(Number.isSafeInteger(max(0)) && max(0) > 0, true, "every maxMessages is a positive safe integer");

const rec = (seq) => ({ type: "event", event: { seq } });
const records = [rec(4), rec(5), { type: "header" }, rec(6)];
check(snapshotRecords(records, 0, -1), [], "history 0: the one message the harness sends is dropped");
check(snapshotRecords(records, 20, -1).map((r) => r.event.seq), [4, 5, 6], "history 20: every event");
check(snapshotRecords(records, 20, 4).map((r) => r.event.seq), [5, 6], "only the events after `since`");
check(snapshotRecords(undefined, 20, -1), [], "no records: none");

console.log(`follow_history: ${failed ? `${failed} FAIL` : "all ok"}`);
process.exit(failed ? 1 : 0);
