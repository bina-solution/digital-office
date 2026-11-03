window.__ModuleLoader__.load({
	id: "@bina/dsh-client-office-links",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

		// ── a link to the office opens where the person already is ──────────────────────────────
		// The harness renders every markdown link to `http(s)` with `target="_blank"` (measured in
		// dsh-web-frontend's renderer, 2026-10-08). For a source on the web that is right. For the
		// other half of what the office agent posts — a console deep link to a work item, an app, a
		// screen — it is wrong, and the owner said so twice: «it opens a new window although I asked
		// that by default it opens in the same browser window I am already in».
		//
		// So: a click on a link to THIS office is turned into a navigation of the current tab, and
		// every other link is left exactly as the harness drew it. The office is named by the page's
		// OWN suffix — `bina.localhost` → `localhost`, `bina.hacohen.…` → `hacohen.…` — so any
		// sibling host of the office counts (console, plane, drive…) and nothing else does. A page
		// reached by a bare name or an address from inside the office network (the container, an IP)
		// has no suffix to compare, and there the `*.localhost` family is the office.
		const HERE = String(location.hostname || "").toLowerCase();
		const SUFFIX = /\.[a-z0-9-]/i.test(HERE) ? HERE.replace(/^[^.]+\./, "") : "";

		function isOfficeHost(host) {
			if (SUFFIX && (host === SUFFIX || host.endsWith("." + SUFFIX))) return true;
			return /(^|\.)localhost$/.test(host);
		}

		function onClick(ev) {
			// A new tab is what the person ASKED for when they hold a modifier, and a link a handler
			// already acted on is not ours to take.
			if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
			const a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
			if (!a) return;
			let url;
			try {
				url = new URL(a.href, location.href);
			} catch (e) {
				return;
			}
			if (url.protocol !== "http:" && url.protocol !== "https:") return;
			// SAME ORIGIN IS NOT AUTOMATICALLY THE HARNESS'S ROUTING. A link to the console the person
			// is ALREADY in — which is the usual shape, because the office agent writes links to its
			// own office: `https://console.<office>/#/m/project-pln/…` — has this page's origin, and
			// the line that skipped it sent exactly those links to the harness's `target="_blank"`,
			// i.e. a NEW TAB for a link to the office in front of them (measured 2026-10-13 in the
			// console tile: `#/m/machine` opened `about:blank` + a tab, the desktop never moved).
			// What is the harness's own is its OWN paths (below its mount): a console route on the
			// console's root is the desktop's, whoever wrote it.
			const consoleRoute = /^#\/m\//.test(url.hash || "");
			// …AND A LINK TO THIS PAGE'S OWN CONSOLE IS THE OFFICE WHATEVER ITS HOST IS CALLED. The
			// hostname rules below are for links to OTHER hosts; the console this page is embedded in
			// may be reached by a name with no suffix at all (`console:8000` inside the office
			// network — the plugin's own rule says a bare name or an address has no suffix to compare,
			// and then only `*.localhost` counts). A route of that console is the desktop's.
			const ownConsole = url.origin === location.origin && consoleRoute && !/^\/a\//.test(url.pathname);
			if (url.origin === location.origin && !ownConsole) return;
			if (!ownConsole && !isOfficeHost(url.hostname.toLowerCase())) return;
			ev.preventDefault();
			// …AND THE EVENT STOPS HERE. `preventDefault` alone is not enough: the harness draws a
			// markdown link with a handler of its own, and a tab still opened INTERMITTENTLY while the
			// desktop also moved (measured 2026-10-13 after the swap: `popups: ['about:blank',
			// 'http://console:8000/#/m/machine']` on a run whose verdict read as a pass, because the
			// probe was counting popups for the whole session — and the owner's requirement is exactly
			// "no new tab"). This listener is on `window` in the CAPTURE phase, so stopping propagation
			// here means nothing later — the renderer's own handler included — ever sees the click.
			if (ev.stopPropagation) ev.stopPropagation();
			// …and THE TOP WINDOW IS THE TAB. This page is normally a window inside the office
			// desktop, so assigning here moved the FRAME and the desktop stayed where it was: the
			// owner's «הכל באותו דסקטופ כשרק הקישור משתנה» did not happen (measured 2026-10-09,
			// DGO-511). The desktop is the top window, and a link to the office moves it exactly as
			// if the address had been pasted there. `href` (not `assign`) because the top may be
			// another origin — setting it is allowed there, calling methods on it is not.
			const win = (window.top && window.top !== window) ? window.top : window;
			win.location.href = officeTarget(url);
		}

		// WHICH OFFICE A LINK MEANS. The link was written by the office that OWNS the work item, so
		// it carries that office's console address — and the person reading it is in ANOTHER office,
		// whose edge may even be on another port (hp-laptop serves :80, the MacBook :8080). A console
		// link means the console the reader is ALREADY LOOKING AT: the office in front of them is the
		// one they are in, and only its route should change.
		//
		// A frame learns its embedder's origin two ways and both are used: `location.ancestorOrigins`
		// (Chromium's own, unaffected by any referrer policy) and `document.referrer`, which is
		// trimmed to the origin when the embedder is another origin — the only part this needs.
		function consoleOrigin() {
			try {
				const a = location.ancestorOrigins;
				if (a && a.length) return String(a[a.length - 1] || "");
			} catch (e) { /* an engine without it falls through to the referrer */ }
			try {
				return document.referrer ? new URL(document.referrer).origin : "";
			} catch (e) {
				return "";
			}
		}

		function officeTarget(url) {
			const here = consoleOrigin();
			if (!here || !isOfficeHost(new URL(here).hostname.toLowerCase())) return url.href;
			if (!/^#\/m\//.test(url.hash || "")) return url.href;   // not a console route: as written
			return here + "/" + url.hash;
		}

		function apply(ctx) {
			if (typeof document === "undefined") return;
			// ON WINDOW, in the capture phase: a click has to be claimed BEFORE any other handler on
			// the page claims it. Measured 2026-10-09 (DGO-511): a document-level listener that ran
			// first called preventDefault, this one then read the event as already handled
			// (`ev.defaultPrevented`) and returned — the link went nowhere and the plugin looked
			// broken while its logic was fine. Window capture is strictly ahead of document capture.
			ctx.effect(
				() => {
					window.addEventListener("click", onClick, true);
					return () => window.removeEventListener("click", onClick, true);
				},
				"office-links: a link to the office stays in this tab",
			);
		}

		exports.apply = apply;
		exports.inject = [];
		return module.exports;
	},
});
