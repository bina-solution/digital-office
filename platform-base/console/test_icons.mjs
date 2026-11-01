#!/usr/bin/env node
/* test_icons.mjs — every tile's icon is one the icon set has.
 *
 *     node platform-base/console/test_icons.mjs
 *
 * A manifest NAMES its tile's icon (`routing[].module.icon`) and ONE set owns the glyphs
 * (`platform-base/bina-ui/bina-icons.js`, copied into each surface that lists apps — gate G27). A
 * name the set does not have is not an error anywhere: the surface draws the neutral window, on
 * purpose, so that a missing glyph is never a word on the screen. Which is also how two tiles wore
 * that window for weeks without anybody deciding they should — the office-extension asked for
 * `building`, and the console's own home tile carried an emoji from before the icon set existed
 * (seen on the map as the Mac office's «המרכז» tile, 2026-10-07).
 *
 * So the fallback stays, and this holds the other half: no manifest in the tree relies on it.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const src = fs.readFileSync(path.join(REPO, "platform-base/bina-ui/bina-icons.js"), "utf8");
const block = src.match(/const BINA_ICONS = \{([\s\S]*?)\n\};/);
const known = new Set(block ? [...block[1].matchAll(/^\s*['"]?([a-z0-9-]+)['"]?:\s/gm)].map((m) => m[1]) : []);

let bad = 0;
const check = (name, ok, detail) => {
  if (!ok) bad++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
};

check("the icon set was read", known.size > 20 && known.has("app"), `${known.size} names`);

const tiles = [];
for (const layer of ["apps", "platform-base"]) {
  for (const app of fs.readdirSync(path.join(REPO, layer)).sort()) {
    const file = path.join(REPO, layer, app, "app.json");
    if (!fs.existsSync(file)) continue;
    for (const r of JSON.parse(fs.readFileSync(file, "utf8")).routing || []) {
      if (r.module && "icon" in r.module) tiles.push({ where: `${layer}/${app}`, name: r.module.name, icon: r.module.icon });
    }
  }
}
check("the manifests' tiles were read", tiles.length > 20, `${tiles.length} tiles`);
const unknown = tiles.filter((t) => !known.has(t.icon));
check(`all ${tiles.length} tiles name an icon the set has`, !unknown.length,
  unknown.map((t) => `${t.where}: «${t.name}» asks for ${JSON.stringify(t.icon)}`).join("\n        ")
  + "\n        add the glyph to platform-base/bina-ui/bina-icons.js (then theme-token-lint.py --fix) or name one it has: " + [...known].sort().join(" "));

/* ── the OTHER thing every surface draws from this set: the half of an office's mark ────────────
 * A linked office is drawn as a colour and an animal (flt-004), and both are NAMES: the colour is a
 * `[data-office-hue="<name>"]` rule in the palette, the animal is a glyph here. The vocabulary that
 * hands them out — `OFFICE_HUES` / `OFFICE_ANIMALS` in apps/dgo-extend/identity.py — is written for
 * ten or twenty offices, while a surface with no glyph for a name draws the same neutral window a
 * tile with a typo draws: the mark's second half, silently missing, on every screen at once.
 * Measured 2026-10-11: the vocabulary named ten animals and the set had three, so a `fox` office and
 * a `lion` office were the same empty tile. */
const idn = fs.readFileSync(path.join(REPO, "apps/dgo-extend/identity.py"), "utf8");
const tuple = (name) => {
  const m = idn.match(new RegExp(`^${name}\\s*=\\s*\\(([^)]*)\\)`, "m"));
  return m ? [...m[1].matchAll(/"([a-z-]+)"/g)].map((x) => x[1]) : [];
};
const animals = tuple("OFFICE_ANIMALS");
const hues = tuple("OFFICE_HUES");
check("the office-mark vocabulary was read", animals.length >= 3 && hues.length >= 3,
  `${animals.length} animals, ${hues.length} colours`);
const noGlyph = animals.filter((a) => !known.has(a));
check(`all ${animals.length} office animals have a glyph`, !noGlyph.length,
  `${noGlyph.join(", ")} — draw them in platform-base/bina-ui/bina-icons.js, then theme-token-lint.py --fix`);
const css = fs.readFileSync(path.join(REPO, "platform-base/bina-ui/theme-tokens.css"), "utf8");
const noHue = hues.filter((h) => !css.includes(`[data-office-hue="${h}"]`));
check(`all ${hues.length} office colours have a palette rule`, !noHue.length,
  `${noHue.join(", ")} — add the rule to platform-base/bina-ui/theme-tokens.css`);

console.log(bad ? `\n${bad} failing` : "\n0 failing");
process.exit(bad ? 1 : 0);
