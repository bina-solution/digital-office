#!/usr/bin/env node
/* test_module_ref.mjs — which tile a console link names, when the name is not this office's id.
 *
 *     node platform-base/console/test_module_ref.mjs
 *
 * The failure this guards, measured 2026-10-09 (the owner, «הקישור למשימה עדיין לא עובד», DGO-511):
 * the office's task tool hands him `#/m/project-pln/bina/projects/<id>/issues/<id>`. That is this
 * office's MODULE id; on a linked office the same app is a tile `plane.hp-laptop` — no module named
 * `project-pln` — so `route()` fell through to `MODULES[0]`, rewrote the address to it and opened the
 * AGENT. The link looked like it worked and showed the wrong thing. A link written with the app's
 * ALIAS (`plane`) broke the same way on the office that owns the id.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const win = {};
new Function("window", fs.readFileSync(path.join(HERE, "static/module-ref.js"), "utf8"))(win);
const { resolve } = win.BinaModuleRef;

let bad = 0;
const check = (name, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n        got  ${got}\n        want ${want}`}`);
};

// this office: Plane installed here (module id project-pln, alias plane) and the agent (id bina)
const LOCAL = [
  { id: "bina", alias: "bina", embed: "/a/bina/" },
  { id: "project-pln", alias: "plane", embed: "/a/plane/", external: true, host: "plane" },
];
// a linked office: the same app, a tile named by its alias, carrying the writer's module id
const REMOTE = [
  { id: "bina", alias: "bina" },
  { id: "plane.hp-laptop", remote: { alias: "plane", module_id: "project-pln", office: "hp-laptop" } },
];

const id = (m) => (m ? m.id : "<none>");

check("the module's own id", id(resolve(LOCAL, "project-pln")), "project-pln");
check("the app's alias, on the office that owns it", id(resolve(LOCAL, "plane")), "project-pln");
check("the id the WRITER used, on a linked office", id(resolve(REMOTE, "project-pln")), "plane.hp-laptop");
check("the alias, on a linked office", id(resolve(REMOTE, "plane")), "plane.hp-laptop");
check("the tile's own id, on a linked office", id(resolve(REMOTE, "plane.hp-laptop")), "plane.hp-laptop");
check("a local tile beats a remote one of the same name",
  id(resolve([...LOCAL, { id: "plane.macbook", remote: { alias: "plane", module_id: "plane" } }], "plane")),
  "project-pln");
check("the AGENT is still reachable by its own id", id(resolve(REMOTE, "bina")), "bina");
check("a name nobody has resolves to nothing (route() owns the fallback)", id(resolve(LOCAL, "nope")), "<none>");
check("no reference at all", id(resolve(LOCAL, "")), "<none>");
check("an empty registry is not a crash", id(resolve([], "bina")), "<none>");

console.log(`\n${bad === 0 ? "all passed" : bad + " FAILED"}`);
process.exit(bad === 0 ? 0 : 1);
