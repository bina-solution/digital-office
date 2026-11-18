// The office's folder after a sign-in (home-folder.mjs, DGO-1920): handed once per NEW account, never to one that
// has worked here (in any folder — an adapter restart must not move a working screen), never while signed out —
// and a failed hand-off is tried again, not marked done.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHomeFolder, decide, hasSessions } from "../home-folder.mjs";

const OFFICE = "/mnt/c/Users/user/Desktop/Desktop/MyDGO";

function desk({ account, sessions = [] }) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "home-folder-"));
  fs.mkdirSync(path.join(d, ".config", "Claude"), { recursive: true });
  if (account) fs.writeFileSync(path.join(d, ".config", "Claude", "config.json"), JSON.stringify({ lastKnownAccountUuid: account }));
  sessions.forEach(([acct, cwd], i) => {
    const dir = path.join(d, ".config", "Claude", "claude-code-sessions", acct, "org");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `local_${i}.json`), JSON.stringify({ sessionId: `local_${i}`, cwd }));
  });
  return d;
}

test("decide: only a signed-in account, never handed, that has not worked here", () => {
  assert.equal(decide({ signedIn: false, account: "a", handed: [], worked: false }).hand, null);
  assert.equal(decide({ signedIn: null, account: "a", handed: [], worked: false }).hand, null);
  assert.equal(decide({ signedIn: true, account: null, handed: [], worked: false }).hand, null);
  assert.equal(decide({ signedIn: true, account: "a", handed: ["a"], worked: false }).hand, null);
  assert.equal(decide({ signedIn: true, account: "a", handed: [], worked: true }).hand, null);
  assert.equal(decide({ signedIn: true, account: "a", handed: ["b"], worked: false }).hand, "a");
});

test("sessions count for their own account only, in any folder", () => {
  const d = desk({ account: "new", sessions: [["old", "/somewhere/else"]] });
  assert.equal(hasSessions(d, "old"), true);
  assert.equal(hasSessions(d, "new"), false);
});

test("a new account is handed the office once; a failed hand-off is tried again", async () => {
  const d = desk({ account: "new", sessions: [["old", OFFICE]] });
  const stateFile = path.join(d, "home-folder.json");
  const calls = [];
  let fail = true;
  const h = createHomeFolder({
    desk: d, folders: [OFFICE, "/workspace/office"], stateFile, signedIn: () => true, log: () => {},
    drive: async (args) => { calls.push(args); if (fail) throw new Error("the view was loading"); },
  });
  await h.tick();
  assert.deepEqual(calls, [["home", OFFICE]]);
  assert.equal(fs.existsSync(stateFile), false);           // not marked: the next minute tries again
  fail = false;
  await h.tick();
  assert.deepEqual(JSON.parse(fs.readFileSync(stateFile, "utf8")).handed, ["new"]);
  await h.tick();
  assert.equal(calls.length, 2);                             // once, and never again for this account
});

test("an account that has worked here (any folder), or a signed-out app, is never handed it", async () => {
  const d = desk({ account: "old", sessions: [["old", "/repo/some-worktree"]] });
  const calls = [];
  const mk = (signedIn) => createHomeFolder({ desk: d, folders: [OFFICE], stateFile: path.join(d, "s.json"),
    signedIn: () => signedIn, log: () => {}, drive: async (a) => { calls.push(a); } });
  await mk(true).tick();
  await mk(false).tick();
  assert.equal(calls.length, 0);
});
