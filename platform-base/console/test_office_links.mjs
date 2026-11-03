#!/usr/bin/env node
/* test_office_links.mjs — a link inside a framed app that points INTO the office opens here.
 *
 *     node platform-base/console/test_office_links.mjs
 *
 * The rule lives in `officeTarget` (static/app.js) and this holds it without a browser: given a
 * URL and the shell's own address, what should the shell do with it? The cases that matter are the
 * ones that must NOT be touched — a site on the internet is somebody else's page, and a same-origin
 * path of the app itself belongs to the app.
 *
 * Why the rule exists at all (owner, 2026-10-09): the agent's answer carries a work-item link, the
 * harness renders every absolute http(s) link with `target="_blank"`, and the click opened a second
 * tab that asked for a sign-in while the office was already open, signed in, one click away.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(DIR, "static", "app.js"), "utf8");
const body = src.match(/function officeTarget\(([\s\S]*?)\n\}/);
if (!body) {
  console.log("FAIL  officeTarget is not in static/app.js");
  process.exit(1);
}
const officeTarget = new Function(
  "href", "base", "modules", "here",
  `${body[0]}\nreturn officeTarget(href, base, modules, here);`,
);

const MODULES = [
  { id: "plane.hp-laptop", host: "plane.hp-laptop", external: true },
  { id: "drive.hp-laptop", host: "drive.hp-laptop", external: true },
  { id: "bina", host: "bina", external: false },
];
const CONSOLE = "http://console.localhost:8080/";
const ITEM = "bina/projects/e13492c5/issues/83b516fd";

let bad = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`}`);
};

check("this console's own route to a linked office's app opens here",
  officeTarget(`http://console.localhost:8080/#/m/plane.hp-laptop/${ITEM}`, CONSOLE, MODULES, CONSOLE),
  { module: "plane.hp-laptop", path: "/" + ITEM });
check("…and the tile's own nested host, the shape a link out of Plane has",
  officeTarget(`http://plane.hp-laptop.console.localhost:8080/${ITEM}`, CONSOLE, MODULES, CONSOLE),
  { module: "plane.hp-laptop", path: "/" + ITEM });
check("…with no path at all (the tile itself)",
  officeTarget("http://console.localhost:8080/#/m/drive.hp-laptop", CONSOLE, MODULES, CONSOLE),
  { module: "drive.hp-laptop", path: "" });
check("an app of THIS office, on this origin, is this shell's route too",
  officeTarget("http://console.localhost:8080/#/m/bina/x", CONSOLE, MODULES, CONSOLE),
  { module: "bina", path: "/x" });

check("a site on the internet is not ours to open",
  officeTarget("https://example.com/x", CONSOLE, MODULES, CONSOLE), null);
check("a nested host of an app that does not keep its own host is not a tile",
  officeTarget("http://bina.console.localhost:8080/x", CONSOLE, MODULES, CONSOLE), null);
check("a route naming a module this shell does not have",
  officeTarget("http://console.localhost:8080/#/m/nope/x", CONSOLE, MODULES, CONSOLE), null);
check("a same-origin page of the app itself belongs to the app",
  officeTarget("/a/bina/healthz", CONSOLE, MODULES, CONSOLE), null);
check("something that is not a URL at all",
  officeTarget("mailto:x@example.com", CONSOLE, MODULES, CONSOLE), null);

console.log(bad === 0 ? "\nok — the office's own links open in the office" : `\n${bad} failing`);
process.exit(bad === 0 ? 0 : 1);
