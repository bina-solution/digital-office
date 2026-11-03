#!/usr/bin/env node
/**
 * locale-default.test.mjs — the office's language is RECORDED once, an explicit choice is never
 * overwritten, and nothing about it can take the language pack down.
 *
 *     node apps/bina-ds/plugins/locale-he/test/locale-default.test.mjs
 *
 * The defect this pins (DGO-550, measured 2026-10-13): the pack ships every Hebrew dictionary and the
 * interface still opened in English, because nothing ever selected a language — the active one was
 * whatever the browser asked for, with the vendor's `en` as the fallback. The image now carries the
 * office's language as the locale namespace's composition default (`base`, harness/customize.sh), and
 * this node half turns it into a preference the office holds. What matters is that every other case is
 * a refusal or a no-op:
 *
 *   1. no preference at all             → `he` becomes the workspace preference, once;
 *   2. a preference already there       → nothing is written (the owner chose; the office does not argue);
 *   3. no settings service              → the pack still applies (dictionaries are not conditional);
 *   4. the namespace not registered yet → logged, never thrown (the composition default already answers);
 *   5. a refused write                  → logged, never thrown.
 *
 * Runs without the harness: `ctx` is the two methods the plugin actually uses, and `settings` is the
 * provider API it calls by name (`get(ns)` / `update(ns, patch)`). Exits non-zero on any failed case,
 * so a gate suite may call it anywhere.
 */
import { apply, LOCALE_NAMESPACE, OFFICE_LOCALE, recordOfficeLocale } from "../lib/index.js";

const results = [];
function check(name, ok, detail = "") {
	results.push({ name, ok, detail });
	console.log(`${ok ? "ok  " : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

/** A host context with just enough cordis: `inject(deps, cb)` runs `cb` once the deps exist. */
function fakeContext({ settings } = {}) {
	const injects = [];
	return {
		injects,
		inject(deps, cb) {
			injects.push(deps);
			if (deps.includes("settings") && settings !== undefined) cb({ settings });
		},
	};
}

/** A settings provider holding one namespace's resolved value. */
function fakeSettings(value) {
	const calls = [];
	return {
		calls,
		provider: {
			get: (ns) => (ns === LOCALE_NAMESPACE ? value : undefined),
			update: async (ns, patch) => {
				calls.push({ ns, patch });
				value = { ...value, ...patch };
			},
		},
	};
}

/** One tick is enough for the `.then(...)` in the plugin to settle. */
const flush = () => new Promise((resolve) => setImmediate(resolve));

// 0 ── `apply` is what the loader calls; it must reach the recording.
{
	const s = fakeSettings({});
	const ctx = fakeContext({ settings: s.provider });
	apply(ctx);
	await flush();
	check("apply() records the office's language", s.calls.length === 1 && s.calls[0].patch.preference === OFFICE_LOCALE, JSON.stringify(s.calls));
}

// 1 ── nothing declared: the office's language becomes the preference.
{
	const s = fakeSettings({});
	const ctx = fakeContext({ settings: s.provider });
	recordOfficeLocale(ctx);
	await flush();
	check(
		"an empty settings document gets the office's language",
		s.calls.length === 1 && s.calls[0].ns === LOCALE_NAMESPACE && s.calls[0].patch.preference === OFFICE_LOCALE,
		JSON.stringify(s.calls),
	);
}

// 2 ── the owner already chose: nothing is written, in either direction.
for (const chosen of ["en", "he"]) {
	const s = fakeSettings({ preference: chosen });
	const ctx = fakeContext({ settings: s.provider });
	recordOfficeLocale(ctx);
	await flush();
	check(`an existing preference ("${chosen}") is left exactly as it is`, s.calls.length === 0, JSON.stringify(s.calls));
}

// 3 ── a composition without a settings service still gets the language and the dictionaries.
{
	const ctx = fakeContext({});
	let threw = null;
	try {
		recordOfficeLocale(ctx);
	} catch (error) {
		threw = error;
	}
	check("no settings service is not a failure", threw === null && ctx.injects[0].includes("settings"), String(threw));
}

// 4 ── the namespace is registered by ANOTHER plugin; the composition default is what answers the
// interface meantime, so this row logs and never throws.
{
	const errors = [];
	const realWarn = console.warn;
	console.warn = (...args) => errors.push(args.join(" "));
	const ctx = fakeContext({
		settings: {
			get: () => undefined,
			update: () => {
				throw new Error(`settings namespace "${LOCALE_NAMESPACE}" is not registered`);
			},
		},
	});
	let threw = null;
	try {
		recordOfficeLocale(ctx);
		await flush();
	} catch (error) {
		threw = error;
	} finally {
		console.warn = realWarn;
	}
	check(
		"an unregistered namespace is logged, not thrown",
		threw === null && errors.some((line) => line.includes("could not record")),
		errors.join(" | "),
	);
}

// 5 ── the failure path is contained: a write that rejects must not throw out of the plugin.
{
	const errors = [];
	const realWarn = console.warn;
	console.warn = (...args) => errors.push(args.join(" "));
	const ctx = fakeContext({
		settings: { get: () => ({}), update: () => Promise.reject(new Error("read-only")) },
	});
	let threw = null;
	try {
		recordOfficeLocale(ctx);
		await flush();
	} catch (error) {
		threw = error;
	} finally {
		console.warn = realWarn;
	}
	check(
		"a refused write is logged, not thrown",
		threw === null && errors.some((line) => line.includes("could not record")),
		errors.join(" | "),
	);
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length === 0 ? 0 : 1);
