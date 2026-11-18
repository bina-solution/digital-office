// DGO-1250: a session archived or brought back through the door is the harness's own archive (its workspace
// registry), and the answer says what the harness holds afterwards. archiveSession is read out of server.mjs
// itself (the server listens on import), so this tests the code that runs. Run: node test_archive.mjs
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const src = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "server.mjs"), "utf8");
const body = /async function archiveSession\([\s\S]*?\n}\n/.exec(src)?.[0];
if (!body) { console.error("FAIL could not find archiveSession in server.mjs"); process.exit(1); }
if (!/\(sub === "archive" \|\| sub === "unarchive"\) && req\.method === "POST"/.test(src)) {
  console.error("FAIL no POST /v1/sessions/<id>/archive|unarchive route calls it"); process.exit(1);
}

let failed = 0;
const check = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
};

const calls = [];
let held = ["s-old"];
const rpc = async (method, args) => {
  calls.push([method, args]);
  const id = args.request.sessionId;
  if (method === "workspace/archiveSession") held = [...new Set([...held, id])];
  else if (method === "workspace/unarchiveSession") held = held.filter((x) => x !== id);
  else throw new Error(`unexpected ${method}`);
  return { archivedSessionIds: held };
};
// eslint-disable-next-line no-new-func
const archiveSession = new Function("rpc", `${body}\nreturn archiveSession;`)(rpc);

check(await archiveSession("s-1", true), { id: "s-1", archived: true, archived_ids: ["s-old", "s-1"] }, "archive: the harness's set, the id in it");
check(calls[0], ["workspace/archiveSession", { request: { sessionId: "s-1" } }], "…by workspace/archiveSession({sessionId})");
check(await archiveSession("s-1", true), { id: "s-1", archived: true, archived_ids: ["s-old", "s-1"] }, "archive again: idempotent");
check(await archiveSession("s-1", false), { id: "s-1", archived: false, archived_ids: ["s-old"] }, "unarchive: out of the set");
check(calls.at(-1)[0], "workspace/unarchiveSession", "…by workspace/unarchiveSession");
// a bare uuid given, the harness's `session-<uuid>` held: the same session
const prefixed = new Function("rpc", `${body}\nreturn archiveSession;`)(async () => ({ archivedSessionIds: ["session-abc"] }));
check((await prefixed("abc", true)).archived, true, "a bare uuid matches the harness's session- form");
// an answer without the set (an older harness): never claims the session archived
const bare = new Function("rpc", `${body}\nreturn archiveSession;`)(async () => ({}));
check(await bare("s-2", true), { id: "s-2", archived: false, archived_ids: [] }, "no set in the answer: not claimed archived");

console.log(failed ? `FAILED ${failed}` : "PASS");
process.exit(failed ? 1 : 0);
