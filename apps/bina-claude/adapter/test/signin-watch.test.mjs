// node --test apps/bina-claude/adapter/test/signin-watch.test.mjs — a lost sign-in is never silent (DGO-1684).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createWatch, desktopSignIn, step, texts } from "../signin-watch.mjs";

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "bina-claude-watch-"));

test("the desktop: a cookie gone after a signed-in START is unknown, never «signed out» (Exampleu, 2026-11-09)", () => {
  const h = tmp();
  const dir = path.join(h, ".config", "Claude");
  assert.equal(desktopSignIn(h).state, false, "no store: a fresh office");
  fs.mkdirSync(path.join(dir, "logs"), { recursive: true });
  const start = (present) => `2026-11-09 19:01:55 [info] Starting app {\n2026-11-09 19:01:55 [info] [startup-sign-in] state: {\n`
    + `  sign_in_cookie_present: ${present},\n  signed_in_at_last_exit: true\n}\n`;
  fs.writeFileSync(path.join(dir, "Cookies"), "SQLite format 3\0 .claude.ai sessionKey v10…");
  fs.writeFileSync(path.join(dir, "logs", "main.log"), start(true));
  assert.equal(desktopSignIn(h).state, true);
  fs.writeFileSync(path.join(dir, "Cookies"), "SQLite format 3\0 .claude.ai __cf_bm");
  assert.equal(desktopSignIn(h).state, null, "taken off the disk by the running app: it is still signed in");
  assert.match(desktopSignIn(h).why, /restart would ask/);
  fs.appendFileSync(path.join(dir, "logs", "main.log"), "2026-11-09 19:02:30 [warn] [auth] session_stale_relogin\n");
  assert.equal(desktopSignIn(h).state, false, "claude.ai refused to renew it after that start");
  fs.appendFileSync(path.join(dir, "logs", "main.log"), "2026-11-09 19:03:47 [info] Starting app {\n" + start(false));
  assert.equal(desktopSignIn(h).state, false, "the app's own last start found no sign-in");
  // …and the watcher, fed the unknown, never rings.
  let s = step({}, { desktop: true }).next;
  for (let i = 0; i < 5; i++) { const o = step(s, { desktop: null }); assert.deepEqual(o.actions, []); s = o.next; }
});

test("a face that was signed in rings once after two signed-out readings, and its notice is read when it is back", () => {
  let s = {};
  const run = (r) => { const o = step(s, r); s = o.next; return o.actions.map((a) => `${a.face}:${a.do}`); };
  assert.deepEqual(run({ desktop: true }), []);
  assert.deepEqual(run({ desktop: false }), [], "one reading is not a sign-out: a store read mid-write");
  assert.deepEqual(run({ desktop: null }), [], "unknown changes nothing");
  assert.deepEqual(run({ desktop: false }), ["desktop:post"]);
  s.desktop.notice = 7;
  assert.deepEqual(run({ desktop: false }), [], "never twice");
  assert.deepEqual(run({ desktop: true }), ["desktop:read"]);
});

test("an app that was never signed in (a new office) raises nothing", () => {
  let s = {};
  for (let i = 0; i < 5; i++) { const o = step(s, { desktop: false }); assert.deepEqual(o.actions, []); s = o.next; }
});

test("the notice says the step and links the tile, by the shell's own route (gate G95) — never a terminal", () => {
  const d = texts("desktop", { office: "exampleu", at: Date.parse("2026-11-09T18:30:00Z") });
  assert.match(d.body, /Continue with Google/);
  assert.match(d.body, /18:30 UTC/);
  assert.equal(d.link, "/#/m/bina-claude");
  assert.doesNotMatch(d.body, /\/login|מסוף|terminal/);
});

test("the watcher posts to notifications, retries when it is down, keeps its state over a restart, and reads the notice", async () => {
  const got = [];
  let up = false;
  const srv = http.createServer((req, res) => {
    let b = "";
    req.on("data", (c) => { b += c; });
    req.on("end", () => {
      if (!up) { res.writeHead(503); return res.end(); }
      got.push([req.url, b ? JSON.parse(b) : {}]);
      res.writeHead(201, { "content-type": "application/json" });
      res.end(JSON.stringify({ id: 42, created: true }));
    });
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const url = `http://127.0.0.1:${srv.address().port}`;
  const stateFile = path.join(tmp(), "signin-watch.json");
  const reading = { desktop: true };
  const make = () => createWatch({ read: () => ({ ...reading }), stateFile, notifications: url, office: "exampleu", log: () => {} });
  let w = make();
  await w.tick();
  reading.desktop = false;
  await w.tick();
  w = make();                                   // the adapter restarted between the two readings
  await w.tick();
  assert.equal(got.length, 0, "notifications was down: nothing reached it");
  up = true;
  await w.tick();
  assert.equal(got.length, 1);
  const [p, body] = got[0];
  assert.equal(p, "/api/notifications");
  assert.equal(body.source, "bina-claude");
  assert.match(body.source_id, /^signed-out-desktop-\d+$/, "one notice per incident: each one rings");
  assert.equal(body.source_id, `signed-out-desktop-${JSON.parse(fs.readFileSync(stateFile, "utf8")).desktop.incident}`,
               "the incident that failed to post is the one that posted: a retry is the same notice");
  assert.equal(body.level, "error");
  await w.tick();
  assert.equal(got.length, 1, "rung once");
  reading.desktop = true;
  await w.tick();
  assert.deepEqual(got.map((g) => g[0]), ["/api/notifications", "/api/notifications/42/read"]);
  srv.close();
});
