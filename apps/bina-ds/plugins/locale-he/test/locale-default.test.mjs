#!/usr/bin/env node
/**
 * locale-default.test.mjs — the interface opens in the office's language, whatever the browser asks for.
 *
 *     node apps/bina-ds/plugins/locale-he/test/locale-default.test.mjs
 *
 * The defect this pins (DGO-550, measured 2026-10-13): the pack ships every Hebrew dictionary and the
 * interface still opened in English, because nothing ever selected a language — the active one was
 * whatever the browser asked for, with the vendor's `en` as the fallback.
 *
 * Since DeepSeek Harness 0.2.x (EXU-64) the active language is the `locale` row's own config, so the
 * office DECLARES it in the profile instead of writing it at run time. This test reads that declaration:
 *
 *   1. the profile has a `locale` row whose config says `preference: he` (the office's language);
 *   2. it is a plain row patch (no `disabled`, no other keys), so a choice in Settings → שפה still wins;
 *   3. the pack's node half writes nothing at run time (its apply is empty) — the declaration is the
 *      only place the language is said.
 *
 * Exits non-zero on any failed case, so a gate suite may call it anywhere. (Under 0.1.6 this file
 * pinned the run-time write and its refusals; that write no longer exists.)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { apply, LOCALE_ROW, OFFICE_LOCALE } from "../lib/index.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const patchFile = path.resolve(here, "../../../harness/profile/cordis.patch.yml");
const results = [];
function check(name, ok, detail = "") {
	results.push(ok);
	console.log(`${ok ? "ok  " : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

// The patch is YAML with `!!js` tags; the one row this test needs is plain, so it is read as text:
// the `- id: locale` row and the indented lines under it, up to the next top-level item.
const text = fs.readFileSync(patchFile, "utf8");
const lines = text.split("\n");
const at = lines.findIndex((l) => l.trim() === `- id: ${LOCALE_ROW}` && l.startsWith("- "));
const row = [];
for (let i = at + 1; at >= 0 && i < lines.length && (lines[i].startsWith(" ") || lines[i].trim() === ""); i++) {
	if (lines[i].trim() && !lines[i].trim().startsWith("#")) row.push(lines[i].trim());
}

check("1. the profile declares the locale row", at >= 0, path.relative(process.cwd(), patchFile));
check(`1. its config says preference: ${OFFICE_LOCALE}`, row.includes("config:") && row.includes(`preference: ${OFFICE_LOCALE}`), row.join(" | "));
check("2. a plain config patch (nothing else on the row)", row.length === 2, `${row.length} line(s)`);
let wrote = false;
const ctx = new Proxy({}, { get() { wrote = true; return () => {}; } });
apply(ctx);
check("3. the node half touches nothing at run time", wrote === false);

const failed = results.filter((r) => !r).length;
console.log(failed ? `${failed} failed` : `all ${results.length} passed`);
process.exit(failed ? 1 : 0);
