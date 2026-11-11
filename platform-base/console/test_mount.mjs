#!/usr/bin/env node
/* test_mount.mjs — the console served UNDER another office's console (DGO-553).
 *
 *     node platform-base/console/test_mount.mjs
 *
 * The failure this guards: this shell builds absolute paths — `/api/version`, `/a/drive/`,
 * `/?bare=1#/m/x`. Served at its own root that is the office's own edge. Served THROUGH a linked
 * office's proxy at `/a/console-home.<office>/`, an absolute `/api/version` asks the OTHER office's
 * edge a question about ITS apps, and the tile shows one office's data under another office's name.
 * That is not hypothetical: it is the same class the compiler records from 2026-10-05 (two tiles of
 * the MacBook showing hp-laptop's conversations).
 *
 * mount.js is one seam — `document.baseURI` in, `dgoUrl()` + a wrapped `fetch` out — and this file
 * proves it both ways: at home nothing changes, mounted everything stays inside the mount.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "static/mount.js"), "utf8");

/** A window as mount.js sees it: a document with a baseURI, an origin, and a fetch that records. */
function boot(baseURI, origin = "http://console.localhost") {
  const calls = [];
  const win = {
    location: { href: origin + "/", origin },
    document: { baseURI },
    fetch: (u) => { calls.push(u); return Promise.resolve({ ok: true }); },
  };
  win.window = win;
  new Function("window", "document", "location", "URL", SRC)(win, win.document, win.location, URL);
  return { win, calls };
}

let bad = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { bad++; console.log(`  FAIL  ${name}\n        got ${JSON.stringify(got)} want ${JSON.stringify(want)}`); }
  else console.log(`  ok    ${name}`);
};

console.log("at home — the mount is empty and nothing is rewritten:");
{
  const { win, calls } = boot("http://console.localhost/");
  check("DGO_MOUNT is empty", win.DGO_MOUNT, "");
  check("dgoUrl leaves an api path alone", win.dgoUrl("/api/version"), "/api/version");
  check("dgoUrl leaves a relative path alone", win.dgoUrl("api/version"), "api/version");
  check("dgoUrl leaves an absolute url alone", win.dgoUrl("http://x/y"), "http://x/y");
  win.fetch("/api/modules");
  check("fetch is untouched", calls, ["/api/modules"]);
}

console.log("\nmounted by another office's console — everything stays inside the mount:");
{
  const { win, calls } = boot("http://console.localhost/a/console-home.macbook/");
  check("DGO_MOUNT is the proxy path, no trailing slash", win.DGO_MOUNT, "/a/console-home.macbook");
  check("an api call is prefixed", win.dgoUrl("/api/version"), "/a/console-home.macbook/api/version");
  check("an app tile path is prefixed", win.dgoUrl("/a/drive/"), "/a/console-home.macbook/a/drive/");
  check("the shell's own bare link is prefixed", win.dgoUrl("/"), "/a/console-home.macbook/");
  check("an already-prefixed path is not doubled", win.dgoUrl("/a/console-home.macbook/api"), "/a/console-home.macbook/api");
  check("an external host is never rewritten", win.dgoUrl("http://plane.localhost/x"), "http://plane.localhost/x");
  win.fetch("/api/modules");
  check("fetch goes through the seam", calls, ["/a/console-home.macbook/api/modules"]);
}

console.log("\na page on ANOTHER origin (a peer's nested host) is not a mount:");
{
  const { win } = boot("http://console-home.macbook.console.localhost/");
  check("DGO_MOUNT stays empty", win.DGO_MOUNT, "");
  check("dgoUrl is the identity", win.dgoUrl("/api/version"), "/api/version");
}

console.log(bad ? `\nmount: ${bad} FAILED` : "\nmount: all good");
process.exit(bad ? 1 : 0);
