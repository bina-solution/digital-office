#!/usr/bin/env node
/* test_widget_label.mjs — the line under a window pushed aside says its whole somewhere.
 *
 *     node platform-base/console/test_widget_label.mjs [path-to-desktop.js]
 *
 * DGO-532, measured on 2026-10-10: desktop mode draws a window pushed far aside as a round button in a
 * 120px box with ONE line under it — «<the tile's name> · <the label the screen posted>». The shell
 * composes that line from what the screen sent, and the box cannot grow (a widget sits in a flank
 * beside its neighbours), so a line longer than the box was cut with an ellipsis and NOTHING said the
 * rest: «התראות · 120 לא נקראו» needs 123px in Segoe UI and 130px with this distro's fonts. A screen
 * cannot fix it either — it does not know how much room the shell gave it.
 *
 * So the rule this holds: wherever the label's text is set, the same element carries a title with the
 * WHOLE line. The check is on the source (the shell's own drawing runs inside a closure that builds a
 * desktop — canvases, a dock, a menu bar — and cannot be instantiated for a unit test), and it fails
 * on the pre-fix file, which is how it was proved.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const SRC = process.argv[2] || path.join(REPO, "platform-base/console/static/desktop.js");
const CSS = fs.readFileSync(path.join(REPO, "platform-base/console/static/desktop.css"), "utf8");
const js = fs.readFileSync(SRC, "utf8");

let bad = 0;
const check = (name, ok, detail) => {
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
};

// 1 — the two lines the widget draws: the screen's own label, and a window's title in icon mode.
const composed = js.includes('w.widget.label ? m.name + " · " + w.widget.label : m.name');
const titled = js.includes("w.title || m.name");
check("the widget's line is still composed from the tile and the screen's label", composed,
  "desktop.js no longer composes `m.name + ' · ' + widget.label` — DGO-532's measurement named this line");
check("a window pushed aside as an icon still draws its title", titled, "`w.title || m.name` is gone");

// 2 — and every place that sets it puts the whole line in a title too, through ONE helper.
const setter = /function\s+label\s*\(\s*w\s*,\s*text\s*\)\s*\{([^}]*)\}/.exec(js);
check("the label is written through one helper", !!setter,
  "no `function label(w, text)` — the two write sites must go through one, or a window reused for another app keeps the previous title");
if (setter) {
  const body = setter[1];
  check("…which sets the text", /wgLbl\.textContent\s*=/.test(body), body.trim().slice(0, 120));
  check("…AND the title, with the same string", /wgLbl\.title\s*=\s*text\b/.test(body), body.trim().slice(0, 120));
}
const writes = [...js.matchAll(/wgLbl\.textContent\s*=/g)].length;
const viaHelper = [...js.matchAll(/\blabel\(w,\s/g)].length;
check(`every write of the label goes through it (${viaHelper} call(s), ${writes} direct write(s))`,
  writes === 1 && viaHelper >= 2,
  "a direct `wgLbl.textContent =` outside the helper is a line whose whole nobody can read");

// 3 — the cut is real: the box is 120px and the label ellipsises at its width.
const box = /WG_BOX\s*=\s*\{\s*widget:\s*\[(\d+),\s*(\d+)\]\s*,\s*icon:\s*\[(\d+),\s*(\d+)\]\s*\}/.exec(js);
check("the widget's box is the 120px the measurement named", !!box && box[1] === "120" && box[3] === "120",
  box ? `widget ${box[1]}px, icon ${box[3]}px` : "WG_BOX is gone — the label's bound is no longer this gate's business");
const lbl = /\.dk-wg-lbl\{([^}]*)\}/.exec(CSS);
check("the label is still one line, bounded, with an ellipsis past it",
  !!lbl && /max-width:\s*120px/.test(lbl[1]) && /text-overflow:ellipsis/.test(lbl[1]) && /white-space:nowrap/.test(lbl[1]),
  lbl ? lbl[1] : ".dk-wg-lbl is gone from desktop.css");

console.log(bad ? `\n${bad} failing` : "\n0 failing");
process.exit(bad ? 1 : 0);
