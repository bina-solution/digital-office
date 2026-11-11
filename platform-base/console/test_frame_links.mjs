#!/usr/bin/env node
/* test_frame_links.mjs — which link inside an app's frame belongs to the SHELL.
 *
 *     node platform-base/console/test_frame_links.mjs
 *
 * The failure this guards, measured on the live office 2026-10-12 (DGO-501/ui2-060): the work-item
 * link the office's own task tool hands the owner — `http://console.<host>/#/m/project-pln/…` — was
 * clicked inside the CHAT's frame. Same origin, so the browser's default action navigated the frame:
 * the chat window turned into the console and the desk never moved. The owner asked for «הכל באותו
 * דסקטופ כשרק הקישור משתנה בלי שנוצר דף חדש בכרום».
 *
 * The live half (a real console, desktop mode, a deep link clicked inside a window) is
 * `scripts/ui-coverage/desktop-links.py`; this is the half a node process can hold.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const win = {};
new Function("window", fs.readFileSync(path.join(HERE, "static/frame-links.js"), "utf8"))(win);
const { isConsoleLink, wantsOwnTab } = win.BinaFrameLinks;

const ORIGIN = "http://console.localhost";
let bad = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) { bad++; console.log(`  FAIL  ${name}\n        got ${JSON.stringify(got)} want ${JSON.stringify(want)}`); }
  else console.log(`  ok    ${name}`);
};

console.log("a console address is the shell's:");
check("the item link the office hands out", isConsoleLink(`${ORIGIN}/#/m/project-pln/bina/projects/p/issues/i`, ORIGIN), true);
check("…with the console's root written out", isConsoleLink(`${ORIGIN}/#/m/drive`, ORIGIN), true);
check("…as a bare hash in the same document", isConsoleLink("#/m/bina", ORIGIN), true);
check("…and with a query inside the route", isConsoleLink(`${ORIGIN}/#/m/my-docs?open=7`, ORIGIN), true);

console.log("\nan app's own screens are NOT — they are what the frame is for:");
check("a route under the app's proxy path", isConsoleLink(`${ORIGIN}/a/bina/#/thread/3`, ORIGIN), false);
check("a path inside the app", isConsoleLink(`${ORIGIN}/a/drive/files/9`, ORIGIN), false);
check("the app's own root", isConsoleLink(`${ORIGIN}/a/mail/`, ORIGIN), false);

console.log("\nneither is anything that is not this console:");
check("another host", isConsoleLink("http://drive.localhost/#/m/drive", ORIGIN), false);
check("a fragment that names no module", isConsoleLink(`${ORIGIN}/#elsewhere`, ORIGIN), false);
check("an empty href", isConsoleLink("", ORIGIN), false);
check("a javascript: href", isConsoleLink("javascript:void(0)", ORIGIN), false);

console.log("\nand a person asking for their own tab keeps it:");
check("ctrl-click", wantsOwnTab({ ctrlKey: true }), true);
check("cmd-click", wantsOwnTab({ metaKey: true }), true);
check("middle-click", wantsOwnTab({ button: 1 }), true);
check("a plain left click", wantsOwnTab({ button: 0 }), false);
check("no event at all", wantsOwnTab(null), false);

console.log();
if (bad) { console.log(`${bad} check(s) failed`); process.exit(1); }
console.log("frame links: a console address goes to the shell, everything else stays in the frame");
